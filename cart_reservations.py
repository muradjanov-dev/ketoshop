"""
Savat broni — savatdagi mahsulot 24 soat egasiniki (egasi, 2026-10-13).

    "savatga solinishi bilan olindi desin, agar savatda 24 soat turib qolsa
    unda mijozni ogohlantirib sotuvga qaytariladi u savatdan olib, bir vaqtda
    2 ta yoki ko'p odamlar qolgan narsani talashib qolishmasin"

Before this, a cart held nothing: two buyers could both put the last four
packs in their carts, whoever checked out first got them, and the other —
sometimes after already paying by card — was told "only 2 left".

How it works now:
  * the hold itself is in database.py ("Savat broni"): a cart line keeps its
    quantity for its buyer until cart.reserved_until, 24 h after the buyer
    last touched the cart; adding is capped at what nobody else holds, and
    create_order never takes another buyer's hold;
  * ~4 h before the end the buyer is warned with the cart and the checkout
    buttons — that is abandoned_cart.py's stage 2;
  * here: every few minutes expired lines leave the carts (back on sale) and
    the buyer is told which ones, in their language. A release at night is
    told in the morning (09:00–21:00 only, like every buyer push);
  * /bron — admins see who holds what until when.

Buyers who see a product whose last pieces are all held get "⏳ band" rather
than "sold out" (product_card / Mini App) — owner's choice, 2026-10-13.
"""
import asyncio
import html
import logging
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import database
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router(name="cart_reservations")

CHECK_EVERY = 300                  # 5 min — a released pack is back on sale quickly
TZ_OFFSET = timedelta(hours=5)
QUIET_START, QUIET_END = 21, 9     # same quiet hours as abandoned_cart.py
SEND_DELAY = 0.05
MAX_LINES = 10


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


def _quiet(now_tk: datetime | None = None) -> bool:
    h = (now_tk or _now_tk()).hour
    return h >= QUIET_START or h < QUIET_END


def _t(uz: str, ru: str, lang: str) -> str:
    if lang == "ru":
        return ru
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        return lat_to_cyr(uz)
    return uz


def _qty(v) -> str:
    v = float(v or 0)
    return str(int(v)) if v.is_integer() else f"{v:g}"


def hold_end_text(until_utc: datetime, lang: str, now_utc: datetime | None = None) -> str:
    """'bugun 18:40' / 'ertaga 02:00' (Tashkent) — when a hold runs out."""
    end = until_utc + TZ_OFFSET
    today = ((now_utc or datetime.utcnow()) + TZ_OFFSET).date()
    clock = end.strftime("%H:%M")
    if end.date() == today:
        return _t(f"bugun {clock}", f"сегодня {clock}", lang)
    if end.date() == today + timedelta(days=1):
        return _t(f"ertaga {clock}", f"завтра {clock}", lang)
    return end.strftime("%d.%m %H:%M")


# ───────────────────────────── buyer messages ─────────────────────────────

def release_text(items: list[dict], lang: str) -> str:
    from locales import get_display_unit, localize_product_text
    lines = []
    for it in items[:MAX_LINES]:
        name = localize_product_text(it.get("name"), it.get("name_ru"), lang) or it.get("name") or "—"
        unit = get_display_unit(it.get("unit") or "piece", lang)
        lines.append(f"• {'🧺 ' if it.get('is_set') else ''}{html.escape(name, quote=False)} × {_qty(it.get('quantity'))} {unit}")
    if len(items) > MAX_LINES:
        lines.append(_t(f"… va yana {len(items) - MAX_LINES} ta", f"… и ещё {len(items) - MAX_LINES}", lang))
    return "\n".join([
        _t("🛒 <b>Savatingizdagi mahsulotlar sotuvga qaytarildi</b>",
           "🛒 <b>Товары из вашей корзины вернулись в продажу</b>", lang),
        "",
        _t("Ular 24 soat siz uchun band turdi:", "Они были закреплены за вами 24 часа:", lang),
        *lines,
        "",
        _t("Hali kerak bo'lsa — qayta qo'shing: omborda bo'lsa, yana 24 soat siz uchun band qilinadi.",
           "Если ещё нужны — добавьте снова: если они есть на складе, мы снова закрепим их за вами на 24 часа.",
           lang),
    ])


