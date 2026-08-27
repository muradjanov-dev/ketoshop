"""
Scheduled tips broadcaster.

Sends the next keto tip from broadcast_tips.TIPS to every (non-banned) user on a
2-day cadence at ~08:00 Asia/Tashkent. State (which tip is next, when the last
one went out) lives in the broadcast_state DB row, so the cadence survives
restarts and redeploys.

Admins get a per-send delivery summary and, when content is running low
(<= WARN_REMAINING tips left), a once-a-day "top up the tips" reminder.
"""
import asyncio
import html
import logging
import re
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramBadRequest,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

import database
from broadcast_tips import TIPS
from config import ADMIN_IDS, WEBAPP_URL

logger = logging.getLogger(__name__)

# Tip content is Uzbek-only (see broadcast_tips.py), so the button label is
# fixed rather than looked up per-recipient language.
_SHOP_BUTTON = (
    InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🌿 Do'konga o'tish", web_app=WebAppInfo(url=WEBAPP_URL))
    ]])
    if WEBAPP_URL else None
)

# Asia/Tashkent is a fixed UTC+5 offset (no DST) — avoid a tzdata dependency.
TZ_OFFSET = timedelta(hours=5)
SEND_HOUR = 8           # 08:00 Tashkent
INTERVAL_DAYS = 2       # every 2 days
WARN_REMAINING = 5      # ~10 days of content left (5 tips * 2 days)
CHECK_EVERY = 900       # re-check every 15 minutes
SEND_DELAY = 0.05       # pause between user sends (~20/sec, under Telegram limits)


def _format_tip(text: str) -> str:
    """Convert stored tip text to Telegram-safe HTML (**bold** -> <b>)."""
    text = html.escape(text, quote=False)
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text, flags=re.S)


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


async def _notify_admins(bot: Bot, text: str):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception:
            pass


async def _broadcast_to_all(bot: Bot, text: str) -> tuple[int, int]:
    """Send `text` to every eligible user. Returns (sent, failed)."""
    user_ids = await database.get_all_user_ids()
    sent = failed = 0
    for uid in user_ids:
        try:
            await bot.send_message(
                uid, text, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                reply_markup=_SHOP_BUTTON,
            )
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await bot.send_message(
                    uid, text, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                    reply_markup=_SHOP_BUTTON,
                )
                sent += 1
            except Exception:
                failed += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            # User blocked the bot / never started it / deactivated — skip.
            failed += 1
        except Exception:
            logger.exception("Broadcast send failed for user %s", uid)
            failed += 1
        await asyncio.sleep(SEND_DELAY)
    return sent, failed


async def send_next_tip(bot: Bot) -> tuple[int, int] | None:
    """Send the next queued tip to everyone. Returns (sent, failed) or None if
    there are no tips left to send."""
    state = await database.get_broadcast_state()
    idx = state["next_index"]
    if idx >= len(TIPS):
        return None

    text = _format_tip(TIPS[idx])
    sent, failed = await _broadcast_to_all(bot, text)
    await database.advance_broadcast(idx + 1)

    remaining = len(TIPS) - (idx + 1)
    await _notify_admins(
        bot,
        f"📤 Eslatma <b>#{idx + 1}/{len(TIPS)}</b> yuborildi.\n"
        f"✅ {sent} ta yetkazildi, ⚠️ {failed} ta yetmadi.\n"
        f"📦 {remaining} ta eslatma qoldi (~{remaining * INTERVAL_DAYS} kun).",
    )
    logger.info("Broadcast tip #%d sent: %d ok, %d failed", idx + 1, sent, failed)
    return sent, failed


async def _maybe_warn_low_content(bot: Bot, state: dict):
    """Once a day, if content is nearly exhausted, nudge admins to add more."""
    remaining = len(TIPS) - state["next_index"]
    if remaining > WARN_REMAINING:
        return
    now_tk = _now_tk()
    if now_tk.hour < SEND_HOUR:
        return
    if state["last_warn_date"] == now_tk.date():
        return  # already warned today

    if remaining <= 0:
        msg = (
            "🛑 <b>Eslatmalar tugadi!</b>\n"
            "Yangi eslatma qo'shmaguningizcha yuborish to'xtaydi.\n"
            "broadcast_tips.py fayliga yangi eslatmalar qo'shing."
        )
    else:
        msg = (
            f"⚠️ <b>Eslatmalar tugayapti:</b> {remaining} ta qoldi "
            f"(~{remaining * INTERVAL_DAYS} kun).\n"
            "Yangi eslatmalar qo'shishni unutmang."
        )
    await _notify_admins(bot, msg)
    await database.set_broadcast_warn_date(now_tk.date())


async def _tick(bot: Bot):
    state = await database.get_broadcast_state()
    if not state["enabled"]:
        return

    await _maybe_warn_low_content(bot, state)

    if state["next_index"] >= len(TIPS):
        return  # nothing left to send

    last = state["last_sent_at"]
    if last is None:
        due = True  # first send after arming — goes out immediately
    else:
        now_tk = _now_tk()
        last_tk = last + TZ_OFFSET
        elapsed_days = (now_tk.date() - last_tk.date()).days
        due = elapsed_days >= INTERVAL_DAYS and now_tk.hour >= SEND_HOUR

    if due:
        await send_next_tip(bot)


async def scheduler_loop(bot: Bot):
    """Background task: check every CHECK_EVERY seconds whether a tip is due."""
    logger.info("Broadcast scheduler started (%d tips loaded)", len(TIPS))
    while True:
        try:
            await _tick(bot)
        except Exception:
            logger.exception("Broadcast tick failed")
        await asyncio.sleep(CHECK_EVERY)
