"""Safe checkout, order state, and UI regressions for pickup."""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import courier_board
import webapp_server
import handlers.cart as cart


class Request(dict):
    def __init__(self, body, *, storage=None):
        super().__init__(user_id=123, user_lang="uz")
        self._body = body
        self.headers = {"Authorization": "tma signed"}
        self.app = {"bot_token": "1:test", "bot": SimpleNamespace(id=1), "storage": storage}

    async def json(self):
        return self._body


class PickupCheckoutApiTests(unittest.IsolatedAsyncioTestCase):
    config = {"enabled": True, "address": "Real shop address", "map_url": "https://maps.example/shop"}
    cart = [{"product_id": 7, "set_id": None, "is_set": False, "name": "Tea", "cart_quantity": 2,
             "price": 100, "unit": "kg", "seller_id": 9}]

    def common_patches(self):
        return [
            patch.object(webapp_server, "_validate_init_data", return_value={"user": {"id": 123, "first_name": "Ali"}}),
            patch.object(webapp_server, "get_pickup_settings", AsyncMock(return_value=self.config)),
            patch.object(webapp_server, "get_cart", AsyncMock(return_value=self.cart)),
            patch("promotions.bonuses_for_items", AsyncMock(return_value=[])),
            patch("gift_campaign.gift_lines", AsyncMock(return_value=[])),
            patch("gamification.is_redemption_enabled", AsyncMock(return_value=False)),
        ]

    async def test_cash_pickup_ignores_tampered_customer_location_and_fee(self):
        request = Request({"phone": "+998901234567", "delivery_method": "pickup", "payment_method": "cash",
                           "address": "Attacker address", "latitude": 41.31, "longitude": 69.24,
                           "delivery_fee": 999999})
        created = AsyncMock(return_value=(42, []))
        send_sellers = AsyncMock()
        send_thanks = AsyncMock()
        checks = self.common_patches()
        with checks[0], checks[1], checks[2], checks[3], checks[4], checks[5], \
             patch.object(webapp_server, "create_order", created), \
             patch.object(webapp_server, "update_user_info", AsyncMock(), create=True) as update_profile, \
             patch("handlers.cart.verify_uzbekistan", AsyncMock(side_effect=AssertionError("pickup must not geocode"))), \
             patch("handlers.cart._notify_sellers", send_sellers), \
             patch("handlers.cart.send_order_thanks", send_thanks):
            response = await webapp_server.api_checkout(request)
        self.assertEqual(response.status, 200)
        payload = json.loads(response.text)
        self.assertEqual(payload["order_id"], 42)
        kwargs = created.await_args.kwargs
        self.assertEqual(kwargs["address"], "Real shop address")
        self.assertIsNone(kwargs["latitude"])
        self.assertIsNone(kwargs["longitude"])
        self.assertEqual(kwargs["total"], 200)
        self.assertEqual(kwargs["pickup_map_url"], self.config["map_url"])
        update_profile.assert_not_awaited()

    async def test_disabled_pickup_is_rejected_before_cart_or_location_work(self):
        request = Request({"phone": "+998901234567", "delivery_method": "pickup", "payment_method": "cash"})
        checks = self.common_patches()
        checks[1] = patch.object(webapp_server, "get_pickup_settings", AsyncMock(return_value={"enabled": False}))
        with checks[0], checks[1], patch.object(webapp_server, "get_cart", AsyncMock()) as cart:
            response = await webapp_server.api_checkout(request)
        self.assertEqual(response.status, 409)
        self.assertEqual(json.loads(response.text)["error"], "pickup_unavailable")
        cart.assert_not_awaited()

    async def test_regular_regional_delivery_still_requires_online_payment(self):
        request = Request({"phone": "+998901234567", "delivery_method": "bts", "payment_method": "cash",
                           "latitude": 41.3, "longitude": 69.2})
        with patch("handlers.cart.verify_uzbekistan", AsyncMock(return_value=True)):
            response = await webapp_server.api_checkout(request)
        self.assertEqual(response.status, 400)
        self.assertEqual(json.loads(response.text)["error"], "cash_not_available")

    async def test_online_pickup_deferral_freezes_shop_instructions_without_coordinates(self):
        from aiogram.fsm.storage.memory import MemoryStorage
        from aiogram.fsm.storage.base import StorageKey
        storage = MemoryStorage()
        request = Request({"phone": "+998901234567", "delivery_method": "pickup", "payment_method": "online",
                           "address": "tampered", "latitude": 0, "longitude": 0, "delivery_fee": 1234}, storage=storage)
        checks = self.common_patches()
        with checks[0], checks[1], checks[2], checks[3], checks[4], checks[5]:
            response = await webapp_server.api_checkout(request)
        self.assertEqual(response.status, 200)
        data = await storage.get_data(StorageKey(bot_id=1, chat_id=123, user_id=123))
        self.assertEqual(data["pending_address"], "Real shop address")
        self.assertEqual(data["pending_pickup_map_url"], self.config["map_url"])
        self.assertNotIn("pending_pickup_working_hours", data)
        self.assertIsNone(data["pending_latitude"])
        self.assertIsNone(data["pending_longitude"])
        self.assertEqual(data["pending_total"], 200)

    async def test_bot_online_deferral_freezes_pickup_instructions(self):
        class State:
            data = {"lang": "uz", "payment_method": "online", "phone": "+998901234567",
                    "address": "Real shop", "delivery_method": "pickup", "latitude": None,
                    "longitude": None, "pickup_map_url": self.config["map_url"]}
            async def get_data(self): return dict(self.data)
            async def set_state(self, state): self.current_state = state
            async def update_data(self, **kwargs): self.data.update(kwargs)
        class Callback:
            from_user = SimpleNamespace(id=123, full_name="Ali", username="ali")
            message = SimpleNamespace(edit_text=AsyncMock())
            answer = AsyncMock()
        state, callback = State(), Callback()
        with patch.object(cart, "_build_order_summary", AsyncMock(return_value=("summary", 200, [{"name":"Tea"}], 0))):
            await cart._create_and_process_order(callback, state, object())
        self.assertEqual(state.data["pending_address"], "Real shop")
        self.assertEqual(state.data["pending_pickup_map_url"], self.config["map_url"])
        self.assertNotIn("pending_pickup_working_hours", state.data)
        self.assertIsNone(state.data["pending_latitude"])
        self.assertIsNone(state.data["pending_longitude"])

    async def test_stale_bot_pickup_selection_is_rejected_when_disabled(self):
        class State:
            cleared = False
            async def get_state(self): return cart.CheckoutStates.waiting_fulfillment.state
            async def get_data(self): return {"lang": "uz"}
            async def clear(self): self.cleared = True
        class Callback:
            data = "fulfillment:pickup"
            from_user = SimpleNamespace(id=123)
            message = SimpleNamespace(edit_text=AsyncMock())
            answer = AsyncMock()
        state, callback = State(), Callback()
        with patch.object(cart, "get_pickup_settings", AsyncMock(return_value={"enabled": False})):
            await cart.choose_fulfillment(callback, state)
        self.assertTrue(state.cleared)
        callback.answer.assert_awaited_once()
        callback.message.edit_text.assert_not_awaited()

    async def test_confirmation_rechecks_pickup_availability_before_creating_order(self):
        class State:
            cleared = False
            async def get_data(self): return {"lang": "uz", "delivery_method": "pickup"}
            async def clear(self): self.cleared = True
        class Callback:
            message = SimpleNamespace(edit_text=AsyncMock())
            answer = AsyncMock()
        state, callback = State(), Callback()
        with patch.object(cart, "get_pickup_settings", AsyncMock(return_value={"enabled": False})), \
             patch.object(cart, "_create_and_process_order", AsyncMock()) as create:
            await cart.order_confirm_yes(callback, state, object())
        self.assertTrue(state.cleared)
        create.assert_not_awaited()

    async def test_old_fulfillment_callback_is_rejected_after_checkout_state_changes(self):
        class State:
            async def get_state(self): return cart.CheckoutStates.waiting_phone.state
            async def get_data(self): return {"lang": "uz"}
        class Callback:
            data = "fulfillment:pickup"
            from_user = SimpleNamespace(id=123)
            answer = AsyncMock()
        callback = Callback()
        with patch.object(cart, "get_pickup_settings", AsyncMock(side_effect=AssertionError("stale callback"))):
            await cart.choose_fulfillment(callback, State())
        callback.answer.assert_awaited_once()
        self.assertTrue(callback.answer.await_args.kwargs["show_alert"])

    async def test_bot_entry_shows_fulfillment_choice_only_when_pickup_is_ready(self):
        class State:
            async def set_data(self, data): self.data = data
            async def set_state(self, state): self.state = state
        class Callback:
            from_user = SimpleNamespace(id=123)
            message = SimpleNamespace(edit_text=AsyncMock())
            answer = AsyncMock()
        callback, state = Callback(), State()
        with patch.object(cart, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(cart, "get_cart", AsyncMock(return_value=[{"product_id": 7}])), \
             patch.object(cart, "get_pickup_settings", AsyncMock(return_value=self.config)):
            await cart.start_checkout(callback, state)
        self.assertEqual(state.state, cart.CheckoutStates.waiting_fulfillment)
        self.assertIn("Buyurtmani qanday olasiz", callback.message.edit_text.await_args.args[0])

    async def test_quick_order_never_replays_pickup_using_home_pin(self):
        profile = {"phone": "+998901234567", "address": "📍 41.300000, 69.200000"}
        with patch.object(cart, "get_user", AsyncMock(return_value=profile)), \
             patch.object(cart, "get_last_order_prefs", AsyncMock(return_value={
                 "delivery_method": "pickup", "payment_method": "cash"})):
            prefs = await cart._quick_order_prefs(123)
        self.assertIsNone(prefs)

    async def test_bot_pickup_only_updates_phone_and_keeps_saved_home_address(self):
        class State:
            data = {"pickup": True}
            async def update_data(self, **kw): self.data.update(kw)
            async def get_data(self): return self.data
            async def set_state(self, state): self.state = state
        message = SimpleNamespace(from_user=SimpleNamespace(id=123), answer=AsyncMock())
        state = State()
        with patch.object(cart, "get_pickup_settings", AsyncMock(return_value=self.config)), \
             patch.object(cart, "update_user_info", AsyncMock()) as update:
            await cart._phone_accepted(message, state, "uz", "+998901234567")
        update.assert_awaited_once_with(123, phone="+998901234567")
        self.assertEqual(state.data["address"], self.config["address"])
        self.assertIsNone(state.data["latitude"])


class PickupCourierBoardTests(unittest.IsolatedAsyncioTestCase):
    async def test_pickup_ready_message_uses_saved_address_and_map_link(self):
        order = {"id": 56, "user_id": 123, "delivery_method": "pickup", "address": "Real shop",
                 "pickup_map_url": "https://maps.example/shop"}
        bot = SimpleNamespace(send_message=AsyncMock())
        with patch.object(courier_board.database, "get_user_language", AsyncMock(return_value="uz")), \
             patch("handlers.seller._build_buyer_status_block", return_value=("now", "timeline")):
            await courier_board._notify_buyer(bot, order, "ready")
        sent = bot.send_message.await_args.kwargs["text"]
        self.assertIn("Real shop", sent)
        self.assertIn("https://maps.example/shop", sent)
        self.assertNotIn("vaqti", sent)

    async def test_pickup_collection_message_is_labelled_collected(self):
        order = {"id": 56, "user_id": 123, "delivery_method": "pickup"}
        bot = SimpleNamespace(send_message=AsyncMock())
        with patch.object(courier_board.database, "get_user_language", AsyncMock(return_value="uz")), \
             patch("handlers.seller._build_buyer_status_block", return_value=("now", "timeline")):
            await courier_board._notify_buyer(bot, order, "delivered")
        self.assertIn("Olib ketildi", bot.send_message.await_args.kwargs["text"])

    async def test_ready_pickup_can_be_collected_without_shipped_transition(self):
        order = {"id": 55, "status": "ready", "delivery_method": "pickup", "user_id": 123,
                 "address": "Real shop", "pickup_map_url": "https://maps.example/shop",
                 "items": "[]"}
        fresh = dict(order, status="delivered")
        with patch.object(courier_board.database, "get_order", AsyncMock(side_effect=[order, fresh])), \
             patch.object(courier_board.database, "transition_order_status", AsyncMock(return_value=True)) as move, \
             patch("order_admin_feed.status_changed"):
            result = await courier_board.move_order(55, "delivered", expected_from="ready", bot=None)
        self.assertTrue(result["ok"])
        move.assert_awaited_once_with(55, ["ready"], "delivered")

    async def test_pickup_cannot_be_sent_to_courier(self):
        order = {"id": 55, "status": "ready", "delivery_method": "pickup"}
        with patch.object(courier_board.database, "get_order", AsyncMock(return_value=order)), \
             patch.object(courier_board.database, "transition_order_status", AsyncMock()) as move:
            result = await courier_board.move_order(55, "shipped", expected_from="ready", bot=None)
        self.assertFalse(result["ok"])
        move.assert_not_awaited()

    async def test_courier_assignment_sql_excludes_pickup(self):
        class Conn:
            query = ""
            async def execute(self, query, *args):
                self.query = query
                return "UPDATE 0"
        class Pool:
            def __init__(self): self.conn = Conn()
            def acquire(self):
                from contextlib import asynccontextmanager
                @asynccontextmanager
                async def cm(): yield self.conn
                return cm()
        pool = Pool()
        with patch.object(courier_board.database, "pool", pool):
            assigned = await courier_board.assign_courier(55, 88)
        self.assertFalse(assigned)
        self.assertIn("delivery_method IS DISTINCT FROM 'pickup'", pool.conn.query)


if __name__ == "__main__":
    unittest.main(verbosity=2)
