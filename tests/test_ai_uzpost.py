"""AI sotuvchida UzPost (egasi, 2026-11-07): AI Marg'ilonga faqat BTS/EMU ni
aytgan — "nega uzpostni qo'shmayapsan, uni ham tahminiy narxlari bilan qo'sh!".
No Telegram, no database, no UzPost network calls."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ai_sales
import database
import handlers.cart as cart
import uzpost

BODOM = {"id": 12, "name": "Bodom uni 500gr", "price": 87000, "unit": "kg", "quantity": 9,
         "is_active": 1, "discount_percent": 0, "discount_until": None}
MARGILON = (40.4717, 71.7246, "📍 40.471700, 71.724600 — Marg'ilon")
NUKUS = (42.4611, 59.6166, "📍 42.461100, 59.616600 — Nukus")
CHILONZOR = (41.2856, 69.2034, "📍 41.285600, 69.203400 — Chilonzor")
OFFICE = {"index": "150100", "name": "Marg'ilon Pochtamt", "address": "Farg'ona, Marg'ilon, Mustaqillik 1",
          "hours": "Du-Sha 08:00-18:00", "region": "Farg'ona", "lat": 40.47, "lng": 71.72, "km": 1.2}


def run(coro):
    return asyncio.run(coro)


class FakeState:
    def __init__(self):
        self.state, self.data = None, {}

    async def get_state(self):
        return self.state

    async def set_state(self, value):
        self.state = getattr(value, "state", value)

    async def get_data(self):
        return dict(self.data)

    async def set_data(self, data):
        self.data = dict(data)

    async def update_data(self, **values):
        self.data.update(values)

    async def clear(self):
        self.state, self.data = None, {}


class FakeMessage:
    def __init__(self, user_id=777):
        self.text = "ha"
        self.from_user = type("U", (), {"id": user_id, "full_name": "T", "username": None,
                                        "first_name": "T", "is_bot": False})()
        self.chat = type("C", (), {"id": user_id, "type": "private"})()
        self.answer = AsyncMock()


class KnowledgeTest(unittest.TestCase):
    def test_uzpost_is_offered_first_for_regions_with_approximate_prices(self):
        text = ai_sales._shop_knowledge()
        self.assertIn("UzPost «Bir Qadam»", text)
        self.assertIn("posilka 1 kg gacha ~18 000 so'm", text)       # 15 000 tarif + 3 000
        self.assertIn("har keyingi kg +3 000 so'm", text)
        self.assertIn("+7 000 so'm", text)                           # Qoraqalpog'iston, Xorazm, Surxondaryo
        self.assertLess(text.index("📮 Viloyatlarga UzPost"), text.index("📦 Viloyatlarga BTS / EMU"))
        self.assertIn("UzPost (narxi bilan), BTS yoki EMU", ai_sales._sales_rules())

    def test_the_card_tool_accepts_uzpost(self):
        self.assertEqual(ai_sales.DELIVERY["uzpost"], uzpost.METHOD)
        spec = {s["name"]: s for s in ai_sales._TOOL_SPECS}["buyurtma_kartasi"]
        self.assertIn("uzpost", spec["input_schema"]["properties"]["yetkazish"]["enum"])
        self.assertNotIn("uzpost", ai_sales.CASH_OK)                 # faqat karta oldindan


class QuoteTest(unittest.TestCase):
    def test_the_quote_line_is_the_checkout_fee(self):
        items = [{"name": "Bodom uni 500gr", "quantity": 2, "unit": "kg"},
                 {"name": "Eritritol 1000gr", "quantity": 1, "unit": "kg"}]
        line = ai_sales._uzpost_line(items, 343000)
        fee = cart.delivery_fee_for(uzpost.METHOD, 343000, items, False)
        far = cart.delivery_fee_for(uzpost.METHOD, 343000, items, True)
        self.assertEqual((fee, far), (24000, 32000))                 # 2,2 kg → 3 kg
        self.assertIn(f"yetkazish ~24 000 so'm (posilka ~2,2 kg) -> JAMI ~367 000 so'm", line)
        self.assertIn("Surxondaryoga yetkazish ~32 000 so'm -> JAMI ~375 000 so'm", line)
        self.assertIn("faqat Toshkentdan tashqaridagi mijozga", line)

    def test_hisob_carries_the_uzpost_line(self):
        with patch.object(database, "get_product", AsyncMock(return_value=dict(BODOM))):
            out = run(ai_sales._tool_quote(1, {"mahsulotlar": [{"mahsulot_id": 12, "miqdor": 1}]}))
        self.assertIn("Jami (mahsulotlar): 87 000 so'm", out)
        self.assertIn("UzPost «Bir Qadam» bilan", out)
        self.assertIn("yetkazish ~18 000 so'm (posilka ~0,7 kg) -> JAMI ~105 000 so'm", out)


class CardTest(unittest.TestCase):
    def setUp(self):
        ai_sales._sessions.clear()
        self.state = FakeState()
        session = ai_sales._session(777)
        session["fsm"] = self.state
        session["phone"] = "+998901234567"
        for name, value in (("get_cart", AsyncMock(return_value=[{"product_id": 12}])),
                            ("get_user_language", AsyncMock(return_value="uz"))):
            p = patch.object(database, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.lookup = AsyncMock(return_value=dict(OFFICE))
        p = patch.object(uzpost, "nearest_office", self.lookup)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(ai_sales._sessions.clear)

    def card(self, args, location=None, said=()):
        session = ai_sales._sessions[777]
        if location:
            session["location"] = location
        session.setdefault("said", []).extend(said)
        return run(ai_sales._tool_card(FakeMessage(), args))

    def test_regional_pin_gets_the_nearest_office_and_card_only_payment(self):
        out = self.card({"yetkazish": "uzpost", "tolov_turi": "naqd"}, location=MARGILON)
        self.assertTrue(out.startswith("OK:"), out)
        self.assertIn("faqat karta", out)
        data = self.state.data
        self.assertEqual(data["delivery_method"], uzpost.METHOD)
        self.assertEqual(data["payment_method"], "online")
        self.assertEqual(data["post_office"], OFFICE)
        self.assertEqual(data["post_office_line"], uzpost.office_line(OFFICE))
        self.assertFalse(data["uzpost_far"])
        self.lookup.assert_awaited_once_with(MARGILON[0], MARGILON[1])

    def test_far_regions_pay_the_far_tariff(self):
        self.lookup.return_value = dict(OFFICE, region="Qoraqalpog'iston Respublikasi")
        self.card({"yetkazish": "uzpost"}, location=NUKUS)
        self.assertTrue(self.state.data["uzpost_far"])

    def test_uzpost_is_not_for_tashkent(self):
        out = self.card({"yetkazish": "uzpost"}, location=CHILONZOR)
        self.assertTrue(out.startswith("Xato:"), out)
        self.assertIn("UzPost faqat viloyatlarga", out)
        self.assertIsNone(self.state.state)

    def test_uzpost_down_still_opens_the_card_and_admins_pick_the_office(self):
        self.lookup.side_effect = RuntimeError("UzPost down")
        out = self.card({"yetkazish": "uzpost"}, location=MARGILON)
        self.assertTrue(out.startswith("OK:"), out)
        self.assertIsNone(self.state.data["post_office"])
        self.assertIsNone(self.state.data["post_office_line"])

    def test_other_methods_carry_no_post_office(self):
        self.card({"yetkazish": "toshkent_kuryer"}, location=CHILONZOR)
        self.assertIsNone(self.state.data["post_office"])
        self.assertFalse(self.state.data["uzpost_far"])
        self.lookup.assert_not_awaited()

    def test_courier_outside_tashkent_points_to_uzpost(self):
        out = self.card({"yetkazish": "toshkent_kuryer"}, location=MARGILON)
        self.assertIn("UzPost", out)


class StatusTest(unittest.TestCase):
    def test_shipped_uzpost_order_is_at_the_post(self):
        meaning = ai_sales._status_meaning({"status": "shipped", "delivery_method": uzpost.METHOD,
                                            "post_office": "150100 Marg'ilon"})
        self.assertIn("pochtaga topshirilgan", meaning)
        self.assertIn("150100", meaning)
        self.assertEqual(ai_sales._DELIVERY_NAME[uzpost.METHOD], "UzPost pochta")


if __name__ == "__main__":
    unittest.main()
