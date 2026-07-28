from __future__ import annotations

from decimal import Decimal
import logging

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.integrations.cardmarket_links import (
    CARDMARKET_MATCH_AMBIGUOUS,
    CARDMARKET_MATCH_EXACT,
    CARDMARKET_MATCH_EXACT_VARIANT,
    CARDMARKET_MATCH_FAILED,
    CARDMARKET_MATCH_MANUAL,
    CARDMARKET_MATCH_SET_NAME,
    normalize_cardmarket_product_url,
    resolve_cardmarket_product_url,
)
from app.integrations.price_values import parse_positive_price
from app.models import Card, CardPrint, ImageAsset, InventoryItem, PriceHistory, SourceMapping, StorageLocation, SyncJob
from app.schemas import (
    CardDetail,
    CardFilterOptions,
    PricingStatus,
    CardSummary,
    PriceHistoryPoint,
    SourceMappingResponse,
)
from app.services.price_monitor import build_price_monitor_status
from app.services.app_settings import get_app_settings
from app.services.currency import convert_amount
from app.services.sync import _extract_price_targets, serialize_sync_job

logger = logging.getLogger(__name__)

from app.services.card_common import (
    CARDMARKET_SAFE_MATCH_QUALITIES,
    _first_image,
    _is_safe_cardmarket_quality,
    _placeholder_url,
    _preferred_cardmarket_locale,
    _proxy_remote_image_url,
)

def _latest_price_entry(item: InventoryItem) -> PriceHistory | None:
    valid_history = [entry for entry in item.price_history if parse_positive_price(entry.price) is not None]
    if not valid_history:
        return None
    return max(valid_history, key=lambda entry: entry.captured_at)

def _group_source_mappings(mappings: list[SourceMapping]) -> dict[tuple[str, int], list[SourceMapping]]:
    grouped: dict[tuple[str, int], list[SourceMapping]] = {}
    for mapping in mappings:
        grouped.setdefault((mapping.target_type, mapping.target_id), []).append(mapping)
    return grouped

def _mappings_for_item(grouped_mappings: dict[tuple[str, int], list[SourceMapping]], item: InventoryItem) -> list[SourceMapping]:
    return [
        *grouped_mappings.get(("card_print", item.card_print_id), []),
        *grouped_mappings.get(("card", item.card_print.card.id), []),
    ]

async def _load_source_mappings(db: AsyncSession, items: list[InventoryItem]) -> dict[tuple[str, int], list[SourceMapping]]:
    if not items:
        return {}

    card_ids = sorted({item.card_print.card.id for item in items})
    card_print_ids = sorted({item.card_print_id for item in items})
    result = await db.execute(
        select(SourceMapping).where(
            or_(
                and_(SourceMapping.target_type == "card", SourceMapping.target_id.in_(card_ids)),
                and_(SourceMapping.target_type == "card_print", SourceMapping.target_id.in_(card_print_ids)),
            )
        )
    )
    return _group_source_mappings(result.scalars().all())

async def _load_active_price_jobs(db: AsyncSession, items: list[InventoryItem]) -> dict[int, SyncJob]:
    if not items:
        return {}

    result = await db.execute(
        select(SyncJob)
        .where(
            SyncJob.job_type == "price_update",
            SyncJob.status.in_(["pending", "running"]),
        )
        .order_by(SyncJob.created_at.desc())
    )
    jobs = result.scalars().all()
    if not jobs:
        return {}

    item_ids = {item.id for item in items}
    card_print_ids_for_items = {item.card_print_id for item in items}
    item_ids_by_print_id: dict[int, list[int]] = {}
    for item in items:
        item_ids_by_print_id.setdefault(item.card_print_id, []).append(item.id)
    candidates_by_item_id: dict[int, list[tuple[tuple[int, int, int, int], SyncJob]]] = {}

    for job in jobs:
        inventory_item_ids, card_print_ids = _extract_price_targets(job.payload)
        has_targets = bool(inventory_item_ids or card_print_ids)
        status_rank = 0 if job.status == "running" else 1
        priority_rank = -(job.priority or 0)
        recency_rank = -job.id

        if has_targets:
            target_item_ids = item_ids.intersection(inventory_item_ids)
            for card_print_id in card_print_ids_for_items.intersection(card_print_ids):
                target_item_ids.update(item_ids_by_print_id.get(card_print_id, []))
            candidate_key = (0, status_rank, priority_rank, recency_rank)
        elif job.status == "running":
            target_item_ids = item_ids
            candidate_key = (2, status_rank, priority_rank, recency_rank)
        else:
            continue

        for item_id in target_item_ids:
            candidates_by_item_id.setdefault(item_id, []).append((candidate_key, job))

    job_map: dict[int, SyncJob] = {}
    for item_id, candidates in candidates_by_item_id.items():
        job_map[item_id] = min(candidates, key=lambda candidate: candidate[0])[1]
    return job_map

