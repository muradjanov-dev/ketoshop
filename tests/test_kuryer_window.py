"""Kuryer paneli alohida oyna (/kuryer): faqat Kanban, Telegram orqali kirish.

* Kuryer API'si admin paroli YOKI admin/kuryerning Telegram initData'sini qabul
  qiladi; boshqa Telegram foydalanuvchisi — 403.
* Dashboard va boshqa API'lar Telegram orqali ochilmaydi (faqat parol).
* /kuryer sahifasi kuryer rejimida yuklanadi; botda "Buyurtmalar" va /courier
  ichida shu oynani ochadigan web_app tugmasi bor.
"""
import asyncio
import hashlib
import hmac
import json
import os
import time
import unittest
from unittest import mock
from urllib.parse import urlencode

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("ADMIN_WEB_PASSWORD", "test-password")

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import admin_web
import courier_board
import database
import keyboards

ADMIN, COURIER, STRANGER = 111, 222, 333


def init_data(user_id: int) -> str:
    fields = {"auth_date": str(int(time.time())),
              "user": json.dumps({"id": user_id, "first_name": "T"}, separators=(",", ":"))}
    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", admin_web.BOT_TOKEN.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


class KuryerWindowApiTest(unittest.TestCase):
    def _run(self, coro_fn):
        async def go():
            app = web.Application()
            admin_web.setup_admin_routes(app)
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                with mock.patch.object(admin_web, "ADMIN_IDS", [ADMIN]), \
                     mock.patch.object(database, "get_courier_ids", mock.AsyncMock(return_value=[COURIER])), \
                     mock.patch.object(courier_board, "board_snapshot",
                                       mock.AsyncMock(return_value={"columns": []})):
                    return await coro_fn(client)
            finally:
                await client.close()
        return asyncio.run(go())

    def test_courier_and_admin_can_open_board_by_telegram(self):
        async def check(client):
            out = []
            for uid in (COURIER, ADMIN, STRANGER):
                r = await client.get("/admin/api/courier/board",
                                     headers={"Authorization": "tma " + init_data(uid)})
                out.append(r.status)
            r = await client.get("/admin/api/courier/board")
            out.append(r.status)
            r = await client.get("/admin/api/courier/board",
                                 headers={"Authorization": "tma " + init_data(COURIER) + "x"})
            out.append(r.status)
            return out
        self.assertEqual(self._run(check), [200, 200, 403, 401, 401])

    def test_dashboard_stays_password_only(self):
        async def check(client):
            r = await client.get("/admin/api/dashboard",
                                 headers={"Authorization": "tma " + init_data(ADMIN)})
            return r.status
        self.assertEqual(self._run(check), 401)

    def test_password_session_still_works(self):
        async def check(client):
            cookie = {admin_web.SESSION_COOKIE: admin_web._make_session()}
            r = await client.get("/admin/api/courier/board", cookies=cookie)
            return r.status
        self.assertEqual(self._run(check), 200)

    def test_kuryer_page_boots_courier_mode(self):
        async def check(client):
            r = await client.get("/kuryer")
            return r.status, await r.text()
        status, html = self._run(check)
        self.assertEqual(status, 200)
        self.assertIn("window.KURYER_MODE=true", html)
        self.assertIn("telegram-web-app.js", html)
        self.assertIn("body.kuryer-mode .view:not(#view-courier){display:none!important}", html)


class KuryerButtonTest(unittest.TestCase):
    def test_orders_section_and_courier_panel_have_window_button(self):
        with mock.patch.object(keyboards, "WEBAPP_URL", "https://shop.example/"):
            kb = keyboards.admin_order_filter_keyboard("uz")
            first = kb.inline_keyboard[0][0]
            self.assertEqual(first.web_app.url, "https://shop.example/kuryer")
            from handlers.courier import get_courier_keyboard
            ckb = get_courier_keyboard("uz")
            self.assertEqual(ckb.inline_keyboard[0][0].web_app.url, "https://shop.example/kuryer")

    def test_no_button_without_webapp_url(self):
        with mock.patch.object(keyboards, "WEBAPP_URL", ""):
            kb = keyboards.admin_order_filter_keyboard("uz")
            self.assertTrue(all(b.web_app is None for row in kb.inline_keyboard for b in row))


if __name__ == "__main__":
    unittest.main()
