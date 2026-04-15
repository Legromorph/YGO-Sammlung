from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import AppSettingsPayload, AppSettingsResponse
from app.services.app_settings import get_app_settings, update_app_settings

router = APIRouter()


@router.get("/", response_model=AppSettingsResponse)
async def read_settings(db: AsyncSession = Depends(get_db)) -> AppSettingsResponse:
    return await get_app_settings(db)


@router.put("/", response_model=AppSettingsResponse)
async def save_settings(payload: AppSettingsPayload, db: AsyncSession = Depends(get_db)) -> AppSettingsResponse:
    settings = await update_app_settings(db, payload)
    await db.commit()
    return settings

