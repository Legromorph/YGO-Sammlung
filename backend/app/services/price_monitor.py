from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import session_scope
from app.models import InventoryItem, PriceHistory, PriceMonitorState
from app.services.currency import convert_amount

logger = logging.getLogger(__name__)

PRICE_STATE_NEW = "new"
PRICE_STATE_STABLE = "stable"
PRICE_STATE_LOW_VALUE_STABLE = "low_value_stable"
PRICE_STATE_WATCH = "watch"
PRICE_STATE_VOLATILE = "volatile"
PRICE_STATE_HIGH_VOLATILITY = "high_volatility"
PRICE_STATE_RETRY = "retry"


@dataclass(slots=True)
class PriceMonitorPolicy:
    stability_state: str
    interval_hours: int
    priority: int
    volatility_score: float
    consecutive_stable_checks: int
    next_price_check_at: datetime


def _as_float(value: object | None) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _pct_change(previous: float | None, current: float | None) -> float | None:
    if previous in (None, 0) or current is None:
        return None
    return round(((current - previous) / previous) * 100, 2)


async def _low_value_threshold_for_currency(currency: str | None) -> float:
    base_threshold = Decimal(str(settings.price_monitor_low_value_threshold))
    converted = await convert_amount(base_threshold, "EUR", currency or "EUR")
    return float(converted) if converted is not None else float(base_threshold)


def _recent_price_samples(
    history: list[PriceHistory] | None,
    *,
    current_price: float | None,
    current_currency: str | None,
    checked_at: datetime,
) -> list[tuple[datetime, float, str]]:
    samples: list[tuple[datetime, float, str]] = []

    if current_price is not None:
        samples.append((checked_at, current_price, (current_currency or "EUR").upper()))

    skipped_duplicate_current = False
    for entry in (history or [])[:5]:
        price = _as_float(entry.price)
        if price is None:
            continue
        if (
            current_price is not None
            and not skipped_duplicate_current
            and entry.captured_at >= checked_at - timedelta(seconds=1)
            and abs(price - current_price) < 0.0001
            and (entry.currency or current_currency or "EUR").upper() == (current_currency or "EUR").upper()
        ):
            skipped_duplicate_current = True
            continue
        samples.append((entry.captured_at, price, (entry.currency or current_currency or "EUR").upper()))

    return samples


async def derive_price_monitor_policy(
    item: InventoryItem,
    *,
    history: list[PriceHistory] | None = None,
    current_price: float | None = None,
    current_currency: str | None = None,
    state: PriceMonitorState | None = None,
    checked_at: datetime | None = None,
) -> PriceMonitorPolicy:
    checked_at = checked_at or datetime.utcnow()
    current_price = _as_float(current_price if current_price is not None else item.current_market_price)
    current_currency = (current_currency or item.current_price_currency or "EUR").upper()
    samples = _recent_price_samples(history, current_price=current_price, current_currency=current_currency, checked_at=checked_at)

    if not samples:
        interval_hours = settings.price_monitor_min_interval_hours
        next_price_check_at = checked_at + timedelta(hours=interval_hours)
        return PriceMonitorPolicy(
            stability_state=PRICE_STATE_NEW,
            interval_hours=interval_hours,
            priority=settings.price_monitor_new_priority,
            volatility_score=0,
            consecutive_stable_checks=0,
            next_price_check_at=next_price_check_at,
        )

    latest_price = samples[0][1]
    latest_currency = samples[0][2]
    pair_changes: list[float] = []
    for index in range(len(samples) - 1):
        change = _pct_change(samples[index + 1][1], samples[index][1])
        if change is not None:
            pair_changes.append(abs(change))

    recent_baseline_samples = [sample[1] for sample in samples[1:5]]
    cluster_reference = median(recent_baseline_samples) if recent_baseline_samples else latest_price
    cluster_change = abs(_pct_change(cluster_reference, latest_price) or 0.0)
    volatility_score = round(max([cluster_change, *pair_changes]) if pair_changes else cluster_change, 2)

    low_value_threshold = await _low_value_threshold_for_currency(latest_currency)
    is_low_value = latest_price <= low_value_threshold
    stable_small_change = (pair_changes[0] if pair_changes else 0.0) <= settings.price_monitor_stable_change_threshold
    strong_changes = sum(1 for change in pair_changes if change >= settings.price_monitor_volatile_change_threshold)
    very_strong_changes = sum(1 for change in pair_changes if change >= settings.price_monitor_high_volatility_change_threshold)

    if is_low_value and len(samples) >= 2 and all(change <= settings.price_monitor_stable_change_threshold for change in pair_changes[:3]):
        consecutive_stable_checks = (state.consecutive_stable_checks if state and state.price_stability_state == PRICE_STATE_LOW_VALUE_STABLE else 0) + 1
        interval_hours = settings.price_monitor_very_stable_interval_hours if consecutive_stable_checks >= settings.price_monitor_low_value_checks_for_very_stable else settings.price_monitor_stable_interval_hours
        stability_state = PRICE_STATE_LOW_VALUE_STABLE
        priority = settings.price_monitor_low_value_priority
    elif volatility_score >= settings.price_monitor_high_volatility_change_threshold or very_strong_changes >= 2:
        consecutive_stable_checks = 0
        interval_hours = settings.price_monitor_min_interval_hours
        stability_state = PRICE_STATE_HIGH_VOLATILITY
        priority = settings.price_monitor_high_volatility_priority
    elif volatility_score >= settings.price_monitor_volatile_change_threshold or strong_changes >= 2:
        consecutive_stable_checks = 0
        interval_hours = settings.price_monitor_volatile_interval_hours
        stability_state = PRICE_STATE_VOLATILE
        priority = settings.price_monitor_volatile_priority
    elif volatility_score >= settings.price_monitor_watch_change_threshold:
        consecutive_stable_checks = 0
        interval_hours = settings.price_monitor_default_interval_hours
        stability_state = PRICE_STATE_WATCH
        priority = settings.price_monitor_watch_priority
    else:
        consecutive_stable_checks = (state.consecutive_stable_checks if state and state.price_stability_state in {PRICE_STATE_STABLE, PRICE_STATE_WATCH} and stable_small_change else 0) + 1
        interval_hours = settings.price_monitor_default_interval_hours
        stability_state = PRICE_STATE_STABLE
        priority = settings.price_monitor_stable_priority

    next_price_check_at = checked_at + timedelta(hours=interval_hours)
    return PriceMonitorPolicy(
        stability_state=stability_state,
        interval_hours=interval_hours,
        priority=priority,
        volatility_score=volatility_score,
        consecutive_stable_checks=consecutive_stable_checks,
        next_price_check_at=next_price_check_at,
    )


