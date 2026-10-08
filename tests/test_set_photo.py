"""Mini App rasm manzili: Telegram file_id proksi orqali, /admin'da
yuklangan rasm (setlar) — o'z manzili bilan."""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from webapp_server import photo_url


class PhotoUrlTest(unittest.TestCase):
    def test_telegram_file_id_goes_through_the_proxy(self):
        self.assertEqual(photo_url("AgACAgIAAxkBAAIB"), "/api/photo/AgACAgIAAxkBAAIB")

    def test_uploaded_set_image_is_served_as_is(self):
        self.assertEqual(photo_url("/img/7"), "/img/7")
        self.assertEqual(photo_url("https://keto.standart-eko.uz/img/7"),
                         "https://keto.standart-eko.uz/img/7")

    def test_no_image(self):
        self.assertIsNone(photo_url(None))
        self.assertIsNone(photo_url(""))


if __name__ == "__main__":
    unittest.main()
