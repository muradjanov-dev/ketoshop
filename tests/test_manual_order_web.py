"""Qo'lda buyurtma from the admin site's dashboard (owner, 2026-11-09:
"qo'lda kiritiladigan buyurtmalarni ham dashboarddan ham kiritish imkonini
qilib ber").

The database and the Telegram feed are mocked: nothing here writes an order
or sends a card."""
import json
import os
import shutil
import subprocess
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("ADMIN_WEB_PASSWORD", "test-password")

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import admin_web
import database
import manual_order
import order_admin_feed
import regions
import uzpost

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = open(os.path.join(ROOT, "webapp", "admin.html"), encoding="utf-8").read().replace("\r\n", "\n")

PRODUCTS = {
    11: {"id": 11, "name": "Bodom uni 500gr", "price": 120000, "discount_percent": 0,
         "discount_until": None, "unit": "dona", "is_active": 1, "quantity": 7},
    # 10% off with no end date: the shelf price is 90 000.
    12: {"id": 12, "name": "Eritritol 1 kg", "price": 100000, "discount_percent": 10,
         "discount_until": None, "unit": "dona", "is_active": 1, "quantity": 3},
    # A discount that ended long ago no longer counts.
    13: {"id": 13, "name": "Kokos yog'i 500 ml", "price": 80000, "discount_percent": 20,
         "discount_until": datetime(2020, 1, 1), "unit": "dona", "is_active": 1, "quantity": 0},
}

GOOD = {"name": "Dilnoza", "phone": "90 123-45-67", "address": "Toshkent, Chilonzor 5",
        "items": [{"product_id": 11, "quantity": 2}, {"product_id": 12, "quantity": "1", "price": "81000"}],
        "payment": "cash", "delivery": "self", "status": "delivered"}


class ParseTest(unittest.TestCase):
    def test_lines_take_the_bots_shape(self):
        order = manual_order.parse(GOOD, PRODUCTS)
        self.assertEqual(order["phone"], "+998901234567")
        first, second = order["items"]
        self.assertEqual(first, {"product_id": 11, "name": "Bodom uni 500gr", "quantity": 2,
                                 "price": 120000.0, "unit": "dona"})
        # 81 000 for a 90 000 shelf price is a 10% per-order discount, written
        # like the bot writes it so the card shows the 🔥 badge.
        self.assertEqual(second["price"], 81000.0)
        self.assertEqual(second["original_price"], 90000.0)
        self.assertEqual(second["discount_percent"], 10)
        self.assertEqual(order["total"], 2 * 120000 + 81000)
        self.assertEqual(order["uzpost_fee"], 0)

    def test_no_price_means_todays_shelf_price(self):
        order = manual_order.parse(dict(GOOD, items=[{"product_id": 12, "quantity": 1},
                                                     {"product_id": 13, "quantity": "1,5"}]), PRODUCTS)
        self.assertEqual([i["price"] for i in order["items"]], [90000.0, 80000.0])
        self.assertEqual(order["items"][1]["quantity"], 1.5)
        self.assertNotIn("discount_percent", order["items"][0])

    def test_price_above_the_shelf_is_refused_like_in_the_bot(self):
        with self.assertRaisesRegex(manual_order.Invalid, "baland"):
            manual_order.parse(dict(GOOD, items=[{"product_id": 12, "quantity": 1, "price": 95000}]), PRODUCTS)

    def test_uzpost_adds_the_parcel_fee(self):
        body = dict(GOOD, delivery="uzpost", address="Nukus, Qoraqalpog'iston")
        order = manual_order.parse(body, PRODUCTS)
        far = uzpost.is_far(regions.region_from_text(body["address"]))
        self.assertEqual(order["uzpost_fee"], uzpost.buyer_fee(order["items"], far))
        self.assertGreater(order["uzpost_fee"], 0)
        self.assertEqual(order["total"], 2 * 120000 + 81000 + order["uzpost_fee"])

    def test_bad_input_is_explained(self):
        cases = [
            (dict(GOOD, name=" "), "ism"),
            (dict(GOOD, phone="12345"), "Telefon"),
            (dict(GOOD, address=""), "Manzil"),
            (dict(GOOD, items=[]), "mahsulot"),
            (dict(GOOD, items=[{"product_id": 99, "quantity": 1}]), "topilmadi"),
            (dict(GOOD, items=[{"product_id": 11, "quantity": 0}]), "soni"),
            (dict(GOOD, items=[{"product_id": 11, "quantity": "ikki"}]), "raqam"),
            (dict(GOOD, items=[{"product_id": 11, "quantity": 1, "price": -5}]), "narxi"),
            (dict(GOOD, payment="crypto"), "To'lov"),
            (dict(GOOD, delivery="yandex_market"), "Yetkazish"),
            (dict(GOOD, status=""), "Holat"),
        ]
        for body, word in cases:
            with self.subTest(word=word), self.assertRaisesRegex(manual_order.Invalid, f"(?i){word}"):
                manual_order.parse(body, PRODUCTS)

    def test_running_total_needs_no_customer_yet(self):
        body = {"items": [{"product_id": 11, "quantity": 1}], "delivery": "uzpost"}
        order = manual_order.parse(body, PRODUCTS, need_customer=False)
        self.assertEqual(order["subtotal"], 120000)
        self.assertGreater(order["uzpost_fee"], 0)


class ApiTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.saved = AsyncMock(return_value=901)
        self.feed = MagicMock()
        for target, attr, value in [
            (database, "get_product", AsyncMock(side_effect=lambda pid: PRODUCTS.get(pid))),
            (database, "add_manual_order", self.saved),
            (order_admin_feed, "manual_created", self.feed),
            (admin_web, "ADMIN_WEB_PASSWORD", "test-password"),
        ]:
            p = patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)
        app = web.Application()
        admin_web.setup_admin_routes(app)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)
        self.client.session.cookie_jar.update_cookies({admin_web.SESSION_COOKIE: admin_web._make_session()})

    async def post(self, body):
        response = await self.client.post("/admin/api/manual-order", json=body)
        return response.status, await response.json()

    async def test_save_writes_a_manual_order_and_tells_the_admins(self):
        status, data = await self.post(GOOD)
        self.assertEqual(status, 200, data)
        self.assertEqual(data["id"], 901)
        self.assertEqual(data["total"], 321000)
        kwargs = self.saved.await_args.kwargs
        self.assertEqual(kwargs["admin_user_id"], admin_web.WEB_SELLER_ID)
        self.assertEqual(kwargs["customer_name"], "Dilnoza")
        self.assertEqual(kwargs["phone"], "+998901234567")
        self.assertEqual(kwargs["address"], "Toshkent, Chilonzor 5")
        self.assertEqual(kwargs["total"], 321000)
        self.assertEqual((kwargs["payment_method"], kwargs["delivery_method"], kwargs["status"]),
                         ("cash", "self", "delivered"))
        self.assertEqual([i["product_id"] for i in kwargs["items_data"]], [11, 12])
        # The same «Qo'lda buyurtma» card the bot sends, signed by the site.
        self.feed.assert_called_once_with(None, 901, admin_web.MANUAL_ORDER_BY)

    async def test_preview_prices_without_saving(self):
        status, data = await self.post({"preview": True, "delivery": "uzpost", "address": "Toshkent",
                                        "items": [{"product_id": 11, "quantity": 2}]})
        self.assertEqual(status, 200, data)
        self.assertTrue(data["preview"])
        self.assertGreater(data["uzpost_fee"], 0)
        self.assertEqual(data["total"], 240000 + data["uzpost_fee"])
        self.saved.assert_not_awaited()
        self.feed.assert_not_called()

    async def test_full_preview_checks_the_customer_too(self):
        status, data = await self.post(dict(GOOD, preview=True, full=True, phone="12"))
        self.assertEqual(status, 400)
        self.assertIn("Telefon", data["error"])
        status, data = await self.post(dict(GOOD, preview=True, full=True))
        self.assertEqual(status, 200, data)
        self.assertEqual((data["name"], data["phone"]), ("Dilnoza", "+998901234567"))
        self.saved.assert_not_awaited()

    async def test_refused_orders_write_nothing(self):
        for body in (dict(GOOD, phone="12345"), dict(GOOD, status=None),
                     dict(GOOD, items=[{"product_id": 12, "quantity": 1, "price": 99000}]),
                     dict(GOOD, items=[{"product_id": 404, "quantity": 1}]), [1, 2]):
            with self.subTest(body=body):
                status, data = await self.post(body)
                self.assertEqual(status, 400)
                self.assertTrue(data["error"])
        self.saved.assert_not_awaited()
        self.feed.assert_not_called()

    async def test_needs_the_admin_password(self):
        self.client.session.cookie_jar.clear()
        status, _ = await self.post(GOOD)
        self.assertEqual(status, 401)
        self.saved.assert_not_awaited()


