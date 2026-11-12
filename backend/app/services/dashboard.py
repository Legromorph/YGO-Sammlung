from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import quote

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.integrations.cardmarket import (
    CARDMARKET_MATCH_EXACT,
    CARDMARKET_MATCH_EXACT_VARIANT,
    CARDMARKET_MATCH_MANUAL,
    CARDMARKET_MATCH_SET_NAME,
)
from app.integrations.price_values import parse_positive_price
from app.models import CardPrint, InventoryItem, PriceHistory, SyncJob
from app.schemas import DashboardResponse, DashboardTrendItem, DashboardValuePoint
from app.services.app_settings import get_app_settings
from app.services.currency import convert_amount
from app.time_utils import utc_now

_SAFE_PRICE_MATCH_QUALITIES = {
    CARDMARKET_MATCH_EXACT,
    CARDMARKET_MATCH_EXACT_VARIANT,
    CARDMARKET_MATCH_MANUAL,
    CARDMARKET_MATCH_SET_NAME,
    "manual",
}


def _card_image_url(item: InventoryItem) -> str:
    assets = sorted(
        [asset for asset in item.card_print.image_assets if asset.status == "downloaded" and asset.local_path],
        key=lambda asset: asset.downloaded_at or asset.updated_at,
        reverse=True,
    )
    if assets:
        return f"/media/{assets[0].local_path}"

    if item.card_print.remote_image_url:
        return f"{settings.api_prefix}/assets/proxy?url={quote(item.card_print.remote_image_url, safe='')}"

    return f"{settings.api_prefix}/assets/placeholder?item_id={item.id}&label={quote(item.card_print.card.name, safe='')}"


async def _dashboard_item(
    item: InventoryItem,
    *,
    display_currency: str,
) -> DashboardTrendItem:
    market_price = parse_positive_price(item.current_market_price)
    converted_price = await convert_amount(market_price, item.current_price_currency, display_currency)
    return DashboardTrendItem(
        inventory_item_id=item.id,
        card_id=item.card_print.card.id,
        card_print_id=item.card_print.id,
        name=item.card_print.card.name,
        set_name=item.card_print.set_name,
        set_code=item.card_print.set_code,
        card_number=item.card_print.card_number,
        rarity=item.card_print.rarity,
        language=item.card_print.language,
        image_url=_card_image_url(item),
        storage_path=item.storage_location.path_cache if item.storage_location else None,
        current_market_price=float(converted_price) if converted_price is not None else None,
        current_price_currency=display_currency,
        price_change_7d=item.price_change_7d,
        price_change_30d=item.price_change_30d,
        trend_score=item.trend_score,
        quantity=item.quantity,
        last_priced_at=item.last_priced_at,
        last_price_source=item.last_price_source,
        last_price_match_quality=item.last_price_match_quality,
    )


def _has_uncertain_price(item: InventoryItem) -> bool:
    return bool(
        parse_positive_price(item.current_market_price) is not None
        and item.last_price_match_quality
        and item.last_price_match_quality not in _SAFE_PRICE_MATCH_QUALITIES
    )


def _has_stale_price(item: InventoryItem, now) -> bool:
    return bool(item.last_priced_at and item.last_priced_at < now - timedelta(days=30))


async def _display_price_value(
    value: float | int | Decimal | None,
    source_currency: str | None,
    target_currency: str,
) -> float | None:
    converted = await convert_amount(value, source_currency, target_currency)
    return float(converted) if converted is not None else None


