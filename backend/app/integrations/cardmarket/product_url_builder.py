from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

from .set_slug_resolver import CardmarketSetSlugCandidate, get_cardmarket_set_slug_resolver


CARDMARKET_CATEGORY = "Products/Singles"
CARDMARKET_BASE_URL = "https://www.cardmarket.com"
CARDMARKET_MATCH_EXACT = "exact_verified"
CARDMARKET_MATCH_EXACT_VARIANT = "exact_verified_variant"
CARDMARKET_MATCH_SET_NAME = "set_name_verified_name_only"
CARDMARKET_MATCH_MANUAL = "manual_verified"
CARDMARKET_MATCH_AMBIGUOUS = "ambiguous"
CARDMARKET_MATCH_FAILED = "failed"
CARDMARKET_SAFE_MATCH_QUALITIES = frozenset(
    {
        CARDMARKET_MATCH_EXACT,
        CARDMARKET_MATCH_EXACT_VARIANT,
        CARDMARKET_MATCH_MANUAL,
        CARDMARKET_MATCH_SET_NAME,
    }
)

_STOPWORDS = {"of", "the", "and", "for", "de", "la", "le", "el", "in", "on", "to", "a", "an"}
_ROMAN_NUMERALS = {"i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"}


def _ascii_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("ascii", "ignore").decode("ascii")


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _variant_number(variant_name: str | None) -> int | None:
    match = re.search(r"V\.?\s*-?\s*(\d+)", variant_name or "", flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


@dataclass(slots=True)
class CardmarketUrlCandidate:
    url: str
    set_slug: str
    product_slug: str
    variant_name: str | None = None
    reason: str | None = None
    set_slug_source: str | None = None


class CardmarketProductUrlBuilder:
    def __init__(self, *, variant_probe_limit: int = 12) -> None:
        self.set_slug_resolver = get_cardmarket_set_slug_resolver()
        self.variant_probe_limit = max(1, min(int(variant_probe_limit), 32))

    def slugify_segment(self, value: str | None) -> str | None:
        text = _ascii_text(value).strip()
        if not text:
            return None
        text = re.sub(r"(?<=\w)'(?=\w)", "", text)

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

    def build_set_slug(
        self,
        set_name: str | None,
        *,
        set_code: str | None = None,
        existing_set_slug: str | None = None,
        verified_set_slugs: list[str] | None = None,
        alias_names: list[str] | None = None,
    ) -> str | None:
        return self.set_slug_resolver.resolve_best_slug(
            set_name=set_name,
            set_code=set_code,
            existing_set_slug=existing_set_slug,
            verified_set_slugs=verified_set_slugs,
            alias_names=alias_names,
        )

    def build_product_slug(self, *, product_name: str | None, variant_name: str | None = None, rarity: str | None = None) -> str | None:
        parts = [value for value in [product_name, variant_name, rarity] if value]
        if not parts:
            return None
        return self.slugify_segment(" ".join(parts))

    def build_product_url(self, set_slug: str, product_slug: str) -> str:
        return f"{CARDMARKET_BASE_URL}/en/YuGiOh/{CARDMARKET_CATEGORY}/{set_slug}/{product_slug}"

    def build_fallback_url(self, card_name: str | None) -> str | None:
        slug = self.slugify_segment(card_name)
        if not slug:
            return None
        return f"{CARDMARKET_BASE_URL}/en/YuGiOh/Cards/{slug}"

    def build_candidate_urls(
        self,
        *,
        set_name: str | None,
        set_code: str | None = None,
        set_slug_candidates: list[CardmarketSetSlugCandidate] | None = None,
        alias_names: list[str] | None = None,
        product_name: str | None,
        rarity: str | None = None,
        variant_count: int = 1,
        explicit_variant_name: str | None = None,
    ) -> list[CardmarketUrlCandidate]:
        resolved_set_slug_candidates = set_slug_candidates or self.set_slug_resolver.resolve_candidates(
            set_name=set_name,
            set_code=set_code,
            alias_names=alias_names,
        )
        base_product_slug = self.slugify_segment(product_name)
        rarity_slug = self.slugify_segment(rarity)
        if not resolved_set_slug_candidates or not base_product_slug:
            return []

        candidates: list[CardmarketUrlCandidate] = []

        def add(set_slug: str, set_slug_source: str, product_slug: str | None, *, variant_name: str | None = None, reason: str) -> None:
            if not product_slug:
                return
            candidates.append(
                CardmarketUrlCandidate(
                    url=self.build_product_url(set_slug, product_slug),
                    set_slug=set_slug,
                    product_slug=product_slug,
                    variant_name=variant_name,
                    reason=reason,
                    set_slug_source=set_slug_source,
                )
            )

        variant_numbers: list[int] = []
        explicit_number = _variant_number(explicit_variant_name)
        if explicit_number:
            variant_numbers.append(explicit_number)
        if variant_count > 1:
            probe_count = min(max(variant_count, self.variant_probe_limit), 32)
            variant_numbers.extend(range(1, probe_count + 1))
        variant_numbers = [int(number) for number in _dedupe_preserve_order([str(number) for number in variant_numbers])]

        for set_candidate in resolved_set_slug_candidates:
            if variant_numbers:
                if rarity_slug:
                    for variant_number in variant_numbers:
                        compact_variant = f"V{variant_number}"
                        add(
                            set_candidate.slug,
                            set_candidate.source,
                            f"{base_product_slug}-{compact_variant}-{rarity_slug}",
                            variant_name=compact_variant,
                            reason="canonical_variant_with_rarity",
                        )

                for variant_number in variant_numbers:
                    compact_variant = f"V{variant_number}"
                    add(
                        set_candidate.slug,
                        set_candidate.source,
                        f"{base_product_slug}-{compact_variant}",
                        variant_name=compact_variant,
                        reason="compact_variant_suffix",
                    )

                for variant_number in variant_numbers:
                    compact_variant = f"V{variant_number}"
                    hyphen_variant = f"V-{variant_number}"
                    if rarity_slug:
                        add(
                            set_candidate.slug,
                            set_candidate.source,
                            f"{base_product_slug}-{hyphen_variant}-{rarity_slug}",
                            variant_name=compact_variant,
                            reason="hyphen_variant_suffix_with_rarity",
                        )
                        add(
                            set_candidate.slug,
                            set_candidate.source,
                            f"{base_product_slug}-{rarity_slug}-{compact_variant}",
                            variant_name=compact_variant,
                            reason="compact_variant_rarity_before_variant",
                        )
                    add(
                        set_candidate.slug,
                        set_candidate.source,
                        f"{base_product_slug}-{hyphen_variant}",
                        variant_name=compact_variant,
                        reason="hyphen_variant_suffix",
                    )

                if rarity_slug:
                    add(set_candidate.slug, set_candidate.source, f"{base_product_slug}-{rarity_slug}", reason="base_product_slug_with_rarity")
                add(set_candidate.slug, set_candidate.source, base_product_slug, reason="base_product_slug")
            else:
                add(set_candidate.slug, set_candidate.source, base_product_slug, reason="base_product_slug")
                if rarity_slug:
                    add(set_candidate.slug, set_candidate.source, f"{base_product_slug}-{rarity_slug}", reason="base_product_slug_with_rarity")

        deduped: list[CardmarketUrlCandidate] = []
        seen_urls: set[str] = set()
        for candidate in candidates:
            if candidate.url in seen_urls:
                continue
            seen_urls.add(candidate.url)
            deduped.append(candidate)
        return deduped


CardmarketUrlBuilder = CardmarketProductUrlBuilder

_DEFAULT_BUILDER = CardmarketProductUrlBuilder()


def slugify_cardmarket_segment(value: str | None) -> str | None:
    return _DEFAULT_BUILDER.slugify_segment(value)


def build_cardmarket_set_slug(
    set_name: str | None,
    *,
    set_code: str | None = None,
    existing_set_slug: str | None = None,
    verified_set_slugs: list[str] | None = None,
    alias_names: list[str] | None = None,
) -> str | None:
    return _DEFAULT_BUILDER.build_set_slug(
        set_name,
        set_code=set_code,
        existing_set_slug=existing_set_slug,
        verified_set_slugs=verified_set_slugs,
        alias_names=alias_names,
    )


def build_cardmarket_product_slug(*, product_name: str | None, variant_name: str | None = None) -> str | None:
    return _DEFAULT_BUILDER.build_product_slug(product_name=product_name, variant_name=variant_name)


def build_cardmarket_product_url(locale: str, set_slug: str, product_slug: str) -> str:
    del locale
    return _DEFAULT_BUILDER.build_product_url(set_slug, product_slug)


def build_cardmarket_fallback_url(locale: str, card_name: str | None) -> str | None:
    del locale
    return _DEFAULT_BUILDER.build_fallback_url(card_name)


def _slug_has_variant_marker(product_slug: str | None) -> bool:
    return bool(product_slug and re.search(r"(?:^|-)V-?\d+(?:-|$)", product_slug, flags=re.IGNORECASE))
