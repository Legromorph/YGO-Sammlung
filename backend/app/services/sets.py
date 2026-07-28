from __future__ import annotations

from datetime import datetime, timedelta
import logging
import re
from urllib.parse import quote

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.card_metadata import apply_card_metadata, normalize_card_metadata
from app.config import settings
from app.integrations.card_data import get_card_data_provider
from app.integrations.price_values import parse_positive_price
from app.models import Card, CardPrint, CardSet, ImageAsset, InventoryItem, SourceMapping
from app.schemas import CardSetSummary, SetCardRow, SetCardsResponse
from app.services.app_settings import get_app_settings
from app.services.currency import convert_amount
from app.time_utils import utc_now

logger = logging.getLogger(__name__)

LANGUAGE_SET_CODE_PREFIXES: dict[str, tuple[str, ...]] = {
    "de": ("DE",),
    "en": ("EN",),
    "fr": ("FR",),
    "it": ("IT",),
    "es": ("ES", "SP"),
    "pt": ("PT",),
    "jp": ("JP",),
    "ja": ("JP",),
    "ko": ("KR",),
}


def normalize_name(value: str) -> str:
    return " ".join(value.lower().split())


def _normalize_lookup_value(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"[^a-z0-9]", "", value.lower())


def _parse_int(value: object) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


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


def _preferred_set_code_prefix(language: str | None) -> str | None:
    normalized_language = (language or "").strip().lower()
    prefixes = LANGUAGE_SET_CODE_PREFIXES.get(normalized_language)
    return prefixes[0] if prefixes else None


def _translate_prefixed_value(value: str | None, language: str | None) -> str | None:
    normalized_value = (value or "").strip().upper()
    replacement_prefix = _preferred_set_code_prefix(language)
    if not normalized_value or not replacement_prefix:
        return normalized_value or None

    match = re.match(r"^([A-Z]{2,3})(.*)$", normalized_value)
    if not match:
        return normalized_value
    return f"{replacement_prefix}{match.group(2)}"


def _translate_set_code_language(set_code: str | None, language: str | None) -> str | None:
    normalized_set_code = (set_code or "").strip().upper()
    if not normalized_set_code:
        return None
    replacement_prefix = _preferred_set_code_prefix(language)
    if not replacement_prefix or "-" not in normalized_set_code:
        return normalized_set_code

    series, suffix = normalized_set_code.split("-", 1)
    translated_suffix = _translate_prefixed_value(suffix, language)
    if not translated_suffix:
        return normalized_set_code
    return f"{series}-{translated_suffix}"


def _translate_card_number_language(card_number: str | None, language: str | None, *, set_code: str | None = None) -> str | None:
    translated_from_value = _translate_prefixed_value(card_number, language)
    if translated_from_value:
        return translated_from_value
    translated_set_code = _translate_set_code_language(set_code, language)
    if translated_set_code:
        return _derive_card_number(translated_set_code)
    return (card_number or "").strip().upper() or None


def _set_code_language_neutral_signature(set_code: str | None) -> tuple[str, str] | None:
    normalized_set_code = (set_code or "").strip().upper()
    if not normalized_set_code:
        return None
    if "-" not in normalized_set_code:
        return _normalize_lookup_value(normalized_set_code), ""

    series, suffix = normalized_set_code.split("-", 1)
    match = re.match(r"([A-Z]{2,3})([A-Z0-9-]+)$", suffix)
    if not match:
        return _normalize_lookup_value(series), _normalize_lookup_value(suffix)
    return _normalize_lookup_value(series), _normalize_lookup_value(match.group(2))


def _print_signature(card_print: CardPrint) -> tuple[int, str, str, str]:
    set_signature = _set_code_language_neutral_signature(card_print.set_code) or ("", "")
    return (
        int(card_print.card_id),
        set_signature[0],
        set_signature[1],
        _normalize_lookup_value(card_print.rarity),
    )


def _placeholder_url(set_id: int, card_name: str) -> str:
    return f"{settings.api_prefix}/assets/placeholder?item_id={set_id}&label={card_name}"


def _proxy_remote_image_url(url: str | None) -> str | None:
    if not url:
        return None
    return f"{settings.api_prefix}/assets/proxy?url={quote(url, safe='')}"


def _first_image(card_print: CardPrint) -> ImageAsset | None:
    assets = sorted(
        [asset for asset in card_print.image_assets if asset.status == "downloaded" and asset.local_path],
        key=lambda asset: asset.downloaded_at or asset.updated_at,
        reverse=True,
    )
    return assets[0] if assets else None


