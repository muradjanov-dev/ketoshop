"""Holat o'zgarsa — yangi xabar emas, o'sha kartochka tahrirlanadi (egasi, 2026-11-13:
"buyurtmalarni statusi o'zgarganidan keyin qayta yubormagin huddi o'shani edit qil,
botdan ko'p xabar kelib bizni chalg'ityapti")."""
import asyncio
import os
import unittest
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database  # noqa: E402
import handlers.seller as seller  # noqa: E402
import order_admin_feed as feed  # noqa: E402

ADMIN, OTHER, WATCHER = 4242, 4343, 7112339935
ORDER = {"id": 905, "user_id": 555, "seller_id": 1, "status": "confirmed", "total": 150000,
         "items": "[]", "customer_name": "Ali", "phone": "+998901234567", "address": "Toshkent",
         "delivery_method": "courier", "source": "bot",
         "created_at": datetime(2026, 11, 13, 10, 0), "confirmed_at": None,
         "shipped_at": None, "delivered_at": None}


class FakeBot:
    def __init__(self, broken=()):
        self.edits, self.sends, self.broken = [], [], set(broken)
        self.next_id = 500

    async def edit_message_text(self, text, chat_id, message_id, **kw):
        if message_id in self.broken:
            raise RuntimeError("Telegram server says - Bad Request: message to edit not found")
        if message_id == "same":
            raise RuntimeError("Bad Request: message is not modified")
        self.edits.append((chat_id, message_id, text, kw.get("reply_markup")))

    async def send_message(self, chat_id, text, **kw):
        self.next_id += 1
        self.sends.append((chat_id, text, kw.get("reply_markup")))
        return NS(message_id=self.next_id)


def buttons(markup):
    return [b.callback_data for row in (markup.inline_keyboard if markup else []) for b in row if b.callback_data]


class FeedEditTest(unittest.TestCase):
    def run_feed(self, bot, cards, order=None, deleted_by=None):
        remembered, cleared = {}, []

        async def set_card(order_id, chat_id, message_id):
            remembered[chat_id] = message_id

        async def go():
            if deleted_by is not None:
                feed.deleted(bot, order or dict(ORDER), deleted_by)
            else:
                feed.status_changed(bot, ORDER["id"], "pending", "confirmed", NS(id=ADMIN, full_name="Ali Admin",
                                                                               username=None))
            await asyncio.gather(*list(feed._tasks))

        with patch.object(feed, "ADMIN_IDS", [ADMIN, OTHER]), \
                patch.object(feed, "ORDER_WATCHER_IDS", [WATCHER]), \
                patch.object(database, "get_order", AsyncMock(return_value=dict(order or ORDER))), \
                patch.object(database, "get_user", AsyncMock(return_value={"username": "ali_buyer"})), \
                patch.object(database, "get_user_language", AsyncMock(return_value="uz")), \
                patch.object(database, "get_order_cards", AsyncMock(return_value=dict(cards))), \
                patch.object(database, "set_order_card", set_card), \
                patch.object(database, "delete_order_cards", AsyncMock(side_effect=lambda oid: cleared.append(oid))), \
                patch("order_pins.status_changed", lambda *a: None), \
                patch("handlers.cart.order_history_block", AsyncMock(return_value="")):
            asyncio.run(go())
        return remembered, cleared

    def test_existing_cards_are_edited_not_resent(self):
        bot = FakeBot()
        remembered, _ = self.run_feed(bot, {ADMIN: 11, OTHER: 12, WATCHER: 13})
        self.assertEqual(bot.sends, [])
        self.assertEqual(sorted((c, m) for c, m, _, _ in bot.edits), [(ADMIN, 11), (OTHER, 12), (WATCHER, 13)])
        by_chat = {c: (text, markup) for c, _, text, markup in bot.edits}
        self.assertIn("#905", by_chat[OTHER][0])
        self.assertIn("order_act:ship:905", buttons(by_chat[OTHER][1]))     # next step: «Yo'lda»
        self.assertNotIn("order_act:confirm:905", buttons(by_chat[OTHER][1]))
        self.assertIsNone(by_chat[WATCHER][1])                              # watcher: no buttons
        self.assertEqual(remembered, {})

    def test_no_card_yet_sends_one_and_remembers_it(self):
        bot = FakeBot()
        remembered, _ = self.run_feed(bot, {ADMIN: 11})
        self.assertEqual([c for c, _, _, _ in bot.edits], [ADMIN])
        self.assertEqual(sorted(c for c, _, _ in bot.sends), sorted([OTHER, WATCHER]))
        self.assertEqual(set(remembered), {OTHER, WATCHER})

    def test_card_deleted_by_hand_is_replaced(self):
        bot = FakeBot(broken={12})
        remembered, _ = self.run_feed(bot, {ADMIN: 11, OTHER: 12, WATCHER: 13})
        self.assertEqual([c for c, _, _ in bot.sends], [OTHER])
        self.assertEqual(remembered, {OTHER: bot.next_id})

    def test_unchanged_card_sends_nothing(self):
        bot = FakeBot()
        self.run_feed(bot, {ADMIN: "same", OTHER: "same", WATCHER: "same"})
        self.assertEqual((bot.edits, bot.sends), ([], []))

    def test_delete_edits_the_cards_without_buttons_and_forgets_them(self):
        bot = FakeBot()
        _, cleared = self.run_feed(bot, {ADMIN: 11, OTHER: 12, WATCHER: 13},
                                   deleted_by=NS(id=ADMIN, full_name="Ali Admin", username=None))
        self.assertEqual(bot.sends, [])
        self.assertEqual(sorted(c for c, _, _, _ in bot.edits), sorted([OTHER, WATCHER]))   # not the deleter
        self.assertTrue(all(markup is None and "o'chirildi" in text for _, _, text, markup in bot.edits))
        self.assertEqual(cleared, [905])


class TappedCardTest(unittest.TestCase):
    def run_tap(self, card_order):
        msg = NS(edit_text=AsyncMock(), edit_reply_markup=AsyncMock(), answer=AsyncMock(), photo=None,
                 chat=NS(id=ADMIN), message_id=11, bot=NS(delete_message=AsyncMock()))
        cb = NS(data="order_act:confirm:905", from_user=NS(id=ADMIN, full_name="Admin", username=None),
                message=msg, answer=AsyncMock(), bot=NS(send_message=AsyncMock()))
        pending = dict(ORDER, status="pending")
        render = AsyncMock()
        with patch.object(seller, "ADMIN_IDS", [ADMIN]), \
                patch.object(seller, "get_user_language", AsyncMock(return_value="uz")), \
                patch.object(seller, "get_order", AsyncMock(side_effect=[pending, dict(ORDER)])), \
                patch.object(seller, "transition_order_status", AsyncMock(return_value=True)), \
                patch.object(seller, "render_seller_orders", render), \
                patch.object(database, "order_card_order", AsyncMock(return_value=card_order)), \
                patch("order_admin_feed.status_changed", lambda *a: None), \
                patch.object(seller, "_build_buyer_status_block", lambda *a: ("", "")):
            asyncio.run(seller.handle_order_action(cb, NS(send_message=AsyncMock())))
        return cb, render

    def test_tapping_the_order_card_keeps_it_as_the_card(self):
        cb, render = self.run_tap(905)
        render.assert_not_awaited()
        cb.answer.assert_awaited()

    def test_a_panel_card_still_goes_back_to_the_orders_page(self):
        _, render = self.run_tap(None)
        render.assert_awaited()


if __name__ == "__main__":
    unittest.main()
