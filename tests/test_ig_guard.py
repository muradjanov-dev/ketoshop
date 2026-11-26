"""Instagram himoyasi (ig_guard.py, egasi 2026-11-26: "suspicious action ...
akauntni 100% xavfsiz holatda"). Tarmoqsiz."""
import asyncio
import os
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ig_guard
import meta_comments as mc


def _run(coro):
    return asyncio.run(coro)


class GuardTest(unittest.TestCase):
    def setUp(self):
        ig_guard._sent.clear()
        ig_guard._last["at"] = 0.0
        ig_guard._paused.update(until=None, loaded=True)
        self.addCleanup(ig_guard._sent.clear)
        self.addCleanup(ig_guard._paused.update, {"until": None, "loaded": False})
        for p in (patch.object(ig_guard, "MIN_GAP", 0.0), patch.object(ig_guard, "MAX_GAP", 0.0),
                  patch.object(ig_guard, "_now_tk", lambda: datetime(2026, 11, 26, 12))):
            p.start()
            self.addCleanup(p.stop)

    def test_warnings_are_recognised(self):
        self.assertTrue(ig_guard.is_warning(368, "Temporarily blocked"))
        self.assertTrue(ig_guard.is_warning(None, "We detected suspicious activity"))
        self.assertTrue(ig_guard.is_warning(4, "Application request limit reached"))
        self.assertFalse(ig_guard.is_warning(100, "Field is only available for top-level comments"))

    def test_hourly_cap_and_night(self):
        for _ in range(ig_guard.HOURLY):
            _run(ig_guard.before_write())
        with self.assertRaises(ig_guard.Blocked):
            _run(ig_guard.before_write())
        ig_guard._sent.clear()
        with patch.object(ig_guard, "_now_tk", lambda: datetime(2026, 11, 26, 2)):
            with self.assertRaises(ig_guard.Blocked):
                _run(ig_guard.before_write())

    def test_meta_warning_pauses_everything_and_tells_admins_once(self):
        saved = AsyncMock()
        bot = NS(send_message=AsyncMock())

        class Resp:
            async def json(self, content_type=None):
                return {"error": {"code": 368, "message": "suspicious activity"}}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        session = NS(request=lambda *a, **k: Resp())
        import ai_sales
        with patch.object(ai_sales, "set_setting", saved), patch("config.ADMIN_IDS", [1, 2]), \
                patch.object(ig_guard, "pause", wraps=ig_guard.pause) as pause:
            async def go():
                with self.assertRaises(mc.GraphError):
                    await mc._graph(session, "POST", "x/replies", "T", body={"message": "hi"})
            # admin xabari uchun bot — pause() ichida yaratilmasin
            orig = ig_guard.pause

            async def with_bot(reason, hours=ig_guard.PAUSE_HOURS, bot_=None):
                return await orig(reason, hours, bot=bot)
            with patch.object(ig_guard, "pause", with_bot):
                _run(go())
                with self.assertRaises(mc.GraphError) as blocked:   # endi har qanday yozish to'xtaydi
                    _run(mc._graph(session, "POST", "y/replies", "T", body={}))
        self.assertTrue(mc.guarded(blocked.exception))
        self.assertEqual(bot.send_message.await_count, 2)
        self.assertIsNotNone(ig_guard._paused["until"])

    def test_reads_are_never_blocked(self):
        ig_guard._paused["until"] = datetime.utcnow() + timedelta(hours=5)

        class Resp:
            async def json(self, content_type=None):
                return {"data": []}

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False
        session = NS(request=lambda *a, **k: Resp())
        self.assertEqual(_run(mc._graph(session, "GET", "me", "T")), {"data": []})


if __name__ == "__main__":
    unittest.main()


class SafePaceTest(unittest.TestCase):
    """Egasi, 2026-11-26: "o'zing xavfsizlik ... har necha daqiqada yozish kerakligini aniqla"."""

    def test_about_one_a_minute_never_faster(self):
        # Egasi, 2026-11-26: "to'xtab qolma, blok qilmaydigan oraliqda, aytaylik xar 1 daqiqada".
        self.assertGreaterEqual(ig_guard.MIN_GAP, 50)
        self.assertGreater(ig_guard.MAX_GAP, ig_guard.MIN_GAP)
        self.assertLessEqual(ig_guard.HOURLY, 60)
        self.assertEqual(ig_guard.PAUSE_HOURS, 48)               # ogohlantirishda baribir to'xtaydi

    def test_resume_once_turns_everything_back_on(self):
        import comment_followup as cf
        import database
        import ig_direct
        claimed = AsyncMock(side_effect=[True, False])
        with patch.object(database, "claim_release_notes", claimed), \
                patch.object(database, "set_meta_comments_followup", AsyncMock()) as follow, \
                patch.object(ig_direct, "set_enabled", AsyncMock()) as direct, \
                patch.object(ig_guard, "resume", AsyncMock()) as resume:
            self.assertTrue(_run(cf.resume_safely_once()))
            self.assertFalse(_run(cf.resume_safely_once()))
        follow.assert_awaited_once_with(True)
        direct.assert_awaited_once_with(True)
        resume.assert_awaited_once()
