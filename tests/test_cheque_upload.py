"""Mini App payment cheque upload — owner report 2026-10-11: buyers who
ordered on the site could not send their cheque. When the bot could not
write to the buyer (never pressed START, or blocked the bot) every attempt
created an order and still answered "Chekni yuborib bo'lmadi"."""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

import webapp_server
import subscription_gate
import state_guard
import handlers.cart as cart
import handlers.start as start
from handlers.cart import CheckoutStates

BUYER, ADMIN_A, ADMIN_B = 123, 900, 901
FORBIDDEN = TelegramForbiddenError(method=None, message="Forbidden: bot can't initiate conversation with a user")


def _sent_photo(**kwargs):
    return SimpleNamespace(photo=[SimpleNamespace(file_id=f"photo-{kwargs['chat_id']}")])


def _sent_document(**kwargs):
    return SimpleNamespace(document=SimpleNamespace(file_id=f"doc-{kwargs['chat_id']}"))


class Request(dict):
    def __init__(self, storage, bot, match_info=None):
        super().__init__(user_id=BUYER, user_lang="uz")
        self.app = {"storage": storage, "bot": bot}
        self.match_info = match_info or {}


class ChequeUploadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.storage = MemoryStorage()
        self.state = FSMContext(storage=self.storage,
                                key=StorageKey(bot_id=1, chat_id=BUYER, user_id=BUYER))
        await self.state.set_state(CheckoutStates.waiting_cheque)
        await self.state.update_data(
            lang="uz", pending_items=[{"product_id": 7, "name": "Tea", "quantity": 1, "price": 100}],
            pending_total=100, pending_phone="+998901234567", pending_address="addr",
            pending_delivery_method="self", pending_customer_name="Ali")
        self.create_order = AsyncMock(return_value=(500, []))
        self.set_cheque = AsyncMock()
        self.forward = AsyncMock()
        self.notify = AsyncMock()

    def _bot(self, photo=_sent_photo, document=_sent_document):
        return SimpleNamespace(id=1, send_photo=AsyncMock(side_effect=photo),
                               send_document=AsyncMock(side_effect=document))

    async def _upload(self, bot, handler=webapp_server.api_checkout_cheque, match_info=None):
        with patch.object(webapp_server, "_read_cheque_upload",
                          AsyncMock(return_value=(b"jpeg", "image/jpeg", "chek.jpg"))), \
             patch.object(webapp_server, "ADMIN_IDS", [ADMIN_A, ADMIN_B]), \
             patch.object(webapp_server, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(webapp_server, "create_order", self.create_order), \
             patch.object(webapp_server, "get_order", AsyncMock(return_value={
                 "id": 500, "user_id": BUYER, "payment_method": "online", "status": "pending",
                 "customer_name": "Ali", "items": "[]", "total": 100})), \
             patch("database.set_order_cheque", self.set_cheque), \
             patch("handlers.cart._forward_cheque_to_admins", self.forward), \
             patch("handlers.cart._notify_sellers", self.notify), \
             patch("handlers.cart.send_order_thanks", AsyncMock()):
            response = await handler(Request(self.storage, bot, match_info))
        return response.status, json.loads(response.text)

    async def test_reachable_buyer_gets_the_echo_and_every_admin_the_cheque(self):
        status, body = await self._upload(self._bot())
        self.assertEqual(status, 200)
        self.assertEqual(body["order_id"], 500)
        self.set_cheque.assert_awaited_once_with(500, f"photo-{BUYER}", "photo")
        self.assertNotIn(ADMIN_A, self.forward.await_args.kwargs["skip"])
        self.assertIsNone(await self.state.get_state())

    async def test_unreachable_buyer_cheque_goes_straight_to_an_admin(self):
        def photo(**kwargs):
            if kwargs["chat_id"] == BUYER:
                raise FORBIDDEN
            return _sent_photo(**kwargs)
        bot = self._bot(photo=photo, document=lambda **kw: (_ for _ in ()).throw(FORBIDDEN))
        status, body = await self._upload(bot)
        self.assertEqual(status, 200)
        self.assertEqual(self.create_order.await_count, 1)
        self.set_cheque.assert_awaited_once_with(500, f"photo-{ADMIN_A}", "photo")
        # The admin who received the upload is not sent a second copy.
        self.assertEqual(self.forward.await_args.kwargs["skip"], {ADMIN_A})
        self.notify.assert_awaited_once()
        self.assertIsNone(await self.state.get_state())

    async def test_picture_refused_as_photo_is_sent_as_a_document(self):
        bot = self._bot(photo=lambda **kw: (_ for _ in ()).throw(
            TelegramBadRequest(method=None, message="Bad Request: PHOTO_INVALID_DIMENSIONS")))
        status, _ = await self._upload(bot)
        self.assertEqual(status, 200)
        self.set_cheque.assert_awaited_once_with(500, f"doc-{BUYER}", "document")

    async def test_total_failure_never_creates_a_second_order_on_retry(self):
        fail = lambda **kw: (_ for _ in ()).throw(FORBIDDEN)
        bot = self._bot(photo=fail, document=fail)
        status, body = await self._upload(bot)
        self.assertEqual(status, 502)
        self.assertEqual(body["order_id"], 500)  # the Mini App retries against this order
        status, body = await self._upload(bot)
        self.assertEqual((status, body["error"]), (409, "no_pending_checkout"))
        self.assertEqual(self.create_order.await_count, 1)
        self.set_cheque.assert_not_awaited()

    async def test_retry_on_existing_order_falls_back_to_admin_too(self):
        def photo(**kwargs):
            if kwargs["chat_id"] == BUYER:
                raise FORBIDDEN
            return _sent_photo(**kwargs)
        bot = self._bot(photo=photo, document=lambda **kw: (_ for _ in ()).throw(FORBIDDEN))
        status, body = await self._upload(bot, webapp_server.api_order_cheque, {"id": "500"})
        self.assertEqual((status, body["order_id"]), (200, 500))
        self.set_cheque.assert_awaited_once_with(500, f"photo-{ADMIN_A}", "photo")
        self.create_order.assert_not_awaited()


class SubscriptionGateChequeTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, state_value):
        storage = MemoryStorage()
        state = FSMContext(storage=storage, key=StorageKey(bot_id=1, chat_id=BUYER, user_id=BUYER))
        if state_value:
            await state.set_state(state_value)
        bot = SimpleNamespace(send_message=AsyncMock())
        event = SimpleNamespace(from_user=SimpleNamespace(id=BUYER, language_code="uz"),
                                chat=SimpleNamespace(type="private", id=BUYER), text=None)
        handler = AsyncMock(return_value="handled")
        with patch.object(subscription_gate, "Message", SimpleNamespace), \
             patch.object(subscription_gate, "_is_subscribed", AsyncMock(return_value=False)):
            await subscription_gate.SubscriptionGateMiddleware()(handler, event, {"bot": bot, "state": state})
        return handler, bot

    async def test_unsubscribed_buyer_can_still_send_the_cheque(self):
        handler, bot = await self._run(CheckoutStates.waiting_cheque)
        handler.assert_awaited_once()
        bot.send_message.assert_not_awaited()

    async def test_unsubscribed_user_without_pending_cheque_is_still_gated(self):
        handler, bot = await self._run(None)
        handler.assert_not_awaited()
        bot.send_message.assert_awaited_once()


