"""Eritritol sovg'asi yana 30 kun — 18.10 09:00 da hammaga va kanalga e'lon
(egasi, 2026-10-17). Telegram va bazaga ulanmasdan: hech kimga haqiqiy
xabar ketmaydi."""
import asyncio
import os
import re
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
import gift_campaign as g

UNTIL = datetime(2026, 11, 17, 9, 0)
ENDED = {"key": g.CAMPAIGN_KEY, "announced_at": datetime(2026, 9, 17, 4, 0),
         "ends_at": datetime(2026, 10, 17, 4, 0), "ended_notified_at": datetime(2026, 10, 17, 4, 5)}
PROD = {"id": 9, "name": "Eritritol 100gr", "quantity": 120, "photo_id": "PHOTO"}


def run(coro):
    return asyncio.run(coro)


class TextTest(unittest.TestCase):
    def test_opens_with_by_popular_demand_in_every_language(self):
        self.assertTrue(g.extension_text("uz", UNTIL).startswith(
            "🎉 <b>Talab va takliflaringizga binoan — sovg'a aksiyasi davom etadi!</b>"))
        self.assertTrue(g.extension_text("uz_cyr", UNTIL).startswith(
            "🎉 <b>Талаб ва таклифларингизга биноан — совға акцияси давом этади!</b>"))
        self.assertTrue(g.extension_text("ru", UNTIL).startswith(
            "🎉 <b>По вашим просьбам и пожеланиям — акция с подарком продолжается!</b>"))

    def test_facts_and_caption_size(self):
        for lang in ("uz", "uz_cyr", "ru"):
            for channel in (False, True):
                text = g.extension_text(lang, UNTIL, channel=channel)
                self.assertIn("17.11.2026", text)
                self.assertIn("30", text)
                self.assertLess(len(re.sub(r"<[^>]+>", "", text)), 1024)     # photo caption
                self.assertEqual(text.count("<b>"), text.count("</b>"))
                self.assertNotIn("{", text)

    def test_channel_copy_links_the_bot_even_in_cyrillic(self):
        text = g.extension_text("uz_cyr", UNTIL, channel=True)
        self.assertIn('🛒 Буюртма бериш: <a href="https://t.me/ketoshopbot">@ketoshopbot</a>', text)
        self.assertNotIn("Hoziroq", text)
        self.assertNotIn("t.me", g.extension_text("uz", UNTIL))            # the bot copy has the button

    def test_no_pressure_words(self):
        for lang in ("uz", "ru"):
            low = g.extension_text(lang, UNTIL).lower()
            for word in ("faqat bugun", "shoshiling", "только сегодня", "успейте", "последний шанс"):
                self.assertNotIn(word, low)