async def _load_exact_cardmarket_references(
    db: AsyncSession,
    *,
    normalized_name: str,
    language: str,
) -> dict[tuple[str | None, str | None, str | None, str | None], str]:
    exact_references: dict[tuple[str | None, str | None, str | None, str | None], str] = {}

    card_print_rows = await db.execute(
        select(
            CardPrint.set_code,
            CardPrint.card_number,
            CardPrint.rarity,
            CardPrint.language,
            CardPrint.cardmarket_product_url,
            CardPrint.cardmarket_product_slug,
            CardPrint.cardmarket_set_slug,
            CardPrint.cardmarket_match_quality,
        )
        .join(Card, Card.id == CardPrint.card_id)
        .where(
            Card.normalized_name == normalized_name,
            CardPrint.language == language,
        )
    )
    for set_code, card_number, rarity, card_language, product_url, product_slug, set_slug, match_quality in card_print_rows.all():
        exact_url = normalize_cardmarket_product_url(product_url)
        if not exact_url and product_slug and set_slug:
            locale = _preferred_cardmarket_locale(card_language, language)
            exact_url = build_cardmarket_product_url(locale, set_slug, product_slug)
        if not exact_url or not _is_safe_cardmarket_quality(match_quality):
            continue
        exact_references[(set_code, card_number, rarity, card_language)] = exact_url

    mapping_rows = await db.execute(
        select(
            CardPrint.set_code,
            CardPrint.card_number,
            CardPrint.rarity,
            CardPrint.language,
            CardPrint.cardmarket_match_quality,
            SourceMapping.external_url,
            SourceMapping.external_id,
        )
        .join(CardPrint, SourceMapping.target_id == CardPrint.id)
        .join(Card, Card.id == CardPrint.card_id)
        .where(
            SourceMapping.target_type == "card_print",
            SourceMapping.provider_key == "cardmarket",
            Card.normalized_name == normalized_name,
            CardPrint.language == language,
        )
    )
    for set_code, card_number, rarity, card_language, match_quality, external_url, external_id in mapping_rows.all():
        if not _is_safe_cardmarket_quality(match_quality):
            continue
        exact_url = normalize_cardmarket_product_url(external_url) or normalize_cardmarket_product_url(external_id)
        if not exact_url:
            continue
        exact_references.setdefault((set_code, card_number, rarity, card_language), exact_url)

    return exact_references

