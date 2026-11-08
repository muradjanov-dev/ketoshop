"""YANGI5 — yangi a'zoga birinchi buyurtmaga 8 soat 5% (egasi, 2026-11-06).
Bazaga ulanmaydi, xabar yuborilmaydi."""
import asyncio
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import bot_discount
import database
import welcome_promo as wp

NOW = datetime(2026, 11, 7, 7, 0)          # 12:00 Tashkent
USER = 555


def run(coro):
    return asyncio.run(coro)


class Pool:
    """Swallows the few writes step() makes."""
    def __init__(self):
        self.executed = []

    def acquire(self):
        pool = self

        class Conn:
            async def execute(self, sql, *args):
                pool.executed.append((sql, args))

        class _Ctx:
            async def __aenter__(self):
                return Conn()

            async def __aexit__(self, *a):
                return False
        return _Ctx()


def window(started, order=None):
    return (patch.object(wp, "_now", return_value=NOW),
            patch.object(wp, "_started_at", AsyncMock(return_value=started)),
            patch.object(wp, "_first_order", AsyncMock(return_value=order)))


class WindowTest(unittest.TestCase):
    def pct(self, started, order=None, user=USER):
        a, b, c = window(started, order)
        with a, b, c:
            return run(wp.percent_for(user))

    def test_open_for_eight_hours_until_the_first_order(self):
        self.assertEqual(self.pct(NOW - timedelta(hours=1)), 5)
        self.assertEqual(self.pct(NOW - timedelta(hours=7, minutes=59)), 5)
        self.assertEqual(self.pct(NOW - timedelta(hours=8)), 0)
        self.assertEqual(self.pct(NOW - timedelta(hours=1), order={"id": 1, "items": []}), 0)
        self.assertEqual(self.pct(None), 0)

    def test_admins_never(self):
        with patch.object(wp, "ADMIN_IDS", [USER]):
            self.assertEqual(self.pct(NOW - timedelta(hours=1)), 0)

    def test_a_db_error_means_no_discount_not_a_broken_checkout(self):
        with patch.object(wp, "_started_at", AsyncMock(side_effect=RuntimeError("db"))):
            self.assertEqual(run(wp.percent_for(USER)), 0)

    def test_bot_discount_rides_on_it(self):
        with patch.object(bot_discount, "is_active", AsyncMock(return_value=False)), \
             patch.object(wp, "percent_for", AsyncMock(return_value=5)):
            self.assertEqual(run(bot_discount.percent_for(USER)), 5)
        with patch.object(bot_discount, "is_active", AsyncMock(return_value=True)), \
             patch.object(wp, "percent_for", AsyncMock(return_value=5)):
            self.assertEqual(run(bot_discount.percent_for(USER)), 10)     # the bigger campaign wins
        with patch.object(bot_discount, "is_active", AsyncMock(return_value=False)), \
             patch.object(wp, "percent_for", AsyncMock(return_value=5)), \
             patch.object(bot_discount, "ADMIN_IDS", [USER]):
            self.assertEqual(run(bot_discount.percent_for(USER)), 0)

    def test_labels(self):
        self.assertEqual(bot_discount.saving_label("uz", 5), "🎁 YANGI5 — yangi a'zo chegirmasi (−5%)")
        self.assertIn("YANGI5", bot_discount.saving_label("ru", 5))
        self.assertIn("Bot orqali", bot_discount.saving_label("uz", 10))
        self.assertEqual(bot_discount.saving_label("uz_cyr", 5), "🎁 YANGI5 — янги аъзо чегирмаси (−5%)")

    def test_never_stacks_on_a_deeper_product_discount(self):
        self.assertEqual(bot_discount.line_price(10000, 10000, 5), 9500)
        self.assertEqual(bot_discount.line_price(10000, 8000, 5), 8000)