async def _value_history(db: AsyncSession, inventory_items: list[InventoryItem]) -> list[DashboardValuePoint]:
    app_settings = await get_app_settings(db)
    display_currency = app_settings.preferred_currency
    start_date = utc_now().date() - timedelta(days=13)
    history_result = await db.execute(
        select(PriceHistory)
        .where(
            PriceHistory.captured_at >= datetime.combine(start_date, datetime.min.time(), tzinfo=UTC),
            PriceHistory.price > 0,
        )
        .order_by(PriceHistory.inventory_item_id, PriceHistory.captured_at.asc())
    )
    history_entries = history_result.scalars().all()
    grouped: dict[int, list[PriceHistory]] = defaultdict(list)
    for entry in history_entries:
        grouped[entry.inventory_item_id].append(entry)

    items_by_id = {item.id: item for item in inventory_items}
    item_quantities = {item.id: item.quantity for item in inventory_items}
    converted_history_prices: dict[int, float | None] = {}
    points: list[DashboardValuePoint] = []
    for offset in range(14):
        day = start_date + timedelta(days=offset)
        total = 0.0
        day_end = datetime.combine(day, datetime.max.time(), tzinfo=UTC)
        for item_id, quantity in item_quantities.items():
            price = None
            selected_entry = None
            for entry in grouped.get(item_id, []):
                if entry.captured_at <= day_end:
                    selected_entry = entry
                else:
                    break
            if selected_entry is not None:
                if selected_entry.id not in converted_history_prices:
                    converted_history_prices[selected_entry.id] = await _display_price_value(
                        selected_entry.price,
                        selected_entry.currency,
                        display_currency,
                    )
                price = converted_history_prices[selected_entry.id]
            if price is None:
                inventory_item = items_by_id.get(item_id)
                current_price = parse_positive_price(inventory_item.current_market_price) if inventory_item else None
                if inventory_item and current_price is not None and day == utc_now().date():
                    price = await _display_price_value(current_price, inventory_item.current_price_currency, display_currency)
            total += (price or 0) * quantity
        points.append(DashboardValuePoint(date=day, total_value=round(total, 2), display_currency=display_currency))
    return points


def _price_change_value(item: InventoryItem) -> float:
    return float(item.price_change_7d or 0)


async def get_dashboard(db: AsyncSession) -> DashboardResponse:
    app_settings = await get_app_settings(db)
    display_currency = app_settings.preferred_currency
    now = utc_now()
    items_result = await db.execute(
        select(InventoryItem)
        .options(
            selectinload(InventoryItem.storage_location),
            selectinload(InventoryItem.card_print).selectinload(CardPrint.card),
            selectinload(InventoryItem.card_print).selectinload(CardPrint.image_assets),
        )
        .order_by(InventoryItem.updated_at.desc())
    )
    inventory_items = items_result.scalars().unique().all()

    total_cards = sum(item.quantity for item in inventory_items)
    total_value = 0.0
    priced_items = 0
    purchase_value = 0.0
    purchase_value_market = 0.0
    item_values: dict[int, float] = {}
    for item in inventory_items:
        converted_price = await _display_price_value(parse_positive_price(item.current_market_price), item.current_price_currency, display_currency)
        if converted_price is not None:
            item_values[item.id] = converted_price * item.quantity
            total_value += item_values[item.id]
            priced_items += 1
        if item.purchase_price is not None:
            purchase_value += float(item.purchase_price) * item.quantity
            purchase_value_market += item_values.get(item.id, 0.0)

    priced = [item for item in inventory_items if item.id in item_values]
    gainers = sorted((item for item in priced if (item.price_change_7d or 0) > 0), key=lambda item: item.price_change_7d or 0, reverse=True)
    losers = sorted((item for item in priced if (item.price_change_7d or 0) < 0), key=lambda item: item.price_change_7d or 0)
    most_valuable = sorted(priced, key=lambda item: item_values[item.id], reverse=True)

    failed_jobs_count = await db.scalar(
        select(func.count(SyncJob.id)).where(SyncJob.status == "failed", SyncJob.created_at >= now - timedelta(days=7))
    )

    async def serialize(items: list[InventoryItem], limit: int) -> list[DashboardTrendItem]:
        return [await _dashboard_item(item, display_currency=display_currency) for item in items[:limit]]

    return DashboardResponse(
        total_cards=total_cards,
        distinct_items=len(inventory_items),
        total_value=round(total_value, 2),
        priced_cards=priced_items,
        purchase_value=round(purchase_value, 2),
        purchase_value_market=round(purchase_value_market, 2),
        value_history=await _value_history(db, inventory_items),
        top_gainers=await serialize(gainers, 5),
        top_losers=await serialize(losers, 5),
        most_valuable_cards=await serialize(most_valuable, 8),
        missing_price_count=len(inventory_items) - priced_items,
        uncertain_price_count=sum(1 for item in inventory_items if _has_uncertain_price(item)),
        stale_price_count=sum(1 for item in inventory_items if _has_stale_price(item, now)),
        failed_jobs_count=int(failed_jobs_count or 0),
        display_currency=display_currency,
    )
