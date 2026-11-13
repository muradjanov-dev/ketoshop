"""GPT va Gemini'ni izohlarda solishtirish (gemini_compare.py, 2026-11-13)."""
import asyncio
import os
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://ci:ci@localhost:5432/ci")
os.environ.setdefault("BOT_TOKEN", "123456:CI-TOKEN")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_sales  # noqa: E402
import comment_ai  # noqa: E402
import database  # noqa: E402
import gemini_compare as gc  # noqa: E402
import meta_comments  # noqa: E402

OWNER = next(iter(ai_sales.OWNER_IDS), None) or 1


class SchemaTest(unittest.TestCase):
    def test_comment_schema_becomes_gemini_schema(self):
        s = gc.gemini_schema(comment_ai.SCHEMA)
        self.assertEqual(s["type"], "OBJECT")
        self.assertNotIn("additionalProperties", s)
        self.assertEqual(s["properties"]["category"]["type"], "STRING")
        self.assertEqual(s["properties"]["category"]["enum"], list(comment_ai.CATEGORIES))
        self.assertEqual(s["properties"]["confident"]["type"], "BOOLEAN")
        self.assertEqual(s["required"], comment_ai.SCHEMA["required"])


class CompareTest(unittest.TestCase):
    def run_compare(self, gem=None, key="AIza-test"):
        rows = [{"id": 1, "text": "Narxi qancha?", "category": "narx", "media_id": "M1", "platform": "ig"},
                {"id": 2, "text": "spam havola", "category": "spam", "media_id": "M1", "platform": "ig"},
                {"id": 3, "text": "Эритрит кушилганми", "category": "boshqa", "media_id": "M2", "platform": "ig"}]
        sent = AsyncMock()
        gpt = AsyncMock(return_value={"data": {"category": "narx", "reply": "Narxlar @ketoshopbot da", "confident": True},
                                      "seconds": 1.0})
        gem = gem or AsyncMock(return_value={"data": {"category": "narx", "reply": "Narxi botimizda 🌿",
                                                      "confident": True},
                                             "input": 1000, "output": 50, "seconds": 2.0})
        with patch.object(gc, "gemini_key", AsyncMock(return_value=(key, "gemini-x-flash"))), \
                patch.object(database, "get_meta_comments_state", AsyncMock(return_value={"kb": {}})), \
                patch.object(database, "meta_comments_report", AsyncMock(return_value=rows)), \
                patch.object(comment_ai, "catalog_text", AsyncMock(return_value="- Eritritol — 1 so'm")), \
                patch.object(meta_comments, "post_context", AsyncMock(return_value=("Post", "https://img/1.jpg"))), \
                patch.object(meta_comments, "reply_public", sent), \
                patch.object(gc, "ask_gpt", gpt), patch.object(gc, "ask_gemini", gem):
            result = asyncio.run(gc.compare(5))
        return result, gpt, gem, sent

    def test_both_answer_the_same_comments_and_nothing_is_sent(self):
        (items, totals), gpt, gem, sent = self.run_compare()
        self.assertEqual([it["row"]["id"] for it in items], [1, 3])          # spam skipped
        self.assertEqual(gpt.await_count, 2)
        self.assertEqual(gem.await_count, 2)
        self.assertEqual(gpt.await_args.args[0], gem.await_args.args[2])     # same instructions
        self.assertIn("Telegram", items[0]["gpt"])                           # finalize applied
        self.assertEqual(totals["gem_in"], 2000)
        sent.assert_not_awaited()
        pages = gc.render(items, totals)
        self.assertIn("🟢 GPT", pages[0])
        self.assertIn("🔵 Gemini", pages[0])
        self.assertIn("Hech narsa Instagram'ga yuborilmadi", pages[-1])

    def test_a_gemini_error_is_shown_not_raised(self):
        (items, totals), *_ = self.run_compare(gem=AsyncMock(side_effect=gc.GeminiError("quota")))
        self.assertEqual(totals["gem_err"], 2)
        self.assertIn("quota", items[0]["gem"])

    def test_no_key_says_how_to_give_one(self):
        with patch.object(gc, "gemini_key", AsyncMock(return_value=("", "m"))):
            with self.assertRaises(gc.GeminiError) as ctx:
                asyncio.run(gc.compare(5))
        self.assertIn("/gemini_kalit", str(ctx.exception))

    def test_long_output_is_split_into_telegram_sized_pages(self):
        items = [{"row": {"text": "x" * 120}, "gpt": "g" * 900, "gem": "m" * 900} for _ in range(12)]
        totals = {"gpt_s": 1, "gem_s": 1, "gem_in": 1, "gem_out": 1, "gpt_err": 0, "gem_err": 0, "model": "m"}
        pages = gc.render(items, totals)
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(len(p) <= 4096 for p in pages))


class KeyCommandTest(unittest.TestCase):
    def message(self, text, chat="private", uid=OWNER):
        return NS(text=text, chat=NS(type=chat), from_user=NS(id=uid), delete=AsyncMock(), answer=AsyncMock())

    def test_good_key_is_saved_and_the_message_deleted(self):
        msg = self.message("/gemini_kalit AIzaSECRET1234")
        saved = AsyncMock()
        with patch.object(ai_sales, "ADMIN_IDS", [OWNER]), patch.object(ai_sales, "OWNER_IDS", {OWNER}), \
                patch.object(gc, "gemini_key", AsyncMock(return_value=("", "gemini-x-flash"))), \
                patch.object(gc, "verify", AsyncMock(return_value=(None, []))), \
                patch.object(ai_sales, "set_setting", saved):
            asyncio.run(gc.cmd_key(msg))
        msg.delete.assert_awaited()
        self.assertEqual(saved.await_args_list[0].args[:2], (gc.KEY_SETTING, "AIzaSECRET1234"))
        self.assertIn("…1234", msg.answer.await_args.args[0])
        self.assertNotIn("AIzaSECRET1234", msg.answer.await_args.args[0])

    def test_unknown_model_lists_the_open_ones_and_saves_nothing(self):
        msg = self.message("/gemini_kalit AIzaKEY gemini-old")
        saved = AsyncMock()
        with patch.object(ai_sales, "ADMIN_IDS", [OWNER]), patch.object(ai_sales, "OWNER_IDS", {OWNER}), \
                patch.object(gc, "verify", AsyncMock(return_value=("not found", ["gemini-3-flash"]))), \
                patch.object(ai_sales, "set_setting", saved):
            asyncio.run(gc.cmd_key(msg))
        saved.assert_not_awaited()
        self.assertIn("gemini-3-flash", msg.answer.await_args.args[0])

    def test_group_chat_never_saves(self):
        msg = self.message("/gemini_kalit AIzaKEY", chat="supergroup")
        saved = AsyncMock()
        with patch.object(ai_sales, "ADMIN_IDS", [OWNER]), patch.object(ai_sales, "set_setting", saved):
            asyncio.run(gc.cmd_key(msg))
        msg.delete.assert_awaited()
        saved.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
