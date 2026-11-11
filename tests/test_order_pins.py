"""New (unconfirmed) orders are pinned for admins and unpinned once they move
on (owner, 2026-11-11). Telegram and the database are fakes."""
import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
import order_admin_feed
import order_pins


class FakeBot:
    def __init__(self):
        self.pinned, self.unpinned, self.sent, self.n = [], [], [], 500

    async def pin_chat_message(self, chat_id, message_id, disable_notification=False):
        self.pinned.append((chat_id, message_id, disable_notification))

    async def unpin_chat_message(self, chat_id, message_id=None):
        self.unpinned.append((chat_id, message_id))

    async def send_message(self, chat_id, text, **kw):
        self.n += 1
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        return SimpleNamespace(message_id=self.n)


class PinsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.pins = []          # (chat, msg, order)
        self.orders = {7: {"id": 7, "status": "pending", "source": "bot", "items": "[]", "total": 120000,
                           "customer_name": "Test", "phone": "+998900000000", "address": "Toshkent"}}
        self.claimed = set()

        async def add(order_id, chat_id, message_id):
            self.pins.append((chat_id, message_id, order_id))

        async def take(order_id):
            mine = [p for p in self.pins if p[2] == order_id]
            self.pins = [p for p in self.pins if p[2] != order_id]
            return [{"chat_id": c, "message_id": m} for c, m, _ in mine]

        async def to_release():
            return sorted({o for _, _, o in self.pins
                           if o not in self.orders or self.orders[o]["status"] != "pending"})

        async def waiting(limit=30):
            pinned = {o for _, _, o in self.pins}
            return [o for o in self.orders.values() if o["status"] == "pending" and o["id"] not in pinned]

        async def claim(key):
            if key in self.claimed:
                return False
            self.claimed.add(key)
            return True

        for p in (patch.object(database, "add_order_pin", add), patch.object(database, "take_order_pins", take),
                  patch.object(database, "order_pins_to_release", to_release),
                  patch.object(database, "pending_orders_without_pins", waiting),
                  patch.object(database, "claim_release_notes", claim),
                  patch.object(database, "get_user_language", AsyncMock(return_value="uz")),
                  patch.object(order_pins, "ADMIN_IDS", [101, 102])):
            p.start()
            self.addCleanup(p.stop)
        self.bot = FakeBot()

    async def settle(self):
        await asyncio.sleep(0)
        if order_pins._tasks:
            await asyncio.gather(*list(order_pins._tasks))

    async def test_pinned_quietly_then_released_when_confirmed(self):
        await order_pins.pin(self.bot, 7, 101, 11)
        await order_pins.pin(self.bot, 7, 102, 12)
        self.assertEqual(self.bot.pinned, [(101, 11, True), (102, 12, True)])
        order_pins.status_changed(self.bot, 7, "pending")         # still new: stays pinned
        await self.settle()
        self.assertEqual(self.bot.unpinned, [])
        order_pins.status_changed(self.bot, 7, "confirmed")
        await self.settle()
        self.assertEqual(sorted(self.bot.unpinned), [(101, 11), (102, 12)])
        self.assertEqual(self.pins, [])

    async def test_feed_hook_unpins_on_status_change_and_delete(self):
        await order_pins.pin(self.bot, 7, 101, 11)
        with patch.object(order_admin_feed, "_send_all", AsyncMock()):
            order_admin_feed.status_changed(self.bot, 7, "pending", "cancelled", "Admin")
            await self.settle()
        self.assertEqual(self.bot.unpinned, [(101, 11)])
        await order_pins.pin(self.bot, 8, 101, 21)
        with patch.object(order_admin_feed, "_send_deleted", AsyncMock()):
            order_admin_feed.deleted(self.bot, {"id": 8, "source": "bot"}, None)
            await self.settle()
        self.assertIn((101, 21), self.bot.unpinned)

    async def test_reconcile_catches_changes_made_elsewhere(self):
        await order_pins.pin(self.bot, 7, 101, 11)
        self.orders[7]["status"] = "shipped"                      # e.g. moved on the courier board
        self.assertEqual(await order_pins.reconcile(self.bot), 1)
        self.assertEqual(self.bot.unpinned, [(101, 11)])

    async def test_orders_already_waiting_are_pinned_once(self):
        n = await order_pins.pin_waiting_once(self.bot)
        self.assertEqual(n, 2)                                    # order 7 for two admins
        self.assertIn("Tasdiqlanmagan buyurtma #7", self.bot.sent[0][1])
        buttons = [b.callback_data for row in self.bot.sent[0][2].inline_keyboard for b in row]
        self.assertTrue(any("7" in (cb or "") for cb in buttons))
        self.assertEqual(await order_pins.pin_waiting_once(self.bot), 0)

    async def test_new_order_card_is_pinned_for_admins_only(self):
        import handlers.cart as cart
        bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=77)),
                              send_location=AsyncMock(), pin_chat_message=AsyncMock())
        order = {"id": 5, "keto_redeemed": 0}
        data = {"user_id": 1, "username": "u", "customer_name": "Ali", "phone": "+998901112233",
                "address": "Toshkent", "total": 120000, "delivery_method": "self", "payment_method": "cash"}
        items = [{"product_id": 1, "name": "Bodom uni", "quantity": 1, "price": 120000, "unit": "dona"}]
        with patch.object(cart, "get_order", AsyncMock(return_value=order)), \
             patch.object(cart, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(cart, "ADMIN_IDS", [101]), patch.object(cart, "ORDER_WATCHER_IDS", [303]):
            await cart._notify_sellers(bot, 5, items, data, "uz")
        bot.pin_chat_message.assert_awaited_once_with(101, 77, disable_notification=True)
        self.assertEqual(self.pins, [(101, 77, 5)])


if __name__ == "__main__":
    unittest.main()
