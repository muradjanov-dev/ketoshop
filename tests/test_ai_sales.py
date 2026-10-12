"""AI sotuvchi — modelga ulanmasdan.

Ikki qatlam alohida tekshiriladi:

1. Suhbat mantiqi (ai_sales.py, ai_memory.py) — soxta provayder bilan: vosita
   to'g'ri chaqiladimi, xato is_error bo'lib ketadimi, buyurtma haqiqiy
   create_order() ga tushadimi, kimga AI javob beradi (mijoz / admin / kuryer
   / guruh), guruhda vosita umuman berilmaydimi, xotira promptga tushadimi.
2. Provayder formati (ai_provider.py) — soxta klient bilan: OpenAI Responses
   API ga to'g'ri shaklda so'rov ketadimi (function_call_output,
   previous_response_id, strict), Anthropic ga ham (bitta user xabaridagi
   tool_result lar, keshlanadigan tizim bloklari).

Test na pul sarflaydi, na tarmoqqa chiqadi, na bazaga ulanadi.
"""
import asyncio
import json
import os
import time
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-not-used")

import ai_memory
import ai_provider
import ai_sales
import database
from ai_provider import ToolCall, Turn

_SAVED_MODULE = {}


def setUpModule():
    # Xotira va sozlamalar bazaga bormasin: xotira yozuvi jim yutiladi,
    # profil bo'sh, sozlamalar keshi "yangi" (default — hammasi yoqilgan).
    _SAVED_MODULE["remember"] = ai_memory.remember
    _SAVED_MODULE["build_profile"] = ai_memory.build_profile
    ai_memory.remember = AsyncMock(return_value=True)
    ai_memory.build_profile = AsyncMock(return_value="")
    ai_sales._settings.update(at=float("inf"), values={}, staff=set())


def tearDownModule():
    ai_memory.remember = _SAVED_MODULE["remember"]
    ai_memory.build_profile = _SAVED_MODULE["build_profile"]
    ai_sales._settings.update(at=float("-inf"), values={}, staff=set())


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
                           "rules": rules, "catalog": catalog, "state": state})
        return self._turns.pop(0)


class _FakeUser:
    def __init__(self, user_id=777):
        self.id = user_id
        self.full_name = "Test Xaridor"
        self.username = "testuser"
        self.is_bot = False
        self.first_name = "Test"


class _FakeMessage:
    def __init__(self, text="salom", user_id=777, chat_type="private"):
        self.text = text
        self.from_user = _FakeUser(user_id)
        self.chat = NS(id=user_id, type=chat_type)
        self.bot = None
        self.answer = AsyncMock()


def _run(coro):
    return asyncio.run(coro)


def _settings(**values):
    """Bazasiz sozlamalar: _settings(customers="0") — mijozlarga o'chiq."""
    ai_sales._settings.update(at=float("inf"), values=dict(values), staff=set())


class _ProviderSwap(unittest.TestCase):
    """ai_sales.PROVIDER ni soxtasiga almashtirib, oxirida qaytaradi."""

    def use(self, turns):
        saved = ai_sales.PROVIDER
        self.addCleanup(setattr, ai_sales, "PROVIDER", saved)
        ai_sales.PROVIDER = _FakeProvider(turns)
        return ai_sales.PROVIDER


def _patch(test, obj, name, value):
    test.addCleanup(setattr, obj, name, getattr(obj, name))
    setattr(obj, name, value)


class AiSalesToolLoopTest(_ProviderSwap):
    def setUp(self):
        ai_sales._sessions.clear()
        ai_sales._catalog_cache = (9e18, "10 | Kokos uni 1000gr | 55 000 so'm / kg")
        self._saved = {}
        for name in ("get_product", "add_to_cart", "get_cart",
                     "get_cart_line_for_product", "remove_from_cart",
                     "create_order", "clear_cart", "get_user_language"):
            self._saved[name] = getattr(database, name)
        ai_memory.remember.reset_mock()

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
        database.get_cart_line_for_product = AsyncMock(return_value=(None, 0.0))
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
        # Savatga solingan mahsulot — mijozning qiziqishi sifatida eslab qolindi.
        ai_memory.remember.assert_awaited_with(777, "interest", "Kokos uni 1000gr", 10)

    def test_changing_the_quantity_replaces_the_line_instead_of_adding(self):
        database.get_product = AsyncMock(return_value={
            "id": 10, "name": "Kokos uni 1000gr", "unit": "kg", "quantity": 9, "is_active": 1})
        database.get_cart_line_for_product = AsyncMock(return_value=(55, 3.0))
        database.remove_from_cart = AsyncMock()
        database.add_to_cart = AsyncMock()
        out = _run(ai_sales._tool_add(777, {"mahsulot_id": 10, "miqdor": 2}))
        self.assertTrue(out.startswith("OK:"), out)
        database.remove_from_cart.assert_awaited_once_with(55)
        database.add_to_cart.assert_awaited_once_with(777, product_id=10, quantity=2.0)

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
            # Haqiqiy _build_order_summary shu kalitlarni o'qiydi — bo'lmasa
            # KeyError (2026-10-12 gacha AI buyurtmasi shu sababli yiqilardi).
            data["phone"], data["address"], data["payment_method"]
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
        self.assertEqual(kwargs["delivery_method"], "self")   # default — Toshkent kuryeri

    def test_turn_limit_stops_a_tool_loop_and_resets_the_chain(self):
        database.get_cart = AsyncMock(return_value=[])
        self.addCleanup(setattr, ai_sales, "MAX_TURNS", ai_sales.MAX_TURNS)
        ai_sales.MAX_TURNS = 3
        import handlers.cart as cart
        _patch(self, cart, "_build_order_summary", AsyncMock(return_value=(None, 0, [], 0)))
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

    def test_remember_tool_writes_feedback_to_the_customer_memory(self):
        out = _run(ai_sales._run_tool(None, _FakeMessage(), "eslab_qol", {
            "turi": "fikr", "matn": "Bodom uni — keks qildi, yoqdi", "mahsulot_id": 12}))
        self.assertTrue(out.startswith("OK:"), out)
        ai_memory.remember.assert_awaited_once_with(777, "fikr", "Bodom uni — keks qildi, yoqdi", 12)

    def test_product_info_tool_returns_the_description_and_logs_interest(self):
        database.get_product = AsyncMock(return_value={
            "id": 12, "name": "Bodom uni 500gr", "unit": "dona", "quantity": 7, "is_active": 1,
            "price": 89000, "discount_percent": 0, "discount_until": None,
            "description": "Bodomdan tortilgan <b>mayin</b> un."})
        out = _run(ai_sales._tool_info(777, {"mahsulot_id": 12}))
        self.assertIn("89 000 so'm", out)
        self.assertIn("Bodomdan tortilgan mayin un.", out)     # HTML tozalangan
        ai_memory.remember.assert_awaited_once_with(777, "interest", "Bodom uni 500gr", 12)


