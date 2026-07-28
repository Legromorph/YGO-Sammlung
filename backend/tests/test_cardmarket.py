from __future__ import annotations

from types import SimpleNamespace
import unittest

from app.integrations.cardmarket.product_resolver import CardmarketProductResolver
from app.integrations.cardmarket.product_url_builder import (
    CARDMARKET_MATCH_AMBIGUOUS,
    CARDMARKET_MATCH_MANUAL,
    CardmarketProductUrlBuilder,
)
from app.integrations.cardmarket.set_slug_resolver import (
    CardmarketSetSlugCandidate,
    CardmarketSetSlugResolver,
)
from app.integrations.cardmarket.types import CardmarketPrintContext
from app.integrations.cardmarket.url_builder import (
    normalize_cardmarket_product_url,
    resolve_cardmarket_product_url,
)
from app.models import Card, CardPrint, InventoryItem
from app.schemas import CardPayload, CardmarketLinkPayload
from app.services.cards import (
    _card_set_lookup_codes,
    _cardmarket_variant_count_for_remote_card,
    _find_local_cardmarket_references,
    _resolve_cardmarket_link,
    update_cardmarket_link,
)


class CardmarketUrlTests(unittest.TestCase):
    def test_language_specific_print_code_includes_set_family_lookup(self) -> None:
        self.assertEqual(_card_set_lookup_codes("MP25-DE006"), ["MP25-DE006", "MP25"])

    def test_2025_mega_pack_uses_the_cardmarket_tin_slug(self) -> None:
        candidates = CardmarketSetSlugResolver().resolve_candidates(
            set_name="2025 Mega-Pack",
            set_code="MP25-DE006",
        )

        self.assertEqual(candidates[0].slug, "2025-Mega-Pack-Tin")
        self.assertTrue(candidates[0].verified)

    def test_set_name_is_preserved_for_card_autofill(self) -> None:
        resolution = resolve_cardmarket_product_url(
            locale="en",
            cardmarket_set_slug="OTS-Tournament-Pack-28",
            cardmarket_set_name="OTS Tournament Pack 28",
            cardmarket_product_name="Chamber Dragonmaid",
            card_name="Chamber Dragonmaid",
            allow_fallback=False,
        )

        self.assertEqual(resolution.set_name, "OTS Tournament Pack 28")
        self.assertEqual(resolution.set_slug, "OTS-Tournament-Pack-28")
        self.assertIsNotNone(resolution.url)

    def test_multiple_print_candidates_include_v_number_and_english_rarity(self) -> None:
        builder = CardmarketProductUrlBuilder(variant_probe_limit=12)
        candidates = builder.build_candidate_urls(
            set_name="Rarity Collection 5",
            set_slug_candidates=[
                CardmarketSetSlugCandidate(
                    slug="Rarity-Collection-5",
                    source="test",
                    verified=True,
                )
            ],
            product_name="Dominus Impulse",
            rarity="Platinum Secret Rare",
            variant_count=6,
        )

        self.assertEqual(
            [candidate.url for candidate in candidates[:4]],
            [
                "https://www.cardmarket.com/en/YuGiOh/Products/Singles/Rarity-Collection-5/Dominus-Impulse-V1-Platinum-Secret-Rare",
                "https://www.cardmarket.com/en/YuGiOh/Products/Singles/Rarity-Collection-5/Dominus-Impulse-V2-Platinum-Secret-Rare",
                "https://www.cardmarket.com/en/YuGiOh/Products/Singles/Rarity-Collection-5/Dominus-Impulse-V3-Platinum-Secret-Rare",
                "https://www.cardmarket.com/en/YuGiOh/Products/Singles/Rarity-Collection-5/Dominus-Impulse-V4-Platinum-Secret-Rare",
            ],
        )
        self.assertIn("Dominus-Impulse-V12-Platinum-Secret-Rare", candidates[11].url)

    def test_apostrophes_do_not_create_an_extra_hyphen(self) -> None:
        builder = CardmarketProductUrlBuilder()
        self.assertEqual(builder.slugify_segment("Collector's Rare"), "Collectors-Rare")
        self.assertEqual(builder.slugify_segment("Magician's Souls"), "Magicians-Souls")

    def test_language_equivalent_set_codes_count_all_variants(self) -> None:
        remote_card = {
            "card_sets": [
                {
                    "set_code": "RA05-EN080",
                    "set_name": "Rarity Collection 5",
                    "set_rarity": rarity,
                }
                for rarity in (
                    "Collector's Rare",
                    "Platinum Secret Rare",
                    "Secret Rare",
                    "Super Rare",
                    "Ultimate Rare",
                    "Ultra Rare",
                )
            ]
        }

        self.assertEqual(
            _cardmarket_variant_count_for_remote_card(
                remote_card,
                set_code="RA05-DE080",
                set_name="Rarity Collection 5",
            ),
            6,
        )

    def test_confirmed_german_link_is_reused_for_equivalent_print_code(self) -> None:
        expected = {
            "url": (
                "https://www.cardmarket.com/en/YuGiOh/Products/Singles/"
                "Rarity-Collection-5/Dominus-Impulse-V4-Platinum-Secret-Rare"
            )
        }
        references = {
            ("RA05-DE080", "EN080", "Platinum Secret Rare", "de"): [expected],
        }

        result = _find_local_cardmarket_references(
            references,
            set_code="RA05-EN080",
            card_number="EN080",
            rarity="Platinum Secret Rare",
            language="en",
        )
        self.assertEqual(result, [expected])

    def test_deceptive_cardmarket_hostname_is_rejected(self) -> None:
        self.assertIsNone(
            normalize_cardmarket_product_url(
                "https://www.cardmarket.com.evil.example/en/YuGiOh/Products/Singles/A/B"
            )
        )


class CardmarketManualResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_generated_candidate_requires_manual_confirmation(self) -> None:
        resolver = CardmarketProductResolver()
        resolver.set_slug_resolver = SimpleNamespace(
            resolve_candidates=lambda **_: [
                CardmarketSetSlugCandidate(
                    slug="Burst-Protocol",
                    source="test",
                    verified=True,
                )
            ]
        )
        context = CardmarketPrintContext(
            product_name="Artmage Non-Finito",
            set_name="Burst Protocol",
            set_code="BPRO-EN035",
            rarity="Ultra Rare",
            card_number="EN035",
            language="en",
            variant_count=2,
        )

        result = await resolver.resolve(context)

        self.assertEqual(
            result.url,
            (
                "https://www.cardmarket.com/en/YuGiOh/Products/Singles/"
                "Burst-Protocol/Artmage-Non-Finito-V1-Ultra-Rare"
            ),
        )
        self.assertEqual(result.match_quality, CARDMARKET_MATCH_AMBIGUOUS)
        self.assertEqual(result.variant_name, "V1")
        self.assertEqual(result.parse_status, "manual_confirmation_required")
        self.assertIsNone(result.verified_at)
        self.assertEqual(result.diagnostics["mode"], "manual_only")

    async def test_existing_url_is_kept_but_not_automatically_confirmed(self) -> None:
        url = (
            "https://www.cardmarket.com/en/YuGiOh/Products/Singles/"
            "Rarity-Collection-5/Dominus-Impulse-V4-Platinum-Secret-Rare"
        )
        result = await CardmarketProductResolver().resolve(
            CardmarketPrintContext(
                product_name="Dominus Impulse",
                set_name="Rarity Collection 5",
                set_code="RA05-DE080",
                rarity="Platinum Secret Rare",
                card_number="DE080",
                language="de",
                existing_product_url=url,
            )
        )

        self.assertEqual(result.url, url)
        self.assertEqual(result.match_quality, CARDMARKET_MATCH_AMBIGUOUS)
        self.assertIsNone(result.verified_at)


class _EmptyScalars:
    def all(self) -> list[object]:
        return []

    def first(self) -> None:
        return None


class _EmptyResult:
    def scalars(self) -> _EmptyScalars:
        return _EmptyScalars()


class _CardmarketLinkTestDb:
    def __init__(self, item: InventoryItem) -> None:
        self.item = item
        self.added: list[object] = []

    async def get(self, _model, _identifier, **_kwargs):
        return self.item

    async def execute(self, _statement):
        return _EmptyResult()

    def add(self, value: object) -> None:
        self.added.append(value)

    async def delete(self, _value: object) -> None:
        return None

    async def flush(self) -> None:
        return None


class CardmarketLinkStorageTests(unittest.IsolatedAsyncioTestCase):
    def _item(self) -> InventoryItem:
        card = Card(name="Artmage Non-Finito", normalized_name="artmage non-finito")
        card_print = CardPrint(
            id=13,
            card_id=1,
            set_name="Burst Protocol",
            set_code="BPRO-EN035",
            rarity="Ultra Rare",
            language="en",
        )
        card_print.card = card
        item = InventoryItem(id=21, card_print_id=13)
        item.card_print = card_print
        return item

    def test_unclassified_stored_link_stays_unconfirmed(self) -> None:
        item = self._item()
        item.card_print.cardmarket_product_url = (
            "https://www.cardmarket.com/en/YuGiOh/Products/Singles/"
            "Burst-Protocol/Artmage-Non-Finito-V1-Ultra-Rare"
        )

        url, quality = _resolve_cardmarket_link(item, [], None)

        self.assertIsNotNone(url)
        self.assertEqual(quality, CARDMARKET_MATCH_AMBIGUOUS)

    def test_confirmation_payload_defaults_to_unconfirmed(self) -> None:
        url = "https://www.cardmarket.com/en/YuGiOh/Products/Singles/A/B"
        self.assertFalse(CardmarketLinkPayload(url=url).confirmed)
        self.assertTrue(CardmarketLinkPayload(url=url, confirmed=True).confirmed)

    def test_general_card_payload_cannot_claim_a_verified_link(self) -> None:
        self.assertNotIn("cardmarket_match_quality", CardPayload.model_fields)
        self.assertNotIn("cardmarket_verified_at", CardPayload.model_fields)

    async def test_saving_and_confirming_are_separate_actions(self) -> None:
        url = (
            "https://www.cardmarket.com/en/YuGiOh/Products/Singles/"
            "Burst-Protocol/Artmage-Non-Finito-V1-Ultra-Rare"
        )
        item = self._item()
        db = _CardmarketLinkTestDb(item)

        await update_cardmarket_link(db, item.id, url, confirmed=False)  # type: ignore[arg-type]
        self.assertEqual(item.card_print.cardmarket_match_quality, CARDMARKET_MATCH_AMBIGUOUS)
        self.assertIsNone(item.card_print.cardmarket_verified_at)

        await update_cardmarket_link(db, item.id, url, confirmed=True)  # type: ignore[arg-type]
        self.assertEqual(item.card_print.cardmarket_match_quality, CARDMARKET_MATCH_MANUAL)
        self.assertIsNotNone(item.card_print.cardmarket_verified_at)
        self.assertIsNotNone(item.card_print.cardmarket_verified_at.tzinfo)


if __name__ == "__main__":
    unittest.main()
