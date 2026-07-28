from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import logging
import re
from urllib.parse import quote

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.cardmarket import CardmarketPrintContext, CardmarketResolvedProduct
from app.integrations.cardmarket.set_slug_resolver import cardmarket_set_code_family
from app.integrations.cardmarket_links import (
    CARDMARKET_MATCH_AMBIGUOUS,
    CARDMARKET_MATCH_EXACT,
    CARDMARKET_MATCH_EXACT_VARIANT,
    CARDMARKET_MATCH_FAILED,
    CARDMARKET_MATCH_MANUAL,
    CARDMARKET_SAFE_MATCH_QUALITIES,
    build_cardmarket_product_slug,
    normalize_cardmarket_product_url,
    split_cardmarket_product_url,
)
from app.integrations.price_values import parse_positive_price
from app.models import CardPrint, CardSet, ImageAsset, InventoryItem
from app.schemas import CardPayload
from app.time_utils import utc_now

logger = logging.getLogger(__name__)

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
class DuplicateInventoryItemError(ValueError):
    def __init__(
        self,
        *,
        existing_item_id: int,
        existing_quantity: int,
        increment_by: int,
        card_name: str,
        set_code: str | None,
        language: str,
        condition: str,
    ) -> None:
        self.existing_item_id = existing_item_id
        self.existing_quantity = existing_quantity
        self.increment_by = max(1, increment_by)
        self.card_name = card_name
        self.set_code = set_code
        self.language = language
        self.condition = condition
        super().__init__("Eine identische Kartenposition existiert bereits.")

    def to_detail(self) -> dict[str, object]:
        return {
            "code": "duplicate_card",
            "message": "Diese Kartenposition existiert bereits. Soll die vorhandene Menge erhöht werden?",
            "existing_item_id": self.existing_item_id,
            "existing_quantity": self.existing_quantity,
            "increment_by": self.increment_by,
            "suggested_quantity": self.existing_quantity + self.increment_by,
            "signature": {
                "name": self.card_name,
                "set_code": self.set_code,
                "language": self.language,
                "condition": self.condition,
            },
        }

def normalize_name(value: str) -> str:
    return " ".join(value.lower().split())

def _parse_language_preferences(value: str | None, *, default: tuple[str, ...] = ("de", "en")) -> list[str]:
    raw_parts = [part.strip().lower() for part in (value or "").split(",") if part and part.strip()]
    normalized_parts: list[str] = []
    seen: set[str] = set()
    for part in raw_parts:
        normalized = _normalize_language_code(part) or part
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        normalized_parts.append(normalized)
    if normalized_parts:
        return normalized_parts
    return list(default)

def _normalize_language_code(value: str | None) -> str:
    return (value or "").strip().lower()

def _extract_set_code_language_prefix(set_code: str | None) -> str | None:
    normalized_set_code = (set_code or "").strip().upper()
    if "-" not in normalized_set_code:
        return None
    suffix = normalized_set_code.split("-", 1)[1]
    match = re.match(r"([A-Z]{2,3})", suffix)
    if not match:
        return None
    return match.group(1)

def _validate_set_code_language(language: str, set_code: str | None) -> None:
    normalized_language = _normalize_language_code(language)
    expected_prefixes = LANGUAGE_SET_CODE_PREFIXES.get(normalized_language)
    if not expected_prefixes:
        return

    detected_prefix = _extract_set_code_language_prefix(set_code)
    if not detected_prefix or detected_prefix in expected_prefixes:
        return

    expected_preview = expected_prefixes[0]
    raise ValueError(
        f"Setcode '{set_code}' passt nicht zur Sprache '{normalized_language.upper()}'. "
        f"Erwartet wird nach dem Bindestrich {', '.join(expected_prefixes)} (z. B. POTD-{expected_preview}011)."
    )

def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None

