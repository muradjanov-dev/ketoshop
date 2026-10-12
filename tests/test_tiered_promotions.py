"""Stevia tiers use one gift, with stock counted in retail packs."""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import admin_web
import promotions
import webapp_server
import ai_sales


def stevia_promo():
    return {
        "name": "Stevia bonus",
        "bonus_mode": "tiered",
        "days": 0,
        "ends_at": None,
        "bonuses": [
            {"trigger_product_id": 124, "trigger_quantity": threshold,
             "trigger_name": "Stevia 1000g", "trigger_unit": "piece",
             "bonus_product_id": pid, "bonus_amount": grams,
             "bonus_unit": "gr", "bonus_stock_qty": packs,
             "bonus_name": name, "bonus_price": price}
            for threshold, pid, grams, packs, name, price in [
                (1, 101, 200, 1, "Stevia 200gr", 33000),
                (2, 123, 500, 1, "Stevia 500g", 76000),
                (4, 124, 2000, 2, "Stevia 1000g", 150000),
            ]
        ],
    }


class TieredBonusTests(unittest.TestCase):
    def test_only_highest_qualified_tier_is_given_once(self):
        for qty, grams, pid, packs, value in [
            (1, 200, 101, 1, 33000), (1.999, 200, 101, 1, 33000),
            (2, 500, 123, 1, 76000), (3, 500, 123, 1, 76000),
            (3.999, 500, 123, 1, 76000), (4, 2000, 124, 2, 300000),
            (5, 2000, 124, 2, 300000), (8, 2000, 124, 2, 300000),
        ]:
            with self.subTest(qty=qty):
                lines = promotions.compute_bonuses(stevia_promo(), [{"product_id": 124, "quantity": qty}])
                self.assertEqual(len(lines), 1)
                line = lines[0]
                self.assertEqual((line["quantity"], line["product_id"], line["stock_quantity"]),
                                 (grams, pid, packs))
                self.assertEqual(line["price"], 0)
                self.assertEqual(line["bonus_value"], value)
                self.assertTrue(line["cost_in_expenses"])

    def test_below_first_tier_and_other_products_earn_nothing(self):
        for items in [[{"product_id": 124, "quantity": .999}],
                      [{"product_id": 128, "quantity": 4}]]:
            self.assertEqual(promotions.compute_bonuses(stevia_promo(), items), [])

    def test_split_rows_are_summed_and_bonus_and_set_rows_are_ignored(self):
        items = [{"product_id": 124, "quantity": 1}, {"product_id": 124, "quantity": 1},
                 {"product_id": 124, "quantity": 4, "is_bonus": True},
                 {"product_id": 124, "quantity": 4, "is_set": True}]
        lines = promotions.compute_bonuses(stevia_promo(), items)
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["quantity"], 500)

    def test_rule_order_does_not_change_selected_tier(self):
        promo = stevia_promo()
        promo["bonuses"].reverse()
        lines = promotions.compute_bonuses(promo, [{"product_id": 124, "quantity": 2}])
        self.assertEqual([b["quantity"] for b in lines], [500])

    def test_top_tier_can_display_kilograms_with_two_stock_packs(self):
        promo = stevia_promo()
        promo["bonuses"][-1].update(bonus_amount=2, bonus_unit="kg")
        lines = promotions.compute_bonuses(promo, [{"product_id": 124, "quantity": 8}])
        self.assertEqual([(b["quantity"], b["unit"], b["stock_quantity"]) for b in lines], [(2, "kg", 2)])

    def test_nudge_offers_only_next_tier_and_stops_at_last(self):
        for qty, needed, gift in [(1, 1, 500), (2, 2, 2000), (3, 1, 2000)]:
            with self.subTest(qty=qty):
                misses = promotions.compute_near_misses(stevia_promo(), [{"product_id": 124, "quantity": qty}])
                self.assertEqual([(m["needed"], m["bonus_amount"]) for m in misses], [(needed, gift)])
        self.assertEqual(promotions.compute_near_misses(stevia_promo(), [{"product_id": 124, "quantity": 8}]), [])

    def test_product_hint_includes_all_three_tiers(self):
        hint = promotions.bonus_hint(stevia_promo(), 124, "uz")
        for amount in ("200 gr", "500 gr", "2000 gr"):
            self.assertIn(amount, hint)

    def test_showcase_does_not_sum_mutually_exclusive_gifts(self):
        promo = stevia_promo()
        text = promotions.showcase_text(promo, promo["bonuses"], "uz")
        self.assertIn("300 000", text)
        self.assertNotIn("409 000", text)
        self.assertIn("eng yuqori bosqich", text)

    def test_mass_gifts_deduct_packs_instead_of_grams(self):
        for amount, unit, name, expected in [
            (200, "gr", "Stevia 200gr", 1), (500, "gr", "Stevia 500g", 1),
            (2000, "gr", "Stevia 1000g", 2), (2, "kg", "Stevia 1000g", 2),
        ]:
            with self.subTest(name=name, unit=unit):
                self.assertEqual(promotions.to_stock_qty(amount, unit, "piece", name), expected)


