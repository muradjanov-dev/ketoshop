"""A pack bought by the piece is not "1 kg" (owner, 2026-10-28: an order card
read «Pista mag'zi 500gr × 1 kg» for one 500 g pack)."""
import json
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import order_admin_feed as feed
from locales import line_unit

# The lines of the order the owner pasted, as orders.items keeps them.
ITEMS = [
    {"name": "Eritrtitol 1000gr", "quantity": 1, "price": 91000, "unit": "piece"},
    {"name": "Yashil grechka doni 1000gr", "quantity": 1, "price": 30600, "unit": "kg"},
    {"name": "Kepak. -o‘rtacha kattalikda (sredniy)", "quantity": 2, "price": 8500, "unit": "kg"},
    {"name": "Pista mag'zi 500gr", "quantity": 1, "price": 15300, "unit": "kg"},
    {"name": "Psillium sheluxa 150gr", "quantity": 1, "price": 61600, "unit": "kg"},
    {"name": "Lasos baliq tushonkasi 700ml", "quantity": 2, "price": 81786, "unit": "liter"},
    {"name": "Zig'ir uni", "quantity": 0.5, "price": 90000, "unit": "kg"},
    {"name": "Kepakli bug'doy uni", "quantity": 25, "price": 9000, "unit": "kg", "bulk": True},
    {"name": "Asal", "quantity": 2, "price": 100000, "unit": "jar"},
]


class LineUnitTest(unittest.TestCase):
    def test_packs_are_counted_not_weighed(self):
        for it in ITEMS[:6]:
            self.assertEqual(line_unit(it, "uz"), "", it["name"])
            self.assertEqual(line_unit(it, "ru"), "", it["name"])

    def test_real_weights_and_other_units_are_named(self):
        self.assertEqual(line_unit(ITEMS[6], "uz"), "kg")          # half a kilo
        self.assertEqual(line_unit(ITEMS[7], "ru"), "кг")          # wholesale
        self.assertEqual(line_unit(ITEMS[8], "uz"), "banka")
        self.assertEqual(line_unit({"unit": "custom", "quantity": 1}, "uz"), "custom")
        self.assertEqual(line_unit({"quantity": 1}, "uz"), "")


class OrderCardTest(unittest.TestCase):
    def test_status_card(self):
        order = {"id": 795, "status": "confirmed", "customer_name": "Bek", "phone": "+998900000000",
                 "address": "Toshkent", "total": 436650, "items": json.dumps(ITEMS)}
        for lang in ("uz", "uz_cyr", "ru"):
            text = feed.build_card(order, lang, title="status_title", by="Admin",
                                   old_status="pending", new_status="confirmed")
            self.assertIn("Pista mag'zi 500gr × 1 — 15 300", text)
            self.assertIn("Psillium sheluxa 150gr × 1 — 61 600", text)
            self.assertIn("Lasos baliq tushonkasi 700ml × 2 — 163 572", text)
            self.assertIn("Kepak. -o‘rtacha kattalikda (sredniy) × 2 — 17 000", text)
            self.assertNotIn("× 1 kg", text)
            self.assertNotIn("× 1 кг", text)
        uz = feed.build_card(order, "uz", title="status_title", by="Admin")
        self.assertIn("Zig'ir uni × 0.5 kg — 45 000", uz)
        self.assertIn("Kepakli bug'doy uni × 25 kg", uz)
        self.assertIn("Asal × 2 banka", uz)

    def test_courier_board_lines(self):
        import courier_board
        lines = courier_board._parse_items(json.dumps(ITEMS))
        self.assertEqual([l["unit"] for l in lines],
                         ["", "", "", "", "", "", "kg", "kg", "banka"])


if __name__ == "__main__":
    unittest.main()
