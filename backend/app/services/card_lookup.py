from __future__ import annotations

import logging

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.cardmarket import (
    CardmarketPrintContext,
    CardmarketResolvedProduct,
    get_cardmarket_product_resolver,
)
from app.integrations.cardmarket_links import (
    CARDMARKET_CATEGORY,
    CARDMARKET_MATCH_AMBIGUOUS,
    CARDMARKET_MATCH_FAILED,
    build_cardmarket_product_url,
    build_cardmarket_set_slug,
    normalize_cardmarket_product_url,
    resolve_cardmarket_product_url,
)
from app.integrations.card_data import get_card_data_provider
from app.integrations.price_values import parse_positive_price
from app.models import Card, CardPrint, CardSet, SourceMapping
from app.schemas import (
    CardLookupPrintOption,
    CardLookupResponse,
    CardLookupSuggestion,
)
from app.services.app_settings import get_app_settings
from app.services.currency import convert_amount
from app.services.card_common import (
    CARDMARKET_SAFE_MATCH_QUALITIES,
    _append_local_cardmarket_reference,
    _build_failed_cardmarket_resolution,
    _build_print_label,
    _card_numbers_match,
    _dedupe_text_values,
    _derive_card_number,
    _derive_print_language,
    _find_matching_card_set,
    _is_safe_cardmarket_quality,
    _load_cardmarket_set_slug_hints,
    _normalize_lookup_value,
    _normalize_optional_text,
    _parse_language_preferences,
    _preferred_cardmarket_locale,
    _price_note,
    _remote_image_url,
    _resolve_default_remote_price,
    _set_codes_match_language_neutral,
    _update_card_set_cardmarket_metadata,
    normalize_name,
)

logger = logging.getLogger(__name__)

