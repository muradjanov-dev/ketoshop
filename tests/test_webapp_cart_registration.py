"""Regression coverage for first-time Telegram Mini App cart users."""
import asyncio
import hashlib
import hmac
import json
import os
import unittest
from urllib.parse import urlencode
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import webapp_server


class CartUserRegistrationTests(unittest.IsolatedAsyncioTestCase):
    class Request(dict):
        def __init__(self, data):
            super().__init__(data)
            self.app = data["app"]

        async def json(self):
            return {"product_id": 7, "quantity": 1}

    class AuthRequest(dict):
        path = "/api/cart/add"

        def __init__(self, init_data, bot_token):
            self.headers = {"Authorization": f"tma {init_data}"}
            self.app = {"bot_token": bot_token}

    @staticmethod
    def _signed_init_data(bot_token, user):
        values = {
            "auth_date": "1900000000",
            "user": json.dumps(user, separators=(",", ":")),
        }
        data_check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        values["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        return urlencode(values)

    async def test_only_verified_init_data_exposes_the_user_profile(self):
        bot_token = "123:token"
        profile = {"id": 12345, "first_name": "Ali", "username": "ali_v"}
        request = self.AuthRequest(self._signed_init_data(bot_token, profile), bot_token)
        handler = AsyncMock(return_value=webapp_server._json({"ok": True}))

        with patch.object(webapp_server, "get_user_language", AsyncMock(return_value=None)):
            response = await webapp_server.auth_middleware(request, handler)

        self.assertEqual(response.status, 200)
        self.assertEqual(request["user_id"], 12345)
        self.assertEqual(request["telegram_user"], profile)

        request = self.AuthRequest(
            self._signed_init_data(bot_token, profile).replace("ali_v", "fake_v"), bot_token
        )
        handler.reset_mock()
        with patch.object(webapp_server, "get_user_language", AsyncMock(return_value=None)):
            response = await webapp_server.auth_middleware(request, handler)
        self.assertEqual(response.status, 403)
        handler.assert_not_awaited()

    async def _add_cart_item(self, existing_user=None):
        users = {}
        if existing_user:
            users[existing_user["user_id"]] = dict(existing_user)
        events = []

        async def create_user(user_id, username=None, full_name=None, language="uz"):
            # Model create_user's INSERT ... ON CONFLICT DO NOTHING contract.
            events.append(("register", user_id))
            users.setdefault(user_id, {
                "user_id": user_id,
                "username": username,
                "full_name": full_name,
                "language": language,
            })

        async def add_to_cart(user_id, **kwargs):
            events.append(("cart", user_id))
            if user_id not in users:
                raise RuntimeError("cart_user_id_fkey")

        request = self.Request({
            "user_id": 12345,
            "telegram_user": {
                "id": 12345,
                "first_name": "Ali",
                "last_name": "Valiyev",
                "username": "ali_v",
                "language_code": "uz",
            },
            "user_lang": "uz",
            "app": {"bot": object()},
        })
        product = {"id": 7, "name": "Test product", "quantity": 5}

        with patch.object(webapp_server, "create_user", create_user, create=True), \
             patch("database.get_product", AsyncMock(return_value=product)), \
             patch("database.get_cart_line_for_product", AsyncMock(return_value=(None, 0))), \
             patch.object(webapp_server, "add_to_cart", add_to_cart), \
             patch("handlers.cart.send_added_to_cart", AsyncMock()):
            response = await webapp_server.api_cart_add(request)
            # Let the fire-and-forget notification task settle cleanly.
            await asyncio.sleep(0)

        self.assertEqual(response.status, 200)
        self.assertEqual(events, [("register", 12345), ("cart", 12345)])
        return users[12345]

    async def test_first_time_verified_user_is_registered_before_cart_insert(self):
        user = await self._add_cart_item()

        self.assertEqual(user, {
            "user_id": 12345,
            "username": "ali_v",
            "full_name": "Ali Valiyev",
            "language": "uz",
        })

    async def test_existing_user_profile_is_not_overwritten(self):
        existing = {
            "user_id": 12345,
            "username": "saved_username",
            "full_name": "Saved Name",
            "language": "ru",
            "phone": "+998900000000",
        }

        user = await self._add_cart_item(existing_user=existing)

        self.assertEqual(user, existing)


if __name__ == "__main__":
    unittest.main(verbosity=2)
