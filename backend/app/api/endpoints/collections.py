from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import CollectionDetail, CollectionPayload, CollectionSummary
from app.services.collections import delete_collection, get_collection, list_collections, upsert_collection

router = APIRouter()


@router.get("/", response_model=list[CollectionSummary])
async def get_all_collections(db: AsyncSession = Depends(get_db)) -> list[CollectionSummary]:
    return await list_collections(db)


@router.post("/", response_model=CollectionDetail, status_code=status.HTTP_201_CREATED)
async def create_collection(payload: CollectionPayload, db: AsyncSession = Depends(get_db)) -> CollectionDetail:
    try:
        collection = await upsert_collection(db, payload)
        await db.commit()
        detail = await get_collection(db, collection.id)
        return detail
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{collection_id}", response_model=CollectionDetail)
async def get_collection_detail(collection_id: int, db: AsyncSession = Depends(get_db)) -> CollectionDetail:
    collection = await get_collection(db, collection_id)
    if not collection:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Collection not found")
    return collection


@router.put("/{collection_id}", response_model=CollectionDetail)
async def update_collection_detail(collection_id: int, payload: CollectionPayload, db: AsyncSession = Depends(get_db)) -> CollectionDetail:
    try:
        collection = await upsert_collection(db, payload, collection_id=collection_id)
        await db.commit()
        detail = await get_collection(db, collection.id)
        return detail
    except ValueError as exc:
        await db.rollback()
        status_code = status.HTTP_404_NOT_FOUND if "not found" in str(exc).lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.delete("/{collection_id}", status_code=status.HTTP_200_OK)
async def remove_collection(collection_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    try:
        await delete_collection(db, collection_id)
        await db.commit()
        return {"message": "Collection deleted"}
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
