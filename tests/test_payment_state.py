"""AI karta buyurtmasi: "TO'LANMAGAN" belgisi va "✅ To'lov tasdiqlandi" tugmasi.

AI buyurtmani pul kelmasdan tuzadi (payment_method='cash', izoh "To'lov: KARTA").
Egasi, 2026-10-14: to'lanmagan buyurtma hali to'lanmaganini ko'rsatsin.
Bazaga ham, Telegram'ga ham ulanmaydi.
"""
import asyncio
import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ai_sales
import payment_state
from handlers.cart import payment_status_block

AI_NOTE = "To'lov: KARTA (chek kutilmoqda)"


class CardPaymentStateTest(unittest.TestCase):
    def test_states(self):
        state = payment_state.card_payment_state
        self.assertEqual(state("cash", AI_NOTE), "unpaid")
        self.assertEqual(state("cash", AI_NOTE, "file123"), "cheque")
        self.assertIsNone(state("online", AI_NOTE, "file123"))        # tasdiqlangan
        self.assertIsNone(state("cash", None))                        # oddiy naqd
        self.assertIsNone(state("cash", "3-uy, 12-xonadon"))

    def test_order_card_line_never_says_cash_on_delivery_for_an_unpaid_card_order(self):
        unpaid = payment_status_block("cash", "pending", "uz", AI_NOTE)
        self.assertIn("TO'LANMAGAN", unpaid)
        self.assertNotIn("Yetkazib berishda", unpaid)
        self.assertIn("tekshiring", payment_status_block("cash", "pending", "uz", AI_NOTE, "file"))
        self.assertIn("НЕ ОПЛАЧЕНО", payment_status_block("cash", "pending", "ru", AI_NOTE))
        # Boshqa buyurtmalar avvalgidek.
        self.assertIn("Yetkazib berishda", payment_status_block("cash", "pending", "uz"))
        self.assertIn("To'langan", payment_status_block("online", "pending", "uz", AI_NOTE, "file"))


class CardPaidButtonTest(unittest.TestCase):
    def setUp(self):
        self.saved = (ai_sales.ADMIN_IDS, ai_sales.mark_card_paid)
        ai_sales.ADMIN_IDS = [1]

    def tearDown(self):
        ai_sales.ADMIN_IDS, ai_sales.mark_card_paid = self.saved

    def _tap(self, user_id=1):
        return NS(data="aipaid:5001", from_user=NS(id=user_id, username="admin", full_name="Admin"),
                  answer=AsyncMock(),
                  message=NS(caption="🧾 Buyurtma #5001 uchun to'lov cheki", edit_reply_markup=AsyncMock(),
                             edit_caption=AsyncMock()))

    def test_admin_confirms_and_the_button_disappears(self):
        ai_sales.mark_card_paid = AsyncMock(return_value=True)
        callback = self._tap()
        asyncio.run(ai_sales.cb_card_paid(callback))
        ai_sales.mark_card_paid.assert_awaited_once_with(5001)
        callback.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)
        self.assertIn("To'lov tasdiqlandi", callback.message.edit_caption.await_args.kwargs["caption"])
        self.assertIn("#5001", callback.answer.await_args.args[0])

    def test_non_admin_cannot_confirm(self):
        ai_sales.mark_card_paid = AsyncMock(return_value=True)
        asyncio.run(ai_sales.cb_card_paid(self._tap(user_id=99)))
        ai_sales.mark_card_paid.assert_not_awaited()

    def test_the_cheque_reaches_admins_with_the_confirm_button(self):
        keyboard = ai_sales._paid_kb(5001)
        self.assertEqual(keyboard.inline_keyboard[0][0].callback_data, "aipaid:5001")


if __name__ == "__main__":
    unittest.main()
