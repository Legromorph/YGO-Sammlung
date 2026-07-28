from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any
import logging
import re

from app.config import settings
from app.integrations.card_data import get_card_data_provider
from app.integrations.cardmarket import (
    CARDMARKET_MATCH_EXACT,
    CARDMARKET_MATCH_EXACT_VARIANT,
    CARDMARKET_MATCH_FAILED,
)
from app.integrations.price_values import parse_positive_price
from app.models import Card, CardPrint, InventoryItem, SourceMapping


logger = logging.getLogger(__name__)
PRICE_MATCH_FALLBACK_NAME_ONLY = "fallback_name_only"
PRINT_LANGUAGE_PREFIXES = ("DE", "EN", "FR", "IT", "ES", "SP", "PT", "JP", "KR")


def _normalize_token(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _set_code_language_neutral_signature(set_code: str | None) -> tuple[str, str] | None:
    normalized_set_code = (set_code or "").strip().upper()
    if "-" not in normalized_set_code:
        return None
    series, suffix = normalized_set_code.split("-", 1)
    language_prefix_pattern = "|".join(PRINT_LANGUAGE_PREFIXES)
    match = re.match(rf"(?:{language_prefix_pattern})([A-Z0-9-]+)$", suffix)
    if not match:
        return None
    return _normalize_token(series), _normalize_token(match.group(1))


def _set_codes_match_language_neutral(left: str | None, right: str | None) -> bool:
    normalized_left = _normalize_token(left)
    normalized_right = _normalize_token(right)
    if not normalized_left or not normalized_right:
        return False
    if normalized_left == normalized_right:
        return True
    left_signature = _set_code_language_neutral_signature(left)
    right_signature = _set_code_language_neutral_signature(right)
    return bool(left_signature and right_signature and left_signature == right_signature)


def _derive_card_number(set_code: str | None) -> str | None:
    if not set_code or "-" not in set_code:
        return None
    return set_code.rsplit("-", 1)[-1] or None


def _card_number_language_neutral(value: str | None) -> str:
    normalized_value = (value or "").strip().upper()
    language_prefix_pattern = "|".join(PRINT_LANGUAGE_PREFIXES)
    match = re.match(rf"^(?:{language_prefix_pattern})([A-Z0-9-]+)$", normalized_value)
    return _normalize_token(match.group(1) if match else normalized_value)


def _derive_print_language(set_code: str | None) -> str:
    if not set_code or "-" not in set_code:
        return "en"
    suffix = set_code.split("-", 1)[1].upper()
    if suffix.startswith("DE"):
        return "de"
    if suffix.startswith("EN"):
        return "en"
    if suffix.startswith("FR"):
        return "fr"
    if suffix.startswith("IT"):
        return "it"
    if suffix.startswith("ES") or suffix.startswith("SP"):
        return "es"
    if suffix.startswith("PT"):
        return "pt"
    if suffix.startswith("JP"):
        return "jp"
    if suffix.startswith("KR"):
        return "ko"
    return "en"


def _match_remote_print(card_print: CardPrint, remote_print: dict[str, Any]) -> bool:
    return (
        _set_codes_match_language_neutral(card_print.set_code, remote_print.get("set_code"))
        and _card_number_language_neutral(card_print.card_number)
        == _card_number_language_neutral(_derive_card_number(remote_print.get("set_code")))
        and _normalize_token(card_print.rarity) == _normalize_token(remote_print.get("set_rarity"))
    )


@dataclass(slots=True)
class PriceSnapshot:
    market_price: float | None
    currency: str
    provider_key: str
    source_key: str
    match_quality: str | None = None
    note: str | None = None
    cardmarket_reference: str | None = None
    indicators: dict[str, Any] = field(default_factory=dict)


class YgoProDeckPriceProvider:
    provider_key = "ygoprodeck"
    lookup_timeout_seconds = max(20, settings.request_timeout_seconds * 2)

    def __init__(self) -> None:
        self._prepared_cards_by_external_id: dict[str, dict[str, Any]] = {}
        self._prepared_cards_by_name: dict[str, dict[str, Any]] = {}

    async def prepare_price_run(
        self,
        contexts: list[
            tuple[
                InventoryItem,
                SourceMapping | None,
                SourceMapping | None,
                SourceMapping | None,
            ]
        ],
    ) -> dict[str, int]:
        set_names = sorted(
            {
                item.card_print.set_name.strip()
                for item, _card_mapping, _print_mapping, _cardmarket_mapping in contexts
                if item.card_print.set_name and item.card_print.set_name.strip()
            }
        )
        if len(contexts) < 2 or not set_names:
            return {"requested_sets": 0, "loaded_sets": 0, "cached_cards": 0}

        provider = get_card_data_provider()
        semaphore = asyncio.Semaphore(3)

        async def fetch_set(set_name: str) -> list[dict[str, Any]]:
            async with semaphore:
                try:
                    return await asyncio.wait_for(
                        provider.fetch_cards_for_set(set_name, tcgplayer_data=True),
                        timeout=self.lookup_timeout_seconds,
                    )
                except asyncio.TimeoutError:
                    logger.warning("YGOPRODeck set prefetch timed out for '%s'.", set_name)
                    return []
                except Exception as exc:
                    logger.warning("YGOPRODeck set prefetch failed for '%s': %s", set_name, exc)
                    return []

        set_results = await asyncio.gather(*(fetch_set(set_name) for set_name in set_names))
        loaded_sets = 0
        for remote_cards in set_results:
            if remote_cards:
                loaded_sets += 1
            for remote_card in remote_cards:
                external_id = str(remote_card.get("external_id") or "").strip()
                if external_id:
                    self._prepared_cards_by_external_id[external_id] = remote_card
                normalized_name = _normalize_token(remote_card.get("name"))
                if normalized_name:
                    self._prepared_cards_by_name[normalized_name] = remote_card

        return {
            "requested_sets": len(set_names),
            "loaded_sets": loaded_sets,
            "cached_cards": len(self._prepared_cards_by_external_id),
        }

    async def healthcheck(self) -> dict[str, Any]:
        probe = await get_card_data_provider().healthcheck()
        return {
            "key": self.provider_key,
            "label": "Printpreise via YGOPRODeck",
            "category": "price",
            "configured": True,
            "available": probe["available"],
            "active": settings.price_provider == self.provider_key,
            "notes": "Print-spezifische TCGPlayer-Marktdaten; Cardmarket-Kartenpreis nur als klar markierter Fallback.",
        }

    async def fetch_price(
        self,
        card: Card,
        card_print: CardPrint,
        condition: str | None = None,
        *,
        card_mapping: SourceMapping | None = None,
        print_mapping: SourceMapping | None = None,
        cardmarket_mapping: SourceMapping | None = None,
        cardmarket_reference: str | None = None,
    ) -> PriceSnapshot:
        del cardmarket_mapping

        provider = get_card_data_provider()
        external_id = None
        for mapping in [print_mapping, card_mapping]:
            if mapping and mapping.provider_key == provider.provider_key and mapping.external_id:
                external_id = mapping.external_id
                break

        remote_card = self._prepared_cards_by_external_id.get(str(external_id)) if external_id else None
        if remote_card is None:
            remote_card = self._prepared_cards_by_name.get(_normalize_token(card.name))
        lookup_mode = "prefetched_set" if remote_card is not None else "single_card"
        if remote_card is None:
            remote_card = await provider.fetch_card(
                external_id=external_id,
                name=card.name,
                language=None if external_id else card_print.language,
                tcgplayer_data=True,
            )
        base_indicators = {
            "provider_lookup_external_id": external_id,
            "provider_lookup_mode": lookup_mode,
            "card_name": card.name,
            "set_name": card_print.set_name,
            "set_code": card_print.set_code,
            "card_number": card_print.card_number,
            "rarity": card_print.rarity,
            "language": card_print.language,
            "condition": condition,
            "cardmarket_reference": cardmarket_reference,
            "price_dataset": "tcgplayer",
        }
        if not remote_card:
            return PriceSnapshot(
                market_price=None,
                currency="USD",
                provider_key=self.provider_key,
                source_key=f"{self.provider_key}:lookup_failed",
                match_quality=CARDMARKET_MATCH_FAILED,
                note="Kein passender YGOPRODeck-Datensatz gefunden.",
                indicators={
                    **base_indicators,
                    "source_market": f"{self.provider_key}:lookup_failed",
                    "provider_diagnostics": {
                        "provider": self.provider_key,
                        "lookup_external_id": external_id,
                        "lookup_name": card.name,
                        "lookup_language": None if external_id else card_print.language,
                        "matched_remote_card": False,
                    },
                },
            )

        matched_print = next((entry for entry in (remote_card.get("card_sets") or []) if _match_remote_print(card_print, entry)), None)
        set_price = parse_positive_price(matched_print.get("set_price")) if matched_print else None
        matched_print_indicators = {
            "matched_print_found": bool(matched_print),
            "matched_set_code": matched_print.get("set_code") if matched_print else None,
            "matched_card_number": _derive_card_number(matched_print.get("set_code")) if matched_print else None,
            "matched_rarity": matched_print.get("set_rarity") if matched_print else None,
            "matched_language": _derive_print_language(matched_print.get("set_code")) if matched_print else None,
            "source_url": matched_print.get("set_url") if matched_print else None,
        }
        provider_diagnostics = {
            "provider": self.provider_key,
            "lookup_external_id": external_id,
            "lookup_name": card.name,
            "lookup_language": None if external_id else card_print.language,
            "matched_remote_card": True,
            "remote_external_id": remote_card.get("external_id"),
            **matched_print_indicators,
        }

        if set_price is not None:
            note = "Print-spezifischer TCGPlayer-Marktpreis via YGOPRODeck; der Karten-Zustand ist nicht eingepreist."
            source_key = f"{self.provider_key}:tcgplayer_set_price"
            return PriceSnapshot(
                market_price=set_price,
                currency="USD",
                provider_key=self.provider_key,
                source_key=source_key,
                match_quality=CARDMARKET_MATCH_EXACT,
                note=note,
                cardmarket_reference=cardmarket_reference,
                indicators={
                    **base_indicators,
                    **matched_print_indicators,
                    "external_id": remote_card.get("external_id"),
                    "set_price": set_price,
                    "set_price_low": parse_positive_price(matched_print.get("set_price_low")),
                    "set_edition": matched_print.get("set_edition"),
                    "source_market": source_key,
                    "pricing_strategy_used": "exact_print_tcgplayer_market",
                    "note": note,
                    "provider_diagnostics": provider_diagnostics,
                },
            )

        generic_cardmarket_price = parse_positive_price((remote_card.get("prices") or {}).get("cardmarket_price"))
        if settings.price_allow_card_level_fallback and generic_cardmarket_price is not None:
            note = (
                "Kein positiver Printpreis vorhanden. Verwendet wird der niedrigste Cardmarket-Kartenpreis "
                "über alle Druckversionen via YGOPRODeck; bitte den Print prüfen."
            )
            source_key = f"{self.provider_key}:cardmarket_card_price"
            return PriceSnapshot(
                market_price=generic_cardmarket_price,
                currency="EUR",
                provider_key=self.provider_key,
                source_key=source_key,
                match_quality=PRICE_MATCH_FALLBACK_NAME_ONLY,
                note=note,
                cardmarket_reference=cardmarket_reference,
                indicators={
                    **base_indicators,
                    **matched_print_indicators,
                    "external_id": remote_card.get("external_id"),
                    "source_market": source_key,
                    "pricing_strategy_used": "card_level_cardmarket_fallback",
                    "requires_review": True,
                    "note": note,
                    "provider_diagnostics": provider_diagnostics,
                },
            )

        return PriceSnapshot(
            market_price=None,
            currency="USD",
            provider_key=self.provider_key,
            source_key=f"{self.provider_key}:unpriced",
            match_quality=CARDMARKET_MATCH_FAILED,
            note="Kein positiver, print-spezifischer Marktpreis vorhanden.",
            cardmarket_reference=cardmarket_reference,
            indicators={
                **base_indicators,
                **matched_print_indicators,
                "external_id": remote_card.get("external_id"),
                "source_market": f"{self.provider_key}:unpriced",
                "provider_diagnostics": provider_diagnostics,
            },
        )


class CardmarketPriceProvider:
    provider_key = "cardmarket"
    lookup_timeout_seconds = settings.request_timeout_seconds

    async def healthcheck(self) -> dict[str, Any]:
        credentials_configured = all(
            [
                settings.cardmarket_app_token,
                settings.cardmarket_app_secret,
                settings.cardmarket_access_token,
                settings.cardmarket_access_secret,
            ]
        )
        return {
            "key": self.provider_key,
            "label": "Cardmarket (manuell)",
            "category": "price",
            "configured": credentials_configured,
            "available": False,
            "active": settings.price_provider == self.provider_key,
            "notes": (
                "Automatisierte Seitenabrufe sind deaktiviert. Produktlinks und Preise werden manuell gepflegt, "
                "bis eine autorisierte API-Anbindung verfügbar ist."
            ),
        }

    async def fetch_price(
        self,
        card: Card,
        card_print: CardPrint,
        condition: str | None = None,
        *,
        card_mapping: SourceMapping | None = None,
        print_mapping: SourceMapping | None = None,
        cardmarket_mapping: SourceMapping | None = None,
        cardmarket_reference: str | None = None,
    ) -> PriceSnapshot:
        del card, card_print, condition, card_mapping, print_mapping, cardmarket_mapping
        return PriceSnapshot(
            market_price=None,
            currency="EUR",
            provider_key=self.provider_key,
            source_key=f"{self.provider_key}:manual_only",
            match_quality=CARDMARKET_MATCH_FAILED,
            note=(
                "Automatisierte Cardmarket-Preisabfragen sind deaktiviert. "
                "Bitte einen bestätigten Produktlink und bei Bedarf einen manuellen Marktpreis verwenden."
            ),
            cardmarket_reference=cardmarket_reference,
            indicators={
                "source": "cardmarket",
                "source_url": cardmarket_reference,
                "parse_status": "manual_only",
                "requires_review": True,
            },
        )


def get_price_providers():
    return [YgoProDeckPriceProvider(), CardmarketPriceProvider()]


def get_active_price_provider():
    for provider in get_price_providers():
        if provider.provider_key == settings.price_provider:
            return provider
    return None
