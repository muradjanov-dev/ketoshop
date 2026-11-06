"""Buyurtma kuzatuvchisi (egasi, 2026-11-06): botdan faqat yangi buyurtma va
buyurtma holati kartalari boradi, admin emas; ulanganda yetkazilmagan
buyurtmalar bir marta test uchun yuboriladi. Bazaga ulanmaydi, xabar
yuborilmaydi."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import config
import database
import order_admin_feed
import order_watchers
from handlers import admin as admin_handlers
from handlers import cart

ORDER = {"id": 5, "user_id": 10, "customer_name": "Ali", "phone": "+998901234567",
         "address": "Chilonzor 5", "status": "confirmed", "total": 50000, "source": "bot",
         "delivery_method": "self", "payment_method": "cash",
         "items": [{"product_id": 1, "name": "Chia", "quantity": 1, "price": 50000, "unit": "piece"}]}


def run(coro):
    return asyncio.run(coro)


class ConfigTest(unittest.TestCase):
    def test_watcher_is_not_an_admin(self):
        self.assertIn(7112339935, config.ORDER_WATCHER_IDS)
        self.assertNotIn(7112339935, config.ADMIN_IDS)
        self.assertFalse(admin_handlers.is_admin(7112339935))

    def test_recipients_are_admins_then_watchers_once(self):
        with patch.object(order_admin_feed, "ADMIN_IDS", [1, 2]), \
             patch.object(order_admin_feed, "ORDER_WATCHER_IDS", [3, 2]):
            self.assertEqual(order_admin_feed.recipients(), [1, 2, 3])


class FeedTest(unittest.TestCase):
    def _patches(self):
        return (patch.object(database, "get_order", AsyncMock(return_value=dict(ORDER))),
                patch.object(database, "get_user", AsyncMock(return_value={"username": "ali"})),
                patch.object(database, "get_user_language", AsyncMock(return_value="uz")),
                patch("handlers.cart.order_history_block", AsyncMock(return_value="")))

    def test_status_cards_reach_the_watcher(self):
        bot = MagicMock()
        bot.send_message = AsyncMock()
        p1, p2, p3, p4 = self._patches()
        with p1, p2, p3, p4, patch.object(order_admin_feed, "ADMIN_IDS", [1]), \
             patch.object(order_admin_feed, "ORDER_WATCHER_IDS", [3]):
            run(order_admin_feed._send_all(bot, 5, title="status_title", by="x",
                                           old_status="confirmed", new_status="shipped"))
        self.assertEqual([c.args[0] for c in bot.send_message.await_args_list], [1, 3])
        self.assertIn("#5", bot.send_message.await_args_list[1].args[1])

    def test_open_orders_go_to_one_chat_after_an_intro(self):
        bot = MagicMock()
        bot.send_message = AsyncMock()
        p1, p2, p3, p4 = self._patches()
        with p1, p2, p3, p4, patch.object(order_admin_feed, "OPEN_SEND_GAP", 0), \
             patch.object(database, "get_open_order_ids", AsyncMock(return_value=[5, 6])):
            self.assertEqual(run(order_admin_feed.send_open_orders(bot, 3)), (2, 2))
        calls = bot.send_message.await_args_list
        self.assertEqual({c.args[0] for c in calls}, {3})
        self.assertIn("yetkazilmagan 2 ta buyurtma", calls[0].args[1])
        self.assertIn("Yetkazilmagan buyurtma #5", calls[1].args[1])
        self.assertIn("Chia", calls[1].args[1])

    def test_intro_failure_is_raised_so_it_can_be_retried(self):
        bot = MagicMock()
        bot.send_message = AsyncMock(side_effect=RuntimeError("Forbidden: bot can't initiate conversation"))
        with patch.object(database, "get_open_order_ids", AsyncMock(return_value=[5])), \
             patch.object(database, "get_user_language", AsyncMock(return_value="uz")):
            with self.assertRaises(RuntimeError):
                run(order_admin_feed.send_open_orders(bot, 3))

    def test_open_order_query(self):
        seen = {}

        class Conn:
            async def fetch(self, sql, *args):
                seen["sql"], seen["args"] = sql, args
                return [{"id": 7}, {"id": 9}]

        class Pool:
            def acquire(self):
                class _Ctx:
                    async def __aenter__(self):
                        return Conn()

                    async def __aexit__(self, *a):
                        return False
                return _Ctx()

        with patch.object(database, "pool", Pool()):
            self.assertEqual(run(database.get_open_order_ids()), [7, 9])
        self.assertEqual(seen["args"][0], list(database.COURIER_BOARD_STATUSES))
        self.assertIn("<> 'test'", seen["sql"])


class NewOrderCardTest(unittest.TestCase):
    def test_watcher_gets_the_card_without_admin_buttons(self):
        bot = MagicMock()
        bot.send_message = AsyncMock()
        bot.send_location = AsyncMock()
        data = {"customer_name": "Ali", "phone": "+998901234567", "total": 50000, "user_id": 10,
                "username": "ali", "address": "Chilonzor 5", "delivery_method": "self",
                "payment_method": "cash", "status": "pending"}
        with patch.object(cart, "ADMIN_IDS", [1]), patch.object(cart, "ORDER_WATCHER_IDS", [3, 1]), \
             patch.object(cart, "get_order", AsyncMock(return_value=dict(ORDER, status="pending"))), \
             patch.object(cart, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(cart, "order_history_block", AsyncMock(return_value="")):
            run(cart._notify_sellers(bot, 5, ORDER["items"], data, "uz"))
        by_chat = {c.kwargs["chat_id"]: c.kwargs for c in bot.send_message.await_args_list}
        self.assertEqual(set(by_chat), {1, 3})                       # the admin-watcher not twice
        self.assertIsNotNone(by_chat[1]["reply_markup"])
        self.assertIsNone(by_chat[3]["reply_markup"])
        self.assertIn("Chia", by_chat[3]["text"])


class OneOffTest(unittest.TestCase):
    def test_sent_once_and_admins_told(self):
        bot = MagicMock()
        bot.send_message = AsyncMock()
        send = AsyncMock(return_value=(8, 8))
        with patch.object(database, "claim_release_notes", AsyncMock(side_effect=[True, False])), \
             patch.object(order_admin_feed, "send_open_orders", send), \
             patch.object(order_watchers, "ADMIN_IDS", [1, 2]):
            self.assertTrue(run(order_watchers._try(bot, 3)))
            self.assertTrue(run(order_watchers._try(bot, 3)))
        send.assert_awaited_once()
        self.assertEqual([c.args[0] for c in bot.send_message.await_args_list], [1, 2])
        self.assertIn("8 / 8", bot.send_message.await_args_list[0].args[1])

    def test_not_started_yet_releases_the_claim(self):
        release = AsyncMock()
        with patch.object(database, "claim_release_notes", AsyncMock(return_value=True)), \
             patch.object(database, "release_release_notes", release), \
             patch.object(order_admin_feed, "send_open_orders", AsyncMock(side_effect=RuntimeError("Forbidden"))):
            self.assertFalse(run(order_watchers._try(MagicMock(), 3)))
        release.assert_awaited_once_with("order-watch-open-orders:3")

    def test_loop_skips_a_watcher_who_is_an_admin(self):
        tried = AsyncMock(return_value=True)
        with patch.object(order_watchers, "ORDER_WATCHER_IDS", [1, 3]), \
             patch.object(order_watchers, "ADMIN_IDS", [1]), \
             patch.object(order_watchers, "_try", tried), \
             patch.object(order_watchers, "register_couriers", AsyncMock()):
            run(order_watchers.scheduler_loop(MagicMock()))
        self.assertEqual([c.args[1] for c in tried.await_args_list], [3])


if __name__ == "__main__":
    unittest.main()
