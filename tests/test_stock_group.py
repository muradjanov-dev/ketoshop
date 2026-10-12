"""Ombor guruhi: kam qolgan / tugagan ro'yxat xodimlar guruhiga, hamma belgilab."""
import asyncio
import os
import unittest
from datetime import datetime
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import stock_alerts

GROUP = -1004478720239
PRODUCTS = [
    {"id": 1, "name": "Eritritol", "quantity": 0, "unit": "piece", "low_stock_threshold": None},
    {"id": 2, "name": "Stevia <tabletka>", "quantity": 3, "unit": "piece", "low_stock_threshold": None},
    {"id": 3, "name": "Bodom uni", "quantity": 40, "unit": "piece", "low_stock_threshold": None},
]


def member(uid, name, status="member", is_bot=False):
    return NS(status=status, user=NS(id=uid, first_name=name, is_bot=is_bot))


def make_bot():
    statuses = {11: member(11, "Ali"), 22: member(22, "Vali", status="left")}
    return NS(
        send_message=AsyncMock(),
        get_chat_administrators=AsyncMock(return_value=[
            member(77, "Guruh egasi", status="creator"),
            member(99, "Ketoshop bot", status="administrator", is_bot=True),
        ]),
        get_chat_member=AsyncMock(side_effect=lambda chat, uid: statuses[uid]),
    )


def at(hour):
    return patch.object(stock_alerts, "_now_tk", return_value=datetime(2026, 10, 12, hour, 0))


class GroupBase(unittest.TestCase):
    def setUp(self):
        for p in (patch.object(stock_alerts, "STOCK_GROUP_ID", GROUP),
                  patch.object(stock_alerts, "ADMIN_IDS", [11, 22])):
            p.start()
            self.addCleanup(p.stop)


class DailyListTest(GroupBase):
    def run_daily(self, hour, claim=True, products=PRODUCTS):
        bot = make_bot()
        with at(hour), \
             patch.object(stock_alerts.database, "get_stock_snapshot", AsyncMock(return_value=products)), \
             patch.object(stock_alerts.database, "claim_stock_group_post",
                          AsyncMock(return_value=claim)) as claim_mock:
            asyncio.run(stock_alerts._maybe_post_group_list(bot))
        return bot, claim_mock

    def test_posts_full_list_with_everyone_tagged(self):
        bot, claim = self.run_daily(10)
        claim.assert_awaited_once_with(GROUP, datetime(2026, 10, 12).date())
        bot.send_message.assert_awaited_once()
        chat, text = bot.send_message.call_args.args
        self.assertEqual(chat, GROUP)
        self.assertIn("Eritritol", text)
        self.assertIn("Stevia &lt;tabletka&gt;", text)
        self.assertNotIn("Bodom uni", text)
        self.assertIn('<a href="tg://user?id=77">Guruh egasi</a>', text)
        self.assertIn('<a href="tg://user?id=11">Ali</a>', text)
        self.assertNotIn("tg://user?id=99", text)   # the bot itself
        self.assertNotIn("tg://user?id=22", text)   # bot admin not in the group

    def test_once_a_day(self):
        bot, _ = self.run_daily(10, claim=False)
        bot.send_message.assert_not_awaited()

    def test_not_at_night(self):
        bot, claim = self.run_daily(7)
        claim.assert_not_awaited()
        bot.send_message.assert_not_awaited()

    def test_nothing_low_nothing_posted(self):
        bot, claim = self.run_daily(10, products=PRODUCTS[2:])
        claim.assert_not_awaited()
        bot.send_message.assert_not_awaited()

    def test_switched_off(self):
        with patch.object(stock_alerts, "STOCK_GROUP_ID", 0):
            bot, claim = self.run_daily(10)
        claim.assert_not_awaited()
        bot.send_message.assert_not_awaited()


class ChangeAlertTest(GroupBase):
    def run_check(self, hour):
        bot = make_bot()
        with at(hour), \
             patch.object(stock_alerts.database, "get_stock_snapshot", AsyncMock(return_value=PRODUCTS)), \
             patch.object(stock_alerts.database, "stock_alerts_initialized", AsyncMock(return_value=True)), \
             patch.object(stock_alerts.database, "get_stock_alert_levels", AsyncMock(return_value={})), \
             patch.object(stock_alerts.database, "set_stock_alert_levels", AsyncMock()), \
             patch.object(stock_alerts.database, "get_user_language", AsyncMock(return_value="uz")):
            sent = asyncio.run(stock_alerts.check_now(bot))
        return bot, sent

    def test_one_group_message_per_sweep(self):
        bot, sent = self.run_check(12)
        self.assertEqual(sent, 2)
        group_msgs = [c.args[1] for c in bot.send_message.call_args_list if c.args[0] == GROUP]
        self.assertEqual(len(group_msgs), 1)
        text = group_msgs[0]
        self.assertIn("Tugadi", text)
        self.assertIn("Eritritol", text)
        self.assertIn("Stevia &lt;tabletka&gt; — <b>3", text)
        self.assertIn("tg://user?id=11", text)
        # Admins still get their own personal alerts.
        admin_chats = [c.args[0] for c in bot.send_message.call_args_list if c.args[0] != GROUP]
        self.assertEqual(sorted(admin_chats), [11, 11, 22, 22])

    def test_group_quiet_at_night(self):
        bot, sent = self.run_check(23)
        self.assertEqual(sent, 2)
        self.assertNotIn(GROUP, [c.args[0] for c in bot.send_message.call_args_list])


class ButtonTest(GroupBase):
    def test_send_group_button(self):
        bot = make_bot()
        cb = NS(from_user=NS(id=11, full_name="Ali"), answer=AsyncMock())
        with patch.object(stock_alerts.database, "get_stock_snapshot", AsyncMock(return_value=PRODUCTS)):
            asyncio.run(stock_alerts.send_stock_to_group(cb, bot))
        chat, text = bot.send_message.call_args.args
        self.assertEqual(chat, GROUP)
        self.assertIn("Yuboruvchi: Ali", text)
        self.assertIn("Eritritol", text)
        self.assertIn("✅", cb.answer.call_args.args[0])

    def test_failed_send_is_reported(self):
        bot = make_bot()
        bot.send_message = AsyncMock(side_effect=RuntimeError("chat not found"))
        cb = NS(from_user=NS(id=11, full_name="Ali"), answer=AsyncMock())
        with patch.object(stock_alerts.database, "get_stock_snapshot", AsyncMock(return_value=PRODUCTS)):
            asyncio.run(stock_alerts.send_stock_to_group(cb, bot))
        self.assertIn("❌", cb.answer.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
