from __future__ import annotations

from dataclasses import replace
import logging

from .product_url_builder import CardmarketProductUrlBuilder
from .product_verifier import CardmarketProductVerifier
from .set_slug_resolver import CardmarketSetSlugResolver, get_cardmarket_set_slug_resolver
from .types import CardmarketPrintContext, CardmarketResolvedProduct
from .url_builder import (
    CARDMARKET_MATCH_AMBIGUOUS,
    CARDMARKET_MATCH_EXACT,
    CARDMARKET_MATCH_EXACT_VARIANT,
    CARDMARKET_MATCH_FAILED,
    CARDMARKET_MATCH_SET_NAME,
    normalize_cardmarket_product_url,
)


logger = logging.getLogger(__name__)


class CardmarketProductResolver:
    def __init__(self) -> None:
        self.set_slug_resolver: CardmarketSetSlugResolver = get_cardmarket_set_slug_resolver()
        self.url_builder = CardmarketProductUrlBuilder()
        self.verifier = CardmarketProductVerifier()

    async def resolve(self, context: CardmarketPrintContext) -> CardmarketResolvedProduct:
        existing_url = normalize_cardmarket_product_url(context.existing_product_url)
        if existing_url:
            logger.info("Verifying stored Cardmarket URL: %s", existing_url)
            verified = await self.verifier.verify_url(existing_url, context)
            if verified.match_quality in {CARDMARKET_MATCH_EXACT, CARDMARKET_MATCH_EXACT_VARIANT, CARDMARKET_MATCH_SET_NAME}:
                return verified

        if context.existing_set_slug and context.existing_product_slug:
            candidate_url = self.url_builder.build_product_url(context.existing_set_slug, context.existing_product_slug)
            logger.info("Verifying stored Cardmarket slug URL: %s", candidate_url)
            verified = await self.verifier.verify_url(candidate_url, context)
            if verified.match_quality in {CARDMARKET_MATCH_EXACT, CARDMARKET_MATCH_EXACT_VARIANT, CARDMARKET_MATCH_SET_NAME}:
                return verified

        set_slug_candidates = self.set_slug_resolver.resolve_candidates(
            set_name=context.set_name,
            set_code=context.set_code,
            existing_set_slug=context.existing_set_slug,
            verified_set_slugs=context.set_slug_hints,
            alias_names=context.set_aliases,
        )
        if set_slug_candidates:
            logger.info(
                "Resolved Cardmarket set slug candidates for set '%s' (%s): %s",
                context.set_name,
                context.set_code,
                ", ".join(f"{candidate.slug} [{candidate.source}]" for candidate in set_slug_candidates),
            )
        candidates = self.url_builder.build_candidate_urls(
            set_name=context.set_name,
            set_code=context.set_code,
            set_slug_candidates=set_slug_candidates,
            alias_names=context.set_aliases,
            product_name=context.product_name,
            rarity=context.rarity,
            variant_count=context.variant_count,
            explicit_variant_name=context.variant_name,
        )

        best_ambiguous: CardmarketResolvedProduct | None = None
        for candidate in candidates:
            try:
                logger.info("Trying Cardmarket URL candidate: %s", candidate.url)
                verified = await self.verifier.verify_url(candidate.url, context)
            except Exception as exc:
                logger.warning("Failed to resolve candidate %s: %s", candidate.url, exc)
                continue

            verified = replace(verified, set_slug_source=candidate.set_slug_source)
            if verified.match_quality in {CARDMARKET_MATCH_EXACT, CARDMARKET_MATCH_EXACT_VARIANT, CARDMARKET_MATCH_SET_NAME}:
                logger.info("Resolved exact Cardmarket product for %s: %s", context.product_name, verified.url)
                return verified

            best_ambiguous = verified

        if best_ambiguous:
            return best_ambiguous

        fallback_set_slug = set_slug_candidates[0].slug if set_slug_candidates else None
        fallback_set_source = set_slug_candidates[0].source if set_slug_candidates else None
        return CardmarketResolvedProduct(
            url=None,
            set_slug=fallback_set_slug or self.url_builder.build_set_slug(context.set_name, set_code=context.set_code, alias_names=context.set_aliases),
            product_slug=None,
            product_name=context.product_name,
            set_name=context.set_name,
            rarity=context.rarity,
            card_number=context.card_number,
            variant_name=context.variant_name,
            match_quality=CARDMARKET_MATCH_FAILED,
            verified_at=None,
            reason="no exact product url resolved",
            parse_status="failed",
            set_slug_source=fallback_set_source,
        )


_DEFAULT_RESOLVER = CardmarketProductResolver()


def get_cardmarket_product_resolver() -> CardmarketProductResolver:
    return _DEFAULT_RESOLVER