def _resolve_cardmarket_link(item: InventoryItem, mappings: list[SourceMapping], latest_payload: dict | None) -> tuple[str | None, str | None]:
    latest_payload = latest_payload or {}
    card_print = item.card_print
    locale = _preferred_cardmarket_locale(card_print.language, latest_payload.get("language"))
    preferred_product_name = card_print.cardmarket_product_name or card_print.card.name

    stored_product_url = normalize_cardmarket_product_url(card_print.cardmarket_product_url)
    if stored_product_url:
        return stored_product_url, card_print.cardmarket_match_quality or CARDMARKET_MATCH_AMBIGUOUS

    direct_reference = normalize_cardmarket_product_url(item.cardmarket_reference)
    if direct_reference:
        return direct_reference, CARDMARKET_MATCH_AMBIGUOUS

    for mapping in mappings:
        if mapping.provider_key != "cardmarket":
            continue
        mapping_url = normalize_cardmarket_product_url(mapping.external_url) or normalize_cardmarket_product_url(mapping.external_id)
        if mapping_url:
            mapping_payload = mapping.payload if isinstance(mapping.payload, dict) else {}
            mapping_quality = mapping_payload.get("match_quality")
            return mapping_url, mapping_quality or CARDMARKET_MATCH_AMBIGUOUS

    for source in (latest_payload.get("source_url"), latest_payload.get("cardmarket_product_url")):
        exact_url = normalize_cardmarket_product_url(source)
        if exact_url:
            payload_quality = latest_payload.get("match_quality")
            return exact_url, payload_quality or CARDMARKET_MATCH_AMBIGUOUS

    derived_resolution = resolve_cardmarket_product_url(
        locale=locale,
        cardmarket_product_url=None,
        cardmarket_product_slug=card_print.cardmarket_product_slug,
        cardmarket_set_slug=card_print.cardmarket_set_slug,
        cardmarket_set_name=card_print.cardmarket_set_name or card_print.set_name,
        cardmarket_product_name=preferred_product_name,
        cardmarket_variant_name=card_print.cardmarket_variant_name,
        cardmarket_rarity=card_print.cardmarket_expected_rarity or card_print.rarity,
        card_name=preferred_product_name,
        has_multiple_variants=False,
        allow_fallback=False,
    )
    if derived_resolution.url and derived_resolution.mode in CARDMARKET_SAFE_MATCH_QUALITIES:
        return derived_resolution.url, derived_resolution.mode

    return None, CARDMARKET_MATCH_FAILED

def _build_pricing_status(item: InventoryItem, mappings: list[SourceMapping], active_job: SyncJob | None) -> PricingStatus:
    latest_entry = _latest_price_entry(item)
    latest_payload = latest_entry.payload if latest_entry and latest_entry.payload else {}
    cardmarket_link, cardmarket_link_mode = _resolve_cardmarket_link(item, mappings, latest_payload)
    monitor_status = build_price_monitor_status(item, active_job=active_job)

    match_quality = item.last_price_match_quality or latest_payload.get("match_quality")
    note = (
        monitor_status.get("last_error_message")
        or item.last_price_note
        or latest_payload.get("note")
        or monitor_status.get("note")
    )
    source = item.last_price_source or (latest_entry.provider_key if latest_entry else None)
    last_updated_at = monitor_status.get("last_updated_at") or item.last_priced_at or (latest_entry.captured_at if latest_entry else None)

    if item.current_market_price is None:
        status = monitor_status.get("status") or "unpriced"
    elif match_quality == "manual":
        status = "manual"
    elif match_quality in {CARDMARKET_MATCH_EXACT, CARDMARKET_MATCH_EXACT_VARIANT, CARDMARKET_MATCH_MANUAL}:
        status = "exact"
    elif match_quality in {CARDMARKET_MATCH_SET_NAME, "high_confidence"}:
        status = "high_confidence"
    elif match_quality in {CARDMARKET_MATCH_AMBIGUOUS, CARDMARKET_MATCH_FAILED, "fallback", "fallback_name_only"}:
        status = "fallback"
    else:
        status = monitor_status.get("status") or "fallback"

    return PricingStatus(
        status=status,
        is_updating=active_job is not None,
        pending_job_id=active_job.id if active_job else None,
        match_quality=match_quality,
        source=source,
        note=note,
        last_updated_at=last_updated_at,
        cardmarket_url=cardmarket_link,
        cardmarket_link_mode=cardmarket_link_mode,
        last_price_check_at=monitor_status.get("last_price_check_at"),
        next_price_check_at=monitor_status.get("next_price_check_at"),
        price_check_interval_hours=monitor_status.get("price_check_interval_hours"),
        price_volatility_score=monitor_status.get("price_volatility_score"),
        price_check_priority=monitor_status.get("price_check_priority"),
        price_stability_state=monitor_status.get("price_stability_state"),
        failure_count=monitor_status.get("failure_count"),
        consecutive_stable_checks=monitor_status.get("consecutive_stable_checks"),
        last_error_message=monitor_status.get("last_error_message"),
        pending_job=serialize_sync_job(active_job) if active_job else None,
    )

