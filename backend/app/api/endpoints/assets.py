from __future__ import annotations

from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.config import settings

router = APIRouter()

ALLOWED_IMAGE_HOSTS = {"images.ygoprodeck.com"}


@router.get("/placeholder")
async def placeholder_asset(
    item_id: int = Query(default=0),
    label: str = Query(default="Card"),
) -> Response:
    safe_label = (label or "Card").replace("&", "&amp;").replace("<", "").replace(">", "")
    svg = f"""
    <svg xmlns="http://www.w3.org/2000/svg" width="360" height="520" viewBox="0 0 360 520" fill="none">
      <rect width="360" height="520" rx="28" fill="#10231F"/>
      <rect x="18" y="18" width="324" height="484" rx="20" fill="url(#g)"/>
      <circle cx="278" cy="92" r="68" fill="#D6A64D" fill-opacity="0.22"/>
      <path d="M52 402C110 330 168 294 228 294C277 294 308 319 330 360V470H52V402Z" fill="#0E1515" fill-opacity="0.4"/>
      <text x="38" y="76" fill="#F6F1DE" font-size="24" font-family="Arial, sans-serif">YGO Collection</text>
      <text x="38" y="420" fill="#F6F1DE" font-size="30" font-family="Arial, sans-serif">{safe_label}</text>
      <text x="38" y="456" fill="#C1C4B3" font-size="18" font-family="Arial, sans-serif">Item #{item_id}</text>
      <defs>
        <linearGradient id="g" x1="18" y1="18" x2="342" y2="502" gradientUnits="userSpaceOnUse">
          <stop stop-color="#1D4037"/>
          <stop offset="1" stop-color="#11191A"/>
        </linearGradient>
      </defs>
    </svg>
    """
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/proxy")
async def proxy_asset(url: str = Query(min_length=10)) -> Response:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in ALLOWED_IMAGE_HOSTS:
        return Response(status_code=400, content="Unsupported remote image host")

    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, follow_redirects=True) as client:
        response = await client.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36",
                "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            },
        )
        response.raise_for_status()

    return Response(
        content=response.content,
        media_type=response.headers.get("content-type", "image/jpeg"),
        headers={"Cache-Control": "public, max-age=86400"},
    )
