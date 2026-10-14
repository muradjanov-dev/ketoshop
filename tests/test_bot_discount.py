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
# Chegirma muddati ichidagi sobit payt (12.10 13:00 Toshkent) — testlar
# 14-oktabrdan keyin ham shu holatni tekshirsin, haqiqiy soatga bog'lanmasin.
DURING = datetime(2026, 10, 12, 8, 0)
_clock = patch.object(bot_discount, "_now_utc", lambda: DURING)


def setUpModule():
    _clock.start()


def tearDownModule():
    _clock.stop()


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

    def test_cost_floor_is_off(self):
        self.assertIs(bot_discount.COST_FLOOR, False)

    def test_full_ten_whatever_the_margin(self):
        # Owner, 2026-10-13: "marjasidan qatiy nazar 10%". Cost 95 000 or even
        # above the shelf price — still 90 000.
        for cost in (95000.0, 100000.0, 120000.0):
            self.costs = ({1: (cost, True)}, {})
            items = [line(100000, 2)]
            self.assertEqual(self.apply(items), 20000)
            self.assertEqual(items[0]["price"], 90000)
            self.assertEqual(items[0]["discount_percent"], 10)

    def test_healthy_margin_gets_the_full_ten(self):
        self.costs = ({1: (60000.0, True)}, {})
        items = [line(100000)]
        self.assertEqual(self.apply(items), 10000)

    def test_set_gets_the_full_ten_too(self):
        self.costs = ({}, {7: (115000.0, True)})
        items = [{"set_id": 7, "is_set": True, "name": "Set", "unit": "piece", "quantity": 1,
                  "price": 120000, "original_price": 120000, "discount_percent": 0}]
        self.assertEqual(self.apply(items), 12000)

    def test_unknown_cost_gets_the_full_ten(self):
        self.costs = ({1: (0.0, False)}, {})
        self.assertEqual(self.apply([line(100000)]), 10000)

    def test_cart_saving_matches_checkout(self):
        rows = [{"product_id": 1, "price": 45000, "cart_quantity": 2, "discount_percent": 0},
                {"set_id": 7, "price": 120000, "cart_quantity": 1, "is_set": True}]
        self.assertEqual(run(bot_discount.cart_saving(rows, 10)), 4500 * 2 + 12000)
        self.assertEqual(run(bot_discount.cart_saving(rows, 0)), 0)
        self.costs = ({1: (44000.0, True)}, {7: (115000.0, True)})
        self.assertEqual(run(bot_discount.cart_saving(rows, 10)), 4500 * 2 + 12000)


class CostFloorSwitchTest(unittest.TestCase):
    """COST_FLOOR = True brings the 2026-10-08 rule back: never below cost."""

    def setUp(self):
        self.costs = ({}, {})
        for p in (patch.object(bot_discount, "_cost_maps", AsyncMock(side_effect=lambda items: self.costs)),
                  patch.object(bot_discount, "COST_FLOOR", True)):
            p.start()
            self.addCleanup(p.stop)

    def apply(self, items):
        return run(bot_discount.apply(items, 10))

    def test_never_below_cost(self):
        self.costs = ({1: (95000.0, True)}, {})
        items = [line(100000, 2)]
        self.assertEqual(self.apply(items), 10000)
        self.assertEqual(items[0]["price"], 95000)
        self.assertEqual(items[0]["discount_percent"], 5)

    def test_no_margin_no_discount(self):
        self.costs = ({1: (100000.0, True)}, {})
        items = [line(100000)]
        self.assertEqual(self.apply(items), 0)
        self.assertNotIn("bot_discount", items[0])

    def test_fractional_cost_rounds_up(self):
        self.costs = ({1: (91234.4, True)}, {})
        items = [line(100000)]
        self.apply(items)
        self.assertEqual(items[0]["price"], 91235)


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

    def test_lists_below_cost(self):
        text = bot_discount.margin_report_text({
            "total": 2, "capped": [], "no_cost": [],
            "below_cost": [{"name": "Kokos", "price": 100000, "cost": 95000, "new": 90000, "loss": 5000}],
        })
        self.assertIn("tannarxdan arzon sotiladi (1 ta)", text)
        self.assertIn("• Kokos — 100 000 → 90 000 (tannarx 95 000, har donada −5 000)", text)
        self.assertNotIn("zararsiz", text)

    def test_all_fine(self):
        text = bot_discount.margin_report_text({"total": 2, "capped": [], "below_cost": [], "no_cost": []})
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


