"""Expense CRUD through real HTTP handlers and SQL; no live services."""
import contextlib
import os
import re
import sqlite3
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("ADMIN_WEB_PASSWORD", "test-password")

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import admin_web
import database


class ExpenseConnection:
    """Run the SQL against an isolated relational store, preserving predicates."""
    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            amount DOUBLE PRECISION NOT NULL,
            created_at TEXT DEFAULT '2026-10-26T10:00:00',
            bonus_order_id INTEGER, gift_order_id INTEGER, delivery_order_id INTEGER)""")
        self.db.executemany("INSERT INTO expenses VALUES (?,?,?,?,?,?,?)", [
            (325, "Bonus", 1250000, "2026-10-25T11:07:31", None, None, None),
            (326, "Sovg'a", 5000, "2026-10-25T12:00:00", None, 753, None),
            (327, "Kuryer", 25000, "2026-10-25T13:00:00", None, None, 749),
            (328, "Aksiya", 5000, "2026-10-25T14:00:00", 752, None, None),
        ])

    def query(self, sql, args):
        positions = [int(n) - 1 for n in re.findall(r"\$(\d+)", sql)]
        return self.db.execute(re.sub(r"\$\d+", "?", sql), tuple(args[i] for i in positions))

    async def fetchval(self, sql, *args):
        row = self.query(sql, args).fetchone()
        return row[0] if row else None

    async def fetchrow(self, sql, *args):
        row = self.query(sql, args).fetchone()
        return dict(row) if row else None

    async def fetch(self, sql, *args):
        return [dict(row) for row in self.query(sql, args).fetchall()]


class ExpensePool:
    def __init__(self, conn):
        self.conn = conn

    @contextlib.asynccontextmanager
    async def acquire(self):
        yield self.conn


class ExpenseCrudTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = ExpenseConnection()
        self.addCleanup(self.conn.db.close)
        self.pool_patch = patch.object(database, "pool", ExpensePool(self.conn))
        self.pool_patch.start()
        self.addCleanup(self.pool_patch.stop)
        app = web.Application()
        admin_web.setup_admin_routes(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.client.session.cookie_jar.update_cookies({admin_web.SESSION_COOKIE: admin_web._make_session()})

    async def expenses(self):
        response = await self.client.get("/admin/api/expenses")
        self.assertEqual(response.status, 200)
        return (await response.json())["expenses"]

    async def test_list_distinguishes_manual_and_order_linked_expenses(self):
        rows = {r["id"]: r for r in await self.expenses()}
        self.assertIs(rows[325].get("editable"), True)
        for eid in (326, 327, 328):
            self.assertIs(rows[eid].get("editable"), False)

    async def test_create_edit_and_delete_manual_expense(self):
        response = await self.client.post("/admin/api/expenses", json={"name": "  Bonus  ", "amount": 1250000})
        self.assertEqual(response.status, 200)
        eid = (await response.json())["id"]
        before = next(r for r in await self.expenses() if r["id"] == eid)
        response = await self.client.post(f"/admin/api/expenses/{eid}", json={"name": "Bonus tuzatildi", "amount": 125000})
        self.assertEqual(response.status, 200, await response.text())
        after = next(r for r in await self.expenses() if r["id"] == eid)
        self.assertEqual(after["name"], "Bonus tuzatildi")
        self.assertEqual(after["amount"], 125000)
        self.assertEqual(after["created_at"], before["created_at"])
        response = await self.client.post(f"/admin/api/expenses/{eid}/delete")
        self.assertEqual(response.status, 200, await response.text())
        self.assertNotIn(eid, [r["id"] for r in await self.expenses()])

    async def test_mistaken_amount_correction_changes_total_by_exact_difference(self):
        before = sum(r["amount"] for r in await self.expenses())
        response = await self.client.post("/admin/api/expenses/325", json={"name": "Bonus", "amount": 125000})
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(before - sum(r["amount"] for r in await self.expenses()), 1125000)

    async def test_automatic_expenses_cannot_be_changed_or_deleted(self):
        for eid in (326, 327, 328):
            before = dict(self.conn.db.execute("SELECT * FROM expenses WHERE id=?", (eid,)).fetchone())
            response = await self.client.post(f"/admin/api/expenses/{eid}", json={"name": "Override", "amount": 1})
            self.assertEqual(response.status, 409, await response.text())
            response = await self.client.post(f"/admin/api/expenses/{eid}/delete")
            self.assertEqual(response.status, 409, await response.text())
            self.assertEqual(dict(self.conn.db.execute("SELECT * FROM expenses WHERE id=?", (eid,)).fetchone()), before)

    async def test_missing_expense_returns_404(self):
        for path, body in [("/admin/api/expenses/999", {"name": "Bonus", "amount": 125000}),
                           ("/admin/api/expenses/999/delete", None)]:
            response = await self.client.post(path, json=body)
            self.assertEqual(response.status, 404, await response.text())

    async def test_invalid_payload_does_not_create_or_change_money(self):
        payloads = [
            {"name": "Bonus", "amount": a} for a in [0, -1, True, "NaN", "Infinity", "-Infinity", None, "abc"]
        ] + [{"name": "   ", "amount": 125000}, {"name": 123, "amount": 125000},
             {"name": "x" * 201, "amount": 125000}, [], None]
        for body in payloads:
            for path in ("/admin/api/expenses", "/admin/api/expenses/325"):
                with self.subTest(body=body, path=path):
                    response = await self.client.post(path, json=body)
                    self.assertEqual(response.status, 400, await response.text())
        rows = await self.expenses()
        self.assertEqual(len(rows), 4)
        self.assertEqual(next(r for r in rows if r["id"] == 325)["amount"], 1250000)

    async def test_authentication_is_required_for_every_mutation(self):
        self.client.session.cookie_jar.clear()
        for path in ("/admin/api/expenses", "/admin/api/expenses/325", "/admin/api/expenses/325/delete"):
            response = await self.client.post(path, json={"name": "Bonus", "amount": 1})
            self.assertEqual(response.status, 401, await response.text())
        response = await self.client.get("/admin/api/expenses")
        self.assertEqual(response.status, 401)


if __name__ == "__main__":
    unittest.main()
