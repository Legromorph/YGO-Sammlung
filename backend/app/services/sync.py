from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import session_scope
from app.integrations.card_data import get_card_data_provider
from app.integrations.images import get_active_image_provider
from app.integrations.prices import get_active_price_provider, get_price_providers
from app.integrations.ygo_omega import get_ygo_omega_probe
from app.models import Card, CardPrint, ImageAsset, InventoryItem, PriceHistory, SourceMapping, SyncJob
from app.schemas import ProviderStatus, SyncJobResponse
from app.services.price_monitor import record_price_monitor_failure, refresh_price_monitor_state

logger = logging.getLogger(__name__)

JOB_PROVIDER_MAP = {
    "price_update": "ygoprodeck",
    "image_sync": "ygoprodeck",
    "trend_rebuild": "internal",
    "card_data_sync": "ygoprodeck",
}
CARDMARKET_SAFE_MATCH_QUALITIES = {
    "exact_verified",
    "exact_verified_variant",
    "set_name_verified_name_only",
}

SyncHandler = Callable[[dict | None], Awaitable[dict]]


def _normalize_target_ids(values: object) -> list[int]:
    normalized: list[int] = []
    seen: set[int] = set()
    for value in values or []:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed <= 0 or parsed in seen:
            continue
        seen.add(parsed)
        normalized.append(parsed)
    return sorted(normalized)


def _as_float(value: object | None) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_price_targets(payload: dict | None) -> tuple[list[int], list[int]]:
    payload = payload or {}
    inventory_item_ids = _normalize_target_ids(payload.get("inventory_item_ids"))
    card_print_ids = _normalize_target_ids(payload.get("card_print_ids"))
    return inventory_item_ids, card_print_ids


def _price_targets_overlap(left_payload: dict | None, right_payload: dict | None) -> bool:
    left_inventory_ids, left_print_ids = _extract_price_targets(left_payload)
    right_inventory_ids, right_print_ids = _extract_price_targets(right_payload)

    left_is_global = not left_inventory_ids and not left_print_ids
    right_is_global = not right_inventory_ids and not right_print_ids

    if left_is_global and right_is_global:
        return True
    if left_is_global != right_is_global:
        return False

    left_inventory_set = set(left_inventory_ids)
    right_inventory_set = set(right_inventory_ids)
    if left_inventory_set and right_inventory_set and left_inventory_set.intersection(right_inventory_set):
        return True

    left_print_set = set(left_print_ids)
    right_print_set = set(right_print_ids)
    if left_print_set and right_print_set and left_print_set.intersection(right_print_set):
        return True

    return False


def _build_job_lock_key(job_type: str, payload: dict | None) -> str:
    if job_type != "price_update":
        return f"{job_type}:global"

    inventory_item_ids, card_print_ids = _extract_price_targets(payload)
    if not inventory_item_ids and not card_print_ids:
        return "price_update:global"

    target_payload: dict[str, list[int]] = {}
    if inventory_item_ids:
        target_payload["inventory_item_ids"] = inventory_item_ids
    else:
        target_payload["card_print_ids"] = card_print_ids

    signature = json.dumps(target_payload, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:16]
    return f"price_update:targeted:{digest}"


def _job_health(job: SyncJob, now: datetime | None = None) -> tuple[bool, str | None]:
    now = now or datetime.utcnow()
    if job.status == "running" and job.started_at:
        timeout_cutoff = now - timedelta(minutes=settings.sync_job_running_timeout_minutes)
        if job.started_at <= timeout_cutoff:
            return True, f"running for more than {settings.sync_job_running_timeout_minutes} minutes"
    if job.status == "pending":
        if job.available_at and job.available_at > now:
            return False, None
        warning_cutoff = now - timedelta(minutes=settings.sync_job_pending_warning_minutes)
        if job.created_at <= warning_cutoff:
            return True, f"pending for more than {settings.sync_job_pending_warning_minutes} minutes"
    return False, None


