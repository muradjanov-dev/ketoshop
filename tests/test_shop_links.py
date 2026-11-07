"""Sayt havolalari — t.me/<bot>/shop?startapp=<kod> (owner, 2026-11-07).

The SQL itself was run against a throwaway Postgres while writing this (CI has
no database); these tests pin the parts that don't need one: the code rules,
the link, and that the code is read from the SIGNED initData on launch.
"""
import asyncio
import hashlib
import hmac
import json
import os
import time
import unittest
from unittest.mock import AsyncMock, Mock, patch
from urllib.parse import urlencode

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
import keyboards
import shop_links
import webapp_server as ws

BUYER = 777000333


def run(coro):
    return asyncio.run(coro)


def signed_init_data(token: str, **fields) -> str:
    data = {"auth_date": str(int(time.time())), "user": json.dumps({"id": BUYER, "language_code": "uz"}),
            **fields}
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


class CodeTest(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(shop_links.slugify("Kepak"), "kepak")
        self.assertEqual(shop_links.slugify("Gluten 1-qism"), "gluten_1_qism")
        self.assertEqual(shop_links.slugify("  Yo'lda O'g'il  "), "yolda_ogil")
        self.assertEqual(shop_links.slugify("Кепак 2"), "kepak_2")
        self.assertEqual(shop_links.slugify("Şakar Çoy"), "shakar_choy")
        self.assertEqual(shop_links.slugify("!!!"), "")

    def test_owner_links(self):
        self.assertEqual(dict(shop_links.DEFAULTS), {"kepak": "Kepak", "gluten_1_qism": "Gluten 1-qism"})
        self.assertTrue(shop_links.link("kepak").endswith("/shop?startapp=kepak"))
        self.assertTrue(shop_links.link("kepak").startswith("https://t.me/"))
        for code, name in shop_links.DEFAULTS:
            self.assertEqual(shop_links.slugify(name), code)
            self.assertRegex(code, shop_links.CODE_RE)

    def test_codes_fit_telegram(self):
        code = shop_links.slugify("x" * 200)
        self.assertLessEqual(len(code), 64)
        self.assertRegex(code, shop_links.CODE_RE)

    def test_recipe_links_are_not_shop_links(self):
        for bad in ("recipe-bodom-noni", "", "Kepak", "-x", "a b"):
            self.assertIsNone(shop_links.CODE_RE.match(bad), bad)


class RecordTest(unittest.TestCase):
    def test_bad_code_never_touches_the_db(self):
        with patch.object(database, "pool", None):
            for bad in (None, "", "recipe-bodom", "a b"):
                self.assertFalse(run(shop_links.record_open(BUYER, bad, 1)))
            self.assertFalse(run(shop_links.record_open(None, "kepak", 1)))

    def test_db_trouble_never_breaks_the_shop(self):
        broken = Mock()
        broken.acquire.side_effect = RuntimeError("db down")
        with patch.object(database, "pool", broken), patch.object(shop_links, "_ready", False):
            self.assertFalse(run(shop_links.record_open(BUYER, "kepak", 1)))


class LaunchTest(unittest.TestCase):
    """auth_middleware → api_bot_access, with real initData signing."""

    def setUp(self):
        ws._bot_access.clear()

    def launch(self, init_data):
        store = {}
        req = Mock()
        req.path = ws.BOT_ACCESS_PATH
        req.headers = {"Authorization": "tma " + init_data}
        req.app = {"bot_token": "1:test", "bot": None}
        req.__setitem__ = lambda s, k, v: store.__setitem__(k, v)
        req.__getitem__ = lambda s, k: store[k]
        req.get = lambda k, d=None: store.get(k, d)
        record = AsyncMock(return_value=True)
        with patch.object(shop_links, "record_open", record), \
             patch.object(ws, "get_user_language", AsyncMock(return_value="uz")):
            resp = run(ws.auth_middleware(req, ws.api_bot_access))
        return resp, record

    def test_launch_through_a_link_is_recorded(self):
        init = signed_init_data("1:test", start_param="kepak")
        resp, record = self.launch(init)
        self.assertEqual(resp.status, 200)
        record.assert_awaited_once()
        user_id, code, auth = record.await_args.args
        self.assertEqual((user_id, code), (BUYER, "kepak"))
        self.assertTrue(str(auth).isdigit())

    def test_plain_launch_passes_no_code(self):
        resp, record = self.launch(signed_init_data("1:test"))
        self.assertEqual(resp.status, 200)
        self.assertEqual(record.await_args.args[1], "")

    def test_forged_code_is_refused(self):
        init = signed_init_data("1:test", start_param="kepak").replace("kepak", "gluten_1_qism")
        resp, record = self.launch(init)
        self.assertEqual(resp.status, 403)
        record.assert_not_awaited()


class BotTest(unittest.TestCase):
    def test_commands_published_for_admins(self):
        names = {c.command for c in keyboards.ADMIN_COMMANDS} if hasattr(keyboards, "ADMIN_COMMANDS") else None
        src = open(keyboards.__file__, encoding="utf-8").read()
        for cmd in ("sayt_havola", "sayt_havolalar"):
            self.assertIn(f'command="{cmd}"', src)
            if names is not None:
                self.assertIn(cmd, names)

    def test_make_link_reply(self):
        msg = Mock()
        msg.from_user.id = 1
        msg.text = "/sayt_havola Gluten 1-qism"
        msg.answer = AsyncMock()
        with patch.object(shop_links, "ADMIN_IDS", [1]), \
             patch.object(shop_links, "create", AsyncMock(return_value=("gluten_1_qism", "Gluten 1-qism", True))):
            run(shop_links.cmd_make(msg))
        text = msg.answer.await_args.args[0]
        self.assertIn("/shop?startapp=gluten_1_qism", text)
        self.assertIn("Gluten 1-qism", text)

    def test_non_admin_gets_nothing(self):
        msg = Mock()
        msg.from_user.id = 2
        msg.text = "/sayt_havola X"
        msg.answer = AsyncMock()
        with patch.object(shop_links, "ADMIN_IDS", [1]), \
             patch.object(shop_links, "create", AsyncMock()) as create:
            run(shop_links.cmd_make(msg))
        msg.answer.assert_not_awaited()
        create.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
