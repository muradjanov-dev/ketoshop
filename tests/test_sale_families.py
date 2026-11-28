"""Bir mahsulotning bir nechta qadog'i aksiyada — birga aytiladi (egasi, 2026-11-28: Steviya 2 kg va 5 kg)."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import comment_ai
import database
import ig_direct

PRODUCTS = [
    {"id": 1, "name": "Steviya 2 kg", "price": 300000, "discount_percent": 50, "quantity": 489, "category": "s"},
    {"id": 2, "name": "STEVIYA 5kg", "price": 750000, "discount_percent": 52, "quantity": 694, "category": "s"},
    {"id": 3, "name": "Bodom uni 1000gr", "price": 170000, "discount_percent": 0, "quantity": 9, "category": "f"},
]


class FamilyTest(unittest.TestCase):
    def test_family_and_lines(self):
        self.assertEqual(comment_ai.family("STEVIYA 5kg"), comment_ai.family("Steviya 2 kg"))
        lines = comment_ai.sale_families([(50, "Steviya 2 kg"), (52, "STEVIYA 5kg"), (20, "Bodom uni 1000gr")])
        self.assertEqual(len(lines), 1)
        self.assertIn("STEVIYA 5kg va Steviya 2 kg", lines[0])

    def test_comment_catalog_lists_biggest_first_and_both_packs(self):
        comment_ai._catalog_cache = (0.0, "")
        with patch.object(database, "admin_list_products", AsyncMock(return_value=PRODUCTS)):
            text = asyncio.run(comment_ai.catalog_text())
        sale = text.split("CHEGIRMADAGILAR")[1]
        self.assertLess(sale.index("STEVIYA 5kg"), sale.index("Steviya 2 kg"))
        self.assertIn("BIR MAHSULOTNING BIR NECHTA QADOG'I AKSIYADA", text)
        self.assertIn("BIR NECHTA QADOQ", comment_ai.RULES)
        comment_ai._catalog_cache = (0.0, "")

    def test_direct_block(self):
        items = [dict(p, old=p["price"], new=p["price"] / 2, d=p["discount_percent"]) for p in PRODUCTS[:2]]
        block = ig_direct.discount_block(items)
        self.assertIn("ikkalasini birga ayt", block)
        self.assertIn("STEVIYA 5kg va Steviya 2 kg", block)


if __name__ == "__main__":
    unittest.main()