async def ensure_initial_price_monitor_state(
    db: AsyncSession,
    item: InventoryItem,
    *,
    now: datetime | None = None,
) -> PriceMonitorState:
    now = now or datetime.utcnow()
    result = await db.execute(select(PriceMonitorState).where(PriceMonitorState.inventory_item_id == item.id).limit(1))
    state = result.scalar_one_or_none()
    if state:
        return state

    state = PriceMonitorState(
        inventory_item_id=item.id,
        last_price_check_at=None,
        next_price_check_at=now,
        price_check_interval_hours=settings.price_monitor_min_interval_hours,
        price_volatility_score=0,
        price_check_priority=settings.price_monitor_new_priority,
        price_stability_state=PRICE_STATE_NEW,
        failure_count=0,
        consecutive_stable_checks=0,
        last_enqueued_at=now,
        last_error_message=None,
    )
    db.add(state)
    await db.flush()
    logger.info("Created initial price monitor state for inventory item %s", item.id)
    return state


async def refresh_price_monitor_state(
    db: AsyncSession,
    item: InventoryItem,
    *,
    history: list[PriceHistory] | None = None,
    current_price: float | None = None,
    current_currency: str | None = None,
    checked_at: datetime | None = None,
) -> PriceMonitorState:
    checked_at = checked_at or datetime.utcnow()
    result = await db.execute(select(PriceMonitorState).where(PriceMonitorState.inventory_item_id == item.id).limit(1))
    state = result.scalar_one_or_none()
    if not state:
        state = PriceMonitorState(inventory_item_id=item.id)
        db.add(state)

    policy = await derive_price_monitor_policy(
        item,
        history=history or item.price_history,
        current_price=current_price,
        current_currency=current_currency,
        state=state,
        checked_at=checked_at,
    )

    state.last_price_check_at = checked_at
    state.next_price_check_at = policy.next_price_check_at
    state.price_check_interval_hours = policy.interval_hours
    state.price_volatility_score = policy.volatility_score
    state.price_check_priority = policy.priority
    state.price_stability_state = policy.stability_state
    state.consecutive_stable_checks = policy.consecutive_stable_checks
    state.failure_count = 0
    state.last_error_message = None
    await db.flush()
    logger.info(
        "Updated price monitor state for inventory item %s: state=%s interval=%sh volatility=%s",
        item.id,
        state.price_stability_state,
        state.price_check_interval_hours,
        state.price_volatility_score,
    )
    return state