class AiSalesCartTotalTest(unittest.TestCase):
    """savatni_korish jami summani checkout'ning o'z hisobidan beradi."""

    def test_cart_uses_checkout_math_with_discount_gift_and_delivery_fee(self):
        items = [
            {"product_id": 10, "name": "Bodom uni 500gr", "quantity": 2, "unit": "dona",
             "price": 80100, "original_price": 89000, "discount_percent": 10, "bot_discount": 10},
            {"product_id": 95, "name": "Eritritol 100gr", "quantity": 1, "unit": "dona",
             "price": 0, "is_bonus": True, "is_gift": True},
        ]
        import gift_campaign
        import handlers.cart as cart
        import mystery_gift
        _patch(self, cart, "_build_order_summary",
               AsyncMock(return_value=("matn", 160200 + 25000, items, 0)))
        _patch(self, gift_campaign, "cart_hint", AsyncMock(return_value=""))
        _patch(self, mystery_gift, "cart_hint", lambda subtotal, lang: "")
        _patch(self, ai_sales, "_promo_hint", AsyncMock(return_value=""))

        out = _run(ai_sales._tool_cart(777))

        self.assertIn("160 200", out)                      # mahsulotlar, chegirma bilan
        self.assertIn("botdan buyurtma chegirmasi -10%", out)
        self.assertIn("SOVG'A: Eritritol 100gr", out)
        self.assertIn("yetkazish 25 000", out)
        self.assertIn("JAMI 185 200", out)

    def test_empty_cart(self):
        import handlers.cart as cart
        _patch(self, cart, "_build_order_summary", AsyncMock(return_value=(None, 0, [], 0)))
        self.assertEqual(_run(ai_sales._tool_cart(777)), "Savat bo'sh.")


class AiSalesGateTest(_ProviderSwap):
    """Kim AI ga tushadi, kim operatorga (support_relay) — FILTR darajasida."""

    def setUp(self):
        ai_sales._sessions.clear()
        ai_sales._opted_out.clear()
        ai_sales._paused.clear()
        self.use([])                       # kalit bor holat (is_enabled True)
        _patch(self, ai_sales, "ADMIN_IDS", [1])
        _patch(self, ai_sales, "AUTOSTART", True)
        _settings()

    def tearDown(self):
        ai_sales._sessions.clear()
        ai_sales._opted_out.clear()
        ai_sales._paused.clear()
        _settings()

    def gate(self, message):
        return _run(ai_sales._has_session(message))

    def test_customer_plain_text_reaches_ai_by_default(self):
        self.assertTrue(self.gate(_FakeMessage("salom")))

    def test_customers_go_to_the_operators_when_switched_off(self):
        _settings(customers="0")
        self.assertFalse(self.gate(_FakeMessage("salom")))

    def test_admin_plain_text_is_answered_only_while_the_test_switch_is_on(self):
        # Egasi, 2026-10-13: "hozircha adminlarga ham javob bersin, testlash uchun".
        self.assertTrue(self.gate(_FakeMessage("salom", user_id=1)))
        # O'chirilgach — 2026-10-12 qoidasi: "adminlar yozgan xabarga javob yozmasin".
        _settings(admins="0")
        self.assertFalse(self.gate(_FakeMessage("salom", user_id=1)))
        ai_sales._session(1)                                   # /ai bilan ochdi
        self.assertTrue(self.gate(_FakeMessage("salom", user_id=1)))

    def test_couriers_and_internal_accounts_never_get_the_ai(self):
        ai_sales._settings["staff"] = {555}
        self.assertFalse(self.gate(_FakeMessage("salom", user_id=555)))
        internal = next(iter(database.LEADERBOARD_EXCLUDED_USER_IDS))
        self.assertFalse(self.gate(_FakeMessage("salom", user_id=internal)))

    def test_paused_buyer_goes_to_the_admins_until_the_pause_ends(self):
        ai_sales.pause_for_human(777, seconds=60)
        self.assertFalse(self.gate(_FakeMessage("salom")))
        ai_sales._paused[777] = time.time() - 1                # muddat tugadi
        self.assertTrue(self.gate(_FakeMessage("salom")))

    def test_ai_off_sends_the_customer_back_to_the_operators(self):
        ai_sales._opted_out.add(777)
        self.assertFalse(self.gate(_FakeMessage("salom")))

    def test_no_key_means_everything_goes_to_the_operators(self):
        ai_sales.PROVIDER = None
        self.assertFalse(self.gate(_FakeMessage("salom")))

    def test_group_messages_never_reach_the_private_sales_handler(self):
        self.assertFalse(self.gate(_FakeMessage("salom", chat_type="supergroup")))

    def test_admin_reply_through_support_relay_pauses_the_ai(self):
        from handlers import support_relay
        ai_sales._session(777)
        support_relay._pause_ai(777)
        self.assertTrue(ai_sales._is_paused(777))
        self.assertNotIn(777, ai_sales._sessions)
        self.assertFalse(self.gate(_FakeMessage("salom")))

    def test_thanks_alone_costs_no_model_call(self):
        for text in ("rahmat", "Katta rahmat!", "спасибо", "Раҳмат 🙏"):
            self.assertTrue(ai_sales.is_thanks_only(text), text)
        # Tasdiqlash bo'lishi mumkin bo'lganlar modelga boradi.
        for text in ("ha", "ok", "xo'p", "rahmat, yana eritritol bormi?", "👍"):
            self.assertFalse(ai_sales.is_thanks_only(text), text)


