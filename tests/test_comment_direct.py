"""Izohdan keyingi Direct va «javobsiz izoh qolmasin» (egasi, 2026-11-16)."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import comment_ai  # noqa: E402
import database  # noqa: E402

PRODUCTS = [
    {"name": "Bodom uni 500gr", "price": 100000, "discount_percent": 20, "discount_until": None, "quantity": 5},
    {"name": "Eritritol 500gr", "price": 80000, "discount_percent": 10, "discount_until": None, "quantity": 3},
    {"name": "Kokos uni 500gr", "price": 60000, "discount_percent": 0, "discount_until": None, "quantity": 9},
    {"name": "Tugagan", "price": 50000, "discount_percent": 30, "discount_until": None, "quantity": 0},
    {"name": "Optom", "price": 50000, "discount_percent": 30, "discount_until": None, "quantity": 9, "b2b_only": 1},
]


def run(coro):
    return asyncio.run(coro)


class DirectTest(unittest.TestCase):
    def dm(self, products, comment="Zo'r", dm="Izohingiz uchun rahmat!"):
        with patch.object(database, "admin_list_products", AsyncMock(return_value=products)):
            return run(comment_ai.dm_text_full(comment, dm))

    def test_shop_link_and_the_discounted_list_apart(self):
        text = self.dm(PRODUCTS)
        self.assertIn("🛍 Barcha mahsulotlarimiz va narxlari: https://t.me/ketoshopbot/shop", text)
        self.assertIn("🔥 Chegirmadagilar:", text)
        self.assertLess(text.index("Bodom uni"), text.index("Eritritol"))           # biggest discount first
        self.assertIn("• Bodom uni 500gr — 80 000 so'm (−20%)", text)
        self.assertNotIn("Kokos uni", text)                                        # not discounted
        self.assertNotIn("Tugagan", text)                                          # out of stock
        self.assertNotIn("Optom", text)                                            # wholesale only

    def test_no_discounts_just_the_link(self):
        text = self.dm([PRODUCTS[2]])
        self.assertNotIn("Chegirmadagilar", text)
        self.assertIn("https://t.me/ketoshopbot/shop", text)

    def test_fits_instagrams_1000_characters(self):
        many = [dict(PRODUCTS[0], name=f"Mahsulot raqam {i} juda uzun nomli 500gr") for i in range(80)]
        text = self.dm(many)
        self.assertLessEqual(len(text), 1000)
        self.assertIn("… va boshqalar — havolada", text)

    def test_telegram_handles_become_links(self):
        # Egasi, 2026-11-16: "directdagi havolada telegram havolasi … oddiy username u yerda ochilmaydi".
        text = self.dm([], dm="Rahmat! Telegram botimiz @ketoshopbot va kanalimiz @ketoshop_uz da kutamiz")
        self.assertIn("https://t.me/ketoshopbot va", text)
        self.assertIn("https://t.me/ketoshop_uz", text)
        self.assertNotIn("@ketoshop", text)

    def test_cyrillic_comment_gets_a_cyrillic_dm(self):
        text = self.dm(PRODUCTS, comment="Зўр экан", dm="Раҳмат!")
        self.assertIn("Чегирмадагилар", text)
        self.assertIn("https://t.me/ketoshopbot/shop", text)


class AdviceFirstTest(unittest.TestCase):
    def test_rules_put_advice_before_selling(self):
        # Egasi, 2026-11-16: "faqat sotuvga yo'naltiraverma bu qo'pollik, tavsiyalar ham bergin va keto tavsiyalar ham".
        self.assertIn("AVVAL FOYDA, KEYIN MAHSULOT", comment_ai.RULES)
        self.assertIn("keto/PP maslahati", comment_ai.RULES)
        self.assertIn("har javobda sotuvga undama", comment_ai.RULES)
        self.assertIn("Avval foyda", comment_ai.FOLLOWUP_RULES)
        self.assertIn("keto yoki PP\n  maslahati", comment_ai.FOLLOWUP_RULES.replace("\r", ""))


class HoldingTest(unittest.TestCase):
    def test_every_category_but_spam_gets_an_answer(self):
        for cat in ("salomatlik", "shikoyat", "boshqa", None, "nimadir"):
            self.assertTrue(comment_ai.holding_reply(cat), cat)
        self.assertIsNone(comment_ai.holding_reply("spam"))
        self.assertIn("shifokor", comment_ai.holding_reply("salomatlik"))
        self.assertIn("Kechirasiz", comment_ai.holding_reply("shikoyat"))

    def test_holding_texts_follow_the_house_rules(self):
        for text in comment_ai.HOLDING.values():
            self.assertNotIn("agar sir", text.lower())
            self.assertIn("Direct", text)


if __name__ == "__main__":
    unittest.main()
