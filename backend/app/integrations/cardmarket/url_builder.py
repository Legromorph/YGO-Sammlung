from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from .product_url_builder import (
    CARDMARKET_BASE_URL,
    CARDMARKET_CATEGORY,
    CARDMARKET_MATCH_AMBIGUOUS,
    CARDMARKET_MATCH_EXACT,
    CARDMARKET_MATCH_EXACT_VARIANT,
    CARDMARKET_MATCH_FAILED,
    CARDMARKET_MATCH_SET_NAME,
    CardmarketProductUrlBuilder,
    CardmarketUrlBuilder,
    CardmarketUrlCandidate,
    _slug_has_variant_marker,
    build_cardmarket_fallback_url,
    build_cardmarket_product_slug,
    build_cardmarket_product_url,
    build_cardmarket_set_slug,
    slugify_cardmarket_segment,
)
from .set_slug_resolver import CardmarketSetSlugCandidate


@dataclass(slots=True)
class CardmarketLinkResolution:
    url: str | None
    mode: str
    category: str = CARDMARKET_CATEGORY
    set_slug: str | None = None
    product_slug: str | None = None
    product_name: str | None = None
    variant_name: str | None = None
    verified_at: datetime | None = None
    reason: str | None = None


_DEFAULT_BUILDER = CardmarketProductUrlBuilder()


def normalize_cardmarket_product_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None
    if "cardmarket.com" not in parsed.netloc.lower():
        return None

    path_segments = [segment for segment in parsed.path.split("/") if segment]
    if len(path_segments) < 6:
        return None
    if path_segments[2:4] != ["Products", "Singles"]:
        return None
    return f"{parsed.scheme}://{parsed.netloc}/{'/'.join(path_segments[:6])}"


def split_cardmarket_product_url(url: str | None) -> tuple[str | None, str | None, str | None]:
    parsed = urlparse(url or "")
    if parsed.scheme not in {"http", "https"} or "cardmarket.com" not in parsed.netloc.lower():
        return None, None, None

    path_segments = [segment for segment in parsed.path.split("/") if segment]
    if len(path_segments) < 6 or path_segments[2:4] != ["Products", "Singles"]:
        return None, None, None
    return path_segments[0], path_segments[4], path_segments[5]


def resolve_cardmarket_product_url(
    *,
    locale: str,
    cardmarket_product_url: str | None = None,
    cardmarket_product_slug: str | None = None,
    cardmarket_set_slug: str | None = None,
    cardmarket_set_name: str | None = None,
    cardmarket_product_name: str | None = None,
    cardmarket_variant_name: str | None = None,
    card_name: str | None = None,
    has_multiple_variants: bool = False,
    allow_fallback: bool = True,
) -> CardmarketLinkResolution:
    del locale

    exact_url = normalize_cardmarket_product_url(cardmarket_product_url)
    if exact_url:
        _, set_slug, product_slug = split_cardmarket_product_url(exact_url)
        mode = CARDMARKET_MATCH_EXACT_VARIANT if _slug_has_variant_marker(product_slug) or cardmarket_variant_name else CARDMARKET_MATCH_EXACT
        return CardmarketLinkResolution(
            url=exact_url,
            mode=mode,
            set_slug=set_slug,
            product_slug=product_slug,
            product_name=cardmarket_product_name or card_name,
            variant_name=cardmarket_variant_name,
            verified_at=datetime.utcnow(),
            reason="stored_exact_url",
        )

    derived_set_slug = cardmarket_set_slug or build_cardmarket_set_slug(cardmarket_set_name)
    if cardmarket_product_slug and derived_set_slug:
        mode = CARDMARKET_MATCH_EXACT_VARIANT if _slug_has_variant_marker(cardmarket_product_slug) or cardmarket_variant_name else CARDMARKET_MATCH_EXACT
        return CardmarketLinkResolution(
            url=_DEFAULT_BUILDER.build_product_url(derived_set_slug, cardmarket_product_slug),
            mode=mode,
            set_slug=derived_set_slug,
            product_slug=cardmarket_product_slug,
            product_name=cardmarket_product_name or card_name,
            variant_name=cardmarket_variant_name,
            verified_at=datetime.utcnow(),
            reason="stored_exact_slug",
        )

    explicit_set_candidates = (
        [CardmarketSetSlugCandidate(slug=derived_set_slug, source="explicit_set_slug", verified=True)]
        if derived_set_slug
        else None
    )
    candidates = _DEFAULT_BUILDER.build_candidate_urls(
        set_name=cardmarket_set_name,
        set_slug_candidates=explicit_set_candidates,
        product_name=cardmarket_product_name or card_name,
        rarity=None,
        variant_count=2 if has_multiple_variants else 1,
        explicit_variant_name=cardmarket_variant_name,
    )
    if candidates:
        first_candidate = candidates[0]
        return CardmarketLinkResolution(
            url=first_candidate.url,
            mode=CARDMARKET_MATCH_EXACT_VARIANT if _slug_has_variant_marker(first_candidate.product_slug) else CARDMARKET_MATCH_SET_NAME,
            set_slug=first_candidate.set_slug,
            product_slug=first_candidate.product_slug,
            product_name=cardmarket_product_name or card_name,
            variant_name=first_candidate.variant_name,
            reason=first_candidate.reason,
        )

    fallback_url = _DEFAULT_BUILDER.build_fallback_url(card_name or cardmarket_product_name) if allow_fallback else None
    return CardmarketLinkResolution(
        url=fallback_url,
        mode=CARDMARKET_MATCH_AMBIGUOUS if fallback_url else CARDMARKET_MATCH_FAILED,
        set_slug=derived_set_slug,
        product_slug=cardmarket_product_slug,
        product_name=cardmarket_product_name or card_name,
        variant_name=cardmarket_variant_name,
        reason="fallback_search_url" if fallback_url else "no_cardmarket_url_available",
    )
