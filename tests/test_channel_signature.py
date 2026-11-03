"""Har bir kanal posti «💚 @ketoshop_uz — Сизнинг Кето дўконингиз» bilan tugaydi
(egasi, 2026-11-03). Session middleware: kanalga matn va izohli media imzolanadi,
boshqa chatlar, tahrirlar va izohsiz rasm tegilmaydi; ikki marta yo'q, limitdan
oshmaydi."""
import asyncio
import os
import unittest
from unittest.mock import AsyncMock, patch

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

from aiogram.methods import EditMessageText, SendMessage, SendPhoto

import channel_signature as cs

CH = -1002132040345


class SignatureTest(unittest.TestCase):
    def setUp(self):
        p = patch.object(cs, "REQUIRED_CHANNEL_ID", CH)
        p.start()
        self.addCleanup(p.stop)

    def test_channel_text_is_signed_once(self):
        m = cs.sign_method(SendMessage(chat_id=CH, text="<b>❓ Savol?</b>\n\nFakt.\n\n#кетофакт"))
        self.assertTrue(m.text.endswith("\n\n💚 @ketoshop_uz — Сизнинг Кето дўконингиз"))
        again = cs.sign_method(m)
        self.assertEqual(again.text.count("Сизнинг Кето дўконингиз"), 1)

    def test_channel_by_username_too(self):
        m = cs.sign_method(SendMessage(chat_id="@ketoshop_uz", text="Salom"))
        self.assertIn(cs.SIGNATURE, m.text)

    def test_other_chats_and_edits_untouched(self):
        for method in (SendMessage(chat_id=4242, text="Salom"),
                       EditMessageText(chat_id=CH, message_id=5, text="Salom")):
            self.assertIs(cs.sign_method(method), method)

    def test_captions_signed_but_a_bare_photo_is_not(self):
        m = cs.sign_method(SendPhoto(chat_id=CH, photo="file-id", caption="Retsept"))
        self.assertTrue(m.caption.endswith(cs.SIGNATURE))
        bare = SendPhoto(chat_id=CH, photo="file-id")
        self.assertIs(cs.sign_method(bare), bare)        # its text comes next, signed there

    def test_never_past_telegram_limits(self):
        long_caption = "x" * (cs.CAPTION_LIMIT - 10)
        m = cs.sign_method(SendPhoto(chat_id=CH, photo="file-id", caption=long_caption))
        self.assertEqual(m.caption, long_caption)
        tags = "<b>" + "y" * (cs.CAPTION_LIMIT - 60) + "</b>"   # tags don't count
        self.assertIn(cs.SIGNATURE, cs.sign_method(SendPhoto(chat_id=CH, photo="f", caption=tags)).caption)

    def test_middleware_passes_the_signed_call_on(self):
        make_request = AsyncMock(return_value="ok")
        mw = cs.ChannelSignatureMiddleware()
        out = asyncio.run(mw(make_request, object(), SendMessage(chat_id=CH, text="Post")))
        self.assertEqual(out, "ok")
        self.assertIn(cs.SIGNATURE, make_request.await_args.args[1].text)


if __name__ == "__main__":
    unittest.main()
