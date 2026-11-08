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
        if "FROM products WHERE id = ANY" in sql:
            return []           # catalogue costs missing unless supplied by a test
        if "SUM(qty) AS held" in sql:
            return []           # no other buyer holds anything (Savat broni)
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

    def _run(self, order_items, new_items, stock, total=125_000, status="confirmed", set_items=None, source=None):
        order = {"id": 1, "user_id": 7, "status": status, "total": total,
                 "items": json.dumps(order_items), "source": source}
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

    def test_manual_edit_keeps_inventory_unchanged_even_without_stock(self):
        old = [_line(1, 2, 50_000), _line(2, 1, 20_000)]
        new = [_line(1, 3, 50_000), _line(3, 0.5, 10_000)]
        res, conn = self._run(old, new, {1: 0, 2: 0, 3: 0},
                              total=145_000, source="manual")
        self.assertEqual(conn.stock, {1: 0, 2: 0, 3: 0})
        self.assertEqual(conn.saved, ([new[0], dict(new[1], unit_cost_snapshot=0,
                                                  unit_cost_known=False)], 180_000))
        self.assertEqual(res["low_stock"], [])

    def test_b2b_edit_rejected_without_writing(self):
        order = {"id": 1, "user_id": 7, "status": "confirmed", "source": "b2b",
                 "total": 10, "items": json.dumps([_line(1, 1, 10)])}
        conn = FakeConn(order, {1: 5})
        database.pool = FakePool(conn)
        with self.assertRaises(database.OrderChangedError):
            asyncio.run(database.admin_update_order_items(1, [_line(1, 1, 10)], [_line(1, 2, 10)]))
        self.assertIsNone(conn.saved)
        self.assertEqual(conn.stock, {1: 5})

    def test_manual_added_line_cost_stays_fixed_after_catalog_change(self):
        old = [dict(_line(1, 2, 50_000), unit_cost_snapshot=30_000,
                    unit_cost_known=True), _line(2, 1, 20_000)]
        new = [dict(old[0], quantity=3), old[1], _line(3, 0.5, 10_000)]

        class CostConn(FakeConn):
            async def fetch(self, sql, *args):
                if "FROM products WHERE id = ANY" in sql:
                    return [{"id": pid, "cost_price": 6_000} for pid in args[0]]
                return await super().fetch(sql, *args)

        conn = CostConn({"id": 1, "user_id": 7, "status": "pending",
                         "source": "manual", "total": 145_000,
                         "items": json.dumps(old)}, {1: 0, 2: 0, 3: 0})
        database.pool = FakePool(conn)
        asyncio.run(database.admin_update_order_items(1, old, new))
        saved, total = conn.saved
        self.assertEqual(saved[:2], new[:2])  # preserve historical/legacy costs
        self.assertEqual(database.line_cost(saved[2], {3: 9_000}, {}), (3_000, True))
        self.assertEqual(total, 200_000)
        self.assertEqual(conn.stock, {1: 0, 2: 0, 3: 0})
        self.assertNotIn("unit_cost_snapshot", new[2])  # leave the draft alone

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


class ManualOrderEditTest(unittest.TestCase):
    """Qo'lda buyurtma (egasi, 2026-11-08): yetkazilgandan keyin ham son, narx,
    mahsulot qo'shish — avval tuzatish faqat ikkinchi buyurtma bo'lib tushardi."""
    setUp = OrderEditTest.setUp
    tearDown = OrderEditTest.tearDown
    _run = OrderEditTest._run

    def test_who_is_editable(self):
        e = database.order_editable
        for st in ("pending", "confirmed", "preparing", "ready", "shipped", "delivered"):
            self.assertTrue(e(st, "manual"), st)
        self.assertFalse(e("cancelled", "manual"))
        self.assertTrue(e("confirmed", None))
        self.assertFalse(e("shipped", None))
        self.assertFalse(e("delivered", "bot"))
        self.assertFalse(e("confirmed", "b2b"))

    def test_delivered_manual_order_gets_its_extra_two(self):
        res, conn = self._run([_line(1, 4, 10_000)], [_line(1, 6, 10_000)], {1: 0},
                              total=40_000, status="delivered", source="manual")
        self.assertEqual(conn.saved[0][0]["quantity"], 6)
        self.assertEqual((res["old_total"], res["new_total"]), (40_000, 60_000))
        self.assertEqual(conn.stock, {1: 0})                      # manual never moves stock

    def test_price_fix_moves_the_total(self):
        cheaper = dict(_line(1, 4, 9_000), original_price=10_000, discount_percent=10)
        res, conn = self._run([_line(1, 4, 10_000)], [cheaper], {}, total=40_000,
                              status="shipped", source="manual")
        self.assertEqual(res["new_total"], 36_000)
        self.assertEqual(conn.saved[0][0]["price"], 9_000)

    def test_customer_order_after_shipping_and_cancelled_manual_stay_shut(self):
        with self.assertRaises(database.OrderChangedError):
            self._run([_line(1, 1, 10)], [_line(1, 2, 10)], {1: 5}, status="delivered", source="bot")
        with self.assertRaises(database.OrderChangedError):
            self._run([_line(1, 1, 10)], [_line(1, 2, 10)], {1: 5}, status="cancelled", source="manual")

    def test_edit_button_on_manual_cards(self):
        def has_edit(status, source):
            kb = seller_order_keyboard("uz", 5, status, is_admin=True, source=source)
            return any(b.callback_data == "oedit:5" for row in kb.inline_keyboard for b in row)
        self.assertTrue(has_edit("delivered", "manual"))
        self.assertTrue(has_edit("shipped", "manual"))
        self.assertFalse(has_edit("cancelled", "manual"))
        self.assertFalse(has_edit("delivered", "bot"))
        self.assertFalse(has_edit("confirmed", "b2b"))           # wholesale: its own books


