"""Kuryer paneli "Hammasi" — barcha yakunlangan buyurtmalar (2026-10-09).

* "Hammasi" yetkazilgan va bekor qilingan buyurtmalarning HAMMASINI oladi —
  avval eng yangi 400 tasi bilan cheklangan edi, 400 dan oshgach eskilari
  paneldan yo'qolib qoldi.
* "Faol" o'zgarmagan: faqat oxirgi soatlarda yetkazilganlar.
* Panel javobi gzip bilan siqiladi — u har necha soniyada qayta so'raladi.
"""
import asyncio
import os
import unittest
from contextlib import asynccontextmanager
from unittest import mock

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("ADMIN_WEB_PASSWORD", "test-password")

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import admin_web
import courier_board
import database


class _Conn:
    def __init__(self):
        self.sql, self.args = "", ()

    async def fetch(self, sql, *args):
        self.sql, self.args = sql, args
        return []


class _Pool:
    def __init__(self):
        self.conn = _Conn()

    def acquire(self):
        @asynccontextmanager
        async def cm():
            yield self.conn
        return cm()


class BoardOrdersQueryTest(unittest.TestCase):
    def _query(self, scope):
        pool = _Pool()
        with mock.patch.object(database, "pool", pool):
            asyncio.run(database.get_courier_board_orders(24, scope))
        return pool.conn

    def test_all_scope_has_no_cap(self):
        conn = self._query("all")
        self.assertNotIn("LIMIT", conn.sql.upper())
        self.assertEqual(conn.args[1], ["delivered", "cancelled"])
        self.assertEqual(len(conn.args), 2)

    def test_active_scope_still_windowed(self):
        conn = self._query("active")
        self.assertIn("hours", conn.sql)
        self.assertEqual(conn.args[1], ["delivered"])
        self.assertEqual(conn.args[2], "24")


class BoardCompressionTest(unittest.TestCase):
    def test_board_response_is_gzipped(self):
        cards = [{"id": i, "customer_name": "Mijoz", "address": "Toshkent " * 20}
                 for i in range(300)]

        async def go():
            app = web.Application()
            admin_web.setup_admin_routes(app)
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                # config is imported once per run, by whichever test module
                # came first, so pin the password instead of trusting the env.
                with mock.patch.object(admin_web, "ADMIN_WEB_PASSWORD", "test-password"), \
                     mock.patch.object(courier_board, "board_snapshot",
                                       mock.AsyncMock(return_value={"columns": [{"cards": cards}]})):
                    r = await client.post("/admin/api/login", json={"password": "test-password"})
                    self.assertEqual(r.status, 200)
                    r = await client.get("/admin/api/courier/board?scope=all",
                                         headers={"Accept-Encoding": "gzip"})
                    body = await r.json()
                    return r.status, r.headers.get("Content-Encoding"), body
            finally:
                await client.close()

        status, encoding, body = asyncio.run(go())
        self.assertEqual(status, 200)
        self.assertEqual(encoding, "gzip")
        self.assertEqual(len(body["columns"][0]["cards"]), 300)


if __name__ == "__main__":
    unittest.main()
