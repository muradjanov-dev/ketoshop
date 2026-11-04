"""Qo'lda buyurtmada UzPost (egasi, 2026-11-05): kg bo'yicha narx, «Jami»ga
qo'shiladi, kuryer chiqimi shu narxdan tarifni oladi. Bazaga ulanmaydi."""
import asyncio
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import delivery_costs
from handlers import admin

ROOT = Path(__file__).resolve().parent.parent
ITEMS = [{"name": "Stevia 500g", "price": 50000, "quantity": 2, "unit": "dona"}]   # 2 × 0,5 kg + box = 1,2 kg


def data(**kw):
    d = {"name": "Mijoz", "phone": "+998901234567", "address": "Samarqand, Registon", "items": ITEMS,
         "payment": "online", "delivery": "uzpost", "status": "confirmed", "lang": "uz"}
    d.update(kw)
    return d


class FeeTest(unittest.TestCase):
    def test_priced_like_a_buyers_own_order(self):
        self.assertEqual(admin._manual_uzpost(data()), (21000, 1.2))              # 15 000 + 3 000 + 3 000
        self.assertEqual(admin._manual_uzpost(data(address="Nukus shahri"))[0], 25000)   # far: +7 000 a kg
        self.assertEqual(admin._manual_uzpost(data(delivery="bts")), (0, 0.0))

    def test_courier_cost_reads_the_same_tariff_back(self):
        fee, _ = admin._manual_uzpost(data())
        order = {"total": 100000 + fee, "keto_redeemed": 0, "items": ITEMS, "post_office": None}
        self.assertEqual(delivery_costs.uzpost_cost(order), fee - 3000 + 5000)   # tariff + trip


class FormTest(unittest.TestCase):
    def test_uzpost_is_offered(self):
        src = (ROOT / "handlers" / "admin.py").read_text(encoding="utf-8")
        block = src[src.index('("self", "btn_delivery_self")'):]
        self.assertIn('("uzpost", "btn_delivery_uzpost")', block[:block.index("]")])

    def test_confirm_screen_shows_weight_fee_and_the_total_with_it(self):
        state = MagicMock()
        state.get_data = AsyncMock(return_value=data())
        state.set_state = AsyncMock()
        target = MagicMock()
        target.edit_text = AsyncMock()
        asyncio.run(admin._show_manual_confirm(target, state, "uz"))
        text = target.edit_text.await_args.args[0]
        self.assertIn("~1,2 kg · yetkazish 21 000 so'm (jamiga qo'shildi)", text)
        self.assertIn("Jami: 121 000 so'm", text)

    def test_saved_total_includes_the_fee(self):
        state = MagicMock()
        state.get_data = AsyncMock(return_value=data())
        state.clear = AsyncMock()
        cb = MagicMock()
        cb.from_user.id = 1
        cb.message.edit_text = AsyncMock()
        cb.answer = AsyncMock()
        with patch.object(admin, "add_manual_order", AsyncMock(return_value=901)) as add, \
             patch("order_admin_feed.manual_created", MagicMock()):
            try:
                asyncio.run(admin.manual_save(cb, state))
            except Exception:
                pass                                # anything after the save is not what this test is about
        self.assertEqual(add.await_args.kwargs["total"], 121000)
        self.assertEqual(add.await_args.kwargs["delivery_method"], "uzpost")


if __name__ == "__main__":
    unittest.main()
