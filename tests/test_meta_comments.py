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
               "replied_by": None, "replied_at": None, "reply_text": None, "reply_kind": None, "note": None,
               "ai_confident": None, "ai_dm": None, "dm_sent_at": None}
        row.update({k: v for k, v in c.items() if v is not None})
        self.rows[self.next] = row
        self.next += 1
        return copy.deepcopy(row)

    async def get_meta_comment(self, key):
        return copy.deepcopy(self.rows.get(key))

    async def update_meta_comment(self, key, **fields):
        self.rows[key].update(fields)
        if fields.get("private_sent") is True:
            self.rows[key]["dm_sent_at"] = datetime.utcnow()
        return copy.deepcopy(self.rows[key])

    async def meta_comment_dm_recent(self, from_id, days=7):
        return bool(from_id) and any(r.get("from_id") == from_id and r.get("private_sent")
                                     for r in self.rows.values())

    async def list_meta_comments_failed(self, limit=200):
        return [copy.deepcopy(r) for r in self.rows.values()
                if r["status"] in ("new", "pending") and r.get("ai_confident") is True and r.get("ai_draft")
                and (r.get("note") or "").startswith("❌ AI yubora olmadi")][:limit]

    async def list_meta_comments_unchecked(self, limit=40):
        return [copy.deepcopy(r) for r in self.rows.values()
                if r["status"] in ("new", "pending") and r.get("ai_confident") is None][:limit]

    async def list_meta_comments_with_cards(self, received_before=None):
        return [copy.deepcopy(r) for r in self.rows.values() if r["tg_messages"]
                and (received_before is None or r["received_at"] < received_before)]

    async def meta_comment_same_author_texts(self, from_id, media_id, key):
        return [r["text"] for r in self.rows.values() if from_id and media_id and r.get("from_id") == from_id
                and r.get("media_id") == media_id and r["id"] != key
                and r["status"] in ("ai_answered", "answered", "sending")]

    async def claim_release_notes(self, key):
        claimed = getattr(self, "claimed", set())
        self.claimed = claimed
        if key in claimed:
            return False
        claimed.add(key)
        return True

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
            "find_meta_comment_by_card", "get_user", "meta_comment_dm_recent",
            "list_meta_comments_unchecked", "list_meta_comments_with_cards", "claim_release_notes",
            "meta_comment_same_author_texts", "list_meta_comments_failed")]


class FakeBot:
    def __init__(self):
        self.sent, self.edits, self.deleted, self.n = [], [], [], 100

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))

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


class SubReplyCheckTest(unittest.IsolatedAsyncioTestCase):
    async def test_no_replies_lookup_on_an_answer_to_an_answer(self):
        # 2026-11-12: GET /{reply}/replies itself raised #100 for 38 comments.
        called = []

        async def graph(*a, **k):
            called.append(a)
            return {"data": []}
        with patch.object(mc, "_graph", graph):
            self.assertIsNone(await mc.our_existing_reply(None, IDENT, {"comment_id": "sub", "parent_id": "top",
                                                                        "platform": "ig"}))
            self.assertEqual(called, [])
            await mc.our_existing_reply(None, IDENT, {"comment_id": "top", "platform": "ig"})
            self.assertEqual(len(called), 1)

    def test_template_for_plain_questions_only(self):
        kb = comment_ai.kb_with_defaults({})
        self.assertIn("@ketoshopbot", comment_ai.template_reply("narx", kb))
        self.assertIn("Oqsoy", comment_ai.template_reply("manzil", kb))
        self.assertIn("pochta", comment_ai.template_reply("yetkazish", kb))
        for cat in ("salomatlik", "shikoyat", "boshqa", "spam", None):
            self.assertIsNone(comment_ai.template_reply(cat, kb))


