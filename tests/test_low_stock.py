"""Mijoz kam qolgan mahsulotni va nechta qolganini oldindan ko'radi — egasi,
2026-10-12: "hozir eng oxirgi holatga bormaguncha buni bila olishmaydi".
Chegara adminlar ogohlantirishi bilan bir xil (stock_alerts.level_for)."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import stock_alerts
import webapp_server
import handlers.cart as cart
import product_card


def product(qty, threshold=None, unit="kg", **kw):
    return {"id": 7, "name": "Bodom uni 500gr", "name_ru": None, "description": "Mazali",
            "price": 87000, "unit": unit, "quantity": qty, "low_stock_threshold": threshold,
            "category": "flour", "photo_id": None, "discount_percent": 0, "discount_until": None, **kw}


class LowLeftTest(unittest.TestCase):
    def test_same_limit_as_the_admin_alerts(self):
        self.assertEqual(stock_alerts.low_left(product(3)), 3)
        self.assertEqual(stock_alerts.low_left(product(4.0)), 4)
        self.assertIsNone(stock_alerts.low_left(product(5)))          # limit 5 → not low
        self.assertIsNone(stock_alerts.low_left(product(40)))
        self.assertIsNone(stock_alerts.low_left(product(0)))          # out — its own message
        self.assertEqual(stock_alerts.low_left(product(7, threshold=10)), 7)
        self.assertIsNone(stock_alerts.low_left(product(0.5)))        # no whole piece left

    def test_stock_line(self):
        self.assertEqual(stock_alerts.stock_line(product(3), "uz"), "⚠️ <b>Kam qoldi: atigi 3 dona</b>")
        self.assertEqual(stock_alerts.stock_line(product(3), "ru"), "⚠️ <b>Осталось всего 3 шт</b>")
        self.assertIn("атиги 3", stock_alerts.stock_line(product(3), "uz_cyr"))
        self.assertEqual(stock_alerts.stock_line(product(12.0), "uz"), "✅ Mavjud: 12 dona")   # not "12.0"


class BotCardTest(unittest.TestCase):
    def caption(self, p, lang="uz"):
        import bot_discount
        import gift_campaign
        import promotions
        with patch.object(bot_discount, "reminder", AsyncMock(return_value="")), \
             patch.object(gift_campaign, "card_line", AsyncMock(return_value="")), \
             patch.object(promotions, "get_active", AsyncMock(return_value=None)), \
             patch.object(product_card, "get_product_rating", AsyncMock(return_value=(0, 0))):
            return asyncio.run(product_card.build_caption(p, lang, None))

    def test_low_product_card_says_how_many_are_left(self):
        text = self.caption(product(2))
        self.assertIn("⚠️ <b>Kam qoldi: atigi 2 dona</b>", text)
        self.assertNotIn("Mavjud", text)

    def test_plenty_reads_as_before(self):
        text = self.caption(product(25))
        self.assertIn("✅ Mavjud: 25 dona", text)
        self.assertNotIn("Kam qoldi", text)


class MiniAppTest(unittest.TestCase):
    def test_product_payload_carries_the_count_only_when_low(self):
        self.assertEqual(webapp_server._serialize_product(product(3), "uz")["low_stock"], 3)
        self.assertIsNone(webapp_server._serialize_product(product(30), "uz")["low_stock"])
        data = webapp_server._serialize_product(product(0), "uz")
        self.assertIsNone(data["low_stock"])
        self.assertTrue(data["out_of_stock"])

    def test_page_has_the_strings_and_the_cart_warning(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "webapp", "index.html"),
                  encoding="utf-8") as f:
            page = f.read()
        for needle in ("lowStockBadge: '⚠️ {n} ta qoldi'", "lowStockBadge: '⚠️ Осталось {n} шт.'",
                       "p.low_stock", "item.low_stock", "item.available < item.quantity",
                       'id="detail-low-stock"'):
            self.assertIn(needle, page)


class BotCartNoteTest(unittest.TestCase):
    @staticmethod
    def row(stock, qty, threshold=None, **kw):
        return {"stock": stock, "cart_quantity": qty, "low_stock_threshold": threshold, **kw}

    def test_more_in_the_cart_than_on_the_shelf(self):
        self.assertEqual(cart.cart_stock_note(self.row(2, 5), "uz"),
                         "⚠️ <b>Omborda atigi 2 ta bor — sonini 2 taga tushiring</b>")
        self.assertIn("Закончился", cart.cart_stock_note(self.row(0, 1), "ru"))

    def test_low_but_enough(self):
        self.assertEqual(cart.cart_stock_note(self.row(3, 1), "uz"), "⚠️ <i>3 ta qoldi</i>")

    def test_plenty_and_sets_say_nothing(self):
        self.assertEqual(cart.cart_stock_note(self.row(50, 2), "uz"), "")
        self.assertEqual(cart.cart_stock_note(self.row(999, 2, is_set=True), "uz"), "")

    def test_no_pressure_words(self):
        texts = [stock_alerts.stock_line(product(2), lg) for lg in ("uz", "ru")] + \
                [cart.cart_stock_note(self.row(s, q), lg) for s, q in ((2, 5), (3, 1), (0, 1)) for lg in ("uz", "ru")]
        for text in texts:
            for word in ("shoshiling", "tezroq", "ulgurib", "tugab qolmasidan", "спешите", "успейте"):
                self.assertNotIn(word, text.lower())


if __name__ == "__main__":
    unittest.main()
