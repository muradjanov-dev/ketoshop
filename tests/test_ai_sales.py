"""AI sotuvchi tsikli — modelga ulanmasdan.

Anthropic klienti ham, baza ham o'rnini bosuvchi (stub) bilan almashtiriladi:
test na pul sarflaydi, na tarmoqqa chiqadi. Tekshiriladigan narsa modelning
gapi emas, bizning qismimiz: vosita to'g'ri chaqiladimi, natija BITTA user
xabarida qaytadimi, xato "is_error" bo'lib ketadimi va buyurtma haqiqiy
create_order() ga tushadimi.
"""
import asyncio
import os
import time
import unittest
from unittest.mock import AsyncMock

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-not-used")

import ai_sales
import database


class _Block:
    """anthropic content block o'rnini bosadi (text yoki tool_use)."""

    def __init__(self, type, text=None, name=None, input=None, id=None):
        self.type = type
        self.text = text
        self.name = name
        self.input = input or {}
        self.id = id


class _Response:
    def __init__(self, content, stop_reason):
        self.content = content
        self.stop_reason = stop_reason


class _FakeMessages:
    """Oldindan tayyorlangan javoblarni navbat bilan qaytaradi va har
    so'rovning `messages` ini eslab qoladi."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        # `messages` ro'yxati chaqiruvdan keyin ham o'sib boradi (bitta obyekt),
        # shuning uchun nusxasini olamiz — aks holda har bir chaqiruv suhbatning
        # OXIRGI holatini ko'rsatadi.
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self._responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.messages = _FakeMessages(responses)


class _FakeUser:
    id = 777
    full_name = "Test Xaridor"
    username = "testuser"


class _FakeMessage:
    def __init__(self, text="salom"):
        self.text = text
        self.from_user = _FakeUser()
        self.bot = None


def _run(coro):
    return asyncio.run(coro)


class AiSalesToolLoopTest(unittest.TestCase):
    def setUp(self):
        ai_sales._sessions.clear()
        ai_sales._catalog_cache = (9e18, "10 | Kokos uni 1000gr | 55 000 so'm / kg | qoldiq 4")
        self._saved = {}
        for name in ("get_product", "add_to_cart", "get_cart",
                     "get_cart_line_for_product", "remove_from_cart",
                     "create_order", "clear_cart", "get_user_language"):
            self._saved[name] = getattr(database, name)

    def tearDown(self):
        for name, fn in self._saved.items():
            setattr(database, name, fn)
        ai_sales._client = None
        ai_sales._catalog_cache = None
        ai_sales._sessions.clear()

    def test_add_to_cart_tool_runs_and_reply_comes_back(self):
        database.get_product = AsyncMock(return_value={
            "id": 10, "name": "Kokos uni 1000gr", "unit": "kg",
            "quantity": 4, "is_active": 1,
        })
        database.add_to_cart = AsyncMock()

        ai_sales._client = _FakeClient([
            _Response([_Block("tool_use", name="savatga_qoshish", id="t1",
                              input={"mahsulot_id": 10, "miqdor": 2})], "tool_use"),
            _Response([_Block("text", text="2 kg kokos uni savatga solindi.")], "end_turn"),
        ])
        message = _FakeMessage("kokos uni 2 kg")
        ai_sales._session(message.from_user.id)

        reply = _run(ai_sales._respond(None, message, message.text))

        self.assertEqual(reply, "2 kg kokos uni savatga solindi.")
        database.add_to_cart.assert_awaited_once_with(777, product_id=10, quantity=2.0)

        # Vosita natijasi bitta user xabarida, tool_use_id bilan qaytdi.
        second_call = ai_sales._client.messages.calls[1]
        tool_turn = second_call["messages"][-1]
        self.assertEqual(tool_turn["role"], "user")
        self.assertEqual(len(tool_turn["content"]), 1)
        self.assertEqual(tool_turn["content"][0]["tool_use_id"], "t1")
        self.assertFalse(tool_turn["content"][0]["is_error"])

    def test_stock_shortfall_returns_is_error(self):
        database.get_product = AsyncMock(return_value={
            "id": 10, "name": "Kokos uni 1000gr", "unit": "kg",
            "quantity": 1, "is_active": 1,
        })
        database.add_to_cart = AsyncMock()

        ai_sales._client = _FakeClient([
            _Response([_Block("tool_use", name="savatga_qoshish", id="t1",
                              input={"mahsulot_id": 10, "miqdor": 5})], "tool_use"),
            _Response([_Block("text", text="Uzr, atigi 1 kg qolgan.")], "end_turn"),
        ])
        message = _FakeMessage()
        ai_sales._session(message.from_user.id)

        _run(ai_sales._respond(None, message, message.text))

        database.add_to_cart.assert_not_awaited()
        result = ai_sales._client.messages.calls[1]["messages"][-1]["content"][0]
        self.assertTrue(result["is_error"])
        self.assertIn("atigi 1", result["content"])

    def test_order_tool_creates_a_real_order_and_clears_the_cart(self):
        items = [{"product_id": 10, "name": "Kokos uni", "quantity": 2,
                  "price": 55000, "unit": "kg", "seller_id": 1}]

        async def fake_summary(user_id, data, lang):
            return "matn", 110000, items, 0

        notified = {}

        async def fake_notify(bot, order_id, items_data, data, lang):
            notified["order_id"] = order_id
            notified["payment_method"] = data["payment_method"]

        import handlers.cart as cart
        saved = (cart._build_order_summary, cart._notify_sellers, cart.notify_low_stock)
        cart._build_order_summary = fake_summary
        cart._notify_sellers = fake_notify
        cart.notify_low_stock = AsyncMock()
        database.create_order = AsyncMock(return_value=(4242, []))
        database.clear_cart = AsyncMock()
        database.get_user_language = AsyncMock(return_value="uz")
        try:
            ai_sales._client = _FakeClient([
                _Response([_Block("tool_use", name="buyurtma_rasmiylashtirish", id="t9",
                                  input={"ism": "Dilnoza", "telefon": "+998901234567",
                                         "manzil": "Chilonzor 9"})], "tool_use"),
                _Response([_Block("text", text="Buyurtmangiz #4242 qabul qilindi.")], "end_turn"),
            ])
            message = _FakeMessage("ha, tasdiqlayman")
            ai_sales._session(message.from_user.id)

            reply = _run(ai_sales._respond(None, message, message.text))
        finally:
            cart._build_order_summary, cart._notify_sellers, cart.notify_low_stock = saved

        self.assertIn("4242", reply)
        database.clear_cart.assert_awaited_once_with(777)
        self.assertEqual(notified["order_id"], 4242)
        # To'lovni faqat admin ko'radi: AI buyurtmasi doim naqd sifatida tushadi.
        self.assertEqual(notified["payment_method"], "cash")
        kwargs = database.create_order.await_args.kwargs
        self.assertEqual(kwargs["payment_method"], "cash")
        self.assertEqual(kwargs["phone"], "+998901234567")
        self.assertEqual(kwargs["customer_name"], "Dilnoza")

    def test_turn_limit_stops_a_tool_loop(self):
        database.get_cart = AsyncMock(return_value=[])
        self.addCleanup(setattr, ai_sales, "MAX_TURNS", ai_sales.MAX_TURNS)
        ai_sales.MAX_TURNS = 3
        ai_sales._client = _FakeClient([
            _Response([_Block("tool_use", name="savatni_korish", id=f"t{i}", input={})],
                      "tool_use")
            for i in range(3)
        ])
        message = _FakeMessage()
        ai_sales._session(message.from_user.id)

        reply = _run(ai_sales._respond(None, message, message.text))

        self.assertEqual(len(ai_sales._client.messages.calls), 3)
        self.assertTrue(reply)  # jim qolmaydi, biror javob baribir ketadi


class AiSalesGateTest(unittest.TestCase):
    def tearDown(self):
        ai_sales._sessions.clear()

    def test_text_filter_ignores_users_without_a_session(self):
        """Suhbat yoqilmagan bo'lsa handler UMUMAN mos kelmasligi kerak —
        aks holda xabar support_relay ga yetib bormaydi."""
        message = _FakeMessage()
        self.assertFalse(ai_sales._has_session(message))
        ai_sales._sessions[message.from_user.id] = {"messages": [], "last": 0, "orders": 0}
        # ADMIN_ONLY yoqilgan holatda begona foydalanuvchi baribir o'tmaydi.
        expected = ai_sales._allowed(message.from_user.id)
        self.assertEqual(ai_sales._has_session(message), expected)



class AiSalesLocationAndPaymentTest(unittest.TestCase):
    """Lokatsiya manzil bo'lib tushadimi, karta tanlansa nima qaytadi."""

    def setUp(self):
        ai_sales._sessions.clear()
        ai_sales._catalog_cache = (9e18, "10 | Kokos uni 1000gr | 55 000 so'm / kg | qoldiq 4")
        self._saved = {n: getattr(database, n) for n in
                       ("create_order", "clear_cart", "get_user_language")}
        self._items = [{"product_id": 10, "name": "Kokos uni", "quantity": 2,
                        "price": 55000, "unit": "kg", "seller_id": 1}]

    def tearDown(self):
        for name, fn in self._saved.items():
            setattr(database, name, fn)
        ai_sales._client = None
        ai_sales._catalog_cache = None
        ai_sales._sessions.clear()

    def _order(self, tool_input, location=None):
        """Buyurtma vositasini bir marta ishga tushiradi va (javob, create_order
        kwargs, adminlarga ketgan ma'lumot) ni qaytaradi."""
        items = self._items

        async def fake_summary(user_id, data, lang):
            return "matn", 110000, items, 0

        notified = {}

        async def fake_notify(bot, order_id, items_data, data, lang):
            notified.update(data)

        import handlers.cart as cart
        saved = (cart._build_order_summary, cart._notify_sellers, cart.notify_low_stock)
        cart._build_order_summary = fake_summary
        cart._notify_sellers = fake_notify
        cart.notify_low_stock = AsyncMock()
        database.create_order = AsyncMock(return_value=(4242, []))
        database.clear_cart = AsyncMock()
        database.get_user_language = AsyncMock(return_value="uz")
        try:
            message = _FakeMessage("ha")
            session = ai_sales._session(message.from_user.id)
            if location:
                session["location"] = location
            result = _run(ai_sales._tool_order(None, message, tool_input))
        finally:
            cart._build_order_summary, cart._notify_sellers, cart.notify_low_stock = saved
        return result, database.create_order.await_args.kwargs, notified

    def test_shared_location_becomes_the_address_and_the_admin_pin(self):
        result, kwargs, notified = self._order(
            {"ism": "Dilnoza", "telefon": "+998901234567", "tolov_turi": "naqd"},
            location=(41.311081, 69.240562, "📍 41.311081, 69.240562 — Chilonzor"),
        )
        self.assertTrue(result.startswith("OK:"), result)
        self.assertIn("Chilonzor", kwargs["address"])
        # Koordinata create_order ga ham, admin xabariga ham tushadi —
        # _notify_sellers o'shandan lokatsiya pin ini yuboradi.
        self.assertAlmostEqual(kwargs["latitude"], 41.311081)
        self.assertAlmostEqual(notified["longitude"], 69.240562)

    def test_typed_address_and_location_are_both_kept(self):
        _, kwargs, _ = self._order(
            {"ism": "Dilnoza", "telefon": "+998901234567", "manzil": "3-uy, 12-xonadon",
             "tolov_turi": "naqd"},
            location=(41.3, 69.2, "📍 41.300000, 69.200000"),
        )
        self.assertIn("41.300000", kwargs["address"])
        self.assertIn("3-uy, 12-xonadon", kwargs["address"])

    def test_no_address_and_no_location_is_an_error_not_an_order(self):
        items = self._items

        async def fake_summary(user_id, data, lang):
            return "matn", 110000, items, 0

        import handlers.cart as cart
        saved = cart._build_order_summary
        cart._build_order_summary = fake_summary
        database.create_order = AsyncMock()
        database.get_user_language = AsyncMock(return_value="uz")
        try:
            message = _FakeMessage()
            ai_sales._session(message.from_user.id)
            result = _run(ai_sales._tool_order(None, message, {
                "ism": "Dilnoza", "telefon": "+998901234567", "tolov_turi": "naqd"}))
        finally:
            cart._build_order_summary = saved
        self.assertTrue(result.startswith("Xato:"), result)
        database.create_order.assert_not_awaited()

    def test_card_payment_returns_the_card_but_never_marks_the_order_paid(self):
        result, kwargs, notified = self._order(
            {"ism": "Dilnoza", "telefon": "+998901234567", "manzil": "Chilonzor 9",
             "tolov_turi": "karta"})
        # AI kartani aytadi...
        self.assertIn(ai_sales.PAYMENT_CARD_NUMBER, result)
        self.assertIn("tasdiqlama", result.lower())
        # ...lekin bazada buyurtma "to'langan" bo'lib qolmaydi: online = chek
        # tekshirilgan degani (handlers/cart.py), buni faqat admin qo'yadi.
        self.assertEqual(kwargs["payment_method"], "cash")
        self.assertEqual(notified["payment_method"], "cash")
        self.assertIn("KARTA", kwargs["address_note"])
        # Endi chek kutilyapti — rasm kelsa adminlarga uzatiladi.
        self.assertEqual(ai_sales._sessions[777]["awaiting_cheque"], 4242)


