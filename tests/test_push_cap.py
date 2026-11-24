"""Bitta userga kuniga nechta rejali xabar (push_cap.py, egasi 2026-11-15):
faol xaridorga 2 ta, xarid qilmagan va 3 kundan beri jimlarga 1 ta."""
import asyncio
import os
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database  # noqa: E402
import push_cap  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def run(coro):
    return asyncio.run(coro)


class ClaimTest(unittest.TestCase):
    def test_limits_go_to_the_database_in_one_atomic_call(self):
        claim = AsyncMock(return_value=True)
        with patch.object(database, "claim_user_push", claim):
            self.assertTrue(run(push_cap.claim(7, "tips")))
        # Egasi, 2026-11-24: kuniga 1, haftasiga 3 / 2, orasida 1 kun bo'sh; maslahat — past ustunlik.
        self.assertEqual(claim.await_args.args, (7, "tips", 1, 1, 3, None, 3, 2, 2, 1))

    def test_personal_messages_keep_their_weekly_slots(self):
        self.assertEqual(push_cap.reserve_for("reco"), 0)
        self.assertEqual(push_cap.reserve_for("fikr"), 0)
        self.assertEqual(push_cap.reserve_for("kun_mahsuloti"), 1)
        self.assertEqual(push_cap.reserve_for("tips"), 2)
        self.assertEqual(push_cap.reserve_for("keto_savol"), 2)

    def test_a_database_error_never_lets_a_message_through(self):
        with patch.object(database, "claim_user_push", AsyncMock(side_effect=RuntimeError("down"))):
            self.assertFalse(run(push_cap.claim(7, "tips")))


class SendersTest(unittest.TestCase):
    """Every scheduled sender asks the gate per user; admin previews don't."""

    def gate(self, allowed):
        return patch.object(database, "claim_user_push",
                            AsyncMock(side_effect=lambda uid, kind, *a: uid in allowed))

    def test_every_scheduled_sender_uses_the_gate(self):
        for module in ("broadcast", "personal_recommend", "promotions", "product_of_day", "daily_interest",
                       "daily_quiz", "retention", "abandoned_cart", "gift_campaign"):
            src = (ROOT / f"{module}.py").read_text(encoding="utf-8")
            self.assertIn("push_cap", src, module)

    def test_kun_mahsuloti_skips_users_over_the_cap(self):
        import product_of_day
        sent = []

        async def fake_send(bot, uid, prod, lang, captions):
            sent.append(uid)
            return True

        with self.gate({1, 3}), \
                patch.object(database, "get_all_user_ids", AsyncMock(return_value=[1, 2, 3])), \
                patch.object(database, "get_user_languages", AsyncMock(return_value={})), \
                patch.object(product_of_day, "_send_to_user", fake_send), \
                patch.object(product_of_day, "SEND_DELAY", 0), \
                patch("product_ideas.recipe_block", lambda *a, **k: ""):
            result = run(product_of_day.broadcast(MagicMock(), {"id": 1, "name": "Eritritol", "price": 1}))
        self.assertEqual(sent, [1, 3])
        self.assertEqual(result, (2, 0))

    def test_keto_savol_skips_capped_users_but_not_an_admin_test(self):
        import daily_quiz
        bot = MagicMock()
        bot.send_message = AsyncMock()
        with self.gate({2}), \
                patch.object(database, "daily_quiz_sent_keys", AsyncMock(return_value=set())), \
                patch.object(database, "start_daily_quiz", AsyncMock(return_value=31)), \
                patch.object(database, "get_all_user_ids", AsyncMock(return_value=[1, 2, 3])), \
                patch.object(database, "get_user_languages", AsyncMock(return_value={})), \
                patch.object(database, "finish_daily_quiz", AsyncMock()), \
                patch.object(daily_quiz, "SEND_DELAY", 0):
            result = run(daily_quiz.send_round(bot, date(2026, 11, 16)))
            self.assertEqual([c.args[0] for c in bot.send_message.await_args_list], [2])
            self.assertEqual(result["sent"], 1)
            bot.send_message.reset_mock()
            run(daily_quiz.send_round(bot, None, test_user=1))               # an admin's preview is never capped
            self.assertEqual([c.args[0] for c in bot.send_message.await_args_list], [1])

    def test_tips_skip_users_over_the_cap(self):
        import broadcast
        bot = MagicMock()
        bot.send_message = AsyncMock()
        with self.gate({3}), \
                patch.object(database, "get_all_user_ids", AsyncMock(return_value=[1, 2, 3])), \
                patch("bot_discount.footer", AsyncMock(return_value="")):
            sent, failed = run(broadcast._broadcast_to_all(bot, "Maslahat"))
        self.assertEqual([c.args[0] for c in bot.send_message.await_args_list], [3])
        self.assertEqual((sent, failed), (1, 0))


if __name__ == "__main__":
    unittest.main()
