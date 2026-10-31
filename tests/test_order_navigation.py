"""Buyurtma kartasidan "bitta oldingi oynaga" qaytish (egasi, 2026-11-01).

* Admin ro'yxati (filtr+sahifa) dan ochilgan karta: ⬅️, holat tugmasi,
  o'chirish — o'sha ro'yxatga qaytadi, «Buyurtmalar» boshiga emas.
* Karta ostidagi pin/chek kartadan chiqqanda o'chadi.
* Tahrirlagich: ekranda bitta oyna; mahsulot qo'shilgach eski oyna va
  yordamchi xabarlar o'chadi; saqlash/bekor — to'g'ri kartaga qaytadi.
"""
import asyncio
import os
import unittest
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

import handlers.admin as admin
import handlers.order_edit as order_edit
import handlers.seller as seller
from keyboards import order_list_ret, order_ret_back, parse_order_ret, seller_order_keyboard

ADMIN = 4242
CHAT = 4242
ORDER = {"id": 7, "user_id": 555, "seller_id": 1, "status": "shipped", "total": 90000,
         "items": '[{"product_id": 3, "name": "Bodom uni", "quantity": 1, "price": 90000}]',
         "customer_name": "Ali", "phone": "+998", "address": "Toshkent", "delivery_method": "pickup",
         "latitude": 41.3, "longitude": 69.2, "source": "bot",
         "created_at": datetime(2026, 10, 1, 9, 0), "confirmed_at": None,
         "shipped_at": datetime(2026, 10, 1, 10, 0), "delivered_at": None}


class FakeBot:
    def __init__(self):
        self.deleted = []
        self.send_message = AsyncMock()

    async def delete_message(self, chat_id, mid):
        self.deleted.append(mid)


class FakeMsg:
    """Just enough of aiogram's Message: edit in place, answer → a new id."""
    _next = [100]

    def __init__(self, bot, message_id=None, text=""):
        self.bot, self.chat, self.text = bot, NS(id=CHAT), text
        self.photo = self.document = None
        if message_id is None:
            FakeMsg._next[0] += 1
            message_id = FakeMsg._next[0]
        self.message_id = message_id
        self.markup = None
        self.sent = []

    async def edit_text(self, text, reply_markup=None, **kw):
        self.text, self.markup = text, reply_markup

    async def edit_reply_markup(self, reply_markup=None):
        self.markup = reply_markup

    async def answer(self, text, reply_markup=None, **kw):
        m = FakeMsg(self.bot, text=text)
        m.markup = reply_markup
        self.sent.append(m)
        return m

    async def answer_location(self, **kw):
        m = FakeMsg(self.bot, text="📍")
        self.sent.append(m)
        return m


def _cb(data, msg):
    return NS(data=data, from_user=NS(id=ADMIN), message=msg, answer=AsyncMock(), bot=msg.bot)


