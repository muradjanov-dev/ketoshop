"""AI suhbatidagi shikoyat adminlarga (complaints.py, egasi 2026-11-26 — saytdagi
"javdar uni kelmagan edi ... hech kim olib kelmadi" ko'zdan qochgan edi)."""
import asyncio
import os
import unittest
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import complaints
import database


class ComplaintTest(unittest.TestCase):
    def setUp(self):
        complaints._recent.clear()

    def test_recognised_in_every_script(self):
        for text in ("Отган сафар жавдар уни заказ киганимда,кемаган эди, об кеб берамиз диб хеч ким об кемади",
                     "Булар тогри лекин ичида жавдар уни кемаган", "buyurtmam hali kelmadi",
                     "Заказ не пришел, верните деньги", "bodom uni buzilgan ekan"):
            self.assertTrue(complaints.is_complaint(text), text)
        for text in ("bodom uni bormi", "rahmat, yetib keldi", "Сколько стоит стевия"):
            self.assertFalse(complaints.is_complaint(text), text)

    def test_card_goes_to_admins_once_with_orders(self):
        sent = AsyncMock()
        orders = [{"id": 828, "created_at": datetime(2026, 10, 30, 9), "status": "delivered",
                   "items": '[{"name": "Javdar uni", "quantity": 1}]'}]
        user = NS(id=7, full_name="Kiri", username=None)
        with patch("handlers.support_relay._to_admins", sent), \
                patch.object(database, "get_user_orders", AsyncMock(return_value=orders)):
            first = asyncio.run(complaints.escalate(object(), user, "site", "javdar uni kemagan", "Kechirasiz…"))
            second = asyncio.run(complaints.escalate(object(), user, "site", "hech kim olib kelmadi", "…"))
        self.assertTrue(first)
        self.assertFalse(second)                         # 6 soat ichida bitta kartochka
        body = sent.await_args.args[2]
        self.assertIn("SHIKOYAT", body)
        self.assertIn("Sayt yordamchisi", body)
        self.assertIn("#828", body)
        self.assertIn("Javdar uni", body)

    def test_normal_question_sends_nothing(self):
        sent = AsyncMock()
        with patch("handlers.support_relay._to_admins", sent):
            self.assertFalse(asyncio.run(complaints.escalate(object(), NS(id=8, full_name="A", username=None),
                                                             "bot", "steviya narxi", "…")))
        sent.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
