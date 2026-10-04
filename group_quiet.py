"""
Guruhda jim bot — owner, 2026-10-04: "in the telegram chat where bot is admin
there appeared bot buttons so users now able to click … please remove them
from group".

The shop lives in the bot's private chat. In a group the bot keeps only its
group jobs (link guard, the AI seller's text replies, order notifications in
the admins' own group) and stops being a menu:

  * a slash command typed in a group by an ordinary member gets no reply —
    the command message is deleted instead (the bot is admin there), so no
    menu with buttons lands in front of the whole group;
  * a button under a bot message in a group answers only admins (bot admins
    and the group's own admins); members' taps are acknowledged silently;
  * the "/" menu is published for private chats only (see bot.py
    _register_commands), so groups don't show it at all.

Group admins and bot admins keep full use: the admins' order group still
works with its Qabul / Yo'lda buttons.
"""
import logging

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from config import ADMIN_IDS

logger = logging.getLogger(__name__)

GROUP_TYPES = ("group", "supergroup")


def _is_command(message: Message) -> bool:
    text = message.text or message.caption or ""
    return text.startswith("/")


async def _is_group_admin(bot, chat_id: int, user_id: int | None) -> bool:
    if not user_id:
        return False
    if user_id in ADMIN_IDS:
        return True
    import link_guard
    admins = await link_guard._chat_admin_ids(bot, chat_id)
    # Unknown admin list (API hiccup) → treat as admin: never block staff
    # because Telegram didn't answer.
    return admins is None or user_id in admins


class GroupQuietMiddleware(BaseMiddleware):
    """Outer middleware for messages and callback queries."""

    async def __call__(self, handler, event, data):
        bot = data.get("bot")
        try:
            if isinstance(event, Message) and event.chat.type in GROUP_TYPES and _is_command(event):
                if event.sender_chat is None and not await _is_group_admin(
                        bot, event.chat.id, event.from_user.id if event.from_user else None):
                    try:
                        await event.delete()
                    except Exception:
                        logger.info("group_quiet: could not delete a command in %s", event.chat.id)
                    return None
            if (isinstance(event, CallbackQuery) and event.message is not None
                    and event.message.chat.type in GROUP_TYPES
                    and not await _is_group_admin(bot, event.message.chat.id, event.from_user.id)):
                try:
                    await event.answer()
                except Exception:
                    pass
                return None
        except Exception:
            logger.exception("group_quiet failed — letting the update through")
        return await handler(event, data)
