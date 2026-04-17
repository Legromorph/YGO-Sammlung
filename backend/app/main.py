import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.config import settings
from app.services.price_monitor import bootstrap_missing_price_monitor_states
from app.services.sync import bootstrap_missing_media

app = FastAPI(title=settings.app_name, version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.api_prefix)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "status": "ok",
        "app": settings.app_name,
        "api_prefix": settings.api_prefix,
        "health_url": f"{settings.api_prefix}/health/",
    }


@app.on_event("startup")
async def startup():
    settings.cards_media_path.mkdir(parents=True, exist_ok=True)
    asyncio.create_task(bootstrap_missing_media())
    asyncio.create_task(bootstrap_missing_price_monitor_states())


media_root = Path(settings.media_root)
media_root.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=media_root), name="media")
