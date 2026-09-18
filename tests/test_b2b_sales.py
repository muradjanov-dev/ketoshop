"""B2B savdolar ekrani — kim, qachon, nima olgani va foyda rost ko'rinishi."""
import asyncio
import os
import unittest
from datetime import datetime

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("ADMIN_WEB_PASSWORD", "test")

import admin_web
import handlers.admin as admin


def _order(**kw):
    base = {
        "id": 1, "customer_name": "Firma", "phone": "", "address": "",
        "dt": datetime(2026, 9, 18, 9, 0), "status": "delivered",
        "items": [{"name": "Eritritol (B2B)", "quantity": 12, "unit": "kg", "bulk": True}],
        "total": 4_200_000, "cost": 360_000, "profit": 3_840_000, "cost_known": True,
    }
    base.update(kw)
    return base


def render(orders, page=0):
    async def fake():
        return orders
    original = admin.get_b2b_orders
    admin.get_b2b_orders = fake
    try:
        return asyncio.run(admin._render_b2b_sales(page))
    finally:
        admin.get_b2b_orders = original


class B2BSalesScreenTest(unittest.TestCase):
    def test_lists_who_bought_what_and_when(self):
        text, _ = render([_order(id=412, customer_name="Shirin Non MCHJ",
                                 phone="+998901112233")])
        self.assertIn("#412", text)
        self.assertIn("Shirin Non MCHJ", text)
        self.assertIn("+998901112233", text)
        self.assertIn("18.09.2026", text)
        self.assertIn("Eritritol (B2B)", text)

    def test_wholesale_quantity_keeps_its_real_unit(self):
        # A `bulk` line's quantity IS a weight — "0.5 dona" would be nonsense.
        text, _ = render([_order(items=[{"name": "Eritritol (B2B)", "quantity": 0.5,
                                         "unit": "kg", "bulk": True}])])
        self.assertIn("0.5 kg", text)
        self.assertNotIn("0.5 dona", text)

    def test_says_the_money_is_not_on_top_of_the_usual_revenue(self):
        # B2B revenue is inside get_admin_stats' revenue, so the screen must
        # not read as a second pile of money to be added.
        text, _ = render([_order()])
        self.assertIn("umumiy tushum ichida", text)

    def test_uncosted_sale_is_flagged(self):
        text, _ = render([_order(cost_known=False, cost=0, profit=4_200_000)])
        self.assertIn("⚠️", text)
        self.assertIn("tannarxi kiritilmagan", text)

    def test_costed_sale_carries_no_warning(self):
        text, _ = render([_order()])
        self.assertNotIn("⚠️", text)

    def test_long_item_list_is_trimmed(self):
        items = [{"name": f"Mahsulot {i}", "quantity": 1, "unit": "piece"}
                 for i in range(9)]
        text, _ = render([_order(items=items)])
        self.assertIn("va yana 5 ta", text)

    def test_paginates_and_clamps_out_of_range_pages(self):
        orders = [_order(id=i) for i in range(12)]
        _, kb = render(orders, page=0)
        self.assertTrue(any(b.callback_data == "admin:b2b_sales:1"
                            for row in kb.inline_keyboard for b in row))
        text, _ = render(orders, page=99)
        self.assertIn("📄 3 / 3", text)

    def test_empty_state(self):
        text, kb = render([])
        self.assertIn("Hali B2B savdo kiritilmagan", text)
        self.assertTrue(kb.inline_keyboard)

    def test_stays_inside_telegram_message_limit(self):
        items = [{"name": "A" * 60, "quantity": 1, "unit": "piece"} for _ in range(9)]
        orders = [_order(id=i, customer_name="B" * 60, phone="+998" + "9" * 9,
                         items=items) for i in range(12)]
        text, _ = render(orders)
        self.assertLess(len(text), 4000)


class DashboardPayloadTest(unittest.TestCase):
    """What /admin/api/dashboard hands the browser for each wholesale sale."""

    def test_timestamp_is_formatted_server_side(self):
        # Orders carry naive UTC. Shipping one raw would have the browser read
        # it as local time and shift every B2B sale by five hours.
        row = admin_web._b2b_sale_json(_order(dt=datetime(2026, 9, 18, 9, 0)))
        self.assertEqual(row["when"], "18.09.2026 14:00")

    def test_missing_timestamp_does_not_explode(self):
        self.assertEqual(admin_web._b2b_sale_json(_order(dt=None))["when"], "")

    def test_wholesale_line_keeps_its_weight_unit(self):
        row = admin_web._b2b_sale_json(_order(
            items=[{"name": "Eritritol (B2B)", "quantity": 0.5, "unit": "kg", "bulk": True}]))
        self.assertEqual(row["items"][0]["unit"], "kg")
        self.assertEqual(row["items"][0]["quantity"], 0.5)

    def test_retail_line_is_shown_as_pieces(self):
        row = admin_web._b2b_sale_json(_order(
            items=[{"name": "Bodom uni 1000gr", "quantity": 20, "unit": "kg"}]))
        self.assertEqual(row["items"][0]["unit"], "dona")

    def test_carries_the_costing_verdict_through(self):
        self.assertFalse(admin_web._b2b_sale_json(_order(cost_known=False))["cost_known"])
        self.assertTrue(admin_web._b2b_sale_json(_order())["cost_known"])

    def test_payload_is_json_serialisable(self):
        import json
        json.dumps(admin_web._b2b_sale_json(_order()))


if __name__ == "__main__":
    unittest.main()
