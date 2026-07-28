from __future__ import annotations

import asyncio
import logging
import math
import random
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import session_scope
from app.integrations.prices import get_active_price_provider
from app.models import InventoryItem, PriceMonitorState, SyncJob
from app.services.price_monitor import PRICE_STATE_HIGH_VOLATILITY, PRICE_STATE_NEW, PRICE_STATE_RETRY, PRICE_STATE_VOLATILE
from app.services.sync import _extract_price_targets, queue_price_update_job, queue_sync_job
from app.time_utils import utc_now


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


def _schedule_map() -> dict[str, int]:
    return {
        "image_sync": settings.image_sync_interval_minutes,
        "trend_rebuild": settings.trend_sync_interval_minutes,
        "card_data_sync": settings.card_data_sync_interval_minutes,
    }


def _night_window_bounds(now: datetime) -> tuple[datetime, datetime]:
    start_hour = settings.price_monitor_night_window_start_hour
    end_hour = settings.price_monitor_night_window_end_hour

    start = now.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    end = now.replace(hour=end_hour, minute=0, second=0, microsecond=0)

    if start_hour < end_hour:
        if now < start:
            return start, end
        if now >= end:
            return start + timedelta(days=1), end + timedelta(days=1)
        return start, end

    if now >= start:
        return start, end + timedelta(days=1)
    if now < end:
        return start - timedelta(days=1), end
    return start, end + timedelta(days=1)


def _request_spacing_seconds() -> int:
    per_minute = max(1, settings.price_monitor_max_requests_per_minute)
    per_hour = max(1, settings.price_monitor_max_requests_per_hour)
    return max(15, math.ceil(60 / per_minute), math.ceil(3600 / per_hour))


async def _active_price_job_targets() -> tuple[set[int], set[int], datetime | None, bool]:
    async with session_scope() as db:
        result = await db.execute(
            select(SyncJob)
            .where(SyncJob.job_type == "price_update", SyncJob.status.in_(["pending", "running"]))
            .order_by(SyncJob.priority.desc(), SyncJob.created_at.asc(), SyncJob.id.asc())
        )
        inventory_item_ids: set[int] = set()
        card_print_ids: set[int] = set()
        latest_available_at: datetime | None = None
        has_global_job = False
        for job in result.scalars().all():
            active_inventory_ids, active_print_ids = _extract_price_targets(job.payload)
            has_global_job = has_global_job or not active_inventory_ids and not active_print_ids
            inventory_item_ids.update(active_inventory_ids)
            card_print_ids.update(active_print_ids)
            if job.available_at and (latest_available_at is None or job.available_at > latest_available_at):
                latest_available_at = job.available_at
        return inventory_item_ids, card_print_ids, latest_available_at, has_global_job


