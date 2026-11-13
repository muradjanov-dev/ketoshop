"""Qayta aloqa (comment_followup.py, 2026-11-13): kimga, qachon, nima yoziladi."""
import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://ci:ci@localhost:5432/ci")
os.environ.setdefault("BOT_TOKEN", "123456:CI-TOKEN")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import comment_ai  # noqa: E402
import comment_followup as cf  # noqa: E402
import database  # noqa: E402
import meta_comments as mc  # noqa: E402

NOON = datetime(2026, 11, 13, 12, 0)          # Toshkent vaqti
NIGHT = datetime(2026, 11, 13, 22, 0)


def row(key, cid, text="Narxi qancha?", parent=None):
    return {"id": key, "comment_id": cid, "parent_id": parent, "platform": "ig", "media_id": "M1",
            "username": f"user{key}", "text": text, "reply_text": "135 000 so'm",
            "created_at": datetime.utcnow() - timedelta(days=40), "status": "answered"}


class SendOneTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.state = {"followup_on": True, "kb": {}}
        self.stats = {"today": 0, "total": 0, "skipped": 0, "queue": 2, "last": []}
        self.candidates = [row(1, "c1"), row(2, "c2")]
        self.marked, self.sent = [], []
        self.texts = {}

        async def mark(key, text):
            self.marked.append((key, text))

        async def reply_public(session, ident, c, text):
            if c["comment_id"] in getattr(self, "broken", ()):
                raise mc.GraphError(100, "comment gone")
            self.sent.append((c["comment_id"], text))
            return "r1"

        async def compose(r, kb=None, extra=None):
            return self.texts.get(r["comment_id"])

        for p in [
            patch.object(database, "get_meta_comments_state", AsyncMock(side_effect=lambda: dict(self.state))),
            patch.object(database, "meta_comment_followup_stats", AsyncMock(side_effect=lambda d: self.stats)),
            patch.object(database, "meta_comment_followup_candidates",
                         AsyncMock(side_effect=lambda d, n: self.candidates[:n])),
            patch.object(database, "mark_meta_comment_followup", mark),
            patch.object(mc, "load_token", AsyncMock()), patch.object(mc, "token", lambda: "T"),
            patch.object(mc, "identity", AsyncMock(return_value={"page_token": "T"})),
            patch.object(mc, "reply_public", reply_public),
            patch.object(cf, "compose", compose),
            patch.object(cf, "new_products_text", AsyncMock(return_value="")),
            patch.object(cf, "offers_text", AsyncMock(return_value="")),
        ]:
            p.start()
            self.addCleanup(p.stop)

    async def test_sends_one_reply_under_the_old_comment(self):
        self.texts = {"c1": "Agar olgan bo'lsangiz, qanday chiqdi? Retseptlar @ketoshopbot da 🌿"}
        self.assertEqual(await cf.send_one(None, NOON), "sent")
        self.assertEqual(self.sent, [("c1", self.texts["c1"])])
        self.assertEqual(self.marked, [(1, self.texts["c1"])])

    async def test_ai_declines_then_the_next_person_gets_it(self):
        self.texts = {"c2": "Ko'rdingizmi? Yangi mahsulotlarimiz bor 🌿"}
        self.assertEqual(await cf.send_one(None, NOON), "sent")
        self.assertEqual(self.sent, [("c2", self.texts["c2"])])
        self.assertEqual(self.marked, [(1, ""), (2, self.texts["c2"])])   # c1 never picked again

    async def test_deleted_comment_is_marked_and_skipped(self):
        self.texts = {"c1": "Salom 🌿", "c2": "Salom 🌿"}
        self.broken = {"c1"}
        self.assertEqual(await cf.send_one(None, NOON), "sent")
        self.assertEqual(self.marked, [(1, ""), (2, "Salom 🌿")])

    async def test_quiet_hours_cap_off_and_no_token_send_nothing(self):
        self.texts = {"c1": "Salom 🌿"}
        self.assertEqual(await cf.send_one(None, NIGHT), "quiet")
        self.stats["today"] = cf.DAILY
        self.assertEqual(await cf.send_one(None, NOON), "cap")
        self.stats["today"] = 0
        self.state["followup_on"] = False
        self.assertEqual(await cf.send_one(None, NOON), "off")
        self.state["followup_on"] = True
        with patch.object(mc, "token", lambda: ""):
            self.assertEqual(await cf.send_one(None, NOON), "no_token")
        self.assertEqual((self.sent, self.marked), ([], []))

    async def test_empty_queue(self):
        self.candidates = []
        self.assertEqual(await cf.send_one(None, NOON), "none")


