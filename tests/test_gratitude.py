"""gratitude — minnatdorchilikka samimiy tashakkur (egasi, 2026-11-24)."""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import gratitude  # noqa: E402


class GratitudeTest(unittest.TestCase):
    def setUp(self):
        gratitude._last_full.clear()

    def test_thanks_messages_are_recognised(self):
        for text in ("rahmat", "Katta rahmat!", "Assalomu alaykum, katta rahmat", "спасибо большое",
                     "Раҳмат", "rahmat sizlarga", "chin dildan rahmat 🙏"):
            self.assertTrue(gratitude.is_thanks(text), text)
        for text in ("rahmat, bodom uni bormi?", "eritritol bormi", "ok", "ha"):
            self.assertFalse(gratitude.is_thanks(text), text)

    def test_reply_opens_with_salom_or_alik_and_says_the_mission(self):
        text = gratitude.reply("uz", "katta rahmat")
        self.assertTrue(text.startswith("Assalomu alaykum!"))
        self.assertIn("100% tabiiy", text)
        self.assertIn("qo'limizdan kel", text)
        alik = gratitude.reply("uz", "Assalomu alaykum, rahmat")
        self.assertTrue(alik.startswith("Va alaykum assalom!"))
        self.assertTrue(gratitude.reply("ru", "спасибо").startswith("Здравствуйте!"))
        self.assertIn("натуральн", gratitude.reply("ru", "спасибо"))
        self.assertTrue(gratitude.reply("uz_cyr", "раҳмат").startswith("Ассалому алайкум!"))

    def test_second_thanks_the_same_day_gets_a_short_warm_reply(self):
        first = gratitude.reply("uz", "rahmat", user_id=7)
        second = gratitude.reply("uz", "rahmat", user_id=7)
        self.assertIn("100% tabiiy", first)
        self.assertNotIn("100% tabiiy", second)
        self.assertIn(second, [uz for uz, _ in gratitude.SHORT])

    def test_language_follows_the_customer_message(self):
        self.assertEqual(gratitude.language("спасибо", "uz"), "ru")
        self.assertEqual(gratitude.language("раҳмат", "uz"), "uz_cyr")
        self.assertEqual(gratitude.language("rahmat", "ru"), "uz")
        self.assertEqual(gratitude.language("🙏", "ru"), "ru")


if __name__ == "__main__":
    unittest.main()
