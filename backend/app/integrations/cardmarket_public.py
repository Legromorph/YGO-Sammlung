from __future__ import annotations

import asyncio
from dataclasses import dataclass
from dataclasses import field
from html import unescape
import logging
import re
from urllib.parse import unquote, urlparse
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.integrations.cardmarket_links import CARDMARKET_CATEGORY, split_cardmarket_product_url, slugify_cardmarket_segment

try:  # pragma: no cover - optional in non-Docker/local setups
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    from playwright.async_api import async_playwright
except Exception:  # pragma: no cover - fallback when Playwright is unavailable
    async_playwright = None
    PlaywrightTimeoutError = TimeoutError


logger = logging.getLogger(__name__)


def _clean_whitespace(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = " ".join(unescape(value).split())
    return cleaned or None


def _normalize_label_pattern(*labels: str) -> str:
    return "(?:" + "|".join(re.escape(label) for label in labels) + ")"


def _extract_between(text: str, start_labels: tuple[str, ...], end_labels: tuple[str, ...]) -> str | None:
    start_pattern = _normalize_label_pattern(*start_labels)
    end_pattern = _normalize_label_pattern(*end_labels)
    match = re.search(rf"{start_pattern}\s+(.*?)\s+{end_pattern}", text, flags=re.IGNORECASE | re.DOTALL)
    return _clean_whitespace(match.group(1)) if match else None


def _parse_price(value: str | None) -> float | None:
    if not value:
        return None
    normalized = re.sub(r"[^0-9,.\-]", "", value)
    if not normalized:
        return None
    if normalized.count(",") == 1 and normalized.count(".") > 1:
        normalized = normalized.replace(".", "").replace(",", ".")
    elif normalized.count(",") == 1 and normalized.count(".") == 0:
        normalized = normalized.replace(",", ".")
    elif normalized.count(",") > 1 and normalized.count(".") == 0:
        normalized = normalized.replace(".", "").replace(",", ".")
    else:
        normalized = normalized.replace(",", "")
    try:
        return float(normalized)
    except ValueError:
        return None


def _parse_int(value: str | None) -> int | None:
    if not value:
        return None
    normalized = re.sub(r"[^0-9\-]", "", value)
    if not normalized:
        return None
    try:
        return int(normalized)
    except ValueError:
        return None


def _strip_variant_suffix(value: str | None) -> str | None:
    if not value:
        return None
    stripped = re.sub(r"\s*\([^)]*\)\s*$", "", value).strip(" -")
    return _clean_whitespace(stripped)


def _slug_to_name_candidate(product_slug: str) -> str | None:
    tokens = [token for token in unquote(product_slug).split("-") if token]
    if not tokens:
        return None

    cut_index = len(tokens)
    for index, token in enumerate(tokens):
        if token.lower() == "v" and index + 1 < len(tokens) and tokens[index + 1].isdigit():
            cut_index = index
            break

    if cut_index == len(tokens):
        rarity_tokens = {
            "common",
            "rare",
            "super",
            "secret",
            "ultra",
            "ultimate",
            "ghost",
            "gold",
            "collector",
            "collectors",
            "starlight",
            "quarter",
            "century",
            "prismatic",
            "parallel",
        }
        while cut_index > 0 and tokens[cut_index - 1].lower() in rarity_tokens:
            cut_index -= 1

    return _clean_whitespace(" ".join(tokens[:cut_index]))


def _variant_name_from_slug(product_slug: str | None) -> str | None:
    if not product_slug:
        return None
    match = re.search(r"(?:^|-)V-?(\d+)(?:-|$)", product_slug, flags=re.IGNORECASE)
    if match:
        return f"V{match.group(1)}"
    return None


def _text_candidates(title_text: str | None, heading_text: str | None, set_name: str | None, product_slug: str) -> list[str]:
    candidates: list[str] = []

    def add_candidate(value: str | None) -> None:
        cleaned = _strip_variant_suffix(value)
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)

    add_candidate(_slug_to_name_candidate(product_slug))
    add_candidate(title_text.split("|", 1)[0] if title_text else None)

    if heading_text:
        for part in re.split(r"\s+-\s+", heading_text):
            if set_name and set_name in part:
                add_candidate(part.split(set_name, 1)[0])
            add_candidate(part)

        if set_name and set_name in heading_text:
            add_candidate(heading_text.split(set_name, 1)[0])

    return candidates


