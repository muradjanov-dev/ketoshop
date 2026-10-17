"""Past baho sababini muloyim so'rash (egasi, 2026-10-17). Telegram va
bazaga ulanmasdan — hech kimga haqiqiy xabar ketmaydi."""
import asyncio
import os
import re
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
import review_followup as rf


def run(coro):
    return asyncio.run(coro)


ROW = {"id": 7, "user_id": 555, "rating": 1, "created_at": datetime(2026, 9, 30, 12, 0),
       "product_name": "Tabiiy xamirturush — zakvaska", "product_name_ru": "Натуральная закваска",
       "full_name": "Салима", "username": None, "phone": "+998901234567", "language": "uz_cyr"}


class TextTest(unittest.TestCase):
    def test_each_language(self):
        cyr = rf.message_text("uz_cyr", "Салима К.", "Табиий ҳамиртуруш", 1)
        self.assertTrue(cyr.startswith("Ассалому алайкум, Салима! 🌿"))
        self.assertIn("<b>Табиий ҳамиртуруш</b>", cyr)
        self.assertIn("1 ⭐", cyr)
        self.assertIn("узр сўраймиз", cyr)
        self.assertNotIn("{", cyr)
        # Only the brand stays Latin in the Cyrillic text.
        self.assertEqual(re.findall(r"[A-Za-z]+", re.sub(r"<[^>]+>", "", cyr)), ["Ketoshop"])
        self.assertIn("uzr so'raymiz", rf.message_text("uz", "Salima", "Zakvaska", 2))
        self.assertIn("Нам очень жаль", rf.message_text("ru", "Салима", "Закваска", 1))

    def test_no_name_and_escaping(self):
        text = rf.message_text("uz", None, "A <b> & B", 2)
        self.assertTrue(text.startswith("Assalomu alaykum! 🌿"))
        self.assertIn("A &lt;b&gt; &amp; B", text)


class SweepTest(unittest.TestCase):
    def sweep(self, rows=(ROW,), hour=12, claimed=True, banned=False, send_ok=True, on=True):
        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=None if send_ok else RuntimeError("blocked"))
        env = {"REVIEW_FOLLOWUP": "1" if on else "0"}
        with patch.dict(os.environ, env), \
             patch.object(rf, "_now_tk", lambda: datetime(2026, 10, 18, hour, 0)), \
             patch.object(rf, "ADMIN_IDS", [1]), \
             patch.object(database, "get_low_reviews_to_follow_up", AsyncMock(return_value=list(rows))) as due, \
             patch.object(database, "is_user_banned", AsyncMock(return_value=banned)), \
             patch.object(database, "claim_review_followup", AsyncMock(return_value=claimed)) as claim, \
             patch.object(database, "set_review_followup_delivered", AsyncMock()) as mark:
            sent = run(rf.run_once(bot))
        return sent, bot, due, claim, mark

    def to(self, bot, chat_id):
        return [c for c in bot.send_message.await_args_list if c.args[0] == chat_id]

    def test_asks_the_buyer_in_her_language_and_tells_the_admins(self):
        import ai_sales
        with patch.object(ai_sales, "pause_for_human") as pause:
            sent, bot, due, claim, mark = self.sweep()
        # Her answer must reach the admins, not the AI seller.
        pause.assert_called_once_with(555, rf.REPLY_WINDOW_DAYS * 86400)
        self.assertEqual(sent, 1)
        due.assert_awaited_once_with(rf.LOW_RATING, rf.LOOKBACK_DAYS, rf.MIN_AGE_MINUTES)
        claim.assert_awaited_once_with(7, 555)
        mark.assert_awaited_once_with(7, True)
        buyer = self.to(bot, 555)[0].args[1]
        self.assertIn("Ассалому алайкум, Салима!", buyer)
        self.assertIn("Табиий хамиртуруш — закваска", buyer.replace("ҳ", "х"))
        admin = self.to(bot, 1)[0].args[1]
        self.assertIn("Past baho sababi so'raldi", admin)
        self.assertIn("1★ (30.09)", admin)

    def test_never_twice_never_banned_never_at_night_never_when_off(self):
        for kwargs in ({"claimed": False}, {"banned": True}, {"hour": 9}, {"hour": 20}, {"on": False}):
            sent, bot, _, _, _ = self.sweep(**kwargs)
            self.assertEqual(sent, 0, kwargs)
            self.assertEqual(self.to(bot, 555), [], kwargs)

    def test_undelivered_is_recorded_and_admins_get_the_contact(self):
        import ai_sales
        with patch.object(ai_sales, "pause_for_human") as pause:
            sent, bot, _, _, mark = self.sweep(send_ok=False)
        pause.assert_not_called()
        self.assertEqual(sent, 0)
        mark.assert_awaited_once_with(7, False)
        admin = [c for c in bot.send_message.await_args_list if c.args[0] == 1][0].args[1]
        self.assertIn("yozib bo'lmadi", admin)
        self.assertIn("+998901234567", admin)


class AiPauseRestoreTest(unittest.TestCase):
    def test_restart_puts_the_pauses_back(self):
        import ai_sales
        rows = [{"user_id": 555, "seconds_left": 3600}, {"user_id": 556, "seconds_left": 0}]
        with patch.object(database, "get_review_followup_pauses", AsyncMock(return_value=rows)) as get, \
             patch.object(ai_sales, "pause_for_human") as pause:
            self.assertEqual(run(rf.restore_ai_pauses()), 2)
        get.assert_awaited_once_with(rf.REPLY_WINDOW_DAYS)
        self.assertEqual([c.args for c in pause.call_args_list], [(555, 3600), (556, 1)])


class ReplyContextTest(unittest.TestCase):
    def test_support_card_says_what_the_answer_is_about(self):
        recent = {"rating": 1, "product_name": "Zakvaska", "product_name_ru": None}
        with patch.object(database, "get_recent_review_followup", AsyncMock(return_value=recent)) as get:
            line = run(rf.reply_context(555))
        get.assert_awaited_once_with(555, rf.REPLY_WINDOW_DAYS)
        self.assertIn("Past baho sababi", line)
        self.assertIn("Zakvaska, 1★", line)
        with patch.object(database, "get_recent_review_followup", AsyncMock(return_value=None)):
            self.assertEqual(run(rf.reply_context(555)), "")

    def test_relay_card_carries_the_line(self):
        from handlers import support_relay as sr
        message = MagicMock()
        message.text = "Achchiq chiqdi"
        message.from_user.id = 555
        message.from_user.full_name = "Салима"
        message.from_user.username = None
        message.answer = AsyncMock()
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(chat=MagicMock(id=1), message_id=9))
        with patch.object(sr, "ADMIN_IDS", [1]), \
             patch.object(sr, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(sr, "log_support_message", AsyncMock()), \
             patch.object(sr, "count_open_support", AsyncMock(return_value=1)), \
             patch.object(sr, "release_support_claim", AsyncMock()), \
             patch.object(sr, "record_support_relay", AsyncMock()), \
             patch.object(rf, "reply_context", AsyncMock(return_value="⭐ <b>Past baho sababi:</b> Zakvaska\n\n")):
            run(sr.relay_freeform_text(message, bot))
        card = bot.send_message.await_args.args[1]
        self.assertTrue(card.startswith("⭐ <b>Past baho sababi:</b> Zakvaska"))
        self.assertIn("Achchiq chiqdi", card)


if __name__ == "__main__":
    unittest.main()
