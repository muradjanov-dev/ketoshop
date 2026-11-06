"""Yashil va oddiy grechka chalkashmaydi (egasi, 2026-11-06: kun mahsuloti
oddiy «Grechka uni» rasmi ostida yashil grechka matni bilan chiqdi).
Katalogdagi barcha grechka nomlari tekshiriladi. Bazaga ulanmaydi."""
import os
import re
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import personal_recommend
import product_descriptions as pd
import product_ideas

GREEN = re.compile(r"yashil|qovurilmagan|undir|зел[её]н|необжар|пророщ", re.I)

# Every grechka product in the shop on 2026-11-06.
PLAIN = ["Grechka uni", "Grechka uni 400g «Кудесница»", "Grechka unli vermishel makaron 500g"]
GREEN_NAMES = ["Yashil grechka uni 500gr", "Yashil grechka uni 1000gr",
               "Yashil grechka doni 500gr", "Yashil grechka doni 1000gr"]


class GreenOrPlainTest(unittest.TestCase):
    def test_profiles(self):
        for name in PLAIN:
            self.assertEqual(personal_recommend.name_profile(name)["key"], "buckwheat_plain", name)
        for name in GREEN_NAMES:
            self.assertEqual(personal_recommend.name_profile(name)["key"], "buckwheat", name)
        self.assertEqual(personal_recommend.name_profile("Яшил гречка уни")["key"], "buckwheat")
        self.assertEqual(personal_recommend.name_profile("Гречневая мука")["key"], "buckwheat_plain")

    def test_plain_flour_never_says_green(self):
        for name in ("Grechka uni", "Grechka uni 400g «Кудесница»"):
            self.assertEqual(pd.family_key(name), "buckwheat_plain_flour", name)
            uz, ru, _ = pd.describe(name)
            self.assertNotRegex(uz, GREEN, name)
            self.assertNotRegex(ru, GREEN, name)
            self.assertIn("Oddiy grechka", uz)
            for lang in ("uz", "ru", "uz_cyr"):
                self.assertNotRegex(product_ideas.idea_block(name, lang) or "", GREEN, (name, lang))

    def test_plain_grechka_recipes_never_say_green(self):
        product = {"name": "Grechka uni", "category": "keto_flour"}
        for seed in range(6):
            for lang in ("uz", "ru", "uz_cyr"):
                block = product_ideas.recipe_block(product, lang, seed)
                self.assertTrue(block)
                self.assertNotRegex(block, GREEN, (seed, lang))
        prof = personal_recommend.name_profile("Grechka uni")
        for b in prof["benefits"]:
            self.assertNotRegex(b["uz"] + b["ru"], GREEN)

    def test_green_keeps_its_green_text(self):
        uz, ru, key = pd.describe("Yashil grechka uni 500gr")
        self.assertEqual(key, "buckwheat_flour")
        self.assertIn("Yashil grechkadan", uz)
        self.assertIn("зелёной гречки", ru)
        uz, _, key = pd.describe("Yashil grechka doni 500gr")
        self.assertEqual(key, "buckwheat")
        self.assertIn("yashil grechka", uz.lower())

    def test_pasta_is_not_described_as_green_grain(self):
        uz, ru, _ = pd.describe("Grechka unli vermishel makaron 500g")
        self.assertNotRegex(uz, GREEN)
        self.assertNotRegex(ru, GREEN)


if __name__ == "__main__":
    unittest.main()