class ReplyShapeTest(unittest.TestCase):
    """2026-11-11: 37 replies failed with "(#100) Field is only available for
    top-level comments" — they were answers to answers."""

    def test_a_reply_to_a_reply_goes_under_the_top_comment_with_a_mention(self):
        c = {"comment_id": "sub", "parent_id": "top", "platform": "ig", "username": "dilnoza.uz"}
        self.assertEqual(mc.reply_target(c, "Rahmat! 🌿"), ("top", "@dilnoza.uz Rahmat! 🌿"))
        self.assertEqual(mc.reply_target(c, "@dilnoza.uz rahmat"), ("top", "@dilnoza.uz rahmat"))
        self.assertEqual(mc.reply_target(dict(c, platform="fb", username="Ali Valiyev"), "Rahmat"), ("top", "Rahmat"))
        self.assertEqual(mc.reply_target({"comment_id": "top", "platform": "ig"}, "Salom"), ("top", "Salom"))

    def test_finalize_cleans_what_instagram_shows_badly(self):
        f = comment_ai.finalize
        self.assertEqual(f("Narxi?", "**Tabiiy GHEE 1000ml — 135 000 so'm** 😊"), "Tabiiy GHEE 1000ml — 135 000 so'm 😊")
        self.assertEqual(f("Нархи", "Кепак — 10 000 со‘м 😊"), "Кепак — 10 000 сўм 😊")
        self.assertEqual(f("Нархлари", "Stevia 200гр — 33 000 сўм"), "Стевиа 200гр — 33 000 сўм")
        self.assertEqual(f("Zo'r", "Juda xursandman, yordam beraman."), "Juda xursandmiz, yordam beramiz.")
        self.assertEqual(f("Yaxshi", "Yaman emas!"), "Yaman emas!")

    def test_finalize_never_asks_for_the_product_in_our_own_post(self):
        out = comment_ai.finalize("Нархи канча", "Кепак — 10 000 со‘м 😊 Агар бошқа маҳсулот бўлса, "
                                                 "номини ёзинг — аниқ нархини айтаман.")
        self.assertEqual(out, "Кепак — 10 000 сўм 😊 Барча нархлар ва маҳсулотларимиз @ketoshopbot да 🌿")


