from __future__ import annotations

import unittest

from app.domain.print_codes import (
    card_number_language_neutral,
    derive_card_number,
    derive_print_language,
    set_codes_match_language_neutral,
)


class PrintCodeTests(unittest.TestCase):
    def test_card_number_and_language_are_derived_from_set_code(self) -> None:
        self.assertEqual(derive_card_number("RA05-DE080"), "DE080")
        self.assertIsNone(derive_card_number("RA05"))
        self.assertEqual(derive_print_language("RA05-DE080"), "de")
        self.assertEqual(derive_print_language("RA05-SP080"), "es")
        self.assertEqual(derive_print_language("RA05-KR080"), "ko")
        self.assertEqual(derive_print_language("LOB-001"), "en")

    def test_language_variants_of_the_same_print_match(self) -> None:
        self.assertTrue(set_codes_match_language_neutral("RA05-DE080", "RA05-EN080"))
        self.assertFalse(set_codes_match_language_neutral("RA05-DE080", "RA05-EN081"))
        self.assertFalse(set_codes_match_language_neutral("RA05-DE080", "RA04-EN080"))

    def test_letter_suffixes_after_the_language_prefix_stay_distinct(self) -> None:
        self.assertTrue(set_codes_match_language_neutral("CT13-DEV01", "CT13-ENV01"))
        self.assertFalse(set_codes_match_language_neutral("CT13-ENV01", "CT13-ENS01"))

    def test_card_numbers_compare_without_language_prefix(self) -> None:
        self.assertEqual(card_number_language_neutral("DE080"), card_number_language_neutral("EN080"))