def _metric_from_text(text: str, labels: tuple[str, ...]) -> float | None:
    euro = re.escape(chr(8364))
    for label in labels:
        match = re.search(rf"{re.escape(label)}\s*([0-9][0-9.,]*)\s*{euro}", text, flags=re.IGNORECASE)
        if match:
            value = _parse_price(match.group(1))
            if value is not None:
                return value
    return None

def _integer_metric_from_text(text: str, labels: tuple[str, ...]) -> int | None:
    for label in labels:
        match = re.search(rf"{re.escape(label)}\s*([0-9][0-9.,]*)", text, flags=re.IGNORECASE)
        if match:
            value = _parse_int(match.group(1))
            if value is not None:
                return value
    return None


def _is_challenge_text(body_text: str | None, title_text: str | None) -> bool:
    haystack = " ".join(filter(None, [body_text, title_text])).lower()
    return "just a moment" in haystack or "enable javascript and cookies to continue" in haystack


def _browser_locale_from_url(url: str) -> str:
    path_segments = [segment for segment in urlparse(url).path.split("/") if segment]
    if path_segments and path_segments[0].lower() == "de":
        return "de-DE"
    return "en-US"


def _is_supported_cardmarket_path(path: str) -> bool:
    lowered = path.lower()
    return "/yugioh/products/singles/" in lowered or "/yugioh/cards/" in lowered


@dataclass
class CardmarketPublicProduct:
    url: str
    title_text: str | None
    heading_text: str | None
    card_name_candidates: list[str]
    product_name: str | None
    variant_name: str | None
    set_name: str | None
    set_slug: str | None
    product_slug: str | None
    rarity: str | None
    card_number: str | None
    price_trend: float | None
    currency: str
    lowest_offer_price: float | None = None
    available_items: int | None = None
    avg_1d: float | None = None
    avg_7d: float | None = None
    avg_30d: float | None = None
    offer_prices_sample: list[float] = field(default_factory=list)
    filters_used: dict[str, Any] = field(default_factory=dict)
    category: str = CARDMARKET_CATEGORY
    parse_mode: str = "page"


