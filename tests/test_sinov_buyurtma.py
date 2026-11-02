"""🧪 /test_buyurtma — kuryer paneli sinovi uchun test buyurtma (egasi, 2026-11-02).

Bazaga ulanmasdan: yozilgan qator «Yo'lda», 0 so'm, mahsulotsiz, source='test'
(tushumga qo'shilmaydi), avvalgi test o'chiriladi; uni hech qayerdan
«Yetkazildi» qilib bo'lmaydi (kuryer xarajati/Keto/keshbek yozilmasin);
o'chirish tugmasi haqiqiy buyurtmaga tegmaydi.
"""
import asyncio
import json
import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import courier_board
import database
import handlers.seller as seller
import keyboards
import sinov_buyurtma as test_order

ADMIN = 4242


class FakeConn:
    def __init__(self):
        self.inserted = None

    async def fetch(self, sql, *args):
        assert "source = $1" in sql and args == ("test",)
        return [{"id": 5}]

    async def fetchval(self, sql, *args):
        assert sql.strip().startswith("INSERT INTO orders")
        self.inserted = (sql, args)
        return 99


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


class TestOrderTest(unittest.TestCase):
    def test_create_replaces_old_and_writes_a_zero_shipped_test_order(self):
        conn = FakeConn()
        deleted = AsyncMock()
        with patch.object(database, "pool", FakePool(conn)), \
             patch.object(database, "delete_order_permanently", deleted):
            order_id, removed = asyncio.run(test_order.create(ADMIN))
        self.assertEqual((order_id, removed), (99, [5]))
        deleted.assert_awaited_once_with(5)
        sql, args = conn.inserted
        self.assertIn("'shipped'", sql)
        self.assertIn(", 0, 'cash',", sql)                 # total 0 → nothing added to revenue
        self.assertIn("'self'", sql)                       # Ketoshop courier, so it is a route stop
        self.assertEqual(args[0], ADMIN)                   # the admin is the "buyer"
        self.assertEqual(json.loads(args[3]), [])          # no items → no stock moves
        self.assertEqual((args[4], args[5]), (test_order.LAT, test_order.LON))
        self.assertTrue(args[2].startswith("41.311151, 69.279737 — "))
        self.assertEqual(args[-1], "test")

    def test_is_test(self):
        self.assertTrue(test_order.is_test({"source": "test"}))
        self.assertFalse(test_order.is_test({"source": "bot"}))
        self.assertFalse(test_order.is_test({"source": None}))
        self.assertFalse(test_order.is_test(None))

    def test_board_refuses_to_deliver_a_test_order(self):
        order = {"id": 99, "status": "shipped", "source": "test", "delivery_method": "self"}
        trans = AsyncMock(return_value=True)
        with patch.object(database, "get_order", AsyncMock(return_value=order)), \
             patch.object(database, "transition_order_status", trans):
            r = asyncio.run(courier_board.move_order(99, "delivered", expected_from="shipped"))
        self.assertFalse(r["ok"])
        self.assertIn("test buyurtma", r["error"])
        trans.assert_not_awaited()

    def test_bot_card_refuses_to_deliver_a_test_order(self):
        order = {"id": 99, "user_id": ADMIN, "seller_id": None, "status": "shipped", "source": "test"}
        cb = NS(data="order_act:delivered:99", from_user=NS(id=ADMIN),
                message=NS(edit_text=AsyncMock(), answer=AsyncMock()), answer=AsyncMock())
        trans = AsyncMock(return_value=True)
        with patch.object(seller, "ADMIN_IDS", [ADMIN]), \
             patch.object(seller, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(seller, "get_order", AsyncMock(return_value=order)), \
             patch.object(seller, "transition_order_status", trans):
            asyncio.run(seller.handle_order_action(cb, NS(send_message=AsyncMock())))
        trans.assert_not_awaited()
        self.assertEqual(cb.answer.call_args.args[0], test_order.NO_DELIVERY)

    def test_delete_button_never_touches_a_real_order(self):
        cb = NS(data="testord:del:7", from_user=NS(id=ADMIN),
                message=NS(edit_text=AsyncMock()), answer=AsyncMock())
        deleted = AsyncMock()
        with patch.object(test_order, "ADMIN_IDS", [ADMIN]), \
             patch.object(database, "get_order", AsyncMock(return_value={"id": 7, "source": "bot"})), \
             patch.object(database, "delete_order_permanently", deleted):
            asyncio.run(test_order.delete_test_order(cb))
        deleted.assert_not_awaited()
        with patch.object(test_order, "ADMIN_IDS", [ADMIN]), \
             patch.object(database, "get_order", AsyncMock(return_value={"id": 7, "source": "test"})), \
             patch.object(database, "delete_order_permanently", deleted):
            asyncio.run(test_order.delete_test_order(cb))
        deleted.assert_awaited_once_with(7)

    def test_command_published_for_admins(self):
        self.assertIn("test_buyurtma", [c.command for c in keyboards.ADMIN_COMMANDS])


if __name__ == "__main__":
    unittest.main()
