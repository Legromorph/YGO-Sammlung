from __future__ import annotations

from decimal import Decimal
import json
import unittest

from app.models import Card, CardPrint, InventoryItem, StorageLocation
from app.services.exports import (
    build_collection_json_export,
    build_inventory_csv_export,
    json_safe,
    serialize_model,
)


class _ScalarResult:
    def __init__(self, values: list[object]) -> None:
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return self.values


class _JsonExportDb:
    async def execute(self, statement):
        entity = statement.column_descriptions[0]["entity"]
        if entity is Card:
            return _ScalarResult(
                [
                    Card(
                        id=1,
                        name="Book of Moon",
                        normalized_name="book of moon",
                        card_type="Spell Card",
                        card_kind="spell",
                    )
                ]
            )
        return _ScalarResult([])


class _CsvResult:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def all(self):
        return self.rows


class _CsvExportDb:
    async def execute(self, _statement):
        card = Card(
            id=1,
            name="Book of Moon",
            normalized_name="book of moon",
            card_kind="spell",
        )
        card_print = CardPrint(
            id=2,
            card_id=1,
            set_name="Starter Deck",
            set_code="SD-EN001",
            card_number="EN001",
            rarity="Common",
            language="en",
            cardmarket_product_url="https://www.cardmarket.com/en/YuGiOh/Products/Singles/A/B",
            cardmarket_match_quality="manual_verified",
        )
        item = InventoryItem(
            id=3,
            card_print_id=2,
            condition="near_mint",
            quantity=2,
            purchase_price=Decimal("1.2500"),
            current_market_price=Decimal("2.50"),
            current_price_currency="EUR",
            tags=["Zauber"],
        )
        location = StorageLocation(
            id=4,
            name="Ordner 1",
            location_type="binder",
            path_cache="Regal / Ordner 1",
        )
        return _CsvResult([(item, card_print, card, location)])


class ExportTests(unittest.IsolatedAsyncioTestCase):
    def test_json_safe_serializes_decimal_values(self) -> None:
        self.assertEqual(json_safe(Decimal("1.25")), 1.25)

    def test_model_serializer_uses_database_column_names(self) -> None:
        card = Card(
            id=1,
            name="Book of Moon",
            normalized_name="book of moon",
            card_kind="spell",
        )
        serialized = serialize_model(card)
        self.assertEqual(serialized["name"], "Book of Moon")
        self.assertEqual(serialized["card_kind"], "spell")

    async def test_json_export_is_versioned_and_serializable(self) -> None:
        export = await build_collection_json_export(_JsonExportDb())  # type: ignore[arg-type]

        self.assertEqual(export["schema"], "ygo-sammlung.collection-export")
        self.assertEqual(export["version"], 1)
        self.assertEqual(export["tables"]["cards"][0]["name"], "Book of Moon")
        json.dumps(export)

    async def test_csv_export_contains_inventory_totals_and_utf8_bom(self) -> None:
        export = await build_inventory_csv_export(_CsvExportDb())  # type: ignore[arg-type]

        self.assertTrue(export.startswith("\ufeff"))
        self.assertIn("Book of Moon", export)
        self.assertIn("Regal / Ordner 1", export)
        self.assertIn("5.0", export)


if __name__ == "__main__":
    unittest.main()