def _natural_sort_key(value: str | None) -> tuple:
    text = value or ""
    parts = re.split(r"(\d+)", text.upper())
    return tuple(int(part) if part.isdigit() else part for part in parts)


def _merge_warning(existing_warning: str | None, additional_warning: str | None) -> str | None:
    normalized_existing = (existing_warning or "").strip()
    normalized_additional = (additional_warning or "").strip()
    if not normalized_additional:
        return normalized_existing or None
    if not normalized_existing or normalized_additional in normalized_existing:
        return normalized_existing or normalized_additional
    return f"{normalized_existing} {normalized_additional}".strip()


def _set_code_prefix(value: str | None) -> str:
    normalized = (value or "").strip().upper()
    if not normalized:
        return ""
    return normalized.split("-", 1)[0]


def _matches_card_set(remote_print: dict, card_set: CardSet) -> bool:
    remote_set_name = _normalize_lookup_value(remote_print.get("set_name"))
    catalog_set_name = _normalize_lookup_value(card_set.name)
    remote_set_code_prefix = _set_code_prefix(remote_print.get("set_code"))
    catalog_set_code_prefix = _set_code_prefix(card_set.set_code)

    names_match = bool(remote_set_name and catalog_set_name and remote_set_name == catalog_set_name)
    codes_match = bool(remote_set_code_prefix and catalog_set_code_prefix and remote_set_code_prefix == catalog_set_code_prefix)

    if names_match and remote_set_code_prefix and catalog_set_code_prefix:
        return codes_match
    if names_match:
        return True
    if codes_match and not remote_set_name:
        return True
    if codes_match and not catalog_set_name:
        return True
    return False


def _local_card_print_matches_set(card_print: CardPrint, card_set: CardSet) -> bool:
    return _matches_card_set(
        {
            "set_name": card_print.set_name,
            "set_code": card_print.set_code,
        },
        card_set,
    )


def _select_matching_remote_prints(remote_card: dict, card_set: CardSet) -> list[dict]:
    return [entry for entry in (remote_card.get("card_sets") or []) if _matches_card_set(entry, card_set)]


def _dedupe_remote_cards(remote_cards: list[dict]) -> list[dict]:
    deduped: list[dict] = []
    seen_external_ids: set[str] = set()
    for remote_card in remote_cards:
        external_id = str(remote_card.get("external_id") or "").strip()
        if not external_id or external_id in seen_external_ids:
            continue
        seen_external_ids.add(external_id)
        deduped.append(remote_card)
    return deduped


def _matching_remote_card_count(remote_cards: list[dict], card_set: CardSet) -> int:
    return len(_dedupe_remote_cards([remote_card for remote_card in remote_cards if _select_matching_remote_prints(remote_card, card_set)]))


