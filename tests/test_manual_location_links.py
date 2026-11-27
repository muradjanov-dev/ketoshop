"""Qo'lda buyurtma: every kind of location (owner, 2026-11-27: "bot orqali
ham qilganda telegramni lokatsiyasini va boshqa turdagi lokatsiyalarni
yuborish imkonli bo'lsin"). No network: link following is mocked."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import manual_order
from handlers import admin

CITY = (41.311, 69.279)


def run(coro):
    return asyncio.run(coro)


class ShapesTest(unittest.TestCase):
    def test_dms_from_google(self):
        lat, lng = manual_order.parse_location("41°18'39.6\"N 69°16'44.4\"E")
        self.assertAlmostEqual(lat, 41.311, places=3)
        self.assertAlmostEqual(lng, 69.279, places=3)

    def test_2gis_and_apple(self):
        self.assertEqual(manual_order.parse_location(
            "https://2gis.uz/tashkent/geo/70000001/69.279%2C41.311?m=69.279%2C41.311%2F16"), CITY)
        self.assertEqual(manual_order.parse_location("https://maps.apple.com/?ll=41.311,69.279&q=Pin"), CITY)


class ResolveTest(unittest.TestCase):
    def setUp(self):
        manual_order._RESOLVED.clear()

    def test_yandex_short_link_is_followed(self):
        follow = AsyncMock(return_value="https://yandex.uz/maps/10335/tashkent/?ll=69.279%2C41.311&z=17\n<html>")
        with patch.object(manual_order, "_follow", follow):
            self.assertEqual(run(manual_order.resolve_location("https://yandex.uz/maps/-/CHvS5LzQ")), CITY)
            # the second time comes from the cache
            self.assertEqual(run(manual_order.resolve_location("https://yandex.uz/maps/-/CHvS5LzQ")), CITY)
        follow.assert_awaited_once()

    def test_google_short_link_point_in_the_page(self):
        page = "https://www.google.com/maps/place/Foo\n<meta content=\"https://maps.google.com/maps/api/staticmap?center=41.311%2C69.279\">"
        with patch.object(manual_order, "_follow", AsyncMock(return_value=page)):
            self.assertEqual(run(manual_order.resolve_location("Mijoz: https://maps.app.goo.gl/AbC123 shu yerda")), CITY)

    def test_link_that_leads_nowhere_says_what_to_do(self):
        with patch.object(manual_order, "_follow", AsyncMock(side_effect=OSError("down"))):
            with self.assertRaises(manual_order.Invalid) as ctx:
                run(manual_order.resolve_location("https://maps.app.goo.gl/nothing"))
        self.assertIn("Telegram lokatsiyasini", str(ctx.exception))

    def test_other_sites_are_never_fetched(self):
        follow = AsyncMock()
        with patch.object(manual_order, "_follow", follow):
            with self.assertRaises(manual_order.Invalid):
                run(manual_order.resolve_location("https://example.com/x"))
            self.assertIsNone(run(manual_order.resolve_location("Chilonzor 5, 12-uy")))
            self.assertEqual(run(manual_order.resolve_location("41.311, 69.279")), CITY)
        follow.assert_not_awaited()


def fake_state(data):
    store = dict(data)
    st = MagicMock()
    st.get_data = AsyncMock(side_effect=lambda: dict(store))
    st.update_data = AsyncMock(side_effect=lambda **kw: store.update(kw))
    st.set_state = AsyncMock()
    st.store = store
    return st


class BotTest(unittest.TestCase):
    def test_venue_is_a_location_with_its_name(self):
        msg = MagicMock()
        msg.from_user.id = admin.ADMIN_IDS[0] if admin.ADMIN_IDS else 1
        msg.location = None
        msg.venue.location.latitude, msg.venue.location.longitude = CITY
        msg.venue.title, msg.venue.address = "Korzinka Chilonzor", "Bunyodkor 1"
        msg.answer = AsyncMock()
        st = fake_state({"lang": "uz"})
        with patch.object(admin, "is_admin", lambda _uid: True), \
                patch.object(admin, "_show_manual_category_picker", AsyncMock()), \
                patch("handlers.cart.get_location_address_text", AsyncMock(return_value=None)):
            run(admin.manual_address_location(msg, st))
        self.assertEqual((st.store["latitude"], st.store["longitude"]), CITY)
        self.assertIn("Korzinka Chilonzor, Bunyodkor 1", st.store["address"])

    def test_short_link_typed_in_the_address_step(self):
        manual_order._RESOLVED.clear()
        msg = MagicMock()
        msg.text = "https://yandex.uz/maps/-/CHvS5LzQ"
        msg.answer = AsyncMock()
        st = fake_state({"lang": "uz"})
        with patch.object(manual_order, "_follow", AsyncMock(return_value="https://yandex.uz/maps/?ll=69.279,41.311\n")), \
                patch.object(admin, "_show_manual_category_picker", AsyncMock()):
            run(admin.manual_address(msg, st))
        self.assertEqual((st.store["latitude"], st.store["longitude"]), CITY)
        self.assertEqual(st.store["address"], "📍 41.311000, 69.279000")


if __name__ == "__main__":
    unittest.main()
