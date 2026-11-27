"""AI jami javoblar hisobi (ai_totals.py, egasi 2026-11-27)."""
import asyncio
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ai_totals


class FakeConn:
    def __init__(self):
        self.args = []

    async def fetchrow(self, sql, *args):
        self.args.append((sql, args))
        if "ig_dm_messages" in sql and "'held'" in sql:
            raise RuntimeError("relation does not exist")
        if "FROM ai_conversations WHERE channel" in sql:
            return {"replies": {"bot": 1000, "site": 50, "group": 30}[args[0]], "people": 5, "since": None}
        return {"replies": 7, "people": 3, "since": None}


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return Ctx()


class TotalsTest(unittest.TestCase):
    def test_sums_sources_and_survives_missing_table(self):
        conn = FakeConn()
        with patch.object(ai_totals.database, "pool", _Pool(conn), create=True):
            out = asyncio.run(ai_totals.totals([425609051]))
        self.assertEqual(out["telegram"]["bot"]["replies"], 1000)
        self.assertEqual(out["direct_holding"]["replies"], 0)
        # 1080 telegram + 7 direct + 0 holding + 7 izoh + 7 qayta xabar
        self.assertEqual(out["total_replies"], 1101)
        staff_args = [a for sql, a in conn.args if "ai_conversations WHERE channel" in sql]
        self.assertEqual(staff_args[0][1], [425609051])


if __name__ == "__main__":
    unittest.main()