def serialize_sync_job(job: SyncJob) -> SyncJobResponse:
    is_stuck, stuck_reason = _job_health(job)
    return SyncJobResponse(
        id=job.id,
        job_type=job.job_type,
        provider_key=job.provider_key,
        status=job.status,
        available_at=job.available_at,
        priority=job.priority or 0,
        payload=job.payload,
        log_excerpt=job.log_excerpt,
        error_message=job.error_message,
        started_at=job.started_at,
        completed_at=job.completed_at,
        created_at=job.created_at,
        is_stuck=is_stuck,
        stuck_reason=stuck_reason,
        can_retry=job.status == "failed",
        total_items=job.total_items,
        processed_items=job.processed_items,
        successful_items=job.successful_items,
        failed_items=job.failed_items,
        next_scheduled_item_at=job.next_scheduled_item_at,
        rate_limit_per_minute=job.rate_limit_per_minute,
    )


async def create_sync_job_record(
    db: AsyncSession,
    job_type: str,
    *,
    force: bool = False,
    payload: dict | None = None,
    available_at: datetime | None = None,
    priority: int = 0,
) -> tuple[SyncJob, bool]:
    provider_key = JOB_PROVIDER_MAP.get(job_type)
    if job_type == "price_update":
        active_provider = get_active_price_provider()
        provider_key = active_provider.provider_key if active_provider else provider_key
    lock_key = _build_job_lock_key(job_type, payload)

    if not force:
        recent_jobs_result = await db.execute(
            select(SyncJob)
            .where(
                SyncJob.job_type == job_type,
                SyncJob.status.in_(["pending", "running"]),
                SyncJob.created_at >= datetime.utcnow() - timedelta(hours=1),
            )
            .order_by(SyncJob.created_at.desc())
        )
        recent_jobs = recent_jobs_result.scalars().all()
        for existing in recent_jobs:
            if job_type == "price_update":
                if _price_targets_overlap(existing.payload, payload):
                    updated_existing = False
                    if priority > (existing.priority or 0):
                        existing.priority = priority
                        updated_existing = True
                    if existing.status == "pending" and available_at and (existing.available_at is None or available_at < existing.available_at):
                        existing.available_at = available_at
                        updated_existing = True
                    if existing.status == "pending" and payload:
                        existing_payload = dict(existing.payload or {})
                        existing_payload.update(payload)
                        existing.payload = existing_payload
                        updated_existing = True
                    if updated_existing and existing.status == "pending":
                        existing.log_excerpt = "Rescheduled by a newer price update request."
                    logger.info(
                        "Reusing %s job %s for overlapping payload inventory=%s prints=%s",
                        job_type,
                        existing.id,
                        _extract_price_targets(existing.payload)[0],
                        _extract_price_targets(existing.payload)[1],
                    )
                    await db.flush()
                    return existing, False
            elif existing.lock_key == lock_key:
                logger.info("Reusing %s job %s with identical lock key %s", job_type, existing.id, lock_key)
                return existing, False

    job = SyncJob(
        job_type=job_type,
        provider_key=provider_key,
        status="pending",
        lock_key=lock_key,
        available_at=available_at,
        priority=priority,
        payload=payload,
        log_excerpt="Pending worker claim.",
        total_items=0,
        processed_items=0,
        successful_items=0,
        failed_items=0,
    )
    db.add(job)
    await db.flush()
    logger.info("Created %s job %s with lock %s", job_type, job.id, lock_key)
    return job, True


async def queue_sync_job(
    job_type: str,
    *,
    force: bool = False,
    payload: dict | None = None,
    available_at: datetime | None = None,
    priority: int = 0,
) -> SyncJob:
    async with session_scope() as db:
        job, created = await create_sync_job_record(
            db,
            job_type,
            force=force,
            payload=payload,
            available_at=available_at,
            priority=priority,
        )
        await db.flush()
        job_id = job.id
    logger.info(
        "%s %s job %s payload=%s available_at=%s priority=%s",
        "Queued" if created else "Returned existing",
        job_type,
        job_id,
        json.dumps(payload or {}, ensure_ascii=True, sort_keys=True),
        available_at.isoformat() if available_at else None,
        priority,
    )
    async with session_scope() as db:
        job = await db.get(SyncJob, job_id)
        if not job:
            raise ValueError("Queued job could not be reloaded.")
        return job