async def _pending_state(state_value=CheckoutStates.waiting_cheque, pending=True):
    state = FSMContext(storage=MemoryStorage(), key=StorageKey(bot_id=1, chat_id=BUYER, user_id=BUYER))
    if state_value:
        await state.set_state(state_value)
    if pending:
        await state.update_data(lang="uz", pending_items=[{"name": "Tea"}], pending_total=1234567)
    return state


class PayFromChatTests(unittest.IsolatedAsyncioTestCase):
    """The chat side of a Mini App online order: the buyer either taps
    "Botga qaytib to'layman" or has to press START before sending the cheque."""

    async def _guard(self, text, state):
        handler = AsyncMock()
        with patch.object(state_guard, "Message", SimpleNamespace):
            await state_guard.StateResetOnCommandMiddleware()(handler, SimpleNamespace(text=text),
                                                              {"state": state})
        handler.assert_awaited_once()
        return await state.get_state()

    def test_guard_names_the_real_state(self):
        self.assertEqual(CheckoutStates.waiting_cheque.state, state_guard.WAITING_CHEQUE)

    async def test_start_keeps_the_order_waiting_for_its_cheque(self):
        self.assertEqual(await self._guard("/start", await _pending_state()),
                         CheckoutStates.waiting_cheque.state)

    async def test_other_commands_still_reset_it(self):
        self.assertIsNone(await self._guard("/savat", await _pending_state()))

    async def test_start_still_resets_any_other_flow(self):
        self.assertIsNone(await self._guard("/start", await _pending_state(CheckoutStates.waiting_phone, pending=False)))

    async def test_prompt_shows_card_total_and_cancel(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        with patch.object(cart, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(cart, "PAYMENT_CARD_NUMBER", "8600 0000 0000 0000"):
            await cart.send_pending_cheque_prompt(bot, BUYER, {"pending_total": 1234567})
        chat_id, text = bot.send_message.await_args.args
        self.assertEqual(chat_id, BUYER)
        self.assertIn("1 234 567", text)
        self.assertIn("8600 0000 0000 0000", text)
        markup = bot.send_message.await_args.kwargs["reply_markup"]
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, "checkout_cancel")

    async def test_start_mid_payment_reminds_what_to_pay(self):
        state = await _pending_state()
        message = SimpleNamespace(chat=SimpleNamespace(type="private"), bot=object(),
                                  from_user=SimpleNamespace(id=BUYER))
        prompt = AsyncMock()
        with patch.object(start, "_handle_start", AsyncMock()), \
             patch.object(cart, "send_pending_cheque_prompt", prompt):
            await start.cmd_start(message, state)
            prompt.assert_awaited_once()
            await state.clear()
            await start.cmd_start(message, state)
            prompt.assert_awaited_once()  # nothing pending → no reminder

    async def _pay_in_chat(self, state, send_message):
        bot = SimpleNamespace(id=1, send_message=send_message)
        request = Request(state.storage, bot)
        with patch.object(cart, "get_user_language", AsyncMock(return_value="uz")):
            response = await webapp_server.api_checkout_pay_in_chat(request)
        return response.status, json.loads(response.text)

    async def test_pay_in_chat_puts_the_card_details_in_the_chat(self):
        send = AsyncMock()
        self.assertEqual(await self._pay_in_chat(await _pending_state(), send), (200, {"ok": True}))
        send.assert_awaited_once()

    async def test_pay_in_chat_without_pending_checkout(self):
        send = AsyncMock()
        status, body = await self._pay_in_chat(await _pending_state(None, pending=False), send)
        self.assertEqual((status, body["error"]), (409, "no_pending_checkout"))
        send.assert_not_awaited()

    async def test_pay_in_chat_when_the_bot_cant_write_yet(self):
        status, body = await self._pay_in_chat(await _pending_state(), AsyncMock(side_effect=FORBIDDEN))
        self.assertEqual((status, body["error"]), (502, "bot_cant_write"))


if __name__ == "__main__":
    unittest.main()