class LinePriceTest(unittest.TestCase):
    def test_reads_like_manual_entry(self):
        from handlers.order_edit import parse_line_price as p
        self.assertEqual(p("92000", 100_000), 92_000)
        self.assertEqual(p("92 000", 100_000), 92_000)
        self.assertEqual(p("10%", 100_000), 90_000)
        self.assertEqual(p("10", 100_000), 90_000)              # a plain number up to 100 is a percent
        self.assertEqual(p("0", 100_000), 100_000)
        self.assertEqual(p("-", 100_000), 100_000)
        self.assertEqual(p("120000", 100_000), 120_000)         # a wrong low price can be raised
        for bad in ("abc", "", "100%", "-5", "0.0.1"):
            self.assertIsNone(p(bad, 100_000), bad)


class _State:
    def __init__(self, data):
        self.data = dict(data)
        self.state = None

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kw):
        self.data.update(kw)

    async def set_state(self, st):
        self.state = st


class PriceFlowTest(unittest.TestCase):
    def setUp(self):
        from unittest.mock import AsyncMock, patch
        from handlers import order_edit
        self.oe = order_edit
        p = patch.object(order_edit, "_render", AsyncMock())
        self.render = p.start()
        self.addCleanup(p.stop)

    def got(self, text, line, source="manual"):
        from unittest.mock import AsyncMock, Mock
        st = _State({"lang": "uz", "oe_source": source, "oe_items": [line], "oe_price_idx": 0})
        msg = Mock()
        msg.text = text
        msg.answer = AsyncMock(return_value=Mock(message_id=3))
        asyncio.run(self.oe.got_price(msg, st))
        return st, msg

    def test_cheaper_price_keeps_the_fire_badge(self):
        st, _ = self.got("92000", _line(1, 4, 100_000))
        line = st.data["oe_items"][0]
        self.assertEqual((line["price"], line["original_price"], line["discount_percent"]), (92_000, 100_000, 8))
        self.assertEqual(st.state, self.oe.OrderEditStates.editing)
        self.render.assert_awaited()

    def test_back_to_full_price_drops_the_badge(self):
        line = dict(_line(1, 4, 90_000), original_price=100_000, discount_percent=10)
        st, _ = self.got("0", line)
        line = st.data["oe_items"][0]
        self.assertEqual(line["price"], 100_000)
        self.assertNotIn("original_price", line)
        self.assertNotIn("discount_percent", line)

    def test_nonsense_asks_again(self):
        st, msg = self.got("qimmat", _line(1, 4, 100_000))
        self.assertEqual(st.data["oe_items"][0]["price"], 100_000)
        msg.answer.assert_awaited()
        self.render.assert_not_awaited()


class RenderPriceButtonTest(unittest.TestCase):
    def test_price_button_only_on_manual_orders(self):
        from unittest.mock import AsyncMock, MagicMock, Mock, patch
        from aiogram.types import CallbackQuery
        from handlers import order_edit as oe
        for source, shown in (("manual", True), ("bot", False)):
            st = _State({"lang": "uz", "oe_order_id": 5, "oe_source": source, "oe_old_total": 10,
                         "oe_items": [_line(1, 1, 10)], "oe_orig": [_line(1, 1, 10)]})
            cb = MagicMock(spec=CallbackQuery)
            cb.message = Mock(photo=None, document=None, message_id=9)
            cb.message.edit_text = AsyncMock()
            with patch.object(oe, "_delete", AsyncMock()):
                asyncio.run(oe._render(cb, st, edit=True))
            kb = cb.message.edit_text.await_args.kwargs["reply_markup"]
            datas = [b.callback_data for row in kb.inline_keyboard for b in row]
            self.assertEqual("oe:price:0" in datas, shown, source)


if __name__ == "__main__":
    unittest.main()