async def _load_local_cardmarket_references(
    db: AsyncSession,
    *,
    normalized_name: str,
    language: str,
) -> dict[tuple[str | None, str | None, str | None, str | None], list[dict[str, object | None]]]:
    exact_references: dict[tuple[str | None, str | None, str | None, str | None], list[dict[str, object | None]]] = {}

    card_print_rows = await db.execute(
        select(
            CardPrint.set_code,
            CardPrint.card_number,
            CardPrint.rarity,
            CardPrint.language,
            CardPrint.cardmarket_product_url,
            CardPrint.cardmarket_product_slug,
            CardPrint.cardmarket_set_slug,
            CardPrint.cardmarket_set_name,
            CardPrint.cardmarket_product_name,
            CardPrint.cardmarket_variant_name,
            CardPrint.cardmarket_match_quality,
            CardPrint.cardmarket_verified_at,
        )
        .join(Card, Card.id == CardPrint.card_id)
        .where(
            Card.normalized_name == normalized_name,
            CardPrint.language == language,
        )
    )
    for (
        set_code,
        card_number,
        rarity,
        card_language,
        product_url,
        product_slug,
        set_slug,
        cardmarket_set_name,
        cardmarket_product_name,
        cardmarket_variant_name,
        match_quality,
        verified_at,
    ) in card_print_rows.all():
        exact_url = normalize_cardmarket_product_url(product_url)
        if not exact_url and product_slug and set_slug:
            locale = _preferred_cardmarket_locale(card_language, language)
            exact_url = build_cardmarket_product_url(locale, set_slug, product_slug)
        if match_quality is not None and not _is_safe_cardmarket_quality(match_quality):
            continue
        _append_local_cardmarket_reference(
            exact_references,
            (set_code, card_number, rarity, card_language),
            url=exact_url,
            product_slug=product_slug,
            set_slug=set_slug,
            set_name=cardmarket_set_name,
            product_name=cardmarket_product_name,
            variant_name=cardmarket_variant_name,
            match_quality=match_quality,
            verified_at=verified_at,
        )

    mapping_rows = await db.execute(
        select(
            CardPrint.set_code,
            CardPrint.card_number,
            CardPrint.rarity,
            CardPrint.language,
            CardPrint.cardmarket_product_slug,
            CardPrint.cardmarket_set_slug,
            CardPrint.cardmarket_set_name,
            CardPrint.cardmarket_product_name,
            CardPrint.cardmarket_variant_name,
            CardPrint.cardmarket_match_quality,
            CardPrint.cardmarket_verified_at,
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
    for (
        set_code,
        card_number,
        rarity,
        card_language,
        product_slug,
        set_slug,
        cardmarket_set_name,
        cardmarket_product_name,
        cardmarket_variant_name,
        match_quality,
        verified_at,
        external_url,
        external_id,
    ) in mapping_rows.all():
        if not _is_safe_cardmarket_quality(match_quality):
            continue
        exact_url = normalize_cardmarket_product_url(external_url) or normalize_cardmarket_product_url(external_id)
        _append_local_cardmarket_reference(
            exact_references,
            (set_code, card_number, rarity, card_language),
            url=exact_url,
            product_slug=product_slug,
            set_slug=set_slug,
            set_name=cardmarket_set_name,
            product_name=cardmarket_product_name,
            variant_name=cardmarket_variant_name,
            match_quality=match_quality,
            verified_at=verified_at,
        )

    return exact_references

def _find_local_cardmarket_references(
    references: dict[tuple[str | None, str | None, str | None, str | None], list[dict[str, object | None]]],
    *,
    set_code: str | None,
    card_number: str | None,
    rarity: str | None,
    language: str | None,
) -> list[dict[str, object | None]]:
    exact = references.get((set_code, card_number, rarity, language), [])
    if exact:
        return exact

    matches: list[dict[str, object | None]] = []
    for (candidate_set_code, candidate_card_number, candidate_rarity, candidate_language), candidates in references.items():
        if not _set_codes_match_language_neutral(set_code, candidate_set_code):
            continue
        if card_number and candidate_card_number and not _card_numbers_match(card_number, candidate_card_number):
            continue
        if _normalize_lookup_value(rarity) != _normalize_lookup_value(candidate_rarity):
            continue
        if candidate_language == language:
            matches[0:0] = candidates
        else:
            matches.extend(candidates)

    deduped: list[dict[str, object | None]] = []
    seen_urls: set[str] = set()
    for candidate in matches:
        url = str(candidate.get("url") or "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        deduped.append(candidate)
    return deduped

async def search_card_catalog(query: str, *, language: str = "de", limit: int = 8, display_currency: str = "EUR") -> list[CardLookupSuggestion]:
    provider = get_card_data_provider()
    search_languages = _parse_language_preferences(language, default=("de", "en"))
    suggestions: list[CardLookupSuggestion] = []
    seen_external_ids: set[str] = set()

    for search_language in search_languages:
        remote_cards = await provider.search_cards(query=query, language=search_language, limit=limit)
        for card_data in remote_cards:
            external_id = str(card_data.get("external_id", "")).strip()
            if not external_id or external_id in seen_external_ids:
                continue
            seen_external_ids.add(external_id)
            default_market_price, default_price_currency, price_source = _resolve_default_remote_price(card_data)
            if default_market_price is not None and default_price_currency and default_price_currency.upper() != display_currency.upper():
                converted_price = await convert_amount(default_market_price, default_price_currency, display_currency)
                default_market_price = float(converted_price) if converted_price is not None else None
                default_price_currency = display_currency
            suggestions.append(
                CardLookupSuggestion(
                    external_id=external_id,
                    name=card_data.get("name", ""),
                    card_type=card_data.get("card_type"),
                    card_kind=card_data.get("card_kind", "other"),
                    attribute=card_data.get("attribute"),
                    monster_type=card_data.get("monster_type"),
                    image_url=_remote_image_url(card_data),
                    set_count=len(card_data.get("card_sets") or []),
                    default_market_price=default_market_price,
                    default_price_currency=default_price_currency,
                    price_source=price_source,
                )
            )
            if len(suggestions) >= limit:
                return suggestions[:limit]

    return suggestions

async def _fetch_remote_card_for_languages(
    provider,
    *,
    name: str | None = None,
    external_id: str | None = None,
    language: str | None = None,
) -> tuple[dict | None, str]:
    search_languages = _parse_language_preferences(language, default=("de", "en"))
    for candidate_language in search_languages:
        remote_card = await provider.fetch_card(
            name=name,
            external_id=external_id,
            language=candidate_language,
            tcgplayer_data=True,
        )
        if remote_card:
            return remote_card, candidate_language

    remote_card = await provider.fetch_card(
        name=name,
        external_id=external_id,
        language=None,
        tcgplayer_data=True,
    )
    return remote_card, (search_languages[0] if search_languages else "de")

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

async def _load_ygoprodeck_external_id(
    db: AsyncSession,
    *,
    card_id: int,
    card_print_id: int | None,
    payload_external_ids: dict[str, str],
) -> str | None:
    payload_external_id = _normalize_optional_text(payload_external_ids.get("ygoprodeck"))
    if payload_external_id:
        return payload_external_id

    target_filters = [
        and_(SourceMapping.target_type == "card", SourceMapping.target_id == card_id),
    ]
    if card_print_id:
        target_filters.insert(0, and_(SourceMapping.target_type == "card_print", SourceMapping.target_id == card_print_id))

    result = await db.execute(
        select(SourceMapping)
        .where(
            SourceMapping.provider_key == "ygoprodeck",
            or_(*target_filters),
        )
        .order_by(SourceMapping.target_type.desc(), SourceMapping.updated_at.desc())
    )
    mapping = result.scalars().first()
    return _normalize_optional_text(mapping.external_id if mapping else None)

def _matches_cardmarket_remote_print(
    remote_print: dict,
    *,
    set_code: str | None,
    set_name: str | None,
    card_number: str | None,
    rarity: str | None,
) -> bool:
    normalized_set_code = _normalize_lookup_value(set_code)
    normalized_set_name = _normalize_lookup_value(set_name)
    remote_set_code = _normalize_lookup_value(remote_print.get("set_code"))
    remote_set_name = _normalize_lookup_value(remote_print.get("set_name"))

    if normalized_set_code and remote_set_code and not _set_codes_match_language_neutral(set_code, remote_print.get("set_code")):
        return False
    if normalized_set_code and not remote_set_code:
        return False
    if not normalized_set_code and normalized_set_name and remote_set_name and normalized_set_name != remote_set_name:
        return False

    expected_card_number = card_number or _derive_card_number(set_code)
    remote_card_number = _derive_card_number(remote_print.get("set_code"))
    if expected_card_number and remote_card_number and not _card_numbers_match(expected_card_number, remote_card_number):
        return False

    normalized_rarity = _normalize_lookup_value(rarity)
    remote_rarity = _normalize_lookup_value(remote_print.get("set_rarity"))
    if normalized_rarity and remote_rarity and normalized_rarity != remote_rarity:
        return False

    return True

def _cardmarket_variant_count_for_remote_card(remote_card: dict, *, set_code: str | None, set_name: str | None) -> int:
    normalized_set_name = _normalize_lookup_value(set_name)
    if not set_code and not normalized_set_name:
        return 1

    count = 0
    for remote_print in remote_card.get("card_sets") or []:
        remote_set_code = remote_print.get("set_code")
        remote_set_name = _normalize_lookup_value(remote_print.get("set_name"))
        if set_code and remote_set_code:
            matches = _set_codes_match_language_neutral(set_code, remote_set_code)
        else:
            matches = bool(normalized_set_name and remote_set_name == normalized_set_name)
        if matches:
            count += 1
    return max(count, 1)

async def _resolve_exact_cardmarket_product(
    db: AsyncSession,
    *,
    card: Card,
    card_print: CardPrint | None,
    payload: CardPayload,
    normalized_language: str,
    matched_card_set: CardSet | None = None,
) -> CardmarketResolvedProduct:
    resolver = get_cardmarket_product_resolver()
    provider = get_card_data_provider()

    preferred_set_name = payload.cardmarket_set_name or (card_print.cardmarket_set_name if card_print else None) or payload.set_name
    preferred_product_name = payload.cardmarket_product_name or (card_print.cardmarket_product_name if card_print else None) or payload.name
    preferred_variant_name = payload.cardmarket_variant_name or (card_print.cardmarket_variant_name if card_print else None)
    variant_count = 2 if preferred_variant_name else 1
    matched_card_set = matched_card_set or await _find_matching_card_set(db, set_code=payload.set_code, set_name=payload.set_name)
    set_slug_hints = _dedupe_text_values(
        [
            payload.cardmarket_set_slug,
            card_print.cardmarket_set_slug if card_print else None,
            matched_card_set.cardmarket_set_slug if matched_card_set else None,
            *(await _load_cardmarket_set_slug_hints(db, set_code=payload.set_code, card_set=matched_card_set)),
        ]
    )
    alias_names = _dedupe_text_values(
        [
            payload.set_name,
            preferred_set_name,
            matched_card_set.name if matched_card_set else None,
            matched_card_set.cardmarket_set_name if matched_card_set else None,
            *((matched_card_set.cardmarket_aliases or []) if matched_card_set else []),
        ]
    )

    ygoprodeck_external_id = await _load_ygoprodeck_external_id(
        db,
        card_id=card.id,
        card_print_id=card_print.id if card_print and card_print.id else None,
        payload_external_ids=payload.external_ids,
    )
    remote_card = None
    lookup_languages = list(dict.fromkeys([normalized_language, "en"]))
    for lookup_language in lookup_languages:
        try:
            remote_card = await provider.fetch_card(
                external_id=ygoprodeck_external_id,
                name=None if ygoprodeck_external_id else payload.name,
                language=lookup_language,
            )
        except Exception as exc:
            logger.warning(
                "Failed to load %s card data while resolving Cardmarket URL for '%s' (%s): %s",
                lookup_language,
                card.name,
                payload.set_code,
                exc,
            )
            continue
        if remote_card:
            break

    if remote_card:
        try:
            english_product_name, english_set_names_by_code = await _resolve_english_cardmarket_naming(provider, remote_card=remote_card)
            matched_remote_print = next(
                (
                    remote_print
                    for remote_print in remote_card.get("card_sets") or []
                    if _matches_cardmarket_remote_print(
                        remote_print,
                        set_code=payload.set_code,
                        set_name=payload.set_name,
                        card_number=payload.card_number,
                        rarity=payload.rarity,
                    )
                ),
                None,
            )
            preferred_product_name = english_product_name or preferred_product_name
            preferred_set_name = english_set_names_by_code.get(payload.set_code) or next(
                (
                    english_set_name
                    for english_set_code, english_set_name in english_set_names_by_code.items()
                    if _set_codes_match_language_neutral(payload.set_code, english_set_code)
                ),
                preferred_set_name,
            )
            variant_count = _cardmarket_variant_count_for_remote_card(
                remote_card,
                set_code=payload.set_code,
                set_name=payload.set_name,
            )
            if matched_remote_print:
                alias_names = _dedupe_text_values([*alias_names, matched_remote_print.get("set_name")])
                if not preferred_set_name:
                    preferred_set_name = matched_remote_print.get("set_name") or preferred_set_name
        except Exception as exc:
            logger.exception("Failed to enrich Cardmarket naming for '%s' (%s): %s", card.name, payload.set_code, exc)

    context = CardmarketPrintContext(
        product_name=preferred_product_name,
        set_name=preferred_set_name,
        set_code=payload.set_code,
        rarity=payload.cardmarket_expected_rarity or payload.rarity,
        card_number=payload.card_number or _derive_card_number(payload.set_code),
        language=payload.cardmarket_expected_language or normalized_language,
        variant_count=variant_count,
        variant_name=preferred_variant_name,
        existing_product_url=payload.cardmarket_product_url or payload.cardmarket_reference or (card_print.cardmarket_product_url if card_print else None),
        existing_set_slug=payload.cardmarket_set_slug or (card_print.cardmarket_set_slug if card_print else None),
        existing_product_slug=payload.cardmarket_product_slug or (card_print.cardmarket_product_slug if card_print else None),
        set_slug_hints=set_slug_hints,
        set_aliases=alias_names,
    )
    try:
        resolution = await resolver.resolve(context)
    except Exception as exc:
        logger.exception("Failed to resolve Cardmarket product during card creation for '%s' (%s): %s", card.name, payload.set_code, exc)
        return _build_failed_cardmarket_resolution(context, f"resolver error: {exc}")

    _update_card_set_cardmarket_metadata(
        matched_card_set,
        resolution=resolution,
        alias_names=alias_names,
    )
    logger.info(
        "Built Cardmarket URL for card_print %s: %s (%s)",
        card_print.id if card_print and card_print.id else "new",
        resolution.url,
        resolution.match_quality,
    )
    return resolution

async def get_card_lookup(
    db: AsyncSession,
    *,
    name: str | None = None,
    external_id: str | None = None,
    language: str = "de",
) -> CardLookupResponse | None:
    app_settings = await get_app_settings(db)
    lookup_languages = _parse_language_preferences(language, default=("de", "en"))
    preferred_lookup_language = lookup_languages[0] if lookup_languages else "de"
    display_currency = app_settings.preferred_currency
    cardmarket_locale = _preferred_cardmarket_locale(preferred_lookup_language, app_settings.preferred_search_language)
    provider = get_card_data_provider()
    remote_card, resolved_lookup_language = await _fetch_remote_card_for_languages(
        provider,
        name=name,
        external_id=external_id,
        language=language,
    )
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
        language=resolved_lookup_language,
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

        set_price = parse_positive_price(remote_print.get("set_price"))
        if set_price is not None:
            market_price = set_price
            price_currency = "USD"
            price_source = "ygoprodeck:tcgplayer_set_price"
        else:
            market_price = default_market_price
            price_currency = default_price_currency if market_price is not None else None
            price_source = default_price_source if market_price is not None else None

        if market_price is not None and price_currency and price_currency.upper() != display_currency.upper():
            converted_market_price = await convert_amount(market_price, price_currency, display_currency)
            market_price = float(converted_market_price) if converted_market_price is not None else None
            price_currency = display_currency

        local_variant_candidates = _find_local_cardmarket_references(
            exact_cardmarket_references,
            set_code=set_code,
            card_number=print_card_number,
            rarity=rarity,
            language=print_language,
        )
        resolution_inputs = local_variant_candidates or [None]

        for local_variant_candidate in resolution_inputs:
            option_price_source = price_source
            cardmarket_resolution = resolve_cardmarket_product_url(
                locale=cardmarket_locale,
                cardmarket_product_url=str(local_variant_candidate.get("url")) if local_variant_candidate else None,
                cardmarket_product_slug=str(local_variant_candidate.get("product_slug")) if local_variant_candidate and local_variant_candidate.get("product_slug") else None,
                cardmarket_set_slug=(
                    str(local_variant_candidate.get("set_slug"))
                    if local_variant_candidate and local_variant_candidate.get("set_slug")
                    else build_cardmarket_set_slug(cardmarket_set_name, set_code=set_code)
                ),
                cardmarket_set_name=(
                    str(local_variant_candidate.get("set_name"))
                    if local_variant_candidate and local_variant_candidate.get("set_name")
                    else cardmarket_set_name
                ),
                cardmarket_product_name=(
                    str(local_variant_candidate.get("product_name"))
                    if local_variant_candidate and local_variant_candidate.get("product_name")
                    else english_product_name or remote_card.get("name")
                ),
                cardmarket_variant_name=(
                    str(local_variant_candidate.get("variant_name"))
                    if local_variant_candidate and local_variant_candidate.get("variant_name")
                    else None
                ),
                cardmarket_rarity=rarity,
                card_name=english_product_name or remote_card.get("name"),
                has_multiple_variants=has_multiple_variants or len(local_variant_candidates) > 1,
                allow_fallback=False,
            )

            if local_variant_candidate and local_variant_candidate.get("verified_at") and not cardmarket_resolution.verified_at:
                try:
                    cardmarket_resolution.verified_at = local_variant_candidate.get("verified_at")  # type: ignore[assignment]
                except Exception:
                    pass

            if cardmarket_resolution.mode in CARDMARKET_SAFE_MATCH_QUALITIES:
                cardmarket_reference = cardmarket_resolution.url
            else:
                cardmarket_reference = None

            if market_price is None and cardmarket_resolution.mode in {CARDMARKET_MATCH_AMBIGUOUS, CARDMARKET_MATCH_FAILED}:
                option_price_source = default_price_source or "ygoprodeck:none"

            print_options.append(
                CardLookupPrintOption(
                    set_name=set_name,
                    set_code=set_code,
                    card_number=print_card_number,
                    rarity=rarity,
                    rarity_code=rarity_code,
                    cardmarket_product_url=cardmarket_resolution.url if cardmarket_resolution.mode in CARDMARKET_SAFE_MATCH_QUALITIES else None,
                    cardmarket_product_slug=cardmarket_resolution.product_slug if cardmarket_resolution.mode in CARDMARKET_SAFE_MATCH_QUALITIES else None,
                    cardmarket_set_slug=cardmarket_resolution.set_slug,
                    cardmarket_set_name=cardmarket_resolution.set_name or cardmarket_set_name,
                    cardmarket_product_name=cardmarket_resolution.product_name or english_product_name or remote_card.get("name"),
                    cardmarket_variant_name=cardmarket_resolution.variant_name,
                    cardmarket_category=CARDMARKET_CATEGORY,
                    cardmarket_match_quality=cardmarket_resolution.mode,
                    cardmarket_verified_at=cardmarket_resolution.verified_at,
                    market_price=market_price,
                    price_currency=price_currency,
                    price_source=option_price_source,
                    price_note=_price_note(
                        option_price_source,
                        multiple_prints=False,
                        has_cardmarket_reference=bool(cardmarket_reference),
                    ),
                    cardmarket_reference=cardmarket_reference,
                    ygoprodeck_id=remote_card.get("external_id"),
                    display_label=_build_print_label(set_name, set_code, rarity, cardmarket_resolution.variant_name),
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
        card_kind=remote_card.get("card_kind", "other"),
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