class AiGroupModeTest(unittest.TestCase):
    """Guruhda: faqat murojaat qilinganda javob, va sotuv vositasi umuman yo'q."""

    def setUp(self):
        ai_sales._group_last.clear()
        ai_sales._group_history.clear()
        self._saved_chats = ai_sales.GROUP_CHATS
        ai_sales.GROUP_CHATS = {-1001234567890}
        ai_sales._catalog_cache = (9e18, "10 | Kokos uni 1000gr | 55 000 so'm / kg | qoldiq 4")

    def tearDown(self):
        ai_sales.GROUP_CHATS = self._saved_chats
        ai_sales._group_last.clear()
        ai_sales._group_history.clear()
        ai_sales._client = None
        ai_sales._catalog_cache = None

    def _msg(self, text, chat_id=-1001234567890, reply_from=None):
        class _Chat:
            id = chat_id

        class _From:
            def __init__(self, username, is_bot):
                self.username = username
                self.is_bot = is_bot
                self.first_name = "Aziz"

        class _Msg:
            pass

        m = _Msg()
        m.text = text
        m.chat = _Chat()
        m.from_user = _From("aziz", False)
        m.reply_to_message = None
        if reply_from:
            reply = _Msg()
            reply.from_user = _From(reply_from, True)
            m.reply_to_message = reply
        return m

    def test_plain_group_chatter_is_ignored(self):
        self.assertFalse(ai_sales._group_trigger(self._msg("bugun havo issiq ekan")))

    def test_mention_triggers_a_reply(self):
        self.assertTrue(ai_sales._group_trigger(
            self._msg(f"@{ai_sales.BOT_USERNAME} keto unlari bormi?")))

    def test_reply_to_the_bot_triggers_a_reply(self):
        self.assertTrue(ai_sales._group_trigger(
            self._msg("rahmat, narxi qancha?", reply_from=ai_sales.BOT_USERNAME)))

    def test_other_groups_are_never_answered(self):
        self.assertFalse(ai_sales._group_trigger(
            self._msg(f"@{ai_sales.BOT_USERNAME} salom", chat_id=-100999)))

    def test_cooldown_blocks_the_next_question(self):
        message = self._msg(f"@{ai_sales.BOT_USERNAME} salom")
        ai_sales._group_last[message.chat.id] = time.time()
        ai_sales.GROUP_COOLDOWN = 20
        self.assertFalse(ai_sales._group_trigger(message))

    def test_group_answer_carries_no_tools_so_nothing_can_be_sold(self):
        ai_sales._client = _FakeClient([
            _Response([_Block("text", text="Assalomu alaykum! Bodom uni bor, "
                                           "buyurtma uchun botga yozing.")], "end_turn"),
        ])
        reply = _run(ai_sales._group_respond(-1001234567890, "Aziz", "bodom uni bormi?"))
        self.assertIn("botga", reply)
        call = ai_sales._client.messages.calls[0]
        self.assertNotIn("tools", call)          # guruhda savat/buyurtma yo'q
        self.assertEqual(len(ai_sales._group_history[-1001234567890]), 2)

if __name__ == "__main__":
    unittest.main()