class PolicyTest(unittest.TestCase):
    def test_ai_answers_everything_it_can(self):
        # Owner, 2026-11-11: AI answers all by itself; only what it could not
        # answer reaches the admins.
        d = comment_ai.decide
        for cat in comment_ai.CATEGORIES:
            if cat == "spam":
                continue
            self.assertEqual(d(cat, True, "avto"), "auto", cat)
            self.assertEqual(d(cat, False, "avto"), "approve", cat)
        self.assertEqual(d("spam", True, "avto"), "spam")

    def test_modes(self):
        self.assertEqual(comment_ai.decide("rahmat", True, "tasdiq"), "approve")
        self.assertEqual(comment_ai.decide("nimadir", True, "avto"), "approve")

    def test_direct_thanks_carries_the_shop_link(self):
        out = comment_ai.dm_text("Zo'r!", "Izohingiz uchun rahmat, mahsulotlarimizni ko'ring https://evil.example")
        self.assertTrue(out.endswith("👉 https://t.me/ketoshopbot/shop"))
        self.assertNotIn("evil.example", out)
        cyr = comment_ai.dm_text("Раҳмат!", "")
        self.assertIn("Изоҳингиз учун катта раҳмат", cyr)                   # default, in the comment's script
        self.assertTrue(cyr.endswith("https://t.me/ketoshopbot/shop"))

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

        self.order = []

        async def reply_public(session, ident, c, text):
            self.public.append((c["comment_id"], text))
            self.order.append("public")
            return "reply1"

        async def reply_private(session, ident, c, text):
            self.private.append((c["comment_id"], text))
            self.order.append("private")

        async def hide(session, ident, c):
            self.hidden.append(c["comment_id"])

        async def existing(session, ident, c):
            return self.existing

        async def permalink(session, ident, c):
            return "https://www.instagram.com/p/TESTPOST01/"

        self.draft = None
        self.ai = None            # None: AI ready only when a draft is given; "" / "openai" force it
        self.posts = {}           # media_id → (caption, image)
        self.seen_rows = []

        async def draft(row, kb):
            self.seen_rows.append(row)
            return self.draft

        async def provider():
            if self.ai is not None:
                return self.ai
            return "openai" if self.draft is not None else ""

        async def post_context(row):
            return self.posts.get(row.get("media_id"), ("", ""))

        for p in self.db.patches() + [
            patch.object(mc, "identity", AsyncMock(return_value=IDENT)),
            patch.object(mc, "reply_public", reply_public), patch.object(mc, "reply_private", reply_private),
            patch.object(mc, "hide", hide), patch.object(mc, "our_existing_reply", existing),
            patch.object(mc, "_permalink", permalink), patch.object(mc, "AI_DELAY", 0),
            patch.object(mc, "ADMIN_IDS", [ADMIN, 6950127923]),
            patch.object(comment_ai, "draft", draft),
            patch.object(comment_ai, "provider", provider),
            patch.object(mc, "post_context", post_context),
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

    async def test_answered_by_ai_publicly_and_thanked_in_direct_without_bothering_admins(self):
        self.draft = comment_ai.Draft("rahmat", "Rahmat, sog' bo'ling! 🌿", True, "gpt-5.4-mini",
                                      "Izohingiz uchun rahmat! Mahsulotlarimizni ko'rib chiqing")
        await mc.ingest(self.bot, self.comment(text="🔥🔥🔥"), source="webhook")
        await self.settle()
        self.assertEqual(self.public, [("18000000000000001", "Rahmat, sog' bo'ling! 🌿")])
        self.assertEqual(len(self.private), 1)
        self.assertTrue(self.private[0][1].endswith("👉 https://t.me/ketoshopbot/shop"))
        row = self.db.rows[1]
        self.assertEqual((row["status"], row["private_sent"], row["ai_confident"]), ("ai_answered", True, True))
        self.assertEqual(self.bot.sent, [])                      # no card: the AI handled it

    async def test_one_direct_per_person(self):
        self.draft = comment_ai.Draft("rahmat", "Rahmat!", True, "gpt-5.4-mini", "Rahmat")
        await mc.ingest(self.bot, self.comment(comment_id="x1", text="Zo'r"), source="webhook")
        await mc.ingest(self.bot, self.comment(comment_id="x2", text="Yana zo'r"), source="webhook")
        await self.settle()
        self.assertEqual(len(self.public), 2)
        self.assertEqual(len(self.private), 1)

    async def test_health_question_with_a_safe_answer_goes_out(self):
        self.draft = comment_ai.Draft("salomatlik", "Glyuten bug'doydagi oqsil … shifokor bilan maslahatlashing 🌿",
                                      True, "gpt-5.4-mini", "")
        await mc.ingest(self.bot, self.comment(text="Glyuten nima o'zi?"), source="webhook")
        await self.settle()
        self.assertEqual(len(self.public), 1)
        self.assertEqual(self.bot.sent, [])

    async def test_no_second_reply_when_someone_already_answered(self):
        self.draft = comment_ai.Draft("rahmat", "Rahmat!", True, "gpt-5.4-mini")
        self.existing = "Sizga ham rahmat! 🌿"
        await mc.ingest(self.bot, self.comment(text="Zo'r"), source="webhook")
        await self.settle()
        self.assertEqual(self.public, [])
        self.assertEqual(self.db.rows[1]["status"], "answered")
        self.assertEqual(self.bot.sent, [])

    async def test_a_question_that_only_got_the_canned_direct_reply_is_answered(self):
        self.draft = comment_ai.Draft("manzil", "Toshkent, Oqsoy 1-tor ko'chasi, 2A 📍", True, "gpt-5.4-mini")
        self.existing = "Rahmat! Sizga Direct orqali javob yubordik 📩"
        await mc.ingest(self.bot, self.comment(text="Manzil qayerda?"), source="webhook")
        await self.settle()
        self.assertEqual(self.public, [("18000000000000001", "Toshkent, Oqsoy 1-tor ko'chasi, 2A 📍")])

    async def test_what_the_ai_cannot_answer_comes_to_the_admins(self):
        self.draft = comment_ai.Draft("shikoyat", "Uzr so'raymiz 🙏", False, "gpt-5.4-mini")
        await mc.ingest(self.bot, self.comment(text="Buyurtmam 3 kundan beri kelmadi!"), source="webhook")
        await self.settle()
        self.assertEqual(self.public, [])
        self.assertEqual(len(self.bot.sent), 2)                  # one card per admin
        text, kb = self.bot.sent[0][1], self.bot.sent[0][2]
        self.assertIn("AI loyiha", text)
        self.assertEqual(buttons(kb), ["mc:ok:1", "mc:ed:1", "mc:dm:1", "mc:t:narx:1", "mc:t:yetkazish:1",
                                       "mc:t:bot:1", "mc:hide:1", "mc:seen:1", "mc:no:1"])

    async def test_direct_goes_first_then_the_public_reply(self):
        self.draft = comment_ai.Draft("rahmat", "Rahmat!", True, "gpt-5.4-mini", "Rahmat")
        await mc.ingest(self.bot, self.comment(text="Zo'r"), source="webhook")
        await self.settle()
        self.assertEqual(self.order, ["private", "public"])

    async def test_failed_sends_are_retried_once_after_the_fix(self):
        await self.db.insert_meta_comment(dict(self.comment(comment_id="sub1", parent_id="top1", text="Narxi?"),
                                               ai_confident=True, ai_draft="120 000 so'm 🌿",
                                               note="❌ AI yubora olmadi: [100] (#100) Field is only available "
                                                    "for top-level comments."))
        # 2026-11-11: the first run started before the token was loaded and
        # spent its one chance on "[no_token]" — without a token, wait.
        with patch.object(mc, "load_token", AsyncMock()), patch.object(mc, "token", lambda: ""):
            self.assertEqual(await mc.retry_failed_once(self.bot), 0)
        self.assertEqual(self.public, [])
        with patch.object(mc, "load_token", AsyncMock()), patch.object(mc, "token", lambda: "T"):
            self.assertEqual(await mc.retry_failed_once(self.bot), 1)
            self.assertEqual(self.public, [("sub1", "120 000 so'm 🌿")])
            self.assertEqual(self.db.rows[1]["status"], "ai_answered")
            self.assertEqual(await mc.retry_failed_once(self.bot), 0)            # once

    async def test_plain_questions_get_the_template_when_the_ai_is_unsure(self):
        # 2026-11-12: «Narxi qancha», «Нархи» waited for an admin.
        self.draft = comment_ai.Draft("narx", "…", False, "gpt-5.4-mini")
        await mc.ingest(self.bot, self.comment(text="Narxi qancha"), source="webhook")
        await self.settle()
        self.assertEqual(len(self.public), 1)
        self.assertIn("@ketoshopbot", self.public[0][1])
        self.assertEqual(self.bot.sent, [])
        self.assertEqual(self.db.rows[1]["status"], "ai_answered")

    async def test_health_or_complaint_still_go_to_the_admins(self):
        self.draft = comment_ai.Draft("salomatlik", "…", False, "gpt-5.4-mini")
        await mc.ingest(self.bot, self.comment(text="Diabetga mumkinmi?"), source="webhook")
        await self.settle()
        self.assertEqual(self.public, [])
        self.assertEqual(len(self.bot.sent), 2)

    async def test_spam_gets_nothing(self):
        self.draft = comment_ai.Draft("spam", "", True, "gpt-5.4-mini")
        await mc.ingest(self.bot, self.comment(text="Mening sahifamga obuna bo'ling!!!"), source="webhook")
        await self.settle()
        self.assertEqual((self.public, self.private, self.bot.sent), ([], [], []))
        self.assertEqual(self.db.rows[1]["status"], "skipped")

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

    async def test_old_comments_are_answered_too_but_never_ping_admins(self):
        old = datetime.utcnow() - timedelta(days=10)
        self.draft = comment_ai.Draft("rahmat", "Раҳмат!", True, "gpt-5.4-mini")
        await mc.ingest(self.bot, self.comment(comment_id="a", text="Раҳмат", created_at=old),
                        source="backfill", backfill=True)
        await self.settle()
        self.draft = comment_ai.Draft("boshqa", "…", False, "gpt-5.4-mini")
        await mc.ingest(self.bot, self.comment(comment_id="b", text="Бу нима?", created_at=old),
                        source="backfill", backfill=True)
        await mc.ingest(self.bot, self.comment(comment_id="c", text="Rahmat", created_at=old),
                        source="backfill", our_reply="Sizga ham rahmat!", backfill=True)
        await self.settle()
        self.assertEqual(self.public, [("a", "Раҳмат!")])
        self.assertEqual(self.private, [])                      # older than 7 days: Meta allows no Direct
        statuses = {r["comment_id"]: r["status"] for r in self.db.rows.values()}
        self.assertEqual(statuses, {"a": "ai_answered", "b": "new", "c": "answered"})
        self.assertEqual(self.bot.sent, [])                     # the unanswerable old one waits in /izohlar

    async def test_catch_up_answers_comments_from_before_this_change(self):
        # Rows the old rules left waiting (ai_confident is NULL), with cards out.
        for cid, text in (("p", "Narxi qancha?"), ("q", "Toshkentga yetkazasizlarmi?")):
            await self.db.insert_meta_comment(dict(self.comment(comment_id=cid, text=text),
                                                   tg_messages=[{"c": ADMIN, "m": 7}]))
        self.draft = comment_ai.Draft("narx", "Bodom uni 500gr — 120 000 so'm 🌿", True, "gpt-5.4-mini")
        stats = await mc.catch_up(self.bot)
        self.assertEqual(stats["auto"], 2)
        self.assertEqual(len(self.public), 2)
        self.assertEqual(self.bot.sent, [])                     # no new cards…
        self.assertEqual(len(self.bot.edits), 2)                # …the old ones now say the AI answered
        self.assertIn("🤖 AI javob berdi", self.bot.edits[0][2])
        again = await mc.catch_up(self.bot)
        self.assertEqual(sum(again.values()), 0)

    async def test_one_answer_for_the_same_text_tagging_different_people(self):
        self.draft = comment_ai.Draft("boshqa", "Ma'lumot uchun rahmat! 🌿", True, "gpt-5.4-mini")
        for cid, tag in (("t1", "@ali"), ("t2", "@vali"), ("t3", "@gani")):
            await self.db.insert_meta_comment(self.comment(comment_id=cid, text=f"{tag} Bug'doyda kimyoviy moddalar ko'p"))
        stats = await mc.catch_up(self.bot)
        self.assertEqual((stats["auto"], stats["repeat"]), (1, 2))
        self.assertEqual(len(self.public), 1)

    async def test_the_ai_sees_the_post_it_is_under(self):
        self.posts["18100000000000009"] = ("Bodom uni 500gr — keto pishiriqlar uchun", "https://cdn.example/thumb.jpg")
        self.draft = comment_ai.Draft("narx", "Bodom uni 500gr — 120 000 so'm 🌿", True, "gpt-5.4-mini")
        await mc.ingest(self.bot, self.comment(text="Narxi qancha?"), source="webhook")
        await self.settle()
        row = self.seen_rows[0]
        self.assertEqual((row["post_caption"], row["post_image"]),
                         ("Bodom uni 500gr — keto pishiriqlar uchun", "https://cdn.example/thumb.jpg"))

    async def test_ai_hiccup_is_retried_later_without_a_card(self):
        self.ai = "openai"               # AI is configured, but this call returned nothing
        await mc.ingest(self.bot, self.comment(text="Narxi qancha?"), source="webhook")
        await self.settle()
        self.assertEqual(self.bot.sent, [])
        self.assertIsNone(self.db.rows[1]["ai_confident"])      # catch_up will try again

    async def test_report_groups_answers_by_post_and_explains_the_rest(self):
        today = datetime.utcnow()
        rows_today = [
            {"platform": "ig", "post_link": "https://www.instagram.com/reel/AAA/", "media_id": "m1",
             "ad_name": None, "text": "Narxi?", "reply_text": "120 000 so'm", "private_sent": True},
            {"platform": "ig", "post_link": "https://www.instagram.com/reel/AAA/", "media_id": "m1",
             "ad_name": None, "text": "Zo'r", "reply_text": "Rahmat!", "private_sent": False},
            {"platform": "fb", "post_link": "https://www.facebook.com/1_2", "media_id": "1_2",
             "ad_name": "Kepak", "text": "Manzil?", "reply_text": "Oqsoy 1-tor", "private_sent": True},
        ]
        rows_open = [{"platform": "ig", "username": "u1", "text": "Buyurtmam kelmadi", "post_link": None,
                      "ai_confident": False, "category": "shikoyat", "note": None},
                     {"platform": "ig", "username": "u2", "text": "?", "post_link": None,
                      "ai_confident": None, "category": None, "note": None}]

        async def report(scope, limit=500):
            return rows_today if scope == "today" else rows_open
        with patch.object(database, "meta_comments_report", report):
            text = "\n".join(await mc.report_texts())
        self.assertIn("AI bugun javob berdi: 3 ta</b> (📩 Direct: 2)", text)
        self.assertIn("reel/AAA</a> — <b>2</b> ta", text)
        self.assertIn("📣 Kepak — <b>1</b> ta", text)
        self.assertIn("Javob bera olmagan: 2 ta", text)
        self.assertIn("AI aniq javob topolmadi (⚠️ Tanqid / shikoyat)", text)
        self.assertIn("AI hali ko'rmagan", text)

    async def test_old_cards_are_deleted_once(self):
        await self.db.insert_meta_comment(dict(self.comment(comment_id="k1"),
                                               tg_messages=[{"c": ADMIN, "m": 11}, {"c": 6950127923, "m": 12}]))
        await self.db.insert_meta_comment(dict(self.comment(comment_id="k2"), tg_messages=[{"c": ADMIN, "m": 13}]))
        self.assertEqual(await mc.cleanup_cards_once(self.bot), 3)
        self.assertEqual(sorted(self.bot.deleted), [(ADMIN, 11), (ADMIN, 13), (6950127923, 12)])
        self.assertTrue(all(r["tg_messages"] == [] for r in self.db.rows.values()))
        self.assertEqual(await mc.cleanup_cards_once(self.bot), 0)         # only once

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


class ProviderTest(unittest.IsolatedAsyncioTestCase):
    """Egasi, 2026-11-09: "antropic emas, gpt api bor" — GPT birinchi."""

    async def pick(self, bot_key="", env=None):
        with patch.dict(os.environ, env or {}, clear=False), \
             patch.object(comment_ai, "_openai_key", AsyncMock(return_value=bot_key)):
            return await comment_ai.provider()

    async def test_gpt_first(self):
        self.assertEqual(await self.pick("sk-bot", {"ANTHROPIC_API_KEY": "a"}), "openai")
        self.assertEqual(await self.pick("sk-bot", {"ANTHROPIC_API_KEY": ""}), "openai")

    async def test_claude_only_without_a_gpt_key_or_when_asked(self):
        self.assertEqual(await self.pick("", {"ANTHROPIC_API_KEY": "a"}), "anthropic")
        self.assertEqual(await self.pick("sk", {"ANTHROPIC_API_KEY": "a", "COMMENT_AI_PROVIDER": "anthropic"}),
                         "anthropic")
        self.assertEqual(await self.pick("", {"ANTHROPIC_API_KEY": ""}), "")

    async def test_the_ai_sellers_key_is_used(self):
        import ai_sales
        seller = SimpleNamespace(name="openai", api_key="sk-from-ai-kalit")
        with patch.object(ai_sales, "_load_settings", AsyncMock(return_value={})), \
             patch.object(ai_sales, "PROVIDER", seller), patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env"}):
            self.assertEqual(await comment_ai._openai_key(), "sk-from-ai-kalit")
        with patch.object(ai_sales, "_load_settings", AsyncMock(return_value={})), \
             patch.object(ai_sales, "PROVIDER", None), patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env"}):
            self.assertEqual(await comment_ai._openai_key(), "sk-env")


class FakeResponses:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    async def create(self, **kw):
        self.calls.append(kw)
        return self.replies.pop(0)


def gpt_reply(payload, refusal=False, status="completed"):
    part = SimpleNamespace(type="refusal" if refusal else "output_text")
    return SimpleNamespace(output_text="" if refusal else json.dumps(payload), status=status,
                           output=[SimpleNamespace(type="message", content=[part])],
                           usage=SimpleNamespace(input_tokens=900, input_tokens_details=SimpleNamespace(cached_tokens=800),
                                                 output_tokens=40))


class GptDraftTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import openai
        self.usage = AsyncMock()
        self.made = []
        self.responses = FakeResponses([])

        def factory(**kw):
            self.made.append(kw)
            return SimpleNamespace(responses=self.responses)

        comment_ai._openai_client = None
        for p in (patch.object(comment_ai, "provider", AsyncMock(return_value="openai")),
                  patch.object(comment_ai, "_openai_key", AsyncMock(return_value="sk-test")),
                  patch.object(comment_ai, "catalog_text", AsyncMock(return_value="- Bodom uni 500gr — 120 000 so'm")),
                  patch.object(database, "record_ai_usage", self.usage),
                  patch.object(openai, "AsyncOpenAI", factory),
                  patch.dict(os.environ, {"COMMENT_AI_OPENAI_MODEL": ""})):
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(lambda: setattr(comment_ai, "_openai_client", None))
        self.kb = {"manzil": "Toshkent", "yetkazish": "kuryer"}
        self.row = {"platform": "ig", "username": "dilnoza", "ad_name": "Glyuten", "text": "Narxi qancha?"}

    async def test_simple_comment_uses_the_ai_sellers_model_with_a_strict_schema(self):
        self.responses.replies = [gpt_reply({"category": "narx", "reply": "120 000 so'm 🌿", "confident": True})]
        d = await comment_ai.draft(self.row, self.kb)
        self.assertEqual((d.category, d.reply, d.confident, d.model), ("narx", "120 000 so'm 🌿", True, "gpt-5.4-mini"))
        call = self.responses.calls[0]
        self.assertEqual(call["model"], "gpt-5.4-mini")
        self.assertEqual(call["reasoning"], {"effort": "low"})
        fmt = call["text"]["format"]
        self.assertEqual((fmt["type"], fmt["strict"]), ("json_schema", True))
        self.assertIn("Bodom uni 500gr", call["instructions"])
        self.assertTrue(call["instructions"].startswith(comment_ai.RULES))   # stable prefix first → cached
        self.assertIn("Narxi qancha?", call["input"][0]["content"][0]["text"])
        self.assertEqual(len(call["input"][0]["content"]), 1)                 # no post image here
        self.assertEqual(self.made[0]["api_key"], "sk-test")
        args = self.usage.await_args.args
        self.assertEqual((args[0], args[1], args[2], args[3], args[4]),
                         ("gpt-5.4-mini · izohlar", "openai", 900, 800, 40))   # its own row in ai_usage

    async def test_post_caption_and_image_go_to_the_model(self):
        self.responses.replies = [gpt_reply({"category": "narx", "reply": "120 000 so'm", "confident": True, "dm": ""})]
        await comment_ai.draft(dict(self.row, post_caption="Bodom uni 500gr", post_image="https://cdn.example/p.jpg"),
                               self.kb)
        content = self.responses.calls[0]["input"][0]["content"]
        self.assertIn("POST MATNI:\nBodom uni 500gr", content[0]["text"])
        self.assertEqual(content[1], {"type": "input_image", "image_url": "https://cdn.example/p.jpg", "detail": "low"})

    async def test_rules_speak_as_the_team_and_never_ask_which_product(self):
        self.assertIn('"biz"', comment_ai.RULES)
        self.assertIn("HECH QACHON \"qaysi mahsulot?\"", comment_ai.RULES)
        self.assertIn("iltimos", comment_ai.RULES)

    async def test_complex_question_gets_a_second_deeper_pass_which_decides(self):
        self.responses.replies = [gpt_reply({"category": "salomatlik", "reply": "qisqa", "confident": True, "dm": "a"}),
                                  gpt_reply({"category": "salomatlik", "reply": "Shifokor bilan maslahatlashing 🌿",
                                             "confident": False, "dm": "Rahmat!"})]
        d = await comment_ai.draft(dict(self.row, text="Diabetga bo'ladimi?"), self.kb)
        self.assertEqual((d.category, d.reply, d.confident, d.dm),
                         ("salomatlik", "Shifokor bilan maslahatlashing 🌿", False, "Rahmat!"))
        self.assertEqual([c["reasoning"]["effort"] for c in self.responses.calls], ["low", "medium"])
        self.assertEqual(comment_ai.decide(d.category, d.confident, "avto"), "approve")
        self.assertIn("dm", self.responses.calls[0]["text"]["format"]["schema"]["required"])

    async def test_refusal_incomplete_or_garbage_means_no_draft(self):
        for reply in (gpt_reply({}, refusal=True), gpt_reply({"category": "narx", "reply": "x", "confident": True},
                                                             status="incomplete"),
                      SimpleNamespace(output_text="salom", status="completed", output=[], usage=None)):
            self.responses.replies = [reply]
            self.assertIsNone(await comment_ai.draft(self.row, self.kb))

    async def test_label(self):
        self.assertEqual(await comment_ai.provider_label(), "GPT (gpt-5.4-mini)")


class ClaudeDraftTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for p in (patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}),
                  patch.object(comment_ai, "provider", AsyncMock(return_value="anthropic")),
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

    async def test_complex_question_is_redrafted_by_sonnet(self):
        plain, beta = self.client(
            [claude_reply({"category": "salomatlik", "reply": "qisqa", "confident": True})],
            [claude_reply({"category": "rahmat", "reply": "Shifokor bilan maslahatlashing 🌿", "confident": True})])
        d = await comment_ai.draft(dict(self.row, text="Diabetga bo'ladimi?"), self.kb)
        self.assertEqual((d.category, d.model, d.confident), ("salomatlik", "claude-sonnet-5-5", True))
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
        with patch.object(comment_ai, "provider", AsyncMock(return_value="")):
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