class TickTest(unittest.TestCase):
    def tick(self, now, row=ENDED, prod=PROD, claimed=True):
        bot = MagicMock()
        extended = dict(row, ends_at=datetime(2026, 11, 17, 4, 0), ended_notified_at=None)
        states = iter([row, extended, extended, extended])
        with patch.object(g, "_now_tk", lambda: now), \
             patch.object(g, "_state", AsyncMock(side_effect=lambda force=False: next(states))), \
             patch.object(g, "gift_product", AsyncMock(return_value=prod)), \
             patch.object(g, "book_delivered_gifts", AsyncMock(return_value=(0, 0.0))), \
             patch.object(g, "announce_extension", AsyncMock(return_value={
                 "sent": 10, "failed": 1, "channel": True, "until": UNTIL})) as announce, \
             patch.object(g, "_notify_admins", AsyncMock()) as notify, \
             patch.object(database, "claim_release_notes", AsyncMock(side_effect=lambda key: claimed and key == g.EXTEND_KEY)) as claim, \
             patch.object(database, "claim_gift_stock_alert", AsyncMock(return_value=True)) as alert, \
             patch.object(database, "extend_gift_campaign", AsyncMock()) as extend, \
             patch.object(database, "get_gift_campaign_stats", AsyncMock(return_value={})), \
             patch.object(database, "mark_gift_ended_notified", AsyncMock()):
            run(g._tick(bot))
        return announce, notify, claim, alert, extend

    def test_switches_back_on_and_announces_at_nine_on_the_18th(self):
        announce, notify, claim, _, extend = self.tick(datetime(2026, 10, 18, 9, 3))
        self.assertIn(g.EXTEND_KEY, [c.args[0] for c in claim.await_args_list])
        extend.assert_awaited_once_with(g.CAMPAIGN_KEY, 30)
        announce.assert_awaited_once()
        admin = notify.await_args.args[1]
        self.assertIn("yana 30 kunga uzaytirildi", admin)
        self.assertIn("17.11.2026", admin)
        self.assertIn("✅ 10 ta", admin)
        self.assertIn("Kanal: ✅ chiqdi", admin)

    def test_not_before_nine_not_after_noon_not_before_the_18th_not_twice(self):
        for now in (datetime(2026, 10, 18, 8, 59), datetime(2026, 10, 18, 12, 0),
                    datetime(2026, 10, 17, 20, 30)):
            announce, _, _, _, extend = self.tick(now)
            announce.assert_not_awaited()
            extend.assert_not_awaited()
        announce, _, _, _, extend = self.tick(datetime(2026, 10, 18, 9, 3), claimed=False)
        announce.assert_not_awaited()
        extend.assert_not_awaited()

    def test_not_while_the_campaign_is_running_or_long_after(self):
        live = dict(ENDED, ends_at=datetime(2030, 1, 1))
        for row, now in ((live, datetime(2026, 10, 18, 9, 3)), (ENDED, datetime(2026, 10, 21, 9, 3))):
            announce, _, claim, _, extend = self.tick(now, row=row)
            announce.assert_not_awaited()
            extend.assert_not_awaited()

    def test_missing_gift_product_waits_and_tells_the_admins(self):
        announce, notify, claim, alert, extend = self.tick(datetime(2026, 10, 18, 9, 3), prod=None)
        announce.assert_not_awaited()
        extend.assert_not_awaited()
        self.assertNotIn(g.EXTEND_KEY, [c.args[0] for c in claim.await_args_list])
        alert.assert_awaited_once()
        self.assertIn("uzaytirilmadi", notify.await_args.args[1])


class AnnounceTest(unittest.TestCase):
    def test_everyone_in_their_language_and_the_channel_without_a_button(self):
        bot = MagicMock()
        sends = []

        async def fake_send_photo(_bot, chat_id, photo, text, markup):
            sends.append((chat_id, photo, text, markup))
            return chat_id != 3                                       # user 3 blocked the bot

        row = dict(ENDED, ends_at=datetime(2026, 11, 17, 4, 0))
        with patch.object(g, "_state", AsyncMock(return_value=row)), \
             patch.object(g, "gift_product", AsyncMock(return_value=PROD)), \
             patch.object(g, "_send_photo", side_effect=fake_send_photo), \
             patch.object(g, "SEND_DELAY", 0), \
             patch("config.REQUIRED_CHANNEL_ID", -100500), \
             patch.object(database, "get_all_user_ids", AsyncMock(return_value=[1, 2, 3])), \
             patch.object(database, "get_user_languages", AsyncMock(return_value={1: "uz", 2: "ru", 3: "uz_cyr"})):
            stats = run(g.announce_extension(bot))
        self.assertEqual((stats["sent"], stats["failed"], stats["channel"]), (2, 1, True))
        self.assertEqual(stats["until"], UNTIL)
        channel = sends[0]
        self.assertEqual(channel[0], -100500)
        self.assertIsNone(channel[3])                                 # comments stay open
        self.assertIn("Талаб ва таклифларингизга биноан", channel[2])
        by_user = {s[0]: s for s in sends[1:]}
        self.assertIn("Talab va takliflaringizga binoan", by_user[1][2])
        self.assertIn("По вашим просьбам", by_user[2][2])
        self.assertIsNotNone(by_user[1][3])                           # shop button for bot users
        self.assertTrue(all(s[1] == "PHOTO" for s in sends))


if __name__ == "__main__":
    unittest.main()
