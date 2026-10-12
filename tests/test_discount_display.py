"""10% chegirmali narx har bir kartochkada (egasi, 2026-10-12: "botda va
saytda hamma mahsulotlarga bir xilda 10% lik chegirma va narxlari ko'rinib
tursin"). Kartochkadagi narx checkout yozadigan narx bilan aynan bir xil
bo'lishi shart. Telegram va bazaga ulanmasdan."""
import asyncio
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import bot_discount
import daily_interest
import product_card
import webapp_server

DURING = datetime(2026, 10, 12, 8, 0)
AFTER = datetime(2026, 10, 15, 8, 0)


def run(coro):
    return asyncio.run(coro)


def product(pid=1, price=100000, **kw):
    return {"id": pid, "name": "Bodom uni", "name_ru": None, "description": "Tavsif",
            "description_ru": None, "price": price, "discount_percent": 0,
            "discount_until": None, "unit": "piece", "quantity": 7, "category": "un",
            "photo_id": None, "seller_name": "", **kw}


class _Base(unittest.TestCase):
    """Chegirma yoqilgan, 12-oktabr; tannarxlar self.costs dan."""
    active = True
    now = DURING

    def setUp(self):
        self.costs = ({}, {})
        for p in (patch.object(bot_discount, "_now_utc", lambda: self.now),
                  patch.object(bot_discount, "is_active", AsyncMock(side_effect=lambda: self.active and not bot_discount.ended())),
                  patch.object(bot_discount, "_cost_maps", AsyncMock(side_effect=lambda rows: self.costs))):
            p.start()
            self.addCleanup(p.stop)


class DisplayPricesTest(_Base):
    def test_ten_percent_on_products_and_sets(self):
        rows = [product(1, 100000), product(2, 45000),
                {"id": 7, "is_set": True, "set_price": 200000, "name": "Set"}]
        self.assertEqual(run(bot_discount.display_prices(rows)), [90000, 40500, 180000])

    def test_off_or_ended_shows_nothing(self):
        self.active = False
        self.assertEqual(run(bot_discount.display_prices([product()])), [None])
        self.active, self.now = True, AFTER
        self.assertEqual(run(bot_discount.display_prices([product()])), [None])

    def test_cost_floor_same_as_checkout(self):
        # cost 95 000 → only 5% off; cost ≥ price → no discount on the card.
        self.costs = ({1: (95000.0, True), 2: (120000.0, True)}, {})
        self.assertEqual(run(bot_discount.display_prices([product(1), product(2)])), [95000, None])
        self.assertEqual(bot_discount.shown_percent(100000, 95000), 5)

    def test_bigger_own_discount_wins(self):
        until = datetime.utcnow() + timedelta(days=3)
        p = product(discount_percent=20, discount_until=until)
        self.assertEqual(run(bot_discount.display_prices([p])), [None])

    def test_card_price_equals_checkout_price(self):
        self.costs = ({1: (93000.0, True)}, {})
        shown = run(bot_discount.display_price(product(1, 100000)))
        line = {"product_id": 1, "price": 100000, "original_price": 100000, "quantity": 1}
        run(bot_discount.apply([line], 10))
        self.assertEqual(shown, line["price"])
        self.assertEqual(bot_discount.shown_percent(100000, shown), line["discount_percent"])


class MiniAppTest(_Base):
    def test_product_cards_show_struck_price_and_badge(self):
        out = run(webapp_server._serialize_products([product(1, 100000), product(2, 50000)], "uz"))
        self.assertEqual([(o["price"], o["original_price"], o["discount_percent"]) for o in out],
                         [(90000, 100000, 10), (45000, 50000, 10)])
        self.assertIsNone(out[0]["discount_until"])

    def test_unchanged_when_off(self):
        self.active = False
        out = run(webapp_server._serialize_products([product(1, 100000)], "uz"))[0]
        self.assertEqual((out["price"], out["original_price"], out["discount_percent"]), (100000, 100000, 0))

    def test_set_card(self):
        s = {"id": 7, "name": "Set", "name_ru": None, "set_price": 200000, "image_url": None}
        self.assertEqual(webapp_server._serialize_set(s, "uz")["price"], 200000)
        out = webapp_server._serialize_set(s, "uz", 180000)
        self.assertEqual((out["price"], out["original_price"], out["discount_percent"]), (180000, 200000, 10))


class BotCardTest(_Base):
    def caption(self, p, lang="uz"):
        with patch.object(product_card, "get_product_rating", AsyncMock(return_value=(0, 0))), \
             patch("promotions.get_active", AsyncMock(return_value=None)), \
             patch("gift_campaign.card_line", AsyncMock(return_value="")), \
             patch.object(bot_discount, "reminder", AsyncMock(return_value="")):
            return run(product_card.build_caption(p, lang, None))

    def test_card_shows_old_and_new_price(self):
        text = self.caption(product(1, 100000))
        self.assertIn("90 000", text)
        self.assertIn("<s>100 000</s>", text)
        self.assertIn("−10%", text)

    def test_card_plain_when_off(self):
        self.active = False
        text = self.caption(product(1, 100000))
        self.assertIn("100 000", text)
        self.assertNotIn("<s>", text)


class InterestMessageTest(unittest.TestCase):
    def test_price_line_uses_bot_price(self):
        text, _ = daily_interest.build_message(product(1, 100000), "uz", 0, None, 90000)
        self.assertIn("90 000", text)
        self.assertIn("<s>100 000</s>", text)
        self.assertIn("−10%", text)

    def test_shelf_price_without_it(self):
        text, _ = daily_interest.build_message(product(1, 100000), "uz", 0, None)
        self.assertNotIn("<s>", text)


if __name__ == "__main__":
    unittest.main()
