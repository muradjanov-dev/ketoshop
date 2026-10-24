"""📮 UzPost «Bir Qadam» — price by weight, nearest office, checkout wiring
(owner, 2026-10-24). No network and no database: UzPost's API is faked."""
import asyncio
import json
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import uzpost


def run(coro):
    return asyncio.run(coro)


OFFICES = {"result": [
    {"index": "141600", "one_step": "Bor", "lat": "39.402371", "lng": "67.243000"},
    {"index": "141601", "one_step": "Yo'q", "lat": "39.40", "lng": "67.24"},
    {"index": "181300", "one_step": "Bor", "lat": "39.0873", "lng": "66.8400,1810"},
    {"index": "230100", "one_step": "Bor", "lat": "42.4610", "lng": "59.6170"},
    {"index": "999999", "one_step": "Bor", "lat": "0", "lng": "0"},
    {"index": "", "one_step": "Bor", "lat": "41.3", "lng": "69.2"},
]}
DETAIL_URGUT = {"result": {"postal_office": {
    "index": "141600", "name_uz": "UzPost - Urgut Pochtamt", "region": "Самарқанд", "city": "Ургут",
    "district": "Ургут", "street": "А.Навоий шох кучаси", "house": "17.0",
    "working_days": "Пн-Сб", "working_hours": "09:00-17:00", "one_step": "Bor"}}}


class WeightTest(unittest.TestCase):
    def test_pack_size_from_the_name(self):
        cases = {
            "Bodom uni 1000gr": 1.0, "Stevia 1000g": 1.0, "Lasos baliq tushonkasi 700ml": 0.7,
            "Zaytun yog‘i Ispaniya (5 l  qovurish uchun)": 5.0, "zig'ir uru'gi 1 kg": 1.0,
            "Qora fermentlangan Solod 1kg": 1.0, "Zig'ir uni 400g «Кудесница»": 0.4,
            "Toza Steviya 20gr": 0.02, "Шоколад 100 гр": 0.1, "Kepakli bug'doy uni": None,
            "«Победа» 100% Charged": None, "Omega 3 kapsula": None,
        }
        for name, kg in cases.items():
            self.assertEqual(uzpost.pack_kg(name), kg, name)

    def test_line_weight(self):
        self.assertEqual(uzpost.item_kg({"name": "Bodom uni 1000gr", "quantity": 2, "unit": "kg"}), 2.0)
        self.assertEqual(uzpost.item_kg({"name": "Kepakli bug'doy uni", "quantity": 3, "unit": "kg"}), 3)
        self.assertEqual(uzpost.item_kg({"name": "Kokos yog'i", "quantity": 2, "unit": "piece"}),
                         2 * uzpost.DEFAULT_ITEM_KG)
        self.assertEqual(uzpost.item_kg({"name": "Keto set", "quantity": 1, "is_set": True}), uzpost.SET_KG)
        # An aksiya bonus's quantity is its DISPLAY amount ("100" for 100 gr):
        # the parcel carries stock_quantity packs of it.
        self.assertAlmostEqual(uzpost.item_kg({"name": "Eritritol 100gr", "quantity": 100,
                                               "stock_quantity": 1, "is_bonus": True}), 0.1)
        self.assertEqual(uzpost.item_kg({"name": "x", "quantity": "junk"}), 0.0)

    def test_parcel_and_price(self):
        items = [{"name": "Bodom uni 1000gr", "quantity": 2, "unit": "kg"},
                 {"name": "Stevia 200gr", "quantity": 1},
                 {"name": "Eritritol 100gr", "quantity": 1, "is_gift": True}]
        kg = uzpost.parcel_kg(items)
        self.assertAlmostEqual(kg, 2.3 + uzpost.PACKAGING_KG)
        self.assertEqual(uzpost.tariff(kg), 15_000 + 2 * 3_000)          # 2.4 kg → 3 kg
        self.assertEqual(uzpost.tariff(kg, far=True), 15_000 + 2 * 7_000)
        self.assertEqual(uzpost.buyer_fee(items), 21_000 + 3_000)
        self.assertEqual(uzpost.tariff(0.05), 15_000)                    # never below 1 kg
        self.assertEqual(uzpost.tariff(3.0), 21_000)                     # exactly 3 kg stays 3
        self.assertEqual(uzpost.fmt_kg(2.4), "2,4")
        self.assertEqual(uzpost.fmt_kg(3.0), "3")

    def test_far_regions(self):
        for r in ("karakalpakstan", "khorezm", "surkhandarya", "Қорақалпоғистон Республикаси",
                  "Хоразм", "Сурхондарё", "230100 — Nukus Pochtamt, Қорақалпоғистон"):
            self.assertTrue(uzpost.is_far(r), r)
        for r in (None, "", "samarkand", "Самарқанд", "tashkent_region"):
            self.assertFalse(uzpost.is_far(r), r)


