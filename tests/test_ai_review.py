"""Kunlik AI o'z-o'zini tekshirish va darslar (ai_review.py, egasi 2026-11-27)."""
import asyncio
import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ai_review
import ai_sales


class ReportTest(unittest.TestCase):
    def test_input_lists_turns_and_existing_lessons(self):
        turns = [{"channel": "bot", "question": "Salom", "answer": "Assalomu alaykum"}]
        text = ai_review.review_input(turns, ["Suhbat o'rtasida salom berma"])
        self.assertIn("[1] bot | MIJOZ: Salom", text)
        self.assertIn("- Suhbat o'rtasida salom berma", text)

    def test_report_quotes_problem_turn(self):
        turns = [{"channel": "sayt", "question": "Narxi <qancha>?", "answer": "Zo'r!"}]
        out = ai_review.report_text({"score": 6, "summary": "Yaxshi", "issues": [{"turn": 1, "problem": "qolip"}],
                                     "lessons": []}, turns)
        self.assertIn("6/10", out)
        self.assertIn("qolip", out)
        self.assertIn("&lt;qancha&gt;", out)

    def test_buttons(self):
        kb = ai_review.lesson_kb(7)
        self.assertEqual([b.callback_data for b in kb.inline_keyboard[0]], ["aidars:ok:7", "aidars:no:7"])


class RunTest(unittest.TestCase):
    def test_sends_report_and_one_message_per_lesson(self):
        turns = [{"channel": "bot", "question": f"q{i}", "answer": f"a{i}"} for i in range(5)]
        result = {"score": 7, "summary": "s", "issues": [], "lessons": ["Dars bir", " ", "Dars ikki"]}
        bot = NS(send_message=AsyncMock())
        with patch.object(ai_review, "_turns", AsyncMock(return_value=turns)), \
                patch.object(ai_review, "_existing_lessons", AsyncMock(return_value=[])), \
                patch.object(ai_review, "_ask", AsyncMock(return_value=result)), \
                patch.object(ai_review, "save_lessons", AsyncMock(return_value=[11, 12])) as save:
            out = asyncio.run(ai_review.run_review(bot, [99]))
        save.assert_awaited_once_with(["Dars bir", "Dars ikki"])
        self.assertEqual(bot.send_message.await_count, 3)
        self.assertEqual(bot.send_message.await_args_list[2].kwargs["reply_markup"].inline_keyboard[0][0].callback_data,
                         "aidars:ok:12")
        self.assertIn("2 dars", out)

    def test_few_turns_no_model_call(self):
        ask = AsyncMock()
        with patch.object(ai_review, "_turns", AsyncMock(return_value=[])), patch.object(ai_review, "_ask", ask):
            asyncio.run(ai_review.run_review(NS(send_message=AsyncMock()), [99]))
        ask.assert_not_awaited()


class DecideTest(unittest.TestCase):
    def _pool(self, row):
        conn = MagicMock()
        conn.execute = AsyncMock()
        conn.fetchrow = AsyncMock(return_value=row)
        ctx = MagicMock()
        ctx.__aenter__ = AsyncMock(return_value=conn)
        ctx.__aexit__ = AsyncMock(return_value=False)
        return NS(acquire=lambda: ctx), conn

    def test_approve_adds_fact_and_refreshes(self):
        pool, conn = self._pool({"id": 5, "text": "Qisqa yoz"})
        with patch.object(ai_review.database, "pool", pool, create=True), \
                patch.object(ai_review.database, "add_ai_fact", AsyncMock(return_value=42)) as add, \
                patch.object(ai_sales, "invalidate_knowledge") as inv:
            row = asyncio.run(ai_review.decide(5, True, 917456291))
        add.assert_awaited_once_with("DARS: Qisqa yoz", 917456291)
        inv.assert_called_once()
        self.assertEqual(row["text"], "Qisqa yoz")

    def test_reject_or_repeat_never_adds(self):
        for row in ({"id": 5, "text": "x"}, None):
            pool, _ = self._pool(row)
            with patch.object(ai_review.database, "pool", pool, create=True), \
                    patch.object(ai_review.database, "add_ai_fact", AsyncMock()) as add:
                asyncio.run(ai_review.decide(5, row is None, 1))
            add.assert_not_awaited()


class CallbackTest(unittest.TestCase):
    def test_non_owner_denied(self):
        cb = NS(from_user=NS(id=1), data="aidars:ok:5", answer=AsyncMock())
        with patch.object(ai_sales, "is_owner", return_value=False), \
                patch.object(ai_review, "decide", AsyncMock()) as decide:
            asyncio.run(ai_review.cb_lesson(cb))
        decide.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