async def _display_price_value(
    value: float | int | Decimal | None,
    source_currency: str | None,
    target_currency: str,
) -> tuple[float | None, str | None]:
    if value is None:
        return None, None

    converted = await convert_amount(value, source_currency, target_currency)
    if converted is None:
        if source_currency and source_currency.upper() != target_currency.upper():
            return None, f"Preis konnte nicht von {source_currency.upper()} nach {target_currency.upper()} umgerechnet werden."
        return float(value), None

    return float(converted), None

async def _display_optional_price_value(
    value: float | int | Decimal | None,
    source_currency: str | None,
    target_currency: str,
) -> float | None:
    if value is None:
        return None
    converted, _note = await _display_price_value(value, source_currency, target_currency)
    if converted is not None:
        return float(converted)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

async def _display_price_sample_values(
    values: list[float | int | Decimal | None] | None,
    source_currency: str | None,
    target_currency: str,
) -> list[float]:
    sample: list[float] = []
    for value in values or []:
        converted = await _display_optional_price_value(value, source_currency, target_currency)
        if converted is not None:
            sample.append(converted)
    return sample

async def _serialize_price_history_point(entry: PriceHistory, *, display_currency: str) -> PriceHistoryPoint:
    converted_price, conversion_note = await _display_price_value(entry.price, entry.currency, display_currency)
    payload = entry.payload or {}
    lowest_offer_price = await _display_optional_price_value(payload.get("lowest_offer_price"), entry.currency, display_currency)
    selected_market_price = await _display_optional_price_value(
        payload.get("market_price_median_top5") if payload.get("market_price_median_top5") is not None else payload.get("selected_market_price"),
        entry.currency,
        display_currency,
    )
    price_trend = await _display_optional_price_value(payload.get("price_trend"), entry.currency, display_currency)
    avg_1d = await _display_optional_price_value(payload.get("avg_1d"), entry.currency, display_currency)
    avg_7d = await _display_optional_price_value(payload.get("avg_7d"), entry.currency, display_currency)
    avg_30d = await _display_optional_price_value(payload.get("avg_30d"), entry.currency, display_currency)
    top5_offer_prices = await _display_price_sample_values(
        payload.get("top5_offer_prices") if payload.get("top5_offer_prices") is not None else payload.get("raw_offer_prices_sample"),
        entry.currency,
        display_currency,
    )
    raw_offer_prices_sample = await _display_price_sample_values(
        payload.get("raw_offer_prices_sample") if payload.get("raw_offer_prices_sample") is not None else payload.get("top5_offer_prices"),
        entry.currency,
        display_currency,
    )

    return PriceHistoryPoint(
        captured_at=entry.captured_at,
        price=float(converted_price) if converted_price is not None else float(entry.price),
        currency=display_currency,
        metric=entry.metric,
        provider_key=entry.provider_key,
        match_quality=payload.get("match_quality"),
        note=" ".join(filter(None, [payload.get("note"), conversion_note])) or None,
        source_url=payload.get("source_url"),
        source_product_id=payload.get("source_product_id"),
        set_code=payload.get("matched_set_code") or payload.get("set_code"),
        card_number=payload.get("matched_card_number") or payload.get("card_number"),
        rarity=payload.get("matched_rarity") or payload.get("rarity"),
        language=payload.get("matched_language") or payload.get("language"),
        lowest_offer_price=lowest_offer_price,
        selected_market_price=selected_market_price,
        market_price_median_top5=selected_market_price,
        pricing_strategy_used=payload.get("pricing_strategy_used"),
        offer_count_considered=payload.get("offers_considered_count") or payload.get("offer_count_considered"),
        offers_considered_count=payload.get("offers_considered_count") or payload.get("offer_count_considered"),
        outlier_detected=payload.get("outlier_detected"),
        price_trend=price_trend,
        avg_1d=avg_1d,
        avg_7d=avg_7d,
        avg_30d=avg_30d,
        filters_used=payload.get("filters_used"),
        parse_status=payload.get("parse_status"),
        top5_offer_prices=top5_offer_prices,
        raw_offer_prices_sample=raw_offer_prices_sample,
    )

