from __future__ import annotations

from datetime import datetime
import re

from .page_fetcher import CardmarketPageFetcher
from .summary_parser import CardmarketSummary, CardmarketSummaryParser
from .types import CardmarketPrintContext, CardmarketResolvedProduct
from .url_builder import (
    CARDMARKET_MATCH_AMBIGUOUS,
    CARDMARKET_MATCH_EXACT,
    CARDMARKET_MATCH_EXACT_VARIANT,
    CARDMARKET_MATCH_SET_NAME,
    split_cardmarket_product_url,
)


def _normalize_token(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _numbers_match(left: str | None, right: str | None) -> bool:
    normalized_left = _normalize_token(left)
    normalized_right = _normalize_token(right)
    if not normalized_left or not normalized_right:
        return True
    return normalized_left == normalized_right or normalized_left.endswith(normalized_right) or normalized_right.endswith(normalized_left)


def _text_match(left: str | None, right: str | None) -> bool:
    normalized_left = _normalize_token(left)
    normalized_right = _normalize_token(right)
    if not normalized_left or not normalized_right:
        return True
    return normalized_left == normalized_right


class CardmarketProductVerifier:
    def __init__(self) -> None:
        self.fetcher = CardmarketPageFetcher()
        self.summary_parser = CardmarketSummaryParser()

    def _language_filter(self, language: str | None) -> int:
        normalized = (language or "").strip().lower()
        if normalized.startswith("de"):
            return 3
        return 1

    def _match_quality(self, context: CardmarketPrintContext, summary: CardmarketSummary) -> tuple[str, str]:
        if not _text_match(context.set_name, summary.set_name):
            return CARDMARKET_MATCH_AMBIGUOUS, "set name mismatch"
        if not _text_match(context.product_name, summary.product_name):
            return CARDMARKET_MATCH_AMBIGUOUS, "product name mismatch"
        if not _numbers_match(context.card_number, summary.card_number):
            return CARDMARKET_MATCH_AMBIGUOUS, "card number mismatch"
        if not _text_match(context.rarity, summary.rarity):
            return CARDMARKET_MATCH_AMBIGUOUS, "rarity mismatch"

        if context.variant_count <= 1 and not context.variant_name and not summary.variant_name:
            return CARDMARKET_MATCH_EXACT, "single print verified"
        if summary.variant_name or context.variant_name:
            return CARDMARKET_MATCH_EXACT_VARIANT, "variant verified"
        return CARDMARKET_MATCH_SET_NAME, "name-only verified"

    async def verify_url(self, url: str, context: CardmarketPrintContext) -> CardmarketResolvedProduct:
        page = await self.fetcher.fetch_product_page(url, language_filter=self._language_filter(context.language))
        summary = self.summary_parser.parse(page.html, page.final_url)
        match_quality, reason = self._match_quality(context, summary)
        _, set_slug, product_slug = split_cardmarket_product_url(summary.url)
        return CardmarketResolvedProduct(
            url=summary.url,
            set_slug=set_slug,
            product_slug=product_slug,
            product_name=summary.product_name,
            set_name=summary.set_name,
            rarity=summary.rarity,
            card_number=summary.card_number,
            variant_name=summary.variant_name,
            match_quality=match_quality,
            verified_at=datetime.utcnow() if match_quality in {CARDMARKET_MATCH_EXACT, CARDMARKET_MATCH_EXACT_VARIANT, CARDMARKET_MATCH_SET_NAME} else None,
            reason=reason,
            parse_status=page.parse_status,
            diagnostics={
                "requested_url": url,
                "page_fetch": {
                    "requested_url": page.requested_url,
                    "final_url": page.final_url,
                    "fetched_at": page.fetched_at.isoformat(),
                    "parse_status": page.parse_status,
                    "title_text": page.title_text,
                },
                "summary": {
                    "url": summary.url,
                    "title_text": summary.title_text,
                    "heading_text": summary.heading_text,
                    "product_name": summary.product_name,
                    "variant_name": summary.variant_name,
                    "set_name": summary.set_name,
                    "set_slug": summary.set_slug,
                    "product_slug": summary.product_slug,
                    "rarity": summary.rarity,
                    "card_number": summary.card_number,
                    "price_trend": summary.price_trend,
                    "avg_1d": summary.avg_1d,
                    "avg_7d": summary.avg_7d,
                    "avg_30d": summary.avg_30d,
                    "currency": summary.currency,
                    "parse_status": summary.parse_status,
                },
            },
        )
