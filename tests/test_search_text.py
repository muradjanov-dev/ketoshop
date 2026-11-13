"""Qidiruv lotin va kirillda bir xil (2026-11-11). Mini App'da 7 kunda 88
qidiruvdan 20 tasi bo'sh qaytgan: «кепак», «кепакли бугдой», «какао»,
«жадвар» hech narsa topmagan, holbuki «Kepakli bug'doy uni», «Kakao nibs
200gr», «Javdar uni» do'konda bor. Bot ham, sayt ham bitta qoidadan
(search_text.py) foydalanadi. Bazaga ulanmaydi."""
import asyncio
import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
import search_text
from search_text import find, fold, near

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "webapp" / "index.html").read_text(encoding="utf-8").replace("\r\n", "\n")

# Names as the shop writes them — Latin, some Cyrillic, some Russian.
NAMES = [
    "Alluloza 500gr", "Bodom uni 1000gr", "Bodom uni 200gr", "Eritritol 500gr", "Eritrtitol 1000gr",
    "Javdar uni", "Kakao nibs 200gr", "Kepakli bug'doy uni", "Kepakli un makaron vermishel 500g",
    "Kokos shakari 250gr", "Kokos uni 500gr", "Kokos yog'i Extra Virgin 450ml", "Makkajo'xori uni",
    "No'xat uni", "Qizil guruch (Devzira) (bo'yalmagan, yog'lanmagan) 500gr", "Qovoq urugʻi 200gr",
    "Stevia 500g", "Toza Steviya 50gr", "Zaytun yog'i(qovurish uchun) 1000ml", "Zig'ir uni 500gr",
    "Шоколад Победа 57%", "Табиий ҳамиртуруш— закваска", "Yeryong'oq pasta 200gr",
]
PRODUCTS = [{"id": i + 1, "name": n, "name_ru": None, "description": ""} for i, n in enumerate(NAMES)]


def names(found):
    return [p["name"] for p in found]


class FoldTest(unittest.TestCase):
    def test_both_scripts_meet(self):
        pairs = [
            ("кепакли буғдой", "Kepakli bug'doy"), ("кепакли бугдой", "Kepakli bugʻdoy"),
            ("какао", "Kakao"), ("жавдар", "Javdar"), ("зиғир", "zig‘ir"), ("нўхат", "No'xat"),
            ("ковок", "Qovoq"), ("қовоқ", "qovoq"), ("холва", "holva"), ("шоколад", "Shokolad"),
            ("чиа", "Chia"), ("ёнғоқ", "yong`oq"), ("ер ёнғоқ", "Yer yong'oq"), ("стевия", "Stevia"),
            ("şokolad", "shokolad"), ("ÇIA", "chia"), ("какао", "Cacao"),
        ]
        for a, b in pairs:
            self.assertEqual(fold(a), fold(b), (a, b))

    def test_shape(self):
        self.assertEqual(fold("Kepakli bugʻdoy UNI, 500gr!"), "kepakli bugdoy uni 500gr")
        self.assertEqual(fold(""), "")
        self.assertEqual(fold(None), "")

    def test_idempotent(self):
        for n in NAMES + ["кепакли бугдой", "Shokolad", "ҳолва", "Steviya"]:
            self.assertEqual(fold(fold(n)), fold(n), n)


