"""Fikr so'rash (feedback_ask.py, egasi 2026-11-16): 2 kunda bir AI xaridordan
oldingi mahsuloti haqida qisqa so'raydi — kuniga xabar chegarasi ichida."""
import asyncio
import os
import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ai_memory  # noqa: E402
import database  # noqa: E402
import feedback_ask as fa  # noqa: E402

NOW = datetime.utcnow()
DELIVERED = {"id": 1, "status": "delivered", "delivered_at": NOW - timedelta(days=5),
             "items": '[{"product_id": 7, "name": "Bodom uni 500gr", "quantity": 1}]'}


def run(coro):
    return asyncio.run(coro)


class TextTest(unittest.TestCase):
    def test_every_other_day(self):
        d = date(2026, 11, 16)
        self.assertNotEqual(fa.is_ask_day(d), fa.is_ask_day(d + timedelta(days=1)))
        self.assertEqual(fa.is_ask_day(d), fa.is_ask_day(d + timedelta(days=2)))

    def test_templates_in_every_language(self):
        topic = {"product_id": 7, "name": "Bodom uni 500gr"}
        # Egasi, 2026-11-26: "avval bizdan … olgan ekansiz, ma'qul keldimi? … qisqaroq".
        uz, ru = fa.template(topic, "uz"), fa.template(topic, "ru")
        self.assertIn("Avval bizdan Bodom uni 500gr olgandingiz — ma'qul keldimi?", uz)
        self.assertIn("Вы брали у нас Bodom uni 500gr — понравилось?", ru)
        self.assertLessEqual(len(uz), fa.TEXT_MAX)
        self.assertLessEqual(len(ru), fa.TEXT_MAX)
        self.assertIn("маъқул келдими", fa.template(topic, "uz_cyr"))
        self.assertIn("qanday mahsulot qo'shsak", fa.template(None, "uz"))

    def test_ai_text_is_checked(self):
        topic = {"product_id": 7, "name": "Bodom uni 500gr"}
        good = "Bodom uni bilan nima pishirdingiz, yoqdimi? 😊 Fikringiz biz uchun muhim — shu yerga yozing."
        self.assertTrue(fa.acceptable(good, topic, "uz"))
        self.assertFalse(fa.acceptable(good + " https://t.me/x", topic, "uz"))            # no links
        self.assertFalse(fa.acceptable("Yoqdimi? 😊", topic, "uz"))                         # names the product
        self.assertFalse(fa.acceptable("Как вам бодом уни?", topic, "uz"))                 # right script
        self.assertFalse(fa.acceptable("a" * 400, None, "uz"))                              # short

    def test_no_key_means_the_template(self):
        with patch("comment_ai._openai_key", AsyncMock(return_value="")):
            self.assertEqual(run(fa.compose(None, "ru")), fa.template(None, "ru"))


class TopicTest(unittest.TestCase):
    def topic(self, orders, notes=(), reviews=()):
        with patch.object(database, "get_user_orders", AsyncMock(return_value=list(orders))), \
                patch.object(ai_memory, "notes", AsyncMock(return_value=list(notes))), \
                patch.object(ai_memory, "_reviews", AsyncMock(return_value=list(reviews))):
            return run(fa.topic_for(5))

    def test_a_delivered_product_not_yet_asked(self):
        self.assertEqual(self.topic([DELIVERED])["name"], "Bodom uni 500gr")

    def test_asked_or_reviewed_products_are_skipped_then_general_once_a_month(self):
        asked = [{"kind": "asked", "product_id": 7, "text": "Bodom uni 500gr", "created_at": NOW}]
        self.assertIsNone(self.topic([DELIVERED], asked))                                    # general ask
        self.assertIsNone(self.topic([DELIVERED], reviews=[{"product_id": 7}]))
        general = asked + [{"kind": "asked", "product_id": None, "text": fa.GENERAL_NOTE,
                            "created_at": NOW - timedelta(days=3)}]
        self.assertIs(self.topic([DELIVERED], general), False)                              # nothing this time

    def test_no_delivered_order_nothing_to_ask(self):
        self.assertIs(self.topic([dict(DELIVERED, status="pending")]), False)


class RoundTest(unittest.TestCase):
    def test_round_respects_the_cap_skips_staff_and_marks_only_after_sending(self):
        sent, marked = [], []

        async def topic_for(uid):
            return {"product_id": 7, "name": "Bodom uni 500gr"} if uid != 3 else False

        async def send(bot, uid, text):
            sent.append(uid)
            return uid != 4                                                    # 4 blocked the bot

        async def mark(uid, topic):
            marked.append(uid)

        admin = next(iter(fa.ADMIN_IDS), 999)
        with patch.object(database, "get_user_ids_with_orders", AsyncMock(return_value=[1, 2, 3, 4, admin])), \
                patch.object(database, "get_user_languages", AsyncMock(return_value={})), \
                patch.object(database, "claim_user_push", AsyncMock(side_effect=lambda uid, kind, *a: uid != 2)), \
                patch.object(fa, "topic_for", topic_for), patch.object(fa, "_send", send), \
                patch.object(fa, "_mark", mark), patch.object(fa, "SEND_DELAY", 0), \
                patch.object(fa, "compose", AsyncMock(return_value="Bodom uni qanday chiqdi?")):
            stats = run(fa.send_round(NS()))
        self.assertEqual(sent, [1, 4])
        self.assertEqual(marked, [1])
        self.assertEqual((stats["sent"], stats["capped"], stats["nothing"], stats["failed"]), (1, 1, 1, 1))

    def test_tips_skip_a_user_who_got_the_feedback_ask_today(self):
        src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "broadcast.py"),
                   encoding="utf-8").read()
        self.assertIn('push_cap.claim(uid, "tips", unless=("fikr",))', src)


if __name__ == "__main__":
    unittest.main()
