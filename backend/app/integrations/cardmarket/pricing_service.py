from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging

from app.models import Card, CardPrint

from .offers_parser import CardmarketOffersParseResult, CardmarketOffersParser
from .page_fetcher import CardmarketFetchedPage, CardmarketPageFetcher
from .product_resolver import CardmarketProductResolver, get_cardmarket_product_resolver
from .summary_parser import CardmarketSummary, CardmarketSummaryParser
from .types import CardmarketPrintContext, CardmarketResolvedProduct
from .url_builder import CARDMARKET_MATCH_AMBIGUOUS, CARDMARKET_MATCH_FAILED, CARDMARKET_MATCH_SET_NAME


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CardmarketPricingResult:
    market_price: float | None
    currency: str
    source_url: str | None
    product_url: str | None
    price_trend: float | None
    avg_1d: float | None
    avg_7d: float | None
    avg_30d: float | None
    market_price_median_top5: float | None
    offers_considered_count: int
    filters_used: dict[str, int | str]
    fetched_at: datetime
    top5_offer_prices: list[float] = field(default_factory=list)
    parse_status: str = "parsed"
    match_quality: str = CARDMARKET_MATCH_FAILED
    note: str | None = None
    resolved_product: CardmarketResolvedProduct | None = None


class CardmarketPricingService:
    def __init__(self) -> None:
        self.resolver: CardmarketProductResolver = get_cardmarket_product_resolver()
        self.fetcher = CardmarketPageFetcher()
        self.summary_parser = CardmarketSummaryParser()
        self.offers_parser = CardmarketOffersParser()

    def _language_filter(self, language: str | None) -> int:
        normalized = (language or "").strip().lower()
        if normalized.startswith("en"):
            return 1
        if normalized.startswith("de"):
            return 3
        raise ValueError(f"Cardmarket language filter not supported for '{language}'.")

    def _condition_filter(self, condition: str | None) -> int:
        mapping = {
            "mint": 1,
            "near_mint": 2,
            "excellent": 3,
            "good": 4,
            "played": 5,
            "poor": 5,
        }
        return mapping.get((condition or "").strip().lower(), 2)

    def _build_context(self, card: Card, card_print: CardPrint, cardmarket_reference: str | None = None) -> CardmarketPrintContext:
        variant_count = 2 if card_print.cardmarket_variant_name else 1
        if not card_print.cardmarket_product_url and card_print.cardmarket_match_quality in {
            CARDMARKET_MATCH_SET_NAME,
            CARDMARKET_MATCH_AMBIGUOUS,
            CARDMARKET_MATCH_FAILED,
        }:
            variant_count = 4
        return CardmarketPrintContext(
            product_name=card_print.cardmarket_product_name or card.name,
            set_name=card_print.cardmarket_set_name or card_print.set_name,
            set_code=card_print.set_code,
            rarity=card_print.cardmarket_expected_rarity or card_print.rarity,
            card_number=card_print.card_number,
            language=card_print.cardmarket_expected_language or card_print.language,
            variant_count=variant_count,
            variant_name=card_print.cardmarket_variant_name,
            existing_product_url=cardmarket_reference or card_print.cardmarket_product_url,
            existing_set_slug=card_print.cardmarket_set_slug,
            existing_product_slug=card_print.cardmarket_product_slug,
            set_slug_hints=[card_print.cardmarket_set_slug] if card_print.cardmarket_set_slug else [],
            set_aliases=[value for value in [card_print.set_name, card_print.cardmarket_set_name] if value],
        )

    def _note(self, *, offers: CardmarketOffersParseResult, summary: CardmarketSummary) -> str:
        return (
            f"Median aus {offers.offers_considered_count} Cardmarket-Angeboten fuer den exakten Print. "
            f"Trend={summary.price_trend if summary.price_trend is not None else 'n/a'}, "
            f"1d={summary.avg_1d if summary.avg_1d is not None else 'n/a'}, "
            f"7d={summary.avg_7d if summary.avg_7d is not None else 'n/a'}, "
            f"30d={summary.avg_30d if summary.avg_30d is not None else 'n/a'}."
        )

    async def fetch_for_print(
        self,
        card: Card,
        card_print: CardPrint,
        condition: str | None,
        *,
        cardmarket_reference: str | None = None,
    ) -> CardmarketPricingResult:
        context = self._build_context(card, card_print, cardmarket_reference=cardmarket_reference)

        resolved_product = await self.resolver.resolve(context)
        if not resolved_product.url or resolved_product.match_quality == CARDMARKET_MATCH_FAILED:
            logger.warning("Failed to resolve Cardmarket product for card_print %s: %s", card_print.id, resolved_product.reason)
            return CardmarketPricingResult(
                market_price=None,
                currency="EUR",
                source_url=None,
                product_url=resolved_product.url,
                price_trend=None,
                avg_1d=None,
                avg_7d=None,
                avg_30d=None,
                market_price_median_top5=None,
                offers_considered_count=0,
                filters_used={},
                fetched_at=datetime.utcnow(),
                parse_status="failed",
                match_quality=resolved_product.match_quality,
                note=f"Cardmarket-Link konnte nicht gebaut werden: {resolved_product.reason}",
                resolved_product=resolved_product,
            )

        language_filter = self._language_filter(card_print.language)
        min_condition = self._condition_filter(condition)
        seller_country = 7

        logger.info(
            "Built Cardmarket URL for card_print %s: %s",
            card_print.id,
            resolved_product.url,
        )
        fetched_page: CardmarketFetchedPage = await self.fetcher.fetch_filtered_product_page(
            resolved_product.url,
            seller_country=seller_country,
            language_filter=language_filter,
            min_condition=min_condition,
        )
        summary = self.summary_parser.parse(fetched_page.html, fetched_page.final_url)
        logger.info(
            "Parsed summary values: trend=%s avg1d=%s avg7d=%s avg30d=%s",
            summary.price_trend,
            summary.avg_1d,
            summary.avg_7d,
            summary.avg_30d,
        )
        offers = self.offers_parser.parse(fetched_page.html)
        logger.info("Parsed first 5 offer prices: %s", offers.top5_offer_prices)

        if offers.market_price_median_top5 is None:
            logger.warning("Failed to parse offer table for card_print %s: no matching offers", card_print.id)
            return CardmarketPricingResult(
                market_price=None,
                currency=summary.currency,
                source_url=fetched_page.final_url,
                product_url=resolved_product.url,
                price_trend=summary.price_trend,
                avg_1d=summary.avg_1d,
                avg_7d=summary.avg_7d,
                avg_30d=summary.avg_30d,
                market_price_median_top5=None,
                offers_considered_count=0,
                filters_used={
                    "sellerCountry": seller_country,
                    "language": language_filter,
                    "minCondition": min_condition,
                },
                fetched_at=fetched_page.fetched_at,
                top5_offer_prices=[],
                parse_status=offers.parse_status,
                match_quality=resolved_product.match_quality,
                note="Keine passenden Cardmarket-Angebote nach Filterung vorhanden.",
                resolved_product=resolved_product,
            )

        logger.info("Computed median market price: %s", offers.market_price_median_top5)
        logger.info("Stored market price for card_print %s", card_print.id)
        return CardmarketPricingResult(
            market_price=offers.market_price_median_top5,
            currency=summary.currency,
            source_url=fetched_page.final_url,
            product_url=resolved_product.url,
            price_trend=summary.price_trend,
            avg_1d=summary.avg_1d,
            avg_7d=summary.avg_7d,
            avg_30d=summary.avg_30d,
            market_price_median_top5=offers.market_price_median_top5,
            offers_considered_count=offers.offers_considered_count,
            filters_used={
                "sellerCountry": seller_country,
                "language": language_filter,
                "minCondition": min_condition,
            },
            fetched_at=fetched_page.fetched_at,
            top5_offer_prices=offers.top5_offer_prices,
            parse_status="parsed",
            match_quality=resolved_product.match_quality,
            note=self._note(offers=offers, summary=summary),
            resolved_product=resolved_product,
        )


_DEFAULT_PRICING_SERVICE = CardmarketPricingService()


def get_cardmarket_pricing_service() -> CardmarketPricingService:
    return _DEFAULT_PRICING_SERVICE