class TokenHintsTest(unittest.IsolatedAsyncioTestCase):
    """2026-11-11: '(#100) … requires pages_read_engagement' — which of the two
    causes it is."""

    async def hints(self, granted, pages):
        async def graph(session, method, path, token, params=None, body=None):
            if path == "me/permissions":
                return {"data": [{"permission": p, "status": "granted"} for p in granted]
                        + [{"permission": "pages_messaging", "status": "declined"}]}
            if path == "me/accounts":
                return {"data": [{"id": i, "name": n} for i, n in pages]}
            raise AssertionError(path)
        with patch.object(mc, "_graph", graph):
            return await mc.token_hints("candidate")

    async def test_missing_permissions_are_named(self):
        text = await self.hints(["ads_read", "pages_show_list"], [(mc.PAGE_ID, "Keto market.uz")])
        self.assertIn("pages_read_engagement", text)
        self.assertIn("instagram_manage_comments", text)
        self.assertIn("pages_messaging", text)          # declined counts as missing
        self.assertNotIn("sahifasi bu tokenga ulanmagan", text)

    async def test_page_not_assigned(self):
        text = await self.hints(list(mc.NEEDED_PERMISSIONS), [("123", "Boshqa sahifa")])
        self.assertIn("sahifasi bu tokenga ulanmagan", text)
        self.assertIn("Boshqa sahifa", text)
        self.assertNotIn("yo'q ruxsatlar", text)

    async def test_nothing_to_say(self):
        self.assertEqual(await self.hints(list(mc.NEEDED_PERMISSIONS), [(mc.PAGE_ID, "Keto market.uz")]), "")


