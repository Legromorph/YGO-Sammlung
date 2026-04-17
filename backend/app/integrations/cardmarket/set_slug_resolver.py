from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


def _ascii_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    return normalized.encode("ascii", "ignore").decode("ascii")


def normalize_cardmarket_lookup_key(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]", "", _ascii_text(value).lower())


def _heuristic_slug(value: str | None) -> str | None:
    text = _ascii_text(value).strip()
    if not text:
        return None

    tokens = [token for token in re.split(r"[^A-Za-z0-9]+", text) if token]
    if not tokens:
        return None

    parts: list[str] = []
    for token in tokens:
        if token.isdigit():
            parts.append(token)
        else:
            parts.append(token[:1].upper() + token[1:].lower())
    return "-".join(parts)


_KNOWN_SET_SLUG_ALIASES: dict[str, str] = {
    normalize_cardmarket_lookup_key("2014 Mega-Tin Mega Pack"): "2014-MegaTins-MegaPack",
    normalize_cardmarket_lookup_key("2014 Mega Tin Mega Pack"): "2014-MegaTins-MegaPack",
    normalize_cardmarket_lookup_key("2014 Mega-Tins Mega Pack"): "2014-MegaTins-MegaPack",
    normalize_cardmarket_lookup_key("2014 Mega-Tins Mega-Pack"): "2014-MegaTins-MegaPack",
    normalize_cardmarket_lookup_key("2014-MegaTins-MegaPack"): "2014-MegaTins-MegaPack",
    normalize_cardmarket_lookup_key("MP14"): "2014-MegaTins-MegaPack",
}


@dataclass(slots=True)
class CardmarketSetSlugCandidate:
    slug: str
    source: str
    verified: bool = False


class CardmarketSetSlugResolver:
    def _dedupe(self, values: list[CardmarketSetSlugCandidate]) -> list[CardmarketSetSlugCandidate]:
        seen: set[str] = set()
        deduped: list[CardmarketSetSlugCandidate] = []
        for candidate in values:
            if not candidate.slug or candidate.slug in seen:
                continue
            seen.add(candidate.slug)
            deduped.append(candidate)
        return deduped

    def resolve_candidates(
        self,
        *,
        set_name: str | None,
        set_code: str | None = None,
        existing_set_slug: str | None = None,
        verified_set_slugs: list[str] | None = None,
        alias_names: list[str] | None = None,
    ) -> list[CardmarketSetSlugCandidate]:
        candidates: list[CardmarketSetSlugCandidate] = []

        if existing_set_slug:
            candidates.append(
                CardmarketSetSlugCandidate(
                    slug=existing_set_slug,
                    source="stored_exact_set_slug",
                    verified=True,
                )
            )

        for slug in verified_set_slugs or []:
            if slug:
                candidates.append(
                    CardmarketSetSlugCandidate(
                        slug=slug,
                        source="verified_set_slug_hint",
                        verified=True,
                    )
                )

        alias_inputs = [set_code, set_name, *(alias_names or [])]
        for value in alias_inputs:
            mapped_slug = _KNOWN_SET_SLUG_ALIASES.get(normalize_cardmarket_lookup_key(value))
            if mapped_slug:
                candidates.append(
                    CardmarketSetSlugCandidate(
                        slug=mapped_slug,
                        source="known_set_slug_alias",
                        verified=True,
                    )
                )

        heuristic = _heuristic_slug(set_name)
        if heuristic:
            candidates.append(
                CardmarketSetSlugCandidate(
                    slug=heuristic,
                    source="heuristic_set_slug",
                    verified=False,
                )
            )

        return self._dedupe(candidates)

    def resolve_best_slug(
        self,
        *,
        set_name: str | None,
        set_code: str | None = None,
        existing_set_slug: str | None = None,
        verified_set_slugs: list[str] | None = None,
        alias_names: list[str] | None = None,
    ) -> str | None:
        candidates = self.resolve_candidates(
            set_name=set_name,
            set_code=set_code,
            existing_set_slug=existing_set_slug,
            verified_set_slugs=verified_set_slugs,
            alias_names=alias_names,
        )
        return candidates[0].slug if candidates else None


_DEFAULT_SET_SLUG_RESOLVER = CardmarketSetSlugResolver()


def get_cardmarket_set_slug_resolver() -> CardmarketSetSlugResolver:
    return _DEFAULT_SET_SLUG_RESOLVER
