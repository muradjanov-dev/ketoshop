"""🔎 «Keto fakt» — kanalga har 2 kunda savol bilan boshlanadigan qisqa post
(egasi, 2026-11-03). Bazaga ulanmasdan: jadval (retsept kunlari bilan to'qnashmaydi),
post tuzilishi, bir marta yuborish, tugmasiz, o'chirish va mahsulot havolasi.
"""
import asyncio
import os
import re
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import keyboards
import keto_fakt as kf
import recipe_channel

LINK = '👉 <b><a href="https://t.me/x?start=prod_1">🛒 Ботда сотиб олиш</a></b> 👈'


class ScheduleTest(unittest.TestCase):
    def test_every_other_day_from_start(self):
        self.assertTrue(kf.is_fact_day(kf.START))
        self.assertFalse(kf.is_fact_day(kf.START + timedelta(days=1)))
        self.assertTrue(kf.is_fact_day(kf.START + timedelta(days=2)))
        self.assertFalse(kf.is_fact_day(kf.START - timedelta(days=2)))

    def test_never_on_a_recipe_day(self):
        for i in range(120):
            day = kf.START + timedelta(days=i)
            self.assertFalse(kf.is_fact_day(day) and recipe_channel.is_new_day(day), day)

    def test_rotation_walks_the_list_then_repeats(self):
        first = kf.fact_for(kf.START)
        self.assertEqual(first, kf.FACTS[0])
        self.assertEqual(kf.fact_for(kf.START + timedelta(days=2)), kf.FACTS[1])
        self.assertEqual(kf.fact_for(kf.START + timedelta(days=2 * len(kf.FACTS))), first)

    def test_next_fact_day(self):
        self.assertEqual(kf.next_fact_day(date(2026, 11, 3)), date(2026, 11, 4))
        self.assertEqual(kf.next_fact_day(date(2026, 11, 5)), date(2026, 11, 6))


class PostTest(unittest.TestCase):
    def test_every_post_opens_and_closes_with_a_question_and_stays_short(self):
        slugs = set()
        for fact in kf.FACTS:
            slug, _, question, body, tip, closing = fact
            self.assertNotIn(slug, slugs)
            slugs.add(slug)
            self.assertTrue(question.rstrip().endswith("?"), slug)
            self.assertTrue(closing.rstrip().endswith("?"), slug)
            text = kf.post_text(fact, LINK)
            self.assertTrue(text.startswith("<b>❓ "), slug)
            self.assertNotIn("⟦", text)
            self.assertNotIn("<s>", text)
            plain = re.sub(r"<[^>]+>", "", text)
            self.assertLess(len(plain), 700, slug)               # "qisqagina"
            self.assertIn(LINK, text)
            self.assertTrue(text.endswith(kf.HASHTAG))

    def test_cyrillic_with_latin_names_kept(self):
        ghee = next(f for f in kf.FACTS if f[0] == "ghee-tutun")
        text = kf.post_text(ghee, LINK)
        self.assertIn("GHEE", text)                               # not «ГҲЕЕ»
        self.assertIn("қовуриш", text)
        ev = next(f for f in kf.FACTS if f[0] == "zaytun-extra-virgin")
        self.assertIn("Extra Virgin", kf.post_text(ev, LINK))

    def test_product_link_or_shop(self):
        found = AsyncMock(return_value=[{"id": 7, "is_active": 0}, {"id": 9, "is_active": 1}])
        with patch.object(kf.database, "admin_search_products", found):
            line = asyncio.run(kf._product_link("ghee"))
        self.assertIn("start=prod_9", line)
        with patch.object(kf.database, "admin_search_products", AsyncMock(return_value=[])):
            self.assertIn("/shop", asyncio.run(kf._product_link("ghee")))
        self.assertIn("/shop", asyncio.run(kf._product_link(None)))
        with patch.object(kf.database, "admin_search_products", AsyncMock(side_effect=RuntimeError)):
            self.assertIn("/shop", asyncio.run(kf._product_link("ghee")))


class TickTest(unittest.TestCase):
    def setUp(self):
        self.bot = AsyncMock()
        self.patches = [patch.object(kf, "REQUIRED_CHANNEL_ID", -100),
                        patch.object(kf, "ADMIN_IDS", [1]),
                        patch.object(kf, "is_enabled", AsyncMock(return_value=True)),
                        patch.object(kf, "_product_link", AsyncMock(return_value=LINK)),
                        patch.object(kf.database, "claim_release_notes", AsyncMock(return_value=True)),
                        patch.object(kf.database, "release_release_notes", AsyncMock())]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()

    def _tick(self, when: datetime):
        with patch.object(kf, "_now_tk", lambda: when):
            asyncio.run(kf._tick(self.bot))

    def test_posts_on_a_fact_day_without_a_button(self):
        self._tick(datetime(2026, 11, 4, 16, 5))
        channel = [c for c in self.bot.send_message.await_args_list if c.args[0] == -100]
        self.assertEqual(len(channel), 1)
        self.assertNotIn("reply_markup", channel[0].kwargs)       # comments stay open
        self.assertTrue(channel[0].args[1].startswith("<b>❓ "))
        kf.database.claim_release_notes.assert_awaited_once_with("keto-fakt-2026-11-04")

    def test_quiet_before_the_hour_on_other_days_and_when_paused(self):
        self._tick(datetime(2026, 11, 4, 15, 59))
        self._tick(datetime(2026, 11, 5, 16, 30))
        with patch.object(kf, "is_enabled", AsyncMock(return_value=False)):
            self._tick(datetime(2026, 11, 6, 16, 30))
        self.bot.send_message.assert_not_awaited()

    def test_failed_post_gives_the_day_back(self):
        self.bot.send_message.side_effect = RuntimeError("telegram down")
        self._tick(datetime(2026, 11, 4, 16, 5))
        kf.database.release_release_notes.assert_awaited_once_with("keto-fakt-2026-11-04")


class AdminTest(unittest.TestCase):
    def test_preview_command_is_published(self):
        self.assertIn("fakt_test", [c.command for c in keyboards.ADMIN_COMMANDS])


if __name__ == "__main__":
    unittest.main()
