"""«🔥 Ko'p olinadi»: ko'p buyurtmada uchragan mahsulot oldinda, ulgurji va
ichki akkauntlar hisobga kirmaydi; retsept paneli matnlari hamma tilda."""
import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
import recipes
from database import LEADERBOARD_EXCLUDED_USER_IDS, popular_ranking

BUYER = 1001
INTERNAL = next(iter(LEADERBOARD_EXCLUDED_USER_IDS))


def order(items, user_id=BUYER, source="bot", as_text=False):
    lines = [{"product_id": pid, "quantity": q} for pid, q in items]
    return {"items": json.dumps(lines) if as_text else lines, "user_id": user_id, "source": source}


class RankingTest(unittest.TestCase):
    def test_counts_orders_not_quantity(self):
        # One bulk line of product 1 must not beat product 2 that three
        # different orders carried.
        rows = [order([(1, 500)]), order([(2, 1)]), order([(2, 1)]), order([(2, 2)])]
        self.assertEqual(popular_ranking(rows), [2, 1])

    def test_an_order_counts_once_per_product(self):
        rows = [order([(1, 1), (1, 1), (1, 1)]), order([(2, 1)]), order([(2, 1)])]
        self.assertEqual(popular_ranking(rows), [2, 1])

    def test_ties_go_to_larger_quantity(self):
        rows = [order([(1, 1)]), order([(2, 3)])]
        self.assertEqual(popular_ranking(rows), [2, 1])

    def test_b2b_is_left_out(self):
        rows = [order([(1, 1)], source="b2b"), order([(1, 1)], source="b2b"), order([(2, 1)])]
        self.assertEqual(popular_ranking(rows), [2])

    def test_internal_accounts_are_left_out(self):
        rows = [order([(1, 1)], user_id=INTERNAL), order([(1, 1)], user_id=INTERNAL), order([(2, 1)])]
        self.assertEqual(popular_ranking(rows), [2])

    def test_manual_order_counts_even_when_an_admin_typed_it(self):
        # A manual order's user_id is the admin who logged it; the buyer is real.
        rows = [order([(1, 1)], user_id=INTERNAL, source="manual"),
                order([(1, 1)], user_id=INTERNAL, source="manual"), order([(2, 1)])]
        self.assertEqual(popular_ranking(rows), [1, 2])

    def test_items_stored_as_text_and_null_source(self):
        rows = [order([(3, 1)], source=None, as_text=True)]
        self.assertEqual(popular_ranking(rows), [3])

    def test_lines_without_product_are_skipped(self):
        rows = [{"items": [{"set_id": 5, "quantity": 1}, {"product_id": 4, "quantity": 1}],
                 "user_id": BUYER, "source": "bot"}]
        self.assertEqual(popular_ranking(rows), [4])


class _Conn:
    def __init__(self, orders, products):
        self.orders, self.products, self.queries = orders, products, []

    async def fetch(self, sql, *args):
        self.queries.append(sql)
        if "FROM orders" in sql:
            return self.orders
        ids = args[0]
        return [p for p in self.products if p["id"] in ids]


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return pool.conn

            async def __aexit__(self, *exc):
                return False
        return _Ctx()


class PopularProductsTest(unittest.TestCase):
    def test_keeps_ranking_order_and_limit(self):
        orders = [order([(1, 1)]), order([(2, 1)]), order([(2, 1)]), order([(3, 1)]),
                  order([(3, 1)]), order([(3, 1)])]
        products = [{"id": 1}, {"id": 2}, {"id": 3}]       # DB order is not rank order
        conn = _Conn(orders, products)
        with patch.object(database, "pool", _Pool(conn)):
            got = asyncio.run(database.get_popular_products(limit=2))
        self.assertEqual([p["id"] for p in got], [3, 2])
        # Sold-out and wholesale-only products never reach the one-tap row.
        product_sql = conn.queries[1]
        self.assertIn("p.quantity > 0", product_sql)
        self.assertIn("b2b_only", product_sql)
        self.assertIn("is_active = 1", product_sql)

    def test_no_orders_means_no_row(self):
        conn = _Conn([], [{"id": 1}])
        with patch.object(database, "pool", _Pool(conn)):
            self.assertEqual(asyncio.run(database.get_popular_products()), [])
        self.assertEqual(len(conn.queries), 1)


class ApiPopularTest(unittest.TestCase):
    def test_endpoint_is_cached_and_serialized(self):
        import webapp_server
        webapp_server._POPULAR_CACHE.clear()
        rows = [{"id": 7, "name": "Bodom uni"}]
        fetch = AsyncMock(return_value=rows)
        ser = AsyncMock(return_value=[{"id": 7}])

        class Req(dict):
            pass
        req = Req(user_lang="uz", user_id=1001)
        with patch.object(webapp_server, "get_popular_products", fetch), \
             patch.object(webapp_server, "_serialize_products", ser):
            asyncio.run(webapp_server.api_popular(req))
            resp = asyncio.run(webapp_server.api_popular(req))
        self.assertEqual(fetch.await_count, 1)          # second call from the cache
        self.assertEqual(json.loads(resp.text), [{"id": 7}])
        self.assertEqual(ser.await_args.args[0], rows)


class RecipeBarLabelsTest(unittest.TestCase):
    def test_bar_labels_in_every_language(self):
        for lang in ("uz", "ru", "uz_cyr"):
            labels = recipes.labels(lang)
            for key in ("bar_title", "bar_count", "bar_btn", "go_cart"):
                self.assertTrue(labels[key], f"{lang}:{key}")
            self.assertIn("{n}", labels["bar_count"], lang)
        # Never "everything for this recipe": some ingredients come from home.
        self.assertEqual(recipes.labels("uz")["bar_title"], "Retseptdagi Ketoshop mahsulotlari")
        for lang in ("uz", "ru", "uz_cyr"):
            title = recipes.labels(lang)["bar_title"].lower()
            for word in ("hammasi", "всё", "ҳаммаси"):
                self.assertNotIn(word, title, lang)
        self.assertIn("корзин", recipes.labels("ru")["bar_btn"])
        self.assertIn("Саватга", recipes.labels("uz_cyr")["bar_btn"])


if __name__ == "__main__":
    unittest.main()
