"""Foyda hisobi — bitta tannarx qoidasi (database.line_cost), savdo qaysi
kunga yozilishi (database.SALE_SQL) va dollar kursi."""
import asyncio
import contextlib
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from datetime import date, datetime

import database
import targets
from handlers.admin import _month_block_text
from locales import get_text

COSTS = {10: 40_000, 20: 0}
SET_COSTS = {7: 95_000}


class LineCostTest(unittest.TestCase):
    def test_product_line(self):
        self.assertEqual(database.line_cost({"product_id": 10, "quantity": 2}, COSTS, SET_COSTS), (80_000, True))

    def test_set_line_is_costed_from_its_components(self):
        line = {"is_set": True, "set_id": 7, "product_id": None, "quantity": 2, "price": 150_000}
        self.assertEqual(database.line_cost(line, COSTS, SET_COSTS), (190_000, True))

    def test_gift_costs_nothing_here(self):
        # Booked in Chiqimlar instead — must not be charged twice.
        self.assertEqual(database.line_cost({"product_id": 10, "quantity": 1, "is_gift": True, "is_bonus": True},
                                            COSTS, SET_COSTS), (0, True))

    def test_bonus_line_by_stock_quantity(self):
        line = {"product_id": 10, "quantity": 100, "stock_quantity": 0.1, "is_bonus": True}
        cost, known = database.line_cost(line, COSTS, SET_COSTS)
        self.assertAlmostEqual(cost, 4_000)
        self.assertTrue(known)

    def test_line_carrying_its_own_cost_price_is_costed_by_it(self):
        # B2B Eritritol: sold by the kilo out of a wholesale sack, and the
        # catalog only has 100gr/500gr packs, so the line keeps its own cost.
        line = {"name": "Eritritol (B2B)", "quantity": 12, "cost_price": 30_000, "unit": "kg"}
        self.assertEqual(database.line_cost(line, COSTS, SET_COSTS), (360_000, True))

    def test_line_cost_price_wins_over_the_catalog(self):
        # A cost fixed at sale time must survive later edits to the product.
        line = {"product_id": 10, "quantity": 2, "cost_price": 50_000}
        self.assertEqual(database.line_cost(line, COSTS, SET_COSTS), (100_000, True))

    def test_b2b_eritritol_without_a_cost_is_still_flagged(self):
        # The old "id": -1 rows, until the backfill runs.
        line = {"id": -1, "name": "Eritritol (B2B)", "quantity": 12, "unit": "kg"}
        self.assertEqual(database.line_cost(line, COSTS, SET_COSTS), (0, False))

    def test_missing_cost_price_is_flagged(self):
        self.assertEqual(database.line_cost({"product_id": 20, "quantity": 1}, COSTS, SET_COSTS), (0, False))
        self.assertEqual(database.line_cost({"is_set": True, "set_id": 99, "quantity": 1}, COSTS, SET_COSTS),
                         (0, False))


class _FakeConn:
    """Records every statement get_admin_stats issues and answers each one
    with a canned row, so the test can assert on the WHERE clauses that decide
    which orders the money comes from."""

    def __init__(self):
        self.queries: list[str] = []
        self.transaction_settings: list[dict] = []

    def transaction(self, **settings):
        self.transaction_settings.append(settings)

        @contextlib.asynccontextmanager
        async def _cm():
            yield
        return _cm()

    async def fetchrow(self, sql, *args):
        self.queries.append(sql)
        if "users_total" in sql:
            return {"users_total": 500, "reviews_total": 40,
                    "products_active": 116, "products_in_stock": 100}
        if "FILTER (WHERE status = 'pending')" in sql:
            return {"total": 6, "pending": 3, "confirmed": 1, "delivered": 1,
                    "cancelled": 1}
        if "AS booked_value" in sql:
            return {"sold": 5, "booked_value": 1_568_000, "keto_discount": 20_000}
        if "AS revenue" in sql:
            return {"delivered": 3, "revenue": 561_000,
                    "b2b_revenue": 0, "b2b_orders": 0, "keto_discount": 18_000}
        return {"users_new": 4, "reviews_new": 1, "expenses": 35_000}

    async def fetch(self, sql, *args):
        self.queries.append(sql)
        if "cost_price FROM products" in sql:
            return [{"id": 10, "cost_price": 40_000}]
        if "product_set_items" in sql:
            return []
        return [{"items": '[{"product_id": 10, "quantity": 1, "cost_price": 354950}]'}]

    async def fetchval(self, sql, *args):
        self.queries.append(sql)
        return 0


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        @contextlib.asynccontextmanager
        async def _cm():
            yield self._conn
        return _cm()


