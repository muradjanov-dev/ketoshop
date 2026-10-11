"""Mahsulot qo'llanmasi (2026-10-11): qaysi mahsulotga qaysi qo'llanma, matn
qoidalari, 100 g dagi raqamlar va kun mahsuloti bilan birga yuborilishi.

Hech qanday haqiqiy xabar yuborilmaydi — bot to'liq mock.
"""
import asyncio
import os
import re
import unittest
from unittest import mock

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import product_card
import product_guides as pg
import product_of_day
from product_guides_content import GUIDES, NUTRITION, NUTRI_NOTE
from translit import lat_to_cyr

TG_TEXT_MAX = 4096


class MatchTest(unittest.TestCase):
    # Real names from the live catalogue (2026-10-11), including the ones a
    # careless order of rules would put in the wrong place.
    CASES = {
        "Ksantan kamedi 100g": "xanthan",
        "Psillium sheluxa 150gr": "psyllium",
        "Psillium uni 300gr": "psyllium",
        "Toza Steviya 20gr": "stevia_pure",
        "TOZA STEVIA 1000G": "stevia_pure",
        "Stevia 500g": "stevia",
        "Alluloza +Steviya 200gr": "allulose_stevia",
        "Alluloza 1000gr": "allulose",
        "Eritrtitol 1000gr": "erythritol",
        "Keto muzqaymoqlari (Shokolad, kakao)": "keto_icecream",
        "Kakao nibs 200gr": "cacao_nibs",
        "«Победа» 100% Charged с цельным фундуком": "chocolate",
        "Шоколад Победа 57%": "chocolate",
        "Qora shokolad granula (shakarsiz) 1000g": "chocolate",
        "Kokos yog‘i 400 gr extra vergin": "coconut_oil",
        "Kokos slivka 400ml": "coconut_cream",
        "Kokos shakari 250gr": "coconut_sugar",
        "Kokos uni 500gr": "coconut_flour",
        "Kokos chipsi 100g": "coconut_flakes",
        "Uy kuvi saryog'i 800gr": "ghee_butter",
        "Tabiiy GHEE 1000ml": "ghee_butter",
        "Зайтун ёғи совуқ сиқим- Extra vergin": "olive_oil",
        "Zaytun yog‘i Ispaniya (5 l, qovurish uchun)": "olive_oil",
        "Xandonpista pastasi 200gr": "nut_paste",
        "Yeryong'oq pasta 200gr": "nut_paste",
        "Pista mag'zi 500gr": "pistachio",
        "Fistashka uni 1000gr": "pistachio_flour",
        "Arpabodiyon (fenxel) 100gr": "fennel",
        "Arpa uni": "barley_flour",
        "Kepakli bug'doy uni 500g «Кудесница»": "wholewheat_flour",
        "Kepak. -o‘rtacha kattalikda (sredniy)": "bran",
        "bulgur guruchi 1000gr": "bulgur",
        "Qizil guruch (Devzira) (bo'yalmagan, yog'lanmagan) 500gr": "rice",
        "Guruch uni": "rice_flour",
        "Yashil grechka doni 500gr": "buckwheat",
        "Yashil grechka uni 500gr": "buckwheat_flour",
        "Jo'xori kraxmali 1000gr": "starch",
        "Makkajo'xori uni": "corn_flour",
        "Suli yormasi": "oats",
        "Ovsyanka uni 400g «Кудесница»": "oats",
        "2-nav un": "wheat_2nd",
        "Soya uni": "soy_flour",
        "Qora fermentlangan Solod 1kg": "malt",
        "Табиий ҳамиртуруш— закваска": "sourdough",
        "Qora sedana 200gr": "nigella",
        "Qora kunjut 300gr": "sesame",
        "Qovoq urugʻi 200gr": "pumpkin_seed",
        "Zig'ir uni 400g «Кудесница»": "flax",
        "Chia urug'i 600gr": "chia",
        "Rastaropsha urug'i 300gr": "milk_thistle",
        "Zomin tog‘ asali 700 gr": "honey",
        "Olma sirkasi (Toshkent) 5% 500ml": "vinegar",
        "Himalay tuz 500gr": "salt",
        "Koritsa 70g": "cinnamon",
        "Losos baliq tushonkasi 1L": "salmon",
        "Bodom uni 1000gr": "almond_flour",
        "Polba uni": "spelt_flour",
        "Javdar uni": "rye_flour",
        "No'xat uni": "chickpea_flour",
    }

    def test_real_names_land_on_the_right_guide(self):
        for name, key in self.CASES.items():
            self.assertEqual(pg.guide_key(name), key, name)

    def test_unknown_name_gets_no_guide(self):
        self.assertIsNone(pg.guide_key("Telefon g'ilofi"))
        self.assertIsNone(pg.guide_key(""))

    def test_every_rule_points_at_a_written_guide(self):
        # A rule for a key with no text would match and then crash on render.
        for key, _rx in pg._MATCH:
            self.assertIn(key, GUIDES, key)


