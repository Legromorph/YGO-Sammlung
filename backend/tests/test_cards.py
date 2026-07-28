from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from app.models import InventoryItem
from app.schemas import CardPayload
from app.services.cards import (
    _fetch_remote_card_for_languages,
    _is_exact_inventory_duplicate_candidate,
    _normalize_language_code,
    _normalize_tags,
    _validate_set_code_language,
    normalize_name,
)


class CardManagementTests(unittest.TestCase):
    def test_names_and_tags_are_normalized_consistently(self) -> None:
        self.assertEqual(normalize_name("  Dark   Magician  "), "dark magician")
        self.assertEqual(_normalize_tags([" Zauber ", "zauber", "", "Sammlung"]), ["sammlung", "zauber"])

    def test_language_codes_and_set_codes_are_validated(self) -> None:
        self.assertEqual(_normalize_language_code(" DE "), "de")
        self.assertIsNone(_validate_set_code_language("de", "RA05-DE080"))
        with self.assertRaises(ValueError):
            _validate_set_code_language("de", "RA05-EN080")

    def test_duplicate_detection_includes_purchase_data_notes_and_tags(self) -> None:
        item = InventoryItem(
            card_print_id=1,
            purchase_price=1.25,
            notes="Tausch",
            tags=["Ordner"],
        )
        payload = CardPayload(
            name="Book of Moon",
            condition="near_mint",
            quantity=1,
            purchase_price=1.25,
            notes="Tausch",
            tags=["Ordner"],
        )

        self.assertTrue(_is_exact_inventory_duplicate_candidate(item, payload=payload))


class CardLookupTests(unittest.IsolatedAsyncioTestCase):
    async def test_autofill_requests_print_specific_tcgplayer_data(self) -> None:
        provider = SimpleNamespace(
            fetch_card=AsyncMock(return_value={"external_id": "95365081"}),
        )

        result, language = await _fetch_remote_card_for_languages(
            provider,
            external_id="95365081",
            language="de,en",
        )

        self.assertEqual(result, {"external_id": "95365081"})
        self.assertEqual(language, "de")
        provider.fetch_card.assert_awaited_once_with(
            name=None,
            external_id="95365081",
            language="de",
            tcgplayer_data=True,
        )


if __name__ == "__main__":
    unittest.main()
