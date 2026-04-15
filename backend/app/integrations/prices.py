from __future__ import annotations

from dataclasses import dataclass, field
import logging
import re
from statistics import median
from typing import Any

from app.config import settings
from app.integrations.card_data import get_card_data_provider
from app.integrations.cardmarket_links import (
    CARDMARKET_MATCH_AMBIGUOUS,
    CARDMARKET_MATCH_EXACT,
    CARDMARKET_MATCH_EXACT_VARIANT,
    CARDMARKET_MATCH_SET_NAME,
    normalize_cardmarket_product_url,
    resolve_cardmarket_product_url,
)
from app.integrations.cardmarket_public import get_cardmarket_public_client
from app.models import Card, CardPrint, SourceMapping

try:  # pragma: no cover - optional in non-Docker/local setups
    from playwright.async_api import async_playwright
except Exception:  # pragma: no cover - fallback when Playwright is unavailable
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


def _derive_card_number(set_code: str | None) -> str | None:
    if not set_code or "-" not in set_code:
        return None
    return set_code.rsplit("-", 1)[-1] or None


def _derive_print_language(set_code: str | None) -> str:
    if not set_code or "-" not in set_code:
        return "en"

    segment = set_code.split("-", 1)[-1].upper()
    match = re.match(r"([A-Z]{2,3})", segment)
    token = match.group(1) if match else ""

    if token.startswith("EN"):
        return "en"
    if token.startswith("DE"):
        return "de"
    if token.startswith("FR"):
        return "fr"
    if token.startswith("IT"):
        return "it"
    if token.startswith("SP") or token.startswith("ES"):
        return "es"
    if token.startswith("PT"):
        return "pt"
    if token.startswith("JP"):
        return "jp"
    if token.startswith("KR"):
        return "ko"
    return "en"


def _exact_cardmarket_reference(
    *,
    cardmarket_mapping: SourceMapping | None,
    cardmarket_reference: str | None,
) -> str | None:
    if cardmarket_mapping:
        exact_url = normalize_cardmarket_product_url(cardmarket_mapping.external_url) or normalize_cardmarket_product_url(cardmarket_mapping.external_id)
        if exact_url:
            return exact_url
    exact_reference = normalize_cardmarket_product_url(cardmarket_reference)
    if exact_reference:
        return exact_reference
    return None


def _card_print_has_variant(card_print: CardPrint) -> bool:
    if card_print.cardmarket_variant_name:
        return True
    return bool(card_print.cardmarket_product_slug and re.search(r"(?:^|-)V-?\d+(?:-|$)", card_print.cardmarket_product_slug, flags=re.IGNORECASE))


def _cardmarket_language_filter(language: str | None, fallback_language: str | None = None) -> tuple[int, str]:
    candidate = (language or fallback_language or "en").strip().lower()
    if candidate.startswith("de"):
        return 3, "de-DE"
    if candidate.startswith("en"):
        return 1, "en-US"
    return 1, "en-US"


def _cardmarket_min_condition(condition: str | None) -> int:
    candidate = (condition or "").strip().lower()
    mapping = {
        "mint": 1,
        "near_mint": 2,
        "excellent": 3,
        "good": 4,
        "light_played": 5,
        "played": 5,
        "poor": 5,
    }
    return mapping.get(candidate, 2)


def _cardmarket_offer_sample_size() -> int:
    return max(1, int(settings.cardmarket_offer_sample_size))


def _is_low_outlier(candidate: float, reference_prices: list[float]) -> bool:
    if len(reference_prices) < 1 or candidate <= 0:
        return False
    next_price = reference_prices[0]
    cluster = reference_prices[: min(len(reference_prices), _cardmarket_offer_sample_size() - 1)]
    cluster_median = median(cluster) if cluster else next_price
    return (
        candidate < next_price * settings.cardmarket_low_outlier_ratio_vs_next
        and candidate < cluster_median * settings.cardmarket_low_outlier_ratio_vs_cluster
    )


