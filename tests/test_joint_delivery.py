"""Bitta manzilga bitta yetkazish (joint_delivery.py, egasi 2026-11-27)."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ai_sales
import joint_delivery as jd

HOME = (41.280861, 69.102697)


class PlaceTest(unittest.TestCase):
    def test_distance_and_same_place(self):
        self.assertLess(jd.distance_m(*HOME, 41.2812, 69.1030), 60)
        self.assertTrue(jd.same_place({"latitude": HOME[0], "longitude": HOME[1]}, 41.2812, 69.1030, None))
        self.assertFalse(jd.same_place({"latitude": HOME[0], "longitude": HOME[1]}, 41.30, 69.24, None))

    def test_address_text_when_no_pin(self):
        order = {"latitude": None, "longitude": None, "address": "Mevazar, Zangiota tumani, 12-uy"}
        self.assertTrue(jd.same_place(order, None, None, "mevazar zangiota tumani 12 uy"))
        self.assertFalse(jd.same_place(order, None, None, "Chilonzor 9"))
        self.assertFalse(jd.same_place({"address": "uy"}, None, None, "uy"))   # too short to trust

    def test_fee_paid(self):
        items = [{"price": 29000, "quantity": 1}, {"price": 28000, "quantity": 1}, {"price": 0, "quantity": 1}]
        self.assertEqual(jd.fee_paid(91000, 0, items), 34000)
        self.assertEqual(jd.fee_paid(57000, 0, items), 0)
        self.assertEqual(jd.fee_paid(47000, 10000, items), 0)


class FakeConn:
    def __init__(self, rows):
        self.rows, self.updates, self.args = rows, [], None

    async def fetch(self, sql, *args):
        self.args = args
        return self.rows

    async def execute(self, sql, *args):
        self.updates.append(args)


class LookupTest(unittest.TestCase):
    def test_only_open_courier_orders_and_newest_same_place(self):
        conn = FakeConn([{"id": 1124, "latitude": HOME[0], "longitude": HOME[1], "address": ""}])
        got = asyncio.run(jd.open_order_at(5, *HOME, conn=conn))
        self.assertEqual(got, 1124)
        uid, method, statuses, _since, exclude = conn.args
        self.assertEqual((uid, method), (5, "self"))
        self.assertEqual(statuses, ["pending", "confirmed", "preparing", "ready"])   # not shipped/delivered
        self.assertNotIn("shipped", statuses)

    def test_other_place_is_separate(self):
        conn = FakeConn([{"id": 1124, "latitude": 41.33, "longitude": 69.28, "address": ""}])
        self.assertIsNone(asyncio.run(jd.open_order_at(5, *HOME, conn=conn)))

    def test_waive_only_for_courier(self):
        with patch.object(jd, "open_order_at", AsyncMock(return_value=1124)):
            self.assertEqual(asyncio.run(jd.waive("self", 5, *HOME)), 1124)
            self.assertIsNone(asyncio.run(jd.waive("pickup", 5, *HOME)))
            self.assertIsNone(asyncio.run(jd.waive("uzpost", 5, *HOME)))


class MarkTest(unittest.TestCase):
    ITEMS = [{"price": 29000, "quantity": 1}, {"price": 28000, "quantity": 1}]

    def test_marked_when_fee_waived(self):
        conn = FakeConn([{"id": 1124, "latitude": HOME[0], "longitude": HOME[1], "address": ""}])
        got = asyncio.run(jd.mark_created(conn, 1125, 5, "self", *HOME, "", 57000, 0, self.ITEMS))
        self.assertEqual(got, 1124)
        self.assertEqual(conn.updates, [(1124, 1125)])
        self.assertEqual(conn.args[-1], 1125)            # never joins itself

    def test_not_marked_when_fee_paid_or_not_courier(self):
        conn = FakeConn([{"id": 1124, "latitude": HOME[0], "longitude": HOME[1], "address": ""}])
        self.assertIsNone(asyncio.run(jd.mark_created(conn, 1125, 5, "self", *HOME, "", 91000, 0, self.ITEMS)))
        self.assertIsNone(asyncio.run(jd.mark_created(conn, 1125, 5, "pickup", *HOME, "", 57000, 0, self.ITEMS)))
        self.assertEqual(conn.updates, [])


class TextTest(unittest.TestCase):
    def test_notes(self):
        self.assertIn("#1124", jd.note(1124, "uz"))
        self.assertIn("Доставим", jd.note(1124, "ru"))
        self.assertIn("бирга", jd.note(1124, "uz_cyr"))
        self.assertIn("BITTA MANZILGA BITTA YETKAZISH", ai_sales._sales_rules())


if __name__ == "__main__":
    unittest.main()
