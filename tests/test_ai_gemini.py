"""Gemini AI sotuvchida (egasi, 2026-11-26: "/ai_holat ga geminini tanlash
imkonini ham qo'shib qo'ya olasanmi?").

1. GeminiProvider — tarmoqsiz: so'rov shakli (systemInstruction boshida,
   vositalar, thinkingLevel), vosita chaqiruvi va natijasi, thoughtSignature
   saqlanishi, sarf, uzilish va rad etish.
2. ai_sales — model tugmasi GPT ↔ Gemini provayderini almashtiradi, GPT
   kaliti zaxirada qoladi (izohlar AI'si va yurist uchun), sinov so'rovi
   o'tmasa model almashmaydi.
"""
import asyncio
import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ai_provider
import ai_sales
from ai_provider import GeminiProvider, Tool, ToolResult, Turn


def _run(coro):
    return asyncio.run(coro)


TOOL = Tool("savatga", "Savatga qo'shish", {"type": "object", "properties": {"id": {"type": "integer"}},
                                            "required": ["id"], "additionalProperties": False})


class GeminiProviderTest(unittest.TestCase):
    def setUp(self):
        self.provider = GeminiProvider("AIza-test", "gemini-3.5-flash-lite", "low")
        self.bodies = []
        self.replies = []

        async def fake_post(body):
            import copy
            self.bodies.append(copy.deepcopy(body))
            return self.replies.pop(0)
        self.provider._post = fake_post

    def test_tool_call_round_trip_keeps_the_signature_and_names_the_result(self):
        call_part = {"functionCall": {"name": "savatga", "args": {"id": 7}}, "thoughtSignature": "SIG"}
        self.replies = [
            {"candidates": [{"content": {"role": "model", "parts": [call_part]}, "finishReason": "STOP"}],
             "usageMetadata": {"promptTokenCount": 5000, "cachedContentTokenCount": 4000,
                               "candidatesTokenCount": 20, "thoughtsTokenCount": 30}},
            {"candidates": [{"content": {"role": "model", "parts": [
                {"text": "o'ylayapman", "thought": True}, {"text": "Savatga qo'shildi ✅"}]},
                "finishReason": "STOP"}]},
        ]
        state = {}
        turn = _run(self.provider.step(state, "QOIDALAR", "KATALOG", [TOOL], user="7 ni qo'sh"))

        body = self.bodies[0]
        self.assertEqual(body["systemInstruction"]["parts"][0]["text"], "QOIDALAR\n\nKATALOG")
        self.assertEqual(body["generationConfig"]["thinkingConfig"], {"thinkingLevel": "low"})
        decl = body["tools"][0]["functionDeclarations"][0]
        self.assertEqual(decl["name"], "savatga")
        self.assertEqual(decl["parametersJsonSchema"]["required"], ["id"])
        self.assertEqual(len(turn.calls), 1)
        self.assertEqual((turn.calls[0].name, turn.calls[0].args), ("savatga", {"id": 7}))
        self.assertEqual((turn.usage.input, turn.usage.cached, turn.usage.output), (5000, 4000, 50))

        turn2 = _run(self.provider.step(state, "QOIDALAR", "KATALOG", [TOOL],
                                        results=[ToolResult(turn.calls[0].id, "ok")]))
        sent = self.bodies[1]["contents"]
        self.assertEqual(sent[1]["parts"][0], call_part)                 # imzo o'zgarmagan
        response = sent[2]["parts"][0]["functionResponse"]
        self.assertEqual(response["name"], "savatga")
        self.assertEqual(response["response"], {"output": "ok"})
        self.assertNotIn("id", response)                                  # o'zimiz qo'ygan id ketmaydi
        self.assertEqual(turn2.text, "Savatga qo'shildi ✅")              # fikrlash matni chiqmaydi
        self.assertFalse(turn2.truncated)

    def test_truncated_refused_and_reset(self):
        self.replies = [
            {"candidates": [{"content": {"parts": [{"text": "Yarim"}]}, "finishReason": "MAX_TOKENS"}]},
            {"candidates": [{"finishReason": "SAFETY"}]},
            {"promptFeedback": {"blockReason": "OTHER"}},
        ]
        state = {}
        self.assertTrue(_run(self.provider.step(state, "r", "c", None, user="a")).truncated)
        self.assertTrue(_run(self.provider.step(state, "r", "c", None, user="b")).refused)
        self.assertTrue(_run(self.provider.step(state, "r", "c", None, user="c")).refused)
        self.assertNotIn("tools", self.bodies[0])
        ai_provider.reset(state)
        self.assertNotIn("contents", state)

    def test_effort_never_sends_minimal(self):
        self.assertEqual(GeminiProvider("k", "gemini-3.8-flash", "minimal")._thinking(),
                         {"thinkingLevel": "low"})

    def test_prices_are_known(self):
        for name in ("gemini-3.1-flash-lite", "gemini-3.5-flash-lite", "gemini-3.8-flash",
                     "gpt-6.1-terra", "gpt-6-luna", "gpt-5.6-luna"):
            self.assertIsNotNone(ai_provider.price_for(name), name)


