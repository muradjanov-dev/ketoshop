"""Mahsulot tavsiflari: oilani nomdan topish, uch tilda to'g'ri chiqish, uzunlik."""
import os
import re
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import product_descriptions as pd
from translit import lat_to_cyr

# What the product card can hold once price/stock/discount lines are added —
# see handlers.catalog.DESC_IN_CARD_MAX.
CARD_LIMIT = 650


class FamilyMatchTest(unittest.TestCase):
    def test_real_product_names_land_on_the_right_family(self):
        cases = {
            "Bodom uni 500gr": "almond_flour",
            "Eritritol 1kg": "sweeteners",
            "Chia urug'i 250gr": "chia",
            "Kokos uni 1000gr": "coconut",
            "Zomin tog' asali 700 gr": "honey",
            "Psillium 200gr": "fiber_supp",
            "Losos baliq tushonkasi 1L": "fish",
            "Himalay tuzi 500gr": "salt",
            "Olma sirkasi 500ml": "vinegar",
        }
        for name, want in cases.items():
            self.assertEqual(pd.family_key(name), want, name)

    def test_form_beats_ingredient(self):
        """"Bodom yog'i" is an OIL, not almond flour.

        The family matcher was written for the recommendation broadcast,
        where either answer works. A description has to be right: the almond
        entry talks about replacing wheat flour, which is nonsense on a
        bottle of oil.
        """
        for name in ("Bodom yog'i", "Kokos yog'i 400 gr", "Zig'ir yog'i 250ml",
                     "Kunjut yog'i", "Qovoq urug'i yog'i", "Uy kuvi saryog'i",
                     "Zaytun yog‘i Ispaniya", "MCT yog'", "Avokado moyi"):
            self.assertEqual(pd.family_key(name), "oils", name)

        for name in ("Bodom pastasi 300gr", "Kunjut pastasi (tahini)",
                     "Kokos pastasi", "Yeryong'oq pasta 200gr"):
            self.assertEqual(pd.family_key(name), "pastes", name)

    def test_unoiled_is_not_an_oil(self):
        # "yog'lanmagan" (unoiled) contains "yog'" but describes rice.
        self.assertEqual(
            pd.family_key("Qizil guruch (Devzira) (bo'yalmagan, yog'lanmagan) 1000gr"),
            "diet_rice")

    def test_flour_keeps_its_ingredient_family(self):
        self.assertEqual(pd.family_key("Bodom uni 500gr"), "almond_flour")
        self.assertEqual(pd.family_key("Zig'ir uni 300gr"), "flax")

    def test_cyrillic_name_still_matches(self):
        # Some products are keyed into the shop in Cyrillic; the matcher
        # transliterates before comparing.
        self.assertEqual(pd.family_key("Эритрит 500гр"), "sweeteners")

    def test_unknown_name_reports_itself(self):
        uz, ru, key = pd.describe("Alla balla qutisi")
        self.assertIsNone(key)          # caller can surface it
        self.assertTrue(uz and ru)      # but still gets usable text


class TextShapeTest(unittest.TestCase):
    def _all_texts(self):
        for key, entry in pd.FAMILY.items():
            yield key, "uz", pd._build("uz", **entry["uz"])
            yield key, "ru", pd._build("ru", **entry["ru"])

    def test_every_family_has_both_languages(self):
        for key, entry in pd.FAMILY.items():
            self.assertIn("uz", entry, key)
            self.assertIn("ru", entry, key)

    def test_every_text_fits_the_product_card(self):
        for key, lang, text in self._all_texts():
            self.assertLessEqual(len(text), CARD_LIMIT, f"{key}/{lang}")

    def test_cyrillic_render_also_fits(self):
        # Cyrillic is produced at display time, and can come out longer.
        for key, entry in pd.FAMILY.items():
            cyr = lat_to_cyr(pd._build("uz", **entry["uz"]))
            self.assertLessEqual(len(cyr), CARD_LIMIT, key)

    def test_uzbek_transliterates_cleanly(self):
        # A stray Latin letter in the Cyrillic output means the source used a
        # spelling Uzbek Latin has no letter for — "pancake" became "панcаке".
        # °C is a unit symbol and is allowed to stay.
        for key, entry in pd.FAMILY.items():
            cyr = lat_to_cyr(pd._build("uz", **entry["uz"])).replace("°C", "")
            stray = re.findall(r"[a-zA-Z]", cyr)
            self.assertEqual(stray, [], f"{key}: {stray}")

    def test_sections_are_present(self):
        for key, lang, text in self._all_texts():
            self.assertIn(pd._H[lang]["benefits"], text, f"{key}/{lang}")
            self.assertIn(pd._H[lang]["use"], text, f"{key}/{lang}")
            self.assertIn(pd._H[lang]["keep"], text, f"{key}/{lang}")

    def test_no_medical_claims(self):
        # Food, not medicine: "davolaydi" / "лечит" must never appear.
        banned = ("davolaydi", "davolash", "лечит", "излечива", "вылечива")
        for key, lang, text in self._all_texts():
            low = text.lower()
            for word in banned:
                self.assertNotIn(word, low, f"{key}/{lang}: {word}")


class DescribeTest(unittest.TestCase):
    def test_returns_three_parts(self):
        uz, ru, key = pd.describe("Bodom uni 200gr")
        self.assertEqual(key, "almond_flour")
        self.assertIn("Bodom", uz)
        self.assertIn("миндал", ru.lower())

    def test_same_family_different_sizes_share_text(self):
        a = pd.describe("Bodom uni 200gr")[0]
        b = pd.describe("Bodom uni 1000gr")[0]
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main(verbosity=1)
