"""AI sotuvchi — modelga ulanmasdan.

Ikki qatlam alohida tekshiriladi:

1. Suhbat mantiqi (ai_sales.py) — soxta provayder bilan: vosita to'g'ri
   chaqiladimi, xato is_error bo'lib ketadimi, buyurtma haqiqiy
   create_order() ga tushadimi, guruhda vosita umuman berilmaydimi.
2. Provayder formati (ai_provider.py) — soxta klient bilan: OpenAI Responses
   API ga to'g'ri shaklda so'rov ketadimi (function_call_output,
   previous_response_id, strict), Anthropic ga ham (bitta user xabaridagi
   tool_result lar, keshlanadigan tizim bloklari).

Test na pul sarflaydi, na tarmoqqa chiqadi.
"""
import asyncio
import json
import os
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-not-used")

import ai_provider
import ai_sales
import database
from ai_provider import ToolCall, Turn


class _FakeProvider:
    """Oldindan tayyorlangan Turn larni navbat bilan qaytaradi va har
    chaqiruvni (user matni, natijalar, vositalar) eslab qoladi."""
    name = "fake"
    model = "fake-model"

    def __init__(self, turns):
        self._turns = list(turns)
        self.calls = []

    async def step(self, state, rules, catalog, tools, *, user=None, results=None,
                   max_tokens=800, history_limit=40):
        self.calls.append({"user": user, "results": results, "tools": tools,
                           "rules": rules, "catalog": catalog})
        return self._turns.pop(0)


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


class _ProviderSwap(unittest.TestCase):
    """ai_sales.PROVIDER ni soxtasiga almashtirib, oxirida qaytaradi."""

    def use(self, turns):
        saved = ai_sales.PROVIDER
        self.addCleanup(setattr, ai_sales, "PROVIDER", saved)
        ai_sales.PROVIDER = _FakeProvider(turns)
        return ai_sales.PROVIDER


