"""Yangi foydalanuvchiga bugungi retsept, rasmi bilan, to'liq — video
qo'llanmadan keyin (egasi, 2026-10-14). Bot va baza mock."""
import asyncio
import os
import re
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import recipes
import welcome_recipe as wr
from recipes_content import RECIPES


def run(coro):
    return asyncio.run(coro)


class TextTest(unittest.TestCase):
    def test_every_recipe_fits_a_photo_caption_in_every_language(self):
        for r in RECIPES:
            for lang in ("uz", "uz_cyr", "ru"):
                cap = wr.caption_text(r, lang)
                self.assertLessEqual(len(cap), wr.CAPTION_MAX, (r["slug"], lang))
                self.assertIn(recipes._pick(r["title"], lang).split()[0], cap)
                self.assertIn(recipes._pick(recipes.AI_NOTE, lang), cap)   # AI photo is said out loud

    def test_full_recipe_every_ingredient_and_step(self):
        r = RECIPES[0]
        text = wr.recipe_text(r, "uz")
        for item in r["ingredients"]:
            self.assertIn(recipes._pick(item["name"], "uz"), text)
        for i in range(1, len(r["steps"]) + 1):
            self.assertIn(f"\n{i}. ", text)
        self.assertIn("Maslahat", text)
        self.assertIn("Keyingi retsept", text)

    def test_home_ingredients_are_marked(self):
        r = next(x for x in RECIPES if any(not i.get("match") for i in x["ingredients"]))
        home = next(i for i in r["ingredients"] if not i.get("match"))
        line = next(l for l in wr.recipe_text(r, "uz").split("\n") if recipes._pick(home["name"], "uz") in l)
        self.assertIn("(uydan)", line)

    def test_languages(self):
        r = RECIPES[0]
        self.assertIn("Ингредиенты", wr.recipe_text(r, "ru"))
        cyr = wr.caption_text(r, "uz_cyr")
        self.assertIn("Сизга бугунги", cyr)

    def test_buttons(self):
        with patch("config.WEBAPP_URL", "https://keto.example/app"):
            kb = wr.keyboard(RECIPES[0], "uz")
        self.assertEqual(kb.inline_keyboard[0][0].callback_data, wr.CALLBACK + RECIPES[0]["slug"])
        self.assertEqual(kb.inline_keyboard[1][0].web_app.url, "https://keto.example/app")


class SendTest(unittest.TestCase):
    def setUp(self):
        wr._photo_ids.clear()

    def bot(self):
        b = AsyncMock()
        photo = MagicMock()
        photo.photo = [MagicMock(file_id="F1")]
        b.send_photo.return_value = photo
        return b

    def test_new_user_gets_photo_then_full_text_once(self):
        bot = self.bot()
        with patch.object(wr, "_pop_pending", AsyncMock(side_effect=[True, False])):
            self.assertTrue(run(wr.maybe_send(bot, 9, "uz")))
            self.assertFalse(run(wr.maybe_send(bot, 9, "uz")))      # language switched again
        bot.send_photo.assert_awaited_once()
        self.assertIn("Sizga bugungi keto retseptimiz", bot.send_photo.call_args.kwargs["caption"])
        bot.send_message.assert_awaited_once()
        self.assertIn("Masalliqlar", bot.send_message.call_args.args[1])

    def test_photo_is_uploaded_once_then_reused(self):
        bot = self.bot()
        run(wr.send_recipe(bot, 1, "uz", RECIPES[0]))
        run(wr.send_recipe(bot, 2, "uz", RECIPES[0]))
        self.assertEqual(bot.send_photo.call_args_list[1].args[1], "F1")

    def test_never_raises(self):
        with patch.object(wr, "_pop_pending", AsyncMock(side_effect=RuntimeError("db"))):
            self.assertFalse(run(wr.maybe_send(AsyncMock(), 9, "uz")))

    def test_every_recipe_has_its_photo(self):
        for r in RECIPES:
            self.assertTrue((wr.PHOTO_DIR / f"{r['slug']}.jpg").exists(), r["slug"])


class CartButtonTest(unittest.TestCase):
    def test_all_to_cart(self):
        cb = AsyncMock()
        cb.from_user.id = 9
        cb.data = wr.CALLBACK + RECIPES[0]["slug"]
        res = {"added": ["Bodom uni", "Psillium"], "already": [], "missing": ["Kunjut"]}
        with patch.object(wr.database, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(recipes, "find", return_value=RECIPES[0]), \
             patch.object(recipes, "add_all_to_cart", AsyncMock(return_value=res)) as add:
            run(wr.add_all(cb))
        add.assert_awaited_once_with(9, RECIPES[0], "uz")
        text = cb.message.answer.call_args.args[0]
        self.assertIn("2 ta mahsulot savatga qo'shildi", text)
        self.assertIn("Kunjut", text)


class WiringTest(unittest.TestCase):
    def test_recipe_follows_the_video(self):
        src = open(os.path.join(os.path.dirname(wr.__file__), "handlers", "start.py"), encoding="utf-8").read()
        video = src.index("onboarding_video.maybe_send_to_new_user")
        recipe = src.index("welcome_recipe.maybe_send(")
        self.assertLess(video, recipe)
        self.assertIn("welcome_recipe.mark_pending(tg_user.id)", src)


if __name__ == "__main__":
    unittest.main()
