"""Guruhda jim bot (group_quiet.py) — Telegram'ga ulanmasdan."""
import asyncio
import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from aiogram.types import CallbackQuery, Message

import group_quiet
from config import ADMIN_IDS

MEMBER, GROUP_ADMIN = 555, 777
GROUP = -100123


def msg(text, chat_type="supergroup", user=MEMBER):
    m = Message.model_construct(text=text, caption=None, sender_chat=None,
                                chat=NS(id=GROUP if chat_type != "private" else user, type=chat_type),
                                from_user=NS(id=user))
    object.__setattr__(m, "delete", AsyncMock())
    return m


def cb(chat_type="supergroup", user=MEMBER):
    c = CallbackQuery.model_construct(id="1", from_user=NS(id=user), chat_instance="x", data="catalog",
                                      message=NS(chat=NS(id=GROUP, type=chat_type)))
    object.__setattr__(c, "answer", AsyncMock())
    return c


def run(event):
    handler = AsyncMock(return_value="handled")
    with patch("link_guard._chat_admin_ids", AsyncMock(return_value={GROUP_ADMIN})):
        out = asyncio.run(group_quiet.GroupQuietMiddleware()(handler, event, {"bot": NS(id=1)}))
    return out, handler


class GroupQuietTest(unittest.TestCase):
    def test_member_command_in_group_is_deleted_and_ignored(self):
        m = msg("/start@ketoshopbot")
        out, handler = run(m)
        self.assertIsNone(out)
        handler.assert_not_called()
        m.delete.assert_awaited()

    def test_group_admin_and_bot_admin_keep_commands(self):
        for user in (GROUP_ADMIN, next(iter(ADMIN_IDS))):
            out, handler = run(msg("/menu", user=user))
            self.assertEqual(out, "handled")

    def test_private_chat_untouched(self):
        out, _ = run(msg("/start", chat_type="private"))
        self.assertEqual(out, "handled")

    def test_plain_group_message_still_reaches_link_guard(self):
        out, _ = run(msg("salom, t.me/spam"))
        self.assertEqual(out, "handled")

    def test_member_button_tap_in_group_is_silenced(self):
        c = cb()
        out, handler = run(c)
        self.assertIsNone(out)
        handler.assert_not_called()
        c.answer.assert_awaited()

    def test_admin_button_tap_in_group_works(self):
        out, _ = run(cb(user=GROUP_ADMIN))
        self.assertEqual(out, "handled")
        out, _ = run(cb(chat_type="private"))
        self.assertEqual(out, "handled")


if __name__ == "__main__":
    unittest.main()
