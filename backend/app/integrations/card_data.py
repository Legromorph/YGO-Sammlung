from __future__ import annotations

import asyncio
from datetime import date
from difflib import SequenceMatcher
from typing import Any
import re
import unicodedata

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


def _normalize_search_text(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    text = (
        text.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _significant_tokens(value: str) -> tuple[str, ...]:
    return tuple(token for token in value.split(" ") if len(token) >= 2)


class YgoProDeckCardDataProvider:
    provider_key = "ygoprodeck"
    default_headers = {
        "User-Agent": "Mozilla/5.0 (compatible; YGO-Sammlung/1.0; +https://ygoprodeck.com/)",
        "Accept": "application/json",
    }

    def __init__(self) -> None:
        self._search_catalog_cache: dict[str, list[dict[str, Any]]] = {}
        self._search_catalog_locks: dict[str, asyncio.Lock] = {}

    async def healthcheck(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, headers=self.default_headers) as client:
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
        normalized_limit = max(1, limit)
        api_candidate_limit = max(normalized_limit * 4, 16)
        params: dict[str, Any] = {"fname": query.strip(), "num": api_candidate_limit, "offset": 0, "misc": "yes"}
        if language and language.lower() not in {"", "en"}:
            params["language"] = language.lower()
        data = await self._request(params)
        normalized_query = _normalize_search_text(query)
        ranked_candidates: list[tuple[int, dict[str, Any]]] = []
        seen_ids: set[str] = set()

        for raw_entry in data:
            entry = self._decorate_search_entry(self._normalize_card(raw_entry))
            external_id = str(entry.get("external_id", "")).strip()
            if not external_id or external_id in seen_ids:
                continue
            score = self._score_search_entry(entry, normalized_query)
            if score <= 0:
                continue
            seen_ids.add(external_id)
            ranked_candidates.append((score + 25, entry))

        if len(normalized_query.replace(" ", "")) >= 3:
            scored_matches = await self._search_catalog_contains(
                query=query,
                language=language,
                exclude_ids=seen_ids,
                limit=max(normalized_limit * 8, 24),
            )
            for entry in scored_matches:
                ranked_candidates.append((self._score_search_entry(entry, normalized_query), entry))

        ranked_candidates.sort(
            key=lambda item: (
                -item[0],
                str(item[1].get("name") or ""),
            )
        )
        return [entry for _, entry in ranked_candidates[:normalized_limit]]

    async def fetch_sets(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, headers=self.default_headers) as client:
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

    async def fetch_cards_page(self, *, offset: int = 0, limit: int = 1000, language: str | None = None) -> list[dict[str, Any]]:
        normalized_limit = max(1, min(int(limit), 1000))
        params: dict[str, Any] = {"num": normalized_limit, "offset": max(0, int(offset)), "misc": "yes"}
        if language and language.lower() not in {"", "en"}:
            params["language"] = language.lower()
        data = await self._request(params)
        return [self._normalize_card(entry) for entry in data]

    async def _request(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds, headers=self.default_headers) as client:
            response = await client.get(f"{settings.ygoprodeck_api_base_url}/cardinfo.php", params=params)
            if response.status_code >= 400:
                return []
            payload = response.json()
        return payload.get("data", [])

    async def _search_catalog_contains(
        self,
        *,
        query: str,
        language: str | None,
        exclude_ids: set[str],
        limit: int,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        catalog = await self._get_search_catalog(language)
        normalized_query = _normalize_search_text(query)
        if not normalized_query:
            return []

        scored_entries: list[tuple[int, dict[str, Any]]] = []
        for entry in catalog:
            external_id = str(entry.get("external_id", "")).strip()
            if not external_id or external_id in exclude_ids:
                continue

            score = self._score_search_entry(entry, normalized_query)
            if score <= 0:
                continue
            scored_entries.append((score, entry))

        scored_entries.sort(
            key=lambda item: (
                -item[0],
                str(item[1].get("name") or ""),
            )
        )
        return [entry for _, entry in scored_entries[:limit]]

    async def _get_search_catalog(self, language: str | None) -> list[dict[str, Any]]:
        cache_key = (language or "en").strip().lower() or "en"
        cached = self._search_catalog_cache.get(cache_key)
        if cached is not None:
            return cached

        lock = self._search_catalog_locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            cached = self._search_catalog_cache.get(cache_key)
            if cached is not None:
                return cached

            catalog: list[dict[str, Any]] = []
            offset = 0
            page_size = 1000
            while True:
                page = await self.fetch_cards_page(offset=offset, limit=page_size, language=language)
                if not page:
                    break

                for entry in page:
                    catalog.append(self._decorate_search_entry(entry))

                if len(page) < page_size:
                    break
                offset += page_size
                if offset >= 40000:
                    break

            self._search_catalog_cache[cache_key] = catalog
            return catalog

    def _decorate_search_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        normalized_name = _normalize_search_text(entry.get("name"))
        return {
            **entry,
            "_normalized_name": normalized_name,
            "_normalized_compact_name": normalized_name.replace(" ", ""),
            "_normalized_tokens": tuple(token for token in normalized_name.split(" ") if token),
        }

    def _score_search_entry(self, entry: dict[str, Any], normalized_query: str) -> int:
        normalized_name = str(entry.get("_normalized_name") or "")
        compact_name = str(entry.get("_normalized_compact_name") or "")
        tokens = tuple(str(token) for token in entry.get("_normalized_tokens") or ())
        compact_query = normalized_query.replace(" ", "")
        query_tokens = _significant_tokens(normalized_query)

        if not normalized_name:
            return 0
        if normalized_name == normalized_query or compact_name == compact_query:
            return 1000
        if normalized_name.startswith(normalized_query):
            return 900
        if normalized_query in normalized_name:
            return 840 - min(normalized_name.index(normalized_query) * 4, 220)
        if compact_query and compact_query in compact_name:
            return 750 - min(compact_name.index(compact_query), 250)

        candidate_query_tokens = query_tokens or _significant_tokens(compact_query)
        if not candidate_query_tokens:
            return 0

        token_scores: list[int] = []
        for query_token in candidate_query_tokens:
            best_token_score = 0
            for token in tokens:
                token_score = self._score_search_token(query_token, token)
                if token_score > best_token_score:
                    best_token_score = token_score
            if best_token_score <= 0:
                return 0
            token_scores.append(best_token_score)

        aggregate_score = int(sum(token_scores) / len(token_scores))
        if len(token_scores) > 1:
            aggregate_score += min(120, len(token_scores) * 25)
        return aggregate_score

    def _score_search_token(self, query_token: str, token: str) -> int:
        if len(query_token) < 2 or len(token) < 2:
            return 0
        if token == query_token:
            return 820
        if token.startswith(query_token):
            return 760
        if query_token in token:
            return 700 - abs(len(token) - len(query_token)) * 12
        if token in query_token and len(token) >= max(4, len(query_token) - 2):
            return 620 - abs(len(token) - len(query_token)) * 12

        ratio = SequenceMatcher(None, query_token, token).ratio()
        if ratio >= 0.76 and token[:2] == query_token[:2]:
            return int(ratio * 700)
        if len(query_token) >= 5 and len(token) >= 5 and ratio >= 0.84:
            return int(ratio * 650)
        return 0

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
    return _DEFAULT_CARD_DATA_PROVIDER


_DEFAULT_CARD_DATA_PROVIDER = YgoProDeckCardDataProvider()