def tk(day, hour=12, minute=0):
    """Toshkent vaqtidagi payt → UTC (bot ichida hamma joy UTC bilan ishlaydi)."""
    return datetime(2026, 10, day, hour, minute) - timedelta(hours=5)


class DeadlineTest(unittest.TestCase):
    """Egasi, 2026-10-12: chegirma 7 kun — 14-oktabr 23:59 (Toshkent) gacha."""

    def tearDown(self):
        bot_discount._cache.update(at=0.0, active=False)

    def test_ends_at_the_last_second_of_the_14th(self):
        self.assertFalse(bot_discount.ended(tk(14, 23, 59)))
        self.assertTrue(bot_discount.ended(tk(15, 0, 0)))

    def test_switched_on_is_still_off_after_the_end(self):
        bot_discount._cache.update(at=10**12, active=True)
        with patch.object(bot_discount, "_now_utc", lambda: tk(15, 0, 1)):
            self.assertFalse(run(bot_discount.is_active()))
            self.assertEqual(run(bot_discount.percent_for(BUYER)), 0)
            self.assertEqual(run(bot_discount.reminder("uz")), "")
            self.assertIsNone(run(bot_discount.site_banner("uz")))
        self.assertEqual(run(bot_discount.percent_for(BUYER)), 10)   # DURING

    def test_days_left_counts_today(self):
        self.assertEqual(bot_discount.days_left(tk(12)), 3)
        self.assertEqual(bot_discount.days_left(tk(13, 0, 30)), 2)
        self.assertEqual(bot_discount.days_left(tk(14, 23, 59)), 1)

    def test_deadline_line_in_every_language(self):
        self.assertEqual(bot_discount.deadline_line("uz", tk(12)),
                         "⏳ 14-oktabr kuni oxirigacha amal qiladi — 3 kun qoldi")
        self.assertEqual(bot_discount.deadline_line("ru", tk(13)),
                         "⏳ Действует до 14 октября включительно — осталось 2 дня")
        self.assertIn("14-октябр", bot_discount.deadline_line("uz_cyr", tk(12)))
        self.assertEqual(bot_discount.deadline_line("uz", tk(14)), "⏳ Bugun oxirgi kun — soat 23:59 gacha")
        self.assertEqual(bot_discount.deadline_line("ru", tk(14)), "⏳ Сегодня последний день — до 23:59")

    def test_reminder_and_banner_carry_the_deadline(self):
        bot_discount._cache.update(at=10**12, active=True)
        self.assertIn("3 kun qoldi", run(bot_discount.reminder("uz")))
        self.assertIn("3 kun qoldi", run(bot_discount.footer("uz")))
        self.assertIn("3 kun qoldi", run(bot_discount.channel_footer("uz")))
        self.assertIn("осталось 3 дня", run(bot_discount.site_banner("ru"))["deadline"])

    def test_no_pressure_words(self):
        for now in (tk(12), tk(14)):
            for lang in ("uz", "ru"):
                text = bot_discount.deadline_line(lang, now).lower()
                for word in ("shoshiling", "faqat bugun", "oxirgi imkoniyat", "спешите", "только сегодня"):
                    self.assertNotIn(word, text)


