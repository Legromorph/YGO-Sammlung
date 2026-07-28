from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from app.integrations.price_values import parse_localized_price, parse_positive_price
from app.integrations.prices import (
    PRICE_MATCH_FALLBACK_NAME_ONLY,
    CardmarketPriceProvider,
    YgoProDeckPriceProvider,
    _match_remote_print,
)
from app.models import Card, CardPrint, PriceHistory, SourceMapping
from app.services.price_monitor import _recent_price_samples
from app.time_utils import utc_now


class PriceValueTests(unittest.TestCase):
    def test_positive_prices_reject_zero_negative_and_non_finite_values(self) -> None:
        self.assertIsNone(parse_positive_price(None))
        self.assertIsNone(parse_positive_price("0"))
        self.assertIsNone(parse_positive_price("-1.25"))
        self.assertIsNone(parse_positive_price("nan"))
        self.assertIsNone(parse_positive_price("inf"))
        self.assertEqual(parse_positive_price("3.72"), 3.72)

    def test_localized_prices_support_german_and_english_thousands(self) -> None:
        self.assertEqual(parse_localized_price("1.234,56 EUR"), 1234.56)
        self.assertEqual(parse_localized_price("EUR 1,234.56"), 1234.56)
        self.assertEqual(parse_localized_price("0,73 EUR"), 0.73)


class CardmarketManualPriceProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_never_fetches_a_public_page(self) -> None:
        card = Card(name="Book of Moon", normalized_name="book of moon")
        card_print = CardPrint(card_id=1, language="de")
        url = "https://www.cardmarket.com/en/YuGiOh/Products/Singles/A/B"

        snapshot = await CardmarketPriceProvider().fetch_price(
            card,
            card_print,
            "near_mint",
            cardmarket_reference=url,
        )

        self.assertIsNone(snapshot.market_price)
        self.assertEqual(snapshot.source_key, "cardmarket:manual_only")
        self.assertEqual(snapshot.indicators["parse_status"], "manual_only")
        self.assertEqual(snapshot.cardmarket_reference, url)


class YgoProDeckPriceProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.card = Card(name="Invoked Magistus Omega", normalized_name="invoked magistus omega")
        self.card_print = CardPrint(
            id=22,
            card_id=1,
            set_name="Burst Protocol",
            set_code="BPRO-EN100",
            card_number="EN100",
            rarity="Ultra Rare",
            language="en",
        )
        self.mapping = SourceMapping(
            target_type="card_print",
            target_id=22,
            provider_key="ygoprodeck",
            external_id="38423248",
        )

    async def test_uses_positive_exact_print_price_from_tcgplayer_dataset(self) -> None:
        remote_card = {
            "external_id": "38423248",
            "card_sets": [
                {
                    "set_name": "Burst Protocol",
                    "set_code": "BPRO-EN100",
                    "set_rarity": "Ultra Rare",
                    "set_price": "3.72",
                    "set_price_low": "1.42",
                    "set_url": "https://example.test/print",
                }
            ],
            "prices": {"cardmarket_price": "0.73"},
        }
        data_provider = SimpleNamespace(
            provider_key="ygoprodeck",
            fetch_card=AsyncMock(return_value=remote_card),
        )

        with patch("app.integrations.prices.get_card_data_provider", return_value=data_provider):
            snapshot = await YgoProDeckPriceProvider().fetch_price(
                self.card,
                self.card_print,
                "near_mint",
                print_mapping=self.mapping,
            )

        self.assertEqual(snapshot.market_price, 3.72)
        self.assertEqual(snapshot.currency, "USD")
        self.assertEqual(snapshot.source_key, "ygoprodeck:tcgplayer_set_price")
        self.assertEqual(snapshot.indicators["pricing_strategy_used"], "exact_print_tcgplayer_market")
        data_provider.fetch_card.assert_awaited_once_with(
            external_id="38423248",
            name=self.card.name,
            language=None,
            tcgplayer_data=True,
        )

    async def test_zero_exact_price_uses_labeled_card_level_fallback(self) -> None:
        remote_card = {
            "external_id": "38423248",
            "card_sets": [
                {
                    "set_name": "Burst Protocol",
                    "set_code": "BPRO-EN100",
                    "set_rarity": "Ultra Rare",
                    "set_price": "0",
                }
            ],
            "prices": {"cardmarket_price": "0.73"},
        }
        data_provider = SimpleNamespace(
            provider_key="ygoprodeck",
            fetch_card=AsyncMock(return_value=remote_card),
        )

        with patch("app.integrations.prices.get_card_data_provider", return_value=data_provider):
            snapshot = await YgoProDeckPriceProvider().fetch_price(
                self.card,
                self.card_print,
                "near_mint",
                print_mapping=self.mapping,
            )

        self.assertEqual(snapshot.market_price, 0.73)
        self.assertEqual(snapshot.currency, "EUR")
        self.assertEqual(snapshot.match_quality, PRICE_MATCH_FALLBACK_NAME_ONLY)
        self.assertTrue(snapshot.indicators["requires_review"])

    async def test_batch_prefetch_reuses_one_set_response(self) -> None:
        remote_card = {
            "external_id": "38423248",
            "name": self.card.name,
            "card_sets": [
                {
                    "set_name": "Burst Protocol",
                    "set_code": "BPRO-EN100",
                    "set_rarity": "Ultra Rare",
                    "set_price": "3.72",
                }
            ],
            "prices": {"cardmarket_price": "0.73"},
        }
        data_provider = SimpleNamespace(
            provider_key="ygoprodeck",
            fetch_cards_for_set=AsyncMock(return_value=[remote_card]),
            fetch_card=AsyncMock(return_value=None),
        )
        item = SimpleNamespace(card_print=SimpleNamespace(set_name="Burst Protocol"))
        provider = YgoProDeckPriceProvider()

        with patch("app.integrations.prices.get_card_data_provider", return_value=data_provider):
            summary = await provider.prepare_price_run(
                [
                    (item, None, self.mapping, None),
                    (item, None, self.mapping, None),
                ]
            )
            snapshot = await provider.fetch_price(
                self.card,
                self.card_print,
                "near_mint",
                print_mapping=self.mapping,
            )

        self.assertEqual(summary, {"requested_sets": 1, "loaded_sets": 1, "cached_cards": 1})
        self.assertEqual(snapshot.market_price, 3.72)
        self.assertEqual(snapshot.indicators["provider_lookup_mode"], "prefetched_set")
        data_provider.fetch_cards_for_set.assert_awaited_once_with(
            "Burst Protocol",
            tcgplayer_data=True,
        )
        data_provider.fetch_card.assert_not_awaited()

    def test_matches_language_equivalent_print_codes(self) -> None:
        german_print = CardPrint(
            set_code="BLZD-DE027",
            card_number="027",
            rarity="Secret Rare",
            language="de",
        )

        self.assertTrue(
            _match_remote_print(
                german_print,
                {
                    "set_code": "BLZD-EN027",
                    "set_rarity": "Secret Rare",
                },
            )
        )


class PriceMonitorSampleTests(unittest.TestCase):
    def test_samples_are_newest_first_and_do_not_mix_currencies_or_zeroes(self) -> None:
        now = utc_now()
        history = [
            PriceHistory(price=5, currency="USD", captured_at=now - timedelta(hours=3)),
            PriceHistory(price=0, currency="EUR", captured_at=now - timedelta(hours=1)),
            PriceHistory(price=2, currency="EUR", captured_at=now - timedelta(hours=2)),
            PriceHistory(price=3, currency="EUR", captured_at=now - timedelta(minutes=30)),
        ]

        samples = _recent_price_samples(
            history,
            current_price=4,
            current_currency="EUR",
            checked_at=now,
        )

        self.assertEqual([sample[1] for sample in samples], [4, 3, 2])
        self.assertTrue(all(sample[2] == "EUR" for sample in samples))


if __name__ == "__main__":
    unittest.main()
