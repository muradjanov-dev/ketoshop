"""30-day TOP-10 to the channel every three days at 10:00 Tashkent.

Starts 23 October 2026. Only names are public: no sales or stock counts.
Each date is claimed atomically in the existing release_notes_sent table
before sending, so restarts/overlapping workers cannot duplicate a post.
Definite Telegram rejections release the claim for a retry. An ambiguous
network failure retains it: Telegram may already have published the post.
"""
import asyncio
import html
import logging
from datetime import date, datetime, timedelta, timezone

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import database
from config import BOT_USERNAME, REQUIRED_CHANNEL_ID
from translit import lat_to_cyr

logger = logging.getLogger(__name__)
START = date(2026, 10, 23)
EVERY_DAYS = 3
SEND_HOUR = 10
LAST_HOUR = 22
CHECK_EVERY = 300


def _now_tk() -> datetime:
    return datetime.now(timezone(timedelta(hours=5)))


def build_text(products: list[dict]) -> str:
    lines = ["🏆 <b>Охирги 30 кунда энг кўп сотилган маҳсулотлар</b>", "",
             "Харидорларимиз энг кўп танлаган маҳсулотлар:", ""]
    for rank, product in enumerate(products[:10], 1):
        # Bound each name before escaping so even a very long catalogue name
        # cannot overflow Telegram's message limit or split an HTML entity.
        name = " ".join(str(product["name"]).split())
        name = lat_to_cyr(name[:119] + "…" if len(name) > 120 else name)
        while len(html.escape(name, quote=False)) > 300:
            name = name[:-2] + "…"
        lines.append(f"{rank}. {html.escape(name, quote=False)}")
    lines += ["", "🌿 Ўзингизга мос маҳсулотларни дўконимиздан танланг!", "@ketoshop_uz"]
    return "\n".join(lines)


async def _tick(bot: Bot) -> None:
    now = _now_tk()
    day = now.date()
    if not REQUIRED_CHANNEL_ID or day < START or (day - START).days % EVERY_DAYS:
        return
    if not SEND_HOUR <= now.hour < LAST_HOUR:
        return
    products = await database.get_channel_bestsellers()
    if not products:
        return
    text = build_text(products)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🛒 Дўконни очиш", url=f"https://t.me/{BOT_USERNAME}/shop")
    ]])
    key = f"channel-bestsellers:{day.isoformat()}"
    if not await database.claim_release_notes(key):
        return
    try:
        await bot.send_message(REQUIRED_CHANNEL_ID, text, parse_mode=ParseMode.HTML,
                               reply_markup=keyboard, disable_web_page_preview=True)
    except (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter):
        await database.release_release_notes(key)
        logger.warning("Bestseller channel post rejected; retry next tick (%s)", key, exc_info=True)
    except Exception:
        # Timeout/disconnect can happen AFTER Telegram accepted the message.
        # Keep the claim rather than risk publishing the same list twice.
        logger.exception("Bestseller delivery uncertain; claim retained (%s)", key)
    else:
        logger.info("Bestseller channel post sent (%s, %d products)", key, len(products))


async def scheduler_loop(bot: Bot) -> None:
    logger.info("Bestseller channel scheduler: every 3 days from %s, 10:00 Tashkent", START)
    while True:
        try:
            await _tick(bot)
        except Exception:
            logger.exception("Bestseller channel scheduler failed")
        await asyncio.sleep(CHECK_EVERY)
