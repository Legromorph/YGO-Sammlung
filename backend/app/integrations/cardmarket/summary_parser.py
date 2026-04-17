from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from urllib.parse import unquote
import re

from bs4 import BeautifulSoup

from .url_builder import split_cardmarket_product_url


@dataclass(slots=True)
class CardmarketSummary:
    url: str
    title_text: str | None
    heading_text: str | None
    product_name: str | None
    variant_name: str | None
    set_name: str | None
    set_slug: str | None
    product_slug: str | None
    rarity: str | None
    card_number: str | None
    price_trend: float | None
    avg_1d: float | None
    avg_7d: float | None
    avg_30d: float | None
    currency: str
    parse_status: str


def _clean_whitespace(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = " ".join(unescape(value).split())
    return cleaned or None


def _extract_between(text: str, start_labels: tuple[str, ...], end_labels: tuple[str, ...]) -> str | None:
    start_pattern = "(?:" + "|".join(re.escape(label) for label in start_labels) + ")"
    end_pattern = "(?:" + "|".join(re.escape(label) for label in end_labels) + ")"
    match = re.search(rf"{start_pattern}\s+(.*?)\s+{end_pattern}", text, flags=re.IGNORECASE | re.DOTALL)
    return _clean_whitespace(match.group(1)) if match else None


def _parse_price(value: str | None) -> float | None:
    if not value:
        return None
    normalized = re.sub(r"[^0-9,.\-]", "", value)
    if not normalized:
        return None
    if normalized.count(",") == 1 and normalized.count(".") == 0:
        normalized = normalized.replace(",", ".")
    elif normalized.count(",") >= 1 and normalized.count(".") >= 1:
        normalized = normalized.replace(".", "").replace(",", ".")
    try:
        return float(normalized)
    except ValueError:
        return None


def _metric_from_text(text: str, labels: tuple[str, ...]) -> float | None:
    for label in labels:
        match = re.search(rf"{re.escape(label)}\s*([0-9][0-9.,]*)\s*€", text, flags=re.IGNORECASE)
        if match:
            value = _parse_price(match.group(1))
            if value is not None:
                return value
    return None


def _strip_variant_suffix(value: str | None) -> str | None:
    if not value:
        return None
    stripped = re.sub(r"\s*\([^)]*\)\s*$", "", value).strip(" -")
    return _clean_whitespace(stripped)


def _slug_to_name_candidate(product_slug: str | None) -> str | None:
    tokens = [token for token in unquote(product_slug or "").split("-") if token]
    if not tokens:
        return None

    cut_index = len(tokens)
    for index, token in enumerate(tokens):
        lowered = token.lower()
        if lowered == "v" and index + 1 < len(tokens) and tokens[index + 1].isdigit():
            cut_index = index
            break
        if re.fullmatch(r"v\d+", lowered):
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
    if not match:
        return None
    return f"V{match.group(1)}"


def _product_name_from_heading(heading_text: str | None, set_name: str | None) -> str | None:
    if not heading_text:
        return None
    candidate = heading_text
    if set_name and set_name in candidate:
        candidate = candidate.split(set_name, 1)[0]
    candidate = re.sub(r"\s*-\s*Singles\s*$", "", candidate, flags=re.IGNORECASE)
    return _strip_variant_suffix(candidate)


class CardmarketSummaryParser:
    def parse(self, html: str, final_url: str) -> CardmarketSummary:
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text("\n", strip=True)
        _, set_slug, product_slug = split_cardmarket_product_url(final_url)

        title_text = _clean_whitespace(soup.title.get_text(" ", strip=True) if soup.title else None)
        heading = soup.find("h1")
        heading_text = _clean_whitespace(heading.get_text(" ", strip=True) if heading else None)

        set_name = _extract_between(
            text,
            ("Printed in", "Erschienen in", "Publie dans", "Publicado en", "Pubblicato in"),
            ("Reprints", "Show Versions", "Show Offers", "Preis-Trend", "Price Trend"),
        ) or _clean_whitespace(unquote(set_slug).replace("-", " "))

        rarity = _extract_between(
            text,
            ("Rarity", "Raritaet", "Rarete", "Rareza", "Rarita"),
            ("Number", "Nummer", "Numero"),
        )
        card_number = _extract_between(
            text,
            ("Number", "Nummer", "Numero"),
            ("Printed in", "Erschienen in", "Publie dans", "Publicado en", "Pubblicato in"),
        )

        price_trend = _metric_from_text(text, ("Price Trend", "Preis-Trend", "Trend de prix", "Trend prezzo", "Tendencia de precio"))
        avg_30d = _metric_from_text(text, ("30-days average price", "30 Day Average", "30-day average price", "30-Tages-Durchschnitt"))
        avg_7d = _metric_from_text(text, ("7-days average price", "7 Day Average", "7-day average price", "7-Tages-Durchschnitt"))
        avg_1d = _metric_from_text(text, ("1-day average price", "1 Day Average", "1-days average price", "1-Tages-Durchschnitt"))

        product_name = _product_name_from_heading(heading_text, set_name) or _slug_to_name_candidate(product_slug) or title_text

        return CardmarketSummary(
            url=final_url,
            title_text=title_text,
            heading_text=heading_text,
            product_name=product_name,
            variant_name=_variant_name_from_slug(product_slug),
            set_name=set_name,
            set_slug=set_slug,
            product_slug=product_slug,
            rarity=rarity,
            card_number=card_number,
            price_trend=price_trend,
            avg_1d=avg_1d,
            avg_7d=avg_7d,
            avg_30d=avg_30d,
            currency="EUR",
            parse_status="parsed",
        )
