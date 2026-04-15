from __future__ import annotations

from datetime import datetime, timedelta
import logging
import re
from urllib.parse import quote

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.integrations.card_data import get_card_data_provider
from app.models import Card, CardPrint, CardSet, ImageAsset, InventoryItem, SourceMapping
from app.schemas import CardSetSummary, SetCardRow, SetCardsResponse
from app.services.app_settings import get_app_settings
from app.services.currency import convert_amount

logger = logging.getLogger(__name__)


def normalize_name(value: str) -> str:
    return " ".join(value.lower().split())


def _parse_float(value: str | float | int | None) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_int(value: object) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


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


def _placeholder_url(set_id: int, card_name: str) -> str:
    return f"{settings.api_prefix}/assets/placeholder?item_id={set_id}&label={card_name}"


def _proxy_remote_image_url(url: str | None) -> str | None:
    if not url:
        return None
    return f"{settings.api_prefix}/assets/proxy?url={quote(url, safe='')}"


def _first_image(card_print: CardPrint) -> ImageAsset | None:
    assets = sorted(
        [asset for asset in card_print.image_assets if asset.status == "downloaded" and asset.local_path],
        key=lambda asset: asset.downloaded_at or asset.updated_at,
        reverse=True,
    )
    return assets[0] if assets else None


def _natural_sort_key(value: str | None) -> tuple:
    text = value or ""
    parts = re.split(r"(\d+)", text.upper())
    return tuple(int(part) if part.isdigit() else part for part in parts)


def _matches_card_set(remote_print: dict, card_set: CardSet) -> bool:
    remote_set_code = (remote_print.get("set_code") or "").upper()
    catalog_set_code = (card_set.set_code or "").upper()
    if catalog_set_code and remote_set_code:
        if remote_set_code == catalog_set_code or remote_set_code.startswith(f"{catalog_set_code}-"):
            return True

    remote_set_name = remote_print.get("set_name")
    return bool(remote_set_name and normalize_name(remote_set_name) == card_set.normalized_name)


def _select_matching_remote_prints(remote_card: dict, card_set: CardSet) -> list[dict]:
    return [entry for entry in (remote_card.get("card_sets") or []) if _matches_card_set(entry, card_set)]


def _build_completeness_warning(card_set: CardSet) -> tuple[bool, str | None]:
    expected_card_count = _expected_card_count(card_set)
    loaded_card_count = int(card_set.loaded_card_count or 0)
    loaded_print_count = int(card_set.loaded_print_count or 0)

    if expected_card_count <= 0:
        return True, card_set.sync_warning

    if loaded_card_count < expected_card_count:
        return (
            False,
            card_set.sync_warning
            or (
                f"Set moeglicherweise unvollstaendig: lokal {loaded_card_count} von erwarteten "
                f"{expected_card_count} Karten und {loaded_print_count} Prints."
            ),
        )

    return True, card_set.sync_warning


def _expected_card_count(card_set: CardSet) -> int:
    payload_count = _parse_int((card_set.source_payload or {}).get("num_of_cards")) or 0
    direct_count = int(card_set.card_count or 0)
    return max(payload_count, direct_count)


async def _local_set_counts(db: AsyncSession, set_id: int) -> tuple[int, int]:
    row = await db.execute(
        select(
            func.count(func.distinct(CardPrint.card_id)),
            func.count(CardPrint.id),
        ).where(CardPrint.set_id == set_id)
    )
    loaded_card_count, loaded_print_count = row.one()
    return int(loaded_card_count or 0), int(loaded_print_count or 0)


