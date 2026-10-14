"""Savat broni (egasi, 2026-10-13): savatga solingan mahsulot 24 soat
egasiniki, boshqa xaridor faqat qolganini oladi, buyurtma boshqaning
bronini ololmaydi, muddati tugasa sotuvga qaytadi. Baza — xotiradagi
soxta ulanish (SQL qatorlari bo'yicha), Telegram — mock."""
import asyncio
import json
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
from database import InsufficientStockError

ALI, VALI, GULI = 101, 202, 303


def run(coro):
    return asyncio.run(coro)


class FakeConn:
    """Just enough of asyncpg for the Savat broni queries, keyed on SQL text."""

    def __init__(self, shelf, sets=None):
        self.shelf = dict(shelf)                 # product_id -> quantity
        self.sets = sets or {}                   # set_id -> [(product_id, qty)]
        self.cart = []                           # dict rows
        self.next_id = 1
        self.notices = []

    # -- helpers --
    def now(self):
        return datetime.utcnow()

    def hold(self):
        return self.now() + timedelta(hours=24)

    def live(self, row):
        return row.get("reserved_until") is not None and row["reserved_until"] > self.now()

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return _Tx()

    # -- asyncpg API --
    async def fetch(self, sql, *args):
        if "SUM(qty) AS held" in sql:
            ids, ex_user, ex_cart = args
            held = {}
            for r in self.cart:
                if not self.live(r) or r["user_id"] == ex_user or r["id"] == ex_cart:
                    continue
                parts = [(r["product_id"], 1.0)] if r["product_id"] else self.sets.get(r["set_id"], [])
                for pid, q in parts:
                    if pid in ids:
                        held[pid] = held.get(pid, 0.0) + r["quantity"] * q
            return [{"pid": p, "held": h} for p, h in held.items()]
        if "FROM product_set_items WHERE set_id" in sql:
            return [{"product_id": p, "quantity": q} for p, q in self.sets.get(args[0], [])]
        if "SELECT id, quantity FROM products WHERE id = ANY" in sql:
            return [{"id": p, "quantity": self.shelf[p]} for p in args[0] if p in self.shelf]
        if "WITH gone AS" in sql:
            gone = [r for r in self.cart if r.get("reserved_until") and r["reserved_until"] <= self.now()]
            self.cart = [r for r in self.cart if r not in gone]
            return [{"user_id": r["user_id"], "quantity": r["quantity"], "is_set": bool(r["set_id"]),
                     "name": f"P{r['product_id'] or r['set_id']}", "name_ru": None, "unit": "piece"}
                    for r in gone]
        raise AssertionError(f"unexpected fetch: {sql[:80]}")

    async def fetchrow(self, sql, *args):
        if "FROM cart WHERE user_id = $1 AND product_id = $2 FOR UPDATE" in sql:
            return next(({"id": r["id"], "quantity": r["quantity"]} for r in self.cart
                         if r["user_id"] == args[0] and r["product_id"] == args[1]), None)
        if "FROM cart WHERE user_id = $1 AND set_id = $2 FOR UPDATE" in sql:
            return next(({"id": r["id"], "quantity": r["quantity"]} for r in self.cart
                         if r["user_id"] == args[0] and r["set_id"] == args[1]), None)
        if "SELECT user_id, product_id, set_id FROM cart WHERE id" in sql:
            return next(({k: r[k] for k in ("user_id", "product_id", "set_id")}
                         for r in self.cart if r["id"] == args[0]), None)
        if sql.strip().startswith("UPDATE products SET quantity = quantity - $1"):
            qty, pid = args
            self.shelf[pid] -= qty
            return {"quantity": self.shelf[pid], "name": f"P{pid}", "low_stock_threshold": None}
        raise AssertionError(f"unexpected fetchrow: {sql[:80]}")

    async def fetchval(self, sql, *args):
        if "SELECT quantity FROM products WHERE id = $1 FOR UPDATE" in sql:
            return self.shelf.get(args[0])
        if "MIN(reserved_until)" in sql:
            live = [r["reserved_until"] for r in self.cart if r["user_id"] == args[0] and self.live(r)]
            return min(live) if live else None
        if "INSERT INTO cart_release_notices" in sql:
            self.notices.append({"user_id": args[0], "items": json.loads(args[1])})
            return len(self.notices)
        raise AssertionError(f"unexpected fetchval: {sql[:80]}")

    async def execute(self, sql, *args):
        if sql.startswith("DELETE FROM cart WHERE id"):
            self.cart = [r for r in self.cart if r["id"] != args[0]]
        elif "INSERT INTO cart (user_id, product_id" in sql or "INSERT INTO cart (user_id, set_id" in sql:
            is_set = "set_id" in sql.split("(")[1]
            self.cart.append({"id": self.next_id, "user_id": args[0],
                              "product_id": None if is_set else args[1], "set_id": args[1] if is_set else None,
                              "quantity": float(args[2]), "reserved_until": self.hold()})
            self.next_id += 1
        elif "UPDATE cart SET quantity = $1" in sql:
            for r in self.cart:
                if r["id"] == args[1]:
                    r.update(quantity=float(args[0]), reserved_until=self.hold())
        elif "UPDATE cart SET reserved_until" in sql and "WHERE user_id = $1" in sql:
            for r in self.cart:
                if r["user_id"] == args[0] and self.live(r):
                    r["reserved_until"] = self.hold()
        else:
            raise AssertionError(f"unexpected execute: {sql[:80]}")


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


