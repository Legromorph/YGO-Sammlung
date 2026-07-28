from __future__ import annotations

from app.config import settings

from .product_url_builder import CardmarketProductUrlBuilder
from .set_slug_resolver import CardmarketSetSlugResolver, get_cardmarket_set_slug_resolver
from .types import CardmarketPrintContext, CardmarketResolvedProduct
from .url_builder import (
    CARDMARKET_MATCH_AMBIGUOUS,
    CARDMARKET_MATCH_FAILED,
    normalize_cardmarket_product_url,
    split_cardmarket_product_url,
)


MANUAL_CONFIRMATION_REASON = "Automatisch erzeugter Vorschlag; manuelle Bestätigung erforderlich."


class CardmarketProductResolver:
    """Builds suggestions without requesting or scraping Cardmarket pages."""

    def __init__(self) -> None:
        self.set_slug_resolver: CardmarketSetSlugResolver = get_cardmarket_set_slug_resolver()
        self.url_builder = CardmarketProductUrlBuilder(
            variant_probe_limit=settings.cardmarket_variant_probe_max,
        )

    def _suggestion(
        self,
        context: CardmarketPrintContext,
        *,
        url: str,
        variant_name: str | None,
        set_slug_source: str | None,
        diagnostics: dict[str, object],
    ) -> CardmarketResolvedProduct:
        _, set_slug, product_slug = split_cardmarket_product_url(url)
        return CardmarketResolvedProduct(
            url=url,
            set_slug=set_slug,
            product_slug=product_slug,
            product_name=context.product_name,
            set_name=context.set_name,
            rarity=context.rarity,
            card_number=context.card_number,
            variant_name=variant_name or context.variant_name,
            match_quality=CARDMARKET_MATCH_AMBIGUOUS,
            verified_at=None,
            reason=MANUAL_CONFIRMATION_REASON,
            parse_status="manual_confirmation_required",
            set_slug_source=set_slug_source,
            diagnostics=diagnostics,
        )

    async def resolve(self, context: CardmarketPrintContext) -> CardmarketResolvedProduct:
        existing_url = normalize_cardmarket_product_url(context.existing_product_url)
        if existing_url:
            return self._suggestion(
                context,
                url=existing_url,
                variant_name=context.variant_name,
                set_slug_source="stored_unverified_url",
                diagnostics={
                    "mode": "manual_only",
                    "source": "stored_unverified_url",
                    "candidate_url": existing_url,
                },
            )

        if context.existing_set_slug and context.existing_product_slug:
            candidate_url = self.url_builder.build_product_url(
                context.existing_set_slug,
                context.existing_product_slug,
            )
            return self._suggestion(
                context,
                url=candidate_url,
                variant_name=context.variant_name,
                set_slug_source="stored_product_slug",
                diagnostics={
                    "mode": "manual_only",
                    "source": "stored_product_slug",
                    "candidate_url": candidate_url,
                },
            )

        set_slug_candidates = self.set_slug_resolver.resolve_candidates(
            set_name=context.set_name,
            set_code=context.set_code,
            existing_set_slug=context.existing_set_slug,
            verified_set_slugs=context.set_slug_hints,
            alias_names=context.set_aliases,
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
        if candidates:
            candidate = candidates[0]
            return self._suggestion(
                context,
                url=candidate.url,
                variant_name=candidate.variant_name,
                set_slug_source=candidate.set_slug_source,
                diagnostics={
                    "mode": "manual_only",
                    "source": "generated_candidate",
                    "candidate_count": len(candidates),
                    "candidate_url": candidate.url,
                    "candidate_reason": candidate.reason,
                    "set_slug_candidates": [
                        {
                            "slug": item.slug,
                            "source": item.source,
                            "verified": item.verified,
                        }
                        for item in set_slug_candidates
                    ],
                },
            )

        fallback_set_slug = set_slug_candidates[0].slug if set_slug_candidates else None
        return CardmarketResolvedProduct(
            url=None,
            set_slug=fallback_set_slug,
            product_slug=None,
            product_name=context.product_name,
            set_name=context.set_name,
            rarity=context.rarity,
            card_number=context.card_number,
            variant_name=context.variant_name,
            match_quality=CARDMARKET_MATCH_FAILED,
            verified_at=None,
            reason="Kein Cardmarket-Linkvorschlag konnte erzeugt werden.",
            parse_status="manual_suggestion_failed",
            set_slug_source=set_slug_candidates[0].source if set_slug_candidates else None,
            diagnostics={"mode": "manual_only", "candidate_count": 0},
        )


_DEFAULT_RESOLVER = CardmarketProductResolver()


def get_cardmarket_product_resolver() -> CardmarketProductResolver:
    return _DEFAULT_RESOLVER
