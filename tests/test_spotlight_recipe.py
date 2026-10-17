"""Kun mahsuloti ichida retsept (egasi, 2026-10-16: "kun mahsuloti bilan
birga bir retsept ham yozib ber ichida"). Telegram va bazaga ulanmasdan."""
import asyncio
import os
import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import product_card
import product_ideas
import product_of_day
import reco_content


def product(name="Chia urug'i 300gr", category="seeds", **kw):
    return {"id": 5, "name": name, "name_ru": None, "category": category, "description": "Tavsif",
            "description_ru": None, "price": 50000, "unit": "piece", "quantity": 7, **kw}


class RecipeBlockTest(unittest.TestCase):
    def test_recipe_of_the_products_own_family(self):
        block = product_ideas.recipe_block(product(), "uz", 0)
        self.assertTrue(block.startswith("🍳 <b>Bugungi retsept</b>\n"))
        self.assertIn("Masalliqlar:", block)
        self.assertIn("chia", block.lower())
        self.assertTrue(product_ideas.recipe_block(product(), "ru", 0).startswith("🍳 <b>Рецепт дня</b>\n"))
        cyr = product_ideas.recipe_block(product(), "uz_cyr", 0)
        self.assertTrue(cyr.startswith("🍳 <b>Бугунги рецепт</b>"))   # tags kept, рецепт with ц
        self.assertNotIn("Kerak", cyr)

    def test_rotates_by_day(self):
        chia = next(p for p in reco_content.PROFILES if p["key"] == "chia")
        self.assertGreaterEqual(len(chia["recipes"]), 2)
        seen = {product_ideas.recipe_for(product(), "uz", seed) for seed in range(len(chia["recipes"]))}
        self.assertEqual(len(seen), len(chia["recipes"]))

    def test_unknown_name_falls_back_to_category_then_general(self):
        generic = reco_content.CATEGORY_GENERIC_PROFILES["keto_flour"]["recipes"][0]["uz"]
        self.assertEqual(product_ideas.recipe_for(product("Yangi un X", "keto_flour"), "uz", 0), generic)
        default = reco_content.DEFAULT_PROFILE["recipes"][0]["uz"]
        self.assertEqual(product_ideas.recipe_for(product("Alla balla", "nothing"), "uz", 0), default)

    def test_seed_is_the_date(self):
        self.assertEqual(product_of_day._recipe_seed(date(2026, 10, 16)), date(2026, 10, 16).toordinal())
        self.assertNotEqual(product_of_day._recipe_seed(date(2026, 10, 16)),
                            product_of_day._recipe_seed(date(2026, 10, 17)))


class SpotlightTest(unittest.TestCase):
    def test_every_buyer_gets_the_recipe_in_their_language(self):
        texts = {}

        async def fake_send(bot, uid, prod, lang, captions):
            texts[uid] = await captions.get(lang, None)
            return True

        built = AsyncMock(side_effect=lambda p, lang, rate, extra=None, tip=None: extra)
        with patch.object(product_of_day.database, "get_all_user_ids", AsyncMock(return_value=[1, 2, 3])), \
             patch.object(product_of_day.database, "get_user_languages", AsyncMock(return_value={2: "ru", 3: "uz_cyr"})), \
             patch.object(product_of_day, "_send_to_user", fake_send), \
             patch.object(product_card, "build_caption", built), \
             patch.object(product_of_day, "SEND_DELAY", 0):
            sent, failed = asyncio.run(product_of_day.broadcast(None, product(), date(2026, 10, 16)))
        self.assertEqual((sent, failed), (3, 0))
        self.assertIn("Bugungi retsept", texts[1])
        self.assertIn("Рецепт дня", texts[2])
        self.assertIn("Бугунги рецепт", texts[3])
        seed = date(2026, 10, 16).toordinal()
        self.assertIn(product_ideas.recipe_for(product(), "uz", seed).split("\n")[0], texts[1])

    def test_channel_post_carries_the_recipe(self):
        built = AsyncMock(return_value="CARD")
        sent = AsyncMock()
        with patch.object(product_of_day, "REQUIRED_CHANNEL_ID", -100123), \
             patch("gamification.is_enabled", AsyncMock(return_value=False)), \
             patch.object(product_card, "build_caption", built), \
             patch.object(product_card, "send_product_message", sent):
            self.assertTrue(asyncio.run(product_of_day.post_to_channel(None, product(), date(2026, 10, 16))))
        extra = built.await_args.args[3]
        self.assertTrue(extra.startswith("🍳 <b>Бугунги рецепт</b>"))    # the channel reads Cyrillic


if __name__ == "__main__":
    unittest.main()
