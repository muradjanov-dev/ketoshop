import unittest
from pathlib import Path

import promotions
from webapp_server import create_webapp


def _promotion() -> dict:
    return {
        "id": 7,
        "name": "Mavlid Aksiyasi",
        "bonuses": [
            {
                "trigger_product_id": 10,
                "trigger_quantity": 2,
                "trigger_unit": "kg",
                "trigger_name": "Kokos uni 1000gr",
                "trigger_name_ru": None,
                "bonus_product_id": 59,
                "bonus_amount": 1,
                "bonus_unit": "dona",
                "bonus_stock_qty": 1,
                "bonus_name": "Kokos qirindisi 200gr",
                "bonus_name_ru": None,
                "bonus_price": 18000,
                "bonus_photo_id": None,
                "max_bonus_amount": None,
            }
        ],
    }


class PromotionRegressionTests(unittest.TestCase):
    def test_earned_bonus_scales_and_stays_free(self) -> None:
        bonuses = promotions.compute_bonuses(
            _promotion(),
            [{"product_id": 10, "quantity": 5, "price": 85000}],
        )

        self.assertEqual(len(bonuses), 1)
        self.assertEqual(bonuses[0]["quantity"], 2)
        self.assertEqual(bonuses[0]["stock_quantity"], 2)
        self.assertEqual(bonuses[0]["price"], 0)
        self.assertEqual(bonuses[0]["bonus_value"], 36000)

    def test_cart_reports_how_much_is_missing_for_bonus(self) -> None:
        misses = promotions.compute_near_misses(
            _promotion(),
            [{"product_id": 10, "quantity": 1}],
        )

        self.assertEqual(len(misses), 1)
        self.assertEqual(misses[0]["needed"], 1)
        self.assertIn("Yana 1 dona", promotions.near_miss_text(misses, "uz"))

    def test_webapp_registers_promo_api_and_banner(self) -> None:
        app = create_webapp(object())  # type: ignore[arg-type]
        paths = {resource.canonical for resource in app.router.resources()}
        html = Path("webapp/index.html").read_text(encoding="utf-8")

        self.assertIn("/api/promo", paths)
        self.assertIn('id="home-promo-banner"', html)
        self.assertIn("await loadPromo()", html)


if __name__ == "__main__":
    unittest.main()