async def queue_price_update_job(
    *,
    inventory_item_ids: list[int] | None = None,
    card_print_ids: list[int] | None = None,
    trigger: str = "scheduler",
    reason: str | None = None,
    available_at: datetime | None = None,
    priority: int = 0,
    force: bool = False,
) -> SyncJob:
    payload: dict[str, object] = {
        "trigger": trigger,
    }
    normalized_inventory_item_ids = _normalize_target_ids(inventory_item_ids or [])
    normalized_card_print_ids = _normalize_target_ids(card_print_ids or [])
    if normalized_inventory_item_ids:
        payload["inventory_item_ids"] = normalized_inventory_item_ids
    if normalized_card_print_ids:
        payload["card_print_ids"] = normalized_card_print_ids
    if reason:
        payload["reason"] = reason
    if available_at:
        payload["available_at"] = available_at.isoformat()
    payload["priority"] = priority
    return await queue_sync_job(
        "price_update",
        force=force,
        payload=payload,
        available_at=available_at,
        priority=priority,
    )


async def get_sync_job(db: AsyncSession, job_id: int) -> SyncJobResponse | None:
    job = await db.get(SyncJob, job_id)
    if not job:
        return None
    return serialize_sync_job(job)


async def list_sync_jobs(
    db: AsyncSession,
    *,
    limit: int = 25,
    status: str | None = None,
    job_type: str | None = None,
) -> list[SyncJobResponse]:
    stmt = select(SyncJob).order_by(SyncJob.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(SyncJob.status == status)
    if job_type:
        stmt = stmt.where(SyncJob.job_type == job_type)
    result = await db.execute(stmt)
    jobs = result.scalars().all()
    return [serialize_sync_job(job) for job in jobs]


async def retry_sync_job(job_id: int) -> SyncJob:
    async with session_scope() as db:
        job = await db.get(SyncJob, job_id)
        if not job:
            raise ValueError("Job not found.")
        if job.status != "failed":
            raise ValueError("Nur fehlgeschlagene Jobs koennen erneut gestartet werden.")

        retry_payload = dict(job.payload or {})
        retry_payload["trigger"] = "retry"
        retry_payload["retry_of"] = job.id
        retried_job, _ = await create_sync_job_record(
            db,
            job.job_type,
            force=True,
            payload=retry_payload,
            available_at=datetime.utcnow(),
            priority=job.priority or 0,
        )
        await db.flush()
        retried_job_id = retried_job.id

    logger.info("Created retry job %s from failed job %s", retried_job_id, job_id)
    async with session_scope() as db:
        retried_job = await db.get(SyncJob, retried_job_id)
        if not retried_job:
            raise ValueError("Retried job could not be reloaded.")
        return retried_job


async def get_provider_statuses() -> list[ProviderStatus]:
    statuses = []
    for provider in get_price_providers():
        statuses.append(ProviderStatus(**await provider.healthcheck()))
    statuses.append(ProviderStatus(**await get_card_data_provider().healthcheck()))
    statuses.append(ProviderStatus(**await get_active_image_provider().healthcheck()))
    statuses.append(ProviderStatus(**await get_ygo_omega_probe().healthcheck()))
    return statuses


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


async def fail_stale_running_jobs() -> int:
    cutoff = datetime.utcnow() - timedelta(minutes=settings.sync_job_running_timeout_minutes)
    failed_count = 0

    async with session_scope() as db:
        result = await db.execute(
            select(SyncJob)
            .where(
                SyncJob.status == "running",
                SyncJob.started_at.is_not(None),
                SyncJob.started_at <= cutoff,
            )
            .with_for_update(skip_locked=True)
        )
        jobs = result.scalars().all()
        for job in jobs:
            job.status = "failed"
            job.completed_at = datetime.utcnow()
            job.error_message = (
                "Worker timeout: job exceeded "
                f"{settings.sync_job_running_timeout_minutes} minutes without completion."
            )
            job.log_excerpt = "Marked as failed by stale-job recovery."
            failed_count += 1

    if failed_count:
        logger.warning("Recovered %s stale running sync job(s)", failed_count)
    return failed_count


async def claim_next_sync_job(*, worker_name: str) -> SyncJob | None:
    running_lock_keys = select(SyncJob.lock_key).where(SyncJob.status == "running")
    now = datetime.utcnow()

    async with session_scope() as db:
        result = await db.execute(
            select(SyncJob)
            .where(
                SyncJob.status == "pending",
                or_(SyncJob.available_at.is_(None), SyncJob.available_at <= now),
                ~SyncJob.lock_key.in_(running_lock_keys),
            )
            .order_by(
                SyncJob.priority.desc(),
                SyncJob.available_at.asc().nullsfirst(),
                SyncJob.created_at.asc(),
                SyncJob.id.asc(),
            )
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = result.scalar_one_or_none()
        if not job:
            return None

        job.status = "running"
        job.started_at = datetime.utcnow()
        job.completed_at = None
        job.error_message = None
        job.log_excerpt = f"Claimed by {worker_name}."
        if job.total_items is None:
            job.total_items = 0
        if job.processed_items is None:
            job.processed_items = 0
        if job.successful_items is None:
            job.successful_items = 0
        if job.failed_items is None:
            job.failed_items = 0
        await db.flush()

    logger.info("Claimed pending job %s of type %s", job.id, job.job_type)
    return job


async def _claim_job_by_id(job_id: int, *, worker_name: str) -> SyncJob | None:
    async with session_scope() as db:
        result = await db.execute(
            select(SyncJob)
            .where(SyncJob.id == job_id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        job = result.scalar_one_or_none()
        if not job:
            return None
        if job.status == "pending":
            job.status = "running"
            job.started_at = datetime.utcnow()
            job.completed_at = None
            job.error_message = None
            job.log_excerpt = f"Claimed directly by {worker_name}."
            if job.total_items is None:
                job.total_items = 0
            if job.processed_items is None:
                job.processed_items = 0
            if job.successful_items is None:
                job.successful_items = 0
            if job.failed_items is None:
                job.failed_items = 0
            await db.flush()
            logger.info("Claimed specific pending job %s of type %s", job.id, job.job_type)
            return job
        return job


async def _complete_job(job_id: int, summary: dict) -> None:
    async with session_scope() as db:
        job = await db.get(SyncJob, job_id)
        if not job:
            logger.warning("Job %s disappeared before completion could be stored", job_id)
            return

        if job.total_items is None:
            total_items = summary.get("total_items", summary.get("matched_items"))
            if isinstance(total_items, int):
                job.total_items = total_items
        if job.processed_items is None:
            processed_items = summary.get("processed_items", summary.get("matched_items"))
            if isinstance(processed_items, int):
                job.processed_items = processed_items
        if job.successful_items is None:
            successful_items = summary.get("successful_items", summary.get("updated_items"))
            if isinstance(successful_items, int):
                job.successful_items = successful_items
        if job.failed_items is None:
            failed_items = summary.get("failed_items", summary.get("unresolved_items"))
            if isinstance(failed_items, int):
                job.failed_items = failed_items

        job.status = "completed"
        job.completed_at = datetime.utcnow()
        job.error_message = None
        job.log_excerpt = json.dumps(summary, ensure_ascii=True)

    logger.info("Completed job %s", job_id)


async def _fail_job(job_id: int, error_message: str) -> None:
    async with session_scope() as db:
        job = await db.get(SyncJob, job_id)
        if not job:
            logger.warning("Job %s disappeared before failure could be stored: %s", job_id, error_message)
            return
        job.status = "failed"
        job.completed_at = datetime.utcnow()
        job.error_message = error_message
        job.log_excerpt = "Job failed."

    logger.error("Failed job %s: %s", job_id, error_message)


def _job_handlers() -> dict[str, SyncHandler]:
    return {
        "price_update": _run_price_sync,
        "image_sync": _run_image_sync,
        "trend_rebuild": _run_trend_rebuild,
        "card_data_sync": _run_card_data_sync,
    }


async def process_claimed_sync_job(job_id: int, *, worker_name: str) -> None:
    async with session_scope() as db:
        job = await db.get(SyncJob, job_id)
        if not job:
            logger.warning("Worker %s could not find claimed job %s", worker_name, job_id)
            return
        if job.status != "running":
            logger.warning("Worker %s skipped job %s because status is %s", worker_name, job_id, job.status)
            return
        job_type = job.job_type
        payload = job.payload

    handler = _job_handlers().get(job_type)
    if not handler:
        await _fail_job(job_id, f"Unsupported job type: {job_type}")
        return

    payload_log = json.dumps(payload or {}, ensure_ascii=True, sort_keys=True)
    logger.info("Running %s job %s with payload=%s", job_type, job_id, payload_log)

    # Add job_id to payload for handlers that need it
    handler_payload = dict(payload or {})
    handler_payload["_job_id"] = job_id

    try:
        summary = await handler(handler_payload)
        await _complete_job(job_id, summary)
    except Exception as exc:
        logger.exception("Exception while processing job %s of type %s", job_id, job_type)
        await _fail_job(job_id, str(exc))


async def execute_sync_job(job_id: int) -> None:
    worker_name = "legacy-direct"
    job = await _claim_job_by_id(job_id, worker_name=worker_name)
    if not job:
        logger.warning("Direct execution requested for missing or locked job %s", job_id)
        return
    if job.status != "running":
        logger.info("Direct execution skipped for job %s because status is %s", job_id, job.status)
        return
    await process_claimed_sync_job(job.id, worker_name=worker_name)


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
            .where(or_(Card.last_synced_at.is_(None), Card.last_synced_at < datetime.utcnow() - timedelta(days=1)))
            .options(selectinload(Card.card_prints))
            .order_by(Card.name.asc())
        )
        cards = result.scalars().unique().all()

        for card in cards:
            remote = await provider.fetch_card(name=card.name)
            if not remote:
                continue

            card.card_type = remote.get("card_type")
            card.subtype = remote.get("subtype")
            card.frame_type = remote.get("frame_type")
            card.description = remote.get("description")
            card.attribute = remote.get("attribute")
            card.monster_type = remote.get("monster_type")
            card.archetype = remote.get("archetype")
            card.atk = remote.get("atk")
            card.defense = remote.get("defense")
            card.level = remote.get("level")
            card.rank = remote.get("rank")
            card.link_rating = remote.get("link_rating")
            card.link_arrows = remote.get("link_arrows")
            card.pendulum_scale = remote.get("pendulum_scale")
            card.pendulum_effect = remote.get("pendulum_effect")
            card.spell_trap_type = remote.get("spell_trap_type")
            card.limitations = remote.get("limitations")
            card.source_payload = remote.get("payload")
            card.last_synced_at = datetime.utcnow()

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
            mapping.last_synced_at = datetime.utcnow()
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
                print_mapping.last_synced_at = datetime.utcnow()

            synced += 1

    logger.info("Card data sync updated %s card(s)", synced)
    return {"synced_cards": synced}


async def _run_price_sync(payload: dict | None = None) -> dict:
    job_id = payload.get("_job_id") if payload else None
    is_manual_trigger = bool(payload and payload.get("trigger") == "manual")
    provider = get_active_price_provider()
    if not provider:
        raise RuntimeError("Missing active price provider.")
    price_lookup_timeout_seconds = max(20, settings.request_timeout_seconds * 2)

    updated = 0
    unresolved = 0
    failed = 0
    inventory_item_ids, card_print_ids = _extract_price_targets(payload)
    logger.info(
        "Running price update for inventory_items=%s card_prints=%s",
        inventory_item_ids,
        card_print_ids,
    )

    async with session_scope() as db:
        stmt = (
            select(InventoryItem)
            .options(
                selectinload(InventoryItem.card_print).selectinload(CardPrint.card),
                selectinload(InventoryItem.storage_location),
                selectinload(InventoryItem.price_history),
                selectinload(InventoryItem.price_monitor_state),
            )
            .order_by(InventoryItem.updated_at.asc())
        )
        if inventory_item_ids:
            stmt = stmt.where(InventoryItem.id.in_(inventory_item_ids))
        elif card_print_ids:
            stmt = stmt.where(InventoryItem.card_print_id.in_(card_print_ids))

        result = await db.execute(stmt)
        items = result.scalars().unique().all()
        if not items:
            logger.warning("Price update payload matched no inventory items.")
            await _persist_job_progress(
                job_id,
                total_items=0,
                processed_items=0,
                successful_items=0,
                failed_items=0,
                next_scheduled_item_at=None,
                rate_limit_per_minute=5 if is_manual_trigger else None,
            )
            return {
                "updated_items": 0,
                "unresolved_items": 0,
                "failed_items": 0,
                "requested_inventory_items": len(inventory_item_ids),
                "requested_card_prints": len(card_print_ids),
                "matched_items": 0,
            }

        processed_items = 0
        successful_items = 0
        failed_items_progress = 0
        await _persist_job_progress(
            job_id,
            total_items=len(items),
            processed_items=0,
            successful_items=0,
            failed_items=0,
            next_scheduled_item_at=None,
            rate_limit_per_minute=5 if is_manual_trigger else None,
        )

        now = datetime.utcnow()
        for i, item in enumerate(items):
            try:
                # Rate limiting for manual updates
                if job_id and is_manual_trigger and i > 0:
                    await asyncio.sleep(12)  # 5 per minute = 12 seconds between requests

                card = item.card_print.card
                card_mapping = await _find_mapping(db, "card", card.id, provider.provider_key)
                print_mapping = await _find_mapping(db, "card_print", item.card_print_id, provider.provider_key)
                cardmarket_mapping = await _find_mapping(db, "card_print", item.card_print_id, "cardmarket")
                snapshot = None
                primary_provider_error: Exception | None = None
                try:
                    snapshot = await asyncio.wait_for(
                        provider.fetch_price(
                            card,
                            item.card_print,
                            item.condition,
                            card_mapping=card_mapping,
                            print_mapping=print_mapping,
                            cardmarket_mapping=cardmarket_mapping,
                            cardmarket_reference=item.cardmarket_reference,
                        ),
                        timeout=price_lookup_timeout_seconds,
                    )
                except asyncio.TimeoutError as exc:
                    primary_provider_error = RuntimeError(
                        f"Price provider '{provider.provider_key}' timeout after {price_lookup_timeout_seconds}s"
                    )
                    logger.warning("%s for inventory item %s", primary_provider_error, item.id)
                except Exception as exc:
                    primary_provider_error = exc
                    logger.warning(
                        "Price provider '%s' failed for inventory item %s: %s",
                        provider.provider_key,
                        item.id,
                        exc,
                    )

                if snapshot is None and primary_provider_error:
                    raise primary_provider_error
                if not snapshot:
                    logger.warning("Price provider returned no snapshot for inventory item %s", item.id)
                    unresolved += 1
                    processed_items += 1
                    failed_items_progress += 1
                    await refresh_price_monitor_state(
                        db,
                        item,
                        history=item.price_history,
                        current_price=_as_float(item.current_market_price),
                        current_currency=item.current_price_currency,
                        checked_at=now,
                    )
                    await _persist_job_progress(
                        job_id,
                        processed_items=processed_items,
                        successful_items=successful_items,
                        failed_items=failed_items_progress,
                        next_scheduled_item_at=(now + timedelta(seconds=12)) if is_manual_trigger and i < len(items) - 1 else None,
                    )
                    continue

                logger.info(
                    "Price snapshot for inventory item %s (%s): match=%s source=%s price=%s%s",
                    item.id,
                    item.card_print.card.name,
                    snapshot.match_quality,
                    snapshot.source_key,
                    snapshot.market_price,
                    f" {snapshot.currency}" if snapshot.market_price is not None else "",
                )

                item.last_price_source = snapshot.source_key
                item.last_priced_at = now
                item.last_price_match_quality = snapshot.match_quality
                item.last_price_note = snapshot.note
                resolved_match_quality = snapshot.indicators.get("resolved_cardmarket_match_quality") or snapshot.match_quality
                has_verified_cardmarket_product = str(resolved_match_quality or "") in CARDMARKET_SAFE_MATCH_QUALITIES
                if has_verified_cardmarket_product and snapshot.cardmarket_reference:
                    item.cardmarket_reference = snapshot.cardmarket_reference
                resolved_product_url = snapshot.indicators.get("resolved_cardmarket_product_url")
                if not resolved_product_url and has_verified_cardmarket_product and snapshot.cardmarket_reference:
                    resolved_product_url = snapshot.cardmarket_reference
                if has_verified_cardmarket_product and resolved_product_url:
                    item.card_print.cardmarket_product_url = str(resolved_product_url)
                resolved_product_slug = snapshot.indicators.get("resolved_cardmarket_product_slug")
                if has_verified_cardmarket_product and resolved_product_slug:
                    item.card_print.cardmarket_product_slug = str(resolved_product_slug)
                resolved_set_slug = snapshot.indicators.get("resolved_cardmarket_set_slug")
                if has_verified_cardmarket_product and resolved_set_slug:
                    item.card_print.cardmarket_set_slug = str(resolved_set_slug)
                resolved_product_name = snapshot.indicators.get("resolved_cardmarket_product_name")
                if has_verified_cardmarket_product and resolved_product_name:
                    item.card_print.cardmarket_product_name = str(resolved_product_name)
                resolved_set_name = snapshot.indicators.get("resolved_cardmarket_set_name")
                if has_verified_cardmarket_product and resolved_set_name:
                    item.card_print.cardmarket_set_name = str(resolved_set_name)
                resolved_variant_name = snapshot.indicators.get("resolved_cardmarket_variant_name")
                if has_verified_cardmarket_product and resolved_variant_name:
                    item.card_print.cardmarket_variant_name = str(resolved_variant_name)
                if has_verified_cardmarket_product and resolved_match_quality:
                    item.card_print.cardmarket_match_quality = str(resolved_match_quality)
                resolved_verified_at = snapshot.indicators.get("resolved_cardmarket_verified_at")
                if has_verified_cardmarket_product and isinstance(resolved_verified_at, str) and resolved_verified_at:
                    try:
                        item.card_print.cardmarket_verified_at = datetime.fromisoformat(resolved_verified_at)
                    except ValueError:
                        logger.warning("Invalid resolved_cardmarket_verified_at for inventory item %s: %s", item.id, resolved_verified_at)

                if snapshot.market_price is None:
                    logger.warning(
                        "Price update skipped for inventory item %s (%s): %s",
                        item.id,
                        item.card_print.card.name,
                        snapshot.note or snapshot.match_quality or "no price",
                    )
                    unresolved += 1
                    processed_items += 1
                    failed_items_progress += 1
                    await refresh_price_monitor_state(
                        db,
                        item,
                        history=item.price_history,
                        current_price=_as_float(item.current_market_price),
                        current_currency=item.current_price_currency,
                        checked_at=now,
                    )
                    await _persist_job_progress(
                        job_id,
                        processed_items=processed_items,
                        successful_items=successful_items,
                        failed_items=failed_items_progress,
                        next_scheduled_item_at=(now + timedelta(seconds=12)) if is_manual_trigger and i < len(items) - 1 else None,
                    )
                    continue

                item.current_market_price = snapshot.market_price
                item.current_price_currency = snapshot.currency
                price_history_entry = PriceHistory(
                    inventory_item_id=item.id,
                    card_print_id=item.card_print_id,
                    provider_key=snapshot.provider_key,
                    metric="market",
                    currency=snapshot.currency,
                    price=snapshot.market_price,
                    payload=snapshot.indicators,
                    captured_at=now,
                )
                db.add(price_history_entry)

                external_id = snapshot.indicators.get("external_id")
                if external_id:
                    card_mapping = await _find_mapping(db, "card", card.id, provider.provider_key)
                    if not card_mapping:
                        card_mapping = SourceMapping(
                            target_type="card",
                            target_id=card.id,
                            provider_key=provider.provider_key,
                            external_id=str(external_id),
                        )
                        db.add(card_mapping)
                    card_mapping.external_id = str(external_id)
                    card_mapping.last_synced_at = datetime.utcnow()

                await refresh_price_monitor_state(
                    db,
                    item,
                    history=[price_history_entry, *item.price_history],
                    current_price=_as_float(snapshot.market_price),
                    current_currency=snapshot.currency,
                    checked_at=now,
                )
                updated += 1
                processed_items += 1
                successful_items += 1
                await _persist_job_progress(
                    job_id,
                    processed_items=processed_items,
                    successful_items=successful_items,
                    failed_items=failed_items_progress,
                    next_scheduled_item_at=(now + timedelta(seconds=12)) if is_manual_trigger and i < len(items) - 1 else None,
                )
            except Exception as exc:
                logger.exception("Price update failed for inventory item %s: %s", item.id, exc)
                unresolved += 1
                failed += 1
                processed_items += 1
                failed_items_progress += 1
                await record_price_monitor_failure(db, item, error_message=str(exc), checked_at=now)
                await _persist_job_progress(
                    job_id,
                    processed_items=processed_items,
                    successful_items=successful_items,
                    failed_items=failed_items_progress,
                    next_scheduled_item_at=(now + timedelta(seconds=12)) if is_manual_trigger and i < len(items) - 1 else None,
                )

    await _run_trend_rebuild()
    logger.info("Completed price update for %s item(s), unresolved=%s", updated, unresolved)
    return {
        "updated_items": updated,
        "unresolved_items": unresolved,
        "requested_inventory_items": len(inventory_item_ids),
        "requested_card_prints": len(card_print_ids),
        "matched_items": updated + unresolved,
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
            asset.downloaded_at = datetime.utcnow()
            card_print.remote_image_url = image_payload.remote_url
            downloaded += 1

    logger.info("Image sync downloaded %s image(s)", downloaded)
    return {"downloaded_images": downloaded}


def _price_change(history: list[PriceHistory], days: int) -> float:
    if len(history) < 2:
        return 0.0
    cutoff = datetime.utcnow() - timedelta(days=days)
    latest = float(history[0].price)
    baseline = None
    for entry in history:
        if entry.captured_at <= cutoff:
            baseline = float(entry.price)
            break
    if baseline in (None, 0):
        baseline = float(history[-1].price)
    if not baseline:
        return 0.0
    return round(((latest - baseline) / baseline) * 100, 2)


async def _run_trend_rebuild(payload: dict | None = None) -> dict:
    del payload
    recalculated = 0
    async with session_scope() as db:
        result = await db.execute(select(InventoryItem).options(selectinload(InventoryItem.price_history)).order_by(InventoryItem.id.asc()))
        items = result.scalars().unique().all()
        for item in items:
            history = sorted(item.price_history, key=lambda entry: entry.captured_at, reverse=True)
            item.price_change_7d = _price_change(history, 7)
            item.price_change_30d = _price_change(history, 30)
            item.trend_score = round((item.price_change_7d or 0) * 0.7 + (item.price_change_30d or 0) * 0.3, 2)
            recalculated += 1

    logger.info("Trend rebuild recalculated %s inventory item(s)", recalculated)
    return {"recalculated_items": recalculated}
