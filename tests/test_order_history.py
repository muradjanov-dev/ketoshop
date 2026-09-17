"""Yangi buyurtma kartasida "mijozning nechanchi buyurtmasi" qatori."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
from handlers import cart


def block(pos, lang="uz"):
    with patch.object(database, "get_order_history_position", AsyncMock(return_value=pos)):
        return asyncio.run(cart.order_history_block(555, 42, lang))


class OrderHistoryBlockTest(unittest.TestCase):
    def test_first_order(self):
        self.assertIn("Yangi mijoz — 1-buyurtmasi", block({"nth": 1, "delivered": 0, "cancelled": 0}))

    def test_repeat_order(self):
        text = block({"nth": 3, "delivered": 2, "cancelled": 1})
        self.assertIn("3-buyurtmasi", text)
        self.assertIn("oldingi 2 tasi yetkazilgan", text)
        self.assertIn("1 ta bekor qilingan", text)

    def test_russian_admin(self):
        self.assertIn("3-й заказ", block({"nth": 3, "delivered": 2, "cancelled": 0}, "ru"))

    def test_history_unavailable_never_breaks_the_card(self):
        with patch.object(database, "get_order_history_position", AsyncMock(side_effect=RuntimeError("db"))):
            self.assertEqual(asyncio.run(cart.order_history_block(555, 42, "uz")), "")
        self.assertEqual(asyncio.run(cart.order_history_block(None, 42, "uz")), "")


if __name__ == "__main__":
    unittest.main()
