"""100 Keto start sovg'asi (egasi, 2026-10-13): har bir yangi foydalanuvchiga,
tantanali, o'z tilida, qanday yig'ish va ishlatish bilan. Bot va baza mock —
hech qanday haqiqiy xabar yuborilmaydi."""
import asyncio
import os
import re
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import gamification
import referral_contest
import referral_program as rp
import subscription_gate


def run(coro):
    return asyncio.run(coro)


class AmountTest(unittest.TestCase):
    def test_hundred_for_everyone(self):
        self.assertEqual(rp.WELCOME_KETO, 100)
        self.assertEqual(referral_contest.REFERRAL_KETO_REWARD, 100)   # came by a friend's link


class GrantTest(unittest.TestCase):
    def test_credits_and_waits_for_the_language(self):
        bot = AsyncMock()
        with patch("database.credit_welcome_keto", AsyncMock(return_value=True)) as credit, \
             patch.object(rp, "mark_welcome_pending", AsyncMock()) as pending:
            run(rp.grant_welcome_bonus(bot, 9))
        credit.assert_awaited_once_with(9, 100)
        pending.assert_awaited_once_with(9, 100)
        bot.send_message.assert_not_called()      # language not chosen yet

    def test_already_had_it(self):
        with patch("database.credit_welcome_keto", AsyncMock(return_value=False)), \
             patch.object(rp, "mark_welcome_pending", AsyncMock()) as pending:
            run(rp.grant_welcome_bonus(AsyncMock(), 9))
        pending.assert_not_called()


class CeremonyTextTest(unittest.TestCase):
    def test_uz_tells_what_how_to_collect_and_spend(self):
        text = rp.ceremony_text("uz", "Ali", 100, 100)
        for part in ("Tabriklaymiz, Ali", "100 ta Keto tangacha", "1 ta tangacha = 1 so'm",
                     "Qanday yig'iladi", "Qanday ishlatiladi", "Ketochalarni ishlatish",
                     "Bepul xarid qilish", "Kabinetim"):
            self.assertIn(part, text)

    def test_rates_come_from_gamification(self):
        text = rp.ceremony_text("uz", "Ali", 100, 100)
        self.assertIn("<b>500 ta</b>", text)                     # 0.5% of 100 000
        self.assertIn("Kumush — 1 000", text)
        self.assertIn("Olmos — 3 000", text)
        self.assertIn("<b>3%</b>", text)                          # referral cashback
        with patch.dict(gamification.EARN_RATES, {"bronze": 0.01}):
            self.assertIn("<b>1 000 ta</b>", rp.ceremony_text("uz", "Ali", 100, 100))

    def test_ru(self):
        text = rp.ceremony_text("ru", "Ali", 100, 100)
        self.assertIn("Поздравляем, Ali", text)
        self.assertIn("Использовать Ketочки", text)

    def test_cyrillic_keeps_numbers_and_the_name(self):
        text = rp.ceremony_text("uz_cyr", "Jasur", 100, 1500)
        self.assertIn("Jasur", text)                              # never transliterated
        self.assertIn("1 500", text)
        self.assertNotIn("{", text)
        latin = re.findall(r"[a-zA-Z]+", re.sub(r"<[^>]+>|Ketoshop|Jasur", "", text))
        self.assertEqual(latin, [])

    def test_name_is_escaped_and_has_a_fallback(self):
        self.assertIn("A&lt;b&gt;", rp.ceremony_text("uz", "A<b>", 100, 100))
        self.assertIn("do'stim", rp.ceremony_text("uz", "", 100, 100))
        self.assertIn("друг", rp.ceremony_text("ru", "", 100, 100))

    def test_no_promises_while_keto_is_off(self):
        text = rp.ceremony_text("uz", "Ali", 100, 100, earning=False, spending=False)
        self.assertNotIn("Qanday yig'iladi", text)
        self.assertNotIn("Qanday ishlatiladi", text)

    def test_piggy_bank_taboo(self):
        for lang in ("uz", "ru", "uz_cyr"):
            self.assertNotIn("cho'chqa", rp.ceremony_text(lang, "Ali", 100, 100).lower())


class CelebrateTest(unittest.TestCase):
    def _go(self, pending_amount, balance=100):
        bot = AsyncMock()
        with patch.object(rp, "_pop_welcome_pending", AsyncMock(return_value=pending_amount)), \
             patch("database.get_user", AsyncMock(return_value={"keto_balance": balance})), \
             patch.object(gamification, "is_enabled", AsyncMock(return_value=True)), \
             patch.object(gamification, "is_redemption_enabled", AsyncMock(return_value=True)):
            ok = run(rp.celebrate(bot, 9, "uz", "Ali"))
        return ok, bot

    def test_new_user_gets_the_ceremony(self):
        ok, bot = self._go(100, balance=100)
        self.assertTrue(ok)
        bot.send_message.assert_awaited_once()
        self.assertIn("100 ta Keto", bot.send_message.call_args.args[1])
        datas = [b.callback_data for row in bot.send_message.call_args.kwargs["reply_markup"].inline_keyboard
                 for b in row]
        self.assertEqual(datas, ["kabinetim", "catalog"])

    def test_nobody_else(self):
        # Returning user switching language, or a second tap: nothing pending.
        ok, bot = self._go(None)
        self.assertFalse(ok)
        bot.send_message.assert_not_called()

    def test_never_raises(self):
        with patch.object(rp, "_pop_welcome_pending", AsyncMock(side_effect=RuntimeError("db"))):
            self.assertFalse(run(rp.celebrate(AsyncMock(), 9, "uz", "Ali")))


class GateTest(unittest.TestCase):
    """A brand-new user stopped by the channel gate picks a language after
    subscribing — that tap brings the welcome, the gift and the video."""

    def _confirm(self, is_new):
        from aiogram.types import CallbackQuery
        event = MagicMock(spec=CallbackQuery)
        event.data = subscription_gate.CHECK_CALLBACK
        event.from_user = MagicMock(id=777000111, language_code="uz")
        event.message = AsyncMock()
        event.answer = AsyncMock()
        mw = subscription_gate.SubscriptionGateMiddleware()
        with patch.object(subscription_gate, "_is_subscribed", AsyncMock(return_value=True)), \
             patch("handlers.start.ensure_registered", AsyncMock(return_value=is_new)):
            run(mw(AsyncMock(), event, {"bot": AsyncMock()}))
        return event.message.edit_text.call_args

    def test_new_user_gets_the_language_picker(self):
        call = self._confirm(is_new=True)
        datas = [b.callback_data for row in call.kwargs["reply_markup"].inline_keyboard for b in row]
        self.assertTrue(all(d.startswith("lang:") for d in datas))

    def test_returning_user_just_continues(self):
        call = self._confirm(is_new=False)
        datas = [b.callback_data for row in call.kwargs["reply_markup"].inline_keyboard for b in row]
        self.assertEqual(datas, ["main_menu"])


if __name__ == "__main__":
    unittest.main()
