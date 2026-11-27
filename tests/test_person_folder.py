"""Mijoz papkasi va 5 soatlik salom qoidasi (person_folder.py, egasi 2026-11-27)."""
import asyncio
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ai_tone
import comment_ai
import person_folder as pf

NOW = datetime(2026, 11, 27, 12, 0)


def _row(hours_ago, them="savol", us="javob", channel="bot"):
    return {"at": NOW - timedelta(hours=hours_ago), "channel": channel, "them": them, "us": us}


class GreetingTest(unittest.TestCase):
    def test_hours_since_last_reply_ignores_unanswered(self):
        rows = [_row(7), _row(0.1, us="")]
        self.assertAlmostEqual(pf.hours_since_reply(rows, NOW), 7)
        self.assertIsNone(pf.hours_since_reply([_row(1, us="")], NOW))

    def test_five_hour_rule(self):
        self.assertTrue(pf.needs_greeting(None))
        self.assertTrue(pf.needs_greeting(5))
        self.assertFalse(pf.needs_greeting(4.9))
        self.assertIn("SALOM BERMA", pf.greeting_rule(0.5))
        self.assertIn("qisqa salom", pf.greeting_rule(6))
        self.assertIn("3 kun", pf.greeting_rule(72))

    def test_greet_first(self):
        self.assertEqual(ai_tone.greet_first("bodom uni bor", "uz", True), "Assalomu alaykum! Bodom uni bor")
        self.assertEqual(ai_tone.greet_first("Есть", "ru", True), "Здравствуйте! Есть")
        self.assertEqual(ai_tone.greet_first("Salom! Bor", "uz", True), "Salom! Bor")
        self.assertEqual(ai_tone.greet_first("Bor", "uz", False), "Bor")


class KeyTest(unittest.TestCase):
    def test_keys(self):
        self.assertEqual(pf.folder_key("ig", "@Ali.Uz "), "ig:ali.uz")
        self.assertEqual(pf.folder_key("tg", 42), "tg:42")
        self.assertIsNone(pf.folder_key("ig", ""))


class BlockTest(unittest.TestCase):
    def _block(self, rows, stored=None):
        refresh = AsyncMock()
        with patch.object(pf, "history", AsyncMock(return_value=rows)), \
                patch.object(pf, "get_summary", AsyncMock(return_value=stored)), \
                patch.object(pf, "refresh", refresh):
            async def go():
                out = await pf.block("tg", 7, now=NOW)
                await asyncio.sleep(0)
                return out
            text, hours = asyncio.run(go())
        return text, hours, refresh

    def test_new_person(self):
        text, hours, refresh = self._block([])
        self.assertIsNone(hours)
        self.assertIn("avval gaplashmaganmiz", text)
        self.assertIn("birinchi marta", text)
        refresh.assert_not_awaited()

    def test_summary_recent_lines_and_refresh_when_stale(self):
        rows = [_row(100 - i, them=f"q{i}") for i in range(20)]
        text, hours, refresh = self._block(rows, {"summary": "- bodom uni olgan", "turns": 10})
        self.assertIn("XULOSA:\n- bodom uni olgan", text)
        self.assertIn("q19", text)
        self.assertNotIn("q5 ", text)
        self.assertIn("SALOM", text)
        refresh.assert_called_once()

    def test_not_stale_no_refresh(self):
        rows = [_row(10 - i) for i in range(12)]
        _, _, refresh = self._block(rows, {"summary": "x", "turns": 10})
        refresh.assert_not_called()

    def test_db_failure_is_silent(self):
        with patch.object(pf, "history", AsyncMock(side_effect=RuntimeError("no db"))):
            self.assertEqual(asyncio.run(pf.block("ig", "ali")), ("", None))


class CommentDraftTest(unittest.TestCase):
    def test_folder_in_prompt_and_midchat_greeting_dropped(self):
        seen = {}

        async def inner(c, kb):
            seen["prompt"] = comment_ai.comment_prompt(c)
            return comment_ai.Draft("savol", "Assalomu alaykum! Ha, bor.", True, "m")
        with patch.object(pf, "block", AsyncMock(return_value=("MIJOZ PAPKASI: x", 1.0))), \
                patch.object(comment_ai, "_draft", inner):
            d = asyncio.run(comment_ai.draft({"username": "ali", "text": "bormi?"}, {}))
        self.assertIn("MIJOZ PAPKASI", seen["prompt"])
        self.assertEqual(d.reply, "Ha, bor.")


if __name__ == "__main__":
    unittest.main()
