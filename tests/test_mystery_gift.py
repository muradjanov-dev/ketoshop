"""Sirli sovg'a — 400 000 so'mdan yuqori buyurtmalarga (2026-09-19)."""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import mystery_gift as mg
from config import MYSTERY_GIFT_FROM


class ThresholdTest(unittest.TestCase):
    def test_exactly_on_the_line_qualifies(self):
        self.assertTrue(mg.qualifies(MYSTERY_GIFT_FROM))

    def test_one_som_short_does_not(self):
        self.assertFalse(mg.qualifies(MYSTERY_GIFT_FROM - 1))

    def test_empty_cart(self):
        self.assertFalse(mg.qualifies(0))
        self.assertFalse(mg.qualifies(None))


class HintTest(unittest.TestCase):
    def test_reached_says_it_is_theirs(self):
        self.assertIn("Sirli sovg'a", mg.cart_hint(MYSTERY_GIFT_FROM, "uz"))

    def test_near_counts_down(self):
        hint = mg.cart_hint(MYSTERY_GIFT_FROM - 50_000, "uz")
        self.assertIn("50 000", hint)

    def test_far_away_stays_quiet(self):
        # A nudge for a sum they were never going to spend reads as an ad.
        self.assertEqual(mg.cart_hint(MYSTERY_GIFT_FROM - mg.NEAR_WINDOW - 1, "uz"), "")

    def test_never_names_the_gift(self):
        # The intrigue is the offer: no line may say what is in the box.
        for lang in ("uz", "uz_cyr", "ru"):
            for line in (mg.card_line(lang), mg.cart_hint(MYSTERY_GIFT_FROM, lang),
                         mg.order_line(MYSTERY_GIFT_FROM, lang)):
                self.assertNotIn("Eritritol", line)
                self.assertNotIn("Stevia", line)


class LanguageTest(unittest.TestCase):
    def test_every_buyer_language_is_covered(self):
        for lang in ("uz", "uz_cyr", "ru"):
            for line in (mg.card_line(lang), mg.free_delivery_card_line(lang),
                         mg.cart_hint(MYSTERY_GIFT_FROM, lang)):
                self.assertTrue(line and not line.startswith("["), (lang, line))

    def test_cyrillic_is_really_cyrillic(self):
        self.assertIn("СИРЛИ", mg.card_line("uz_cyr"))

    def test_russian_is_not_uzbek(self):
        self.assertNotEqual(mg.card_line("ru"), mg.card_line("uz"))


class AdminNoteTest(unittest.TestCase):
    def test_packing_note_only_when_earned(self):
        # Nothing else tells the packer: the gift has no order line.
        self.assertTrue(mg.admin_note(MYSTERY_GIFT_FROM))
        self.assertEqual(mg.admin_note(MYSTERY_GIFT_FROM - 1), "")


if __name__ == "__main__":
    unittest.main()
