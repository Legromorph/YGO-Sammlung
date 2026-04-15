from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import logging
import re
from urllib.parse import quote

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.integrations.cardmarket_links import (
    CARDMARKET_CATEGORY,
    CARDMARKET_MATCH_AMBIGUOUS,
    CARDMARKET_MATCH_EXACT,
    CARDMARKET_MATCH_EXACT_VARIANT,
    CARDMARKET_MATCH_FAILED,
    CARDMARKET_MATCH_SET_NAME,
    build_cardmarket_fallback_url,
    build_cardmarket_product_slug,
    build_cardmarket_product_url,
    build_cardmarket_set_slug,
    normalize_cardmarket_product_url,
    resolve_cardmarket_product_url,
    _slug_has_variant_marker,
)
from app.integrations.card_data import get_card_data_provider
from app.integrations.cardmarket_public import CardmarketPublicProduct, get_cardmarket_public_client
from app.models import Card, CardPrint, ImageAsset, InventoryItem, PriceHistory, SourceMapping, StorageLocation, SyncJob
from app.schemas import (
    CardDetail,
    CardFilterOptions,
    CardLookupPrintOption,
    CardLookupResponse,
    CardLookupSuggestion,
    CardPayload,
    PricingStatus,
    CardSummary,
    PriceHistoryPoint,
    SourceMappingResponse,
)
from app.services.price_monitor import build_price_monitor_status
from app.services.app_settings import get_app_settings
from app.services.currency import convert_amount
from app.services.price_monitor import ensure_initial_price_monitor_state
from app.services.sync import _extract_price_targets, serialize_sync_job

logger = logging.getLogger(__name__)


def normalize_name(value: str) -> str:
    return " ".join(value.lower().split())


def _first_image(card_print: CardPrint) -> ImageAsset | None:
    assets = sorted(
        [asset for asset in card_print.image_assets if asset.status == "downloaded" and asset.local_path],
        key=lambda asset: asset.downloaded_at or asset.updated_at,
        reverse=True,
    )
    return assets[0] if assets else None


def _placeholder_url(item_id: int, card_name: str) -> str:
    return f"{settings.api_prefix}/assets/placeholder?item_id={item_id}&label={card_name}"


def _proxy_remote_image_url(url: str | None) -> str | None:
    if not url:
        return None
    return f"{settings.api_prefix}/assets/proxy?url={quote(url, safe='')}"


def _parse_float(value: str | float | int | None) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _cardmarket_url(value: str | None) -> str | None:
    return normalize_cardmarket_product_url(value) or (value if value and value.startswith(("http://", "https://")) else None)


def _slugify_cardmarket_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "-", value.strip())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return normalized or "Cards"


def _fallback_cardmarket_card_url(card_name: str) -> str:
    return f"https://www.cardmarket.com/en/YuGiOh/Cards/{_slugify_cardmarket_name(card_name)}"


def _preferred_cardmarket_locale(language: str | None, fallback_language: str | None) -> str:
    candidate = (language or fallback_language or "de").strip().lower()
    if candidate.startswith("en"):
        return "en"
    return "de"


def _remote_image_url(card_data: dict) -> str | None:
    images = card_data.get("card_images") or []
    if not images:
        return None
    first_image = images[0]
    return _proxy_remote_image_url(first_image.get("image_url_small") or first_image.get("image_url"))


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


def _resolve_default_remote_price(card_data: dict) -> tuple[float | None, str | None, str | None]:
    prices = card_data.get("prices", {}) or {}
    cardmarket_price = _parse_float(prices.get("cardmarket_price"))
    tcgplayer_price = _parse_float(prices.get("tcgplayer_price"))
    ebay_price = _parse_float(prices.get("ebay_price"))
    amazon_price = _parse_float(prices.get("amazon_price"))

    if cardmarket_price is not None:
        return cardmarket_price, "EUR", "ygoprodeck:cardmarket"
    if tcgplayer_price is not None:
        return tcgplayer_price, "USD", "ygoprodeck:tcgplayer"
    if ebay_price is not None:
        return ebay_price, "USD", "ygoprodeck:ebay"
    if amazon_price is not None:
        return amazon_price, "USD", "ygoprodeck:amazon"
    return None, None, None


def _build_print_label(set_name: str | None, set_code: str | None, rarity: str | None) -> str:
    parts = [part for part in [set_name, set_code, rarity] if part]
    return " | ".join(parts) if parts else "Unbekannter Druck"


