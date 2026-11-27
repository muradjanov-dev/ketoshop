"""Telegram ↔ Instagram papkalarini bog'lash (person_folder.py, egasi 2026-11-27)."""
import asyncio
import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import comment_ai
import ig_direct
import person_folder as pf

NOW = datetime(2026, 11, 27, 12, 0)


class LinkTextTest(unittest.TestCase):
    def test_personal_links_only_plain_bot_url(self):
        text = ("Botimiz: https://t.me/ketoshopbot\nDo'kon: https://t.me/ketoshopbot/shop?startapp=instagram\n"
                "Kanal: https://t.me/ketoshop_uz")
        out = pf.personal_links(text, "abcdefghjk")
        self.assertIn("https://t.me/ketoshopbot?start=iguabcdefghjk\n", out)
        self.assertIn("https://t.me/ketoshopbot/shop?startapp=instagram", out)
        self.assertIn("https://t.me/ketoshop_uz", out)
        self.assertEqual(pf.personal_links(text, None), text)

    def test_parse_payload(self):
        self.assertEqual(pf.parse_payload("iguabcdefghjk"), "abcdefghjk")
        for bad in ("ig_reels", "igu123", "sayt", None, "iguabcdefghjk1"):
            self.assertIsNone(pf.parse_payload(bad), bad)


class FakeConn:
    def __init__(self):
        self.calls = []

    async def fetch(self, sql, *args):
        self.calls.append(sql)
        if "FROM ai_dialog" in sql:
            return [{"created_at": NOW - timedelta(hours=30), "channel": "bot", "question": "botdagi savol",
                     "answer": "botdagi javob"}]
        if "FROM meta_comments" in sql:
            return [{"at": NOW - timedelta(hours=2), "ch": "ig", "text": "izoh", "reply_text": "javob"}]
        return []


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        pool = self

        class Ctx:
            async def __aenter__(self):
                return pool.conn

            async def __aexit__(self, *a):
                return False
        return Ctx()


class MergeTest(unittest.TestCase):
    def _history(self, **kw):
        conn = FakeConn()
        with patch.object(pf.database, "pool", _Pool(conn), create=True), \
                patch.object(pf, "linked", AsyncMock(return_value=[("tg", 42)])):
            return asyncio.run(pf.history("ig", "ali", **kw))

    def test_private_folder_merges_linked_telegram(self):
        rows = self._history()
        self.assertEqual([r["channel"] for r in rows], ["telegram bot", "izoh"])

    def test_public_comment_never_sees_telegram(self):
        rows = self._history(public=True)
        self.assertEqual([r["channel"] for r in rows], ["izoh"])

    def test_block_merges_linked_summary_only_in_private(self):
        async def summary(key):
            return {"summary": f"- {key}", "turns": 99}
        with patch.object(pf, "history", AsyncMock(return_value=[])), \
                patch.object(pf, "get_summary", summary), \
                patch.object(pf, "linked", AsyncMock(return_value=[("tg", 42)])):
            private, _ = asyncio.run(pf.block("ig", "ali"))
            public, _ = asyncio.run(pf.block("ig", "ali", public=True))
        self.assertIn("- tg:42", private)
        self.assertIn("Telegramdagi", private)
        self.assertNotIn("tg:42", public)
        self.assertIn("OCHIQ IZOH", public)


class WiringTest(unittest.TestCase):
    def test_comment_uses_public_folder(self):
        block = AsyncMock(return_value=("", None))
        with patch.object(pf, "block", block), \
                patch.object(comment_ai, "_draft", AsyncMock(return_value=None)):
            asyncio.run(comment_ai.draft({"username": "ali", "text": "?"}, {}))
        self.assertTrue(block.await_args.kwargs.get("public"))

    def test_direct_bot_link_becomes_personal(self):
        plan = ig_direct.Plan("replied", [f"Botimiz: {ig_direct.BOT_LINK}", "boshqa"])
        with patch.object(ig_direct, "_compose", AsyncMock(return_value=plan)), \
                patch.object(pf, "ig_token", AsyncMock(return_value="abcdefghjk")):
            out = asyncio.run(ig_direct.compose({"username": "ali"}, [], first_contact=False,
                                                catalog_ok=False, now=NOW))
        self.assertEqual(out.messages[0], "Botimiz: https://t.me/ketoshopbot?start=iguabcdefghjk")

    def test_start_links_and_runs_plain_start(self):
        from handlers import start
        msg = NS(from_user=NS(id=42), chat=NS(type="private"))
        with patch.object(pf, "link_from_start", AsyncMock(return_value="ali")) as link, \
                patch.object(start, "_handle_start", AsyncMock()) as handle, \
                patch.object(start, "_remind_pending_cheque", AsyncMock()):
            asyncio.run(start.cmd_start_deep_link(msg, NS(args="iguabcdefghjk"), None))
        link.assert_awaited_once_with(42, "iguabcdefghjk")
        handle.assert_awaited_once_with(msg, None, None, None)


if __name__ == "__main__":
    unittest.main()
