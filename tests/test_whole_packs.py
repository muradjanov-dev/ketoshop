"""Butun qadoq (egasi, 2026-11-06): «Bodom uni 500gr - 1 ta: 43 500 so'm» —
"yarim kgni yarmini hisoblayapti degan shikoyatlar keldi find error and fix
everywhere". The AI read a 500 g pack priced in "kg" as 0.5 kg; the bot offered
"0.5" for dona/litr goods. No Telegram, no database."""
import asyncio
import json
import os
import unittest
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ai_sales
import database
import keyboards
import pack_audit

BODOM = {"id": 12, "name": "Bodom uni 500gr", "price": 87000, "unit": "kg", "quantity": 9,
         "is_active": 1, "discount_percent": 0, "discount_until": None}


def run(coro):
    return asyncio.run(coro)


class AiWholePackTest(unittest.TestCase):
    def setUp(self):
        for name, value in (("get_product", AsyncMock(return_value=dict(BODOM))),
                            ("get_cart_line_for_product", AsyncMock(return_value=(None, 0))),
                            ("add_to_cart", AsyncMock(return_value=1.0))):
            p = patch.object(database, name, value)
            p.start()
            self.addCleanup(p.stop)
        for name, value in (("_promo_hint", AsyncMock(return_value="")), ("_remember_quiet", AsyncMock())):
            p = patch.object(ai_sales, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_the_exact_complaint_one_500g_pack_is_the_full_price(self):
        out = run(ai_sales._tool_quote(1, {"mahsulotlar": [{"mahsulot_id": 12, "miqdor": 1}]}))
        self.assertIn("Bodom uni 500gr — 1 dona × 87 000 = 87 000 so'm", out)
        self.assertNotIn("43 500", out)

    def test_half_a_pack_is_refused_in_the_quote_and_the_cart(self):
        out = run(ai_sales._tool_quote(1, {"mahsulotlar": [{"mahsulot_id": 12, "miqdor": 0.5}]}))
        self.assertTrue(out.startswith("Xato:"), out)
        self.assertIn("butun qadoq", out)
        out = run(ai_sales._tool_add(1, {"mahsulot_id": 12, "miqdor": 0.5}))
        self.assertTrue(out.startswith("Xato:"), out)
        database.add_to_cart.assert_not_awaited()
        out = run(ai_sales._tool_add(1, {"mahsulot_id": 12, "miqdor": 1}))
        self.assertIn("Bodom uni 500gr — 1 dona", out)

    def test_the_model_is_told_packs_not_kilos(self):
        specs = {s["name"]: s for s in ai_sales._TOOL_SPECS}
        add = specs["savatga_qoshish"]
        self.assertEqual(add["input_schema"]["properties"]["miqdor"]["type"], "integer")
        self.assertNotIn("0.5/1/2", add["description"])
        quote = specs["hisob"]["input_schema"]["properties"]["mahsulotlar"]["items"]["properties"]
        self.assertEqual(quote["miqdor"]["type"], "integer")

    def test_the_catalog_prices_a_pack_not_a_kilo(self):
        with patch.object(ai_sales, "_catalog_cache", None), \
             patch.object(database, "get_all_products_paginated", AsyncMock(return_value=([dict(BODOM)], 1))), \
             patch.object(database, "get_categories", AsyncMock(return_value=[])), \
             patch.object(database, "get_active_sets_for_catalog", AsyncMock(return_value=[])):
            text = run(ai_sales._catalog_text())
        self.assertIn("12 | Bodom uni 500gr | 87 000 so'm / dona", text)
        self.assertNotIn("so'm / kg", text)
        self.assertIn("NARX — BIR QADOQ", text)

    def test_a_half_price_line_no_longer_passes_the_price_check(self):
        catalog = "12 | Bodom uni 500gr | 87 000 so'm / dona"
        check = ai_sales.PriceCheck("", catalog, "")
        self.assertEqual(check.bad("• Bodom uni 500gr - 1 ta: 43 500 so'm"), [43500])
        self.assertEqual(check.bad("• Bodom uni 500gr - 2 ta: 174 000 so'm"), [])


class BotWholePackTest(unittest.TestCase):
    def test_no_half_button_for_any_unit(self):
        for unit in ("kg", "g", "piece", "liter", "jar", "bundle", ""):
            kb = keyboards.quantity_keyboard("uz", 5, unit)
            labels = [b.text for row in kb.inline_keyboard for b in row]
            self.assertNotIn("0.5", labels, unit)
            self.assertIn("1", labels, unit)

    def test_an_old_half_button_is_refused(self):
        import handlers.cart as cart
        callback = NS(data="qty:5:0.5", from_user=NS(id=7), answer=AsyncMock())
        with patch.object(cart, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(cart, "add_to_cart", AsyncMock()) as add:
            run(cart.add_item_to_cart(callback))
        add.assert_not_awaited()
        self.assertTrue(callback.answer.await_args.kwargs.get("show_alert"))


class PackAuditTest(unittest.TestCase):
    ITEMS = [{"name": "Bodom uni 500gr", "quantity": 0.5, "price": 87000, "unit": "kg"},
             {"name": "Eritritol 500gr", "quantity": 2, "price": 68000, "unit": "kg"},
             {"name": "Eritritol 100gr", "quantity": 0.5, "price": 0, "is_gift": True},
             {"name": "Eritritol (B2B)", "quantity": 2.5, "price": 50000, "unit": "kg", "bulk": True}]

    def test_only_retail_half_packs_count(self):
        lines = pack_audit.half_pack_lines(self.ITEMS)
        self.assertEqual([l["name"] for l in lines], ["Bodom uni 500gr"])

    def test_report_lists_open_orders_with_the_full_pack_price(self):
        class Conn:
            async def fetch(self, sql, *args):
                return [{"id": 5003, "status": "pending", "items": json.dumps(TestItems), "total": 179500},
                        {"id": 4100, "status": "delivered", "items": json.dumps(TestItems), "total": 179500},
                        {"id": 4200, "status": "pending", "items": json.dumps([TestItems[1]]), "total": 136000}]

        class Pool:
            def acquire(self):
                class Ctx:
                    async def __aenter__(self_inner):
                        return Conn()

                    async def __aexit__(self_inner, *a):
                        return False
                return Ctx()
        TestItems = self.ITEMS
        with patch.object(database, "pool", Pool()):
            open_orders, finished = run(pack_audit.find_orders())
        self.assertEqual([o["id"] for o in open_orders], [5003])
        self.assertEqual([o["id"] for o in finished], [4100])
        text = pack_audit.report_text(open_orders, finished)
        self.assertIn("#5003 — Bodom uni 500gr × 0.5 = 43 500 so'm (1 qadoq: 87 000 so'm)", text)
        self.assertIn("#4100", text)

    def test_sent_once_and_only_when_there_is_something(self):
        bot = AsyncMock()
        with patch.object(pack_audit, "find_orders", AsyncMock(return_value=([], []))), \
             patch.object(database, "claim_release_notes", AsyncMock(return_value=True)):
            self.assertTrue(run(pack_audit.run_once(bot)))
        bot.send_message.assert_not_awaited()
        order = {"id": 5003, "status": "pending", "total": 1, "lines": [self.ITEMS[0]]}
        with patch.object(pack_audit, "find_orders", AsyncMock(return_value=([order], []))), \
             patch.object(pack_audit, "ADMIN_IDS", [1, 2]), \
             patch.object(database, "claim_release_notes", AsyncMock(return_value=False)):
            run(pack_audit.run_once(bot))                       # already sent by an earlier start
        bot.send_message.assert_not_awaited()
        with patch.object(pack_audit, "find_orders", AsyncMock(return_value=([order], []))), \
             patch.object(pack_audit, "ADMIN_IDS", [1, 2]), \
             patch.object(database, "claim_release_notes", AsyncMock(return_value=True)):
            run(pack_audit.run_once(bot))
        self.assertEqual(bot.send_message.await_count, 2)


if __name__ == "__main__":
    unittest.main()
