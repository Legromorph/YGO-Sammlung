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
from app.models import InventoryItem, PriceMonitorState, SyncJob
from app.services.price_monitor import PRICE_STATE_HIGH_VOLATILITY, PRICE_STATE_NEW, PRICE_STATE_RETRY, PRICE_STATE_VOLATILE
from app.services.sync import _extract_price_targets, queue_price_update_job, queue_sync_job


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


async def _active_price_job_targets() -> tuple[set[int], set[int], datetime | None]:
    async with session_scope() as db:
        result = await db.execute(
            select(SyncJob)
            .where(SyncJob.job_type == "price_update", SyncJob.status.in_(["pending", "running"]))
            .order_by(SyncJob.priority.desc(), SyncJob.created_at.asc(), SyncJob.id.asc())
        )
        inventory_item_ids: set[int] = set()
        card_print_ids: set[int] = set()
        latest_available_at: datetime | None = None
        for job in result.scalars().all():
            active_inventory_ids, active_print_ids = _extract_price_targets(job.payload)
            inventory_item_ids.update(active_inventory_ids)
            card_print_ids.update(active_print_ids)
            if job.available_at and (latest_available_at is None or job.available_at > latest_available_at):
                latest_available_at = job.available_at
        return inventory_item_ids, card_print_ids, latest_available_at


async def _enqueue_due_price_monitor_jobs() -> int:
    now = datetime.utcnow()
    active_inventory_ids, _active_print_ids, latest_available_at = await _active_price_job_targets()
    spacing_seconds = _request_spacing_seconds()
    night_start, _night_end = _night_window_bounds(now)
    next_slot_at = max(now, (latest_available_at + timedelta(seconds=spacing_seconds)) if latest_available_at else now)

    enqueued = 0
    async with session_scope() as db:
        result = await db.execute(
            select(PriceMonitorState)
            .join(PriceMonitorState.inventory_item)
            .options(
                selectinload(PriceMonitorState.inventory_item).selectinload(InventoryItem.card_print),
                selectinload(PriceMonitorState.inventory_item).selectinload(InventoryItem.price_history),
                selectinload(PriceMonitorState.inventory_item).selectinload(InventoryItem.price_monitor_state),
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
            .limit(settings.price_monitor_scheduler_batch_size)
        )
        states = result.scalars().all()
        if not states:
            return 0

        for state in states:
            item = state.inventory_item
            if item.id in active_inventory_ids:
                continue

            urgency_state = state.price_stability_state or PRICE_STATE_NEW
            urgent = urgency_state in {PRICE_STATE_NEW, PRICE_STATE_RETRY, PRICE_STATE_VOLATILE, PRICE_STATE_HIGH_VOLATILITY} or (state.price_check_priority or 0) >= settings.price_monitor_volatile_priority

            base_slot_at = next_slot_at if urgent else max(night_start, next_slot_at)
            jitter = timedelta(seconds=random.randint(0, max(0, settings.price_monitor_jitter_seconds)))
            available_at = base_slot_at + jitter

            job = await queue_price_update_job(
                inventory_item_ids=[item.id],
                card_print_ids=[item.card_print_id],
                trigger="scheduler",
                reason=f"state:{urgency_state}",
                available_at=available_at,
                priority=state.price_check_priority or 0,
            )
            state.last_enqueued_at = now
            enqueued += 1
            next_slot_at = base_slot_at + timedelta(seconds=spacing_seconds)

            logger.info(
                "Scheduled price update job %s for inventory item %s at %s (state=%s priority=%s)",
                job.id,
                item.id,
                available_at.isoformat(),
                urgency_state,
                state.price_check_priority or 0,
            )

    return enqueued


async def run_scheduler() -> None:
    intervals = _schedule_map()
    next_run = {
        job_type: datetime.utcnow() + timedelta(minutes=minutes)
        for job_type, minutes in intervals.items()
        if minutes > 0
    }
    logger.info("Starting sync scheduler with jobs: %s", next_run)

    while True:
        try:
            enqueued_price_jobs = await _enqueue_due_price_monitor_jobs()
            if enqueued_price_jobs:
                logger.info("Enqueued %s due price monitor job(s)", enqueued_price_jobs)

            now = datetime.utcnow()
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
