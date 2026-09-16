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

# Tip content is authored in Uzbek (see broadcast_tips.py). Every buyer still
# reads it in their own language (owner, 2026-09-17: "har doim o'z tilida"):
# Cyrillic Uzbek is transliterated, Russian is machine-translated once per tip
# — see localized_tip.
_SHOP_LABEL = {"uz": "🌿 Do'konga o'tish", "ru": "🌿 В магазин"}


def shop_button(lang: str = "uz") -> InlineKeyboardMarkup | None:
    if not WEBAPP_URL:
        return None
    label = _SHOP_LABEL["ru"] if lang == "ru" else _SHOP_LABEL["uz"]
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        label = lat_to_cyr(label)
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, web_app=WebAppInfo(url=WEBAPP_URL))
    ]])


_SHOP_BUTTON = shop_button("uz")

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


_AI_TRANSLATE_RULES = (
    "Translate the Uzbek (Latin script) text into natural, simple Russian for a "
    "shop's Telegram customers. Keep every emoji, line break and **bold** marker "
    "exactly where they are. Keep @usernames, links and phone numbers unchanged. "
    "Reply with the translation only."
)


async def _ai_translate_ru(raw: str) -> str | None:
    """Fallback translator: the AI provider the sales bot already uses (only
    when a key is configured). Usage is booked like every other AI call."""
    try:
        import ai_provider
        provider = ai_provider.build()
        if provider is None:
            return None
        turn = await provider.step({}, _AI_TRANSLATE_RULES, "", None, user=raw, max_tokens=2000)
        usage = turn.usage
        if usage and (usage.input or usage.output):
            cost = ai_provider.estimate_cost(provider.model, usage.input, usage.cached, usage.output)
            await database.record_ai_usage(provider.model, provider.name, usage.input,
                                           usage.cached, usage.output, cost)
        return (turn.text or "").strip() or None
    except Exception:
        logger.warning("AI translation of a tip failed", exc_info=True)
        return None


async def localized_tip(raw: str, lang: str) -> str | None:
    """The tip as HTML in `lang`, or None when it can't be given in that
    language (Russian translation unavailable) — then that buyer skips this
    tip rather than getting it in a language they didn't choose."""
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        return lat_to_cyr(_format_tip(raw))
    if lang != "ru":
        return _format_tip(raw)
    from translator import translate
    ru = None
    for attempt in range(3):              # the free endpoint throttles bursts
        ru = await translate(raw, "uz", "ru")
        if ru and ru.strip() != raw.strip():
            break
        ru = None
        await asyncio.sleep(5 * (attempt + 1))
    if not ru:
        ru = await _ai_translate_ru(raw)  # the shop's own AI key, if configured
    if not ru:
        return None
    # The translator sometimes pads the **bold** markers ("** Совет **") or
    # loses one of a pair; tidy them, and drop them all if they don't pair up.
    ru = re.sub(r"\*\*\s*(.+?)\s*\*\*", r"**\1**", ru, flags=re.S)
    if ru.count("**") % 2:
        ru = ru.replace("**", "")
    return _format_tip(ru)


async def _broadcast_to_all(bot: Bot, text: str | dict) -> tuple[int, int]:
    """Send to every eligible user. `text` is one HTML string, or a
    {lang: HTML | None} map — a None language is skipped. Returns (sent, failed)."""
    user_ids = await database.get_all_user_ids()
    langs = await database.get_user_languages(user_ids) if isinstance(text, dict) else {}
    sent = failed = 0
    for uid in user_ids:
        lang = langs.get(uid, "uz")
        body = text.get(lang, text.get("uz")) if isinstance(text, dict) else text
        if body is None:
            continue
        markup = shop_button(lang)
        try:
            await bot.send_message(
                uid, body, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                reply_markup=markup,
            )
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
            try:
                await bot.send_message(
                    uid, body, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                    reply_markup=markup,
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

    raw = TIPS[idx]
    texts = {lang: await localized_tip(raw, lang) for lang in ("uz", "uz_cyr", "ru")}
    if texts["ru"] is None:
        logger.warning("Tip #%d: Russian translation unavailable — Russian-language users skip it", idx + 1)
    sent, failed = await _broadcast_to_all(bot, texts)
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