class FindTest(unittest.TestCase):
    def first(self, query):
        found = find(query, PRODUCTS)
        self.assertTrue(found, query)
        return found[0]["name"]

    def test_the_empty_searches_of_the_week(self):
        self.assertEqual(self.first("кепак"), "Kepakli bug'doy uni")
        self.assertEqual(self.first("кепакли бугдой"), "Kepakli bug'doy uni")
        self.assertEqual(self.first("какао"), "Kakao nibs 200gr")
        self.assertEqual(self.first("жадвар"), "Javdar uni")          # two letters swapped
        self.assertIn("Bodom uni 1000gr", names(find("bodom", PRODUCTS)))

    def test_typos_only_when_nothing_matches_as_written(self):
        self.assertEqual(set(names(find("kakos", PRODUCTS))), {n for n in NAMES if n.startswith("Kokos")})
        self.assertEqual(self.first("eritrol"), "Eritritol 500gr")       # the old pg_trgm examples
        self.assertEqual(self.first("aluloza"), "Alluloza 500gr")
        self.assertEqual(names(find("шакар", PRODUCTS)), ["Kokos shakari 250gr"])   # not «makaron»
        self.assertNotIn("Makkajo'xori uni", names(find("makaron", PRODUCTS)))

    def test_a_misspelt_name_still_shows_next_to_the_right_one(self):
        self.assertEqual(names(find("эритритол", PRODUCTS)), ["Eritritol 500gr", "Eritrtitol 1000gr"])

    def test_both_spellings_of_stevia(self):
        want = {"Stevia 500g", "Toza Steviya 50gr"}
        self.assertEqual(set(names(find("stevia", PRODUCTS))), want)
        self.assertEqual(set(names(find("стевия", PRODUCTS))), want)

    def test_cyrillic_names_found_in_latin(self):
        self.assertEqual(names(find("shokolad", PRODUCTS)), ["Шоколад Победа 57%"])
        self.assertEqual(names(find("zakvaska", PRODUCTS)), ["Табиий ҳамиртуруш— закваска"])

    def test_closer_words_first(self):
        found = names(find("yog'", PRODUCTS))
        self.assertLess(found.index("Kokos yog'i Extra Virgin 450ml"),
                        found.index("Qizil guruch (Devzira) (bo'yalmagan, yog'lanmagan) 500gr"))

    def test_words_in_any_order_and_name_ru(self):
        self.assertEqual(self.first("uni bodom"), "Bodom uni 1000gr")
        ru = [{"id": 1, "name": "Bodom uni", "name_ru": "Миндальная мука"}]
        self.assertEqual(names(find("миндальная", ru)), ["Bodom uni"])

    def test_description_after_names(self):
        rows = [{"id": 1, "name": "Keto non", "description": "Bodom unidan pishirilgan"},
                {"id": 2, "name": "Bodom uni"}]
        self.assertEqual(names(find("bodom", rows)), ["Bodom uni", "Keto non"])

    def test_empty_query_keeps_everything(self):
        self.assertEqual(find("", PRODUCTS), PRODUCTS)

    def test_no_match(self):
        self.assertEqual(find("kefir", PRODUCTS), [])


class NearTest(unittest.TestCase):
    def test_extra_words_still_lead_somewhere(self):
        self.assertEqual(names(near("bodom uni bormi", PRODUCTS))[:2], ["Bodom uni 1000gr", "Bodom uni 200gr"])
        self.assertEqual(find("bodom uni bormi", PRODUCTS), [])

    def test_nothing_alike_offers_nothing(self):
        self.assertEqual(near("o'rik", PRODUCTS), [])
        self.assertEqual(near("kefir", PRODUCTS), [])

    def test_limit(self):
        self.assertEqual(len(near("uni", PRODUCTS, limit=2)), 2)


class FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return Ctx()


class DatabaseTest(unittest.TestCase):
    def setUp(self):
        self.conn = MagicMock()
        self.conn.fetch = AsyncMock(return_value=PRODUCTS)

    def test_pages_and_total(self):
        with patch.object(database, "pool", FakePool(self.conn)):
            page0, total = asyncio.run(database.search_products("кокос", page=0, per_page=2))
            page1, _ = asyncio.run(database.search_products("кокос", page=1, per_page=2))
        self.assertEqual(total, 3)
        self.assertEqual(len(page0), 2)
        self.assertEqual(len(page1), 1)
        sql = self.conn.fetch.await_args.args[0]
        self.assertIn("p.is_active = 1 AND (p.b2b_only IS NOT TRUE)", sql)

    def test_suggestions(self):
        with patch.object(database, "pool", FakePool(self.conn)):
            got = asyncio.run(database.search_suggestions("javdar uni bormi", limit=3))
        self.assertEqual(got[0]["name"], "Javdar uni")


class MiniAppApiTest(unittest.TestCase):
    def search(self, q, found, suggested):
        import webapp_server
        from aiohttp.test_utils import make_mocked_request

        async def go():
            req = make_mocked_request("GET", "/api/search?q=" + q)
            req["user_id"] = 77
            req["user_lang"] = "uz"
            with patch.object(webapp_server, "search_products", AsyncMock(return_value=(found, len(found)))), \
                 patch.object(database, "search_suggestions", AsyncMock(return_value=suggested)), \
                 patch.object(webapp_server, "_serialize_products",
                              AsyncMock(side_effect=lambda ps, *a, **k: [{"id": p["id"]} for p in ps])):
                resp = await webapp_server.api_search(req)
            return json.loads(resp.body)
        return asyncio.run(go())

    def test_matches_come_plain(self):
        self.assertEqual(self.search("kepak", [{"id": 8}], []), [{"id": 8}])

    def test_nothing_found_sends_marked_suggestions(self):
        self.assertEqual(self.search("bodom%20bormi", [], [{"id": 2}]), [{"id": 2, "near": True}])
        self.assertEqual(self.search("zzz", [], []), [])


