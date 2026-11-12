from __future__ import annotations

from decimal import Decimal
import unittest

from app.services.inventory import _allocate_display_total


class DisplayAllocationTests(unittest.TestCase):
    def test_even_split_adds_up_to_the_cent(self) -> None:
        lines, average, _ = _allocate_display_total(Decimal("100.00"), [(1, 1), (2, 1), (3, 1)])

        self.assertEqual(sum(line.line_total for line in lines), Decimal("100.00"))
        self.assertEqual(average, Decimal("33.3333"))
        self.assertEqual(sorted(line.line_total for line in lines), [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")])

    def test_market_value_split_follows_card_value(self) -> None:
        lines, _, _ = _allocate_display_total(
            Decimal("90.00"),
            [(1, 1), (2, 2)],
            {1: Decimal("40"), 2: Decimal("5")},
        )
        by_print = {line.card_print_id: line for line in lines}

        self.assertEqual(by_print[1].line_total, Decimal("72.00"))
        self.assertEqual(by_print[2].line_total, Decimal("18.00"))
        self.assertEqual(by_print[2].unit_price, Decimal("9.0000"))

    def test_zero_weights_fall_back_to_even_split(self) -> None:
        lines, _, _ = _allocate_display_total(Decimal("10.00"), [(1, 1), (2, 1)], {1: Decimal("0"), 2: Decimal("0")})

        self.assertEqual([line.line_total for line in lines], [Decimal("5.00"), Decimal("5.00")])

    def test_no_lines_returns_nothing(self) -> None:
        self.assertEqual(_allocate_display_total(Decimal("10.00"), []), ([], None, 0))
