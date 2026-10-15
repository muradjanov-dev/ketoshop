"""Saytda tillar aralashmasin (egasi, 2026-10-13: "saytda tillar aralashib
ketipti"): aksiya matnlari, birliklar va set nomlari kirill o'zbekchada
kirillda, rus tilida ruscha. Telegram va bazaga ulanmasdan."""
import os
import re
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import promotions
import webapp_server
from translit import lat_to_cyr

LATIN_WORD = re.compile(r"\b(?!MCT\b)[A-Za-z]{2,}\b")


def latin_words(text: str) -> list[str]:
    # HTML tags are markup, not words the buyer reads.
    return LATIN_WORD.findall(re.sub(r"<[^>]+>", "", text))


RULE = {
    "trigger_quantity": 1, "trigger_unit": "piece",
    "trigger_name": "Bodom uni 200gr", "trigger_name_ru": "Миндальная мука 200г",
    "bonus_amount": 100, "bonus_unit": "gr",
    "bonus_name": "Eritritol 200gr", "bonus_name_ru": "Эритритол 200г",
    "bonus_price": 30000, "bonus_stock_qty": 0.5,
}


class AksiyaTextTest(unittest.TestCase):
    def test_units(self):
        self.assertEqual(promotions.unit_label("piece", "uz"), "dona")
        self.assertEqual(promotions.unit_label("piece", "uz_cyr"), "дона")
        self.assertEqual(promotions.unit_label("piece", "ru"), "шт")

    def test_name_and_conditions(self):
        promo = {"name": "Stevia — doimiy bonus", "conditions": "Har bir buyurtmaga sovg'a",
                 "name_ru": "Стевия — постоянный бонус", "conditions_ru": None}
        self.assertEqual(latin_words(promotions.promo_name(promo, "uz_cyr")), [])
        self.assertEqual(latin_words(promotions.promo_conditions(promo, "uz_cyr")), [])
        self.assertEqual(promotions.promo_name(promo, "ru"), "Стевия — постоянный бонус")
        self.assertEqual(promotions.promo_name(promo, "uz"), "Stevia — doimiy bonus")

    def test_rule_line_and_block_in_cyrillic(self):
        line = promotions.rule_line(RULE, "uz_cyr")
        self.assertEqual(latin_words(line), [], line)
        self.assertIn("совға", line)
        block = promotions.rule_block(RULE, "uz_cyr")
        self.assertEqual(latin_words(block), [], block)
        self.assertIn("<b>БЕПУЛ</b>", block)       # tags survive the transliteration
        self.assertIn("<s>", block)

    def test_rule_in_russian_uses_russian_names(self):
        line = promotions.rule_line(RULE, "ru")
        self.assertIn("Миндальная мука 200г", line)
        self.assertIn("в подарок", line)
        self.assertEqual(latin_words(line), [], line)

    def test_latin_page_unchanged(self):
        self.assertEqual(promotions.rule_line(RULE, "uz"),
                         "1 dona Bodom uni 200gr → 100 gr Eritritol sovg'a")


class SetNameTest(unittest.TestCase):
    SET = {"id": 3, "name": "Keto nonushta seti", "name_ru": "Кето-завтрак набор",
           "set_price": 200000, "image_url": None}

    def test_set_name_per_language(self):
        self.assertEqual(webapp_server._serialize_set(self.SET, "uz")["name"], "Keto nonushta seti")
        self.assertEqual(latin_words(webapp_server._serialize_set(self.SET, "uz_cyr")["name"]), [])
        self.assertEqual(webapp_server._serialize_set(self.SET, "ru")["name"], "Кето-завтрак набор")


class BrandTest(unittest.TestCase):
    def test_mct_stays_latin(self):
        # "MCT yog'i" came out "МCТ ёғи": C has no Uzbek letter.
        self.assertEqual(lat_to_cyr("MCT yog'i 500ml"), "MCT ёғи 500мл")


class MiniAppTextsTest(unittest.TestCase):
    """The checkout's pickup texts used to be hard-coded Latin Uzbek."""
    INDEX = os.path.join(os.path.dirname(__file__), "..", "webapp", "index.html")

    def test_no_hard_coded_pickup_texts_and_keys_in_both_languages(self):
        with open(self.INDEX, encoding="utf-8") as f:
            html = f.read()
        script = html[html.index("const L = {"):]
        ru_at = script.index("\n  ru: {")
        for key in ("lblReceiveMode", "modeDelivery", "modePickup", "pickupAddressTitle", "openOnMap"):
            self.assertIn(f"\n    {key}: '", script[:ru_at], key)
            self.assertIn(f"\n    {key}: '", script[ru_at:], key)
        # Outside the uz table no code line spells these out any more.
        rest = script[script.index("function buildActiveLocale"):]
        for text in ("Xaritada ochish", "Olib ketish manzili", "'🏪 Olib ketish'"):
            self.assertNotIn(text, rest, text)
        self.assertNotIn("Ketочки", html)
        self.assertIn("'MCT'", html[html.index("const _UZ_BRANDS"):][:200])


if __name__ == "__main__":
    unittest.main()