class SaleBasisTest(unittest.TestCase):
    """24.09.2026 example: 5 new orders totaling 1,568,000 so'm, while
    deliveries were 561,000 so'm. Profit is deliveries less cost and period
    expenses (171,050 so'm)."""

    def _stats(self, period="today"):
        conn = _FakeConn()
        with patch.object(database, "pool", _FakePool(conn)):
            stats = asyncio.run(database.get_admin_stats(period))
        return stats, conn.queries

    def test_new_orders_and_deliveries_use_their_own_date_fields(self):
        _, queries = self._stats()
        booked = next(q for q in queries if "AS booked_value" in q)
        delivered = next(q for q in queries if "AS revenue" in q)
        items = next(q for q in queries if q.startswith("SELECT items FROM orders"))
        self.assertIn("created_at", booked)
        self.assertIn(database.SALE_SQL, booked)
        self.assertIn("status = 'delivered'", delivered)
        self.assertIn("delivered_at", delivered)
        self.assertIn("status = 'delivered'", items)
        self.assertIn("delivered_at", items)
        self.assertNotIn("delivered_at", booked)

    def test_delivered_revenue_is_scoped_by_delivery_time(self):
        _, queries = self._stats()
        money = next(q for q in queries if "AS revenue" in q)
        scope = money.split("FROM orders", 1)[1]
        self.assertIn("status = 'delivered'", scope)
        self.assertIn("delivered_at", scope)

    def test_booked_sales_and_delivered_money_are_distinct_fields(self):
        stats, _ = self._stats()
        self.assertEqual(stats["orders_sold"], 5)
        self.assertEqual(stats["booked_value"], 1_568_000)
        self.assertEqual(stats["orders_delivered"], 3)
        self.assertEqual(stats["delivered_revenue"], 561_000)
        self.assertEqual(stats["revenue"], 561_000)
        self.assertEqual(stats["product_cost"], 354_950)
        self.assertEqual(stats["expenses"], 35_000)
        self.assertEqual(stats["profit"], 171_050)
        self.assertEqual(stats["aov"], 1_568_000 // 5)

    def test_all_financial_reads_share_a_repeatable_read_only_snapshot(self):
        conn = _FakeConn()
        with patch.object(database, "pool", _FakePool(conn)):
            asyncio.run(database.get_admin_stats("today"))
        self.assertEqual(conn.transaction_settings, [
            {"isolation": "repeatable_read", "readonly": True}
        ])
        set_cost_query = next(q for q in conn.queries if "product_set_items" in q)
        self.assertTrue(set_cost_query, "set costs must be read in the same transaction")

    def test_report_takes_its_sale_count_straight_from_the_stats(self):
        day = {"orders_sold": 5, "booked_value": 1_568_000,
               "orders_delivered": 3, "orders_total": 6, "orders_cancelled": 1,
               "revenue": 561_000, "profit": 171_050}
        month = {"orders_sold": 136, "booked_value": 53_758_281,
                 "revenue": 48_000_000, "profit": 16_157_899,
                 "missing_cost_products": []}

        async def _stats(period):
            return month if isinstance(period, dict) else day

        with patch.object(database, "get_admin_stats", _stats), \
             patch.object(database, "get_targets_state", AsyncMock(return_value={})), \
             patch.object(database, "get_ai_usage_today", AsyncMock(return_value=[])), \
             patch.object(database, "get_ai_usage_month", AsyncMock(return_value={})), \
             patch.object(database, "count_ai_questions_today", AsyncMock(return_value=0)), \
             patch.object(targets, "_now_tk", return_value=datetime(2026, 9, 24, 20, 17)), \
             patch.object(targets, "current_usd_rate", AsyncMock(return_value=(11_814.0, "24.09.2026"))):
            snap = asyncio.run(targets.snapshot())

        self.assertEqual(snap["sales"], 5)
        self.assertEqual(snap["day_booked_value"], 1_568_000)
        self.assertEqual(snap["day_delivered_revenue"], 561_000)
        self.assertEqual(snap["day_profit"], 171_050)
        self.assertEqual(snap["observed_at"], datetime(2026, 9, 24, 20, 17))
        self.assertEqual(snap["month_orders"], 136)
        text = targets.build_message(snap, 20)
        self.assertIn("5 / 10", text)
        self.assertIn("20:17 HOLATIGA", text)
        self.assertIn("1 568 000 so'm", text)
        self.assertIn("561 000 so'm", text)
        self.assertIn("171 050 so'm", text)
        self.assertNotIn("yetmadi", text.lower())

    def test_expense_only_day_shows_zero_sales_and_negative_profit(self):
        snap = {
            "sales": 0, "daily_target": 10, "sales_left": 10,
            "day_revenue": 0, "day_booked_value": 0,
            "day_delivered_revenue": 0, "day_profit": -35_000,
            "month_profit_usd": 0, "monthly_target_usd": 2_000,
            "month_profit": -35_000, "monthly_target_uzs": 23_600_000,
            "usd_rate_date": None, "usd_rate": 11_800,
            "missing_cost_products": [], "remaining_uzs": 23_635_000,
            "remaining_usd": 2_003, "needed_per_day_usd": 67,
            "days_left": 30, "month_orders": 0, "month_revenue": 0,
            "month_booked_value": 0, "month_delivered_revenue": 0,
        }
        text = targets.build_message(snap, 13)
        self.assertIn("Yangi buyurtmalar summasi: 0 so'm", text)
        self.assertIn("Yetkazilgan savdo: 0 so'm", text)
        self.assertIn("sof foyda: -35 000 so'm", text)

        snap["observed_at"] = datetime(2026, 9, 24, 20, 17)
        late_status = targets.build_message(snap, 20)
        self.assertIn("20:17 HOLATIGA", late_status)
        self.assertNotIn("20:00 HOLATIGA", late_status)

    def test_export_detail_uses_delivered_and_expense_periods(self):
        conn = _FakeConn()
        period = {"start": "2026-09-24", "end": "2026-09-24"}
        with patch.object(database, "pool", _FakePool(conn)):
            orders = asyncio.run(database.get_delivered_orders_for_period(period))
            expenses = asyncio.run(database.get_expenses_for_period(period))
        order_query = next(q for q in conn.queries if "SELECT id, items, total" in q)
        expense_query = next(q for q in conn.queries if "FROM expenses" in q)
        self.assertIn("status = 'delivered'", order_query)
        self.assertIn("delivered_at >= $1", order_query)
        self.assertIn("delivered_at <= $2", order_query)
        self.assertIn("created_at >= $1", expense_query)
        self.assertIn("created_at <= $2", expense_query)
        self.assertEqual(len(orders), 1)
        self.assertEqual(len(expenses), 1)

    def test_telegram_monthly_report_labels_both_time_bases(self):
        month = {
            "month": 9, "year": 2026, "is_current": False,
            "orders": 5, "booked_value": 1_568_000,
            "delivered_orders": 3, "delivered_revenue": 561_000,
            "revenue": 561_000, "b2b_revenue": 0,
        }
        with patch("handlers.admin.get_month_name", return_value="Sentabr"):
            text = _month_block_text("uz", month)
        self.assertIn("Yangi buyurtmalar: 5 ta · 1 568 000 so'm", text)
        self.assertIn("Yetkazilgan savdo: 3 ta · 561 000 so'm", text)
        uz_stats = get_text("admin_stats", "uz")
        ru_stats = get_text("admin_stats", "ru")
        self.assertIn("{booked_value}", uz_stats)
        self.assertIn("{delivered_orders}", uz_stats)
        self.assertIn("Davrda yaratilgan buyurtmalar", uz_stats)
        self.assertIn("Ulardan yetkazilgan", uz_stats)
        self.assertIn("Заказы, созданные за период", ru_stats)
        self.assertIn("Из них доставлены", ru_stats)


class CancelledOrderTest(unittest.TestCase):
    """Egasi, 2026-09-25: "agar buyurtma bekor bo'lsa unda u savdodan olib
    tashlansin raqamlari". The sale leaves the money by itself (SALE_SQL is
    evaluated on every read); what did NOT leave was the gift / bonus /
    courier the shop had already booked against it."""

    def test_cancelling_unbooks_the_order_s_expenses(self):
        conn = _FakeConn()
        seen = []

        async def _execute(sql, *args):
            seen.append((sql, args))
            return "DELETE 2"

        conn.execute = _execute
        with patch.object(database, "pool", _FakePool(conn)):
            dropped = asyncio.run(database.update_order_status(41, "cancelled"))
            self.assertIsNone(dropped)
            n = asyncio.run(database.drop_order_expenses(41))
        self.assertEqual(n, 2)
        deletes = [q for q, _ in seen if "DELETE FROM expenses" in q]
        self.assertTrue(deletes, "cancelling must unbook the order's expenses")
        self.assertIn("gift_order_id", deletes[0])
        self.assertIn("bonus_order_id", deletes[0])
        self.assertIn("delivery_order_id", deletes[0])

    def test_delivering_does_not_unbook_anything(self):
        conn = _FakeConn()
        seen = []

        async def _execute(sql, *args):
            seen.append(sql)
            return "UPDATE 1"

        conn.execute = _execute
        with patch.object(database, "pool", _FakePool(conn)):
            asyncio.run(database.update_order_status(41, "delivered"))
        self.assertFalse([q for q in seen if "DELETE FROM expenses" in q])


class SentReportSnapshotTest(unittest.TestCase):
    def test_snapshot_is_idempotent_and_delivery_time_requires_success(self):
        conn = _FakeConn()
        writes = []
        inserts = {"count": 0}

        async def _fetchrow(sql, *args):
            writes.append((sql, args))
            inserts["count"] += 1
            return {"report_date": args[0]} if inserts["count"] == 1 else None

        async def _execute(sql, *args):
            writes.append((sql, args))
            return "UPDATE 1"

        conn.fetchrow = _fetchrow
        conn.execute = _execute
        with patch.object(database, "pool", _FakePool(conn)):
            self.assertTrue(asyncio.run(database.record_target_report_snapshot(
                date(2026, 9, 24), 20, {"sales": 5}, "report text"
            )))
            self.assertFalse(asyncio.run(database.record_target_report_snapshot(
                date(2026, 9, 24), 20, {"sales": 6}, "newer text"
            )))
            asyncio.run(database.finish_target_report_snapshot(date(2026, 9, 24), 20, 3, 2))
            asyncio.run(database.finish_target_report_snapshot(date(2026, 9, 24), 13, 3, 0))

        insert_sql = writes[0][0]
        self.assertIn("ON CONFLICT (report_date, slot) DO NOTHING", insert_sql)
        self.assertEqual(writes[0][1][3], "report text")
        outcome_sql = [sql for sql, _ in writes if "UPDATE target_report_snapshots" in sql]
        self.assertEqual(len(outcome_sql), 2)
        self.assertIn("sent_at = CASE WHEN $5 > 0", outcome_sql[0])
        self.assertEqual(writes[-2][1][2:], ("partial", 3, 2))
        self.assertEqual(writes[-1][1][2:], ("failed", 3, 0))


class KetoDiscountTest(unittest.TestCase):
    """Keto spent at checkout is already off the revenue, so it must be
    reported without also being charged to Chiqimlar."""

    def test_reported_but_not_booked_as_an_expense(self):
        conn = _FakeConn()
        with patch.object(database, "pool", _FakePool(conn)):
            stats = asyncio.run(database.get_admin_stats("today"))
        self.assertEqual(stats["keto_discount"], 18_000)
        # Profit = revenue - expenses - cost. The Keto discount is in none of
        # those terms: the buyer simply paid 18 000 less, and `revenue` is
        # already that much lower.
        self.assertEqual(stats["profit"],
                         stats["revenue"] - stats["expenses"] - stats["product_cost"])

    def test_report_shows_the_keto_line(self):
        snap = {
            "sales": 5, "daily_target": 10, "sales_left": 5,
            "day_revenue": 1_040_000, "day_profit": 300_000,
            "day_keto_discount": 18_000, "month_keto_discount": 240_000,
            "month_profit": 16_157_899, "month_profit_usd": 1368,
            "monthly_target_usd": 2000, "monthly_target_uzs": 23_628_000,
            "remaining_uzs": 7_470_201, "remaining_usd": 632,
            "needed_per_day_usd": 90, "days_left": 7, "usd_rate": 11_814,
            "usd_rate_date": "24.09.2026", "month_orders": 136,
            "month_revenue": 53_758_281, "missing_cost_products": [],
        }
        text = targets.build_message(snap, 20)
        self.assertIn("Keto chegirmasi: 18 000 so'm", text)
        self.assertIn("tushumdan ayrilgan", text)
        self.assertIn("Shu oyda Keto bilan to'langan: 240 000 so'm", text)


class StatusReminderTest(unittest.TestCase):
    """The one-off "where we stand" push: the two standing targets, today
    against them, and what the rest of the month needs per day."""

    BASE = {
        "date": date(2026, 9, 25), "month_first": date(2026, 9, 1), "days_total": 30,
        "usd_rate_date": "25.09.2026",
        "sales": 3, "daily_target": 10, "sales_left": 7,
        "month_profit": 15_949_725, "month_profit_usd": 1348,
        "monthly_target_usd": 2000, "monthly_target_uzs": 23_662_000,
        "remaining_uzs": 7_712_015, "remaining_usd": 652,
        "needed_per_day_usd": 109, "days_left": 6, "usd_rate": 11_831,
        "month_orders": 136, "month_revenue": 54_983_281,
        "missing_cost_products": [],
    }

    def test_states_both_targets_and_what_is_left(self):
        text = targets.build_status_reminder(dict(self.BASE))
        self.assertIn("Har kuni <b>10 ta yangi buyurtma</b>", text)
        self.assertIn("Oyiga <b>$2 000 sof foyda</b>", text)
        self.assertIn("Bugun (25.09.2026) yangi buyurtmalar: 3 / 10", text)
        self.assertIn("yana <b>7 ta</b> yangi buyurtma kerak", text)
        self.assertIn("Oyning oxirigacha 6 kun", text)
        self.assertIn("<b>$109</b> sof foyda", text)
        # Every figure carries the date it belongs to.
        self.assertIn("25.09.2026", text)
        self.assertIn("Sentabr 2026", text)
        self.assertIn("Oy boshidan (01.09 - 25.09)".replace("-", chr(8211)), text)

    def test_hit_target_does_not_ask_for_zero_more_sales(self):
        snap = dict(self.BASE, sales=12, sales_left=0, remaining_uzs=0,
                    remaining_usd=0, month_profit_usd=2114)
        text = targets.build_status_reminder(snap)
        self.assertNotIn("bugungi 0 tani", text)
        self.assertIn("Bugungi maqsad bajarildi", text)

    def test_sent_once_per_key(self):
        calls = []

        class _Bot:
            async def send_message(self, chat_id, text, **kw):
                calls.append(chat_id)

        claimed = {"n": 0}

        async def _claim(key):
            claimed["n"] += 1
            return claimed["n"] == 1        # only the first run wins the key

        async def _snap():
            return dict(self.BASE)

        with patch.object(targets.database, "claim_release_notes", _claim),              patch.object(targets, "snapshot", _snap),              patch.object(targets, "ADMIN_IDS", [1, 2, 2, 3]):
            first = asyncio.run(targets.send_status_reminder(_Bot()))
            second = asyncio.run(targets.send_status_reminder(_Bot()))

        self.assertTrue(first)
        self.assertFalse(second, "a redeploy must not push the same status twice")
        self.assertEqual(calls, [1, 2, 3], "each admin exactly once")


class UsdRateTest(unittest.TestCase):
    def test_target_uses_the_live_rate_and_says_so(self):
        snap = {
            "sales": 4, "daily_target": 10, "sales_left": 6, "day_revenue": 0, "day_profit": 0,
            "month_profit": 11_797_460, "month_profit_usd": 1000, "monthly_target_usd": 2000,
            "monthly_target_uzs": 23_594_920, "remaining_uzs": 11_797_460, "remaining_usd": 1000,
            "needed_per_day_usd": 71, "days_left": 14, "usd_rate": 11797.46, "usd_rate_date": "17.09.2026",
            "month_orders": 40, "month_revenue": 60_000_000,
            "missing_cost_products": ["Psillium 250gr"],
        }
        text = targets.build_message(snap, 13)
        self.assertIn("1$ = 11 797 so'm, Markaziy bank, 17.09.2026", text)
        self.assertIn("Tannarxi kiritilmagan: Psillium 250gr", text)

    def test_bad_rate_falls_back(self):
        targets._rate_cache = (0.0, None, None)
        with patch("aiohttp.ClientSession", side_effect=RuntimeError("offline")):
            self.assertEqual(asyncio.run(targets.current_usd_rate()), (None, None))


if __name__ == "__main__":
    unittest.main()
