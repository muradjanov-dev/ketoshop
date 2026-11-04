"""Olib ketilgan buyurtmaga kuryer chiqimi yozilmaydi, xato yozilganlari
qaytariladi (egasi, 2026-11-04). Bazaga ulanmaydi, xabar yubormaydi."""
import asyncio
import os
import re
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import delivery_costs

ROOT = Path(__file__).resolve().parent.parent
PICKUP = ["Olib ketdi", "Ofisdan olib ketdi", "Ishdan olib ketdi", "Olib ketish", "Olib ketishdi",
          "Олиб кетди", "олиб кетди", "OLIB KETDI", "olibketdi", "Самовывоз", "pickup"]
ADDRESSES = ["Chilonzor 24", "Qoraqamish 2/1", "Sergeli-7", "Foodcity", "Do‘stlik metrosi", "Авиасозлар 4",
             "Yakkasaroy Bratskiy", "📍 41.311081, 69.240562", "Olmazor, Kichik halqa yo'li 12", ""]


def run(coro):
    return asyncio.run(coro)


class PatternTest(unittest.TestCase):
    def test_recognises_a_collected_order(self):
        rx = re.compile(delivery_costs.PICKUP_ADDRESS_RE, re.IGNORECASE)
        for a in PICKUP:
            self.assertTrue(rx.search(a), a)
        for a in ADDRESSES:
            self.assertFalse(rx.search(a), a)


class SweepTest(unittest.TestCase):
    def test_booking_skips_collected_orders(self):
        fetch = AsyncMock(return_value=[])
        with patch.object(delivery_costs.database, "get_unbooked_delivery_orders", fetch):
            run(delivery_costs.book_delivered_courier_costs())
        self.assertEqual(fetch.await_args.kwargs["skip_address"], delivery_costs.PICKUP_ADDRESS_RE)

    def test_wrong_fees_come_back_and_admins_hear_the_sum(self):
        rows = [{"id": 1, "amount": 25000.0, "order_id": 873}, {"id": 2, "amount": 25000.0, "order_id": 855}]
        bot = MagicMock()
        bot.send_message = AsyncMock()
        with patch.object(delivery_costs.database, "remove_pickup_courier_expenses", AsyncMock(return_value=rows)) as rm, \
             patch("config.ADMIN_IDS", [111, 222]):
            count, total = run(delivery_costs.remove_pickup_courier_costs(bot))
        rm.assert_awaited_once_with(delivery_costs.PICKUP_ADDRESS_RE)
        self.assertEqual((count, total), (2, 50000.0))
        self.assertEqual(bot.send_message.await_count, 2)
        text = bot.send_message.await_args.args[1]
        self.assertIn("50 000 so'm", text)
        self.assertIn("#855, #873", text)

    def test_nothing_to_give_back_says_nothing(self):
        bot = MagicMock()
        bot.send_message = AsyncMock()
        with patch.object(delivery_costs.database, "remove_pickup_courier_expenses", AsyncMock(return_value=[])):
            self.assertEqual(run(delivery_costs.remove_pickup_courier_costs(bot)), (0, 0.0))
        bot.send_message.assert_not_awaited()

    def test_pickup_is_free(self):
        self.assertEqual(delivery_costs.fee_for("pickup"), 0)


class ManualOrderFormTest(unittest.TestCase):
    def test_pickup_is_offered(self):
        src = (ROOT / "handlers" / "admin.py").read_text(encoding="utf-8")
        block = src[src.index("    options = [\n        (\"self\", \"btn_delivery_self\"),".replace("\n", os.linesep if "\r\n" in src else "\n")):]
        block = block[:block.index("]")]
        self.assertIn('("pickup", "btn_delivery_pickup")', block)


if __name__ == "__main__":
    unittest.main()