class OfficeTest(unittest.TestCase):
    def setUp(self):
        uzpost._offices.update(at=0.0, list=[])
        uzpost._details.clear()

    def test_parse_keeps_bir_qadam_with_sane_coordinates(self):
        offices = uzpost.parse_offices(OFFICES)
        self.assertEqual([o["index"] for o in offices], ["141600", "181300", "230100"])
        self.assertEqual(offices[1]["lng"], 66.84)

    def test_nearest_office_and_its_lines(self):
        async def fake(url):
            return OFFICES if url == uzpost.OFFICES_URL else DETAIL_URGUT
        with patch.object(uzpost, "_get_json", side_effect=fake) as get:
            office = run(uzpost.nearest_office(39.40, 67.24))
            run(uzpost.nearest_office(39.40, 67.24))
        self.assertEqual(get.call_count, 2)                  # list + detail, both cached after
        self.assertEqual(office["index"], "141600")
        self.assertEqual(office["name"], "Urgut Pochtamt")
        self.assertEqual(office["address"], "Самарқанд, Ургут, А.Навоий шох кучаси 17")
        self.assertEqual(office["hours"], "Пн-Сб 09:00-17:00")
        self.assertLess(office["km"], 1)
        self.assertEqual(uzpost.office_line(office),
                         "141600 — Urgut Pochtamt, Самарқанд, Ургут, А.Навоий шох кучаси 17")
        self.assertIn("pt=67.243000,39.402371", uzpost.map_url(office))
        latin = uzpost.localize(office, "uz")
        self.assertEqual(latin["address"], "Samarqand, Urgut, A.Navoiy shox kuchasi 17")
        self.assertEqual(latin["hours"], "Du-Sha 09:00-17:00")
        self.assertEqual(uzpost.localize(office, "uz_cyr")["hours"], "Ду-Ша 09:00-17:00")
        self.assertIs(uzpost.localize(office, "ru"), office)

    def test_uzpost_down_means_no_office_not_an_error(self):
        with patch.object(uzpost, "_get_json", AsyncMock(return_value=None)):
            self.assertIsNone(run(uzpost.nearest_office(39.4, 67.2)))
        self.assertIsNone(run(uzpost.nearest_office(None, None)))
        self.assertEqual(uzpost.office_line(None), "")

    def test_stale_list_beats_nothing(self):
        uzpost._offices.update(at=1.0, list=uzpost.parse_offices(OFFICES))
        async def fake(url):
            return None if url == uzpost.OFFICES_URL else {}
        with patch.object(uzpost, "_get_json", side_effect=fake):
            office = run(uzpost.nearest_office(42.46, 59.61))
        self.assertEqual(office["index"], "230100")
        self.assertEqual(office["name"], "UzPost 230100")


