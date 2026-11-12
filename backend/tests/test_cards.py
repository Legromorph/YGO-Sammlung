from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

from app.models import InventoryItem
from app.schemas import CardPayload
from app.domain.print_codes import normalize_name
from app.services.card_common import (
    _is_exact_inventory_duplicate_candidate,
    _normalize_language_code,
    _normalize_tags,
    _validate_set_code_language,
)
from app.services.card_lookup import _fetch_remote_card_for_languages


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
    async def test_autofill_looks_up_the_card_in_the_preferred_language(self) -> None:
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
        )


class CardImageUrlTests(unittest.TestCase):
    def test_image_url_helpers_build_api_urls(self) -> None:
        from app.services.card_common import _placeholder_url, _remote_image_url

        self.assertEqual(_placeholder_url(7, "Dark"), "/api/assets/placeholder?item_id=7&label=Dark")
        self.assertTrue(
            (_remote_image_url({"card_images": [{"image_url_small": "https://img/x.jpg"}]}) or "").startswith("/api/assets/proxy?url=")
        )


class YgoProDeckRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_requests_never_send_the_rejected_tcgplayer_parameter(self) -> None:
        from unittest.mock import patch

        from app.integrations.card_data import YgoProDeckCardDataProvider

        provider = YgoProDeckCardDataProvider()
        sent_params: list[dict] = []

        async def fake_request(params: dict) -> list[dict]:
            sent_params.append(dict(params))
            return []

        with patch.object(provider, "_request", side_effect=fake_request):
            await provider.fetch_card(external_id="89631139")
            await provider.fetch_cards_for_set("Legend of Blue Eyes White Dragon")

        self.assertTrue(sent_params)
        self.assertTrue(all("tcgplayer_data" not in params for params in sent_params))
