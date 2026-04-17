from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(slots=True)
class CardmarketPrintContext:
    product_name: str | None
    set_name: str | None
    set_code: str | None
    rarity: str | None
    card_number: str | None
    language: str | None
    variant_count: int = 1
    variant_name: str | None = None
    existing_product_url: str | None = None
    existing_set_slug: str | None = None
    existing_product_slug: str | None = None
    set_slug_hints: list[str] = field(default_factory=list)
    set_aliases: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CardmarketResolvedProduct:
    url: str | None
    set_slug: str | None
    product_slug: str | None
    product_name: str | None
    set_name: str | None
    rarity: str | None
    card_number: str | None
    variant_name: str | None
    match_quality: str
    verified_at: datetime | None
    reason: str
    parse_status: str
    set_slug_source: str | None = None
