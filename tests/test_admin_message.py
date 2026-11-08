"""POST /admin/api/admin-message — botdan adminlarga (va bir nechta ID'ga)
xabar (2026-11-05). Haqiqiy xabar yuborilmaydi: bot mock."""
import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("ADMIN_WEB_PASSWORD", "test")

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

import admin_web


class SplitTest(unittest.TestCase):
    def test_short_text_is_one_part(self):
        self.assertEqual(admin_web.split_admin_message("salom\n\ndunyo"), ["salom\n\ndunyo"])

    def test_long_text_is_cut_at_blank_lines_and_nothing_is_lost(self):
        blocks = [f"Bo'lim {i}\n" + ("x" * 900) for i in range(10)]
        parts = admin_web.split_admin_message("\n\n".join(blocks), limit=2000)
        self.assertTrue(all(len(p) <= 2000 for p in parts))
        self.assertEqual("\n\n".join(parts), "\n\n".join(blocks))
        self.assertTrue(all(p.startswith("Bo'lim") for p in parts))

    def test_one_huge_block_is_cut_too(self):
        parts = admin_web.split_admin_message("y" * 5000, limit=2000)
        self.assertEqual([len(p) for p in parts], [2000, 2000, 1000])


class EndpointTest(unittest.TestCase):
    def call(self, body, authed=True, send=None):
        app = web.Application()
        bot = MagicMock()
        bot.send_message = send or AsyncMock()
        app["bot"] = bot
        req = make_mocked_request("POST", "/admin/api/admin-message", app=app)
        req.json = AsyncMock(return_value=body)
        with patch.object(admin_web, "_authed", return_value=authed), \
             patch.object(admin_web, "ADMIN_IDS", [111, 222]):
            resp = asyncio.run(admin_web.api_admin_message(req))
        return resp.status, (json.loads(resp.body) if resp.body else {}), bot.send_message

    def test_closed_without_the_admin_session(self):
        status, _, send = self.call({"text": "x"}, authed=False)
        self.assertEqual(status, 401)
        send.assert_not_awaited()

    def test_every_admin_and_the_extra_id_once(self):
        status, d, send = self.call({"text": "<b>Hisobot</b>", "user_ids": [333, 111]})
        self.assertEqual(status, 200)
        self.assertEqual([c.args[0] for c in send.await_args_list], [111, 222, 333])
        self.assertEqual((d["sent"], d["failed"], d["extra_reached"], d["parts"]), (3, [], [333, 111], 1))
        self.assertEqual(send.await_args_list[0].kwargs["parse_mode"], "HTML")

    def test_bad_html_goes_as_plain_text(self):
        calls = []

        async def send(chat_id, text, **kw):
            calls.append(kw.get("parse_mode"))
            if kw.get("parse_mode") == "HTML":
                raise Exception("Bad Request: can't parse entities")
        status, d, _ = self.call({"text": "<b>oops"}, send=AsyncMock(side_effect=send))
        self.assertEqual(d["sent"], 2)
        self.assertEqual(calls, ["HTML", None, "HTML", None])

    def test_someone_who_never_started_the_bot_is_reported(self):
        async def send(chat_id, text, **kw):
            if chat_id == 333:
                raise Exception("Forbidden: bot can't initiate conversation with a user")
        status, d, _ = self.call({"text": "x", "user_ids": [333]}, send=AsyncMock(side_effect=send))
        self.assertEqual((d["sent"], d["failed"], d["extra_reached"]), (2, [333], []))

    def test_only_the_listed_people(self):
        # A pay calculation for two people must not reach every admin.
        status, d, send = self.call({"text": "KPI", "user_ids": [222, 444], "only": True})
        self.assertEqual(status, 200)
        self.assertEqual([c.args[0] for c in send.await_args_list], [222, 444])
        self.assertEqual((d["sent"], d["extra_reached"]), (2, [222, 444]))

    def test_only_needs_ids_and_must_be_a_real_true(self):
        self.assertEqual(self.call({"text": "x", "only": True})[0], 400)
        _, _, send = self.call({"text": "x", "user_ids": [444], "only": "yes"})
        self.assertEqual([c.args[0] for c in send.await_args_list], [111, 222, 444])

    def test_bad_requests(self):
        self.assertEqual(self.call({"text": "  "})[0], 400)
        self.assertEqual(self.call({"text": "x", "user_ids": ["abc"]})[0], 400)
        self.assertEqual(self.call({"text": "x", "user_ids": list(range(11))})[0], 400)
        self.assertEqual(self.call({"text": "x" * 20001})[0], 400)

    def test_registered_as_post_only(self):
        app = web.Application()
        admin_web.setup_admin_routes(app)
        methods = {r.method for r in app.router.routes() if r.resource.canonical == "/admin/api/admin-message"}
        self.assertEqual(methods, {"POST"})


if __name__ == "__main__":
    unittest.main()