class ComposeTest(unittest.IsolatedAsyncioTestCase):
    async def test_ai_gets_the_old_comment_post_and_new_products(self):
        seen = {}

        async def ask(key, model, instructions, user, effort, image=None, schema=None):
            seen.update(instructions=instructions, user=user, image=image, schema=schema)
            return {"reply": "Assalomu alaykum! Kepakli un hozir ham bizda bor 🌾 Agar olgan bo'lsangiz, "
                             "nima pishirdingiz? Retseptlar @ketoshopbot da.", "skip": False}

        with patch.object(comment_ai, "provider", AsyncMock(return_value="openai")), \
                patch.object(comment_ai, "_openai_key", AsyncMock(return_value="k")), \
                patch.object(comment_ai, "catalog_text", AsyncMock(return_value="- Kepakli bug'doy uni — 10 000 so'm")), \
                patch.object(comment_ai, "_ask_openai", ask), \
                patch.object(mc, "post_context", AsyncMock(return_value=("Kepak reel", "https://img/1.jpg"))):
            text = await cf.compose(row(1, "c1"), {}, ("- Bodom uni — 90 000 so'm", "- 2 ta un → 1 sovg'a"))
        self.assertIn("@ketoshopbot", text)
        self.assertIs(seen["schema"], comment_ai.FOLLOWUP_SCHEMA)
        self.assertEqual(seen["image"], "https://img/1.jpg")
        self.assertIn("ESKI IZOH:\nNarxi qancha?", seen["user"])
        self.assertIn("Kepak reel", seen["user"])
        self.assertIn("Bodom uni", seen["instructions"])
        self.assertIn("2 ta un", seen["instructions"])

    async def test_skip_means_no_text(self):
        with patch.object(comment_ai, "provider", AsyncMock(return_value="openai")), \
                patch.object(comment_ai, "_openai_key", AsyncMock(return_value="k")), \
                patch.object(comment_ai, "catalog_text", AsyncMock(return_value="")), \
                patch.object(comment_ai, "_ask_openai", AsyncMock(return_value={"reply": "", "skip": True})), \
                patch.object(mc, "post_context", AsyncMock(return_value=("", ""))):
            self.assertIsNone(await cf.compose(row(1, "c1"), {}, ("", "")))

    async def test_no_gpt_no_followup(self):
        with patch.object(comment_ai, "provider", AsyncMock(return_value="anthropic")), \
                patch.object(mc, "post_context", AsyncMock(return_value=("", ""))):
            self.assertIsNone(await cf.compose(row(1, "c1"), {}, ("", "")))


class RulesTest(unittest.TestCase):
    def test_no_manipulation_and_bot_for_recipes(self):
        rules = comment_ai.FOLLOWUP_RULES
        for phrase in ("Shoshiltirma", "faqat bugun", "buyurma", "Boshqa chegirma o'ylab topma",
                       "@ketoshopbot", "Agar olgan bo'lsangiz", "skip=true", "\"biz\""):
            self.assertIn(phrase, rules)

    def test_direct_in_cyrillic(self):
        out = comment_ai.finalize("Тел номер беринг", "Agar xohlasangiz, Direct'ga ham yo'llab qo'yamiz 🙂")
        self.assertIn("Директга", out)
        self.assertNotIn("c", out.replace("@", ""))

    def test_admin_menu_has_the_command(self):
        import keyboards
        self.assertIn("izoh_qayta", str(keyboards.__dict__))


class NewProductsTest(unittest.IsolatedAsyncioTestCase):
    async def test_only_recent_in_stock_retail(self):
        now = datetime.utcnow()
        products = [
            {"name": "Bodom uni", "created_at": now - timedelta(days=5), "quantity": 3, "price": 90000},
            {"name": "Eski un", "created_at": now - timedelta(days=200), "quantity": 3, "price": 10000},
            {"name": "Tugagan", "created_at": now - timedelta(days=2), "quantity": 0, "price": 10000},
            {"name": "Optom", "created_at": now - timedelta(days=2), "quantity": 9, "price": 10000, "b2b_only": 1},
        ]
        with patch.object(database, "admin_list_products", AsyncMock(return_value=products)), \
                patch("manual_order.shelf_price", lambda p: p["price"]):
            text = await cf.new_products_text()
        self.assertEqual(text, "- Bodom uni — 90 000 so'm")


if __name__ == "__main__":
    unittest.main()
