from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import StorageLocationPayload, StorageLocationResponse
from app.services.storage import delete_storage_location, get_storage_location, list_storage_locations, upsert_storage_location

router = APIRouter()


@router.get("/", response_model=list[StorageLocationResponse])
async def get_locations(db: AsyncSession = Depends(get_db)) -> list[StorageLocationResponse]:
    return await list_storage_locations(db)


@router.post("/", response_model=StorageLocationResponse, status_code=status.HTTP_201_CREATED)
async def create_location(payload: StorageLocationPayload, db: AsyncSession = Depends(get_db)) -> StorageLocationResponse:
    try:
        location = await upsert_storage_location(db, payload)
        await db.commit()
        locations = await list_storage_locations(db)
        return next(item for item in locations if item.id == location.id)
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{location_id}", response_model=StorageLocationResponse)
async def get_location(location_id: int, db: AsyncSession = Depends(get_db)) -> StorageLocationResponse:
    locations = await list_storage_locations(db)
    for location in locations:
        if location.id == location_id:
            return location
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Storage location not found")


@router.put("/{location_id}", response_model=StorageLocationResponse)
async def update_location(location_id: int, payload: StorageLocationPayload, db: AsyncSession = Depends(get_db)) -> StorageLocationResponse:
    try:
        location = await upsert_storage_location(db, payload, location_id=location_id)
        await db.commit()
        locations = await list_storage_locations(db)
        return next(item for item in locations if item.id == location.id)
    except ValueError as exc:
        await db.rollback()
        status_code = status.HTTP_404_NOT_FOUND if "not found" in str(exc).lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.delete("/{location_id}", status_code=status.HTTP_200_OK)
async def remove_location(location_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    try:
        await delete_storage_location(db, location_id)
        await db.commit()
        return {"message": "Storage location deleted"}
    except ValueError as exc:
        await db.rollback()
        status_code = status.HTTP_404_NOT_FOUND if "not found" in str(exc).lower() else status.HTTP_409_CONFLICT
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