async def serialize_card_summary(
    item: InventoryItem,
    *,
    mappings: list[SourceMapping] | None = None,
    active_job: SyncJob | None = None,
    display_currency: str = "EUR",
) -> CardSummary:
    card_print = item.card_print
    card = card_print.card
    image_asset = _first_image(card_print)
    if image_asset and image_asset.local_path:
        image_url = f"/media/{image_asset.local_path}"
    elif card_print.remote_image_url:
        image_url = _proxy_remote_image_url(card_print.remote_image_url) or _placeholder_url(item.id, card.name)
    else:
        image_url = _placeholder_url(item.id, card.name)
    current_market_price, conversion_note = await _display_price_value(item.current_market_price, item.current_price_currency, display_currency)
    purchase_price = float(item.purchase_price) if item.purchase_price is not None else None
    pricing = _build_pricing_status(item, mappings or [], active_job)
    if conversion_note:
        pricing = pricing.model_copy(update={"note": f"{pricing.note} {conversion_note}".strip() if pricing.note else conversion_note})

    return CardSummary(
        id=item.id,
        card_id=card.id,
        card_print_id=card_print.id,
        name=card.name,
        language=card_print.language,
        set_name=card_print.set_name,
        set_code=card_print.set_code,
        card_number=card_print.card_number,
        rarity=card_print.rarity,
        condition=item.condition,
        quantity=item.quantity,
        purchase_price=purchase_price,
        current_market_price=current_market_price,
        current_price_currency=display_currency,
        total_value=round((current_market_price or 0) * item.quantity, 2),
        price_change_7d=item.price_change_7d,
        price_change_30d=item.price_change_30d,
        trend_score=item.trend_score,
        card_type=card.card_type,
        card_kind=card.card_kind,
        attribute=card.attribute,
        monster_type=card.monster_type,
        atk=card.atk,
        defense=card.defense,
        level=card.level,
        rank=card.rank,
        link_rating=card.link_rating,
        storage_location_id=item.storage_location_id,
        storage_location_name=item.storage_location.name if item.storage_location else None,
        storage_path=item.storage_location.path_cache if item.storage_location else None,
        has_image=image_asset is not None,
        has_price=current_market_price is not None,
        image_url=image_url,
        last_priced_at=item.last_priced_at,
        last_price_source=item.last_price_source,
        last_price_match_quality=item.last_price_match_quality,
        last_price_note=item.last_price_note,
        pricing=pricing,
        notes=item.notes,
        updated_at=item.updated_at,
    )

