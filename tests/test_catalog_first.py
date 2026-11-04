"""Sayt katalogdan ochiladi: rasmli kategoriya plitkalari, darhol mahsulotlar,
2 ustun / 3 ustun / ro'yxat (egasi, 2026-11-04). Bazaga ulanmaydi."""
import asyncio
import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from aiohttp.test_utils import make_mocked_request

import database
import webapp_server

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "webapp" / "index.html").read_text(encoding="utf-8")


class OpensOnTheCatalogTest(unittest.TestCase):
    def test_catalog_is_the_first_page_and_tab(self):
        self.assertIn('<div class="page active" id="page-catalog">', HTML)
        self.assertIn('<div class="page" id="page-home">', HTML)
        self.assertIn("let activePage = 'catalog';", HTML)
        tabs = re.findall(r'class="tab-item[^"]*" data-page="(\w+)"', HTML)
        self.assertEqual(tabs[0], "catalog")
        self.assertIn('class="tab-item active" data-page="catalog"', HTML)

    def test_back_goes_to_the_catalog_and_home_is_drawn_when_opened(self):
        self.assertIn("if (activePage && activePage !== 'catalog') {\n    switchPage('catalog');", HTML.replace("\r\n", "\n"))
        self.assertIn("if (page === 'home' && !homeRendered) renderHomePage();", HTML)
        init = HTML[HTML.index("(async function init()"):]
        init = init[:init.index("await loadProducts();")]
        self.assertNotIn("renderHomePage();", init)               # not drawn behind the catalog

    def test_tiles_and_switch_sit_above_the_grid(self):
        page = HTML[HTML.index('id="page-catalog"'):HTML.index('id="page-cart"')]
        order = [page.index(x) for x in ('id="cat-tiles"', 'id="categories"', 'id="view-switch"', 'id="product-grid"')]
        self.assertEqual(order, sorted(order))


class TilesEndpointTest(unittest.TestCase):
    def setUp(self):
        webapp_server._TILES.update(at=0.0, data=None)

    def call(self):
        raw = {"categories": {"sweeteners": {"count": 8, "photo": "AgACfile"}, "oils": {"count": 3, "photo": "/img/7"},
                              "salt": {"count": 2, "photo": None}},
               "discounts": {"count": 4, "photo": "https://cdn.example/x.jpg"}}
        sets = [{"id": 1, "image_url": None}, {"id": 2, "image_url": "/img/9"}]
        with patch.object(database, "get_category_tiles", AsyncMock(return_value=raw)) as tiles, \
             patch.object(database, "get_active_sets_for_catalog", AsyncMock(return_value=sets)):
            body = asyncio.run(webapp_server.api_category_tiles(make_mocked_request("GET", "/api/category-tiles"))).body
            asyncio.run(webapp_server.api_category_tiles(make_mocked_request("GET", "/api/category-tiles")))
        return json.loads(body), tiles

    def test_counts_and_photo_addresses(self):
        d, tiles = self.call()
        self.assertEqual(d["total"], 13)                          # products only, sets separate
        self.assertEqual(d["categories"]["sweeteners"], {"count": 8, "photo_url": "/api/photo/AgACfile"})
        self.assertEqual(d["categories"]["oils"]["photo_url"], "/img/7")
        self.assertIsNone(d["categories"]["salt"]["photo_url"])
        self.assertEqual(d["categories"]["sets"], {"count": 2, "photo_url": "/img/9"})
        self.assertEqual(d["discounts"], {"count": 4, "photo_url": "https://cdn.example/x.jpg"})
        tiles.assert_awaited_once()                               # the second call came from the cache

    def test_route(self):
        app = webapp_server.create_webapp(object())  # type: ignore[arg-type]
        methods = {r.method for r in app.router.routes() if r.resource.canonical == "/api/category-tiles"}
        self.assertEqual(methods - {"HEAD"}, {"GET"})


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TileTextTest(unittest.TestCase):
    def run_js(self, expr, lang):
        block = HTML[HTML.index("function tileCountText("):HTML.index("async function loadCatalogTiles(")]
        gx = "function gx(uz, ru) { return lang === 'ru' ? ru : uz; }"
        code = f"const lang = {json.dumps(lang)};\n{gx}\n{block}\nprocess.stdout.write(JSON.stringify({expr}));"
        return json.loads(subprocess.run(["node", "-e", code], capture_output=True, text=True, encoding="utf-8",
                                         check=True).stdout)

    def test_counts_read_naturally(self):
        self.assertEqual(self.run_js("[1, 5].map(tileCountText)", "uz"), ["1 ta mahsulot", "5 ta mahsulot"])
        self.assertEqual(self.run_js("[1, 2, 5, 11, 21, 22, 112].map(tileCountText)", "ru"),
                         ["1 товар", "2 товара", "5 товаров", "11 товаров", "21 товар", "22 товара", "112 товаров"])

    def test_photo_address_cannot_break_out_of_css(self):
        self.assertEqual(self.run_js("cssUrl(\"/img/1') ; x(\")", "uz"), "/img/1%27%29%20;%20x%28")


if __name__ == "__main__":
    unittest.main()
