"""Kunlik qiziqish eslatmasi qo'llanma asosida (2026-10-11) va kartochkadagi
«📖 Qo'llanma» tugmasi. Bot to'liq mock — hech qanday xabar yuborilmaydi."""
import asyncio
import os
import re
import unittest
from unittest import mock

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import daily_interest as di
import product_card
import product_guides as pg
import promotions

XANTHAN = {"id": 5, "name": "Ksantan kamedi 100g", "name_ru": None, "price": 19000,
           "quantity": 20, "discount_percent": 0, "discount_until": None}
UNKNOWN = {"id": 6, "name": "Telefon g'ilofi", "name_ru": None, "price": 5000,
           "quantity": 3, "discount_percent": 0, "discount_until": None}


def build(product, lang, cycle=0):
    with mock.patch.object(promotions, "bonus_hint", return_value=None):
        return di.build_message(product, lang, cycle, None)


class InterestMessageTest(unittest.TestCase):
    def test_guided_product_gets_numbers_benefit_use_and_caution(self):
        text, kb = build(XANTHAN, "uz", 0)
        g = pg.guide_parts(XANTHAN["name"], "uz")
        self.assertIn(pg.card_line(XANTHAN["name"], "uz"), text)
        self.assertIn(g["benefits"][0], text)
        self.assertIn(g["uses"][0][0], text)
        self.assertIn(g["cautions"][0], text)
        self.assertIn("guide:5", [b.callback_data for row in kb.inline_keyboard for b in row])

    def test_rotates_day_by_day(self):
        g = pg.guide_parts(XANTHAN["name"], "uz")
        day0, _ = build(XANTHAN, "uz", 0)
        day1, _ = build(XANTHAN, "uz", 1)
        self.assertNotEqual(day0, day1)
        self.assertIn(g["uses"][1][0], day1)
        self.assertNotIn(g["uses"][0][0], day1)

    def test_cyrillic_reader_sees_no_latin(self):
        p = dict(XANTHAN)
        text, kb = build(p, "uz_cyr", 2)
        body = re.sub(r"<[^>]+>", "", text)
        self.assertEqual(re.findall(r"[a-zA-Z]+", body), [])
        labels = [b.text for row in kb.inline_keyboard for b in row]
        self.assertTrue(all(not re.search(r"[a-zA-Z]", t) for t in labels), labels)

    def test_russian(self):
        text, kb = build(XANTHAN, "ru", 0)
        self.assertIn("Попробуйте сегодня", text)
        self.assertIn("сум", text)
        self.assertIn("📖 Как использовать", [b.text for row in kb.inline_keyboard for b in row])

    def test_unknown_product_keeps_the_old_message(self):
        text, kb = build(UNKNOWN, "uz", 0)
        self.assertNotIn("Bugun sinab ko'ring", text)
        self.assertNotIn("guide:6", [b.callback_data for row in kb.inline_keyboard for b in row])


class CardGuideButtonTest(unittest.TestCase):
    def _kb(self, product):
        with mock.patch.object(product_card, "get_cart_line_for_product", mock.AsyncMock(return_value=(None, 0))), \
             mock.patch.object(product_card, "get_cart_badge", mock.AsyncMock(return_value=(0, 0))), \
             mock.patch.object(product_card, "get_product", mock.AsyncMock(return_value=product)):
            return asyncio.run(product_card.detail_keyboard(1, product["id"], "", 0, "uz", False))

    def test_button_next_to_reviews_when_guide_exists(self):
        kb = self._kb(XANTHAN)
        self.assertEqual([b.callback_data for b in kb.inline_keyboard[1]], ["reviews:5", "guide:5"])

    def test_no_button_without_guide(self):
        kb = self._kb(UNKNOWN)
        self.assertEqual([b.callback_data for b in kb.inline_keyboard[1]], ["reviews:6"])


class GuideHandlerTest(unittest.TestCase):
    def _press(self, data, product):
        from handlers import catalog
        cb = mock.AsyncMock()
        cb.data = data
        cb.from_user.id = 1
        with mock.patch.object(catalog, "get_user_language", mock.AsyncMock(return_value="uz")), \
             mock.patch.object(catalog, "get_product", mock.AsyncMock(return_value=product)):
            asyncio.run(catalog.show_product_guide(cb))
        return cb

    def test_sends_the_full_guide(self):
        cb = self._press("guide:5", XANTHAN)
        text = cb.message.answer.call_args.args[0]
        self.assertEqual(text, pg.guide_text(XANTHAN, "uz"))

    def test_unknown_or_missing_product_sends_nothing(self):
        self._press("guide:6", UNKNOWN).message.answer.assert_not_called()
        self._press("guide:x", None).message.answer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