def _is_suspiciously_small_result(expected_card_count: int, matched_card_count: int) -> bool:
    if matched_card_count <= 0:
        return False
    if expected_card_count >= 8:
        return matched_card_count <= max(2, expected_card_count // 4)
    return expected_card_count == 0 and matched_card_count <= 1


def _build_completeness_warning(card_set: CardSet) -> tuple[bool, str | None]:
    expected_card_count = _expected_card_count(card_set)
    loaded_card_count = int(card_set.loaded_card_count or 0)
    loaded_print_count = int(card_set.loaded_print_count or 0)

    if expected_card_count <= 0:
        return True, card_set.sync_warning

    if loaded_card_count < expected_card_count:
        return (
            False,
            card_set.sync_warning
            or (
                f"Set möglicherweise unvollständig: lokal {loaded_card_count} von erwarteten "
                f"{expected_card_count} Karten und {loaded_print_count} Prints."
            ),
        )

    return True, card_set.sync_warning


def _expected_card_count(card_set: CardSet) -> int:
    payload_count = _parse_int((card_set.source_payload or {}).get("num_of_cards")) or 0
    direct_count = int(card_set.card_count or 0)
    return max(payload_count, direct_count)


async def _local_set_counts(db: AsyncSession, card_set: CardSet) -> tuple[int, int]:
    result = await db.execute(
        select(CardPrint).where(CardPrint.set_id == card_set.id)
    )
    matching_card_ids: set[int] = set()
    matching_print_count = 0
    for card_print in result.scalars().all():
        if not _local_card_print_matches_set(card_print, card_set):
            continue
        matching_card_ids.add(card_print.card_id)
        matching_print_count += 1
    return len(matching_card_ids), matching_print_count


def _select_translation_source_language(prints: list[CardPrint], requested_language: str) -> str | None:
    counts: dict[str, int] = {}
    for card_print in prints:
        language = (card_print.language or "").strip().lower()
        if not language:
            continue
        counts[language] = counts.get(language, 0) + 1

    if not counts:
        return None

    if requested_language != "en" and counts.get("en"):
        return "en"

    fallback_languages = [language for language in counts if language != requested_language]
    if not fallback_languages:
        return None
    return max(fallback_languages, key=lambda language: (counts.get(language, 0), language == "en", language))


async def _ensure_requested_language_prints(db: AsyncSession, card_set: CardSet, requested_language: str) -> None:
    normalized_language = (requested_language or "").strip().lower()
    if not normalized_language:
        return

    result = await db.execute(
        select(CardPrint)
        .where(CardPrint.set_id == card_set.id)
        .options(selectinload(CardPrint.card))
    )
    local_prints = [card_print for card_print in result.scalars().all() if _local_card_print_matches_set(card_print, card_set)]
    if not local_prints:
        return

    source_language = _select_translation_source_language(local_prints, normalized_language)
    if not source_language:
        return

    source_prints = [card_print for card_print in local_prints if (card_print.language or "").strip().lower() == source_language]
    if not source_prints:
        return

    target_prints = [card_print for card_print in local_prints if (card_print.language or "").strip().lower() == normalized_language]
    target_by_signature = {
        _print_signature(card_print): card_print
        for card_print in target_prints
    }

    mapping_target_ids = [card_print.id for card_print in [*source_prints, *target_prints]]
    mapping_result = await db.execute(
        select(SourceMapping).where(
            SourceMapping.target_type == "card_print",
            SourceMapping.provider_key == "ygoprodeck",
            SourceMapping.target_id.in_(mapping_target_ids or [-1]),
        )
    )
    mappings_by_target_id = {mapping.target_id: mapping for mapping in mapping_result.scalars().all()}

    derived_any = False
    for source_print in source_prints:
        signature = _print_signature(source_print)
        target_print = target_by_signature.get(signature)
        is_new_target = target_print is None
        if is_new_target:
            target_print = CardPrint(card_id=source_print.card_id, set_id=source_print.set_id, language=normalized_language)
            db.add(target_print)
            await db.flush()
            target_by_signature[signature] = target_print

        translated_set_code = _translate_set_code_language(source_print.set_code, normalized_language) or source_print.set_code
        translated_card_number = _translate_card_number_language(
            source_print.card_number,
            normalized_language,
            set_code=source_print.set_code,
        ) or _derive_card_number(translated_set_code)

        target_print.set_id = source_print.set_id
        target_print.language = normalized_language
        target_print.set_name = source_print.set_name or card_set.name
        target_print.set_code = translated_set_code
        target_print.card_number = translated_card_number
        target_print.rarity = source_print.rarity
        target_print.rarity_code = source_print.rarity_code
        target_print.edition = source_print.edition
        target_print.release_date = source_print.release_date
        target_print.remote_image_url = source_print.remote_image_url
        target_print.cardmarket_set_slug = source_print.cardmarket_set_slug
        target_print.cardmarket_set_name = source_print.cardmarket_set_name or source_print.set_name or card_set.name
        target_print.cardmarket_product_name = source_print.cardmarket_product_name or source_print.card.name
        target_print.cardmarket_variant_name = source_print.cardmarket_variant_name
        target_print.cardmarket_category = source_print.cardmarket_category
        target_print.cardmarket_expected_rarity = source_print.cardmarket_expected_rarity or source_print.rarity
        target_print.cardmarket_expected_language = normalized_language
        target_print.cardmarket_expected_set_name = source_print.cardmarket_expected_set_name or source_print.set_name or card_set.name
        if is_new_target:
            target_print.cardmarket_product_url = None
            target_print.cardmarket_product_slug = None
            target_print.cardmarket_match_quality = None
            target_print.cardmarket_verified_at = None

        source_mapping = mappings_by_target_id.get(source_print.id)
        if source_mapping:
            target_mapping = mappings_by_target_id.get(target_print.id)
            if not target_mapping:
                target_mapping = SourceMapping(
                    target_type="card_print",
                    target_id=target_print.id,
                    provider_key=source_mapping.provider_key,
                    external_id=source_mapping.external_id,
                )
                db.add(target_mapping)
                mappings_by_target_id[target_print.id] = target_mapping

            payload = dict(source_mapping.payload or {})
            if translated_set_code:
                payload["set_code"] = translated_set_code
            target_mapping.external_id = source_mapping.external_id
            target_mapping.external_url = source_mapping.external_url
            target_mapping.payload = payload or None
            target_mapping.last_synced_at = source_mapping.last_synced_at or utc_now()

        derived_any = derived_any or is_new_target

    if derived_any:
        logger.info(
            "Derived %s set print variants for set %s (%s) from %s source prints.",
            normalized_language.upper(),
            card_set.name,
            card_set.set_code,
            source_language.upper(),
        )
    await db.flush()


async def _fetch_remote_cards_via_catalog_scan(
    provider,
    *,
    card_set: CardSet,
    expected_card_count: int,
    page_size: int = 1000,
) -> tuple[list[dict], int]:
    matched_cards: list[dict] = []
    seen_external_ids: set[str] = set()
    offset = 0
    pages_scanned = 0

    while True:
        page = await provider.fetch_cards_page(offset=offset, limit=page_size)
        if not page:
            break
        pages_scanned += 1

        for remote_card in page:
            if not _select_matching_remote_prints(remote_card, card_set):
                continue
            external_id = str(remote_card.get("external_id") or "").strip()
            if not external_id or external_id in seen_external_ids:
                continue
            seen_external_ids.add(external_id)
            matched_cards.append(remote_card)

        if expected_card_count and len(matched_cards) >= expected_card_count:
            break
        if len(page) < page_size:
            break
        offset += len(page)

    return matched_cards, pages_scanned


async def _load_exact_remote_set_cards(
    provider,
    *,
    card_set: CardSet,
    expected_card_count: int,
) -> tuple[list[dict], str, int, int]:
    direct_remote_cards = await provider.fetch_cards_for_set(card_set.name, tcgplayer_data=True)
    direct_exact_cards = _dedupe_remote_cards(
        [remote_card for remote_card in direct_remote_cards if _select_matching_remote_prints(remote_card, card_set)]
    )
    direct_exact_count = len(direct_exact_cards)
    direct_is_complete = expected_card_count > 0 and direct_exact_count >= expected_card_count

    if direct_exact_cards and (
        direct_is_complete or (expected_card_count <= 0 and not _is_suspiciously_small_result(expected_card_count, direct_exact_count))
    ):
        return direct_exact_cards, "cardset_query", direct_exact_count, 0

    logger.warning(
        "Set query for %s (%s) returned only %s exact card(s) for expected %s. Falling back to catalog scan.",
        card_set.name,
        card_set.set_code,
        direct_exact_count,
        expected_card_count,
    )
    scanned_cards, pages_scanned = await _fetch_remote_cards_via_catalog_scan(
        provider,
        card_set=card_set,
        expected_card_count=expected_card_count,
    )
    scanned_exact_cards = _dedupe_remote_cards(scanned_cards)
    if scanned_exact_cards:
        logger.info(
            "Catalog scan recovered %s exact card(s) for %s (%s) after %s page(s).",
            len(scanned_exact_cards),
            card_set.name,
            card_set.set_code,
            pages_scanned,
        )
        return scanned_exact_cards, "catalog_scan", direct_exact_count, pages_scanned

    return direct_exact_cards, "cardset_query", direct_exact_count, pages_scanned


async def _find_card_by_external_id(db: AsyncSession, provider_key: str, external_id: str) -> Card | None:
    result = await db.execute(
        select(Card)
        .join(SourceMapping, and_(SourceMapping.target_type == "card", SourceMapping.target_id == Card.id))
        .where(SourceMapping.provider_key == provider_key, SourceMapping.external_id == external_id)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _ensure_card_mapping(db: AsyncSession, card: Card, provider_key: str, remote_card: dict) -> None:
    result = await db.execute(
        select(SourceMapping).where(
            SourceMapping.target_type == "card",
            SourceMapping.target_id == card.id,
            SourceMapping.provider_key == provider_key,
        )
    )
    mapping = result.scalar_one_or_none()
    if not mapping:
        mapping = SourceMapping(target_type="card", target_id=card.id, provider_key=provider_key, external_id=remote_card["external_id"])
        db.add(mapping)
    mapping.external_id = remote_card["external_id"]
    mapping.external_url = f"https://db.ygoprodeck.com/card/?search={remote_card['external_id']}"
    mapping.payload = {"name": remote_card["name"]}
    mapping.last_synced_at = utc_now()


async def _ensure_print_mapping(db: AsyncSession, card_print: CardPrint, provider_key: str, remote_card: dict, remote_print: dict) -> None:
    result = await db.execute(
        select(SourceMapping).where(
            SourceMapping.target_type == "card_print",
            SourceMapping.target_id == card_print.id,
            SourceMapping.provider_key == provider_key,
        )
    )
    mapping = result.scalar_one_or_none()
    if not mapping:
        mapping = SourceMapping(target_type="card_print", target_id=card_print.id, provider_key=provider_key, external_id=remote_card["external_id"])
        db.add(mapping)
    mapping.external_id = remote_card["external_id"]
    mapping.external_url = f"https://db.ygoprodeck.com/card/?search={remote_card['external_id']}"
    mapping.payload = {
        "set_name": remote_print.get("set_name"),
        "set_code": remote_print.get("set_code"),
        "set_rarity": remote_print.get("set_rarity"),
        "set_rarity_code": remote_print.get("set_rarity_code"),
        "set_price": remote_print.get("set_price"),
    }
    mapping.last_synced_at = utc_now()


def _serialize_card_set(card_set: CardSet) -> CardSetSummary:
    is_complete, warning = _build_completeness_warning(card_set)
    expected_card_count = _expected_card_count(card_set)
    loaded_card_count = int(card_set.loaded_card_count or 0)
    loaded_print_count = int(card_set.loaded_print_count or 0)
    return CardSetSummary(
        id=card_set.id,
        provider_key=card_set.provider_key,
        name=card_set.name,
        set_code=card_set.set_code,
        card_count=expected_card_count,
        expected_card_count=expected_card_count,
        loaded_card_count=loaded_card_count,
        loaded_print_count=loaded_print_count,
        is_complete=is_complete,
        warning=warning,
        release_date=card_set.release_date,
        last_synced_at=card_set.last_synced_at,
    )


async def sync_card_sets_catalog(db: AsyncSession, *, force: bool = False) -> None:
    latest_sync = await db.scalar(select(func.max(CardSet.catalog_synced_at)).where(CardSet.provider_key == "ygoprodeck"))
    if latest_sync and not force and latest_sync >= utc_now() - timedelta(hours=24):
        return

    provider = get_card_data_provider()
    remote_sets = await provider.fetch_sets()
    if not remote_sets:
        logger.warning("Set catalog sync returned no remote sets.")
        return

    existing_result = await db.execute(select(CardSet).where(CardSet.provider_key == provider.provider_key))
    existing_sets = existing_result.scalars().all()
    existing_by_key = {
        (card_set.normalized_name, _set_code_prefix(card_set.set_code)): card_set
        for card_set in existing_sets
    }
    existing_by_name: dict[str, list[CardSet]] = {}
    for card_set in existing_sets:
        existing_by_name.setdefault(card_set.normalized_name, []).append(card_set)
    synced_at = utc_now()

    for remote_set in remote_sets:
        normalized_name = normalize_name(remote_set["name"])
        remote_set_code_prefix = _set_code_prefix(remote_set.get("set_code"))
        card_set = existing_by_key.get((normalized_name, remote_set_code_prefix))
        if not card_set:
            candidates = existing_by_name.get(normalized_name, [])
            if len(candidates) == 1:
                card_set = candidates[0]
        if not card_set:
            card_set = CardSet(provider_key=provider.provider_key, name=remote_set["name"], normalized_name=normalized_name)
            db.add(card_set)
            existing_by_name.setdefault(normalized_name, []).append(card_set)
        card_set.name = remote_set["name"]
        card_set.normalized_name = normalized_name
        card_set.set_code = remote_set.get("set_code")
        card_set.card_count = remote_set.get("card_count")
        card_set.release_date = remote_set.get("release_date")
        card_set.source_payload = remote_set.get("payload")
        card_set.catalog_synced_at = synced_at
        card_set.last_synced_at = synced_at
        existing_by_key[(normalized_name, remote_set_code_prefix)] = card_set

    await db.flush()


async def list_card_sets(db: AsyncSession, *, q: str | None = None, limit: int = 30) -> list[CardSetSummary]:
    await sync_card_sets_catalog(db)
    stmt = select(CardSet).where(CardSet.provider_key == "ygoprodeck")
    if q:
        pattern = f"%{q.strip()}%"
        stmt = stmt.where(or_(CardSet.name.ilike(pattern), CardSet.set_code.ilike(pattern)))
    stmt = stmt.order_by(CardSet.name.asc()).limit(limit)
    result = await db.execute(stmt)
    return [_serialize_card_set(card_set) for card_set in result.scalars().all()]


async def _upsert_card_set_card(db: AsyncSession, card_set: CardSet, remote_card: dict, *, provider_key: str) -> None:
    card = await _find_card_by_external_id(db, provider_key, remote_card["external_id"])
    if not card:
        card = await db.scalar(select(Card).where(Card.normalized_name == normalize_name(remote_card["name"])))

    if not card:
        card = Card(name=remote_card["name"], normalized_name=normalize_name(remote_card["name"]))
        db.add(card)
        await db.flush()

    card.name = remote_card["name"]
    card.normalized_name = normalize_name(remote_card["name"])
    card.description = remote_card.get("description")
    apply_card_metadata(
        card,
        normalize_card_metadata(
            card_type=remote_card.get("card_type"),
            subtype=remote_card.get("subtype"),
            frame_type=remote_card.get("frame_type"),
            attribute=remote_card.get("attribute"),
            monster_type=remote_card.get("monster_type"),
            archetype=remote_card.get("archetype"),
            atk=remote_card.get("atk"),
            defense=remote_card.get("defense"),
            level=remote_card.get("level"),
            rank=remote_card.get("rank"),
            link_rating=remote_card.get("link_rating"),
            link_arrows=remote_card.get("link_arrows"),
            pendulum_scale=remote_card.get("pendulum_scale"),
            pendulum_effect=remote_card.get("pendulum_effect"),
            spell_trap_type=remote_card.get("spell_trap_type"),
        ),
    )
    card.limitations = remote_card.get("limitations")
    card.source_payload = remote_card.get("payload")
    card.last_synced_at = utc_now()

    await _ensure_card_mapping(db, card, provider_key, remote_card)
    await db.flush()

    remote_prints = _select_matching_remote_prints(remote_card, card_set)
    image_payload = (remote_card.get("card_images") or [{}])[0]
    remote_image_url = image_payload.get("image_url")

    for remote_print in remote_prints:
        set_code = remote_print.get("set_code")
        card_print = await db.scalar(
            select(CardPrint).where(
                CardPrint.card_id == card.id,
                CardPrint.set_id == card_set.id,
                CardPrint.set_code == set_code,
                CardPrint.rarity == remote_print.get("set_rarity"),
            )
        )
        if not card_print:
            card_print = CardPrint(card_id=card.id, set_id=card_set.id)
            db.add(card_print)

        card_print.set_id = card_set.id
        card_print.language = _derive_print_language(set_code)
        card_print.set_name = remote_print.get("set_name") or card_set.name
        card_print.set_code = set_code
        card_print.card_number = _derive_card_number(set_code)
        card_print.rarity = remote_print.get("set_rarity")
        card_print.rarity_code = remote_print.get("set_rarity_code")
        card_print.release_date = card_set.release_date
        card_print.remote_image_url = remote_image_url

        await db.flush()
        await _ensure_print_mapping(db, card_print, provider_key, remote_card, remote_print)


async def sync_card_set_cards(db: AsyncSession, card_set: CardSet, *, language: str = "de", force: bool = False) -> None:
    expected_card_count = _expected_card_count(card_set)
    if expected_card_count:
        card_set.card_count = expected_card_count
    local_loaded_card_count, local_loaded_print_count = await _local_set_counts(db, card_set)
    card_set.loaded_card_count = local_loaded_card_count
    card_set.loaded_print_count = local_loaded_print_count

    is_complete, warning = _build_completeness_warning(card_set)
    is_stale = not card_set.cards_synced_at or card_set.cards_synced_at < utc_now() - timedelta(days=7)
    needs_sync = force or not local_loaded_print_count or not is_complete or is_stale

    if not needs_sync:
        await _ensure_requested_language_prints(db, card_set, language)
        local_loaded_card_count, local_loaded_print_count = await _local_set_counts(db, card_set)
        card_set.loaded_card_count = local_loaded_card_count
        card_set.loaded_print_count = local_loaded_print_count
        card_set.sync_warning = warning
        await db.flush()
        return

    provider = get_card_data_provider()
    remote_cards, sync_strategy, direct_exact_count, pages_scanned = await _load_exact_remote_set_cards(
        provider,
        card_set=card_set,
        expected_card_count=expected_card_count,
    )
    if not remote_cards:
        await _ensure_requested_language_prints(db, card_set, language)
        local_loaded_card_count, local_loaded_print_count = await _local_set_counts(db, card_set)
        card_set.loaded_card_count = local_loaded_card_count
        card_set.loaded_print_count = local_loaded_print_count
        card_set.sync_warning = f"Provider lieferte für {card_set.name} keine Karten."
        logger.warning("Set sync returned no cards for %s (%s).", card_set.name, card_set.set_code)
        await db.flush()
        return

    if expected_card_count and len(remote_cards) < expected_card_count:
        logger.warning(
            "Exact set sync for %s returned only %s of expected %s cards via %s. Requested language %s will be ignored for completeness.",
            card_set.name,
            len(remote_cards),
            expected_card_count,
            sync_strategy,
            language,
        )

    for remote_card in remote_cards:
        await _upsert_card_set_card(db, card_set, remote_card, provider_key=provider.provider_key)

    await _ensure_requested_language_prints(db, card_set, language)
    local_loaded_card_count, local_loaded_print_count = await _local_set_counts(db, card_set)
    card_set.loaded_card_count = local_loaded_card_count
    card_set.loaded_print_count = local_loaded_print_count
    card_set.cards_synced_at = utc_now()
    card_set.last_synced_at = card_set.cards_synced_at

    is_complete = not expected_card_count or local_loaded_card_count >= expected_card_count
    if not is_complete:
        card_set.sync_warning = (
            f"Set möglicherweise unvollständig: lokal {local_loaded_card_count} von erwarteten "
            f"{expected_card_count} Karten nach dem Sync. Quelle={sync_strategy}, direkter Treffer={direct_exact_count}, Seiten im Vollscan={pages_scanned}."
        )
        logger.warning(
            "Set %s (%s) remains incomplete after sync: %s of %s cards, %s prints. Strategy=%s direct_exact=%s pages_scanned=%s",
            card_set.name,
            card_set.set_code,
            local_loaded_card_count,
            expected_card_count,
            local_loaded_print_count,
            sync_strategy,
            direct_exact_count,
            pages_scanned,
        )
    else:
        card_set.sync_warning = None

    await db.flush()


async def get_card_set_cards(db: AsyncSession, set_id: int, *, language: str = "de") -> SetCardsResponse:
    app_settings = await get_app_settings(db)
    display_currency = app_settings.preferred_currency
    requested_language = (language or "de").strip().lower() or "de"
    await sync_card_sets_catalog(db)
    card_set = await db.get(CardSet, set_id)
    if not card_set:
        raise ValueError("Set not found.")

    await sync_card_set_cards(db, card_set, language=requested_language)

    result = await db.execute(
        select(CardPrint)
        .where(
            CardPrint.set_id == card_set.id,
            CardPrint.language == requested_language,
        )
        .options(
            selectinload(CardPrint.card),
            selectinload(CardPrint.image_assets),
        )
    )
    raw_prints = result.scalars().unique().all()
    prints = [card_print for card_print in raw_prints if _local_card_print_matches_set(card_print, card_set)]
    filtered_out_print_count = len(raw_prints) - len(prints)
    if filtered_out_print_count > 0:
        warning = f"{filtered_out_print_count} lokal verknüpfte Prints wurden wegen unpassender Set-Zuordnung ausgeblendet."
        card_set.sync_warning = _merge_warning(card_set.sync_warning, warning)
        logger.warning(
            "Filtered %s locally linked print(s) from set %s (%s) because they do not match the canonical set signature.",
            filtered_out_print_count,
            card_set.name,
            card_set.set_code,
        )
    print_ids = [card_print.id for card_print in prints]

    inventory_totals: dict[int, dict[str, object]] = {}
    if print_ids:
        inventory_quantity_result = await db.execute(
            select(
                InventoryItem.card_print_id,
                func.coalesce(func.sum(InventoryItem.quantity), 0),
            )
            .where(InventoryItem.card_print_id.in_(print_ids))
            .group_by(InventoryItem.card_print_id)
        )
        inventory_totals = {
            row[0]: {
                "quantity": int(row[1] or 0),
                "price": None,
                "currency": None,
            }
            for row in inventory_quantity_result.all()
        }
        inventory_prices_result = await db.execute(
            select(
                InventoryItem.card_print_id,
                InventoryItem.current_market_price,
                InventoryItem.current_price_currency,
            )
            .where(
                InventoryItem.card_print_id.in_(print_ids),
                InventoryItem.current_market_price > 0,
            )
            .order_by(
                InventoryItem.card_print_id.asc(),
                InventoryItem.last_priced_at.desc().nullslast(),
                InventoryItem.updated_at.desc(),
            )
        )
        for card_print_id, price, currency in inventory_prices_result.all():
            bucket = inventory_totals.setdefault(
                card_print_id,
                {"quantity": 0, "price": None, "currency": None},
            )
            if bucket["price"] is not None:
                continue
            positive_price = parse_positive_price(price)
            if positive_price is not None:
                bucket["price"] = positive_price
                bucket["currency"] = currency

    mapping_result = await db.execute(
        select(SourceMapping).where(
            SourceMapping.target_type == "card_print",
            SourceMapping.provider_key == "ygoprodeck",
            SourceMapping.target_id.in_(print_ids or [-1]),
        )
    )
    mappings = {mapping.target_id: mapping for mapping in mapping_result.scalars().all()}

    duplicate_signatures: set[tuple[str, str, str]] = set()
    seen_signatures: set[tuple[str, str, str]] = set()
    items: list[SetCardRow] = []
    for card_print in prints:
        image_asset = _first_image(card_print)
        if image_asset and image_asset.local_path:
            image_url = f"/media/{image_asset.local_path}"
        elif card_print.remote_image_url:
            image_url = _proxy_remote_image_url(card_print.remote_image_url) or _placeholder_url(card_set.id, card_print.card.name)
        else:
            image_url = _placeholder_url(card_set.id, card_print.card.name)

        inventory_totals_row = inventory_totals.get(card_print.id, {})
        mapping = mappings.get(card_print.id)
        mapping_price = parse_positive_price((mapping.payload or {}).get("set_price")) if mapping and mapping.payload else None
        mapping_currency = "USD" if mapping_price is not None else None
        converted_inventory_price = None
        if inventory_totals_row.get("price") is not None:
            converted = await convert_amount(inventory_totals_row.get("price"), inventory_totals_row.get("currency"), display_currency)
            converted_inventory_price = float(converted) if converted is not None else None
        converted_mapping_price = None
        if mapping_price is not None:
            converted = await convert_amount(mapping_price, mapping_currency, display_currency)
            converted_mapping_price = float(converted) if converted is not None else None

        signature = (
            mapping.external_id if mapping else str(card_print.card_id),
            card_print.set_code or "",
            card_print.rarity or "",
        )
        if signature in seen_signatures:
            duplicate_signatures.add(signature)
        seen_signatures.add(signature)

        items.append(
            SetCardRow(
                card_print_id=card_print.id,
                card_id=card_print.card_id,
                name=card_print.card.name,
                language=card_print.language,
                card_number=card_print.card_number,
                set_code=card_print.set_code,
                rarity=card_print.rarity,
                card_type=card_print.card.card_type,
                card_kind=card_print.card.card_kind,
                image_url=image_url,
                existing_quantity=int(inventory_totals_row.get("quantity", 0)),
                current_market_price=converted_inventory_price if converted_inventory_price is not None else converted_mapping_price,
                current_price_currency=display_currency if (converted_inventory_price is not None or converted_mapping_price is not None) else inventory_totals_row.get("currency") or mapping_currency,
            )
        )

    if duplicate_signatures:
        duplicate_message = f"Lokale Dubletten erkannt: {len(duplicate_signatures)} Print-Signaturen erscheinen mehrfach."
        logger.warning("Duplicate local set print signatures for %s (%s): %s", card_set.name, card_set.set_code, sorted(duplicate_signatures))
        card_set.sync_warning = _merge_warning(card_set.sync_warning, duplicate_message)

    await db.flush()

    items.sort(key=lambda item: (_natural_sort_key(item.card_number or item.set_code), item.rarity or "", item.name))
    serialized_set = _serialize_card_set(card_set)
    serialized_set.set_code = _translate_set_code_language(serialized_set.set_code, requested_language) or serialized_set.set_code
    return SetCardsResponse(set=serialized_set, items=items)
