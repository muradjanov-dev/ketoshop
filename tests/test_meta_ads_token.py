"""/reklama_token — Meta reklama tokenini serverga kirmasdan, bot orqali berish.

Tekshiriladi: token Meta'da tekshirilmaguncha saqlanmaydi, tokenli xabar
o'chiriladi, guruhda qabul qilinmaydi, faqat admin, "off" o'chiradi,
bazadagi token env'dan ustun va Graph so'rovlari shu token bilan ketadi.
"""
import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
import meta_ads

ADMIN = 777


def _message(text, chat_type="private", user_id=ADMIN, delete_fails=False):
    msg = SimpleNamespace(
        text=text,
        chat=SimpleNamespace(type=chat_type),
        from_user=SimpleNamespace(id=user_id),
        answer=AsyncMock(),
        delete=AsyncMock(side_effect=RuntimeError("no rights") if delete_fails else None),
    )
    return msg


class TokenSourceTest(unittest.TestCase):
    def tearDown(self):
        meta_ads._db_token = ""

    def test_bot_token_wins_over_env(self):
        with patch.object(meta_ads, "ENV_TOKEN", "ENV"):
            meta_ads._db_token = ""
            self.assertEqual(meta_ads.token(), "ENV")
            meta_ads._db_token = "DB"
            self.assertEqual(meta_ads.token(), "DB")
        with patch.object(meta_ads, "ENV_TOKEN", ""):
            meta_ads._db_token = ""
            self.assertFalse(meta_ads.is_enabled())

    def test_load_token_reads_the_database(self):
        with patch.object(database, "get_meta_ads_token", AsyncMock(return_value=" EAAX \n")):
            asyncio.run(meta_ads.load_token())
        self.assertEqual(meta_ads._db_token, "EAAX")

    def test_load_token_survives_a_database_error(self):
        meta_ads._db_token = "OLD"
        with patch.object(database, "get_meta_ads_token", AsyncMock(side_effect=RuntimeError("db"))):
            with self.assertLogs("meta_ads", "WARNING"):
                asyncio.run(meta_ads.load_token())
        self.assertEqual(meta_ads._db_token, "OLD")

    def test_graph_calls_use_the_current_token_unless_overridden(self):
        seen = []

        class Resp:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def json(self, content_type=None):
                return {"data": []}

        class Session:
            def get(self, url, params=None, timeout=None):
                seen.append(params["access_token"])
                return Resp()

        meta_ads._db_token = "DB"
        asyncio.run(meta_ads._get(Session(), "me"))
        asyncio.run(meta_ads._get(Session(), "me", access_token="CANDIDATE"))
        self.assertEqual(seen, ["DB", "CANDIDATE"])


class TokenCommandTest(unittest.TestCase):
    def setUp(self):
        self.saved = AsyncMock()
        self.patches = [
            patch.object(meta_ads, "ADMIN_IDS", [ADMIN]),
            patch.object(meta_ads, "ENV_TOKEN", ""),
            patch.object(database, "set_meta_ads_token", self.saved),
            patch.object(database, "get_meta_ads_token", AsyncMock(return_value=None)),
        ]
        for p in self.patches:
            p.start()
        meta_ads._db_token = ""

    def tearDown(self):
        for p in self.patches:
            p.stop()
        meta_ads._db_token = ""

    def _graph(self, me=None, error=None):
        async def fake_get(session, path, **params):
            if error:
                raise error
            if path == "me":
                return me or {"id": "1", "name": "ketoshop-bot"}
            if path == "me/adaccounts":
                return {"data": [{"account_id": "840216037679254", "name": "Ketoshop",
                                  "account_status": 1},
                                 {"account_id": "555", "name": "Instagram boost",
                                  "account_status": 3}]}
            raise AssertionError(path)
        return fake_get

    def test_valid_token_is_checked_saved_and_message_deleted(self):
        msg = _message("/reklama_token EAAgood123")
        with patch.object(meta_ads, "_get", self._graph()):
            asyncio.run(meta_ads.cmd_token(msg))
        msg.delete.assert_awaited_once()
        self.saved.assert_awaited_once_with("EAAgood123", ADMIN)
        self.assertEqual(meta_ads.token(), "EAAgood123")
        reply = msg.answer.await_args.args[0]
        self.assertIn("✅ Token saqlandi — ketoshop-bot", reply)
        self.assertIn("<code>555</code>", reply)
        self.assertIn("To'lov qarzi bor", reply)          # "Pay now" hisobi ko'rinadi
        self.assertNotIn("EAAgood123", reply)

    def test_invalid_token_is_not_saved(self):
        msg = _message("/reklama_token EAAbad")
        with patch.object(meta_ads, "_get", self._graph(error=meta_ads.GraphError(190, "Invalid OAuth"))):
            asyncio.run(meta_ads.cmd_token(msg))
        self.saved.assert_not_awaited()
        self.assertFalse(meta_ads.is_enabled())
        self.assertIn("Token ishlamadi, saqlanmadi", msg.answer.await_args.args[0])
        msg.delete.assert_awaited_once()                 # baribir chatdan o'chadi

    def test_group_chat_never_saves(self):
        msg = _message("/reklama_token EAAgood123", chat_type="supergroup")
        with patch.object(meta_ads, "_get", self._graph()):
            asyncio.run(meta_ads.cmd_token(msg))
        self.saved.assert_not_awaited()
        msg.delete.assert_awaited_once()
        self.assertIn("shaxsiy chatda", msg.answer.await_args.args[0])

    def test_non_admin_is_ignored(self):
        msg = _message("/reklama_token EAAgood123", user_id=1)
        asyncio.run(meta_ads.cmd_token(msg))
        self.saved.assert_not_awaited()
        msg.answer.assert_not_awaited()

    def test_off_removes_the_bot_token(self):
        meta_ads._db_token = "DB"
        msg = _message("/reklama_token off")
        asyncio.run(meta_ads.cmd_token(msg))
        self.saved.assert_awaited_once_with(None, ADMIN)
        self.assertFalse(meta_ads.is_enabled())

    def test_status_without_token_explains_how(self):
        msg = _message("/reklama_token")
        asyncio.run(meta_ads.cmd_token(msg))
        self.assertIn("/reklama_token EAA", msg.answer.await_args.args[0])

    def test_status_lists_visible_accounts(self):
        meta_ads._db_token = "EAAstored9876"
        msg = _message("/reklama_token")
        with patch.object(database, "get_meta_ads_token", AsyncMock(return_value="EAAstored9876")), \
             patch.object(meta_ads, "_get", self._graph()):
            asyncio.run(meta_ads.cmd_token(msg))
        reply = msg.answer.await_args.args[0]
        self.assertIn("bot orqali berilgan (…9876)", reply)
        self.assertIn("<code>840216037679254</code>", reply)
        self.assertNotIn("EAAstored", reply)

    def test_delete_failure_is_reported(self):
        msg = _message("/reklama_token EAAgood123", delete_fails=True)
        with patch.object(meta_ads, "_get", self._graph()):
            asyncio.run(meta_ads.cmd_token(msg))
        self.assertIn("qo'lda o'chiring", msg.answer.await_args.args[0])

    def test_reklama_without_token_points_to_the_command(self):
        msg = _message("/reklama")
        asyncio.run(meta_ads.cmd_report(msg))
        self.assertIn("/reklama_token", msg.answer.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
