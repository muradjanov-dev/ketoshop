"""/ombor → "Barcha adminlarga yuborish": to'liq ro'yxat har bir adminga boradi."""
import asyncio
import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import stock_alerts

PRODUCTS = [
    {"id": 1, "name": "Eritritol", "quantity": 0, "unit": "piece", "low_stock_threshold": None},
    {"id": 2, "name": "Stevia", "quantity": 3, "unit": "piece", "low_stock_threshold": None},
    {"id": 3, "name": "Bodom uni", "quantity": 40, "unit": "piece", "low_stock_threshold": None},
]


class SendAllTest(unittest.TestCase):
    def test_every_admin_gets_full_list(self):
        bot = NS(send_message=AsyncMock())
        cb = NS(from_user=NS(id=1, full_name="Ali <b>"),
                message=NS(edit_reply_markup=AsyncMock()), answer=AsyncMock())
        with patch.object(stock_alerts, "ADMIN_IDS", [11, 22]), \
             patch.object(stock_alerts.database, "get_stock_snapshot",
                          AsyncMock(return_value=PRODUCTS)):
            asyncio.run(stock_alerts.send_stock_to_all_admins(cb, bot))
        chats = [c.args[0] for c in bot.send_message.call_args_list]
        self.assertEqual(chats, [11, 22])
        text = bot.send_message.call_args_list[0].args[1]
        self.assertIn("Eritritol", text)
        self.assertIn("Stevia", text)
        self.assertNotIn("Bodom uni", text)
        self.assertIn("Ali &lt;b&gt;", text)
        self.assertIn("2/2", cb.answer.call_args.args[0])

    def test_button_only_when_something_is_low(self):
        self.assertTrue(stock_alerts._low_or_out(PRODUCTS))
        self.assertFalse(stock_alerts._low_or_out(PRODUCTS[2:]))


if __name__ == "__main__":
    unittest.main()
