from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AppSetting,
    Card,
    CardPrint,
    CardSet,
    Collection,
    CollectionCard,
    Deck,
    DeckCard,
    ImageAsset,
    InventoryItem,
    PriceHistory,
    PurchaseBatch,
    PurchaseBatchItem,
    PriceMonitorState,
    SourceMapping,
    StorageLocation,
)
from app.time_utils import utc_now


EXPORT_MODELS = (
    AppSetting,
    Card,
    CardSet,
    CardPrint,
    StorageLocation,
    InventoryItem,
    PurchaseBatch,
    PurchaseBatchItem,
    PriceHistory,
    Deck,
    DeckCard,
    Collection,
    CollectionCard,
    ImageAsset,
    SourceMapping,
    PriceMonitorState,
)


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def serialize_model(instance: Any) -> dict[str, Any]:
    return {
        column.name: json_safe(getattr(instance, column.name))
        for column in instance.__table__.columns
    }


async def build_collection_json_export(db: AsyncSession) -> dict[str, Any]:
    tables: dict[str, list[dict[str, Any]]] = {}
    for model in EXPORT_MODELS:
        result = await db.execute(select(model).order_by(model.id.asc()))
        tables[model.__tablename__] = [serialize_model(item) for item in result.scalars().all()]

    return {
        "schema": "ygo-sammlung.collection-export",
        "version": 1,
        "generated_at": utc_now().isoformat(),
        "tables": tables,
    }


def _csv_value(value: Any) -> str | int | float:
    converted = json_safe(value)
    if converted is None:
        return ""
    if isinstance(converted, (dict, list)):
        return json.dumps(converted, ensure_ascii=False, separators=(",", ":"))
    return converted


async def build_inventory_csv_export(db: AsyncSession) -> str:
    result = await db.execute(
        select(InventoryItem, CardPrint, Card, StorageLocation)
        .join(CardPrint, InventoryItem.card_print_id == CardPrint.id)
        .join(Card, CardPrint.card_id == Card.id)
        .outerjoin(StorageLocation, InventoryItem.storage_location_id == StorageLocation.id)
        .order_by(Card.name.asc(), CardPrint.set_code.asc(), InventoryItem.id.asc())
    )

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        (
            "Inventar-ID",
            "Karte",
            "Kartenart",
            "Set",
            "Setcode",
            "Kartennummer",
            "Seltenheit",
            "Sprache",
            "Zustand",
            "Menge",
            "Kaufpreis pro Karte",
            "Kaufpreis gesamt",
            "Marktpreis pro Karte",
            "Marktwert gesamt",
            "Währung",
            "Lagerort",
            "Cardmarket-Link",
            "Linkstatus",
            "Preisquelle",
            "Preis aktualisiert",
            "Notizen",
            "Tags",
        )
    )

    for item, card_print, card, storage_location in result.all():
        market_total = (
            Decimal(str(item.current_market_price)) * item.quantity
            if item.current_market_price is not None
            else None
        )
        storage_path = (
            storage_location.path_cache or storage_location.name
            if storage_location
            else None
        )
        writer.writerow(
            tuple(
                _csv_value(value)
                for value in (
                    item.id,
                    card.name,
                    card.card_kind,
                    card_print.set_name,
                    card_print.set_code,
                    card_print.card_number,
                    card_print.rarity,
                    card_print.language,
                    item.condition,
                    item.quantity,
                    item.purchase_price,
                    item.allocated_purchase_total,
                    item.current_market_price,
                    market_total,
                    item.current_price_currency,
                    storage_path,
                    card_print.cardmarket_product_url or item.cardmarket_reference,
                    card_print.cardmarket_match_quality,
                    item.last_price_source,
                    item.last_priced_at,
                    item.notes,
                    item.tags,
                )
            )
        )

    return "\ufeff" + output.getvalue()
