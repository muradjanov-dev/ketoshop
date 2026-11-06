"""Chek tasdig'i (egasi, 2026-11-06): "botdan kelgan har qanday rasmni tolov
rasmi deb qabul qilmasin, bu tolov cheki yoki yoqligini tizim so'rasin".
No Telegram, no database."""
import asyncio
import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import cheque_confirm
import handlers.cart as cart
import handlers.support_relay as support_relay
from locales import get_text

WAITING = "CheckoutStates:waiting_cheque"


def _run(coro):
    return asyncio.run(coro)


def _patch(test, obj, name, value):
    test.addCleanup(setattr, obj, name, getattr(obj, name))
    setattr(obj, name, value)


class FakeState:
    def __init__(self, state=None, data=None):
        self.state, self.data = state, dict(data or {})

    async def get_state(self):
        return self.state

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)
        return dict(self.data)

    async def clear(self):
        self.state, self.data = None, {}


USER = NS(id=777, full_name="Test Xaridor", username="testuser", is_bot=False)


def photo(message_id=50, album=None, caption=None):
    return NS(photo=[NS(file_id="small"), NS(file_id="big")], document=None, message_id=message_id,
              media_group_id=album, caption=caption, from_user=USER, reply=AsyncMock(),
              chat=NS(id=777, type="private"))


def tap(data):
    return NS(data=data, from_user=USER, answer=AsyncMock(),
              message=NS(edit_text=AsyncMock(), edit_reply_markup=AsyncMock()))


def buttons(message):
    markup = message.reply.await_args.kwargs["reply_markup"]
    return [row[0].callback_data for row in markup.inline_keyboard]


class CheckoutChequeTest(unittest.TestCase):
    def setUp(self):
        cheque_confirm._busy.clear()
        self.finalize = AsyncMock()
        _patch(self, cart, "_finalize_online_order", self.finalize)
        self.relay = AsyncMock()
        _patch(self, support_relay, "relay_media", self.relay)
        self.state = FakeState(WAITING, {"lang": "uz", "pending_items": [{"product_id": 12}]})
        self.bot = NS(send_message=AsyncMock())

    def test_a_photo_is_asked_about_not_turned_into_an_order(self):
        message = photo()
        _run(cart.process_cheque_photo(message, self.state))
        self.finalize.assert_not_awaited()
        self.assertIn("to'lov chekimi", message.reply.await_args.args[0])
        self.assertEqual(buttons(message), ["chek:co:ha:50", "chek:co:yoq:50"])

    def test_yes_places_the_order_with_that_picture(self):
        _run(cart.process_cheque_photo(photo(), self.state))
        callback = tap("chek:co:ha:50")
        _run(cart.confirm_cheque(callback, self.state, self.bot))
        self.finalize.assert_awaited_once()
        buyer, state, bot, file_id, kind = self.finalize.await_args.args
        self.assertEqual((buyer.from_user.id, file_id, kind), (777, "big", "photo"))
        self.assertIs(state, self.state)
        callback.message.edit_text.assert_awaited_once()      # tugmalar olib tashlandi
        self.relay.assert_not_awaited()

    def test_a_second_tap_never_places_a_second_order(self):
        _run(cart.process_cheque_photo(photo(), self.state))
        _run(cart.confirm_cheque(tap("chek:co:ha:50"), self.state, self.bot))
        again = tap("chek:co:ha:50")
        _run(cart.confirm_cheque(again, self.state, self.bot))
        self.finalize.assert_awaited_once()
        self.assertEqual(again.answer.await_args.args[0], get_text("cheque_confirm_expired", "uz"))

    def test_a_tap_while_the_first_is_still_running_waits(self):
        _run(cart.process_cheque_photo(photo(), self.state))
        cheque_confirm._busy.add(777)
        callback = tap("chek:co:ha:50")
        _run(cart.confirm_cheque(callback, self.state, self.bot))
        self.finalize.assert_not_awaited()
        self.assertEqual(callback.answer.await_args.args[0], get_text("cheque_confirm_busy", "uz"))
        self.assertIn("50", self.state.data["cheque_candidates"])     # rasm yo'qolmadi

    def test_no_sends_the_picture_to_the_operators_and_keeps_waiting(self):
        _run(cart.process_cheque_photo(photo(caption="karta ishlamayapti"), self.state))
        _run(cart.confirm_cheque(tap("chek:co:yoq:50"), self.state, self.bot))
        self.finalize.assert_not_awaited()
        self.relay.assert_awaited_once_with(self.bot, USER, "photo", "big", "karta ishlamayapti")
        text = self.bot.send_message.await_args.args[1]
        self.assertEqual(text, get_text("cheque_still_waiting", "uz"))
        markup = self.bot.send_message.await_args.kwargs["reply_markup"]
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, "checkout_cancel")
        self.assertEqual(self.state.state, WAITING)                     # buyurtma hali chek kutadi
        self.assertTrue(self.state.data["pending_items"])

    def test_one_question_per_album(self):
        first, second = photo(50, album="A1"), photo(51, album="A1")
        _run(cart.process_cheque_photo(first, self.state))
        _run(cart.process_cheque_photo(second, self.state))
        first.reply.assert_awaited_once()
        second.reply.assert_not_awaited()

    def test_a_file_is_asked_about_too(self):
        message = photo()
        message.photo, message.document = None, NS(file_id="pdf", mime_type="application/pdf")
        _run(cart.process_cheque_document(message, self.state))
        _run(cart.confirm_cheque(tap("chek:co:ha:50"), self.state, self.bot))
        self.assertEqual(self.finalize.await_args.args[3:], ("pdf", "document"))

    def test_each_question_keeps_its_own_picture(self):
        a, b = photo(50), photo(51)
        b.photo = [NS(file_id="other")]
        _run(cart.process_cheque_photo(a, self.state))
        _run(cart.process_cheque_photo(b, self.state))
        _run(cart.confirm_cheque(tap("chek:co:ha:50"), self.state, self.bot))
        self.assertEqual(self.finalize.await_args.args[3], "big")

    def test_only_the_last_few_pictures_are_kept(self):
        for mid in range(60, 68):
            _run(cart.process_cheque_photo(photo(mid), self.state))
        kept = sorted(self.state.data["cheque_candidates"], key=int)
        self.assertEqual(kept, [str(m) for m in range(68 - cheque_confirm.KEEP, 68)])

    def test_a_tap_after_the_order_was_cancelled_is_answered(self):
        callback = tap("chek:co:ha:50")
        _patch(self, cart, "get_user_language", AsyncMock(return_value="ru"))
        _run(cart.stale_cheque_question(callback))
        self.assertEqual(callback.answer.await_args.args[0], get_text("cheque_confirm_expired", "ru"))
        callback.message.edit_reply_markup.assert_awaited_once_with(reply_markup=None)

    def test_the_buyer_is_answered_in_their_own_chat(self):
        bot = NS(send_message=AsyncMock())
        _run(cheque_confirm.Buyer(bot, USER).answer("salom", parse_mode="HTML"))
        bot.send_message.assert_awaited_once_with(777, "salom", parse_mode="HTML")

    def test_callback_data_is_parsed_strictly(self):
        self.assertEqual(cheque_confirm.parse("chek:co:ha:50"), ("co", "ha", "50"))
        self.assertIsNone(cheque_confirm.parse("chek:co:maybe:50"))
        self.assertIsNone(cheque_confirm.parse("freereply:777:card"))
        self.assertLessEqual(len("chek:co:yoq:2147483647".encode()), 64)   # Telegram chegarasi


