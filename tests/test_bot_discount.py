"""Bot orqali buyurtmaga 10% chegirma va uning e'lon kampaniyasi —
Telegram va bazaga ulanmasdan. Hech qanday xabar haqiqatan yuborilmaydi."""
import asyncio
import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import bot_discount
import bot_discount_campaign as campaign
import database
from config import ADMIN_IDS

BUYER = 555000111


def run(coro):
    return asyncio.run(coro)


def line(price, qty=1, original=None, **kw):
    return {"product_id": 1, "name": "Bodom uni", "unit": "piece", "quantity": qty,
            "price": price, "original_price": original if original is not None else price,
            "discount_percent": 0, **kw}


class ApplyTest(unittest.TestCase):
    """Narx hisobi. Tannarx bazadan olinadi — bu yerda _cost_maps almashtiriladi."""

    def setUp(self):
        self.costs = ({}, {})            # {product_id: (cost, known)}, {set_id: ...}
        patcher = patch.object(bot_discount, "_cost_maps", AsyncMock(side_effect=lambda items: self.costs))
        patcher.start()
        self.addCleanup(patcher.stop)

    def apply(self, items, percent=10):
        return run(bot_discount.apply(items, percent))

    def test_ten_percent_off_every_paid_line(self):
        items = [line(45000, 2), line(120000, product_id=2)]
        saved = self.apply(items)
        self.assertEqual(saved, 4500 * 2 + 12000)
        self.assertEqual([it["price"] for it in items], [40500, 108000])
        self.assertEqual([it["original_price"] for it in items], [45000, 120000])
        self.assertEqual([it["discount_percent"] for it in items], [10, 10])
        self.assertTrue(all(it["bot_discount"] == 10 for it in items))

    def test_any_amount_even_one_cheap_item(self):
        self.assertEqual(self.apply([line(9000)]), 900)

    def test_gifts_and_bonuses_are_untouched(self):
        items = [line(0, is_bonus=True), line(0, is_gift=True)]
        self.assertEqual(self.apply(items), 0)
        self.assertNotIn("bot_discount", items[0])

    def test_does_not_stack_with_a_product_discount(self):
        # 🔥-20% already cheaper than -10% → the product's own price stays.
        bigger = [line(80000, original=100000, discount_percent=20)]
        self.assertEqual(self.apply(bigger), 0)
        self.assertEqual(bigger[0]["price"], 80000)
        # 🔥-5% → -10% of the shelf price wins, not -5% then -10%.
        smaller = [line(95000, original=100000, discount_percent=5)]
        self.assertEqual(self.apply(smaller), 5000)
        self.assertEqual(smaller[0]["price"], 90000)

    def test_zero_percent_changes_nothing(self):
        items = [line(45000)]
        self.assertEqual(self.apply(items, 0), 0)
        self.assertEqual(items[0]["price"], 45000)

    def test_never_below_cost(self):
        # Shelf 100 000, cost 95 000 → only 5 000 off, never 90 000.
        self.costs = ({1: (95000.0, True)}, {})
        items = [line(100000, 2)]
        self.assertEqual(self.apply(items), 10000)
        self.assertEqual(items[0]["price"], 95000)
        self.assertEqual(items[0]["discount_percent"], 5)

    def test_no_margin_no_discount(self):
        self.costs = ({1: (100000.0, True)}, {})
        items = [line(100000)]
        self.assertEqual(self.apply(items), 0)
        self.assertEqual(items[0]["price"], 100000)
        self.assertNotIn("bot_discount", items[0])

    def test_fractional_cost_rounds_up(self):
        self.costs = ({1: (91234.4, True)}, {})
        items = [line(100000)]
        self.apply(items)
        self.assertEqual(items[0]["price"], 91235)

    def test_healthy_margin_gets_the_full_ten(self):
        self.costs = ({1: (60000.0, True)}, {})
        items = [line(100000)]
        self.assertEqual(self.apply(items), 10000)

    def test_set_is_floored_by_its_components_cost(self):
        self.costs = ({}, {7: (115000.0, True)})
        items = [{"set_id": 7, "is_set": True, "name": "Set", "unit": "piece", "quantity": 1,
                  "price": 120000, "original_price": 120000, "discount_percent": 0}]
        self.assertEqual(self.apply(items), 5000)

    def test_unknown_cost_gets_the_full_ten(self):
        self.costs = ({1: (0.0, False)}, {})
        self.assertEqual(self.apply([line(100000)]), 10000)

    def test_cart_saving_matches_checkout(self):
        rows = [{"product_id": 1, "price": 45000, "cart_quantity": 2, "discount_percent": 0},
                {"set_id": 7, "price": 120000, "cart_quantity": 1, "is_set": True}]
        self.assertEqual(run(bot_discount.cart_saving(rows, 10)), 4500 * 2 + 12000)
        self.assertEqual(run(bot_discount.cart_saving(rows, 0)), 0)
        self.costs = ({1: (44000.0, True)}, {7: (115000.0, True)})
        self.assertEqual(run(bot_discount.cart_saving(rows, 10)), 1000 * 2 + 5000)


