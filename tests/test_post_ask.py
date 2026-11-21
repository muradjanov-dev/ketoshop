"""«Savolingiz bo'lsa — botga yozing» har post oxirida (egasi, 2026-11-21)."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from aiogram.methods import SendMessage, SendPhoto

import channel_signature
import database
import post_ask
import push_cap

CHANNEL = -1001


def run(coro):
    return asyncio.run(coro)


class LineTest(unittest.TestCase):
    def setUp(self):
        self.p = [patch.object(channel_signature, "REQUIRED_CHANNEL_ID", CHANNEL),
                  patch.object(database, "get_user_language", AsyncMock(return_value="ru"))]
        for p in self.p:
            p.start()

    def tearDown(self):
        for p in self.p:
            p.stop()

    def test_channel_post_gets_the_line_then_the_signature(self):
        async def go():
            m = await post_ask.add_line(SendMessage(chat_id=CHANNEL, text="Keto fakt"))
            return channel_signature.sign_method(m).text
        text = run(go())
        self.assertIn("исталган саволингизни", text)
        self.assertIn("@", text)
        self.assertTrue(text.rstrip().endswith("Сизнинг Кето дўконингиз"))
        self.assertLess(text.index("исталган"), text.index("Сизнинг Кето"))

    def test_scheduled_post_to_a_buyer_in_their_language_once(self):
        async def go():
            with patch.object(database, "claim_user_push", AsyncMock(return_value=True)):
                self.assertTrue(await push_cap.claim(10, "tips"))
            photo = await post_ask.add_line(SendPhoto(chat_id=10, photo="x"))              # bare photo: waits
            first = await post_ask.add_line(SendMessage(chat_id=10, text="Maslahat"))
            second = await post_ask.add_line(SendMessage(chat_id=10, text="Javob"))      # not a scheduled post
            return photo, first, second
        photo, first, second = run(go())
        self.assertIsNone(photo.caption)
        self.assertIn("любой вопрос", first.text)
        self.assertEqual(second.text, "Javob")

    def test_capped_or_unclaimed_messages_stay_as_written(self):
        async def go():
            with patch.object(database, "claim_user_push", AsyncMock(return_value=False)):
                await push_cap.claim(11, "tips")
            return await post_ask.add_line(SendMessage(chat_id=11, text="Buyurtma #5 qabul qilindi"))
        self.assertEqual(run(go()).text, "Buyurtma #5 qabul qilindi")

    def test_never_twice_never_past_the_limit(self):
        line = post_ask.channel_line()
        once = post_ask.with_line("A", line, 4096)
        self.assertEqual(post_ask.with_line(once, line, 4096), once)
        long = "x" * 1000
        self.assertEqual(post_ask.with_line(long, line, 1024), long)

    def test_shop_link_sometimes_reads_healthy_products_world(self):
        import channel_link
        text = "Fakt\n\n" + channel_link.link_line(channel_link.SHOP_URL, channel_link.SHOP_LABEL)
        with patch.object(post_ask._rng, "random", lambda: 0.1):
            out = post_ask.vary_shop_link(text)
        self.assertIn("🛍️ <b>Соғлом маҳсулотлар дунёси:</b>", out)
        self.assertIn(channel_link.SHOP_URL, out)
        self.assertNotIn(channel_link.SHOP_LABEL, out)
        with patch.object(post_ask._rng, "random", lambda: 0.9):
            self.assertEqual(post_ask.vary_shop_link(text), text)

    def test_languages(self):
        self.assertIn("istalgan savolingizni", post_ask.dm_line("uz"))
        self.assertIn("исталган саволингизни", post_ask.dm_line("uz_cyr"))
        self.assertIn("любой вопрос", post_ask.dm_line("ru"))


if __name__ == "__main__":
    unittest.main()
