"""Holat o'zgargach menyuga emas, buyurtmalar sahifasiga qaytish.

* Buyurtma kartasidagi Qabul/Yo'lda/Yetkazildi → buyurtmalar ro'yxati
  (kartaning ⬅️ tugmasi ochadigan sahifa), natija toast bo'lib chiqadi.
* /courier paneli: ro'yxat bo'shasa — menyu emas, ikkinchi ro'yxat.
"""
import asyncio
import os
import unittest
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import handlers.courier as courier
import handlers.seller as seller

ADMIN = 4242
ORDER = {"id": 7, "user_id": 555, "seller_id": 1, "status": "confirmed", "total": 90000,
         "items": "[]", "customer_name": "Ali", "phone": "+998", "address": "Toshkent", "delivery_method": "self",
         "created_at": datetime(2026, 10, 1, 9, 0), "confirmed_at": datetime(2026, 10, 1, 9, 5),
         "shipped_at": None, "delivered_at": None}


def _callback(data, user_id=ADMIN):
    msg = NS(edit_text=AsyncMock(), answer=AsyncMock(), photo=None)
    return NS(data=data, from_user=NS(id=user_id), message=msg, answer=AsyncMock())


class OrderCardRedirectTest(unittest.TestCase):
    def test_status_change_from_card_opens_orders_page(self):
        cb = _callback("order_act:confirm:7")
        bot = NS(send_message=AsyncMock())
        with patch.object(seller, "ADMIN_IDS", [ADMIN]), \
             patch.object(seller, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(seller, "get_order", AsyncMock(return_value=dict(ORDER, status="pending"))), \
             patch.object(seller, "transition_order_status", AsyncMock(return_value=True)), \
             patch.object(seller, "get_seller_orders", AsyncMock(return_value=[ORDER])):
            asyncio.run(seller.handle_order_action(cb, bot))
        page = cb.message.edit_text.call_args
        self.assertIn("Buyurtmalar", page.args[0])
        buttons = [b.callback_data for row in page.kwargs["reply_markup"].inline_keyboard for b in row]
        self.assertIn("seller_order:7", buttons)
        self.assertNotIn("seller:add_product", buttons)          # not the panel menu
        self.assertEqual(cb.answer.call_args.args[0], seller.get_text("order_accepted", "uz"))


def _row(oid):
    return dict(ORDER, id=oid)


class FakeConn:
    def __init__(self, new, mine):
        self.new, self.mine = new, mine

    async def fetch(self, sql, *a):
        return list(self.new if "courier_id IS NULL" in sql else self.mine)

    async def fetchrow(self, sql, *a):
        return dict(ORDER, id=a[0], courier_id=None)

    async def execute(self, sql, *a):
        oid = a[-1]
        self.new = [r for r in self.new if r["id"] != oid]
        self.mine = self.mine + [_row(oid)]


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *e):
                return False
        return Ctx()


class CourierRedirectTest(unittest.TestCase):
    def test_last_pickup_opens_my_orders_not_menu(self):
        conn = FakeConn(new=[_row(7)], mine=[])
        cb = _callback("courier:pickup:7:0")
        with patch.object(courier, "is_courier", AsyncMock(return_value=True)), \
             patch.object(courier.database, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(courier.database, "pool", FakePool(conn)):
            asyncio.run(courier.courier_callback_handler(cb, NS(send_message=AsyncMock())))
        text = cb.message.edit_text.call_args.args[0]
        self.assertIn("Mening buyurtmam", text)
        self.assertIn("#7", text)


if __name__ == "__main__":
    unittest.main()
