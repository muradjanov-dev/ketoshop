"""Faollik hisoboti (egasi, 2026-10-18): saytdagi harakatlar qanday
nomlanadi, qachon yoziladi, va /admin/api/activity parolsiz yopiq. Bazaga
ulanmaydi — yozuv ham, hisobot SQL'i ham mock orqali."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("ADMIN_WEB_PASSWORD", "test")

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

import activity
import admin_web
import webapp_server


class SiteActionTest(unittest.TestCase):
    def test_buyer_choices_are_named(self):
        for method, path, label in (
            ("GET", "/api/categories", "Saytni ochdi"),
            ("GET", "/api/product/42", "Mahsulot sahifasi"),
            ("GET", "/api/set/7", "To'plam sahifasi"),
            ("POST", "/api/product/42/reviews", "Sharh yozish"),
            ("GET", "/api/search", "Qidiruv"),
            ("POST", "/api/cart/add", "Savatga qo'shish"),
            ("POST", "/api/cart/update", "Savatda +/-"),
            ("POST", "/api/cart/remove", "Savatdan o'chirish"),
            ("POST", "/api/cart/clear", "Savatni tozalash"),
            ("POST", "/api/checkout", "Buyurtma berdi"),
            ("POST", "/api/checkout/cheque", "Chek yubordi"),
            ("POST", "/api/orders/15/cheque", "Chek yubordi"),
            ("POST", "/api/checkout/pay-in-chat", "Chatda to'lash"),
            ("GET", "/api/orders", "Buyurtmalarim"),
            ("POST", "/api/orders/15/cancel", "Buyurtmani bekor qilish"),
            ("GET", "/api/recipes/keto-pitsa", "Retsept ochildi"),
            ("POST", "/api/recipes/keto-pitsa/cart", "Retseptdan savatga"),
            ("POST", "/api/restock-wait", "Kelganda xabar bering"),
            ("POST", "/api/site-feedback", "Saytga baho"),
            ("POST", "/api/lang", "Til tanlash"),
        ):
            self.assertEqual(activity.site_action(method, path), label, (method, path))

    def test_start_up_preloads_and_lookups_are_not_counted(self):
        for method, path in (
            ("GET", "/api/products"), ("GET", "/api/top"), ("GET", "/api/leaderboard"),
            ("GET", "/api/promo"), ("GET", "/api/cart"), ("GET", "/api/keto/status"),
            ("GET", "/api/lang"), ("GET", "/api/recipes"), ("GET", "/api/pickup-config"),
            ("GET", "/api/product/42/reviews"), ("GET", "/api/geocode"), ("GET", "/api/bot-access"),
            ("POST", "/api/categories"), ("GET", "/api/checkout"),
        ):
            self.assertIsNone(activity.site_action(method, path), (method, path))


class MiddlewareTest(unittest.TestCase):
    def call(self, method, path, status, log_side_effect=None):
        app = web.Application()
        app["bot_token"] = "1:test"
        request = make_mocked_request(method, path, headers={"Authorization": "tma x"}, app=app)

        async def handler(_request):
            return web.json_response({}, status=status)

        with patch.object(webapp_server, "_validate_init_data", return_value={"user": {"id": 77}}), \
             patch.object(webapp_server, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(webapp_server, "bot_can_write", AsyncMock(return_value=True)), \
             patch.object(activity, "log_site", MagicMock(side_effect=log_side_effect)) as log:
            response = asyncio.run(webapp_server.auth_middleware(request, handler))
        return response, log

    def test_logged_after_a_successful_request(self):
        response, log = self.call("POST", "/api/cart/add", 200)
        self.assertEqual(response.status, 200)
        log.assert_called_once_with(77, "Savatga qo'shish")

    def test_not_logged_when_the_request_failed_or_is_a_preload(self):
        _, log = self.call("POST", "/api/checkout", 400)
        log.assert_not_called()
        _, log = self.call("GET", "/api/products", 200)
        log.assert_not_called()

    def test_a_logging_failure_never_breaks_the_response(self):
        response, log = self.call("GET", "/api/categories", 200, log_side_effect=RuntimeError("db down"))
        self.assertEqual(response.status, 200)
        log.assert_called_once()


class AdminEndpointTest(unittest.TestCase):
    def test_closed_without_the_admin_session(self):
        request = make_mocked_request("GET", "/admin/api/activity")
        with patch.object(admin_web.database, "get_activity_report", AsyncMock()) as report:
            response = asyncio.run(admin_web.api_activity(request))
        self.assertEqual(response.status, 401)
        report.assert_not_awaited()

    def test_registered_as_get_only(self):
        app = web.Application()
        admin_web.setup_admin_routes(app)
        methods = {r.method for r in app.router.routes() if r.resource.canonical == "/admin/api/activity"}
        self.assertEqual(methods - {"HEAD"}, {"GET"})


if __name__ == "__main__":
    unittest.main()
