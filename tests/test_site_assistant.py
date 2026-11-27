"""Saytdagi «Yordamchi» (site_assistant.py, 2026-11-15): botdagi AI sotuvchi
saytda — Telegram'ga xos vositalarsiz, rasmli kartochkalar bilan."""
import asyncio
import os
import sys
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://ci:ci@localhost:5432/ci")
os.environ.setdefault("BOT_TOKEN", "123456:CI-TOKEN")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ai_sales  # noqa: E402
import database  # noqa: E402
import site_assistant as sa  # noqa: E402

USER = {"id": 555, "first_name": "Ali", "username": "ali"}
PRODUCT = {"id": 7, "name": "Eritritol 500gr", "name_ru": None, "price": 76000, "discount_percent": 0,
           "discount_until": None, "unit": "dona", "photo_id": "AgADfile", "quantity": 4, "is_active": 1}
ORDERS = [
    {"id": 5002, "status": "shipped", "total": 152000, "created_at": datetime(2026, 11, 14, 9, 0),
     "delivery_method": "courier", "payment_method": "cash", "address": "Toshkent, Chilonzor",
     "items": '[{"product_id": 7, "name": "Eritritol 500gr", "quantity": 2, "price": 76000, "unit": "dona"},'
              ' {"product_id": 9, "name": "Eritritol 100gr", "quantity": 1, "price": 0, "is_bonus": true}]'},
    {"id": 4900, "status": "delivered", "total": 50000, "created_at": datetime(2026, 11, 1, 9, 0),
     "delivery_method": "pickup", "payment_method": "online", "address": "Do'kon", "items": "[]"},
]


class ToolsTest(unittest.TestCase):
    def test_site_has_no_telegram_only_tools(self):
        names = {t.name for t in sa.WEB_TOOLS}
        self.assertNotIn("buyurtma_kartasi", names)
        self.assertNotIn("lokatsiya_tugmasi", names)
        self.assertIn("buyurtma_holati", names)
        self.assertIn("savatga_qoshish", names)


class CardsTest(unittest.TestCase):
    def run_cards(self, trace, cart=None):
        async def product(pid):
            return dict(PRODUCT, id=pid, photo_id=f"/img/{pid}")
        with patch.object(database, "get_product", product), \
                patch.object(database, "get_user_orders", AsyncMock(return_value=ORDERS)), \
                patch.object(database, "get_cart", AsyncMock(return_value=cart or [])):
            return asyncio.run(sa.build_cards(555, "uz", trace))

    def test_product_cards_from_tools(self):
        cards = self.run_cards([("mahsulot_haqida", {"mahsulot_id": 7}, "Eritritol — 76 000 so'm"),
                                ("mahsulot_haqida", {"mahsulot_id": 8}, "Xato: yo'q")])
        self.assertEqual([c["type"] for c in cards], ["product"])
        self.assertEqual(cards[0]["photo_url"], "/img/7")
        self.assertEqual(cards[0]["price"], 76000)

    def test_order_cards_are_the_buyers_own_with_photos(self):
        cards = self.run_cards([("buyurtma_holati", {}, "#5002 · yo'lda")])
        self.assertEqual([c["id"] for c in cards], [5002])            # open ones only
        card = cards[0]
        self.assertEqual(card["status_text"], database_status("shipped"))
        self.assertEqual(card["items"][0]["photo_url"], "/img/7")
        self.assertEqual(card["items"][0]["total"], 152000)
        self.assertTrue(card["items"][1]["gift"])
        self.assertEqual(card["payment"], "Naqd")
        self.assertEqual(card["address"], "Toshkent, Chilonzor")

    def test_order_by_number_and_unknown_number(self):
        self.assertEqual([c["id"] for c in self.run_cards([("buyurtma_holati", {"buyurtma_raqami": 4900}, "ok")])],
                         [4900])
        self.assertEqual(self.run_cards([("buyurtma_holati", {"buyurtma_raqami": 1}, "Xato: yo'q")]), [])

    def test_cart_card_after_adding(self):
        cart = [{"name": "Eritritol 500gr", "cart_quantity": 2, "price": 76000, "discount_percent": 0,
                 "discount_until": None, "unit": "dona", "photo_id": "/img/7"}]
        cards = self.run_cards([("savatga_qoshish", {"mahsulot_id": 7, "miqdor": 2}, "OK")], cart=cart)
        self.assertEqual([c["type"] for c in cards], ["product", "cart"])
        self.assertEqual(cards[1]["total"], 152000)
        self.assertEqual(cards[1]["items"][0]["photo_url"], "/img/7")


def database_status(status):
    from locales import get_order_status
    return get_order_status(status, "uz")


