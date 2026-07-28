from __future__ import annotations

from datetime import datetime
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.card_metadata import apply_card_metadata, normalize_card_metadata
from app.integrations.cardmarket_links import (
    CARDMARKET_CATEGORY,
    CARDMARKET_MATCH_AMBIGUOUS,
    CARDMARKET_MATCH_FAILED,
    CARDMARKET_MATCH_MANUAL,
    normalize_cardmarket_product_url,
    split_cardmarket_product_url,
)
from app.models import Card, CardPrint, InventoryItem, PriceHistory, SourceMapping, StorageLocation
from app.schemas import CardPayload
from app.services.price_monitor import ensure_initial_price_monitor_state
from app.time_utils import utc_now

logger = logging.getLogger(__name__)

from app.services.card_common import (
    CARDMARKET_SAFE_MATCH_QUALITIES,
    DuplicateInventoryItemError,
    _cardmarket_variant_number,
    _dedupe_text_values,
    _find_exact_inventory_duplicate,
    _find_matching_card_set,
    _manual_cardmarket_resolution,
    _normalize_language_code,
    _normalize_optional_text,
    _normalize_price_value,
    _update_card_set_cardmarket_metadata,
    _validate_set_code_language,
    normalize_name,
)
from app.services.card_lookup import _resolve_exact_cardmarket_product

