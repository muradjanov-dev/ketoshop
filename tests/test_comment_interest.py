"""«+» izohi — qiziqish: mahsulot, narx va buyurtma yo'li (egasi, 2026-11-28)."""
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import comment_ai as c


class InterestTest(unittest.TestCase):
    def test_detects_interest_only(self):
        for t in ("+", "++", "+1", "Narx", "info", "цена", "+ 😍", "Batafsil"):
            self.assertTrue(c.is_interest(t), t)
        for t in ("Zo'r", "Assalomu alaykum", "Rahmat", "Bu qancha turadi, yetkazasizmi?"):
            self.assertFalse(c.is_interest(t), t)

    def test_prompt_hint_and_rule(self):
        p = c.comment_prompt({"platform": "ig", "text": "+", "username": "x", "post_caption": "Bodom uni"})
        self.assertIn("QIZIQISH", p)
        self.assertNotIn("QIZIQISH", c.comment_prompt({"platform": "ig", "text": "Rahmat", "username": "x"}))
        self.assertIn('"+" bu rahmat EMAS', c.RULES)

    def test_bare_greeting_gets_order_path(self):
        out = c.finalize("+", "Assalomu alaykum 🙂")
        self.assertIn("ketoshop_uz", out)
        self.assertIn("Direct", out)
        kept = c.finalize("+", "Assalomu alaykum! Bodom uni 1000gr — 162 000 so'm")
        self.assertNotIn("ketoshop_uz", kept)
        self.assertNotIn("ketoshop_uz", c.finalize("Rahmat", "Sizga ham rahmat 🙂"))

    def test_long_caption_keeps_video_summary(self):
        cap = "x" * 1500 + " VIDEO MAZMUNI (ovozi va kadrlaridan): Bodom unidan non"
        p = c.comment_prompt({"platform": "ig", "text": "+", "username": "x", "post_caption": cap})
        self.assertIn("Bodom unidan non", p)


if __name__ == "__main__":
    unittest.main()