def _normalize_lookup_value(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _card_numbers_match(left: str | None, right: str | None) -> bool:
    normalized_left = _normalize_lookup_value(left)
    normalized_right = _normalize_lookup_value(right)
    if not normalized_left or not normalized_right:
        return False
    return normalized_left == normalized_right or normalized_left.endswith(normalized_right) or normalized_right.endswith(normalized_left)


def _is_verified_cardmarket_quality(value: str | None) -> bool:
    return value in {CARDMARKET_MATCH_EXACT, CARDMARKET_MATCH_EXACT_VARIANT}


def _is_safe_cardmarket_quality(value: str | None) -> bool:
    return value in {CARDMARKET_MATCH_EXACT, CARDMARKET_MATCH_EXACT_VARIANT, CARDMARKET_MATCH_SET_NAME}


def _price_note(price_source: str | None, *, multiple_prints: bool, has_cardmarket_reference: bool) -> str:
    source_notes = {
        "ygoprodeck:set_price": "Print-spezifischer YGOPRODeck-Setpreis als Startwert.",
        "ygoprodeck:cardmarket": "Cardmarket-Snapshot ueber YGOPRODeck als Startwert.",
        "ygoprodeck:tcgplayer": "TCGplayer-Fallback als Startwert.",
        "ygoprodeck:ebay": "eBay-Fallback als Startwert.",
        "ygoprodeck:amazon": "Amazon-Fallback als Startwert.",
        "cardmarket:public-product-page": "Preis-Trend aus der oeffentlichen Cardmarket-Produktseite als Startwert.",
    }
    note_parts = [source_notes.get(price_source, "Es liegt derzeit nur ein allgemeiner Provider-Snapshot vor.")]
    if multiple_prints:
        note_parts.append("Bitte Set, Setcode und Seltenheit auswaehlen, damit die Druckvariante sauber feststeht.")
    note_parts.append("Zustandsspezifische Cardmarket-Preise sind im MVP ohne offizielle Cardmarket-API noch nicht automatisiert verfuegbar.")
    if not has_cardmarket_reference:
        note_parts.append("Eine Cardmarket-Referenz konnte nur aus vorhandenen lokalen Mappings uebernommen werden.")
    return " ".join(note_parts)


def _latest_price_entry(item: InventoryItem) -> PriceHistory | None:
    if not item.price_history:
        return None
    return max(item.price_history, key=lambda entry: entry.captured_at)


def _group_source_mappings(mappings: list[SourceMapping]) -> dict[tuple[str, int], list[SourceMapping]]:
    grouped: dict[tuple[str, int], list[SourceMapping]] = {}
    for mapping in mappings:
        grouped.setdefault((mapping.target_type, mapping.target_id), []).append(mapping)
    return grouped


def _mappings_for_item(grouped_mappings: dict[tuple[str, int], list[SourceMapping]], item: InventoryItem) -> list[SourceMapping]:
    return [
        *grouped_mappings.get(("card_print", item.card_print_id), []),
        *grouped_mappings.get(("card", item.card_print.card.id), []),
    ]


async def _load_source_mappings(db: AsyncSession, items: list[InventoryItem]) -> dict[tuple[str, int], list[SourceMapping]]:
    if not items:
        return {}

    card_ids = sorted({item.card_print.card.id for item in items})
    card_print_ids = sorted({item.card_print_id for item in items})
    result = await db.execute(
        select(SourceMapping).where(
            or_(
                and_(SourceMapping.target_type == "card", SourceMapping.target_id.in_(card_ids)),
                and_(SourceMapping.target_type == "card_print", SourceMapping.target_id.in_(card_print_ids)),
            )
        )
    )
    return _group_source_mappings(result.scalars().all())


async def _load_active_price_jobs(db: AsyncSession, items: list[InventoryItem]) -> dict[int, SyncJob]:
    if not items:
        return {}

    result = await db.execute(
        select(SyncJob)
        .where(
            SyncJob.job_type == "price_update",
            SyncJob.status.in_(["pending", "running"]),
        )
        .order_by(SyncJob.created_at.desc())
    )
    jobs = result.scalars().all()
    if not jobs:
        return {}

    job_map: dict[int, SyncJob] = {}
    for item in items:
        best_job: SyncJob | None = None
        best_key: tuple[int, int, int, int] | None = None
        for job in jobs:
            inventory_item_ids, card_print_ids = _extract_price_targets(job.payload)
            has_targets = bool(inventory_item_ids or card_print_ids)
            direct_match = item.id in inventory_item_ids or item.card_print_id in card_print_ids

            if direct_match:
                specificity = 0
            elif has_targets:
                continue
            else:
                # Avoid showing "updating" for globally queued but not yet running jobs.
                if job.status != "running":
                    continue
                specificity = 2

            status_rank = 0 if job.status == "running" else 1
            priority_rank = -(job.priority or 0)
            recency_rank = -job.id
            candidate_key = (specificity, status_rank, priority_rank, recency_rank)

            if best_key is None or candidate_key < best_key:
                best_key = candidate_key
                best_job = job

        if best_job:
            job_map[item.id] = best_job
    return job_map


async def _load_exact_cardmarket_references(
    db: AsyncSession,
    *,
    normalized_name: str,
    language: str,
) -> dict[tuple[str | None, str | None, str | None, str | None], str]:
    exact_references: dict[tuple[str | None, str | None, str | None, str | None], str] = {}

    card_print_rows = await db.execute(
        select(
            CardPrint.set_code,
            CardPrint.card_number,
            CardPrint.rarity,
            CardPrint.language,
            CardPrint.cardmarket_product_url,
            CardPrint.cardmarket_product_slug,
            CardPrint.cardmarket_set_slug,
            CardPrint.cardmarket_match_quality,
        )
        .join(Card, Card.id == CardPrint.card_id)
        .where(
            Card.normalized_name == normalized_name,
            CardPrint.language == language,
        )
    )
    for set_code, card_number, rarity, card_language, product_url, product_slug, set_slug, match_quality in card_print_rows.all():
        exact_url = normalize_cardmarket_product_url(product_url)
        if not exact_url and product_slug and set_slug:
            locale = _preferred_cardmarket_locale(card_language, language)
            exact_url = build_cardmarket_product_url(locale, set_slug, product_slug)
        if not exact_url or not _is_safe_cardmarket_quality(match_quality):
            continue
        exact_references[(set_code, card_number, rarity, card_language)] = exact_url

    mapping_rows = await db.execute(
        select(
            CardPrint.set_code,
            CardPrint.card_number,
            CardPrint.rarity,
            CardPrint.language,
            SourceMapping.external_url,
            SourceMapping.external_id,
        )
        .join(CardPrint, SourceMapping.target_id == CardPrint.id)
        .join(Card, Card.id == CardPrint.card_id)
        .where(
            SourceMapping.target_type == "card_print",
            SourceMapping.provider_key == "cardmarket",
            Card.normalized_name == normalized_name,
            CardPrint.language == language,
        )
    )
    for set_code, card_number, rarity, card_language, external_url, external_id in mapping_rows.all():
        exact_url = normalize_cardmarket_product_url(external_url) or normalize_cardmarket_product_url(external_id)
        if not exact_url:
            continue
        exact_references.setdefault((set_code, card_number, rarity, card_language), exact_url)

    return exact_references


def _resolve_cardmarket_link(item: InventoryItem, mappings: list[SourceMapping], latest_payload: dict | None) -> tuple[str | None, str | None]:
    latest_payload = latest_payload or {}
    card_print = item.card_print
    locale = _preferred_cardmarket_locale(card_print.language, latest_payload.get("language"))
    preferred_product_name = card_print.cardmarket_product_name or card_print.card.name

    for source in (
        latest_payload.get("source_url"),
        latest_payload.get("cardmarket_product_url"),
        card_print.cardmarket_product_url,
    ):
        exact_url = normalize_cardmarket_product_url(source)
        if exact_url:
            return exact_url, CARDMARKET_MATCH_EXACT_VARIANT if card_print.cardmarket_variant_name else CARDMARKET_MATCH_EXACT

    for mapping in mappings:
        if mapping.provider_key != "cardmarket":
            continue
        mapping_url = normalize_cardmarket_product_url(mapping.external_url) or normalize_cardmarket_product_url(mapping.external_id)
        if mapping_url:
            return mapping_url, CARDMARKET_MATCH_EXACT_VARIANT if card_print.cardmarket_variant_name else CARDMARKET_MATCH_EXACT

    direct_reference = normalize_cardmarket_product_url(item.cardmarket_reference)
    if direct_reference:
        return direct_reference, CARDMARKET_MATCH_SET_NAME if not card_print.cardmarket_variant_name else CARDMARKET_MATCH_EXACT_VARIANT

    derived_resolution = resolve_cardmarket_product_url(
        locale=locale,
        cardmarket_product_url=None,
        cardmarket_product_slug=card_print.cardmarket_product_slug,
        cardmarket_set_slug=card_print.cardmarket_set_slug,
        cardmarket_set_name=card_print.cardmarket_set_name or card_print.set_name,
        cardmarket_product_name=preferred_product_name,
        cardmarket_variant_name=card_print.cardmarket_variant_name,
        card_name=preferred_product_name,
        has_multiple_variants=False,
        allow_fallback=True,
    )
    if derived_resolution.url:
        return derived_resolution.url, derived_resolution.mode

    fallback_url = build_cardmarket_fallback_url(locale, preferred_product_name) or _fallback_cardmarket_card_url(preferred_product_name)
    return fallback_url, CARDMARKET_MATCH_AMBIGUOUS


def _build_pricing_status(item: InventoryItem, mappings: list[SourceMapping], active_job: SyncJob | None) -> PricingStatus:
    latest_entry = _latest_price_entry(item)
    latest_payload = latest_entry.payload if latest_entry and latest_entry.payload else {}
    cardmarket_link, cardmarket_link_mode = _resolve_cardmarket_link(item, mappings, latest_payload)
    monitor_status = build_price_monitor_status(item, active_job=active_job)

    match_quality = item.last_price_match_quality or latest_payload.get("match_quality")
    note = item.last_price_note or latest_payload.get("note") or monitor_status.get("note")
    source = item.last_price_source or (latest_entry.provider_key if latest_entry else None)
    last_updated_at = monitor_status.get("last_updated_at") or item.last_priced_at or (latest_entry.captured_at if latest_entry else None)

    if item.current_market_price is None:
        status = monitor_status.get("status") or "unpriced"
    elif match_quality == "manual":
        status = "manual"
    elif match_quality in {CARDMARKET_MATCH_EXACT, CARDMARKET_MATCH_EXACT_VARIANT}:
        status = "exact"
    elif match_quality in {CARDMARKET_MATCH_SET_NAME, "high_confidence"}:
        status = "high_confidence"
    else:
        status = monitor_status.get("status") or "fallback"

    return PricingStatus(
        status=status,
        is_updating=active_job is not None,
        pending_job_id=active_job.id if active_job else None,
        match_quality=match_quality,
        source=source,
        note=note,
        last_updated_at=last_updated_at,
        cardmarket_url=cardmarket_link,
        cardmarket_link_mode=cardmarket_link_mode,
        last_price_check_at=monitor_status.get("last_price_check_at"),
        next_price_check_at=monitor_status.get("next_price_check_at"),
        price_check_interval_hours=monitor_status.get("price_check_interval_hours"),
        price_volatility_score=monitor_status.get("price_volatility_score"),
        price_check_priority=monitor_status.get("price_check_priority"),
        price_stability_state=monitor_status.get("price_stability_state"),
        failure_count=monitor_status.get("failure_count"),
        consecutive_stable_checks=monitor_status.get("consecutive_stable_checks"),
        last_error_message=monitor_status.get("last_error_message"),
        pending_job=serialize_sync_job(active_job) if active_job else None,
    )


async def _display_price_value(
    value: float | int | Decimal | None,
    source_currency: str | None,
    target_currency: str,
) -> tuple[float | None, str | None]:
    if value is None:
        return None, None

    converted = await convert_amount(value, source_currency, target_currency)
    if converted is None:
        if source_currency and source_currency.upper() != target_currency.upper():
            return None, f"Preis konnte nicht von {source_currency.upper()} nach {target_currency.upper()} umgerechnet werden."
        return float(value), None

    return float(converted), None


async def _display_optional_price_value(
    value: float | int | Decimal | None,
    source_currency: str | None,
    target_currency: str,
) -> float | None:
    if value is None:
        return None
    converted, _note = await _display_price_value(value, source_currency, target_currency)
    if converted is not None:
        return float(converted)
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def _display_price_sample_values(
    values: list[float | int | Decimal | None] | None,
    source_currency: str | None,
    target_currency: str,
) -> list[float]:
    sample: list[float] = []
    for value in values or []:
        converted = await _display_optional_price_value(value, source_currency, target_currency)
        if converted is not None:
            sample.append(converted)
    return sample


def _cardmarket_import_note(product: CardmarketPublicProduct, fallback_source: str | None = None) -> str:
    if product.parse_mode == "page":
        return _price_note("cardmarket:public-product-page", multiple_prints=False, has_cardmarket_reference=True)

    source_note = _price_note(fallback_source, multiple_prints=False, has_cardmarket_reference=True)
    return "Die Cardmarket-Produktseite hat den direkten Serverzugriff blockiert; die Druckvariante wurde daher aus der URL erkannt. " + source_note


async def _load_local_cardmarket_references(
    db: AsyncSession,
    *,
    normalized_name: str,
    language: str,
) -> dict[tuple[str | None, str | None, str | None, str | None], str]:
    exact_references: dict[tuple[str | None, str | None, str | None, str | None], str] = {}

    card_print_rows = await db.execute(
        select(
            CardPrint.set_code,
            CardPrint.card_number,
            CardPrint.rarity,
            CardPrint.language,
            CardPrint.cardmarket_product_url,
            CardPrint.cardmarket_product_slug,
            CardPrint.cardmarket_set_slug,
            CardPrint.cardmarket_match_quality,
        )
        .join(Card, Card.id == CardPrint.card_id)
        .where(
            Card.normalized_name == normalized_name,
            CardPrint.language == language,
        )
    )
    for set_code, card_number, rarity, card_language, product_url, product_slug, set_slug, match_quality in card_print_rows.all():
        exact_url = normalize_cardmarket_product_url(product_url)
        if not exact_url and product_slug and set_slug:
            locale = _preferred_cardmarket_locale(card_language, language)
            exact_url = build_cardmarket_product_url(locale, set_slug, product_slug)
        if match_quality is not None and not _is_safe_cardmarket_quality(match_quality):
            continue
        if exact_url:
            exact_references[(set_code, card_number, rarity, card_language)] = exact_url

    mapping_rows = await db.execute(
        select(
            CardPrint.set_code,
            CardPrint.card_number,
            CardPrint.rarity,
            CardPrint.language,
            SourceMapping.external_url,
            SourceMapping.external_id,
        )
        .join(CardPrint, SourceMapping.target_id == CardPrint.id)
        .join(Card, Card.id == CardPrint.card_id)
        .where(
            SourceMapping.target_type == "card_print",
            SourceMapping.provider_key == "cardmarket",
            Card.normalized_name == normalized_name,
            CardPrint.language == language,
        )
    )
    for set_code, card_number, rarity, card_language, external_url, external_id in mapping_rows.all():
        exact_url = normalize_cardmarket_product_url(external_url) or normalize_cardmarket_product_url(external_id)
        if exact_url:
            exact_references.setdefault((set_code, card_number, rarity, card_language), exact_url)

    return exact_references


async def search_card_catalog(query: str, *, language: str = "de", limit: int = 8, display_currency: str = "EUR") -> list[CardLookupSuggestion]:
    provider = get_card_data_provider()
    remote_cards = await provider.search_cards(query=query, language=language, limit=limit)
    suggestions: list[CardLookupSuggestion] = []

    for card_data in remote_cards:
        default_market_price, default_price_currency, price_source = _resolve_default_remote_price(card_data)
        if default_market_price is not None and default_price_currency and default_price_currency.upper() != display_currency.upper():
            converted_price = await convert_amount(default_market_price, default_price_currency, display_currency)
            default_market_price = float(converted_price) if converted_price is not None else None
            default_price_currency = display_currency
        suggestions.append(
            CardLookupSuggestion(
                external_id=card_data.get("external_id", ""),
                name=card_data.get("name", ""),
                card_type=card_data.get("card_type"),
                attribute=card_data.get("attribute"),
                monster_type=card_data.get("monster_type"),
                image_url=_remote_image_url(card_data),
                set_count=len(card_data.get("card_sets") or []),
                default_market_price=default_market_price,
                default_price_currency=default_price_currency,
                price_source=price_source,
            )
        )

    return suggestions


async def _lookup_by_name_candidates(
    db: AsyncSession,
    *,
    language: str,
    candidates: list[str],
) -> CardLookupResponse | None:
    tried: set[tuple[str, str | None]] = set()
    provider = get_card_data_provider()

    async def try_lookup(name: str, candidate_language: str | None) -> CardLookupResponse | None:
        key = (name, candidate_language)
        if key in tried:
            return None
        tried.add(key)
        return await get_card_lookup(db, name=name, language=candidate_language or language)

    for candidate in candidates:
        if not candidate:
            continue
        direct = await try_lookup(candidate, language)
        if direct:
            return direct

    for candidate in candidates:
        if not candidate:
            continue
        generic = await try_lookup(candidate, "en")
        if generic:
            return generic

    for candidate in candidates:
        if not candidate:
            continue
        results = await provider.search_cards(query=candidate, language=language, limit=6)
        normalized_candidate = normalize_name(candidate)
        best_match = next(
            (
                result
                for result in results
                if normalize_name(result.get("name") or "") == normalized_candidate or normalized_candidate in normalize_name(result.get("name") or "")
            ),
            None,
        )
        if best_match and best_match.get("external_id"):
            lookup = await get_card_lookup(db, external_id=best_match["external_id"], language=language)
            if lookup:
                return lookup

    return None


def _select_cardmarket_print(
    print_options: list[CardLookupPrintOption],
    product: CardmarketPublicProduct,
) -> CardLookupPrintOption | None:
    best_option: CardLookupPrintOption | None = None
    best_score = -1
    normalized_set_name = _normalize_lookup_value(product.set_name)
    normalized_rarity = _normalize_lookup_value(product.rarity)

    for option in print_options:
        score = 0
        if normalized_set_name:
            option_set_name = _normalize_lookup_value(option.set_name)
            if option_set_name == normalized_set_name:
                score += 5
            elif normalized_set_name and normalized_set_name in option_set_name:
                score += 3

        if normalized_rarity:
            option_rarity = _normalize_lookup_value(option.rarity)
            if option_rarity == normalized_rarity:
                score += 4

        if _card_numbers_match(option.card_number, product.card_number):
            score += 5

        if score > best_score:
            best_score = score
            best_option = option

    return best_option if best_score > 0 else None


def _build_cardmarket_print_option(product: CardmarketPublicProduct, matched_option: CardLookupPrintOption | None = None) -> CardLookupPrintOption:
    market_price = product.price_trend if product.price_trend is not None else matched_option.market_price if matched_option else None
    price_source = "cardmarket:public-product-page" if product.price_trend is not None else matched_option.price_source if matched_option else None
    exact_product_url = normalize_cardmarket_product_url(product.url)
    exact_product_page = exact_product_url is not None
    match_quality = CARDMARKET_MATCH_EXACT_VARIANT if exact_product_page and (product.variant_name or _slug_has_variant_marker(product.product_slug)) else CARDMARKET_MATCH_EXACT if exact_product_page else CARDMARKET_MATCH_AMBIGUOUS
    return CardLookupPrintOption(
        set_name=matched_option.set_name if matched_option and matched_option.set_name else product.set_name,
        set_code=matched_option.set_code if matched_option else None,
        card_number=matched_option.card_number if matched_option and matched_option.card_number else product.card_number,
        rarity=matched_option.rarity if matched_option and matched_option.rarity else product.rarity,
        rarity_code=matched_option.rarity_code if matched_option else None,
        cardmarket_product_url=exact_product_url if exact_product_page else None,
        cardmarket_product_slug=product.product_slug if exact_product_page else None,
        cardmarket_set_slug=product.set_slug if exact_product_page else None,
        cardmarket_set_name=product.set_name,
        cardmarket_product_name=product.product_name,
        cardmarket_variant_name=product.variant_name if exact_product_page else None,
        cardmarket_category=product.category,
        cardmarket_match_quality=match_quality,
        cardmarket_verified_at=datetime.utcnow() if exact_product_page else None,
        market_price=market_price,
        price_currency=product.currency if market_price is not None else matched_option.price_currency if matched_option else None,
        price_source=price_source,
        price_note=_cardmarket_import_note(product, price_source),
        cardmarket_reference=product.url,
        ygoprodeck_id=matched_option.ygoprodeck_id if matched_option else None,
        display_label=_build_print_label(
            matched_option.set_name if matched_option and matched_option.set_name else product.set_name,
            matched_option.set_code if matched_option else None,
            matched_option.rarity if matched_option and matched_option.rarity else product.rarity,
        ),
    )


async def get_card_lookup_from_cardmarket_url(
    db: AsyncSession,
    *,
    url: str,
    language: str = "de",
) -> CardLookupResponse:
    app_settings = await get_app_settings(db)
    display_currency = app_settings.preferred_currency
    product = await get_cardmarket_public_client().fetch_product(url)
    base_lookup = await _lookup_by_name_candidates(db, language=language, candidates=product.card_name_candidates)

    if not base_lookup:
        synthetic_print = _build_cardmarket_print_option(product)
        fallback_name = product.card_name_candidates[0] if product.card_name_candidates else product.title_text or "Unbekannte Karte"
        if synthetic_print.market_price is not None and synthetic_print.price_currency and synthetic_print.price_currency.upper() != display_currency.upper():
            converted = await convert_amount(synthetic_print.market_price, synthetic_print.price_currency, display_currency)
            synthetic_print.market_price = float(converted) if converted is not None else None
            synthetic_print.price_currency = display_currency
        converted_product_price = None
        if product.price_trend is not None:
            converted_price = await convert_amount(product.price_trend, product.currency, display_currency)
            converted_product_price = float(converted_price) if converted_price is not None else None
        return CardLookupResponse(
            external_id="",
            name=fallback_name,
            image_url=None,
            ygoprodeck_id=None,
            default_market_price=converted_product_price,
            default_price_currency=display_currency if converted_product_price is not None else None,
            price_source="cardmarket:public-product-page" if product.price_trend is not None else None,
            price_note=synthetic_print.price_note or _cardmarket_import_note(product, "cardmarket:public-product-page"),
            condition_price_supported=False,
            cardmarket_reference=product.url,
            print_options=[synthetic_print],
            cardmarket_product_url=synthetic_print.cardmarket_product_url,
            cardmarket_product_slug=synthetic_print.cardmarket_product_slug,
            cardmarket_set_slug=synthetic_print.cardmarket_set_slug,
            cardmarket_set_name=product.set_name,
            cardmarket_product_name=product.product_name,
            cardmarket_variant_name=product.variant_name,
            cardmarket_category=product.category,
            cardmarket_match_quality=synthetic_print.cardmarket_match_quality,
            cardmarket_verified_at=synthetic_print.cardmarket_verified_at,
        )

    matched_print = _select_cardmarket_print(base_lookup.print_options, product)
    resolved_print = _build_cardmarket_print_option(product, matched_print)
    if resolved_print.market_price is not None and resolved_print.price_currency and resolved_print.price_currency.upper() != display_currency.upper():
        converted = await convert_amount(resolved_print.market_price, resolved_print.price_currency, display_currency)
        resolved_print.market_price = float(converted) if converted is not None else None
        resolved_print.price_currency = display_currency

    converted_default_price = base_lookup.default_market_price
    if converted_default_price is not None and base_lookup.default_price_currency and base_lookup.default_price_currency.upper() != display_currency.upper():
        converted = await convert_amount(converted_default_price, base_lookup.default_price_currency, display_currency)
        converted_default_price = float(converted) if converted is not None else None
    converted_product_price = None
    if product.price_trend is not None:
        converted_price = await convert_amount(product.price_trend, product.currency, display_currency)
        converted_product_price = float(converted_price) if converted_price is not None else None

    return base_lookup.model_copy(
        update={
            "default_market_price": converted_product_price if converted_product_price is not None else converted_default_price,
            "default_price_currency": display_currency if (converted_product_price is not None or converted_default_price is not None) else base_lookup.default_price_currency,
            "price_source": "cardmarket:public-product-page" if product.price_trend is not None else base_lookup.price_source,
            "price_note": _cardmarket_import_note(product, resolved_print.price_source),
            "cardmarket_reference": product.url,
            "cardmarket_product_url": resolved_print.cardmarket_product_url,
            "cardmarket_product_slug": resolved_print.cardmarket_product_slug,
            "cardmarket_set_slug": resolved_print.cardmarket_set_slug,
            "cardmarket_set_name": product.set_name,
            "cardmarket_product_name": resolved_print.cardmarket_product_name,
            "cardmarket_variant_name": resolved_print.cardmarket_variant_name,
            "cardmarket_category": product.category,
            "cardmarket_match_quality": resolved_print.cardmarket_match_quality,
            "cardmarket_verified_at": resolved_print.cardmarket_verified_at,
            "print_options": [resolved_print],
        }
    )


async def _resolve_english_cardmarket_naming(
    provider,
    *,
    remote_card: dict,
) -> tuple[str | None, dict[str, str]]:
    external_id = str(remote_card.get("external_id") or "").strip()
    if not external_id:
        return remote_card.get("name"), {}

    english_card = await provider.fetch_card(external_id=external_id, language="en")
    if not english_card:
        return remote_card.get("name"), {}

    product_name = english_card.get("name") or remote_card.get("name")
    set_names_by_code: dict[str, str] = {}
    for english_print in english_card.get("card_sets") or []:
        set_code = english_print.get("set_code")
        set_name = english_print.get("set_name")
        if set_code and set_name:
            set_names_by_code[set_code] = set_name
    return product_name, set_names_by_code


async def get_card_lookup(
    db: AsyncSession,
    *,
    name: str | None = None,
    external_id: str | None = None,
    language: str = "de",
) -> CardLookupResponse | None:
    app_settings = await get_app_settings(db)
    display_currency = app_settings.preferred_currency
    cardmarket_locale = _preferred_cardmarket_locale(language, app_settings.preferred_search_language)
    provider = get_card_data_provider()
    remote_card = await provider.fetch_card(name=name, external_id=external_id, language=language)
    if not remote_card:
        return None
    english_product_name, english_set_names_by_code = await _resolve_english_cardmarket_naming(
        provider,
        remote_card=remote_card,
    )

    normalized_name = normalize_name(remote_card.get("name") or name or "")
    exact_cardmarket_references = await _load_local_cardmarket_references(
        db,
        normalized_name=normalized_name,
        language=language,
    )

    default_market_price, default_price_currency, default_price_source = _resolve_default_remote_price(remote_card)
    if default_market_price is not None and default_price_currency and default_price_currency.upper() != display_currency.upper():
        converted_default_price = await convert_amount(default_market_price, default_price_currency, display_currency)
        default_market_price = float(converted_default_price) if converted_default_price is not None else None
        default_price_currency = display_currency

    raw_prints = remote_card.get("card_sets") or [{}]
    print_options: list[CardLookupPrintOption] = []
    seen_keys: set[tuple[str | None, str | None, str | None]] = set()
    set_counts: dict[str, int] = {}
    for remote_print in raw_prints:
        set_key = _normalize_lookup_value(remote_print.get("set_code") or remote_print.get("set_name"))
        if set_key:
            set_counts[set_key] = set_counts.get(set_key, 0) + 1

    for remote_print in raw_prints:
        set_name = remote_print.get("set_name")
        set_code = remote_print.get("set_code")
        rarity = remote_print.get("set_rarity")
        rarity_code = remote_print.get("set_rarity_code")
        cardmarket_set_name = english_set_names_by_code.get(set_code) or set_name
        key = (set_name, set_code, rarity)
        if key in seen_keys:
            continue
        seen_keys.add(key)

        print_card_number = _derive_card_number(set_code)
        print_language = _derive_print_language(set_code)
        set_key = _normalize_lookup_value(set_code or set_name)
        has_multiple_variants = bool(set_key and set_counts.get(set_key, 0) > 1)

        set_price = _parse_float(remote_print.get("set_price"))
        if set_price is not None:
            market_price = set_price
            price_currency = "USD"
            price_source = "ygoprodeck:set_price"
        else:
            market_price = default_market_price if not has_multiple_variants else None
            price_currency = default_price_currency if market_price is not None else None
            price_source = default_price_source if market_price is not None else None

        if market_price is not None and price_currency and price_currency.upper() != display_currency.upper():
            converted_market_price = await convert_amount(market_price, price_currency, display_currency)
            market_price = float(converted_market_price) if converted_market_price is not None else None
            price_currency = display_currency

        exact_reference = exact_cardmarket_references.get((set_code, print_card_number, rarity, print_language))
        cardmarket_resolution = resolve_cardmarket_product_url(
            locale=cardmarket_locale,
            cardmarket_product_url=exact_reference,
            cardmarket_product_slug=None,
            cardmarket_set_slug=build_cardmarket_set_slug(cardmarket_set_name),
            cardmarket_set_name=cardmarket_set_name,
            cardmarket_product_name=english_product_name or remote_card.get("name"),
            cardmarket_variant_name=None,
            card_name=english_product_name or remote_card.get("name"),
            has_multiple_variants=has_multiple_variants,
            allow_fallback=True,
        )

        if cardmarket_resolution.mode in {CARDMARKET_MATCH_EXACT, CARDMARKET_MATCH_EXACT_VARIANT, CARDMARKET_MATCH_SET_NAME}:
            cardmarket_reference = cardmarket_resolution.url
        else:
            cardmarket_reference = cardmarket_resolution.url or exact_reference

        if market_price is None and cardmarket_resolution.mode in {CARDMARKET_MATCH_AMBIGUOUS, CARDMARKET_MATCH_FAILED}:
            price_source = default_price_source or "ygoprodeck:none"

        print_options.append(
            CardLookupPrintOption(
                set_name=set_name,
                set_code=set_code,
                card_number=print_card_number,
                rarity=rarity,
                rarity_code=rarity_code,
                cardmarket_product_url=cardmarket_resolution.url if cardmarket_resolution.mode in {CARDMARKET_MATCH_EXACT, CARDMARKET_MATCH_EXACT_VARIANT, CARDMARKET_MATCH_SET_NAME} else None,
                cardmarket_product_slug=cardmarket_resolution.product_slug if cardmarket_resolution.mode in {CARDMARKET_MATCH_EXACT, CARDMARKET_MATCH_EXACT_VARIANT, CARDMARKET_MATCH_SET_NAME} else None,
                cardmarket_set_slug=cardmarket_resolution.set_slug,
                cardmarket_set_name=cardmarket_set_name,
                cardmarket_product_name=cardmarket_resolution.product_name or english_product_name or remote_card.get("name"),
                cardmarket_variant_name=cardmarket_resolution.variant_name,
                cardmarket_category=CARDMARKET_CATEGORY,
                cardmarket_match_quality=cardmarket_resolution.mode,
                cardmarket_verified_at=cardmarket_resolution.verified_at,
                market_price=market_price,
                price_currency=price_currency,
                price_source=price_source,
                price_note=_price_note(
                    price_source,
                    multiple_prints=has_multiple_variants,
                    has_cardmarket_reference=bool(cardmarket_reference),
                ),
                cardmarket_reference=cardmarket_reference,
                ygoprodeck_id=remote_card.get("external_id"),
                display_label=_build_print_label(set_name, set_code, rarity),
            )
        )

    safe_default_market_price = default_market_price if len(print_options) <= 1 else None
    safe_default_price_currency = default_price_currency if safe_default_market_price is not None else None
    safe_default_price_source = default_price_source if safe_default_market_price is not None else None
    first_cardmarket_reference = next(
        (option.cardmarket_reference for option in print_options if normalize_cardmarket_product_url(option.cardmarket_reference)),
        None,
    )
    first_cardmarket_quality = next((option.cardmarket_match_quality for option in print_options if option.cardmarket_match_quality), None)
    first_cardmarket_verified_at = next((option.cardmarket_verified_at for option in print_options if option.cardmarket_verified_at), None)
    return CardLookupResponse(
        external_id=remote_card.get("external_id", ""),
        name=remote_card.get("name", ""),
        effect_text=remote_card.get("description"),
        card_type=remote_card.get("card_type"),
        subtype=remote_card.get("subtype"),
        attribute=remote_card.get("attribute"),
        monster_type=remote_card.get("monster_type"),
        archetype=remote_card.get("archetype"),
        atk=remote_card.get("atk"),
        defense=remote_card.get("defense"),
        level=remote_card.get("level"),
        rank=remote_card.get("rank"),
        link_rating=remote_card.get("link_rating"),
        link_arrows=remote_card.get("link_arrows") or [],
        pendulum_scale=remote_card.get("pendulum_scale"),
        pendulum_effect=remote_card.get("pendulum_effect"),
        spell_trap_type=remote_card.get("spell_trap_type"),
        image_url=_remote_image_url(remote_card),
        ygoprodeck_id=remote_card.get("external_id"),
        default_market_price=safe_default_market_price,
        default_price_currency=safe_default_price_currency,
        price_source=safe_default_price_source,
        price_note=_price_note(
            safe_default_price_source,
            multiple_prints=len(print_options) > 1,
            has_cardmarket_reference=bool(first_cardmarket_reference),
        ),
        condition_price_supported=False,
        cardmarket_reference=first_cardmarket_reference,
        print_options=print_options,
        cardmarket_product_url=next((option.cardmarket_product_url for option in print_options if option.cardmarket_product_url), None),
        cardmarket_product_slug=next((option.cardmarket_product_slug for option in print_options if option.cardmarket_product_slug), None),
        cardmarket_set_slug=next((option.cardmarket_set_slug for option in print_options if option.cardmarket_set_slug), None),
        cardmarket_set_name=next((option.cardmarket_set_name for option in print_options if option.cardmarket_set_name), None),
        cardmarket_product_name=next((option.cardmarket_product_name for option in print_options if option.cardmarket_product_name), None),
        cardmarket_variant_name=next((option.cardmarket_variant_name for option in print_options if option.cardmarket_variant_name), None),
        cardmarket_category=next((option.cardmarket_category for option in print_options if option.cardmarket_category), None),
        cardmarket_match_quality=first_cardmarket_quality,
        cardmarket_verified_at=first_cardmarket_verified_at,
    )


async def serialize_card_summary(
    item: InventoryItem,
    *,
    mappings: list[SourceMapping] | None = None,
    active_job: SyncJob | None = None,
    display_currency: str = "EUR",
) -> CardSummary:
    card_print = item.card_print
    card = card_print.card
    image_asset = _first_image(card_print)
    if image_asset and image_asset.local_path:
        image_url = f"/media/{image_asset.local_path}"
    elif card_print.remote_image_url:
        image_url = _proxy_remote_image_url(card_print.remote_image_url) or _placeholder_url(item.id, card.name)
    else:
        image_url = _placeholder_url(item.id, card.name)
    current_market_price, conversion_note = await _display_price_value(item.current_market_price, item.current_price_currency, display_currency)
    purchase_price = float(item.purchase_price) if item.purchase_price is not None else None
    pricing = _build_pricing_status(item, mappings or [], active_job)
    if conversion_note:
        pricing = pricing.model_copy(update={"note": f"{pricing.note} {conversion_note}".strip() if pricing.note else conversion_note})

    return CardSummary(
        id=item.id,
        card_id=card.id,
        card_print_id=card_print.id,
        name=card.name,
        language=card_print.language,
        set_name=card_print.set_name,
        set_code=card_print.set_code,
        card_number=card_print.card_number,
        rarity=card_print.rarity,
        condition=item.condition,
        quantity=item.quantity,
        purchase_price=purchase_price,
        current_market_price=current_market_price,
        current_price_currency=display_currency,
        total_value=round((current_market_price or 0) * item.quantity, 2),
        price_change_7d=item.price_change_7d,
        price_change_30d=item.price_change_30d,
        trend_score=item.trend_score,
        card_type=card.card_type,
        attribute=card.attribute,
        monster_type=card.monster_type,
        atk=card.atk,
        defense=card.defense,
        level=card.level,
        rank=card.rank,
        link_rating=card.link_rating,
        storage_location_id=item.storage_location_id,
        storage_location_name=item.storage_location.name if item.storage_location else None,
        storage_path=item.storage_location.path_cache if item.storage_location else None,
        has_image=image_asset is not None,
        has_price=current_market_price is not None,
        image_url=image_url,
        last_priced_at=item.last_priced_at,
        last_price_source=item.last_price_source,
        last_price_match_quality=item.last_price_match_quality,
        last_price_note=item.last_price_note,
        pricing=pricing,
        notes=item.notes,
        updated_at=item.updated_at,
    )


async def list_cards(
    db: AsyncSession,
    *,
    page: int = 1,
    page_size: int = 20,
    q: str | None = None,
    language: str | None = None,
    set_code: str | None = None,
    card_type: str | None = None,
    attribute: str | None = None,
    monster_type: str | None = None,
    rarity: str | None = None,
    condition: str | None = None,
    storage_location_id: int | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    min_atk: int | None = None,
    max_atk: int | None = None,
    min_defense: int | None = None,
    max_defense: int | None = None,
    level: int | None = None,
    rank: int | None = None,
    has_image: bool | None = None,
    has_price: bool | None = None,
    price_direction: str | None = None,
    sort_by: str = "updated_at",
    sort_order: str = "desc",
) -> tuple[list[CardSummary], int]:
    app_settings = await get_app_settings(db)
    display_currency = app_settings.preferred_currency
    stmt = (
        select(InventoryItem)
        .join(InventoryItem.card_print)
        .join(CardPrint.card)
        .outerjoin(InventoryItem.storage_location)
        .options(
            selectinload(InventoryItem.storage_location),
            selectinload(InventoryItem.price_history),
            selectinload(InventoryItem.price_monitor_state),
            selectinload(InventoryItem.card_print).selectinload(CardPrint.card),
            selectinload(InventoryItem.card_print).selectinload(CardPrint.image_assets),
        )
    )
    count_stmt = select(func.count(InventoryItem.id)).join(InventoryItem.card_print).join(CardPrint.card).outerjoin(InventoryItem.storage_location)

    filters = []
    if q:
        pattern = f"%{q.strip()}%"
        filters.append(
            or_(
                Card.name.ilike(pattern),
                Card.description.ilike(pattern),
                CardPrint.set_name.ilike(pattern),
                CardPrint.set_code.ilike(pattern),
                CardPrint.card_number.ilike(pattern),
                CardPrint.rarity.ilike(pattern),
                CardPrint.language.ilike(pattern),
                InventoryItem.notes.ilike(pattern),
                StorageLocation.name.ilike(pattern),
            )
        )
    if language:
        filters.append(CardPrint.language == language)
    if set_code:
        filters.append(CardPrint.set_code.ilike(f"%{set_code}%"))
    if card_type:
        filters.append(Card.card_type == card_type)
    if attribute:
        filters.append(Card.attribute == attribute)
    if monster_type:
        filters.append(Card.monster_type == monster_type)
    if rarity:
        filters.append(CardPrint.rarity == rarity)
    if condition:
        filters.append(InventoryItem.condition == condition)
    if storage_location_id:
        filters.append(InventoryItem.storage_location_id == storage_location_id)
    if min_price is not None:
        filters.append(InventoryItem.current_market_price >= min_price)
    if max_price is not None:
        filters.append(InventoryItem.current_market_price <= max_price)
    if min_atk is not None:
        filters.append(Card.atk >= min_atk)
    if max_atk is not None:
        filters.append(Card.atk <= max_atk)
    if min_defense is not None:
        filters.append(Card.defense >= min_defense)
    if max_defense is not None:
        filters.append(Card.defense <= max_defense)
    if level is not None:
        filters.append(Card.level == level)
    if rank is not None:
        filters.append(Card.rank == rank)
    if has_image is True:
        filters.append(CardPrint.image_assets.any(and_(ImageAsset.status == "downloaded", ImageAsset.local_path.is_not(None))))
    if has_image is False:
        filters.append(~CardPrint.image_assets.any(and_(ImageAsset.status == "downloaded", ImageAsset.local_path.is_not(None))))
    if has_price is True:
        filters.append(InventoryItem.current_market_price.is_not(None))
    if has_price is False:
        filters.append(InventoryItem.current_market_price.is_(None))
    if price_direction == "up":
        filters.append(InventoryItem.price_change_7d > 0)
    elif price_direction == "down":
        filters.append(InventoryItem.price_change_7d < 0)
    elif price_direction == "volatile":
        filters.append(func.abs(InventoryItem.trend_score) >= 10)

    if filters:
        stmt = stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)

    sort_map = {
        "name": Card.name,
        "set_code": CardPrint.set_code,
        "price": InventoryItem.current_market_price,
        "quantity": InventoryItem.quantity,
        "trend": InventoryItem.trend_score,
        "updated_at": InventoryItem.updated_at,
    }
    sort_column = sort_map.get(sort_by, InventoryItem.updated_at)
    sort_clause = sort_column.asc() if sort_order == "asc" else sort_column.desc()
    stmt = stmt.order_by(sort_clause, Card.name.asc()).offset((page - 1) * page_size).limit(page_size)

    total = await db.scalar(count_stmt) or 0
    result = await db.execute(stmt)
    items = result.scalars().unique().all()
    grouped_mappings = await _load_source_mappings(db, items)
    active_jobs = await _load_active_price_jobs(db, items)
    serialized_items: list[CardSummary] = []
    for item in items:
        serialized_items.append(
            await serialize_card_summary(
                item,
                mappings=_mappings_for_item(grouped_mappings, item),
                active_job=active_jobs.get(item.id),
                display_currency=display_currency,
            )
        )
    return serialized_items, int(total)


