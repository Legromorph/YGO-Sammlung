from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import session_scope
from app.domain.card_metadata import apply_card_metadata, normalize_card_metadata
from app.integrations.card_data import get_card_data_provider
from app.integrations.images import get_active_image_provider
from app.integrations.cardmarket_links import CARDMARKET_SAFE_MATCH_QUALITIES
from app.integrations.price_values import parse_positive_price
from app.integrations.prices import get_active_price_provider
from app.models import Card, CardPrint, ImageAsset, InventoryItem, PriceHistory, SourceMapping, SyncJob
from app.services.price_monitor import (
    _low_value_threshold_for_currency,
    record_price_monitor_failure,
    refresh_price_monitor_state,
)
from app.time_utils import utc_now

logger = logging.getLogger(__name__)

from app.services.sync_jobs import (
    _append_job_log,
    _build_price_item_context,
    _build_snapshot_log_context,
    _extract_price_targets,
)

async def bootstrap_missing_media() -> None:
    async with session_scope() as db:
        inventory_exists = await db.scalar(select(InventoryItem.id).limit(1))
        downloaded_images = await db.scalar(select(func.count(ImageAsset.id)).where(ImageAsset.status == "downloaded")) or 0
        missing_remote_images = await db.scalar(select(func.count(CardPrint.id)).where(CardPrint.remote_image_url.is_(None))) or 0

    if not inventory_exists:
        return
    if downloaded_images > 0 and missing_remote_images == 0:
        return

    await _run_card_data_sync()
    await _run_image_sync()

async def _persist_job_progress(job_id: int | None, **updates: object) -> None:
    if not job_id or not updates:
        return
    async with session_scope() as db:
        job = await db.get(SyncJob, job_id)
        if not job:
            return
        for field, value in updates.items():
            setattr(job, field, value)

async def _find_mapping(db: AsyncSession, target_type: str, target_id: int, provider_key: str) -> SourceMapping | None:
    result = await db.execute(
        select(SourceMapping).where(
            SourceMapping.target_type == target_type,
            SourceMapping.target_id == target_id,
            SourceMapping.provider_key == provider_key,
        )
    )
    return result.scalar_one_or_none()

async def _run_card_data_sync(payload: dict | None = None) -> dict:
    del payload
    provider = get_card_data_provider()
    synced = 0
    async with session_scope() as db:
        result = await db.execute(
            select(Card)
            .join(Card.card_prints)
            .where(or_(Card.last_synced_at.is_(None), Card.last_synced_at < utc_now() - timedelta(days=1)))
            .options(selectinload(Card.card_prints))
            .order_by(Card.name.asc())
        )
        cards = result.scalars().unique().all()

        for card in cards:
            remote = await provider.fetch_card(name=card.name)
            if not remote:
                continue

            card.description = remote.get("description")
            apply_card_metadata(
                card,
                normalize_card_metadata(
                    card_type=remote.get("card_type"),
                    subtype=remote.get("subtype"),
                    frame_type=remote.get("frame_type"),
                    attribute=remote.get("attribute"),
                    monster_type=remote.get("monster_type"),
                    archetype=remote.get("archetype"),
                    atk=remote.get("atk"),
                    defense=remote.get("defense"),
                    level=remote.get("level"),
                    rank=remote.get("rank"),
                    link_rating=remote.get("link_rating"),
                    link_arrows=remote.get("link_arrows"),
                    pendulum_scale=remote.get("pendulum_scale"),
                    pendulum_effect=remote.get("pendulum_effect"),
                    spell_trap_type=remote.get("spell_trap_type"),
                ),
            )
            card.limitations = remote.get("limitations")
            card.source_payload = remote.get("payload")
            card.last_synced_at = utc_now()

            mapping = await _find_mapping(db, "card", card.id, provider.provider_key)
            if not mapping:
                mapping = SourceMapping(
                    target_type="card",
                    target_id=card.id,
                    provider_key=provider.provider_key,
                    external_id=remote["external_id"],
                )
                db.add(mapping)
            mapping.external_id = remote["external_id"]
            mapping.external_url = f"https://db.ygoprodeck.com/card/?search={remote['external_id']}"
            mapping.last_synced_at = utc_now()
            mapping.payload = {"name": remote["name"]}

            remote_sets = {entry.get("set_code"): entry for entry in remote.get("card_sets", []) if entry.get("set_code")}
            for card_print in card.card_prints:
                remote_set = remote_sets.get(card_print.set_code)
                if not remote_set:
                    continue
                card_print.set_name = card_print.set_name or remote_set.get("set_name")
                card_print.rarity = card_print.rarity or remote_set.get("set_rarity")
                card_print.rarity_code = card_print.rarity_code or remote_set.get("set_rarity_code")
                if remote.get("card_images"):
                    card_print.remote_image_url = remote["card_images"][0].get("image_url")
                print_mapping = await _find_mapping(db, "card_print", card_print.id, provider.provider_key)
                if not print_mapping:
                    print_mapping = SourceMapping(
                        target_type="card_print",
                        target_id=card_print.id,
                        provider_key=provider.provider_key,
                        external_id=remote["external_id"],
                    )
                    db.add(print_mapping)
                print_mapping.external_id = remote["external_id"]
                print_mapping.last_synced_at = utc_now()

            synced += 1

    logger.info("Card data sync updated %s card(s)", synced)
    return {"synced_cards": synced}