class _Base(unittest.TestCase):
    shelf = {1: 4.0}
    sets = {}

    def setUp(self):
        self.conn = FakeConn(self.shelf, self.sets)
        p = patch.object(database, "pool", FakePool(self.conn))
        p.start()
        self.addCleanup(p.stop)

    def take(self, user, qty, pid=1):
        async def go():
            async with self.conn.transaction():
                return await database._take_stock(self.conn, pid, qty, user)
        return run(go())


class FirstComeTest(_Base):
    """The owner's case: 4 coconut chips on the shelf."""

    def test_first_cart_holds_the_pieces(self):
        self.assertEqual(run(database.add_to_cart(ALI, 1, 4)), 4)
        self.assertEqual(run(database.add_to_cart(VALI, 1, 2)), 0)      # nothing free for Vali

    def test_second_buyer_gets_only_the_rest(self):
        run(database.add_to_cart(ALI, 1, 3))
        self.assertEqual(run(database.add_to_cart(VALI, 1, 2)), 1)      # capped at the 1 left

    def test_own_cart_grows_up_to_the_shelf(self):
        run(database.add_to_cart(ALI, 1, 2))
        self.assertEqual(run(database.add_to_cart(ALI, 1, 5)), 4)

    def test_set_quantity_is_capped_too(self):
        run(database.add_to_cart(VALI, 1, 1))
        run(database.add_to_cart(ALI, 1, 1))
        ali_line = next(r["id"] for r in self.conn.cart if r["user_id"] == ALI)
        self.assertEqual(run(database.set_cart_quantity(ali_line, 9)), 3)   # 4 on the shelf − Vali's 1

    def test_nothing_free_removes_a_shrunk_line(self):
        run(database.add_to_cart(ALI, 1, 2))
        self.conn.shelf[1] = 0                     # an admin wrote the stock off
        self.assertEqual(run(database.add_to_cart(ALI, 1, 1)), 0)
        self.assertFalse(self.conn.cart)


class CheckoutTest(_Base):
    def test_order_never_takes_another_buyers_hold(self):
        run(database.add_to_cart(ALI, 1, 4))
        with self.assertRaises(InsufficientStockError) as ctx:
            self.take(VALI, 2)
        self.assertEqual(ctx.exception.available, 0)
        self.assertEqual(self.conn.shelf[1], 4)

    def test_holder_buys_what_they_hold(self):
        run(database.add_to_cart(ALI, 1, 4))
        row = self.take(ALI, 4)
        self.assertEqual(row["quantity"], 0)

    def test_others_take_only_the_unheld_part(self):
        run(database.add_to_cart(ALI, 1, 3))
        self.take(VALI, 1)
        with self.assertRaises(InsufficientStockError):
            self.take(GULI, 1)


