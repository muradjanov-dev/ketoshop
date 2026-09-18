"""Foyda hisobi — bitta tannarx qoidasi (database.line_cost) va dollar kursi."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
import targets

COSTS = {10: 40_000, 20: 0}
SET_COSTS = {7: 95_000}


class LineCostTest(unittest.TestCase):
    def test_product_line(self):
        self.assertEqual(database.line_cost({"product_id": 10, "quantity": 2}, COSTS, SET_COSTS), (80_000, True))

    def test_set_line_is_costed_from_its_components(self):
        line = {"is_set": True, "set_id": 7, "product_id": None, "quantity": 2, "price": 150_000}
        self.assertEqual(database.line_cost(line, COSTS, SET_COSTS), (190_000, True))

    def test_gift_costs_nothing_here(self):
        # Booked in Chiqimlar instead — must not be charged twice.
        self.assertEqual(database.line_cost({"product_id": 10, "quantity": 1, "is_gift": True, "is_bonus": True},
                                            COSTS, SET_COSTS), (0, True))

    def test_bonus_line_by_stock_quantity(self):
        line = {"product_id": 10, "quantity": 100, "stock_quantity": 0.1, "is_bonus": True}
        cost, known = database.line_cost(line, COSTS, SET_COSTS)
        self.assertAlmostEqual(cost, 4_000)
        self.assertTrue(known)

    def test_line_carrying_its_own_cost_price_is_costed_by_it(self):
        # B2B Eritritol: sold by the kilo out of a wholesale sack, and the
        # catalog only has 100gr/500gr packs, so the line keeps its own cost.
        line = {"name": "Eritritol (B2B)", "quantity": 12, "cost_price": 30_000, "unit": "kg"}
        self.assertEqual(database.line_cost(line, COSTS, SET_COSTS), (360_000, True))

    def test_line_cost_price_wins_over_the_catalog(self):
        # A cost fixed at sale time must survive later edits to the product.
        line = {"product_id": 10, "quantity": 2, "cost_price": 50_000}
        self.assertEqual(database.line_cost(line, COSTS, SET_COSTS), (100_000, True))

    def test_b2b_eritritol_without_a_cost_is_still_flagged(self):
        # The old "id": -1 rows, until the backfill runs.
        line = {"id": -1, "name": "Eritritol (B2B)", "quantity": 12, "unit": "kg"}
        self.assertEqual(database.line_cost(line, COSTS, SET_COSTS), (0, False))

    def test_missing_cost_price_is_flagged(self):
        self.assertEqual(database.line_cost({"product_id": 20, "quantity": 1}, COSTS, SET_COSTS), (0, False))
        self.assertEqual(database.line_cost({"is_set": True, "set_id": 99, "quantity": 1}, COSTS, SET_COSTS),
                         (0, False))


class UsdRateTest(unittest.TestCase):
    def test_target_uses_the_live_rate_and_says_so(self):
        snap = {
            "sales": 4, "daily_target": 10, "sales_left": 6, "day_revenue": 0, "day_profit": 0,
            "month_profit": 11_797_460, "month_profit_usd": 1000, "monthly_target_usd": 2000,
            "monthly_target_uzs": 23_594_920, "remaining_uzs": 11_797_460, "remaining_usd": 1000,
            "needed_per_day_usd": 71, "days_left": 14, "usd_rate": 11797.46, "usd_rate_date": "17.09.2026",
            "month_orders": 40, "month_revenue": 60_000_000,
            "missing_cost_products": ["Psillium 250gr"],
        }
        text = targets.build_message(snap, 13)
        self.assertIn("1$ = 11 797 so'm, Markaziy bank, 17.09.2026", text)
        self.assertIn("Tannarxi kiritilmagan: Psillium 250gr", text)

    def test_bad_rate_falls_back(self):
        targets._rate_cache = (0.0, None, None)
        with patch("aiohttp.ClientSession", side_effect=RuntimeError("offline")):
            self.assertEqual(asyncio.run(targets.current_usd_rate()), (None, None))


if __name__ == "__main__":
    unittest.main()