def _select_cardmarket_market_price(offer_prices: list[float]) -> tuple[float | None, bool, str, int]:
    sample = [price for price in offer_prices[:_cardmarket_offer_sample_size()] if price and price > 0]
    if not sample:
        return None, False, "no_offers", 0
    if len(sample) == 1:
        return sample[0], False, "single_offer", 1

    lowest_offer = sample[0]
    if _is_low_outlier(lowest_offer, sample[1:]):
        if len(sample) >= 3 and _is_low_outlier(sample[1], sample[2:]):
            cluster = sample[2:]
            if not cluster:
                return sample[1], True, "second_offer_due_to_low_outlier", len(sample)
            if len(cluster) == 1:
                return cluster[0], True, "third_offer_due_to_double_low_outlier", len(sample)
            return float(median(cluster)), True, "median_of_cluster_due_to_low_outlier", len(sample)
        return sample[1], True, "second_offer_due_to_low_outlier", len(sample)

    if len(sample) >= 2 and _is_low_outlier(sample[1], sample[2:]):
        if len(sample) >= 3:
            cluster = sample[2:]
            if len(cluster) == 1:
                return cluster[0], True, "third_offer_due_to_low_outlier", len(sample)
            return float(median(cluster)), True, "median_of_cluster_due_to_low_outlier", len(sample)

    return lowest_offer, False, "first_offer", len(sample)


def _cardmarket_locale(language: str | None) -> str:
    candidate = (language or "en").strip().lower()
    if candidate.startswith("de"):
        return "de"
    return "en"


