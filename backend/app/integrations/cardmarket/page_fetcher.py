from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
import logging

import httpx

from app.config import settings

try:  # pragma: no cover - optional in local environments
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    from playwright.async_api import async_playwright
except Exception:  # pragma: no cover - fallback when Playwright is unavailable
    async_playwright = None
    PlaywrightTimeoutError = TimeoutError


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CardmarketFetchedPage:
    requested_url: str
    final_url: str
    html: str
    title_text: str | None
    body_text: str
    fetched_at: datetime
    parse_status: str


def _browser_locale(language_filter: int) -> str:
    if language_filter == 3:
        return "de-DE"
    return "en-US"


def _is_challenge_page(title_text: str | None, body_text: str | None) -> bool:
    haystack = " ".join(filter(None, [title_text, body_text])).lower()
    return "just a moment" in haystack or "enable javascript and cookies to continue" in haystack


def _with_query_params(url: str, params: dict[str, int]) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({key: str(value) for key, value in params.items()})
    return urlunparse(parsed._replace(query=urlencode(query)))


class CardmarketPageFetcher:
    def __init__(self) -> None:
        self.timeout_seconds = settings.request_timeout_seconds
        self.playwright_timeout_seconds = settings.cardmarket_playwright_timeout_seconds
        self._playwright = None
        self._browser = None

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

    async def _fetch_with_httpx(self, url: str, *, language_filter: int) -> CardmarketFetchedPage:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7" if language_filter == 3 else "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            title_text = None
            body_text = response.text
            return CardmarketFetchedPage(
                requested_url=url,
                final_url=str(response.url),
                html=response.text,
                title_text=title_text,
                body_text=body_text,
                fetched_at=datetime.utcnow(),
                parse_status="httpx",
            )

    async def _fetch_with_playwright(self, url: str, *, language_filter: int) -> CardmarketFetchedPage:
        browser = await self._ensure_browser()
        context = await browser.new_context(
            locale=_browser_locale(language_filter),
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
            viewport={"width": 1600, "height": 2200},
        )
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=self.playwright_timeout_seconds * 1000)
            await page.wait_for_timeout(2000)
            html = await page.content()
            title_text = await page.title()
            body_text = await page.text_content("body") or ""
            if _is_challenge_page(title_text, body_text):
                raise RuntimeError("Cardmarket challenge page detected.")
            return CardmarketFetchedPage(
                requested_url=url,
                final_url=page.url,
                html=html,
                title_text=title_text,
                body_text=body_text,
                fetched_at=datetime.utcnow(),
                parse_status="playwright",
            )
        finally:
            await context.close()

    async def fetch_product_page(self, url: str, *, language_filter: int = 1) -> CardmarketFetchedPage:
        logger.info("Fetching Cardmarket product page %s", url)
        try:
            page = await self._fetch_with_playwright(url, language_filter=language_filter)
            logger.debug("Fetched Cardmarket page via Playwright: %s -> %s", url, page.final_url)
            return page
        except Exception as exc:
            logger.warning("Playwright fetch failed for %s: %s. Falling back to httpx.", url, exc)
            return await self._fetch_with_httpx(url, language_filter=language_filter)

    async def fetch_filtered_product_page(
        self,
        url: str,
        *,
        seller_country: int,
        language_filter: int,
        min_condition: int,
    ) -> CardmarketFetchedPage:
        filtered_url = _with_query_params(
            url,
            {
                "sellerCountry": seller_country,
                "language": language_filter,
                "minCondition": min_condition,
            },
        )
        logger.info(
            "Fetching Cardmarket product page with sellerCountry=%s language=%s minCondition=%s: %s",
            seller_country,
            language_filter,
            min_condition,
            filtered_url,
        )
        return await self.fetch_product_page(filtered_url, language_filter=language_filter)
