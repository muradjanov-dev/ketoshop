"""Bir martalik tasdiqlangan xabar (customer_notice.py). Telegram'ga ulanmaydi."""
import asyncio
import os
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import customer_notice as cn
import database


class NoticeTest(unittest.TestCase):
    def tick(self, hour, claimed=True):
        bot = MagicMock()
        bot.send_message = AsyncMock()
        with patch.object(cn, "_now_tk", lambda: datetime(2026, 11, 21, hour, 0)), \
             patch.object(cn, "ADMIN_IDS", [1]), \
             patch.object(database, "claim_release_notes", AsyncMock(return_value=claimed)):
            done = asyncio.run(cn._tick(bot))
        return done, bot

    def test_sent_once_in_daytime_admins_told(self):
        done, bot = self.tick(10)
        self.assertTrue(done)
        chats = [c.args[0] for c in bot.send_message.await_args_list]
        self.assertEqual(chats, [6908484737, 1, 2020857190, 1, 7386577240, 1])
        self.assertIn("жарима қўймайди", bot.send_message.await_args_list[0].args[1])
        rye = bot.send_message.await_args_list[4].args[1]
        self.assertIn("жавдар уни", rye)
        self.assertIn("муаммо ҳал бўлдими", rye)
        paid = bot.send_message.await_args_list[2].args[1]
        self.assertIn("229 900", paid)
        self.assertIn("Повторно платить ничего не нужно", paid)

    def test_paid_customer_ai_is_held_until_the_admins_answer(self):
        import ai_sales
        from datetime import datetime
        with patch.object(cn, "AI_HOLD", {555: datetime(2099, 1, 1)}):
            cn.hold_ai()
        self.addCleanup(ai_sales.resume, 555)
        self.assertTrue(ai_sales._is_paused(555))

    def test_not_at_night_not_twice(self):
        done, bot = self.tick(7)
        self.assertFalse(done)
        bot.send_message.assert_not_awaited()
        done, bot = self.tick(10, claimed=False)
        self.assertTrue(done)
        bot.send_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