def _buttons(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


def _card_patches():
    return [patch.object(seller, "ADMIN_IDS", [ADMIN]),
            patch.object(seller, "get_user_language", AsyncMock(return_value="uz")),
            patch.object(seller, "get_order", AsyncMock(return_value=dict(ORDER))),
            patch.object(seller, "get_user", AsyncMock(return_value=None)),
            patch("handlers.cart.order_history_block", AsyncMock(return_value=""))]


def _run_with(patches, coro):
    for p in patches:
        p.start()
    try:
        return asyncio.run(coro)
    finally:
        for p in reversed(patches):
            p.stop()


class ReturnContextTest(unittest.TestCase):
    def test_card_from_list_leads_back_to_that_list(self):
        ret = order_list_ret("shipped", 2)
        kb = seller_order_keyboard("uz", 7, "shipped", is_admin=True, ret=ret)
        data = _buttons(kb)
        self.assertIn("order_act:delivered:7:list:shipped:2", data)
        self.assertIn("msgclient:7:list:shipped:2", data)
        self.assertIn("order_delete:7:list:shipped:2", data)
        self.assertEqual(data[-1], "admin:orders:shipped:2")       # ⬅️
        edit = _buttons(seller_order_keyboard("uz", 7, "ready", is_admin=True, ret=ret))
        self.assertIn("oedit:7:list:shipped:2", edit)

    def test_card_from_seller_page_unchanged(self):
        data = _buttons(seller_order_keyboard("uz", 7, "shipped", is_admin=True))
        self.assertIn("order_act:delivered:7", data)
        self.assertEqual(data[-1], "seller:orders")
        self.assertEqual(order_ret_back(""), "seller:orders")

    def test_parse_and_size(self):
        self.assertEqual(parse_order_ret("seller_order:7:list:confirmed:3".split(":"), 2),
                         ":list:confirmed:3")
        self.assertEqual(parse_order_ret(["seller_order", "7"], 2), "")
        self.assertEqual(parse_order_ret("x:7:list:all:zz".split(":"), 2), "")
        kb = seller_order_keyboard("uz", 9999999, "pending", is_admin=True,
                                   ret=order_list_ret("cancelled", 999), notify=True)
        self.assertTrue(all(len(d.encode()) <= 64 for d in _buttons(kb)))


class CardFlowTest(unittest.TestCase):
    def setUp(self):
        seller._CARD_EXTRAS.clear()

    def test_view_from_list_keeps_context_and_pin_goes_on_leave(self):
        bot = FakeBot()
        msg = FakeMsg(bot, message_id=50)
        cb = _cb("seller_order:7:list:shipped:2", msg)
        _run_with(_card_patches(), seller.view_seller_order(cb))
        self.assertEqual(_buttons(msg.markup)[-1], "admin:orders:shipped:2")
        pin = msg.sent[0].message_id
        self.assertEqual(seller._CARD_EXTRAS[(CHAT, 50)], [pin])

        # ⬅️ → the same filtered list, and the pin under the card is removed
        render = AsyncMock()
        with patch.object(admin, "is_admin", lambda uid: True), \
             patch.object(admin, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(admin, "render_orders_list", render):
            asyncio.run(admin.show_filtered_orders(_cb("admin:orders:shipped:2", msg)))
        self.assertEqual(render.call_args.args[1:3], ("shipped", 2))
        self.assertEqual(bot.deleted, [pin])

    def test_delivered_from_card_returns_to_its_list(self):
        bot = FakeBot()
        msg = FakeMsg(bot, message_id=60)
        seller._CARD_EXTRAS[(CHAT, 60)] = [61]
        cb = _cb("order_act:delivered:7:list:shipped:2", msg)
        render = AsyncMock()
        with patch.object(seller, "ADMIN_IDS", [ADMIN]), \
             patch.object(seller, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(seller, "get_order", AsyncMock(return_value=dict(ORDER))), \
             patch.object(seller, "transition_order_status", AsyncMock(return_value=True)), \
             patch.object(seller, "get_user_delivered_order_count", AsyncMock(return_value=1)), \
             patch("gamification.award_keto_for_order", AsyncMock()), \
             patch("bloggers.award_for_order", AsyncMock()), \
             patch("referral_program.award_order_cashback", AsyncMock()), \
             patch("order_admin_feed.status_changed", lambda *a, **k: None), \
             patch.object(admin, "render_orders_list", render):
            asyncio.run(seller.handle_order_action(cb, bot))
        self.assertEqual(render.call_args.args[1:3], ("shipped", 2))
        self.assertEqual(bot.deleted, [61])
        self.assertEqual(cb.answer.call_args.args[0], seller.get_text("order_marked_delivered", "uz"))


class EditorFlowTest(unittest.TestCase):
    def setUp(self):
        seller._CARD_EXTRAS.clear()
        self.state = FSMContext(storage=MemoryStorage(),
                                key=StorageKey(bot_id=1, chat_id=CHAT, user_id=ADMIN))
        self.bot = FakeBot()
        self.db = [patch.object(order_edit, "ADMIN_IDS", [ADMIN]),
                   # _render tells a callback from a typed message by type
                   patch.object(order_edit, "CallbackQuery", NS),
                   patch.object(order_edit.database, "get_user_language", AsyncMock(return_value="uz")),
                   patch.object(order_edit.database, "get_order",
                                AsyncMock(return_value=dict(ORDER, status="ready"))),
                   patch.object(order_edit.database, "admin_search_products", AsyncMock(return_value=[
                       {"id": 9, "name": "Kokos uni", "price": 50000, "quantity": 4, "is_active": 1}])),
                   patch.object(order_edit.database, "get_product", AsyncMock(return_value={
                       "id": 9, "name": "Kokos uni", "price": 50000, "is_active": 1, "unit": "dona"})),
                   ] + _card_patches()

    def _go(self, coro):
        return _run_with(self.db, coro)

    def test_add_product_leaves_one_editor_then_save_returns_to_card(self):
        card = FakeMsg(self.bot, message_id=70)
        self._go(order_edit.open_editor(_cb("oedit:7:list:ready:1", card), self.state))
        data = asyncio.run(self.state.get_data())
        self.assertEqual((data["oe_ret"], data["oe_msg_id"]), (":list:ready:1", 70))

        # ➕ → prompt; typed name → results; pick → the results become the editor
        self._go(order_edit.ask_search(_cb("oe:add", card), self.state))
        prompt = card.sent[-1]
        typed = FakeMsg(self.bot, text="kokos")
        self._go(order_edit.got_search(typed, self.state))
        results = typed.sent[-1]
        self._go(order_edit.pick_product(_cb("oe:pick:9", results), self.state))
        self.assertIn("Kokos uni", " ".join(b.text for row in results.markup.inline_keyboard for b in row))
        self.assertEqual(sorted(self.bot.deleted), sorted([70, prompt.message_id]))
        data = asyncio.run(self.state.get_data())
        self.assertEqual((data["oe_msg_id"], data["oe_junk"]), (results.message_id, []))

        # 💾 → the order card again, with the way back to the same list
        saved = {"old_total": 90000, "new_total": 140000, "low_stock": []}
        with patch.object(order_edit.database, "admin_update_order_items", AsyncMock(return_value=saved)):
            self._go(order_edit.save_edit(_cb("oe:save", results), self.state, self.bot))
        btns = _buttons(results.markup)
        self.assertEqual(btns[0], "oe:notify:7:list:ready:1")
        self.assertEqual(btns[-1], "admin:orders:ready:1")
        self.assertIn("140 000", results.text)
        self.assertIsNone(asyncio.run(self.state.get_state()))

    def test_cancel_goes_straight_back_to_card(self):
        card = FakeMsg(self.bot, message_id=80)
        self._go(order_edit.open_editor(_cb("oedit:7:list:all:0", card), self.state))
        cb = _cb("oe:cancel", card)
        self._go(order_edit.cancel_edit(cb, self.state))
        self.assertEqual(_buttons(card.markup)[-1], "admin:orders:all:0")
        self.assertEqual(cb.answer.call_args.args[0], seller.get_text("oe_no_changes", "uz"))


if __name__ == "__main__":
    unittest.main()
