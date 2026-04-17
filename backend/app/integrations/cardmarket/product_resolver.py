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


def _build_resolution_context(context: CardmarketPrintContext) -> dict[str, object]:
    return {
        "product_name": context.product_name,
        "set_name": context.set_name,
        "set_code": context.set_code,
        "rarity": context.rarity,
        "card_number": context.card_number,
        "language": context.language,
        "variant_count": context.variant_count,
        "variant_name": context.variant_name,
        "existing_product_url": context.existing_product_url,
        "existing_set_slug": context.existing_set_slug,
        "existing_product_slug": context.existing_product_slug,
        "set_slug_hints": context.set_slug_hints,
        "set_aliases": context.set_aliases,
    }


def _attach_resolution_diagnostics(
    resolved: CardmarketResolvedProduct,
    *,
    context: CardmarketPrintContext,
    trace: list[dict[str, object]],
) -> CardmarketResolvedProduct:
    diagnostics = dict(resolved.diagnostics or {})
    diagnostics["resolution_context"] = _build_resolution_context(context)
    diagnostics["resolution_trace"] = trace
    return replace(resolved, diagnostics=diagnostics)


class CardmarketProductResolver:
    def __init__(self) -> None:
        self.set_slug_resolver: CardmarketSetSlugResolver = get_cardmarket_set_slug_resolver()
        self.url_builder = CardmarketProductUrlBuilder()
        self.verifier = CardmarketProductVerifier()

    async def resolve(self, context: CardmarketPrintContext) -> CardmarketResolvedProduct:
        resolution_trace: list[dict[str, object]] = []
        existing_url = normalize_cardmarket_product_url(context.existing_product_url)
        if existing_url:
            logger.info("Verifying stored Cardmarket URL: %s", existing_url)
            resolution_trace.append(
                {
                    "stage": "verify_existing_product_url",
                    "candidate_url": existing_url,
                }
            )
            verified = await self.verifier.verify_url(existing_url, context)
            resolution_trace.append(
                {
                    "stage": "verify_existing_product_url_result",
                    "candidate_url": existing_url,
                    "result_url": verified.url,
                    "match_quality": verified.match_quality,
                    "reason": verified.reason,
                    "parse_status": verified.parse_status,
                    "verification_diagnostics": verified.diagnostics,
                }
            )
            if verified.match_quality in {CARDMARKET_MATCH_EXACT, CARDMARKET_MATCH_EXACT_VARIANT, CARDMARKET_MATCH_SET_NAME}:
                return _attach_resolution_diagnostics(verified, context=context, trace=resolution_trace)

        if context.existing_set_slug and context.existing_product_slug:
            candidate_url = self.url_builder.build_product_url(context.existing_set_slug, context.existing_product_slug)
            logger.info("Verifying stored Cardmarket slug URL: %s", candidate_url)
            resolution_trace.append(
                {
                    "stage": "verify_existing_slug_url",
                    "candidate_url": candidate_url,
                    "set_slug": context.existing_set_slug,
                    "product_slug": context.existing_product_slug,
                }
            )
            verified = await self.verifier.verify_url(candidate_url, context)
            resolution_trace.append(
                {
                    "stage": "verify_existing_slug_url_result",
                    "candidate_url": candidate_url,
                    "result_url": verified.url,
                    "match_quality": verified.match_quality,
                    "reason": verified.reason,
                    "parse_status": verified.parse_status,
                    "verification_diagnostics": verified.diagnostics,
                }
            )
            if verified.match_quality in {CARDMARKET_MATCH_EXACT, CARDMARKET_MATCH_EXACT_VARIANT, CARDMARKET_MATCH_SET_NAME}:
                return _attach_resolution_diagnostics(verified, context=context, trace=resolution_trace)

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
        resolution_trace.append(
            {
                "stage": "resolve_set_slug_candidates",
                "candidates": [
                    {
                        "slug": candidate.slug,
                        "source": candidate.source,
                        "verified": candidate.verified,
                    }
                    for candidate in set_slug_candidates
                ],
            }
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
            resolution_trace.append(
                {
                    "stage": "try_candidate_url",
                    "candidate_url": candidate.url,
                    "set_slug": candidate.set_slug,
                    "product_slug": candidate.product_slug,
                    "variant_name": candidate.variant_name,
                    "reason": candidate.reason,
                    "set_slug_source": candidate.set_slug_source,
                }
            )
            try:
                logger.info("Trying Cardmarket URL candidate: %s", candidate.url)
                verified = await self.verifier.verify_url(candidate.url, context)
            except Exception as exc:
                logger.warning("Failed to resolve candidate %s: %s", candidate.url, exc)
                resolution_trace.append(
                    {
                        "stage": "candidate_url_error",
                        "candidate_url": candidate.url,
                        "error": str(exc),
                    }
                )
                continue

            verified = replace(verified, set_slug_source=candidate.set_slug_source)
            resolution_trace.append(
                {
                    "stage": "candidate_url_result",
                    "candidate_url": candidate.url,
                    "result_url": verified.url,
                    "match_quality": verified.match_quality,
                    "reason": verified.reason,
                    "parse_status": verified.parse_status,
                    "set_slug_source": candidate.set_slug_source,
                    "verification_diagnostics": verified.diagnostics,
                }
            )
            if verified.match_quality in {CARDMARKET_MATCH_EXACT, CARDMARKET_MATCH_EXACT_VARIANT, CARDMARKET_MATCH_SET_NAME}:
                logger.info("Resolved exact Cardmarket product for %s: %s", context.product_name, verified.url)
                return _attach_resolution_diagnostics(verified, context=context, trace=resolution_trace)

            best_ambiguous = verified

        if best_ambiguous:
            return _attach_resolution_diagnostics(best_ambiguous, context=context, trace=resolution_trace)

        fallback_set_slug = set_slug_candidates[0].slug if set_slug_candidates else None
        fallback_set_source = set_slug_candidates[0].source if set_slug_candidates else None
        resolution_trace.append(
            {
                "stage": "resolution_failed",
                "fallback_set_slug": fallback_set_slug,
                "fallback_set_source": fallback_set_source,
                "candidate_count": len(candidates),
            }
        )
        return _attach_resolution_diagnostics(
            CardmarketResolvedProduct(
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
            ),
            context=context,
            trace=resolution_trace,
        )


_DEFAULT_RESOLVER = CardmarketProductResolver()


def get_cardmarket_product_resolver() -> CardmarketProductResolver:
    return _DEFAULT_RESOLVER
