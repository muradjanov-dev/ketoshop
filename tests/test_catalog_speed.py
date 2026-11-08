"""Katalog tezligi va to'liqligi (egasi, 2026-11-08: "kategoriyani bosgach ham
sekin yuklanyapti ... pastga tushsa bazida hamma mahsulot chiqmayapti odamlar
shu ekan faqat deb o'ylab qolishyapti").

Checked in a real browser while writing this (Edge, 390 px, 112 products,
600 ms fake latency): one /api/products request for the whole session, a
category tap draws in 40–70 ms, scrolling reaches all 112, the line under the
grid reads «Yana 82 ta mahsulot» → «Hammasi shu — 112 ta mahsulot», and a
failed load offers «Qayta urinish». These tests pin the list logic and the
wiring."""
import json
import os
import re
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = open(os.path.join(ROOT, "webapp", "index.html"), encoding="utf-8").read().replace("\r\n", "\n")


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ListTest(unittest.TestCase):
    def run_js(self, body):
        block = PAGE[PAGE.index("const CATALOG_FETCH = 200;"):PAGE.index("async function loadProducts(")]
        stub = """
const calls = [];
let failNext = false;
const DATA = {
  all: [{id: 1, category: 'salt'}, {id: 2, category: 'oils'}, {id: 3, category: 'salt'}],
  sets: [{id: 9, is_set: true}],
  discounts: [{id: 2, category: 'oils'}],
};
async function api(url) {
  calls.push(url);
  if (failNext) { failNext = false; throw new Error('network'); }
  const m = /category=([a-z_]+)/.exec(url);
  const list = m ? (DATA[m[1]] || DATA.all.filter(p => p.category === m[1])) : DATA.all;
  return { products: list, total: list.length, page: 0, pages: 1 };
}
"""
        code = stub + block + "\n(async () => {\n" + body + "\n})().catch(e => { console.error(e); process.exit(1); });"
        out = subprocess.run(["node", "-e", code], capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def test_categories_come_from_one_request(self):
        out = self.run_js("""
const salt = await catalogListFor('salt');
const oils = await catalogListFor('oils');
const all = await catalogListFor('all');
process.stdout.write(JSON.stringify({salt: salt.products.map(p => p.id), total: salt.total,
  oils: oils.products.map(p => p.id), all: all.total, calls}));""")
        self.assertEqual(out["salt"], [1, 3])
        self.assertEqual(out["total"], 2)                       # the heading counts the tab, not the shop
        self.assertEqual(out["oils"], [2])
        self.assertEqual(out["all"], 3)
        self.assertEqual(out["calls"], ["/api/products?page=0&per_page=200"])

    def test_sets_and_discounts_are_their_own_lists(self):
        out = self.run_js("""
await catalogListFor('sets'); await catalogListFor('discounts'); await catalogListFor('sets');
process.stdout.write(JSON.stringify(calls));""")
        self.assertEqual(out, ["/api/products?category=sets&page=0&per_page=200",
                               "/api/products?category=discounts&page=0&per_page=200"])

    def test_a_failure_is_never_kept(self):
        out = self.run_js("""
failNext = true;
let failed = false;
try { await catalogListFor('salt'); } catch (_) { failed = true; }
const again = await catalogListFor('salt');
process.stdout.write(JSON.stringify({failed, ids: again.products.map(p => p.id), calls: calls.length}));""")
        self.assertTrue(out["failed"])
        self.assertEqual(out["ids"], [1, 3])
        self.assertEqual(out["calls"], 2)

    def test_kept_for_a_while_then_asked_again(self):
        out = self.run_js("""
await catalogListFor('all');
catalogCache.all.at -= CATALOG_TTL + 1;
await catalogListFor('all');
clearCatalogCache();
await catalogListFor('all');
process.stdout.write(JSON.stringify(calls.length));""")
        self.assertEqual(out, 3)

    def test_a_shop_bigger_than_one_request_asks_per_category(self):
        out = self.run_js("""
const real = api;
api = async url => { const r = await real(url); if (!/category=/.test(url)) r.total = 999; return r; };
const salt = await catalogListFor('salt');
process.stdout.write(JSON.stringify({ids: salt.products.map(p => p.id), calls}));""")
        self.assertEqual(out["ids"], [1, 3])
        self.assertEqual(out["calls"][-1], "/api/products?category=salt&page=0&per_page=200")


class WiringTest(unittest.TestCase):
    def test_old_paging_is_gone(self):
        for name in ("currentPage", "totalPages", "isLoadingMore", "scroll-loader", "CATALOG_PAGE_SIZE"):
            self.assertNotIn(name, PAGE, name)

    def test_cards_drawn_from_memory_with_an_honest_end(self):
        draw = PAGE[PAGE.index("function catalogDrawMore("):PAGE.index("function renderCatalogMore(")]
        self.assertNotIn("api(", draw)                           # no request per 30 cards
        more = PAGE[PAGE.index("function renderCatalogMore("):PAGE.index("function catalogLoadMore(")]
        for key in ("t.catalogMore", "t.catalogEnd", "t.catalogRetry"):
            self.assertIn(key, more)
        for key in ("catalogMore", "catalogEnd", "catalogRetry"):
            self.assertEqual(len(re.findall(r"\n    " + key + r": '", PAGE)), 2, key)   # uz + ru
        self.assertIn("scrollHeight - 1200", PAGE)

    def test_list_travels_with_the_categories(self):
        init = PAGE[PAGE.index("(async function init()"):]
        self.assertLess(init.index("fetchCatalogList('all')"), init.index("categories = await api('/api/categories')"))

    def test_new_language_new_names(self):
        block = PAGE[PAGE.index("// Reload dynamic content."):]
        self.assertLess(block.index("clearCatalogCache();"), block.index("loadProducts();"))

    def test_search_leaves_no_footer(self):
        search = PAGE[PAGE.index("// Search results are one list"):PAGE.index("// ===== PRODUCT DETAIL =====")]
        self.assertIn("catalogList = [];", search)
        self.assertIn("renderCatalogMore();", search)


if __name__ == "__main__":
    unittest.main()