async def _load_price_sync_items(
    payload: dict | None,
    *,
    provider_key: str,
) -> list[tuple[InventoryItem, SourceMapping | None, SourceMapping | None, SourceMapping | None]]:
    inventory_item_ids, card_print_ids = _extract_price_targets(payload)
    async with session_scope() as db:
        stmt = (
            select(InventoryItem)
            .options(selectinload(InventoryItem.card_print).selectinload(CardPrint.card))
            .order_by(InventoryItem.updated_at.asc(), InventoryItem.id.asc())
        )
        target_filters = []
        if inventory_item_ids:
            target_filters.append(InventoryItem.id.in_(inventory_item_ids))
        if card_print_ids:
            target_filters.append(InventoryItem.card_print_id.in_(card_print_ids))
        if target_filters:
            stmt = stmt.where(or_(*target_filters))

        result = await db.execute(stmt)
        items = result.scalars().unique().all()
        if not items:
            return []

        card_ids = {item.card_print.card.id for item in items}
        print_ids = {item.card_print_id for item in items}
        mappings_result = await db.execute(
            select(SourceMapping).where(
                SourceMapping.provider_key.in_((provider_key, "cardmarket")),
                or_(
                    and_(SourceMapping.target_type == "card", SourceMapping.target_id.in_(card_ids)),
                    and_(SourceMapping.target_type == "card_print", SourceMapping.target_id.in_(print_ids)),
                ),
            )
        )
        mappings_by_key = {
            (mapping.target_type, mapping.target_id, mapping.provider_key): mapping
            for mapping in mappings_result.scalars().all()
        }

    return [
        (
            item,
            mappings_by_key.get(("card", item.card_print.card.id, provider_key)),
            mappings_by_key.get(("card_print", item.card_print_id, provider_key)),
            mappings_by_key.get(("card_print", item.card_print_id, "cardmarket")),
        )
        for item in items
    ]