class AskTest(unittest.TestCase):
    def setUp(self):
        sa._recent.clear()
        p = patch.object(ai_sales, "mid_conversation", AsyncMock(return_value=True))  # salom qoidasi alohida (test_person_folder)
        p.start()
        self.addCleanup(p.stop)

    def run_ask(self, respond, ready=True, allowed=True, paused=False, text="Buyurtmam qayerda?"):
        async def fake_respond(bot, message, user_text, tools=None):
            return await respond(bot, message, user_text, tools)

        with patch.object(ai_sales, "_ready", AsyncMock(return_value=ready)), \
                patch.object(ai_sales, "_allowed", AsyncMock(return_value=allowed)), \
                patch.object(ai_sales, "_is_paused", lambda uid: paused), \
                patch.object(ai_sales, "_respond", fake_respond), \
                patch.object(ai_sales, "_mirror", AsyncMock()) as mirror, \
                patch.object(sa, "build_cards", AsyncMock(return_value=[{"type": "order", "id": 5002}])):
            result = asyncio.run(sa.ask(None, USER, text, "uz"))
        return result, mirror

    def test_reply_and_cards_come_back_and_the_turn_is_mirrored(self):
        seen = {}

        async def respond(bot, message, user_text, tools):
            seen.update(text=user_text, tools=tools, uid=message.from_user.id)
            message.web_cards.append(("buyurtma_holati", {}, "#5002"))
            return "Buyurtmangiz #5002 yo'lda 🚚"

        result, mirror = self.run_ask(respond)
        self.assertEqual(result["reply"], "Buyurtmangiz #5002 yo'lda 🚚")
        self.assertEqual(result["cards"], [{"type": "order", "id": 5002}])
        self.assertTrue(seen["text"].startswith("[SAYT YORDAMCHISI"))
        self.assertIs(seen["tools"], sa.WEB_TOOLS)
        self.assertEqual(seen["uid"], 555)
        self.assertIn("🌐 Sayt", mirror.await_args.args[2])
        self.assertIn("id 555", mirror.await_args.args[2])          # who is writing (2026-11-21)

    def test_who_line_from_the_database_when_the_profile_is_empty(self):
        from types import SimpleNamespace
        user = SimpleNamespace(id=7, full_name=None, first_name="", username=None)
        with patch.object(database, "get_user", AsyncMock(return_value={"full_name": "Dilnoza K", "username": "dil"})):
            asyncio.run(sa._fill_who(user))
        self.assertEqual(sa.who_line(user), "Dilnoza K @dil · id 7")

    def test_ai_off_gives_contacts_without_calling_the_model(self):
        respond = AsyncMock()
        result, _ = self.run_ask(respond, ready=False)
        respond.assert_not_awaited()
        self.assertIn("@ketoshopbot", result["reply"])
        self.assertTrue(result.get("offline"))

    def test_failure_returns_a_polite_line(self):
        async def respond(*a):
            raise RuntimeError("boom")
        result, _ = self.run_ask(respond)
        self.assertTrue(result.get("error"))
        self.assertIn("Kechirasiz", result["reply"])

    def test_hourly_limit(self):
        for _ in range(sa.HOURLY_LIMIT):
            self.assertFalse(sa._limited(1, now=1000.0))
        self.assertTrue(sa._limited(1, now=1000.0))
        self.assertFalse(sa._limited(1, now=1000.0 + 3601))


class RespondLoopTest(unittest.TestCase):
    """The real ai_sales._respond loop with a scripted model: the site's
    tool list goes to the model and the tool trace lands on the message."""

    def test_order_status_through_the_real_loop(self):
        from ai_provider import ToolCall, Turn

        class Provider:
            name, model = "fake", "fake-model"

            def __init__(self, turns):
                self.turns, self.calls = list(turns), []

            async def step(self, state, rules, catalog, tools, *, user=None, results=None,
                           max_tokens=800, history_limit=40):
                self.calls.append({"tools": tools, "user": user, "results": results})
                return self.turns.pop(0)

        provider = Provider([Turn(calls=[ToolCall("t1", "buyurtma_holati", {})]),
                             Turn(text="Buyurtmangiz #5002 yo'lda 🚚")])
        saved = (ai_sales.PROVIDER, ai_sales._catalog_cache)
        self.addCleanup(lambda: (setattr(ai_sales, "PROVIDER", saved[0]),
                                 setattr(ai_sales, "_catalog_cache", saved[1]), ai_sales._sessions.clear()))
        ai_sales.PROVIDER = provider
        ai_sales._catalog_cache = (9e18, "7 | Eritritol 500gr | 76 000 so'm / dona")
        message = sa.WebMessage(None, USER, "buyurtmam qayerda")
        with patch.object(database, "get_user_orders", AsyncMock(return_value=ORDERS)),                 patch.object(database, "get_user_language", AsyncMock(return_value="uz")):
            reply = asyncio.run(ai_sales._respond(None, message, "buyurtmam qayerda", tools=sa.WEB_TOOLS))
        self.assertEqual(reply, "Buyurtmangiz #5002 yo'lda 🚚")
        self.assertIs(provider.calls[0]["tools"], sa.WEB_TOOLS)
        self.assertEqual(message.web_cards[0][0], "buyurtma_holati")
        self.assertIn("#5002", message.web_cards[0][2])
        self.assertNotIn("#4900", message.web_cards[0][2])          # delivered one not listed when one is open


class EndpointTest(unittest.TestCase):
    def test_route_and_tracking_kind(self):
        import webapp_server
        self.assertIn("assistant", webapp_server.TRACK_KINDS)
        self.assertTrue(callable(webapp_server.api_assistant))


class RespondTraceTest(unittest.TestCase):
    def test_respond_accepts_tools_and_records_the_trace(self):
        import inspect
        src = inspect.getsource(ai_sales._respond)
        self.assertIn("tools=None", src)
        self.assertIn('getattr(message, "web_cards", None)', src)
        self.assertNotIn("TOOLS,", src.replace("tools = tools or TOOLS", ""))


class PageTest(unittest.TestCase):
    def test_widget_is_on_the_page(self):
        page = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webapp", "index.html"),
                    encoding="utf-8").read()
        for needle in ('id="asst-fab"', 'id="asst-modal"', "const Assistant = (() => {", "Assistant.start();",
                       "'/api/assistant'", "_isModalOpen('asst-modal')", "Keto shopdagi istalgan mahsulot"):
            self.assertIn(needle, page)


if __name__ == "__main__":
    unittest.main()
