"""O'chirilgan buyurtmaning eski kartasi (owner, 2026-11-06).

Bir admin buyurtmani 🗑 bilan o'chirganda, boshqa adminlardagi yangi buyurtma
kartasida «✅ Qabul qilish» qolib ketardi — bosilsa faqat «❌» chiqardi.

* Har qanday karta tugmasi: «Buyurtma #N o'chirilgan» deb aytadi, kartadan
  o'lik tugmalarni oladi (ro'yxat bo'lsa — ro'yxatni qayta chizadi).
* O'chirilganda qolgan adminlar va kuzatuvchilarga «🗑 Buyurtma #N o'chirildi»
  kartasi boradi; o'chirgan adminning o'ziga emas, 🧪 test buyurtmaga emas.
"""
import asyncio
import os
import unittest
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import handlers.admin as admin
import handlers.order_edit as order_edit
import handlers.seller as seller
import order_admin_feed

ADMIN, OTHER, WATCHER = 4242, 4343, 7112339935
ORDER = {"id": 904, "user_id": 555, "seller_id": 1, "status": "pending", "total": 204350,
         "items": "[]", "customer_name": "Ali", "phone": "+998", "address": "Toshkent",
         "delivery_method": "self", "source": "bot",
         "created_at": datetime(2026, 11, 6, 13, 50), "confirmed_at": None,
         "shipped_at": None, "delivered_at": None}


def _callback(data, user_id=ADMIN):
    msg = NS(edit_text=AsyncMock(), edit_reply_markup=AsyncMock(), answer=AsyncMock(),
             photo=None, chat=NS(id=user_id), message_id=1, bot=NS(delete_message=AsyncMock()))
    return NS(data=data, from_user=NS(id=user_id, full_name="Admin", username=None),
              message=msg, answer=AsyncMock(), bot=NS(send_message=AsyncMock()))


def _gone_text(order_id=904):
    return seller.get_text("order_gone_alert", "uz", order_id=order_id)


