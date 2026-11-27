"""AI sovg'a aksiyasini biladi va buyurtma ustida yosh so'ramaydi (egasi, 2026-11-27)."""
import asyncio
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ai_sales
import comment_followup
import gift_campaign

GIFT = {"id": 7, "name": "Eritritol 100gr", "quantity": 40}
STATE = {"ends_at": datetime(2026, 12, 30, 4, 0), "announced_at": datetime(2026, 11, 20, 4, 0)}


def _live(active=True, prod=GIFT):
    return [patch.object(gift_campaign, "is_active", AsyncMock(return_value=active)),
            patch.object(gift_campaign, "gift_product", AsyncMock(return_value=prod)),
            patch.object(gift_campaign, "_state", AsyncMock(return_value=STATE))]


def _run(coro, patches):
    for p in patches:
        p.start()
    try:
        return asyncio.run(coro)
    finally:
        for p in patches:
            p.stop()


class AiLineTest(unittest.TestCase):
    def test_active_campaign_is_described(self):
        line = _run(gift_campaign.ai_line(), _live())
        self.assertIn("HAR BIR buyurtmaga Eritritol 100gr", line)
        self.assertIn("30.12 gacha", line)
        self.assertIn("ikki sovg'a", line)

    def test_off_or_out_of_stock_is_silent(self):
        self.assertEqual(_run(gift_campaign.ai_line(), _live(active=False)), "")
        self.assertEqual(_run(gift_campaign.ai_line(), _live(prod=dict(GIFT, quantity=0))), "")


class PromptTest(unittest.TestCase):
    def test_dynamic_block_shows_gift_not_no_promo(self):
        with patch.object(ai_sales, "_promo_text", AsyncMock(return_value="")), \
                patch.object(ai_sales, "_bot_discount_text", AsyncMock(return_value="")), \
                patch.object(ai_sales, "_knowledge_text", AsyncMock(return_value="")):
            block = _run(ai_sales._dynamic_block("KAT"), _live())
        self.assertIn("FAOL AKSIYA:\nSovg'a aksiyasi", block)
        self.assertNotIn("hozir yo'q", block)

    def test_instagram_offers_include_gift(self):
        import promotions
        with patch.object(promotions, "get_active", AsyncMock(return_value=None)):
            text = _run(comment_followup.offers_text(), _live())
        self.assertTrue(text.startswith("- Sovg'a aksiyasi"))


class PortraitTest(unittest.TestCase):
    def test_no_age_question_while_ordering(self):
        claim = AsyncMock(return_value="age")
        with patch.object(ai_sales.customer_portrait, "ask_allowed", return_value=True), \
                patch.object(ai_sales, "ai_card_open", AsyncMock(return_value=False)), \
                patch.object(ai_sales.customer_portrait, "claim_question", claim):
            for text in ("Wunda 2ta sovĝa boladmi", "Buyurtma tasdiqlanboldyuu", "qachon keladi"):
                self.assertEqual(asyncio.run(ai_sales._portrait_hint(1, {}, text)), "", text)
            claim.assert_not_awaited()
            self.assertTrue(asyncio.run(ai_sales._portrait_hint(1, {}, "keto non uchun un kerak")))


if __name__ == "__main__":
    unittest.main()


class OrderRulesTest(unittest.TestCase):
    def test_short_ordering_rules_in_prompt(self):
        rules = ai_sales._sales_rules()
        self.assertIn("QISQA VA MANTIQLI", rules)
        self.assertIn("QAYTA BUYURTMA", rules)
