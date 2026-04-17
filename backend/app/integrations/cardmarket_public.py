from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Any

from .cardmarket.offers_parser import CardmarketOffersParser
from .cardmarket.page_fetcher import CardmarketPageFetcher
from .cardmarket.summary_parser import CardmarketSummaryParser
from .cardmarket.url_builder import CARDMARKET_CATEGORY


@dataclass(slots=True)
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
        self.fetcher = CardmarketPageFetcher()
        self.summary_parser = CardmarketSummaryParser()
        self.offers_parser = CardmarketOffersParser()

    async def fetch_product(self, url: str) -> CardmarketPublicProduct:
        fetched = await self.fetcher.fetch_product_page(url, language_filter=1)
        summary = self.summary_parser.parse(fetched.html, fetched.final_url)
        candidates = [value for value in [summary.product_name, summary.title_text, summary.heading_text] if value]
        return CardmarketPublicProduct(
            url=summary.url,
            title_text=summary.title_text,
            heading_text=summary.heading_text,
            card_name_candidates=list(dict.fromkeys(candidates)),
            product_name=summary.product_name,
            variant_name=summary.variant_name,
            set_name=summary.set_name,
            set_slug=summary.set_slug,
            product_slug=summary.product_slug,
            rarity=summary.rarity,
            card_number=summary.card_number,
            price_trend=summary.price_trend,
            currency=summary.currency,
            avg_1d=summary.avg_1d,
            avg_7d=summary.avg_7d,
            avg_30d=summary.avg_30d,
            parse_mode=fetched.parse_status,
        )

    async def fetch_offer_product(
        self,
        url: str,
        *,
        language_filter: int,
        min_condition: int,
        seller_country: int = 7,
        locale: str | None = None,
    ) -> CardmarketPublicProduct:
        del locale
        fetched = await self.fetcher.fetch_filtered_product_page(
            url,
            seller_country=seller_country,
            language_filter=language_filter,
            min_condition=min_condition,
        )
        summary = self.summary_parser.parse(fetched.html, fetched.final_url)
        offers = self.offers_parser.parse(fetched.html)
        candidates = [value for value in [summary.product_name, summary.title_text, summary.heading_text] if value]
        return CardmarketPublicProduct(
            url=summary.url,
            title_text=summary.title_text,
            heading_text=summary.heading_text,
            card_name_candidates=list(dict.fromkeys(candidates)),
            product_name=summary.product_name,
            variant_name=summary.variant_name,
            set_name=summary.set_name,
            set_slug=summary.set_slug,
            product_slug=summary.product_slug,
            rarity=summary.rarity,
            card_number=summary.card_number,
            price_trend=summary.price_trend,
            currency=summary.currency,
            lowest_offer_price=offers.top5_offer_prices[0] if offers.top5_offer_prices else None,
            avg_1d=summary.avg_1d,
            avg_7d=summary.avg_7d,
            avg_30d=summary.avg_30d,
            offer_prices_sample=offers.offer_prices,
            filters_used={
                "sellerCountry": seller_country,
                "language": language_filter,
                "minCondition": min_condition,
            },
            parse_mode=fetched.parse_status,
        )


_CARDMARKET_PUBLIC_CLIENT = CardmarketPublicProductPageClient()


def get_cardmarket_public_client() -> CardmarketPublicProductPageClient:
    return _CARDMARKET_PUBLIC_CLIENT
