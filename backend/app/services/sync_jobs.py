from __future__ import annotations

import json
import logging
import traceback
import asyncio
from datetime import datetime, timedelta
from typing import Awaitable, Callable

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import session_scope
from app.integrations.card_data import get_card_data_provider
from app.integrations.images import get_active_image_provider
from app.integrations.prices import get_active_price_provider, get_price_providers
from app.integrations.ygo_omega import get_ygo_omega_probe
from app.models import InventoryItem, SourceMapping, SyncJob
from app.schemas import ProviderStatus, SyncJobResponse
from app.time_utils import utc_now

logger = logging.getLogger(__name__)

JOB_PROVIDER_MAP = {
    "price_update": "ygoprodeck",
    "image_sync": "ygoprodeck",
    "trend_rebuild": "internal",
    "card_data_sync": "ygoprodeck",
}
JOB_LOG_MAX_CHARS = 250_000
JOB_LOG_EXCERPT_LIMIT = 220

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
    del payload
    # Price providers share external rate limits. One lock serializes all price
    # jobs even when they target different inventory items.
    return f"{job_type}:global"

def _merge_price_job_payload(existing_payload: dict | None, incoming_payload: dict | None) -> dict:
    existing_payload = dict(existing_payload or {})
    incoming_payload = dict(incoming_payload or {})
    merged = {**existing_payload, **incoming_payload}

    for key in ("inventory_item_ids", "card_print_ids"):
        target_ids = _normalize_target_ids(
            [
                *(existing_payload.get(key) or []),
                *(incoming_payload.get(key) or []),
            ]
        )
        if target_ids:
            merged[key] = target_ids
        else:
            merged.pop(key, None)
    return merged

def _job_health(job: SyncJob, now: datetime | None = None) -> tuple[bool, str | None]:
    now = now or utc_now()
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

def _format_job_log_value(value: object) -> str:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)

def _trim_job_excerpt(value: str | None) -> str | None:
    if not value:
        return None
    compact = " ".join(str(value).split())
    if len(compact) <= JOB_LOG_EXCERPT_LIMIT:
        return compact
    return f"{compact[:JOB_LOG_EXCERPT_LIMIT - 3].rstrip()}..."

def _render_job_log_entry(level: str, message: str, *, context: dict[str, object] | None = None) -> str:
    timestamp = utc_now().isoformat(timespec="seconds").replace("+00:00", "Z")
    lines = [f"[{timestamp}] {level.upper():<7} {message}"]
    for key, value in (context or {}).items():
        if value in (None, "", [], {}, ()):
            continue
        rendered = _format_job_log_value(value)
        if "\n" in rendered:
            lines.append(f"  {key}:")
            lines.extend(f"    {line}" for line in rendered.splitlines())
        else:
            lines.append(f"  {key}: {rendered}")
    return "\n".join(lines)

def _append_job_log_blob(existing: str | None, entry: str) -> str:
    combined = entry if not existing else f"{existing.rstrip()}\n\n{entry}"
    if len(combined) <= JOB_LOG_MAX_CHARS:
        return combined

    overflow_notice = "[... older job log lines truncated ...]\n"
    kept_length = max(0, JOB_LOG_MAX_CHARS - len(overflow_notice))
    trimmed = combined[-kept_length:].lstrip()
    return f"{overflow_notice}{trimmed}"

def _apply_job_log_update(
    job: SyncJob,
    *,
    level: str,
    message: str,
    context: dict[str, object] | None = None,
    excerpt: str | None = None,
    reset: bool = False,
) -> None:
    entry = _render_job_log_entry(level, message, context=context)
    job.log_details = entry if reset else _append_job_log_blob(job.log_details, entry)
    trimmed_excerpt = _trim_job_excerpt(excerpt)
    if trimmed_excerpt is not None:
        job.log_excerpt = trimmed_excerpt

async def _append_job_log(
    job_id: int | None,
    message: str,
    *,
    level: str = "INFO",
    context: dict[str, object] | None = None,
    excerpt: str | None = None,
) -> None:
    if not job_id:
        return
    async with session_scope() as db:
        job = await db.get(SyncJob, job_id)
        if not job:
            return
        _apply_job_log_update(job, level=level, message=message, context=context, excerpt=excerpt)

def _build_price_item_context(
    item: InventoryItem,
    *,
    provider_key: str,
    card_mapping: SourceMapping | None = None,
    print_mapping: SourceMapping | None = None,
    cardmarket_mapping: SourceMapping | None = None,
) -> dict[str, object]:
    return {
        "provider": provider_key,
        "inventory_item_id": item.id,
        "card_print_id": item.card_print_id,
        "card_id": item.card_print.card.id,
        "card_name": item.card_print.card.name,
        "set_name": item.card_print.set_name,
        "set_code": item.card_print.set_code,
        "card_number": item.card_print.card_number,
        "rarity": item.card_print.rarity,
        "language": item.card_print.language,
        "condition": item.condition,
        "stored_cardmarket_reference": item.cardmarket_reference,
        "stored_cardmarket_product_url": item.card_print.cardmarket_product_url,
        "stored_cardmarket_match_quality": item.card_print.cardmarket_match_quality,
        "provider_card_mapping": card_mapping.external_id if card_mapping else None,
        "provider_print_mapping": print_mapping.external_id if print_mapping else None,
        "cardmarket_mapping": cardmarket_mapping.external_id if cardmarket_mapping else None,
    }

