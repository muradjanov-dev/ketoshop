"""Instagram/Facebook izohlari → bot (TZ «4-qism», 2026-11-09).

Meta Graph va Claude API soxta: hech qanday izohga haqiqiy javob ketmaydi,
hech qanday model chaqirilmaydi. Baza — xotiradagi lug'at."""
import asyncio
import copy
import hashlib
import hmac
import json
import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import comment_ai
import database
import meta_comments as mc

IDENT = {"page_token": "PAGE", "page_name": "Keto market.uz", "ig_id": "17841400000000001",
         "ig_username": "ketoshop.uz"}
ADMIN = next(iter(mc.ADMIN_IDS)) if mc.ADMIN_IDS else 425609051

# TZ'dagi Instagram izohi namunasi.
IG_HOOK = {"object": "instagram", "entry": [{"id": "17841400000000001", "time": 1762680000, "changes": [{
    "field": "comments",
    "value": {"id": "18000000000000001", "text": "Narxi qancha?",
              "from": {"id": "555", "username": "dilnoza.uz"},
              "media": {"id": "18100000000000009", "media_product_type": "AD",
                        "ad_id": "120000000000000001", "ad_title": "Glyuten 1-qism | 25-45",
                        "original_media_id": "18100000000000001"}}}]}]}

FB_HOOK = {"object": "page", "entry": [{"id": "582508891606220", "time": 1762680000, "changes": [
    {"field": "feed", "value": {"item": "comment", "verb": "add", "comment_id": "582508891606220_1_2",
                                "post_id": "582508891606220_1", "parent_id": "582508891606220_1",
                                "message": "Зўр дўкон экан",
                                "from": {"id": "999", "name": "Тест Фойдаланувчи"},
                                "created_time": 1762680000}},
    {"field": "feed", "value": {"item": "comment", "verb": "edited", "comment_id": "x", "post_id": "y"}},
    {"field": "feed", "value": {"item": "reaction", "verb": "add", "post_id": "y"}},
]}]}


class FakeDB:
    """database.* izoh funksiyalarining xotiradagi nusxasi."""

    def __init__(self, mode="avto"):
        self.rows, self.next = {}, 1
        self.state = {"ai_mode": mode, "kb": {}, "backfilled": True, "token": "T",
                      "last_webhook_at": None, "last_sync_at": None}

    async def get_meta_comments_state(self):
        return copy.deepcopy(self.state)

    async def mark_meta_comments_state(self, **kw):
        if kw.get("backfilled") is not None:
            self.state["backfilled"] = kw["backfilled"]

    async def insert_meta_comment(self, c):
        if any(r["comment_id"] == c["comment_id"] for r in self.rows.values()):
            return None
        row = {"id": self.next, "status": "new", "tg_messages": [], "private_sent": False, "hidden": False,
               "received_at": datetime.utcnow(), "category": None, "ai_draft": None, "ai_model": None,
               "replied_by": None, "replied_at": None, "reply_text": None, "reply_kind": None, "note": None}
        row.update({k: v for k, v in c.items() if v is not None})
        self.rows[self.next] = row
        self.next += 1
        return copy.deepcopy(row)

    async def get_meta_comment(self, key):
        return copy.deepcopy(self.rows.get(key))

    async def update_meta_comment(self, key, **fields):
        self.rows[key].update(fields)
        return copy.deepcopy(self.rows[key])

    async def claim_meta_comment(self, key, from_statuses, to_status):
        if self.rows[key]["status"] in from_statuses:
            self.rows[key]["status"] = to_status
            return True
        return False

    async def find_meta_comment_by_card(self, chat_id, message_id):
        for r in self.rows.values():
            if {"c": chat_id, "m": message_id} in r["tg_messages"]:
                return copy.deepcopy(r)
        return None

    async def get_user(self, uid):
        return {"full_name": "Abdurrahmon"}

    def patches(self):
        return [patch.object(database, name, getattr(self, name)) for name in (
            "get_meta_comments_state", "mark_meta_comments_state", "insert_meta_comment",
            "get_meta_comment", "update_meta_comment", "claim_meta_comment",
            "find_meta_comment_by_card", "get_user")]


class FakeBot:
    def __init__(self):
        self.sent, self.edits, self.n = [], [], 100

    async def send_message(self, chat_id, text, **kw):
        self.n += 1
        self.sent.append((chat_id, text, kw.get("reply_markup")))
        return SimpleNamespace(message_id=self.n, chat=SimpleNamespace(id=chat_id))

    async def edit_message_text(self, text, chat_id=None, message_id=None, **kw):
        self.edits.append((chat_id, message_id, text, kw.get("reply_markup")))


