"""Qo'lda / B2B buyurtma ombordan olmaydi — o'chirilganda yoki bekor
qilinganda ham omborga hech narsa qaytmasligi kerak; ulgurji qatorda miqdor
va narx almashib qolganday ko'rinsa, saqlashdan oldin so'raladi; #889 dan
omborga qo'shilib qolgan miqdor bir marta ayiriladi (2026-11-06).
Bazaga ulanmaydi, xabar yuborilmaydi."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
import stock_corrections
from handlers import admin


class _Tx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class FakeConn:
    def __init__(self, order=None, stock=None):
        self.order = order
        self.stock = dict(stock or {})
        self.status = order and order["status"]
        self.deleted = False

    def transaction(self):
        return _Tx()

    async def fetchrow(self, sql, *args):
        if sql.startswith("SELECT * FROM orders"):
            return dict(self.order) if self.order else None
        if sql.startswith("SELECT name, unit, quantity FROM products"):
            pid = args[0]
            if pid not in self.stock:
                return None
            return {"name": f"p{pid}", "unit": "kg", "quantity": self.stock[pid]}
        raise AssertionError(sql)

    async def execute(self, sql, *args):
        if "quantity = quantity + $1" in sql:
            qty, pid = args
            self.stock[pid] = self.stock.get(pid, 0) + qty
        elif "quantity = quantity - $1" in sql:
            qty, pid = args
            self.stock[pid] -= qty
        elif sql.startswith("UPDATE orders SET status = 'cancelled'"):
            self.status = "cancelled"
        elif sql.startswith("DELETE FROM orders"):
            self.deleted = True
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


def _order(source, status="delivered"):
    return {"id": 889, "status": status, "source": source,
            "items": [{"product_id": 38, "quantity": 6000, "price": 50},
                      {"product_id": 51, "quantity": 12000, "price": 50}]}


def run(coro):
    return asyncio.run(coro)


class StockRestoreTest(unittest.TestCase):
    def _call(self, fn, source, status="delivered"):
        conn = FakeConn(_order(source, status), {38: 6, 51: 5})
        with patch.object(database, "pool", FakePool(conn)), \
             patch.object(database, "drop_order_expenses", AsyncMock(return_value=0)):
            run(fn(889))
        return conn

    def test_deleting_a_b2b_or_manual_order_puts_nothing_back(self):
        for source in ("b2b", "manual"):
            conn = self._call(database.delete_order_permanently, source)
            self.assertTrue(conn.deleted)
            self.assertEqual(conn.stock, {38: 6, 51: 5}, source)

    def test_cancelling_a_b2b_or_manual_order_puts_nothing_back(self):
        for source in ("b2b", "manual"):
            conn = self._call(database.cancel_order, source, status="confirmed")
            self.assertEqual(conn.status, "cancelled")
            self.assertEqual(conn.stock, {38: 6, 51: 5}, source)

    def test_bot_and_site_orders_still_get_their_stock_back(self):
        for source in ("bot", "webapp", None):
            conn = self._call(database.delete_order_permanently, source, status="pending")
            self.assertEqual(conn.stock, {38: 6006, 51: 12005}, source)
            conn = self._call(database.cancel_order, source, status="pending")
            self.assertEqual(conn.stock, {38: 6006, 51: 12005}, source)

    def test_an_already_cancelled_bot_order_is_not_restored_twice(self):
        conn = self._call(database.delete_order_permanently, "bot", status="cancelled")
        self.assertEqual(conn.stock, {38: 6, 51: 5})


class SubtractStockTest(unittest.TestCase):
    def test_takes_the_amount_out_and_leaves_a_short_product_alone(self):
        conn = FakeConn(stock={38: 6006, 35: 50})
        with patch.object(database, "pool", FakePool(conn)):
            done = run(database.subtract_stock([(38, 6000), (35, 12000), (99, 1)]))
        self.assertEqual(conn.stock, {38: 6, 35: 50})
        self.assertEqual([(d["id"], d["before"], d["after"], d["applied"]) for d in done],
                         [(38, 6006, 6, True), (35, 50, 50, False)])


class CorrectionTest(unittest.TestCase):
    def test_889_amounts(self):
        self.assertEqual(stock_corrections.CORRECTIONS["stock-fix-b2b-889-2026-11-06"]["lines"],
                         [(38, 6000), (35, 12000), (36, 8000), (51, 12000)])

    def test_applied_once_and_every_admin_told(self):
        bot = MagicMock()
        bot.send_message = AsyncMock()
        done = [{"id": 38, "name": "Kepak", "unit": "kg", "before": 6006.0, "after": 6.0, "applied": True},
                {"id": 35, "name": "Solod", "unit": "kg", "before": 50.0, "after": 50.0, "applied": False}]
        sub = AsyncMock(return_value=done)
        with patch.object(stock_corrections, "ADMIN_IDS", [1, 2, 1]), \
             patch.object(database, "claim_release_notes", AsyncMock(side_effect=[True, False])), \
             patch.object(database, "subtract_stock", sub):
            run(stock_corrections.run_once(bot))
            run(stock_corrections.run_once(bot))
        sub.assert_awaited_once()
        self.assertEqual([c.args[0] for c in bot.send_message.await_args_list], [1, 2])
        text = bot.send_message.await_args_list[0].args[1]
        self.assertIn("6 006 → <b>6</b> kg", text)
        self.assertIn("Solod: 50 — o'zgartirilmadi", text)

    def test_a_failure_does_not_break_startup(self):
        with patch.object(database, "claim_release_notes", AsyncMock(side_effect=RuntimeError("db"))):
            run(stock_corrections.run_once(None))


class SwapGuessTest(unittest.TestCase):
    def test_the_889_lines_look_swapped(self):
        for qty, price, ref in ((6000, 50, 10000), (12000, 50, 19000), (8000, 50, 15000), (12000, 50, 25000)):
            self.assertTrue(admin._looks_swapped(qty, price, ref), (qty, price, ref))

    def test_normal_wholesale_lines_pass(self):
        self.assertFalse(admin._looks_swapped(50, 6000, 10000))     # the corrected #897 line
        self.assertFalse(admin._looks_swapped(500, 4000, 10000))    # deep wholesale price
        self.assertFalse(admin._looks_swapped(10, 1500, 10000))     # cheap but tiny quantity
        self.assertFalse(admin._looks_swapped(6000, 50, 0))         # no reference price


class SwapButtonsTest(unittest.TestCase):
    def _press(self, data, answer):
        state = MagicMock()
        state.get_data = AsyncMock(return_value=dict(data))
        state.update_data = AsyncMock()
        cb = MagicMock()
        cb.from_user.id = 1
        cb.data = answer
        cb.answer = AsyncMock()
        cb.message.edit_reply_markup = AsyncMock()
        add = AsyncMock()
        with patch.object(admin, "is_admin", return_value=True), \
             patch.object(admin, "_add_manual_item", add):
            run(admin.b2b_swap_answer(cb, state))
        return add

    STATE = {"lang": "uz", "pending_qty": 6000.0, "pending_price": 50.0,
             "pending_product_id": 38, "pending_product_name": "Kepak", "pending_bulk": True}

    def test_fix_swaps_the_two_numbers(self):
        add = self._press(self.STATE, "b2bswap:fix")
        _msg, _state, data, lang, price = add.await_args.args
        self.assertEqual((data["pending_qty"], price), (50.0, 6000.0))
        self.assertTrue(add.await_args.kwargs["bulk"])

    def test_keep_saves_what_was_typed(self):
        add = self._press(self.STATE, "b2bswap:keep")
        _msg, _state, data, lang, price = add.await_args.args
        self.assertEqual((data["pending_qty"], price), (6000.0, 50.0))

    def test_a_stale_button_does_nothing(self):
        add = self._press(dict(self.STATE, pending_price=None), "b2bswap:fix")
        add.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
