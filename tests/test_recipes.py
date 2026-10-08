"""Saytdagi retseptlar — jadval, mahsulotga bog'lash, "hammasini savatga".
Bazaga va Telegram'ga ulanmasdan."""
import asyncio
import os
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import recipes
from recipes_content import RECIPES

ROOT = Path(__file__).resolve().parent.parent


def run(coro):
    return asyncio.run(coro)


def product(pid, name, price, qty=10, **kw):
    return {"id": pid, "name": name, "name_ru": None, "price": price, "unit": "piece",
            "quantity": qty, "photo_id": f"file{pid}", "discount_percent": 0,
            "discount_until": None, **kw}


# Names the way the shop writes them (admin panel, 2026-10-08).
CATALOG = [
    product(1, "Bodom uni 1000gr", 170000),
    product(2, "Bodom uni 200 gr", 38000),
    product(3, "Psillium uni 300gr", 125000),
    product(4, "Psillium shelukha 150 gr", 60000),
    product(5, "Olma sirkasi (Toshkent) 250 gr", 25000),
    product(6, "Oq kunjut 1kg", 45000),
    product(7, "Oq kunjut 300 gr", 18000, qty=0),
    product(8, "Himalay tuzi 1000 gr", 30000),
    product(9, "Chia urug'i 300 gr", 40000),
    product(10, "Kokos qirindisi 200 gr", 18000),
    product(11, "Kakao nibs 200 gr", 60000),
    product(12, "Eritritol 100 gr", 15000),
    product(13, "Tabiiy GHEE 1000 ml", 150000),
    product(14, "Zigʻir urugʻlari 600 gr", 30000),
    product(15, "Qovoq urug'i 200 gr", 35000),
    product(16, "Qora kunjut 300 gr", 25000),
    product(17, "Zaytun yog'i (sovuq siqim, Extra virgin)", 120000),
    product(18, "Kepakli bug'doy uni", 12000),
]


class ScheduleTest(unittest.TestCase):
    def test_a_new_recipe_every_two_days(self):
        start = recipes.START
        self.assertEqual(recipes.schedule(start)[0]["slug"], RECIPES[0]["slug"])
        self.assertEqual(recipes.schedule(start + timedelta(days=1))[0]["slug"], RECIPES[0]["slug"])
        self.assertEqual(recipes.schedule(start + timedelta(days=2))[0]["slug"], RECIPES[1]["slug"])
        self.assertEqual(recipes.schedule(start + timedelta(days=2))[2], start + timedelta(days=4))

    def test_earlier_ones_newest_first_and_no_future_ones(self):
        current, earlier, _ = recipes.schedule(recipes.START + timedelta(days=4))
        self.assertEqual(current["slug"], RECIPES[2]["slug"])
        self.assertEqual([r["slug"] for r in earlier], [RECIPES[1]["slug"], RECIPES[0]["slug"]])
        self.assertIsNone(recipes.find(RECIPES[3]["slug"], recipes.START + timedelta(days=4)))
        self.assertIsNotNone(recipes.find(RECIPES[0]["slug"], recipes.START + timedelta(days=4)))

    def test_cycles_after_the_library_runs_out(self):
        n = len(RECIPES)
        current, earlier, _ = recipes.schedule(recipes.START + timedelta(days=2 * n))
        self.assertEqual(current["slug"], RECIPES[0]["slug"])
        self.assertEqual(len(earlier), n - 1)

    def test_before_start_shows_the_first(self):
        self.assertEqual(recipes.schedule(date(2026, 1, 1))[0]["slug"], RECIPES[0]["slug"])


