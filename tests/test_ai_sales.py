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
    _SAVED_MODULE["record_ai_order"] = ai_sales.record_ai_order
    ai_sales.record_ai_order = AsyncMock()
    ai_sales._settings.update(at=float("inf"), values={}, staff=set())


def tearDownModule():
    ai_memory.remember = _SAVED_MODULE["remember"]
    ai_memory.build_profile = _SAVED_MODULE["build_profile"]
    ai_sales.record_ai_order = _SAVED_MODULE["record_ai_order"]
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
            ai_sales._session(message.from_user.id)["summary_turn"] = 0   # jami oldin ko'rsatilgan
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


class AiRecipeLimitTest(unittest.TestCase):
    """Retsept: bitta mijozga bitta mahsulot bo'yicha 24 soatda bitta, cheklov
    mijozga aytilmaydi; do'kon kutubxonasidagi retsept birinchi."""

    def setUp(self):
        _patch(self, database, "get_product", AsyncMock(return_value={
            "id": 12, "name": "Bodom uni 500gr", "is_active": 1}))
        self.recent = AsyncMock(return_value=False)
        self.record = AsyncMock()
        _patch(self, ai_memory, "recipe_given_recently", self.recent)
        _patch(self, ai_memory, "record_recipe", self.record)

    def test_first_request_gets_the_shop_recipe_and_is_recorded(self):
        out = _run(ai_sales._run_tool(None, _FakeMessage(), "retsept", {"mahsulot_id": 12}))
        self.assertTrue(out.startswith("OK:"), out)
        self.assertIn("Masalliqlar:", out)                  # kutubxonadagi bodom noni
        self.assertIn("Bodom uni", out)
        self.recent.assert_awaited_once_with(777, 12, 24)
        self.record.assert_awaited_once_with(777, 12, "Bodom uni 500gr")

    def test_second_request_within_a_day_is_refused_without_naming_the_rule(self):
        self.recent.return_value = True
        out = _run(ai_sales._run_tool(None, _FakeMessage(), "retsept", {"mahsulot_id": 12}))
        self.assertTrue(out.startswith("RAD:"), out)
        self.assertIn("GAPIRMA", out)
        self.record.assert_not_awaited()

    def test_a_product_without_a_library_recipe_lets_the_model_write_one(self):
        database.get_product = AsyncMock(return_value={
            "id": 30, "name": "Steviya 50gr", "is_active": 1})
        out = _run(ai_sales._run_tool(None, _FakeMessage(), "retsept", {"mahsulot_id": 30}))
        self.assertTrue(out.startswith("OK:"), out)
        self.assertNotIn("Masalliqlar:", out)
        self.assertIn("BITTA qisqa retsept", out)

    def test_rules_route_recipes_through_the_tool_and_the_group_to_the_bot(self):
        rules = ai_sales._sales_rules()
        self.assertIn("RETSEPT", rules)
        self.assertIn("har bir mahsulotga bitta' haqida AYTMA", rules)
        self.assertIn("Retseptni @", ai_sales._group_rules())
        self.assertTrue(ai_sales.looks_like_question("retsept bering"))
        self.assertTrue(ai_sales.looks_like_question("рецепт есть"))


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

    def test_someone_inside_a_bot_form_is_never_answered_by_the_ai(self):
        # Egasi, 2026-10-13: "↩️ Javob berish" dan keyin yozgan javobini AI ushlab,
        # mijozga emas, adminning o'ziga javob berdi.
        typing_reply = NS(get_state=AsyncMock(return_value="SupportReplyStates:waiting_text"))
        idle = NS(get_state=AsyncMock(return_value=None))
        admin_text = _FakeMessage("Ha in shaa ALLOH, bugun yetkazib beramiz", user_id=1)
        self.assertFalse(_run(ai_sales._has_session(admin_text, typing_reply)))
        self.assertTrue(_run(ai_sales._has_session(admin_text, idle)))       # sinov tugmasi yoqilgan
        ai_sales._session(777)
        self.assertFalse(_run(ai_sales._has_session(_FakeMessage("salom"), typing_reply)))
        self.assertTrue(_run(ai_sales._has_session(_FakeMessage("salom"), idle)))

    def test_mixed_script_words_are_fixed_before_sending(self):
        fix = ai_sales.fix_mixed_script
        self.assertEqual(fix("Ha, in shaa ALLOH, shahар ichida 1 kun ichida yetkazib beramiz 😊"),
                         "Ha, in shaa ALLOH, shahar ichida 1 kun ichida yetkazib beramiz 😊")
        self.assertEqual(fix("Ҳа, шаҳar ичида етказиб берамиз"), "Ҳа, шаҳар ичида етказиб берамиз")
        # Brend kirill matnda lotincha qoladi; toza matnlarga tegilmaydi.
        self.assertEqual(fix("Ассалому алайкум, Keto shopга хуш келибсиз!"),
                         "Ассалому алайкум, Keto shopга хуш келибсиз!")
        self.assertEqual(fix("Bodom uni — 89 000 so'm"), "Bodom uni — 89 000 so'm")
        self.assertEqual(fix("Миндальная мука — 89 000 сум"), "Миндальная мука — 89 000 сум")

    def test_saved_address_and_phone_are_shown_when_confirming(self):
        rules = ai_sales._sales_rules()
        self.assertIn("'📍 Manzil: …' / '📞 Raqam: …'", rules)
        self.assertIn("ARALASHTIRMA", rules)
        text = ai_memory.profile_text(None, "uz", [{"id": 1, "status": "delivered", "phone": "+998901112233",
                                                     "items": "[]"}], [],
                                      {"address": "Chilonzor 9"}, None)
        self.assertIn("'📍 Manzil: …', '📞 Raqam: …'", text)

    def test_reply_is_polished_before_sending(self):
        polish = ai_sales.polish_reply
        # O'zbekcha kirill javobda lotin qoldiqlar (mahsulot nomi, so'm) — kirillga.
        out = polish("Ҳа, албатта бор 😊\n• Eritritol 500gr — 68 000 so'm", "uz_cyr")
        self.assertNotRegex(out, r"[A-Za-z]")
        self.assertIn("сўм", out)
        # Ruscha javobda so'm — сум, qolgani o'zgarmaydi.
        self.assertEqual(polish("Миндальная мука — 89 000 so'm"), "Миндальная мука — 89 000 сум")
        # Tugma nomlari matndan olib tashlanadi.
        out = polish("Iltimos, pastdagi tugmani bosing.\n\n📍 Lokatsiyani yuborish\n📞 Raqamni yuborish")
        self.assertEqual(out, "Iltimos, pastdagi tugmani bosing.")
        # Mo'ljal aytilib havola unutilsa — havola qo'shiladi; bor bo'lsa ikkinchi marta emas.
        out = polish("Do'konimiz: Toshkent shahri, Ko'kcha masjidi ro'parasi.")
        self.assertIn("https://t.me/ketoshop_uz/1071", out)
        self.assertEqual(polish(out).count("https://t.me/ketoshop_uz/1071"), 1)
        # Lotin javobga tegilmaydi.
        self.assertEqual(polish("Bodom uni — 89 000 so'm 😊"), "Bodom uni — 89 000 so'm 😊")

    def test_reply_script_follows_the_customer_message(self):
        polish = ai_sales.polish_reply
        out = polish("Албатта, аввалги бодом уни билан нон ретсептини берган эдик 😊", "uz",
                     customer_text="yana boshqa bodom uni retsepti bering")
        self.assertNotRegex(out, r"[\u0400-\u04FF]")
        out = polish("Ha, albatta bor 😊 Eritritol 500gr — 68 000 so'm", "uz",
                     customer_text="эритритол борми? нархи қанча?")
        self.assertNotRegex(out, r"[A-Za-z]")
        out = polish("Psillium uni 300gr — 125 000 so'm 😊\n\nСаватга қўшамизми? 🛒", "uz",
                     customer_text="pishiriq uchun kerak")
        self.assertIn("Savatga qo'shamizmi? 🛒", out)
        self.assertNotRegex(out, r"[\u0400-\u04FF]")
        # Ruscha mijozga ruscha javob o'zgarmaydi; lokatsiya belgisi yozuvni belgilamaydi.
        self.assertEqual(polish("Да, есть 😊", "ru", customer_text="Есть миндальная мука?"), "Да, есть 😊")
        self.assertEqual(polish("Rahmat 😊", "uz", customer_text="[Mijoz telefon raqamini yubordi: +998]"),
                         "Rahmat 😊")

    def test_customer_is_never_addressed_by_name(self):
        strip = ai_sales.strip_name_address
        names = {"Bobur"}
        self.assertEqual(strip("Rahmat, Bobur 😊", names), "Rahmat 😊")
        self.assertEqual(strip("Xaridingiz uchun katta rahmat, Bobur!", names),
                         "Xaridingiz uchun katta rahmat!")
        self.assertEqual(strip("Bobur, buyurtmangiz tayyor 😊", names), "Buyurtmangiz tayyor 😊")
        self.assertEqual(strip("Ajoyib 😊 Bobur, endi manzil kerak.", names),
                         "Ajoyib 😊 Endi manzil kerak.")
        self.assertEqual(strip("Hurmatli Bobur, rahmat", names), "Rahmat")
        self.assertEqual(strip("Sizga, hurmatli Bobur aka, rahmat", names), "Sizga, rahmat")
        self.assertEqual(strip("Rahmat, Dilnoza opa 😊", {"Dilnoza"}), "Rahmat 😊")
        self.assertEqual(strip("• Ism: Bobur\n• Mijoz: Bobur, +998935551122", names),
                         "• Ism: Bobur\n• Mijoz: Bobur, +998935551122")   # ma'lumot qatori
        self.assertEqual(strip("Раҳмат, Шоира 😊", {"Шоира"}), "Раҳмат 😊")
        # Ism qayerdan olinadi: Telegram, yozishma, buyurtma.
        user = NS(first_name="Dilnoza", full_name="Dilnoza Karimova")
        found = ai_sales.customer_names(user, "mayli karta. Ism Bobur, raqam +998935551122")
        self.assertTrue({"Dilnoza", "Karimova", "Bobur"} <= found)
        self.assertIn("ISMI BILAN MUROJAAT QILMA", ai_sales._sales_rules())

    def test_thanks_are_said_as_sizga_rahmat(self):
        thank = ai_sales.thank_politely
        self.assertEqual(thank("Rahmat 😊"), "Sizga rahmat 😊")
        self.assertEqual(thank("Katta rahmat! Buyurtma qabul qilindi."), "Sizga katta rahmat! Buyurtma qabul qilindi.")
        self.assertEqual(thank("Manzil yozildi. Rahmat, endi to'lov."), "Manzil yozildi. Sizga rahmat, endi to'lov.")
        self.assertEqual(thank("Xaridingiz uchun katta rahmat!"), "Xaridingiz uchun katta rahmat!")
        self.assertEqual(thank("Sizga rahmat 😊"), "Sizga rahmat 😊")
        self.assertEqual(thank("Раҳмат 😊"), "Сизга раҳмат 😊")
        # Ism olib tashlangach ham: "Rahmat, Bobur 😊" -> "Sizga rahmat 😊".
        self.assertEqual(thank(ai_sales.strip_name_address("Rahmat, Bobur 😊", {"Bobur"})), "Sizga rahmat 😊")
        self.assertIn("'Sizga rahmat'", ai_sales._sales_rules())

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

    def test_without_a_topic_the_mirror_falls_back_to_every_admin(self):
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


