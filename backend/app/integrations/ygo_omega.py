from __future__ import annotations

from pathlib import Path

from app.config import settings


class YgoOmegaProbe:
    provider_key = "ygo_omega"

    async def healthcheck(self) -> dict:
        if not settings.ygo_omega_directory:
            return {
                "key": self.provider_key,
                "label": "YGO Omega",
                "category": "card-data",
                "configured": False,
                "available": False,
                "active": False,
                "notes": "Kein lokaler Omega-Pfad konfiguriert. Die Architektur bleibt fuer eine spaetere lokale Integration vorbereitet.",
            }

        base_path = Path(settings.ygo_omega_directory)
        files_path = base_path / "YGO Omega_Data" / "Files"
        available = base_path.exists()
        notes = "Pfad gefunden." if available else "Konfigurierter Pfad existiert nicht."
        if available and files_path.exists():
            notes += " Lokale Dateien wurden erkannt, eine offizielle lokale API ist jedoch nicht dokumentiert."

        return {
            "key": self.provider_key,
            "label": "YGO Omega",
            "category": "card-data",
            "configured": True,
            "available": available,
            "active": False,
            "notes": notes,
        }


def get_ygo_omega_probe() -> YgoOmegaProbe:
    return YgoOmegaProbe()