class AiSalesBatchAndMirrorTest(unittest.TestCase):
    """Ketma-ket xabarlar bitta javob oladi; adminlar har javobning nusxasini ko'radi."""

    def setUp(self):
        self.addCleanup(setattr, ai_sales, "DEBOUNCE", ai_sales.DEBOUNCE)
        ai_sales.DEBOUNCE = 0.05
        ai_sales._inboxes.clear()

    def test_quick_messages_are_answered_once_together(self):
        seen = []

        async def handler(message, text):
            seen.append(text)

        async def scenario():
            message = _FakeMessage()
            first = asyncio.create_task(ai_sales._batch(("p", 777), message, "salom", handler))
            await asyncio.sleep(0.01)
            await ai_sales._batch(("p", 777), message, "eritritol bormi?", handler)
            await first

        _run(scenario())
        self.assertEqual(seen, ["salom\neritritol bormi?"])

    def test_message_arriving_mid_answer_gets_its_own_turn(self):
        seen = []

        async def scenario():
            message = _FakeMessage()

            async def handler(msg, text):
                seen.append(text)
                if len(seen) == 1:      # javob yozilayotganda yangi xabar keldi
                    await ai_sales._batch(("p", 777), msg, "narxi qancha?", handler)

            await ai_sales._batch(("p", 777), message, "bodom uni bormi?", handler)

        _run(scenario())
        self.assertEqual(seen, ["bodom uni bormi?", "narxi qancha?"])

    def test_mirror_goes_silently_to_every_admin_with_takeover_buttons(self):
        _patch(self, ai_sales, "ADMIN_IDS", [1, 2])
        _settings()
        bot = NS(send_message=AsyncMock())
        _run(ai_sales._mirror(bot, _FakeMessage("<b>salom</b>"), "<b>salom</b>", "Vaalaykum assalom!"))
        self.assertEqual(bot.send_message.await_count, 2)
        args, kwargs = bot.send_message.await_args
        self.assertIn("&lt;b&gt;salom", args[1])                  # mijoz matni xavfsiz
        self.assertIn("Vaalaykum assalom!", args[1])
        self.assertTrue(kwargs["disable_notification"])
        buttons = [b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row]
        self.assertIn("freereply:777", buttons)
        self.assertIn("aipause:777", buttons)
        self.assertIn("aimem:777", buttons)

    def test_mirror_off_and_admin_chats_send_nothing(self):
        _patch(self, ai_sales, "ADMIN_IDS", [1])
        bot = NS(send_message=AsyncMock())
        _settings(mirror="0")
        _run(ai_sales._mirror(bot, _FakeMessage(), "salom", "javob"))
        _settings()
        _run(ai_sales._mirror(bot, _FakeMessage(user_id=1), "salom", "javob"))
        bot.send_message.assert_not_awaited()

    def test_customer_texts_follow_the_buyer_language(self):
        self.assertEqual(ai_sales._t("Rahmat", "Спасибо", "ru"), "Спасибо")
        self.assertEqual(ai_sales._t("Rahmat", "Спасибо", "uz"), "Rahmat")
        self.assertNotEqual(ai_sales._t("Rahmat", "Спасибо", "uz_cyr"), "Rahmat")


class AiSalesSettingsAndModelTest(_ProviderSwap):
    def tearDown(self):
        _settings()

    def test_switches_default_to_on_and_read_the_stored_value(self):
        _settings()
        self.assertTrue(_run(ai_sales.setting("customers")))
        self.assertTrue(_run(ai_sales.setting("group")))
        _settings(group="0")
        self.assertFalse(_run(ai_sales.setting("group")))

    def test_model_choice_switches_the_model_and_drops_stale_chains(self):
        provider = self.use([])
        provider.name, provider.model = "openai", "gpt-5.5"
        _patch(self, ai_sales, "MODEL", "gpt-5.5")
        session = ai_sales._session(4321)
        session["ai"]["prev_id"] = "resp_old"
        session["awaiting_cheque"] = 99
        self.addCleanup(ai_sales._sessions.pop, 4321, None)

        self.assertIn("gpt-5.4-mini", ai_sales.model_options())
        ai_sales._apply_model("gpt-5.4-mini")

        self.assertEqual(provider.model, "gpt-5.4-mini")
        self.assertNotIn("prev_id", session["ai"])            # eski model zanjiri
        self.assertEqual(session["awaiting_cheque"], 99)       # sessiya qoldi
        ai_sales._apply_model("claude-opus-5")                 # boshqa provayder — e'tiborsiz
        self.assertEqual(provider.model, "gpt-5.4-mini")


