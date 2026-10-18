"""«💬 Izohlar» bo'limi (egasi, 2026-10-18): sayt bahosi endi bazaga ham
yoziladi, /admin/api/feedback parolsiz yopiq. Bazaga ulanmaydi va hech kimga
xabar yubormaydi."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("ADMIN_WEB_PASSWORD", "test")

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

import admin_web
import database
import site_feedback
import webapp_server


class SiteFeedbackStoredTest(unittest.TestCase):
    def send(self, body, save=None):
        async def go():
            req = make_mocked_request("POST", "/api/site-feedback", app={"bot": MagicMock()})
            req["user_id"] = 77
            req["user_lang"] = "ru"
            req["telegram_user"] = {"id": 77, "first_name": "Aziza"}
            req.json = AsyncMock(return_value=body)
            return await webapp_server.api_site_feedback(req)
        with patch.object(database, "save_site_feedback", save or AsyncMock()) as saved, \
             patch.object(site_feedback, "allow", return_value=True), \
             patch.object(site_feedback, "notify_admins", AsyncMock(return_value=2)) as notify:
            resp = asyncio.run(go())
        return resp, saved, notify

    def test_saved_and_still_sent_to_admins(self):
        resp, saved, notify = self.send({"rating": 4, "comment": "Qulay, lekin qidiruv sekin"})
        self.assertEqual(resp.status, 200)
        saved.assert_awaited_once_with(77, 4, "Qulay, lekin qidiruv sekin", "ru")
        notify.assert_awaited_once()

    def test_a_storage_failure_never_loses_the_admin_message(self):
        resp, _, notify = self.send({"rating": 2, "comment": "sekin"}, save=AsyncMock(side_effect=RuntimeError("db down")))
        self.assertEqual(resp.status, 200)
        notify.assert_awaited_once()


class FeedbackEndpointTest(unittest.TestCase):
    def test_closed_without_the_admin_session(self):
        with patch.object(admin_web.database, "get_feedback_overview", AsyncMock()) as overview:
            resp = asyncio.run(admin_web.api_feedback(make_mocked_request("GET", "/admin/api/feedback")))
        self.assertEqual(resp.status, 401)
        overview.assert_not_awaited()

    def test_registered_as_get_only(self):
        app = web.Application()
        admin_web.setup_admin_routes(app)
        methods = {r.method for r in app.router.routes() if r.resource.canonical == "/admin/api/feedback"}
        self.assertEqual(methods - {"HEAD"}, {"GET"})


if __name__ == "__main__":
    unittest.main()
