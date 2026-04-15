from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import InventoryItem, StorageLocation
from app.schemas import StorageLocationPayload, StorageLocationResponse
from app.services.app_settings import get_app_settings
from app.services.currency import convert_amount


async def list_storage_locations(db: AsyncSession) -> list[StorageLocationResponse]:
    app_settings = await get_app_settings(db)
    display_currency = app_settings.preferred_currency
    result = await db.execute(select(StorageLocation).options(selectinload(StorageLocation.parent)).order_by(StorageLocation.path_cache))
    locations = result.scalars().all()

    stats_map: dict[int, tuple[int, float]] = {}
    inventory_result = await db.execute(
        select(InventoryItem.storage_location_id, InventoryItem.quantity, InventoryItem.current_market_price, InventoryItem.current_price_currency).where(
            InventoryItem.storage_location_id.is_not(None)
        )
    )
    for storage_location_id, quantity, current_market_price, current_price_currency in inventory_result.all():
        if storage_location_id is None:
            continue
        card_count, total_value = stats_map.get(storage_location_id, (0, 0.0))
        converted_price = await convert_amount(current_market_price, current_price_currency, display_currency)
        total_value += (float(converted_price) if converted_price is not None else 0.0) * int(quantity or 0)
        stats_map[storage_location_id] = (card_count + int(quantity or 0), round(total_value, 2))

    return [
        StorageLocationResponse(
            id=location.id,
            name=location.name,
            code=location.code,
            location_type=location.location_type,
            description=location.description,
            position_label=location.position_label,
            parent_id=location.parent_id,
            path_cache=location.path_cache,
            card_count=stats_map.get(location.id, (0, 0))[0],
            total_value=stats_map.get(location.id, (0, 0))[1],
            display_currency=display_currency,
        )
        for location in locations
    ]


async def get_storage_location(db: AsyncSession, location_id: int) -> StorageLocation | None:
    result = await db.execute(select(StorageLocation).where(StorageLocation.id == location_id))
    return result.scalar_one_or_none()


async def upsert_storage_location(db: AsyncSession, payload: StorageLocationPayload, location_id: int | None = None) -> StorageLocation:
    if payload.parent_id:
        parent = await get_storage_location(db, payload.parent_id)
        if not parent:
            raise ValueError("Parent location not found.")
        if location_id and payload.parent_id == location_id:
            raise ValueError("A location cannot be its own parent.")

    if location_id:
        location = await get_storage_location(db, location_id)
        if not location:
            raise ValueError("Storage location not found.")
    else:
        location = StorageLocation(path_cache="")
        db.add(location)

    location.name = payload.name
    location.code = payload.code
    location.location_type = payload.location_type
    location.description = payload.description
    location.position_label = payload.position_label
    location.parent_id = payload.parent_id

    await db.flush()
    await rebuild_location_paths(db)
    await db.flush()
    return location


async def rebuild_location_paths(db: AsyncSession) -> None:
    result = await db.execute(select(StorageLocation).order_by(StorageLocation.id))
    locations = result.scalars().all()
    location_map = {location.id: location for location in locations}

    def build_path(location: StorageLocation) -> str:
        if not location.parent_id:
            return location.name
        parent = location_map.get(location.parent_id)
        return f"{build_path(parent)} > {location.name}" if parent else location.name

    for location in locations:
        location.path_cache = build_path(location)


async def delete_storage_location(db: AsyncSession, location_id: int) -> None:
    location = await get_storage_location(db, location_id)
    if not location:
        raise ValueError("Storage location not found.")

    child_count = await db.scalar(select(func.count(StorageLocation.id)).where(StorageLocation.parent_id == location_id))
    if child_count:
        raise ValueError("Location still has child locations.")

    item_count = await db.scalar(select(func.count(InventoryItem.id)).where(InventoryItem.storage_location_id == location_id))
    if item_count:
        raise ValueError("Location is still used by inventory items.")

    await db.delete(location)
