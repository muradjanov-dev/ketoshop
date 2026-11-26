"""Ulgurji (B2B) buyurtma darhol «yetkazildi» emas — boshqalari kabi holatlardan o'tadi
(egasi, 2026-11-26). Bazaga va Telegram'ga ulanmaydi."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database


class Conn:
    def __init__(self):
        self.sql = []

    async def fetchval(self, sql, *args):
        self.sql.append(sql)
        return 77

    async def execute(self, sql, *args):
        self.sql.append(sql)

    def transaction(self):
        class T:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False
        return T()


class Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class C:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return C()


class CreateTest(unittest.TestCase):
    def run_insert(self, coro_fn):
        conn = Conn()
        with patch.object(database, "pool", Pool(conn)), \
             patch.object(database, "_snapshot_order_costs", AsyncMock(side_effect=lambda c, items: items)), \
             patch.object(database, "_touch_b2b_customer", AsyncMock()):
            self.assertEqual(asyncio.run(coro_fn()), 77)
        return next(s for s in conn.sql if "INSERT INTO orders" in s)

    def test_b2b_order_starts_confirmed(self):
        sql = self.run_insert(lambda: database.add_b2b_order(1, "Firma", [{"name": "x", "quantity": 1, "price": 10}], 10))
        self.assertIn("'confirmed', 'b2b'", sql)
        self.assertNotIn("delivered_at", sql)
        self.assertNotIn("shipped_at", sql)

    def test_b2b_eritritol_starts_confirmed(self):
        sql = self.run_insert(lambda: database.add_b2b_eritritol_order(1, "Manzil", "+998", 5, 500000))
        self.assertIn("'confirmed', 'b2b'", sql)
        self.assertNotIn("delivered_at", sql)


class NoBuyerMessageTest(unittest.TestCase):
    def test_status_change_does_not_message_the_admin_who_keyed_it(self):
        from handlers import seller
        src = open(seller.__file__, encoding="utf-8").read()
        self.assertIn('if order and (order.get("source") or "bot") not in ("manual", "b2b"):', src)


if __name__ == "__main__":
    unittest.main()
