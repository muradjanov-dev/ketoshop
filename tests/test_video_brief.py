"""Reels mazmuni — bir video bir marta (video_brief.py, egasi 2026-11-28)."""
import asyncio
import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import comment_ai
import meta_comments
import video_brief as vb


class BriefTest(unittest.TestCase):
    def test_stored_summary_is_reused_without_any_work(self):
        download = AsyncMock()
        with patch.object(vb, "_stored", AsyncMock(return_value={"summary": "Bodom unidan non", "status": "ok",
                                                                  "created_at": datetime.utcnow()})), \
                patch.object(vb, "_download", download):
            out = asyncio.run(vb.brief("m1", "https://x/v.mp4"))
        self.assertEqual(out, "Bodom unidan non")
        download.assert_not_awaited()

    def test_recent_failure_not_retried(self):
        with patch.object(vb, "_stored", AsyncMock(return_value={"summary": "", "status": "failed",
                                                                  "created_at": datetime.utcnow()})), \
                patch.object(vb, "_download", AsyncMock()) as dl:
            self.assertEqual(asyncio.run(vb.brief("m2", "https://x/v.mp4")), "")
        dl.assert_not_awaited()

    def test_no_ffmpeg_is_silent(self):
        with patch.object(vb, "_stored", AsyncMock(return_value=None)), \
                patch.object(vb.shutil, "which", return_value=None):
            self.assertEqual(asyncio.run(vb.brief("m3", "https://x/v.mp4")), "")

    def test_full_pipeline_once_for_many_comments(self):
        saved = {}

        async def stored(mid):
            return saved.get(mid)

        async def save(mid, summary, transcript, status):
            saved[mid] = {"summary": summary, "status": status, "created_at": datetime.utcnow()}

        async def fake_extract(video, work):
            frame = work / "f0.jpg"
            frame.write_bytes(b"jpg")
            audio = work / "audio.mp3"
            audio.write_bytes(b"mp3")
            return audio, [frame], 42.0

        download = AsyncMock(return_value=True)
        with patch.object(vb, "_stored", stored), patch.object(vb, "_save", save), \
                patch.object(vb.shutil, "which", return_value="/usr/bin/ffmpeg"), \
                patch.object(comment_ai, "_openai_key", AsyncMock(return_value="k")), \
                patch.object(vb, "_download", download), patch.object(vb, "extract", fake_extract), \
                patch.object(vb, "_transcribe", AsyncMock(return_value="Bugun bodom unidan non pishiramiz")), \
                patch.object(vb, "_summarise", AsyncMock(return_value="Bodom unidan non retsepti")) as summ:
            async def many():
                return await asyncio.gather(*(vb.brief("reel1", "https://x/v.mp4", "Non") for _ in range(30)))
            outs = asyncio.run(many())
        self.assertEqual(set(outs), {"Bodom unidan non retsepti"})
        self.assertEqual(download.await_count, 1)          # 30 izoh — bitta tahlil
        self.assertEqual(summ.await_count, 1)
        self.assertEqual(saved["reel1"]["status"], "ok")


class WiringTest(unittest.TestCase):
    def test_reels_caption_gets_video_summary(self):
        meta_comments._post_ctx.pop("r9", None)
        data = {"caption": "Keto non", "media_type": "VIDEO", "media_url": "https://x/v.mp4",
                "thumbnail_url": "https://x/t.jpg"}
        with patch.object(meta_comments, "identity", AsyncMock(return_value={"page_token": "t"})), \
                patch.object(meta_comments, "_graph", AsyncMock(return_value=data)), \
                patch.object(vb, "brief", AsyncMock(return_value="Bodom unidan non pishiriladi")) as brief:
            caption, image = asyncio.run(meta_comments.post_context({"media_id": "r9", "platform": "ig"}))
            asyncio.run(meta_comments.post_context({"media_id": "r9", "platform": "ig"}))
        self.assertIn("VIDEO MAZMUNI (ovozi va kadrlaridan): Bodom unidan non", caption)
        self.assertEqual(image, "https://x/t.jpg")
        self.assertEqual(brief.await_count, 1)               # ikkinchi izoh — xotiradagi kesh

    def test_rule_and_dockerfile(self):
        self.assertIn("VIDEO MAZMUNI", comment_ai.RULES)
        docker = (Path(vb.__file__).parent / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("ffmpeg", docker)


if __name__ == "__main__":
    unittest.main()
