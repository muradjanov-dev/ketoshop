"""Buyurtmadan keyingi rahmat xabari: Ketoshop kuryeri — 24 soat,
Yandex — admin kontaktlari, qolganlari — faqat rahmat."""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from config import SUPPORT_USERNAME
from handlers.cart import order_thanks_text


class OrderThanksTest(unittest.TestCase):
    def test_self_courier_promises_24h(self):
        t = order_thanks_text(12, "self", "uz")
        self.assertIn("#12", t)
        self.assertIn("rahmat", t)
        self.assertIn("24 soat", t)
        self.assertNotIn(SUPPORT_USERNAME, t)

    def test_yandex_points_to_admin(self):
        for method in ("yandex_taxi", "yandex_market"):
            t = order_thanks_text(5, method, "ru")
            self.assertIn("@" + SUPPORT_USERNAME, t)
            self.assertNotIn("24", t)

    def test_other_methods_only_thank(self):
        t = order_thanks_text(7, "bts", "uz")
        self.assertIn("rahmat", t)
        self.assertNotIn("24 soat", t)
        self.assertNotIn(SUPPORT_USERNAME, t)

    def test_cyrillic(self):
        t = order_thanks_text(3, "self", "uz_cyr")
        self.assertIn("24 соат", t)


if __name__ == "__main__":
    unittest.main()