async def _find_card_by_external_id(db: AsyncSession, provider_key: str, external_id: str) -> Card | None:
    result = await db.execute(
        select(Card)
        .join(SourceMapping, and_(SourceMapping.target_type == "card", SourceMapping.target_id == Card.id))
        .where(SourceMapping.provider_key == provider_key, SourceMapping.external_id == external_id)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _ensure_card_mapping(db: AsyncSession, card: Card, provider_key: str, remote_card: dict) -> None:
    result = await db.execute(
        select(SourceMapping).where(
            SourceMapping.target_type == "card",
            SourceMapping.target_id == card.id,
            SourceMapping.provider_key == provider_key,
        )
    )
    mapping = result.scalar_one_or_none()
    if not mapping:
        mapping = SourceMapping(target_type="card", target_id=card.id, provider_key=provider_key, external_id=remote_card["external_id"])
        db.add(mapping)
    mapping.external_id = remote_card["external_id"]
    mapping.external_url = f"https://db.ygoprodeck.com/card/?search={remote_card['external_id']}"
    mapping.payload = {"name": remote_card["name"]}
    mapping.last_synced_at = datetime.utcnow()


async def _ensure_print_mapping(db: AsyncSession, card_print: CardPrint, provider_key: str, remote_card: dict, remote_print: dict) -> None:
    result = await db.execute(
        select(SourceMapping).where(
            SourceMapping.target_type == "card_print",
            SourceMapping.target_id == card_print.id,
            SourceMapping.provider_key == provider_key,
        )
    )
    mapping = result.scalar_one_or_none()
    if not mapping:
        mapping = SourceMapping(target_type="card_print", target_id=card_print.id, provider_key=provider_key, external_id=remote_card["external_id"])
        db.add(mapping)
    mapping.external_id = remote_card["external_id"]
    mapping.external_url = f"https://db.ygoprodeck.com/card/?search={remote_card['external_id']}"
    mapping.payload = {
        "set_name": remote_print.get("set_name"),
        "set_code": remote_print.get("set_code"),
        "set_rarity": remote_print.get("set_rarity"),
        "set_rarity_code": remote_print.get("set_rarity_code"),
        "set_price": remote_print.get("set_price"),
    }
    mapping.last_synced_at = datetime.utcnow()


def _serialize_card_set(card_set: CardSet) -> CardSetSummary:
    is_complete, warning = _build_completeness_warning(card_set)
    expected_card_count = _expected_card_count(card_set)
    loaded_card_count = int(card_set.loaded_card_count or 0)
    loaded_print_count = int(card_set.loaded_print_count or 0)
    return CardSetSummary(
        id=card_set.id,
        provider_key=card_set.provider_key,
        name=card_set.name,
        set_code=card_set.set_code,
        card_count=expected_card_count,
        expected_card_count=expected_card_count,
        loaded_card_count=loaded_card_count,
        loaded_print_count=loaded_print_count,
        is_complete=is_complete,
        warning=warning,
        release_date=card_set.release_date,
        last_synced_at=card_set.last_synced_at,
    )


async def sync_card_sets_catalog(db: AsyncSession, *, force: bool = False) -> None:
    latest_sync = await db.scalar(select(func.max(CardSet.catalog_synced_at)).where(CardSet.provider_key == "ygoprodeck"))
    if latest_sync and not force and latest_sync >= datetime.utcnow() - timedelta(hours=24):
        return

    provider = get_card_data_provider()
    remote_sets = await provider.fetch_sets()
    if not remote_sets:
        logger.warning("Set catalog sync returned no remote sets.")
        return

    existing_result = await db.execute(select(CardSet).where(CardSet.provider_key == provider.provider_key))
    existing_by_name = {card_set.normalized_name: card_set for card_set in existing_result.scalars().all()}
    synced_at = datetime.utcnow()

    for remote_set in remote_sets:
        normalized_name = normalize_name(remote_set["name"])
        card_set = existing_by_name.get(normalized_name)
        if not card_set:
            card_set = CardSet(provider_key=provider.provider_key, name=remote_set["name"], normalized_name=normalized_name)
            db.add(card_set)
            existing_by_name[normalized_name] = card_set
        card_set.name = remote_set["name"]
        card_set.normalized_name = normalized_name
        card_set.set_code = remote_set.get("set_code")
        card_set.card_count = remote_set.get("card_count")
        card_set.release_date = remote_set.get("release_date")
        card_set.source_payload = remote_set.get("payload")
        card_set.catalog_synced_at = synced_at
        card_set.last_synced_at = synced_at

    await db.flush()


async def list_card_sets(db: AsyncSession, *, q: str | None = None, limit: int = 30) -> list[CardSetSummary]:
    await sync_card_sets_catalog(db)
    stmt = select(CardSet).where(CardSet.provider_key == "ygoprodeck")
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(CardSet.name.ilike(pattern), CardSet.set_code.ilike(pattern)))
    stmt = stmt.order_by(CardSet.name.asc()).limit(limit)
    result = await db.execute(stmt)
    return [_serialize_card_set(card_set) for card_set in result.scalars().all()]


