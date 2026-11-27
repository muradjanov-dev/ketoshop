"""Qo'lda buyurtma: location + the Ketoshop courier's fee (owner, 2026-11-27:
"qo'lda buyurtma kiritganda lokatsiyani ham kiritish imkoni bo'lsin va
dostavkani shundan kelib chiqib hisoblasin").

Nothing here writes an order or sends a message."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("ADMIN_WEB_PASSWORD", "test-password")

import courier_zone
import manual_order
from handlers import admin

CITY = (41.311, 69.279)          # Amir Temur xiyoboni — inside the city
CHIRCHIQ = (41.469, 69.582)      # well past the city line, inside 40 km
SAMARQAND = (39.654, 66.959)     # far beyond 40 km

PRODUCTS = {11: {"id": 11, "name": "Bodom uni 500gr", "price": 120000, "discount_percent": 0,
                 "discount_until": None, "unit": "dona", "is_active": 1, "quantity": 7}}


def body(**kw):
    b = {"name": "Dilnoza", "phone": "+998901234567", "address": "Toshkent",
         "items": [{"product_id": 11, "quantity": 1}],
         "payment": "cash", "delivery": "self", "status": "pending"}
    b.update(kw)
    return b


class ParseLocationTest(unittest.TestCase):
    def test_plain_pair_either_order(self):
        self.assertEqual(manual_order.parse_location("41.311, 69.279"), CITY)
        self.assertEqual(manual_order.parse_location("69.279,41.311"), CITY)
        self.assertEqual(manual_order.parse_location("📍 41.311000, 69.279000 — Amir Temur"), CITY)

    def test_yandex_links_are_lng_lat(self):
        self.assertEqual(manual_order.parse_location(
            "https://yandex.uz/maps/10335/tashkent/?ll=69.279%2C41.311&z=16"), CITY)
        self.assertEqual(manual_order.parse_location(
            "https://yandex.uz/maps/?pt=69.279,41.311&z=17&l=map"), CITY)
        self.assertEqual(manual_order.parse_location(
            "https://yandex.uz/maps/?whatshere%5Bpoint%5D=69.279%2C41.311&z=17"), CITY)

    def test_google_links(self):
        self.assertEqual(manual_order.parse_location(
            "https://www.google.com/maps/place/x/@41.311,69.279,17z"), CITY)
        self.assertEqual(manual_order.parse_location("https://maps.google.com/?q=41.311,69.279"), CITY)

    def test_nothing_or_bad(self):
        self.assertIsNone(manual_order.parse_location(""))
        self.assertIsNone(manual_order.parse_location("Chilonzor 5-kvartal, 12-uy"))
        with self.assertRaises(manual_order.Invalid):
            manual_order.parse_location("https://yandex.uz/maps/-/CDabc123")
        with self.assertRaises(manual_order.Invalid):
            manual_order.parse_location("48.85, 2.35")       # Paris


class CourierFeeTest(unittest.TestCase):
    def test_city(self):
        order = manual_order.parse(body(location="41.311, 69.279"), PRODUCTS)
        self.assertEqual((order["latitude"], order["longitude"]), CITY)
        self.assertEqual(order["courier_fee"], 25000)
        self.assertEqual(order["total"], 120000 + 25000)

    def test_outside_the_city_adds_per_km(self):
        order = manual_order.parse(body(location="%s, %s" % CHIRCHIQ), PRODUCTS)
        km = courier_zone.billable_km(*CHIRCHIQ)
        self.assertGreater(km, 0)
        self.assertEqual(order["courier"]["km"], km)
        self.assertEqual(order["courier_fee"], 25000 + km * courier_zone.PER_KM)
        self.assertFalse(order["courier"]["far"])
        self.assertEqual(order["total"], 120000 + order["courier_fee"])

    def test_far_is_flagged_not_refused(self):
        order = manual_order.parse(body(location="%s, %s" % SAMARQAND), PRODUCTS)
        self.assertTrue(order["courier"]["far"])

    def test_free_base_from_800k_keeps_km(self):
        order = manual_order.parse(body(items=[{"product_id": 11, "quantity": 7}],
                                        location="%s, %s" % CHIRCHIQ), PRODUCTS)
        km = courier_zone.billable_km(*CHIRCHIQ)
        self.assertEqual(order["courier_fee"], km * courier_zone.PER_KM)

    def test_other_methods_no_courier_fee_but_keep_location(self):
        for method in ("pickup", "yandex_taxi", "bts", "emu"):
            order = manual_order.parse(body(delivery=method, location="41.311, 69.279"), PRODUCTS)
            self.assertEqual(order["courier_fee"], 0, method)
            self.assertEqual(order["total"], 120000, method)
            self.assertEqual(order["latitude"], CITY[0])

    def test_location_can_stand_for_the_address(self):
        order = manual_order.parse(body(address="", location="41.311, 69.279"), PRODUCTS)
        self.assertEqual(order["address"], "📍 41.311000, 69.279000")
        with self.assertRaises(manual_order.Invalid):
            manual_order.parse(body(address=""), PRODUCTS)


def fake_state(data):
    store = dict(data)
    st = MagicMock()
    st.get_data = AsyncMock(side_effect=lambda: dict(store))
    st.update_data = AsyncMock(side_effect=lambda **kw: store.update(kw))
    st.set_state = AsyncMock()
    st.clear = AsyncMock()
    st.store = store
    return st


class BotFlowTest(unittest.TestCase):
    DATA = {"lang": "uz", "name": "A", "phone": "+998930000000", "address": "Chirchiq",
            "payment": "cash", "delivery": "self", "status": "pending",
            "items": [{"product_id": 11, "name": "Bodom uni 500gr", "quantity": 1,
                       "price": 120000, "unit": "dona"}]}

    def test_confirm_and_save_add_the_km_fee(self):
        lat, lng = CHIRCHIQ
        km = courier_zone.billable_km(lat, lng)
        fee = 25000 + km * courier_zone.PER_KM
        data = dict(self.DATA, latitude=lat, longitude=lng)
        target = MagicMock()
        target.edit_text = AsyncMock()
        asyncio.run(admin._show_manual_confirm(target, fake_state(data), "uz"))
        text = target.edit_text.await_args.args[0]
        self.assertIn(f"Shahardan {km} km tashqarida", text)
        self.assertIn(f"Jami: {120000 + fee:,} so'm".replace(",", " "), text)

        saved = AsyncMock(return_value=77)
        cb = MagicMock()
        cb.from_user.id = 1
        cb.message.edit_text = AsyncMock()
        cb.answer = AsyncMock()
        with patch.object(admin, "add_manual_order", saved), \
                patch("order_admin_feed.manual_created", MagicMock()):
            asyncio.run(admin.manual_save(cb, fake_state(data)))
        kw = saved.await_args.kwargs
        self.assertEqual(kw["total"], 120000 + fee)
        self.assertEqual((kw["latitude"], kw["longitude"]), (lat, lng))

    def test_pasted_link_in_the_address_step_is_a_location(self):
        msg = MagicMock()
        msg.text = "https://yandex.uz/maps/?pt=69.279,41.311&z=17"
        msg.answer = AsyncMock()
        st = fake_state(dict(self.DATA, address=None))
        with patch.object(admin, "_show_manual_category_picker", AsyncMock()):
            asyncio.run(admin.manual_address(msg, st))
        self.assertEqual((st.store["latitude"], st.store["longitude"]), CITY)
        self.assertEqual(st.store["address"], "📍 41.311000, 69.279000")

    def test_typed_street_stays_without_location(self):
        msg = MagicMock()
        msg.text = "Chilonzor 5, 12-uy"
        msg.answer = AsyncMock()
        st = fake_state(dict(self.DATA, address=None))
        with patch.object(admin, "_show_manual_category_picker", AsyncMock()):
            asyncio.run(admin.manual_address(msg, st))
        self.assertIsNone(st.store["latitude"])
        self.assertEqual(st.store["address"], "Chilonzor 5, 12-uy")


if __name__ == "__main__":
    unittest.main()
