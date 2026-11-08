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
from unittest.mock import AsyncMock, MagicMock, Mock, patch
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


class NewUserNoticeTest(unittest.TestCase):
    """«Yangi foydalanuvchi qo'shildi» names the shop link (owner, 2026-11-08)."""

    def notice(self, **kw):
        import referral_contest
        bot = Mock()
        bot.send_message = AsyncMock()
        with patch.object(referral_contest, "ADMIN_IDS", [1]):
            run(referral_contest.notify_admins_new_user(bot, BUYER, "ali", "Ali", None, **kw))
        return bot.send_message.await_args.args[1]

    def test_link_is_the_source_when_nothing_else(self):
        text = self.notice(shop_link={"code": "kepak", "name": "Kepak"})
        self.assertIn("🔗 Keldi: 🛍 Sayt havolasi: <b>Kepak</b>", text)
        self.assertIn("?startapp=kepak", text)
        self.assertNotIn("to'g'ridan-to'g'ri", text)

    def test_link_added_under_another_source(self):
        text = self.notice(ad_source="fb_eritritol", shop_link={"code": "kepak", "name": "Kepak"})
        self.assertIn("manba: <code>fb_eritritol</code>", text)
        self.assertTrue(text.rstrip().endswith("?startapp=kepak</code>"))

    def test_name_is_escaped_and_plain_join_unchanged(self):
        self.assertIn("&lt;b&gt;", self.notice(shop_link={"code": "x", "name": "<b>"}))
        self.assertIn("to'g'ridan-to'g'ri qo'shildi", self.notice())

    def test_registration_looks_the_link_up(self):
        import referral_contest
        from types import SimpleNamespace
        from handlers import start
        notify = AsyncMock()
        with patch.object(shop_links, "last_open", AsyncMock(return_value={"code": "kepak", "name": "Kepak"})) as look,              patch.object(referral_contest, "notify_admins_new_user", notify),              patch("referral_program.grant_welcome_bonus", AsyncMock()),              patch("welcome_recipe.mark_pending", AsyncMock()),              patch("welcome_promo.mark_pending", AsyncMock()):
            run(start._process_new_user(Mock(), SimpleNamespace(id=BUYER, username=None, full_name="A"), None))
        look.assert_awaited_once_with(BUYER)
        self.assertEqual(notify.await_args.kwargs["shop_link"], {"code": "kepak", "name": "Kepak"})

    def test_lookup_trouble_never_breaks_registration(self):
        broken = Mock()
        broken.acquire.side_effect = RuntimeError("db down")
        with patch.object(database, "pool", broken), patch.object(shop_links, "_ready", False):
            self.assertIsNone(run(shop_links.last_open(BUYER)))


class AdminApiTest(unittest.TestCase):
    """GET /admin/api/shop-links — /sayt_havolalar's numbers on the admin site."""

    def setUp(self):
        import admin_web
        p = patch.object(admin_web, "ADMIN_WEB_PASSWORD", "test")       # the panel is switched on
        p.start()
        self.addCleanup(p.stop)

    def test_closed_without_the_admin_session(self):
        import admin_web
        from aiohttp.test_utils import make_mocked_request
        with patch.object(shop_links, "stats", AsyncMock()) as stats:
            resp = run(admin_web.api_shop_links(make_mocked_request("GET", "/admin/api/shop-links")))
        self.assertEqual(resp.status, 401)
        stats.assert_not_awaited()

    def test_numbers_and_links(self):
        import admin_web
        from decimal import Decimal
        from aiohttp.test_utils import make_mocked_request
        row = {"code": "kepak", "name": "Kepak", "opens": Decimal("3"), "people": 2, "revenue": Decimal("2.0E+5")}
        with patch.object(admin_web, "_authed", return_value=True),              patch.object(shop_links, "stats", AsyncMock(return_value=[row])) as stats:
            resp = run(admin_web.api_shop_links(make_mocked_request("GET", "/admin/api/shop-links?period=7")))
        body = json.loads(resp.text)
        self.assertEqual(body["period"], "7")
        self.assertTrue(body["links"][0]["link"].endswith("/shop?startapp=kepak"))
        self.assertIsNotNone(stats.await_args.args[0])                  # 7 days back
        with patch.object(admin_web, "_authed", return_value=True),              patch.object(shop_links, "stats", AsyncMock(return_value=[])) as stats:
            run(admin_web.api_shop_links(make_mocked_request("GET", "/admin/api/shop-links?period=all")))
        self.assertIsNone(stats.await_args.args[0])

    def test_registered_as_get_only(self):
        import admin_web
        from aiohttp import web
        app = web.Application()
        admin_web.setup_admin_routes(app)
        methods = {r.method for r in app.router.routes() if r.resource.canonical == "/admin/api/shop-links"}
        self.assertEqual(methods - {"HEAD"}, {"GET"})