class BotTest(unittest.TestCase):
    def run_search(self, query, found, suggested):
        from handlers import search as handler
        message = MagicMock()
        message.answer = AsyncMock()
        with patch.object(handler, "search_products", AsyncMock(return_value=(found, len(found)))), \
             patch.object(handler, "search_suggestions", AsyncMock(return_value=suggested)), \
             patch.object(handler, "get_cart_badge", AsyncMock(return_value=(0, 0))):
            asyncio.run(handler._show_search_results(message, query, "uz", user_id=77))
        args, kwargs = message.answer.await_args
        buttons = [b for row in kwargs["reply_markup"].inline_keyboard for b in row]
        return args[0], buttons

    def test_empty_result_offers_close_names(self):
        text, buttons = self.run_search("javdar <uni> bormi", [], [{"id": 6, "name": "Javdar uni", "name_ru": None}])
        self.assertIn("&lt;uni&gt;", text)                       # the query can't break the HTML
        self.assertIn("Balki", text)
        self.assertIn("product:6", [b.callback_data for b in buttons])
        self.assertIn("search", [b.callback_data for b in buttons])

    def test_empty_result_without_suggestions(self):
        text, buttons = self.run_search("kefir", [], [])
        self.assertNotIn("Balki", text)
        self.assertIn("shu chatga yozing", text)
        self.assertIn("main_menu", [b.callback_data for b in buttons])

    def test_page_buttons_fit_telegram(self):
        from handlers.search import page_callback
        long_query = "кепакли буғдой уни арзонроғи борми ўзи"
        data = page_callback(3, long_query)
        self.assertLessEqual(len(data.encode("utf-8")), 64)
        self.assertTrue(data.startswith("search_page:3:kepakli bugdoy uni"))
        self.assertEqual(page_callback(1, "кепак"), "search_page:1:кепак")


class MiniAppPageTest(unittest.TestCase):
    def test_a_late_answer_cannot_overwrite_a_newer_search(self):
        block = PAGE[PAGE.index("// Catalog search."):PAGE.index("// ===== PRODUCT DETAIL =====")]
        self.assertIn("const seq = ++catalogSeq;", block)
        self.assertGreaterEqual(block.count("if (seq !== catalogSeq) return;"), 2)
        self.assertIn("found.filter(p => p.near)", block)

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_empty_search_says_what_next(self):
        start = PAGE.index("function showCatalogEmpty(")
        end = PAGE.index("// Catalog search.")
        stub = r"""
const els = {};
function el(id) {
  return els[id] || (els[id] = { id, textContent: '', style: {}, children: [],
    set innerHTML(v) { this.children = []; },
    append(...xs) { this.children.push(...xs); }, appendChild(x) { this.children.push(x); },
    querySelector(sel) { return sel === '.emoji' ? el('emoji') : null; } });
}
const document = { getElementById: el, createElement: tag => ({ tag, style: {} }) };
const t = { searchMissNear: "O'xshash mahsulotlar", searchMissNote: 'NOTE', searchMissBtn: 'ASK' };
let asked = 0;
function contactAdmin() { asked++; }
function trk() {}
function createProductCard(p) { return { card: p.id }; }
"""
        run = r"""
showCatalogEmpty('«zzz» topilmadi', 'zzz', []);
const plain = { text: el('catalog-empty-text').textContent, emoji: el('emoji').style.display,
  extra: el('catalog-empty-extra').children.map(c => c.textContent), shown: el('catalog-empty').style.display };
el('catalog-empty-extra').children[1].onclick();
showCatalogEmpty('«bodom bormi» topilmadi', 'bodom bormi', [{ id: 2 }, { id: 3 }]);
const withNear = { text: el('catalog-empty-text').textContent, emoji: el('emoji').style.display,
  title: el('catalog-title').textContent, cards: el('product-grid').children.map(c => c.card) };
showCatalogEmpty('Mahsulotlar topilmadi');
const category = { text: el('catalog-empty-text').textContent, extra: el('catalog-empty-extra').children.length };
process.stdout.write(JSON.stringify({ plain, withNear, category, asked }));
"""
        out = subprocess.run(["node", "-e", stub + PAGE[start:end] + run], capture_output=True,
                             text=True, check=True, encoding="utf-8").stdout
        got = json.loads(out)
        self.assertEqual(got["plain"], {"text": "«zzz» topilmadi", "emoji": "",
                                        "extra": ["NOTE", "ASK"], "shown": "block"})
        self.assertEqual(got["asked"], 1)                             # «Bizga yozing» opens the shop's chat
        self.assertEqual(got["withNear"]["cards"], [2, 3])
        self.assertEqual(got["withNear"]["emoji"], "none")
        self.assertEqual(got["withNear"]["title"], "O'xshash mahsulotlar")
        self.assertEqual(got["category"], {"text": "Mahsulotlar topilmadi", "extra": 0})


if __name__ == "__main__":
    unittest.main()
