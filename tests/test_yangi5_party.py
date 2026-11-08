"""YANGI5 tantana bilan (egasi, 2026-11-08: "ularga ham 8 soatlik 5% lik
chegirmani tabriklab tantana bilan e'lon qil, saytda ham salyutlar va counter
bilan"). Bazaga ham, Telegramga ham ulanmaydi.

Measured in a real browser while writing this (Edge, 390 px): the card
opens over the shop, fireworks are drawn behind it, the clock ticks down,
«Xaridni boshlash» closes it and leaves the pill, a reload doesn't show it
again."""
import asyncio
import json
import os
import shutil
import subprocess
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
import webapp_server as ws
import welcome_promo as wp

USER = 556
PAGE = open(os.path.join(os.path.dirname(ws.__file__), "webapp", "index.html"), encoding="utf-8").read()


def run(coro):
    return asyncio.run(coro)


def pool():
    started = datetime.utcnow()

    class Conn:
        async def execute(self, sql, *args):
            pass

        async def fetchval(self, sql, *args):
            return started if "UPDATE welcome_promo SET started_at" in sql else None

    class P:
        def acquire(self):
            class _Ctx:
                async def __aenter__(self):
                    return Conn()

                async def __aexit__(self, *a):
                    return False
            return _Ctx()
    return P()


class BotTest(unittest.TestCase):
    def test_timer_goes_out_with_the_party_effect(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=7))
        with patch.object(database, "pool", pool()), patch.object(wp, "_table_ready", True):
            self.assertTrue(run(wp.maybe_start(bot, USER, "uz")))
        self.assertEqual(bot.send_message.await_count, 1)
        self.assertEqual(bot.send_message.await_args.kwargs["message_effect_id"], wp.PARTY_EFFECT)
        self.assertTrue(bot.send_message.await_args.args[1].startswith("🎉 <b>Tabriklaymiz!</b>"))

    def test_refused_effect_still_sends_the_timer(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=[RuntimeError("EFFECT_ID_INVALID"), MagicMock(message_id=8)])
        with patch.object(database, "pool", pool()), patch.object(wp, "_table_ready", True):
            self.assertTrue(run(wp.maybe_start(bot, USER, "ru")))
        self.assertEqual(bot.send_message.await_count, 2)
        self.assertNotIn("message_effect_id", bot.send_message.await_args.kwargs)
        self.assertIn("Поздравляем!", bot.send_message.await_args.args[1])


class SiteTest(unittest.TestCase):
    def test_site_visit_starts_a_pending_member(self):
        req = Mock()
        req.get = lambda k, d=None: {"user_id": USER}.get(k, d)
        req.app = {"bot": object()}
        start = AsyncMock(return_value=True)
        payload = AsyncMock(return_value={"code": "YANGI5", "seconds_left": 28800})
        with patch.object(wp, "maybe_start", start), patch.object(wp, "site_payload", payload):
            out = run(ws._welcome_promo(req, "uz"))
        start.assert_awaited_once()
        self.assertEqual(start.await_args.args[1:], (USER, "uz"))
        self.assertEqual(out["code"], "YANGI5")

    def test_site_registration_marks_pending_before_the_shop_asks(self):
        store = {"telegram_user": {"id": USER, "first_name": "Ali"}, "user_lang": "uz"}
        req = Mock()
        req.get = lambda k, d=None: store.get(k, d)
        req.app = {"bot": object()}
        order = []
        pending = AsyncMock(side_effect=lambda uid: order.append("pending"))

        async def process(*a, **k):
            order.append("welcome")

        async def body():
            await ws.ensure_site_user(req, USER)
            order.append("returned")
            await asyncio.sleep(0)

        with patch.object(ws, "get_user", AsyncMock(return_value=None)), \
             patch.object(ws, "create_user", AsyncMock(return_value=True)), \
             patch.object(wp, "mark_pending", pending), \
             patch("handlers.start._process_new_user", process):
            run(body())
        self.assertEqual(order[:2], ["pending", "returned"])     # awaited, not left to the background


class PageTest(unittest.TestCase):
    def test_texts_in_both_languages(self):
        for key in ("wpTitle", "wpSub", "wpGift", "wpLeft", "wpNote", "wpGo"):
            self.assertEqual(PAGE.count(key + ":"), 2, key)   # uz + ru (uz_cyr is derived)

    def test_wiring(self):
        timer = PAGE[PAGE.index("function renderWelcomeTimer("):PAGE.index("// ===== YANGI5 TANTANASI")]
        self.assertIn("celebrateWelcome(w, endsAt);", timer)
        party = PAGE[PAGE.index("function celebrateWelcome("):PAGE.index("function launchFireworks(")]
        self.assertIn("'ketoshop_yangi5_party_' + me", party)
        self.assertIn("try { if (localStorage.getItem(key)) return;", party)    # storage may throw
        self.assertIn("escapeHtml(w.code)", party)                              # never transliterated
        self.assertIn("stopFireworks()", party)
        self.assertIn("clearInterval(clockTimer)", party)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_clock_format(self):
        block = PAGE[PAGE.index("function hmsLeft("):PAGE.index("function celebrateWelcome(")]
        code = block + "\nprocess.stdout.write(JSON.stringify([28800, 28799.6, 61, 5, 0, -3].map(hmsLeft)));"
        out = json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(out, ["8:00:00", "7:59:59", "0:01:01", "0:00:05", "0:00:00", "0:00:00"])


if __name__ == "__main__":
    unittest.main()
