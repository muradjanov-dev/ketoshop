"""/admin/api/reviews — barcha sharhlar, faqat o'qish, admin paroli bilan
(egasi, 2026-10-16). Bazaga ulanmasdan."""
import asyncio
import json
import os
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from aiohttp import web

import admin_web
import database

ROWS = [
    {"id": 9, "rating": 5, "comment": "  Juda mazali!  ", "created_at": datetime(2026, 10, 12, 9, 30),
     "user_id": 11, "product_id": 3, "product_name": "Bodom uni 200gr",
     "full_name": "Malika", "username": "malika", "internal": False},
    {"id": 4, "rating": 3, "comment": None, "created_at": datetime(2026, 9, 1, 8, 0),
     "user_id": 425609051, "product_id": None, "product_name": None,
     "full_name": None, "username": None, "internal": True},
]


class ReviewsApiTest(unittest.TestCase):
    def call(self, authed=True):
        with patch.object(admin_web, "ADMIN_WEB_PASSWORD", "secret"), \
             patch.object(admin_web, "_authed", lambda request: authed), \
             patch.object(database, "get_all_reviews", AsyncMock(return_value=ROWS)) as get:
            resp = asyncio.run(admin_web.api_reviews(object()))
        return resp, get

    def test_needs_the_admin_password(self):
        resp, get = self.call(authed=False)
        self.assertEqual(resp.status, 401)
        get.assert_not_awaited()

    def test_every_review_with_product_and_author(self):
        resp, _ = self.call()
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.body)["reviews"]
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0], {
            "id": 9, "rating": 5, "comment": "Juda mazali!", "created_at": "2026-10-12T09:30:00",
            "product_id": 3, "product": "Bodom uni 200gr", "author": "Malika",
            "username": "malika", "user_id": 11, "internal": False,
        })
        # A deleted product or a missing user row still comes through.
        self.assertEqual((data[1]["product"], data[1]["comment"], data[1]["internal"]), ("", "", True))

    def test_route_is_registered(self):
        app = web.Application()
        admin_web.setup_admin_routes(app)
        routes = {(r.method, r.resource.canonical) for r in app.router.routes()}
        self.assertIn(("GET", "/admin/api/reviews"), routes)


if __name__ == "__main__":
    unittest.main()