class MarginReportTextTest(unittest.TestCase):
    def test_lists_capped_and_missing_cost(self):
        text = bot_discount.margin_report_text({
            "total": 3,
            "capped": [{"name": "Kokos <yog'i>", "price": 100000, "cost": 95000, "new": 95000, "percent": 5.0}],
            "no_cost": [{"name": "Chia", "price": 30000}],
        })
        self.assertIn("Kokos &lt;yog'i&gt; — 100 000 → 95 000 (tannarx 95 000, chegirma 5%)", text)
        self.assertIn("Tannarxi kiritilmagan (1 ta)", text)
        self.assertIn("• Chia — 30 000", text)

    def test_all_fine(self):
        text = bot_discount.margin_report_text({"total": 2, "capped": [], "no_cost": []})
        self.assertIn("zararsiz", text)


class EligibilityTest(unittest.TestCase):
    def tearDown(self):
        bot_discount._cache.update(at=0.0, active=False)

    def _active(self, on):
        bot_discount._cache.update(at=10**12, active=on)   # fresh cache, no DB

    def test_buyer_gets_it_only_while_on(self):
        self._active(True)
        self.assertEqual(run(bot_discount.percent_for(BUYER)), 10)
        self._active(False)
        self.assertEqual(run(bot_discount.percent_for(BUYER)), 0)

    def test_admins_and_internal_accounts_never(self):
        self._active(True)
        self.assertEqual(run(bot_discount.percent_for(next(iter(ADMIN_IDS)))), 0)
        for uid in database.LEADERBOARD_EXCLUDED_USER_IDS:
            self.assertEqual(run(bot_discount.percent_for(uid)), 0)

    def test_reminder_follows_the_switch(self):
        self._active(True)
        self.assertIn("istalgan summaga 10% chegirma", run(bot_discount.reminder("uz")))
        self.assertIn("10%", run(bot_discount.reminder("ru")))
        self.assertIn("исталган", run(bot_discount.reminder("uz_cyr")))
        self.assertTrue(run(bot_discount.footer("uz")).startswith("\n\n🎁"))
        self.assertIn("@", run(bot_discount.channel_footer()))
        self._active(False)
        self.assertEqual(run(bot_discount.reminder("uz")), "")
        self.assertEqual(run(bot_discount.footer("uz")), "")
        self.assertEqual(run(bot_discount.channel_footer()), "")

    def test_admin_sees_the_customer_view_but_never_gets_it(self):
        admin = next(iter(ADMIN_IDS))
        self._active(True)
        self.assertEqual(run(bot_discount.percent_for(admin)), 0)          # order: full price
        self.assertEqual(run(bot_discount.preview_percent_for(admin)), 10)  # cart: shown
        self.assertEqual(run(bot_discount.preview_percent_for(BUYER)), 0)   # buyers get the real one
        self.assertIn("qo'llanmadi", bot_discount.admin_checkout_note("uz", 10))
        self._active(False)
        self.assertEqual(run(bot_discount.preview_percent_for(admin)), 0)

    def test_site_banner_only_while_on(self):
        self._active(True)
        banner = run(bot_discount.site_banner("uz"))
        self.assertEqual(banner["title"], "Bot orqali buyurtmaga 10% chegirma")
        self.assertIn("Istalgan summaga", banner["sub"])
        self.assertIn("Скидка 10%", run(bot_discount.site_banner("ru"))["title"])
        self._active(False)
        self.assertIsNone(run(bot_discount.site_banner("uz")))

    def test_saving_line(self):
        self.assertEqual(bot_discount.saving_line("uz", 10, 12300),
                         "🎁 Bot orqali buyurtma chegirmasi (−10%): <b>−12 300 so'm</b>")


