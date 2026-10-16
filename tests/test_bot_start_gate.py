"""Mini App faqat botni ishga tushirganlar uchun (egasi, 2026-10-14: "Mini
appni yoki saytni ishlatish uchun botni ishga tushurish shart bo'lsin").
Telegram mock — hech qanday haqiqiy so'rov yuborilmaydi."""
import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

import webapp_server as ws

BUYER = 777000222


def run(coro):
    return asyncio.run(coro)


class ProbeTest(unittest.TestCase):
    def setUp(self):
        ws._bot_access.clear()

    def bot(self, effect=None):
        b = AsyncMock()
        b.send_chat_action.side_effect = effect
        return b

    def test_started_bot_can_write(self):
        b = self.bot()
        self.assertTrue(run(ws.bot_can_write(b, BUYER)))
        b.send_chat_action.assert_awaited_once_with(BUYER, "typing")

    def test_never_started_or_blocked(self):
        for exc in (TelegramForbiddenError(method=Mock(), message="Forbidden: bot can't initiate conversation with a user"),
                    TelegramForbiddenError(method=Mock(), message="Forbidden: bot was blocked by the user"),
                    TelegramBadRequest(method=Mock(), message="Bad Request: chat not found")):
            ws._bot_access.clear()
            self.assertFalse(run(ws.bot_can_write(self.bot(exc), BUYER)), exc)

    def test_telegram_trouble_never_locks_the_shop(self):
        self.assertTrue(run(ws.bot_can_write(self.bot(RuntimeError("timeout")), BUYER)))

    def test_admins_and_no_bot_pass(self):
        b = self.bot(TelegramForbiddenError(method=Mock(), message="blocked"))
        with patch.object(ws, "ADMIN_IDS", {BUYER}):
            self.assertTrue(run(ws.bot_can_write(b, BUYER)))
        b.send_chat_action.assert_not_called()
        self.assertTrue(run(ws.bot_can_write(None, BUYER)))

    def test_a_good_answer_is_cached(self):
        b = self.bot()
        run(ws.bot_can_write(b, BUYER))
        run(ws.bot_can_write(b, BUYER))
        self.assertEqual(b.send_chat_action.await_count, 1)

    def test_a_refusal_is_rechecked_soon(self):
        b = self.bot(TelegramForbiddenError(method=Mock(), message="blocked"))
        run(ws.bot_can_write(b, BUYER))
        ws._bot_access[BUYER] = (ws._bot_access[BUYER][0] - ws._BOT_ACCESS_NO_TTL - 1, False)
        b.send_chat_action.side_effect = None          # they pressed START
        self.assertTrue(run(ws.bot_can_write(b, BUYER)))


class MiddlewareTest(unittest.TestCase):
    def setUp(self):
        ws._bot_access.clear()

    def request(self, path, bot):
        req = {}
        req_obj = Mock()
        req_obj.path = path
        req_obj.headers = {"Authorization": "tma x"}
        req_obj.app = {"bot_token": "1:test", "bot": bot}
        req_obj.__setitem__ = lambda s, k, v: req.__setitem__(k, v)
        req_obj.__getitem__ = lambda s, k: req[k]
        req_obj.get = lambda k, d=None: req.get(k, d)
        return req_obj

    def go(self, path, bot):
        handler = AsyncMock(return_value=ws._json({"ok": True}))
        with patch.object(ws, "_validate_init_data", return_value={"user": {"id": BUYER, "language_code": "uz"}}), \
             patch.object(ws, "get_user_language", AsyncMock(return_value="uz")):
            resp = run(ws.auth_middleware(self.request(path, bot), handler))
        return resp, handler

    def test_shop_is_closed_until_start(self):
        blocked = AsyncMock()
        blocked.send_chat_action.side_effect = TelegramForbiddenError(method=Mock(), message="blocked")
        resp, handler = self.go("/api/products", blocked)
        self.assertEqual(resp.status, 403)
        self.assertEqual(json.loads(resp.text)["error"], "start_bot")
        handler.assert_not_awaited()

    def test_the_check_itself_stays_open(self):
        blocked = AsyncMock()
        blocked.send_chat_action.side_effect = TelegramForbiddenError(method=Mock(), message="blocked")
        resp, handler = self.go(ws.BOT_ACCESS_PATH, blocked)
        handler.assert_awaited_once()

    def test_started_buyer_goes_through(self):
        resp, handler = self.go("/api/products", AsyncMock())
        self.assertEqual(resp.status, 200)
        handler.assert_awaited_once()


class PageTest(unittest.TestCase):
    def test_gate_is_wired_into_the_page(self):
        page = open(os.path.join(os.path.dirname(ws.__file__), "webapp", "index.html"), encoding="utf-8").read()
        self.assertIn("function showStartGate(", page)
        self.assertIn("/api/bot-access", page)
        self.assertIn("body.error === 'start_bot'", page)
        for key in ("startGateTitle", "startGateText", "startGateOpen", "startGateCheck", "startGateWaiting"):
            self.assertEqual(page.count(key + ":"), 2, key)   # uz + ru (uz_cyr is derived)


if __name__ == "__main__":
    unittest.main()
