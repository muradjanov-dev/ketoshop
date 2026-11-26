"""AI ishlamagan paytdagi javobsiz savollarga kechikkan javob (egasi,
2026-11-26). Bazasiz, tarmoqsiz: bot, guruh va Instagram Direct yo'llari."""
import asyncio
import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ai_sales
import ig_direct
import missed_replies


def _run(coro):
    return asyncio.run(coro)


class BotLateAnswerTest(unittest.TestCase):
    def test_media_cards_are_dropped_from_the_question(self):
        self.assertEqual(missed_replies.bot_question_text(
            ["🖼 Rasm yubordi (to'lov cheki emas)", "bodom uni bormi?", " ", "narxi?"]),
            "bodom uni bormi?\nnarxi?")

    def test_sorry_only_on_the_first_message(self):
        bot = NS(send_message=AsyncMock())
        chat = missed_replies._LateChat(bot, {"user_id": 5, "first_name": "Ali"}, "salom", "Uzr 🙏")
        _run(chat.answer("Bor, 45 000 so'm."))
        _run(chat.answer("Yana nima kerak?"))
        first, second = [c.args for c in bot.send_message.await_args_list]
        self.assertEqual(first, (5, "Uzr 🙏\n\nBor, 45 000 so'm."))
        self.assertEqual(second, (5, "Yana nima kerak?"))

    def _answer_bot(self, eligible=True, fail=False):
        bot = NS(send_message=AsyncMock())

        async def fake_answer(b, chat, text, late=False):
            self.assertTrue(late)
            if fail:
                raise RuntimeError("credit_balance_exhausted")
            await chat.answer(f"Javob: {text}")

        closed, cards = AsyncMock(), AsyncMock()
        with patch.object(missed_replies, "open_bot_questions",
                          AsyncMock(return_value=[{"user_id": 9, "texts": ["bodom uni bormi?"]}])), \
                patch.object(missed_replies, "_eligible", AsyncMock(return_value=eligible)), \
                patch.object(missed_replies, "_user_info", AsyncMock(return_value={"user_id": 9})), \
                patch.object(missed_replies, "_close_bot_cards", cards), \
                patch.object(missed_replies, "close_bot_questions", closed), \
                patch.object(missed_replies, "PAUSE", (0, 0)), \
                patch.object(ai_sales, "_lang", AsyncMock(return_value="uz")), \
                patch.object(ai_sales, "_answer", fake_answer):
            stats = _run(missed_replies.answer_bot(bot))
        return bot, stats, cards, closed

    def test_answers_and_closes_the_admin_cards(self):
        bot, stats, cards, closed = self._answer_bot()
        self.assertEqual(stats["sent"], 1)
        text = bot.send_message.await_args.args[1]
        self.assertTrue(text.startswith(missed_replies.SORRY["uz"]))
        self.assertIn("Javob: bodom uni bormi?", text)
        cards.assert_awaited_once()
        closed.assert_awaited_once_with(9, "replied")

    def test_not_eligible_is_left_for_the_admins(self):
        bot, stats, cards, _ = self._answer_bot(eligible=False)
        self.assertEqual(stats, {"sent": 0, "skipped": 1})
        bot.send_message.assert_not_awaited()
        cards.assert_not_awaited()

    def test_ai_still_down_stops_the_tick_and_keeps_the_queue(self):
        with self.assertRaises(RuntimeError):
            self._answer_bot(fail=True)

    def test_tick_waits_at_night(self):
        night = datetime(2026, 11, 26, 2, 0)
        self.assertFalse(missed_replies.in_hours(night))
        self.assertTrue(missed_replies.in_hours(datetime(2026, 11, 26, 14, 0)))


class AiSalesHooksTest(unittest.TestCase):
    def _message(self):
        return NS(from_user=NS(id=31, first_name="Vali", full_name="Vali", username=None),
                  chat=NS(id=31, type="private"), message_id=7, reply_to_message=None,
                  answer=AsyncMock(), reply=AsyncMock())

    def test_late_answer_raises_instead_of_a_second_admin_card(self):
        fallback = AsyncMock()
        with patch.object(ai_sales, "_respond", AsyncMock(side_effect=RuntimeError("down"))), \
                patch.object(ai_sales, "_fallback_to_admins", fallback):
            with self.assertRaises(RuntimeError):
                _run(ai_sales._answer(None, self._message(), "salom", late=True))
            _run(ai_sales._answer(None, self._message(), "salom"))
        fallback.assert_awaited_once()

    def test_failed_bot_question_is_flagged_for_a_late_answer(self):
        remember = AsyncMock()
        with patch.object(missed_replies, "remember_bot", remember), \
                patch("handlers.support_relay.relay_text", AsyncMock()):
            _run(ai_sales._fallback_to_admins(None, self._message(), "bodom uni bormi?"))
        remember.assert_awaited_once_with(31, "bodom uni bormi?")

    def test_failed_group_question_is_stored_and_late_mode_raises(self):
        msg = self._message()
        msg.chat = NS(id=-100, type="supergroup")
        remember = AsyncMock()
        with patch.object(ai_sales, "_group_respond", AsyncMock(side_effect=RuntimeError("down"))), \
                patch.object(ai_sales.ai_dialog, "recent", AsyncMock(return_value=[])), \
                patch.object(ai_sales, "_group_memory", AsyncMock(return_value="")), \
                patch.object(missed_replies, "remember_group", remember):
            _run(ai_sales._group_answer(None, msg, "qancha turadi?"))
            remember.assert_awaited_once_with(-100, 7, 31, "Vali", "qancha turadi?", "")
            with self.assertRaises(RuntimeError):
                _run(ai_sales._group_answer(None, msg, "qancha turadi?", late_background="[post]"))

    def test_group_late_reply_goes_under_the_original_message(self):
        bot = NS(send_message=AsyncMock())
        msg = missed_replies._LateGroupMessage(
            bot, {"text": "narxi?", "message_id": 55, "author": "Ali", "user_id": 3, "chat_id": -100}, "Uzr 🙏")
        _run(msg.reply("45 000 so'm"))
        args, kwargs = bot.send_message.await_args
        self.assertEqual(args, (-100, "Uzr 🙏\n\n45 000 so'm"))
        self.assertEqual(kwargs["reply_to_message_id"], 55)