class ContentTest(unittest.TestCase):
    def test_both_languages_and_all_sections(self):
        for key, g in GUIDES.items():
            for lang in ("uz", "ru"):
                e = g[lang]
                self.assertTrue(e["about"].strip(), f"{key}/{lang}")
                self.assertGreaterEqual(len(e["benefits"]), 3, f"{key}/{lang}")
                self.assertGreaterEqual(len(e["cautions"]), 2, f"{key}/{lang}")
                self.assertTrue(e["advice"].strip(), f"{key}/{lang}")

    def test_at_least_three_ways_to_use(self):
        # The owner's minimum (2026-10-11).
        for key, g in GUIDES.items():
            for lang in ("uz", "ru"):
                self.assertGreaterEqual(len(g[lang]["uses"]), 3, f"{key}/{lang}")
                self.assertEqual(len(g["uz"]["uses"]), len(g["ru"]["uses"]), key)

    def test_fits_one_telegram_message(self):
        long_name = "Juda uzun mahsulot nomi " * 6
        for key in GUIDES:
            for lang in ("uz", "uz_cyr", "ru"):
                body = pg._render(key, "ru" if lang == "ru" else "uz")
                if lang == "uz_cyr":
                    body = lat_to_cyr(body)
                self.assertLessEqual(len(body.replace("{name}", long_name)), TG_TEXT_MAX, f"{key}/{lang}")

    def test_uzbek_transliterates_cleanly(self):
        # A Latin letter left in the Cyrillic text means a spelling Uzbek has
        # no letter for. Tags, the name slot and °C are allowed to stay.
        for key in GUIDES:
            cyr = lat_to_cyr(pg._render(key, "uz"))
            cyr = re.sub(r"<[^>]+>|\{name\}|°C", "", cyr)
            self.assertEqual(re.findall(r"[a-zA-Z]+", cyr), [], key)

    def test_no_medical_claims(self):
        # Food, not medicine.
        banned = ("davolaydi", "davolash", "лечит", "излечива", "вылечива")
        for key in GUIDES:
            for lang in ("uz", "ru"):
                low = pg._render(key, lang).lower()
                for word in banned:
                    self.assertNotIn(word, low, f"{key}/{lang}: {word}")

    def test_no_raw_html_in_content(self):
        # The text goes out with parse_mode=HTML; a stray "<" or "&" breaks it.
        for key, g in GUIDES.items():
            for lang in ("uz", "ru"):
                e = g[lang]
                pieces = [e["about"], e["advice"], *e["benefits"], *e["cautions"],
                          *(t for pair in e["uses"] for t in pair)]
                for p in pieces:
                    self.assertNotRegex(p, r"[<>&]", f"{key}/{lang}")


