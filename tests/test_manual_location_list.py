"""Qo'lda buyurtma (egasi, 2026-11-06): manzil bosqichida lokatsiya qabul
qilinadi (uzatilgani ham), koordinata buyurtmaga yoziladi; tanlangan
mahsulotlar ro'yxati to'lov / yetkazish / holat bosqichlarida ham ko'rinadi.
Bazaga ulanmaydi, xabar yuborilmaydi."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
from handlers import admin

ITEMS = [{"product_id": 1, "name": "Qizil guruch (Devzira) 1000gr", "quantity": 1, "price": 58000, "unit": "piece"},
         {"product_id": 2, "name": "Himalay tuz <1000gr>", "quantity": 2, "price": 28000, "unit": "piece"}]


def run(coro):
    return asyncio.run(coro)


def fake_state(data):
    store = dict(data)
    state = MagicMock()

    async def get_data():
        return dict(store)

    async def update_data(**kw):
        store.update(kw)

    async def set_data(d):
        store.clear()
        store.update(d)

    state.get_data = AsyncMock(side_effect=get_data)
    state.update_data = AsyncMock(side_effect=update_data)
    state.set_data = AsyncMock(side_effect=set_data)
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    state.store = store
    return state


def location_message(lat=41.311081, lng=69.279737):
    msg = MagicMock()
    msg.from_user.id = 1
    msg.location.latitude = lat
    msg.location.longitude = lng
    msg.answer = AsyncMock()
    return msg


class LocationTest(unittest.TestCase):
    def _send(self, readable):
        state = fake_state({"lang": "uz", "name": "1", "phone": "+998930000000"})
        msg = location_message()
        geo = AsyncMock(side_effect=readable) if isinstance(readable, Exception) else AsyncMock(return_value=readable)
        with patch.object(admin, "is_admin", return_value=True), \
             patch("handlers.cart.get_location_address_text", geo):
            run(admin.manual_address_location(msg, state))
        return state, msg

    def test_location_becomes_the_address_with_its_coordinates(self):
        state, msg = self._send("Yunusobod tumani, Amir Temur 1")
        self.assertEqual(state.store["address"], "📍 41.311081, 69.279737 — Yunusobod tumani, Amir Temur 1")
        self.assertEqual((state.store["latitude"], state.store["longitude"]), (41.311081, 69.279737))
        state.set_state.assert_awaited_with(admin.AdminStates.manual_pick_category)
        self.assertIn("Lokatsiya qabul qilindi", msg.answer.await_args_list[0].args[0])

    def test_no_street_name_still_takes_the_point(self):
        state, _ = self._send(RuntimeError("geocoder down"))
        self.assertEqual(state.store["address"], "📍 41.311081, 69.279737")
        state.set_state.assert_awaited_with(admin.AdminStates.manual_pick_category)

    def test_registered_for_locations_in_the_address_step(self):
        names = [h.callback.__name__ for h in admin.router.message.handlers]
        self.assertIn("manual_address_location", names)

    def test_a_typed_address_drops_old_coordinates(self):
        state = fake_state({"lang": "uz", "latitude": 41.0, "longitude": 69.0})
        msg = MagicMock()
        msg.text = "Chilonzor 5"
        msg.answer = AsyncMock()
        run(admin.manual_address(msg, state))
        self.assertEqual((state.store["address"], state.store["latitude"]), ("Chilonzor 5", None))

    def test_a_new_manual_order_starts_clean(self):
        state = fake_state({"lang": "uz", "items": ITEMS, "payment": "cash", "latitude": 41.0, "order_type": "b2b"})
        cb = MagicMock()
        cb.from_user.id = 1
        cb.message.edit_text = AsyncMock()
        cb.answer = AsyncMock()
        with patch.object(admin, "is_admin", return_value=True), \
             patch.object(admin, "get_user_language", AsyncMock(return_value="ru")):
            run(admin.manual_order_start(cb, state))
        self.assertEqual(state.store, {"lang": "ru"})


class SaveTest(unittest.TestCase):
    def test_coordinates_go_to_the_order(self):
        state = fake_state({"lang": "uz", "name": "1", "phone": "+998930000000", "address": "📍 41.3, 69.2",
                            "latitude": 41.3, "longitude": 69.2, "items": ITEMS, "payment": "cash",
                            "delivery": "self", "status": "confirmed"})
        cb = MagicMock()
        cb.from_user.id = 1
        cb.message.edit_text = AsyncMock()
        cb.answer = AsyncMock()
        with patch.object(admin, "add_manual_order", AsyncMock(return_value=901)) as add, \
             patch("order_admin_feed.manual_created", MagicMock()):
            try:
                run(admin.manual_save(cb, state))
            except Exception:
                pass                                # only the save call matters here
        self.assertEqual((add.await_args.kwargs["latitude"], add.await_args.kwargs["longitude"]), (41.3, 69.2))

    def test_insert_carries_the_coordinates(self):
        seen = {}

        class Conn:
            def transaction(self):
                class _Tx:
                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *a):
                        return False
                return _Tx()

            async def fetchval(self, sql, *args):
                seen["sql"], seen["args"] = sql, args
                return 901

        class Pool:
            def acquire(self):
                class _Ctx:
                    async def __aenter__(self):
                        return Conn()

                    async def __aexit__(self, *a):
                        return False
                return _Ctx()

        with patch.object(database, "pool", Pool()), \
             patch.object(database, "_snapshot_order_costs", AsyncMock(side_effect=lambda conn, items: items)):
            run(database.add_manual_order(1, "B", "+998", "📍", ITEMS, 1, "cash", "self", "pending",
                                          latitude=41.3, longitude=69.2))
            self.assertEqual(seen["args"][-2:], (41.3, 69.2))
            self.assertIn("latitude, longitude", seen["sql"])
            run(database.add_manual_order(1, "B", "+998", "Chilonzor", ITEMS, 1, "cash", "self", "pending"))
            self.assertEqual(seen["args"][-2:], (None, None))


class ListTest(unittest.TestCase):
    DATA = {"lang": "uz", "name": "1", "phone": "+998930000000", "address": "Chilonzor 5", "items": ITEMS}

    def _cb(self, data):
        cb = MagicMock()
        cb.data = data
        cb.from_user.id = 1
        cb.message.edit_text = AsyncMock()
        cb.answer = AsyncMock()
        return cb

    def _assert_list(self, text):
        self.assertIn("📦 Mahsulotlar (2 ta):", text)
        self.assertIn("• Qizil guruch (Devzira) 1000gr — 1", text)
        self.assertIn("Himalay tuz &lt;1000gr&gt; — 2", text)
        self.assertIn("Jami: 114 000 so'm", text)

    def test_payment_step_shows_the_list(self):
        cb = self._cb("manualfinish")
        run(admin.manual_finish_items(cb, fake_state(self.DATA)))
        text = cb.message.edit_text.await_args.args[0]
        self._assert_list(text)
        self.assertTrue(text.endswith("To'lov turini tanlang:"))

    def test_delivery_and_status_steps_show_the_list(self):
        cb = self._cb("manualpay:cash")
        run(admin.manual_payment(cb, fake_state(self.DATA)))
        self._assert_list(cb.message.edit_text.await_args.args[0])
        cb = self._cb("manualdel:self")
        run(admin.manual_delivery(cb, fake_state(dict(self.DATA, payment="cash"))))
        self._assert_list(cb.message.edit_text.await_args.args[0])

    def test_category_screen_shows_the_list_once_something_is_picked(self):
        target = MagicMock()
        target.edit_text = AsyncMock()
        run(admin._show_manual_category_picker(target, fake_state(self.DATA), "uz"))
        self._assert_list(target.edit_text.await_args.args[0])
        target.edit_text = AsyncMock()
        run(admin._show_manual_category_picker(target, fake_state(dict(self.DATA, items=[])), "uz"))
        self.assertNotIn("Mahsulotlar", target.edit_text.await_args.args[0])

    def test_confirm_screen_unchanged(self):
        target = MagicMock()
        target.edit_text = AsyncMock()
        state = fake_state(dict(self.DATA, payment="cash", delivery="self", status="pending"))
        run(admin._show_manual_confirm(target, state, "uz"))
        text = target.edit_text.await_args.args[0]
        self.assertIn("• Qizil guruch (Devzira) 1000gr — 1", text)
        self.assertIn("Jami: 114 000 so'm", text)
        self.assertIn("Saqlaysizmi?", text)


if __name__ == "__main__":
    unittest.main()