class AiChatLogTopicTest(unittest.TestCase):
    """Mijozlar suhbatlari mavzusi: bitta mijoz — bitta xabar, tahrirlab
    qo'shiladi; limit to'lsa yoki 1 soat jimlikdan keyin — yangi xabar."""

    CHAT, THREAD = -1004478720239, 777001

    def setUp(self):
        ai_sales._chat_logs.clear()
        _patch(self, ai_sales, "ADMIN_IDS", [1])
        _settings(log_chat=str(self.CHAT), log_thread=str(self.THREAD))
        self.sent_ids = iter(range(100, 200))
        self.bot = NS(send_message=AsyncMock(side_effect=lambda *a, **k: NS(message_id=next(self.sent_ids))),
                      edit_message_text=AsyncMock())

    def tearDown(self):
        ai_sales._chat_logs.clear()
        _settings()

    def say(self, user_text, reply, user_id=777):
        _run(ai_sales._mirror(self.bot, _FakeMessage(user_text, user_id=user_id), user_text, reply))

    def test_one_conversation_is_one_message_edited_as_it_grows(self):
        self.say("psillium bormi", "Ha, albatta bor 😊")
        self.say("narxi qancha", "125 000 so'm 🌿")

        self.bot.send_message.assert_awaited_once()
        args, kwargs = self.bot.send_message.await_args
        self.assertEqual(args[0], self.CHAT)
        self.assertEqual(kwargs["message_thread_id"], self.THREAD)
        self.assertTrue(kwargs["disable_notification"])
        edit = self.bot.edit_message_text.await_args.kwargs
        self.assertEqual(edit["message_id"], 100)
        self.assertIn("psillium bormi", edit["text"])
        self.assertIn("125 000 so'm", edit["text"])
        buttons = [b.callback_data for row in edit["reply_markup"].inline_keyboard for b in row]
        self.assertIn("freereply:777", buttons)

    def test_an_hour_of_silence_starts_a_new_message(self):
        self.say("salom", "Vaalaykum assalom! 😊")
        ai_sales._chat_logs[777]["last"] -= ai_sales.LOG_NEW_AFTER + 1
        self.say("yana men", "Xush kelibsiz! 🌿")
        self.assertEqual(self.bot.send_message.await_count, 2)
        self.bot.edit_message_text.assert_not_awaited()

    def test_a_full_message_continues_in_the_next_one(self):
        self.say("salom", "x" * 1400)
        self.say("yana", "y" * 1400)
        self.say("yana", "z" * 1400)                         # 3800 dan oshadi
        self.assertEqual(self.bot.send_message.await_count, 2)
        self.assertIn("davomi 2", self.bot.send_message.await_args.args[1])

    def test_each_customer_has_their_own_message(self):
        self.say("salom", "Assalomu alaykum 😊", user_id=777)
        self.say("salom", "Assalomu alaykum 😊", user_id=888)
        self.assertEqual(self.bot.send_message.await_count, 2)

    def test_admin_replies_land_in_the_same_conversation(self):
        _patch(self, database, "get_user", AsyncMock(return_value={"full_name": "Test Xaridor"}))
        self.say("salom", "Assalomu alaykum 😊")
        _run(ai_sales.log_admin_reply(self.bot, 777, "@admin", "Men yordam beraman"))
        self.assertIn("👨‍💼 <b>@admin</b>: Men yordam beraman",
                      self.bot.edit_message_text.await_args.kwargs["text"])

    def test_ai_topic_command_binds_the_topic_it_is_typed_in(self):
        _patch(self, ai_sales, "OWNER_IDS", {1})
        store = AsyncMock()
        _patch(self, ai_sales, "set_setting", store)
        message = _FakeMessage("/ai_mavzu", user_id=1, chat_type="supergroup")
        message.chat = NS(id=self.CHAT, type="supergroup")
        message.sender_chat, message.is_topic_message, message.message_thread_id = None, True, 4242
        message.delete = AsyncMock()
        bot = NS(send_message=AsyncMock())
        _run(ai_sales.cmd_ai_topic(message, bot))
        store.assert_any_await("log_chat", str(self.CHAT), 1)
        store.assert_any_await("log_thread", "4242", 1)
        message.delete.assert_awaited_once()
        self.assertEqual(bot.send_message.await_args.kwargs["message_thread_id"], 4242)


