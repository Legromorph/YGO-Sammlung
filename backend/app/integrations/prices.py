from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import logging
import re
import traceback

from app.config import settings
from app.integrations.card_data import get_card_data_provider
from app.integrations.cardmarket import (
    CARDMARKET_MATCH_EXACT,
    CARDMARKET_MATCH_EXACT_VARIANT,
    CARDMARKET_MATCH_FAILED,
    get_cardmarket_pricing_service,
)
from app.models import Card, CardPrint, SourceMapping

try:  # pragma: no cover - optional in local environments
    from playwright.async_api import async_playwright
except Exception:  # pragma: no cover
    async_playwright = None


logger = logging.getLogger(__name__)


def _parse_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_token(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _set_code_language_neutral_signature(set_code: str | None) -> tuple[str, str] | None:
    normalized_set_code = (set_code or "").strip().upper()
    if "-" not in normalized_set_code:
        return None
    series, suffix = normalized_set_code.split("-", 1)
    match = re.match(r"([A-Z]{2,3})([A-Z0-9-]+)$", suffix)
    if not match:
        return None
    return _normalize_token(series), _normalize_token(match.group(2))


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
        and _normalize_token(card_print.card_number) == _normalize_token(_derive_card_number(remote_print.get("set_code")))
        and _normalize_token(card_print.rarity) == _normalize_token(remote_print.get("set_rarity"))
        and _normalize_token(card_print.language) == _normalize_token(_derive_print_language(remote_print.get("set_code")))
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

    async def healthcheck(self) -> dict[str, Any]:
        probe = await get_card_data_provider().healthcheck()
        return {
            "key": self.provider_key,
            "label": "YGOPRODeck Market Snapshot",
            "category": "price",
            "configured": True,
            "available": probe["available"],
            "active": settings.price_provider == self.provider_key,
            "notes": "Print-spezifischer YGOPRODeck-Setpreis als separater Fallback-Provider.",
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
        del cardmarket_mapping, cardmarket_reference

        provider = get_card_data_provider()
        external_id = None
        for mapping in [print_mapping, card_mapping]:
            if mapping and mapping.provider_key == provider.provider_key and mapping.external_id:
                external_id = mapping.external_id
                break

        remote_card = await provider.fetch_card(
            external_id=external_id,
            name=card.name,
            language=None if external_id else card_print.language,
        )
        if not remote_card:
            return PriceSnapshot(
                market_price=None,
                currency="USD",
                provider_key=self.provider_key,
                source_key=f"{self.provider_key}:lookup_failed",
                match_quality=CARDMARKET_MATCH_FAILED,
                note="Kein passender YGOPRODeck-Datensatz gefunden.",
                indicators={
                    "source_market": f"{self.provider_key}:lookup_failed",
                    "provider_lookup_external_id": external_id,
                    "card_name": card.name,
                    "set_name": card_print.set_name,
                    "set_code": card_print.set_code,
                    "card_number": card_print.card_number,
                    "rarity": card_print.rarity,
                    "language": card_print.language,
                    "condition": condition,
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
        set_price = _parse_float(matched_print.get("set_price")) if matched_print else None
        if set_price is None:
            return PriceSnapshot(
                market_price=None,
                currency="USD",
                provider_key=self.provider_key,
                source_key=f"{self.provider_key}:unpriced",
                match_quality=CARDMARKET_MATCH_FAILED,
                note="Kein verlasslicher print-spezifischer YGOPRODeck-Preis vorhanden.",
                indicators={
                    "external_id": remote_card.get("external_id"),
                    "provider_lookup_external_id": external_id,
                    "source_market": f"{self.provider_key}:unpriced",
                    "matched_print_found": bool(matched_print),
                    "matched_set_code": matched_print.get("set_code") if matched_print else None,
                    "matched_card_number": _derive_card_number(matched_print.get("set_code")) if matched_print else None,
                    "matched_rarity": matched_print.get("set_rarity") if matched_print else None,
                    "matched_language": _derive_print_language(matched_print.get("set_code")) if matched_print else None,
                    "card_name": card.name,
                    "set_name": card_print.set_name,
                    "set_code": card_print.set_code,
                    "card_number": card_print.card_number,
                    "rarity": card_print.rarity,
                    "language": card_print.language,
                    "condition": condition,
                    "provider_diagnostics": {
                        "provider": self.provider_key,
                        "lookup_external_id": external_id,
                        "lookup_name": card.name,
                        "lookup_language": None if external_id else card_print.language,
                        "matched_remote_card": True,
                        "remote_external_id": remote_card.get("external_id"),
                        "matched_print_found": bool(matched_print),
                        "matched_set_code": matched_print.get("set_code") if matched_print else None,
                    },
                },
            )

        return PriceSnapshot(
            market_price=set_price,
            currency="USD",
            provider_key=self.provider_key,
            source_key=f"{self.provider_key}:set_price",
            match_quality=CARDMARKET_MATCH_EXACT,
            note="Print-spezifischer YGOPRODeck-Setpreis.",
            indicators={
                "external_id": remote_card.get("external_id"),
                "matched_set_code": matched_print.get("set_code"),
                "matched_card_number": _derive_card_number(matched_print.get("set_code")),
                "matched_rarity": matched_print.get("set_rarity"),
                "matched_language": _derive_print_language(matched_print.get("set_code")),
                "set_price": set_price,
                "source_market": f"{self.provider_key}:set_price",
                "card_name": card.name,
                "set_name": card_print.set_name,
                "set_code": card_print.set_code,
                "card_number": card_print.card_number,
                "rarity": card_print.rarity,
                "language": card_print.language,
                "note": "Print-spezifischer YGOPRODeck-Setpreis.",
                "provider_diagnostics": {
                    "provider": self.provider_key,
                    "lookup_external_id": external_id,
                    "lookup_name": card.name,
                    "lookup_language": None if external_id else card_print.language,
                    "matched_remote_card": True,
                    "remote_external_id": remote_card.get("external_id"),
                    "matched_set_code": matched_print.get("set_code"),
                    "matched_card_number": _derive_card_number(matched_print.get("set_code")),
                    "matched_rarity": matched_print.get("set_rarity"),
                },
            },
        )


class CardmarketPriceProvider:
    provider_key = "cardmarket"

    async def healthcheck(self) -> dict[str, Any]:
        configured = async_playwright is not None
        return {
            "key": self.provider_key,
            "label": "Cardmarket Exact Print Median",
            "category": "price",
            "configured": configured,
            "available": configured,
            "active": settings.price_provider == self.provider_key,
            "notes": "Exakter Cardmarket-Produktlink, gefilterte Produktseite, Median der ersten 5 Angebote.",
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
        del card_mapping, print_mapping, cardmarket_mapping

        service = get_cardmarket_pricing_service()
        try:
            result = await service.fetch_for_print(
                card,
                card_print,
                condition,
                cardmarket_reference=cardmarket_reference,
            )
        except Exception as exc:
            logger.exception("Cardmarket pricing failed for %s (%s): %s", card.name, card_print.set_code, exc)
            return PriceSnapshot(
                market_price=None,
                currency="EUR",
                provider_key=self.provider_key,
                source_key=f"{self.provider_key}:failed",
                match_quality=CARDMARKET_MATCH_FAILED,
                note=f"Cardmarket-Preisupdate fehlgeschlagen: {exc}",
                cardmarket_reference=cardmarket_reference,
                indicators={
                    "source": "cardmarket",
                    "source_url": cardmarket_reference,
                    "parse_status": "failed",
                    "exception_type": type(exc).__name__,
                    "error": str(exc),
                    "provider_diagnostics": {
                        "provider": "cardmarket",
                        "card_name": card.name,
                        "set_code": card_print.set_code,
                        "card_number": card_print.card_number,
                        "rarity": card_print.rarity,
                        "language": card_print.language,
                        "condition": condition,
                        "requested_cardmarket_reference": cardmarket_reference,
                        "exception_type": type(exc).__name__,
                        "exception_message": str(exc),
                        "exception_traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
                    },
                },
            )

        indicators = {
            "card_print_id": card_print.id,
            "source": "cardmarket",
            "source_url": result.source_url,
            "source_product_url": result.product_url,
            "currency": result.currency,
            "fetch_mode": result.fetch_mode,
            "price_trend": result.price_trend,
            "avg_1d": result.avg_1d,
            "avg_7d": result.avg_7d,
            "avg_30d": result.avg_30d,
            "market_price_median_top5": result.market_price_median_top5,
            "selected_market_price": result.market_price_median_top5,
            "offers_considered_count": result.offers_considered_count,
            "offer_count_considered": result.offers_considered_count,
            "filters_used": result.filters_used,
            "fetched_at": result.fetched_at.isoformat(),
            "top5_offer_prices": result.top5_offer_prices,
            "raw_offer_prices_sample": result.top5_offer_prices,
            "parse_status": result.parse_status,
            "match_quality": result.match_quality,
            "note": result.note,
            "card_name": card.name,
            "set_name": card_print.set_name,
            "set_code": card_print.set_code,
            "card_number": card_print.card_number,
            "rarity": card_print.rarity,
            "language": card_print.language,
            "condition": condition,
            "provider_diagnostics": result.diagnostics,
        }
        if result.resolved_product:
            indicators.update(
                {
                    "resolved_cardmarket_product_url": result.resolved_product.url,
                    "resolved_cardmarket_set_slug": result.resolved_product.set_slug,
                    "resolved_cardmarket_product_slug": result.resolved_product.product_slug,
                    "resolved_cardmarket_product_name": result.resolved_product.product_name,
                    "resolved_cardmarket_set_name": result.resolved_product.set_name,
                    "resolved_cardmarket_variant_name": result.resolved_product.variant_name,
                    "resolved_cardmarket_match_quality": result.resolved_product.match_quality,
                    "resolved_cardmarket_verified_at": result.resolved_product.verified_at.isoformat() if result.resolved_product.verified_at else None,
                    "resolved_cardmarket_reason": result.resolved_product.reason,
                    "resolved_cardmarket_parse_status": result.resolved_product.parse_status,
                    "resolved_cardmarket_set_slug_source": result.resolved_product.set_slug_source,
                    "resolved_cardmarket_rarity": result.resolved_product.rarity,
                    "resolved_cardmarket_card_number": result.resolved_product.card_number,
                }
            )

        return PriceSnapshot(
            market_price=result.market_price,
            currency=result.currency,
            provider_key=self.provider_key,
            source_key=f"{self.provider_key}:median_top5",
            match_quality=result.match_quality,
            note=result.note,
            cardmarket_reference=result.product_url,
            indicators=indicators,
        )


def get_price_providers():
    return [YgoProDeckPriceProvider(), CardmarketPriceProvider()]


def get_active_price_provider():
    for provider in get_price_providers():
        if provider.provider_key == settings.price_provider:
            return provider
    return YgoProDeckPriceProvider()
