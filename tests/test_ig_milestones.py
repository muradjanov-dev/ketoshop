"""Instagram: har 50 ta javobda hisobot (ig_milestones.py, egasi 2026-11-28)."""
import asyncio
import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ig_milestones as im


class CheckTest(unittest.TestCase):
    def _check(self, comments, directs, claimed):
        claim = AsyncMock(side_effect=lambda key: key not in claimed and not claimed.add(key))
        bot = NS(send_message=AsyncMock())
        with patch.object(im, "comment_total", AsyncMock(return_value=comments)), \
                patch.object(im, "direct_total", AsyncMock(return_value=directs)), \
                patch.object(im.database, "claim_release_notes", claim), \
                patch.object(im, "comment_report", AsyncMock(return_value="IZOH")), \
                patch.object(im, "direct_report", AsyncMock(return_value="DIRECT")), \
                patch.object(im, "ADMIN_IDS", [1, 2]):
            sent = asyncio.run(im.check(bot))
        return sent, bot.send_message

    def test_each_step_once_and_separately(self):
        claimed = set()
        sent, send = self._check(149, 49, claimed)
        self.assertEqual(sent, ["izoh"])                    # 100-bosqich; Direct hali 50 ga yetmagan
        self.assertEqual(send.await_count, 2)               # ikki admin
        self.assertIn("ig50:izoh:100", claimed)
        sent, _ = self._check(149, 49, claimed)
        self.assertEqual(sent, [])                          # qayta yuborilmaydi
        sent, send = self._check(150, 50, claimed)
        self.assertEqual(sent, ["izoh", "direct"])
        self.assertEqual([c.args[1] for c in send.await_args_list], ["IZOH", "IZOH", "DIRECT", "DIRECT"])

    def test_zero_sends_nothing(self):
        sent, send = self._check(0, 10, set())
        self.assertEqual(sent, [])
        send.assert_not_awaited()

    def test_failed_report_releases_claim(self):
        release = AsyncMock()
        with patch.object(im, "comment_total", AsyncMock(return_value=50)), \
                patch.object(im, "direct_total", AsyncMock(return_value=0)), \
                patch.object(im.database, "claim_release_notes", AsyncMock(return_value=True)), \
                patch.object(im.database, "release_release_notes", release), \
                patch.object(im, "comment_report", AsyncMock(side_effect=RuntimeError("db"))):
            self.assertEqual(asyncio.run(im.check(NS(send_message=AsyncMock()))), [])
        release.assert_awaited_once_with("ig50:izoh:50")


if __name__ == "__main__":
    unittest.main()