def _conv(now):
    t = now - timedelta(hours=2)
    return {"conversation_id": "c1", "customer_id": "u1", "messages": [
        {"message_id": "m1", "ours": False, "text": "salom", "created_at": t, "from_id": "u1"},
        {"message_id": "m2", "ours": False, "text": "bodom uni bormi?", "created_at": t, "from_id": "u1"},
        {"message_id": "m3", "ours": True, "text": "Xabaringiz uchun rahmat", "created_at": t, "from_id": "p"},
    ]}


class DirectLateReplyTest(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 26, 12, 0)

    def test_which_held_rows_were_ai_down(self):
        self.assertTrue(ig_direct._held_for_ai({"status": "held", "note": "ai_down"}))
        self.assertTrue(ig_direct._held_for_ai({"status": "held", "note": None, "intent": None, "text": "narxi?"}))
        self.assertFalse(ig_direct._held_for_ai({"status": "held", "intent": "shikoyat", "text": "x"}))
        self.assertFalse(ig_direct._held_for_ai({"status": "held", "note": None, "intent": "", "text": ""}))
        self.assertFalse(ig_direct._held_for_ai({"status": "held", "note": "kechikkan javob: closed"}))
        self.assertFalse(ig_direct._held_for_ai({"status": "replied"}))

    def test_last_batch_is_before_our_holding_reply(self):
        self.assertEqual([m["message_id"] for m in ig_direct.last_customer_batch(_conv(self.now))], ["m1", "m2"])

    def _late(self, plan, now=None):
        rows = {i: {"status": "held", "note": None, "intent": None, "text": "x"} for i in ("m1", "m2")}
        mark = AsyncMock(side_effect=lambda ids, *a, **k: list(ids))
        send = AsyncMock()
        with patch.object(ig_direct, "statuses", AsyncMock(return_value=rows)), \
                patch.object(ig_direct, "replies_since", AsyncMock(return_value=0)), \
                patch.object(ig_direct, "catalog_recent", AsyncMock(return_value=True)), \
                patch.object(ig_direct, "compose", AsyncMock(return_value=plan)), \
                patch.object(ig_direct, "mark", mark), \
                patch.object(ig_direct, "send_text", send), \
                patch.object(ig_direct, "PAUSE", (0, 0)):
            result = _run(ig_direct.late_reply(None, {}, _conv(self.now), now or self.now))
        return result, mark, send

    def test_real_answer_with_an_apology(self):
        plan = ig_direct.Plan("replied", ["Ha, bor — 45 000 so'm."], intent="mahsulot", lang="uz")
        result, mark, send = self._late(plan)
        self.assertEqual(result, "replied")
        self.assertEqual(send.await_args.args[3], ig_direct.LATE_SORRY["uz"] + "Ha, bor — 45 000 so'm.")
        self.assertEqual(mark.await_args.args[1], "replied")
        self.assertEqual(mark.await_args.kwargs["note"], ig_direct.LATE_DONE)

    def test_ai_still_down_sends_nothing(self):
        plan = ig_direct.Plan("held", ["..."], lang="uz", reason="ai_down")
        result, mark, send = self._late(plan)
        self.assertEqual(result, "retry")
        send.assert_not_awaited()
        mark.assert_not_awaited()

    def test_needs_a_human_is_not_asked_again(self):
        plan = ig_direct.Plan("held", ["..."], lang="uz", reason="shikoyat")
        result, mark, send = self._late(plan)
        self.assertEqual(result, "none")
        send.assert_not_awaited()
        self.assertTrue(mark.await_args.kwargs["note"].startswith(ig_direct.LATE_DONE))

    def test_outside_the_24h_window_nothing(self):
        result, mark, send = self._late(ig_direct.Plan("replied", ["x"]), now=self.now + timedelta(hours=23))
        self.assertEqual(result, "none")
        send.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
