"""Katalog tartibi (egasi, 2026-11-08: "saytda chiqayotgan mahsulotlarni ham
kategoriyalab ko'rsat"; "birxil kategoriyada bir xil nomlilar yonma yon
chiqsin"; "botda ham").

Checked in Edge while writing this: «Hammasi» goes category by category in
the tiles' order, each under «<nomi> · N ta mahsulot · Hammasi →»; Bodom uni
500gr → 1000gr, Stevia 200gr → 1000g, Kokos yog'i 500 ml → 1 l side by side;
tapping a heading opens its category."""
import asyncio
import json
import os
import shutil
import subprocess
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
from catalog_order import base_name, size_of, sort_key

PAGE = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webapp", "index.html"),
            encoding="utf-8").read().replace("\r\n", "\n")
NAMES = ["Stevia 1000g", "Eritritol 500gr", "Stevia 200gr", "Eritritol 1 kg", "Alluloza + Steviya 200gr",
         "Kokos yog'i 1 l", "Kokos yog'i 500 ml", "Стевиа 200гр", "Стевиа 1кг", "Kepak (sredniy)", "Grechka 200 гречка"]
EXPECTED = ["Alluloza + Steviya 200gr", "Eritritol 500gr", "Eritritol 1 kg", "Grechka 200 гречка", "Kepak (sredniy)",
            "Kokos yog'i 500 ml", "Kokos yog'i 1 l", "Stevia 200gr", "Stevia 1000g", "Стевиа 200гр", "Стевиа 1кг"]


class RuleTest(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(size_of("Stevia 1000g"), 1000)
        self.assertEqual(size_of("Eritritol 1 kg"), 1000)
        self.assertEqual(size_of("Kokos yog'i 500 ml"), 500)
        self.assertEqual(size_of("Стевиа 1кг"), 1000)
        self.assertEqual(size_of("Chia 0,5 kg"), 500)
        self.assertIsNone(size_of("Grechka 200 гречка"))               # a word, not a unit
        self.assertIsNone(size_of("2-nav un"))

    def test_same_names_side_by_side_smallest_first(self):
        self.assertEqual(sorted(NAMES, key=sort_key), EXPECTED)
        self.assertEqual(base_name("Stevia 200gr"), base_name("Stevia 1000g"))


class BotPagesTest(unittest.TestCase):
    """database.get_products_by_category — the bot's catalog (5 a page)."""

    def test_pages_follow_the_rule(self):
        rows = [{"id": i, "name": n} for i, n in enumerate(reversed(NAMES))]

        class Conn:
            async def fetchval(self, sql, *a):
                return len(rows)

            async def fetch(self, sql, *a):
                assert "LIMIT" not in sql                              # the page is cut after sorting
                return rows

        class Pool:
            def acquire(self):
                class C:
                    async def __aenter__(s):
                        return Conn()

                    async def __aexit__(s, *e):
                        return False
                return C()

        with patch.object(database, "pool", Pool()):
            first, total = asyncio.run(database.get_products_by_category("x", page=0, per_page=5))
            second, _ = asyncio.run(database.get_products_by_category("x", page=1, per_page=5))
        self.assertEqual(total, len(NAMES))
        self.assertEqual([r["name"] for r in first + second], EXPECTED[:10])


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class SiteTest(unittest.TestCase):
    def test_site_reads_names_the_same_way(self):
        block = PAGE[PAGE.index("const PACK_SIZE_RE"):PAGE.index("function catalogGroupHead(")]
        products = [{"name": n, "category": "c"} for n in NAMES]
        code = ("let categories = [{key: 'c'}];\n" + block +
                f"\nprocess.stdout.write(JSON.stringify(orderCatalog({json.dumps(products, ensure_ascii=False)}, false)"
                ".map(p => p.name)));")
        out = subprocess.run(["node", "-e", code], capture_output=True, text=True, encoding="utf-8", check=True).stdout
        self.assertEqual(json.loads(out), EXPECTED)

    def test_mixed_lists_go_category_by_category(self):
        block = PAGE[PAGE.index("const PACK_SIZE_RE"):PAGE.index("function catalogGroupHead(")]
        products = [{"name": "Tuz 1kg", "category": "salt"}, {"name": "Stevia 1000g", "category": "sweet"},
                    {"name": "Bodom uni", "category": "flour"}, {"name": "Stevia 200gr", "category": "sweet"}]
        code = ("let categories = [{key: 'flour'}, {key: 'sweet'}, {key: 'salt'}];\n" + block +
                f"\nprocess.stdout.write(JSON.stringify(orderCatalog({json.dumps(products)}, true).map(p => p.name)));")
        out = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout
        self.assertEqual(json.loads(out), ["Bodom uni", "Stevia 200gr", "Stevia 1000g", "Tuz 1kg"])

    def test_headings_only_in_mixed_lists(self):
        load = PAGE[PAGE.index("async function loadProducts("):PAGE.index("function catalogDrawMore(")]
        self.assertIn("catalogGrouped = currentCat === 'all' || currentCat === 'discounts';", load)
        draw = PAGE[PAGE.index("function catalogDrawMore("):PAGE.index("function renderCatalogMore(")]
        self.assertIn("catalogGrouped && p.category !== catalogLastCat", draw)
        self.assertIn("grid-column: 1 / -1;", PAGE[PAGE.index("#product-grid .catalog-group-head {"):])


if __name__ == "__main__":
    unittest.main()
