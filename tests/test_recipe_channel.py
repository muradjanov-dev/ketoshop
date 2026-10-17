"""Saytdagi yangi retsept kanalga — rasm, boshlanishi va «To'liq retseptni
ko'rish» tugmasi (egasi, 2026-10-17). Telegram va bazaga ulanmasdan."""
import asyncio
import os
import re
import unittest
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
import recipe_channel
import recipes
from recipes_content import RECIPES


def run(coro):
    return asyncio.run(coro)


class CaptionTest(unittest.TestCase):
    def test_every_recipe_fits_a_photo_caption(self):
        for r in RECIPES:
            for lang in ("uz_cyr", "uz", "ru"):
                text = recipe_channel.caption(r, lang)
                plain = re.sub(r"<[^>]+>", "", text)
                self.assertLessEqual(len(plain), 1024, (r["slug"], lang, len(plain)))
                self.assertIn(recipes._pick(r["title"], lang), text)

    def test_channel_reads_cyrillic_and_shows_the_start(self):
        r = next(x for x in RECIPES if x["slug"] == "keto-pitsa")
        text = recipe_channel.caption(r, "uz_cyr")
        self.assertIn("Бодом унидан кето пицца", text)
        self.assertIn("Сайтда янги рецепт", text)
        self.assertIn("• 100 г — Бодом уни", text)
        self.assertIn("ва яна", text)                         # the rest is on the site
        self.assertEqual(len(re.findall(r"^• ", text, re.M)), recipe_channel.TEASER_INGREDIENTS)

    def test_button_goes_to_the_bot(self):
        btn = recipe_channel.channel_keyboard().inline_keyboard[0][0]
        self.assertTrue(btn.url.endswith("?start=retsept"))
        self.assertIn("рецепт", btn.text.lower())


class ScheduleTest(unittest.TestCase):
    def test_new_recipe_days(self):
        self.assertTrue(recipe_channel.is_new_day(recipes.START))
        self.assertFalse(recipe_channel.is_new_day(recipes.START + timedelta(days=1)))
        self.assertTrue(recipe_channel.is_new_day(date(2026, 10, 18)))
        self.assertFalse(recipe_channel.is_new_day(recipes.START - timedelta(days=2)))

    def tick(self, now, claimed=True, posted=True):
        bot = MagicMock()
        with patch.object(recipe_channel, "_now_tk", lambda: now), \
             patch.object(database, "claim_release_notes", AsyncMock(return_value=claimed)) as claim, \
             patch.object(database, "release_release_notes", AsyncMock()) as release, \
             patch.object(recipe_channel, "post_to_channel", AsyncMock(return_value=posted)) as post, \
             patch.object(recipe_channel, "_notify_admins", AsyncMock()) as notify:
            run(recipe_channel._tick(bot))
        return claim, release, post, notify

    def test_posts_once_on_the_day_after_eleven(self):
        claim, release, post, notify = self.tick(datetime(2026, 10, 18, 11, 5))
        self.assertEqual(claim.await_args.args[0], "recipe-channel-keto-pitsa-2026-10-18")
        self.assertEqual(post.await_args.args[1]["slug"], "keto-pitsa")
        notify.assert_awaited_once()
        release.assert_not_awaited()

    def test_not_before_eleven_not_on_the_off_day_not_twice(self):
        for now in (datetime(2026, 10, 18, 10, 59), datetime(2026, 10, 19, 12, 0)):
            claim, _, post, _ = self.tick(now)
            claim.assert_not_awaited()
            post.assert_not_awaited()
        _, _, post, _ = self.tick(datetime(2026, 10, 18, 12, 0), claimed=False)
        post.assert_not_awaited()

    def test_failed_post_is_retried(self):
        _, release, _, notify = self.tick(datetime(2026, 10, 18, 11, 5), posted=False)
        release.assert_awaited_once_with("recipe-channel-keto-pitsa-2026-10-18")
        notify.assert_not_awaited()


class DeepLinkTest(unittest.TestCase):
    def test_payload(self):
        self.assertTrue(recipe_channel.parse_payload("retsept"))
        self.assertTrue(recipe_channel.parse_payload(" Retsept "))
        self.assertFalse(recipe_channel.parse_payload("prod_5"))
        self.assertFalse(recipe_channel.parse_payload(None))

    def test_private_answer_opens_the_mini_app_on_the_recipe(self):
        bot = MagicMock()
        bot.send_photo = AsyncMock()
        with patch.object(recipe_channel, "WEBAPP_URL", "https://keto.example/"), \
             patch.object(recipes, "today_tk", lambda: date(2026, 10, 18)):
            self.assertTrue(run(recipe_channel.open_from_link(bot, 77, "ru")))
        kwargs = bot.send_photo.await_args.kwargs
        button = kwargs["reply_markup"].inline_keyboard[0][0]
        self.assertEqual(button.web_app.url, "https://keto.example/?recipe=keto-pitsa")
        self.assertIn("Кето-пицца", kwargs["caption"])

    def test_no_site_no_answer(self):
        with patch.object(recipe_channel, "WEBAPP_URL", ""):
            self.assertFalse(run(recipe_channel.open_from_link(MagicMock(), 77, "uz")))

    def test_photos_exist_for_every_recipe(self):
        for r in RECIPES:
            self.assertTrue((recipe_channel.PHOTO_DIR / f"{r['slug']}.jpg").exists(), r["slug"])


if __name__ == "__main__":
    unittest.main()