class AiSalesFallbackAndDefaultModelTest(_ProviderSwap):
    """Model javob bera olmasa mijoz yo'qolmaydi; default — arzon gpt-5.4-mini."""

    def setUp(self):
        ai_sales._sessions.clear()

    def tearDown(self):
        ai_sales._sessions.clear()

    def test_default_openai_model_is_the_cheap_one(self):
        self.assertEqual(ai_provider.DEFAULT_MODELS["openai"], "gpt-5.4-mini")
        self.assertIsNotNone(ai_provider.price_for("gpt-5.4-mini"))

    def test_model_failure_hands_the_question_to_the_admins_not_an_apology(self):
        class _Broken:
            name, model = "openai", "gpt-5.4-mini"

            async def step(self, *args, **kwargs):
                raise RuntimeError("400 unsupported parameter")

        self.use([])
        ai_sales.PROVIDER = _Broken()
        _patch(self, ai_sales, "_dynamic_block", AsyncMock(return_value="KATALOG"))
        from handlers import support_relay
        relay = AsyncMock()
        _patch(self, support_relay, "relay_text", relay)
        message = _FakeMessage("bodom uni bormi?")
        ai_sales._session(777)["profiled"] = True

        _run(ai_sales._answer(None, message, "salom\nbodom uni bormi?"))

        relay.assert_awaited_once_with(message, None, "salom\nbodom uni bormi?")
        message.answer.assert_not_awaited()


class AiKeyCommandTest(_ProviderSwap):
    """/ai_kalit: kalit botga beriladi, tekshiriladi, xabar o'chiriladi va
    kalit hech qachon javobda yoki jurnalda to'liq ko'rinmaydi."""

    KEY = "sk-proj-test0000000000000000000000000000WXYZ"

    def setUp(self):
        self.use([])
        ai_sales.PROVIDER = None                     # serverda kalit yo'q holat
        _patch(self, ai_sales, "MODEL", "")
        _patch(self, ai_sales, "ADMIN_IDS", [1])
        self.saved_from_bot = dict(ai_sales._key_source)
        self.addCleanup(ai_sales._key_source.update, self.saved_from_bot)
        self.store = AsyncMock()
        _patch(self, ai_sales, "set_setting", self.store)
        _settings()

    def _message(self, text, chat_type="private"):
        message = _FakeMessage(text, user_id=1, chat_type=chat_type)
        message.delete = AsyncMock()
        return message

    def test_a_working_key_is_stored_applied_and_the_message_deleted(self):
        _patch(self, ai_sales, "_verify_key", AsyncMock(return_value=None))
        message = self._message(f"/ai_kalit {self.KEY}")

        _run(ai_sales.cmd_ai_key(message))

        message.delete.assert_awaited_once()
        self.store.assert_awaited_once_with("openai_key", self.KEY, 1)
        self.assertEqual(ai_sales.PROVIDER.name, "openai")
        self.assertEqual(ai_sales.PROVIDER.api_key, self.KEY)
        self.assertEqual(ai_sales.PROVIDER.model, "gpt-5.4-mini")
        reply = message.answer.await_args.args[0]
        self.assertIn("…WXYZ", reply)
        self.assertNotIn(self.KEY, reply)
        self.assertTrue(ai_sales.is_enabled())

    def test_a_rejected_key_is_not_stored(self):
        _patch(self, ai_sales, "_verify_key",
               AsyncMock(return_value="AuthenticationError: Incorrect API key"))
        message = self._message(f"/ai_kalit {self.KEY}")
        _run(ai_sales.cmd_ai_key(message))
        message.delete.assert_awaited_once()
        self.store.assert_not_awaited()
        self.assertIsNone(ai_sales.PROVIDER)

    def test_a_key_sent_in_a_group_is_deleted_and_ignored(self):
        verify = AsyncMock(return_value=None)
        _patch(self, ai_sales, "_verify_key", verify)
        message = self._message(f"/ai_kalit {self.KEY}", chat_type="supergroup")
        _run(ai_sales.cmd_ai_key(message))
        message.delete.assert_awaited_once()
        verify.assert_not_awaited()
        self.store.assert_not_awaited()

    def test_stored_key_is_picked_up_from_settings(self):
        ai_sales._apply_key(self.KEY)
        self.assertEqual(ai_sales.PROVIDER.api_key, self.KEY)
        self.assertIn("bot orqali", ai_sales._key_status())
        self.assertNotIn(self.KEY, ai_sales._key_status())


