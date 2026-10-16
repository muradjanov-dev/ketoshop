"""Keto savol — har 2 kunda bitta savol botdan hammaga, javobdan keyin
saytga taklif (egasi, 2026-10-16). Telegram va bazaga ulanmasdan — hamma
yuborish mock."""
import os
import re
import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from aiogram.exceptions import TelegramForbiddenError

import daily_quiz
import database
import quiz_bank


class MessageTest(unittest.TestCase):
    def test_question_in_three_languages(self):
        item = quiz_bank.build_item("quiz:q05")
        for lang, word in (("uz", "Keto savol"), ("uz_cyr", "Кето савол"), ("ru", "Кето-вопрос")):
            text, kb = daily_quiz.question_message(item, 12, lang)
            self.assertIn(word, text)
            rows = kb.inline_keyboard
            self.assertEqual(len(rows), 4)
            self.assertEqual([r[0].callback_data for r in rows], [f"dq:12:{p}" for p in range(4)])
            self.assertTrue(all(re.match(r"[ABCD]\) ", r[0].text) for r in rows))
        text, kb = daily_quiz.question_message(item, 12, "uz_cyr")
        latin = re.findall(r"[A-Za-z]{2,}", re.sub(r"<[^>]+>", "", text) + " ".join(r[0].text for r in kb.inline_keyboard))
        self.assertEqual(latin, [])

    def test_keto_question_has_yes_no_buttons(self):
        text, kb = daily_quiz.question_message(quiz_bank.build_item("keto:Asal"), 3, "uz")
        self.assertIn("«Asal» keto uchun mos keladimi?", text)
        self.assertEqual([r[0].text for r in kb.inline_keyboard], ["👍 Ha, mos", "👎 Yo'q, mos emas"])

    def test_answer_marks_explains_and_invites_to_the_game(self):
        item = quiz_bank.build_item("quiz:q05")
        order = quiz_bank.option_order(item, 12)
        wrong_pos = next(p for p, o in enumerate(order) if o != 0)
        right_pos = order.index(0)
        with patch.object(daily_quiz, "WEBAPP_URL", "https://keto.example/"):
            text, kb = daily_quiz.answer_message(item, 12, wrong_pos, "uz", 10, 7)
        lines = text.split("\n")
        option_lines = [l for l in lines if re.match(r"^(✅|❌|▫️) [ABCD]\) ", l)]
        self.assertEqual(len(option_lines), 4)
        self.assertTrue(option_lines[right_pos].startswith("✅"))
        self.assertTrue(option_lines[wrong_pos].startswith("❌"))
        self.assertIn("💡 Bodom unida ~10 g", text)
        self.assertIn("10 kishi javob berdi, 70% i to'g'ri topdi", text)
        button = kb.inline_keyboard[0][0]
        self.assertEqual(button.web_app.url, "https://keto.example/?game=quiz")
        self.assertIn("saytda", button.text)

    def test_game_link_per_kind_and_no_button_without_url(self):
        with patch.object(daily_quiz, "WEBAPP_URL", "https://keto.example"):
            self.assertTrue(daily_quiz.game_url(quiz_bank.build_item("keto:Asal")).endswith("?game=keto"))
            self.assertTrue(daily_quiz.game_url(quiz_bank.build_item("duel:Avokado|Banan")).endswith("?game=duel"))
        with patch.object(daily_quiz, "WEBAPP_URL", ""):
            _, kb = daily_quiz.answer_message(quiz_bank.build_item("keto:Asal"), 1, 0, "ru", 0, 0)
            self.assertIsNone(kb)


class AnswerHandlerTest(unittest.IsolatedAsyncioTestCase):
    def callback(self, data):
        cb = MagicMock()
        cb.data = data
        cb.from_user.id = 77
        cb.answer = AsyncMock()
        cb.message.edit_text = AsyncMock()
        return cb

    async def answer(self, data, recorded=True):
        cb = self.callback(data)
        with patch.object(database, "get_daily_quiz_send", AsyncMock(return_value={"item_key": "keto:Asal"})), \
             patch.object(database, "get_user_language", AsyncMock(return_value="ru")), \
             patch.object(database, "record_daily_quiz_answer", AsyncMock(return_value=recorded)) as rec, \
             patch.object(database, "daily_quiz_stats", AsyncMock(return_value=(4, 3))), \
             patch.object(daily_quiz, "WEBAPP_URL", "https://keto.example"):
            await daily_quiz.on_answer(cb)
        return cb, rec

    async def test_right_answer(self):
        cb, rec = await self.answer("dq:5:1")              # honey: "Нет" is right
        rec.assert_awaited_once_with(5, 77, 1, True)
        self.assertIn("Верно", cb.answer.await_args.args[0])
        text = cb.message.edit_text.await_args.args[0]
        self.assertIn("✅ 👎 Нет, не подходит", text)
        self.assertIn("Ответили 4 чел., верно — 75%", text)

    async def test_wrong_answer_names_the_right_one(self):
        cb, rec = await self.answer("dq:5:0")
        rec.assert_awaited_once_with(5, 77, 0, False)
        popup = cb.answer.await_args
        self.assertIn("Нет, не подходит", popup.args[0])
        self.assertTrue(popup.kwargs["show_alert"])
        self.assertIn("❌ 👍 Да, подходит", cb.message.edit_text.await_args.args[0])

    async def test_second_answer_is_not_counted(self):
        cb, _ = await self.answer("dq:5:0", recorded=False)
        self.assertIn("уже ответили", cb.answer.await_args.args[0])
        cb.message.edit_text.assert_not_awaited()

    async def test_broken_or_unknown(self):
        cb = self.callback("dq:x:y")
        await daily_quiz.on_answer(cb)
        cb.answer.assert_awaited_once_with()
        with patch.object(database, "get_daily_quiz_send", AsyncMock(return_value=None)):
            cb = self.callback("dq:9:0")
            await daily_quiz.on_answer(cb)
            cb.message.edit_text.assert_not_awaited()


