from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import CardPrint, Collection, CollectionCard, InventoryItem
from app.schemas import CollectionCardResponse, CollectionDetail, CollectionPayload, CollectionSummary
from app.services.app_settings import get_app_settings
from app.services.currency import convert_amount


async def _collection_card_name(collection_card: CollectionCard, *, display_currency: str) -> tuple[str, str | None, float | None]:
    if collection_card.inventory_item and collection_card.inventory_item.card_print:
        card_print = collection_card.inventory_item.card_print
    else:
        card_print = collection_card.card_print

    if card_print and card_print.card:
        item = collection_card.inventory_item
        price = None
        if item and item.current_market_price is not None:
            converted = await convert_amount(item.current_market_price, item.current_price_currency, display_currency)
            price = float(converted) if converted is not None else None
        return card_print.card.name, card_print.set_code, price
    return "Unknown Card", None, None


async def serialize_collection(collection: Collection, *, display_currency: str) -> CollectionDetail:
    cards: list[CollectionCardResponse] = []
    total_value = 0.0
    card_count = 0
    for entry in collection.cards:
        card_name, set_code, price = await _collection_card_name(entry, display_currency=display_currency)
        total_price = round((price or 0) * entry.quantity, 2)
        total_value += total_price
        card_count += entry.quantity
        cards.append(
            CollectionCardResponse(
                id=entry.id,
                inventory_item_id=entry.inventory_item_id,
                card_print_id=entry.card_print_id,
                card_name=card_name,
                set_code=set_code,
                quantity=entry.quantity,
                current_market_price=price,
                total_price=total_price,
                notes=entry.notes,
            )
        )
    return CollectionDetail(
        id=collection.id,
        name=collection.name,
        description=collection.description,
        color=collection.color,
        card_count=card_count,
        total_value=round(total_value, 2),
        display_currency=display_currency,
        updated_at=collection.updated_at,
        cards=cards,
    )


async def list_collections(db: AsyncSession) -> list[CollectionSummary]:
    app_settings = await get_app_settings(db)
    display_currency = app_settings.preferred_currency
    result = await db.execute(
        select(Collection)
        .options(
            selectinload(Collection.cards).selectinload(CollectionCard.inventory_item).selectinload(InventoryItem.card_print).selectinload(CardPrint.card),
            selectinload(Collection.cards).selectinload(CollectionCard.card_print).selectinload(CardPrint.card),
        )
        .order_by(Collection.updated_at.desc())
    )
    collections = result.scalars().unique().all()
    return [CollectionSummary(**(await serialize_collection(collection, display_currency=display_currency)).model_dump(exclude={"cards"})) for collection in collections]


async def get_collection(db: AsyncSession, collection_id: int) -> CollectionDetail | None:
    app_settings = await get_app_settings(db)
    display_currency = app_settings.preferred_currency
    result = await db.execute(
        select(Collection)
        .where(Collection.id == collection_id)
        .options(
            selectinload(Collection.cards).selectinload(CollectionCard.inventory_item).selectinload(InventoryItem.card_print).selectinload(CardPrint.card),
            selectinload(Collection.cards).selectinload(CollectionCard.card_print).selectinload(CardPrint.card),
        )
    )
    collection = result.scalar_one_or_none()
    return await serialize_collection(collection, display_currency=display_currency) if collection else None


async def upsert_collection(db: AsyncSession, payload: CollectionPayload, collection_id: int | None = None) -> Collection:
    if collection_id:
        collection = await db.get(Collection, collection_id, options=[selectinload(Collection.cards)])
        if not collection:
            raise ValueError("Collection not found.")
    else:
        collection = Collection()
        db.add(collection)

    collection.name = payload.name
    collection.description = payload.description
    collection.color = payload.color
    collection.cards.clear()

    for entry in payload.cards:
        inventory_item = await db.get(InventoryItem, entry.inventory_item_id) if entry.inventory_item_id else None
        collection.cards.append(
            CollectionCard(
                inventory_item_id=entry.inventory_item_id,
                card_print_id=inventory_item.card_print_id if inventory_item else None,
                quantity=entry.quantity,
                notes=entry.notes,
            )
        )

    await db.flush()
    return collection


async def delete_collection(db: AsyncSession, collection_id: int) -> None:
    collection = await db.get(Collection, collection_id)
    if not collection:
        raise ValueError("Collection not found.")
    await db.delete(collection)
