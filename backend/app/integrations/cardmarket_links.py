from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging
import re
import unicodedata
from urllib.parse import urlparse

CARDMARKET_CATEGORY = "Products/Singles"
CARDMARKET_BASE_URL = "https://www.cardmarket.com"
CARDMARKET_MATCH_EXACT = "exact_verified"
CARDMARKET_MATCH_EXACT_VARIANT = "exact_verified_variant"
CARDMARKET_MATCH_SET_NAME = "set_name_verified_name_only"
CARDMARKET_MATCH_AMBIGUOUS = "ambiguous"
CARDMARKET_MATCH_FAILED = "failed"
_STOPWORDS = {"of", "the", "and", "for", "de", "la", "le", "el", "in", "on", "to", "a", "an"}
_ROMAN_NUMERALS = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}

logger = logging.getLogger(__name__)


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


def _ascii_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("ascii", "ignore").decode("ascii")


def slugify_cardmarket_segment(value: str | None) -> str | None:
    text = _ascii_text(value).strip()
    if not text:
        return None

    tokens = [token for token in re.split(r"[^A-Za-z0-9]+", text) if token]
    if not tokens:
        return None

    slug_parts: list[str] = []
    for index, token in enumerate(tokens):
        lower = token.lower()
        if re.fullmatch(r"V\d+", token.upper()):
            slug_parts.append(token.upper())
        elif lower in _ROMAN_NUMERALS:
            slug_parts.append(token.upper())
        elif token.isdigit():
            slug_parts.append(token)
        elif lower in _STOPWORDS and 0 < index < len(tokens) - 1:
            slug_parts.append(lower)
        else:
            slug_parts.append(token[:1].upper() + token[1:].lower())

    return "-".join(slug_parts)


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
    locale = path_segments[0]
    set_slug = path_segments[4]
    product_slug = path_segments[5]
    return locale, set_slug, product_slug


def build_cardmarket_set_slug(set_name: str | None) -> str | None:
    return slugify_cardmarket_segment(set_name)


def build_cardmarket_product_slug(
    *,
    product_name: str | None,
    variant_name: str | None = None,
) -> str | None:
    parts = [value for value in [product_name, variant_name] if value]
    if not parts:
        return None
    return slugify_cardmarket_segment(" ".join(parts))


def build_cardmarket_product_url(locale: str, set_slug: str, product_slug: str) -> str:
    # Always use English locale for product URLs
    return f"{CARDMARKET_BASE_URL}/en/YuGiOh/{CARDMARKET_CATEGORY}/{set_slug}/{product_slug}"


def build_cardmarket_fallback_url(locale: str, card_name: str | None) -> str | None:
    slug = slugify_cardmarket_segment(card_name)
    if not slug:
        return None
    # Always use English locale for fallback URLs
    return f"{CARDMARKET_BASE_URL}/en/YuGiOh/Cards/{slug}"


def _slug_has_variant_marker(product_slug: str | None) -> bool:
    return bool(product_slug and re.search(r"(?:^|-)V-?\d+(?:-|$)", product_slug, flags=re.IGNORECASE))


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
    exact_url = normalize_cardmarket_product_url(cardmarket_product_url)
    if exact_url:
        _, set_slug, product_slug = split_cardmarket_product_url(exact_url)
        mode = CARDMARKET_MATCH_EXACT_VARIANT if _slug_has_variant_marker(product_slug) or cardmarket_variant_name else CARDMARKET_MATCH_EXACT
        logger.debug("Resolved exact Cardmarket URL %s with mode=%s", exact_url, mode)
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
        logger.debug("Resolved stored Cardmarket slug %s/%s with mode=%s", derived_set_slug, cardmarket_product_slug, mode)
        return CardmarketLinkResolution(
            url=build_cardmarket_product_url(locale, derived_set_slug, cardmarket_product_slug),
            mode=mode,
            set_slug=derived_set_slug,
            product_slug=cardmarket_product_slug,
            product_name=cardmarket_product_name or card_name,
            variant_name=cardmarket_variant_name,
            verified_at=datetime.utcnow(),
            reason="stored_exact_slug",
        )

    derived_product_slug = build_cardmarket_product_slug(
        product_name=cardmarket_product_name or card_name,
        variant_name=cardmarket_variant_name,
    )
    if derived_set_slug and derived_product_slug:
        if has_multiple_variants and not cardmarket_variant_name:
            fallback_url = build_cardmarket_fallback_url(locale, card_name or cardmarket_product_name) if allow_fallback else None
            logger.debug(
                "Cardmarket product ambiguous for set=%s product=%s due to multiple variants",
                derived_set_slug,
                derived_product_slug,
            )
            return CardmarketLinkResolution(
                url=fallback_url,
                mode=CARDMARKET_MATCH_AMBIGUOUS,
                set_slug=derived_set_slug,
                product_slug=None,
                product_name=cardmarket_product_name or card_name,
                variant_name=cardmarket_variant_name,
                reason="multiple_variants_without_exact_slug",
            )

        mode = CARDMARKET_MATCH_EXACT_VARIANT if cardmarket_variant_name else CARDMARKET_MATCH_SET_NAME
        logger.debug("Derived Cardmarket URL for set=%s product=%s with mode=%s", derived_set_slug, derived_product_slug, mode)
        return CardmarketLinkResolution(
            url=build_cardmarket_product_url(locale, derived_set_slug, derived_product_slug),
            mode=mode,
            set_slug=derived_set_slug,
            product_slug=derived_product_slug,
            product_name=cardmarket_product_name or card_name,
            variant_name=cardmarket_variant_name,
            verified_at=datetime.utcnow(),
            reason="derived_from_set_and_name",
        )

    fallback_url = build_cardmarket_fallback_url(locale, card_name or cardmarket_product_name) if allow_fallback else None
    logger.debug(
        "Falling back to generic Cardmarket URL for card=%s set=%s product=%s",
        card_name or cardmarket_product_name,
        cardmarket_set_name,
        cardmarket_product_slug,
    )
    return CardmarketLinkResolution(
        url=fallback_url,
        mode=CARDMARKET_MATCH_AMBIGUOUS if fallback_url else CARDMARKET_MATCH_FAILED,
        set_slug=derived_set_slug,
        product_slug=derived_product_slug,
        product_name=cardmarket_product_name or card_name,
        variant_name=cardmarket_variant_name,
        reason="fallback_search_url" if fallback_url else "no_cardmarket_url_available",
    )
