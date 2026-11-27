"""Kanal postlaridagi hamma izohlar saqlanadi (owner, 2026-11-27). The
database is faked: nothing is written or sent."""
import asyncio
import os
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ai_sales
import channel_comments as cc
import customer_portrait
import database
import keyboards

GROUP = -100777


class FakeConn:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, *args):
        self.calls.append((" ".join(sql.split()), args))


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False
        return Ctx()


def msg(**kw):
    m = MagicMock()
    m.chat = SimpleNamespace(id=kw.pop("chat_id", GROUP), type=kw.pop("chat_type", "supergroup"))
    m.message_id = kw.pop("message_id", 55)
    m.message_thread_id = kw.pop("thread", 40)
    m.from_user = SimpleNamespace(id=kw.pop("user_id", 9001), username="ali", full_name="Ali Valiyev")
    m.text = kw.pop("text", "Bodom uni, steviya, kokos uni")
    m.caption = None
    m.photo = kw.pop("photo", None)
    for kind in ("video", "voice", "video_note", "audio", "document", "animation", "sticker"):
        setattr(m, kind, None)
    m.reply_to_message = SimpleNamespace(message_id=40)
    m.is_automatic_forward = kw.pop("auto", False)
    m.sender_chat = None
    m.forward_origin = SimpleNamespace(message_id=kw.pop("channel_mid", None))
    return m


class RecordTest(unittest.TestCase):
    def setUp(self):
        self.conn = FakeConn()
        cc._table_ready = True
        for target, attr, value in [
            (database, "pool", FakePool(self.conn)),
            (ai_sales, "_channel_group", AsyncMock(return_value=GROUP)),
            (customer_portrait, "is_opted_out", AsyncMock(return_value=False)),
        ]:
            p = patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)

    def inserts(self, table):
        return [args for sql, args in self.conn.calls if f"INSERT INTO {table}" in sql]

    def test_comment_is_kept_in_full(self):
        asyncio.run(cc.record(msg()))
        (args,) = self.inserts("channel_comments")
        self.assertEqual(args[:5], (GROUP, 55, 40, 40, 9001))
        self.assertEqual(args[5:8], ("ali", "Ali Valiyev", "text"))
        self.assertEqual(args[-1], "Bodom uni, steviya, kokos uni")

    def test_channel_post_is_kept_as_the_thread(self):
        asyncio.run(cc.record(msg(auto=True, message_id=40, channel_mid=812, text="10 ta mahsulotingiz?")))
        self.assertEqual(self.inserts("channel_comment_posts"), [(GROUP, 40, 812, "10 ta mahsulotingiz?")])
        self.assertEqual(self.inserts("channel_comments"), [])

    def test_photo_comment(self):
        photo = [SimpleNamespace(file_id="small"), SimpleNamespace(file_id="big")]
        m = msg(photo=photo, text=None)
        m.caption = "shu non chiqdi"
        asyncio.run(cc.record(m))
        (args,) = self.inserts("channel_comments")
        self.assertEqual(args[7:], ("photo", "big", "shu non chiqdi"))

    def test_other_groups_and_private_are_not_kept(self):
        asyncio.run(cc.record(msg(chat_id=-100555)))
        asyncio.run(cc.record(msg(chat_type="private", chat_id=9001)))
        self.assertEqual(self.conn.calls, [])

    def test_opted_out_customer_is_not_kept(self):
        with patch.object(customer_portrait, "is_opted_out", AsyncMock(return_value=True)):
            asyncio.run(cc.record(msg()))
        self.assertEqual(self.inserts("channel_comments"), [])

    def test_a_broken_database_never_raises(self):
        with patch.object(database, "pool", MagicMock(acquire=MagicMock(side_effect=RuntimeError("down")))):
            asyncio.run(cc.record(msg()))

    def test_edit_updates_the_text(self):
        m = msg(text="tahrirlangan")
        asyncio.run(cc.record_edit(m))
        sql, args = self.conn.calls[-1]
        self.assertIn("UPDATE channel_comments SET text", sql)
        self.assertEqual(args, (GROUP, 55, "tahrirlangan"))


class MiddlewareTest(unittest.TestCase):
    def test_handler_runs_and_recording_does_not_block(self):
        recorded = AsyncMock()
        handler = AsyncMock(return_value="done")
        from aiogram.types import Message

        async def go():
            m = MagicMock(spec=Message)
            m.chat = SimpleNamespace(id=GROUP, type="supergroup")
            with patch.object(cc, "record", recorded):
                out = await cc.ChannelCommentsMiddleware()(handler, m, {})
                await asyncio.sleep(0)
            return out
        self.assertEqual(asyncio.run(go()), "done")
        recorded.assert_awaited_once()

    def test_private_messages_are_not_touched(self):
        from aiogram.types import Message
        recorded = AsyncMock()

        async def go():
            m = MagicMock(spec=Message)
            m.chat = SimpleNamespace(id=1, type="private")
            with patch.object(cc, "record", recorded):
                await cc.ChannelCommentsMiddleware()(AsyncMock(), m, {})
        asyncio.run(go())
        recorded.assert_not_called()


class ReadTest(unittest.TestCase):
    def test_file_lists_every_comment(self):
        post = {"text": "Eng ko'p ishlatadigan 10 ta mahsulotingiz?", "created_at": datetime(2026, 11, 23, 0, 5)}
        rows = [
            {"user_id": 1, "full_name": "Ali", "username": "ali", "kind": "text", "text": "Bodom uni",
             "created_at": datetime(2026, 11, 23, 0, 10)},
            {"user_id": 2, "full_name": "Vali", "username": None, "kind": "photo", "text": "",
             "created_at": datetime(2026, 11, 23, 1, 0)},
        ]
        text = cc.comments_file(post, rows)
        self.assertIn("Post (23.11 05:05)", text)
        self.assertIn("Izohlar: 2 ta, 2 kishi", text)
        self.assertIn("Ali (@ali)", text)
        self.assertIn("Bodom uni", text)
        self.assertIn("[photo]", text)

    def test_command_is_published_and_wired(self):
        self.assertIn("kanal_izohlar", [c.command for c in keyboards.ADMIN_COMMANDS])
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        bot_src = open(os.path.join(root, "bot.py"), encoding="utf-8").read()
        self.assertIn("dp.message.outer_middleware(channel_comments.ChannelCommentsMiddleware())", bot_src)
        self.assertIn("dp.include_router(channel_comments.router)", bot_src)
        # first message middleware: before the alphabet rewrite and link_guard
        self.assertLess(bot_src.index("ChannelCommentsMiddleware()"),
                        bot_src.index("IncomingOldLatinMiddleware()"))


if __name__ == "__main__":
    unittest.main()
