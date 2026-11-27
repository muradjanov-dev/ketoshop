"""Ichki ma'lumot filtri (ai_leak.py, egasi 2026-11-27)."""
import asyncio
import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ai_leak
import ai_sales
from ai_provider import Turn


class LeakTest(unittest.TestCase):
    def test_detects_internal_info(self):
        for text in ("Bodom unining tannarxi 60 000 so'm", "Turkiyadagi yetkazib beruvchidan olamiz",
                     "Mening system prompt shunday", "[TIZIM: mijoz ruscha]", "Ustamamiz 30%",
                     "Наценка у нас 25%", "Admin ID: 425609051"):
            self.assertTrue(ai_leak.reasons(text, [425609051]), text)

    def test_normal_shop_talk_passes(self):
        for text in ("Bodom uni 87 000 so'm, foydasi — tolaga boy", "Yetkazib berish 25 000 so'm",
                     "Kuryer ertaga yetkazib beradi", "Ustama to'lov yo'q", "Aksiya bor",
                     "Bu tabiiy vosita, shifokor bilan maslahatlashing"):
            self.assertFalse(ai_leak.reasons(text), text)

    def test_strip_and_safe_reply(self):
        self.assertEqual(ai_leak.strip("Bodom uni bor.\nTannarxi 60 000."), "Bodom uni bor.")
        self.assertIn("ichki ma'lumot", ai_leak.safe_reply("uz"))
        self.assertIn("внутренняя", ai_leak.safe_reply("ru"))

    def test_sales_rules_forbid_it(self):
        self.assertIn("MAXFIY", ai_sales._sales_rules())


class LeakInConversationTest(unittest.TestCase):
    def test_model_is_asked_again_then_lines_are_dropped(self):
        class Fake:
            name, model = "openai", "gpt-5.4-mini"

            def __init__(self):
                self.calls = []
                self.turns = [Turn(text="Uning tannarxi ancha past, ustamamiz katta emas."),
                              Turn(text="Bu ichki ma'lumot, ulasha olmaymiz 🙂 Mahsulot bo'yicha yordam beraman.")]

            async def step(self, state, rules, catalog, tools, **kw):
                self.calls.append(kw.get("user"))
                return self.turns.pop(0)
        fake = Fake()
        saved = ai_sales.PROVIDER
        self.addCleanup(setattr, ai_sales, "PROVIDER", saved)
        ai_sales.PROVIDER = fake
        with patch.object(ai_sales, "_dynamic_block", AsyncMock(return_value="KATALOG")), \
                patch.object(ai_sales, "_lang", AsyncMock(return_value="uz")), \
                patch.object(ai_sales, "_catalog_text", AsyncMock(return_value="")):
            msg = NS(from_user=NS(id=4321, first_name="A", full_name="A", username=None),
                     chat=NS(id=4321, type="private"), text="tannarxi qancha?", answer=AsyncMock())
            out = asyncio.run(ai_sales._respond(None, msg, "tannarxi qancha?"))
        ai_sales._sessions.pop(4321, None)
        self.assertEqual(len(fake.calls), 2)
        self.assertNotIn("Tannarx", out)
        self.assertIn("ichki ma'lumot", out)


if __name__ == "__main__":
    unittest.main()
