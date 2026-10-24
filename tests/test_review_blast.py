"""Fikr so'rovi — every buyer asked once about what they bought (owner,
2026-10-24). No Telegram and no database: nobody gets a real message."""
import asyncio
import os
import re
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import review_blast as rb


def run(coro):
    return asyncio.run(coro)


CATALOG = {
    1: {"id": 1, "name": "Eritritol 500 gr", "name_ru": "Эритритол 500 г"},
    2: {"id": 2, "name": "Kokos uni", "name_ru": "Кокосовая мука"},
    3: {"id": 3, "name": "Stevia 100 gr", "name_ru": None},
    4: {"id": 4, "name": "Bodom uni — nozik maydalangan, oliy nav, katta qadoq", "name_ru": None},
}


def order(day, *items):
    return {"at": datetime(2026, 10, day, 12, 0), "items": list(items)}


class PicksTest(unittest.TestCase):
    def test_newest_first_without_gifts_sets_or_repeats(self):
        orders = [
            order(1, {"product_id": 2, "quantity": 1}, {"product_id": 1, "is_gift": True}),
            order(9, {"product_id": 3, "quantity": 2}, {"product_id": 5, "is_set": True},
                  {"product_id": 2, "quantity": 1}),
            order(5, {"product_id": 1, "is_bonus": True}, {"product_id": "4"}),
        ]
        self.assertEqual(rb.picks_for(orders, set(), CATALOG), [3, 2, 4])

    def test_reviewed_and_unknown_products_are_skipped(self):
        orders = [order(3, {"product_id": 1}, {"product_id": 2}, {"product_id": 99},
                        {"product_id": None}, "junk")]
        self.assertEqual(rb.picks_for(orders, {1}, CATALOG), [2])
        self.assertEqual(rb.picks_for(orders, {1, 2}, CATALOG), [])


class TextTest(unittest.TestCase):
    def test_each_language(self):
        uz = rb.message_text("uz", "Dilnoza Karimova", True)
        self.assertTrue(uz.startswith("Assalomu alaykum, Dilnoza! 🌿"))
        self.assertIn("ma'qul keldimi", uz)
        self.assertIn("izoh", uz)
        ru = rb.message_text("ru", "Ольга", True)
        self.assertIn("понравились ли вам наши продукты", ru)
        cyr = rb.message_text("uz_cyr", "Dilnoza", False)
        self.assertTrue(cyr.startswith("Ассалому алайкум, Dilnoza! 🌿"))
        self.assertNotIn("{", cyr)
        self.assertIn("Ketoshop дўконидан", cyr)
        self.assertNotIn("Ketoshopъ", rb.message_text("uz_cyr", "Dilnoza", True))
        # Only the brand and the buyer's own Latin name stay Latin.
        self.assertEqual(sorted(set(re.findall(r"[A-Za-z]+", re.sub(r"<[^>]+>", "", cyr)))),
                         ["Dilnoza", "Ketoshop"])

    def test_general_text_when_everything_is_reviewed(self):
        self.assertIn("baho qo'yganingiz uchun", rb.message_text("uz", None, False))
        self.assertTrue(rb.message_text("uz", None, False).startswith("Assalomu alaykum! 🌿"))

    def test_name_is_escaped(self):
        self.assertIn("Ali&lt;b&gt;", rb.message_text("uz", "Ali<b>", True))

    def test_comment_prompt_keeps_skip_command(self):
        cyr = rb.say("comment", "uz_cyr", product="Кокос уни", stars="⭐⭐⭐⭐")
        self.assertIn("/skip", cyr)
        self.assertIn("<b>Кокос уни</b> — ⭐⭐⭐⭐", cyr)