def _apply_cardmarket_snapshot_metadata(item: InventoryItem, snapshot: object) -> None:
    indicators = getattr(snapshot, "indicators", {}) or {}
    resolved_match_quality = indicators.get("resolved_cardmarket_match_quality")
    if str(resolved_match_quality or "") not in CARDMARKET_SAFE_MATCH_QUALITIES:
        return

    product_url = indicators.get("resolved_cardmarket_product_url") or getattr(snapshot, "cardmarket_reference", None)
    if product_url:
        item.cardmarket_reference = str(product_url)
        item.card_print.cardmarket_product_url = str(product_url)

    metadata_fields = {
        "cardmarket_product_slug": "resolved_cardmarket_product_slug",
        "cardmarket_set_slug": "resolved_cardmarket_set_slug",
        "cardmarket_product_name": "resolved_cardmarket_product_name",
        "cardmarket_set_name": "resolved_cardmarket_set_name",
        "cardmarket_variant_name": "resolved_cardmarket_variant_name",
    }
    for model_field, indicator_key in metadata_fields.items():
        value = indicators.get(indicator_key)
        if value:
            setattr(item.card_print, model_field, str(value))

    item.card_print.cardmarket_match_quality = str(resolved_match_quality)
    verified_at = indicators.get("resolved_cardmarket_verified_at")
    if isinstance(verified_at, str) and verified_at:
        try:
            item.card_print.cardmarket_verified_at = datetime.fromisoformat(verified_at.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            logger.warning("Invalid Cardmarket verification time for inventory item %s: %s", item.id, verified_at)

async def _persist_price_snapshot(
    inventory_item_id: int,
    snapshot: object,
    *,
    checked_at: datetime,
    existing_card_mapping_external_id: str | None,
    low_value_threshold: float,
) -> bool:
    async with session_scope() as db:
        result = await db.execute(
            select(InventoryItem)
            .where(InventoryItem.id == inventory_item_id)
            .options(
                selectinload(InventoryItem.card_print).selectinload(CardPrint.card),
            )
        )
        item = result.scalar_one_or_none()
        if not item:
            raise ValueError(f"Inventory item {inventory_item_id} no longer exists.")

        market_price = parse_positive_price(getattr(snapshot, "market_price", None))
        if market_price is None:
            await record_price_monitor_failure(
                db,
                item,
                error_message=getattr(snapshot, "note", None) or "Provider returned no positive market price.",
                checked_at=checked_at,
            )
            return False

        item.last_price_source = getattr(snapshot, "source_key", None)
        item.last_price_match_quality = getattr(snapshot, "match_quality", None)
        item.last_price_note = getattr(snapshot, "note", None)
        _apply_cardmarket_snapshot_metadata(item, snapshot)

        currency = str(getattr(snapshot, "currency", None) or "EUR").upper()
        item.current_market_price = market_price
        item.current_price_currency = currency
        item.last_priced_at = checked_at

        indicators = dict(getattr(snapshot, "indicators", {}) or {})
        indicators.setdefault("match_quality", getattr(snapshot, "match_quality", None))
        indicators.setdefault("note", getattr(snapshot, "note", None))
        indicators.setdefault("source_market", getattr(snapshot, "source_key", None))
        price_history_entry = PriceHistory(
            inventory_item_id=item.id,
            card_print_id=item.card_print_id,
            provider_key=str(getattr(snapshot, "provider_key", None) or "unknown"),
            metric="market",
            currency=currency,
            price=market_price,
            payload=indicators,
            captured_at=checked_at,
        )
        db.add(price_history_entry)
        history_result = await db.execute(
            select(PriceHistory)
            .where(
                PriceHistory.inventory_item_id == item.id,
                PriceHistory.price > 0,
                PriceHistory.captured_at < checked_at,
            )
            .order_by(PriceHistory.captured_at.desc())
            .limit(5)
        )
        recent_history = history_result.scalars().all()

        external_id = indicators.get("external_id")
        provider_key = getattr(snapshot, "provider_key", None)
        if (
            external_id
            and provider_key
            and str(external_id) != str(existing_card_mapping_external_id or "")
        ):
            card_mapping = await _find_mapping(db, "card", item.card_print.card.id, str(provider_key))
            if not card_mapping:
                card_mapping = SourceMapping(
                    target_type="card",
                    target_id=item.card_print.card.id,
                    provider_key=str(provider_key),
                    external_id=str(external_id),
                )
                db.add(card_mapping)
            card_mapping.external_id = str(external_id)
            card_mapping.last_synced_at = checked_at

        await refresh_price_monitor_state(
            db,
            item,
            history=[price_history_entry, *recent_history],
            current_price=market_price,
            current_currency=currency,
            checked_at=checked_at,
            low_value_threshold=low_value_threshold,
        )
        return True

def _price_provider_rate_limit(provider_key: str) -> tuple[int | None, int]:
    if provider_key != "cardmarket":
        return None, 0

    per_minute = max(1, settings.price_monitor_max_requests_per_minute)
    per_hour = max(1, settings.price_monitor_max_requests_per_hour)
    spacing_seconds = max(
        1,
        (60 + per_minute - 1) // per_minute,
        (3600 + per_hour - 1) // per_hour,
    )
    return per_minute, spacing_seconds

async def _record_price_item_failure(inventory_item_id: int, error_message: str, *, checked_at: datetime) -> None:
    async with session_scope() as db:
        item = await db.get(InventoryItem, inventory_item_id)
        if item:
            await record_price_monitor_failure(db, item, error_message=error_message, checked_at=checked_at)

async def _run_price_sync(payload: dict | None = None) -> dict:
    job_id = payload.get("_job_id") if payload else None
    provider = get_active_price_provider()
    if not provider:
        raise RuntimeError(f"Unknown price provider '{settings.price_provider}'.")

    inventory_item_ids, card_print_ids = _extract_price_targets(payload)
    timeout_seconds = int(getattr(provider, "lookup_timeout_seconds", max(20, settings.request_timeout_seconds * 2)))
    rate_limit_per_minute, spacing_seconds = _price_provider_rate_limit(provider.provider_key)
    contexts = await _load_price_sync_items(payload, provider_key=provider.provider_key)

    logger.info(
        "Running price update via %s for inventory_items=%s card_prints=%s matched=%s",
        provider.provider_key,
        inventory_item_ids,
        card_print_ids,
        len(contexts),
    )
    await _append_job_log(
        job_id,
        "Preparing price update run.",
        context={
            "provider": provider.provider_key,
            "trigger": payload.get("trigger") if payload else None,
            "reason": payload.get("reason") if payload else None,
            "inventory_item_ids": inventory_item_ids,
            "card_print_ids": card_print_ids,
            "matched_items": len(contexts),
            "price_lookup_timeout_seconds": timeout_seconds,
            "rate_limit_per_minute": rate_limit_per_minute,
        },
        excerpt=f"Preparing {len(contexts)} price lookup(s).",
    )
    await _persist_job_progress(
        job_id,
        total_items=len(contexts),
        processed_items=0,
        successful_items=0,
        failed_items=0,
        next_scheduled_item_at=None,
        rate_limit_per_minute=rate_limit_per_minute,
    )

    if not contexts:
        await _append_job_log(
            job_id,
            "Price update payload matched no inventory items.",
            level="WARNING",
            context={
                "requested_inventory_items": inventory_item_ids,
                "requested_card_prints": card_print_ids,
            },
            excerpt="No inventory items matched payload.",
        )
        return {
            "updated_items": 0,
            "unresolved_items": 0,
            "failed_items": 0,
            "requested_inventory_items": len(inventory_item_ids),
            "requested_card_prints": len(card_print_ids),
            "matched_items": 0,
        }

    prepare_price_run = getattr(provider, "prepare_price_run", None)
    if callable(prepare_price_run) and len(contexts) > 1:
        await _append_job_log(
            job_id,
            "Prefetching grouped provider data.",
            context={"provider": provider.provider_key, "matched_items": len(contexts)},
            excerpt="Loading grouped price data.",
        )
        try:
            prefetch_summary = await prepare_price_run(contexts)
        except Exception as exc:
            logger.warning("Price provider prefetch failed; continuing with single lookups: %s", exc)
            prefetch_summary = {"error": str(exc)}
        await _append_job_log(
            job_id,
            "Grouped provider data prepared.",
            context={"provider": provider.provider_key, "prefetch": prefetch_summary},
            excerpt="Grouped price data ready.",
        )

    updated_item_ids: list[int] = []
    unresolved = 0
    failed = 0
    processed = 0
    low_value_thresholds: dict[str, float] = {}

    for index, (item, card_mapping, print_mapping, cardmarket_mapping) in enumerate(contexts):
        if index > 0 and spacing_seconds:
            next_item_at = utc_now() + timedelta(seconds=spacing_seconds)
            await _persist_job_progress(job_id, next_scheduled_item_at=next_item_at)
            await asyncio.sleep(spacing_seconds)

        item_context = _build_price_item_context(
            item,
            provider_key=provider.provider_key,
            card_mapping=card_mapping,
            print_mapping=print_mapping,
            cardmarket_mapping=cardmarket_mapping,
        )
        lookup_started_at = utc_now()

        try:
            snapshot = await asyncio.wait_for(
                provider.fetch_price(
                    item.card_print.card,
                    item.card_print,
                    item.condition,
                    card_mapping=card_mapping,
                    print_mapping=print_mapping,
                    cardmarket_mapping=cardmarket_mapping,
                    cardmarket_reference=item.cardmarket_reference,
                ),
                timeout=timeout_seconds,
            )
            if snapshot is None:
                raise RuntimeError(f"Price provider '{provider.provider_key}' returned no snapshot.")

            checked_at = utc_now()
            snapshot_context = _build_snapshot_log_context(snapshot)
            snapshot_context.update(
                {
                    "lookup_started_at": lookup_started_at.isoformat(),
                    "lookup_completed_at": checked_at.isoformat(),
                    "lookup_duration_ms": int((checked_at - lookup_started_at).total_seconds() * 1000),
                }
            )
            snapshot_currency = str(snapshot.currency or "EUR").upper()
            if parse_positive_price(snapshot.market_price) is not None:
                if snapshot_currency not in low_value_thresholds:
                    low_value_thresholds[snapshot_currency] = await _low_value_threshold_for_currency(snapshot_currency)
                low_value_threshold = low_value_thresholds[snapshot_currency]
            else:
                low_value_threshold = float(settings.price_monitor_low_value_threshold)
            stored = await _persist_price_snapshot(
                item.id,
                snapshot,
                checked_at=checked_at,
                existing_card_mapping_external_id=card_mapping.external_id if card_mapping else None,
                low_value_threshold=low_value_threshold,
            )
            if stored:
                updated_item_ids.append(item.id)
                logger.info(
                    "Stored price for inventory item %s: %s %s via %s in %sms",
                    item.id,
                    snapshot.market_price,
                    snapshot.currency,
                    snapshot.source_key,
                    snapshot_context["lookup_duration_ms"],
                )
            else:
                unresolved += 1
                failed += 1
                await _append_job_log(
                    job_id,
                    "Price lookup completed without a positive market price.",
                    level="WARNING",
                    context={**item_context, **snapshot_context},
                    excerpt=f"Item {item.id}: no usable price.",
                )
        except asyncio.TimeoutError:
            error = f"Price provider '{provider.provider_key}' timed out after {timeout_seconds}s."
            unresolved += 1
            failed += 1
            checked_at = utc_now()
            await _record_price_item_failure(item.id, error, checked_at=checked_at)
            await _append_job_log(
                job_id,
                "Price update timed out for inventory item.",
                level="ERROR",
                context={**item_context, "error_message": error},
                excerpt=f"Item {item.id}: provider timeout.",
            )
        except Exception as exc:
            unresolved += 1
            failed += 1
            checked_at = utc_now()
            await _record_price_item_failure(item.id, str(exc), checked_at=checked_at)
            logger.exception("Price update failed for inventory item %s: %s", item.id, exc)
            await _append_job_log(
                job_id,
                "Price update failed for inventory item.",
                level="ERROR",
                context={
                    **item_context,
                    "lookup_started_at": lookup_started_at.isoformat(),
                    "lookup_completed_at": checked_at.isoformat(),
                    "error_message": str(exc),
                    "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
                },
                excerpt=f"Item {item.id} failed: {str(exc)}",
            )

        processed += 1
        await _persist_job_progress(
            job_id,
            processed_items=processed,
            successful_items=len(updated_item_ids),
            failed_items=failed,
            next_scheduled_item_at=None,
        )

    if updated_item_ids:
        await _run_trend_rebuild({"inventory_item_ids": updated_item_ids})

    logger.info("Completed price update for %s item(s), unresolved=%s, failed=%s", len(updated_item_ids), unresolved, failed)
    if not updated_item_ids and failed:
        raise RuntimeError(f"Kein Marktpreis konnte aktualisiert werden ({failed} fehlgeschlagene Abfrage(n)).")

    return {
        "updated_items": len(updated_item_ids),
        "unresolved_items": unresolved,
        "requested_inventory_items": len(inventory_item_ids),
        "requested_card_prints": len(card_print_ids),
        "matched_items": len(contexts),
        "failed_items": failed,
    }

async def _run_image_sync(payload: dict | None = None) -> dict:
    target_inventory_item_ids, target_card_print_ids = _extract_price_targets(payload)
    provider = get_active_image_provider()
    downloaded = 0
    async with session_scope() as db:
        stmt = (
            select(CardPrint)
            .join(CardPrint.inventory_items)
            .options(selectinload(CardPrint.card), selectinload(CardPrint.image_assets))
            .order_by(CardPrint.updated_at.desc())
        )
        target_filters = []
        if target_card_print_ids:
            target_filters.append(CardPrint.id.in_(target_card_print_ids))
        if target_inventory_item_ids:
            target_filters.append(InventoryItem.id.in_(target_inventory_item_ids))
        if target_filters:
            stmt = stmt.where(or_(*target_filters))

        result = await db.execute(stmt)
        prints = result.scalars().unique().all()
        for card_print in prints:
            if any(asset.status == "downloaded" and asset.local_path for asset in card_print.image_assets):
                continue
            mapping = await _find_mapping(db, "card_print", card_print.id, provider.provider_key)
            image_payload = await provider.download_image(card_print.card, card_print, mapping)
            if not image_payload:
                asset = card_print.image_assets[0] if card_print.image_assets else ImageAsset(card_print_id=card_print.id, provider_key=provider.provider_key)
                asset.status = "failed"
                asset.last_error = "No remote image available."
                db.add(asset)
                continue

            asset = next((image for image in card_print.image_assets if image.provider_key == provider.provider_key), None)
            if not asset:
                asset = ImageAsset(card_print_id=card_print.id, provider_key=provider.provider_key)
                db.add(asset)
            asset.remote_url = image_payload.remote_url
            asset.local_path = image_payload.local_path
            asset.thumbnail_path = image_payload.thumbnail_path
            asset.content_hash = image_payload.content_hash
            asset.width = image_payload.width
            asset.height = image_payload.height
            asset.status = "downloaded"
            asset.last_error = None
            asset.downloaded_at = utc_now()
            card_print.remote_image_url = image_payload.remote_url
            downloaded += 1

    logger.info("Image sync downloaded %s image(s)", downloaded)
    return {"downloaded_images": downloaded}

def _price_change(history: list[PriceHistory], days: int) -> float:
    positive_history = [entry for entry in history if parse_positive_price(entry.price) is not None]
    if len(positive_history) < 2:
        return 0.0
    latest_currency = (positive_history[0].currency or "EUR").upper()
    comparable_history = [
        entry
        for entry in positive_history
        if (entry.currency or "EUR").upper() == latest_currency
    ]
    if len(comparable_history) < 2:
        return 0.0

    cutoff = utc_now() - timedelta(days=days)
    latest = float(comparable_history[0].price)
    baseline = None
    for entry in comparable_history:
        if entry.captured_at <= cutoff:
            baseline = float(entry.price)
            break
    if baseline in (None, 0):
        baseline = float(comparable_history[-1].price)
    if not baseline:
        return 0.0
    return round(((latest - baseline) / baseline) * 100, 2)

async def _run_trend_rebuild(payload: dict | None = None) -> dict:
    inventory_item_ids, card_print_ids = _extract_price_targets(payload)
    recalculated = 0
    async with session_scope() as db:
        stmt = select(InventoryItem).options(selectinload(InventoryItem.price_history)).order_by(InventoryItem.id.asc())
        if inventory_item_ids:
            stmt = stmt.where(InventoryItem.id.in_(inventory_item_ids))
        elif card_print_ids:
            stmt = stmt.where(InventoryItem.card_print_id.in_(card_print_ids))
        result = await db.execute(stmt)
        items = result.scalars().unique().all()
        for item in items:
            history = sorted(item.price_history, key=lambda entry: entry.captured_at, reverse=True)
            item.price_change_7d = _price_change(history, 7)
            item.price_change_30d = _price_change(history, 30)
            item.trend_score = round((item.price_change_7d or 0) * 0.7 + (item.price_change_30d or 0) * 0.3, 2)
            recalculated += 1

    logger.info("Trend rebuild recalculated %s inventory item(s)", recalculated)
    return {"recalculated_items": recalculated}
