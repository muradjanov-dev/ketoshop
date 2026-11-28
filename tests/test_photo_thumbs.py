"""Light, ready-made shop photos (photo_thumbs.py, owner 2026-11-28: "sayt
rasmlari sekin ochilyapti"). No network, the database is faked."""
import asyncio
import io
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://unused/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from PIL import Image

import database
import photo_thumbs as pt

TG = "AgACAgIAAxkBAAIBQ2Zk_example-file-id"


def png(w=2000, h=1500, alpha=False):
    im = Image.new("RGBA" if alpha else "RGB", (w, h), (200, 120, 80, 128) if alpha else (200, 120, 80))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


class FakeConn:
    def __init__(self, store):
        self.store = store

    async def execute(self, sql, *args):
        if sql.lstrip().startswith("INSERT INTO photo_thumbs"):
            self.store.setdefault(args[0], (args[1], args[2]))

    async def fetchrow(self, sql, key):
        hit = self.store.get(key)
        return {"data": hit[0], "content_type": hit[1]} if hit else None

    async def fetchval(self, sql, key):
        return 1 if key in self.store else None


class FakePool:
    def __init__(self):
        self.store = {}

    def acquire(self):
        conn = FakeConn(self.store)

        class Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False
        return Ctx()


class UrlTest(unittest.TestCase):
    def test_urls(self):
        self.assertEqual(pt.url_for(TG), f"/p/tg/{TG}")
        self.assertEqual(pt.url_for("/img/47"), "/p/img/47")
        self.assertEqual(pt.url_for("https://x.uz/a.jpg"), "https://x.uz/a.jpg")
        self.assertIsNone(pt.url_for(None))
        self.assertEqual(pt.url_for("short"), "/api/photo/short")


class ShrinkTest(unittest.TestCase):
    def test_big_png_becomes_small_jpeg(self):
        raw = png()
        small = pt.shrink(raw)
        im = Image.open(io.BytesIO(small))
        self.assertEqual(im.format, "JPEG")
        self.assertLessEqual(max(im.size), pt.MAX_SIDE)
        self.assertLess(len(small), len(raw) / 5)

    def test_transparent_png_gets_white_background(self):
        im = Image.open(io.BytesIO(pt.shrink(png(400, 400, alpha=True))))
        self.assertEqual(im.mode, "RGB")


class GetTest(unittest.TestCase):
    def setUp(self):
        pt._mem.clear()
        pt._table_ready = True
        self.pool = FakePool()
        p = patch.object(database, "pool", self.pool)
        p.start()
        self.addCleanup(p.stop)

    def test_made_once_then_served_from_cache(self):
        get_img = AsyncMock(return_value={"data": png(), "content_type": "image/png"})
        with patch.object(database, "get_web_image", get_img):
            first = asyncio.run(pt.get(None, "img", "47"))
            pt._mem.clear()                               # a restart: memory gone, table kept
            second = asyncio.run(pt.get(None, "img", "47"))
        self.assertEqual(first, second)
        self.assertEqual(first[1], "image/jpeg")
        get_img.assert_awaited_once()                     # the original was read once
        self.assertIn("img:47", self.pool.store)

    def test_telegram_photo_downloaded_once(self):
        bot = MagicMock()
        bot.get_file = AsyncMock(return_value=MagicMock(file_path="photos/a.jpg"))

        async def download(path, destination):
            destination.write(png(1280, 1280))
        bot.download_file = AsyncMock(side_effect=download)
        a = asyncio.run(pt.get(bot, "tg", TG))
        b = asyncio.run(pt.get(bot, "tg", TG))
        self.assertIs(a, b)
        bot.download_file.assert_awaited_once()

    def test_small_original_is_kept_as_is(self):
        buf = io.BytesIO()
        Image.new("RGB", (40, 40), (1, 2, 3)).save(buf, "JPEG", quality=30)
        raw = buf.getvalue()
        with patch.object(database, "get_web_image", AsyncMock(return_value={"data": raw, "content_type": "image/jpeg"})):
            data, ctype = asyncio.run(pt.get(None, "img", "5"))
        self.assertLessEqual(len(data), len(raw))

    def test_failure_returns_none(self):
        with patch.object(database, "get_web_image", AsyncMock(return_value=None)):
            self.assertIsNone(asyncio.run(pt.get(None, "img", "9")))


class ServeTest(unittest.TestCase):
    def setUp(self):
        pt._mem.clear()

    def req(self, kind, ref):
        r = MagicMock()
        r.match_info = {"kind": kind, "ref": ref}
        r.app = {"bot": None}
        return r

    def test_ready_copy_cached_for_a_year(self):
        with patch.object(pt, "get", AsyncMock(return_value=(b"jpg", "image/jpeg"))):
            resp = asyncio.run(pt.serve(self.req("img", "47")))
        self.assertEqual(resp.headers["Cache-Control"], pt.CACHE_HEADER)
        self.assertEqual(resp.body, b"jpg")

    def test_falls_back_to_the_original(self):
        from aiohttp import web
        with patch.object(pt, "get", AsyncMock(return_value=None)):
            with self.assertRaises(web.HTTPFound) as ctx:
                asyncio.run(pt.serve(self.req("tg", TG)))
        self.assertEqual(ctx.exception.location, f"/api/photo/{TG}")

    def test_bad_refs_are_404(self):
        from aiohttp import web
        for kind, ref in (("img", "abc"), ("tg", "../etc"), ("x", "1")):
            with self.assertRaises(web.HTTPNotFound):
                asyncio.run(pt.serve(self.req(kind, ref)))


class BackupTest(unittest.TestCase):
    def test_thumbs_not_in_backups(self):
        self.assertIn("photo_thumbs", database._BACKUP_EXCLUDE_TABLES)


if __name__ == "__main__":
    unittest.main()
