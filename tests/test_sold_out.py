"""Tugagan mahsulot do'konda qoladi va «tez orada qaytadi» deydi (egasi,
2026-10-14: "qolmagan mahsulotlar do'konda turaversin va qolmaganini va
tezda qaytishini kretiv uslubda yozib qo'y"). Telegram va bazaga ulanmasdan."""
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

INDEX = Path(__file__).resolve().parent.parent / "webapp" / "index.html"


def product(quantity, description="Tavsif"):
    return {"id": 5, "name": "Chia urug'i 300gr", "name_ru": "Семена чиа 300г",
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
    def test_sold_out_card_says_it_comes_back(self):
        self.assertIn("Hammasini olib ketishdi", caption(product(0)))
        self.assertIn("tez orada qaytadi", caption(product(0)))
        self.assertIn("Всё раскупили", caption(product(0), "ru"))
        cyr = caption(product(0), "uz_cyr")
        self.assertIn("Ҳаммасини олиб кетишди", cyr)
        self.assertNotIn("Hammasini", cyr)

    def test_in_stock_card_has_no_note(self):
        text = caption(product(3))
        self.assertNotIn("olib ketishdi", text)
        self.assertNotIn("qaytadi", text)

    def test_long_description_still_fits_the_photo_caption(self):
        # The note is budgeted like the other extras: a long description gets
        # trimmed, the note and the price stay, and the caption fits 1024.
        text = caption(product(0, "Juda uzun tavsif. " * 80))
        plain = re.sub(r"<[^>]+>", "", text)
        self.assertLessEqual(len(plain), 1024)
        self.assertIn("tez orada qaytadi", text)
        self.assertIn("50 000", text)


class MiniAppTextsTest(unittest.TestCase):
    KEYS = ("soldOutStamp", "soonTitle0", "soonText0", "soonTitle1", "soonText1",
            "soonTitle2", "soonText2", "soonFavAdd", "soonFavOn")

    def test_every_sold_out_text_exists_in_uz_and_ru(self):
        html = INDEX.read_text(encoding="utf-8")
        ru_at = html.index("\n  ru: {")
        uz, ru = html[:ru_at], html[ru_at:]
        for key in self.KEYS:
            self.assertRegex(uz, r"\n    %s: '" % key, key)
            self.assertRegex(ru, r"\n    %s: '" % key, key)

    def test_sold_out_cards_are_stamped_not_hidden(self):
        html = INDEX.read_text(encoding="utf-8")
        # Both the catalog grid and the home rows use the stamp + note.
        self.assertEqual(html.count("soldOutStampHtml(p) +"), 2)
        self.assertEqual(html.count("cardNoteHtml(p);"), 2)


if __name__ == "__main__":
    unittest.main()