class RelayMediaTest(unittest.TestCase):
    """«❌ Yo'q» — rasm operatorga savol kabi: avval rasm, keyin «↩️ Javob berish» kartasi."""

    def test_picture_then_the_reply_card_for_every_admin(self):
        import ai_sales
        import review_blast
        import review_followup
        _patch(self, support_relay, "ADMIN_IDS", [1, 2])
        _patch(self, support_relay, "get_user_language", AsyncMock(return_value="uz"))
        log = AsyncMock()
        _patch(self, support_relay, "log_support_message", log)
        _patch(self, support_relay, "count_open_support", AsyncMock(return_value=1))
        _patch(self, support_relay, "release_support_claim", AsyncMock())
        _patch(self, support_relay, "record_support_relay", AsyncMock())
        _patch(self, review_followup, "reply_context", AsyncMock(return_value=""))
        _patch(self, review_blast, "reply_context", AsyncMock(return_value=""))
        _patch(self, ai_sales, "log_customer_message", AsyncMock())
        order = []
        bot = NS(send_photo=AsyncMock(side_effect=lambda *a, **k: order.append(("photo", a[0]))),
                 send_document=AsyncMock(),
                 send_message=AsyncMock(side_effect=lambda *a, **k: order.append(("card", a[0])) or
                                        NS(chat=NS(id=a[0]), message_id=9)))
        _run(support_relay.relay_media(bot, USER, "photo", "big", "shu bormi?"))
        self.assertEqual(order, [("photo", 1), ("card", 1), ("photo", 2), ("card", 2)])
        self.assertEqual(bot.send_photo.await_args.args, (2, "big"))
        card = bot.send_message.await_args
        self.assertIn("cheki emas", card.args[1])               # HTML-escaped apostrophe
        self.assertIn("shu bormi?", card.args[1])
        self.assertEqual(card.kwargs["reply_markup"].inline_keyboard[0][0].callback_data, "freereply:777:card")
        self.assertIn("shu bormi?", log.await_args.args[2])


class LocaleTest(unittest.TestCase):
    def test_every_text_has_uz_ru_and_a_cyrillic_form(self):
        for key in ("cheque_confirm_question", "btn_cheque_yes", "btn_cheque_no", "cheque_confirm_yes_done",
                    "cheque_confirm_no_done", "cheque_still_waiting", "cheque_not_cheque_relayed",
                    "cheque_confirm_expired", "cheque_confirm_busy"):
            for lang in ("uz", "ru", "uz_cyr"):
                self.assertNotIn("[", get_text(key, lang)[:1], (key, lang))
            self.assertNotEqual(get_text(key, "uz"), get_text(key, "ru"), key)
            self.assertRegex(get_text(key, "uz_cyr"), "[а-яўқғҳ]", key)


if __name__ == "__main__":
    unittest.main()