class AiSalesToolLoopTest(_ProviderSwap):
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
        ai_sales._catalog_cache = None
        ai_sales._sessions.clear()

    def test_add_to_cart_tool_runs_and_reply_comes_back(self):
        database.get_product = AsyncMock(return_value={
            "id": 10, "name": "Kokos uni 1000gr", "unit": "kg",
            "quantity": 4, "is_active": 1,
        })
        database.add_to_cart = AsyncMock()
        provider = self.use([
            Turn(calls=[ToolCall("t1", "savatga_qoshish", {"mahsulot_id": 10, "miqdor": 2})]),
            Turn(text="2 kg kokos uni savatga solindi."),
        ])
        message = _FakeMessage("kokos uni 2 kg")
        ai_sales._session(message.from_user.id)

        reply = _run(ai_sales._respond(None, message, message.text))

        self.assertEqual(reply, "2 kg kokos uni savatga solindi.")
        database.add_to_cart.assert_awaited_once_with(777, product_id=10, quantity=2.0)
        # Birinchi chaqiruv — mijoz matni, katalog va vositalar bilan.
        self.assertEqual(provider.calls[0]["user"], "kokos uni 2 kg")
        self.assertIn("Kokos uni", provider.calls[0]["catalog"])
        self.assertTrue(provider.calls[0]["tools"])
        # Ikkinchisi — vosita natijasi, o'sha id bilan, xatosiz.
        result = provider.calls[1]["results"][0]
        self.assertEqual(result.id, "t1")
        self.assertFalse(result.is_error)

    def test_stock_shortfall_returns_is_error(self):
        database.get_product = AsyncMock(return_value={
            "id": 10, "name": "Kokos uni 1000gr", "unit": "kg",
            "quantity": 1, "is_active": 1,
        })
        database.add_to_cart = AsyncMock()
        provider = self.use([
            Turn(calls=[ToolCall("t1", "savatga_qoshish", {"mahsulot_id": 10, "miqdor": 5})]),
            Turn(text="Uzr, atigi 1 kg qolgan."),
        ])
        message = _FakeMessage()
        ai_sales._session(message.from_user.id)

        _run(ai_sales._respond(None, message, message.text))

        database.add_to_cart.assert_not_awaited()
        result = provider.calls[1]["results"][0]
        self.assertTrue(result.is_error)
        self.assertIn("qolgan", result.output)

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
            self.use([
                Turn(calls=[ToolCall("t9", "buyurtma_rasmiylashtirish", {
                    "ism": "Dilnoza", "telefon": "+998901234567",
                    "manzil": "Chilonzor 9", "tolov_turi": "naqd"})]),
                Turn(text="Buyurtmangiz #4242 qabul qilindi."),
            ])
            message = _FakeMessage("ha, tasdiqlayman")
            ai_sales._session(message.from_user.id)
            reply = _run(ai_sales._respond(None, message, message.text))
        finally:
            cart._build_order_summary, cart._notify_sellers, cart.notify_low_stock = saved

        self.assertIn("4242", reply)
        database.clear_cart.assert_awaited_once_with(777)
        self.assertEqual(notified["order_id"], 4242)
        self.assertEqual(notified["payment_method"], "cash")
        kwargs = database.create_order.await_args.kwargs
        self.assertEqual(kwargs["payment_method"], "cash")
        self.assertEqual(kwargs["phone"], "+998901234567")
        self.assertEqual(kwargs["customer_name"], "Dilnoza")

    def test_turn_limit_stops_a_tool_loop_and_resets_the_chain(self):
        database.get_cart = AsyncMock(return_value=[])
        self.addCleanup(setattr, ai_sales, "MAX_TURNS", ai_sales.MAX_TURNS)
        ai_sales.MAX_TURNS = 3
        provider = self.use([
            Turn(text="bir soniya", calls=[ToolCall(f"t{i}", "savatni_korish", {})])
            for i in range(3)
        ])
        message = _FakeMessage()
        session = ai_sales._session(message.from_user.id)
        session["ai"]["prev_id"] = "resp_old"

        reply = _run(ai_sales._respond(None, message, message.text))

        self.assertEqual(len(provider.calls), 3)
        self.assertTrue(reply)  # jim qolmaydi
        # Javobsiz function_call qolgan zanjir tozalandi — keyingi xabar 400 bermaydi.
        self.assertNotIn("prev_id", session["ai"])

    def test_refusal_hands_over_the_support_phone(self):
        self.use([Turn(refused=True)])
        message = _FakeMessage()
        ai_sales._session(message.from_user.id)
        reply = _run(ai_sales._respond(None, message, message.text))
        self.assertIn(ai_sales.SUPPORT_PHONES, reply)


class AiSalesGateTest(unittest.TestCase):
    def tearDown(self):
        ai_sales._sessions.clear()

    def test_text_filter_ignores_users_without_a_session(self):
        """Suhbat yoqilmagan bo'lsa handler UMUMAN mos kelmasligi kerak —
        aks holda xabar support_relay ga yetib bormaydi."""
        message = _FakeMessage()
        self.assertFalse(ai_sales._has_session(message))
        ai_sales._sessions[message.from_user.id] = {"ai": {}, "last": 0, "orders": 0}
        expected = ai_sales._allowed(message.from_user.id) and ai_sales.is_enabled()
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




class AiGroupModeTest(_ProviderSwap):
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
        ai_sales._catalog_cache = None

    def _msg(self, text, chat_id=-1001234567890, reply_from=None):
        def user(username, is_bot):
            return NS(username=username, is_bot=is_bot, first_name="Aziz")
        reply = NS(from_user=user(reply_from, True)) if reply_from else None
        return NS(text=text, chat=NS(id=chat_id), from_user=user("aziz", False),
                  reply_to_message=reply)

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
        self.addCleanup(setattr, ai_sales, "GROUP_COOLDOWN", ai_sales.GROUP_COOLDOWN)
        ai_sales.GROUP_COOLDOWN = 20
        self.assertFalse(ai_sales._group_trigger(message))

    def test_group_answer_carries_no_tools_so_nothing_can_be_sold(self):
        provider = self.use([Turn(text="Bodom uni bor, buyurtma uchun botga yozing.")])
        reply = _run(ai_sales._group_respond(-1001234567890, "Aziz", "bodom uni bormi?"))
        self.assertIn("botga", reply)
        self.assertIsNone(provider.calls[0]["tools"])     # guruhda savat/buyurtma yo'q
        self.assertIn("SOTUV JOYI EMAS", provider.calls[0]["rules"])


