import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://ci:ci@localhost:5432/ci")
os.environ.setdefault("BOT_TOKEN", "123456:CI-TOKEN")

import referral_program  # noqa: E402


def _order(**kw):
    base = {"id": 7, "user_id": 555, "source": "bot", "keto_redeemed": 0,
            "items": [{"price": 50000, "quantity": 2}], "total": 125000}
    base.update(kw)
    return base


class CashbackBaseTest(unittest.TestCase):
    def test_products_only_without_delivery(self):
        self.assertEqual(referral_program.cashback_base(_order()), 100000)

    def test_keto_paid_part_excluded(self):
        self.assertEqual(referral_program.cashback_base(_order(keto_redeemed=20000)), 80000)

    def test_never_negative(self):
        self.assertEqual(referral_program.cashback_base(_order(keto_redeemed=999999)), 0)

    def test_items_as_json_string(self):
        self.assertEqual(referral_program.cashback_base(_order(items='[{"price": 1000, "quantity": 3}]')), 3000)


class AwardCashbackTest(unittest.IsolatedAsyncioTestCase):
    async def _run(self, order, claim_result=111):
        bot = AsyncMock()
        with patch.object(referral_program.database, "claim_referral_cashback",
                          AsyncMock(return_value=claim_result)) as claim, \
             patch.object(referral_program.database, "get_user",
                          AsyncMock(return_value={"language": "uz", "keto_balance": 3010,
                                                  "full_name": "Ali Valiyev"})):
            await referral_program.award_order_cashback(order, bot)
        return claim, bot

    async def test_three_percent_paid_and_referrer_notified(self):
        claim, bot = await self._run(_order())
        claim.assert_awaited_once_with(555, 7, 3000)
        self.assertEqual(bot.send_message.await_args.args[0], 111)

    async def test_no_referral_or_already_paid_sends_nothing(self):
        claim, bot = await self._run(_order(), claim_result=None)
        claim.assert_awaited_once()
        bot.send_message.assert_not_awaited()

    async def test_manual_and_b2b_orders_skipped(self):
        for src in ("manual", "b2b"):
            claim, _ = await self._run(_order(source=src))
            claim.assert_not_awaited()

    async def test_fully_keto_paid_order_does_not_use_up_cashback(self):
        claim, _ = await self._run(_order(keto_redeemed=100000))
        claim.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