class KeyboardTest(unittest.TestCase):
    def test_buttons(self):
        kb = rb.keyboard([4, 2], CATALOG, "ru")
        texts = [row[0].text for row in kb.inline_keyboard]
        self.assertEqual(texts[1], "⭐ Кокосовая мука")
        self.assertTrue(texts[0].endswith("…"))
        self.assertLessEqual(len(texts[0]), rb.NAME_MAX + 2)
        self.assertEqual([row[0].callback_data for row in kb.inline_keyboard], ["rbl:4", "rbl:2"])

    def test_capped_and_empty(self):
        many = {i: {"id": i, "name": f"Mahsulot {i}"} for i in range(20)}
        self.assertEqual(len(rb.keyboard(list(many), many, "uz").inline_keyboard), rb.MAX_BUTTONS)
        self.assertIsNone(rb.keyboard([], CATALOG, "uz"))

    def test_stars_callback_fits_telegram_limit(self):
        datas = [b.callback_data for b in rb.stars_keyboard(123456).inline_keyboard[0]]
        self.assertEqual(datas[0], "rbs:123456:1")
        self.assertTrue(all(len(d.encode()) <= 64 for d in datas))


class WindowTest(unittest.TestCase):
    def test_daytime_until_last_day(self):
        self.assertTrue(rb.in_window(datetime(2026, 10, 24, 17, 30)))
        self.assertFalse(rb.in_window(datetime(2026, 10, 24, 21, 0)))
        self.assertFalse(rb.in_window(datetime(2026, 10, 25, 8, 59)))
        self.assertTrue(rb.in_window(datetime(2026, 10, 26, 9, 0)))
        self.assertFalse(rb.in_window(datetime(2026, 10, 27, 12, 0)))

    def test_outside_window_touches_nothing(self):
        with patch.object(rb, "_round_finished", AsyncMock()) as finished:
            self.assertEqual(run(rb.run_once(MagicMock(), datetime(2026, 10, 24, 22, 0))), 0)
            finished.assert_not_called()

    def test_switch_off(self):
        with patch.dict(os.environ, {"REVIEW_BLAST": "0"}), \
                patch.object(rb, "_round_finished", AsyncMock()) as finished:
            self.assertEqual(run(rb.run_once(MagicMock(), datetime(2026, 10, 24, 12, 0))), 0)
            finished.assert_not_called()


class RunTest(unittest.TestCase):
    def test_each_buyer_once_and_summary_once(self):
        orders = {
            10: [order(20, {"product_id": 1}, {"product_id": 2})],
            11: [order(18, {"product_id": 3})],
            12: [order(15, {"product_id": 2})],
        }
        users = {10: {"user_id": 10, "full_name": "Aziza", "language": "uz"},
                 11: {"user_id": 11, "full_name": "Олег", "language": "ru"},
                 12: {"user_id": 12, "full_name": "Bek", "language": "uz_cyr"}}
        reviewed = {12: {2}}
        bot = MagicMock()
        bot.send_message = AsyncMock()
        claims = []

        async def claim(uid, n):
            claims.append((uid, n))
            return uid != 11          # 11 was claimed by an earlier tick

        noon = datetime(2026, 10, 24, 12, 0)
        with patch.object(rb, "_round_finished", AsyncMock(return_value=False)), \
                patch.object(rb, "_load_audience", AsyncMock(return_value=(orders, users, reviewed, CATALOG))), \
                patch.object(rb, "_claim", side_effect=claim), \
                patch.object(rb, "_set_delivered", AsyncMock()) as delivered, \
                patch.object(rb, "_finish_round", AsyncMock(return_value=True)), \
                patch.object(rb, "_round_counts", AsyncMock(return_value={"delivered": 2, "with_products": 1, "failed": 0})), \
                patch.object(rb, "_pause_ai") as pause, \
                patch.object(rb, "_now_tk", return_value=noon), \
                patch.object(rb, "SEND_DELAY", 0), \
                patch.object(rb, "ADMIN_IDS", [1, 2]):
            self.assertEqual(run(rb.run_once(bot, noon)), 2)

        self.assertEqual(claims, [(10, 2), (11, 1), (12, 0)])
        buyer_calls = [c for c in bot.send_message.await_args_list if c.args[0] in (10, 11, 12)]
        self.assertEqual([c.args[0] for c in buyer_calls], [10, 12])
        first_kb = buyer_calls[0].kwargs["reply_markup"].inline_keyboard
        self.assertEqual([r[0].callback_data for r in first_kb], ["rbl:1", "rbl:2"])
        self.assertIsNone(buyer_calls[1].kwargs["reply_markup"])     # everything reviewed
        self.assertEqual(delivered.await_count, 2)
        self.assertEqual(pause.call_count, 2)
        admin_calls = [c for c in bot.send_message.await_args_list if c.args[0] in (1, 2)]
        self.assertEqual(len(admin_calls), 2)
        self.assertIn("Fikr so'rovi yuborildi", admin_calls[0].args[1])

    def test_blocked_buyer_is_not_paused_or_marked(self):
        from aiogram.exceptions import TelegramForbiddenError
        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=TelegramForbiddenError(MagicMock(), "blocked"))
        noon = datetime(2026, 10, 24, 12, 0)
        with patch.object(rb, "_round_finished", AsyncMock(return_value=False)), \
                patch.object(rb, "_load_audience", AsyncMock(return_value=(
                    {10: [order(20, {"product_id": 1})]},
                    {10: {"user_id": 10, "full_name": "A", "language": "uz"}}, {}, CATALOG))), \
                patch.object(rb, "_claim", AsyncMock(return_value=True)), \
                patch.object(rb, "_set_delivered", AsyncMock()) as delivered, \
                patch.object(rb, "_finish_round", AsyncMock(return_value=False)), \
                patch.object(rb, "_pause_ai") as pause, \
                patch.object(rb, "_now_tk", return_value=noon), \
                patch.object(rb, "SEND_DELAY", 0):
            self.assertEqual(run(rb.run_once(bot, noon)), 0)
        delivered.assert_not_awaited()
        pause.assert_not_called()


