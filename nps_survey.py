"""
One-time NPS (1-10) satisfaction survey — sent to every buyer who has placed
at least one real (non-manual) order, with an inline 1-10 score keyboard.
After tapping a score the buyer is asked why (free text), and every new
score + reason is relayed live to all admins as it comes in.

Public API:
  nps_score_keyboard()                         -> InlineKeyboardMarkup
  send_nps_batch(bot, only_user=None)          -> (sent, failed)
  notify_admins_new_vote(bot, user, score)     -> fired right when a score is tapped
  notify_admins_reason(bot, user, score, text) -> fired once the reason arrives (or /skip)
"""
import asyncio
import logging

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import database
from config import ADMIN_IDS
from locales import get_text

logger = logging.getLogger(__name__)

SEND_DELAY = 0.05  # ~20 msgs/sec, under Telegram limits, same as other broadcasters


def nps_score_keyboard() -> InlineKeyboardMarkup:
    row1 = [InlineKeyboardButton(text=str(n), callback_data=f"nps_score:{n}") for n in range(1, 6)]
    row2 = [InlineKeyboardButton(text=str(n), callback_data=f"nps_score:{n}") for n in range(6, 11)]
    return InlineKeyboardMarkup(inline_keyboard=[row1, row2])


def _who(user: dict | None, user_id: int) -> str:
    if user and user.get("username"):
        return f"@{user['username']}"
    if user and user.get("full_name"):
        return user["full_name"]
    return f"ID {user_id}"


async def notify_admins_new_vote(bot: Bot, user: dict | None, user_id: int, score: int):
    """Fired the moment a buyer taps a score — so no vote is lost even if
    they never answer the follow-up "why" question."""
    text = (
        f"🗳 <b>Yangi NPS ovoz</b>\n"
        f"👤 {_who(user, user_id)} (ID: <code>{user_id}</code>)\n"
        f"⭐ Baho: <b>{score}/10</b>\n"
        f"💬 Sababi so'ralmoqda…"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception:
            pass


async def notify_admins_reason(bot: Bot, user: dict | None, user_id: int, score: int, comment: str | None):
    """Fired once the buyer's free-text reason (or /skip) arrives."""
    comment_text = comment if comment else "— (izoh berilmadi)"
    text = (
        f"📝 <b>NPS sababi keldi</b>\n"
        f"👤 {_who(user, user_id)} (ID: <code>{user_id}</code>)\n"
        f"⭐ Baho: <b>{score}/10</b>\n"
        f"💬 Sababi: {comment_text}"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception:
            pass


async def send_nps_batch(bot: Bot, only_user: int | None = None) -> tuple[int, int]:
    """Send the survey to every eligible buyer. `only_user` restricts the
    send to a single id (used for a preview). Returns (sent, failed)."""
    if only_user is not None:
        user_ids = [only_user]
    else:
        user_ids = await database.get_user_ids_with_orders()
        user_ids = [uid for uid in user_ids if uid not in database.LEADERBOARD_EXCLUDED_USER_IDS]

    kb = nps_score_keyboard()
    sent = failed = 0
    for uid in user_ids:
        try:
            lang = await database.get_user_language(uid)
            text = get_text("nps_survey_prompt", lang)
            try:
                await bot.send_message(uid, text, reply_markup=kb, parse_mode=ParseMode.HTML)
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                await bot.send_message(uid, text, reply_markup=kb, parse_mode=ParseMode.HTML)
            sent += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            failed += 1
        except Exception:
            logger.exception("NPS survey send failed for user %s", uid)
            failed += 1
        await asyncio.sleep(SEND_DELAY)
    return sent, failed
