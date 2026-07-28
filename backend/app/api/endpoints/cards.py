from __future__ import annotations

from datetime import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.schemas import (
    CardDetail,
    CardFilterOptions,
    CardListResponse,
    CardLookupResponse,
    CardLookupSuggestion,
    CardmarketLinkPayload,
    CardPayload,
    CardSummary,
    PriceHistoryPoint,
    SyncJobResponse,
)
from app.services.app_settings import get_app_settings
from app.services.card_creation import get_card_creation_orchestrator
from app.services.cards import (
    DuplicateInventoryItemError,
    delete_card,
    get_card_detail,
    get_card_lookup,
    get_filter_options,
    list_cards,
    price_history_for_card,
    search_card_catalog,
    update_cardmarket_link,
    upsert_card,
)
from app.services.sync import queue_price_update_job, serialize_sync_job
from app.time_utils import utc_now

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/", response_model=CardListResponse)
async def get_cards(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    q: str | None = None,
    language: str | None = None,
    set_code: str | None = None,
    card_type: str | None = None,
    attribute: str | None = None,
    monster_type: str | None = None,
    rarity: str | None = None,
    condition: str | None = None,
    storage_location_id: int | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    min_atk: int | None = None,
    max_atk: int | None = None,
    min_defense: int | None = None,
    max_defense: int | None = None,
    level: int | None = None,
    rank: int | None = None,
    has_image: bool | None = None,
    has_price: bool | None = None,
    price_direction: str | None = Query(default=None, pattern="^(up|down|volatile)$"),
    sort_by: str = Query(default="updated_at"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
) -> CardListResponse:
    items, total = await list_cards(
        db,
        page=page,
        page_size=page_size,
        q=q,
        language=language,
        set_code=set_code,
        card_type=card_type,
        attribute=attribute,
        monster_type=monster_type,
        rarity=rarity,
        condition=condition,
        storage_location_id=storage_location_id,
        min_price=min_price,
        max_price=max_price,
        min_atk=min_atk,
        max_atk=max_atk,
        min_defense=min_defense,
        max_defense=max_defense,
        level=level,
        rank=rank,
        has_image=has_image,
        has_price=has_price,
        price_direction=price_direction,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return CardListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get("/filters", response_model=CardFilterOptions)
async def card_filter_options(db: AsyncSession = Depends(get_db)) -> CardFilterOptions:
    return await get_filter_options(db)


@router.get("/lookup/search", response_model=list[CardLookupSuggestion])
async def search_card_lookup(
    q: str = Query(min_length=2),
    language: str = Query(default="de,en", min_length=2, max_length=16),
    limit: int = Query(default=8, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
) -> list[CardLookupSuggestion]:
    app_settings = await get_app_settings(db)
    return await search_card_catalog(q, language=language, limit=limit, display_currency=app_settings.preferred_currency)


@router.get("/lookup/autofill", response_model=CardLookupResponse)
async def card_lookup_autofill(
    name: str | None = None,
    external_id: str | None = None,
    language: str = Query(default="de,en", min_length=2, max_length=16),
    db: AsyncSession = Depends(get_db),
) -> CardLookupResponse:
    if not name and not external_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Either name or external_id is required")

    lookup = await get_card_lookup(db, name=name, external_id=external_id, language=language)
    if not lookup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No matching remote card found")
    return lookup


@router.post("/", response_model=CardSummary, status_code=status.HTTP_201_CREATED)
async def create_card(payload: CardPayload, db: AsyncSession = Depends(get_db)) -> CardSummary:
    try:
        return await get_card_creation_orchestrator().create_card(db, payload)
    except DuplicateInventoryItemError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.to_detail()) from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed after pricing during card creation for '%s' (%s): %s", payload.name, payload.set_code, exc)
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Karte wurde nach dem Anlegen nicht korrekt verarbeitet. Bitte Backend-Logs prüfen.",
        ) from exc


@router.get("/{card_id}", response_model=CardDetail)
async def get_card(card_id: int, db: AsyncSession = Depends(get_db)) -> CardDetail:
    card = await get_card_detail(db, card_id)
    if not card:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Card not found")
    return card


@router.put("/{card_id}", response_model=CardSummary)
async def update_card(card_id: int, payload: CardPayload, db: AsyncSession = Depends(get_db)) -> CardSummary:
    try:
        item = await upsert_card(db, payload, inventory_item_id=card_id)
        await db.commit()
        detail = await get_card_detail(db, item.id)
        if not detail:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Card could not be reloaded after update")
        return CardSummary(
            **detail.model_dump(
                exclude={
                    "effect_text",
                    "subtype",
                    "archetype",
                    "spell_trap_type",
                    "rarity_code",
                    "edition",
                    "release_date",
                    "cardmarket_reference",
                    "tags",
                    "link_arrows",
                    "pendulum_scale",
                    "pendulum_effect",
                    "price_history",
                    "source_mappings",
                }
            )
        )
    except ValueError as exc:
        await db.rollback()
        status_code = status.HTTP_404_NOT_FOUND if "not found" in str(exc).lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get("/{card_id}/price-history", response_model=list[PriceHistoryPoint])
async def get_card_price_history(card_id: int, db: AsyncSession = Depends(get_db)) -> list[PriceHistoryPoint]:
    return await price_history_for_card(db, card_id)


@router.put("/{card_id}/cardmarket-link", response_model=CardDetail)
async def update_card_cardmarket_link(card_id: int, payload: CardmarketLinkPayload, db: AsyncSession = Depends(get_db)) -> CardDetail:
    try:
        item = await update_cardmarket_link(db, card_id, payload.url, confirmed=payload.confirmed)
        await db.commit()
        detail = await get_card_detail(db, item.id)
        if not detail:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Card could not be reloaded after update")
        return detail
    except ValueError as exc:
        await db.rollback()
        status_code = status.HTTP_404_NOT_FOUND if "not found" in str(exc).lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.post("/{card_id}/price-update", response_model=SyncJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def trigger_price_update(card_id: int, db: AsyncSession = Depends(get_db)) -> SyncJobResponse:
    card = await get_card_detail(db, card_id)
    if not card:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Card not found")

    job = await queue_price_update_job(
        inventory_item_ids=[card_id],
        card_print_ids=[card.card_print_id],
        trigger="manual",
        reason="manual_price_update_button",
        available_at=utc_now(),
        priority=settings.price_monitor_manual_priority,
    )
    return serialize_sync_job(job)


@router.delete("/{card_id}", status_code=status.HTTP_200_OK)
async def remove_card(card_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    try:
        await delete_card(db, card_id)
        await db.commit()
        return {"message": "Card deleted"}
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
