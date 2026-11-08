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
            bonus_order_id INTEGER, gift_order_id INTEGER, delivery_order_id INTEGER,
            category_id INTEGER)""")
        self.db.execute("""CREATE TABLE expense_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            created_at TEXT DEFAULT '2026-11-08T10:00:00')""")
        self.db.executemany("INSERT INTO expenses (id, name, amount, created_at, bonus_order_id, gift_order_id, "
                            "delivery_order_id) VALUES (?,?,?,?,?,?,?)", [
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

    async def execute(self, sql, *args):
        self.query(sql, args)


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



class ExpenseCategoryTest(unittest.IsolatedAsyncioTestCase):
    """Chiqim kategoriyalari (egasi, 2026-11-08: "xarajatlar bo'limiga kategoriya
    qo'shish imkoniyatini qo'sh")."""
    asyncSetUp = ExpenseCrudTest.asyncSetUp

    async def add_category(self, name):
        response = await self.client.post("/admin/api/expense-categories", json={"name": name})
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    async def listed(self, query=""):
        response = await self.client.get("/admin/api/expenses" + query)
        self.assertEqual(response.status, 200, await response.text())
        return (await response.json())["expenses"]

    async def test_add_pick_filter_and_sum(self):
        first = await self.add_category("  Reklama ")
        self.assertTrue(first["created"])
        again = await self.add_category("REKLAMA")                   # the same category, any case
        self.assertEqual((again["id"], again["created"]), (first["id"], False))
        response = await self.client.post("/admin/api/expenses",
                                          json={"name": "Instagram", "amount": 300000, "category_id": first["id"]})
        self.assertEqual(response.status, 200, await response.text())
        response = await self.client.get("/admin/api/expense-categories")
        cats = (await response.json())["categories"]
        self.assertEqual([(c["name"], c["uses"]) for c in cats], [("Reklama", 1)])

        rows = {r["name"]: r for r in await self.listed()}
        self.assertEqual(rows["Instagram"]["category_name"], "Reklama")
        self.assertIsNone(rows["Bonus"]["category_name"])
        self.assertEqual(rows["Kuryer"]["category_name"], "🚚 Kuryer (avtomatik)")
        self.assertEqual([r["name"] for r in await self.listed(f"?category={first['id']}")], ["Instagram"])
        self.assertEqual([r["name"] for r in await self.listed("?category=none")], ["Bonus"])
        self.assertEqual([r["id"] for r in await self.listed("?category=auto:kuryer")], [327])
        response = await self.client.get("/admin/api/expenses?category=drop%20table")
        self.assertEqual(response.status, 400)

        response = await self.client.get("/admin/api/expenses/by-category?period=all")
        totals = {t["name"]: (t["total"], t["count"]) for t in (await response.json())["totals"]}
        self.assertEqual(totals["Reklama"], (300000, 1))
        self.assertEqual(totals["Kategoriyasiz"], (1250000, 1))
        self.assertEqual(totals["🚚 Kuryer (avtomatik)"], (25000, 1))
        self.assertEqual(totals["🎁 Sovg'a (avtomatik)"], (5000, 1))
        self.assertEqual(totals["🎁 Aksiya bonusi (avtomatik)"], (5000, 1))

    async def test_editing_an_expense_changes_its_category(self):
        cid = (await self.add_category("Ijara"))["id"]
        response = await self.client.post("/admin/api/expenses/325",
                                          json={"name": "Bonus", "amount": 1250000, "category_id": cid})
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(next(r for r in await self.listed() if r["id"] == 325)["category_id"], cid)
        response = await self.client.post("/admin/api/expenses/325",
                                          json={"name": "Bonus", "amount": 1250000, "category_id": None})
        self.assertEqual(response.status, 200, await response.text())
        self.assertIsNone(next(r for r in await self.listed() if r["id"] == 325)["category_id"])

    async def test_unknown_or_bad_category_is_refused_without_writing(self):
        for cat in (999, -1, True, "abc"):
            with self.subTest(cat=cat):
                response = await self.client.post("/admin/api/expenses",
                                                  json={"name": "X", "amount": 1000, "category_id": cat})
                self.assertEqual(response.status, 400, await response.text())
        self.assertEqual(len(await self.listed()), 4)

    async def test_rename_and_delete(self):
        a = (await self.add_category("Reklama"))["id"]
        b = (await self.add_category("Ijara"))["id"]
        response = await self.client.post(f"/admin/api/expense-categories/{a}", json={"name": "ijara"})
        self.assertEqual(response.status, 409)                     # the name is taken
        response = await self.client.post(f"/admin/api/expense-categories/{a}", json={"name": "Marketing"})
        self.assertEqual(response.status, 200, await response.text())
        await self.client.post("/admin/api/expenses", json={"name": "Ofis", "amount": 5000000, "category_id": b})
        response = await self.client.post(f"/admin/api/expense-categories/{b}/delete")
        self.assertEqual(response.status, 200, await response.text())
        ofis = next(r for r in await self.listed() if r["name"] == "Ofis")
        self.assertIsNone(ofis["category_id"])                     # the expense stays, uncategorised
        self.assertEqual(ofis["amount"], 5000000)
        for path in (f"/admin/api/expense-categories/{b}", f"/admin/api/expense-categories/{b}/delete"):
            response = await self.client.post(path, json={"name": "Yangi"})
            self.assertEqual(response.status, 404)
        for bad in ("", "   ", "x" * 61, 5):
            response = await self.client.post("/admin/api/expense-categories", json={"name": bad})
            self.assertEqual(response.status, 400)

    async def test_category_endpoints_need_the_admin_session(self):
        self.client.session.cookie_jar.clear()
        for path in ("/admin/api/expense-categories", "/admin/api/expense-categories/1",
                     "/admin/api/expense-categories/1/delete"):
            response = await self.client.post(path, json={"name": "X"})
            self.assertEqual(response.status, 401)
        for path in ("/admin/api/expense-categories", "/admin/api/expenses/by-category"):
            response = await self.client.get(path)
            self.assertEqual(response.status, 401)


if __name__ == "__main__":
    unittest.main()
