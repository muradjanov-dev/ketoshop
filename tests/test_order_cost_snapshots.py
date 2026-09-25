"""Cost snapshots keep historical order profit stable after catalog edits."""
import asyncio
import contextlib
import json
import os
import unittest
from datetime import datetime
from unittest import mock

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("ADMIN_WEB_PASSWORD", "test-password")

import database
import admin_web
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer


class SnapshotConn:
    def __init__(self):
        self.inserted_items = []
        self.executed = []
        self.order_items = [{"product_id": 10, "name": "Flax", "quantity": 2}]
        self.audit_records = []
        self.cost_write_events = []
        self.transaction_active = False

    async def fetch(self, sql, *args):
        if "FROM products WHERE id = ANY" in sql:
            self.cost_write_events.append(("snapshot", self.transaction_active))
            return [
                {"id": 10, "cost_price": 40_000},
                {"id": 11, "cost_price": 0},
                {"id": 12, "cost_price": float("inf")},
            ]
        if "FROM product_set_items" in sql:
            return [
                {"set_id": 7, "quantity": 2, "cost_price": 30_000},
                {"set_id": 7, "quantity": 1, "cost_price": 0},
            ]
        if "FROM order_line_cost_audit" in sql:
            return self.audit_records
        return []

    async def fetchrow(self, sql, *args):
        if "UPDATE products SET quantity" in sql:
            return {"quantity": 4, "name": "Mahsulot", "low_stock_threshold": 0}
        if "FROM orders" in sql and "items" in sql:
            row = {"items": json.dumps(self.order_items)}
            if "created_at" in sql:
                row.update({"id": 41, "created_at": datetime(2026, 9, 1), "status": "delivered"})
            return row
        return None

    async def fetchval(self, sql, *args):
        if "INSERT INTO orders" in sql:
            self.cost_write_events.append(("insert", self.transaction_active))
            if "latitude" in sql:
                index = 5
            elif "B2B Eritritol" in sql:
                index = 3
            elif "phone, address, items" in sql:
                index = 4
            else:
                index = 2
            self.inserted_items.append(json.loads(args[index]))
            return 41
        if "INSERT INTO order_line_cost_audit" in sql:
            self.executed.append((sql, args))
            self.audit_records.append({
                "line_index": args[1], "old_unit_cost": args[2],
                "new_unit_cost": args[3], "reason": args[4],
                "changed_at": datetime(2026, 9, 25),
            })
            return 99
        return 1

    async def execute(self, sql, *args):
        self.executed.append((sql, args))
        if sql.startswith("UPDATE orders SET items"):
            self.order_items = json.loads(args[1])
        return "OK"

    def transaction(self):
        @contextlib.asynccontextmanager
        async def _transaction():
            self.transaction_active = True
            try:
                yield
            finally:
                self.transaction_active = False
        return _transaction()


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        @contextlib.asynccontextmanager
        async def _acquire():
            yield self.conn
        return _acquire()


