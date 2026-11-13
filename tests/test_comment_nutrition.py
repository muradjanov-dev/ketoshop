"""Izohlar AI'si uglevod, kaloriya va tarkib savollariga katalogdan javob beradi
(2026-11-13: «Шу махсулотларда канча углевод бор», «Эритрит кушилганми» javobsiz qolgan)."""
import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://ci:ci@localhost:5432/ci")
os.environ.setdefault("BOT_TOKEN", "123456:CI-TOKEN")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import comment_ai  # noqa: E402
import database  # noqa: E402
import meta_comments  # noqa: E402


class FactsTest(unittest.TestCase):
    def test_numbers_per_100g_for_a_plain_product(self):
        facts = comment_ai.product_facts({"name": "Eritritol 500gr"})
        self.assertIn("100 g: ~20 kkal · uglevod 0 g", facts)
        self.assertIn("✅ keto", facts)

    def test_mixed_goods_get_no_borrowed_numbers(self):
        for name in ("BODOM UNIDAN PECHENIY", "Kepakli un makaron vermishel 500g",
                     "Barilla spagetti Kepakli undan", "Grechka unli vermishel makaron 500g", "Qovoq uni"):
            self.assertNotIn("kkal", comment_ai.product_facts({"name": name}), name)

    def test_unknown_product_gets_nothing_invented(self):
        self.assertEqual(comment_ai.product_facts({"name": "Dos bros"}), "")

    def test_variant_note_rides_along(self):
        facts = comment_ai.product_facts({"name": "Uy kuvi saryog'i 800gr"})
        self.assertIn("oddiy sariyog' — taxminan 740 kkal", facts)

    def test_short_composition_is_added_long_one_is_not(self):
        self.assertIn("tarkibi: 100% bodom", comment_ai.product_facts({"name": "Bodom uni 500gr",
                                                                       "composition": "100% bodom"}))
        long = "x" * (comment_ai.COMPOSITION_MAX + 1)
        self.assertNotIn("tarkibi", comment_ai.product_facts({"name": "Dos bros", "composition": long}))


class CatalogTest(unittest.TestCase):
    def test_catalog_lines_keep_prices_and_carry_facts(self):
        products = [{"name": "Eritritol 500gr", "quantity": 5, "price": 76000, "category": "s"},
                    {"name": "Psillium 1kg", "quantity": 0, "price": 150000, "category": "s",
                     "composition": "100% psillium, tola"}]
        with patch.object(database, "admin_list_products", AsyncMock(return_value=products)), \
                patch("manual_order.shelf_price", lambda p: p["price"]), \
                patch.object(comment_ai, "_catalog_cache", (0.0, "")):
            text = asyncio.run(comment_ai.catalog_text())
        self.assertIn("- Eritritol 500gr — 76 000 so'm · 100 g: ~20 kkal · uglevod 0 g", text)
        self.assertIn("- Psillium 1kg — 150 000 so'm (tugagan) · 100 g:", text)
        self.assertIn("tarkibi: 100% psillium, tola", text)        # the comma survives


class RulesTest(unittest.TestCase):
    def test_rules_answer_numbers_only_from_the_catalog(self):
        self.assertIn("Uglevod, kaloriya, GI yoki tarkib so'ralsa", comment_ai.RULES)
        self.assertIn("o'ylab\n  topma, confident=false", comment_ai.RULES.replace("\r", ""))

    def test_unanswerable_ones_are_rechecked_once_after_this_change(self):
        self.assertEqual(meta_comments.RECHECK_KEY_D, "meta_comments_recheck_2026_11_13d")


if __name__ == "__main__":
    unittest.main()