async def list_cards(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
    language: str | None = None,
    set_code: str | None = None,
    card_type: str | None = None,
    attribute: str | None = None,
    monster_type: str | None = None,
    rarity: str | None = None,
    condition: str | None = None,
    storage_location_id: int | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    min_atk: int | None = None,
    max_atk: int | None = None,
    min_defense: int | None = None,
    max_defense: int | None = None,
    level: int | None = None,
    rank: int | None = None,
    has_image: bool | None = None,
    has_price: bool | None = None,
    price_direction: str | None = None,
    sort_by: str = "updated_at",
    sort_order: str = "desc",
) -> tuple[list[CardSummary], int]:
    app_settings = await get_app_settings(db)
    display_currency = app_settings.preferred_currency
    stmt = (
        select(InventoryItem)
        .join(InventoryItem.card_print)
        .join(CardPrint.card)
        .outerjoin(InventoryItem.storage_location)
        .options(
            selectinload(InventoryItem.storage_location),
            selectinload(InventoryItem.price_history),
            selectinload(InventoryItem.price_monitor_state),
            selectinload(InventoryItem.card_print).selectinload(CardPrint.card),
            selectinload(InventoryItem.card_print).selectinload(CardPrint.image_assets),
        )
    )
    count_stmt = select(func.count(InventoryItem.id)).join(InventoryItem.card_print).join(CardPrint.card).outerjoin(InventoryItem.storage_location)

    filters = []
    if q:
        pattern = f"%{q.strip()}%"
        filters.append(
            or_(
                Card.name.ilike(pattern),
                Card.description.ilike(pattern),
                CardPrint.set_name.ilike(pattern),
                CardPrint.set_code.ilike(pattern),
                CardPrint.card_number.ilike(pattern),
                CardPrint.rarity.ilike(pattern),
                CardPrint.language.ilike(pattern),
                InventoryItem.notes.ilike(pattern),
                StorageLocation.name.ilike(pattern),
            )
        )
    if language:
        filters.append(CardPrint.language == language)
    if set_code:
        filters.append(CardPrint.set_code.ilike(f"%{set_code}%"))
    if card_type:
        filters.append(Card.card_type == card_type)
    if attribute:
        filters.append(Card.attribute == attribute)
    if monster_type:
        filters.append(Card.monster_type == monster_type)
    if rarity:
        filters.append(CardPrint.rarity == rarity)
    if condition:
        filters.append(InventoryItem.condition == condition)
    if storage_location_id:
        filters.append(InventoryItem.storage_location_id == storage_location_id)
    if min_price is not None:
        filters.append(InventoryItem.current_market_price >= min_price)
    if max_price is not None:
        filters.append(InventoryItem.current_market_price <= max_price)
    if min_atk is not None:
        filters.append(Card.atk >= min_atk)
    if max_atk is not None:
        filters.append(Card.atk <= max_atk)
    if min_defense is not None:
        filters.append(Card.defense >= min_defense)
    if max_defense is not None:
        filters.append(Card.defense <= max_defense)
    if level is not None:
        filters.append(Card.level == level)
    if rank is not None:
        filters.append(Card.rank == rank)
    if has_image is True:
        filters.append(CardPrint.image_assets.any(and_(ImageAsset.status == "downloaded", ImageAsset.local_path.is_not(None))))
    if has_image is False:
        filters.append(~CardPrint.image_assets.any(and_(ImageAsset.status == "downloaded", ImageAsset.local_path.is_not(None))))
    if has_price is True:
        filters.append(InventoryItem.current_market_price > 0)
    if has_price is False:
        filters.append(or_(InventoryItem.current_market_price.is_(None), InventoryItem.current_market_price <= 0))
    if price_direction == "up":
        filters.append(InventoryItem.price_change_7d > 0)
    elif price_direction == "down":
        filters.append(InventoryItem.price_change_7d < 0)
    elif price_direction == "volatile":
        filters.append(func.abs(InventoryItem.trend_score) >= 10)

    if filters:
        stmt = stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)

    sort_map = {
        "name": Card.name,
        "set_code": CardPrint.set_code,
        "price": InventoryItem.current_market_price,
        "quantity": InventoryItem.quantity,
        "trend": InventoryItem.trend_score,
        "updated_at": InventoryItem.updated_at,
    }
    sort_column = sort_map.get(sort_by, InventoryItem.updated_at)
    sort_clause = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    stmt = stmt.order_by(sort_clause, Card.name.asc()).offset((page - 1) * page_size).limit(page_size)

    total = await db.scalar(count_stmt) or 0
    result = await db.execute(stmt)
    items = result.scalars().unique().all()
    grouped_mappings = await _load_source_mappings(db, items)
    active_jobs = await _load_active_price_jobs(db, items)
    serialized_items: list[CardSummary] = []
    for item in items:
        serialized_items.append(
            await serialize_card_summary(
                item,
                mappings=_mappings_for_item(grouped_mappings, item),
                active_job=active_jobs.get(item.id),
                display_currency=display_currency,
            )
        )
    return serialized_items, int(total)

