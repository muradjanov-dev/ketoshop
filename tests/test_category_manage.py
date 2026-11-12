"""Bo'limlar (kategoriyalar) boshqaruvi — egasi, 2026-11-12: "ortiqcha
bo'limlarni o'chirib tashla, va admin panelga ortiqcha bo'limlarni o'chirish
va tahrirlash imkoniyatini ham qo'shgin". Baza soxta (xotirada)."""
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("ADMIN_WEB_PASSWORD", "test-password")

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import admin_web
import category_corrections
import database
import keyboards
import locales


class FakeStore:
    def __init__(self):
        self.cats = [
            {"id": 1, "key": "keto_flour", "name_uz": "🥣 Keto unlar", "name_ru": "🥣 Кето мука", "is_active": 1, "sort_order": 0},
            {"id": 2, "key": "salt", "name_uz": "🧂 Tuz", "name_ru": "🧂 Соль", "is_active": 1, "sort_order": 1},
            {"id": 3, "key": "qovoq_uni", "name_uz": "Qovoq uni", "name_ru": "Qovoq uni", "is_active": 1, "sort_order": 2},
        ]
        self.products = [{"category": "keto_flour", "is_active": 1}, {"category": "keto_flour", "is_active": 0},
                         {"category": "salt", "is_active": 1}]

    async def get_categories(self, active_only=True):
        return [dict(c) for c in self.cats if c["is_active"] or not active_only]

    async def category_product_counts(self):
        out = {}
        for p in self.products:
            c = out.setdefault(p["category"], {"total": 0, "active": 0})
            c["total"] += 1
            c["active"] += p["is_active"]
        return out

    async def update_category(self, key, *, name_uz=None, name_ru=None, is_active=None):
        for c in self.cats:
            if c["key"] == key:
                if name_uz is not None:
                    c["name_uz"] = name_uz
                if name_ru is not None:
                    c["name_ru"] = name_ru
                if is_active is not None:
                    c["is_active"] = 1 if is_active else 0
                return dict(c)
        return None

    async def delete_category(self, key, move_to=None):
        if not any(c["key"] == key for c in self.cats):
            return {"deleted": False, "moved": 0, "products": 0, "error": "not_found"}
        n = sum(1 for p in self.products if p["category"] == key)
        if n and not any(c["key"] == move_to for c in self.cats if c["key"] != key):
            return {"deleted": False, "moved": 0, "products": n, "error": "has_products"}
        for p in self.products:
            if p["category"] == key:
                p["category"] = move_to
        self.cats = [c for c in self.cats if c["key"] != key]
        return {"deleted": True, "moved": n, "products": n, "error": None}


class ApiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = FakeStore()
        for name in ("get_categories", "category_product_counts", "update_category", "delete_category"):
            p = patch.object(database, name, getattr(self.store, name))
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(admin_web, "ADMIN_WEB_PASSWORD", "test-password")
        p.start()
        self.addCleanup(p.stop)
        app = web.Application()
        admin_web.setup_admin_routes(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.client.session.cookie_jar.update_cookies({admin_web.SESSION_COOKIE: admin_web._make_session()})

    async def test_list_shows_every_category_with_product_counts(self):
        r = await self.client.get("/admin/api/categories")
        data = await r.json()
        rows = {c["key"]: c for c in data["categories"]}
        self.assertEqual((rows["keto_flour"]["total"], rows["keto_flour"]["active"]), (2, 1))
        self.assertEqual((rows["qovoq_uni"]["total"], rows["qovoq_uni"]["active"]), (0, 0))

    async def test_rename_and_hide(self):
        r = await self.client.post("/admin/api/categories/salt", json={"name_uz": "🧂 Himalay tuzi", "name_ru": ""})
        self.assertEqual(r.status, 200, await r.text())
        self.assertEqual(self.store.cats[1]["name_uz"], "🧂 Himalay tuzi")
        r = await self.client.post("/admin/api/categories/salt", json={"is_active": False})
        self.assertEqual(r.status, 200)
        self.assertEqual(self.store.cats[1]["is_active"], 0)
        bad = await self.client.post("/admin/api/categories/salt", json={"name_uz": "  "})
        self.assertEqual(bad.status, 400)

    async def test_empty_category_is_deleted(self):
        r = await self.client.post("/admin/api/categories/qovoq_uni/delete", json={})
        self.assertEqual(r.status, 200, await r.text())
        self.assertNotIn("qovoq_uni", [c["key"] for c in self.store.cats])

    async def test_category_with_products_needs_a_new_home(self):
        r = await self.client.post("/admin/api/categories/keto_flour/delete", json={})
        self.assertEqual(r.status, 409)
        self.assertIn("2 ta mahsulot", (await r.json())["error"])
        self.assertIn("keto_flour", [c["key"] for c in self.store.cats])
        r = await self.client.post("/admin/api/categories/keto_flour/delete", json={"move_to": "salt"})
        self.assertEqual(r.status, 200, await r.text())
        self.assertEqual([p["category"] for p in self.store.products], ["salt", "salt", "salt"])

    async def test_unknown_or_odd_keys(self):
        self.assertEqual((await self.client.post("/admin/api/categories/nope/delete", json={})).status, 404)
        self.assertEqual((await self.client.post("/admin/api/categories/Bad Key", json={"name_uz": "x"})).status, 404)

    async def test_needs_the_password(self):
        self.client.session.cookie_jar.clear()
        self.assertEqual((await self.client.get("/admin/api/categories")).status, 401)


class BotButtonsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.saved = list(locales.CATEGORIES)
        self.addCleanup(lambda: locales.CATEGORIES.__setitem__(slice(None), self.saved))

    async def test_hidden_or_deleted_categories_leave_the_bot_keyboard(self):
        store = FakeStore()
        store.cats[1]["is_active"] = 0            # «Tuz» hidden — it is in the original hardcoded list too
        locales.CATEGORIES[:] = ["keto_flour", "salt", "pp_flour", "qovoq_uni"]
        with patch.object(database, "get_categories", store.get_categories):
            await database.sync_categories_to_locales()
        self.assertEqual(locales.CATEGORIES, ["keto_flour", "qovoq_uni"])
        locales.unregister_category("qovoq_uni")
        kb = keyboards.categories_keyboard("uz")
        data = [b.callback_data for row in kb.inline_keyboard for b in row]
        self.assertIn("cat:keto_flour", data)
        self.assertNotIn("cat:salt", data)
        self.assertNotIn("cat:qovoq_uni", data)


class CleanupListTest(unittest.TestCase):
    def test_the_six_empty_categories_from_the_screenshot(self):
        self.assertEqual(sorted(category_corrections.DELETE_IF_EMPTY["category-cleanup-2026-11-12"]),
                         sorted(["tabiiy_soklar", "sok_vitamin", "eko_vitamin_sok", "eko_vitamin_sok_2",
                                 "qovoq_uni", "bodom_unida_pechiniy"]))
        self.assertIn("category-cleanup-2026-11-12", category_corrections.FIXES)


if __name__ == "__main__":
    unittest.main()
