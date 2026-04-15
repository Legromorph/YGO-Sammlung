from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import CardSetSummary, SetCardsResponse
from app.services.sets import get_card_set_cards, list_card_sets

router = APIRouter()


@router.get("/", response_model=list[CardSetSummary])
async def get_sets(
    q: str | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[CardSetSummary]:
    try:
        items = await list_card_sets(db, q=q, limit=limit)
        await db.commit()
        return items
    except Exception:
        await db.rollback()
        raise


@router.get("/{set_id}/cards", response_model=SetCardsResponse)
async def get_set_cards(
    set_id: int,
    language: str = Query(default="de", min_length=2, max_length=8),
    db: AsyncSession = Depends(get_db),
) -> SetCardsResponse:
    try:
        response = await get_card_set_cards(db, set_id, language=language)
        await db.commit()
        return response
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception:
        await db.rollback()
        raise
