"""Video qo'llanma (2026-10-11): yangi foydalanuvchiga avtomatik, hozirgilarga
admin tugmasi bilan, hech kimga ikki marta emas. Bot to'liq mock — hech
qanday haqiqiy xabar yuborilmaydi."""
import asyncio
import os
import re
import unittest
from unittest import mock

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import keyboards
import onboarding_video as ov


def run(coro):
    return asyncio.run(coro)


class CaptionTest(unittest.TestCase):
    def test_three_languages(self):
        self.assertIn("buyurtma", ov.caption("uz"))
        self.assertIn("заказ", ov.caption("ru"))
        cyr = ov.caption("uz_cyr")
        self.assertIn("буюртма", cyr)
        # Only the brand and the HTML tags may stay Latin.
        self.assertEqual(re.findall(r"[a-zA-Z]+", re.sub(r"<[^>]+>|Ketoshop", "", cyr)), [])

    def test_owner_wording(self):
        self.assertIn("Bot va sayt orqali Keto va sog'lom mahsulotlarni oson buyurtma", ov.caption("uz"))


class SendVideosTest(unittest.TestCase):
    def test_one_video_is_a_captioned_video(self):
        bot = mock.AsyncMock()
        run(ov.send_videos(bot, 5, "uz", ["A"]))
        bot.send_video.assert_awaited_once()
        self.assertEqual(bot.send_video.call_args.args[:2], (5, "A"))
        self.assertEqual(bot.send_video.call_args.kwargs["caption"], ov.caption("uz"))
        bot.send_media_group.assert_not_called()

    def test_two_videos_are_one_album_with_one_caption(self):
        bot = mock.AsyncMock()
        run(ov.send_videos(bot, 5, "ru", ["A", "B"]))
        media = bot.send_media_group.call_args.args[1]
        self.assertEqual([m.media for m in media], ["A", "B"])
        self.assertEqual(media[0].caption, ov.caption("ru"))
        self.assertIsNone(media[1].caption)

    def test_no_admin_mood_line_on_buyer_video(self):
        import admin_mood
        seen = []
        bot = mock.AsyncMock()
        bot.send_video.side_effect = lambda *a, **k: seen.append(admin_mood._quiet.get())
        run(ov.send_videos(bot, 5, "uz", ["A"]))
        self.assertEqual(seen, [True])
        self.assertFalse(admin_mood._quiet.get())


class NewUserTest(unittest.TestCase):
    def _go(self, state, was_sent=False):
        bot = mock.AsyncMock()
        mark = mock.AsyncMock()
        with mock.patch.object(ov, "get_state", mock.AsyncMock(return_value=state)), \
             mock.patch.object(ov, "_was_sent", mock.AsyncMock(return_value=was_sent)), \
             mock.patch.object(ov, "_mark_sent", mark):
            ok = run(ov.maybe_send_to_new_user(bot, 9, "uz"))
        return ok, bot, mark

    def test_sends_once_and_remembers(self):
        ok, bot, mark = self._go({"file_ids": ["A", "B"], "auto_new": True})
        self.assertTrue(ok)
        bot.send_media_group.assert_awaited_once()
        mark.assert_awaited_once_with(9)

    def test_nothing_before_upload(self):
        ok, bot, mark = self._go({"file_ids": [], "auto_new": True})
        self.assertFalse(ok)
        bot.send_media_group.assert_not_called()
        bot.send_video.assert_not_called()

    def test_auto_off(self):
        ok, bot, _ = self._go({"file_ids": ["A"], "auto_new": False})
        self.assertFalse(ok)
        bot.send_video.assert_not_called()

    def test_never_twice(self):
        ok, bot, _ = self._go({"file_ids": ["A"], "auto_new": True}, was_sent=True)
        self.assertFalse(ok)
        bot.send_video.assert_not_called()

    def test_failure_never_breaks_onboarding(self):
        with mock.patch.object(ov, "get_state", mock.AsyncMock(side_effect=RuntimeError("db"))):
            self.assertFalse(run(ov.maybe_send_to_new_user(mock.AsyncMock(), 9, "uz")))


class BroadcastTest(unittest.TestCase):
    def test_only_pending_users_each_in_own_language(self):
        from aiogram.exceptions import TelegramForbiddenError
        bot = mock.AsyncMock()
        sent_to = []

        async def fake_send(b, uid, lang, fids):
            if uid == 3:
                raise TelegramForbiddenError(method=mock.Mock(), message="blocked")
            sent_to.append((uid, lang))

        mark = mock.AsyncMock()
        with mock.patch.object(ov, "get_state", mock.AsyncMock(return_value={"file_ids": ["A", "B"], "auto_new": True})), \
             mock.patch.object(ov, "_pending_user_ids", mock.AsyncMock(return_value=[1, 2, 3])), \
             mock.patch.object(ov.database, "get_user_languages", mock.AsyncMock(return_value={1: "ru", 2: "uz_cyr"})), \
             mock.patch.object(ov, "send_videos", side_effect=fake_send), \
             mock.patch.object(ov, "_mark_sent", mark), \
             mock.patch.object(ov, "SEND_DELAY", 0):
            sent, failed = run(ov.broadcast(bot, 777))
        self.assertEqual((sent, failed), (2, 1))
        self.assertEqual(sent_to, [(1, "ru"), (2, "uz_cyr")])
        self.assertEqual([c.args[0] for c in mark.await_args_list], [1, 2])   # blocked user not marked
        self.assertFalse(ov._broadcast_running)
        self.assertEqual(bot.send_message.call_args.args[0], 777)            # admin gets the result


class KeyboardTest(unittest.TestCase):
    def test_marketing_menu_has_the_button(self):
        kb = keyboards.admin_marketing_menu_keyboard("uz")
        datas = [b.callback_data for row in kb.inline_keyboard for b in row]
        self.assertIn("admin:video", datas)

    def test_help_button_only_with_videos(self):
        from handlers.start import build_help_keyboard
        without = [b.callback_data for row in build_help_keyboard("uz").inline_keyboard for b in row]
        with_ = [b.callback_data for row in build_help_keyboard("uz", video=True).inline_keyboard for b in row]
        self.assertNotIn("howto_video", without)
        self.assertEqual(with_[0], "howto_video")


class AdminGuardTest(unittest.TestCase):
    def test_strangers_cannot_open_or_broadcast(self):
        cb = mock.AsyncMock()
        cb.from_user.id = 123456
        with mock.patch.object(ov, "ADMIN_IDS", {1}), \
             mock.patch.object(ov.asyncio, "create_task") as task:
            run(ov.open_screen(cb, mock.AsyncMock()))
            run(ov.start_all(cb))
        cb.message.edit_text.assert_not_called()
        task.assert_not_called()

    def test_video_file_id(self):
        m = mock.Mock(video=mock.Mock(file_id="V"), document=None)
        self.assertEqual(ov._video_file_id(m), "V")
        m = mock.Mock(video=None, document=mock.Mock(file_id="D", mime_type="video/mp4"))
        self.assertEqual(ov._video_file_id(m), "D")
        m = mock.Mock(video=None, document=mock.Mock(file_id="P", mime_type="application/pdf"))
        self.assertIsNone(ov._video_file_id(m))


if __name__ == "__main__":
    unittest.main()
