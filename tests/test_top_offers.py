"""⭐ TOP takliflar — saytning tepasidagi banner va popup (egasi, 2026-11-26:
"5 kg va 2 kg lik steviyalarni saytda top mahsulotlar deb pop up chiqar")."""
import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
import webapp_server as ws


class TopOffersTest(unittest.TestCase):
    def _call(self, products):
        async def get_product(pid):
            return products.get(pid)
        serialized = AsyncMock(side_effect=lambda ps, lang, uid: [{"id": p["id"]} for p in ps])
        request = {"user_lang": "uz", "user_id": 5}
        with patch.object(ws, "TOP_OFFER_IDS", (173, 174)), \
                patch.object(database, "get_product", get_product), \
                patch.object(ws, "_serialize_products", serialized):
            resp = asyncio.run(ws.api_top_offers(request))
        return json.loads(resp.text)

    def test_only_active_discounted_in_stock(self):
        on = {"is_active": 1, "b2b_only": False, "quantity": 600, "discount_percent": 52, "discount_until": None}
        self.assertEqual(self._call({173: dict(on, id=173), 174: dict(on, id=174)}), [{"id": 173}, {"id": 174}])
        self.assertEqual(self._call({173: dict(on, id=173, discount_percent=0),
                                     174: dict(on, id=174, quantity=0)}), [])

    def test_banner_is_at_the_very_top_of_home_and_respects_reduced_motion(self):
        html = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webapp",
                                 "index.html"), encoding="utf-8").read()
        home = html.index('id="page-home"')
        self.assertLess(home, html.index('id="top-offer-banner"'))
        self.assertLess(html.index('id="top-offer-banner"'), html.index('id="home-recipe"'))
        self.assertIn(".top-offer, .top-offer::after, .top-offer .to-badge { animation: none; }", html)
        self.assertIn("loadTopOffers();", html)


if __name__ == "__main__":
    unittest.main()
