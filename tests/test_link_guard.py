"""Guruhdagi havola qo'riqchisi — Telegram'ga ulanmasdan."""
import asyncio
import os
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

os.environ.setdefault("DATABASE_URL", "postgresql://test/test")
os.environ.setdefault("BOT_TOKEN", "1:test")

import link_guard
from config import ADMIN_IDS

GROUP = -1001234567890


def _msg(text="", *, user_id=555, chat_type="supergroup", entities=None,
         caption=None, caption_entities=None, markup=None, sender_chat=None, auto_fwd=False):
    return NS(
        text=text, caption=caption, entities=entities, caption_entities=caption_entities,
        reply_markup=markup, chat=NS(id=GROUP, type=chat_type),
        from_user=NS(id=user_id, first_name="Aziz") if user_id else None,
        sender_chat=sender_chat, is_automatic_forward=auto_fwd, message_id=1,
    )


def _bot(admin_ids=(111,)):
    return NS(
        id=999,
        get_chat_administrators=AsyncMock(return_value=[NS(user=NS(id=i)) for i in admin_ids]),
    )


def run(coro):
    return asyncio.run(coro)


class HasLinkTest(unittest.TestCase):
    def test_plain_text_is_not_a_link(self):
        self.assertFalse(link_guard.has_link(_msg("keto non bormi? @aziz")))

    def test_url_entity(self):
        self.assertTrue(link_guard.has_link(_msg("qarang", entities=[NS(type="url")])))

    def test_hidden_text_link(self):
        self.assertTrue(link_guard.has_link(_msg("bu yerda", entities=[NS(type="text_link")])))

    def test_link_in_photo_caption(self):
        self.assertTrue(link_guard.has_link(
            _msg(caption="aksiya", caption_entities=[NS(type="url")])))

    def test_split_telegram_link_without_entity(self):
        self.assertTrue(link_guard.has_link(_msg("kanalga kiring t . me/spam_kanal")))

    def test_url_button(self):
        markup = NS(inline_keyboard=[[NS(url="https://spam.example")]])
        self.assertTrue(link_guard.has_link(_msg("bosing", markup=markup)))


class GuardFilterTest(unittest.TestCase):
    def setUp(self):
        link_guard._admin_cache.clear()
        self._enabled, self._only = link_guard.ENABLED, link_guard.ONLY_CHATS
        link_guard.ENABLED, link_guard.ONLY_CHATS = True, set()

    def tearDown(self):
        link_guard.ENABLED, link_guard.ONLY_CHATS = self._enabled, self._only

    def link(self, **kw):
        return _msg("https://spam.example", entities=[NS(type="url")], **kw)

    def test_member_link_is_removed(self):
        self.assertTrue(run(link_guard._should_guard(self.link(), _bot())))

    def test_group_admin_may_post_links(self):
        self.assertFalse(run(link_guard._should_guard(self.link(user_id=111), _bot())))

    def test_bot_admin_may_post_links(self):
        self.assertFalse(run(link_guard._should_guard(self.link(user_id=ADMIN_IDS[0]), _bot())))

    def test_anonymous_admin_and_linked_channel(self):
        self.assertFalse(run(link_guard._should_guard(
            self.link(user_id=None, sender_chat=NS(id=GROUP)), _bot())))
        self.assertFalse(run(link_guard._should_guard(
            self.link(user_id=None, sender_chat=NS(id=-100777), auto_fwd=True), _bot())))

    def test_private_chat_is_untouched(self):
        self.assertFalse(run(link_guard._should_guard(self.link(chat_type="private"), _bot())))

    def test_unknown_admins_fail_safe(self):
        bot = _bot()
        bot.get_chat_administrators = AsyncMock(side_effect=RuntimeError("no rights"))
        self.assertFalse(run(link_guard._should_guard(self.link(), bot)))

    def test_only_chats_limits_scope(self):
        link_guard.ONLY_CHATS = {-100999}
        self.assertFalse(run(link_guard._should_guard(self.link(), _bot())))

    def test_admin_list_is_cached(self):
        bot = _bot()
        run(link_guard._should_guard(self.link(), bot))
        run(link_guard._should_guard(self.link(), bot))
        self.assertEqual(bot.get_chat_administrators.await_count, 1)


class WarningTextTest(unittest.TestCase):
    def test_kind_wording_in_the_senders_language(self):
        uz = link_guard.warning_text(5, "Aziz", "uz")
        self.assertIn('<a href="tg://user?id=5">Aziz</a>, iltimos, guruhda havola tarqatmang', uz)
        self.assertIn("noqulay bo'lishi mumkin", uz)
        self.assertIn("пожалуйста, не распространяйте ссылки", link_guard.warning_text(5, "Aziz", "ru"))
        self.assertIn("илтимос, гуруҳда ҳавола тарқатманг", link_guard.warning_text(5, "Aziz", "uz_cyr"))

    def test_without_a_name(self):
        self.assertTrue(link_guard.warning_text(5, "", "uz").startswith("🙏 Iltimos, guruhda"))


if __name__ == "__main__":
    unittest.main()