def _normalize_tags(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return sorted({value.strip().lower() for value in values if value and value.strip()})

def _dedupe_text_values(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = _normalize_optional_text(value)
        if not normalized:
            continue
        key = normalize_name(normalized)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped

def _card_set_lookup_codes(set_code: str | None) -> list[str]:
    normalized = (set_code or "").strip().upper()
    family = cardmarket_set_code_family(normalized)
    return list(dict.fromkeys(value for value in [normalized, family] if value))

async def _find_matching_card_set(
    db: AsyncSession,
    *,
    set_code: str | None,
    set_name: str | None,
) -> CardSet | None:
    set_code_candidates = _card_set_lookup_codes(set_code)
    if set_code_candidates:
        result = await db.execute(
            select(CardSet)
            .where(CardSet.set_code.in_(set_code_candidates))
            .order_by(CardSet.updated_at.desc())
        )
        matches = result.scalars().all()
        for candidate in set_code_candidates:
            card_set = next(
                (
                    match
                    for match in matches
                    if (match.set_code or "").strip().upper() == candidate
                ),
                None,
            )
            if card_set:
                return card_set

    normalized_set_name = normalize_name(set_name) if set_name else ""
    if normalized_set_name:
        result = await db.execute(
            select(CardSet)
            .where(CardSet.normalized_name == normalized_set_name)
            .order_by(CardSet.updated_at.desc())
        )
        matches = result.scalars().all()
        if len(matches) == 1:
            return matches[0]

    return None

async def _load_cardmarket_set_slug_hints(
    db: AsyncSession,
    *,
    set_code: str | None,
    card_set: CardSet | None,
) -> list[str]:
    hints: list[str | None] = []
    if card_set and card_set.cardmarket_set_slug:
        hints.append(card_set.cardmarket_set_slug)

    set_code_candidates = _card_set_lookup_codes(set_code)
    if set_code_candidates:
        family = cardmarket_set_code_family(set_code)
        code_filters = [CardPrint.set_code.in_(set_code_candidates)]
        if family:
            code_filters.append(CardPrint.set_code.like(f"{family}-%"))
        result = await db.execute(
            select(CardPrint.cardmarket_set_slug)
            .where(
                or_(*code_filters),
                CardPrint.cardmarket_set_slug.is_not(None),
                CardPrint.cardmarket_match_quality.in_(tuple(CARDMARKET_SAFE_MATCH_QUALITIES)),
            )
            .distinct()
        )
        hints.extend(result.scalars().all())

    return _dedupe_text_values(hints)

def _build_failed_cardmarket_resolution(context: CardmarketPrintContext, reason: str) -> CardmarketResolvedProduct:
    return CardmarketResolvedProduct(
        url=None,
        set_slug=context.existing_set_slug or (context.set_slug_hints[0] if context.set_slug_hints else None),
        product_slug=context.existing_product_slug or build_cardmarket_product_slug(product_name=context.product_name, variant_name=context.variant_name),
        product_name=context.product_name,
        set_name=context.set_name,
        rarity=context.rarity,
        card_number=context.card_number,
        variant_name=context.variant_name,
        match_quality=CARDMARKET_MATCH_FAILED,
        verified_at=None,
        reason=reason,
        parse_status="failed",
    )

def _update_card_set_cardmarket_metadata(
    card_set: CardSet | None,
    *,
    resolution: CardmarketResolvedProduct,
    alias_names: list[str],
) -> None:
    if not card_set or resolution.match_quality not in CARDMARKET_SAFE_MATCH_QUALITIES or not resolution.set_slug:
        return

    card_set.cardmarket_set_slug = resolution.set_slug
    card_set.cardmarket_set_name = resolution.set_name or card_set.cardmarket_set_name or card_set.name
    card_set.cardmarket_aliases = _dedupe_text_values(
        [
            *(card_set.cardmarket_aliases or []),
            card_set.name,
            card_set.cardmarket_set_name,
            resolution.set_name,
            *alias_names,
        ]
    ) or None
    card_set.cardmarket_slug_match_quality = resolution.match_quality
    card_set.cardmarket_slug_verified_at = resolution.verified_at or utc_now()
    logger.info("Resolved cardmarket set slug '%s' for set '%s'", resolution.set_slug, card_set.name)

def _normalize_price_value(value: float | int | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.0001"))

def _first_image(card_print: CardPrint) -> ImageAsset | None:
    assets = sorted(
        [asset for asset in card_print.image_assets if asset.status == "downloaded" and asset.local_path],
        key=lambda asset: asset.downloaded_at or asset.updated_at,
        reverse=True,
    )
    return assets[0] if assets else None

def _placeholder_url(item_id: int, card_name: str) -> str:
    return f"{settings.api_prefix}/assets/placeholder?item_id={item_id}&label={card_name}"

def _proxy_remote_image_url(url: str | None) -> str | None:
    if not url:
        return None
    return f"{settings.api_prefix}/assets/proxy?url={quote(url, safe='')}"

def _cardmarket_url(value: str | None) -> str | None:
    return normalize_cardmarket_product_url(value) or (value if value and value.startswith(("http://", "https://")) else None)

def _preferred_cardmarket_locale(language: str | None, fallback_language: str | None) -> str:
    candidate = (language or fallback_language or "de").strip().lower()
    if candidate.startswith("en"):
        return "en"
    return "de"

def _remote_image_url(card_data: dict) -> str | None:
    images = card_data.get("card_images") or []
    if not images:
        return None
    first_image = images[0]
    return _proxy_remote_image_url(first_image.get("image_url_small") or first_image.get("image_url"))

def _derive_card_number(set_code: str | None) -> str | None:
    if not set_code or "-" not in set_code:
        return None
    return set_code.rsplit("-", 1)[-1] or None

def _derive_print_language(set_code: str | None) -> str:
    if not set_code or "-" not in set_code:
        return "en"

    segment = set_code.split("-", 1)[-1].upper()
    match = re.match(r"([A-Z]{2,3})", segment)
    token = match.group(1) if match else ""

    if token.startswith("EN"):
        return "en"
    if token.startswith("DE"):
        return "de"
    if token.startswith("FR"):
        return "fr"
    if token.startswith("IT"):
        return "it"
    if token.startswith("SP") or token.startswith("ES"):
        return "es"
    if token.startswith("PT"):
        return "pt"
    if token.startswith("JP"):
        return "jp"
    if token.startswith("KR"):
        return "ko"
    return "en"

def _resolve_default_remote_price(card_data: dict) -> tuple[float | None, str | None, str | None]:
    prices = card_data.get("prices", {}) or {}
    cardmarket_price = parse_positive_price(prices.get("cardmarket_price"))
    tcgplayer_price = parse_positive_price(prices.get("tcgplayer_price"))
    ebay_price = parse_positive_price(prices.get("ebay_price"))
    amazon_price = parse_positive_price(prices.get("amazon_price"))

    if cardmarket_price is not None:
        return cardmarket_price, "EUR", "ygoprodeck:cardmarket"
    if tcgplayer_price is not None:
        return tcgplayer_price, "USD", "ygoprodeck:tcgplayer"
    if ebay_price is not None:
        return ebay_price, "USD", "ygoprodeck:ebay"
    if amazon_price is not None:
        return amazon_price, "USD", "ygoprodeck:amazon"
    return None, None, None

def _build_print_label(
    set_name: str | None,
    set_code: str | None,
    rarity: str | None,
    variant_name: str | None = None,
) -> str:
    parts = [part for part in [set_name, set_code, rarity, variant_name] if part]
    return " | ".join(parts) if parts else "Unbekannter Druck"

def _normalize_lookup_value(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]", "", value.lower())

def _card_numbers_match(left: str | None, right: str | None) -> bool:
    normalized_left = _normalize_lookup_value(left)
    normalized_right = _normalize_lookup_value(right)
    if not normalized_left or not normalized_right:
        return False
    return normalized_left == normalized_right or normalized_left.endswith(normalized_right) or normalized_right.endswith(normalized_left)

def _set_code_language_neutral_signature(set_code: str | None) -> tuple[str, str] | None:
    normalized_set_code = (set_code or "").strip().upper()
    if "-" not in normalized_set_code:
        return None
    series, suffix = normalized_set_code.split("-", 1)
    match = re.match(r"([A-Z]{2,3})([A-Z0-9-]+)$", suffix)
    if not match:
        return None
    return _normalize_lookup_value(series), _normalize_lookup_value(match.group(2))

def _set_codes_match_language_neutral(left: str | None, right: str | None) -> bool:
    normalized_left = _normalize_lookup_value(left)
    normalized_right = _normalize_lookup_value(right)
    if not normalized_left or not normalized_right:
        return False
    if normalized_left == normalized_right:
        return True
    left_signature = _set_code_language_neutral_signature(left)
    right_signature = _set_code_language_neutral_signature(right)
    return bool(left_signature and right_signature and left_signature == right_signature)

def _cardmarket_variant_number(value: str | None) -> int | None:
    match = re.search(r"V\.?\s*-?\s*(\d+)", value or "", flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None

def _manual_cardmarket_resolution(
    url: str | None,
    *,
    product_name: str | None = None,
    variant_name: str | None = None,
    match_quality: str = CARDMARKET_MATCH_AMBIGUOUS,
    verified_at: datetime | None = None,
) -> CardmarketResolvedProduct | None:
    exact_url = normalize_cardmarket_product_url(url)
    if not exact_url:
        return None

    _, set_slug, product_slug = split_cardmarket_product_url(exact_url)
    variant_number = _cardmarket_variant_number(product_slug)
    resolved_variant_name = variant_name or (f"V{variant_number}" if variant_number else None)
    resolved_match_quality = match_quality if match_quality in CARDMARKET_SAFE_MATCH_QUALITIES else CARDMARKET_MATCH_AMBIGUOUS
    return CardmarketResolvedProduct(
        url=exact_url,
        set_slug=set_slug,
        product_slug=product_slug,
        product_name=product_name,
        set_name=None,
        rarity=None,
        card_number=None,
        variant_name=resolved_variant_name,
        match_quality=resolved_match_quality,
        verified_at=verified_at if resolved_match_quality in CARDMARKET_SAFE_MATCH_QUALITIES else None,
        reason="stored_cardmarket_url",
        parse_status="stored_verified" if resolved_match_quality in CARDMARKET_SAFE_MATCH_QUALITIES else "stored_unverified",
    )

def _append_local_cardmarket_reference(
    references: dict[tuple[str | None, str | None, str | None, str | None], list[dict[str, object | None]]],
    key: tuple[str | None, str | None, str | None, str | None],
    *,
    url: str | None,
    product_slug: str | None = None,
    set_slug: str | None = None,
    set_name: str | None = None,
    product_name: str | None = None,
    variant_name: str | None = None,
    match_quality: str | None = None,
    verified_at: datetime | None = None,
) -> None:
    exact_url = normalize_cardmarket_product_url(url)
    if not exact_url:
        return

    _, derived_set_slug, derived_product_slug = split_cardmarket_product_url(exact_url)
    candidate = {
        "url": exact_url,
        "product_slug": product_slug or derived_product_slug,
        "set_slug": set_slug or derived_set_slug,
        "set_name": set_name,
        "product_name": product_name,
        "variant_name": variant_name,
        "match_quality": match_quality,
        "verified_at": verified_at,
    }

    existing = references.setdefault(key, [])
    candidate_identity = (
        candidate["url"],
        candidate["product_slug"],
        candidate["variant_name"],
    )
    if any((entry.get("url"), entry.get("product_slug"), entry.get("variant_name")) == candidate_identity for entry in existing):
        return
    existing.append(candidate)

def _is_verified_cardmarket_quality(value: str | None) -> bool:
    return value in {CARDMARKET_MATCH_EXACT, CARDMARKET_MATCH_EXACT_VARIANT, CARDMARKET_MATCH_MANUAL}

def _is_safe_cardmarket_quality(value: str | None) -> bool:
    return value in CARDMARKET_SAFE_MATCH_QUALITIES

def _price_note(price_source: str | None, *, multiple_prints: bool, has_cardmarket_reference: bool) -> str:
    source_notes = {
        "ygoprodeck:set_price": "Print-spezifischer YGOPRODeck-Setpreis als Startwert.",
        "ygoprodeck:tcgplayer_set_price": "Print-spezifischer TCGPlayer-Marktpreis via YGOPRODeck als Startwert.",
        "ygoprodeck:cardmarket": (
            "Allgemeiner Cardmarket-Kartenpreis via YGOPRODeck als Fallback; "
            "dieser Wert ist nicht druckspezifisch."
        ),
        "ygoprodeck:tcgplayer": "TCGplayer-Fallback als Startwert.",
        "ygoprodeck:ebay": "eBay-Fallback als Startwert.",
        "ygoprodeck:amazon": "Amazon-Fallback als Startwert.",
        "cardmarket:public-product-page": "Preis-Trend aus der öffentlichen Cardmarket-Produktseite als Startwert.",
    }
    note_parts = [source_notes.get(price_source, "Es liegt derzeit nur ein allgemeiner Provider-Snapshot vor.")]
    if multiple_prints:
        note_parts.append("Bitte Set, Setcode und Seltenheit auswählen, damit die Druckvariante sauber feststeht.")
    note_parts.append("Zustandsspezifische Cardmarket-Preise sind im MVP ohne offizielle Cardmarket-API noch nicht automatisiert verfügbar.")
    if not has_cardmarket_reference:
        note_parts.append("Eine Cardmarket-Referenz konnte nur aus vorhandenen lokalen Mappings übernommen werden.")
    return " ".join(note_parts)

def _is_exact_inventory_duplicate_candidate(
    item: InventoryItem,
    *,
    payload: CardPayload,
) -> bool:
    if _normalize_price_value(item.purchase_price) != _normalize_price_value(payload.purchase_price):
        return False
    if _normalize_optional_text(item.notes) != _normalize_optional_text(payload.notes):
        return False
    if _normalize_tags(item.tags) != _normalize_tags(payload.tags):
        return False
    return True

async def _find_exact_inventory_duplicate(
    db: AsyncSession,
    *,
    card_print_id: int,
    payload: CardPayload,
    exclude_inventory_item_id: int | None = None,
) -> InventoryItem | None:
    stmt = (
        select(InventoryItem)
        .where(
            InventoryItem.card_print_id == card_print_id,
            InventoryItem.condition == payload.condition,
        )
        .order_by(InventoryItem.updated_at.desc())
    )
    if payload.storage_location_id is None:
        stmt = stmt.where(InventoryItem.storage_location_id.is_(None))
    else:
        stmt = stmt.where(InventoryItem.storage_location_id == payload.storage_location_id)
    if exclude_inventory_item_id:
        stmt = stmt.where(InventoryItem.id != exclude_inventory_item_id)

    result = await db.execute(stmt)
    for candidate in result.scalars().all():
        if _is_exact_inventory_duplicate_candidate(
            candidate,
            payload=payload,
        ):
            return candidate
    return None