class AiChequeTest(unittest.TestCase):
    """Chek AI sessiyasiga bog'liq emas: bot qayta ishga tushsa ham karta
    buyurtmasiga biriktiriladi (egasi, 2026-10-13: "chekni qabul qilmadi")."""

    def setUp(self):
        ai_sales._sessions.clear()
        ai_sales._paused.clear()
        _patch(self, ai_sales, "ADMIN_IDS", [1])
        _settings()
        self.now = datetime.utcnow()
        self.orders = []
        _patch(self, database, "get_user_orders", AsyncMock(side_effect=lambda uid: self.orders))
        self.attach = AsyncMock()
        _patch(self, database, "set_order_cheque", self.attach)
        import handlers.cart as cart
        self.forward = AsyncMock()
        _patch(self, cart, "_forward_cheque_to_admins", self.forward)

    def tearDown(self):
        ai_sales._sessions.clear()
        ai_sales._paused.clear()
        _settings()

    def _order(self, **kw):
        order = {"id": 4242, "created_at": self.now - timedelta(hours=1), "status": "pending",
                 "payment_method": "cash", "address_note": "To'lov: KARTA (chek kutilmoqda)",
                 "cheque_file_id": None}
        order.update(kw)
        return order

    def _photo(self, user_id=777):
        message = _FakeMessage(None, user_id=user_id)
        message.photo = [NS(file_id="small"), NS(file_id="big")]
        message.document = None
        message.forward = AsyncMock()
        return message

    def test_card_order_cheque_is_attached_even_after_a_restart(self):
        self.orders = [self._order()]
        message = self._photo()                              # sessiya yo'q — bot qayta ishga tushgan
        data = _run(ai_sales._cheque_filter(message))
        self.assertEqual(data, {"cheque_order": 4242})

        _run(ai_sales.on_cheque(message, None, **data))

        self.attach.assert_awaited_once_with(4242, "big", "photo")
        self.forward.assert_awaited_once()
        self.assertEqual(self.forward.await_args.args[1], 4242)
        self.assertIn("#4242", message.answer.await_args.args[0])

    def test_a_photo_sent_inside_a_bot_form_belongs_to_that_form(self):
        self.orders = [self._order()]
        in_form = NS(get_state=AsyncMock(return_value="SomeAdminForm:waiting_photo"))
        self.assertFalse(_run(ai_sales._cheque_filter(self._photo(), in_form)))

    def test_paused_ai_does_not_lose_the_cheque(self):
        self.orders = [self._order()]
        ai_sales.pause_for_human(777, seconds=600)
        self.assertEqual(_run(ai_sales._cheque_filter(self._photo())), {"cheque_order": 4242})

    def test_cash_old_paid_or_closed_orders_are_not_cheque_targets(self):
        for order in (self._order(address_note=None),                       # naqd
                      self._order(created_at=self.now - timedelta(days=4)),  # eski
                      self._order(payment_method="online"),
                      self._order(cheque_file_id="already"),
                      self._order(status="delivered"),
                      self._order(status="cancelled")):
            self.orders = [order]
            self.assertFalse(_run(ai_sales._cheque_filter(self._photo())), order)

    def test_admin_photos_and_plain_text_are_not_cheques(self):
        self.orders = [self._order()]
        self.assertFalse(_run(ai_sales._cheque_filter(self._photo(user_id=1))))
        text = _FakeMessage("salom")
        text.photo, text.document = None, None
        self.assertFalse(_run(ai_sales._cheque_filter(text)))

    def test_pdf_receipt_counts_but_other_files_do_not(self):
        self.orders = [self._order()]
        pdf = self._photo()
        pdf.photo, pdf.document = None, NS(file_id="doc", mime_type="application/pdf")
        self.assertEqual(_run(ai_sales._cheque_filter(pdf)), {"cheque_order": 4242})
        zip_file = self._photo()
        zip_file.photo, zip_file.document = None, NS(file_id="z", mime_type="application/zip")
        self.assertFalse(_run(ai_sales._cheque_filter(zip_file)))

    def test_unlinked_receipt_in_an_open_conversation_goes_to_the_admins(self):
        ai_sales._session(777)
        message = self._photo()
        data = _run(ai_sales._cheque_filter(message))
        self.assertEqual(data, {"cheque_order": None})
        bot = NS(send_message=AsyncMock())
        _run(ai_sales.on_cheque(message, bot, **data))
        message.forward.assert_awaited_once_with(1)
        self.assertIn("bog'lanmagan", bot.send_message.await_args.args[1])
        self.attach.assert_not_awaited()


