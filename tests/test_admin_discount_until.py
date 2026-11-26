"""Admin paneldan qo'yilgan chegirma eski, o'tib ketgan muddat bilan yashirinmasin (2026-11-26)."""
import os
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import admin_web


class StaleUntilTest(unittest.TestCase):
    def test_expired_date_is_cleared(self):
        old = {"discount_percent": 15, "discount_until": datetime(2026, 11, 7, 8, 57)}
        self.assertTrue(admin_web.discount_until_stale(old, 15))       # Ksantan kamedi: same percent, date long gone

    def test_new_percent_clears_the_date(self):
        future = {"discount_percent": 10, "discount_until": datetime.utcnow() + timedelta(days=3)}
        self.assertTrue(admin_web.discount_until_stale(future, 15))

    def test_running_timed_discount_kept(self):
        future = {"discount_percent": 15, "discount_until": datetime.utcnow() + timedelta(days=3)}
        self.assertFalse(admin_web.discount_until_stale(future, 15))

    def test_no_date_nothing_to_do(self):
        self.assertFalse(admin_web.discount_until_stale({"discount_percent": 0, "discount_until": None}, 20))


if __name__ == "__main__":
    unittest.main()