class CardmarketPublicProductPageClient:
    def __init__(self) -> None:
        self.timeout = settings.request_timeout_seconds
        self.playwright_timeout_seconds = settings.cardmarket_playwright_timeout_seconds
        self._browser = None
        self._playwright = None

    async def _ensure_browser(self):
        if self._browser is not None:
            return self._browser
        if async_playwright is None:
            raise RuntimeError("Playwright ist nicht verfuegbar.")
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        return self._browser

    async def _render_page(self, url: str, *, locale: str, open_offers: bool = False) -> tuple[str, str, str]:
        browser = await self._ensure_browser()
        last_error: Exception | None = None
        max_attempts = 1 if open_offers else 3
        navigation_timeout_seconds = min(self.playwright_timeout_seconds, 25 if open_offers else self.playwright_timeout_seconds)

        for attempt in range(max_attempts):
            context = await browser.new_context(
                locale=locale,
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
                viewport={"width": 1600, "height": 2200},
            )
            page = await context.new_page()
            try:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=navigation_timeout_seconds * 1000)
                except PlaywrightTimeoutError as exc:
                    last_error = exc

                await page.wait_for_timeout(900 if open_offers else 1500)
                title_text = await page.title()
                body_text = await page.text_content("body") or ""
                if _is_challenge_text(body_text, title_text):
                    raise RuntimeError("Cardmarket challenge page")

                if open_offers:
                    offer_labels = [
                        "Show Offers",
                        "Angebote anzeigen",
                        "Angebote",
                        "Afficher les offres",
                        "Mostra offerte",
                        "Mostrar ofertas",
                    ]
                    clicked = False
                    for label in offer_labels:
                        try:
                            await page.get_by_text(label, exact=False).first.click(timeout=5000)
                            clicked = True
                            break
                        except Exception:
                            try:
                                await page.locator(f'a:has-text("{label}"), button:has-text("{label}")').first.click(timeout=5000)
                                clicked = True
                                break
                            except Exception:
                                continue
                    if not clicked:
                        raise RuntimeError("Cardmarket offers button not found")
                    await page.wait_for_selector(".article-row", timeout=9000)

                html = await page.content()
                final_url = page.url
                body_text = await page.text_content("body") or ""
                return html, final_url, body_text
            except Exception as exc:
                last_error = exc
                if attempt < max_attempts - 1:
                    await asyncio.sleep(2 + attempt * 2)
                    continue
                raise
            finally:
                await context.close()

        if last_error:
            raise last_error
        raise RuntimeError("Cardmarket page could not be rendered.")

    def _parse_product_html(
        self,
        html: str,
        final_url: str,
        *,
        parse_mode: str,
        offer_mode: bool = False,
        filters_used: dict[str, Any] | None = None,
    ) -> CardmarketPublicProduct:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n", strip=True)
        _, set_slug, product_slug = split_cardmarket_product_url(final_url)
        if not product_slug:
            raise ValueError("Cardmarket product slug not found in rendered page.")

        title_text = _clean_whitespace(soup.title.get_text(" ", strip=True) if soup.title else None)
        heading_text = _clean_whitespace(soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else None)

        set_name = _extract_between(
            text,
            ("Erschienen in", "Printed in", "Pubblicato in", "Publicado en", "Publie dans"),
            ("Reprints", "Show Reprints", "Mostra ristampe", "Mostrar reimpresiones", "Afficher les reimpressions"),
        ) or _clean_whitespace(unquote(set_slug).replace("-", " "))

        rarity = _extract_between(
            text,
            ("Raritaet", "RaritÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â¤t", "Rarity", "Rarete", "RaretÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©", "Rareza", "Rarita"),
            ("Nummer", "Number", "Numero", "NumÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©ro"),
        )
        card_number = _extract_between(
            text,
            ("Nummer", "Number", "Numero", "NumÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©ro"),
            ("Erschienen in", "Printed in", "Pubblicato in", "Publicado en", "Publie dans"),
        )
        price_trend = _metric_from_text(
            text,
            ("Preis-Trend", "Price Trend", "Trend de prix", "Trend prezzo", "Tendencia de precio"),
        )
        lowest_offer_price = _metric_from_text(text, ("From", "Ab"))
        avg_30d = _metric_from_text(
            text,
            ("30-Tages-Durchschnitt", "30-Day Average", "30 Day Average", "Moyenne sur 30 jours", "Media 30 giorni", "Promedio de 30 dias"),
        )
        avg_7d = _metric_from_text(
            text,
            ("7-Tages-Durchschnitt", "7-Day Average", "7 Day Average", "Moyenne sur 7 jours", "Media 7 giorni", "Promedio de 7 dias"),
        )
        avg_1d = _metric_from_text(
            text,
            ("1-Tages-Durchschnitt", "1-Day Average", "1 Day Average", "Moyenne sur 1 jour", "Media 1 giorno", "Promedio de 1 dia"),
        )
        available_items = _integer_metric_from_text(text, ("Available items", "Verfuegbare Artikel", "VerfÃƒÆ’Ã‚Â¼gbare Artikel"))

        offer_prices_sample: list[float] = []
        if offer_mode:
            for offer_cell in soup.select(".article-row .col-offer"):
                offer_text = offer_cell.get_text(" ", strip=True)
                price = None
                for match in re.findall(r"([0-9]+(?:[.,][0-9]{2})?)", offer_text):
                    price = _parse_price(match)
                    if price is not None:
                        break
                if price is None:
                    continue
                offer_prices_sample.append(price)
                if len(offer_prices_sample) >= settings.cardmarket_offer_sample_size:
                    break
            if offer_prices_sample:
                lowest_offer_price = offer_prices_sample[0]
        return CardmarketPublicProduct(
            url=final_url,
            title_text=title_text,
            heading_text=heading_text,
            card_name_candidates=_text_candidates(title_text, heading_text, set_name, product_slug),
            product_name=_strip_variant_suffix(_slug_to_name_candidate(product_slug)) or heading_text or title_text,
            variant_name=_variant_name_from_slug(product_slug),
            set_name=set_name,
            set_slug=set_slug,
            product_slug=product_slug,
            rarity=rarity,
            card_number=card_number,
            price_trend=price_trend,
            currency="EUR",
            lowest_offer_price=lowest_offer_price,
            available_items=available_items,
            avg_1d=avg_1d,
            avg_7d=avg_7d,
            avg_30d=avg_30d,
            offer_prices_sample=offer_prices_sample,
            filters_used=filters_used or {},
            category=CARDMARKET_CATEGORY,
            parse_mode=parse_mode,
        )

    async def fetch_product(self, url: str) -> CardmarketPublicProduct:
        parsed_url = urlparse(url)
        if parsed_url.scheme not in {"http", "https"} or "cardmarket.com" not in parsed_url.netloc.lower():
            raise ValueError("Nur Cardmarket-Produktlinks werden unterstuetzt.")
        if not _is_supported_cardmarket_path(parsed_url.path):
            raise ValueError("Unterstuetzt werden nur Cardmarket Yu-Gi-Oh!-Einzelkartenlinks.")

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                        "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7",
                        "Cache-Control": "no-cache",
                        "Pragma": "no-cache",
                        "Upgrade-Insecure-Requests": "1",
                    },
                )
                response.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException):
            try:
                html, final_url, _body_text = await self._render_page(url, locale=_browser_locale_from_url(url), open_offers=False)
                return self._parse_product_html(html, final_url, parse_mode="playwright")
            except Exception:
                return self._fallback_from_url(url)

        try:
            soup = BeautifulSoup(response.text, "html.parser")
            text = soup.get_text("\n", strip=True)
            if _is_challenge_text(text, _clean_whitespace(soup.title.get_text(" ", strip=True) if soup.title else None)):
                raise ValueError("Cardmarket challenge response")

            _, set_slug, product_slug = split_cardmarket_product_url(str(response.url))
            if not product_slug:
                return self._fallback_from_url(str(response.url))
            title_text = _clean_whitespace(soup.title.get_text(" ", strip=True) if soup.title else None)
            heading_text = _clean_whitespace(soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else None)

            set_name = _extract_between(
                text,
                ("Erschienen in", "Printed in", "Pubblicato in", "Publicado en", "Publie dans"),
                ("Reprints", "Show Reprints", "Mostra ristampe", "Mostrar reimpresiones", "Afficher les reimpressions"),
            ) or _clean_whitespace(unquote(set_slug).replace("-", " "))

            rarity = _extract_between(
                text,
                ("Raritaet", "RaritÃƒÆ’Ã‚Â¤t", "Rarity", "Rarete", "RaretÃƒÆ’Ã‚Â©", "Rareza", "Rarita"),
                ("Nummer", "Number", "Numero", "NumÃƒÆ’Ã‚Â©ro"),
            )
            card_number = _extract_between(
                text,
                ("Nummer", "Number", "Numero", "NumÃƒÆ’Ã‚Â©ro"),
                ("Erschienen in", "Printed in", "Pubblicato in", "Publicado en", "Publie dans"),
            )
            price_trend = _metric_from_text(
                text,
                ("Preis-Trend", "Price Trend", "Trend de prix", "Trend prezzo", "Tendencia de precio"),
            )

            return CardmarketPublicProduct(
                url=str(response.url),
                title_text=title_text,
                heading_text=heading_text,
                card_name_candidates=_text_candidates(title_text, heading_text, set_name, product_slug),
                product_name=_strip_variant_suffix(_slug_to_name_candidate(product_slug)) or heading_text or title_text,
                variant_name=_variant_name_from_slug(product_slug),
                set_name=set_name,
                set_slug=set_slug,
                product_slug=product_slug,
                rarity=rarity,
                card_number=card_number,
                price_trend=price_trend,
                currency="EUR",
                category=CARDMARKET_CATEGORY,
                parse_mode="page",
            )
        except Exception:
            try:
                html, final_url, _body_text = await self._render_page(url, locale=_browser_locale_from_url(url), open_offers=False)
                return self._parse_product_html(html, final_url, parse_mode="playwright")
            except Exception:
                return self._fallback_from_url(url)

    async def fetch_offer_product(
        self,
        url: str,
        *,
        language_filter: int,
        min_condition: int,
        seller_country: int = 7,
        locale: str | None = None,
    ) -> CardmarketPublicProduct:
        parsed_url = urlparse(url)
        if parsed_url.scheme not in {"http", "https"} or "cardmarket.com" not in parsed_url.netloc.lower():
            raise ValueError("Nur Cardmarket-Produktlinks werden unterstuetzt.")
        if not _is_supported_cardmarket_path(parsed_url.path):
            raise ValueError("Unterstuetzt werden nur Cardmarket Yu-Gi-Oh!-Einzelkartenlinks.")

        filtered_url = parsed_url._replace(
            query=f"sellerCountry={seller_country}&language={language_filter}&minCondition={min_condition}"
        ).geturl()
        browser_locale = locale or _browser_locale_from_url(filtered_url)
        try:
            html, final_url, body_text = await self._render_page(filtered_url, locale=browser_locale, open_offers=True)
            offer_mode = True
            parse_mode = "playwright-offers"
        except Exception as exc:
            logger.warning(
                "Cardmarket offer mode failed for %s (language=%s condition=%s country=%s): %s. Falling back to product page mode.",
                url,
                language_filter,
                min_condition,
                seller_country,
                exc,
            )
            html, final_url, body_text = await self._render_page(filtered_url, locale=browser_locale, open_offers=False)
            offer_mode = False
            parse_mode = "playwright-product-fallback"
        product = self._parse_product_html(
            html,
            final_url,
            parse_mode=parse_mode,
            offer_mode=offer_mode,
            filters_used={
                "seller_country": seller_country,
                "language": language_filter,
                "min_condition": min_condition,
                "locale": browser_locale,
                "source_url": filtered_url,
                "offer_mode": offer_mode,
            },
        )
        logger.info(
            "Fetched Cardmarket offers for %s with language=%s minCondition=%s sellerCountry=%s",
            product.product_name,
            language_filter,
            min_condition,
            seller_country,
        )
        logger.debug("Cardmarket offer page excerpt: %s", body_text[:500])
        return product

    def _fallback_from_url(self, url: str) -> CardmarketPublicProduct:
        parsed_url = urlparse(url)
        path_segments = [segment for segment in parsed_url.path.split("/") if segment]
        set_slug = None
        product_slug = None
        if len(path_segments) >= 6 and path_segments[2:4] == ["Products", "Singles"]:
            set_slug = path_segments[4]
            product_slug = path_segments[5]
        elif len(path_segments) >= 4 and path_segments[2].lower() == "cards":
            product_slug = path_segments[3]
        elif path_segments:
            product_slug = path_segments[-1]

        set_name = _clean_whitespace(unquote(set_slug).replace("-", " ")) if set_slug else None
        slug_candidate = _slug_to_name_candidate(product_slug or "")

        rarity_match = re.search(
            r"(Quarter-Century-Secret-Rare|Prismatic-Secret-Rare|Starlight-Rare|Collectors?-Rare|Ghost-Rare|Ultimate-Rare|Secret-Rare|Ultra-Rare|Super-Rare|Gold-Rare|Rare|Common)$",
            product_slug or "",
            flags=re.IGNORECASE,
        )
        rarity = _clean_whitespace(rarity_match.group(1).replace("-", " ")) if rarity_match else None

        return CardmarketPublicProduct(
            url=url,
            title_text=slug_candidate,
            heading_text=None,
            card_name_candidates=_text_candidates(slug_candidate, None, set_name, product_slug or ""),
            product_name=slug_candidate,
            variant_name=_variant_name_from_slug(product_slug),
            set_name=set_name,
            set_slug=set_slug,
            product_slug=product_slug,
            rarity=rarity,
            card_number=None,
            price_trend=None,
            currency="EUR",
            lowest_offer_price=None,
            category=CARDMARKET_CATEGORY,
            parse_mode="url",
        )
_CARDMARKET_PUBLIC_CLIENT = CardmarketPublicProductPageClient()


def get_cardmarket_public_client() -> CardmarketPublicProductPageClient:
    return _CARDMARKET_PUBLIC_CLIENT