class AiLocationButtonTest(unittest.TestCase):
    """Manzil so'ralganda — '📍 Lokatsiyani yuborish' tugmasi, keyin menyu qaytadi."""

    def setUp(self):
        ai_sales._sessions.clear()

    def tearDown(self):
        ai_sales._sessions.clear()

    def test_location_and_phone_buttons_then_the_menu_comes_back(self):
        out = _run(ai_sales._run_tool(None, _FakeMessage(), "lokatsiya_tugmasi", {}))
        self.assertTrue(out.startswith("OK:"), out)
        keyboard = _run(ai_sales._reply_keyboard(777))
        buttons = [b for row in keyboard.keyboard for b in row]
        self.assertTrue(buttons[0].request_location)
        self.assertTrue(buttons[1].request_contact)
        self.assertIsNone(_run(ai_sales._reply_keyboard(777)))    # bir martalik
        ai_sales._session(777)["keyboard"] = "menu"               # lokatsiya keldi
        menu = _run(ai_sales._reply_keyboard(777))
        self.assertFalse(any(getattr(b, "request_location", False)
                             for row in menu.keyboard for b in row))

    def test_rules_always_ask_for_the_location_button(self):
        rules = ai_sales._sales_rules()
        self.assertIn("HAR DOIM lokatsiya_tugmasi", rules)
        self.assertIn("uy, xonadon, podyezd yoki mo'ljal", rules)