class ExpiryTest(_Base):
    def expire(self, user):
        for r in self.conn.cart:
            if r["user_id"] == user:
                r["reserved_until"] = datetime.utcnow() - timedelta(minutes=1)

    def test_expired_hold_frees_the_stock(self):
        run(database.add_to_cart(ALI, 1, 4))
        self.expire(ALI)
        self.assertEqual(run(database.add_to_cart(VALI, 1, 2)), 2)

    def test_release_takes_lines_out_and_queues_one_notice(self):
        run(database.add_to_cart(ALI, 1, 4))
        run(database.add_to_cart(VALI, 1, 0))      # nothing free — no line
        self.expire(ALI)
        notices = run(database.release_expired_holds())
        self.assertEqual([n["user_id"] for n in notices], [ALI])
        self.assertEqual(notices[0]["items"][0]["quantity"], 4)
        self.assertFalse([r for r in self.conn.cart if r["user_id"] == ALI])

    def test_touching_the_cart_restarts_the_24_hours(self):
        run(database.add_to_cart(ALI, 1, 1))
        self.conn.cart[0]["reserved_until"] = datetime.utcnow() + timedelta(hours=2)
        run(database.add_to_cart(ALI, 1, 1))
        left = self.conn.cart[0]["reserved_until"] - datetime.utcnow()
        self.assertGreater(left, timedelta(hours=23))

    def test_checkout_extends_the_hold(self):
        run(database.add_to_cart(ALI, 1, 1))
        self.conn.cart[0]["reserved_until"] = datetime.utcnow() + timedelta(hours=1)
        run(database.extend_cart_hold(ALI))
        self.assertGreater(self.conn.cart[0]["reserved_until"] - datetime.utcnow(), timedelta(hours=23))

    def test_legacy_lines_hold_nothing(self):
        # Lines from before this shipped: reserved_until NULL.
        self.conn.cart.append({"id": 99, "user_id": ALI, "product_id": 1, "set_id": None,
                               "quantity": 4.0, "reserved_until": None})
        self.assertEqual(run(database.add_to_cart(VALI, 1, 4)), 4)
        self.assertEqual(run(database.release_expired_holds()), [])


class SetsTest(_Base):
    shelf = {1: 4.0, 2: 10.0}
    sets = {7: [(1, 2.0), (2, 1.0)]}               # a set = 2 × P1 + 1 × P2

    def test_a_set_holds_its_parts(self):
        self.assertEqual(run(database.add_to_cart(ALI, set_id=7, quantity=1)), 1)
        self.assertEqual(run(database.add_to_cart(VALI, 1, 4)), 2)     # 2 of P1 are in Ali's set

    def test_sets_are_capped_by_the_scarcest_part(self):
        self.assertEqual(run(database.add_to_cart(ALI, set_id=7, quantity=5)), 2)


class DisplayTest(_Base):
    def test_viewer_sees_what_is_free_and_band(self):
        run(database.add_to_cart(ALI, 1, 4))
        seen = run(database.apply_holds([{"id": 1, "name": "Kokos chips", "quantity": 4}], VALI))[0]
        self.assertEqual(seen["quantity"], 0)
        self.assertTrue(seen["held_out"])
        own = run(database.apply_holds([{"id": 1, "quantity": 4}], ALI))[0]
        self.assertEqual(own["quantity"], 4)                           # their own hold isn't hidden

    def test_stock_view_and_hold_end(self):
        run(database.add_to_cart(ALI, 1, 3))
        self.assertEqual(run(database.stock_view([1], VALI))[1], {"shelf": 4.0, "held": 3.0, "free": 1.0})
        self.assertIsNotNone(run(database.cart_hold_until(ALI)))
        self.assertIsNone(run(database.cart_hold_until(VALI)))