class CheckoutWiringTest(unittest.TestCase):
    def test_fee_rules(self):
        from handlers.cart import delivery_fee_for, charged_delivery_fee, SELF_DELIVERY_FEE
        items = [{"name": "Bodom uni 1000gr", "quantity": 1, "price": 160_000}]
        self.assertEqual(delivery_fee_for("uzpost", 2_000_000, items), 21_000)   # no free threshold
        self.assertEqual(delivery_fee_for("uzpost", 0, items, far=True), 25_000)
        self.assertEqual(delivery_fee_for("bts", 100_000, items), 0)
        self.assertEqual(delivery_fee_for("self", 100_000), SELF_DELIVERY_FEE)
        self.assertEqual(charged_delivery_fee(181_000, 0, items), 21_000)
        self.assertEqual(charged_delivery_fee(171_000, 10_000, items), 21_000)
        self.assertEqual(charged_delivery_fee(150_000, 0, items), 0)

    def test_keyboard(self):
        from keyboards import delivery_method_keyboard
        out = delivery_method_keyboard("uz", in_tashkent=False, uzpost_fee=21_000).inline_keyboard
        self.assertEqual([r[0].callback_data for r in out[:3]],
                         ["delivery:uzpost", "delivery:bts", "delivery:emu"])
        self.assertEqual(out[0][0].text, "📮 UzPost — 1 kunda, ~21 000 so'm")
        plain = delivery_method_keyboard("ru", in_tashkent=False).inline_keyboard
        self.assertEqual(plain[0][0].text, "📮 UzPost (за 1 день)")
        town = delivery_method_keyboard("uz", in_tashkent=True).inline_keyboard
        self.assertNotIn("delivery:uzpost", [r[0].callback_data for r in town])

    def test_texts_in_each_language(self):
        from handlers.cart import uzpost_office_text, order_thanks_text
        office = {"index": "141600", "name": "Urgut Pochtamt", "address": "Самарқанд, Ургут, А.Навоий 17",
                  "hours": "Пн-Сб 09:00-17:00", "region": "Самарқанд", "lat": 39.4, "lng": 67.2, "km": 0.2}
        uz = uzpost_office_text(office, 2.4, "uz")
        self.assertIn("<b>141600</b> — Urgut Pochtamt", uz)
        self.assertIn("Samarqand, Urgut", uz)
        self.assertIn("Du-Sha", uz)
        self.assertIn("~2,4 kg", uz)
        self.assertIn("Ду-Ша", uzpost_office_text(office, 2.4, "uz_cyr"))
        self.assertIn("почтовое отделение", uzpost_office_text(None, 1, "ru"))
        self.assertIn("Посылка придёт", uzpost_office_text(office, 1, "ru"))
        self.assertIn("admin aniqlab", uzpost_office_text(None, 1, "uz"))
        self.assertIn("UzPost «Bir Qadam»", order_thanks_text(7, "uzpost", "uz"))

    def test_choosing_uzpost_stores_the_office(self):
        from handlers import cart
        office = {"index": "230100", "name": "Nukus Pochtamt", "address": "Нукус", "hours": "",
                  "region": "Қорақалпоғистон Республикаси", "lat": 42.46, "lng": 59.61, "km": 2.0}
        state = MagicMock()
        state.get_data = AsyncMock(return_value={"lang": "uz", "latitude": 42.46, "longitude": 59.61})
        state.update_data = AsyncMock()
        state.set_state = AsyncMock()
        callback = MagicMock()
        callback.data = "delivery:uzpost"
        callback.from_user.id = 5
        callback.answer = AsyncMock()
        callback.message.edit_text = AsyncMock()
        with patch.object(cart.uzpost, "nearest_office", AsyncMock(return_value=office)), \
                patch.object(cart, "get_cart", AsyncMock(return_value=[
                    {"name": "Bodom uni 1000gr", "cart_quantity": 1, "unit": "kg"}])):
            run(cart.process_delivery_method(callback, state))
        stored = {}
        for c in state.update_data.await_args_list:
            stored.update(c.kwargs)
        self.assertEqual(stored["delivery_method"], "uzpost")
        self.assertTrue(stored["uzpost_far"])
        self.assertTrue(stored["post_office_line"].startswith("230100 — Nukus Pochtamt"))
        self.assertIn("230100", callback.message.edit_text.await_args.args[0])
        callback.answer.assert_awaited_once()

    def test_choosing_another_method_forgets_the_office(self):
        from handlers import cart
        state = MagicMock()
        state.get_data = AsyncMock(return_value={"lang": "uz", "post_office_line": "x"})
        state.update_data = AsyncMock()
        state.set_state = AsyncMock()
        callback = MagicMock()
        callback.data = "delivery:bts"
        callback.answer = AsyncMock()
        callback.message.edit_text = AsyncMock()
        run(cart.process_delivery_method(callback, state))
        stored = {}
        for c in state.update_data.await_args_list:
            stored.update(c.kwargs)
        self.assertIsNone(stored["post_office_line"])
        self.assertFalse(stored["uzpost_far"])


class CostTest(unittest.TestCase):
    def test_tariff_plus_trip(self):
        import delivery_costs
        items = [{"name": "Bodom uni 1000gr", "quantity": 1, "price": 160_000}]
        paid = {"total": 181_000, "keto_redeemed": 0, "items": json.dumps(items), "post_office": "x"}
        self.assertEqual(delivery_costs.uzpost_cost(paid), 18_000 + 5_000)
        keyed = {"total": 160_000, "keto_redeemed": 0, "items": items,
                 "post_office": "230100 — Nukus Pochtamt, Қорақалпоғистон"}
        self.assertEqual(delivery_costs.uzpost_cost(keyed), 15_000 + 7_000 + 5_000)


class QuoteApiTest(unittest.TestCase):
    def test_quote(self):
        import webapp_server
        office = {"index": "141600", "name": "Urgut Pochtamt", "address": "Самарқанд, Ургут",
                  "hours": "Пн-Сб 09:00-17:00", "region": "Самарқанд", "lat": 39.4, "lng": 67.2, "km": 0.2}
        req = MagicMock()
        req.query = {"lat": "39.40", "lng": "67.24"}
        store = {"user_id": 5, "user_lang": "uz"}
        req.__getitem__.side_effect = store.__getitem__
        req.get.side_effect = store.get
        with patch.object(webapp_server, "get_cart", AsyncMock(return_value=[
                {"name": "Bodom uni 1000gr", "cart_quantity": 2, "unit": "kg"}])), \
                patch.object(uzpost, "nearest_office", AsyncMock(return_value=office)):
            resp = run(webapp_server.api_uzpost_quote(req))
        body = json.loads(resp.text)
        self.assertEqual(body["fee"], 15_000 + 2 * 3_000 + 3_000)
        self.assertEqual(body["office"]["address"], "Samarqand, Urgut")
        self.assertIn("yandex.uz/maps", body["office"]["map_url"])
        req.query = {"lat": "x"}
        self.assertEqual(run(webapp_server.api_uzpost_quote(req)).status, 400)


if __name__ == "__main__":
    unittest.main()