async def record_price_monitor_failure(
    db: AsyncSession,
    item: InventoryItem,
    *,
    error_message: str,
    checked_at: datetime | None = None,
) -> PriceMonitorState:
    checked_at = checked_at or datetime.utcnow()
    result = await db.execute(select(PriceMonitorState).where(PriceMonitorState.inventory_item_id == item.id).limit(1))
    state = result.scalar_one_or_none()
    if not state:
        state = PriceMonitorState(inventory_item_id=item.id)
        db.add(state)

    failure_count = (state.failure_count or 0) + 1
    base_interval = state.price_check_interval_hours or settings.price_monitor_default_interval_hours
    backoff_hours = min(
        settings.price_monitor_max_interval_hours,
        max(settings.price_monitor_min_interval_hours, base_interval * (2 ** min(failure_count - 1, 3))),
    )

    state.last_price_check_at = checked_at
    state.next_price_check_at = checked_at + timedelta(hours=backoff_hours)
    state.price_check_interval_hours = backoff_hours
    state.price_volatility_score = max(float(state.price_volatility_score or 0), 100.0)
    state.price_check_priority = max(state.price_check_priority or 0, settings.price_monitor_retry_priority)
    state.price_stability_state = PRICE_STATE_RETRY
    state.failure_count = failure_count
    state.consecutive_stable_checks = 0
    state.last_error_message = error_message
    await db.flush()
    logger.warning(
        "Price monitor failure for inventory item %s: failure_count=%s backoff=%sh error=%s",
        item.id,
        state.failure_count,
        state.price_check_interval_hours,
        error_message,
    )
    return state


def build_price_monitor_status(
    item: InventoryItem,
    *,
    active_job: Any | None = None,
) -> dict[str, Any]:
    state = item.price_monitor_state
    latest_history = max(item.price_history, key=lambda entry: entry.captured_at) if item.price_history else None

    last_price_check_at = None
    next_price_check_at = None
    interval_hours = settings.price_monitor_default_interval_hours
    volatility_score = float(abs(item.trend_score or 0))
    priority = settings.price_monitor_stable_priority
    stability_state = PRICE_STATE_NEW if item.current_market_price is None and not latest_history else PRICE_STATE_STABLE
    failure_count = 0
    consecutive_stable_checks = 0
    last_error_message = None

    if state:
        last_price_check_at = state.last_price_check_at
        next_price_check_at = state.next_price_check_at
        interval_hours = state.price_check_interval_hours or interval_hours
        volatility_score = float(state.price_volatility_score or volatility_score)
        priority = state.price_check_priority or priority
        stability_state = state.price_stability_state or stability_state
        failure_count = state.failure_count or 0
        consecutive_stable_checks = state.consecutive_stable_checks or 0
        last_error_message = state.last_error_message
    else:
        last_price_check_at = item.last_priced_at or (latest_history.captured_at if latest_history else None)
        if last_price_check_at:
            next_price_check_at = last_price_check_at + timedelta(hours=interval_hours)

    if active_job is not None:
        stability_state = "updating"

    return {
        "status": stability_state,
        "is_updating": active_job is not None,
        "pending_job_id": active_job.id if active_job else None,
        "match_quality": item.last_price_match_quality,
        "source": item.last_price_source,
        "note": item.last_price_note or last_error_message,
        "last_updated_at": last_price_check_at or item.last_priced_at or (latest_history.captured_at if latest_history else None),
        "cardmarket_url": item.cardmarket_reference,
        "cardmarket_link_mode": None,
        "last_price_check_at": last_price_check_at,
        "next_price_check_at": next_price_check_at,
        "price_check_interval_hours": interval_hours,
        "price_volatility_score": volatility_score,
        "price_check_priority": priority,
        "price_stability_state": stability_state if stability_state != "updating" else (state.price_stability_state if state else PRICE_STATE_NEW),
        "failure_count": failure_count,
        "consecutive_stable_checks": consecutive_stable_checks,
        "last_error_message": last_error_message,
    }


async def bootstrap_missing_price_monitor_states() -> int:
    created = 0
    async with session_scope() as db:
        result = await db.execute(
            select(InventoryItem)
            .outerjoin(PriceMonitorState, PriceMonitorState.inventory_item_id == InventoryItem.id)
            .options(selectinload(InventoryItem.price_history))
            .where(PriceMonitorState.id.is_(None))
            .order_by(InventoryItem.id.asc())
        )
        items = result.scalars().unique().all()
        now = datetime.utcnow()
        for item in items:
            await refresh_price_monitor_state(db, item, history=item.price_history, checked_at=now)
            created += 1
    if created:
        logger.info("Bootstrapped %s missing price monitor state(s)", created)
    return created
