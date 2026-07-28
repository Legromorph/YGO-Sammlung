from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services.exports import build_collection_json_export, build_inventory_csv_export
from app.time_utils import utc_now

router = APIRouter()


def _download_headers(extension: str) -> dict[str, str]:
    timestamp = utc_now().strftime("%Y%m%d-%H%M%S")
    return {
        "Content-Disposition": f'attachment; filename="ygo-sammlung-{timestamp}.{extension}"',
        "Cache-Control": "no-store",
    }


@router.get("/collection.json")
async def export_collection_json(db: AsyncSession = Depends(get_db)) -> Response:
    payload = await build_collection_json_export(db)
    return Response(
        content=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        media_type="application/json",
        headers=_download_headers("json"),
    )


@router.get("/inventory.csv")
async def export_inventory_csv(db: AsyncSession = Depends(get_db)) -> Response:
    content = await build_inventory_csv_export(db)
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers=_download_headers("csv"),
    )