class PageTest(unittest.TestCase):
    def test_button_on_the_dashboard_opens_the_form(self):
        dash = PAGE[PAGE.index('id="view-dashboard"'):PAGE.index('id="view-faollik"')]
        self.assertIn('id="moOpenBtn"', dash)
        self.assertIn('id="moModal"', PAGE)
        self.assertIn("$('#moOpenBtn').addEventListener('click',openManualOrder)", PAGE)

    def test_form_offers_the_bots_choices(self):
        form = PAGE[PAGE.index('id="moModal"'):PAGE.index("</form>", PAGE.index('id="moModal"'))]
        for code in (*manual_order.PAYMENTS, *manual_order.DELIVERIES, *manual_order.STATUSES):
            self.assertIn(f'value="{code}"', form)


SLICE = PAGE[PAGE.index("const MO={lines:[]"):PAGE.index("/* ===== modals ===== */")]

SANDBOX = r"""
const vm=require('node:vm');
const nodes={};
function el(id,extra={}){
  const n={id,value:'',innerHTML:'',textContent:'',dataset:{},handlers:{},cls:new Set(),
    classList:{add(c){n.cls.add(c);},remove(c){n.cls.delete(c);},contains(c){return n.cls.has(c);},toggle(c,on){on?n.cls.add(c):n.cls.delete(c);}},
    addEventListener(t,f){n.handlers[t]=f;},focus(){},querySelector(){return null;},querySelectorAll(){return [];},...extra};
  nodes['#'+id]=n;return n;
}
['moOpenBtn','moClear','moSearch','moLines','moName','moPhone','moAddress','moCalc','moSave','moForm','moModal'].forEach(id=>el(id));
// The result list, read back out of the HTML the page wrote into it.
el('moResults',{
  querySelectorAll(){return [...this.innerHTML.matchAll(/data-pid="(\d+)"( class="on")?/g)].map(m=>({dataset:{pid:m[1]},
    classList:{contains:()=>!!m[2],toggle(){}},scrollIntoView(){}}));},
  querySelector(s){const m=s==='button.on'&&/data-pid="(\d+)" class="on"/.exec(this.innerHTML);return m?{dataset:{pid:m[1]}}:null;},
});
for(const id of ['moPayment','moDelivery','moStatus'])el(id,{selectedIndex:0,options:[{text:'—'}]});
const requests=[];
let confirmAnswer=true, toasts=[];
const ctx=vm.createContext({console,Number,String,Math,Date,JSON,Promise,
  setTimeout:(f)=>{f();return 0;},clearTimeout(){},
  $:s=>nodes[s],
  fmt:n=>Math.round(+n).toLocaleString('en-US').replace(/,/g,' ')+" so'm",
  esc:s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),
  toast:m=>toasts.push(m),closeModals(){nodes['#moModal'].cls.delete('open');},loadDashboard(){},
  PRODUCTS:[{id:11,name:'Bodom uni 500gr',price:120000,discount_percent:0,is_active:1,quantity:7},
            {id:12,name:'Eritritol 1 kg',price:100000,discount_percent:10,discount_until:null,is_active:1,quantity:3},
            {id:14,name:'Eritritol optom',price:50000,is_active:1,b2b_only:true,quantity:9},
            {id:15,name:'Eritritol eski',price:50000,is_active:0,quantity:9}],
  api:async(path,opts)=>{const body=JSON.parse(opts.body);requests.push(body);
    if(body.preview)return {ok:true,preview:true,name:body.name,phone:'+998901234567',address:body.address,
      items:[{name:'Eritritol 1 kg',quantity:2,price:81000,discount_percent:10}],uzpost_fee:23000,uzpost_kg:2,total:185000};
    return {ok:true,id:901,total:185000};},
});
ctx.window=ctx;ctx.window.confirm=()=>confirmAnswer;
vm.runInContext(%s,ctx);
(async()=>{
  const out={};
  nodes['#moSearch'].value='eritritol';nodes['#moSearch'].handlers.input();
  out.results=nodes['#moResults'].innerHTML;
  // Enter takes the first hit; a second Enter on the same product adds one more.
  for(let i=0;i<2;i++){nodes['#moSearch'].value='eritritol';nodes['#moSearch'].handlers.input();
    nodes['#moSearch'].handlers.keydown({key:'Enter',preventDefault(){}});}
  out.lines=nodes['#moLines'].innerHTML;
  // The admin types a price: 81 000 for the 90 000 shelf price.
  const row={dataset:{i:'0'},querySelector:s=>s==='.sum'?row.sum:row.note,sum:{},note:{}};
  nodes['#moLines'].handlers.input({target:{value:'81000',dataset:{f:'price'},closest:()=>row}});
  out.rowSum=row.sum.textContent;out.rowNote=row.note.innerHTML;
  nodes['#moDelivery'].value='uzpost';nodes['#moDelivery'].handlers.change();
  await new Promise(r=>setImmediate(r));          // the server's preview comes back
  out.calc=nodes['#moCalc'].innerHTML;
  Object.assign(nodes['#moName'],{value:' Dilnoza '});nodes['#moPhone'].value='90 123 45 67';
  nodes['#moAddress'].value='Toshkent';nodes['#moPayment'].value='cash';nodes['#moStatus'].value='pending';
  nodes['#moModal'].cls.add('open');
  await nodes['#moForm'].handlers.submit({preventDefault(){}});
  out.requests=requests;out.toasts=toasts;out.open=nodes['#moModal'].cls.has('open');
  out.after=nodes['#moLines'].innerHTML;out.nameAfter=nodes['#moName'].value;
  process.stdout.write(JSON.stringify(out));
})();
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class FormTest(unittest.TestCase):
    """The page's own form code, with only the DOM and the network replaced."""

    def test_pick_price_and_save(self):
        code = SANDBOX % json.dumps(SLICE)
        # Through stdin: the script is longer than a Windows command line.
        run = subprocess.run(["node", "-"], input=code, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(run.returncode, 0, run.stderr)
        out = json.loads(run.stdout)
        # Only products a buyer could get: no b2b-only, no hidden ones.
        self.assertIn("Eritritol 1 kg", out["results"])
        self.assertNotIn("optom", out["results"])
        self.assertNotIn("eski", out["results"])
        self.assertIn("90 000 so'm", out["results"])                   # shelf price, 10% applied
        self.assertIn('value="2"', out["lines"])                      # same product twice → 2
        self.assertEqual(out["rowSum"], "162 000 so'm")
        self.assertIn("−10% chegirma", out["rowNote"])
        self.assertIn("UzPost (2 kg)", out["calc"])
        self.assertIn("185 000 so'm", out["calc"])                    # 162 000 + 23 000

        previews = [r for r in out["requests"] if r.get("preview")]
        full = [r for r in previews if r.get("full")]
        saves = [r for r in out["requests"] if not r.get("preview")]
        self.assertEqual(len(full), 1)
        self.assertEqual(len(saves), 1)
        save = saves[0]
        self.assertEqual(save["name"], "Dilnoza")
        self.assertEqual((save["payment"], save["delivery"], save["status"]), ("cash", "uzpost", "pending"))
        self.assertEqual(save["items"], [{"product_id": 12, "quantity": "2", "price": "81000"}])
        self.assertEqual(out["toasts"], ["✅ Buyurtma #901 saqlandi — 185 000 so'm"])
        self.assertFalse(out["open"])
        self.assertIn("Hali mahsulot yo", out["after"])                # the draft is cleared
        self.assertEqual(out["nameAfter"], "")


if __name__ == "__main__":
    unittest.main()
