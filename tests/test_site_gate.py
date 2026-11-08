"""Saytga kirish: kanal, keyin bot, keyin yana saytga (egasi, 2026-11-08:
"sayt uchun ham kanal obunasini talab qil, keyin bot obunasini ham keyin
ularni yana saytga yo'naltir"). Telegram mock — hech qanday haqiqiy so'rov
yuborilmaydi."""
import asyncio
import json
import os
import re
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from aiogram.exceptions import TelegramForbiddenError

import subscription_gate as sg
import webapp_server as ws
from handlers import start

BUYER = 777000444
PAGE = open(os.path.join(os.path.dirname(ws.__file__), "webapp", "index.html"), encoding="utf-8").read()


def run(coro):
    return asyncio.run(coro)


def bot(member: bool = True, started: bool = True, channel_error: bool = False):
    b = AsyncMock()
    if channel_error:
        b.get_chat_member.side_effect = RuntimeError("bot is not an admin there")
    else:
        b.get_chat_member.return_value = Mock(status="member" if member else "left")
    if not started:
        b.send_chat_action.side_effect = TelegramForbiddenError(method=Mock(), message="blocked")
    return b


class GateTest(unittest.TestCase):
    def setUp(self):
        sg._cache.clear()
        sg._site_recheck_at.clear()
        ws._bot_access.clear()

    def test_both_steps_open_the_shop(self):
        g = run(ws.site_gate(bot(), BUYER))
        self.assertEqual((g["ok"], g["subscribed"], g["started"]), (True, True, True))
        self.assertEqual(g["channel"], "ketoshop_uz")         # no '@' — the page adds it

    def test_channel_is_asked_first(self):
        g = run(ws.site_gate(bot(member=False), BUYER))
        self.assertEqual((g["ok"], g["subscribed"], g["started"]), (False, False, True))
        g = run(ws.site_gate(bot(member=False, started=False), BUYER + 1))
        self.assertEqual((g["ok"], g["subscribed"], g["started"]), (False, False, False))

    def test_in_the_channel_but_bot_not_started(self):
        g = run(ws.site_gate(bot(started=False), BUYER))
        self.assertEqual((g["ok"], g["subscribed"], g["started"]), (False, True, False))

    def test_telegram_trouble_never_locks_the_shop(self):
        self.assertTrue(run(ws.site_gate(bot(channel_error=True), BUYER))["ok"])

    def test_admins_pass(self):
        b = bot(member=False, started=False)
        with patch.object(ws, "ADMIN_IDS", {BUYER}):
            self.assertTrue(run(ws.site_gate(b, BUYER))["ok"])
        b.get_chat_member.assert_not_awaited()

    def test_a_no_is_rechecked_every_few_seconds_not_every_poll(self):
        b = bot(member=False)
        self.assertFalse(run(sg.is_subscribed_for_site(b, BUYER)))
        self.assertFalse(run(sg.is_subscribed_for_site(b, BUYER)))      # cached "no"
        self.assertEqual(b.get_chat_member.await_count, 1)
        sg._site_recheck_at[BUYER] = time.monotonic() - sg.SITE_RECHECK - 1
        b.get_chat_member.return_value = Mock(status="member")        # they joined
        self.assertTrue(run(sg.is_subscribed_for_site(b, BUYER)))
        self.assertTrue(sg._cache[BUYER][0])                          # the bot sees it too


class EndpointTest(unittest.TestCase):
    def setUp(self):
        sg._cache.clear()
        sg._site_recheck_at.clear()
        ws._bot_access.clear()

    def request(self, path, b):
        store = {}
        req = Mock()
        req.path = path
        req.headers = {"Authorization": "tma x"}
        req.app = {"bot_token": "1:test", "bot": b}
        req.__setitem__ = lambda s, k, v: store.__setitem__(k, v)
        req.__getitem__ = lambda s, k: store[k]
        req.get = lambda k, d=None: store.get(k, d)
        return req

    def call(self, path, b, handler=None):
        handler = handler or AsyncMock(return_value=ws._json({"ok": True}))
        with patch.object(ws, "_validate_init_data", return_value={"user": {"id": BUYER, "language_code": "uz"}}), \
             patch.object(ws, "get_user_language", AsyncMock(return_value="uz")):
            return run(ws.auth_middleware(self.request(path, b), handler)), handler

    def test_shop_closed_outside_the_channel(self):
        resp, handler = self.call("/api/products", bot(member=False))
        self.assertEqual(resp.status, 403)
        body = json.loads(resp.text)
        self.assertEqual((body["error"], body["subscribed"], body["started"]), ("start_bot", False, True))
        handler.assert_not_awaited()

    def test_gate_check_registers_whoever_passes(self):
        site_user = AsyncMock(return_value=True)
        with patch.object(ws, "ensure_site_user", site_user), \
             patch("shop_links.record_open", AsyncMock(return_value=False)):
            resp, _ = self.call(ws.BOT_ACCESS_PATH, bot(), handler=ws.api_bot_access)
            self.assertTrue(json.loads(resp.text)["ok"])
            site_user.assert_awaited_once()
            site_user.reset_mock()
            sg._cache.clear()
            resp, _ = self.call(ws.BOT_ACCESS_PATH, bot(member=False), handler=ws.api_bot_access)
            self.assertFalse(json.loads(resp.text)["ok"])
            site_user.assert_not_awaited()


