"""💬 «Peshqadam mijozlarimiz fikri» (owner, 2026-11-28). The database is
faked; nothing reaches Telegram."""
import asyncio
import os
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import customer_portrait
import database
import keyboards
import mijozlar_fikri as mf


class Conn:
    def __init__(self, db):
        self.db = db

    async def execute(self, sql, *a):
        s = " ".join(sql.split())
        if s.startswith("INSERT INTO quote_picks"):
            self.db.setdefault(a[0], {"status": "shown", "post_text": a[1]})
        elif s.startswith("UPDATE quote_picks SET status = 'posted'"):
            self.db[a[0]]["status"] = "posted"

    async def fetch(self, sql, *a):
        if "FROM quote_picks" in sql and "status = 'approved'" in sql:
            return [{"key": k} for k, v in self.db.items() if v["status"] == "approved"]
        if "FROM quote_picks" in sql:
            return [{"key": k} for k in self.db]
        if "support_messages" in sql:
            return [{"id": 1, "user_id": 77, "text": "Rahmat, mahsulotlaringiz juda sifatli, yana olaman!",
                     "created_at": datetime.utcnow()},
                    {"id": 2, "user_id": 78, "text": "Buyurtmam hali kelmadi, qachon keladi? rahmat",
                     "created_at": datetime.utcnow()},
                    {"id": 3, "user_id": 79, "text": "Rahmat, mana kanal: https://t.me/xyz juda yoqdi",
                     "created_at": datetime.utcnow()}]
        return []

    async def fetchval(self, sql, *a):
        if "SELECT post_text FROM quote_picks" in sql:
            return self.db.get(a[0], {}).get("post_text")
        if "full_name FROM users" in sql:
            return "DILNOZA Karimova"
        return None

    async def fetchrow(self, sql, *a):
        if "UPDATE quote_picks SET status" in " ".join(sql.split()):
            k, status = a[0], a[1]
            if self.db.get(k, {}).get("status") == "shown":
                self.db[k]["status"] = status
                return {"key": k}
            return None
        if "FROM orders" in sql:
            return {"address": "Toshkent, Chilonzor 5", "latitude": None, "longitude": None}
        return None


class Pool:
    def __init__(self):
        self.db = {}

    def acquire(self):
        c = Conn(self.db)

        class Ctx:
            async def __aenter__(s):
                return c

            async def __aexit__(s, *e):
                return False
        return Ctx()


FEEDBACK = {
    "reviews": [
        {"id": 1, "rating": 5, "comment": "Bodom unidan keto pirog pishirdim, juda mazali chiqdi. Rahmat!",
         "created_at": datetime.utcnow().isoformat(), "user_id": 10, "product_id": 5,
         "product_name": "Bodom uni 500gr", "full_name": "Nafisa Aliyeva", "username": "nafisa", "internal": False},
        {"id": 2, "rating": 2, "comment": "Yaxshi emas, kech keldi va qadog'i yirtilgan edi",
         "created_at": datetime.utcnow().isoformat(), "user_id": 11, "internal": False},
        {"id": 3, "rating": 5, "comment": "Admin test izohi juda zo'r mahsulot",
         "created_at": datetime.utcnow().isoformat(), "user_id": 12, "internal": True},
        {"id": 4, "rating": 5, "comment": "Zo'r", "created_at": datetime.utcnow().isoformat(),
         "user_id": 13, "internal": False},
        {"id": 5, "rating": 5, "comment": "Raqamim +998 90 123 45 67, yana olaman, juda sifatli",
         "created_at": datetime.utcnow().isoformat(), "user_id": 14, "internal": False},
    ],
    "site": [], "nps": [],
}


class Base(unittest.TestCase):
    def setUp(self):
        mf._table_ready = True
        mf._cards.clear()
        self.pool = Pool()
        for target, attr, value in [
            (database, "pool", self.pool),
            (database, "get_feedback_overview", AsyncMock(return_value=FEEDBACK)),
            (database, "get_product", AsyncMock(return_value={"id": 5, "name": "Bodom uni 500gr", "is_active": 1})),
            (customer_portrait, "is_opted_out", AsyncMock(side_effect=lambda uid, *a: uid == 14 and False)),
            (mf, "ADMIN_IDS", [1, 2]),
            (mf, "REQUIRED_CHANNEL_ID", -100),
        ]:
            p = patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)


class CandidatesTest(Base):
    def test_only_good_public_texts(self):
        cs = asyncio.run(mf.candidates())
        keys = [c["key"] for c in cs]
        self.assertEqual(keys[0], "review:1")                     # 5★ with a story wins
        self.assertNotIn("review:2", keys)                        # 2★
        self.assertNotIn("review:3", keys)                        # shop account
        self.assertNotIn("review:4", keys)                        # too short
        self.assertIn("bot:sm:1", keys)                           # thanks sent to the bot
        self.assertNotIn("bot:sm:2", keys)                        # a complaint, even with «rahmat»
        self.assertNotIn("bot:sm:3", keys)                        # a link
        phone = next(c for c in cs if c["key"] == "review:5")
        self.assertNotIn("123 45 67", phone["text"])

    def test_already_shown_never_again(self):
        self.pool.db["review:1"] = {"status": "skipped", "post_text": ""}
        self.assertNotIn("review:1", [c["key"] for c in asyncio.run(mf.candidates())])