def release_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=_t("🛍 Mahsulotlarga o'tish", "🛍 К товарам", lang), callback_data="catalog")]])


async def limit_text(user_id: int, lang: str, product_id: int | None = None,
                     set_id: int | None = None) -> str:
    """Why a cart line can't grow any more: other buyers hold the rest
    ("⏳ band") or the shelf really has no more."""
    from locales import get_text
    try:
        if set_id is not None:
            async with database.pool.acquire() as conn:
                pids = [p for p, _ in await database._set_components(conn, set_id)]
        else:
            pids = [product_id]
        view = await database.stock_view(pids, user_id)
        if any(v["held"] > 0 for v in view.values()):
            return get_text("cart_held_limit", lang)
    except Exception:
        logger.warning("cart limit reason lookup failed", exc_info=True)
    return get_text("cart_stock_limit", lang)


# ───────────────────────────── release loop ─────────────────────────────

async def _send(bot: Bot, user_id: int, text: str, markup) -> bool:
    for attempt in range(2):
        try:
            await bot.send_message(user_id, text, parse_mode=ParseMode.HTML,
                                   reply_markup=markup, disable_web_page_preview=True)
            return True
        except TelegramRetryAfter as exc:
            if attempt:
                return False
            await asyncio.sleep(exc.retry_after + 1)
        except (TelegramForbiddenError, TelegramBadRequest):
            return False
        except Exception:
            logger.exception("Cart release notice to %s failed", user_id)
            return False
    return False


async def run_once(bot: Bot) -> dict:
    """Release what expired (any hour — stock must not stay locked overnight),
    then tell buyers (daytime only). Returns counters."""
    stats = {"released": 0, "sent": 0, "failed": 0}
    released = await database.release_expired_holds()
    stats["released"] = sum(len(n["items"]) for n in released)
    if released:
        logger.info("Cart holds released: %d lines for %d buyers", stats["released"], len(released))
    if _quiet():
        return stats
    notices = await database.pending_release_notices()
    if not notices:
        return stats
    langs = await database.get_user_languages([n["user_id"] for n in notices])
    for n in notices:
        if not await database.mark_release_notice_sent(n["id"]):
            continue
        lang = langs.get(n["user_id"], "uz")
        if await _send(bot, n["user_id"], release_text(n["items"], lang), release_keyboard(lang)):
            stats["sent"] += 1
        else:
            stats["failed"] += 1
        await asyncio.sleep(SEND_DELAY)
    return stats


async def scheduler_loop(bot: Bot) -> None:
    logger.info("Cart hold release loop started (every %ds)", CHECK_EVERY)
    while True:
        try:
            await run_once(bot)
        except Exception:
            logger.exception("Cart hold release tick failed")
        await asyncio.sleep(CHECK_EVERY)


# ───────────────────────────── admin view ─────────────────────────────

def holds_text(rows: list[dict], now_utc: datetime | None = None) -> str:
    if not rows:
        return "🛒 <b>Savatlardagi bron</b>\n\nHozir hech kimning savatida band mahsulot yo'q."
    by_name: dict[str, list[dict]] = {}
    for r in rows:
        by_name.setdefault(("🧺 " if r.get("is_set") else "") + str(r.get("name") or "—"), []).append(r)
    parts = [f"🛒 <b>Savatlardagi bron</b> — {len(rows)} ta qator, 24 soatlik",
             "Band mahsulotni boshqa xaridor ololmaydi; muddati tugasa sotuvga qaytadi."]
    for name, holders in by_name.items():
        held = sum(float(h["quantity"] or 0) for h in holders)
        shelf = holders[0].get("shelf")
        head = f"\n<b>{html.escape(name, quote=False)}</b> — band {_qty(held)}"
        if shelf is not None:
            head += f", omborda {_qty(shelf)}"
        parts.append(head)
        for h in holders:
            who = html.escape(h.get("full_name") or str(h["user_id"]), quote=False)
            if h.get("username"):
                who += f" (@{html.escape(h['username'], quote=False)})"
            parts.append(f"  • {who} — {_qty(h['quantity'])}, "
                         f"{hold_end_text(h['reserved_until'], 'uz', now_utc)} gacha")
    return "\n".join(parts)


@router.message(Command("bron"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_holds(message: Message):
    from bot_discount import send_long
    await send_long(message.bot, message.chat.id, holds_text(await database.live_holds()))