class SiteUserTest(unittest.TestCase):
    def go(self, existing=None, inserted=True):
        store = {"telegram_user": {"id": BUYER, "first_name": "Ali", "last_name": "V", "username": "ali"},
                 "user_lang": "ru"}
        req = Mock()
        req.get = lambda k, d=None: store.get(k, d)
        req.app = {"bot": object()}
        create = AsyncMock(return_value=inserted)
        process = AsyncMock()

        async def body():
            r = await ws.ensure_site_user(req, BUYER)
            await asyncio.sleep(0)
            return r

        with patch.object(ws, "get_user", AsyncMock(return_value=existing)), \
             patch.object(ws, "create_user", create), \
             patch("handlers.start._process_new_user", process):
            result = run(body())
        return result, create, process

    def test_new_member_greeted_once(self):
        result, create, process = self.go()
        self.assertTrue(result)
        self.assertEqual(create.await_args.kwargs, {"username": "ali", "full_name": "Ali V", "language": "ru"})
        process.assert_awaited_once()
        self.assertEqual(process.await_args.args[1].id, BUYER)

    def test_existing_member_left_alone(self):
        result, _, process = self.go(existing={"user_id": BUYER})
        self.assertFalse(result)
        process.assert_not_awaited()

    def test_bot_registered_them_a_moment_ago(self):
        result, _, process = self.go(inserted=False)
        self.assertFalse(result)
        process.assert_not_awaited()

    def test_bot_side_skips_when_the_site_won_the_race(self):
        process = AsyncMock()
        with patch.object(start, "get_user", AsyncMock(return_value=None)), \
             patch.object(start, "create_user", AsyncMock(return_value=False)), \
             patch.object(start, "_process_new_user", process):
            self.assertFalse(run(start.ensure_registered(Mock(), SimpleNamespace(
                id=BUYER, username=None, full_name="A"))))
        process.assert_not_awaited()


class BackToSiteTest(unittest.TestCase):
    def setUp(self):
        start._site_return.clear()

    def test_payload(self):
        for p in ("sayt", " SAYT "):
            self.assertTrue(start.is_site_payload(p))
        for p in (None, "", "sayt_x", "retsept"):
            self.assertFalse(start.is_site_payload(p))

    def test_button_opens_the_shop_in_their_language(self):
        for lang, word in (("uz", "Do'konga qaytish"), ("ru", "Вернуться в магазин"), ("uz_cyr", "Дўконга")):
            b = Mock()
            b.send_message = AsyncMock()
            run(start.send_back_to_site(b, BUYER, lang))
            markup = b.send_message.await_args.kwargs["reply_markup"]
            button = markup.inline_keyboard[0][0]
            self.assertIn(word, button.text, lang)
            self.assertIsNotNone(button.web_app)                # opens the Mini App, not a chat

    def handle(self, is_new):
        msg = Mock()
        msg.chat.type = "private"
        msg.from_user.id = BUYER
        msg.answer = AsyncMock()
        back = AsyncMock()
        with patch.object(start, "is_user_banned", AsyncMock(return_value=False)), \
             patch.object(start, "ensure_registered", AsyncMock(return_value=is_new)), \
             patch.object(start, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(start, "ensure_menu_keyboard", AsyncMock()), \
             patch.object(start, "send_back_to_site", back):
            run(start._handle_start(msg, None, site_return=True))
        return msg, back

    def test_returning_buyer_goes_straight_back(self):
        msg, back = self.handle(is_new=False)
        back.assert_awaited_once()
        msg.answer.assert_not_awaited()                   # no language picker
        self.assertNotIn(BUYER, start._site_return)

    def test_new_member_picks_a_language_first(self):
        msg, back = self.handle(is_new=True)
        back.assert_not_awaited()
        msg.answer.assert_awaited_once()                  # the language picker
        self.assertIn(BUYER, start._site_return)


class PageTest(unittest.TestCase):
    def test_two_steps_in_both_languages(self):
        for key in ("gateChannelStep", "gateChannelOpen", "gateBotStep", "gateDone", "gateChannelFirst"):
            self.assertEqual(PAGE.count(key + ":"), 2, key)   # uz + ru (uz_cyr is derived)

    def test_wiring(self):
        gate = PAGE[PAGE.index("function showStartGate("):PAGE.index("(async function init()")]
        self.assertIn("'?start=sayt'", gate)
        self.assertIn("if (!subscribed)", gate)                          # bot only after the channel
        self.assertIn("showStartGate(info)", gate)                       # each poll redraws the steps
        self.assertIn("showStartGate(access); return;", PAGE)
        self.assertIn("showStartGate(body);", PAGE)
        # The channel's handle is never run through the Cyrillic converter.
        self.assertNotRegex(PAGE, re.compile(r"gateChannelStep: '[^']*ketoshop_uz"))


if __name__ == "__main__":
    unittest.main()
