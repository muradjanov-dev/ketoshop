"""To'plamlar (set) saytda savatga tushishi (2026-11-12).

11.11 tahlili: «Keto set» 12 marta ochilgan / 0 marta savatga, «Supper set»
10 / 0 — mahsulotlarda esa 776 ochilishdan 414 tasi savatga. Sabab: set
oynasi doim «Savatga qo'shish» ko'rsatardi (out_of_stock har doim False,
quantity 999), lekin baza (database._line_cap) setni bitta qismi ham
yetmasa savatga qo'ymaydi — xaridor faqat «Savatga qo'shib bo'lmadi» ko'rardi.
Endi /api/set va «To'plamlar» ro'yxati qismlarning qoldig'idan hisoblaydi,
rad javobi yetmagan qismni aytadi, «Kelganda xabar bering» qismlarni kutadi.
Baza va Telegram — mock."""
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import bot_discount
import database
import webapp_server


def a_set(active=1, items=None):
    items = items if items is not None else [
        {"product_id": 1, "quantity": 1.0, "name": "Bodom uni 500gr", "name_ru": "Миндальная мука 500г",
         "price": 98000, "unit": "piece", "image_url": None, "photo_id": "AgADfile", "is_active": 1},
        {"product_id": 4, "quantity": 1.0, "name": "Eritritol 500gr", "name_ru": None,
         "price": 85000, "unit": "piece", "image_url": "/img/9", "photo_id": None, "is_active": 1},
        {"product_id": 8, "quantity": 2.0, "name": "Chia urug'i 300gr", "name_ru": None,
         "price": 42000, "unit": "kg", "image_url": None, "photo_id": None, "is_active": 1},
    ]
    return {"id": 7, "name": "Keto set", "name_ru": "Кето набор", "set_price": 230000,
            "description": "Boshlash uchun", "description_ru": None, "image_url": "/img/3",
            "is_active": active, "items": items,
            "original_total": sum(i["price"] * i["quantity"] for i in items)}


def view(free, shelf=None):
    """stock_view's answer: {pid: {shelf, held, free}}."""
    shelf = shelf or {}
    return {pid: {"shelf": shelf.get(pid, f), "held": shelf.get(pid, f) - f, "free": f}
            for pid, f in free.items()}


class Request(dict):
    def __init__(self, body=None, match=None, query=None, user_id=101, lang="uz"):
        super().__init__(user_id=user_id, user_lang=lang)
        self._body = body or {}
        self.match_info = match or {}
        self.query = query or {}
        self.app = {"bot": None}

    async def json(self):
        return self._body


def body_of(resp):
    return json.loads(resp.body)


class SetCapacityTest(unittest.TestCase):
    items = a_set()["items"]

    def test_the_scarcest_part_decides(self):
        got = webapp_server.set_capacity(self.items, view({1: 5, 4: 3, 8: 5}))
        self.assertEqual(got, {"available": 2, "short": [], "held": False})   # chia: 5 // 2

    def test_a_missing_part_stops_the_set(self):
        got = webapp_server.set_capacity(self.items, view({1: 5, 4: 0, 8: 1}))
        self.assertEqual(got["available"], 0)
        self.assertEqual(got["short"], [4, 8])          # eritritol out, chia 1 < 2
        self.assertFalse(got["held"])

    def test_parts_only_held_in_other_carts_are_band(self):
        got = webapp_server.set_capacity(self.items, view({1: 5, 4: 0, 8: 4}, shelf={4: 2}))
        self.assertEqual((got["available"], got["short"], got["held"]), (0, [4], True))

    def test_an_archived_part_or_unknown_product_is_missing(self):
        items = [dict(self.items[0], is_active=0), self.items[1]]
        self.assertEqual(webapp_server.set_capacity(items, view({1: 9, 4: 9}))["short"], [1])
        self.assertEqual(webapp_server.set_capacity(self.items[:1], {})["short"], [1])

    def test_a_set_without_parts_never_ran_out(self):
        got = webapp_server.set_capacity([], {})
        self.assertEqual(got["available"], int(database.SET_WITHOUT_ITEMS_STOCK))
        self.assertEqual(got["short"], [])


class _Patched(unittest.IsolatedAsyncioTestCase):
    free = {1: 5, 4: 3, 8: 6}
    shelf = None

    def setUp(self):
        self.set = a_set()
        self.stock = AsyncMock(side_effect=lambda pids, viewer: view(
            {p: self.free.get(p, 0) for p in pids}, self.shelf))
        for p in [
            patch.object(database, "get_set", AsyncMock(side_effect=lambda sid: self.set if sid == 7 else None)),
            patch.object(database, "stock_view", self.stock),
            patch.object(bot_discount, "display_price", AsyncMock(return_value=None)),
            patch.object(bot_discount, "display_prices", AsyncMock(side_effect=lambda rows: [None] * len(rows))),
        ]:
            p.start()
            self.addCleanup(p.stop)


