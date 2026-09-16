"""Toshkent bo'ylab bepul yetkazib berish — 800 000 so'mdan (2026-09-17)."""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from handlers import cart


class FreeDeliveryTest(unittest.TestCase):
    def test_threshold(self):
        self.assertEqual(cart.delivery_fee_for("self", 799_999), 25_000)
        self.assertEqual(cart.delivery_fee_for("self", 800_000), 0)
        self.assertEqual(cart.delivery_fee_for("self", 1_200_000), 0)

    def test_other_couriers_are_never_charged_by_us(self):
        for method in ("yandex_taxi", "yandex_market", "bts", "emu", None):
            self.assertEqual(cart.delivery_fee_for(method, 100_000), 0)

    def test_gift_lines_do_not_count(self):
        items = [{"price": 790_000, "quantity": 1}, {"price": 0, "quantity": 1, "is_gift": True}]
        self.assertEqual(cart.delivery_fee_for("self", cart.goods_subtotal(items)), 25_000)

    def test_lines_in_every_language(self):
        self.assertIn("BEPUL", cart.delivery_fee_text("self", 0, "uz"))
        self.assertIn("БЕСПЛАТНО", cart.delivery_fee_text("self", 0, "ru"))
        self.assertIn("БЕПУЛ", cart.delivery_fee_text("self", 0, "uz_cyr"))
        self.assertIn("25 000", cart.delivery_fee_text("self", 25_000, "uz"))
        self.assertEqual(cart.delivery_fee_text("bts", 0, "uz"), "")

    def test_hint_only_within_reach(self):
        self.assertEqual(cart.free_delivery_hint(300_000, "uz"), "")
        self.assertIn("120 000 so'm", cart.free_delivery_hint(680_000, "uz"))
        self.assertIn("bepul", cart.free_delivery_hint(900_000, "uz"))


if __name__ == "__main__":
    unittest.main()
