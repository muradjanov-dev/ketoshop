"""O'zbekcha kirill (rus klaviaturasida ham) — javob kirillda (2026-11-21 suhbatlar tahlili)."""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ai_sales as a


class DetectTest(unittest.TestCase):
    def test_uzbek_typed_on_a_russian_keyboard(self):
        for q in ("Мана шу Кето сомса ретцептиздан нечта сомса чикади", "Бодом уни кере кимдан олса булади",
                  "Сабаби ботга кириб заказ расмийлаштирвотти", "Унда стевия + алюлоза олган яхшими",
                  "Мана шу шоколадный гранулани таркиби?", "Хоп"):
            self.assertTrue(a.writes_uzbek_cyrillic(q, "uz"), q)

    def test_russian_stays_russian(self):
        for q in ("Где мой заказ?", "Сколько стоит миндальная мука?", "Она по руски не понимает"):
            self.assertFalse(a.writes_uzbek_cyrillic(q, "uz"), q)
        self.assertFalse(a.writes_uzbek_cyrillic("Наргиза", "ru"))   # a tie goes by the bot language
        self.assertTrue(a.writes_uzbek_cyrillic("Наргиза", "uz"))


class PolishTest(unittest.TestCase):
    def test_latin_reply_to_uzbek_cyrillic_becomes_cyrillic_links_kept(self):
        out = a.polish_reply("Bodom uni bizda bor, buyurtma uchun @ketoshopbot ga yozing: https://t.me/ketoshopbot/shop",
                             "uz", customer_text="Бодом уни кере кимдан олса булади")
        self.assertIn("Бодом уни бизда бор", out)
        self.assertIn("@ketoshopbot", out)
        self.assertIn("https://t.me/ketoshopbot/shop", out)

    def test_russian_reply_untouched(self):
        self.assertEqual(a.polish_reply("Миндальная мука — 90 000 сум.", "ru", customer_text="Сколько стоит?"),
                         "Миндальная мука — 90 000 сум.")


if __name__ == "__main__":
    unittest.main()