class SetDetailTest(_Patched):
    async def test_in_stock_set_is_orderable_up_to_the_scarcest_part(self):
        d = body_of(await webapp_server.api_set_detail(Request(match={"id": "7"})))
        self.assertFalse(d["out_of_stock"])
        self.assertEqual(d["quantity"], 3)                  # eritritol 3, chia 6 // 2
        self.assertEqual(d["unit"], "dona")                 # not the raw "piece"
        self.assertEqual([i["out_of_stock"] for i in d["items"]], [False, False, False])
        self.assertEqual([i["quantity"] for i in d["items"]], [1, 1, 2])
        self.assertEqual(d["items"][0]["photo_url"], "/api/photo/AgADfile")
        self.assertEqual(d["items"][1]["photo_url"], "/img/9")
        self.assertEqual(d["original_total"], 98000 + 85000 + 2 * 42000)
        self.assertEqual(d["description"], "Boshlash uchun")
        self.stock.assert_awaited_once()
        self.assertEqual(self.stock.await_args.args[1], 101)   # other buyers' holds, not their own

    async def test_set_with_a_missing_part_says_so(self):
        self.free = {1: 5, 4: 0, 8: 6}
        d = body_of(await webapp_server.api_set_detail(Request(match={"id": "7"}, lang="ru")))
        self.assertTrue(d["out_of_stock"])
        self.assertFalse(d["held_out"])
        self.assertEqual(d["quantity"], 0)
        self.assertEqual([i["out_of_stock"] for i in d["items"]], [False, True, False])
        self.assertEqual(d["items"][0]["name"], "Миндальная мука 500г")
        self.assertEqual(d["unit"], "шт")

    async def test_part_held_in_other_carts_is_band(self):
        self.free, self.shelf = {1: 5, 4: 0, 8: 6}, {4: 1}
        d = body_of(await webapp_server.api_set_detail(Request(match={"id": "7"})))
        self.assertTrue(d["out_of_stock"] and d["held_out"])

    async def test_archived_set_is_not_found(self):
        self.set = a_set(active=0)
        resp = await webapp_server.api_set_detail(Request(match={"id": "7"}))
        self.assertEqual(resp.status, 404)


class SetsCategoryTest(_Patched):
    async def test_catalog_marks_a_set_whose_part_ran_out(self):
        second = dict(a_set(), id=8, name="Supper set",
                      items=[dict(a_set()["items"][0])])
        self.free = {1: 5, 4: 0, 8: 6}
        with patch.object(database, "get_active_sets_for_catalog", AsyncMock(return_value=[self.set, second])):
            d = body_of(await webapp_server.api_products(Request(query={"category": "sets"})))
        by_id = {p["id"]: p for p in d["products"]}
        self.assertTrue(by_id[7]["out_of_stock"])          # «Yo'lda 🚚» on the card, still listed
        self.assertFalse(by_id[8]["out_of_stock"])
        self.assertEqual(by_id[8]["quantity"], 5)
        self.assertTrue(all(p["is_set"] for p in d["products"]))
        self.assertEqual(self.stock.await_count, 1)        # one stock query for every set


class SetCartAddTest(_Patched):
    def patches(self, line_after):
        added = AsyncMock(return_value=line_after)
        ps = [patch.object(database, "get_cart_line_for_set", AsyncMock(return_value=(None, 0.0))),
              patch.object(webapp_server, "ensure_site_user", AsyncMock(return_value=True)),
              patch.object(webapp_server, "add_to_cart", added),
              patch.object(webapp_server, "_limit_reason", AsyncMock(return_value="out_of_stock")),
              patch("handlers.cart.send_added_to_cart", AsyncMock())]
        for p in ps:
            p.start()
            self.addCleanup(p.stop)
        return added

    async def test_refused_set_names_the_missing_part(self):
        self.free = {1: 5, 4: 0, 8: 6}
        self.patches(0.0)
        resp = await webapp_server.api_cart_add(Request(body={"set_id": 7, "quantity": 1}))
        self.assertEqual(resp.status, 409)
        self.assertEqual(body_of(resp), {"error": "out_of_stock", "missing": ["Eritritol 500gr"]})

    async def test_set_in_stock_goes_in(self):
        added = self.patches(1.0)
        resp = await webapp_server.api_cart_add(Request(body={"set_id": 7, "quantity": 1}))
        self.assertEqual(body_of(resp), {"ok": True, "added": 1.0})
        self.assertEqual(added.await_args.kwargs, {"product_id": None, "quantity": 1.0, "set_id": 7})

    async def test_archived_set_never_reaches_the_cart(self):
        self.set = a_set(active=0)
        added = self.patches(1.0)
        resp = await webapp_server.api_cart_add(Request(body={"set_id": 7, "quantity": 1}))
        self.assertEqual(resp.status, 404)
        added.assert_not_awaited()