class TextTest(unittest.TestCase):
    def test_time_left(self):
        self.assertEqual(wp.left_text(7 * 3600 + 42 * 60 + 30, "uz"), "7 soat 42 daqiqa")
        self.assertEqual(wp.left_text(42 * 60, "uz"), "42 daqiqa")
        self.assertEqual(wp.left_text(3 * 3600 + 5 * 60, "ru"), "3 ч 5 мин")
        self.assertEqual(wp.left_text(-5, "uz"), "0 daqiqa")
        self.assertEqual(wp.left_text(7 * 3600, "uz"), "7 soat")
        self.assertEqual(wp.left_text(2 * 3600, "ru"), "2 ч")

    def test_until_today_or_tomorrow(self):
        self.assertEqual(wp.until_text(NOW + timedelta(hours=8), "uz", NOW), "Bugun 20:00 gacha")
        late = datetime(2026, 11, 7, 17, 0)                      # 22:00 Tashkent
        self.assertEqual(wp.until_text(late + timedelta(hours=8), "uz", late), "Ertaga 06:00 gacha")

    def test_quiet_hours(self):
        self.assertTrue(wp.is_quiet(datetime(2026, 11, 7, 17, 0)))    # 22:00
        self.assertTrue(wp.is_quiet(datetime(2026, 11, 7, 2, 59)))    # 07:59
        self.assertFalse(wp.is_quiet(datetime(2026, 11, 7, 3, 0)))    # 08:00
        self.assertFalse(wp.is_quiet(datetime(2026, 11, 7, 16, 59)))  # 21:59

    def test_every_text_in_three_languages(self):
        for lang in ("uz", "uz_cyr", "ru"):
            text = wp.timer_text(lang, 3600, NOW + timedelta(hours=1), NOW)
            self.assertIn("5%", text)
            self.assertEqual(text.count("<b>"), text.count("</b>"))
        cyr = wp.timer_text("uz_cyr", 3600, NOW + timedelta(hours=1), NOW)
        self.assertIn("Биринчи буюртмангизга 5% чегирма", cyr)
        self.assertIn("YANGI5", cyr)                                     # the name is never transliterated
        self.assertNotIn("ъ", cyr.split("—")[0])

    def test_order_saving_counts_only_yangi5_lines(self):
        order = {"items": [{"price": 9500, "original_price": 10000, "quantity": 2, "bot_discount": 5},
                           {"price": 8000, "original_price": 10000, "quantity": 1},
                           {"price": 0, "quantity": 1, "is_gift": True}]}
        self.assertEqual(wp.order_saving(order), 1000)


class StepTest(unittest.TestCase):
    def row(self, started, done=0, msg=77):
        return {"user_id": USER, "lang": "uz", "started_at": started, "reminders_done": done,
                "timer_message_id": msg}

    def step(self, row, order=None, cart=(200000, 10000), now=NOW):
        bot = MagicMock()
        bot.send_message = AsyncMock()
        bot.edit_message_text = AsyncMock()
        pool = Pool()
        wp._shown.clear()
        with patch.object(database, "pool", pool), \
             patch.object(database, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(wp, "_first_order", AsyncMock(return_value=order)), \
             patch.object(wp, "cart_numbers", AsyncMock(return_value=cart)):
            run(wp.step(bot, row, now))
        return bot, pool

    def test_reminder_at_two_hours_with_what_the_cart_saves(self):
        bot, pool = self.step(self.row(NOW - timedelta(hours=2, minutes=1)))
        text = bot.send_message.await_args.args[1]
        self.assertIn("5 soat 59 daqiqa qoldi", text)
        self.assertIn("200 000 so'mlik", text)
        self.assertIn("10 000 so'm tejaysiz", text)
        self.assertIn("190 000", text)
        self.assertEqual(pool.executed[0][1], (USER, 1))
        bot.edit_message_text.assert_awaited()                          # the timer moved on

    def test_empty_cart_gets_the_example(self):
        bot, _ = self.step(self.row(NOW - timedelta(hours=4, minutes=1), done=1), cart=(0, 0))
        self.assertIn("300 000 so'mlik buyurtmada <b>15 000 so'm</b>", bot.send_message.await_args.args[1])

    def test_no_reminder_at_night_but_it_is_used_up(self):
        night = datetime(2026, 11, 7, 18, 0)                           # 23:00 Tashkent
        bot, pool = self.step(self.row(night - timedelta(hours=2, minutes=1)), now=night)
        bot.send_message.assert_not_awaited()
        self.assertEqual(pool.executed[0][1], (USER, 1))

    def test_a_long_overdue_reminder_is_skipped(self):
        bot, pool = self.step(self.row(NOW - timedelta(hours=3, minutes=30)))
        bot.send_message.assert_not_awaited()
        self.assertEqual(pool.executed[0][1], (USER, 1))

    def test_nothing_due_only_the_timer(self):
        bot, pool = self.step(self.row(NOW - timedelta(minutes=30)))
        bot.send_message.assert_not_awaited()
        self.assertEqual(pool.executed, [])
        text = bot.edit_message_text.await_args.args[0]
        self.assertIn("Qoldi: 7 soat 30 daqiqa", text)

    def test_first_order_closes_it_with_the_saving(self):
        order = {"id": 901, "items": [{"price": 9500, "original_price": 10000, "quantity": 3, "bot_discount": 5}]}
        bot, pool = self.step(self.row(NOW - timedelta(hours=1)), order=order)
        self.assertIn("closed_at", pool.executed[0][0])
        text = bot.edit_message_text.await_args.args[0]
        self.assertIn("#901", text)
        self.assertIn("1 500 so'm", text)
        bot.send_message.assert_not_awaited()

    def test_time_up_closes_it(self):
        bot, pool = self.step(self.row(NOW - timedelta(hours=8, minutes=1), done=3))
        self.assertIn("closed_at", pool.executed[0][0])
        self.assertIn("muddati tugadi", bot.edit_message_text.await_args.args[0])


class StartTest(unittest.TestCase):
    def test_starts_once_and_sends_the_timer(self):
        started = datetime.utcnow()
        calls = []

        class Conn:
            async def execute(self, sql, *args):
                calls.append(("execute", sql, args))

            async def fetchval(self, sql, *args):
                calls.append(("fetchval", sql, args))
                return started if "UPDATE welcome_promo SET started_at" in sql else None

        class P:
            def acquire(self):
                class _Ctx:
                    async def __aenter__(self):
                        return Conn()

                    async def __aexit__(self, *a):
                        return False
                return _Ctx()

        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=42))
        with patch.object(database, "pool", P()), patch.object(wp, "_table_ready", True):
            self.assertTrue(run(wp.maybe_start(bot, USER, "ru")))
        self.assertIn("Скидка 5%", bot.send_message.await_args.args[1])
        self.assertEqual(calls[-1][2], (USER, 42))

    def test_returning_user_is_a_no_op(self):
        class Conn:
            async def fetchval(self, sql, *args):
                return None

        class P:
            def acquire(self):
                class _Ctx:
                    async def __aenter__(self):
                        return Conn()

                    async def __aexit__(self, *a):
                        return False
                return _Ctx()

        bot = MagicMock()
        bot.send_message = AsyncMock()
        with patch.object(database, "pool", P()), patch.object(wp, "_table_ready", True):
            self.assertFalse(run(wp.maybe_start(bot, USER, "uz")))
        bot.send_message.assert_not_awaited()


