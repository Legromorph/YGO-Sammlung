from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.price_values import parse_positive_price
from app.models import CardPrint, CardSet, InventoryItem, PriceHistory, PurchaseBatch, PurchaseBatchItem, SourceMapping, StorageLocation
from app.schemas import BulkSetImportPayload, BulkSetImportResponse
from app.services.currency import convert_amount
from app.services.sets import _expected_card_count, sync_card_set_cards, sync_card_sets_catalog
from app.services.price_monitor import ensure_initial_price_monitor_state
from app.time_utils import utc_now

FOUR_DP = Decimal("0.0001")
TWO_DP = Decimal("0.01")


@dataclass(slots=True)
class AllocationLine:
    card_print_id: int
    quantity: int
    unit_price: Decimal
    line_total: Decimal


def _normalize_note(value: str | None) -> str | None:
    normalized = value.strip() if value else None
    return normalized or None


def _to_decimal_amount(value: object) -> Decimal:
    if value in (None, ""):
        return Decimal("0.00")
    return Decimal(str(value)).quantize(TWO_DP, rounding=ROUND_HALF_UP)


def _to_float(value: Decimal | float | int | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _allocate_display_total(
    display_total_price: Decimal,
    selected_lines: list[tuple[int, int]],
    unit_weights: dict[int, Decimal] | None = None,
) -> tuple[list[AllocationLine], Decimal | None, int]:
    """Split a purchase total across lines, exact to the cent.

    Without weights every card costs the same. With ``unit_weights`` (for
    example market prices) each line gets a share proportional to
    ``weight * quantity``. Leftover cents go to the lines with the largest
    rounding remainder, so the line totals always add up to the total.
    """
    total_quantity = sum(quantity for _, quantity in selected_lines)
    if total_quantity <= 0:
        return [], None, 0

    total_cents = int((display_total_price * 100).to_integral_value(rounding=ROUND_HALF_UP))
    average_unit_price = (display_total_price / Decimal(total_quantity)).quantize(FOUR_DP, rounding=ROUND_HALF_UP)

    weights = unit_weights or {}
    line_weights = [weights.get(card_print_id, Decimal(1)) * quantity for card_print_id, quantity in selected_lines]
    weight_sum = sum(line_weights, Decimal(0))
    if weight_sum <= 0:
        line_weights = [Decimal(quantity) for _, quantity in selected_lines]
        weight_sum = Decimal(total_quantity)

    raw_shares = [Decimal(total_cents) * weight / weight_sum for weight in line_weights]
    line_cents = [int(share) for share in raw_shares]
    remainder_cents = total_cents - sum(line_cents)
    by_fraction = sorted(range(len(selected_lines)), key=lambda index: (-(raw_shares[index] - line_cents[index]), index))
    for index in by_fraction[:remainder_cents]:
        line_cents[index] += 1

    allocations: list[AllocationLine] = []
    for (card_print_id, quantity), cents in zip(selected_lines, line_cents):
        line_total = (Decimal(cents) / Decimal(100)).quantize(TWO_DP, rounding=ROUND_HALF_UP)
        allocations.append(
            AllocationLine(
                card_print_id=card_print_id,
                quantity=quantity,
                unit_price=(line_total / Decimal(quantity)).quantize(FOUR_DP, rounding=ROUND_HALF_UP),
                line_total=line_total,
            )
        )
    return allocations, average_unit_price, remainder_cents


async def _market_value_weights(
    market_prices: dict[int, tuple[float | None, str, str | None]],
    *,
    currency: str,
) -> dict[int, Decimal]:
    """Per-unit market prices in the purchase currency; unpriced cards get the cheapest known price."""
    converted: dict[int, Decimal] = {}
    for card_print_id, (price, price_currency, _source) in market_prices.items():
        if price is None:
            continue
        value = await convert_amount(price, price_currency, currency)
        if value is not None and value > 0:
            converted[card_print_id] = Decimal(str(value))
    if not converted:
        return {}
    floor_weight = min(converted.values())
    return {card_print_id: converted.get(card_print_id, floor_weight) for card_print_id in market_prices}


async def bulk_add_inventory_from_set(db: AsyncSession, payload: BulkSetImportPayload) -> BulkSetImportResponse:
    if payload.storage_location_id:
        storage_location = await db.get(StorageLocation, payload.storage_location_id)
        if not storage_location:
            raise ValueError("Storage location not found.")

    await sync_card_sets_catalog(db)
    card_set = await db.get(CardSet, payload.set_id)
    if not card_set:
        raise ValueError("Set not found.")

    requested_language = (payload.language or "de").strip().lower() or "de"
    await sync_card_set_cards(db, card_set, language=requested_language)
    expected_card_count = _expected_card_count(card_set)
    loaded_card_count = int(card_set.loaded_card_count or 0)
    set_warning = None
    if expected_card_count > 0 and loaded_card_count < expected_card_count:
        set_warning = (
            f"Das Set '{card_set.name}' ist laut Katalog unvollständig geladen ({loaded_card_count}/{expected_card_count} Karten). "
            "Die gewählten Karten wurden trotzdem gespeichert."
        )

    selected_quantities: dict[int, int] = {}
    for item in payload.items:
        if item.quantity <= 0:
            continue
        selected_quantities[item.card_print_id] = selected_quantities.get(item.card_print_id, 0) + item.quantity

    if not selected_quantities:
        raise ValueError("Bitte mindestens eine Karte mit Menge > 0 auswählen.")

    selected_print_ids = list(selected_quantities.keys())
    print_result = await db.execute(
        select(CardPrint).where(
            CardPrint.id.in_(selected_print_ids),
            CardPrint.set_id == payload.set_id,
        )
    )
    card_prints = print_result.scalars().all()
    prints_by_id = {card_print.id: card_print for card_print in card_prints}

    missing_ids = sorted(set(selected_print_ids) - set(prints_by_id))
    if missing_ids:
        raise ValueError("Mindestens eine ausgewählte Karte gehört nicht zum Set.")

    language_mismatches = sorted(card_print.id for card_print in card_prints if (card_print.language or "").lower() != requested_language)
    if language_mismatches:
        raise ValueError(
            f"Die ausgewählte Sprache '{requested_language.upper()}' passt nicht zu mindestens einem Print. "
            "Bitte Kartenliste in derselben Sprache laden und erneut auswählen."
        )

    mapping_result = await db.execute(
        select(SourceMapping).where(
            SourceMapping.target_type == "card_print",
            SourceMapping.target_id.in_(selected_print_ids),
            SourceMapping.provider_key.in_(["ygoprodeck", "cardmarket"]),
        )
    )
    mappings_by_print: dict[int, dict[str, SourceMapping]] = {}
    for mapping in mapping_result.scalars().all():
        provider_bucket = mappings_by_print.setdefault(mapping.target_id, {})
        provider_bucket.setdefault(mapping.provider_key, mapping)

    price_snapshot_result = await db.execute(
        select(
            InventoryItem.card_print_id,
            InventoryItem.current_market_price,
            InventoryItem.current_price_currency,
            InventoryItem.last_price_source,
        )
        .where(
            InventoryItem.card_print_id.in_(selected_print_ids),
            InventoryItem.current_market_price > 0,
        )
        .order_by(
            InventoryItem.card_print_id.asc(),
            InventoryItem.last_priced_at.desc().nullslast(),
            InventoryItem.updated_at.desc(),
        )
    )
    price_snapshot_by_print: dict[int, tuple[float | None, str, str | None]] = {}
    for card_print_id, price, currency, last_price_source in price_snapshot_result.all():
        if card_print_id in price_snapshot_by_print:
            continue
        positive_price = parse_positive_price(price)
        if positive_price is None:
            continue
        price_snapshot_by_print[card_print_id] = (
            positive_price,
            currency or payload.currency,
            last_price_source or "inventory:existing",
        )

    market_prices: dict[int, tuple[float | None, str, str | None]] = {}
    for card_print_id in selected_print_ids:
        market_price, market_currency, market_source = price_snapshot_by_print.get(card_print_id, (None, payload.currency, None))
        if market_price is None:
            ygoprodeck_mapping = mappings_by_print.get(card_print_id, {}).get("ygoprodeck")
            set_price = parse_positive_price((ygoprodeck_mapping.payload or {}).get("set_price")) if ygoprodeck_mapping else None
            if set_price is not None:
                market_price, market_currency, market_source = set_price, "USD", "ygoprodeck:set_price"
        market_prices[card_print_id] = (market_price, market_currency, market_source)

    ordered_lines = [(card_print_id, selected_quantities[card_print_id]) for card_print_id in selected_print_ids]
    has_purchase_price = payload.display_total_price is not None and payload.display_total_price > 0
    display_total_price = _to_decimal_amount(payload.display_total_price)
    unit_weights = (
        await _market_value_weights(market_prices, currency=payload.currency)
        if payload.allocation_mode == "market_value"
        else None
    )
    allocations, average_unit_price, remainder_cents = _allocate_display_total(display_total_price, ordered_lines, unit_weights)
    if not has_purchase_price:
        average_unit_price = None
        remainder_cents = 0
    total_quantity = sum(line.quantity for line in allocations)
    total_allocated_price = sum((line.line_total for line in allocations), Decimal("0.00"))
    allocation_difference = (display_total_price - total_allocated_price).quantize(TWO_DP, rounding=ROUND_HALF_UP)
    normalized_notes = _normalize_note(payload.notes)
    now = utc_now()

    purchase_batch = PurchaseBatch(
        source_type="set_import",
        label=card_set.name,
        set_id=card_set.id,
        storage_location_id=payload.storage_location_id,
        language=requested_language,
        condition=payload.condition,
        total_price=display_total_price,
        currency=payload.currency,
        total_units=total_quantity,
        allocated_unit_price=average_unit_price,
        rounding_remainder_cents=remainder_cents,
        notes=normalized_notes,
        payload={
            "set_code": card_set.set_code,
            "expected_card_count": expected_card_count,
            "loaded_card_count": loaded_card_count,
            "requested_language": requested_language,
            "line_count": len(allocations),
            "display_total_price": _to_float(display_total_price) if has_purchase_price else None,
            "allocation_mode": payload.allocation_mode if has_purchase_price else None,
            "allocation_difference": _to_float(allocation_difference),
        },
    )
    db.add(purchase_batch)
    await db.flush()

    created_items = 0
    imported_inventory_item_ids: list[int] = []
    imported_card_print_ids: list[int] = []
    allocation_lines: list[dict[str, float | int | None]] = []
    for allocation in allocations:
        card_print = prints_by_id[allocation.card_print_id]
        mapping_bundle = mappings_by_print.get(card_print.id, {})
        cardmarket_mapping = mapping_bundle.get("cardmarket")
        market_price, market_currency, market_source = market_prices[card_print.id]

        initial_match_quality = "exact" if market_source == "ygoprodeck:set_price" else "high_confidence" if market_price is not None else None
        initial_note = (
            "Print-spezifischer Snapshot aus dem lokalen Set-Mapping. Ein gezieltes Preisupdate wurde direkt nach dem Import angestossen."
            if market_price is not None
            else "Noch kein verlasslicher Marktpreis vorhanden. Direkt nach dem Import wird ein gezieltes Preisupdate gestartet."
        )

        inventory_item = InventoryItem(
            card_print_id=card_print.id,
            storage_location_id=payload.storage_location_id,
            purchase_batch_id=purchase_batch.id,
            condition=payload.condition,
            quantity=allocation.quantity,
            purchase_price=allocation.unit_price if has_purchase_price else None,
            allocated_purchase_total=allocation.line_total if has_purchase_price else None,
            current_market_price=market_price,
            current_price_currency=market_currency or payload.currency,
            last_price_source=market_source,
            last_priced_at=now if market_price is not None else None,
            last_price_match_quality=initial_match_quality,
            last_price_note=initial_note,
            cardmarket_reference=(cardmarket_mapping.external_url or cardmarket_mapping.external_id) if cardmarket_mapping else None,
            notes=normalized_notes,
        )
        db.add(inventory_item)
        await db.flush()
        await ensure_initial_price_monitor_state(db, inventory_item, now=now)
        created_items += 1
        imported_inventory_item_ids.append(inventory_item.id)
        imported_card_print_ids.append(card_print.id)
        allocation_lines.append(
            {
                "inventory_item_id": inventory_item.id,
                "card_print_id": card_print.id,
                "quantity": allocation.quantity,
                "allocated_purchase_price_per_unit": _to_float(allocation.unit_price) if has_purchase_price else None,
                "allocated_purchase_total": _to_float(allocation.line_total) or 0.0,
            }
        )

        db.add(
            PurchaseBatchItem(
                purchase_batch_id=purchase_batch.id,
                inventory_item_id=inventory_item.id,
                card_print_id=card_print.id,
                quantity=allocation.quantity,
                allocated_purchase_price_per_unit=allocation.unit_price if has_purchase_price else None,
                allocated_purchase_total=allocation.line_total,
            )
        )

        if market_price is not None:
            db.add(
                PriceHistory(
                    inventory_item_id=inventory_item.id,
                    card_print_id=card_print.id,
                    provider_key=market_source or "bulk-set-import",
                    metric="market",
                    currency=inventory_item.current_price_currency,
                    price=market_price,
                    payload={
                        "source": "bulk-set-import",
                        "set_id": payload.set_id,
                        "set_name": card_set.name,
                        "purchase_batch_id": purchase_batch.id,
                        "match_quality": initial_match_quality,
                        "note": initial_note,
                        "set_code": card_print.set_code,
                        "card_number": card_print.card_number,
                        "rarity": card_print.rarity,
                        "language": card_print.language,
                    },
                    captured_at=now,
                )
            )

    await db.flush()
    return BulkSetImportResponse(
        purchase_batch_id=purchase_batch.id,
        created_items=created_items,
        merged_items=0,
        imported_lines=len(allocations),
        total_quantity=total_quantity,
        imported_inventory_item_ids=imported_inventory_item_ids,
        imported_card_print_ids=imported_card_print_ids,
        display_total_price=_to_float(display_total_price) or 0.0,
        purchase_batch_total_price=_to_float(display_total_price) or 0.0,
        currency=payload.currency,
        allocated_unit_price=_to_float(average_unit_price),
        total_allocated_price=_to_float(total_allocated_price) or 0.0,
        allocation_difference=_to_float(allocation_difference) or 0.0,
        allocation_lines=allocation_lines,
        rounding_remainder_cents=remainder_cents,
        allocation_mode=payload.allocation_mode,
        warning=set_warning,
    )