class CheckoutSummaryTest(unittest.TestCase):
    """handlers.cart._build_order_summary: narx qatorlarda, bepul yetkazish
    chegirmagacha bo'lgan summadan."""

    def setUp(self):
        bot_discount._cache.update(at=10**12, active=True)

    def tearDown(self):
        bot_discount._cache.update(at=0.0, active=False)

    def summary(self, user_id, cart_rows, delivery="self"):
        import handlers.cart as cart
        import gamification
        import gift_campaign
        import promotions
        data = {"delivery_method": delivery, "payment_method": "cash", "phone": "+998901234567",
                "address": "Chilonzor"}
        with patch.object(cart, "get_cart", AsyncMock(return_value=cart_rows)), \
             patch.object(bot_discount, "_cost_maps", AsyncMock(return_value=({}, {}))), \
             patch.object(promotions, "bonuses_for_items", AsyncMock(return_value=[])), \
             patch.object(promotions, "get_active", AsyncMock(return_value=None)), \
             patch.object(gift_campaign, "gift_lines", AsyncMock(return_value=[])), \
             patch.object(gift_campaign, "cart_hint", AsyncMock(return_value="")), \
             patch.object(gamification, "buyer_rate", AsyncMock(return_value=0)):
            return run(cart._build_order_summary(user_id, data, "uz"))

    @staticmethod
    def row(price, qty):
        return {"product_id": 1, "name": "Bodom uni", "unit": "piece", "price": price,
                "cart_quantity": qty, "discount_percent": 0, "discount_until": None}

    def test_buyer_pays_ninety_percent_and_sees_the_line(self):
        text, total, items, _ = self.summary(BUYER, [self.row(100000, 2)])
        self.assertEqual(items[0]["price"], 90000)
        self.assertEqual(items[0]["original_price"], 100000)
        self.assertEqual(total, 180000 + 25000)            # + courier under 800 000
        self.assertIn("−20 000 so'm", text)
        self.assertIn("🎁-10%", text)

    def test_free_delivery_measured_before_the_discount(self):
        # 850 000 on the shelf → 765 000 to pay, delivery stays free.
        _, total, _, _ = self.summary(BUYER, [self.row(850000, 1)])
        self.assertEqual(total, 765000)

    def test_admin_order_is_full_price(self):
        _, total, items, _ = self.summary(next(iter(ADMIN_IDS)), [self.row(100000, 2)])
        self.assertEqual(items[0]["price"], 100000)
        self.assertEqual(total, 200000 + 25000)


class CampaignScheduleTest(unittest.TestCase):
    T0 = datetime(2026, 10, 8, 5, 0)

    def test_first_step_starts_right_away(self):
        self.assertEqual(campaign.next_due({}, self.T0), "teaser1")

    def test_two_hours_between_steps(self):
        steps = {"teaser1": {"started_at": self.T0, "finished_at": self.T0 + timedelta(minutes=3)}}
        self.assertIsNone(campaign.next_due(steps, self.T0 + timedelta(minutes=119)))
        self.assertEqual(campaign.next_due(steps, self.T0 + timedelta(hours=2)), "teaser2")
        steps["teaser2"] = {"started_at": self.T0 + timedelta(hours=2),
                            "finished_at": self.T0 + timedelta(hours=2, minutes=3)}
        self.assertIsNone(campaign.next_due(steps, self.T0 + timedelta(hours=3)))
        self.assertEqual(campaign.next_due(steps, self.T0 + timedelta(hours=4)), "announce")

    def test_unfinished_step_resumes_after_a_restart(self):
        steps = {"teaser1": {"started_at": self.T0, "finished_at": None}}
        self.assertEqual(campaign.next_due(steps, self.T0 + timedelta(minutes=1)), "teaser1")

    def test_done_when_all_finished(self):
        done = {s: {"started_at": self.T0, "finished_at": self.T0} for s in campaign.STEPS}
        self.assertIsNone(campaign.next_due(done, self.T0 + timedelta(days=1)))

    def test_only_daytime(self):
        day = datetime(2026, 10, 8)
        self.assertFalse(campaign.in_window(day.replace(hour=8, minute=59)))
        self.assertTrue(campaign.in_window(day.replace(hour=9)))
        self.assertTrue(campaign.in_window(day.replace(hour=20, minute=59)))
        self.assertFalse(campaign.in_window(day.replace(hour=21)))


