import os
import unittest
from datetime import datetime

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")

import gift_campaign as g


class GiftReminderTextTest(unittest.TestCase):
    UNTIL = datetime(2026, 10, 17)

    def test_both_segments_all_languages(self):
        for seg in ("new", "again"):
            for lang in ("uz", "uz_cyr", "ru"):
                text = g.reminder_text(seg, lang, self.UNTIL)
                self.assertIn("17.10.2026", text)
                self.assertLess(len(text), 1024)          # fits a photo caption
                self.assertEqual(text.count("<b>"), text.count("</b>"))

    def test_wording(self):
        self.assertIn("Xabaringiz bormi?", g.reminder_text("new", "uz", self.UNTIL))
        self.assertIn("Yana sovg'a olishni istaysizmi?", g.reminder_text("again", "uz", self.UNTIL))
        self.assertIn("Хотите ещё один подарок?", g.reminder_text("again", "ru", self.UNTIL))
        self.assertIn("Хабарингиз борми?", g.reminder_text("new", "uz_cyr", self.UNTIL))

    def test_no_pressure_words(self):
        for seg in ("new", "again"):
            for lang in ("uz", "ru"):
                low = g.reminder_text(seg, lang, self.UNTIL).lower()
                for word in ("faqat bugun", "shoshiling", "только сегодня", "успейте", "последний шанс"):
                    self.assertNotIn(word, low)

    def test_gift_line_detection(self):
        self.assertTrue(g.has_gift_line('[{"name": "Eritritol 100gr", "is_bonus": true, "is_gift": true}]'))
        self.assertFalse(g.has_gift_line('[{"name": "Promo bonus", "is_bonus": true}]'))
        self.assertFalse(g.has_gift_line("not json"))
        self.assertFalse(g.has_gift_line(None))

    def test_scheduled_once_for_the_right_morning(self):
        self.assertEqual(str(g.REMINDER_FROM), "2026-10-03")
        self.assertEqual(g.REMINDER_WINDOW, (9, 12))


if __name__ == "__main__":
    unittest.main()