class CostSnapshotTests(unittest.TestCase):
    def test_snapshot_records_product_set_and_missing_cost_without_backfill(self):
        items = [
            {"product_id": 10, "quantity": 2},
            {"is_set": True, "set_id": 7, "quantity": 1},
            {"product_id": 11, "quantity": 1},
            {"product_id": 12, "quantity": 1},
            {"product_id": 99, "quantity": 1},
            {"product_id": 10, "quantity": 100, "stock_quantity": 0.1, "is_bonus": True},
            {"product_id": 10, "quantity": 100, "stock_quantity": 0.1,
             "is_bonus": True, "cost_in_expenses": True},
        ]
        result = asyncio.run(database._snapshot_order_costs(SnapshotConn(), items))

        self.assertEqual(result[0]["unit_cost_snapshot"], 40_000)
        self.assertTrue(result[0]["unit_cost_known"])
        self.assertEqual(result[1]["unit_cost_snapshot"], 60_000)
        self.assertFalse(result[1]["unit_cost_known"])
        self.assertEqual(result[2]["unit_cost_snapshot"], 0)
        self.assertFalse(result[2]["unit_cost_known"])
        self.assertFalse(result[3]["unit_cost_known"])
        self.assertFalse(result[4]["unit_cost_known"])
        self.assertEqual(result[5]["stock_quantity"], 0.1)
        self.assertEqual(database.line_cost(result[5], {}, {}), (4_000, True))
        self.assertNotIn("unit_cost_snapshot", result[6])
        self.assertEqual(database.line_cost(result[6], {10: 40_000}, {}), (0, True))
        self.assertNotIn("unit_cost_snapshot", items[0])

    def test_snapshot_wins_even_when_zero_means_cost_was_missing_at_sale(self):
        item = {"product_id": 10, "quantity": 2,
                "unit_cost_snapshot": 0, "unit_cost_known": False}

        self.assertEqual(database.line_cost(item, {10: 40_000}, {}), (0, False))

    def test_positive_snapshot_survives_catalog_cost_change(self):
        item = {"product_id": 10, "quantity": 2,
                "unit_cost_snapshot": 25_000, "unit_cost_known": True}

        self.assertEqual(database.line_cost(item, {10: 40_000}, {}), (50_000, True))

    def test_gift_and_expense_booked_bonus_are_not_double_costed(self):
        gift = {"product_id": 10, "quantity": 1, "is_gift": True,
                "unit_cost_snapshot": 40_000, "unit_cost_known": True}
        booked_bonus = {"product_id": 10, "quantity": 100, "stock_quantity": 0.1,
                        "is_bonus": True, "cost_in_expenses": True,
                        "unit_cost_snapshot": 40_000, "unit_cost_known": True}
        regular_bonus = {"product_id": 10, "quantity": 100, "stock_quantity": 0.1,
                         "is_bonus": True, "unit_cost_snapshot": 40_000,
                         "unit_cost_known": True}

        self.assertEqual(database.line_cost(gift, {10: 40_000}, {}), (0, True))
        self.assertEqual(database.line_cost(booked_bonus, {10: 40_000}, {}), (0, True))
        self.assertAlmostEqual(database.line_cost(regular_bonus, {10: 40_000}, {})[0], 4_000)

    def test_every_order_creation_path_stores_snapshots(self):
        item = {"product_id": 10, "name": "Flax", "quantity": 1, "price": 100_000}
        for create in (
            lambda: database.add_manual_order(1, "Buyer", "", "", [item], 100_000,
                                               "cash", None, "delivered"),
            lambda: database.add_b2b_order(1, "Company", [item], 100_000),
            lambda: database.create_order(1, "Buyer", "", "", [item], 100_000),
        ):
            conn = SnapshotConn()
            with mock.patch.object(database, "pool", FakePool(conn)):
                asyncio.run(create())
            self.assertEqual(conn.inserted_items[0][0]["unit_cost_snapshot"], 40_000)
            self.assertEqual(conn.cost_write_events, [("snapshot", True), ("insert", True)])

        b2b_eritritol_conn = SnapshotConn()
        with mock.patch.object(database, "pool", FakePool(b2b_eritritol_conn)):
            asyncio.run(database.add_b2b_eritritol_order(
                1, "", "", 0.5, 100_000, cost_per_kg=30_000
            ))
        line = b2b_eritritol_conn.inserted_items[0][0]
        self.assertEqual(line["cost_price"], 30_000)
        self.assertEqual(database.line_cost(line, {}, {}), (15_000, True))

    def test_historical_cost_update_sets_snapshot_and_appends_audit(self):
        conn = SnapshotConn()
        with mock.patch.object(database, "pool", FakePool(conn)):
            audit = asyncio.run(database.set_order_line_unit_cost(41, 0, 55_000, "Hisob-faktura"))
            review = asyncio.run(database.get_order_line_cost_review(41))

        update = next(entry for entry in conn.executed if entry[0].startswith("UPDATE orders"))
        stored = json.loads(update[1][1])
        self.assertEqual(stored[0]["unit_cost_snapshot"], 55_000)
        self.assertTrue(stored[0]["unit_cost_known"])
        audit_insert = next(entry for entry in conn.executed if "INSERT INTO order_line_cost_audit" in entry[0])
        self.assertEqual(audit_insert[1][2:], (40_000, 55_000, "Hisob-faktura"))
        self.assertEqual(audit["old_unit_cost"], 40_000)
        self.assertEqual(database.line_cost(stored[0], {10: 80_000}, {}), (110_000, True))
        self.assertEqual(review["lines"][0]["cost_source"], "snapshot")
        self.assertEqual(review["audit"][0]["new_unit_cost"], 55_000)
        self.assertEqual(review["audit"][0]["reason"], "Hisob-faktura")

    def test_historical_cost_requires_positive_finite_cost_and_reason(self):
        for unit_cost, reason in ((0, "nima uchun"), (-1, "aniq sabab"),
                                  (float("nan"), "aniq sabab"), (12_000, " ")):
            with self.subTest(unit_cost=unit_cost, reason=reason):
                with self.assertRaises(ValueError):
                    asyncio.run(database.set_order_line_unit_cost(41, 0, unit_cost, reason))

    def test_review_and_correction_handle_legacy_product_and_b2b_lines(self):
        conn = SnapshotConn()
        conn.order_items = [
            {"product_id": 10, "name": "Zig'ir urug'i 1000g", "quantity": 1},
            {"id": -1, "name": "Eritritol (B2B)", "quantity": 12, "unit": "kg"},
        ]
        with mock.patch.object(database, "pool", FakePool(conn)):
            review = asyncio.run(database.get_order_line_cost_review(41))
            fixed = asyncio.run(database.set_order_line_unit_cost(41, 0, 48_000, "Hisob-faktura"))

        self.assertEqual(review["lines"][0]["unit_cost"], 40_000)
        self.assertFalse(review["lines"][1]["cost_known"])
        self.assertEqual(fixed["old_unit_cost"], 40_000)
        self.assertNotIn("phone", review)
        self.assertNotIn("customer_name", review)


class AdminCostApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = web.Application()
        admin_web.setup_admin_routes(self.app)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()

    async def test_cost_endpoints_require_admin_session(self):
        response = await self.client.get("/admin/api/orders/41/costs")
        self.assertEqual(response.status, 401)
        response = await self.client.post(
            "/admin/api/orders/41/lines/0/cost",
            json={"unit_cost": 20_000, "reason": "Hisob-faktura"},
        )
        self.assertEqual(response.status, 401)

    async def test_authenticated_admin_can_review_and_correct_cost(self):
        cookie = {admin_web.SESSION_COOKIE: admin_web._make_session()}
        review = {"order_id": 41, "status": "delivered", "created_at": None,
                  "lines": [], "audit": []}
        with mock.patch.object(database, "get_order_line_cost_review", mock.AsyncMock(return_value=review)), \
             mock.patch.object(database, "set_order_line_unit_cost", mock.AsyncMock(
                 return_value={"id": 7, "old_unit_cost": None, "new_unit_cost": 20_000,
                               "reason": "Hisob-faktura"})) as update:
            response = await self.client.get("/admin/api/orders/41/costs", cookies=cookie)
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["order_id"], 41)

            response = await self.client.post(
                "/admin/api/orders/41/lines/0/cost", cookies=cookie,
                json={"unit_cost": 20_000, "reason": "Hisob-faktura"},
            )
            self.assertEqual(response.status, 200)
            update.assert_awaited_once_with(41, 0, 20_000.0, "Hisob-faktura")

            response = await self.client.post(
                "/admin/api/orders/41/lines/0/cost", cookies=cookie,
                json={"unit_cost": float("inf"), "reason": "Hisob-faktura"},
            )
            self.assertEqual(response.status, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
