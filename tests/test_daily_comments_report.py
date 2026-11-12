"""Izohlar kunlik hisobotda va 3 soatlik AI sarfi xabarida (egasi, 2026-11-11:
"nechta izohga qayerda javob berganini ham va necha pul ketganini ham admin
kunlik hisobotga qo'shgin", "nechta izohga javob berganingni ham … faqat
narxini emas"). Baza soxta."""
import os
import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import database
import meta_comments as mc
import targets

ANSWERED = [
    {"platform": "ig", "post_link": "https://www.instagram.com/reel/AAA/", "media_id": "m1", "ad_name": None,
     "private_sent": True},
    {"platform": "ig", "post_link": "https://www.instagram.com/reel/AAA/", "media_id": "m1", "ad_name": None,
     "private_sent": False},
    {"platform": "ig", "post_link": "https://www.instagram.com/p/BBB/", "media_id": "m2", "ad_name": "Kepak video",
     "private_sent": True},
]
USAGE = [{"model": "gpt-5.4-mini", "requests": 90, "cost_usd": 0.40},
         {"model": "gpt-5.4-mini · izohlar", "requests": 41, "cost_usd": 0.035}]


def patches():
    return [patch.object(database, "meta_comments_report", AsyncMock(return_value=ANSWERED)),
            patch.object(database, "get_ai_usage_today", AsyncMock(return_value=USAGE)),
            patch.object(database, "get_ai_usage_month", AsyncMock(return_value={"cost_usd": 7.25})),
            patch.object(database, "meta_comment_open_breakdown",
                         AsyncMock(return_value={"unchecked": 1, "unanswerable": 4, "failed": 0})),
            patch.object(database, "meta_comment_today",
                         AsyncMock(return_value={"ai_answered": 3, "dms": 2, "dms_all": 2}))]


class SummaryTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for p in patches():
            p.start()
            self.addCleanup(p.stop)

    async def test_count_place_and_money(self):
        s = await mc.daily_summary()
        self.assertEqual((s["answered"], s["dms"], s["posts"], s["open"]), (3, 2, 2, 5))
        self.assertAlmostEqual(s["cost"], 0.035)
        self.assertEqual([(g["label"], g["n"]) for g in s["top"]], [("reel/AAA", 2), ("p/BBB", 1)])
        text = "\n".join(mc.summary_lines(s))
        self.assertTrue(text.startswith("💬 <b>Izohlarga AI javob berdi: 3 ta</b> — 2 ta post/reels ostida"))
        self.assertIn("reel/AAA</a> — 2 ta", text)
        self.assertIn("📣 Kepak video — 1 ta", text)
        self.assertIn("Izohlarga AI sarfi: $0.035", text)
        self.assertIn("javobsiz: 5 ta", text)

    async def test_spend_report_leads_with_the_count(self):
        text = await mc.spend_text(datetime(2026, 11, 11, 18, 0))
        first_lines = text.split("\n")[:4]
        self.assertIn("Izohlarga AI javob berdi: 3 ta", "\n".join(first_lines))
        self.assertIn("Jami AI sarfi: <b>$0.44</b>", text)

    def test_nothing_to_say_no_block(self):
        self.assertEqual(mc.summary_lines({}), [])
        self.assertEqual(mc.summary_lines({"answered": 0, "open": 0, "cost": 0}), [])


def snap(**extra):
    base = {"date": date(2026, 11, 11), "observed_at": datetime(2026, 11, 11, 20, 0), "sales": 9, "daily_target": 10,
            "sales_left": 1, "day_revenue": 0, "day_booked_value": 0, "day_delivered_revenue": 0, "day_profit": 0,
            "month_profit_usd": 100, "monthly_target_usd": 1000, "month_profit": 1_250_000,
            "monthly_target_uzs": 12_500_000, "usd_rate": 12500, "usd_rate_date": "11.11.2026",
            "remaining_uzs": 11_250_000, "remaining_usd": 900, "days_left": 19, "needed_per_day_usd": 47,
            "month_orders": 120, "month_booked_value": 0, "month_revenue": 0}
    base.update(extra)
    return base


class DailyReportTest(unittest.TestCase):
    def test_evening_report_has_the_comment_block(self):
        comments = {"answered": 123, "dms": 10, "posts": 29, "cost": 0.031, "open": 53,
                    "top": [{"link": "https://www.instagram.com/reel/AAA/", "label": "reel/AAA", "ad": None, "n": 16}]}
        with patch("ai_sales.is_enabled", return_value=False):
            text = targets.build_message(snap(comments=comments), 20)
        self.assertIn("Izohlarga AI javob berdi: 123 ta</b> — 29 ta post/reels ostida", text)
        self.assertIn("reel/AAA</a> — 16 ta", text)
        self.assertIn("$0.031", text)

    def test_midday_report_and_no_data_stay_as_before(self):
        comments = {"answered": 5, "dms": 0, "posts": 1, "cost": 0.01, "open": 0, "top": []}
        self.assertNotIn("Izohlarga AI", targets.build_message(snap(comments=comments), 13))
        with patch("ai_sales.is_enabled", return_value=False):
            self.assertNotIn("Izohlarga AI", targets.build_message(snap(), 20))


if __name__ == "__main__":
    unittest.main()
