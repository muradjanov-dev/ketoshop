"""Yangi foydalanuvchilar haqidagi xabar — har 5 tasi bitta xabarda (egasi, 2026-11-24)."""
import asyncio
import os
import unittest
import uuid
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
import referral_contest as rc


class TextTest(unittest.TestCase):
    def test_numbered_list_for_many_plain_for_one(self):
        many = rc.digest_text(["👤 A (ID 1)\n🔗 x", "👤 B (ID 2)\n🔗 y"])
        self.assertTrue(many.startswith("🆕 <b>2 ta yangi foydalanuvchi qo'shildi!</b>"))
        self.assertIn("1. 👤 A", many)
        self.assertIn("2. 👤 B", many)
        self.assertTrue(rc.digest_text(["👤 A"]).startswith("🆕 <b>Yangi foydalanuvchi qo'shildi!</b>"))
        self.assertTrue(rc.digest_text(["👤 A"], 1234).endswith("👥 Jami foydalanuvchilar: <b>1 234</b> ta"))


PG_URL = os.getenv("GAMES_PG_URL")


@unittest.skipUnless(PG_URL, "GAMES_PG_URL not set")
class PostgresTest(unittest.TestCase):
    def test_one_message_per_five_and_a_day_old_one_goes_alone(self):
        import asyncpg
        schema = "nu_" + uuid.uuid4().hex[:8]
        self.assertEqual(rc.DIGEST_SIZE, 10)
        loop = asyncio.new_event_loop()
        bot = Mock()
        bot.send_message = AsyncMock()

        async def go():
            admin = await asyncpg.connect(PG_URL)
            await admin.execute(f"CREATE SCHEMA {schema}")
            await admin.close()
            pool = await asyncpg.create_pool(PG_URL, min_size=1, max_size=2, server_settings={"search_path": schema})
            async with pool.acquire() as c:
                await c.execute("CREATE TABLE users (user_id BIGINT PRIMARY KEY);"
                                "INSERT INTO users SELECT generate_series(1, 321);")
            try:
                with patch.object(database, "pool", pool), patch.object(rc, "_digest_ready", False), \
                     patch.object(rc, "ADMIN_IDS", [1, 2]):
                    for i in range(9):
                        await rc.queue_new_user(bot, f"👤 U{i}")
                    before = bot.send_message.await_count
                    await rc.queue_new_user(bot, "👤 U9")
                    after_five = bot.send_message.await_count
                    await rc.queue_new_user(bot, "👤 U5")                 # waits again
                    async with pool.acquire() as c:
                        await c.execute("UPDATE new_user_digest SET created_at = created_at - interval '25 hours' "
                                        "WHERE sent_at IS NULL")
                    await rc.queue_new_user(bot, "👤 U6")                 # the oldest waited a day
                    return before, after_five, bot.send_message.await_count
            finally:
                await pool.close()
                admin = await asyncpg.connect(PG_URL)
                await admin.execute(f"DROP SCHEMA {schema} CASCADE")
                await admin.close()

        before, after_five, end = loop.run_until_complete(go())
        loop.close()
        self.assertEqual(before, 0)
        self.assertEqual(after_five, 2)                               # one message to each of 2 admins
        first = bot.send_message.await_args_list[0].args[1]
        self.assertIn("10 ta yangi foydalanuvchi", first)
        self.assertIn("10. 👤 U9", first)
        self.assertIn("👥 Jami foydalanuvchilar: <b>321</b> ta", first)
        self.assertEqual(end, 4)
        self.assertIn("2 ta yangi foydalanuvchi", bot.send_message.await_args_list[-1].args[1])


if __name__ == "__main__":
    unittest.main()
