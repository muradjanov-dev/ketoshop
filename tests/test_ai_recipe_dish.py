"""Mijoz so'ragan taomning o'zi beriladi (egasi, 2026-11-27: non so'ralganda palov berildi)."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ai_sales


class DishTest(unittest.TestCase):
    def test_dish_kind(self):
        self.assertEqual(ai_sales.dish_kind("non"), "non")
        self.assertEqual(ai_sales.dish_kind("хлеб"), "non")
        self.assertEqual(ai_sales.dish_kind("Pechene"), "pechene")
        self.assertIsNone(ai_sales.dish_kind(""))

    def test_bread_never_becomes_pilaf(self):
        self.assertIn("palov", ai_sales._library_recipe("Yashil grechka doni 500gr", "").lower())
        self.assertEqual(ai_sales._library_recipe("Yashil grechka doni 500gr", "non"), "")
        self.assertIn("non", ai_sales._library_recipe("Bodom uni 1000gr", "non").lower())

    def test_tool_passes_dish_and_writes_that_dish(self):
        product = {"id": 77, "name": "Yashil grechka doni 500gr", "is_active": True}
        with patch.object(ai_sales.database, "get_product", AsyncMock(return_value=product)), \
                patch.object(ai_sales.ai_memory, "recipes_since", AsyncMock(return_value=0)), \
                patch.object(ai_sales.ai_memory, "record_recipe", AsyncMock()):
            out = asyncio.run(ai_sales._tool_recipe(1, {"mahsulot_id": 77, "taom": "non"}))
        self.assertIn("«non» — AYNAN shu taomni yoz", out)
        self.assertNotIn("palov", out.lower())

    def test_schema_and_rules(self):
        tool = next(t for t in ai_sales._TOOL_SPECS if t["name"] == "retsept")
        self.assertIn("taom", tool["input_schema"]["properties"])
        self.assertIn("taom", tool["input_schema"]["required"])
        rules = ai_sales._sales_rules()
        self.assertIn("DONDAN NON", rules)
        self.assertIn("AYNAN o'sha taomni ber", rules)


if __name__ == "__main__":
    unittest.main()


class GreetingOnlyTest(unittest.TestCase):
    def test_rule_against_menu_and_stock_phrases(self):
        rules = ai_sales._sales_rules()
        self.assertIn("FAQAT SALOM", rules)
        self.assertIn("tez aytib beramiz", rules)


class AdminMessageRecordTest(unittest.TestCase):
    def test_customer_message_goes_into_dialog_admins_do_not(self):
        import admin_web
        src = open(admin_web.__file__, encoding="utf-8").read()
        self.assertIn("ai_dialog.record(chat_id, \"bot\", \"[Do'kon o'zi yozdi]\", text)", src)
        self.assertIn("if chat_id in staff:", src)
