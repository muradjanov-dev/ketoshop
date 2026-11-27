"""📦 Oylik savat (owner, 2026-11-27). Pricing, the admin-only gate, the
reminder date and the GIF. No database, nothing is sent."""
import io
import os
import unittest
from datetime import date
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import keyboards
import oylik_savat as o

P = {
    1: {"id": 1, "name": "Bodom uni 500gr", "price": 87000, "discount_percent": 0, "discount_until": None,
        "is_active": 1, "unit": "dona"},
    2: {"id": 2, "name": "Steviya 200gr", "price": 33000, "discount_percent": 12, "discount_until": None,
        "is_active": 1, "unit": "dona"},
    3: {"id": 3, "name": "Yashirin", "price": 10000, "discount_percent": 0, "is_active": 0},
}
CITY = {"method": "self", "lat": 41.311, "lng": 69.279}


def q(pieces_1, pieces_2=0, delivery=CITY):
    items = o.clean_items([{"product_id": 1, "quantity": pieces_1}, {"product_id": 2, "quantity": pieces_2}])
    return o.price(items, P, delivery)


class TierTest(unittest.TestCase):
    def test_owner_tiers(self):
        self.assertEqual([o.tier_percent(n) for n in (4, 5, 7, 8, 9, 10, 11, 25)], [0, 4, 4, 7, 7, 9, 10, 10])

    def test_next_tier_hint(self):
        self.assertEqual(o.next_tier(3), {"need": 2, "percent": 4, "free_courier": False})
        self.assertEqual(o.next_tier(9), {"need": 1, "percent": 9, "free_courier": True})
        self.assertIsNone(o.next_tier(11))


class PriceTest(unittest.TestCase):
    def test_percent_on_every_line_and_savings(self):
        r = q(3, 2)                                   # 5 pieces → −4%
        self.assertEqual(r["percent"], 4)
        bodom, stevia = r["lines"]
        self.assertEqual(bodom["price"], round(87000 * .96))
        self.assertEqual(bodom["original_price"], 87000)
        self.assertEqual(stevia["original_price"], 29040)             # 12% shelf discount first
        self.assertEqual(r["savings"], r["shelf_total"] - r["subtotal"])
        self.assertEqual(r["delivery_fee"], 25000)
        self.assertEqual(r["total"], r["subtotal"] + 25000)
        self.assertEqual(r["savings_year"], r["savings"] * 12)

    def test_ten_pieces_free_courier_counts_as_savings(self):
        r = q(10)
        self.assertEqual((r["percent"], r["delivery_fee"], r["delivery_saved"]), (9, 0, 25000))
        self.assertTrue(r["free_courier"])
        self.assertEqual(r["savings"], 870000 - 791700 + 25000)

    def test_outside_city_km_still_paid_with_free_courier(self):
        import courier_zone
        far = {"method": "self", "lat": 41.469, "lng": 69.582}
        r = q(11, delivery=far)
        self.assertEqual(r["delivery_fee"], courier_zone.extra_fee(41.469, 69.582))
        self.assertGreater(r["delivery_fee"], 0)

    def test_pickup_free_uzpost_paid(self):
        self.assertEqual(q(5, delivery={"method": "pickup"})["delivery_fee"], 0)
        self.assertGreater(q(5, delivery={"method": "uzpost", "address": "Samarqand"})["delivery_fee"], 0)

    def test_too_few_and_hidden_products(self):
        r = o.price(o.clean_items([{"product_id": 1, "quantity": 2}, {"product_id": 3, "quantity": 5}]), P, CITY)
        self.assertEqual(r["pieces"], 2)
        self.assertFalse(r["ready"])

    def test_clean_items(self):
        self.assertEqual(o.clean_items([{"product_id": 1, "quantity": 3}, {"product_id": "1", "quantity": "30"},
                                        {"product_id": 0, "quantity": 1}, "x", {"product_id": 2}]),
                         [{"product_id": 1, "quantity": o.MAX_QTY}])


class DatesTest(unittest.TestCase):
    def test_next_date(self):
        self.assertEqual(o.next_date(15, date(2026, 12, 13)), date(2026, 12, 15))
        self.assertEqual(o.next_date(5, date(2026, 12, 13)), date(2027, 1, 5))
        self.assertEqual(o.next_date(28, date(2026, 2, 28)), date(2026, 2, 28))


class GateTest(unittest.TestCase):
    def test_admins_only_until_public(self):
        with patch.object(o, "PUBLIC", False), patch("config.ADMIN_IDS", [42]):
            self.assertTrue(o.allowed(42))
            self.assertFalse(o.allowed(7))
            self.assertFalse(o.allowed(None))
        with patch.object(o, "PUBLIC", True):
            self.assertTrue(o.allowed(7))

    def test_command_is_admin_scope_only(self):
        self.assertIn("oylik_savat", [c.command for c in keyboards.ADMIN_COMMANDS])
        public = keyboards.BUYER_COMMANDS
        self.assertNotIn("oylik_savat", [c.command for c in public])


class GifTest(unittest.TestCase):
    def test_gif_has_frames(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")
        buf = io.BytesIO()
        Image.new("RGB", (200, 150), (200, 120, 80)).save(buf, "JPEG")
        gif = o.render_gif([buf.getvalue(), None, b"not an image"], 10, 412000, 460000)
        self.assertTrue(gif.startswith(b"GIF8"))
        self.assertGreater(Image.open(io.BytesIO(gif)).n_frames, 10)


class TextTest(unittest.TestCase):
    def test_summary_in_each_language(self):
        r = q(10)
        sub = {"day": 15, "status": "active"}
        uz = o.summary_text(sub, r, "uz", date(2026, 12, 1))
        self.assertIn("−9%", uz)
        self.assertIn("tejaysiz", uz)
        self.assertIn("15.12", uz)
        self.assertIn("экономите", o.summary_text(sub, r, "ru", date(2026, 12, 1)))
        self.assertNotIn("tejaysiz", o.summary_text(sub, r, "uz_cyr", date(2026, 12, 1)))


if __name__ == "__main__":
    unittest.main()