class AiUsagePromoKnowledgeTest(_ProviderSwap):
    """Sarf bazaga $ bilan yoziladi, aksiya faqat haqiqiy hisobdan aytiladi,
    o'rgatilgan bilim promptga tushadi, javobsiz savol yozib qo'yiladi."""

    def setUp(self):
        ai_sales._sessions.clear()
        ai_sales._catalog_cache = (9e18, "10 | Kokos uni 1000gr | 55 000 so'm / kg | qoldiq 4")
        ai_sales.invalidate_knowledge()
        self._saved = {n: getattr(database, n) for n in (
            "record_ai_usage", "list_ai_facts", "log_ai_question", "get_cart")}
        import promotions
        self._promotions = promotions
        self._saved_active = promotions.get_active

    def tearDown(self):
        for name, fn in self._saved.items():
            setattr(database, name, fn)
        self._promotions.get_active = self._saved_active
        ai_sales._catalog_cache = None
        ai_sales.invalidate_knowledge()
        ai_sales._sessions.clear()

    def test_every_model_call_is_recorded_with_a_dollar_cost(self):
        database.record_ai_usage = AsyncMock()
        database.list_ai_facts = AsyncMock(return_value=[])
        self._promotions.get_active = AsyncMock(return_value=None)
        provider = self.use([Turn(text="Salom!", usage=ai_provider.Usage(8000, 7680, 40))])
        provider.model, provider.name = "gpt-5.5", "openai"
        message = _FakeMessage()
        ai_sales._session(message.from_user.id)

        _run(ai_sales._respond(None, message, "salom"))

        args = database.record_ai_usage.await_args.args
        self.assertEqual(args[:5], ("gpt-5.5", "openai", 8000, 7680, 40))
        # 320 yangi * $5 + 7680 kesh * $0.50 + 40 chiqish * $30, 1M ga bo'lingan
        self.assertAlmostEqual(args[5], (320 * 5 + 7680 * 0.5 + 40 * 30) / 1_000_000)

    def test_usage_failure_never_breaks_the_conversation(self):
        database.record_ai_usage = AsyncMock(side_effect=RuntimeError("db down"))
        database.list_ai_facts = AsyncMock(return_value=[])
        self._promotions.get_active = AsyncMock(return_value=None)
        self.use([Turn(text="Salom!", usage=ai_provider.Usage(100, 0, 5))])
        message = _FakeMessage()
        ai_sales._session(message.from_user.id)
        self.assertEqual(_run(ai_sales._respond(None, message, "salom")), "Salom!")

    def test_taught_facts_and_active_promo_reach_the_prompt(self):
        database.list_ai_facts = AsyncMock(return_value=[
            {"id": 1, "text": "Yetkazish Toshkent ichida 25 000 so'm"}])
        self._promotions.get_active = AsyncMock(return_value={
            "name": "Mavlid Aksiyasi", "ends_at": None, "bonuses": []})
        saved = (self._promotions.promo_name, self._promotions.days_left,
                 self._promotions.promo_conditions)
        self._promotions.promo_name = lambda p, lang: p["name"]
        self._promotions.days_left = lambda p: 3
        self._promotions.promo_conditions = lambda p, lang: ""
        try:
            block = _run(ai_sales._dynamic_block("10 | Kokos uni"))
        finally:
            (self._promotions.promo_name, self._promotions.days_left,
             self._promotions.promo_conditions) = saved
        self.assertIn("Yetkazish Toshkent ichida 25 000 so'm", block)
        self.assertIn("Mavlid Aksiyasi", block)
        self.assertIn("3 kun", block)

    def test_no_promo_says_so_instead_of_leaving_room_to_invent_one(self):
        database.list_ai_facts = AsyncMock(return_value=[])
        self._promotions.get_active = AsyncMock(return_value=None)
        block = _run(ai_sales._dynamic_block("10 | Kokos uni"))
        self.assertIn("FAOL AKSIYA: hozir yo'q", block)

    def test_cart_tool_adds_the_real_near_miss_numbers(self):
        database.get_cart = AsyncMock(return_value=[
            {"product_id": 95, "name": "Eritritol 500gr", "price": 68000,
             "cart_quantity": 2, "unit": "piece", "set_id": None}])
        self._promotions.get_active = AsyncMock(return_value={"bonuses": [{
            "trigger_product_id": 95, "trigger_quantity": 3, "trigger_unit": "piece",
            "trigger_name": "Eritritol 500gr", "bonus_amount": 1, "bonus_unit": "dona",
            "bonus_name": "Eritritol 500gr", "max_bonus_amount": None}]})
        hint = _run(ai_sales._promo_hint(777))
        self.assertIn("AKSIYA:", hint)
        self.assertIn("yana 1", hint)            # 3 dan 2 si bor — 1 ta yetmaydi
        self.assertIn("bosimsiz", hint)

    def test_unanswered_question_tool_logs_for_the_admins(self):
        database.log_ai_question = AsyncMock()
        out = _run(ai_sales._run_tool(None, _FakeMessage(), "javobsiz_savol",
                                      {"savol": "Halol sertifikati bormi?"}))
        database.log_ai_question.assert_awaited_once_with("Halol sertifikati bormi?", 777)
        self.assertTrue(out.startswith("OK:"))

    def test_daily_report_line_names_model_tokens_and_dollars(self):
        lines = ai_sales.usage_lines(
            [{"model": "gpt-5.5", "provider": "openai", "requests": 142,
              "input_tokens": 912340, "cached_tokens": 701220,
              "output_tokens": 38410, "cost_usd": 2.5585}],
            {"requests": 1830, "input_tokens": 11_200_000, "output_tokens": 460_000,
             "cost_usd": 31.4})
        text = "\n".join(lines)
        for expected in ("gpt-5.5", "142 so'rov", "912.3K", "38.4K", "$2.56", "$31.40"):
            self.assertIn(expected, text)


