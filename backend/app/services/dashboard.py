from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.integrations.cardmarket_links import (
    CARDMARKET_MATCH_AMBIGUOUS,
    CARDMARKET_MATCH_EXACT,
    CARDMARKET_MATCH_EXACT_VARIANT,
    CARDMARKET_MATCH_FAILED,
    CARDMARKET_MATCH_MANUAL,
    CARDMARKET_MATCH_SET_NAME,
    normalize_cardmarket_product_url,
)
from app.integrations.price_values import parse_positive_price
from app.models import CardPrint, InventoryItem, PriceHistory, SyncJob
from app.schemas import DashboardResponse, DashboardTrendItem, DashboardValuePoint
from app.services.app_settings import get_app_settings
from app.services.currency import convert_amount
from app.services.sync import serialize_sync_job
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
    review_reasons: list[str] | None = None,
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
        review_reasons=review_reasons or [],
    )


def _review_reasons(item: InventoryItem) -> list[str]:
    reasons: list[str] = []
    now = utc_now()
    exact_cardmarket_url = normalize_cardmarket_product_url(item.card_print.cardmarket_product_url)

    if parse_positive_price(item.current_market_price) is None:
        reasons.append("Kein Preis")

    if item.last_price_match_quality and item.last_price_match_quality not in _SAFE_PRICE_MATCH_QUALITIES:
        reasons.append("Unsicherer Match")

    if item.last_priced_at and item.last_priced_at < now - timedelta(days=30):
        reasons.append("Veraltete Daten")

    if not exact_cardmarket_url:
        reasons.append("Print prüfen")

    return list(dict.fromkeys(reasons))


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
    distinct_items = len(inventory_items)
    total_value = 0.0
    priced_cards = 0
    for item in inventory_items:
        market_price = parse_positive_price(item.current_market_price)
        converted_price = await _display_price_value(market_price, item.current_price_currency, display_currency)
        if converted_price is not None:
            total_value += converted_price * item.quantity
            priced_cards += 1
    cards_with_images = sum(1 for item in inventory_items if any(asset.status == "downloaded" and asset.local_path for asset in item.card_print.image_assets))

    gainers = [item for item in inventory_items if (item.price_change_7d or 0) > 0 and parse_positive_price(item.current_market_price) is not None]
    losers = [item for item in inventory_items if (item.price_change_7d or 0) < 0 and parse_positive_price(item.current_market_price) is not None]
    trending = [
        item
        for item in inventory_items
        if parse_positive_price(item.current_market_price) is not None
        and (abs(item.trend_score or 0) >= 10 or abs(item.price_change_7d or 0) >= 15)
    ]
    missing_price = [item for item in inventory_items if parse_positive_price(item.current_market_price) is None]
    review_candidates = [item for item in inventory_items if _review_reasons(item)]

    gainers = sorted(gainers, key=lambda item: (_price_change_value(item), item.trend_score or 0), reverse=True)
    losers = sorted(losers, key=lambda item: (_price_change_value(item), item.trend_score or 0))
    trending = sorted(trending, key=lambda item: (abs(item.trend_score or 0), abs(item.price_change_7d or 0)), reverse=True)
    missing_price = sorted(missing_price, key=lambda item: (item.last_priced_at or datetime.min, item.updated_at), reverse=True)
    review_candidates = sorted(
        review_candidates,
        key=lambda item: (
            100 if parse_positive_price(item.current_market_price) is None else 0,
            50 if item.last_price_match_quality and item.last_price_match_quality not in _SAFE_PRICE_MATCH_QUALITIES else 0,
            30 if item.last_priced_at and item.last_priced_at < utc_now() - timedelta(days=30) else 0,
            10 if not normalize_cardmarket_product_url(item.card_print.cardmarket_product_url) else 0,
        ),
        reverse=True,
    )

    recent_price_update_candidates = sorted(
        [item for item in inventory_items if item.last_priced_at is not None],
        key=lambda item: item.last_priced_at or datetime.min,
        reverse=True,
    )

    recent_history_result = await db.execute(
        select(PriceHistory)
        .where(PriceHistory.price > 0)
        .options(selectinload(PriceHistory.inventory_item).selectinload(InventoryItem.card_print).selectinload(CardPrint.card))
        .order_by(PriceHistory.captured_at.desc())
        .limit(12)
    )
    recent_history = recent_history_result.scalars().all()
    recent_item_ids = {history.inventory_item_id for history in recent_history}
    recent_price_updates = [item for item in recent_price_update_candidates if item.id in recent_item_ids] or recent_price_update_candidates

    recent_jobs_result = await db.execute(select(SyncJob).order_by(SyncJob.created_at.desc()).limit(8))
    recent_jobs = recent_jobs_result.scalars().all()

    top_gainers = [await _dashboard_item(item, display_currency=display_currency) for item in gainers[:5]]
    top_losers = [await _dashboard_item(item, display_currency=display_currency) for item in losers[:5]]
    trending_cards = [await _dashboard_item(item, display_currency=display_currency) for item in trending[:6]]
    missing_price_cards = [await _dashboard_item(item, display_currency=display_currency) for item in missing_price[:6]]
    review_cards = [await _dashboard_item(item, display_currency=display_currency, review_reasons=_review_reasons(item)) for item in review_candidates[:6]]
    recent_cards = [await _dashboard_item(item, display_currency=display_currency) for item in recent_price_updates[:8]]

    return DashboardResponse(
        total_cards=total_cards,
        distinct_items=distinct_items,
        total_value=total_value,
        priced_cards=priced_cards,
        cards_with_images=cards_with_images,
        value_history=await _value_history(db, inventory_items),
        top_gainers=top_gainers,
        top_losers=top_losers,
        trending_cards=trending_cards,
        missing_price_cards=missing_price_cards,
        review_candidates=review_cards,
        recent_price_updates=recent_cards,
        recent_jobs=[serialize_sync_job(job) for job in recent_jobs],
        display_currency=display_currency,
    )
