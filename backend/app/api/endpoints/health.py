from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from app.config import settings
from app.database import database_ok
from app.schemas import HealthResponse

router = APIRouter()


@router.get("/", response_model=HealthResponse)
async def healthcheck() -> HealthResponse:
    database = False
    try:
        database = await database_ok()
    except Exception:
        database = False

    image_directory = Path(settings.cards_media_path).exists()
    status = "ok" if database and image_directory else "degraded"
    return HealthResponse(
        status=status,
        database=database,
        image_directory=image_directory,
        active_providers={
            "price": settings.price_provider,
            "card_data": settings.card_data_provider,
            "image": settings.image_provider,
        },
    )