class AiUsageReportTest(unittest.TestCase):
    """Kunlik sarf hisoboti: 23:58 da bir marta, hamma adminlarga, ovozsiz."""

    def setUp(self):
        from datetime import date
        self.day = date(2026, 10, 13)
        _patch(self, ai_sales, "ADMIN_IDS", [1, 2, 1])
        self.store = AsyncMock(side_effect=lambda key, value, by=None:
                               ai_sales._settings["values"].__setitem__(key, value))
        _patch(self, ai_sales, "set_setting", self.store)
        _patch(self, ai_sales, "_usage_for_day", AsyncMock(return_value=(
            [{"model": "gpt-5.4-mini", "provider": "openai", "requests": 214,
              "input_tokens": 2_100_000, "cached_tokens": 1_900_000,
              "output_tokens": 31_200, "cost_usd": 0.42}],
            {"requests": 2300, "input_tokens": 29_000_000, "output_tokens": 1_000_000,
             "cost_usd": 6.1}, 3)))
        import targets
        _patch(self, targets, "current_usd_rate", AsyncMock(return_value=(12_800.0, "13.10.2026")))
        self.bot = NS(send_message=AsyncMock())

    def tearDown(self):
        _settings()

    def at(self, hour, minute, day=13):
        return datetime(2026, 10, day, hour, minute)

    def test_report_text_has_tokens_dollars_and_sum(self):
        text = ai_sales.usage_report_text(self.day, *_run(ai_sales._usage_for_day(self.day)), 12_800.0)
        for expected in ("13.10.2026", "$0.42", "5 376 so'm", "214 so'rov", "2.10M kirish",
                         "1.90M keshdan", "31.2K chiqish", "gpt-5.4-mini", "Oy boshidan",
                         "$6.10", "3 ta"):
            self.assertIn(expected, text)

    def test_sent_once_at_the_end_of_the_day_to_every_admin_silently(self):
        _settings(usage_report_day="2026-10-12")
        self.assertIsNone(_run(ai_sales._usage_report_tick(self.bot, self.at(20, 0))))
        self.bot.send_message.assert_not_awaited()

        self.assertEqual(_run(ai_sales._usage_report_tick(self.bot, self.at(23, 58))), self.day)
        self.assertEqual(self.bot.send_message.await_count, 2)          # takror admin bir marta
        self.assertTrue(self.bot.send_message.await_args.kwargs["disable_notification"])

        self.assertIsNone(_run(ai_sales._usage_report_tick(self.bot, self.at(23, 59))))
        self.assertEqual(self.bot.send_message.await_count, 2)          # qayta yuborilmadi

    def test_a_missed_night_is_sent_next_morning_but_not_on_first_ever_run(self):
        _settings()                                                    # hali hech qachon yuborilmagan
        self.assertIsNone(_run(ai_sales._usage_report_tick(self.bot, self.at(10, 0, day=14))))
        self.bot.send_message.assert_not_awaited()
        _settings(usage_report_day="2026-10-12")                      # 13-kechasi o'tkazib yuborildi
        self.assertEqual(_run(ai_sales._usage_report_tick(self.bot, self.at(10, 0, day=14))), self.day)
        self.bot.send_message.assert_awaited()

    def test_switched_off_report_sends_nothing(self):
        _settings(report="0", usage_report_day="2026-10-12")
        self.assertIsNone(_run(ai_sales._usage_report_tick(self.bot, self.at(23, 58))))
        self.bot.send_message.assert_not_awaited()


class AiSalesMemoryContextTest(_ProviderSwap):
    """Mijoz xotirasi suhbatning birinchi xabariga bir marta qo'shiladi."""

    def setUp(self):
        ai_sales._sessions.clear()
        ai_sales._group_context.clear()
        ai_sales._catalog_cache = (9e18, "10 | Kokos uni")
        _patch(self, ai_sales, "_dynamic_block", AsyncMock(return_value="KATALOG"))

    def tearDown(self):
        ai_sales._sessions.clear()
        ai_sales._group_context.clear()
        ai_sales._catalog_cache = None
        ai_memory.build_profile = AsyncMock(return_value="")

    def test_profile_and_group_question_open_the_conversation_once(self):
        ai_memory.build_profile = AsyncMock(return_value="[MIJOZ XOTIRASI] Bodom uni olgan")
        ai_sales._group_context[777] = (time.time(), "bodom uni bormi?", "Bor, 89 000 so'm")
        provider = self.use([Turn(text="Salom!"), Turn(text="Albatta.")])
        message = _FakeMessage()

        _run(ai_sales._respond(None, message, "salom"))
        _run(ai_sales._respond(None, message, "yana bitta savol"))

        first, second = provider.calls[0]["user"], provider.calls[1]["user"]
        self.assertIn("[MIJOZ XOTIRASI] Bodom uni olgan", first)
        self.assertIn("bodom uni bormi?", first)              # guruhdagi savoli ulandi
        self.assertTrue(first.endswith("[MIJOZ XABARI]\nsalom"))
        self.assertEqual(second, "yana bitta savol")           # ikkinchi marta yo'q
        self.assertNotIn(777, ai_sales._group_context)