async def get_card_detail(db: AsyncSession, inventory_item_id: int) -> CardDetail | None:
    app_settings = await get_app_settings(db)
    display_currency = app_settings.preferred_currency
    result = await db.execute(
        select(InventoryItem)
        .where(InventoryItem.id == inventory_item_id)
        .options(
            selectinload(InventoryItem.storage_location),
            selectinload(InventoryItem.price_history),
            selectinload(InventoryItem.price_monitor_state),
            selectinload(InventoryItem.card_print).selectinload(CardPrint.card),
            selectinload(InventoryItem.card_print).selectinload(CardPrint.image_assets),
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        return None

    mappings_result = await db.execute(
        select(SourceMapping).where(
            or_(
                and_(SourceMapping.target_type == "card", SourceMapping.target_id == item.card_print.card.id),
                and_(SourceMapping.target_type == "card_print", SourceMapping.target_id == item.card_print.id),
            )
        )
    )
    mappings = mappings_result.scalars().all()
    active_jobs = await _load_active_price_jobs(db, [item])
    summary = await serialize_card_summary(item, mappings=mappings, active_job=active_jobs.get(item.id), display_currency=display_currency)
    card = item.card_print.card
    price_history_entries = []
    for history in sorted(item.price_history, key=lambda entry: entry.captured_at, reverse=True)[:40]:
        converted_price, conversion_note = await _display_price_value(history.price, history.currency, display_currency)
        payload = history.payload or {}
        lowest_offer_price = await _display_optional_price_value(payload.get("lowest_offer_price"), history.currency, display_currency)
        selected_market_price = await _display_optional_price_value(payload.get("selected_market_price"), history.currency, display_currency)
        price_trend = await _display_optional_price_value(payload.get("price_trend"), history.currency, display_currency)
        avg_1d = await _display_optional_price_value(payload.get("avg_1d"), history.currency, display_currency)
        avg_7d = await _display_optional_price_value(payload.get("avg_7d"), history.currency, display_currency)
        avg_30d = await _display_optional_price_value(payload.get("avg_30d"), history.currency, display_currency)
        raw_offer_prices_sample = await _display_price_sample_values(
            payload.get("raw_offer_prices_sample"),
            history.currency,
            display_currency,
        )
        price_history_entries.append(
            PriceHistoryPoint(
                captured_at=history.captured_at,
                price=float(converted_price) if converted_price is not None else float(history.price),
                currency=display_currency,
                metric=history.metric,
                provider_key=history.provider_key,
                match_quality=payload.get("match_quality"),
                note=" ".join(filter(None, [payload.get("note"), conversion_note])) or None,
                source_url=payload.get("source_url"),
                source_product_id=payload.get("source_product_id"),
                set_code=payload.get("matched_set_code") or payload.get("set_code"),
                card_number=payload.get("matched_card_number") or payload.get("card_number"),
                rarity=payload.get("matched_rarity") or payload.get("rarity"),
                language=payload.get("matched_language") or payload.get("language"),
                lowest_offer_price=lowest_offer_price,
                selected_market_price=selected_market_price,
                pricing_strategy_used=payload.get("pricing_strategy_used"),
                offer_count_considered=payload.get("offer_count_considered"),
                outlier_detected=payload.get("outlier_detected"),
                price_trend=price_trend,
                avg_1d=avg_1d,
                avg_7d=avg_7d,
                avg_30d=avg_30d,
                filters_used=payload.get("filters_used"),
                raw_offer_prices_sample=raw_offer_prices_sample,
            )
        )

    return CardDetail(
        **summary.model_dump(),
        effect_text=card.description,
        subtype=card.subtype,
        archetype=card.archetype,
        spell_trap_type=card.spell_trap_type,
        rarity_code=item.card_print.rarity_code,
        edition=item.card_print.edition,
        release_date=item.card_print.release_date,
        cardmarket_reference=item.cardmarket_reference,
        cardmarket_product_url=item.card_print.cardmarket_product_url,
        cardmarket_product_slug=item.card_print.cardmarket_product_slug,
        cardmarket_set_slug=item.card_print.cardmarket_set_slug,
        cardmarket_set_name=item.card_print.cardmarket_set_name,
        cardmarket_product_name=item.card_print.cardmarket_product_name,
        cardmarket_variant_name=item.card_print.cardmarket_variant_name,
        cardmarket_category=item.card_print.cardmarket_category,
        cardmarket_match_quality=item.card_print.cardmarket_match_quality,
        cardmarket_verified_at=item.card_print.cardmarket_verified_at,
        cardmarket_expected_rarity=item.card_print.cardmarket_expected_rarity,
        cardmarket_expected_language=item.card_print.cardmarket_expected_language,
        cardmarket_expected_set_name=item.card_print.cardmarket_expected_set_name,
        tags=item.tags or [],
        link_arrows=card.link_arrows or [],
        pendulum_scale=card.pendulum_scale,
        pendulum_effect=card.pendulum_effect,
        price_history=price_history_entries,
        source_mappings=[
            SourceMappingResponse(
                provider_key=mapping.provider_key,
                external_id=mapping.external_id,
                external_url=mapping.external_url,
                last_synced_at=mapping.last_synced_at,
            )
            for mapping in mappings
        ],
    )


async def upsert_card(db: AsyncSession, payload: CardPayload, inventory_item_id: int | None = None) -> InventoryItem:
    if payload.storage_location_id:
        storage_location = await db.get(StorageLocation, payload.storage_location_id)
        if not storage_location:
            raise ValueError("Storage location not found.")

    if payload.card_id:
        card = await db.get(Card, payload.card_id)
    else:
        card = await db.scalar(select(Card).where(Card.normalized_name == normalize_name(payload.name)))

    if not card:
        card = Card(name=payload.name, normalized_name=normalize_name(payload.name))
        db.add(card)

    card.name = payload.name
    card.normalized_name = normalize_name(payload.name)
    card.card_type = payload.card_type
    card.subtype = payload.subtype
    card.description = payload.effect_text
    card.attribute = payload.attribute
    card.monster_type = payload.monster_type
    card.archetype = payload.archetype
    card.atk = payload.atk
    card.defense = payload.defense
    card.level = payload.level
    card.rank = payload.rank
    card.link_rating = payload.link_rating
    card.link_arrows = payload.link_arrows
    card.pendulum_scale = payload.pendulum_scale
    card.pendulum_effect = payload.pendulum_effect
    card.spell_trap_type = payload.spell_trap_type

    await db.flush()

    card_print = None
    if payload.card_print_id:
        card_print = await db.get(CardPrint, payload.card_print_id)
    if not card_print:
        card_print = await db.scalar(
            select(CardPrint).where(
                CardPrint.card_id == card.id,
                CardPrint.set_code == payload.set_code,
                CardPrint.language == payload.language,
                CardPrint.card_number == payload.card_number,
                CardPrint.rarity == payload.rarity,
            )
        )
    if not card_print:
        card_print = CardPrint(card_id=card.id, language=payload.language)
        db.add(card_print)

    preferred_cardmarket_set_name = payload.cardmarket_set_name or card_print.cardmarket_set_name or payload.set_name
    preferred_cardmarket_product_name = payload.cardmarket_product_name or card_print.cardmarket_product_name or payload.name
    preferred_cardmarket_variant_name = payload.cardmarket_variant_name or card_print.cardmarket_variant_name

    cardmarket_resolution = resolve_cardmarket_product_url(
        locale=_preferred_cardmarket_locale(payload.language, payload.language),
        cardmarket_product_url=payload.cardmarket_product_url or payload.cardmarket_reference,
        cardmarket_product_slug=payload.cardmarket_product_slug,
        cardmarket_set_slug=payload.cardmarket_set_slug,
        cardmarket_set_name=preferred_cardmarket_set_name,
        cardmarket_product_name=preferred_cardmarket_product_name,
        cardmarket_variant_name=preferred_cardmarket_variant_name,
        card_name=preferred_cardmarket_product_name,
        has_multiple_variants=payload.cardmarket_match_quality in {CARDMARKET_MATCH_AMBIGUOUS, CARDMARKET_MATCH_FAILED},
        allow_fallback=True,
    )

    card_print.language = payload.language
    card_print.set_name = payload.set_name
    card_print.set_code = payload.set_code
    card_print.card_number = payload.card_number
    card_print.rarity = payload.rarity
    card_print.rarity_code = payload.rarity_code
    card_print.edition = payload.edition
    card_print.release_date = payload.release_date
    card_print.cardmarket_product_url = cardmarket_resolution.url if cardmarket_resolution.mode in {CARDMARKET_MATCH_EXACT, CARDMARKET_MATCH_EXACT_VARIANT, CARDMARKET_MATCH_SET_NAME} else None
    card_print.cardmarket_product_slug = cardmarket_resolution.product_slug if card_print.cardmarket_product_url else None
    card_print.cardmarket_set_slug = cardmarket_resolution.set_slug or payload.cardmarket_set_slug
    card_print.cardmarket_set_name = preferred_cardmarket_set_name
    card_print.cardmarket_product_name = cardmarket_resolution.product_name or preferred_cardmarket_product_name
    card_print.cardmarket_variant_name = cardmarket_resolution.variant_name or preferred_cardmarket_variant_name
    card_print.cardmarket_category = payload.cardmarket_category or CARDMARKET_CATEGORY
    card_print.cardmarket_match_quality = payload.cardmarket_match_quality or cardmarket_resolution.mode
    card_print.cardmarket_verified_at = payload.cardmarket_verified_at or cardmarket_resolution.verified_at
    card_print.cardmarket_expected_rarity = payload.cardmarket_expected_rarity or payload.rarity
    card_print.cardmarket_expected_language = payload.cardmarket_expected_language or payload.language
    card_print.cardmarket_expected_set_name = payload.cardmarket_expected_set_name or payload.set_name

    await db.flush()

    if inventory_item_id:
        item = await db.get(InventoryItem, inventory_item_id)
        if not item:
            raise ValueError("Card not found.")
    else:
        item = InventoryItem(card_print_id=card_print.id)
        db.add(item)

    item.card_print_id = card_print.id
    item.storage_location_id = payload.storage_location_id
    item.condition = payload.condition
    item.quantity = payload.quantity
    item.purchase_price = payload.purchase_price
    item.current_market_price = payload.current_market_price
    item.current_price_currency = payload.current_price_currency
    item.cardmarket_reference = payload.cardmarket_reference or card_print.cardmarket_product_url or cardmarket_resolution.url
    item.notes = payload.notes
    item.tags = payload.tags
    if payload.current_market_price is not None:
        item.last_priced_at = datetime.utcnow()
        item.last_price_source = "manual"
        item.last_price_match_quality = "manual"
        item.last_price_note = "Manuell gepflegter Marktpreis."

    await db.flush()
    if inventory_item_id is None:
        await ensure_initial_price_monitor_state(db, item, now=datetime.utcnow())

    if payload.current_market_price is not None:
        db.add(
            PriceHistory(
                inventory_item_id=item.id,
                card_print_id=card_print.id,
                provider_key=item.last_price_source or "manual",
                metric="market",
                currency=item.current_price_currency,
                price=payload.current_market_price,
                payload={
                    "source": "manual",
                    "match_quality": "manual",
                    "note": "Manuell gepflegter Marktpreis.",
                    "set_code": card_print.set_code,
                    "card_number": card_print.card_number,
                    "rarity": card_print.rarity,
                    "language": card_print.language,
                    "source_url": payload.cardmarket_reference,
                    "cardmarket_product_url": payload.cardmarket_product_url,
                    "source_product_id": payload.external_ids.get("cardmarket"),
                },
            )
        )

    existing_mappings_result = await db.execute(
        select(SourceMapping).where(SourceMapping.target_type == "card_print", SourceMapping.target_id == card_print.id)
    )
    existing_mappings = {mapping.provider_key: mapping for mapping in existing_mappings_result.scalars().all()}
    for provider_key, external_id in payload.external_ids.items():
        mapping = existing_mappings.get(provider_key)
        if not mapping:
            mapping = SourceMapping(target_type="card_print", target_id=card_print.id, provider_key=provider_key, external_id=external_id)
            db.add(mapping)
        mapping.external_id = external_id
        if provider_key == "cardmarket":
            mapping.external_url = (
                normalize_cardmarket_product_url(payload.cardmarket_product_url)
                or normalize_cardmarket_product_url(payload.cardmarket_reference)
                or normalize_cardmarket_product_url(external_id)
                or payload.cardmarket_product_url
                or payload.cardmarket_reference
            )
        mapping.last_synced_at = datetime.utcnow()

    await db.flush()
    return item


async def delete_card(db: AsyncSession, inventory_item_id: int) -> None:
    item = await db.get(InventoryItem, inventory_item_id)
    if not item:
        raise ValueError("Card not found.")
    await db.delete(item)


async def get_filter_options(db: AsyncSession) -> CardFilterOptions:
    async def distinct_values(column) -> list[str]:
        result = await db.execute(select(column).where(column.is_not(None)).distinct().order_by(column.asc()))
        return [value for value in result.scalars().all() if value]

    from app.services.storage import list_storage_locations

    return CardFilterOptions(
        rarities=await distinct_values(CardPrint.rarity),
        conditions=await distinct_values(InventoryItem.condition),
        card_types=await distinct_values(Card.card_type),
        attributes=await distinct_values(Card.attribute),
        monster_types=await distinct_values(Card.monster_type),
        storage_locations=await list_storage_locations(db),
    )


async def price_history_for_card(db: AsyncSession, inventory_item_id: int) -> list[PriceHistoryPoint]:
    app_settings = await get_app_settings(db)
    display_currency = app_settings.preferred_currency
    result = await db.execute(
        select(PriceHistory)
        .where(PriceHistory.inventory_item_id == inventory_item_id)
        .order_by(PriceHistory.captured_at.desc())
    )
    history = result.scalars().all()
    items: list[PriceHistoryPoint] = []
    for entry in history:
        converted_price, conversion_note = await _display_price_value(entry.price, entry.currency, display_currency)
        payload = entry.payload or {}
        lowest_offer_price = await _display_optional_price_value(payload.get("lowest_offer_price"), entry.currency, display_currency)
        selected_market_price = await _display_optional_price_value(payload.get("selected_market_price"), entry.currency, display_currency)
        price_trend = await _display_optional_price_value(payload.get("price_trend"), entry.currency, display_currency)
        avg_1d = await _display_optional_price_value(payload.get("avg_1d"), entry.currency, display_currency)
        avg_7d = await _display_optional_price_value(payload.get("avg_7d"), entry.currency, display_currency)
        avg_30d = await _display_optional_price_value(payload.get("avg_30d"), entry.currency, display_currency)
        raw_offer_prices_sample = await _display_price_sample_values(
            payload.get("raw_offer_prices_sample"),
            entry.currency,
            display_currency,
        )
        items.append(
            PriceHistoryPoint(
                captured_at=entry.captured_at,
                price=float(converted_price) if converted_price is not None else float(entry.price),
                currency=display_currency,
                metric=entry.metric,
                provider_key=entry.provider_key,
                match_quality=payload.get("match_quality"),
                note=" ".join(filter(None, [payload.get("note"), conversion_note])) or None,
                source_url=payload.get("source_url"),
                source_product_id=payload.get("source_product_id"),
                set_code=payload.get("matched_set_code") or payload.get("set_code"),
                card_number=payload.get("matched_card_number") or payload.get("card_number"),
                rarity=payload.get("matched_rarity") or payload.get("rarity"),
                language=payload.get("matched_language") or payload.get("language"),
                lowest_offer_price=lowest_offer_price,
                selected_market_price=selected_market_price,
                pricing_strategy_used=payload.get("pricing_strategy_used"),
                offer_count_considered=payload.get("offer_count_considered"),
                outlier_detected=payload.get("outlier_detected"),
                price_trend=price_trend,
                avg_1d=avg_1d,
                avg_7d=avg_7d,
                avg_30d=avg_30d,
                filters_used=payload.get("filters_used"),
                raw_offer_prices_sample=raw_offer_prices_sample,
            )
        )
    return items
