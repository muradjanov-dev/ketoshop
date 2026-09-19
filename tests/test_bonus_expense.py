"""Aksiya bonuslari Chiqimlarga yoziladi, foydadan ikki marta yechilmaydi
(2026-09-19). Namuna: 2 kg Steviyaga 0.5 kg Steviya bonus."""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
import promotions


def _stevia_promo() -> dict:
    """2 kg Steviya olgan mijozga 0.5 kg Steviya bepul."""
    return {
        "id": 11,
        "name": "Steviya aksiyasi",
        "bonuses": [
            {
                "trigger_product_id": 21,
                "trigger_quantity": 2,
                "trigger_unit": "kg",
                "trigger_name": "Stevia 1000gr",
                "trigger_name_ru": None,
                "bonus_product_id": 21,
                "bonus_amount": 0.5,
                "bonus_unit": "kg",
                "bonus_stock_qty": 0.5,
                "bonus_name": "Stevia 1000gr",
                "bonus_name_ru": None,
                "bonus_price": 300_000,
                "bonus_photo_id": None,
                "max_bonus_amount": None,
            }
        ],
    }


class BonusLineTest(unittest.TestCase):
    def test_two_kg_earns_the_half_kilo(self):
        bonuses = promotions.compute_bonuses(
            _stevia_promo(), [{"product_id": 21, "quantity": 2, "price": 600_000}])
        self.assertEqual(len(bonuses), 1)
        self.assertEqual(bonuses[0]["stock_quantity"], 0.5)
        self.assertEqual(bonuses[0]["price"], 0)

    def test_one_kg_earns_nothing(self):
        self.assertEqual(
            promotions.compute_bonuses(
                _stevia_promo(), [{"product_id": 21, "quantity": 1, "price": 300_000}]),
            [])

    def test_bonus_is_marked_for_the_expense_book(self):
        bonuses = promotions.compute_bonuses(
            _stevia_promo(), [{"product_id": 21, "quantity": 2, "price": 600_000}])
        self.assertTrue(bonuses[0]["cost_in_expenses"])


class CostingTest(unittest.TestCase):
    def test_booked_bonus_is_not_charged_as_goods(self):
        # Charging it here AND booking it in Chiqimlar would take the same
        # stevia off the profit twice.
        line = promotions.compute_bonuses(
            _stevia_promo(), [{"product_id": 21, "quantity": 2, "price": 600_000}])[0]
        self.assertEqual(database.item_cost_qty(line), 0.0)

    def test_older_bonus_lines_are_costed_as_before(self):
        # Orders placed before the switch have no marker: they were costed as
        # goods and never booked, and must keep reading exactly as they did.
        legacy = {"is_bonus": True, "quantity": 100, "stock_quantity": 0.1}
        self.assertEqual(database.item_cost_qty(legacy), 0.1)

    def test_gifts_are_still_free_of_goods_cost(self):
        self.assertEqual(database.item_cost_qty({"is_gift": True, "quantity": 1}), 0.0)

    def test_paid_lines_untouched(self):
        self.assertEqual(database.item_cost_qty({"quantity": 3}), 3.0)


if __name__ == "__main__":
    unittest.main()