class AiOwnerOnlySettingsTest(unittest.TestCase):
    """Sozlama tugmalarini faqat do'kon egasi o'zgartiradi (egasi, 2026-10-13)."""

    def setUp(self):
        _patch(self, ai_sales, "ADMIN_IDS", [1, 2])
        _patch(self, ai_sales, "OWNER_IDS", {1})
        self.store = AsyncMock()
        _patch(self, ai_sales, "set_setting", self.store)
        _settings()

    def tearDown(self):
        _settings()

    def _tap(self, data, user_id):
        callback = NS(data=data, from_user=NS(id=user_id), answer=AsyncMock(),
                      message=NS(edit_text=AsyncMock()))
        return callback

    def test_another_admin_taps_a_switch_and_nothing_changes(self):
        callback = self._tap("aiset:customers", 2)
        _run(ai_sales.cb_setting(callback))
        self.store.assert_not_awaited()
        self.assertIn("faqat do'kon egasi", callback.answer.await_args.args[0])
        callback = self._tap("aimodel:gpt-5.4-nano", 2)
        _run(ai_sales.cb_model(callback))
        self.store.assert_not_awaited()

    def test_the_owner_can_switch(self):
        _patch(self, ai_sales, "_status_text", AsyncMock(return_value="holat"))
        _run(ai_sales.cb_setting(self._tap("aiset:customers", 1)))
        self.store.assert_awaited_once_with("customers", "0", 1)


