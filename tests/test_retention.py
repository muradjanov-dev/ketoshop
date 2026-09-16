"""Qayta sotuv (retention.py) — bazaga va Telegram'ga ulanmasdan.

Tekshiriladi: "qachon tugaydi" hisobi, bitta mijozga bitta xabar qoidasi
(ustuvorlik, 7 kun, ochiq buyurtma, savat), birga olinadigan mahsulot,
shaxsiy sovg'a aksiya sovg'asi bilan qo'shilib ikkita bo'lib ketmasligi,
darajali keshbek va har bir xabar mijozning o'z tilida chiqishi.
"""
import asyncio
import os
import re
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import gamification
import gift_campaign
import retention

NOW = datetime(2026, 9, 17, 5, 0)
KOKOS = ("p", 10)
ERIT = ("p", 20)
PSY = ("p", 30)
AVAILABLE = {
    KOKOS: {"id": 10, "name": "Kokos uni 1000gr", "name_ru": "Кокосовая мука 1000г", "quantity": 5},
    ERIT: {"id": 20, "name": "Eritritol 500gr", "name_ru": "Эритрит 500г", "quantity": 5},
    PSY: {"id": 30, "name": "Psillium 250gr", "name_ru": "Псиллиум 250г", "quantity": 5},
}


def order(oid, days_ago, *keys, status="delivered", qty=1):
    at = NOW - timedelta(days=days_ago)
    return {"id": oid, "status": status, "created_at": at,
            "delivered_at": at if status == "delivered" else None,
            "items": [{"product_id": k[1], "quantity": qty, "price": 50000,
                       "name": AVAILABLE[k]["name"]} for k in keys]}


def ctx(**over):
    base = {"product_medians": {}, "shop_median": 30, "available": AVAILABLE, "pairs": {},
            "sent_refs": set(), "offer": None, "last_message_at": None,
            "cart_touched_at": None, "cart_reminded_at": None, "opted_out": False}
    base.update(over)
    return base


class IntervalTest(unittest.TestCase):
    def test_own_rhythm_wins(self):
        orders = [order(1, 58, KOKOS), order(2, 38, KOKOS), order(3, 19, KOKOS)]
        due = retention.replenish_due(orders, {KOKOS: 40}, 30, NOW, AVAILABLE)
        self.assertEqual(len(due), 1)
        self.assertEqual((due[0]["interval"], due[0]["source"], due[0]["days"]), (19, "user", 19))

    def test_product_median_needs_three_gaps(self):
        users = {1: [order(1, 60, ERIT), order(2, 40, ERIT)],
                 2: [order(3, 50, ERIT), order(4, 30, ERIT)]}
        medians, _ = retention.learn_intervals(users)
        self.assertNotIn(ERIT, medians)
        users[3] = [order(5, 45, ERIT), order(6, 25, ERIT)]
        medians, _ = retention.learn_intervals(users)
        self.assertEqual(medians[ERIT], 20)

    def test_split_orders_are_one_restock(self):
        self.assertEqual(retention._gaps([NOW, NOW + timedelta(days=2), NOW + timedelta(days=30)]), [30])

    def test_not_due_yet_and_long_gone(self):
        self.assertEqual(retention.replenish_due([order(1, 12, KOKOS)], {}, 30, NOW, AVAILABLE), [])
        self.assertEqual(retention.replenish_due([order(1, 50, KOKOS)], {}, 30, NOW, AVAILABLE), [])

    def test_sold_out_products_are_not_reminded(self):
        self.assertEqual(retention.replenish_due([order(1, 30, KOKOS)], {}, 30, NOW, {}), [])