def buttons(markup) -> list[str]:
    return [b.callback_data for row in (markup.inline_keyboard if markup else []) for b in row]


class WebhookPayloadTest(unittest.TestCase):
    def test_instagram_ad_comment(self):
        [c] = mc.parse_webhook(IG_HOOK)
        self.assertEqual((c["platform"], c["comment_id"], c["ad_id"]), ("ig", "18000000000000001", "120000000000000001"))
        self.assertEqual((c["username"], c["text"], c["ad_name"]), ("dilnoza.uz", "Narxi qancha?", "Glyuten 1-qism | 25-45"))
        self.assertEqual(c["account_id"], "17841400000000001")
        # Our own reply arriving through the same webhook is recognised even without a token.
        own = copy.deepcopy(IG_HOOK)
        own["entry"][0]["changes"][0]["value"]["from"] = {"id": "17841400000000001", "username": "ketoshop.uz"}
        [o] = mc.parse_webhook(own)
        self.assertTrue(mc.is_own(o, {}))

    def test_facebook_new_comments_only(self):
        [c] = mc.parse_webhook(FB_HOOK)
        self.assertEqual((c["platform"], c["comment_id"], c["media_id"]), ("fb", "582508891606220_1_2", "582508891606220_1"))
        self.assertIsNone(c["parent_id"])            # a comment on the post itself
        self.assertEqual(c["username"], "Тест Фойдаланувчи")
        self.assertFalse(mc.is_own(c, IDENT))
        self.assertTrue(mc.is_own(dict(c, from_id=mc.PAGE_ID), IDENT))

    def test_signature(self):
        raw = json.dumps(IG_HOOK).encode()
        good = "sha256=" + hmac.new(b"s3cret", raw, hashlib.sha256).hexdigest()
        self.assertTrue(mc.signature_ok(raw, good, "s3cret"))
        self.assertFalse(mc.signature_ok(raw, good, "other"))
        self.assertFalse(mc.signature_ok(raw, None, "s3cret"))
        self.assertFalse(mc.signature_ok(raw, good, ""))


class WebhookEndpointTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.ingested = []

        async def fake_ingest(bot, c, *, source, **kw):
            self.ingested.append((c["comment_id"], source))

        for p in (patch.object(mc, "APP_SECRET", "s3cret"), patch.object(mc, "VERIFY_TOKEN", "verify-me"),
                  patch.object(mc, "ingest", fake_ingest),
                  patch.object(database, "mark_meta_comments_state", AsyncMock())):
            p.start()
            self.addCleanup(p.stop)
        app = web.Application()
        mc.setup_routes(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def test_verification_handshake(self):
        ok = await self.client.get("/meta/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "verify-me",
                                                            "hub.challenge": "42"})
        self.assertEqual((ok.status, await ok.text()), (200, "42"))
        bad = await self.client.get("/meta/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "nope",
                                                             "hub.challenge": "42"})
        self.assertEqual(bad.status, 403)

    async def test_only_signed_events_are_taken(self):
        raw = json.dumps(IG_HOOK).encode()
        unsigned = await self.client.post("/meta/webhook", data=raw)
        self.assertEqual(unsigned.status, 403)
        forged = await self.client.post("/meta/webhook", data=raw, headers={"X-Hub-Signature-256": "sha256=00"})
        self.assertEqual(forged.status, 403)
        sig = "sha256=" + hmac.new(b"s3cret", raw, hashlib.sha256).hexdigest()
        good = await self.client.post("/meta/webhook", data=raw, headers={"X-Hub-Signature-256": sig})
        self.assertEqual(good.status, 200)
        await asyncio.sleep(0)
        self.assertEqual(self.ingested, [("18000000000000001", "webhook")])