async def _enqueue_due_price_monitor_jobs() -> int:
    now = utc_now()
    provider = get_active_price_provider()
    if provider is None:
        logger.error("Price scheduler is disabled because PRICE_PROVIDER=%s is unknown.", settings.price_provider)
        return 0
    if provider.provider_key == "cardmarket":
        logger.error("Price scheduler is disabled because Cardmarket is configured for manual prices only.")
        return 0

    active_inventory_ids, active_print_ids, latest_available_at, has_global_job = await _active_price_job_targets()
    if has_global_job:
        return 0

    night_start, _night_end = _night_window_bounds(now)

    async with session_scope() as db:
        stmt = (
            select(PriceMonitorState)
            .join(PriceMonitorState.inventory_item)
            .options(
                selectinload(PriceMonitorState.inventory_item),
            )
            .where(
                or_(
                    PriceMonitorState.next_price_check_at.is_(None),
                    PriceMonitorState.next_price_check_at <= now,
                )
            )
            .order_by(
                PriceMonitorState.price_check_priority.desc(),
                PriceMonitorState.next_price_check_at.asc().nullsfirst(),
                PriceMonitorState.inventory_item_id.asc(),
            )
        )
        if active_inventory_ids:
            stmt = stmt.where(~PriceMonitorState.inventory_item_id.in_(active_inventory_ids))
        if active_print_ids:
            stmt = stmt.where(~InventoryItem.card_print_id.in_(active_print_ids))
        stmt = stmt.limit(settings.price_monitor_scheduler_batch_size)

        result = await db.execute(stmt)
        states = result.scalars().all()
        due_entries = [
            {
                "state_id": state.id,
                "inventory_item_id": state.inventory_item.id,
                "card_print_id": state.inventory_item.card_print_id,
                "state": state.price_stability_state or PRICE_STATE_NEW,
                "priority": state.price_check_priority or 0,
            }
            for state in states
        ]

    if not due_entries:
        return 0

    enqueued_state_ids: list[int] = []
    enqueued_jobs = 0
    if provider.provider_key != "cardmarket":
        batches: dict[str, list[dict[str, int | str]]] = {"urgent": [], "night": []}
        for entry in due_entries:
            urgent = entry["state"] in {
                PRICE_STATE_NEW,
                PRICE_STATE_RETRY,
                PRICE_STATE_VOLATILE,
                PRICE_STATE_HIGH_VOLATILITY,
            } or int(entry["priority"]) >= settings.price_monitor_volatile_priority
            batches["urgent" if urgent else "night"].append(entry)

        for batch_name, batch_entries in batches.items():
            if not batch_entries:
                continue
            available_at = now if batch_name == "urgent" else max(now, night_start) + timedelta(
                seconds=random.randint(0, max(0, settings.price_monitor_jitter_seconds))
            )
            job = await queue_price_update_job(
                inventory_item_ids=[int(entry["inventory_item_id"]) for entry in batch_entries],
                card_print_ids=[int(entry["card_print_id"]) for entry in batch_entries],
                trigger="scheduler",
                reason=f"monitor_batch:{batch_name}",
                available_at=available_at,
                priority=max(int(entry["priority"]) for entry in batch_entries),
            )
            enqueued_state_ids.extend(int(entry["state_id"]) for entry in batch_entries)
            enqueued_jobs += 1
            logger.info(
                "Scheduled batched %s price job %s for %s item(s) at %s.",
                provider.provider_key,
                job.id,
                len(batch_entries),
                available_at.isoformat(),
            )
    else:
        spacing_seconds = _request_spacing_seconds()
        next_slot_at = max(now, (latest_available_at + timedelta(seconds=spacing_seconds)) if latest_available_at else now)
        for entry in due_entries:
            urgent = entry["state"] in {
                PRICE_STATE_NEW,
                PRICE_STATE_RETRY,
                PRICE_STATE_VOLATILE,
                PRICE_STATE_HIGH_VOLATILITY,
            } or int(entry["priority"]) >= settings.price_monitor_volatile_priority
            base_slot_at = next_slot_at if urgent else max(night_start, next_slot_at)
            available_at = base_slot_at + timedelta(
                seconds=random.randint(0, max(0, settings.price_monitor_jitter_seconds))
            )
            job = await queue_price_update_job(
                inventory_item_ids=[int(entry["inventory_item_id"])],
                card_print_ids=[int(entry["card_print_id"])],
                trigger="scheduler",
                reason=f"state:{entry['state']}",
                available_at=available_at,
                priority=int(entry["priority"]),
            )
            enqueued_state_ids.append(int(entry["state_id"]))
            enqueued_jobs += 1
            next_slot_at = base_slot_at + timedelta(seconds=spacing_seconds)
            logger.info(
                "Scheduled Cardmarket price job %s for inventory item %s at %s.",
                job.id,
                entry["inventory_item_id"],
                available_at.isoformat(),
            )

    if enqueued_state_ids:
        async with session_scope() as db:
            result = await db.execute(
                select(PriceMonitorState).where(PriceMonitorState.id.in_(enqueued_state_ids))
            )
            for state in result.scalars().all():
                state.last_enqueued_at = now

    return enqueued_jobs


async def run_scheduler() -> None:
    intervals = _schedule_map()
    next_run = {
        job_type: utc_now() + timedelta(minutes=minutes)
        for job_type, minutes in intervals.items()
        if minutes > 0
    }
    logger.info("Starting sync scheduler with jobs: %s", next_run)

    while True:
        try:
            enqueued_price_jobs = await _enqueue_due_price_monitor_jobs()
            if enqueued_price_jobs:
                logger.info("Enqueued %s due price monitor job(s)", enqueued_price_jobs)

            now = utc_now()
            for job_type, scheduled_at in list(next_run.items()):
                if now < scheduled_at:
                    continue

                job = await queue_sync_job(job_type, payload={"trigger": "scheduler"})
                logger.info("Scheduled %s job %s", job_type, job.id)
                next_run[job_type] = now + timedelta(minutes=intervals[job_type])
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unexpected error in sync scheduler loop")

        await asyncio.sleep(settings.sync_scheduler_poll_seconds)


def main() -> None:
    asyncio.run(run_scheduler())


if __name__ == "__main__":
    main()
