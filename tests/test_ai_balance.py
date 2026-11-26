"""OpenAI balansi ogohlantirishi (egasi, 2026-11-26: "$1 qolganda hamma
adminlarga xabar ber"). Bazasiz, tarmoqsiz."""
import asyncio
import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ai_balance
import ai_sales


def _run(coro):
    return asyncio.run(coro)


class BalanceTest(unittest.TestCase):
    def setUp(self):
        self.values = {}
        self.bot = NS(send_message=AsyncMock())
        saved = (ai_balance._bot["bot"], ai_balance._last_exhausted["at"])
        self.addCleanup(lambda: (ai_balance._bot.__setitem__("bot", saved[0]),
                                 ai_balance._last_exhausted.__setitem__("at", saved[1])))
        ai_balance._bot["bot"] = self.bot
        ai_balance._last_exhausted["at"] = 0.0

        async def set_setting(key, value, by=None):
            self.values[key] = value
        p1 = patch.object(ai_balance, "_values", AsyncMock(side_effect=lambda: self.values))
        p2 = patch.object(ai_sales, "set_setting", set_setting)
        p3 = patch("config.ADMIN_IDS", [1, 2])
        for p in (p1, p2, p3):
            p.start()
            self.addCleanup(p.stop)

    def _spend(self, total):
        return patch.object(ai_balance, "total_openai_spend", AsyncMock(return_value=total))

    def test_unknown_balance_never_alerts(self):
        with self._spend(5.0):
            self.assertEqual(_run(ai_balance.check()), "none")
        self.bot.send_message.assert_not_awaited()

    def test_alert_once_when_one_dollar_is_left(self):
        message = NS(from_user=NS(id=1), text="/ai_balans 20", bot=self.bot, answer=AsyncMock())
        with self._spend(100.0):
            _run(ai_balance.cmd_balance(message))
        self.assertEqual(self.values[ai_balance.BALANCE_KEY], "20.0000")
        self.assertEqual(float(self.values[ai_balance.BASE_KEY]), 100.0)

        with self._spend(110.0):                                   # $10 qoldi
            self.assertEqual(_run(ai_balance.check()), "ok")
        with self._spend(119.2):                                   # $0.80 qoldi
            self.assertEqual(_run(ai_balance.check()), "alerted")
            self.assertEqual(_run(ai_balance.check()), "already")
        self.assertEqual(self.bot.send_message.await_count, 2)     # 2 admin, bir marta
        text = self.bot.send_message.await_args.args[1]
        self.assertIn("$0.80", text)
        self.assertIn("/ai_balans", text)

        with self._spend(119.2):                                   # to'ldirildi — yana kuzatadi
            _run(ai_balance.cmd_balance(NS(from_user=NS(id=1), text="/ai_balans 25", bot=self.bot,
                                           answer=AsyncMock())))
        self.assertEqual(self.values[ai_balance.ALERTED_KEY], "0")

    def test_bad_amount_is_rejected(self):
        message = NS(from_user=NS(id=1), text="/ai_balans yigirma", bot=self.bot, answer=AsyncMock())
        _run(ai_balance.cmd_balance(message))
        self.assertNotIn(ai_balance.BALANCE_KEY, self.values)

    def test_exhausted_error_alerts_once_per_gap(self):
        async def go():
            ai_balance.note_error(RuntimeError("Error code: 429 - {'code': 'credit_balance_exhausted'}"))
            ai_balance.note_error(RuntimeError("credit_balance_exhausted"))
            ai_balance.note_error(RuntimeError("timeout"))
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        _run(go())
        self.assertEqual(self.bot.send_message.await_count, 2)     # 2 admin, bitta xabar
        self.assertIn("tugadi", self.bot.send_message.await_args.args[1])

    def test_step_failure_reports_the_error(self):
        class Broken:
            name, model = "openai", "gpt-5.4-mini"

            async def step(self, *a, **k):
                raise RuntimeError("insufficient_quota")
        noted = []
        with patch.object(ai_sales, "PROVIDER", Broken()), \
                patch.object(ai_balance, "note_error", lambda e: noted.append(str(e))):
            with self.assertRaises(RuntimeError):
                _run(ai_sales._step({}, "r", "c", None, user="x"))
        self.assertEqual(noted, ["insufficient_quota"])


if __name__ == "__main__":
    unittest.main()
