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
from handlers import start as start_handlers
from config import ADMIN_IDS

MEMBER, GROUP_ADMIN = 555, 777
GROUP = -100123


def msg(text, chat_type="supergroup", user=MEMBER, sender_chat=None):
    m = Message.model_construct(text=text, caption=None, sender_chat=sender_chat,
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

    def test_no_shop_menu_in_group_for_anyone(self):
        # Owner, 2026-10-04: an anonymous "/start" from the group itself put
        # the language buttons in KETOSHOP chat. Nobody gets a menu there.
        bot_admin = next(iter(ADMIN_IDS))
        cases = [msg("/menu", user=GROUP_ADMIN), msg("/start", user=bot_admin),
                 msg("/start", user=1087968824, sender_chat=NS(id=GROUP))]
        for m in cases:
            out, handler = run(m)
            self.assertIsNone(out)
            handler.assert_not_called()
            m.delete.assert_awaited()

    def test_bot_admin_report_command_still_works(self):
        out, _ = run(msg("/ombor@ketoshopbot", user=next(iter(ADMIN_IDS))))
        self.assertEqual(out, "handled")

    def test_private_chat_untouched(self):
        out, _ = run(msg("/start", chat_type="private"))
        self.assertEqual(out, "handled")

    def test_start_handler_does_not_show_language_keyboard_in_group(self):
        m = msg("/start")
        object.__setattr__(m, "answer", AsyncMock())
        with patch.object(start_handlers, "is_user_banned", AsyncMock(return_value=False)) as banned:
            asyncio.run(start_handlers._handle_start(m, None))
        m.answer.assert_not_awaited()
        banned.assert_not_awaited()

    def test_menu_and_persistent_button_handlers_ignore_group(self):
        m = msg("/menu")
        object.__setattr__(m, "answer", AsyncMock())
        state = NS(clear=AsyncMock())
        asyncio.run(start_handlers.cmd_menu(m, state))
        m.answer.assert_not_awaited()
        state.clear.assert_not_awaited()

        m = msg("🏠 Bosh menyu")
        state = NS(clear=AsyncMock())
        asyncio.run(start_handlers.menu_button_pressed(m, state))
        state.clear.assert_not_awaited()

        m = msg("🛒 Savat")
        state = NS(clear=AsyncMock())
        asyncio.run(start_handlers.cart_button_pressed(m, state))
        state.clear.assert_not_awaited()

    def test_private_menu_button_still_opens_the_shop(self):
        m = msg("🏠 Bosh menyu", chat_type="private")
        object.__setattr__(m, "answer", AsyncMock())
        state = NS(clear=AsyncMock())
        with patch.object(start_handlers, "get_user_language", AsyncMock(return_value="uz")), \
                patch.object(start_handlers, "get_text", return_value="welcome"), \
                patch.object(start_handlers, "main_menu_keyboard", return_value="shop keyboard"):
            asyncio.run(start_handlers.menu_button_pressed(m, state))
        state.clear.assert_awaited_once()
        m.answer.assert_awaited_once()

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