class OneMessageRuleTest(unittest.TestCase):
    def test_replenish_for_a_regular(self):
        orders = [order(1, 60, KOKOS), order(2, 30, KOKOS)]
        plan = retention.plan_for_user(1, orders, NOW, ctx())
        self.assertEqual(plan["kind"], "replenish")
        self.assertEqual(plan["items"][0]["key"], KOKOS)

    def test_open_order_blocks_everything(self):
        orders = [order(1, 60, KOKOS), order(2, 30, KOKOS), order(3, 1, ERIT, status="pending")]
        self.assertIsNone(retention.plan_for_user(1, orders, NOW, ctx()))

    def test_seven_day_gap_between_messages(self):
        orders = [order(1, 60, KOKOS), order(2, 30, KOKOS)]
        self.assertIsNone(retention.plan_for_user(1, orders, NOW, ctx(last_message_at=NOW - timedelta(days=3))))
        self.assertIsNotNone(retention.plan_for_user(1, orders, NOW, ctx(last_message_at=NOW - timedelta(days=8))))

    def test_active_cart_is_left_to_the_cart_reminder(self):
        orders = [order(1, 60, KOKOS), order(2, 30, KOKOS)]
        self.assertIsNone(retention.plan_for_user(1, orders, NOW, ctx(cart_touched_at=NOW - timedelta(hours=5))))
        self.assertIsNone(retention.plan_for_user(1, orders, NOW, ctx(cart_reminded_at=NOW - timedelta(hours=5))))

    def test_opt_out_is_respected(self):
        orders = [order(1, 60, KOKOS), order(2, 30, KOKOS)]
        self.assertIsNone(retention.plan_for_user(1, orders, NOW, ctx(opted_out=True)))

    def test_same_reason_is_never_sent_twice(self):
        orders = [order(1, 52, KOKOS), order(2, 26, KOKOS)]
        self.assertEqual(retention.plan_for_user(1, orders, NOW, ctx())["ref"], "replenish:p10:2")
        self.assertIsNone(retention.plan_for_user(1, orders, NOW, ctx(sent_refs={"replenish:p10:2"})))

    def test_second_order_checkin_window(self):
        plan = retention.plan_for_user(1, [order(1, 4, KOKOS)], NOW, ctx())
        self.assertEqual(plan["kind"], "second_checkin")
        self.assertIsNone(retention.plan_for_user(1, [order(1, 9, KOKOS)], NOW, ctx()))

    def test_last_call_beats_replenish(self):
        offer = {"id": 7, "kind": "second_checkin", "expires_at": NOW + timedelta(days=2)}
        plan = retention.plan_for_user(1, [order(1, 30, KOKOS)], NOW, ctx(offer=offer))
        self.assertEqual(plan["kind"], "second_lastcall")
        self.assertEqual(plan["days_left"], 2)

    def test_winback_stages(self):
        gone = lambda d: retention.plan_for_user(1, [order(1, d, PSY)], NOW,
                                                 ctx(available={}))  # nothing to replenish
        self.assertEqual(gone(31)["kind"], "winback_30")
        self.assertIsNone(gone(45))
        self.assertEqual(gone(62)["kind"], "winback_60")
        self.assertEqual(gone(91)["kind"], "winback_90")
        self.assertIsNone(gone(120))

    def test_cross_sell_uses_what_others_bought_together(self):
        together = {u: [order(u, 40, KOKOS, ERIT)] for u in (11, 12, 13)}
        pairs = retention.cross_sell_pairs(together)
        orders = [order(1, 60, KOKOS), order(2, 30, KOKOS)]
        plan = retention.plan_for_user(1, orders, NOW, ctx(pairs=pairs))
        self.assertEqual(plan["also"], (KOKOS, [ERIT]))
        # Already bought recently → not suggested.
        orders.append(order(3, 20, ERIT))
        plan = retention.plan_for_user(1, orders, NOW, ctx(pairs=pairs))
        self.assertIsNone((plan or {}).get("also"))

    def test_also_bought_wording_and_buttons(self):
        for lang, phrase in (("uz", "Siz olgan <b>Kokos uni 1000gr</b> bilan boshqalar <b>Eritritol 500gr</b>, "
                                    "<b>Psillium 250gr</b> ham olishyapti"),
                             ("ru", "Вы взяли <b>Кокосовая мука 1000г</b> — другие покупатели к нему ещё берут"),
                             ("uz_cyr", "Сиз олган <b>Кокос уни 1000гр</b> билан бошқалар")):
            text = retention.also_bought_text(AVAILABLE[KOKOS], [AVAILABLE[ERIT], AVAILABLE[PSY]], lang)
            self.assertIn(phrase, text)
        rows = retention.also_bought_rows([AVAILABLE[ERIT]], "ru")
        self.assertEqual((rows[0][0].text, rows[0][0].callback_data), ("🛒 Эритрит 500г", "product:20"))


_LATIN_WORD = re.compile(r"\b[A-Za-z]{3,}\b")


def _latin_words(text: str) -> set[str]:
    """Latin words left after removing HTML tags, brands and commands."""
    text = re.sub(r"<[^>]+>|/\w+|Ketoshop|Keto|Aziz", " ", text)   # the buyer's own name stays as typed
    return set(_LATIN_WORD.findall(text))