class CountdownTest(unittest.TestCase):
    """"2 kun qoldi" (13-okt) va "oxirgi kun" (14-okt) — faqat o'z kunida, 11:00–21:00."""

    @staticmethod
    def due(steps, day, hour, minute=0):
        return campaign.countdown_due(steps, datetime(2026, 10, day, hour, minute))

    def test_each_reminder_only_on_its_own_day_and_hours(self):
        self.assertIsNone(self.due({}, 11, 12))
        self.assertEqual(self.due({}, 12, 16, 40), "left3")
        left3_done = {"left3": {"started_at": tk(12, 17), "finished_at": tk(12, 17, 5)}}
        self.assertIsNone(self.due(left3_done, 12, 18))
        self.assertIsNone(self.due(left3_done, 13, 10, 59))
        self.assertEqual(self.due({}, 13, 11), "left2")
        self.assertIsNone(self.due({}, 13, 21))
        self.assertIsNone(self.due({}, 15, 12))

    def test_a_missed_day_is_never_sent_late(self):
        # 13-okt butunlay o'tkazib yuborildi → 14-okt faqat "oxirgi kun".
        self.assertEqual(self.due({}, 14, 11), "lastday")
        started = {"left2": {"started_at": tk(13, 11), "finished_at": None}}
        self.assertEqual(self.due(started, 14, 11), "lastday")

    def test_interrupted_send_resumes_the_same_day(self):
        started = {"left2": {"started_at": tk(13, 11), "finished_at": None}}
        self.assertEqual(self.due(started, 13, 15), "left2")
        done = {"left2": {"started_at": tk(13, 11), "finished_at": tk(13, 11, 5)}}
        self.assertIsNone(self.due(done, 13, 15))

    def test_messages_name_the_real_date_and_have_the_button(self):
        for lang, date in (("uz", "14-oktabr"), ("ru", "14 октября"), ("uz_cyr", "14-октябр")):
            text, markup = campaign.build_message("left2", lang)
            self.assertIn(date, text)
            self.assertIn("10%", text)
            self.assertEqual(markup.inline_keyboard[0][0].text,
                             {"uz": "🎁 10% chegirmani olish", "ru": "🎁 Получить скидку 10%",
                              "uz_cyr": "🎁 10% чегирмани олиш"}[lang])
            text, markup = campaign.build_message("lastday", lang)
            self.assertIn("23:59", text)
            self.assertIsNotNone(markup)
        text, markup = campaign.build_channel_message("left2")
        self.assertIn("14-октябр", text)
        self.assertTrue(markup.inline_keyboard[0][0].url.startswith("https://t.me/"))

    def test_no_pushy_words(self):
        for step in campaign.COUNTDOWN_STEPS:
            for lang in ("uz", "ru"):
                text = campaign.build_message(step, lang)[0].lower()
                for word in ("shoshiling", "faqat bugun", "oxirgi imkoniyat", "спешите", "только сегодня"):
                    self.assertNotIn(word, text)

    def _tick(self, now_utc, steps, active=True):
        bot = AsyncMock()
        run_step = AsyncMock(return_value=(5, 1, []))
        claim, finish = AsyncMock(), AsyncMock()
        with patch.object(campaign, "_now_utc", lambda: now_utc), \
             patch.object(campaign, "_steps", AsyncMock(return_value=steps)), \
             patch.object(campaign, "_claim", claim), patch.object(campaign, "_finish", finish), \
             patch.object(campaign, "run_step", run_step), \
             patch.object(bot_discount, "is_active", AsyncMock(return_value=active)):
            run(campaign._countdown_tick(bot))
        return bot, run_step, claim

    def test_tick_sends_the_due_reminder_and_tells_the_admins(self):
        bot, run_step, claim = self._tick(tk(13, 11, 1), {})
        run_step.assert_awaited_once_with(bot, "left2")
        claim.assert_awaited_once_with("left2")
        self.assertIn("«2 kun qoldi» eslatmasi", bot.send_message.await_args_list[0].args[1])

    def test_switched_off_discount_is_not_advertised(self):
        _, run_step, claim = self._tick(tk(13, 11, 1), {}, active=False)
        run_step.assert_not_awaited()
        claim.assert_not_awaited()

    def test_after_the_end_only_the_admins_hear_it_once(self):
        bot, run_step, claim = self._tick(tk(15, 9, 0), {})
        run_step.assert_not_awaited()
        claim.assert_awaited_once_with("ended")
        recipients = {c.args[0] for c in bot.send_message.await_args_list}
        self.assertEqual(recipients, set(ADMIN_IDS))
        self.assertIn("muddati tugadi", bot.send_message.await_args_list[0].args[1])
        bot, _, claim = self._tick(tk(15, 10, 0), {"ended": {"started_at": tk(15, 9), "finished_at": tk(15, 9)}})
        claim.assert_not_awaited()
        bot.send_message.assert_not_awaited()
        bot, _, claim = self._tick(tk(15, 0, 30), {})   # night — waits for 09:00
        claim.assert_not_awaited()


