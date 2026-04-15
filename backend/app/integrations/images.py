from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from app.config import settings
from app.integrations.card_data import get_card_data_provider
from app.models import Card, CardPrint, SourceMapping


def slugify(value: str) -> str:
    lowered = "".join(char.lower() if char.isalnum() else "-" for char in value)
    return "-".join(part for part in lowered.split("-") if part) or "card"


@dataclass
class ImageDownloadResult:
    remote_url: str
    local_path: str
    thumbnail_path: str
    content_hash: str
    width: int
    height: int


class YgoProDeckImageProvider:
    provider_key = "ygoprodeck"

    async def healthcheck(self) -> dict[str, Any]:
        try:
            settings.cards_media_path.mkdir(parents=True, exist_ok=True)
            writable = settings.cards_media_path.exists()
        except Exception:
            writable = False

        return {
            "key": self.provider_key,
            "label": "YGOPRODeck Images",
            "category": "image",
            "configured": True,
            "available": writable,
            "active": settings.image_provider == self.provider_key,
            "notes": "Bilder werden lokal gespeichert und bei erneutem Sync nicht doppelt geladen.",
        }

    async def download_image(self, card: Card, card_print: CardPrint, mapping: SourceMapping | None = None) -> ImageDownloadResult | None:
        provider = get_card_data_provider()
        remote_card = await provider.fetch_card(
            external_id=mapping.external_id if mapping and mapping.provider_key == provider.provider_key else None,
            name=card.name,
            language=card_print.language,
        )
        if not remote_card:
            return None

        image_payload = (remote_card.get("card_images") or [{}])[0]
        remote_url = image_payload.get("image_url")
        if not remote_url:
            return None

        external_id = remote_card.get("external_id") or card_print.id
        base_name = f"{slugify(card.name)}-{external_id}"
        extension = Path(remote_url).suffix or ".jpg"
        local_rel = f"{settings.cards_image_subdir}/{base_name}{extension}"
        thumb_rel = f"{settings.cards_image_subdir}/{base_name}-thumb{extension}"
        local_abs = settings.media_root_path / local_rel
        thumb_abs = settings.media_root_path / thumb_rel

        if local_abs.exists() and thumb_abs.exists():
            image = Image.open(local_abs)
            return ImageDownloadResult(
                remote_url=remote_url,
                local_path=local_rel,
                thumbnail_path=thumb_rel,
                content_hash=sha256(local_abs.read_bytes()).hexdigest(),
                width=image.width,
                height=image.height,
            )

        settings.cards_media_path.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.get(remote_url)
            response.raise_for_status()
            content = response.content

        local_abs.write_bytes(content)
        image = Image.open(BytesIO(content))
        thumbnail = image.copy()
        thumbnail.thumbnail((360, 525))
        thumbnail.save(thumb_abs)

        return ImageDownloadResult(
            remote_url=remote_url,
            local_path=local_rel,
            thumbnail_path=thumb_rel,
            content_hash=sha256(content).hexdigest(),
            width=image.width,
            height=image.height,
        )


def get_active_image_provider() -> YgoProDeckImageProvider:
    return YgoProDeckImageProvider()
