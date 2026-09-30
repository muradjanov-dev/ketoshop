"""Admin buyurtma tahrirlash — bazaga ulanmasdan.

database.admin_update_order_items soxta ulanish bilan tekshiriladi: ombor faqat
farq bo'yicha siljiydimi, jami yetkazish/Keto ni saqlagan holda o'zgaradimi,
eskirgan qoralama va yetarli bo'lmagan ombor rad etiladimi.
"""
import asyncio
import json
import os
import unittest

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
from keyboards import seller_order_keyboard


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeConn:
    def __init__(self, order, stock, set_items=None):
        self.order = order
        self.stock = dict(stock)
        self.set_items = set_items or {}
        self.saved = None

    def transaction(self):
        return _Tx()

    async def fetchrow(self, sql, *args):
        if sql.startswith("SELECT * FROM orders"):
            return dict(self.order)
        if "quantity = quantity - $1" in sql:
            qty, pid = args
            if self.stock.get(pid, 0) < qty:
                return None
            self.stock[pid] -= qty
            return {"quantity": self.stock[pid], "name": f"p{pid}", "low_stock_threshold": None}
        raise AssertionError(sql)

    async def fetchval(self, sql, *args):
        return self.stock.get(args[0], 0)

    async def fetch(self, sql, *args):
        return [{"product_id": p, "quantity": q} for p, q in self.set_items.get(args[0], [])]

    async def execute(self, sql, *args):
        if "quantity = quantity + $1" in sql:
            qty, pid = args
            self.stock[pid] = self.stock.get(pid, 0) + qty
        elif sql.startswith("UPDATE orders SET items"):
            self.saved = (json.loads(args[0]), args[1])
        else:
            raise AssertionError(sql)


class FakePool:
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


def _line(pid, qty, price):
    return {"product_id": pid, "is_set": False, "name": f"p{pid}", "quantity": qty, "price": price}


GIFT = {"product_id": 9, "is_gift": True, "name": "Eritritol", "quantity": 1, "price": 0}


class OrderEditTest(unittest.TestCase):
    def setUp(self):
        self._pool = database.pool

    def tearDown(self):
        database.pool = self._pool

    def _run(self, order_items, new_items, stock, total=125_000, status="confirmed", set_items=None):
        order = {"id": 1, "status": status, "total": total, "items": json.dumps(order_items)}
        conn = FakeConn(order, stock, set_items)
        database.pool = FakePool(conn)
        res = asyncio.run(database.admin_update_order_items(1, order_items, new_items))
        return res, conn

    def test_qty_change_moves_only_difference_and_keeps_fee(self):
        old = [_line(1, 2, 50_000), GIFT]
        new = [_line(1, 3, 50_000), GIFT]
        # total 125 000 = 100 000 goods + 25 000 delivery
        res, conn = self._run(old, new, {1: 5, 9: 10})
        self.assertEqual(conn.stock, {1: 4, 9: 10})  # gift untouched
        self.assertEqual(res["new_total"], 175_000)
        self.assertEqual(conn.saved[1], 175_000)

    def test_remove_and_add_lines(self):
        old = [_line(1, 2, 50_000), _line(2, 1, 20_000)]
        new = [_line(1, 2, 50_000), _line(3, 2, 10_000)]
        res, conn = self._run(old, new, {1: 0, 2: 0, 3: 5}, total=120_000)
        self.assertEqual(conn.stock, {1: 0, 2: 1, 3: 3})
        self.assertEqual(res["new_total"], 120_000)

    def test_set_line_moves_components(self):
        old = [{"set_id": 7, "is_set": True, "name": "set", "quantity": 1, "price": 90_000}]
        new = [{"set_id": 7, "is_set": True, "name": "set", "quantity": 2, "price": 90_000}]
        _, conn = self._run(old, new, {1: 5, 2: 5}, total=90_000, set_items={7: [(1, 1), (2, 2)]})
        self.assertEqual(conn.stock, {1: 4, 2: 3})

    def test_insufficient_stock_rejected(self):
        with self.assertRaises(database.InsufficientStockError):
            self._run([_line(1, 1, 10)], [_line(1, 5, 10)], {1: 2})

    def test_stale_draft_or_shipped_rejected(self):
        with self.assertRaises(database.OrderChangedError):
            self._run([_line(1, 1, 10)], [_line(1, 2, 10)], {1: 5}, status="shipped")
        order = {"id": 1, "status": "pending", "total": 10, "items": json.dumps([_line(1, 3, 10)])}
        database.pool = FakePool(FakeConn(order, {1: 5}))
        with self.assertRaises(database.OrderChangedError):
            asyncio.run(database.admin_update_order_items(1, [_line(1, 1, 10)], [_line(1, 2, 10)]))

    def test_only_gift_left_rejected(self):
        with self.assertRaises(ValueError):
            self._run([_line(1, 1, 10), GIFT], [GIFT], {1: 5})

    def test_edit_button_only_for_admin_before_shipping(self):
        def has_edit(status, is_admin):
            kb = seller_order_keyboard("uz", 5, status, is_admin=is_admin)
            return any(b.callback_data == "oedit:5" for row in kb.inline_keyboard for b in row)
        self.assertTrue(has_edit("pending", True))
        self.assertTrue(has_edit("ready", True))
        self.assertFalse(has_edit("shipped", True))
        self.assertFalse(has_edit("pending", False))


if __name__ == "__main__":
    unittest.main()