class BotLinkTest(unittest.TestCase):
    """t.me/<bot>?start=<kod> (owner, 2026-11-08): the bot counts every
    arrival and answers with «🛍 Do'konni ochish»."""

    def test_links(self):
        self.assertTrue(shop_links.bot_link("kepak").endswith("?start=kepak"))
        self.assertNotIn("/shop", shop_links.bot_link("kepak"))

    def test_other_readers_payloads_are_never_link_codes(self):
        with patch.object(database, "pool", None):                       # no DB touched
            for bad in (None, "", "sayt", "retsept", "retsept_pitsa", "fb_x", "ig_x", "ad_x",
                        "prod_5", "ref123", "a b"):
                self.assertIsNone(run(shop_links.code_for_start(bad)), bad)
            self.assertIsNone(run(shop_links.create("Sayt", 1)))          # can't be created either

    def test_known_code_is_counted_as_a_bot_arrival(self):
        sql = []

        class Conn:
            async def fetchval(self, q, *a):
                return "kepak" if a == ("kepak",) else None

            async def execute(self, q, *a):
                sql.append((q, a))

        class Pool:
            def acquire(self):
                class C:
                    async def __aenter__(s):
                        return Conn()

                    async def __aexit__(s, *e):
                        return False
                return C()

        with patch.object(database, "pool", Pool()), patch.object(shop_links, "_ready", True):
            self.assertEqual(run(shop_links.note_start(BUYER, " Kepak ")), "kepak")
            self.assertIsNone(run(shop_links.note_start(BUYER, "nomalum")))
        self.assertEqual(len(sql), 1)
        q, args = sql[0]
        self.assertIn("'bot'", q)
        self.assertEqual(args[:2], ("kepak", BUYER))

    def start(self, args, chat="private"):
        from handlers import start
        msg = Mock()
        msg.chat.type = chat
        msg.from_user.id = BUYER
        command = Mock(args=args)
        handle = AsyncMock()
        note = AsyncMock(return_value="kepak" if args == "kepak" else None)
        parse = Mock(return_value=None)
        with patch.object(start, "_handle_start", handle), \
             patch.object(start, "_remind_pending_cheque", AsyncMock()), \
             patch.object(shop_links, "note_start", note), \
             patch("bloggers.parse_payload", parse):
            run(start.cmd_start_deep_link(msg, command, Mock()))
        return handle, note, parse

    def test_start_kepak_is_counted_and_never_a_blogger(self):
        handle, note, parse = self.start("kepak")
        note.assert_awaited_once_with(BUYER, "kepak")
        parse.assert_not_called()
        self.assertEqual(handle.await_args.kwargs["shop_code"], "kepak")

    def test_other_payloads_skip_the_lookup(self):
        for args in ("fb_eritritol", "prod_5", "sayt", "ref42"):
            handle, note, _ = self.start(args)
            note.assert_not_awaited()
            self.assertIsNone(handle.await_args.kwargs["shop_code"], args)

    def handle(self, is_new, language_code="uz"):
        from handlers import start
        msg = Mock()
        msg.chat.type = "private"
        msg.from_user.id = BUYER
        msg.from_user.language_code = language_code
        msg.answer = AsyncMock()
        shop = AsyncMock()
        with patch.object(start, "is_user_banned", AsyncMock(return_value=False)), \
             patch.object(start, "ensure_registered", AsyncMock(return_value=is_new)), \
             patch.object(start, "get_user_language", AsyncMock(return_value="uz_cyr")), \
             patch.object(start, "ensure_menu_keyboard", AsyncMock()), \
             patch.object(start, "send_open_shop", shop):
            run(start._handle_start(msg, None, shop_code="kepak"))
        return msg, shop

    def test_returning_buyer_gets_just_the_button(self):
        msg, shop = self.handle(is_new=False)
        msg.answer.assert_not_awaited()
        self.assertEqual(shop.await_args.args[1:], (BUYER, "uz_cyr"))

    def test_new_member_gets_the_picker_and_the_button(self):
        msg, shop = self.handle(is_new=True, language_code="ru")
        msg.answer.assert_awaited_once()                                  # the language picker
        self.assertEqual(shop.await_args.args[1:], (BUYER, "ru"))

    def test_the_button_opens_the_shop(self):
        from handlers import start
        for lang, word in (("uz", "Do'konni ochish"), ("ru", "Открыть магазин"), ("uz_cyr", "Дўконни очиш")):
            b = Mock()
            b.send_message = AsyncMock()
            run(start.send_open_shop(b, BUYER, lang))
            button = b.send_message.await_args.kwargs["reply_markup"].inline_keyboard[0][0]
            self.assertIn(word, button.text, lang)
            self.assertIsNotNone(button.web_app)

    def test_counted_even_if_they_never_join_the_channel(self):
        import subscription_gate
        from aiogram.types import Message
        event = MagicMock(spec=Message)
        event.text = "/start kepak"
        event.from_user = MagicMock(id=BUYER, language_code="uz")
        event.chat = MagicMock(type="private", id=BUYER)
        note = AsyncMock(return_value="kepak")
        bot = AsyncMock()
        with patch.object(subscription_gate, "_is_subscribed", AsyncMock(return_value=False)), \
             patch.object(subscription_gate, "_awaiting_cheque", AsyncMock(return_value=False)), \
             patch.object(shop_links, "note_start", note):
            run(subscription_gate.SubscriptionGateMiddleware()(AsyncMock(), event, {"bot": bot}))
        subscription_gate._pending_start_payload.pop(BUYER, None)
        note.assert_awaited_once_with(BUYER, "kepak")
        bot.send_message.assert_awaited()                                 # the «join the channel» card

    def test_after_joining_the_channel_the_shop_button_comes(self):
        import subscription_gate
        from aiogram.types import CallbackQuery
        subscription_gate._pending_start_payload[BUYER] = "kepak"
        event = MagicMock(spec=CallbackQuery)
        event.data = subscription_gate.CHECK_CALLBACK
        event.from_user = MagicMock(id=BUYER, language_code="ru")
        event.message = AsyncMock()
        event.answer = AsyncMock()
        shop = AsyncMock()
        with patch.object(subscription_gate, "_is_subscribed", AsyncMock(return_value=True)), \
             patch("handlers.start.ensure_registered", AsyncMock(return_value=True)), \
             patch.object(shop_links, "code_for_start", AsyncMock(return_value="kepak")), \
             patch.object(shop_links, "note_start", AsyncMock()) as note, \
             patch("handlers.start.send_open_shop", shop):
            run(subscription_gate.SubscriptionGateMiddleware()(AsyncMock(), event, {"bot": AsyncMock()}))
        note.assert_not_awaited()                                         # counted once, at the first /start
        self.assertEqual(shop.await_args.args[1:], (BUYER, "ru"))

    def test_report_shows_both_links_and_the_split(self):
        row = {"code": "kepak", "name": "Kepak", "opens": 5, "people": 4, "people_bot": 3, "people_app": 2,
               "new_users": 3, "no_start": 1, "buyers": 0, "orders": 0, "revenue": 0}
        with patch.object(shop_links, "stats", AsyncMock(return_value=[row])):
            text = run(shop_links.build_report("all"))
        self.assertIn("?start=kepak", text)
        self.assertIn("/shop?startapp=kepak", text)
        self.assertIn("🤖 botga 3 · 🛍 do'konga 2", text)


if __name__ == "__main__":
    unittest.main()
