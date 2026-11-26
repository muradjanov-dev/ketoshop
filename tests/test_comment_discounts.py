"""Izohlarda aksiya (egasi, 2026-11-26: "aksiyadagi narxini bu narxi faloncha
sum deb qo'yma, boshqa aksiyadagi mahsulotlarni ham aytib o't va ulgurib
qolishlariga cta ber")."""
import asyncio
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import comment_ai
import database


class DiscountCatalogTest(unittest.TestCase):
    def setUp(self):
        comment_ai._catalog_cache = (0.0, "")
        self.addCleanup(setattr, comment_ai, "_catalog_cache", (0.0, ""))
        until = datetime.utcnow() + timedelta(days=4)
        self.products = [
            {"name": "Bodom uni 500gr", "price": 100000, "discount_percent": 20, "discount_until": until,
             "quantity": 5, "category": "Un"},
            {"name": "Kepak", "price": 10000, "discount_percent": None, "quantity": 9, "category": "Un"},
            {"name": "Chia", "price": 50000, "discount_percent": 10, "discount_until": None,
             "quantity": 0, "category": "Urug'"},
        ]
        self.until = until

    def test_sale_price_is_marked_and_listed(self):
        with patch.object(database, "admin_list_products", AsyncMock(return_value=self.products)):
            text = asyncio.run(comment_ai.catalog_text())
        day = (self.until + timedelta(hours=5)).strftime("%d.%m")
        self.assertIn(f"- Bodom uni 500gr — 80 000 so'm (CHEGIRMA −20%: avval 100 000 so'm; {day} gacha)", text)
        self.assertIn("- Kepak — 10 000 so'm", text)
        self.assertNotIn("Kepak — 10 000 so'm (CHEGIRMA", text)
        sale = text.split("CHEGIRMADAGILAR")[1]
        self.assertIn("Bodom uni 500gr", sale)
        self.assertNotIn("Chia", sale)                 # tugagan — ro'yxatda yo'q
        self.assertNotIn("Kepak", sale)

    def test_rules_ask_for_old_and_new_price_and_a_cta(self):
        self.assertIn("AKSIYA VA CHEGIRMA", comment_ai.RULES)
        self.assertIn("ulgurib", comment_ai.RULES)
        self.assertIn("CHEGIRMA (egasi, 2026-11-26)", comment_ai.FOLLOWUP_RULES)
        self.assertIn("Bilasizmi", comment_ai.FOLLOWUP_RULES)

    def test_never_answered_comment_gets_an_apology_hint(self):
        prompt = comment_ai.followup_prompt({"platform": "ig", "text": "narxi?", "reply_text": ""}, 40)
        self.assertIn("javob bermaganmiz", prompt)


if __name__ == "__main__":
    unittest.main()