async def _upsert_card_set_card(db: AsyncSession, card_set: CardSet, remote_card: dict, *, provider_key: str) -> None:
    card = await _find_card_by_external_id(db, provider_key, remote_card["external_id"])
    if not card:
        card = await db.scalar(select(Card).where(Card.normalized_name == normalize_name(remote_card["name"])))

    if not card:
        card = Card(name=remote_card["name"], normalized_name=normalize_name(remote_card["name"]))
        db.add(card)
        await db.flush()

    card.name = remote_card["name"]
    card.normalized_name = normalize_name(remote_card["name"])
    card.card_type = remote_card.get("card_type")
    card.subtype = remote_card.get("subtype")
    card.frame_type = remote_card.get("frame_type")
    card.description = remote_card.get("description")
    card.attribute = remote_card.get("attribute")
    card.monster_type = remote_card.get("monster_type")
    card.archetype = remote_card.get("archetype")
    card.atk = remote_card.get("atk")
    card.defense = remote_card.get("defense")
    card.level = remote_card.get("level")
    card.rank = remote_card.get("rank")
    card.link_rating = remote_card.get("link_rating")
    card.link_arrows = remote_card.get("link_arrows")
    card.pendulum_scale = remote_card.get("pendulum_scale")
    card.pendulum_effect = remote_card.get("pendulum_effect")
    card.spell_trap_type = remote_card.get("spell_trap_type")
    card.limitations = remote_card.get("limitations")
    card.source_payload = remote_card.get("payload")
    card.last_synced_at = datetime.utcnow()

    await _ensure_card_mapping(db, card, provider_key, remote_card)
    await db.flush()

    remote_prints = _select_matching_remote_prints(remote_card, card_set)
    image_payload = (remote_card.get("card_images") or [{}])[0]
    remote_image_url = image_payload.get("image_url")

    for remote_print in remote_prints:
        set_code = remote_print.get("set_code")
        card_print = await db.scalar(
            select(CardPrint).where(
                CardPrint.card_id == card.id,
                CardPrint.set_id == card_set.id,
                CardPrint.set_code == set_code,
                CardPrint.rarity == remote_print.get("set_rarity"),
            )
        )
        if not card_print:
            card_print = CardPrint(card_id=card.id, set_id=card_set.id)
            db.add(card_print)

        card_print.set_id = card_set.id
        card_print.language = _derive_print_language(set_code)
        card_print.set_name = remote_print.get("set_name") or card_set.name
        card_print.set_code = set_code
        card_print.card_number = _derive_card_number(set_code)
        card_print.rarity = remote_print.get("set_rarity")
        card_print.rarity_code = remote_print.get("set_rarity_code")
        card_print.release_date = card_set.release_date
        card_print.remote_image_url = remote_image_url

        await db.flush()
        await _ensure_print_mapping(db, card_print, provider_key, remote_card, remote_print)


async def sync_card_set_cards(db: AsyncSession, card_set: CardSet, *, language: str = "de", force: bool = False) -> None:
    expected_card_count = _expected_card_count(card_set)
    if expected_card_count:
        card_set.card_count = expected_card_count
    local_loaded_card_count, local_loaded_print_count = await _local_set_counts(db, card_set.id)
    card_set.loaded_card_count = local_loaded_card_count
    card_set.loaded_print_count = local_loaded_print_count

    is_complete, warning = _build_completeness_warning(card_set)
    is_stale = not card_set.cards_synced_at or card_set.cards_synced_at < datetime.utcnow() - timedelta(days=7)
    needs_sync = force or not local_loaded_print_count or not is_complete or is_stale

    if not needs_sync:
        card_set.sync_warning = warning
        return

    provider = get_card_data_provider()
    remote_cards = await provider.fetch_cards_for_set(card_set.name)
    if not remote_cards:
        card_set.sync_warning = f"Provider lieferte fuer {card_set.name} keine Karten."
        logger.warning("Set sync returned no cards for %s (%s).", card_set.name, card_set.set_code)
        return

    if expected_card_count and len(remote_cards) < expected_card_count:
        logger.warning(
            "Canonical set import for %s returned only %s of expected %s cards. Requested language %s will be ignored for completeness.",
            card_set.name,
            len(remote_cards),
            expected_card_count,
            language,
        )

    for remote_card in remote_cards:
        await _upsert_card_set_card(db, card_set, remote_card, provider_key=provider.provider_key)

    local_loaded_card_count, local_loaded_print_count = await _local_set_counts(db, card_set.id)
    card_set.loaded_card_count = local_loaded_card_count
    card_set.loaded_print_count = local_loaded_print_count
    card_set.cards_synced_at = datetime.utcnow()
    card_set.last_synced_at = card_set.cards_synced_at

    is_complete = not expected_card_count or local_loaded_card_count >= expected_card_count
    if not is_complete:
        card_set.sync_warning = (
            f"Set moeglicherweise unvollstaendig: lokal {local_loaded_card_count} von erwarteten "
            f"{expected_card_count} Karten nach dem Sync."
        )
        logger.warning(
            "Set %s (%s) remains incomplete after sync: %s of %s cards, %s prints.",
            card_set.name,
            card_set.set_code,
            local_loaded_card_count,
            expected_card_count,
            local_loaded_print_count,
        )
    else:
        card_set.sync_warning = None

    await db.flush()