def _build_snapshot_log_context(snapshot: object) -> dict[str, object]:
    indicators = getattr(snapshot, "indicators", {}) or {}
    return {
        "source_key": getattr(snapshot, "source_key", None),
        "provider_key": getattr(snapshot, "provider_key", None),
        "market_price": getattr(snapshot, "market_price", None),
        "currency": getattr(snapshot, "currency", None),
        "match_quality": getattr(snapshot, "match_quality", None),
        "note": getattr(snapshot, "note", None),
        "cardmarket_reference": getattr(snapshot, "cardmarket_reference", None),
        "provider_diagnostics": indicators.get("provider_diagnostics"),
        "snapshot_indicators": indicators,
    }

def _build_completion_excerpt(summary: dict) -> str:
    parts: list[str] = []
    for key, label in (
        ("updated_items", "aktualisiert"),
        ("unresolved_items", "offen"),
        ("failed_items", "fehlerhaft"),
        ("matched_items", "treffer"),
        ("downloaded_images", "Bilder"),
        ("synced_cards", "Karten"),
        ("recalculated_items", "neu berechnet"),
    ):
        value = summary.get(key)
        if isinstance(value, int):
            parts.append(f"{value} {label}")
    if not parts:
        return "Job abgeschlossen."
    return f"Abgeschlossen: {', '.join(parts)}."

def serialize_sync_job(job: SyncJob, *, include_details: bool = False) -> SyncJobResponse:
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
        log_details=job.log_details if include_details else None,
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
                SyncJob.created_at >= utc_now() - timedelta(hours=1),
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
                        existing.payload = _merge_price_job_payload(existing.payload, payload)
                        updated_existing = True
                    if updated_existing and existing.status == "pending":
                        _apply_job_log_update(
                            existing,
                            level="INFO",
                            message="Pending job was rescheduled by a newer price update request.",
                            context={
                                "lock_key": existing.lock_key,
                                "priority": existing.priority,
                                "available_at": existing.available_at.isoformat() if existing.available_at else None,
                                "payload": existing.payload,
                            },
                            excerpt="Rescheduled by a newer price update request.",
                        )
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
        total_items=0,
        processed_items=0,
        successful_items=0,
        failed_items=0,
    )
    db.add(job)
    await db.flush()
    scheduled_for_future = bool(available_at and available_at > utc_now())
    _apply_job_log_update(
        job,
        level="INFO",
        message="Job scheduled for later worker claim." if scheduled_for_future else "Job queued and waiting for worker claim.",
        context={
            "job_type": job_type,
            "provider_key": provider_key,
            "lock_key": lock_key,
            "priority": priority,
            "available_at": available_at.isoformat() if available_at else None,
            "payload": payload,
        },
        excerpt=f"Scheduled for {available_at.isoformat()}." if scheduled_for_future and available_at else "Pending worker claim.",
        reset=True,
    )
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

