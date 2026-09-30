"""Checkout "stock_gone" xabari mahsulot nomini va qolgan sonni aytadi."""
import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import handlers.cart as cart
import webapp_server
from database import InsufficientStockError

P = {"id": 7, "name": "Kokos qirindisi 200gr", "name_ru": "Кокосовая стружка 200г"}


class StockGoneTextTest(unittest.TestCase):
    def _bot(self, exc, lang, product=P):
        with patch.object(cart, "get_product", AsyncMock(return_value=product)):
            return asyncio.run(cart.stock_gone_text(exc, lang))

    def test_low_names_product_and_counts(self):
        t = self._bot(InsufficientStockError(7, 3, 2), "uz")
        self.assertIn("Kokos qirindisi 200gr", t)
        self.assertIn("<b>2</b>", t)
        self.assertIn("3 ta", t)

    def test_out_and_russian_name(self):
        t = self._bot(InsufficientStockError(7, 1, 0), "ru")
        self.assertIn("Кокосовая стружка", t)
        self.assertIn("последний", t)

    def test_unknown_product_falls_back(self):
        t = self._bot(InsufficientStockError(7, 1, 0), "uz", product=None)
        self.assertIn("ulgurmay", t)

    def test_webapp_409_carries_name(self):
        req = {"user_lang": "uz", "user_id": 1}
        with patch.object(webapp_server, "get_product", AsyncMock(return_value=P)):
            resp = asyncio.run(webapp_server._stock_gone(InsufficientStockError(7, 3, 2), req))
        body = json.loads(resp.text)
        self.assertEqual(resp.status, 409)
        self.assertEqual(body["error"], "stock_gone")
        self.assertEqual(body["name"], "Kokos qirindisi 200gr")
        self.assertEqual((body["available"], body["requested"]), (2, 3))


if __name__ == "__main__":
    unittest.main()