async def get_card_set_cards(db: AsyncSession, set_id: int, *, language: str = "de") -> SetCardsResponse:
    app_settings = await get_app_settings(db)
    display_currency = app_settings.preferred_currency
    await sync_card_sets_catalog(db)
    card_set = await db.get(CardSet, set_id)
    if not card_set:
        raise ValueError("Set not found.")

    await sync_card_set_cards(db, card_set, language=language)

    set_print_ids_stmt = select(CardPrint.id).where(CardPrint.set_id == card_set.id)
    inventory_totals_result = await db.execute(
        select(
            InventoryItem.card_print_id,
            func.coalesce(func.sum(InventoryItem.quantity), 0),
            func.max(InventoryItem.current_market_price),
            func.max(InventoryItem.current_price_currency),
        )
        .where(InventoryItem.card_print_id.in_(set_print_ids_stmt))
        .group_by(InventoryItem.card_print_id)
    )
    inventory_totals = {
        row[0]: {
            "quantity": int(row[1] or 0),
            "price": float(row[2]) if row[2] is not None else None,
            "currency": row[3],
        }
        for row in inventory_totals_result.all()
    }

    result = await db.execute(
        select(CardPrint)
        .where(CardPrint.set_id == card_set.id)
        .options(
            selectinload(CardPrint.card),
            selectinload(CardPrint.image_assets),
        )
    )
    prints = result.scalars().unique().all()
    print_ids = [card_print.id for card_print in prints]

    mapping_result = await db.execute(
        select(SourceMapping).where(
            SourceMapping.target_type == "card_print",
            SourceMapping.provider_key == "ygoprodeck",
            SourceMapping.target_id.in_(print_ids or [-1]),
        )
    )
    mappings = {mapping.target_id: mapping for mapping in mapping_result.scalars().all()}

    duplicate_signatures: set[tuple[str, str, str]] = set()
    seen_signatures: set[tuple[str, str, str]] = set()
    items: list[SetCardRow] = []
    for card_print in prints:
        image_asset = _first_image(card_print)
        if image_asset and image_asset.local_path:
            image_url = f"/media/{image_asset.local_path}"
        elif card_print.remote_image_url:
            image_url = _proxy_remote_image_url(card_print.remote_image_url) or _placeholder_url(card_set.id, card_print.card.name)
        else:
            image_url = _placeholder_url(card_set.id, card_print.card.name)

        inventory_totals_row = inventory_totals.get(card_print.id, {})
        mapping = mappings.get(card_print.id)
        mapping_price = _parse_float((mapping.payload or {}).get("set_price")) if mapping and mapping.payload else None
        mapping_currency = "USD" if mapping_price is not None else None
        converted_inventory_price = None
        if inventory_totals_row.get("price") is not None:
            converted = await convert_amount(inventory_totals_row.get("price"), inventory_totals_row.get("currency"), display_currency)
            converted_inventory_price = float(converted) if converted is not None else None
        converted_mapping_price = None
        if mapping_price is not None:
            converted = await convert_amount(mapping_price, mapping_currency, display_currency)
            converted_mapping_price = float(converted) if converted is not None else None

        signature = (
            mapping.external_id if mapping else str(card_print.card_id),
            card_print.set_code or "",
            card_print.rarity or "",
        )
        if signature in seen_signatures:
            duplicate_signatures.add(signature)
        seen_signatures.add(signature)

        items.append(
            SetCardRow(
                card_print_id=card_print.id,
                card_id=card_print.card_id,
                name=card_print.card.name,
                language=card_print.language,
                card_number=card_print.card_number,
                set_code=card_print.set_code,
                rarity=card_print.rarity,
                card_type=card_print.card.card_type,
                image_url=image_url,
                existing_quantity=int(inventory_totals_row.get("quantity", 0)),
                current_market_price=converted_inventory_price if converted_inventory_price is not None else converted_mapping_price,
                current_price_currency=display_currency if (converted_inventory_price is not None or converted_mapping_price is not None) else inventory_totals_row.get("currency") or mapping_currency,
            )
        )

    if duplicate_signatures:
        duplicate_message = f"Lokale Dubletten erkannt: {len(duplicate_signatures)} Print-Signaturen erscheinen mehrfach."
        logger.warning("Duplicate local set print signatures for %s (%s): %s", card_set.name, card_set.set_code, sorted(duplicate_signatures))
        card_set.sync_warning = f"{card_set.sync_warning} {duplicate_message}".strip() if card_set.sync_warning else duplicate_message

    card_set.loaded_print_count = len(items)
    await db.flush()

    items.sort(key=lambda item: (_natural_sort_key(item.card_number or item.set_code), item.rarity or "", item.name))
    return SetCardsResponse(set=_serialize_card_set(card_set), items=items)