class PolicyTest(unittest.TestCase):
    def test_tz_table(self):
        d = comment_ai.decide
        self.assertEqual(d("rahmat", False, "avto"), "auto")
        for cat in ("manzil", "yetkazish", "buyurtma", "narx", "mavjudlik"):
            self.assertEqual(d(cat, True, "avto"), "auto", cat)
            self.assertEqual(d(cat, False, "avto"), "approve", cat)
        for cat in ("salomatlik", "shikoyat", "boshqa"):
            self.assertEqual(d(cat, True, "avto"), "approve", cat)
        self.assertEqual(d("spam", True, "avto"), "spam")

    def test_modes_and_old_comments(self):
        self.assertEqual(comment_ai.decide("rahmat", True, "tasdiq"), "approve")
        self.assertEqual(comment_ai.decide("rahmat", True, "avto", fresh=False), "approve")
        self.assertEqual(comment_ai.decide("nimadir", True, "avto"), "approve")

    def test_canned_direct_reply_still_needs_an_answer_for_questions(self):
        self.assertTrue(mc.needs_answer_after_auto("Адрес қаерда", "Rahmat! Sizga Direct orqali javob yubordik 📩"))
        self.assertTrue(mc.needs_answer_after_auto("Narxi qancha?", "Direct'ingizni tekshiring 🌿"))
        self.assertFalse(mc.needs_answer_after_auto("🔥🔥🔥", "Rahmat! Sizga Direct orqali javob yubordik 📩"))
        self.assertFalse(mc.needs_answer_after_auto("Narxi qancha?", "Narxi 120 000 so'm"))

    def test_templates_follow_the_comments_script(self):
        out = comment_ai.in_script_of("Нархи қанча?", "Assalomu alaykum! Narxlar botda: @ketoshopbot 🌿")
        self.assertIn("Ассалому алайкум", out)
        self.assertIn("@ketoshopbot", out)
        self.assertEqual(comment_ai.in_script_of("Narxi?", "Salom"), "Salom")


class ListingTest(unittest.TestCase):
    def test_instagram_listing(self):
        data = {"data": [
            {"id": "c1", "text": "Адрес қаерда", "username": "test_user1", "from": {"id": "1"},
             "timestamp": "2026-11-08T10:00:00+0000",
             "replies": {"data": [
                 {"id": "r1", "text": "Rahmat! Sizga Direct orqali javob yubordik 📩", "username": "ketoshop.uz",
                  "from": {"id": IDENT["ig_id"]}},
                 {"id": "r2", "text": "Men ham so'rayman", "username": "aziza", "from": {"id": "2"}}]}},
            {"id": "c2", "text": "Bizning post", "username": "ketoshop.uz", "from": {"id": IDENT["ig_id"]}},
        ]}
        target = {"platform": "ig", "object": "m1", "ad_id": "a1", "ad_name": "Kepak", "link": "https://instagram.com/p/x"}
        out = mc.comments_from_listing(target, data, IDENT)
        self.assertEqual([(c["comment_id"], ours) for c, ours in out],
                         [("c1", "Rahmat! Sizga Direct orqali javob yubordik 📩"), ("r2", None)])
        self.assertEqual(out[0][0]["ad_name"], "Kepak")
        self.assertEqual(out[0][0]["created_at"], datetime(2026, 11, 8, 10, 0))
        self.assertEqual(out[1][0]["parent_id"], "c1")


