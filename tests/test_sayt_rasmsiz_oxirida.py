"""Saytda rasmi yo'q mahsulotlar ro'yxat oxirida (2026-10-11).

* Saralash SQL'da — ro'yxat sahifalarga bo'lingan, brauzerda saralash faqat
  bitta sahifa ichida ishlardi.
* Bo'sh photo_id ham «rasm yo'q».
* Botning o'z katalogi va admin ro'yxatlari o'zgarmaydi (A→Z).
"""
import asyncio
import os
import unittest
from contextlib import asynccontextmanager
from unittest import mock

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database


class _Conn:
    def __init__(self):
        self.sql = []

    async def fetchval(self, sql, *args):
        return 0

    async def fetch(self, sql, *args):
        self.sql.append(sql)
        return []


class _Pool:
    def __init__(self):
        self.conn = _Conn()

    def acquire(self):
        @asynccontextmanager
        async def cm():
            yield self.conn
        return cm()


PHOTO_TERM = "(NULLIF(TRIM(p.photo_id), '') IS NULL) ASC"


class PhotosFirstSqlTest(unittest.TestCase):
    def _sql(self, coro_fn):
        pool = _Pool()
        with mock.patch.object(database, "pool", pool):
            asyncio.run(coro_fn())
        return pool.conn.sql[-1]

    def test_on_puts_photo_term_first(self):
        for fn in (lambda: database.get_products_by_category("flour", photos_first=True),
                   lambda: database.get_discounted_products(photos_first=True),
                   lambda: database.get_all_products_paginated(photos_first=True)):
            sql = self._sql(fn)
            order = sql[sql.index("ORDER BY"):]
            self.assertTrue(order.startswith(f"ORDER BY {PHOTO_TERM}, LOWER(p.name)"), order)

    def test_off_by_default_keeps_a_to_z(self):
        for fn in (lambda: database.get_products_by_category("flour"),
                   lambda: database.get_discounted_products(),
                   lambda: database.get_all_products_paginated()):
            sql = self._sql(fn)
            self.assertNotIn("photo_id", sql)
            self.assertIn("ORDER BY LOWER(p.name) ASC, p.id ASC", sql)


class SiteUsesItTest(unittest.TestCase):
    def test_site_list_endpoints_ask_for_photos_first(self):
        import webapp_server
        empty = mock.AsyncMock(return_value=([], 0))
        request = mock.Mock()
        request.get = lambda k, d=None: {"user_lang": "uz"}.get(k, d)
        with mock.patch.object(webapp_server, "get_products_by_category", empty) as by_cat, \
             mock.patch.object(webapp_server, "get_all_products_paginated", empty) as all_, \
             mock.patch.object(webapp_server, "get_discounted_products", empty) as disc:
            for cat in ("flour", "", "discounts"):
                request.query = {"category": cat, "page": "0"}
                if cat == "flour":
                    with mock.patch.object(webapp_server, "CATEGORIES", {"flour": {}}):
                        asyncio.run(webapp_server.api_products(request))
                else:
                    asyncio.run(webapp_server.api_products(request))
        for m in (by_cat, all_, disc):
            self.assertTrue(m.await_args.kwargs.get("photos_first"), m)


if __name__ == "__main__":
    unittest.main()