class ContentTest(unittest.TestCase):
    def test_every_recipe_is_complete(self):
        for r in RECIPES:
            with self.subTest(r["slug"]):
                self.assertTrue((ROOT / "webapp" / "recipes" / f"{r['slug']}.jpg").exists())
                for key in ("title", "intro", "servings", "tip"):
                    self.assertTrue(r[key]["uz"] and r[key]["ru"])
                self.assertGreaterEqual(len(r["steps"]), 5)
                self.assertTrue(any(i.get("match") for i in r["ingredients"]))

    def test_every_shop_ingredient_finds_a_product(self):
        for r in RECIPES:
            for item in r["ingredients"]:
                if item.get("match"):
                    with self.subTest(r["slug"], item=item["name"]["uz"]):
                        self.assertIsNotNone(recipes.match_product(item["match"], CATALOG))


class MatchTest(unittest.TestCase):
    def test_cheapest_pack_in_stock(self):
        self.assertEqual(recipes.match_product([["bodom", "uni"]], CATALOG)["id"], 2)
        # 300 gr sesame is cheaper but sold out → the 1 kg pack.
        self.assertEqual(recipes.match_product([["oq", "kunjut"]], CATALOG)["id"], 6)

    def test_apostrophe_variants(self):
        self.assertEqual(recipes.match_product([["zig'ir", "urug'"]], CATALOG)["id"], 14)

    def test_specific_group_beats_a_loose_one(self):
        self.assertEqual(recipes.match_product([["psillium", "uni"]], CATALOG)["id"], 3)

    def test_nothing_found(self):
        self.assertIsNone(recipes.match_product([["avokado"]], CATALOG))


class ViewAndCartTest(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(recipes, "_catalog", AsyncMock(return_value=CATALOG))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_view_links_products_and_says_the_photo_is_ai(self):
        out = run(recipes.view(RECIPES[0], "uz"))
        self.assertEqual(out["image_url"], "/static/recipes/bodom-noni.jpg")
        self.assertIn("sun'iy intellekt", out["ai_note"])
        almond = out["ingredients"][0]
        self.assertEqual(almond["product"]["id"], 2)
        self.assertEqual(almond["product"]["photo_url"], "/api/photo/file2")
        eggs = next(i for i in out["ingredients"] if i["name"] == "Tuxum")
        self.assertNotIn("product", eggs)
        self.assertIn("Изображение", run(recipes.view(RECIPES[0], "ru"))["ai_note"])
        self.assertIn("Глютенсиз", run(recipes.view(RECIPES[0], "uz_cyr"))["title"])

    def test_add_all_to_cart(self):
        in_cart = {8}                                   # salt already there

        async def line(user_id, pid):
            return (1, 1.0) if pid in in_cart else (None, 0.0)

        add = AsyncMock()
        with patch.object(recipes.database, "get_cart_line_for_product", line), \
             patch.object(recipes.database, "add_to_cart", add):
            res = run(recipes.add_all_to_cart(77, RECIPES[0], "uz"))
        self.assertEqual(res["already"], ["Himalay tuzi"])
        self.assertEqual(sorted(c.kwargs["product_id"] for c in add.await_args_list), [2, 3, 5, 6])
        self.assertTrue(all(c.kwargs["quantity"] == 1 for c in add.await_args_list))
        self.assertEqual(res["missing"], [])

    def test_sold_out_is_reported_not_added(self):
        sold_out = [dict(p, quantity=0) if p["id"] == 3 else p for p in CATALOG]
        add = AsyncMock()
        with patch.object(recipes, "_catalog", AsyncMock(return_value=sold_out)), \
             patch.object(recipes.database, "get_cart_line_for_product", AsyncMock(return_value=(None, 0.0))), \
             patch.object(recipes.database, "add_to_cart", add):
            res = run(recipes.add_all_to_cart(77, RECIPES[0], "uz"))
        self.assertIn("Psillium uni", res["missing"])
        self.assertNotIn(3, [c.kwargs["product_id"] for c in add.await_args_list])

    def test_labels_in_every_language(self):
        self.assertEqual(recipes.labels("uz")["add_all"], "🛒 Barcha masalliqlarni savatga")
        self.assertIn("корзину", recipes.labels("ru")["add_all"])
        self.assertIn("саватга", recipes.labels("uz_cyr")["add_all"])


if __name__ == "__main__":
    unittest.main()