class AiMemoryProfileTest(unittest.TestCase):
    """ai_memory: qaysi mahsulot haqida fikr so'raladi, profil nimani aytadi."""

    NOW = datetime(2026, 10, 12, 12, 0)

    def _order(self, oid, status, days_ago, items, delivered_days_ago=None):
        delivered = (self.NOW - timedelta(days=delivered_days_ago)
                     if delivered_days_ago is not None else None)
        return {"id": oid, "status": status, "created_at": self.NOW - timedelta(days=days_ago),
                "delivered_at": delivered, "phone": "+998901112233",
                "items": json.dumps(items)}

    def test_feedback_is_asked_for_a_delivered_product_only_once(self):
        orders = [self._order(5, "delivered", 6, [
            {"product_id": 12, "name": "Bodom uni 500gr", "quantity": 1},
            {"product_id": 95, "name": "Eritritol 100gr", "quantity": 1, "is_gift": True}],
            delivered_days_ago=4)]
        pick = ai_memory.feedback_candidate(orders, [], now=self.NOW)
        self.assertEqual(pick["product_id"], 12)               # sovg'a emas
        asked = [{"kind": "asked", "product_id": 12}]
        self.assertIsNone(ai_memory.feedback_candidate(orders, asked, now=self.NOW))

    def test_too_fresh_cancelled_or_undelivered_orders_are_skipped(self):
        line = [{"product_id": 12, "name": "Bodom uni", "quantity": 1}]
        orders = [self._order(1, "delivered", 2, line, delivered_days_ago=1),   # hali erta
                  self._order(2, "cancelled", 9, line, delivered_days_ago=8),
                  self._order(3, "shipped", 3, line)]
        self.assertIsNone(ai_memory.feedback_candidate(orders, [], now=self.NOW))

    def test_profile_names_orders_notes_last_address_and_the_feedback_ask(self):
        orders = [self._order(5, "delivered", 6, [
            {"product_id": 12, "name": "Bodom uni 500gr", "quantity": 2}], delivered_days_ago=4)]
        notes = [{"kind": "interest", "text": "keto non pishirmoqchi",
                  "created_at": self.NOW - timedelta(days=3)},
                 {"kind": "asked", "text": "x", "created_at": self.NOW}]
        feedback = ai_memory.feedback_candidate(orders, notes, now=self.NOW)
        text = ai_memory.profile_text({"full_name": "Dilnoza"}, "uz_cyr", orders, notes,
                                      {"address": "Chilonzor 9"}, feedback)
        self.assertIn("Dilnoza", text)
        self.assertIn("KIRILL", text)
        self.assertIn("#5 (yetkazilgan", text)
        self.assertIn("Bodom uni 500gr ×2", text)
        self.assertIn("keto non pishirmoqchi", text)
        self.assertIn("Chilonzor 9", text)
        self.assertIn("+998901112233", text)
        self.assertIn("FIKR SO'RA", text)
        self.assertNotIn("· asked", text)                       # ichki belgi ko'rinmaydi

    def test_new_customer_profile_says_so(self):
        text = ai_memory.profile_text(None, "uz", [], [], None, None)
        self.assertIn("yangi mijoz", text)
        self.assertNotIn("FIKR SO'RA", text)


    def test_a_product_already_rated_in_the_bot_is_not_asked_again(self):
        orders = [self._order(5, "delivered", 6, [
            {"product_id": 12, "name": "Bodom uni 500gr", "quantity": 1}], delivered_days_ago=4)]
        self.assertIsNone(ai_memory.feedback_candidate(orders, [], now=self.NOW, reviewed={12}))
        text = ai_memory.profile_text(None, "uz", orders, [], None, None, reviews=[
            {"product_id": 12, "name": "Bodom uni 500gr", "rating": 5, "comment": "zo'r keks chiqdi"}])
        self.assertIn("Bodom uni 500gr ★5 «zo'r keks chiqdi»", text)


class AiSalesLocationAndPaymentTest(unittest.TestCase):
    """Lokatsiya manzil bo'lib tushadimi, karta tanlansa nima qaytadi."""

    def setUp(self):
        ai_sales._sessions.clear()
        self._saved = {n: getattr(database, n) for n in
                       ("create_order", "clear_cart", "get_user_language")}
        self._items = [{"product_id": 10, "name": "Kokos uni", "quantity": 2,
                        "price": 55000, "unit": "kg", "seller_id": 1}]

    def tearDown(self):
        for name, fn in self._saved.items():
            setattr(database, name, fn)
        ai_sales._sessions.clear()

    def _order(self, tool_input, location=None):
        """Buyurtma vositasini bir marta ishga tushiradi va (javob, create_order
        kwargs, adminlarga ketgan ma'lumot) ni qaytaradi."""
        items = self._items

        async def fake_summary(user_id, data, lang):
            data["phone"], data["address"], data["payment_method"]
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
        kwargs = database.create_order.await_args.kwargs if database.create_order.await_count else None
        return result, kwargs, notified

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
        self.assertIn("24 soat", result)

    def test_typed_address_and_location_are_both_kept(self):
        _, kwargs, _ = self._order(
            {"ism": "Dilnoza", "telefon": "+998901234567", "manzil": "3-uy, 12-xonadon",
             "tolov_turi": "naqd"},
            location=(41.3, 69.2, "📍 41.300000, 69.200000"),
        )
        self.assertIn("41.300000", kwargs["address"])
        self.assertIn("3-uy, 12-xonadon", kwargs["address"])

    def test_no_address_and_no_location_is_an_error_not_an_order(self):
        result, kwargs, _ = self._order(
            {"ism": "Dilnoza", "telefon": "+998901234567", "tolov_turi": "naqd"})
        self.assertTrue(result.startswith("Xato:"), result)
        self.assertIsNone(kwargs)

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

    def test_regional_post_is_card_only(self):
        result, kwargs, _ = self._order(
            {"ism": "Aziz", "telefon": "+998901234567", "manzil": "Samarqand, Registon 5",
             "yetkazish": "bts", "tolov_turi": "naqd"})
        self.assertTrue(result.startswith("Xato:"), result)
        self.assertIsNone(kwargs)
        result, kwargs, _ = self._order(
            {"ism": "Aziz", "telefon": "+998901234567", "manzil": "Samarqand, Registon 5",
             "yetkazish": "bts", "tolov_turi": "karta"})
        self.assertTrue(result.startswith("OK:"), result)
        self.assertEqual(kwargs["delivery_method"], "bts")

    def test_tashkent_courier_refuses_a_location_outside_tashkent(self):
        result, kwargs, _ = self._order(
            {"ism": "Aziz", "telefon": "+998901234567", "tolov_turi": "naqd"},
            location=(39.654, 66.975, "📍 Samarqand"))
        self.assertTrue(result.startswith("Xato:"), result)
        self.assertIn("BTS", result)
        self.assertIsNone(kwargs)