class ReplyContextTest(unittest.TestCase):
    def test_marks_survey_answers_only(self):
        with patch.object(rb, "_recent_send", AsyncMock(return_value={"sent_at": datetime.utcnow()})):
            self.assertIn("Fikr so'roviga javob", run(rb.reply_context(5)))
        with patch.object(rb, "_recent_send", AsyncMock(return_value=None)):
            self.assertEqual(run(rb.reply_context(5)), "")


class CommentTest(unittest.TestCase):
    """handlers.reviews.process_comment — the step every survey review ends in."""

    def _message(self, text):
        msg = MagicMock()
        msg.text = text
        msg.from_user = MagicMock(id=10, username=None, full_name="Aziza")
        msg.answer = AsyncMock()
        return msg

    def _state(self, data):
        state = MagicMock()
        state.get_data = AsyncMock(return_value=data)
        state.clear = AsyncMock()
        return state

    def test_voice_note_asks_for_words_and_keeps_the_state(self):
        from handlers import reviews
        msg, state = self._message(None), self._state({"lang": "uz", "product_id": 2, "rating": 5})
        with patch.object(reviews, "add_review", AsyncMock()) as add:
            run(reviews.process_comment(msg, state))
        add.assert_not_awaited()
        state.clear.assert_not_awaited()
        self.assertIn("Sharh yozing", msg.answer.await_args.args[0])

    def test_survey_review_reaches_admins(self):
        from handlers import reviews
        msg = self._message("Juda mazali, yana olaman")
        state = self._state({"lang": "uz", "product_id": 2, "rating": 5, "src": "blast"})
        with patch.object(reviews, "add_review", AsyncMock()) as add,                 patch.object(rb, "notify_review", AsyncMock()) as notify:
            run(reviews.process_comment(msg, state))
        add.assert_awaited_once_with(user_id=10, product_id=2, rating=5,
                                     comment="Juda mazali, yana olaman")
        self.assertEqual(notify.await_args.args[2:], (2, 5, "Juda mazali, yana olaman"))
        self.assertIn("yuqoridagi ro'yxatdan", msg.answer.await_args.args[0])

    def test_ordinary_review_is_unchanged(self):
        from handlers import reviews
        msg, state = self._message("/skip"), self._state({"lang": "ru", "product_id": 3, "rating": 4})
        with patch.object(reviews, "add_review", AsyncMock()) as add,                 patch.object(rb, "notify_review", AsyncMock()) as notify:
            run(reviews.process_comment(msg, state))
        self.assertIsNone(add.await_args.kwargs["comment"])
        notify.assert_not_awaited()
        self.assertNotIn("👆", msg.answer.await_args.args[0])


if __name__ == "__main__":
    unittest.main()
