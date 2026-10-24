"""«Saytimiz sizga qulaymi?» endi qayta-qayta so'ramaydi (egasi, 2026-10-24:
"nega hadeb so'rayveryapti?"). Bazaga ulanmaydi, hech kimga xabar ketmaydi."""
import asyncio
import json
import os
import shutil
import subprocess
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from aiohttp.test_utils import make_mocked_request

import database
import site_feedback
import webapp_server

ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 10, 24, 12, 0)


class AskDueTest(unittest.TestCase):
    def test_rules(self):
        due = site_feedback.ask_due
        self.assertTrue(due(0, None, False, False, NOW))                              # never asked
        self.assertFalse(due(1, NOW - timedelta(days=3), False, False, NOW))          # asked 3 days ago
        self.assertTrue(due(1, NOW - timedelta(days=30), False, False, NOW))          # a month later, once more
        self.assertFalse(due(2, NOW - timedelta(days=90), False, False, NOW))         # twice is the most
        self.assertFalse(due(0, None, True, False, NOW))                              # answered — never again
        self.assertFalse(due(0, None, False, True, NOW))                              # admin / shop account


class EndpointsTest(unittest.TestCase):
    def due(self, user_id, state=None, error=None):
        async def go():
            req = make_mocked_request("GET", "/api/site-feedback/due")
            req["user_id"] = user_id
            return json.loads((await webapp_server.api_site_feedback_due(req)).body)["due"]
        get = AsyncMock(side_effect=error) if error else AsyncMock(return_value=state)
        with patch.object(database, "get_site_feedback_ask", get):
            return asyncio.run(go())

    def test_due(self):
        fresh = {"asks": 0, "last_asked_at": None, "answered": False}
        self.assertTrue(self.due(77, fresh))
        self.assertFalse(self.due(77, dict(fresh, answered=True)))
        self.assertFalse(self.due(77, dict(fresh, asks=1, last_asked_at=datetime.utcnow())))
        admin = next(iter(webapp_server.ADMIN_IDS), None) or next(iter(webapp_server.LEADERBOARD_EXCLUDED_USER_IDS))
        self.assertFalse(self.due(admin, fresh))
        self.assertFalse(self.due(77, error=RuntimeError("db down")))       # trouble → don't ask

    def test_shown_is_recorded(self):
        async def go():
            req = make_mocked_request("POST", "/api/site-feedback/shown")
            req["user_id"] = 77
            return await webapp_server.api_site_feedback_shown(req)
        with patch.object(database, "mark_site_feedback_asked", AsyncMock()) as mark:
            resp = asyncio.run(go())
        self.assertEqual(resp.status, 200)
        mark.assert_awaited_once_with(77)

    def test_routes(self):
        app = webapp_server.create_webapp(object())  # type: ignore[arg-type]
        found = {}
        for r in app.router.routes():
            found.setdefault(r.resource.canonical, set()).add(r.method)
        self.assertEqual(found["/api/site-feedback/due"] - {"HEAD"}, {"GET"})
        self.assertEqual(found["/api/site-feedback/shown"], {"POST"})


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class MiniAppFlowTest(unittest.TestCase):
    def run_flow(self, **scenario):
        out = subprocess.run(["node", str(ROOT / "tests" / "site_feedback_flow.js"), json.dumps(scenario)],
                             capture_output=True, text=True, check=True, cwd=ROOT).stdout
        return json.loads(out)

    def test_server_says_no(self):
        r = self.run_flow(due=False)
        self.assertEqual([c for c in r["calls"] if c[0] == "api"], [["api", "/api/site-feedback/due", "GET"]])
        self.assertNotIn(["open", "show"], r["calls"])

    def test_server_says_yes_and_the_ask_is_remembered_at_once(self):
        r = self.run_flow(due=True)
        self.assertIn(["open", "show"], r["calls"])
        self.assertIn(["api", "/api/site-feedback/shown", "POST"], r["calls"])
        self.assertIn("snoozed", r["stored"])                # even if the app is just closed

    def test_a_recent_ask_on_this_phone_skips_the_server(self):
        import time
        r = self.run_flow(due=True, stored={"snoozed": int(time.time() * 1000) - 5 * 864e5})
        self.assertEqual(r["calls"], [])


if __name__ == "__main__":
    unittest.main()
