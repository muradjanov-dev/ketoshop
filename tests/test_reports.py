"""Finance Excel export keeps booking values and delivery-period profit distinct."""
import asyncio
import json
import os
import unittest
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from openpyxl import load_workbook

import reports
import admin_web
import database
import handlers.admin as admin_handlers


class MonthlyProductReportTest(unittest.TestCase):
    def test_monthly_product_sales_uses_month_orders_excludes_gifts_and_sorts_by_sales(self):
        class FakeConn:
            def __init__(self):
                self.args = None

            async def fetch(self, sql, *args):
                self.sql = sql
                self.args = args
                return [
                    {"items": [
                        {"product_id": 1, "name": "Small", "quantity": 1, "price": 100},
                        {"product_id": 2, "name": "Large", "quantity": 2, "price": 200},
                        {"product_id": 3, "name": "Gift", "quantity": 5, "price": 0, "is_gift": True},
                        {"product_id": 4, "name": "Bonus", "quantity": 1, "price": 500, "is_bonus": True},
                    ]},
                    {"items": '[{"product_id": 1, "name": "Small", "quantity": 2, "price": 100}]'},
                ]

        class FakePool:
            def __init__(self, conn):
                self.conn = conn

            def acquire(self):
                pool_conn = self.conn
                class Acquire:
                    async def __aenter__(self):
                        return pool_conn

                    async def __aexit__(self, *args):
                        return False
                return Acquire()

        conn = FakeConn()
        with patch.object(database, "pool", FakePool(conn)):
            products = asyncio.run(database.get_monthly_product_sales(2026, 10))

        self.assertEqual([p["name"] for p in products], ["Large", "Small"])
        self.assertEqual(products[0]["qty"], 2)
        self.assertEqual(products[0]["revenue"], 400)
        self.assertEqual(products[1]["qty"], 3)
        self.assertEqual(products[1]["revenue"], 300)
        self.assertIn("created_at >= $1", conn.sql)
        self.assertIn("created_at < $2", conn.sql)
        self.assertIn("status <> 'cancelled'", conn.sql)
        self.assertEqual(len(conn.args), 2)

    def test_monthly_admin_drilldown_shows_ranked_product_sales(self):
        callback = SimpleNamespace(
            from_user=SimpleNamespace(id=7), data="admin:monthly_stats:2026:10",
            message=SimpleNamespace(edit_text=AsyncMock()), answer=AsyncMock(),
        )
        products = [
            {"name": "Mahsulot A", "qty": 3, "revenue": 450_000},
            {"name": "Mahsulot B", "qty": 2, "revenue": 300_000},
        ]
        month = {
            "year": 2026, "month": 10, "is_current": False,
            "orders": 2, "booked_value": 750_000, "delivered_orders": 1,
            "delivered_revenue": 450_000, "revenue": 450_000, "b2b_revenue": 0,
        }
        with patch.object(admin_handlers, "is_admin", return_value=True), \
             patch.object(admin_handlers, "get_user_language", AsyncMock(return_value="uz")), \
             patch.object(admin_handlers, "get_month_stats", AsyncMock(return_value=month)), \
             patch.object(admin_handlers, "get_monthly_product_sales", AsyncMock(return_value=products)), \
             patch.object(admin_handlers, "get_month_name", return_value="Oktabr"):
            asyncio.run(admin_handlers.show_specific_month_stats(callback))

        text = callback.message.edit_text.await_args.args[0]
        self.assertIn("Mahsulotlar", text)
        self.assertLess(text.index("Mahsulot A"), text.index("Mahsulot B"))
        self.assertIn("3 ta", text)
        self.assertIn("450 000 so'm", text)