class _FakeConn:
    def __init__(self, products, sets):
        self.products, self.sets = products, sets

    async def fetch(self, sql, *args):
        return self.sets if "product_sets" in sql else self.products


class _FakePool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return pool.conn

            async def __aexit__(self, *exc):
                return False
        return _Ctx()


class PriceListTest(unittest.TestCase):
    """12-oktabr xabari: barcha mahsulotlar asl va chegirmadagi narxi bilan —
    narx checkout bilan bir xil qoida bo'yicha (marjadan qat'i nazar 10%)."""

    PRODUCTS = [
        {"id": 1, "name": "Bodom uni", "name_ru": "Миндальная мука", "category": "flour",
         "price": 120000, "discount_percent": 0, "discount_until": None},
        {"id": 2, "name": "Kokos <yog'i>", "name_ru": None, "category": "flour",
         "price": 50000, "discount_percent": 0, "discount_until": None},
        {"id": 3, "name": "Eritritol", "name_ru": "Эритритол", "category": "sweet",
         "price": 45000, "discount_percent": 0, "discount_until": None},
    ]
    SETS = [{"set_id": 9, "name": "Keto set", "name_ru": "Кето набор", "price": 300000, "is_set": True}]
    COSTS = ({1: (60000.0, True), 2: (49000.0, True), 3: (0.0, False)}, {9: (100000.0, True)})

    def price_list(self):
        with patch.object(database, "pool", _FakePool(_FakeConn(self.PRODUCTS, self.SETS))), \
             patch.object(database, "_order_cost_maps", AsyncMock(return_value=self.COSTS)):
            return run(bot_discount.price_list())

    def test_prices_follow_the_checkout_rule(self):
        items = self.price_list()
        by_name = {i["name"]: (i["base"], i["new"]) for i in items}
        self.assertEqual(by_name["Bodom uni"], (120000, 108000))      # full 10%
        self.assertEqual(by_name["Kokos <yog'i>"], (50000, 45000))    # 10% even under cost
        self.assertEqual(by_name["Eritritol"], (45000, 40500))        # no cost known → 10%
        self.assertEqual(by_name["Keto set"], (300000, 270000))
        self.assertTrue(items[-1]["is_set"])                          # sets come last

    def test_lines_show_old_and_new_price_grouped(self):
        items = self.price_list()
        with patch.object(campaign, "get_category_name", lambda key, lang: {"flour": "Un", "sweet": "Shirinlik"}[key]):
            lines = campaign.price_list_lines(items, "uz")
        self.assertEqual(lines[0], "\n<b>Un</b>")
        self.assertEqual(lines[1], "• Bodom uni — <s>120 000</s> → <b>108 000</b>")
        self.assertIn("&lt;yog'i&gt;", lines[2])                     # names are escaped
        self.assertIn("\n<b>🧺 Setlar</b>", lines)
        with patch.object(campaign, "get_category_name", lambda key, lang: key):
            ru_lines = campaign.price_list_lines(items, "ru")
        self.assertIn("• Миндальная мука — <s>120 000</s> → <b>108 000</b>", ru_lines)
        self.assertIn("\n<b>🧺 Наборы</b>", ru_lines)

    def test_no_discount_no_strikethrough(self):
        line = campaign._price_line({"name": "Suv", "name_ru": None, "base": 5000, "new": 5000}, "uz")
        self.assertEqual(line, "• Suv — 5 000")

    def test_long_list_is_split_and_the_button_comes_last(self):
        items = [{"name": f"Mahsulot {i:03d} uzun nom bilan", "name_ru": None, "category": "flour",
                  "is_set": False, "base": 123000, "new": 110700} for i in range(150)]
        with patch.object(campaign, "get_category_name", lambda key, lang: "Un"):
            msgs = campaign.build_list_messages("left3", "uz", items)
        self.assertGreater(len(msgs), 1)
        self.assertTrue(all(len(text) <= campaign.PART_LIMIT for text, _ in msgs))
        self.assertTrue(all(markup is None for _, markup in msgs[:-1]))
        self.assertEqual(msgs[-1][1].inline_keyboard[0][0].text, "🎁 10% chegirmani olish")
        joined = "\n".join(text for text, _ in msgs)
        for i in range(150):
            self.assertEqual(joined.count(f"Mahsulot {i:03d} "), 1)    # nothing lost or doubled
        self.assertTrue(msgs[0][0].startswith("⏳ <b>10% chegirmaga 3 kun qoldi</b>"))
        self.assertIn("promokodsiz", msgs[-1][0])

    def test_run_step_reads_prices_once_and_sends_every_part(self):
        items = [{"name": "Bodom uni", "name_ru": None, "category": "flour", "is_set": False,
                  "base": 120000, "new": 108000}]
        sent = []

        async def fake_send(bot, chat_id, text, markup):
            sent.append((chat_id, text, markup))
            return True

        price_list = AsyncMock(return_value=items)
        audience = [{"user_id": 1, "language": "uz"}, {"user_id": 2, "language": "uz"},
                    {"user_id": 3, "language": "ru"}]
        with patch.object(bot_discount, "price_list", price_list), \
             patch.object(campaign, "get_category_name", lambda key, lang: "Un"), \
             patch.object(campaign, "PART_LIMIT", 200), \
             patch.object(database, "get_interest_state", AsyncMock(return_value={}), create=True), \
             patch.object(database, "advance_interest", AsyncMock(), create=True), \
             patch.object(campaign, "_done", AsyncMock(return_value=False)), \
             patch.object(campaign, "_audience", AsyncMock(return_value=audience)), \
             patch.object(campaign, "_mark", AsyncMock()), \
             patch.object(campaign, "_send_one", fake_send), \
             patch.object(campaign, "SEND_DELAY", 0):
            ok, failed, _ = run(campaign.run_step(object(), "left3"))
        price_list.assert_awaited_once()
        self.assertEqual((ok, failed), (3, 0))
        per_chat = {}
        for chat_id, text, markup in sent:
            per_chat.setdefault(chat_id, []).append((text, markup))
        self.assertGreater(len(per_chat[1]), 1)                       # split into parts
        self.assertEqual(len(per_chat[1]), len(per_chat[2]))
        self.assertIsNotNone(per_chat[1][-1][1])
        channel = per_chat[campaign.REQUIRED_CHANNEL_ID]
        self.assertIn("чегирма", channel[0][0])                       # channel in Cyrillic
        self.assertTrue(channel[-1][1].inline_keyboard[0][0].url.startswith("https://t.me/"))
        self.assertTrue(per_chat[3][0][0].startswith("⏳ <b>До конца скидки 10% — 3 дня</b>"))


if __name__ == "__main__":
    unittest.main()
