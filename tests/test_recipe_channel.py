"""Saytdagi yangi retsept kanalga — rasm, boshlanishi va matn ichidagi katta
«To'liq retseptni saytimiz orqali ko'ring» havolasi, tugmasiz (egasi,
2026-10-17). Telegram va bazaga ulanmasdan."""
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

LINK = "https://t.me/ketoshopbot?startapp=recipe-keto-pitsa"


def run(coro):
    return asyncio.run(coro)


def bot_with_main_app(enabled):
    bot = MagicMock()
    bot.get_me = AsyncMock(return_value=MagicMock(has_main_web_app=enabled))
    bot.send_photo = AsyncMock()
    return bot


class CaptionTest(unittest.TestCase):
    def test_every_recipe_fits_a_photo_caption(self):
        for r in RECIPES:
            for lang in ("uz_cyr", "uz", "ru"):
                text = recipe_channel.caption(r, lang, LINK)
                plain = re.sub(r"<[^>]+>", "", text)
                self.assertLessEqual(len(plain), 1024, (r["slug"], lang, len(plain)))
                self.assertIn(recipes._pick(r["title"], lang), text)

    def test_channel_reads_cyrillic_and_shows_the_start(self):
        r = next(x for x in RECIPES if x["slug"] == "keto-pitsa")
        text = recipe_channel.caption(r, "uz_cyr", LINK)
        self.assertIn("Бодом унидан кето пицца", text)
        self.assertIn("Сайтда янги рецепт", text)
        self.assertIn("• 100 г — Бодом уни", text)
        self.assertIn("ва яна", text)                         # the rest is on the site
        self.assertIn("1 порцияда", text)                     # not "порсияда"
        self.assertEqual(len(re.findall(r"^• ", text, re.M)), recipe_channel.TEASER_INGREDIENTS)

    def test_big_link_in_the_text_survives_forwarding(self):
        r = next(x for x in RECIPES if x["slug"] == "keto-pitsa")
        text = recipe_channel.caption(r, "uz_cyr", LINK)
        self.assertIn(f'👉 <b><a href="{LINK}">ТЎЛИҚ РЕЦЕПТНИ САЙТИМИЗ ОРҚАЛИ КЎРИНГ</a></b> 👈', text)
        self.assertEqual(text.count(f'href="{LINK}"'), 2)    # the title links too
        ru = recipe_channel.caption(r, "ru", LINK)
        self.assertIn("СМОТРИТЕ ПОЛНЫЙ РЕЦЕПТ НА НАШЕМ САЙТЕ", ru)


class LinkTest(unittest.TestCase):
    def test_one_tap_link_opens_the_mini_app_on_the_recipe(self):
        r = {"slug": "keto-pitsa"}
        self.assertEqual(recipe_channel.full_recipe_link(r, True),
                         f"https://t.me/{recipe_channel.BOT_USERNAME}?startapp=recipe-keto-pitsa")
        self.assertEqual(recipe_channel.full_recipe_link(r, False),
                         f"https://t.me/{recipe_channel.BOT_USERNAME}?start=retsept_keto-pitsa")
        # Telegram allows 64 characters in ?start= and [A-Za-z0-9_-] only.
        for x in RECIPES:
            payload = recipe_channel.full_recipe_link(x, False).split("?start=")[1]
            self.assertLessEqual(len(payload), 64, x["slug"])
            self.assertRegex(payload, r"^[A-Za-z0-9_-]+$")

    def test_main_app_check(self):
        self.assertTrue(run(recipe_channel.main_app_enabled(bot_with_main_app(True))))
        self.assertFalse(run(recipe_channel.main_app_enabled(bot_with_main_app(False))))
        broken = MagicMock()
        broken.get_me = AsyncMock(side_effect=RuntimeError("network"))
        self.assertFalse(run(recipe_channel.main_app_enabled(broken)))

    def test_post_has_no_button_so_comments_stay_open(self):
        r = next(x for x in RECIPES if x["slug"] == "keto-pitsa")
        for enabled, expected in ((True, "?startapp=recipe-keto-pitsa"), (False, "?start=retsept_keto-pitsa")):
            bot = bot_with_main_app(enabled)
            with patch.object(recipe_channel, "REQUIRED_CHANNEL_ID", -100):
                self.assertTrue(run(recipe_channel.post_to_channel(bot, r)))
            kwargs = bot.send_photo.await_args.kwargs
            self.assertNotIn("reply_markup", kwargs)
            self.assertIn(expected, kwargs["caption"])


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
        with patch.object(recipes, "today_tk", lambda: date(2026, 10, 18)):
            self.assertEqual(recipe_channel.parse_payload("retsept"), "keto-pitsa")     # first posts' button
            self.assertEqual(recipe_channel.parse_payload(" Retsept "), "keto-pitsa")
        self.assertEqual(recipe_channel.parse_payload("retsept_bodom-noni"), "bodom-noni")
        self.assertIsNone(recipe_channel.parse_payload("retsept_"))
        self.assertIsNone(recipe_channel.parse_payload("prod_5"))
        self.assertIsNone(recipe_channel.parse_payload(None))

    def open(self, slug, today=date(2026, 10, 20)):
        bot = MagicMock()
        bot.send_photo = AsyncMock()
        with patch.object(recipe_channel, "WEBAPP_URL", "https://keto.example/"), \
             patch.object(recipes, "today_tk", lambda: today):
            self.assertTrue(run(recipe_channel.open_from_link(bot, 77, "ru", slug)))
        kwargs = bot.send_photo.await_args.kwargs
        return kwargs["reply_markup"].inline_keyboard[0][0].web_app.url, kwargs["caption"]

    def test_forwarded_post_opens_its_own_recipe(self):
        url, text = self.open("keto-pitsa")            # posted 18.10, opened 20.10
        self.assertEqual(url, "https://keto.example/?recipe=keto-pitsa")
        self.assertIn("Кето-пицца", text)

    def test_unknown_or_future_recipe_opens_today_s(self):
        today_slug = recipes.schedule(date(2026, 10, 20))[0]["slug"]
        for slug in ("no-such-recipe", "keto-bulochka", None):     # keto-bulochka opens 05.11
            url, _ = self.open(slug)
            self.assertEqual(url, f"https://keto.example/?recipe={today_slug}")

    def test_no_site_no_answer(self):
        with patch.object(recipe_channel, "WEBAPP_URL", ""):
            self.assertFalse(run(recipe_channel.open_from_link(MagicMock(), 77, "uz")))

    def test_photos_exist_for_every_recipe(self):
        for r in RECIPES:
            self.assertTrue((recipe_channel.PHOTO_DIR / f"{r['slug']}.jpg").exists(), r["slug"])


class RecipeApiTest(unittest.TestCase):
    def call(self, slug, today=date(2026, 10, 20)):
        import webapp_server
        request = MagicMock()
        request.match_info = {"slug": slug}
        request.get = lambda key, default=None: "uz" if key == "user_lang" else default
        with patch.object(recipes, "today_tk", lambda: today), \
             patch.object(recipes, "view", AsyncMock(side_effect=lambda r, lang: {"slug": r["slug"]})):
            return run(webapp_server.api_recipe_one(request))

    def test_published_recipe_by_slug(self):
        res = self.call("keto-pitsa")
        self.assertEqual(res.status, 200)
        self.assertIn(b'"keto-pitsa"', res.body)

    def test_future_or_unknown_is_404(self):
        self.assertEqual(self.call("keto-bulochka").status, 404)
        self.assertEqual(self.call("no-such-recipe").status, 404)


if __name__ == "__main__":
    unittest.main()
