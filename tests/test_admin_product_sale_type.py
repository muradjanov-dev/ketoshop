"""Admin website sale type reaches the same product flag used by the bot."""
import contextlib
import os
import re
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("ADMIN_WEB_PASSWORD", "test-password")

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import admin_web
import database
from locales import CATEGORIES


class ProductConnection:
    """Only the Postgres boundary is replaced; handlers and queries run for real."""
    def __init__(self):
        self.products = {}

    async def execute(self, sql, *args):
        if sql.startswith("INSERT INTO users"):
            return "INSERT 0 1"
        match = re.match(r"UPDATE products SET (\w+) = \$1 WHERE id = \$2", sql)
        if match:
            self.products[args[1]][match[1]] = args[0]
            return "UPDATE 1"
        raise AssertionError(f"Unexpected query: {sql}")

    def visible_products(self, sql):
        rows = list(self.products.values())
        if "b2b_only IS NOT TRUE" in sql:
            rows = [p for p in rows if not p["b2b_only"]]
        return rows

    async def fetchval(self, sql, *args):
        match = re.search(r"INSERT INTO products\s*\((.*?)\)\s*VALUES", sql, re.S)
        if match:
            fields = [field.strip() for field in match[1].split(",")]
            assert len(fields) == len(args)
            pid = len(self.products) + 1
            self.products[pid] = {"id": pid, "b2b_only": False, "is_active": 1,
                                  **dict(zip(fields, args))}
            return pid
        if "SELECT COUNT(*) FROM products" in sql:
            return len(self.visible_products(sql))
        raise AssertionError(f"Unexpected query: {sql}")

    async def fetchrow(self, sql, *args):
        if "WHERE p.id = $1" in sql:
            return self.products.get(args[0])
        raise AssertionError(f"Unexpected query: {sql}")

    async def fetch(self, sql, *args):
        if "FROM products" in sql:
            return self.visible_products(sql)
        raise AssertionError(f"Unexpected query: {sql}")


class ProductPool:
    def __init__(self, conn):
        self.conn = conn

    @contextlib.asynccontextmanager
    async def acquire(self):
        yield self.conn


class AdminProductSaleTypeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = ProductConnection()
        self.pool_patch = patch.object(database, "pool", ProductPool(self.conn))
        self.pool_patch.start()
        self.addCleanup(self.pool_patch.stop)
        self.category = next(iter(CATEGORIES))
        app = web.Application()
        app.router.add_post("/products", admin_web.api_products_create)
        app.router.add_post("/products/{id}", admin_web.api_products_update)
        app.router.add_get("/products", admin_web.api_products_list)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.client.session.cookie_jar.update_cookies({admin_web.SESSION_COOKIE: admin_web._make_session()})

    async def create(self, **extra):
        response = await self.client.post("/products", json={
            "name": "Bodom uni 1kg", "price": 180000, "category": self.category,
            "quantity": 10, "b2b_price": 150000, **extra,
        })
        self.assertEqual(response.status, 200, await response.text())
        return (await response.json())["id"]

    async def test_creation_persists_both_sale_types(self):
        for flag in (True, False):
            with self.subTest(flag=flag):
                pid = await self.create(b2b_only=flag)
                product = await database.get_product(pid)
                self.assertIs(product["b2b_only"], flag)
                self.assertEqual(product["b2b_price"], 150000)

    async def test_legacy_creation_defaults_to_general_store(self):
        pid = await self.create()
        self.assertIs(self.conn.products[pid]["b2b_only"], False)

    async def test_edit_changes_visibility_without_changing_wholesale_price(self):
        pid = await self.create()
        for flag, expected_count in ((True, 0), (False, 1)):
            with self.subTest(flag=flag):
                response = await self.client.post(f"/products/{pid}", json={"b2b_only": flag})
                self.assertEqual(response.status, 200, await response.text())
                retail, total = await database.get_products_by_category(self.category)
                self.assertEqual(total, expected_count)
                self.assertEqual(len(retail), expected_count)
                b2b, b2b_total = await database.get_products_by_category(self.category, include_b2b_only=True)
                self.assertEqual(b2b_total, 1)
                self.assertIs(b2b[0]["b2b_only"], flag)
                self.assertEqual(b2b[0]["b2b_price"], 150000)
                listed = await self.client.get("/products")
                self.assertIs((await listed.json())["products"][0]["b2b_only"], flag)

    async def test_unrelated_edit_preserves_existing_sale_type(self):
        # Seed independently so this test also catches a default-false update.
        pid = await self.create()
        self.conn.products[pid]["b2b_only"] = True
        response = await self.client.post(f"/products/{pid}", json={"quantity": 12})
        self.assertEqual(response.status, 200)
        self.assertIs(self.conn.products[pid]["b2b_only"], True)
        self.assertEqual(self.conn.products[pid]["quantity"], 12)

    async def test_non_boolean_sale_type_is_rejected_before_creation(self):
        for invalid in ("false", "true", 0, 1, None, [], {}):
            with self.subTest(invalid=invalid):
                response = await self.client.post("/products", json={
                    "name": "Un", "price": 100, "category": self.category,
                    "b2b_only": invalid,
                })
                self.assertEqual(response.status, 400)
                self.assertEqual(self.conn.products, {})

    async def test_non_boolean_sale_type_does_not_apply_other_edits(self):
        pid = await self.create()
        for invalid in ("false", 0, None):
            with self.subTest(invalid=invalid):
                response = await self.client.post(f"/products/{pid}", json={
                    "b2b_only": invalid, "quantity": 999,
                })
                self.assertEqual(response.status, 400)
                self.assertEqual(self.conn.products[pid]["quantity"], 10)

    async def test_sale_type_edit_requires_admin_session(self):
        pid = await self.create()
        self.client.session.cookie_jar.clear()
        response = await self.client.post(f"/products/{pid}", json={"b2b_only": True})
        self.assertEqual(response.status, 401)
        self.assertIs(self.conn.products[pid]["b2b_only"], False)
