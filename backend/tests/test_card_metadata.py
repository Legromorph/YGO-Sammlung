from __future__ import annotations

import unittest

from app.domain.card_metadata import (
    ALLOWED_METADATA_FIELDS_BY_KIND,
    CanonicalCardKind,
    normalize_card_metadata,
)
from app.integrations.card_data import YgoProDeckCardDataProvider
from app.models import Card, InventoryItem, PriceHistory
from app.time_utils import utc_now


class CardDataNormalizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.provider = YgoProDeckCardDataProvider()

    def test_quick_play_is_a_canonical_spell_type(self) -> None:
        normalized = self.provider._normalize_card(
            {
                "id": 1,
                "name": "Book of Moon",
                "type": "Spell Card",
                "frameType": "spell",
                "race": "Quick-Play",
                "attribute": "SPELL",
                "atk": 999,
            }
        )

        self.assertEqual(normalized["card_kind"], "spell")
        self.assertEqual(normalized["spell_trap_type"], "quick_play")
        self.assertIsNone(normalized["monster_type"])
        self.assertIsNone(normalized["attribute"])
        self.assertIsNone(normalized["atk"])

    def test_monster_race_remains_the_monster_type(self) -> None:
        normalized = self.provider._normalize_card(
            {
                "id": 2,
                "name": "Dark Magician",
                "type": "Normal Monster",
                "frameType": "normal",
                "race": "Spellcaster",
                "attribute": "DARK",
                "atk": 2500,
            }
        )

        self.assertEqual(normalized["card_kind"], "monster")
        self.assertEqual(normalized["monster_type"], "Spellcaster")
        self.assertIsNone(normalized["spell_trap_type"])
        self.assertEqual(normalized["attribute"], "DARK")
        self.assertEqual(normalized["atk"], 2500)

    def test_link_monster_removes_defense_and_level(self) -> None:
        normalized = normalize_card_metadata(
            card_type="Link Monster",
            frame_type="link",
            race="Cyberse",
            atk=2300,
            defense=1200,
            level=4,
            link_rating=3,
            link_arrows=["Top", "Bottom-Left"],
        )

        self.assertEqual(normalized.card_kind, CanonicalCardKind.MONSTER)
        self.assertEqual(normalized.link_rating, 3)
        self.assertEqual(normalized.link_arrows, ["Top", "Bottom-Left"])
        self.assertIsNone(normalized.defense)
        self.assertIsNone(normalized.level)

    def test_xyz_uses_rank_instead_of_level(self) -> None:
        normalized = normalize_card_metadata(
            card_type="XYZ Monster",
            frame_type="xyz",
            level=7,
            rank=4,
        )

        self.assertEqual(normalized.rank, 4)
        self.assertIsNone(normalized.level)

    def test_allowed_fields_are_centralized_by_card_kind(self) -> None:
        self.assertIn("atk", ALLOWED_METADATA_FIELDS_BY_KIND[CanonicalCardKind.MONSTER])
        self.assertNotIn("atk", ALLOWED_METADATA_FIELDS_BY_KIND[CanonicalCardKind.SPELL])
        self.assertIn("spell_trap_type", ALLOWED_METADATA_FIELDS_BY_KIND[CanonicalCardKind.SPELL])


class TimeAndConstraintTests(unittest.TestCase):
    def test_utc_now_is_timezone_aware(self) -> None:
        now = utc_now()
        self.assertIsNotNone(now.tzinfo)
        self.assertEqual(now.utcoffset().total_seconds(), 0)

    def test_integrity_constraints_are_declared_on_models(self) -> None:
        card_constraints = {constraint.name for constraint in Card.__table__.constraints}
        inventory_constraints = {constraint.name for constraint in InventoryItem.__table__.constraints}
        history_constraints = {constraint.name for constraint in PriceHistory.__table__.constraints}

        self.assertIn("ck_cards_card_kind", card_constraints)
        self.assertIn("ck_inventory_items_quantity_positive", inventory_constraints)
        self.assertIn("ck_inventory_items_market_price_positive", inventory_constraints)
        self.assertIn("ck_price_history_price_positive", history_constraints)


if __name__ == "__main__":
    unittest.main()
