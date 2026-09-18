"""Buyurtma manzilidan viloyatni aniqlash."""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import regions as R


class FromTextTest(unittest.TestCase):
    def test_cities_and_districts(self):
        cases = {
            "Toshkent, Chilonzor 9-kv, 12-uy": "tashkent",
            "Toshkent, Sergeli 6-kv": "tashkent",
            "Samarqand, Registon ko'chasi 5": "samarkand",
            "Buxoro, Mustaqillik 4": "bukhara",
            "Andijon viloyati Andijon shahri": "andijan",
            "Namangan, Chust": "namangan",
            "Qarshi shahri": "kashkadarya",
            "Termiz": "surkhandarya",
            "Zomin tumani": "jizzakh",
            "Guliston": "syrdarya",
            "Navoiy, Zarafshon": "navoi",
            "Nukus": "karakalpakstan",
        }
        for addr, want in cases.items():
            self.assertEqual(R.region_from_text(addr), want, addr)

    def test_region_wins_over_the_capital(self):
        """Tashkent the province must not be counted as Tashkent the city.

        "Toshkent viloyati" contains "Toshkent", so checking the city first
        would have swallowed every province order into the capital.
        """
        for addr in ("Toshkent viloyati, Angren", "Ташкентская область",
                     "Angren", "Chirchiq", "Olmaliq"):
            self.assertEqual(R.region_from_text(addr), "tashkent_region", addr)

    def test_apostrophe_spellings_are_all_one_place(self):
        for addr in ("Farg'ona", "Fargʻona", "Fargona", "FARGONA", "Фергана"):
            self.assertEqual(R.region_from_text(addr), "fergana", addr)

    def test_russian_and_cyrillic_uzbek(self):
        self.assertEqual(R.region_from_text("Ургенч, Хорезм"), "khorezm")
        self.assertEqual(R.region_from_text("г. Ташкент, Чиланзар"), "tashkent")

    def test_unrecognised_is_none(self):
        self.assertIsNone(R.region_from_text("uyim, 3-qavat"))
        self.assertIsNone(R.region_from_text(""))
        self.assertIsNone(R.region_from_text(None))


class FromPinTest(unittest.TestCase):
    def test_city_centres(self):
        self.assertEqual(R.region_from_pin(41.31, 69.28), "tashkent")
        self.assertEqual(R.region_from_pin(40.78, 72.34), "andijan")
        self.assertEqual(R.region_from_pin(39.65, 66.96), "samarkand")

    def test_far_away_is_not_guessed(self):
        # A wrong province is worse than an honest "unknown".
        self.assertIsNone(R.region_from_pin(55.75, 37.62))     # Moscow
        self.assertIsNone(R.region_from_pin(0, 0))

    def test_bad_input(self):
        self.assertIsNone(R.region_from_pin(None, None))
        self.assertIsNone(R.region_from_pin("x", "y"))


class RegionOfTest(unittest.TestCase):
    def test_text_beats_pin(self):
        # The buyer's own words are more reliable than the nearest centre.
        order = {"address": "Andijon shahri", "latitude": 41.31, "longitude": 69.28}
        self.assertEqual(R.region_of(order), "andijan")

    def test_pin_used_when_text_says_nothing(self):
        order = {"address": "3-qavat, domofon 12", "latitude": 40.78, "longitude": 72.34}
        self.assertEqual(R.region_of(order), "andijan")

    def test_falls_back_to_unknown(self):
        self.assertEqual(R.region_of({"address": "uyim"}), R.UNKNOWN_KEY)
        self.assertEqual(R.region_of({}), R.UNKNOWN_KEY)

    def test_every_region_has_both_names(self):
        for key, uz, ru, centre, keywords in R.REGIONS:
            self.assertTrue(uz and ru, key)
            self.assertTrue(keywords, key)
            self.assertEqual(R.region_name(key, "uz"), uz)
            self.assertEqual(R.region_name(key, "ru"), ru)

    def test_no_keyword_is_claimed_by_two_regions(self):
        seen = {}
        for key, _uz, _ru, _c, keywords in R.REGIONS:
            for kw in keywords:
                n = R._norm(kw)
                self.assertNotIn(n, seen, f"{n}: {seen.get(n)} va {key}")
                seen[n] = key


if __name__ == "__main__":
    unittest.main(verbosity=1)