class AiGroupModeTest(_ProviderSwap):
    """Guruhda: faqat begona odamning savoliga, adminlarga hech qachon,
    va sotuv vositasi umuman yo'q."""

    CHAT = -1001234567890

    def setUp(self):
        ai_sales._group_calls.clear()
        ai_sales._group_context.clear()
        _patch(self, ai_sales, "GROUP_CHATS", {self.CHAT})
        _patch(self, ai_sales, "CHANNEL_GROUP", False)
        _patch(self, ai_sales, "ADMIN_IDS", [1])
        import link_guard
        self.privileged = AsyncMock(return_value=False)
        _patch(self, link_guard, "is_privileged", self.privileged)
        _settings()
        self.use([])
        ai_sales._catalog_cache = (9e18, "10 | Kokos uni 1000gr | 55 000 so'm / kg")

    def tearDown(self):
        ai_sales._group_calls.clear()
        ai_sales._group_context.clear()
        ai_sales._catalog_cache = None
        _settings()

    def _msg(self, text, chat_id=CHAT, user_id=42, reply=None, sender_chat=None):
        return NS(text=text, caption=None, chat=NS(id=chat_id, type="supergroup"),
                  from_user=NS(id=user_id, username="aziz", is_bot=False, first_name="Aziz"),
                  reply_to_message=reply, sender_chat=sender_chat, reply=AsyncMock())

    def trigger(self, message):
        return _run(ai_sales._group_trigger(message, None))

    def test_a_customer_question_is_answered_without_a_mention(self):
        self.assertTrue(self.trigger(self._msg("Bodom uni bormi?")))
        self.assertTrue(self.trigger(self._msg("eritritol narxi qancha")))
        self.assertTrue(self.trigger(self._msg("Сколько стоит доставка")))

    def test_chatter_that_is_not_a_question_costs_nothing(self):
        for text in ("bugun havo issiq ekan", "+", "👍", "Zo'r post!", "rahmat"):
            self.assertFalse(self.trigger(self._msg(text)), text)

    def test_admins_are_never_answered_in_the_group_even_with_the_test_switch_on(self):
        # Egasi, 2026-10-13: "guruhda adminlar yozsa umuman javob berma" —
        # "Adminlarga ham javob (sinov)" faqat botdagi shaxsiy chatga tegishli.
        _settings(admins="1")
        other = NS(from_user=NS(id=43, is_bot=False, username="olim"),
                   is_automatic_forward=False, sender_chat=None)
        self.assertFalse(self.trigger(self._msg("narxi qancha?", user_id=1)))
        self.assertFalse(self.trigger(self._msg("bormi?", user_id=1, reply=other)))
        self.privileged.return_value = True                    # guruh admini
        self.assertFalse(self.trigger(self._msg("narxi qancha?")))
        self.privileged.return_value = False
        _settings()

    def test_admins_are_never_answered_when_the_test_switch_is_off(self):
        _settings(admins="0")
        self.assertFalse(self.trigger(self._msg("narxi qancha?", user_id=1)))
        self.assertFalse(self.trigger(self._msg(f"@{ai_sales.BOT_USERNAME} bormi?", user_id=1)))
        internal = next(iter(database.LEADERBOARD_EXCLUDED_USER_IDS))
        self.assertFalse(self.trigger(self._msg("narxi qancha?", user_id=internal)))
        self.privileged.return_value = True                    # guruh admini
        self.assertFalse(self.trigger(self._msg("narxi qancha?")))

    def test_people_talking_to_each_other_are_left_alone(self):
        other = NS(from_user=NS(id=43, is_bot=False, username="olim"),
                   is_automatic_forward=False, sender_chat=None)
        self.assertFalse(self.trigger(self._msg("sizda bormi?", reply=other)))

    def test_a_comment_under_a_channel_post_is_answered(self):
        post = NS(is_automatic_forward=True, sender_chat=NS(type="channel"),
                  from_user=None, text="Yangi: Bodom uni 500gr", caption=None)
        self.assertTrue(self.trigger(self._msg("narxi qancha?", reply=post)))

    def test_a_mention_or_reply_to_the_bot_skips_the_question_check(self):
        bot_msg = NS(from_user=NS(id=9, is_bot=True, username=ai_sales.BOT_USERNAME),
                     is_automatic_forward=False, sender_chat=None, text="Bor, 89 000 so'm")
        self.assertTrue(self.trigger(self._msg("yaxshi, olaman", reply=bot_msg)))
        self.assertTrue(self.trigger(self._msg(f"@{ai_sales.BOT_USERNAME} salom")))

    def test_channel_posts_other_groups_switch_and_budget_block_it(self):
        self.assertFalse(self.trigger(self._msg("narxi?", sender_chat=NS(id=-100, type="channel"))))
        self.assertFalse(self.trigger(self._msg("narxi?", chat_id=-100999)))
        _settings(group="0")
        self.assertFalse(self.trigger(self._msg("narxi?")))
        _settings()
        ai_sales._group_calls[self.CHAT] = [time.time()] * ai_sales.GROUP_MAX_PER_HOUR
        self.assertFalse(self.trigger(self._msg("narxi?")))

    def test_group_answer_carries_no_tools_and_no_chain(self):
        provider = self.use([Turn(text="Bodom uni bor, buyurtma uchun botga yozing.")])
        reply = _run(ai_sales._group_respond(self.CHAT, "Aziz", "bodom uni bormi?"))
        self.assertIn("botga", reply)
        self.assertIsNone(provider.calls[0]["tools"])     # guruhda savat/buyurtma yo'q
        self.assertEqual(provider.calls[0]["state"], {})  # zanjirsiz — tarix to'lanmaydi
        self.assertIn("SOTUV JOYI EMAS", provider.calls[0]["rules"])

    def test_skip_means_silence(self):
        self.use([Turn(text="SKIP")])
        self.assertEqual(_run(ai_sales._group_respond(self.CHAT, "Aziz", "zo'r")), "")

    def test_answer_quotes_the_post_and_carries_over_to_the_bot(self):
        provider = self.use([Turn(text="89 000 so'm. Buyurtma uchun @ketoshopbot ga yozing.")])
        post = NS(is_automatic_forward=True, sender_chat=NS(type="channel"),
                  from_user=None, text="Yangi: Bodom uni 500gr", caption=None)
        message = self._msg("narxi qancha?", reply=post)
        _run(ai_sales._group_answer(None, message, "narxi qancha?"))
        self.assertIn("Yangi: Bodom uni 500gr", provider.calls[0]["user"])
        message.reply.assert_awaited_once()
        self.assertIn(42, ai_sales._group_context)