class FlowTest(unittest.IsolatedAsyncioTestCase):
    """ingest → AI → kartochka / o'zi yuborish; adminning tugmalari."""

    async def asyncSetUp(self):
        self.db = FakeDB()
        self.bot = FakeBot()
        self.public, self.private, self.hidden = [], [], []
        self.existing = None

        async def reply_public(session, ident, c, text):
            self.public.append((c["comment_id"], text))
            return "reply1"

        async def reply_private(session, ident, c, text):
            self.private.append((c["comment_id"], text))

        async def hide(session, ident, c):
            self.hidden.append(c["comment_id"])

        async def existing(session, ident, c):
            return self.existing

        async def permalink(session, ident, c):
            return "https://www.instagram.com/p/TESTPOST01/"

        self.draft = None

        async def draft(row, kb):
            return self.draft

        for p in self.db.patches() + [
            patch.object(mc, "identity", AsyncMock(return_value=IDENT)),
            patch.object(mc, "reply_public", reply_public), patch.object(mc, "reply_private", reply_private),
            patch.object(mc, "hide", hide), patch.object(mc, "our_existing_reply", existing),
            patch.object(mc, "_permalink", permalink), patch.object(mc, "AI_DELAY", 0),
            patch.object(mc, "ADMIN_IDS", [ADMIN, 6950127923]),
            patch.object(comment_ai, "draft", draft),
        ]:
            p.start()
            self.addCleanup(p.stop)

    async def settle(self):
        for _ in range(5):
            await asyncio.sleep(0)
        if mc._tasks:
            await asyncio.gather(*list(mc._tasks))

    def comment(self, **kw):
        [c] = mc.parse_webhook(IG_HOOK)
        c.update(kw)
        return c

    async def test_thanks_goes_out_by_itself_then_admins_are_told(self):
        self.draft = comment_ai.Draft("rahmat", "Rahmat, sog' bo'ling! 🌿", True, "claude-haiku-5-5")
        await mc.ingest(self.bot, self.comment(text="🔥🔥🔥"), source="webhook")
        await self.settle()
        self.assertEqual(self.public, [("18000000000000001", "Rahmat, sog' bo'ling! 🌿")])
        row = self.db.rows[1]
        self.assertEqual(row["status"], "ai_answered")
        self.assertEqual(len(self.bot.sent), 2)                  # one card per admin
        self.assertIn("🤖 AI javob berdi", self.bot.sent[0][1])
        self.assertIn("Glyuten 1-qism | 25-45", self.bot.sent[0][1])

    async def test_no_second_reply_when_another_automation_answered(self):
        self.draft = comment_ai.Draft("rahmat", "Rahmat!", True, "claude-haiku-5-5")
        self.existing = "Rahmat! Sizga Direct orqali javob yubordik 📩"
        await mc.ingest(self.bot, self.comment(text="Zo'r"), source="webhook")
        await self.settle()
        self.assertEqual(self.public, [])
        self.assertEqual(self.db.rows[1]["status"], "new")
        self.assertIn("Boshqa avtomat allaqachon javob yozgan", self.bot.sent[0][1])
        self.assertIn("mc:ok:1", buttons(self.bot.sent[0][2]))

    async def test_health_question_waits_for_an_admin(self):
        self.draft = comment_ai.Draft("salomatlik", "Assalomu alaykum! … shifokor bilan maslahatlashing 🌿",
                                      False, "claude-sonnet-5-5")
        await mc.ingest(self.bot, self.comment(text="Autizmli bolaga bo'ladimi?"), source="webhook")
        await self.settle()
        self.assertEqual(self.public, [])
        text, kb = self.bot.sent[0][1], self.bot.sent[0][2]
        self.assertIn("AI loyiha", text)
        self.assertIn("🩺 Salomatlik", text)
        self.assertEqual(buttons(kb), ["mc:ok:1", "mc:ed:1", "mc:dm:1", "mc:t:narx:1", "mc:t:yetkazish:1",
                                       "mc:t:bot:1", "mc:hide:1", "mc:seen:1", "mc:no:1"])

    async def test_admin_reply_to_the_card_is_posted_and_every_card_updates(self):
        await mc.ingest(self.bot, self.comment(), source="webhook")
        await self.settle()
        card_chat, card_id = self.db.rows[1]["tg_messages"][0]["c"], self.db.rows[1]["tg_messages"][0]["m"]
        msg = SimpleNamespace(reply_to_message=SimpleNamespace(message_id=card_id),
                              from_user=SimpleNamespace(id=ADMIN), chat=SimpleNamespace(id=card_chat))
        target = await mc._cmd_target(msg)
        self.assertEqual(target, {"mc_key": 1, "mc_mode": "public"})
        err = await mc.answer(self.bot, 1, "Bodom uni 500gr — 120 000 so'm 🌿", ADMIN)
        self.assertIsNone(err)
        self.assertEqual(self.public, [("18000000000000001", "Bodom uni 500gr — 120 000 so'm 🌿")])
        self.assertEqual(self.db.rows[1]["status"], "answered")
        self.assertEqual(len(self.bot.edits), 2)
        self.assertIn("✅ Javob berildi</b> — Abdurrahmon", self.bot.edits[0][2])
        self.assertIn("↪️ (ochiq) «Bodom uni 500gr", self.bot.edits[0][2])
        # A non-admin's reply is not taken.
        msg.from_user.id = 1
        self.assertFalse(await mc._cmd_target(msg))

    async def test_two_admins_at_once_post_one_reply(self):
        await mc.ingest(self.bot, self.comment(), source="webhook")
        await self.settle()
        self.db.rows[1]["status"] = "sending"           # the other admin's send is in flight
        err = await mc.answer(self.bot, 1, "Javob", ADMIN)
        self.assertIsNotNone(err)
        self.assertEqual(self.public, [])

    async def test_private_reply_once_within_seven_days(self):
        await mc.ingest(self.bot, self.comment(), source="webhook")
        await self.settle()
        self.assertIsNone(await mc.answer(self.bot, 1, "Narxlarni yubordik", ADMIN, private=True))
        self.assertEqual(self.private, [("18000000000000001", "Narxlarni yubordik")])
        self.assertIsNotNone(await mc.answer(self.bot, 1, "Yana", ADMIN, private=True))
        old = self.comment(comment_id="old1", created_at=datetime.utcnow() - timedelta(days=8))
        await mc.ingest(self.bot, old, source="sync")
        await self.settle()
        self.assertIn("7 kun", await mc.answer(self.bot, 2, "Salom", ADMIN, private=True))

    async def test_backfill_shows_unanswered_and_canned_only_but_never_sends(self):
        self.draft = comment_ai.Draft("rahmat", "Rahmat!", True, "claude-haiku-5-5")
        old = datetime.utcnow() - timedelta(days=3)
        await mc.ingest(self.bot, self.comment(comment_id="a", text="Раҳмат", created_at=old),
                        source="backfill", backfill=True)
        await mc.ingest(self.bot, self.comment(comment_id="b", text="Манзил қаерда", created_at=old),
                        source="backfill", our_reply="Rahmat! Sizga Direct orqali javob yubordik 📩", backfill=True)
        await mc.ingest(self.bot, self.comment(comment_id="c", text="Rahmat", created_at=old),
                        source="backfill", our_reply="Sizga ham rahmat!", backfill=True)
        await self.settle()
        self.assertEqual(self.public, [])                       # nothing old goes out by itself
        statuses = {r["comment_id"]: r["status"] for r in self.db.rows.values()}
        self.assertEqual(statuses, {"a": "new", "b": "new", "c": "answered"})
        self.assertIn("Faqat avtomatik javob olgan", self.db.rows[2]["note"])
        self.assertEqual(len(self.bot.sent), 4)                 # a and b, to two admins

    async def test_template_button_follows_the_script(self):
        await mc.ingest(self.bot, self.comment(text="Нархи қанча?"), source="webhook")
        await self.settle()
        cb = SimpleNamespace(data="mc:t:narx:1", from_user=SimpleNamespace(id=ADMIN), bot=self.bot,
                             message=SimpleNamespace(chat=SimpleNamespace(id=ADMIN)), answer=AsyncMock())
        with patch.object(mc, "_kb", AsyncMock(return_value={"tpl_narx": "Assalomu alaykum! Narxlar botda: @ketoshopbot 🌿"})):
            await mc.on_button(cb)
        self.assertEqual(len(self.public), 1)
        self.assertIn("Ассалому алайкум", self.public[0][1])
        self.assertIn("@ketoshopbot", self.public[0][1])

    async def test_hide_and_seen(self):
        await mc.ingest(self.bot, self.comment(text="Spam link"), source="webhook")
        await self.settle()
        cb = SimpleNamespace(data="mc:hide:1", from_user=SimpleNamespace(id=ADMIN), bot=self.bot,
                             message=SimpleNamespace(chat=SimpleNamespace(id=ADMIN)), answer=AsyncMock())
        await mc.on_button(cb)
        self.assertEqual(self.hidden, ["18000000000000001"])
        self.assertEqual(self.db.rows[1]["status"], "hidden")
        stranger = SimpleNamespace(data="mc:seen:1", from_user=SimpleNamespace(id=1), bot=self.bot,
                                   message=None, answer=AsyncMock())
        await mc.on_button(stranger)
        self.assertEqual(self.db.rows[1]["status"], "hidden")


