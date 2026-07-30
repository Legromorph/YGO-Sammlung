from fastapi import APIRouter

from app.api.endpoints import assets, backups, cards, collections, dashboard, decks, exports, health, inventory, sets, settings, storage_locations, sync

api_router = APIRouter()
api_router.include_router(health.router, prefix="/health", tags=["health"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(cards.router, prefix="/cards", tags=["cards"])
api_router.include_router(sets.router, prefix="/sets", tags=["sets"])
api_router.include_router(inventory.router, prefix="/inventory", tags=["inventory"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(storage_locations.router, prefix="/storage-locations", tags=["storage-locations"])
api_router.include_router(decks.router, prefix="/decks", tags=["decks"])
api_router.include_router(collections.router, prefix="/collections", tags=["collections"])
api_router.include_router(sync.router, prefix="/sync", tags=["sync"])
api_router.include_router(assets.router, prefix="/assets", tags=["assets"])
api_router.include_router(exports.router, prefix="/exports", tags=["exports"])
api_router.include_router(backups.router, prefix="/backups", tags=["backups"])
