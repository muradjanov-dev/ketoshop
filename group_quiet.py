"""
Guruhda jim bot — owner, 2026-10-04: "in the telegram chat where bot is admin
there appeared bot buttons so users now able to click … please remove them
from group".

The shop lives in the bot's private chat. In a group the bot keeps only its
group jobs (link guard, the AI seller's text replies, order notifications in
the admins' own group) and stops being a menu:

  * a slash command typed in a group gets no reply — the command message is
    deleted instead (the bot is admin there), so no menu with buttons lands
    in front of the whole group. This holds for EVERYONE, admins and the
    group's anonymous admin included (owner, 2026-10-04, after an anonymous
    "/start" put the language buttons in KETOSHOP chat). The only exception:
    a bot admin's own admin command (ADMIN_COMMANDS, e.g. /ombor) — those
    print reports, not shop menus;
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


def _command_name(message: Message) -> str:
    text = (message.text or message.caption or "").strip()
    return text.split()[0][1:].split("@")[0].lower() if text.startswith("/") else ""


def _admin_command_names() -> set[str]:
    from keyboards import ADMIN_COMMANDS
    return {c.command.lower() for c in ADMIN_COMMANDS}


def _command_allowed_in_group(message: Message) -> bool:
    """Only a bot admin (a real account, not the group's anonymous identity)
    running one of the admin report commands."""
    user = message.from_user
    if message.sender_chat is not None or user is None or user.id not in ADMIN_IDS:
        return False
    return _command_name(message) in _admin_command_names()


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
                if not _command_allowed_in_group(event):
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