class SpendReportTest(unittest.IsolatedAsyncioTestCase):
    """Owner, 2026-11-11: AI spend every 3 hours, comment replies separately."""

    async def test_comment_spend_is_shown_apart(self):
        rows = [{"model": "gpt-5.4-mini", "requests": 120, "cost_usd": 0.42},
                {"model": "gpt-5.4-mini · izohlar", "requests": 37, "cost_usd": 0.031}]
        with patch.object(database, "get_ai_usage_today", AsyncMock(return_value=rows)),              patch.object(database, "get_ai_usage_month", AsyncMock(return_value={"cost_usd": 9.5})),              patch.object(database, "meta_comment_today", AsyncMock(return_value={"ai_answered": 30, "dms": 21})):
            text = await mc.spend_text(datetime(2026, 11, 11, 15, 0))
        self.assertIn("Jami AI sarfi: <b>$0.45</b>", text)
        self.assertIn("Izohlarga: $0.031 — 37 ta so'rov, 30 ta javob, 21 ta Direct", text)
        self.assertIn("Izohlarga AI javob berdi: 30 ta", text)          # the count comes first
        self.assertIn("Qolgani (AI sotuvchi va boshqalar): $0.42", text)
        self.assertIn("Oy boshidan: $9.50", text)
        self.assertIn("11.11, 15:00", text)

    def test_daytime_every_three_hours(self):
        self.assertEqual(mc.SPEND_HOURS, (9, 12, 15, 18, 21))


if __name__ == "__main__":
    unittest.main()
