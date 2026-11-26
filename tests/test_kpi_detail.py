"""Dashboard KPI tafsiloti (kpi_detail.py, egasi 2026-11-26: "har bir tugmani
... bosilganda ichki detallarini ko'ra olaylik, qayerga va qayerdan")."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
import kpi_detail


class KpiDetailTest(unittest.TestCase):
    def test_order_origin_labels(self):
        self.assertEqual(kpi_detail._placed({"source": "b2b"}), "🏢 B2B (optom)")
        self.assertEqual(kpi_detail._placed({"source": "bot", "origin": '{"placed": "site"}'}), "🌐 Sayt")
        self.assertEqual(kpi_detail._touch({"origin": '{"placed": "bot", "touch": {"kind": "ad"}, "ai": true}'}),
                         "📣 Reklama · AI bilan")

    def test_profit_is_shown_as_a_waterfall(self):
        with patch.object(database, "get_admin_stats", AsyncMock(return_value={
                "delivered_revenue": 100, "product_cost": 60, "gross_profit": 40, "profit": 25})), \
                patch.object(database, "get_expense_totals_by_category", AsyncMock(return_value=[
                    {"key": "none", "name": "Kategoriyasiz", "total": 15, "count": 2}])), \
                patch.object(database, "get_product_sales", AsyncMock(return_value={"rows": []})):
            d = asyncio.run(kpi_detail.detail("profit", "30d"))
        rows = [r[0] for r in d["groups"][0]["rows"]]
        self.assertEqual(rows, ["Yetkazilgan tushum", "− Mahsulot tannarxi", "= Yalpi foyda",
                                "− Kategoriyasiz", "= Sof foyda"])

    def test_unknown_kpi_is_harmless(self):
        self.assertEqual(asyncio.run(kpi_detail.detail("nope", "30d"))["groups"], [])

    def test_every_card_is_clickable_in_the_dashboard(self):
        html = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "webapp",
                                 "admin.html"), encoding="utf-8").read()
        self.assertIn("markKpiCards();", html)
        self.assertIn("/admin/api/kpi-detail?kpi=", html)
        self.assertIn("'expenses'", html)


if __name__ == "__main__":
    unittest.main()
