from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import CardPrint, Deck, DeckCard, InventoryItem
from app.schemas import DeckCardResponse, DeckDetail, DeckPayload, DeckSummary
from app.services.app_settings import get_app_settings
from app.services.currency import convert_amount


async def _deck_card_name(deck_card: DeckCard, *, display_currency: str) -> tuple[str, str | None, float | None]:
    if deck_card.inventory_item and deck_card.inventory_item.card_print:
        card_print = deck_card.inventory_item.card_print
    else:
        card_print = deck_card.card_print

    if card_print and card_print.card:
        item = deck_card.inventory_item
        price = None
        if item and item.current_market_price is not None:
            converted = await convert_amount(item.current_market_price, item.current_price_currency, display_currency)
            price = float(converted) if converted is not None else None
        return card_print.card.name, card_print.set_code, price
    return "Unknown Card", None, None


async def serialize_deck(deck: Deck, *, display_currency: str) -> DeckDetail:
    cards: list[DeckCardResponse] = []
    total_value = 0.0
    card_count = 0
    for deck_card in deck.cards:
        card_name, set_code, price = await _deck_card_name(deck_card, display_currency=display_currency)
        total_price = round((price or 0) * deck_card.quantity, 2)
        total_value += total_price
        card_count += deck_card.quantity
        cards.append(
            DeckCardResponse(
                id=deck_card.id,
                inventory_item_id=deck_card.inventory_item_id,
                card_print_id=deck_card.card_print_id,
                card_name=card_name,
                set_code=set_code,
                section=deck_card.section,
                quantity=deck_card.quantity,
                is_missing=deck_card.is_missing,
                current_market_price=price,
                total_price=total_price,
                notes=deck_card.notes,
            )
        )
    return DeckDetail(
        id=deck.id,
        name=deck.name,
        description=deck.description,
        format=deck.format,
        card_count=card_count,
        total_value=round(total_value, 2),
        display_currency=display_currency,
        updated_at=deck.updated_at,
        cards=cards,
    )


async def list_decks(db: AsyncSession) -> list[DeckSummary]:
    app_settings = await get_app_settings(db)
    display_currency = app_settings.preferred_currency
    result = await db.execute(
        select(Deck)
        .options(
            selectinload(Deck.cards).selectinload(DeckCard.inventory_item).selectinload(InventoryItem.card_print).selectinload(CardPrint.card),
            selectinload(Deck.cards).selectinload(DeckCard.card_print).selectinload(CardPrint.card),
        )
        .order_by(Deck.updated_at.desc())
    )
    decks = result.scalars().unique().all()
    return [DeckSummary(**(await serialize_deck(deck, display_currency=display_currency)).model_dump(exclude={"cards"})) for deck in decks]


async def get_deck(db: AsyncSession, deck_id: int) -> DeckDetail | None:
    app_settings = await get_app_settings(db)
    display_currency = app_settings.preferred_currency
    result = await db.execute(
        select(Deck)
        .where(Deck.id == deck_id)
        .options(
            selectinload(Deck.cards).selectinload(DeckCard.inventory_item).selectinload(InventoryItem.card_print).selectinload(CardPrint.card),
            selectinload(Deck.cards).selectinload(DeckCard.card_print).selectinload(CardPrint.card),
        )
    )
    deck = result.scalar_one_or_none()
    return await serialize_deck(deck, display_currency=display_currency) if deck else None


async def upsert_deck(db: AsyncSession, payload: DeckPayload, deck_id: int | None = None) -> Deck:
    if deck_id:
        deck = await db.get(Deck, deck_id, options=[selectinload(Deck.cards)])
        if not deck:
            raise ValueError("Deck not found.")
    else:
        deck = Deck()
        db.add(deck)

    deck.name = payload.name
    deck.description = payload.description
    deck.format = payload.format
    deck.cards.clear()

    for entry in payload.cards:
        inventory_item = await db.get(InventoryItem, entry.inventory_item_id) if entry.inventory_item_id else None
        deck.cards.append(
            DeckCard(
                inventory_item_id=entry.inventory_item_id,
                card_print_id=inventory_item.card_print_id if inventory_item else None,
                quantity=entry.quantity,
                section=entry.section,
                is_missing=entry.is_missing,
                notes=entry.notes,
            )
        )

    await db.flush()
    return deck


async def delete_deck(db: AsyncSession, deck_id: int) -> None:
    deck = await db.get(Deck, deck_id)
    if not deck:
        raise ValueError("Deck not found.")
    await db.delete(deck)
