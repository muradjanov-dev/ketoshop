"""AI reply qilingan post/rasm/videoni ko'radi (post_context.py, egasi 2026-11-27)."""
import asyncio
import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import ai_sales
import post_context as pc

BOT = NS(id=999, download=AsyncMock())


def photo(w, uid):
    return NS(width=w, height=w, file_id="f" + uid, file_unique_id=uid)


class MediaTest(unittest.TestCase):
    def test_photo_picks_largest_within_limit(self):
        msg = NS(photo=[photo(90, "a"), photo(800, "b"), photo(2560, "c")])
        kind, file, _ = pc.media_of(msg)
        self.assertEqual((kind, file.file_unique_id), ("rasm", "b"))

    def test_video_uses_thumbnail_and_duration(self):
        msg = NS(photo=None, video=NS(thumbnail=photo(320, "t"), duration=75))
        kind, file, secs = pc.media_of(msg)
        self.assertEqual((kind, file.file_unique_id, secs), ("video", "t", 75))
        self.assertEqual(pc._duration(75), " (1:15)")


class BlockTest(unittest.TestCase):
    def test_channel_video_post_without_caption_is_understood(self):
        post = NS(is_automatic_forward=True, sender_chat=NS(type="channel", title="Keto shop"),
                  from_user=None, text=None, caption=None, photo=None,
                  video=NS(thumbnail=photo(320, "t"), duration=40))
        msg = NS(reply_to_message=post, external_reply=None, quote=None)
        with patch.object(pc, "describe", AsyncMock(return_value="Yashil grechka uni 500 g qadog'i")):
            out = asyncio.run(pc.reply_block(BOT, msg))
        self.assertIn("kanal posti (Keto shop)", out)
        self.assertIn("video (0:40)", out)
        self.assertIn("videoning muqovasida: Yashil grechka uni", out)

    def test_reply_to_our_photo_message_with_caption(self):
        mine = NS(is_automatic_forward=False, sender_chat=None, from_user=NS(id=999, is_bot=True),
                  text=None, caption="Kun mahsuloti: Psillium sheluxa", photo=[photo(800, "p")])
        msg = NS(reply_to_message=mine, external_reply=None, quote=NS(text="Psillium"))
        with patch.object(pc, "describe", AsyncMock(return_value="Psillium qadog'i, 65 450 so'm")):
            out = asyncio.run(pc.reply_block(BOT, msg))
        self.assertIn("bizning (do'kon botining) xabarimiz", out)
        self.assertIn("mijoz belgilagan joy: «Psillium»", out)
        self.assertIn("rasmda: Psillium qadog'i", out)

    def test_no_reply_no_block_and_lead(self):
        self.assertEqual(asyncio.run(pc.reply_block(BOT, NS(reply_to_message=None, external_reply=None))), "")
        post = NS(is_automatic_forward=True, sender_chat=NS(type="channel", title=None), from_user=None,
                  text="Bodom uni keldi", caption=None, photo=None)
        out = asyncio.run(pc.reply_block(BOT, NS(reply_to_message=post, external_reply=None, quote=None),
                                         "Kanal postiga izoh — savol shu post haqida"))
        self.assertTrue(out.startswith("[Kanal postiga izoh — savol shu post haqida"))
        self.assertIn("Bodom uni keldi", out)

    def test_external_reply(self):
        ext = NS(origin=NS(chat=NS(title="Keto shop")), photo=[photo(640, "e")])
        msg = NS(reply_to_message=None, external_reply=ext, quote=NS(text="1kg 87 000"))
        with patch.object(pc, "describe", AsyncMock(return_value="Bodom uni 1 kg")):
            out = asyncio.run(pc.reply_block(BOT, msg))
        self.assertIn("boshqa chatdagi post (Keto shop)", out)
        self.assertIn("rasmda: Bodom uni 1 kg", out)


class DescribeTest(unittest.TestCase):
    def test_cached_description_skips_download(self):
        pc._cache["cached1"] = "eski tavsif"
        bot = NS(download=AsyncMock())
        out = asyncio.run(pc.describe(bot, photo(100, "cached1")))
        self.assertEqual(out, "eski tavsif")
        bot.download.assert_not_awaited()

    def test_failure_is_silent(self):
        bot = NS(download=AsyncMock(side_effect=RuntimeError("net")))
        with patch.object(pc, "_stored", AsyncMock(return_value=None)):
            self.assertIsNone(asyncio.run(pc.describe(bot, photo(100, "x9"))))


class WiringTest(unittest.TestCase):
    def test_rule_and_helper(self):
        self.assertIn("REPLY KONTEKST", ai_sales._sales_rules())
        with patch("post_context.reply_block", AsyncMock(side_effect=RuntimeError("x"))):
            self.assertEqual(asyncio.run(ai_sales._reply_context(BOT, NS())), "")


if __name__ == "__main__":
    unittest.main()


class LastResortTest(unittest.TestCase):
    def test_polite_text_ask_is_last_resort_in_bot_and_group(self):
        for rules in (ai_sales._sales_rules(), ai_sales._group_rules()):
            self.assertIn("OXIRGI CHORA", rules)
            self.assertIn("yozib yuborsangiz", rules)