class NutritionTest(unittest.TestCase):
    def test_every_guide_but_the_starter_has_figures(self):
        self.assertEqual(set(GUIDES) - set(NUTRITION), {"sourdough"})
        self.assertFalse(set(NUTRITION) - set(GUIDES))
        self.assertFalse(set(NUTRI_NOTE) - set(GUIDES))

    def test_keto_flag_is_known(self):
        for key, n in NUTRITION.items():
            self.assertIn(n["keto"], ("yes", "limited", "no"), key)

    def test_kcal_formula(self):
        # 4·p + 9·f + 4·c + 2·fiber, rounded to 10.
        self.assertEqual(pg._kcal(NUTRITION["almond_flour"]), 590)
        self.assertEqual(pg._kcal(NUTRITION["olive_oil"]), 900)
        self.assertEqual(pg._kcal(NUTRITION["erythritol"]), 20)      # explicit
        self.assertIsNone(pg._kcal(NUTRITION["chocolate"]))          # varies by %

    def test_gi_words(self):
        self.assertIn("ko'tarmaydi", pg._gi_text(0, "uz"))
        self.assertIn("past", pg._gi_text(45, "uz"))
        self.assertIn("o'rta", pg._gi_text(58, "uz"))
        self.assertIn("yuqori", pg._gi_text(95, "uz"))
        self.assertIn("высокий", pg._gi_text(95, "ru"))

    def test_block_in_the_guide(self):
        text = pg.guide_text({"name": "Bodom uni 500gr"}, "uz")
        self.assertIn("100 g da", text)
        self.assertIn("~590 kkal", text)
        self.assertIn("Glikemik indeks", text)
        self.assertIn("Ketoga mos", text)

    def test_unknown_gi_is_left_out_not_invented(self):
        text = pg.guide_text({"name": "Qora sedana 200gr"}, "uz")
        self.assertIn("100 g da", text)
        self.assertNotIn("Glikemik indeks", text)

    def test_card_line(self):
        self.assertEqual(pg.card_line("Bodom uni 500gr", "uz"),
                         "📊 100 g: ~590 kkal · uglevod 10 g · GI ~20 · ✅ keto")
        self.assertEqual(pg.card_line("Bodom uni 500gr", "ru"),
                         "📊 100 г: ~590 ккал · углеводы 10 г · ГИ ~20 · ✅ кето")
        cyr = pg.card_line("Bodom uni 500gr", "uz_cyr")
        self.assertIn("ккал", cyr)
        self.assertNotRegex(cyr, r"[a-zA-Z]")

    def test_card_line_only_with_real_figures(self):
        self.assertIsNone(pg.card_line("Zakvaska", "uz"))        # no figures at all
        self.assertIsNone(pg.card_line("Шоколад Победа 57%", "uz"))  # varies by %
        self.assertIsNone(pg.card_line("Telefon", "uz"))

    def test_card_lines_are_short(self):
        for key in NUTRITION:
            name = next(n for n, k in MatchTest.CASES.items() if k == key) \
                if key in MatchTest.CASES.values() else None
            if not name:
                continue
            for lang in ("uz", "uz_cyr", "ru"):
                line = pg.card_line(name, lang)
                if line:
                    self.assertLessEqual(len(line), 70, f"{key}/{lang}: {line}")


class GuideTextTest(unittest.TestCase):
    def test_three_languages(self):
        p = {"name": "Ksantan kamedi 100g", "name_ru": "Ксантановая камедь 100г"}
        uz = pg.guide_text(p, "uz")
        ru = pg.guide_text(p, "ru")
        cyr = pg.guide_text(p, "uz_cyr")
        self.assertIn("Ksantan kamedi 100g: qayerda va qanday ishlatiladi?", uz)
        self.assertIn("Ксантановая камедь 100г: где и как использовать?", ru)
        self.assertIn("Ксантан камеди 100г", cyr)
        self.assertNotIn("{name}", uz + ru + cyr)
        for t in (uz, cyr):
            self.assertIn("1️⃣", t)
            self.assertIn("3️⃣", t)

    def test_name_is_escaped(self):
        text = pg.guide_text({"name": "Bodom uni <b>&"}, "uz")
        self.assertIn("Bodom uni &lt;b&gt;&amp;", text)

    def test_unknown_product(self):
        self.assertIsNone(pg.guide_text({"name": "Telefon"}, "uz"))


def _caption_mocks():
    """Everything build_caption reads besides the product itself."""
    import bot_discount
    import gift_campaign
    import mystery_gift
    import promotions
    return [
        mock.patch.object(bot_discount, "reminder", mock.AsyncMock(return_value="🎁 " + "x" * 60)),
        mock.patch.object(gift_campaign, "card_line", mock.AsyncMock(return_value="🎁 " + "y" * 60)),
        mock.patch.object(mystery_gift, "card_line", return_value="🎁 " + "z" * 60),
        mock.patch.object(mystery_gift, "free_delivery_card_line", return_value="🚚 " + "w" * 60),
        mock.patch.object(promotions, "get_active", mock.AsyncMock(return_value=None)),
        mock.patch.object(promotions, "bonus_hint", return_value=None),
        mock.patch.object(product_card, "get_product_rating", mock.AsyncMock(return_value=(0, 0))),
    ]