async def get_card_detail(db: AsyncSession, inventory_item_id: int) -> CardDetail | None:
    app_settings = await get_app_settings(db)
    display_currency = app_settings.preferred_currency
    result = await db.execute(
        select(InventoryItem)
        .where(InventoryItem.id == inventory_item_id)
        .options(
            selectinload(InventoryItem.storage_location),
            selectinload(InventoryItem.price_history),
            selectinload(InventoryItem.price_monitor_state),
            selectinload(InventoryItem.card_print).selectinload(CardPrint.card),
            selectinload(InventoryItem.card_print).selectinload(CardPrint.image_assets),
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        return None

    mappings_result = await db.execute(
        select(SourceMapping).where(
            or_(
                and_(SourceMapping.target_type == "card", SourceMapping.target_id == item.card_print.card.id),
                and_(SourceMapping.target_type == "card_print", SourceMapping.target_id == item.card_print.id),
            )
        )
    )
    mappings = mappings_result.scalars().all()
    active_jobs = await _load_active_price_jobs(db, [item])
    summary = await serialize_card_summary(item, mappings=mappings, active_job=active_jobs.get(item.id), display_currency=display_currency)
    card = item.card_print.card
    price_history_entries = []
    valid_history = [entry for entry in item.price_history if parse_positive_price(entry.price) is not None]
    for history in sorted(valid_history, key=lambda entry: entry.captured_at, reverse=True)[:40]:
        price_history_entries.append(await _serialize_price_history_point(history, display_currency=display_currency))

    return CardDetail(
        **summary.model_dump(),
        stored_market_price=parse_positive_price(item.current_market_price),
        stored_price_currency=item.current_price_currency if parse_positive_price(item.current_market_price) is not None else None,
        effect_text=card.description,
        subtype=card.subtype,
        archetype=card.archetype,
        spell_trap_type=card.spell_trap_type,
        rarity_code=item.card_print.rarity_code,
        edition=item.card_print.edition,
        release_date=item.card_print.release_date,
        cardmarket_reference=item.cardmarket_reference,
        cardmarket_product_url=item.card_print.cardmarket_product_url,
        cardmarket_product_slug=item.card_print.cardmarket_product_slug,
        cardmarket_set_slug=item.card_print.cardmarket_set_slug,
        cardmarket_set_name=item.card_print.cardmarket_set_name,
        cardmarket_product_name=item.card_print.cardmarket_product_name,
        cardmarket_variant_name=item.card_print.cardmarket_variant_name,
        cardmarket_category=item.card_print.cardmarket_category,
        cardmarket_match_quality=item.card_print.cardmarket_match_quality,
        cardmarket_verified_at=item.card_print.cardmarket_verified_at,
        cardmarket_expected_rarity=item.card_print.cardmarket_expected_rarity,
        cardmarket_expected_language=item.card_print.cardmarket_expected_language,
        cardmarket_expected_set_name=item.card_print.cardmarket_expected_set_name,
        tags=item.tags or [],
        link_arrows=card.link_arrows or [],
        pendulum_scale=card.pendulum_scale,
        pendulum_effect=card.pendulum_effect,
        price_history=price_history_entries,
        source_mappings=[
            SourceMappingResponse(
                provider_key=mapping.provider_key,
                external_id=mapping.external_id,
                external_url=mapping.external_url,
                last_synced_at=mapping.last_synced_at,
            )
            for mapping in mappings
        ],
    )

async def get_filter_options(db: AsyncSession) -> CardFilterOptions:
    async def distinct_values(column) -> list[str]:
        result = await db.execute(select(column).where(column.is_not(None)).distinct().order_by(column.asc()))
        return [value for value in result.scalars().all() if value]

    from app.services.storage import list_storage_locations

    return CardFilterOptions(
        rarities=await distinct_values(CardPrint.rarity),
        conditions=await distinct_values(InventoryItem.condition),
        card_types=await distinct_values(Card.card_type),
        attributes=await distinct_values(Card.attribute),
        monster_types=await distinct_values(Card.monster_type),
        storage_locations=await list_storage_locations(db),
    )

async def price_history_for_card(db: AsyncSession, inventory_item_id: int) -> list[PriceHistoryPoint]:
    app_settings = await get_app_settings(db)
    display_currency = app_settings.preferred_currency
    result = await db.execute(
        select(PriceHistory)
        .where(
            PriceHistory.inventory_item_id == inventory_item_id,
            PriceHistory.price > 0,
        )
        .order_by(PriceHistory.captured_at.desc())
    )
    history = result.scalars().all()
    items: list[PriceHistoryPoint] = []
    for entry in history:
        items.append(await _serialize_price_history_point(entry, display_currency=display_currency))
    return items