async def upsert_card(db: AsyncSession, payload: CardPayload, inventory_item_id: int | None = None) -> InventoryItem:
    if payload.storage_location_id:
        storage_location = await db.get(StorageLocation, payload.storage_location_id)
        if not storage_location:
            raise ValueError("Storage location not found.")

    normalized_language = _normalize_language_code(payload.language) or "de"
    _validate_set_code_language(normalized_language, payload.set_code)

    if payload.card_id:
        card = await db.get(Card, payload.card_id)
    else:
        card = await db.scalar(select(Card).where(Card.normalized_name == normalize_name(payload.name)))

    if not card:
        card = Card(name=payload.name, normalized_name=normalize_name(payload.name))
        db.add(card)

    card.name = payload.name
    card.normalized_name = normalize_name(payload.name)
    card.description = payload.effect_text
    apply_card_metadata(
        card,
        normalize_card_metadata(
            card_type=payload.card_type,
            subtype=payload.subtype,
            frame_type=payload.subtype,
            attribute=payload.attribute,
            monster_type=payload.monster_type,
            archetype=payload.archetype,
            atk=payload.atk,
            defense=payload.defense,
            level=payload.level,
            rank=payload.rank,
            link_rating=payload.link_rating,
            link_arrows=payload.link_arrows,
            pendulum_scale=payload.pendulum_scale,
            pendulum_effect=payload.pendulum_effect,
            spell_trap_type=payload.spell_trap_type,
        ),
    )

    await db.flush()

    card_print = None
    if payload.card_print_id:
        card_print = await db.get(CardPrint, payload.card_print_id)
    if not card_print:
        card_print = await db.scalar(
            select(CardPrint).where(
                CardPrint.card_id == card.id,
                CardPrint.set_code == payload.set_code,
                CardPrint.language == normalized_language,
                CardPrint.card_number == payload.card_number,
                CardPrint.rarity == payload.rarity,
            )
        )
    if not card_print:
        card_print = CardPrint(card_id=card.id, language=normalized_language)
        db.add(card_print)

    matched_card_set = await _find_matching_card_set(db, set_code=payload.set_code, set_name=payload.set_name)
    if matched_card_set:
        card_print.set_id = matched_card_set.id

    preferred_cardmarket_set_name = payload.cardmarket_set_name or card_print.cardmarket_set_name or payload.set_name
    preferred_cardmarket_product_name = payload.cardmarket_product_name or card_print.cardmarket_product_name or payload.name
    preferred_cardmarket_variant_name = payload.cardmarket_variant_name or card_print.cardmarket_variant_name
    existing_cardmarket_identity_matches_payload = (
        card_print.set_code == payload.set_code
        and _normalize_language_code(card_print.language) == normalized_language
        and card_print.card_number == payload.card_number
        and card_print.rarity == payload.rarity
    )
    existing_safe_cardmarket_url = (
        card_print.cardmarket_product_url
        if existing_cardmarket_identity_matches_payload and card_print.cardmarket_match_quality in CARDMARKET_SAFE_MATCH_QUALITIES
        else None
    )
    existing_safe_cardmarket_slug = card_print.cardmarket_product_slug if existing_safe_cardmarket_url else None
    existing_safe_cardmarket_set_slug = card_print.cardmarket_set_slug if existing_safe_cardmarket_url else None
    existing_safe_match_quality = card_print.cardmarket_match_quality if existing_safe_cardmarket_url else None
    existing_safe_verified_at = card_print.cardmarket_verified_at if existing_safe_cardmarket_url else None
    existing_safe_variant_name = card_print.cardmarket_variant_name if existing_safe_cardmarket_url else preferred_cardmarket_variant_name

    supplied_cardmarket_url = normalize_cardmarket_product_url(payload.cardmarket_product_url or payload.cardmarket_reference)
    supplied_match_quality = CARDMARKET_MATCH_AMBIGUOUS
    supplied_verified_at: datetime | None = None
    if supplied_cardmarket_url and supplied_cardmarket_url == normalize_cardmarket_product_url(existing_safe_cardmarket_url):
        supplied_match_quality = existing_safe_match_quality or CARDMARKET_MATCH_AMBIGUOUS
        supplied_verified_at = existing_safe_verified_at

    manual_cardmarket_resolution = _manual_cardmarket_resolution(
        supplied_cardmarket_url,
        product_name=preferred_cardmarket_product_name,
        variant_name=preferred_cardmarket_variant_name,
        match_quality=supplied_match_quality,
        verified_at=supplied_verified_at,
    )
    if manual_cardmarket_resolution:
        _update_card_set_cardmarket_metadata(
            matched_card_set,
            resolution=manual_cardmarket_resolution,
            alias_names=_dedupe_text_values(
                [
                    payload.set_name,
                    payload.cardmarket_set_name,
                    matched_card_set.name if matched_card_set else None,
                ]
            ),
        )
        if matched_card_set:
            preferred_cardmarket_set_name = (
                matched_card_set.cardmarket_set_name
                or matched_card_set.name
                or preferred_cardmarket_set_name
            )
    cardmarket_resolution = manual_cardmarket_resolution or await _resolve_exact_cardmarket_product(
        db,
        card=card,
        card_print=card_print,
        payload=payload,
        normalized_language=normalized_language,
        matched_card_set=matched_card_set,
    )
    has_verified_cardmarket_product = cardmarket_resolution.match_quality in CARDMARKET_SAFE_MATCH_QUALITIES and bool(cardmarket_resolution.url)
    has_unverified_cardmarket_candidate = cardmarket_resolution.match_quality == CARDMARKET_MATCH_AMBIGUOUS and bool(cardmarket_resolution.url)
    store_unverified_cardmarket_candidate = has_unverified_cardmarket_candidate and not existing_safe_cardmarket_url
    use_cardmarket_resolution = has_verified_cardmarket_product or store_unverified_cardmarket_candidate

    card_print.language = normalized_language
    card_print.set_name = payload.set_name
    card_print.set_code = payload.set_code
    card_print.card_number = payload.card_number
    card_print.rarity = payload.rarity
    card_print.rarity_code = payload.rarity_code
    card_print.edition = payload.edition
    card_print.release_date = payload.release_date
    card_print.cardmarket_product_url = cardmarket_resolution.url if use_cardmarket_resolution else existing_safe_cardmarket_url
    card_print.cardmarket_product_slug = (
        cardmarket_resolution.product_slug
        if use_cardmarket_resolution
        else existing_safe_cardmarket_slug
    )
    card_print.cardmarket_set_slug = (
        cardmarket_resolution.set_slug
        if use_cardmarket_resolution
        else existing_safe_cardmarket_set_slug or payload.cardmarket_set_slug
    )
    card_print.cardmarket_set_name = (
        cardmarket_resolution.set_name
        if use_cardmarket_resolution and cardmarket_resolution.set_name
        else preferred_cardmarket_set_name
    )
    card_print.cardmarket_product_name = (
        cardmarket_resolution.product_name
        if use_cardmarket_resolution and cardmarket_resolution.product_name
        else preferred_cardmarket_product_name
    )
    card_print.cardmarket_variant_name = (
        cardmarket_resolution.variant_name
        if use_cardmarket_resolution
        else existing_safe_variant_name
    )
    card_print.cardmarket_category = payload.cardmarket_category or CARDMARKET_CATEGORY
    card_print.cardmarket_match_quality = (
        cardmarket_resolution.match_quality
        if use_cardmarket_resolution
        else existing_safe_match_quality or cardmarket_resolution.match_quality
    )
    card_print.cardmarket_verified_at = (
        cardmarket_resolution.verified_at
        if has_verified_cardmarket_product
        else existing_safe_verified_at
    )
    card_print.cardmarket_expected_rarity = payload.cardmarket_expected_rarity or payload.rarity
    card_print.cardmarket_expected_language = payload.cardmarket_expected_language or normalized_language
    card_print.cardmarket_expected_set_name = payload.cardmarket_expected_set_name or payload.set_name

    if store_unverified_cardmarket_candidate:
        logger.warning(
            "Stored unverified Cardmarket candidate for card '%s' (%s): %s",
            card.name,
            payload.set_code,
            cardmarket_resolution.url,
        )
    elif not has_verified_cardmarket_product:
        logger.warning(
            "Cardmarket product could not be verified for card '%s' (%s): %s",
            card.name,
            payload.set_code,
            cardmarket_resolution.reason,
        )

    await db.flush()

    resolved_cardmarket_reference = card_print.cardmarket_product_url or normalize_cardmarket_product_url(payload.cardmarket_reference)

    duplicate_item = await _find_exact_inventory_duplicate(
        db,
        card_print_id=card_print.id,
        payload=payload,
        exclude_inventory_item_id=inventory_item_id,
    )
    if duplicate_item and inventory_item_id is None:
        if payload.increment_existing_quantity_on_duplicate:
            duplicate_item.quantity = int(duplicate_item.quantity or 0) + payload.quantity
            if not duplicate_item.cardmarket_reference and resolved_cardmarket_reference:
                duplicate_item.cardmarket_reference = resolved_cardmarket_reference
            await db.flush()
            return duplicate_item
        raise DuplicateInventoryItemError(
            existing_item_id=duplicate_item.id,
            existing_quantity=int(duplicate_item.quantity or 0),
            increment_by=payload.quantity,
            card_name=card.name,
            set_code=card_print.set_code,
            language=card_print.language,
            condition=payload.condition,
        )

    if inventory_item_id:
        item = await db.get(InventoryItem, inventory_item_id)
        if not item:
            raise ValueError("Card not found.")
    else:
        item = InventoryItem(card_print_id=card_print.id)
        db.add(item)

    previous_market_price = item.current_market_price
    previous_price_currency = item.current_price_currency
    price_changed = (
        inventory_item_id is None
        or _normalize_price_value(previous_market_price) != _normalize_price_value(payload.current_market_price)
        or (previous_price_currency or "").upper() != (payload.current_price_currency or "").upper()
    )

    item.card_print_id = card_print.id
    item.storage_location_id = payload.storage_location_id
    item.condition = payload.condition
    item.quantity = payload.quantity
    item.purchase_price = payload.purchase_price
    item.current_market_price = payload.current_market_price
    item.current_price_currency = payload.current_price_currency
    item.cardmarket_reference = resolved_cardmarket_reference
    item.notes = payload.notes
    item.tags = payload.tags
    if payload.current_market_price is not None and price_changed:
        price_source = _normalize_optional_text(payload.current_price_source) or "manual"
        price_match_quality = _normalize_optional_text(payload.current_price_match_quality)
        if not price_match_quality and price_source == "manual":
            price_match_quality = "manual"
        price_note = _normalize_optional_text(payload.current_price_note)
        if not price_note and price_source == "manual":
            price_note = "Manuell gepflegter Marktpreis."

        item.last_priced_at = utc_now()
        item.last_price_source = price_source
        item.last_price_match_quality = price_match_quality
        item.last_price_note = price_note
    elif payload.current_market_price is None and price_changed:
        item.last_priced_at = None
        item.last_price_source = None
        item.last_price_match_quality = None
        item.last_price_note = None

    await db.flush()
    if inventory_item_id is None:
        await ensure_initial_price_monitor_state(db, item, now=utc_now())

    if payload.current_market_price is not None and price_changed:
        db.add(
            PriceHistory(
                inventory_item_id=item.id,
                card_print_id=card_print.id,
                provider_key=item.last_price_source or "manual",
                metric="market",
                currency=item.current_price_currency,
                price=payload.current_market_price,
                payload={
                    "source": item.last_price_source or "manual",
                    "match_quality": item.last_price_match_quality,
                    "note": item.last_price_note,
                    "set_code": card_print.set_code,
                    "card_number": card_print.card_number,
                    "rarity": card_print.rarity,
                    "language": card_print.language,
                    "source_url": resolved_cardmarket_reference or payload.cardmarket_reference,
                    "cardmarket_product_url": card_print.cardmarket_product_url or payload.cardmarket_product_url,
                    "source_product_id": card_print.cardmarket_product_slug or payload.external_ids.get("cardmarket"),
                },
            )
        )

    existing_mappings_result = await db.execute(
        select(SourceMapping).where(SourceMapping.target_type == "card_print", SourceMapping.target_id == card_print.id)
    )
    existing_mappings = {mapping.provider_key: mapping for mapping in existing_mappings_result.scalars().all()}
    for provider_key, external_id in payload.external_ids.items():
        mapping = existing_mappings.get(provider_key)
        if not mapping:
            mapping = SourceMapping(target_type="card_print", target_id=card_print.id, provider_key=provider_key, external_id=external_id)
            db.add(mapping)
            existing_mappings[provider_key] = mapping
        mapping.external_id = external_id
        if provider_key == "cardmarket":
            mapping.external_url = (
                normalize_cardmarket_product_url(card_print.cardmarket_product_url)
                or normalize_cardmarket_product_url(payload.cardmarket_product_url)
                or normalize_cardmarket_product_url(payload.cardmarket_reference)
                or normalize_cardmarket_product_url(external_id)
                or card_print.cardmarket_product_url
                or payload.cardmarket_product_url
                or payload.cardmarket_reference
            )
        mapping.last_synced_at = utc_now()

    if card_print.cardmarket_product_url and card_print.cardmarket_match_quality in CARDMARKET_SAFE_MATCH_QUALITIES:
        mapping = existing_mappings.get("cardmarket")
        if not mapping:
            mapping = SourceMapping(
                target_type="card_print",
                target_id=card_print.id,
                provider_key="cardmarket",
                external_id=card_print.cardmarket_product_slug or card_print.cardmarket_product_url,
            )
            db.add(mapping)
            existing_mappings["cardmarket"] = mapping
        mapping.external_id = card_print.cardmarket_product_slug or card_print.cardmarket_product_url
        mapping.external_url = card_print.cardmarket_product_url
        mapping.payload = {
            "set_slug": card_print.cardmarket_set_slug,
            "product_slug": card_print.cardmarket_product_slug,
            "match_quality": card_print.cardmarket_match_quality,
        }
        mapping.last_synced_at = utc_now()

    await db.flush()
    return item

