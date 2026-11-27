"""The post index on every UzPost order (owner, 2026-11-27: "pochta indeksi
pochtali buyurtmalarda har doyim ko'rinsin"). Nothing is sent or saved."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import manual_order
import order_admin_feed
import uzpost

OFFICE = "141600 — Urgut Pochtamt, Samarqand, Urgut"


class IndexTextTest(unittest.TestCase):
    def test_index_in_text(self):
        self.assertEqual(uzpost.index_in_text("Urgut, 141600, Navoiy 17"), "141600")
        self.assertEqual(uzpost.index_in_text("Toshkent 100047"), "100047")
        self.assertIsNone(uzpost.index_in_text("+998901234567, uy 12"))
        self.assertIsNone(uzpost.index_in_text("Chilonzor 5"))
        self.assertIsNone(uzpost.index_in_text(None))

    def test_index_line_prefers_the_office(self):
        self.assertEqual(uzpost.index_line(OFFICE, "… 100047"), (OFFICE, True))
        self.assertEqual(uzpost.index_line(None, "Urgut 141600"), ("141600", True))
        self.assertEqual(uzpost.index_line("", "Urgut"), (None, False))


class CardTest(unittest.TestCase):
    def lines(self, **kw):
        order = {"customer_name": "Ali", "address": "Samarqand, Urgut",
                 "delivery_method": "uzpost", "status": "cancelled"}
        order.update(kw)
        return "\n".join(order_admin_feed.customer_lines(order, "uz"))

    def test_office_on_the_card(self):
        self.assertIn(f"📮 Indeks: <b>{OFFICE}</b>", self.lines(post_office=OFFICE))

    def test_index_from_the_address(self):
        self.assertIn("📮 Indeks: <b>141600</b>", self.lines(address="Urgut 141600"))

    def test_unknown_is_said_not_hidden(self):
        self.assertIn("Indeks aniqlanmagan", self.lines())

    def test_other_methods_have_no_index_line(self):
        self.assertNotIn("📮", self.lines(delivery_method="self", post_office=OFFICE))


class ManualOfficeTest(unittest.TestCase):
    def test_nearest_office_from_the_pin(self):
        office = {"index": "141600", "name": "Urgut Pochtamt", "address": "Samarqand, Urgut"}
        with patch.object(uzpost, "nearest_office", AsyncMock(return_value=office)) as near:
            line = asyncio.run(manual_order.post_office("uzpost", 39.4, 67.2, "Urgut"))
        near.assert_awaited_once_with(39.4, 67.2)
        self.assertEqual(line, "141600 — Urgut Pochtamt, Samarqand, Urgut")

    def test_typed_index_when_no_pin_or_uzpost_down(self):
        with patch.object(uzpost, "nearest_office", AsyncMock(side_effect=RuntimeError("down"))):
            self.assertEqual(asyncio.run(manual_order.post_office("uzpost", 39.4, 67.2, "Urgut 141600")),
                             "141600")
        self.assertEqual(asyncio.run(manual_order.post_office("uzpost", None, None, "Urgut 141600")),
                         "141600")
        self.assertIsNone(asyncio.run(manual_order.post_office("uzpost", None, None, "Urgut")))

    def test_not_uzpost(self):
        with patch.object(uzpost, "nearest_office", AsyncMock()) as near:
            self.assertIsNone(asyncio.run(manual_order.post_office("self", 41.3, 69.2, "100047")))
        near.assert_not_awaited()

    def test_bot_manual_save_stores_the_office(self):
        from handlers import admin
        data = {"lang": "uz", "name": "A", "phone": "+998930000000", "address": "Urgut 141600",
                "payment": "cash", "delivery": "uzpost", "status": "pending",
                "items": [{"product_id": 1, "name": "Bodom uni 500gr", "quantity": 1, "price": 100000,
                           "unit": "dona"}]}
        st = MagicMock()
        st.get_data = AsyncMock(return_value=data)
        st.clear = AsyncMock()
        cb = MagicMock()
        cb.from_user.id = 1
        cb.message.edit_text = AsyncMock()
        cb.answer = AsyncMock()
        saved = AsyncMock(return_value=9)
        with patch.object(admin, "add_manual_order", saved), \
                patch.object(order_admin_feed, "manual_created", MagicMock()):
            asyncio.run(admin.manual_save(cb, st))
        self.assertEqual(saved.await_args.kwargs["post_office"], "141600")


if __name__ == "__main__":
    unittest.main()