class StaleCardTest(unittest.TestCase):
    def _run_act(self, data):
        cb = _callback(data)
        transition = AsyncMock(return_value=True)
        render_list = AsyncMock()
        with patch.object(seller, "ADMIN_IDS", [ADMIN]), \
             patch.object(seller, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(seller, "get_order", AsyncMock(return_value=None)), \
             patch.object(seller, "transition_order_status", transition), \
             patch.object(seller, "db_cancel_order", AsyncMock()) as cancel, \
             patch.object(admin, "render_orders_list", render_list):
            asyncio.run(seller.handle_order_action(cb, NS(send_message=AsyncMock())))
        return cb, transition, cancel, render_list

    def test_accept_on_deleted_order_says_deleted(self):
        cb, transition, cancel, render_list = self._run_act("order_act:confirm:904")
        cb.answer.assert_awaited_once_with(_gone_text(), show_alert=True)
        self.assertIn("#904", cb.answer.call_args.args[0])
        self.assertNotEqual(cb.answer.call_args.args[0], "❌")
        # The dead buttons come off the card; nothing is written.
        cb.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
        transition.assert_not_awaited()
        render_list.assert_not_awaited()

    def test_reject_on_deleted_order_says_deleted(self):
        cb, transition, cancel, _ = self._run_act("order_act:cancel:904")
        cb.answer.assert_awaited_once_with(_gone_text(), show_alert=True)
        cancel.assert_not_awaited()

    def test_from_admin_list_redraws_the_list(self):
        cb, _, _, render_list = self._run_act("order_act:confirm:904:list:pending:0")
        cb.answer.assert_awaited_once_with(_gone_text(), show_alert=True)
        render_list.assert_awaited_once()
        self.assertEqual(render_list.call_args.args[1:3], ("pending", 0))
        cb.message.edit_reply_markup.assert_not_awaited()

    def test_not_admin_still_gets_plain_refusal(self):
        cb = _callback("order_act:confirm:904", user_id=999)
        with patch.object(seller, "ADMIN_IDS", [ADMIN]), \
             patch.object(seller, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(seller, "get_order", AsyncMock(return_value=dict(ORDER))), \
             patch.object(seller, "transition_order_status", AsyncMock()) as transition:
            asyncio.run(seller.handle_order_action(cb, NS(send_message=AsyncMock())))
        cb.answer.assert_awaited_once_with("❌", show_alert=True)
        transition.assert_not_awaited()

    def test_live_order_still_accepts(self):
        cb = _callback("order_act:confirm:904")
        with patch.object(seller, "ADMIN_IDS", [ADMIN]), \
             patch.object(seller, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(seller, "get_order", AsyncMock(return_value=dict(ORDER))), \
             patch.object(seller, "transition_order_status", AsyncMock(return_value=True)) as transition, \
             patch.object(seller, "get_seller_orders", AsyncMock(return_value=[ORDER])), \
             patch.object(order_admin_feed, "status_changed", MagicMock()):
            asyncio.run(seller.handle_order_action(cb, NS(send_message=AsyncMock())))
        transition.assert_awaited_once_with(904, ["pending"], "confirmed")
        self.assertEqual(cb.answer.call_args.args[0], seller.get_text("order_accepted", "uz"))

    def test_message_client_on_deleted_order(self):
        cb = _callback("msgclient:904")
        state = NS(set_state=AsyncMock(), update_data=AsyncMock())
        with patch.object(seller, "ADMIN_IDS", [ADMIN]), \
             patch.object(seller, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(seller, "get_order", AsyncMock(return_value=None)):
            asyncio.run(seller.message_client_start(cb, state))
        cb.answer.assert_awaited_once_with(_gone_text(), show_alert=True)
        state.set_state.assert_not_awaited()

    def test_open_card_of_deleted_order(self):
        cb = _callback("seller_order:904")
        with patch.object(seller, "ADMIN_IDS", [ADMIN]), \
             patch.object(seller, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(seller, "get_order", AsyncMock(return_value=None)):
            asyncio.run(seller.view_seller_order(cb))
        cb.answer.assert_awaited_once_with(_gone_text(), show_alert=True)

    def test_editor_on_deleted_order(self):
        cb = _callback("oedit:904")
        state = NS(set_state=AsyncMock(), update_data=AsyncMock(), get_data=AsyncMock(return_value={}))
        with patch.object(order_edit, "ADMIN_IDS", [ADMIN]), \
             patch.object(seller, "ADMIN_IDS", [ADMIN]), \
             patch.object(order_edit.database, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(order_edit.database, "get_order", AsyncMock(return_value=None)):
            asyncio.run(order_edit.open_editor(cb, state))
        cb.answer.assert_awaited_once_with(_gone_text(), show_alert=True)
        state.set_state.assert_not_awaited()

    def test_alert_fits_telegram_limit(self):
        for lang in ("uz", "uz_cyr", "ru"):
            text = seller.get_text("order_gone_alert", lang, order_id=99999)
            self.assertLessEqual(len(text), 200, lang)
            self.assertIn("99999", text)


class DeleteNoticeTest(unittest.TestCase):
    def test_delete_tells_the_feed(self):
        cb = _callback("order_delete_do:904")
        with patch.object(admin, "is_admin", lambda uid: True), \
             patch.object(admin, "get_user_language", AsyncMock(return_value="uz")), \
             patch("database.delete_order_permanently", AsyncMock(return_value=dict(ORDER))), \
             patch.object(order_admin_feed, "deleted", MagicMock()) as feed:
            asyncio.run(admin.admin_delete_order_do(cb))
        feed.assert_called_once()
        self.assertEqual(feed.call_args.args[1]["id"], 904)
        self.assertIs(feed.call_args.args[2], cb.from_user)

    def test_missing_order_no_notice(self):
        cb = _callback("order_delete_do:904")
        with patch.object(admin, "is_admin", lambda uid: True), \
             patch.object(admin, "get_user_language", AsyncMock(return_value="uz")), \
             patch("database.delete_order_permanently", AsyncMock(return_value=None)), \
             patch.object(order_admin_feed, "deleted", MagicMock()) as feed:
            asyncio.run(admin.admin_delete_order_do(cb))
        feed.assert_not_called()

    def _feed_run(self, order, by):
        bot = NS(send_message=AsyncMock())

        async def go():
            order_admin_feed.deleted(bot, order, by)
            await asyncio.gather(*list(order_admin_feed._tasks))

        with patch.object(order_admin_feed, "ADMIN_IDS", [ADMIN, OTHER]), \
             patch.object(order_admin_feed, "ORDER_WATCHER_IDS", [WATCHER]), \
             patch.object(order_admin_feed.database, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(order_admin_feed.database, "get_user", AsyncMock(return_value={"username": None})), \
             patch("handlers.cart.order_history_block", AsyncMock(return_value="")):
            asyncio.run(go())
        return bot

    def test_others_get_deleted_card_not_the_deleter(self):
        bot = self._feed_run(dict(ORDER), NS(id=ADMIN, full_name="Ali Admin", username="ali"))
        chats = sorted(c.args[0] for c in bot.send_message.await_args_list)
        self.assertEqual(chats, sorted([OTHER, WATCHER]))
        text = bot.send_message.await_args_list[0].args[1]
        self.assertIn("#904", text)
        self.assertIn("o'chirildi", text)
        self.assertIn("Ali Admin", text)

    def test_test_order_is_silent(self):
        bot = self._feed_run(dict(ORDER, source="test"), NS(id=ADMIN, full_name="A", username=None))
        bot.send_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