class FinanceExcelReportTest(unittest.TestCase):
    def test_order_total_appears_once_and_summary_uses_delivery_period_stats(self):
        orders = [
            {
                "id": 101, "created_at": None, "status": "pending", "total": 250.6,
                "items_data": [
                    {"name": "A", "product_id": 10, "quantity": 1, "price": 100.3},
                    {"name": "B", "product_id": 10, "quantity": 1, "price": 150.3},
                ],
            },
            {
                "id": 102, "created_at": None, "status": "cancelled", "total": 90.6,
                "items_data": [{"name": "C", "product_id": 10, "quantity": 1, "price": 90}],
            },
        ]
        stats = {
            "orders_sold": 1, "booked_value": 250,
            "orders_delivered": 1, "delivered_revenue": 225,
            "product_cost": 80, "expenses": 25, "profit": 120,
            "missing_cost_products": ["Psillium 250gr"],
        }
        delivered_orders = [{
            "id": 201, "delivered_at": None, "total": 225.7,
            "items": '[{"name":"A","product_id":10,"quantity":1,"price":225.7}]',
        }]
        expenses = [
            {"id": 1, "name": "Yetkazish", "amount": 10.7, "created_at": None},
            {"id": 2, "name": "Qadoq", "amount": 15.3, "created_at": None},
        ]

        with patch.object(reports, "get_orders_for_export", AsyncMock(return_value=orders)), \
             patch.object(reports, "get_admin_stats", AsyncMock(return_value=stats)), \
             patch.object(reports, "get_delivered_orders_for_period", AsyncMock(return_value=delivered_orders)), \
             patch.object(reports, "get_expenses_for_period", AsyncMock(return_value=expenses)), \
             patch.object(reports, "get_all_cost_prices", AsyncMock(return_value={10: 80})), \
             patch.object(reports, "get_set_costs", AsyncMock(return_value={})), \
             patch.object(reports, "_fmt_dt", return_value=""):
            buffer, _ = asyncio.run(reports.generate_orders_excel("30d"))

        workbook = load_workbook(BytesIO(buffer.getvalue()), data_only=True)
        detail = workbook["Buyurtmalar"]
        self.assertAlmostEqual(detail.cell(row=2, column=11).value, 250.6)
        self.assertIsNone(detail.cell(row=3, column=11).value)
        self.assertIsNone(detail.cell(row=4, column=11).value)  # cancelled order
        self.assertEqual(detail.cell(row=5, column=10).value, "Hisobot bilan tafovut")
        self.assertAlmostEqual(detail.cell(row=5, column=11).value, -0.6)
        self.assertEqual(detail.cell(row=6, column=11).value, 250)
        self.assertAlmostEqual(sum(detail.cell(row=r, column=11).value or 0
                                   for r in range(2, 6)), 250)

        summary = workbook["Xulosa"]
        amounts = {summary.cell(row=r, column=1).value: summary.cell(row=r, column=2).value
                   for r in range(1, summary.max_row + 1)}
        self.assertEqual(amounts["Yangi buyurtmalar qiymati (yaratilgan sana)"], 250)
        self.assertEqual(amounts["Yetkazilgan tushum"], 225)
        self.assertEqual(amounts["Davr xarajatlari"], 25)
        self.assertEqual(amounts["Sof foyda (yetkazilgan tushum − tannarx − xarajat)"], 120)
        self.assertEqual(amounts["Tannarxi topilmagan mahsulotlar (foyda oshib ko'rinishi mumkin)"],
                         "Psillium 250gr")

        delivered_sheet = workbook["Yetkazilganlar"]
        delivered_total = delivered_sheet.cell(row=delivered_sheet.max_row, column=8).value
        self.assertEqual(delivered_total, amounts["Yetkazilgan tushum"])
        self.assertEqual(delivered_sheet.cell(row=3, column=7).value, "Hisobot bilan tafovut")
        self.assertAlmostEqual(delivered_sheet.cell(row=3, column=8).value, -0.7)
        self.assertAlmostEqual(sum(delivered_sheet.cell(row=r, column=8).value or 0
                                  for r in range(2, delivered_sheet.max_row)), delivered_total)
        expense_sheet = workbook["Xarajatlar"]
        expense_total = expense_sheet.cell(row=expense_sheet.max_row, column=3).value
        self.assertEqual(expense_total, amounts["Davr xarajatlari"])
        self.assertEqual(expense_sheet.cell(row=4, column=2).value, "Hisobot bilan tafovut")
        self.assertAlmostEqual(expense_sheet.cell(row=4, column=3).value, -1.0)
        self.assertAlmostEqual(sum(expense_sheet.cell(row=r, column=3).value or 0
                                  for r in range(2, expense_sheet.max_row)), expense_total)


class FinanceDashboardPayloadTest(unittest.TestCase):
    def test_dashboard_keeps_booked_and_delivered_values_separate(self):
        stats = {
            "orders_sold": 4, "booked_value": 900,
            "orders_delivered": 2, "delivered_revenue": 420,
            "revenue": 420, "product_cost": 190, "expenses": 30, "profit": 200,
            "b2b_revenue": 100, "b2b_orders": 1, "orders_total": 5,
            "orders_pending": 1, "orders_confirmed": 0, "orders_cancelled": 0,
            "keto_discount": 0,
            "orders_delivered_created": 3, "missing_cost_products": ["Psillium 250gr"],
        }
        request = SimpleNamespace(
            cookies={admin_web.SESSION_COOKIE: admin_web._make_session()},
            query={"period": "30d"},
        )
        with patch.object(admin_web, "ADMIN_WEB_PASSWORD", "test"), \
             patch.object(admin_web.database, "get_admin_stats", AsyncMock(return_value=stats)), \
             patch.object(admin_web.database, "get_monthly_breakdown", AsyncMock(return_value=[])), \
             patch.object(admin_web.database, "get_top_products", AsyncMock(return_value=[])), \
             patch.object(admin_web.database, "get_keto_program_stats", AsyncMock(return_value={})), \
             patch.object(admin_web.database, "get_abc_analysis", AsyncMock(return_value=[])), \
             patch.object(admin_web.database, "get_b2b_orders", AsyncMock(return_value=[])), \
             patch.object(admin_web.database, "get_orders_by_region", AsyncMock(return_value=[])):
            response = asyncio.run(admin_web.api_dashboard(request))

        payload = json.loads(response.text)
        self.assertEqual(payload["stats"]["booked_value"], 900)
        self.assertEqual(payload["stats"]["orders_sold"], 4)
        self.assertEqual(payload["stats"]["delivered_revenue"], 420)
        self.assertEqual(payload["stats"]["orders_delivered"], 2)

        dashboard = (Path(__file__).parents[1] / "webapp" / "admin.html").read_text(encoding="utf-8")
        self.assertIn("fmt(st.booked_value)", dashboard)
        self.assertIn("fmt(st.delivered_revenue)", dashboard)
        self.assertIn("st.orders_sold", dashboard)
        self.assertIn("st.orders_delivered", dashboard)
        self.assertIn("s.orders_delivered_created", dashboard)
        self.assertIn("st.missing_cost_products", dashboard)
        self.assertIn("jami yetkazilgan tushum ichida", dashboard)
        self.assertIn("r.delivered_revenue", dashboard)
        self.assertIn("r.delivered_orders", dashboard)


if __name__ == "__main__":
    unittest.main()
