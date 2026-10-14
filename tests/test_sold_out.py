"""Tugagan mahsulot do'konda qoladi va «tez orada qaytadi» deydi (egasi,
2026-10-14: "qolmagan mahsulotlar do'konda turaversin va qolmaganini va
tezda qaytishini kretiv uslubda yozib qo'y", keyin "kreativroq va
samimiyroq bo'lsin" — 5 xil iliq yozuv, faqat mahsulot ichida).
Telegram va bazaga ulanmasdan."""
import asyncio
import os
import re
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import bot_discount
import product_card
from locales import TEXTS

INDEX = Path(__file__).resolve().parent.parent / "webapp" / "index.html"


def product(quantity, description="Tavsif", pid=5):
    return {"id": pid, "name": "Chia urug'i 300gr", "name_ru": "Семена чиа 300г",
            "description": description, "description_ru": None, "price": 50000,
            "discount_percent": 0, "discount_until": None, "unit": "piece",
            "quantity": quantity, "category": "seeds", "photo_id": None, "seller_name": ""}


def caption(p, lang="uz"):
    with patch.object(product_card, "get_product_rating", AsyncMock(return_value=(0, 0))), \
         patch("promotions.get_active", AsyncMock(return_value=None)), \
         patch("gift_campaign.card_line", AsyncMock(return_value="")), \
         patch.object(bot_discount, "reminder", AsyncMock(return_value="")), \
         patch.object(bot_discount, "display_price", AsyncMock(return_value=None)):
        return asyncio.run(product_card.build_caption(p, lang, None))


class BotCardTest(unittest.TestCase):
    def test_sold_out_card_carries_a_warm_note(self):
        # id 5 → note 0; id 6 → note 1: the shelf doesn't repeat one sentence.
        self.assertIn("Siz yolg'iz emassiz", caption(product(0)))
        self.assertIn("Qisqa ta'tilga chiqdi", caption(product(0, pid=6)))
        self.assertIn("Вы не одни", caption(product(0), "ru"))
        cyr = caption(product(0), "uz_cyr")
        self.assertIn("Сиз ёлғиз эмассиз", cyr)
        self.assertNotIn("yolg'iz", cyr)

    def test_in_stock_card_has_no_note(self):
        text = caption(product(3))
        self.assertNotIn("yolg'iz", text)
        self.assertNotIn("kuttirmaymiz", text)

    def test_every_note_exists_in_uz_and_ru(self):
        for i in range(product_card.SOLD_OUT_NOTES):
            entry = TEXTS[f"product_out_of_stock_{i}"]
            self.assertTrue(entry["uz"] and entry["ru"], i)

    def test_long_description_still_fits_the_photo_caption(self):
        # The note is budgeted like the other extras: a long description gets
        # trimmed, the note and the price stay, and the caption fits 1024.
        for pid in range(product_card.SOLD_OUT_NOTES):
            text = caption(product(0, "Juda uzun tavsif. " * 80, pid=pid))
            plain = re.sub(r"<[^>]+>", "", text)
            self.assertLessEqual(len(plain), 1024)
            self.assertIn("50 000", text)


class MiniAppTextsTest(unittest.TestCase):
    KEYS = ("soldOutStamp", "restockAsk", "restockOn", "restockAdded", "restockAlready", "restockBack") + \
        tuple(f"soon{kind}{i}" for kind in ("Title", "Text") for i in range(product_card.SOLD_OUT_NOTES))

    def test_every_sold_out_text_exists_in_uz_and_ru(self):
        html = INDEX.read_text(encoding="utf-8")
        ru_at = html.index("\n  ru: {")
        uz, ru = html[:ru_at], html[ru_at:]
        for key in self.KEYS:
            self.assertRegex(uz, r"\n    %s: '" % key, key)
            self.assertRegex(ru, r"\n    %s: '" % key, key)

    def test_note_count_matches_the_bot(self):
        html = INDEX.read_text(encoding="utf-8")
        self.assertIn(f"const SOLD_OUT_NOTES = {product_card.SOLD_OUT_NOTES};", html)

    def test_sold_out_cards_are_stamped_not_hidden(self):
        html = INDEX.read_text(encoding="utf-8")
        # Both the catalog grid and the home rows use the stamp + note.
        self.assertEqual(html.count("soldOutStampHtml(p) +"), 2)
        self.assertEqual(html.count("cardNoteHtml(p);"), 2)


if __name__ == "__main__":
    unittest.main()
