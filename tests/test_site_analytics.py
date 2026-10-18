"""Sayt analitikasi (egasi, 2026-10-18): Mini App kuzatuvi, /api/track va
admin hisobotlari. Bazaga ulanmaydi va hech narsa yubormaydi."""
import asyncio
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("ADMIN_WEB_PASSWORD", "test")

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

import activity
import admin_web
import webapp_server

ROOT = Path(__file__).resolve().parent.parent


class CleanBatchTest(unittest.TestCase):
    def test_keeps_known_kinds_and_trims(self):
        sid, rows = webapp_server.clean_track_batch({"sid": "abc123xyz", "ev": [
            {"k": "view", "s": "product", "r": 42, "f": "home:sweeteners"},
            {"k": "time", "s": "product", "r": "42", "ms": 6000.4},
            {"k": "search", "s": "catalog", "r": "x" * 200, "ms": 0},
            {"k": "hack", "s": "home"},
            {"k": "time", "s": "home", "ms": -5},
            {"k": "time", "s": "home", "ms": 10 ** 9},
            {"k": "scroll", "s": {"a": 1}, "ms": True},
            "nonsense",
        ]})
        self.assertEqual(sid, "abc123xyz")
        self.assertEqual(rows[0], ("view", "product", "42", "home:sweeteners", None))
        self.assertEqual(rows[1], ("time", "product", "42", None, 6000))
        self.assertEqual(len(rows[2][2]), 80)
        self.assertEqual(rows[2][4], 0)
        self.assertEqual([r[0] for r in rows], ["view", "time", "search", "time", "time", "scroll"])
        self.assertIsNone(rows[3][4])                       # negative ms dropped
        self.assertIsNone(rows[4][4])                       # absurd ms dropped
        self.assertEqual(rows[5][1:], (None, None, None, None))

    def test_bad_batches(self):
        for body in (None, [], {"sid": "x", "ev": []}, {"sid": "abc/../1", "ev": []},
                     {"sid": "abc123", "ev": "no"}, {"ev": []}):
            self.assertIsNone(webapp_server.clean_track_batch(body), body)

    def test_at_most_sixty_rows(self):
        _, rows = webapp_server.clean_track_batch({"sid": "abc123", "ev": [{"k": "row", "r": "x"}] * 500})
        self.assertEqual(len(rows), 60)


class TrackEndpointTest(unittest.TestCase):
    def post(self, body, insert=None):
        async def go():
            req = make_mocked_request("POST", "/api/track")
            req["user_id"] = 77
            req.json = AsyncMock(return_value=body) if not isinstance(body, Exception) else AsyncMock(side_effect=body)
            return await webapp_server.api_track(req)
        import database
        with patch.object(database, "insert_site_events", insert or AsyncMock()) as ins:
            resp = asyncio.run(go())
        return resp, ins

    def test_stores_rows_for_the_signed_in_buyer(self):
        resp, ins = self.post({"sid": "abc123", "ev": [{"k": "view", "s": "home"}]})
        self.assertEqual(resp.status, 200)
        ins.assert_awaited_once_with(77, "abc123", [("view", "home", None, None, None)])

    def test_bad_json_is_400_and_a_db_error_still_200(self):
        resp, ins = self.post(ValueError("bad"))
        self.assertEqual(resp.status, 400)
        ins.assert_not_awaited()
        resp, _ = self.post({"sid": "abc123", "ev": [{"k": "view", "s": "home"}]},
                            insert=AsyncMock(side_effect=RuntimeError("db down")))
        self.assertEqual(resp.status, 200)

    def test_route_and_not_counted_as_a_buyer_action(self):
        app = webapp_server.create_webapp(object())  # type: ignore[arg-type]
        methods = {r.method for r in app.router.routes() if r.resource.canonical == "/api/track"}
        self.assertEqual(methods, {"POST"})
        self.assertIsNone(activity.site_action("POST", "/api/track"))


class AdminEndpointsTest(unittest.TestCase):
    def test_closed_without_the_admin_session(self):
        for handler, path in ((admin_web.api_site_analytics, "/admin/api/site-analytics"),
                              (admin_web.api_site_user, "/admin/api/site-analytics/user/5")):
            req = make_mocked_request("GET", path, match_info={"user_id": "5"})
            with patch.object(admin_web.database, "get_site_analytics", AsyncMock()) as a, \
                 patch.object(admin_web.database, "get_site_user", AsyncMock()) as u:
                resp = asyncio.run(handler(req))
            self.assertEqual(resp.status, 401)
            a.assert_not_awaited()
            u.assert_not_awaited()

    def test_registered_as_get_only(self):
        app = web.Application()
        admin_web.setup_admin_routes(app)
        found = {}
        for r in app.router.routes():
            found.setdefault(r.resource.canonical, set()).add(r.method)
        self.assertEqual(found["/admin/api/site-analytics"] - {"HEAD"}, {"GET"})
        self.assertEqual(found["/admin/api/site-analytics/user/{user_id}"] - {"HEAD"}, {"GET"})


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TrackerScriptTest(unittest.TestCase):
    """The tracker in webapp/index.html, run in node against a fake DOM
    (tests/site_tracker_check.js)."""

    @classmethod
    def setUpClass(cls):
        out = subprocess.run(["node", str(ROOT / "tests" / "site_tracker_check.js")],
                             capture_output=True, text=True, check=True, cwd=ROOT).stdout
        cls.batches = json.loads(out)
        cls.events = [e for b in cls.batches for e in b["body"]["ev"]]

    def find(self, **kw):
        return [e for e in self.events if all(e.get(k) == v for k, v in kw.items())]

    def test_every_batch_is_one_session_sent_with_keepalive(self):
        self.assertTrue(self.batches)
        self.assertEqual(len({b["body"]["sid"] for b in self.batches}), 1)
        self.assertTrue(all(b["url"] == "/api/track" and b["keepalive"] for b in self.batches))

    def test_screens_time_and_source(self):
        self.assertEqual(self.events[0], {"k": "open", "r": "direct", "f": "android"})
        self.assertEqual(self.find(k="time", s="home")[0]["ms"], 4000)
        self.assertEqual(self.find(k="view", s="product")[0], {"k": "view", "s": "product", "r": "42", "f": "catalog:sweeteners"})
        self.assertEqual(self.find(k="time", s="product")[0]["ms"], 6000)
        self.assertEqual(self.find(k="cart_add")[0]["f"], "catalog:sweeteners")
        self.assertEqual(self.find(k="view", s="catalog", r="sweeteners", f="back")[0]["k"], "view")

    def test_only_visible_time_counts(self):
        back = [e["ms"] for e in self.find(k="time", s="catalog", r="sweeteners")]
        self.assertEqual(back, [1000, 3000, 2000])           # the hidden minute is not in it

    def test_scroll_depth_once_per_visit(self):
        self.assertEqual(self.find(k="scroll", s="product")[0]["ms"], 75)
        self.assertEqual(len(self.find(k="scroll", s="catalog", r="sweeteners")), 2)   # before the product, and after


if __name__ == "__main__":
    unittest.main()
