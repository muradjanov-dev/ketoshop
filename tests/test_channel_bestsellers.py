"""Public 30-day bestsellers; all Telegram and database IO stays offline."""
import asyncio
import json
import os
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
import channel_bestsellers


class RankingTest(unittest.IsolatedAsyncioTestCase):
    async def test_paid_quantities_rank_before_stock_filter_and_limit(self):
        orders = [{"items": json.dumps([
            {"product_id": 1, "quantity": 900, "price": 50},  # archived
            {"product_id": 2, "quantity": 2, "price": 50},
            {"product_id": 3, "quantity": 3, "price": 50},
            {"product_id": 3, "quantity": 100, "price": 50, "is_bonus": True},
            {"product_id": 3, "quantity": 200, "price": 50, "is_gift": True},
            {"product_id": 2, "quantity": 400, "price": 0},
            {"product_id": 4, "quantity": -10, "price": 50},
            {"product_id": 5, "quantity": "NaN", "price": 50},
            {"product_id": 6, "quantity": "bad", "price": 50},
        ])}, {"items": [{"product_id": 2, "quantity": 2, "price": 50}]}]
        conn = MagicMock()
        conn.fetch = AsyncMock(side_effect=[orders, [
            {"id": 3, "name": "Chia"}, {"id": 2, "name": "Bodom uni"},
        ]])
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        with patch.object(database, "pool", pool):
            result = await database.get_channel_bestsellers(limit=2)
        self.assertEqual([p["id"] for p in result], [2, 3])
        # Query contracts: current 30-day sales only; unavailable products
        # must be removed before the top ten is cut, without all-time fallback.
        sales_sql, *args = conn.fetch.await_args_list[0].args
        self.assertIn("status <> 'cancelled'", sales_sql)
        self.assertIn("created_at >=", sales_sql)
        self.assertIn("created_at <=", sales_sql)
        self.assertEqual(args[0], "30")
        self.assertIn("source IN ('manual', 'b2b') OR user_id <> ALL($2::bigint[])", sales_sql)
        self.assertEqual(args[1], database._activity_excluded_ids())
        product_sql = conn.fetch.await_args_list[1].args[0]
        self.assertEqual(set(conn.fetch.await_args_list[1].args[1]), {1, 2, 3})
        self.assertIn("is_active = 1", product_sql)
        self.assertIn("quantity > 0", product_sql)
        self.assertIn("b2b_only IS NOT TRUE", product_sql)

    async def test_empty_month_does_not_fall_back_to_old_sales(self):
        conn = MagicMock()
        conn.fetch = AsyncMock(return_value=[])
        pool = MagicMock()
        pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
        with patch.object(database, "pool", pool):
            self.assertEqual(await database.get_channel_bestsellers(), [])
        self.assertEqual(conn.fetch.await_count, 1)


class PostTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.posts = channel_bestsellers
        self.bot = MagicMock()
        self.bot.send_message = AsyncMock()
        self.claims = set()

    async def tick(self, now, products=None):
        async def claim(key):
            if key in self.claims:
                return False
            self.claims.add(key)
            return True

        async def release(key):
            self.claims.discard(key)

        with patch.object(self.posts, "_now_tk", return_value=now), \
             patch.object(self.posts, "REQUIRED_CHANNEL_ID", -100), \
             patch.object(database, "get_channel_bestsellers", AsyncMock(
                 return_value=products if products is not None else [
                     {"id": 2, "name": "Bodom uni", "qty": 987654, "quantity": 123456}
                 ])), \
             patch.object(database, "claim_release_notes", side_effect=claim), \
             patch.object(database, "release_release_notes", side_effect=release):
            await self.posts._tick(self.bot)

    async def test_every_third_day_daytime_and_restart_does_not_duplicate(self):
        for now in (datetime(2026, 10, 22, 12), datetime(2026, 10, 23, 9, 59)):
            await self.tick(now)
        self.bot.send_message.assert_not_awaited()
        await self.tick(datetime(2026, 10, 23, 10))
        await self.tick(datetime(2026, 10, 23, 11))  # another process/restart
        await self.tick(datetime(2026, 10, 24, 10))
        await self.tick(datetime(2026, 10, 25, 10))
        self.assertEqual(self.bot.send_message.await_count, 1)
        await self.tick(datetime(2026, 10, 26, 10))
        self.assertEqual(self.bot.send_message.await_count, 2)
        await self.tick(datetime(2026, 10, 29, 22))  # no late-night catch-up
        self.assertEqual(self.bot.send_message.await_count, 2)

    async def test_channel_payload_hides_sales_and_stock_but_opens_shop(self):
        await self.tick(datetime(2026, 10, 23, 10))
        call = self.bot.send_message.await_args
        self.assertEqual(call.args[0], -100)
        text = call.args[1]
        self.assertIn("Бодом уни", text)
        self.assertIn("30 кун", text)
        self.assertNotIn("987654", text)
        self.assertNotIn("123456", text)
        self.assertIn("https://t.me/", call.kwargs["reply_markup"].inline_keyboard[0][0].url)

    async def test_text_escapes_names_and_stays_within_telegram_limit(self):
        text = self.posts.build_text([{"name": "Un <yangi> & asal"}])
        self.assertIn("&lt;", text)
        self.assertIn("&amp;", text)
        text = self.posts.build_text([{"name": "A" * 2000} for _ in range(12)])
        self.assertLessEqual(len(text), 4096)
        self.assertNotIn("11. ", text)
        text = self.posts.build_text([{"name": "&" * 2000} for _ in range(10)])
        self.assertLessEqual(len(text), 4096)

    async def test_no_sales_means_no_post(self):
        await self.tick(datetime(2026, 10, 23, 10), products=[])
        self.bot.send_message.assert_not_awaited()

    async def test_definite_rejection_can_retry_but_timeout_cannot_duplicate(self):
        from aiogram.exceptions import TelegramBadRequest
        from aiogram.methods import SendMessage
        self.bot.send_message.side_effect = TelegramBadRequest(
            method=SendMessage(chat_id=-100, text="test"), message="rejected")
        with self.assertLogs("channel_bestsellers", level="WARNING"):
            await self.tick(datetime(2026, 10, 23, 10))
        self.assertEqual(self.claims, set())
        self.bot.send_message.side_effect = TimeoutError("delivery unknown")
        with self.assertLogs("channel_bestsellers", level="WARNING"):
            await self.tick(datetime(2026, 10, 23, 10, 5))
        self.bot.send_message.side_effect = None
        await self.tick(datetime(2026, 10, 23, 10, 10))
        self.assertEqual(self.bot.send_message.await_count, 2)

    async def test_shutdown_during_send_keeps_claim_against_restart_duplicate(self):
        self.bot.send_message.side_effect = asyncio.CancelledError
        with self.assertRaises(asyncio.CancelledError):
            await self.tick(datetime(2026, 10, 23, 10))
        self.bot.send_message.side_effect = None
        await self.tick(datetime(2026, 10, 23, 10, 5))
        self.assertEqual(self.bot.send_message.await_count, 1)


if __name__ == "__main__":
    unittest.main()