class CampaignMessageTest(unittest.TestCase):
    def test_teasers_sell_nothing(self):
        for step in ("teaser1", "teaser2"):
            for lang in ("uz", "uz_cyr", "ru"):
                text, markup = campaign.build_message(step, lang)
                self.assertIsNone(markup)
                self.assertNotIn("10%", text)       # the number waits for the announcement

    def test_announcement_has_the_button_in_every_language(self):
        for lang, label in (("uz", "🎁 10% chegirmani olish"), ("ru", "🎁 Получить скидку 10%"),
                            ("uz_cyr", "🎁 10% чегирмани олиш")):
            text, markup = campaign.build_message("announce", lang)
            self.assertIn("10%", text)
            self.assertEqual(markup.inline_keyboard[0][0].text, label)

    def test_channel_versions_are_cyrillic_with_a_link(self):
        text, markup = campaign.build_channel_message("teaser1")
        self.assertIn("Ассалому алайкум", text)
        self.assertIsNone(markup)
        text, markup = campaign.build_channel_message("announce")
        self.assertIn("@", text)
        self.assertTrue(markup.inline_keyboard[0][0].url.startswith("https://t.me/"))

    def test_no_pushy_words(self):
        for step in campaign.STEPS:
            for lang in ("uz", "ru"):
                text = campaign.build_message(step, lang)[0].lower()
                for word in ("shoshiling", "faqat bugun", "oxirgi imkoniyat", "спешите", "только сегодня"):
                    self.assertNotIn(word, text)


class CampaignRunTest(unittest.TestCase):
    """run_step: e'londa chegirma AVVAL yoqiladi, kanal + har mijozga bittadan."""

    def test_announce_switches_on_first_then_sends(self):
        order = []
        sent_to = []

        async def fake_set_active(on, by=None):
            order.append("on")
            return []

        async def fake_send(bot, chat_id, text, markup):
            order.append("send")
            sent_to.append(chat_id)
            return chat_id != 2

        audience = [{"user_id": 1, "language": "uz"}, {"user_id": 2, "language": "ru"}]
        marks = []
        with patch.object(bot_discount, "is_active", AsyncMock(return_value=False)), \
             patch.object(bot_discount, "set_active", fake_set_active), \
             patch.object(database, "get_interest_state", AsyncMock(return_value={}), create=True), \
             patch.object(database, "advance_interest", AsyncMock(), create=True), \
             patch.object(campaign, "_done", AsyncMock(return_value=False)), \
             patch.object(campaign, "_audience", AsyncMock(return_value=audience)), \
             patch.object(campaign, "_mark", AsyncMock(side_effect=lambda s, c, ok: marks.append((c, ok)))), \
             patch.object(campaign, "_send_one", fake_send), \
             patch.object(campaign, "SEND_DELAY", 0):
            sent, failed, _ = run(campaign.run_step(object(), "announce"))

        self.assertEqual(order[0], "on")
        self.assertEqual(sent_to, [campaign.REQUIRED_CHANNEL_ID, 1, 2])
        self.assertEqual((sent, failed), (1, 1))
        self.assertIn((2, False), marks)      # blocked — recorded, never retried

    def test_teaser_does_not_switch_anything_on(self):
        set_active = AsyncMock()
        with patch.object(bot_discount, "set_active", set_active), \
             patch.object(campaign, "_done", AsyncMock(return_value=True)), \
             patch.object(campaign, "_audience", AsyncMock(return_value=[])):
            run(campaign.run_step(object(), "teaser1"))
        set_active.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
