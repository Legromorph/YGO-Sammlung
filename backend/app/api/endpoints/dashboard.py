from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas import DashboardResponse
from app.services.dashboard import get_dashboard

router = APIRouter()


@router.get("/", response_model=DashboardResponse)
async def dashboard_stats(db: AsyncSession = Depends(get_db)) -> DashboardResponse:
    return await get_dashboard(db)
