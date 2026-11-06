"""Botdagi kuryer menyusi Kuryer doskasi holatlarida ishlaydi (2026-11-06):
olib ketilgan buyurtma «Yo'lda» (shipped) bo'ladi, doskadan yo'qolmaydi, har
bir harakat holat kartasi bo'lib boradi; buyurtma kuzatuvchisi bir marta
kuryer qilib qo'shiladi. Bazaga ulanmaydi, xabar yuborilmaydi."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
import order_admin_feed
import order_watchers
from handlers import courier


class Conn:
    def __init__(self, row):
        self.row = row
        self.executed = []
        self.fetched = []

    async def fetchrow(self, sql, *args):
        return dict(self.row) if self.row else None

    async def fetch(self, sql, *args):
        self.fetched.append((sql, args))
        return []

    async def execute(self, sql, *args):
        self.executed.append((sql, args))


class Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return _Ctx()


def press(data, row):
    conn = Conn(row)
    cb = MagicMock()
    cb.data = data
    cb.from_user.id = 7112339935
    cb.answer = AsyncMock()
    cb.message.edit_text = AsyncMock()
    bot = MagicMock()
    bot.send_message = AsyncMock()
    feed = MagicMock()
    with patch.object(database, "pool", Pool(conn)), \
         patch.object(courier, "is_courier", AsyncMock(return_value=True)), \
         patch.object(database, "get_user_language", AsyncMock(return_value="uz")), \
         patch.object(order_admin_feed, "status_changed", feed), \
         patch("gamification.award_keto_for_order", AsyncMock()), \
         patch("bloggers.award_for_order", AsyncMock()), \
         patch("referral_program.award_order_cashback", AsyncMock()):
        asyncio.run(courier.courier_callback_handler(cb, bot))
    return conn, feed, cb


ROW = {"id": 5, "courier_id": None, "delivery_method": "self", "status": "ready", "user_id": 10,
       "source": "bot", "customer_name": "Ali"}


class PickupTest(unittest.TestCase):
    def test_pickup_puts_the_order_on_the_road_column(self):
        conn, feed, _ = press("courier:pickup:5:0", ROW)
        sql, args = conn.executed[0]
        self.assertIn("status = 'shipped'", sql)
        self.assertIn("shipped_at", sql)
        self.assertEqual(args, (7112339935, 5))
        self.assertEqual(feed.call_args.args[1:4], (5, "ready", "shipped"))

    def test_every_waiting_status_can_be_taken(self):
        for status in ("confirmed", "preparing", "ready"):
            conn, _, _ = press("courier:pickup:5:0", dict(ROW, status=status))
            self.assertTrue(conn.executed, status)

    def test_an_order_already_on_the_road_is_not_taken_again(self):
        conn, feed, cb = press("courier:pickup:5:0", dict(ROW, status="shipped"))
        self.assertEqual(conn.executed, [])
        feed.assert_not_called()

    def test_lists_read_the_board_statuses(self):
        conn, _, _ = press("courier:pickup:5:0", ROW)       # refreshes the "new" list
        self.assertEqual(conn.fetched[0][1][0], ["confirmed", "preparing", "ready"])
        conn, _, _ = press("courier:my_orders", None)
        self.assertEqual(conn.fetched[0][1], (7112339935, ["shipped", "delivering"]))


class DeliveredTest(unittest.TestCase):
    def test_delivered_and_returned_send_the_status_card(self):
        mine = dict(ROW, status="shipped", courier_id=7112339935)
        conn, feed, _ = press("courier:delivered:5:0", mine)
        self.assertIn("status = 'delivered'", conn.executed[0][0])
        self.assertEqual(feed.call_args.args[1:4], (5, "shipped", "delivered"))
        conn, feed, _ = press("courier:cancel:5:0", mine)
        self.assertIn("status = 'confirmed'", conn.executed[0][0])
        self.assertEqual(feed.call_args.args[1:4], (5, "shipped", "confirmed"))


class RegisterCourierTest(unittest.TestCase):
    def test_registered_once(self):
        add = AsyncMock()
        with patch.object(database, "claim_release_notes", AsyncMock(side_effect=[True, False])), \
             patch.object(database, "add_courier_db", add):
            asyncio.run(order_watchers.register_couriers())
            asyncio.run(order_watchers.register_couriers())
        add.assert_awaited_once_with(7112339935, None)

    def test_failure_frees_the_claim_for_the_next_start(self):
        release = AsyncMock()
        with patch.object(database, "claim_release_notes", AsyncMock(return_value=True)), \
             patch.object(database, "add_courier_db", AsyncMock(side_effect=RuntimeError("db"))), \
             patch.object(database, "release_release_notes", release):
            asyncio.run(order_watchers.register_couriers())
        release.assert_awaited_once_with("courier-add:7112339935")


if __name__ == "__main__":
    unittest.main()