class FakeMessages:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    async def create(self, **kw):
        self.calls.append(kw)
        return self.replies.pop(0)


def claude_reply(payload, stop="end_turn"):
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=json.dumps(payload))],
                           usage=SimpleNamespace(input_tokens=100, cache_read_input_tokens=0,
                                                 cache_creation_input_tokens=0, output_tokens=20))


class ClaudeDraftTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for p in (patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
                  patch.object(comment_ai, "catalog_text", AsyncMock(return_value="- Bodom uni 500gr — 120 000 so'm")),
                  patch.object(database, "record_ai_usage", AsyncMock())):
            p.start()
            self.addCleanup(p.stop)
        self.kb = {"manzil": "Toshkent", "yetkazish": "kuryer"}
        self.row = {"platform": "ig", "username": "dilnoza", "ad_name": "Glyuten", "text": "Narxi qancha?"}

    def client(self, simple, complex_=()):
        plain, beta = FakeMessages(simple), FakeMessages(complex_)
        fake = SimpleNamespace(messages=plain, beta=SimpleNamespace(messages=beta))
        p = patch.object(comment_ai, "_get_client", lambda: fake)
        p.start()
        self.addCleanup(p.stop)
        return plain, beta

    async def test_simple_comment_uses_haiku_with_a_json_schema(self):
        plain, beta = self.client([claude_reply({"category": "narx", "reply": "120 000 so'm 🌿", "confident": True})])
        d = await comment_ai.draft(self.row, self.kb)
        self.assertEqual((d.category, d.reply, d.confident, d.model), ("narx", "120 000 so'm 🌿", True, "claude-haiku-5-5"))
        call = plain.calls[0]
        self.assertEqual(call["model"], "claude-haiku-5-5")
        self.assertEqual(call["output_config"]["effort"], "low")
        self.assertEqual(call["output_config"]["format"]["type"], "json_schema")
        self.assertEqual(call["system"][1]["cache_control"], {"type": "ephemeral"})   # KB + catalog cached
        self.assertIn("Bodom uni 500gr", call["system"][1]["text"])
        self.assertNotIn("temperature", call)
        self.assertEqual(beta.calls, [])

    async def test_complex_question_is_redrafted_by_sonnet_and_never_confident(self):
        plain, beta = self.client(
            [claude_reply({"category": "salomatlik", "reply": "qisqa", "confident": True})],
            [claude_reply({"category": "rahmat", "reply": "Shifokor bilan maslahatlashing 🌿", "confident": True})])
        d = await comment_ai.draft(dict(self.row, text="Diabetga bo'ladimi?"), self.kb)
        self.assertEqual((d.category, d.model, d.confident), ("salomatlik", "claude-sonnet-5-5", False))
        self.assertEqual(d.reply, "Shifokor bilan maslahatlashing 🌿")
        call = beta.calls[0]
        self.assertEqual((call["model"], call["extra_body"], call["betas"]),
                         ("claude-sonnet-5-5", {"fallbacks": "default"}, ["server-side-fallback-2026-07-01"]))
        self.assertEqual(call["output_config"]["effort"], "medium")

    async def test_a_failed_redraft_keeps_the_first_draft(self):
        class Broken:
            async def create(self, **kw):
                raise TypeError("unexpected keyword")
        plain = FakeMessages([claude_reply({"category": "shikoyat", "reply": "Uzr so'raymiz 🙏", "confident": False})])
        fake = SimpleNamespace(messages=plain, beta=SimpleNamespace(messages=Broken()))
        with patch.object(comment_ai, "_get_client", lambda: fake):
            d = await comment_ai.draft(dict(self.row, text="Aldov!"), self.kb)
        self.assertEqual((d.category, d.reply, d.model), ("shikoyat", "Uzr so'raymiz 🙏", "claude-haiku-5-5"))
        self.assertEqual(comment_ai.decide(d.category, d.confident, "avto"), "approve")

    async def test_refusal_or_garbage_means_no_draft(self):
        self.client([claude_reply({}, stop="refusal")])
        self.assertIsNone(await comment_ai.draft(self.row, self.kb))
        self.client([SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="salom")],
                                     usage=None)])
        self.assertIsNone(await comment_ai.draft(self.row, self.kb))

    async def test_spam_gets_no_text(self):
        self.client([claude_reply({"category": "spam", "reply": "…", "confident": True})])
        d = await comment_ai.draft(self.row, self.kb)
        self.assertEqual((d.category, d.reply), ("spam", ""))

    async def test_no_key_no_ai(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            self.assertIsNone(await comment_ai.draft(self.row, self.kb))


class KnowledgeBaseTest(unittest.TestCase):
    def test_defaults_come_from_the_shop_rules(self):
        kb = comment_ai.kb_with_defaults({"optom": "99 000 00 00", "nonsense": "x"})
        self.assertIn("Oqsoy", kb["manzil"])                    # owner's 2026-11-04 address
        self.assertIn("800 000", kb["yetkazish"])
        self.assertEqual(kb["optom"], "99 000 00 00")
        self.assertNotIn("nonsense", kb)
        block = comment_ai.kb_block(kb, "- Tuz — 5 000 so'm")
        self.assertIn("Tuz — 5 000", block)


if __name__ == "__main__":
    unittest.main()