class ShownTest(unittest.TestCase):
    def test_site_card_cart_ai(self):
        a, b, c = window(NOW - timedelta(hours=1))
        with a, b, c:
            site = run(wp.site_payload(USER, "uz"))
            card = run(wp.card_line(USER, {"price": 10000, "discount_percent": 0, "discount_until": None}, "uz"))
            # A real-clock future: effective_price checks discount_until
            # against the actual time, not the frozen NOW.
            deeper = run(wp.card_line(USER, {"price": 10000, "discount_percent": 20,
                                             "discount_until": datetime.utcnow() + timedelta(days=1)}, "uz"))
            line = run(wp.timer_line(USER, "ru"))
            ai = run(wp.ai_line(USER))
        self.assertEqual((site["code"], site["percent"], site["seconds_left"]), ("YANGI5", 5, 7 * 3600))
        self.assertIn("9 500 so'm", card)
        self.assertIn("⏳ 7 soat qoldi", card)
        self.assertEqual(deeper, "")
        self.assertIn("До конца YANGI5", line)
        self.assertIn("5% chegirma", ai)

    def test_nothing_when_closed(self):
        a, b, c = window(None)
        with a, b, c:
            self.assertIsNone(run(wp.site_payload(USER, "uz")))
            self.assertEqual(run(wp.timer_line(USER, "uz")), "")
            self.assertEqual(run(wp.ai_line(USER)), "")

    def test_cart_numbers_follow_the_checkout_rule(self):
        rows = [{"price": 10000, "cart_quantity": 2, "discount_percent": 0, "discount_until": None,
                 "product_id": 1},
                {"price": 50000, "cart_quantity": 1, "is_set": True, "set_id": 3}]
        with patch.object(database, "get_cart", AsyncMock(return_value=rows)), \
             patch.object(bot_discount, "_cost_maps", AsyncMock(return_value=({}, {}))):
            total, saved = run(wp.cart_numbers(USER))
        self.assertEqual(total, 70000)
        self.assertEqual(saved, 3500)


if __name__ == "__main__":
    unittest.main()