class PostTest(Base):
    def test_first_name_only_region_stars_product_link(self):
        c = asyncio.run(mf.candidates())[0]
        text = asyncio.run(mf.post_text(c))
        self.assertIn("Пешқадам мижозларимиз фикри", text)
        self.assertIn("<blockquote>Bodom unidan keto pirog", text)
        self.assertIn("— Нафиса, Тошкент шаҳри", text)
        self.assertNotIn("Aliyeva", text)
        self.assertNotIn("Алиева", text)
        self.assertNotIn("nafisa", text)
        self.assertIn("⭐⭐⭐⭐⭐", text)
        self.assertIn("#мижозларфикри", text)

    def test_names(self):
        self.assertEqual(mf.first_name("DILNOZA Karimova"), "Dilnoza")
        self.assertIsNone(mf.first_name("🌸🌸"))
        self.assertIsNone(mf.first_name(None))


class FlowTest(Base):
    def bot(self):
        bot = MagicMock()
        msgs = iter(range(100, 200))
        bot.send_message = AsyncMock(side_effect=lambda *a, **k: MagicMock(message_id=next(msgs)))
        bot.edit_message_reply_markup = AsyncMock()
        return bot

    def cb(self, bot, data, admin=1):
        cb = MagicMock()
        cb.from_user.id = admin
        cb.from_user.full_name = "Admin"
        cb.data = data
        cb.bot = bot
        cb.answer = AsyncMock()
        cb.message.chat.id = admin
        cb.message.message_id = 100
        cb.message.edit_reply_markup = AsyncMock()
        cb.message.answer = AsyncMock()
        return cb

    def test_offer_then_approve_posts_once(self):
        bot = self.bot()
        self.assertTrue(asyncio.run(mf.offer(bot)))
        self.assertEqual(bot.send_message.await_count, 2)            # both admins
        self.assertEqual(bot.send_message.await_args_list[0].args[0], 1)
        with patch.object(mf, "_now_tk", return_value=datetime(2026, 11, 29, 12)):
            asyncio.run(mf.on_button(self.cb(bot, "mfk:ok:review:1")))
            second = self.cb(bot, "mfk:ok:review:1", admin=2)
            asyncio.run(mf.on_button(second))
        channel = [c for c in bot.send_message.await_args_list if c.args[0] == -100]
        self.assertEqual(len(channel), 1)                            # first decision wins
        self.assertEqual(self.pool.db["review:1"]["status"], "posted")
        second.answer.assert_awaited_with("Bu izoh bo'yicha qaror qilingan.", show_alert=True)

    def test_night_approval_waits_for_morning(self):
        bot = self.bot()
        asyncio.run(mf.offer(bot))
        with patch.object(mf, "_now_tk", return_value=datetime(2026, 11, 29, 23)):
            asyncio.run(mf.on_button(self.cb(bot, "mfk:ok:review:1")))
        self.assertFalse([c for c in bot.send_message.await_args_list if c.args[0] == -100])
        with patch.object(mf, "_now_tk", return_value=datetime(2026, 11, 30, 9, 5)), \
                patch.object(database, "claim_release_notes", AsyncMock(return_value=True)):
            asyncio.run(mf._tick(bot))
        self.assertEqual(len([c for c in bot.send_message.await_args_list if c.args[0] == -100]), 1)

    def test_skip_offers_the_next_one(self):
        bot = self.bot()
        asyncio.run(mf.offer(bot))
        asyncio.run(mf.on_button(self.cb(bot, "mfk:next:review:1")))
        self.assertEqual(self.pool.db["review:1"]["status"], "skipped")
        self.assertEqual(len(self.pool.db), 2)                       # a second candidate was shown

    def test_non_admin_ignored(self):
        bot = self.bot()
        asyncio.run(mf.offer(bot))
        asyncio.run(mf.on_button(self.cb(bot, "mfk:ok:review:1", admin=999)))
        self.assertEqual(self.pool.db["review:1"]["status"], "shown")


class ScheduleTest(unittest.TestCase):
    def test_every_two_days_from_start(self):
        self.assertTrue(mf.is_day(date(2026, 11, 29)))
        self.assertFalse(mf.is_day(date(2026, 11, 30)))
        self.assertTrue(mf.is_day(date(2026, 12, 1)))
        self.assertFalse(mf.is_day(date(2026, 11, 27)))

    def test_command_published_for_admins(self):
        self.assertIn("mijoz_fikri", [c.command for c in keyboards.ADMIN_COMMANDS])
        self.assertNotIn("mijoz_fikri", [c.command for c in keyboards.BUYER_COMMANDS])


if __name__ == "__main__":
    unittest.main()