class CardCaptionTest(unittest.TestCase):
    PRODUCT = {"id": 7, "name": "Ksantan kamedi 100g", "name_ru": None,
               "description": "Tavsif. " * 200, "description_ru": None,
               "price": 19000, "unit": "dona", "quantity": 20,
               "discount_percent": 0, "discount_until": None}

    def _caption(self, lang):
        patches = _caption_mocks()
        for p in patches:
            p.start()
        try:
            return asyncio.run(product_card.build_caption(dict(self.PRODUCT), lang, None))
        finally:
            for p in patches:
                p.stop()

    def test_card_carries_the_numbers_and_still_fits(self):
        for lang in ("uz", "uz_cyr", "ru"):
            text = self._caption(lang)
            self.assertIn("📊 100", text, lang)
            self.assertLessEqual(len(text), 1024, lang)
            # The long description was trimmed, the price survived.
            self.assertIn("19 000", text, lang)


class SpotlightTest(unittest.TestCase):
    def test_guided_product_drops_the_short_idea(self):
        extra = product_of_day.caption_extra({"name": "Ksantan kamedi 100g"})
        self.assertIsNone(extra("uz"))

    def test_unguided_product_keeps_the_idea(self):
        with mock.patch("product_ideas.idea_block", return_value="💡 g'oya"):
            extra = product_of_day.caption_extra({"name": "Telefon"})
            self.assertEqual(extra("uz"), "💡 g'oya")

    def test_buyer_gets_card_then_guide(self):
        bot = mock.AsyncMock()
        product = {"id": 7, "name": "Ksantan kamedi 100g", "quantity": 5}
        captions = mock.Mock()
        captions.get = mock.AsyncMock(return_value="caption")
        calls = []

        async def card(*a, **k):
            calls.append("card")

        bot.send_message.side_effect = lambda *a, **k: calls.append("guide")
        with mock.patch.object(product_card, "send_card", side_effect=card), \
             mock.patch("gamification.buyer_rate", mock.AsyncMock(return_value=0.005)), \
             mock.patch.object(product_of_day, "SEND_DELAY", 0):
            ok = asyncio.run(product_of_day._send_to_user(
                bot, 42, product, "uz", captions, {"uz": "📖 qo'llanma"}))
        self.assertTrue(ok)
        self.assertEqual(calls, ["card", "guide"])
        self.assertEqual(bot.send_message.call_args.args[:2], (42, "📖 qo'llanma"))

    def test_no_guide_when_the_card_failed(self):
        from aiogram.exceptions import TelegramForbiddenError
        bot = mock.AsyncMock()
        captions = mock.Mock()
        captions.get = mock.AsyncMock(return_value="caption")
        err = TelegramForbiddenError(method=mock.Mock(), message="blocked")
        with mock.patch.object(product_card, "send_card", mock.AsyncMock(side_effect=err)), \
             mock.patch("gamification.buyer_rate", mock.AsyncMock(return_value=0.005)):
            ok = asyncio.run(product_of_day._send_to_user(
                bot, 42, {"id": 7, "name": "x", "quantity": 1}, "uz", captions, {"uz": "g"}))
        self.assertFalse(ok)
        bot.send_message.assert_not_called()

    def test_guide_failure_does_not_fail_the_send(self):
        bot = mock.AsyncMock()
        bot.send_message.side_effect = RuntimeError("boom")
        captions = mock.Mock()
        captions.get = mock.AsyncMock(return_value="caption")
        with mock.patch.object(product_card, "send_card", mock.AsyncMock()), \
             mock.patch("gamification.buyer_rate", mock.AsyncMock(return_value=0.005)), \
             mock.patch.object(product_of_day, "SEND_DELAY", 0):
            ok = asyncio.run(product_of_day._send_to_user(
                bot, 42, {"id": 7, "name": "x", "quantity": 1}, "uz", captions, {"uz": "g"}))
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