class AiUsagePromoKnowledgeTest(_ProviderSwap):
    """Sarf bazaga $ bilan yoziladi, aksiya faqat haqiqiy hisobdan aytiladi,
    o'rgatilgan bilim promptga tushadi, javobsiz savol yozib qo'yiladi."""

    def setUp(self):
        ai_sales._sessions.clear()
        ai_sales._catalog_cache = (9e18, "10 | Kokos uni 1000gr | 55 000 so'm / kg")
        ai_sales.invalidate_knowledge()
        self._saved = {n: getattr(database, n) for n in (
            "record_ai_usage", "list_ai_facts", "log_ai_question", "get_cart")}
        import bot_discount
        import promotions
        self._promotions = promotions
        self._saved_active = promotions.get_active
        _patch(self, bot_discount, "is_active", AsyncMock(return_value=False))

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
            "name": "Mavlid Aksiyasi", "ends_at": "2026-10-15T00:00:00", "bonuses": []})
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

    def test_shop_address_link_and_landmark_reach_bot_and_group(self):
        for rules in (ai_sales._sales_rules(), ai_sales._group_rules()):
            self.assertIn("https://t.me/ketoshop_uz/1071", rules)
            self.assertIn("Ko'kcha masjidi ro'parasi", rules)
        for text in ("manzilingiz qayerda", "адрес магазина", "Do'kon lokatsiyasi"):
            self.assertTrue(ai_sales.looks_like_question(text), text)

    def test_rules_carry_keto_knowledge_delivery_terms_and_brevity(self):
        rules = ai_sales._sales_rules()
        for expected in ("KETO VA PP BILIMLARI", "YETKAZISH VA TO'LOV", "800 000",
                         "MIJOZ XOTIRASI", "eslab_qol", "QISQA, lekin QURUQ EMAS", "BTS",
                         "MIJOZ TOMONIDAN O'YLA", "ENG MOSINI", "'Qaysi biri kerak?'",
                         "Savatga qo'shamizmi? 🛒", "1-2 ta muloyim emoji", "MAKSIMAL ODOB"):
            self.assertIn(expected, rules)
        for expected in ("MAKSIMAL ODOB", "muloyim emoji"):
            self.assertIn(expected, ai_sales._group_rules())
        self.assertIn("SKIP", ai_sales._group_rules())

    def test_catalog_has_no_exact_stock_so_the_prompt_cache_survives_orders(self):
        ai_sales._catalog_cache = None
        _patch(self, database, "get_all_products_paginated", AsyncMock(return_value=([
            {"id": 12, "name": "Bodom uni 500gr", "price": 89000, "unit": "dona", "quantity": 14,
             "category": "unlar", "discount_percent": 0, "discount_until": None},
            {"id": 13, "name": "Kokos uni 1000gr", "price": 55000, "unit": "kg", "quantity": 2,
             "category": "unlar", "discount_percent": 0, "discount_until": None},
            {"id": 14, "name": "Tugagan narsa", "price": 1000, "unit": "dona", "quantity": 0,
             "category": "unlar", "discount_percent": 0, "discount_until": None},
        ], 3)))
        _patch(self, database, "get_categories",
               AsyncMock(return_value=[{"key": "unlar", "name_uz": "Keto unlar"}]))
        _patch(self, database, "get_active_sets_for_catalog", AsyncMock(return_value=[
            {"id": 3, "name": "Keto pishiriq seti", "set_price": 150000, "original_total": 170000,
             "items": [{"name": "Bodom uni 500gr", "quantity": 1}]}]))
        text = _run(ai_sales._catalog_text())
        self.assertIn("# Keto unlar", text)
        self.assertIn("12 | Bodom uni 500gr | 89 000 so'm / dona", text)
        self.assertIn("kam qoldi", text)                    # 2 < chegara
        self.assertNotIn("qoldiq", text)                     # aniq son yo'q
        self.assertNotIn("Tugagan narsa", text)
        self.assertIn("S3 | Keto pishiriq seti | 150 000 so'm (alohida olsa 170 000 so'm)", text)
        # Barqaror bloklar (oilalar, setlar) mahsulotlardan oldin — kesh uchun.
        self.assertLess(text.index("SETLAR"), text.index("MAHSULOTLAR"))


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
