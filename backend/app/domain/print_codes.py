"""Helpers for Yu-Gi-Oh! print codes such as ``RA05-DE080``.

A print code consists of a series (``RA05``), an optional language prefix
(``DE``) and the card number within the set (``080``). These helpers are shared
by the set import, card lookup and price matching code.
"""

from __future__ import annotations

import re

LANGUAGE_SET_CODE_PREFIXES: dict[str, tuple[str, ...]] = {
    "de": ("DE",),
    "en": ("EN",),
    "fr": ("FR",),
    "it": ("IT",),
    "es": ("ES", "SP"),
    "pt": ("PT",),
    "jp": ("JP",),
    "ja": ("JP",),
    "ko": ("KR",),
}

_PREFIX_TO_LANGUAGE: dict[str, str] = {
    "DE": "de",
    "EN": "en",
    "FR": "fr",
    "IT": "it",
    "ES": "es",
    "SP": "es",
    "PT": "pt",
    "JP": "jp",
    "KR": "ko",
    "AE": "en",
}
_LANGUAGE_PREFIX_PATTERN = "|".join(sorted(_PREFIX_TO_LANGUAGE, key=len, reverse=True))


def normalize_name(value: str) -> str:
    return " ".join(value.lower().split())


def normalize_lookup_value(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def derive_card_number(set_code: str | None) -> str | None:
    if not set_code or "-" not in set_code:
        return None
    return set_code.rsplit("-", 1)[-1] or None


def derive_print_language(set_code: str | None) -> str:
    if not set_code or "-" not in set_code:
        return "en"
    suffix = set_code.split("-", 1)[1].upper()
    for prefix, language in _PREFIX_TO_LANGUAGE.items():
        if suffix.startswith(prefix):
            return language
    return "en"


def _strip_language_prefix(value: str) -> str | None:
    match = re.match(rf"^(?:{_LANGUAGE_PREFIX_PATTERN})([A-Z0-9-]+)$", value)
    return match.group(1) if match else None


def set_code_language_neutral_signature(set_code: str | None) -> tuple[str, str] | None:
    """Return ``(series, number)`` without the language prefix, or None if no prefix is present."""
    normalized_set_code = (set_code or "").strip().upper()
    if "-" not in normalized_set_code:
        return None
    series, suffix = normalized_set_code.split("-", 1)
    number = _strip_language_prefix(suffix)
    if number is None:
        return None
    return normalize_lookup_value(series), normalize_lookup_value(number)


def set_codes_match_language_neutral(left: str | None, right: str | None) -> bool:
    normalized_left = normalize_lookup_value(left)
    normalized_right = normalize_lookup_value(right)
    if not normalized_left or not normalized_right:
        return False
    if normalized_left == normalized_right:
        return True
    left_signature = set_code_language_neutral_signature(left)
    right_signature = set_code_language_neutral_signature(right)
    return bool(left_signature and right_signature and left_signature == right_signature)


def card_number_language_neutral(value: str | None) -> str:
    normalized_value = (value or "").strip().upper()
    return normalize_lookup_value(_strip_language_prefix(normalized_value) or normalized_value)
