"""Telegram'ga ketadigan xabarlar uchun himoya: HTML xatosi va uzunlik."""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import tg_safety


class StripMarkupTest(unittest.TestCase):
    def test_tags_go_entities_resolve(self):
        self.assertEqual(tg_safety.strip_markup("<b>Salom</b> &amp; xayr"), "Salom & xayr")

    def test_comparison_is_not_eaten_as_a_tag(self):
        # "narx < 50000 va a > b" must survive: a "<" not followed by a letter
        # is not a tag, and treating it as one swallowed whole sentences.
        text = "narx < 50000 va a > b"
        self.assertEqual(tg_safety.strip_markup(text), text)


class TruncateTest(unittest.TestCase):
    def test_short_text_untouched(self):
        self.assertEqual(tg_safety.truncate("qisqa", 100), "qisqa")

    def test_long_text_is_cut_to_the_limit(self):
        out = tg_safety.truncate("a" * 200, 50)
        self.assertEqual(len(out), 50)
        self.assertTrue(out.endswith("…"))

    def test_markup_is_stripped_before_cutting(self):
        # Slicing raw HTML can leave "<b" dangling, which Telegram rejects in
        # turn — so the retry would fail exactly like the original.
        out = tg_safety.truncate("<b>" + "a" * 100 + "</b>", 20)
        self.assertNotIn("<", out)
        self.assertEqual(len(out), 20)

    def test_caption_limit_is_the_telegram_one(self):
        self.assertEqual(tg_safety._MAX_LEN["caption"], 1024)
        self.assertEqual(tg_safety._MAX_LEN["text"], 4096)

    def test_empty_is_safe(self):
        self.assertEqual(tg_safety.truncate("", 10), "")
        self.assertEqual(tg_safety.truncate(None, 10), "")


if __name__ == "__main__":
    unittest.main(verbosity=1)