class SchedulerTest(unittest.IsolatedAsyncioTestCase):
    async def tick(self, now, last, enabled=True):
        with patch.object(daily_quiz, "_now_tk", lambda: now), \
             patch.object(database, "daily_quiz_enabled", AsyncMock(return_value=enabled)), \
             patch.object(database, "daily_quiz_last_day", AsyncMock(return_value=last)), \
             patch.object(database, "daily_quiz_recent", AsyncMock(return_value=[])), \
             patch.object(daily_quiz, "send_round", AsyncMock(return_value=None)) as send:
            await daily_quiz._tick(MagicMock())
        return send

    async def test_every_two_days_in_the_evening(self):
        evening = datetime(2026, 10, 16, 20, 5)
        (await self.tick(evening, None)).assert_awaited_once_with(unittest.mock.ANY, date(2026, 10, 16))
        (await self.tick(evening, date(2026, 10, 14))).assert_awaited_once()
        (await self.tick(evening, date(2026, 10, 15))).assert_not_awaited()     # only 1 day ago
        (await self.tick(datetime(2026, 10, 16, 19, 59), None)).assert_not_awaited()
        (await self.tick(datetime(2026, 10, 16, 22, 0), None)).assert_not_awaited()
        (await self.tick(evening, None, enabled=False)).assert_not_awaited()

    async def test_send_round_to_everyone_in_their_language(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=[None, None, TelegramForbiddenError(method=None, message="blocked")])
        with patch.object(database, "daily_quiz_sent_keys", AsyncMock(return_value=set())), \
             patch.object(database, "start_daily_quiz", AsyncMock(return_value=31)) as start, \
             patch.object(database, "get_all_user_ids", AsyncMock(return_value=[1, 2, 3])), \
             patch.object(database, "get_user_languages", AsyncMock(return_value={2: "ru"})), \
             patch.object(database, "finish_daily_quiz", AsyncMock()) as finish, \
             patch.object(daily_quiz, "SEND_DELAY", 0):
            result = await daily_quiz.send_round(bot, date(2026, 10, 16))
        self.assertEqual((result["sent"], result["failed"]), (2, 1))
        self.assertEqual(start.await_args.args[0], date(2026, 10, 16))
        self.assertFalse(start.await_args.kwargs["is_test"])
        finish.assert_awaited_once_with(31, 2, 1)
        self.assertIn("Кето-вопрос", bot.send_message.await_args_list[1].args[1])
        self.assertIn("Keto savol", bot.send_message.await_args_list[0].args[1])

    async def test_claimed_day_sends_nothing_and_test_goes_to_one_admin(self):
        bot = MagicMock()
        bot.send_message = AsyncMock()
        with patch.object(database, "daily_quiz_sent_keys", AsyncMock(return_value=set())), \
             patch.object(database, "start_daily_quiz", AsyncMock(return_value=None)):
            self.assertIsNone(await daily_quiz.send_round(bot, date(2026, 10, 16)))
        bot.send_message.assert_not_awaited()
        with patch.object(database, "daily_quiz_sent_keys", AsyncMock(return_value=set())), \
             patch.object(database, "start_daily_quiz", AsyncMock(return_value=40)) as start, \
             patch.object(database, "get_all_user_ids", AsyncMock()) as everyone, \
             patch.object(database, "get_user_languages", AsyncMock(return_value={})), \
             patch.object(database, "finish_daily_quiz", AsyncMock()):
            result = await daily_quiz.send_round(bot, test_user=555)
        everyone.assert_not_awaited()
        self.assertIsNone(start.await_args.args[0])
        self.assertTrue(start.await_args.kwargs["is_test"])
        self.assertEqual(bot.send_message.await_args.args[0], 555)
        self.assertEqual(result["sent"], 1)

    def test_next_day(self):
        now = datetime(2026, 10, 16, 15, 0)
        self.assertEqual(daily_quiz._next_day(None, now), date(2026, 10, 16))
        self.assertEqual(daily_quiz._next_day(None, datetime(2026, 10, 16, 23, 0)), date(2026, 10, 17))
        self.assertEqual(daily_quiz._next_day(date(2026, 10, 16), now), date(2026, 10, 18))


if __name__ == "__main__":
    unittest.main()