class PromotionAdminTests(unittest.IsolatedAsyncioTestCase):
    def request(self, body):
        return SimpleNamespace(json=AsyncMock(return_value=body), match_info={"id": "9"}, can_read_body=True)

    async def test_admin_can_save_permanent_tiered_campaign(self):
        create = AsyncMock(return_value=9)
        with patch.object(admin_web, "ADMIN_WEB_PASSWORD", "test"), patch.object(admin_web, "_authed", return_value=True), \
             patch.object(admin_web.database, "create_promotion", create), \
             patch.object(admin_web.database, "set_promotion_bonuses", AsyncMock()):
            response = await admin_web.api_promos_create(self.request({"name": "Stevia", "days": 0, "bonus_mode": "tiered"}))
        self.assertEqual(response.status, 200)
        self.assertEqual(create.await_args.kwargs["days"], 0)
        self.assertEqual(create.await_args.kwargs["bonus_mode"], "tiered")

    async def test_admin_rejects_unknown_bonus_mode(self):
        with patch.object(admin_web, "ADMIN_WEB_PASSWORD", "test"), patch.object(admin_web, "_authed", return_value=True), \
             patch.object(admin_web.database, "create_promotion", AsyncMock(return_value=9)), \
             patch.object(admin_web.database, "set_promotion_bonuses", AsyncMock()):
            response = await admin_web.api_promos_create(self.request({"name": "Stevia", "bonus_mode": "unknown"}))
        self.assertEqual(response.status, 400)

    async def test_admin_can_start_permanent_campaign(self):
        start = AsyncMock(return_value={"id": 9, "days": 0})
        with patch.object(admin_web, "ADMIN_WEB_PASSWORD", "test"), patch.object(admin_web, "_authed", return_value=True), \
             patch.object(admin_web.database, "start_promotion", start), \
             patch.object(promotions, "refresh", AsyncMock()):
            response = await admin_web.api_promos_start(self.request({"days": 0}))
        self.assertEqual(response.status, 200)
        self.assertEqual(start.await_args.args, (9, 0))

    async def test_fractional_or_negative_days_cannot_become_permanent(self):
        for days in (.5, -1, True):
            with self.subTest(days=days), patch.object(admin_web, "ADMIN_WEB_PASSWORD", "test"), \
                 patch.object(admin_web, "_authed", return_value=True), \
                 patch.object(admin_web.database, "create_promotion", AsyncMock(return_value=9)), \
                 patch.object(admin_web.database, "set_promotion_bonuses", AsyncMock()):
                response = await admin_web.api_promos_create(self.request({"name": "Stevia", "days": days}))
                self.assertEqual(response.status, 400)

    async def test_parser_converts_mass_to_retail_pack_quantity(self):
        products = {101: {"unit": "piece", "name": "Stevia 200gr"},
                    124: {"unit": "piece", "name": "Stevia 1000g"}}
        with patch.object(admin_web.database, "get_product", AsyncMock(side_effect=lambda pid: products[pid])):
            rules = await admin_web._parse_bonus_rules([{
                "trigger_product_id": 124, "trigger_quantity": 1, "bonus_product_id": 101,
                "bonus_amount": 200, "bonus_unit": "gr",
            }])
        self.assertEqual(rules[0]["bonus_stock_qty"], 1)


class MiniAppTierTests(unittest.IsolatedAsyncioTestCase):
    async def test_ai_reads_actual_expiry_after_duration_is_edited(self):
        from datetime import datetime, timedelta
        for days, expiry, permanent in [(7, None, True), (0, datetime.utcnow() + timedelta(days=7), False)]:
            promo = stevia_promo()
            promo.update(days=days, ends_at=expiry)
            with self.subTest(days=days), patch.object(promotions, "get_active", AsyncMock(return_value=promo)):
                text = await ai_sales._promo_text()
            self.assertEqual("o'chirilguncha" in text, permanent)

    async def test_cart_displays_one_gift_without_changing_paid_total(self):
        for qty, amount, value in [(1, "200", 33000), (2, "500", 76000), (4, "2000", 300000), (8, "2000", 300000)]:
            with self.subTest(qty=qty), \
                 patch.object(webapp_server, "get_cart", AsyncMock(return_value=[{
                     "cart_id": 1, "product_id": 124, "name": "Stevia 1000g", "price": 150000,
                     "cart_quantity": qty, "unit": "piece", "stock": 20,
                 }])), patch.object(promotions, "get_active", AsyncMock(return_value=stevia_promo())), \
                 patch("gift_campaign.gift_lines", AsyncMock(return_value=[])), \
                 patch("gift_campaign.cart_hint", AsyncMock(return_value="")), \
                 patch("bot_discount.percent_for", AsyncMock(return_value=0)), \
                 patch("bot_discount.preview_percent_for", AsyncMock(return_value=0)):
                response = await webapp_server.api_cart({"user_id": 999, "user_lang": "uz"})
                result = json.loads(response.text)
                self.assertEqual(result["total"], qty * 150000)
                self.assertEqual([(b["amount"], b["unit"], b["value"]) for b in result["bonuses"]],
                                 [(amount, "gr", value)])


if __name__ == "__main__":
    unittest.main()