def _cardmarket_match_tokens(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return True
    return _normalize_token(left) == _normalize_token(right)


def _cardmarket_name_matches(expected_name: str | None, fallback_name: str | None, product_name: str | None) -> bool:
    if not product_name:
        return False
    normalized_product = _normalize_token(product_name)
    if not normalized_product:
        return False

    for candidate in [expected_name, fallback_name]:
        if not candidate:
            continue
        normalized_candidate = _normalize_token(candidate)
        if not normalized_candidate:
            continue
        if normalized_candidate == normalized_product:
            return True
        if len(normalized_candidate) >= 8 and (
            normalized_candidate in normalized_product or normalized_product in normalized_candidate
        ):
            return True
    return False


def _build_cardmarket_product_resolution(
    *,
    card: Card,
    card_print: CardPrint,
    cardmarket_mapping: SourceMapping | None,
    cardmarket_reference: str | None,
) -> tuple[str | None, str | None, str | None]:
    exact_url = _exact_cardmarket_reference(
        cardmarket_mapping=cardmarket_mapping,
        cardmarket_reference=cardmarket_reference or card_print.cardmarket_product_url,
    )
    if exact_url:
        return exact_url, CARDMARKET_MATCH_EXACT_VARIANT if _card_print_has_variant(card_print) else CARDMARKET_MATCH_EXACT, "stored_exact_url"

    resolution = resolve_cardmarket_product_url(
        locale=_cardmarket_locale(card_print.language),
        cardmarket_product_url=card_print.cardmarket_product_url,
        cardmarket_product_slug=card_print.cardmarket_product_slug,
        cardmarket_set_slug=card_print.cardmarket_set_slug,
        cardmarket_set_name=card_print.cardmarket_set_name or card_print.set_name,
        cardmarket_product_name=card_print.cardmarket_product_name or card.name,
        cardmarket_variant_name=card_print.cardmarket_variant_name,
        card_name=card.name,
        has_multiple_variants=_card_print_has_variant(card_print),
        allow_fallback=False,
    )
    return resolution.url, resolution.mode, resolution.reason


def _verify_cardmarket_product(
    *,
    card: Card,
    card_print: CardPrint,
    product_name: str | None,
    set_name: str | None,
    set_slug: str | None,
    rarity: str | None,
    card_number: str | None,
    variant_name: str | None,
    resolved_mode: str | None,
) -> tuple[bool, str | None, str]:
    expected_name = card_print.cardmarket_product_name or card.name
    expected_set_name = card_print.cardmarket_set_name or card_print.set_name
    expected_rarity = card_print.rarity or card_print.cardmarket_expected_rarity
    expected_number = card_print.card_number
    expected_variant = card_print.cardmarket_variant_name

    name_match = _cardmarket_name_matches(expected_name, card.name, product_name)
    set_name_match = _cardmarket_match_tokens(expected_set_name, set_name)
    if not set_name_match and card_print.cardmarket_set_slug and set_slug:
        set_name_match = _normalize_token(card_print.cardmarket_set_slug) == _normalize_token(set_slug)
    if not set_name_match:
        return False, CARDMARKET_MATCH_AMBIGUOUS, "set name mismatch"
    if expected_number and card_number and not _cardmarket_match_tokens(expected_number, card_number):
        return False, CARDMARKET_MATCH_AMBIGUOUS, "collector number mismatch"
    if expected_rarity and rarity and not _cardmarket_match_tokens(expected_rarity, rarity):
        return False, CARDMARKET_MATCH_AMBIGUOUS, "rarity mismatch"
    if expected_variant and variant_name and not _cardmarket_match_tokens(expected_variant, variant_name):
        return False, CARDMARKET_MATCH_AMBIGUOUS, "variant mismatch"
    if not name_match:
        # If set + print identity are already strong, allow a downgraded verified match.
        if not (expected_number and card_number and _cardmarket_match_tokens(expected_number, card_number)):
            return False, CARDMARKET_MATCH_AMBIGUOUS, "product name mismatch"

    if variant_name or expected_variant:
        final_quality = CARDMARKET_MATCH_EXACT_VARIANT
    elif resolved_mode == CARDMARKET_MATCH_SET_NAME or not name_match:
        final_quality = CARDMARKET_MATCH_SET_NAME
    else:
        final_quality = CARDMARKET_MATCH_EXACT

    return True, final_quality, "verified" if name_match else "verified_with_print_identity"


def _match_remote_print(card_print: CardPrint, remote_print: dict[str, Any]) -> tuple[int, str | None]:
    local_set_code = _normalize_token(card_print.set_code)
    remote_set_code = _normalize_token(remote_print.get("set_code"))
    local_card_number = _normalize_token(card_print.card_number)
    remote_card_number = _normalize_token(_derive_card_number(remote_print.get("set_code")))
    local_rarity = _normalize_token(card_print.rarity)
    remote_rarity = _normalize_token(remote_print.get("set_rarity"))
    local_set_name = _normalize_token(card_print.set_name)
    remote_set_name = _normalize_token(remote_print.get("set_name"))
    local_language = _normalize_token(_derive_print_language(card_print.set_code) if card_print.set_code else card_print.language)
    remote_language = _normalize_token(_derive_print_language(remote_print.get("set_code")))

    exact_match = (
        bool(local_set_code and remote_set_code == local_set_code)
        and bool(local_card_number and remote_card_number == local_card_number)
        and bool(local_rarity and remote_rarity == local_rarity)
        and bool(local_language and remote_language == local_language)
    )
    if exact_match:
        return 1000, CARDMARKET_MATCH_EXACT_VARIANT if _card_print_has_variant(card_print) else CARDMARKET_MATCH_EXACT

    set_name_match = (
        bool(local_set_name and remote_set_name and local_set_name == remote_set_name)
        and bool(local_card_number and remote_card_number == local_card_number)
        and bool(local_rarity and remote_rarity == local_rarity)
        and bool(local_language and remote_language == local_language)
    )
    if set_name_match:
        return 900, CARDMARKET_MATCH_SET_NAME

    return 0, None


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
            "notes": (
                "Nutzt print-spezifische YGOPRODeck-Setpreise als legalen Default-Fallback. "
                "Globale Namenspreise werden bei unsicherem Print-Match bewusst verworfen."
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
        del condition
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
            logger.warning("Price lookup failed for %s (%s): no remote card matched", card.name, card_print.set_code)
            return PriceSnapshot(
                market_price=None,
                currency="EUR",
                provider_key=self.provider_key,
                source_key=f"{self.provider_key}:lookup_failed",
                match_quality=CARDMARKET_MATCH_FAILED,
                note="Kein passender Remote-Datensatz fuer diese Karte gefunden.",
                indicators={
                    "external_id": external_id,
                    "note": "no remote card",
                    "source_market": f"{self.provider_key}:lookup_failed",
                },
            )

        exact_cardmarket_reference = _exact_cardmarket_reference(
            cardmarket_mapping=cardmarket_mapping,
            cardmarket_reference=cardmarket_reference,
        )
        remote_prints = remote_card.get("card_sets", []) or []
        generic_prices = remote_card.get("prices", {}) or {}
        generic_cardmarket_price = _parse_float(generic_prices.get("cardmarket_price"))
        if not remote_prints:
            logger.warning("Price lookup for %s (%s) returned no print data", card.name, card_print.set_code)
            return PriceSnapshot(
                market_price=None,
                currency="EUR" if generic_cardmarket_price is not None else "USD",
                provider_key=self.provider_key,
                source_key=f"{self.provider_key}:no_prints",
                match_quality=CARDMARKET_MATCH_FAILED,
                note="Kein print-spezifischer Datensatz gefunden.",
                cardmarket_reference=exact_cardmarket_reference,
                indicators={
                    "external_id": remote_card.get("external_id"),
                    "cardmarket_price": generic_cardmarket_price,
                    "source_market": f"{self.provider_key}:no_prints",
                    "source_url": exact_cardmarket_reference,
                    "source_product_id": cardmarket_mapping.external_id if cardmarket_mapping else None,
                },
            )

        scored_prints: list[tuple[int, str | None, dict[str, Any]]] = []
        for remote_print in remote_prints:
            score, quality = _match_remote_print(card_print, remote_print)
            if quality:
                scored_prints.append((score, quality, remote_print))

        scored_prints.sort(
            key=lambda entry: (
                2 if entry[1] in {CARDMARKET_MATCH_EXACT, CARDMARKET_MATCH_EXACT_VARIANT} else 1 if entry[1] == CARDMARKET_MATCH_SET_NAME else 0,
                entry[0],
            ),
            reverse=True,
        )
        best_score, best_quality, best_print = scored_prints[0] if scored_prints else (0, None, None)

        matched_set_price = _parse_float(best_print.get("set_price")) if best_print else None
        single_print = len(remote_prints) == 1

        source_key = f"{self.provider_key}:set_price"
        market_price = None
        currency = "USD"
        note: str
        final_quality = best_quality or (CARDMARKET_MATCH_SET_NAME if single_print else CARDMARKET_MATCH_AMBIGUOUS)

        if best_quality in {CARDMARKET_MATCH_EXACT, CARDMARKET_MATCH_EXACT_VARIANT} and matched_set_price is not None and matched_set_price > 0:
            market_price = matched_set_price
            note = (
                "Exakter Print-Match auf YGOPRODeck-Setpreis. "
                "Setcode, Seltenheit und Sprache wurden fuer den Match beruecksichtigt."
            )
        elif single_print and generic_cardmarket_price is not None and generic_cardmarket_price > 0:
            market_price = generic_cardmarket_price
            currency = "EUR"
            source_key = f"{self.provider_key}:cardmarket"
            note = "Nur ein einzelner Druck verfuegbar; allgemeiner Cardmarket-Snapshot ueber YGOPRODeck wurde verwendet."
            if final_quality not in {CARDMARKET_MATCH_EXACT, CARDMARKET_MATCH_EXACT_VARIANT}:
                final_quality = CARDMARKET_MATCH_SET_NAME
        elif best_quality in {CARDMARKET_MATCH_EXACT, CARDMARKET_MATCH_EXACT_VARIANT, CARDMARKET_MATCH_SET_NAME}:
            note = "Print-spezifischer Datensatz gefunden, aber kein verlasslicher Marktpreis vorhanden."
        else:
            note = (
                "Kein verlasslicher print-spezifischer Preis gefunden. "
                "Ein allgemeiner Namenspreis wurde bewusst nicht uebernommen, um falsche Billigpreise zu vermeiden."
            )

        if market_price is None:
            source_key = f"{self.provider_key}:unpriced"

        if market_price is None:
            logger.warning(
                "Price match downgraded for %s (%s): %s",
                card.name,
                card_print.set_code,
                final_quality,
            )
        else:
            logger.info(
                "Price resolved for %s (%s): %s using %s",
                card.name,
                card_print.set_code,
                final_quality,
                source_key,
            )

        indicators = {
            "external_id": remote_card.get("external_id"),
            "match_quality": final_quality,
            "matched_set_code": best_print.get("set_code") if best_print else None,
            "matched_card_number": _derive_card_number(best_print.get("set_code")) if best_print else None,
            "matched_rarity": best_print.get("set_rarity") if best_print else None,
            "matched_language": _derive_print_language(best_print.get("set_code")) if best_print else None,
            "matched_score": best_score or None,
            "cardmarket_price": generic_cardmarket_price,
            "set_price": matched_set_price,
            "source_market": source_key,
            "source_url": exact_cardmarket_reference,
            "source_product_id": cardmarket_mapping.external_id if cardmarket_mapping else None,
            "source_cardmarket_reference": exact_cardmarket_reference,
            "card_name": card.name,
            "set_name": card_print.set_name,
            "set_code": card_print.set_code,
            "card_number": card_print.card_number,
            "rarity": card_print.rarity,
            "language": card_print.language,
            "note": note,
        }

        return PriceSnapshot(
            market_price=market_price,
            currency=currency,
            provider_key=self.provider_key,
            source_key=source_key,
            match_quality=final_quality,
            note=note,
            cardmarket_reference=exact_cardmarket_reference,
            indicators=indicators,
        )


class CardmarketPriceProvider:
    provider_key = "cardmarket"

    async def healthcheck(self) -> dict[str, Any]:
        configured = async_playwright is not None
        notes = (
            "Nutzt die oeffentliche Cardmarket-Produktseite per Browser-Render und wertet die sichtbaren Angebote temporär aus."
            if configured
            else "Playwright ist nicht verfuegbar; Browser-gestuetzte Cardmarket-Preisabfragen sind deaktiviert."
        )
        return {
            "key": self.provider_key,
            "label": "Cardmarket Public Offers",
            "category": "price",
            "configured": configured,
            "available": configured,
            "active": settings.price_provider == self.provider_key,
            "notes": notes,
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
        del card_mapping, print_mapping

        product_url, resolved_mode, resolution_reason = _build_cardmarket_product_resolution(
            card=card,
            card_print=card_print,
            cardmarket_mapping=cardmarket_mapping,
            cardmarket_reference=cardmarket_reference,
        )
        if not product_url:
            logger.warning("Cardmarket price lookup for %s (%s) skipped: no exact product url", card.name, card_print.set_code)
            return PriceSnapshot(
                market_price=None,
                currency="EUR",
                provider_key=self.provider_key,
                source_key=f"{self.provider_key}:unpriced",
                match_quality=CARDMARKET_MATCH_FAILED,
                note="Kein verifizierter Cardmarket-Produktlink vorhanden.",
                cardmarket_reference=None,
                indicators={
                    "source_url": None,
                    "source_filtered_url": None,
                    "source_product_url": None,
                    "source_product_id": cardmarket_mapping.external_id if cardmarket_mapping else None,
                    "resolved_mode": resolved_mode,
                    "resolution_reason": resolution_reason,
                    "note": "missing exact cardmarket product url",
                },
            )

        language_filter, browser_locale = _cardmarket_language_filter(card_print.language, card_print.language)
        min_condition = _cardmarket_min_condition(condition)
        client = get_cardmarket_public_client()
        try:
            product = await client.fetch_offer_product(
                product_url,
                language_filter=language_filter,
                min_condition=min_condition,
                seller_country=7,
                locale=browser_locale,
            )
        except Exception as exc:
            logger.exception("Failed to fetch Cardmarket offers for %s (%s): %s", card.name, card_print.set_code, exc)
            return PriceSnapshot(
                market_price=None,
                currency="EUR",
                provider_key=self.provider_key,
                source_key=f"{self.provider_key}:unpriced",
                match_quality=CARDMARKET_MATCH_FAILED,
                note=f"Cardmarket-Angebote konnten nicht geladen werden: {exc}",
                cardmarket_reference=product_url,
                indicators={
                    "source_url": product_url,
                    "source_filtered_url": None,
                    "source_product_url": product_url,
                    "source_product_id": cardmarket_mapping.external_id if cardmarket_mapping else None,
                    "resolved_mode": resolved_mode,
                    "resolution_reason": resolution_reason,
                    "language_filter": language_filter,
                    "min_condition": min_condition,
                    "seller_country": 7,
                    "error": str(exc),
                },
            )

        offer_prices = [price for price in product.offer_prices_sample if price is not None and price > 0]
        lowest_offer_price = offer_prices[0] if offer_prices else product.lowest_offer_price
        if lowest_offer_price is None and product.lowest_offer_price is not None:
            lowest_offer_price = product.lowest_offer_price

        verified, verification_quality, verification_reason = _verify_cardmarket_product(
            card=card,
            card_print=card_print,
        product_name=product.product_name,
        set_name=product.set_name,
        set_slug=product.set_slug,
        rarity=product.rarity,
        card_number=product.card_number,
        variant_name=product.variant_name,
            resolved_mode=resolved_mode,
        )
        if not verified:
            logger.warning("Cardmarket verification failed for %s (%s): %s", card.name, card_print.set_code, verification_reason)
            return PriceSnapshot(
                market_price=None,
                currency="EUR",
                provider_key=self.provider_key,
                source_key=f"{self.provider_key}:unpriced",
                match_quality=CARDMARKET_MATCH_AMBIGUOUS,
                note=f"Cardmarket-Produkt konnte nicht verifiziert werden: {verification_reason}",
                cardmarket_reference=product_url,
                indicators={
                    "source_url": product_url,
                    "source_filtered_url": product.url,
                    "source_product_url": product_url,
                    "source_product_id": cardmarket_mapping.external_id if cardmarket_mapping else None,
                    "resolved_mode": resolved_mode,
                    "resolution_reason": resolution_reason,
                    "verification_reason": verification_reason,
                    "lowest_offer_price": lowest_offer_price,
                    "selected_market_price": None,
                    "pricing_strategy_used": "verification_failed",
                    "offer_count_considered": len(offer_prices),
                    "outlier_detected": False,
                    "price_trend": product.price_trend,
                    "avg_1d": product.avg_1d,
                    "avg_7d": product.avg_7d,
                    "avg_30d": product.avg_30d,
                    "filters_used": product.filters_used,
                    "raw_offer_prices_sample": offer_prices,
                    "card_name": card.name,
                    "set_name": card_print.set_name,
                    "set_code": card_print.set_code,
                    "card_number": card_print.card_number,
                    "rarity": card_print.rarity,
                    "language": card_print.language,
                    "condition": condition,
                },
            )

        selected_market_price, outlier_detected, pricing_strategy_used, offer_count_considered = _select_cardmarket_market_price(offer_prices)
        if selected_market_price is None and lowest_offer_price is not None:
            selected_market_price = lowest_offer_price
            pricing_strategy_used = "summary_lowest_offer_fallback" if not offer_prices else "lowest_offer_fallback"

        if selected_market_price is None:
            logger.warning("Cardmarket price lookup for %s (%s) returned no usable offers", card.name, card_print.set_code)
            return PriceSnapshot(
                market_price=None,
                currency="EUR",
                provider_key=self.provider_key,
                source_key=f"{self.provider_key}:unpriced",
                match_quality=verification_quality or CARDMARKET_MATCH_AMBIGUOUS,
                note="Keine auswertbaren Cardmarket-Angebote gefunden.",
                cardmarket_reference=product_url,
                indicators={
                    "source_url": product_url,
                    "source_filtered_url": product.url,
                    "source_product_url": product_url,
                    "source_product_id": cardmarket_mapping.external_id if cardmarket_mapping else None,
                    "resolved_mode": resolved_mode,
                    "resolution_reason": resolution_reason,
                    "verification_reason": verification_reason,
                    "lowest_offer_price": lowest_offer_price,
                    "selected_market_price": None,
                    "pricing_strategy_used": pricing_strategy_used,
                    "offer_count_considered": offer_count_considered,
                    "outlier_detected": outlier_detected,
                    "price_trend": product.price_trend,
                    "avg_1d": product.avg_1d,
                    "avg_7d": product.avg_7d,
                    "avg_30d": product.avg_30d,
                    "filters_used": product.filters_used,
                    "raw_offer_prices_sample": offer_prices,
                    "card_name": card.name,
                    "set_name": card_print.set_name,
                    "set_code": card_print.set_code,
                    "card_number": card_print.card_number,
                    "rarity": card_print.rarity,
                    "language": card_print.language,
                    "condition": condition,
                },
            )

        note_parts = [
            f"Cardmarket-Angebote mit sellerCountry=7, language={language_filter}, minCondition={min_condition} ausgewertet.",
            f"Strategie: {pricing_strategy_used}.",
        ]
        if outlier_detected:
            note_parts.append("Guenstigstes Angebot als Ausreisser ignoriert.")
        if product.avg_1d is not None:
            note_parts.append(f"1d={product.avg_1d:.2f} EUR.")
        note = " ".join(note_parts)

        indicators = {
            "source_url": product_url,
            "source_filtered_url": product.url,
            "source_product_url": product_url,
            "source_product_id": cardmarket_mapping.external_id if cardmarket_mapping else None,
            "lowest_offer_price": lowest_offer_price,
            "selected_market_price": selected_market_price,
            "pricing_strategy_used": pricing_strategy_used,
            "offer_count_considered": offer_count_considered,
            "outlier_detected": outlier_detected,
            "price_trend": product.price_trend,
            "avg_1d": product.avg_1d,
            "avg_7d": product.avg_7d,
            "avg_30d": product.avg_30d,
            "filters_used": {
                **(product.filters_used or {}),
                "seller_country": 7,
                "language": language_filter,
                "min_condition": min_condition,
                "locale": browser_locale,
            },
            "raw_offer_prices_sample": offer_prices,
            "card_name": card.name,
            "set_name": card_print.set_name,
            "set_code": card_print.set_code,
            "card_number": card_print.card_number,
            "rarity": card_print.rarity,
            "language": card_print.language,
            "condition": condition,
            "match_quality": verification_quality,
            "note": note,
            "verification_reason": verification_reason,
            "resolved_mode": resolved_mode,
            "resolution_reason": resolution_reason,
            "verified_product_name": product.product_name,
            "verified_set_name": product.set_name,
            "verified_variant_name": product.variant_name,
        }

        logger.info(
            "Cardmarket price resolved for %s (%s): url=%s lowest=%s selected=%s strategy=%s outlier=%s",
            card.name,
            card_print.set_code,
            product_url,
            lowest_offer_price,
            selected_market_price,
            pricing_strategy_used,
            outlier_detected,
        )
        logger.info("Cardmarket offer sample for %s (%s): %s", card.name, card_print.set_code, offer_prices)
        if outlier_detected:
            logger.info("Detected low outlier at first offer for %s (%s)", card.name, card_print.set_code)
        if pricing_strategy_used == "second_offer_due_to_low_outlier":
            logger.info("Selected second offer as market price for %s (%s)", card.name, card_print.set_code)
        elif pricing_strategy_used == "third_offer_due_to_low_outlier":
            logger.info("Selected third offer as market price for %s (%s)", card.name, card_print.set_code)
        elif pricing_strategy_used == "median_of_cluster_due_to_low_outlier":
            logger.info("Selected median of cluster as market price for %s (%s)", card.name, card_print.set_code)

        return PriceSnapshot(
            market_price=selected_market_price,
            currency="EUR",
            provider_key=self.provider_key,
            source_key=f"{self.provider_key}:filtered-offers",
            match_quality=verification_quality or CARDMARKET_MATCH_SET_NAME,
            note=note,
            cardmarket_reference=product_url,
            indicators=indicators,
        )


def get_price_providers():
    return [YgoProDeckPriceProvider(), CardmarketPriceProvider()]


def get_active_price_provider():
    for provider in get_price_providers():
        if provider.provider_key == settings.price_provider:
            return provider
    return YgoProDeckPriceProvider()