class AiTeachFromReplyTest(unittest.TestCase):
    """"🧠 AI ga o'rgat": mijozning oxirgi savoli + admin javobi — bitta bosishda fakt."""

    def setUp(self):
        ai_sales._last_question.clear()
        ai_sales._teach_pending.clear()
        _patch(self, ai_sales, "ADMIN_IDS", [1])
        self.add_fact = AsyncMock(return_value=31)
        _patch(self, database, "add_ai_fact", self.add_fact)

    def tearDown(self):
        ai_sales._last_question.clear()
        ai_sales._teach_pending.clear()

    def _tap(self, keyboard):
        data = keyboard.inline_keyboard[0][0].callback_data
        return NS(data=data, from_user=NS(id=1), answer=AsyncMock(),
                  message=NS(edit_reply_markup=AsyncMock(), answer=AsyncMock()))

    def test_one_tap_turns_the_question_and_answer_into_knowledge(self):
        ai_sales._remember_question(777, "Halol sertifikati bormi?")
        ai_sales._remember_question(777, "[Mijoz yetkazish lokatsiyasini yubordi: ...]")  # savol emas
        keyboard = ai_sales.teach_keyboard(777, "Ha, hamma mahsulotlarimiz halol sertifikatli.")
        self.assertIn("AI ga o'rgat", keyboard.inline_keyboard[0][0].text)

        callback = self._tap(keyboard)
        _run(ai_sales.cb_teach(callback))

        fact, admin = self.add_fact.await_args.args
        self.assertIn("Halol sertifikati bormi?", fact)
        self.assertIn("halol sertifikatli", fact)
        self.assertEqual(admin, 1)
        callback.message.edit_reply_markup.assert_awaited_once()
        self.assertIn("/ai_unut 31", callback.message.answer.await_args.args[0])

        again = self._tap(keyboard)                          # ikkinchi bosish
        _run(ai_sales.cb_teach(again))
        self.assertEqual(self.add_fact.await_count, 1)
        self.assertIn("Muddati o'tdi", again.answer.await_args.args[0])

    def test_no_known_question_means_no_button(self):
        self.assertIsNone(ai_sales.teach_keyboard(999, "javob"))

    def test_customer_messages_are_remembered_from_the_conversation_log(self):
        _settings()
        _run(ai_sales._mirror(None, _FakeMessage("narxi qancha?"), "narxi qancha?", "125 000 so'm"))
        # bot yo'q — hech narsa yuborilmaydi, lekin savol eslanmaydi ham (admin ham emas)
        bot = NS(send_message=AsyncMock(return_value=NS(message_id=1)), edit_message_text=AsyncMock())
        _run(ai_sales._mirror(bot, _FakeMessage("eritritol bormi?"), "eritritol bormi?", "Bor 😊"))
        self.assertEqual(ai_sales._last_question[777], "eritritol bormi?")