# ─────────────────────────── provayder formatlari ───────────────────────────

class _Recorder:
    """klient.<ns>.create(**kwargs) chaqiruvlarini yozib, tayyor javob qaytaradi."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        snapshot = dict(kwargs)
        if "messages" in snapshot:
            snapshot["messages"] = list(snapshot["messages"])
        self.calls.append(snapshot)
        return self._responses.pop(0)


TOOLS = ai_sales.TOOLS


class OpenAIProviderFormatTest(unittest.TestCase):
    def _provider(self, responses):
        p = ai_provider.OpenAIProvider("sk-x", "gpt-5.5", "low")
        rec = _Recorder(responses)
        p.client = NS(responses=rec)
        return p, rec

    @staticmethod
    def _resp(rid, output, text=""):
        return NS(id=rid, output=output, output_text=text)

    def test_tool_call_round_trip_uses_function_call_output_and_chains_the_id(self):
        p, rec = self._provider([
            self._resp("resp_1", [NS(type="function_call", call_id="call_A",
                                     name="savatga_qoshish",
                                     arguments=json.dumps({"mahsulot_id": 10, "miqdor": 2}))]),
            self._resp("resp_2", [NS(type="message", content=[NS(type="output_text")])],
                       text="Savatga qo'shildi."),
        ])
        state = {}
        turn = _run(p.step(state, "QOIDALAR", "KATALOG", TOOLS, user="bodom uni 2 kg"))
        self.assertEqual(turn.calls[0].args, {"mahsulot_id": 10, "miqdor": 2})

        first = rec.calls[0]
        self.assertEqual(first["input"], [{"role": "user", "content": "bodom uni 2 kg"}])
        self.assertIn("KATALOG", first["instructions"])
        self.assertEqual(first["reasoning"], {"effort": "low"})
        self.assertNotIn("previous_response_id", first)

        turn = _run(p.step(state, "QOIDALAR", "KATALOG", TOOLS,
                           results=[ai_provider.ToolResult("call_A", "OK")]))
        second = rec.calls[1]
        self.assertEqual(second["previous_response_id"], "resp_1")
        self.assertEqual(second["input"], [
            {"type": "function_call_output", "call_id": "call_A", "output": "OK"}])
        # instructions zanjirda saqlanmaydi — har chaqiruvda qayta ketishi shart.
        self.assertIn("QOIDALAR", second["instructions"])
        self.assertEqual(turn.text, "Savatga qo'shildi.")
        self.assertEqual(state["prev_id"], "resp_2")

    def test_strict_is_dropped_for_tools_with_optional_fields(self):
        rendered = {t["name"]: t for t in ai_provider.OpenAIProvider.render_tools(TOOLS)}
        self.assertTrue(rendered["savatga_qoshish"]["strict"])
        # manzil/izoh ixtiyoriy — OpenAI strict rejimi buni 400 bilan rad etadi.
        self.assertFalse(rendered["buyurtma_rasmiylashtirish"]["strict"])
        self.assertEqual(rendered["savatga_qoshish"]["type"], "function")

    def test_refusal_is_reported(self):
        p, _ = self._provider([
            self._resp("resp_1", [NS(type="message", content=[NS(type="refusal")])])])
        self.assertTrue(_run(p.step({}, "Q", "K", TOOLS, user="...")).refused)

    def test_no_tools_key_when_tools_is_none(self):
        p, rec = self._provider([self._resp("r", [], text="salom")])
        _run(p.step({}, "Q", "K", None, user="salom"))
        self.assertNotIn("tools", rec.calls[0])

    def test_reset_drops_the_chain(self):
        state = {"prev_id": "resp_9", "turns": 3}
        ai_provider.reset(state)
        self.assertEqual(state, {})


class AnthropicProviderFormatTest(unittest.TestCase):
    def _provider(self, responses):
        p = ai_provider.AnthropicProvider("sk-ant-x", "claude-opus-5", "low")
        rec = _Recorder(responses)
        p.client = NS(messages=rec)
        return p, rec

    def test_tool_results_go_back_in_one_user_message_and_system_is_cached(self):
        p, rec = self._provider([
            NS(stop_reason="tool_use", content=[
                NS(type="tool_use", id="t1", name="savatni_korish", input={}),
                NS(type="tool_use", id="t2", name="savatni_korish", input={})]),
            NS(stop_reason="end_turn", content=[NS(type="text", text="Tayyor.")]),
        ])
        state = {}
        turn = _run(p.step(state, "QOIDALAR", "KATALOG", TOOLS, user="savat"))
        self.assertEqual([c.id for c in turn.calls], ["t1", "t2"])
        self.assertTrue(all("cache_control" in b for b in rec.calls[0]["system"]))

        _run(p.step(state, "QOIDALAR", "KATALOG", TOOLS, results=[
            ai_provider.ToolResult("t1", "a"), ai_provider.ToolResult("t2", "b", True)]))
        tool_turn = rec.calls[1]["messages"][-1]
        self.assertEqual(tool_turn["role"], "user")
        self.assertEqual([r["tool_use_id"] for r in tool_turn["content"]], ["t1", "t2"])
        self.assertTrue(tool_turn["content"][1]["is_error"])

    def test_history_is_trimmed_only_at_a_plain_user_turn(self):
        messages = [
            {"role": "user", "content": "1"},
            {"role": "assistant", "content": [NS(type="tool_use")]},
            {"role": "user", "content": [{"type": "tool_result"}]},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "2"},
            {"role": "assistant", "content": "ok"},
        ]
        ai_provider._trim_at_user_turn(messages, 4)
        # 4 ta qoldirish tool_result dan boshlanardi — u holda API 400 beradi.
        self.assertEqual(messages[0], {"role": "user", "content": "2"})


if __name__ == "__main__":
    unittest.main()
