"""«Bugungi g'oya» bloklari: qaysi mahsulotga qaysi g'oya, uch tilda, uzunlik."""
import os
import re
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import product_ideas as pi
import product_descriptions as pd
from translit import lat_to_cyr

# The idea shares Telegram's 1024-character photo caption with the product
# description (650) and the price/stock lines (~250), so it has to stay small.
IDEA_MAX = 220


class IdeaTextTest(unittest.TestCase):
    def test_every_idea_has_both_languages(self):
        for key, entry in pi.IDEAS.items():
            self.assertIn("uz", entry, key)
            self.assertIn("ru", entry, key)
            self.assertTrue(entry["uz"].strip() and entry["ru"].strip(), key)

    def test_ideas_fit_the_caption_budget(self):
        for key, entry in pi.IDEAS.items():
            for lang in ("uz", "ru"):
                self.assertLessEqual(len(entry[lang]), IDEA_MAX, f"{key}/{lang}")

    def test_every_key_is_a_real_family(self):
        # A typo'd key would simply never fire, silently.
        for key in pi.IDEAS:
            self.assertIn(key, pd.FAMILY, key)

    def test_uzbek_transliterates_cleanly(self):
        for key, entry in pi.IDEAS.items():
            cyr = lat_to_cyr(entry["uz"]).replace("°C", "")
            self.assertEqual(re.findall(r"[a-zA-Z]", cyr), [], key)


class IdeaBlockTest(unittest.TestCase):
    def test_block_for_a_known_product(self):
        for lang in ("uz", "uz_cyr", "ru"):
            block = pi.idea_block("Eritritol 500gr", lang)
            self.assertTrue(block, lang)
            self.assertIn("\n", block)

    def test_cyrillic_heading_is_transliterated(self):
        block = pi.idea_block("Eritritol 500gr", "uz_cyr")
        self.assertNotIn("Bugungi", block)
        self.assertIn("Бугунги", block)

    def test_unknown_product_gets_nothing(self):
        # Better no heading than a heading with nothing under it.
        self.assertIsNone(pi.idea_block("Alla balla qutisi", "uz"))
        self.assertIsNone(pi.idea_block("", "uz"))

    def test_sizes_of_one_product_share_an_idea(self):
        self.assertEqual(pi.idea_block("Bodom uni 200gr", "uz"),
                         pi.idea_block("Bodom uni 1000gr", "uz"))


class OrderIdeaTest(unittest.TestCase):
    ITEMS = [
        {"name": "Eritritol 500gr", "price": 74000, "quantity": 1},
        {"name": "Bodom uni 1000gr", "price": 120000, "quantity": 2},
        {"name": "Sovg'a", "price": 0, "quantity": 1, "is_gift": True},
    ]

    def test_picks_the_priciest_line(self):
        # The biggest line is what the buyer came for.
        block = pi.order_idea_block(self.ITEMS, "uz")
        self.assertIn("pechene", block)          # the almond-flour idea

    def test_gift_lines_are_ignored(self):
        only_gift = [{"name": "Eritritol", "price": 0, "quantity": 1, "is_gift": True}]
        self.assertIsNone(pi.order_idea_block(only_gift, "uz"))

    def test_falls_through_to_a_line_we_have_an_idea_for(self):
        # Salmon has no idea; the sweetener does, even though it costs less.
        items = [{"name": "Losos tushonkasi", "price": 90000, "quantity": 1},
                 {"name": "Eritritol 500gr", "price": 74000, "quantity": 1}]
        block = pi.order_idea_block(items, "uz")
        self.assertIsNotNone(block)
        self.assertIn("kakao", block.lower())

    def test_nothing_recognised_means_no_block(self):
        self.assertIsNone(pi.order_idea_block(
            [{"name": "Losos tushonkasi", "price": 90000, "quantity": 1}], "uz"))
        self.assertIsNone(pi.order_idea_block([], "uz"))
        self.assertIsNone(pi.order_idea_block(None, "uz"))

    def test_malformed_lines_do_not_crash(self):
        items = [{"name": "Eritritol", "price": "x", "quantity": None},
                 "not a dict", {"quantity": 1}]
        pi.order_idea_block(items, "uz")     # must not raise


class SweetenerReachTest(unittest.TestCase):
    """The sweetener push: every family whose product is baked or brewed
    should suggest it, because that is when the buyer needs it."""

    def test_baking_families_suggest_a_sweetener(self):
        import reco_content
        for key in ("almond_flour", "coconut", "cacao", "pp_flour",
                    "rice_flour", "buckwheat", "chickpea", "chia"):
            pairs = reco_content.PAIRINGS.get(key, [])
            self.assertTrue(any(p["profile"] == "sweeteners" for p in pairs), key)


if __name__ == "__main__":
    unittest.main(verbosity=1)