class SheetMatchesTheCartTest(unittest.IsolatedAsyncioTestCase):
    """The root cause, end to end on the Savat broni SQL (test_cart_holds'
    in-memory connection): what the set sheet offers is exactly what
    database.add_to_cart lets in. Before, the sheet said «in stock, 999»
    while the database put 0 sets in."""

    async def sheet_and_cart(self, shelf):
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from test_cart_holds import FakeConn, FakePool
        conn = FakeConn(shelf, {7: [(1, 1.0), (4, 1.0), (8, 2.0)]})
        with patch.object(database, "pool", FakePool(conn)), \
             patch.object(database, "get_set", AsyncMock(return_value=a_set())), \
             patch.object(bot_discount, "display_price", AsyncMock(return_value=None)):
            sheet = body_of(await webapp_server.api_set_detail(Request(match={"id": "7"})))
            in_cart = await database.add_to_cart(101, set_id=7, quantity=50)
        return sheet, in_cart

    async def test_a_missing_part(self):
        sheet, in_cart = await self.sheet_and_cart({1: 5.0, 4: 0.0, 8: 6.0})
        self.assertEqual(in_cart, 0)
        self.assertTrue(sheet["out_of_stock"])
        self.assertEqual(sheet["quantity"], 0)

    async def test_all_parts_there(self):
        sheet, in_cart = await self.sheet_and_cart({1: 5.0, 4: 2.0, 8: 6.0})
        self.assertEqual(in_cart, 2)
        self.assertFalse(sheet["out_of_stock"])
        self.assertEqual(sheet["quantity"], in_cart)


class SetRestockTest(_Patched):
    async def test_waits_for_the_missing_parts_only(self):
        import restock_notify
        self.free = {1: 5, 4: 0, 8: 1}
        sub = AsyncMock(return_value="added")
        with patch.object(restock_notify, "subscribe", sub):
            resp = await webapp_server.api_restock_wait(Request(body={"set_id": 7}))
        self.assertEqual(body_of(resp), {"ok": True, "status": "added"})
        self.assertEqual([c.args[1] for c in sub.await_args_list], [4, 8])
        self.assertEqual({c.args[3] for c in sub.await_args_list}, {"site"})

    async def test_product_wait_unchanged(self):
        import restock_notify
        sub = AsyncMock(return_value="already")
        with patch.object(restock_notify, "subscribe", sub):
            resp = await webapp_server.api_restock_wait(Request(body={"product_id": 4}))
        self.assertEqual(body_of(resp), {"ok": True, "status": "already"})
        self.assertEqual(sub.await_args.args[:2], (101, 4))


class MiniAppWiringTest(unittest.TestCase):
    """The page side of the three fixes (the clicks themselves were checked
    in Edge on a mocked preview — see the PR)."""
    page = open(os.path.join(os.path.dirname(database.__file__), "webapp", "index.html"),
                encoding="utf-8").read()

    def test_set_sheet(self):
        self.assertIn('id="detail-set"', self.page)
        self.assertIn("renderSetItems(p);", self.page)
        # A set's restock waits for its parts, not for the product with its id.
        self.assertIn("p.is_set ? { set_id: p.id } : { product_id: p.id }", self.page)
        # Reviews are a product's; a set never loads /api/product/<set id>/reviews.
        self.assertIn("if (!p.is_set) loadProductReviews(productId);", self.page)
        for key in ("setItemsTitle", "setItemsCount", "setSeparately", "setPartOut", "setMissing"):
            self.assertEqual(self.page.count(key + ":"), 2, key)        # uz + ru

    def test_catalog_card_add_and_bestseller_badge(self):
        self.assertIn('class="card-add"', self.page)
        self.assertIn("api('/api/popular')", self.page)
        self.assertIn("hotBadgeHtml(p) +", self.page)
        self.assertIn("createProductCard(p, { addBtn: false })", self.page)   # favourites
        self.assertIn("{ set_id: p.id, quantity: 1 } : { product_id: p.id, quantity: 1 }", self.page)

    def test_recipe_cta_and_tracking(self):
        self.assertIn("cta('ings')", self.page)
        self.assertIn("cta('end')", self.page)
        self.assertIn("el.onclick = () => openDetail(p.id);", self.page)
        self.assertIn("'cta:' + (where || 'bar')", self.page)

    def test_recipe_labels_in_every_language(self):
        import recipes
        for lang in ("uz", "uz_cyr", "ru"):
            labels = recipes.labels(lang)
            self.assertTrue(labels["cta"].startswith("🛒"), lang)
            self.assertTrue(labels["end_title"], lang)
        self.assertNotIn("Barcha", recipes.labels("uz")["cta"])   # eggs etc. come from home


if __name__ == "__main__":
    unittest.main()