class ModelSwitchTest(unittest.TestCase):
    GPT_KEY = "sk-proj-bot-key-WXYZ"

    def setUp(self):
        saved = (ai_sales.PROVIDER, ai_sales.MODEL, dict(ai_sales._key_source),
                 dict(ai_sales._settings))
        self.addCleanup(self._restore, saved)
        ai_sales._settings.update(at=float("inf"), values={"gemini_key": "AIza-gem-1234"}, staff=set())
        ai_sales._key_source.clear()
        ai_sales._key_source["from_bot"] = False
        ai_sales.PROVIDER = None
        ai_sales._apply_key(self.GPT_KEY)

    @staticmethod
    def _restore(saved):
        ai_sales.PROVIDER, ai_sales.MODEL = saved[0], saved[1]
        ai_sales._key_source.clear()
        ai_sales._key_source.update(saved[2])
        ai_sales._settings.clear()
        ai_sales._settings.update(saved[3])

    def test_gemini_buttons_are_offered_next_to_gpt(self):
        options = ai_sales.model_options()
        self.assertIn("gpt-5.4-mini", options)
        self.assertIn("gemini-3.5-flash-lite", options)
        self.assertNotIn("claude-opus-5", options)

    def test_switch_to_gemini_and_back_keeps_the_gpt_key(self):
        ai_sales._apply_model("gemini-3.5-flash-lite")
        self.assertEqual(ai_sales.PROVIDER.name, "gemini")
        self.assertEqual(ai_sales.PROVIDER.api_key, "AIza-gem-1234")
        self.assertEqual(ai_sales.MODEL, "gemini-3.5-flash-lite")
        self.assertIn("Gemini", ai_sales._key_status())
        self.assertNotIn("AIza-gem-1234", ai_sales._key_status())

        # Har 60 soniyadagi sozlama yuklanishi Gemini'ni GPT ga qaytarib yubormaydi.
        ai_sales._apply_key(self.GPT_KEY)
        ai_sales._apply_model("gemini-3.5-flash-lite")
        self.assertEqual(ai_sales.PROVIDER.name, "gemini")
        # Izohlar AI'si va yurist GPT kalitini topadi.
        self.assertEqual(ai_sales.openai_credentials()[0], self.GPT_KEY)

        ai_sales._apply_model("gpt-5.4-mini")
        self.assertEqual(ai_sales.PROVIDER.name, "openai")
        self.assertEqual(ai_sales.PROVIDER.api_key, self.GPT_KEY)
        self.assertEqual(ai_sales.MODEL, "gpt-5.4-mini")

    def test_without_a_gemini_key_the_model_stays(self):
        ai_sales._settings["values"] = {}
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            ai_sales._apply_model("gemini-3.5-flash-lite")
            self.assertEqual(ai_sales.PROVIDER.name, "openai")
            error = _run(ai_sales._probe("gemini-3.5-flash-lite"))
        self.assertIn("/gemini_kalit", error)

    def test_failed_probe_keeps_the_model(self):
        store = AsyncMock()
        callback = NS(data="aimodel:gemini-3.8-flash", from_user=NS(id=1), answer=AsyncMock(),
                      message=NS(edit_text=AsyncMock()))
        with patch.object(ai_sales, "OWNER_IDS", {1}), \
                patch.object(ai_sales, "_load_settings", AsyncMock()), \
                patch.object(ai_sales, "set_setting", store), \
                patch.object(GeminiProvider, "_post", AsyncMock(side_effect=RuntimeError("Gemini 404"))):
            _run(ai_sales.cb_model(callback))
        store.assert_not_awaited()
        self.assertEqual(ai_sales.PROVIDER.name, "openai")
        self.assertIn("ishlamadi", callback.answer.await_args.args[0])

    def test_passing_probe_switches(self):
        store = AsyncMock()
        callback = NS(data="aimodel:gemini-3.8-flash", from_user=NS(id=1), answer=AsyncMock(),
                      message=NS(edit_text=AsyncMock()))
        ok = {"candidates": [{"content": {"parts": [{"text": "Assalomu alaykum!"}]}, "finishReason": "STOP"}]}
        with patch.object(ai_sales, "OWNER_IDS", {1}), \
                patch.object(ai_sales, "_load_settings", AsyncMock()), \
                patch.object(ai_sales, "_status_text", AsyncMock(return_value="holat")), \
                patch.object(ai_sales, "set_setting", store), \
                patch.object(GeminiProvider, "_post", AsyncMock(return_value=ok)):
            _run(ai_sales.cb_model(callback))
        store.assert_awaited_once_with("model", "gemini-3.8-flash", 1)
        self.assertEqual(ai_sales.PROVIDER.name, "gemini")
        self.assertEqual(ai_sales.MODEL, "gemini-3.8-flash")


if __name__ == "__main__":
    unittest.main()
