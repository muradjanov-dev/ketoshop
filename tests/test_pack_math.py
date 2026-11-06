"""Qadoq tahlili (egasi, 2026-11-06): "yarim narx case ga o'xshash holatlarda ai boshqa
hecham xato qilmasin! buni tahlil qilishni o'rgansin". No model, no database."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import pack_math as pm

B5 = {"id": 12, "name": "Bodom uni 500gr", "price": 87000, "unit": "kg"}
B1 = {"id": 13, "name": "Bodom uni 1000gr", "price": 169000, "unit": "kg"}
JAVDAR = {"id": 17, "name": "Javdar uni", "price": 10000, "unit": "kg"}
ZAYTUN = {"id": 24, "name": "Zaytun yog'i Extra virgin 500ml", "price": 69000, "unit": "liter"}


class PackSizeTest(unittest.TestCase):
    def test_sizes_from_names_and_units(self):
        self.assertEqual(pm.pack_size("Bodom uni 500gr"), (500, "g"))
        self.assertEqual(pm.pack_size("Bodom uni 1 kg"), (1000, "g"))
        self.assertEqual(pm.pack_size("Zaytun yog'i 0,5 l"), (500, "ml"))
        self.assertEqual(pm.pack_size("Lasos tushonkasi 700ml"), (700, "ml"))
        self.assertEqual(pm.pack_size("Миндальная мука 500 г"), (500, "g"))
        self.assertEqual(pm.pack_size("Javdar uni", "kg"), (1000, "g"))          # weighed, no size = 1 kg
        self.assertIsNone(pm.pack_size("Kokos chipsi", "piece"))

    def test_one_family_whatever_the_pack(self):
        self.assertEqual(pm.base_name("Bodom uni 500gr"), pm.base_name("Bodom uni 1000gr"))
        self.assertNotEqual(pm.base_name("Bodom uni 500gr"), pm.base_name("Kokos uni 500gr"))


class PackOptionsTest(unittest.TestCase):
    def test_a_kilo_offers_both_packs_cheapest_first(self):
        out = pm.options_text([B5, B1], 1000, "g")
        self.assertIn("Bodom uni 1000gr (id 13) × 1 dona = 1 kg, 169 000 so'm", out)
        self.assertIn("Bodom uni 500gr (id 12) × 2 dona = 1 kg, 174 000 so'm", out)
        self.assertLess(out.index("169 000"), out.index("174 000"))
        self.assertIn("eng arzon", out)

    def test_half_a_kilo_is_one_whole_500g_pack(self):
        out = pm.options_text([B5, B1], 500, "g")
        self.assertIn("Bodom uni 500gr (id 12) × 1 dona = 500 g, 87 000 so'm", out)
        self.assertNotIn("43 500", out)

    def test_less_than_the_smallest_pack_is_said_not_divided(self):
        out = pm.options_text([B5, B1], 300, "g")
        self.assertIn("300 g alohida sotilmaydi", out)
        self.assertIn("narxni BO'LMA", out)
        self.assertNotIn("52 200", out)                       # 87 000 × 0.6

    def test_mixed_packs_for_one_and_a_half_kilo(self):
        out = pm.options_text([B5, B1], 1500, "g")
        self.assertIn("Bodom uni 1000gr (id 13) × 1 dona + Bodom uni 500gr (id 12) × 1 dona = 1.5 kg, "
                      "256 000 so'm", out)

    def test_litres_and_a_product_without_a_size(self):
        self.assertIn("Zaytun yog'i Extra virgin 500ml (id 24) × 2 dona = 1 l, 138 000 so'm",
                      pm.options_text([ZAYTUN], 1000, "ml"))
        self.assertIn("× 3 dona = 3 kg, 30 000 so'm", pm.options_text([JAVDAR], 3000, "g"))
        self.assertTrue(pm.options_text([{"id": 5, "name": "Kokos chipsi", "price": 9000,
                                          "unit": "piece"}], 500, "g").startswith("Xato:"))


class LineMismatchTest(unittest.TestCase):
    PRODUCTS = [B5, B1, JAVDAR]

    def bad(self, text, trusted=frozenset()):
        return [i["line"] for i in pm.line_mismatch(text, self.PRODUCTS, trusted)]

    def test_the_complaint_lines_are_caught(self):
        self.assertEqual(self.bad("• Bodom uni 500gr - 1 ta: 43 500 so'm"), ["• Bodom uni 500gr - 1 ta: 43 500 so'm"])
        self.assertTrue(self.bad("• Bodom uni 500gr - 1 kg: 87 000 so'm"))            # 1 kg = 2 qadoq
        self.assertTrue(self.bad("Bodom uni 500gr — 2 dona: 87 000 so'm"))
        self.assertTrue(self.bad("Bodom uni 500gr yarim kilosi 43 500 so'm"))

    def test_correct_lines_and_price_lists_pass(self):
        for line in ("• Bodom uni 500gr - 2 dona: 174 000 so'm", "• Bodom uni 1000gr - 1 kg: 169 000 so'm",
                     "• Javdar uni - 3 kg: 30 000 so'm", "Bodom uni 500gr — 87 000 so'm",
                     "Bodom uni 500gr - 87 000 so'm, 1000gr - 169 000 so'm", "Jami: 330 000 so'm",
                     "Bodom uni 1000gr yarim kilo kerak bo'lsa ham 1 dona: 169 000 so'm"):
            self.assertEqual(self.bad(line), [], line)

    def test_a_line_copied_from_the_cart_tool_is_trusted(self):
        # Bot discount: the cart says 78 300 for one pack — not the catalog price.
        self.assertTrue(self.bad("Bodom uni 500gr - 1 dona: 78 300 so'm"))
        self.assertEqual(self.bad("Bodom uni 500gr - 1 dona: 78 300 so'm", trusted={78300}), [])
        self.assertTrue(self.bad("Bodom uni 500gr - 2 dona: 78 300 so'm", trusted={78300}))

    def test_the_fix_note_names_the_right_amount(self):
        note = pm.mismatch_fix(pm.line_mismatch("• Bodom uni 500gr - 1 ta: 43 500 so'm", self.PRODUCTS))
        self.assertIn("1 qadoq = 87 000 so'm", note)
        self.assertIn("qadoq_tanlash", note)


class AiWiringTest(unittest.TestCase):
    def setUp(self):
        import ai_sales
        self.ai = ai_sales

    def test_tool_rule_and_check_are_wired(self):
        names = {t.name for t in self.ai.TOOLS}
        self.assertIn("qadoq_tanlash", names)
        rules = self.ai._sales_rules()
        self.assertIn("MIQDOR VA QADOQ TAHLILI", rules)
        self.assertIn("yarmi EMAS", rules)
        self.assertNotIn("43 500", rules)        # an example amount would whitelist the wrong sum
        self.assertIn("O'ZING HISOBLAMA, qadoq_tanlash ni chaqir", rules)

    def test_pack_tool_reads_the_family_with_discounts(self):
        products = [dict(B5, quantity=5, is_active=1, discount_percent=0, discount_until=None),
                    dict(B1, quantity=0, is_active=1, discount_percent=0, discount_until=None),   # sold out
                    {"id": 30, "name": "Chia urug'i 500gr", "price": 59000, "unit": "kg", "quantity": 9,
                     "is_active": 1, "discount_percent": 0, "discount_until": None}]
        import database
        with patch.object(database, "get_product", AsyncMock(return_value=dict(products[0]))), \
             patch.object(database, "get_all_products_paginated", AsyncMock(return_value=(products, 3))):
            out = asyncio.run(self.ai._tool_pack_options({"mahsulot_id": 12, "miqdor": 1, "birlik": "kg"}))
        self.assertIn("Bodom uni 500gr (id 12) × 2 dona = 1 kg, 174 000 so'm", out)
        self.assertNotIn("1000gr", out)                      # tugagan qadoq taklif qilinmaydi
        self.assertNotIn("Chia", out)                        # boshqa mahsulot emas

    def test_a_mismatched_reply_is_asked_again_then_dropped(self):
        import ai_sales
        import database
        from ai_provider import Turn

        class Provider:
            name, model = "fake", "fake"

            def __init__(self, turns):
                self.turns, self.calls = list(turns), []

            async def step(self, state, rules, catalog, tools, *, user=None, results=None, **kw):
                self.calls.append(user)
                return self.turns.pop(0)
        bad = "Hisoblab berdik:\n• Bodom uni 500gr - 1 ta: 43 500 so'm\nJami: 43 500 so'm"
        provider = Provider([Turn(text=bad), Turn(text=bad), Turn(text=bad)])   # it keeps repeating
        saved = ai_sales.PROVIDER
        self.addCleanup(setattr, ai_sales, "PROVIDER", saved)
        ai_sales.PROVIDER = provider
        message = type("M", (), {})()
        message.from_user = type("U", (), {"id": 991, "full_name": "T", "username": None, "first_name": "T"})()
        message.chat = type("C", (), {"id": 991, "type": "private"})()
        with patch.object(ai_sales, "_catalog_cache", (9e18, "12 | Bodom uni 500gr | 87 000 so'm / dona")), \
             patch.object(database, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(ai_sales, "_opening_context", AsyncMock(return_value="")):
            reply = asyncio.run(ai_sales._respond(None, message, "bodom uni 500gr 1 ta qancha"))
        ai_sales._sessions.pop(991, None)
        fixes = [c for c in provider.calls[1:] if c and c.startswith("[TIZIM")]
        self.assertTrue(fixes)                                   # asked again before sending
        self.assertTrue(any("miqdor va summa mos emas" in c or "summa" in c for c in fixes))
        self.assertNotIn("43 500", reply)


if __name__ == "__main__":
    unittest.main()