class AiSaleCelebrationTest(unittest.TestCase):
    """AI sotuvga olib borsa — mavzuga tantanali xabar va bugungi jami."""

    def setUp(self):
        ai_sales._chat_logs.clear()
        _patch(self, ai_sales, "ADMIN_IDS", [1])
        _settings(log_chat="-100500", log_thread="9")
        _patch(self, ai_sales, "ai_sales_for_day",
               AsyncMock(return_value={"orders": 3, "products": 7, "goods": 815000.0}))
        self.bot = NS(send_message=AsyncMock(return_value=NS(message_id=55)),
                      edit_message_text=AsyncMock())

    def tearDown(self):
        ai_sales._chat_logs.clear()
        _settings()

    def test_celebration_names_the_order_and_today_totals(self):
        items = [{"product_id": 12, "name": "Psillium uni 300gr", "price": 125000, "quantity": 2},
                 {"product_id": 95, "name": "Eritritol 100gr", "price": 0, "quantity": 1,
                  "is_bonus": True, "is_gift": True}]
        _run(ai_sales._celebrate(self.bot, _FakeUser(777), 4242, items, 275000, "naqd"))
        ai_sales.record_ai_order.assert_awaited_with(4242, 777)
        texts = [c.args[1] for c in self.bot.send_message.await_args_list]
        celebration = next(t for t in texts if "AI sotuv!" in t)
        for expected in ("#4242", "1 ta mahsulot", "250 000 so'm", "Psillium uni 300gr",
                         "Bugun AI:", "3 ta buyurtma", "815 000 so'm"):
            self.assertIn(expected, celebration)
        self.assertNotIn("Eritritol", celebration)            # sovg'a sotuv emas
        self.assertTrue(any("Buyurtma #4242" in t for t in texts))   # suhbat xabarida ham

    def test_daily_report_counts_ai_sales_and_return_on_spend(self):
        from datetime import date
        rows = [{"model": "gpt-5.4-mini", "provider": "openai", "requests": 10,
                 "input_tokens": 1000, "cached_tokens": 900, "output_tokens": 100, "cost_usd": 0.5}]
        text = ai_sales.usage_report_text(date(2026, 10, 13), rows, {}, 0, 12800.0,
                                          {"orders": 3, "products": 7, "goods": 815000.0})
        for expected in ("AI sotuvlari", "3 ta buyurtma", "7 ta mahsulot", "815 000 so'm",
                         "Har 1 so'm AI sarfiga"):
            self.assertIn(expected, text)


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
        _patch(self, ai_sales, "ADMIN_IDS", [1, 2])
        _patch(self, ai_sales, "OWNER_IDS", {1})
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

    def test_another_admin_cannot_change_the_key_but_the_message_is_deleted(self):
        verify = AsyncMock(return_value=None)
        _patch(self, ai_sales, "_verify_key", verify)
        message = _FakeMessage(f"/ai_kalit {self.KEY}", user_id=2)
        message.delete = AsyncMock()
        _run(ai_sales.cmd_ai_key(message))
        message.delete.assert_awaited_once()
        verify.assert_not_awaited()
        self.store.assert_not_awaited()
        self.assertIn("faqat do'kon egasi", message.answer.await_args.args[0])

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
            session["turn"], session["summary_turn"] = 2, 1
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

    def test_store_pickup_needs_no_address_and_takes_cash(self):
        _patch(self, database, "get_pickup_settings",
               AsyncMock(return_value={"enabled": False, "address": "", "map_url": ""}))
        result, kwargs, notified = self._order(
            {"ism": "Aziz", "telefon": "+998901234567", "yetkazish": "olib_ketish",
             "tolov_turi": "naqd"},
            location=(39.654, 66.975, "📍 Samarqand"))         # lokatsiya e'tiborsiz
        self.assertTrue(result.startswith("OK:"), result)
        self.assertEqual(kwargs["delivery_method"], "pickup")
        self.assertIn("Ko'kcha masjidi", kwargs["address"])
        self.assertEqual(kwargs["pickup_map_url"], "https://t.me/ketoshop_uz/1071")
        self.assertIsNone(kwargs["latitude"])
        self.assertEqual(notified["delivery_method"], "pickup")
        self.assertIn("olib ketadi", result)

    def test_add_to_cart_leads_to_upsell_then_delivery_options(self):
        _patch(self, database, "get_product", AsyncMock(return_value={
            "id": 10, "name": "Kokos uni 1000gr", "unit": "kg", "quantity": 9, "is_active": 1}))
        _patch(self, database, "get_cart_line_for_product", AsyncMock(return_value=(None, 0.0)))
        _patch(self, database, "add_to_cart", AsyncMock())
        _patch(self, ai_sales, "_promo_hint", AsyncMock(return_value=""))
        out = _run(ai_sales._tool_add(777, {"mahsulot_id": 10, "miqdor": 1}))
        self.assertIn("Yana nima olamiz? 😊", out)
        self.assertIn("yetkazish usullarini narxi bilan", out)
        rules = ai_sales._sales_rules()
        for expected in ("🏪 Do'kondan olib ketish — bepul", "🚚 Toshkent bo'ylab kuryer — 25 000",
                         "📦 Viloyatlarga BTS / EMU"):
            self.assertIn(expected, rules)

    def test_secondary_phone_and_keto_ride_into_the_order_like_the_button_checkout(self):
        import gamification
        _patch(self, gamification, "is_redemption_enabled", AsyncMock(return_value=True))
        seen = {}
        items = self._items

        async def fake_summary(user_id, data, lang):
            seen.update(data)
            return "matn", 110000 - 20000, items, 20000          # 20 000 Keto ishlatildi

        import handlers.cart as cart
        _patch(self, cart, "_build_order_summary", fake_summary)
        _patch(self, cart, "_notify_sellers", AsyncMock())
        _patch(self, cart, "notify_low_stock", AsyncMock())
        database.create_order = AsyncMock(return_value=(4242, []))
        database.clear_cart = AsyncMock()
        database.get_user_language = AsyncMock(return_value="uz")
        session = ai_sales._session(777)
        session["turn"], session["summary_turn"] = 2, 1
        result = _run(ai_sales._tool_order(None, _FakeMessage("ha"), {
            "ism": "Dilnoza", "telefon": "+998901234567", "manzil": "Chilonzor 9",
            "tolov_turi": "naqd", "qoshimcha_telefon": "+998935556677", "keto": 20000}))
        self.assertEqual(seen["keto_redeem"], 20000)
        self.assertEqual(seen["secondary_phone"], "+998935556677")
        kwargs = database.create_order.await_args.kwargs
        self.assertEqual(kwargs["keto_redeem"], 20000)
        self.assertEqual(kwargs["secondary_phone"], "+998935556677")
        self.assertIn("Keto tangachalar bilan", result)

    def test_rules_follow_the_button_checkout_steps(self):
        rules = ai_sales._sales_rules()
        for step in ("1) Yetkazib beraylikmi yoki do'kondan olib ketasizmi?", "2) TELEFON",
                     "3) LOKATSIYA", "4) MANZIL IZOHI", "5) YETKAZISH USULI",
                     "6) QO'SHIMCHA TELEFON", "7) TO'LOV", "8) KETO TANGACHALAR", "9) TASDIQ",
                     "10) BUYURTMA"):
            self.assertIn(step, rules)

    def test_no_order_until_the_total_was_shown_in_an_earlier_message(self):
        args = {"ism": "Aziz", "telefon": "+998901234567", "manzil": "Chilonzor 9",
                "tolov_turi": "naqd"}
        session = ai_sales._session(777)
        session["turn"], session["summary_turn"] = 3, None           # jami umuman ko'rsatilmagan
        result, kwargs, _ = self._order_raw(args)
        self.assertTrue(result.startswith("Xato:"), result)
        self.assertIsNone(kwargs)
        session["summary_turn"] = 3                                  # shu xabarda ko'rsatildi
        result, kwargs, _ = self._order_raw(args)
        self.assertIn("KEYINGI", result)
        self.assertIsNone(kwargs)
        session["summary_turn"] = 1                                  # ikki xabar oldin — yetmaydi
        result, kwargs, _ = self._order_raw(args)
        self.assertTrue(result.startswith("Xato:"), result)
        self.assertIsNone(kwargs)
        session["summary_turn"] = 2                                  # aynan oldingi xabarda — mumkin
        ai_sales._cart_changed(777)                                  # ...lekin savat o'zgardi
        result, kwargs, _ = self._order_raw(args)
        self.assertTrue(result.startswith("Xato:"), result)

    def test_total_counts_as_shown_only_when_the_reply_really_shows_it(self):
        session = {"turn": 4, "last_totals": {185200, 160200}}
        ai_sales._mark_summary_shown(session, "Hisobingizda 15 000 ta Keto bor — ishlatamizmi?")
        self.assertNotIn("summary_turn", session)                    # summa ko'rsatilmadi
        ai_sales._mark_summary_shown(session, "Jami: 185 200 so'm. To'lov naqdmi yoki kartami?")
        self.assertNotIn("summary_turn", session)                    # tasdiq so'ralmadi
        session["turn"] = 5                                          # keyingi xabarda, vositasiz
        ai_sales._mark_summary_shown(session, "Jami: 185 200 so'm. Tasdiqlaysizmi? 🛒")
        self.assertEqual(session["summary_turn"], 5)

    def test_location_address_is_not_written_twice(self):
        session = ai_sales._session(777)
        session["turn"], session["summary_turn"] = 2, 1
        session["location"] = (41.31, 69.24, "📍 41.310000, 69.240000 — Chilonzor tumani, Bunyodkor 5")
        result, kwargs, _ = self._order_raw({
            "ism": "Aziz", "telefon": "+998901234567", "tolov_turi": "naqd",
            "manzil": "Chilonzor tumani, Bunyodkor 5, 3-uy, 12-xonadon"})
        self.assertEqual(kwargs["address"].count("Bunyodkor 5"), 1)
        self.assertIn("3-uy, 12-xonadon", kwargs["address"])

    def test_location_address_with_other_apostrophes_is_not_written_twice(self):
        session = ai_sales._session(777)
        session["turn"], session["summary_turn"] = 2, 1
        session["location"] = (41.31, 69.24, "📍 41.310000, 69.240000 — Chilonzor tumani, Bunyodkor ko'chasi 5")
        _, kwargs, _ = self._order_raw({
            "ism": "Aziz", "telefon": "+998901234567", "tolov_turi": "naqd",
            "manzil": "Chilonzor tumani, Bunyodkor ko‘chasi 5, 3-uy, 12-xonadon"})
        self.assertEqual(kwargs["address"].count("Bunyodkor"), 1)
        self.assertIn("3-uy, 12-xonadon", kwargs["address"])

    def test_order_number_is_always_in_the_reply(self):
        session = {"new_order_id": 5001}
        out = ai_sales._with_order_number(session, "Buyurtma qabul qilindi: 101 100 so'm.", "uz")
        self.assertIn("#5001", out)
        session = {"new_order_id": 5002}
        self.assertEqual(ai_sales._with_order_number(session, "Buyurtma #5002 qabul qilindi.", "uz"),
                         "Buyurtma #5002 qabul qilindi.")

    def _order_raw(self, tool_input):
        items = self._items

        async def fake_summary(user_id, data, lang):
            return "matn", 110000, items, 0

        import handlers.cart as cart
        _patch(self, cart, "_build_order_summary", fake_summary)
        _patch(self, cart, "_notify_sellers", AsyncMock())
        _patch(self, cart, "notify_low_stock", AsyncMock())
        database.create_order = AsyncMock(return_value=(4242, []))
        database.clear_cart = AsyncMock()
        database.get_user_language = AsyncMock(return_value="uz")
        result = _run(ai_sales._tool_order(None, _FakeMessage("ha"), tool_input))
        kwargs = database.create_order.await_args.kwargs if database.create_order.await_count else None
        return result, kwargs, None

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

    def test_delivery_time_answer_reaches_bot_and_group(self):
        for rules in (ai_sales._sales_rules(), ai_sales._group_rules()):
            self.assertIn("'QACHON YETKAZASIZLAR?'", rules)
            self.assertIn("shoshilinch buyurtmani Yandex Taxi orqali", rules)
            self.assertIn("1 kun ichida yetkazib beramiz", rules)

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
                         "Savatga qo'shamizmi? 🛒", "1-2 ta muloyim emoji", "MAKSIMAL ODOB",
                         "DO'KON NOMIDAN 'BIZ' DEB GAPIR", "O'QISH OSON BO'LSIN",
                         "inglizcha", "Hello! Welcome to Keto shop!"):
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