class MessagesTest(unittest.TestCase):
    def test_release_text_in_every_language(self):
        import cart_reservations as cr
        items = [{"name": "Kokos chipsi", "name_ru": "Кокосовые чипсы", "quantity": 4.0, "unit": "piece",
                  "is_set": False}]
        self.assertIn("sotuvga qaytarildi", cr.release_text(items, "uz"))
        self.assertIn("Kokos chipsi × 4", cr.release_text(items, "uz"))
        self.assertIn("вернулись в продажу", cr.release_text(items, "ru"))
        self.assertIn("Кокосовые чипсы", cr.release_text(items, "ru"))
        self.assertIn("қайтарилди", cr.release_text(items, "uz_cyr"))

    def test_hold_end_text(self):
        import cart_reservations as cr
        now = datetime(2026, 10, 14, 8, 0)                             # 13:00 Tashkent
        self.assertEqual(cr.hold_end_text(datetime(2026, 10, 14, 13, 40), "uz", now), "bugun 18:40")
        self.assertEqual(cr.hold_end_text(datetime(2026, 10, 14, 21, 0), "uz", now), "ertaga 02:00")
        self.assertEqual(cr.hold_end_text(datetime(2026, 10, 14, 21, 0), "ru", now), "завтра 02:00")

    def test_release_loop_waits_for_daytime_to_tell(self):
        import cart_reservations as cr
        bot = AsyncMock()
        notice = {"id": 5, "user_id": ALI, "items": [{"name": "Kokos", "quantity": 1, "unit": "piece"}]}
        with patch.object(database, "release_expired_holds", AsyncMock(return_value=[notice])), \
             patch.object(database, "pending_release_notices", AsyncMock(return_value=[notice])), \
             patch.object(database, "mark_release_notice_sent", AsyncMock(return_value=True)), \
             patch.object(database, "get_user_languages", AsyncMock(return_value={ALI: "uz"})):
            with patch.object(cr, "_quiet", return_value=True):
                stats = run(cr.run_once(bot))
            self.assertEqual((stats["released"], stats["sent"]), (1, 0))   # released at night, told later
            bot.send_message.assert_not_called()
            with patch.object(cr, "_quiet", return_value=False), patch.object(cr, "SEND_DELAY", 0):
                stats = run(cr.run_once(bot))
            self.assertEqual(stats["sent"], 1)
            self.assertIn("sotuvga qaytarildi", bot.send_message.call_args.args[1])


class MiniAppTest(_Base):
    def test_cards_show_band_not_sold_out(self):
        import webapp_server
        run(database.add_to_cart(ALI, 1, 4))
        product = {"id": 1, "name": "Kokos chips", "price": 50000, "quantity": 4, "unit": "piece",
                   "category": "snacks", "discount_percent": 0, "discount_until": None}
        with patch("bot_discount.display_prices", AsyncMock(return_value=[None])):
            seen = run(webapp_server._serialize_products([product], "uz", VALI))[0]
            own = run(webapp_server._serialize_products([product], "uz", ALI))[0]
        self.assertTrue(seen["out_of_stock"] and seen["held_out"])
        self.assertFalse(own["out_of_stock"] or own["held_out"])

    def test_band_layer_is_wired_into_the_page(self):
        page = open(os.path.join(os.path.dirname(database.__file__), "webapp", "index.html"),
                    encoding="utf-8").read()
        self.assertIn("function markHeld(", page)
        self.assertIn("p.held_out", page)
        self.assertIn("reason === 'held'", page)
        for key in ("heldOut", "heldLimit", "addedPartly"):
            self.assertEqual(page.count(key + ":"), 2, key)


class WarningTimingTest(unittest.TestCase):
    """abandoned_cart stage 2 is the warning ~4 h before the hold ends."""

    def test_daytime_uses_the_normal_window(self):
        import abandoned_cart as ac
        self.assertEqual(ac.stage2_min_idle(20 * 60, datetime(2026, 10, 14, 15, 0)), 20 * 60)

    def test_last_call_before_the_night(self):
        import abandoned_cart as ac
        # 20:40 → 09:00 is 740 min away: holds ending before the morning are warned now.
        self.assertEqual(ac.stage2_min_idle(20 * 60, datetime(2026, 10, 14, 20, 40)), 24 * 60 - 740)

    def test_window_ends_with_the_hold(self):
        import abandoned_cart as ac
        self.assertEqual(dict((s, (lo, hi)) for s, lo, hi in ac.STAGES)[2], (20 * 60, 24 * 60))


if __name__ == "__main__":
    unittest.main()