class LanguageTest(unittest.TestCase):
    def _texts(self, plan):
        offer = {"id": 1, "kind": "second_checkin", "expires_at": NOW + timedelta(days=14)}
        gift = {"name": "Eritritol 100gr", "name_ru": "Эритрит 100г", "quantity": 3}
        return {lang: retention.build_text(dict(plan, first_name="Aziz"), lang, gift=gift, offer=offer,
                                           also=(AVAILABLE[KOKOS], [AVAILABLE[PSY]]), quick_ready=True)
                for lang in ("uz", "uz_cyr", "ru")}

    def test_every_kind_in_all_three_languages(self):
        replenish = retention.plan_for_user(1, [order(1, 60, KOKOS), order(2, 30, KOKOS)], NOW, ctx())
        plans = [replenish,
                 {"kind": "second_checkin", "days": 4, "order_id": 1},
                 {"kind": "second_lastcall", "days_left": 2, "order_id": 1},
                 {"kind": "winback_30", "days": 31, "order_id": 1},
                 {"kind": "winback_60", "days": 62, "order_id": 1},
                 {"kind": "winback_90", "days": 91, "order_id": 1}]
        for plan in plans:
            texts = self._texts(plan)
            with self.subTest(kind=plan["kind"]):
                self.assertEqual(_latin_words(texts["uz_cyr"]), set(), texts["uz_cyr"])
                self.assertEqual(_latin_words(texts["ru"]), set(), texts["ru"])
                self.assertTrue(re.search(r"[a-z]{4,}", texts["uz"]))
                for lang in ("uz", "uz_cyr", "ru"):
                    kb = retention.build_keyboard(plan, lang, 5, [AVAILABLE[PSY]])
                    labels = " ".join(b.text for row in kb.inline_keyboard for b in row)
                    if lang != "uz":
                        self.assertEqual(_latin_words(labels), set(), labels)

    def test_replenish_reads_like_the_owner_example(self):
        plan = retention.plan_for_user(1, [order(1, 60, KOKOS), order(2, 30, KOKOS)], NOW, ctx())
        text = self._texts(plan)["uz"]
        self.assertIn("tugab qolmadimi?", text)
        self.assertIn("<b>30 kun oldin</b> olgan edingiz", text)
        self.assertIn("har ~30 kunda", text)

    def test_keto_award_and_card_follow_the_language(self):
        level = gamification.get_level(3500)
        for lang in ("uz_cyr", "ru"):
            award = gamification.build_award_message(lang, 500, 4000, level, True,
                                                     gamification.ACHIEVEMENTS[:1], lifetime=4000)
            card = gamification.build_pin_text(lang, "Азиз", 4000, 4000)
            self.assertEqual(_latin_words(award), set(), award)
            self.assertEqual(_latin_words(card), set(), card)


class LoyaltyTierTest(unittest.TestCase):
    def test_rate_grows_with_level(self):
        self.assertEqual([gamification.rate_label(gamification.earn_rate(k)) for k in (0, 3000, 10000, 30000)],
                         ["0.5%", "1%", "2%", "3%"])

    def test_every_achievement_check_has_its_data(self):
        # A missing ctx key used to abort the whole award after crediting.
        ctx = {"orders_delivered": 1, "keto_lifetime": 500, "order_total": 100_000, "lifetime_spend": 100_000}
        with patch.object(gamification.database, "get_user_achievement_codes", AsyncMock(return_value=set())), \
             patch.object(gamification.database, "unlock_achievement", AsyncMock(return_value=True)):
            unlocked = asyncio.run(gamification._check_new_achievements(1, ctx))
        self.assertEqual([a["code"] for a in unlocked], ["first_order"])

    def test_progress_is_shown_in_money(self):
        # Bronza, 2 000 Keto left to Kumush at 0.5% → 400 000 so'm.
        self.assertIn("400 000 so'm", gamification.next_level_progress(1000, "uz"))
        self.assertEqual(gamification.next_level_progress(40000, "uz"), "")


class OneGiftPerOrderTest(unittest.TestCase):
    GIFT = {"id": 99, "name": "Eritritol 100gr", "name_ru": "Эритрит 100г", "quantity": 10, "price": 12000}

    def run_lines(self, subtotal, offer, campaign):
        with patch.object(retention, "active_offer", AsyncMock(return_value=offer)), \
             patch.object(gift_campaign, "is_active", AsyncMock(return_value=campaign)), \
             patch.object(gift_campaign, "gift_product", AsyncMock(return_value=self.GIFT)):
            return asyncio.run(gift_campaign.gift_lines(555, [{"price": subtotal, "quantity": 1}]))

    def test_personal_gift_on_a_small_order(self):
        lines = self.run_lines(40_000, {"id": 7, "expires_at": NOW}, campaign=True)
        self.assertEqual(len(lines), 1)
        self.assertEqual((lines[0]["retention_offer_id"], lines[0]["promo_name"]), (7, "Shaxsiy sovg'a"))

    def test_campaign_order_spends_the_offer_with_one_gift(self):
        lines = self.run_lines(150_000, {"id": 7, "expires_at": NOW}, campaign=True)
        self.assertEqual(len(lines), 1)
        self.assertEqual((lines[0]["retention_offer_id"], lines[0]["promo_name"]), (7, "Sovg'a"))

    def test_no_offer_no_campaign_no_gift(self):
        self.assertEqual(self.run_lines(40_000, None, campaign=True), [])
        self.assertEqual(self.run_lines(150_000, None, campaign=False), [])

    def test_offer_tag_is_what_the_spent_check_matches(self):
        import json
        blob = json.dumps(self.run_lines(40_000, {"id": 7, "expires_at": NOW}, campaign=False))
        self.assertRegex(blob, r'"retention_offer_id": 7[,}]')
        self.assertNotRegex(blob, r'"retention_offer_id": 71[,}]')


if __name__ == "__main__":
    unittest.main()
