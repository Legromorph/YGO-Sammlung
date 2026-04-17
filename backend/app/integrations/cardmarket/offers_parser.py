from __future__ import annotations

from dataclasses import dataclass
from statistics import median
import re

from bs4 import BeautifulSoup


@dataclass(slots=True)
class CardmarketOffersParseResult:
    offer_prices: list[float]
    top5_offer_prices: list[float]
    offers_considered_count: int
    market_price_median_top5: float | None
    parse_status: str


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


def _extract_row_prices(row_text: str) -> list[float]:
    prices: list[float] = []
    for match in re.findall(r"([0-9]+(?:[.,][0-9]{2}))\s*€", row_text):
        value = _parse_price(match)
        if value is not None and value > 0:
            prices.append(value)
    return prices


class CardmarketOffersParser:
    def parse(self, html: str) -> CardmarketOffersParseResult:
        soup = BeautifulSoup(html, "html.parser")
        offer_prices: list[float] = []

        row_selectors = [
            ".article-row",
            "table tbody tr",
            "[data-testid='article-row']",
        ]
        row_elements = []
        for selector in row_selectors:
            row_elements = soup.select(selector)
            if row_elements:
                break

        for row in row_elements:
            row_text = row.get_text(" ", strip=True)
            prices = _extract_row_prices(row_text)
            if not prices:
                continue
            offer_prices.append(prices[0])

        if not offer_prices:
            for cell in soup.select(".col-offer, [class*='offer']"):
                prices = _extract_row_prices(cell.get_text(" ", strip=True))
                if not prices:
                    continue
                offer_prices.append(prices[0])

        top5_offer_prices = [price for price in offer_prices[:5] if price > 0]
        if not top5_offer_prices:
            return CardmarketOffersParseResult(
                offer_prices=[],
                top5_offer_prices=[],
                offers_considered_count=0,
                market_price_median_top5=None,
                parse_status="no_matching_offers",
            )

        return CardmarketOffersParseResult(
            offer_prices=offer_prices,
            top5_offer_prices=top5_offer_prices,
            offers_considered_count=len(top5_offer_prices),
            market_price_median_top5=float(median(top5_offer_prices)),
            parse_status="parsed",
        )
