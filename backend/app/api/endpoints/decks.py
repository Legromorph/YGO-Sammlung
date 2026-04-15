from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import DeckDetail, DeckPayload, DeckSummary
from app.services.decks import delete_deck, get_deck, list_decks, upsert_deck

router = APIRouter()


@router.get("/", response_model=list[DeckSummary])
async def get_all_decks(db: AsyncSession = Depends(get_db)) -> list[DeckSummary]:
    return await list_decks(db)


@router.post("/", response_model=DeckDetail, status_code=status.HTTP_201_CREATED)
async def create_deck(payload: DeckPayload, db: AsyncSession = Depends(get_db)) -> DeckDetail:
    try:
        deck = await upsert_deck(db, payload)
        await db.commit()
        detail = await get_deck(db, deck.id)
        return detail
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{deck_id}", response_model=DeckDetail)
async def get_deck_detail(deck_id: int, db: AsyncSession = Depends(get_db)) -> DeckDetail:
    deck = await get_deck(db, deck_id)
    if not deck:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deck not found")
    return deck


@router.put("/{deck_id}", response_model=DeckDetail)
async def update_deck_detail(deck_id: int, payload: DeckPayload, db: AsyncSession = Depends(get_db)) -> DeckDetail:
    try:
        deck = await upsert_deck(db, payload, deck_id=deck_id)
        await db.commit()
        detail = await get_deck(db, deck.id)
        return detail
    except ValueError as exc:
        await db.rollback()
        status_code = status.HTTP_404_NOT_FOUND if "not found" in str(exc).lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.delete("/{deck_id}", status_code=status.HTTP_200_OK)
async def remove_deck(deck_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    try:
        await delete_deck(db, deck_id)
        await db.commit()
        return {"message": "Deck deleted"}
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