async def delete_card(db: AsyncSession, inventory_item_id: int) -> None:
    item = await db.get(InventoryItem, inventory_item_id)
    if not item:
        raise ValueError("Card not found.")
    await db.delete(item)

async def update_cardmarket_link(
    db: AsyncSession,
    inventory_item_id: int,
    url: str | None,
    *,
    confirmed: bool = False,
) -> InventoryItem:
    item = await db.get(
        InventoryItem,
        inventory_item_id,
        options=[
            selectinload(InventoryItem.card_print).selectinload(CardPrint.card),
        ],
    )
    if not item:
        raise ValueError("Card not found.")

    normalized_url = normalize_cardmarket_product_url(url)
    if url and not normalized_url:
        raise ValueError("Bitte einen gültigen Cardmarket-Produktlink eintragen.")

    card_print = item.card_print
    if normalized_url:
        stored_url = normalize_cardmarket_product_url(card_print.cardmarket_product_url)
        unchanged_safe_link = normalized_url == stored_url and card_print.cardmarket_match_quality in CARDMARKET_SAFE_MATCH_QUALITIES
        _, set_slug, product_slug = split_cardmarket_product_url(normalized_url)
        variant_number = _cardmarket_variant_number(product_slug)
        resolved_variant_name = card_print.cardmarket_variant_name or (f"V{variant_number}" if variant_number else None)
        match_quality = (
            CARDMARKET_MATCH_MANUAL
            if confirmed
            else card_print.cardmarket_match_quality
            if unchanged_safe_link
            else CARDMARKET_MATCH_AMBIGUOUS
        )
        verified_at = (
            utc_now()
            if confirmed
            else card_print.cardmarket_verified_at
            if unchanged_safe_link
            else None
        )
        matched_card_set = await _find_matching_card_set(
            db,
            set_code=card_print.set_code,
            set_name=card_print.set_name,
        )
        manual_resolution = _manual_cardmarket_resolution(
            normalized_url,
            product_name=card_print.cardmarket_product_name or card_print.card.name,
            variant_name=resolved_variant_name,
            match_quality=match_quality,
            verified_at=verified_at,
        )
        if matched_card_set and manual_resolution and match_quality in CARDMARKET_SAFE_MATCH_QUALITIES:
            card_print.set_id = matched_card_set.id
            _update_card_set_cardmarket_metadata(
                matched_card_set,
                resolution=manual_resolution,
                alias_names=_dedupe_text_values(
                    [
                        card_print.set_name,
                        card_print.cardmarket_set_name,
                        matched_card_set.name,
                    ]
                ),
            )
            card_print.cardmarket_set_name = matched_card_set.cardmarket_set_name or matched_card_set.name
        item.cardmarket_reference = normalized_url
        card_print.cardmarket_product_url = normalized_url
        card_print.cardmarket_set_slug = set_slug or card_print.cardmarket_set_slug
        card_print.cardmarket_product_slug = product_slug or card_print.cardmarket_product_slug
        card_print.cardmarket_variant_name = resolved_variant_name
        card_print.cardmarket_category = card_print.cardmarket_category or CARDMARKET_CATEGORY
        card_print.cardmarket_match_quality = match_quality
        card_print.cardmarket_verified_at = verified_at
    else:
        item.cardmarket_reference = None
        card_print.cardmarket_product_url = None
        card_print.cardmarket_product_slug = None
        card_print.cardmarket_variant_name = None
        card_print.cardmarket_match_quality = CARDMARKET_MATCH_FAILED
        card_print.cardmarket_verified_at = None

    existing_mappings_result = await db.execute(
        select(SourceMapping).where(
            SourceMapping.target_type == "card_print",
            SourceMapping.target_id == card_print.id,
            SourceMapping.provider_key == "cardmarket",
        )
    )
    mapping = existing_mappings_result.scalars().first()
    if normalized_url:
        if not mapping:
            mapping = SourceMapping(
                target_type="card_print",
                target_id=card_print.id,
                provider_key="cardmarket",
                external_id=card_print.cardmarket_product_slug or normalized_url,
            )
            db.add(mapping)
        mapping.external_id = card_print.cardmarket_product_slug or normalized_url
        mapping.external_url = normalized_url
        mapping.payload = {
            "set_slug": card_print.cardmarket_set_slug,
            "product_slug": card_print.cardmarket_product_slug,
            "match_quality": card_print.cardmarket_match_quality,
            "source": "manual_confirmation" if confirmed else "manual_edit",
            "confirmed_at": card_print.cardmarket_verified_at.isoformat() if card_print.cardmarket_verified_at else None,
        }
        mapping.last_synced_at = utc_now()
    elif mapping:
        await db.delete(mapping)

    await db.flush()
    return item
