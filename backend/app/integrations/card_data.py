from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from app.config import settings


def _parse_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    try:
        if not value:
            return None
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


class YgoProDeckCardDataProvider:
    provider_key = "ygoprodeck"

    async def healthcheck(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
                response = await client.get(f"{settings.ygoprodeck_api_base_url}/checkDBVer.php")
                response.raise_for_status()
            return {
                "key": self.provider_key,
                "label": "YGOPRODeck",
                "category": "card-data",
                "configured": True,
                "available": True,
                "active": settings.card_data_provider == self.provider_key,
                "notes": "Kartendaten und Bild-URLs via YGOPRODeck API.",
            }
        except Exception as exc:
            return {
                "key": self.provider_key,
                "label": "YGOPRODeck",
                "category": "card-data",
                "configured": True,
                "available": False,
                "active": settings.card_data_provider == self.provider_key,
                "notes": f"Remote-Pruefung fehlgeschlagen: {exc}",
            }

    async def fetch_card(self, *, name: str | None = None, external_id: str | None = None, language: str | None = None) -> dict[str, Any] | None:
        async def attempt(request_language: str | None) -> dict[str, Any] | None:
            params: dict[str, Any] = {"misc": "yes"}
            if external_id:
                params["id"] = external_id
            elif name:
                params["name"] = name
            else:
                return None

            if request_language and request_language.lower() not in {"", "en"}:
                params["language"] = request_language.lower()

            data = await self._request(params)
            if data:
                return self._normalize_card(data[0])

            if name and not external_id:
                params.pop("name", None)
                params["fname"] = name
                data = await self._request(params)
                if data:
                    return self._normalize_card(data[0])

            return None

        direct = await attempt(language)
        if direct:
            return direct

        if language and language.lower() not in {"", "en"}:
            fallback = await attempt(None)
            if fallback:
                return fallback

        return None

    async def search_cards(self, query: str, language: str | None = None, limit: int = 8) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        params: dict[str, Any] = {"fname": query.strip(), "num": limit, "offset": 0, "misc": "yes"}
        if language and language.lower() not in {"", "en"}:
            params["language"] = language.lower()
        data = await self._request(params)
        return [self._normalize_card(entry) for entry in data[:limit]]

    async def fetch_sets(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.get(f"{settings.ygoprodeck_api_base_url}/cardsets.php")
            if response.status_code >= 400:
                return []
            payload = response.json()
        return [
            {
                "name": entry.get("set_name"),
                "set_code": entry.get("set_code"),
                "card_count": _parse_int(entry.get("num_of_cards")),
                "release_date": _parse_date(entry.get("tcg_date")),
                "payload": entry,
            }
            for entry in payload
            if entry.get("set_name")
        ]

    async def fetch_cards_for_set(self, set_name: str, language: str | None = None) -> list[dict[str, Any]]:
        async def attempt(request_language: str | None) -> list[dict[str, Any]]:
            params: dict[str, Any] = {"cardset": set_name, "misc": "yes"}
            if request_language and request_language.lower() not in {"", "en"}:
                params["language"] = request_language.lower()
            return [self._normalize_card(entry) for entry in await self._request(params)]

        direct = await attempt(language)
        if direct:
            return direct
        if language and language.lower() not in {"", "en"}:
            return await attempt(None)
        return direct

    async def _request(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            response = await client.get(f"{settings.ygoprodeck_api_base_url}/cardinfo.php", params=params)
            if response.status_code >= 400:
                return []
            payload = response.json()
        return payload.get("data", [])

    def _normalize_card(self, raw: dict[str, Any]) -> dict[str, Any]:
        card_sets = raw.get("card_sets", []) or []
        card_images = raw.get("card_images", []) or []
        prices = (raw.get("card_prices") or [{}])[0]
        return {
            "external_id": str(raw.get("id")),
            "name": raw.get("name"),
            "description": raw.get("desc"),
            "card_type": raw.get("type"),
            "subtype": raw.get("frameType"),
            "frame_type": raw.get("frameType"),
            "attribute": raw.get("attribute"),
            "monster_type": raw.get("race"),
            "archetype": raw.get("archetype"),
            "atk": _parse_int(raw.get("atk")),
            "defense": _parse_int(raw.get("def")),
            "level": _parse_int(raw.get("level")),
            "rank": _parse_int(raw.get("rank")),
            "link_rating": _parse_int(raw.get("linkval")),
            "link_arrows": raw.get("linkmarkers") or [],
            "pendulum_scale": _parse_int(raw.get("scale")),
            "pendulum_effect": raw.get("pend_desc"),
            "spell_trap_type": raw.get("race") if raw.get("type") in {"Spell Card", "Trap Card"} else None,
            "limitations": raw.get("banlist_info"),
            "card_sets": [
                {
                    "set_name": entry.get("set_name"),
                    "set_code": entry.get("set_code"),
                    "set_rarity": entry.get("set_rarity"),
                    "set_rarity_code": entry.get("set_rarity_code"),
                    "set_price": entry.get("set_price"),
                }
                for entry in card_sets
            ],
            "card_images": card_images,
            "prices": prices,
            "payload": raw,
        }


def get_card_data_provider() -> YgoProDeckCardDataProvider:
    return YgoProDeckCardDataProvider()