async def get_sync_job(db: AsyncSession, job_id: int, *, include_details: bool = False) -> SyncJobResponse | None:
    job = await db.get(SyncJob, job_id)
    if not job:
        return None
    return serialize_sync_job(job, include_details=include_details)

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
            raise ValueError("Nur fehlgeschlagene Jobs können erneut gestartet werden.")

        retry_payload = dict(job.payload or {})
        retry_payload["trigger"] = "retry"
        retry_payload["retry_of"] = job.id
        retried_job, _ = await create_sync_job_record(
            db,
            job.job_type,
            force=True,
            payload=retry_payload,
            available_at=utc_now(),
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

async def _safe_provider_status(
    *,
    key: str,
    label: str,
    category: str,
    configured: bool,
    active: bool,
    healthcheck: Callable[[], Awaitable[dict]],
) -> ProviderStatus:
    try:
        timeout = max(2, settings.request_timeout_seconds + 5)
        return ProviderStatus(**await asyncio.wait_for(healthcheck(), timeout=timeout))
    except Exception as exc:
        logger.exception("Provider healthcheck failed for %s.", key)
        return ProviderStatus(
            key=key,
            label=label,
            category=category,
            configured=configured,
            available=False,
            active=active,
            notes=f"Statusprüfung fehlgeschlagen: {exc}",
        )


async def get_provider_statuses() -> list[ProviderStatus]:
    statuses = []
    for provider in get_price_providers():
        statuses.append(
            await _safe_provider_status(
                key=provider.provider_key,
                label="Printpreise via YGOPRODeck" if provider.provider_key == "ygoprodeck" else "Cardmarket (manuell)",
                category="price",
                configured=True,
                active=settings.price_provider == provider.provider_key,
                healthcheck=provider.healthcheck,
            )
        )
    card_data_provider = get_card_data_provider()
    statuses.append(
        await _safe_provider_status(
            key=card_data_provider.provider_key,
            label="YGOPRODeck",
            category="card-data",
            configured=True,
            active=settings.card_data_provider == card_data_provider.provider_key,
            healthcheck=card_data_provider.healthcheck,
        )
    )
    image_provider = get_active_image_provider()
    statuses.append(
        await _safe_provider_status(
            key=image_provider.provider_key,
            label="YGOPRODeck Images",
            category="image",
            configured=True,
            active=settings.image_provider == image_provider.provider_key,
            healthcheck=image_provider.healthcheck,
        )
    )
    ygo_omega_probe = get_ygo_omega_probe()
    statuses.append(
        await _safe_provider_status(
            key=ygo_omega_probe.provider_key,
            label="YGO Omega",
            category="card-data",
            configured=bool(settings.ygo_omega_directory),
            active=False,
            healthcheck=ygo_omega_probe.healthcheck,
        )
    )
    return statuses

async def fail_stale_running_jobs() -> int:
    cutoff = utc_now() - timedelta(minutes=settings.sync_job_running_timeout_minutes)
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
            job.completed_at = utc_now()
            job.error_message = (
                "Worker timeout: job exceeded "
                f"{settings.sync_job_running_timeout_minutes} minutes without completion."
            )
            _apply_job_log_update(
                job,
                level="ERROR",
                message="Stale running job was force-failed by timeout recovery.",
                context={
                    "started_at": job.started_at.isoformat() if job.started_at else None,
                    "timeout_minutes": settings.sync_job_running_timeout_minutes,
                },
                excerpt="Marked as failed by stale-job recovery.",
            )
            failed_count += 1

    if failed_count:
        logger.warning("Recovered %s stale running sync job(s)", failed_count)
    return failed_count

async def claim_next_sync_job(*, worker_name: str) -> SyncJob | None:
    running_lock_keys = select(SyncJob.lock_key).where(SyncJob.status == "running")
    now = utc_now()

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
        job.started_at = utc_now()
        job.completed_at = None
        job.error_message = None
        if job.total_items is None:
            job.total_items = 0
        if job.processed_items is None:
            job.processed_items = 0
        if job.successful_items is None:
            job.successful_items = 0
        if job.failed_items is None:
            job.failed_items = 0
        _apply_job_log_update(
            job,
            level="INFO",
            message="Worker claimed job.",
            context={"worker_name": worker_name},
            excerpt=f"Claimed by {worker_name}.",
        )
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
            job.started_at = utc_now()
            job.completed_at = None
            job.error_message = None
            if job.total_items is None:
                job.total_items = 0
            if job.processed_items is None:
                job.processed_items = 0
            if job.successful_items is None:
                job.successful_items = 0
            if job.failed_items is None:
                job.failed_items = 0
            _apply_job_log_update(
                job,
                level="INFO",
                message="Job was claimed for direct execution.",
                context={"worker_name": worker_name},
                excerpt=f"Claimed directly by {worker_name}.",
            )
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
        job.completed_at = utc_now()
        job.error_message = None
        _apply_job_log_update(
            job,
            level="INFO",
            message="Job completed successfully.",
            context={"summary": summary},
            excerpt=_build_completion_excerpt(summary),
        )

    logger.info("Completed job %s", job_id)

async def _fail_job(
    job_id: int,
    error_message: str,
    *,
    context: dict[str, object] | None = None,
    traceback_text: str | None = None,
) -> None:
    async with session_scope() as db:
        job = await db.get(SyncJob, job_id)
        if not job:
            logger.warning("Job %s disappeared before failure could be stored: %s", job_id, error_message)
            return
        job.status = "failed"
        job.completed_at = utc_now()
        job.error_message = error_message
        failure_context = dict(context or {})
        failure_context["error_message"] = error_message
        if traceback_text:
            failure_context["traceback"] = traceback_text
        _apply_job_log_update(
            job,
            level="ERROR",
            message="Job failed.",
            context=failure_context,
            excerpt=error_message or "Job failed.",
        )

    logger.error("Failed job %s: %s", job_id, error_message)

def _job_handlers() -> dict[str, SyncHandler]:
    from app.services.sync_tasks import (
        _run_card_data_sync,
        _run_image_sync,
        _run_price_sync,
        _run_trend_rebuild,
    )

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
        await _append_job_log(
            job_id,
            "Worker started job execution.",
            context={
                "worker_name": worker_name,
                "job_type": job_type,
                "payload": payload,
            },
            excerpt=f"Running on {worker_name}.",
        )
        summary = await handler(handler_payload)
        await _complete_job(job_id, summary)
    except Exception as exc:
        logger.exception("Exception while processing job %s of type %s", job_id, job_type)
        await _fail_job(
            job_id,
            str(exc),
            context={
                "worker_name": worker_name,
                "job_type": job_type,
                "payload": payload,
            },
            traceback_text="".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
        )

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
