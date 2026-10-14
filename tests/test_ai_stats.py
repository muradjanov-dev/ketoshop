"""AI hisobot (ai_stats.py): mavzu aniqlash, suhbat hisobi, hisobot matni — bazasiz."""
import asyncio
import os
import time
import unittest
from datetime import datetime

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ai_stats
import database


class _FakeConn:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, *args):
        self.calls.append(("execute", " ".join(sql.split())[:40], args))

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", " ".join(sql.split())[:40], args))
        return 77


class _FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return pool.conn

            async def __aexit__(self, *exc):
                return False
        return _Ctx()


class TopicTest(unittest.TestCase):
    def test_topics_in_every_language(self):
        self.assertEqual(ai_stats.classify("eritritol narxi qancha?"), ["narx"])
        self.assertIn("yetkazish", ai_stats.classify("qachon yetkazib berasizlar?"))
        self.assertIn("retsept", ai_stats.classify("bodom uni bilan retsept bering"))
        self.assertIn("keto", ai_stats.classify("menda qandli diabet bor, keto qilsam bo'ladimi?"))
        self.assertIn("shikoyat", ai_stats.classify("kecha buyurtma bergandim hali kelmadi"))
        self.assertIn("narx", ai_stats.classify("Сколько стоит миндальная мука?"))
        self.assertIn("narx", ai_stats.classify("эритритол борми? нархи қанча?"))
        self.assertEqual(ai_stats.classify("[Mijoz telefon raqamini yubordi: +998]"), [])
        self.assertEqual(ai_stats.classify("Assalomu alaykum"), [])


class RecordTurnTest(unittest.TestCase):
    def setUp(self):
        self.conn = _FakeConn()
        self.saved_pool = database.pool
        database.pool = _FakePool(self.conn)
        ai_stats._open.clear()
        ai_stats._table_ready = True

    def tearDown(self):
        database.pool = self.saved_pool
        ai_stats._open.clear()

    def test_one_conversation_until_an_hour_of_silence(self):
        asyncio.run(ai_stats.record_turn(5, "bot", "psillium bormi"))
        asyncio.run(ai_stats.record_turn(5, "bot", "qachon yetkazasiz"))
        kinds = [c[0] for c in self.conn.calls]
        self.assertEqual(kinds, ["fetchval", "execute"])       # INSERT, keyin UPDATE
        self.assertEqual(self.conn.calls[1][2], (77, ["yetkazish"]))
        ai_stats._open[("bot", 5)] = (77, time.time() - ai_stats.NEW_CONVERSATION_AFTER - 1)
        asyncio.run(ai_stats.record_turn(5, "bot", "salom"))
        self.assertEqual(self.conn.calls[-1][0], "fetchval")   # yangi suhbat

    def test_bot_and_group_are_counted_apart(self):
        asyncio.run(ai_stats.record_turn(5, "bot", "salom"))
        asyncio.run(ai_stats.record_turn(5, "group", "narxi qancha"))
        self.assertEqual([c[0] for c in self.conn.calls], ["fetchval", "fetchval"])


class ReportTextTest(unittest.TestCase):
    def test_report_answers_how_many_people_and_which_topics(self):
        stats = {
            "periods": [("bugun", {"people": 12, "conversations": 14, "messages": 61, "group_conversations": 3}),
                        ("7 kun", {"people": 40, "conversations": 52, "messages": 230, "group_conversations": 9}),
                        ("jami", {"people": 40, "conversations": 52, "messages": 230, "group_conversations": 9})],
            "topics": [("narx", 30), ("yetkazish", 12), ("boshqa", 5)],
            "interests": [("Bodom uni 500gr", 9), ("Eritritol 500gr", 7)],
            "people_with_notes": 55,
            "orders": [("bugun", 2, 375000.0), ("7 kun", 6, 1200000.0), ("jami", 6, 1200000.0)],
            "questions": 3,
            "since": datetime(2026, 10, 14, 6, 0),
        }
        text = ai_stats.report_text(stats)
        for expected in ("Bugun:</b> 12 ta mijoz", "14 ta suhbat (guruhda 3)", "61 ta javob",
                         "💰 Narx / mahsulot bormi — 30", "🚚 Yetkazish — 12", "💬 Boshqa",
                         "Bodom uni 500gr — 9", "55 ta mijoz", "bugun — 2 ta, 375 000 so'm",
                         "3 ta</b> — /ai_bilim", "14.10.2026 dan"):
            self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
