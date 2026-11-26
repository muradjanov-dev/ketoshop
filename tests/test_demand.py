"""🧭 Talab bo'limi (demand.py, egasi 2026-11-26). Bazasiz, tarmoqsiz."""
import asyncio
import os
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
import demand


class NameTest(unittest.TestCase):
    def test_base_name_drops_sizes_and_brands(self):
        self.assertEqual(demand.base_name("Bodom uni 500gr"), "bodom uni")
        self.assertEqual(demand.base_name("Qora guruch 1kg Tayland"), "qora guruch")
        self.assertEqual(demand.base_name("STEVIYA 5kg"), "steviya")
        self.assertEqual(demand.base_name("Toza Steviya 20gr"), "toza steviya")

    def test_question_matches_with_suffixes_and_cyrillic(self):
        rx = demand._pattern("bodom uni")
        for text in ("bodom unidan retsept bering", "Bodom uni bormi?", "бодом уни қанча?"):
            self.assertTrue(rx.search(demand._latin(text)), text)
        self.assertFalse(rx.search(demand._latin("kokos uni bormi")))


class CollectTest(unittest.TestCase):
    def test_counts_products_topics_channels_and_signals(self):
        now = datetime(2026, 11, 26, 10)
        rows = [
            {"channel": "bot", "user": "1", "text": "bodom uni bormi? narxi qancha", "at": now},
            {"channel": "instagram", "user": "ali", "text": "Bodom uni qancha turadi", "at": now},
            {"channel": "direct", "user": "x", "text": "бодом уни борми", "at": now},
            {"channel": "group", "user": "2", "text": "chia urug'i retsept", "at": now},
            {"channel": "search", "user": "3", "text": "kunjut pastasi", "at": now},
        ]
        products = [
            {"id": 1, "name": "Bodom uni 500gr", "quantity": 0, "b2b_only": False},
            {"id": 2, "name": "Bodom uni 1000gr", "quantity": 0, "b2b_only": False},
            {"id": 3, "name": "Chia urug'i 300gr", "quantity": 9, "b2b_only": False},
        ]
        with patch.object(demand, "_rows", AsyncMock(return_value=rows)), \
                patch.object(demand, "_site_products", AsyncMock(return_value={3: {"opens": 4, "cart_adds": 1}})), \
                patch.object(database, "admin_list_products", AsyncMock(return_value=products)), \
                patch.object(database, "get_product_sales",
                             AsyncMock(return_value={"rows": [{"kind": "product", "id": 3, "qty": 2}]})):
            stats = asyncio.run(demand.collect("30d"))
        self.assertEqual(stats["messages"], 5)
        bodom = next(g for g in stats["products"] if g["name"] == "bodom uni")
        self.assertEqual((bodom["asked"], bodom["asked_users"]), (3, 3))
        self.assertIn("tugagan", bodom["signal"])
        self.assertEqual(stats["products"][0]["name"], "bodom uni")          # eng ko'p so'ralgan birinchi
        chia = next(g for g in stats["products"] if g["name"] == "chia urug'i")
        self.assertEqual((chia["sold"], chia["opens"]), (2, 4))
        self.assertEqual(stats["unmet"], [{"q": "kunjut pastasi", "n": 1}])
        topics = {t["key"]: t["n"] for t in stats["topics"]}
        self.assertGreaterEqual(topics.get("narx", 0), 2)
        self.assertEqual(topics.get("retsept"), 1)
        self.assertIn("instagram", {c["key"] for c in stats["channels"]})

    def test_advice_is_cached_per_period(self):
        stats = {"messages": 1, "people": 1, "channels": [], "products": [], "topics": [], "unmet": []}
        import comment_ai
        ask = AsyncMock(return_value={"advice": ["📦 Bodom unini keltiring — 12 kishi so'radi, tugagan"]})
        demand._advice_cache.clear()
        with patch.object(comment_ai, "_openai_key", AsyncMock(return_value="sk")), \
                patch.object(comment_ai, "_ask_openai", ask):
            first = asyncio.run(demand.advice("k", stats))
            second = asyncio.run(demand.advice("k", stats))
        self.assertEqual(first, second)
        ask.assert_awaited_once()

    def test_dashboard_has_the_section_on_top(self):
        html = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webapp",
                                 "admin.html"), encoding="utf-8").read()
        self.assertLess(html.index('id="kpiGrid"'), html.index('id="demandCard"'))
        self.assertLess(html.index('id="demandCard"'), html.index('id="dailyChart"'))
        self.assertIn("loadDemand(q);", html)


if __name__ == "__main__":
    unittest.main()
