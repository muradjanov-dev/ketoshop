"""
Savat broni — savatdagi mahsulot 6 soat egasiniki (egasi, 2026-10-13; 24 soatdan
6 soatga — 2026-10-16: "mijoz savatida 24 soat emas 6 soat saqlansin keyin
ogohlantirish bilan do'konga qaytarilsin"; database.RESERVE_HOURS).

    "savatga solinishi bilan olindi desin, agar savatda 24 soat turib qolsa
    unda mijozni ogohlantirib sotuvga qaytariladi u savatdan olib, bir vaqtda
    2 ta yoki ko'p odamlar qolgan narsani talashib qolishmasin"

Before this, a cart held nothing: two buyers could both put the last four
packs in their carts, whoever checked out first got them, and the other —
sometimes after already paying by card — was told "only 2 left".

How it works now:
  * the hold itself is in database.py ("Savat broni"): a cart line keeps its
    quantity for its buyer until cart.reserved_until, RESERVE_HOURS after the
    buyer last touched the cart; adding is capped at what nobody else holds,
    and create_order never takes another buyer's hold;
  * before the end the buyer is warned with the end time, the cart and the
    checkout buttons — abandoned_cart.py's warning stage (3 h into a 6 h hold);
  * here: every few minutes expired lines leave the carts (back on sale) and
    the buyer is told which ones, in their language. A release at night is
    told in the morning (09:00–21:00 only, like every buyer push);
  * whoever was refused a held product — or tapped "🔔 Bo'shasa xabar bering"
    on its "⏳ band" card — is on its waitlist and hears "siz so'ragan mahsulot
    sotuvga qaytdi" right after the release (restock_notify.py);
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
    hours = database.RESERVE_HOURS
    return "\n".join([
        _t("🛒 <b>Savatingizdagi mahsulotlar sotuvga qaytarildi</b>",
           "🛒 <b>Товары из вашей корзины вернулись в продажу</b>", lang),
        "",
        _t(f"Ular {hours} soat siz uchun band turdi:", f"Они были закреплены за вами {hours} ч:", lang),
        *lines,
        "",
        _t(f"Hali kerak bo'lsa — qayta qo'shing: omborda bo'lsa, yana {hours} soat siz uchun band qilinadi.",
           f"Если ещё нужны — добавьте снова: если они есть на складе, мы снова закрепим их за вами на {hours} ч.",
           lang),
    ])


def release_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=_t("🛍 Mahsulotlarga o'tish", "🛍 К товарам", lang), callback_data="catalog")]])


async def limit_text(user_id: int, lang: str, product_id: int | None = None,
                     set_id: int | None = None) -> str:
    """Why a cart line can't grow any more: other buyers hold the rest
    ("⏳ band") or the shelf really has no more.

    A buyer refused a product because of a hold has asked for it: they go on
    its waitlist and hear "siz so'ragan mahsulot sotuvga qaytdi" when the hold
    runs out (owner, 2026-10-16) — the text says so."""
    from locales import get_text
    try:
        if set_id is not None:
            async with database.pool.acquire() as conn:
                pids = [p for p, _ in await database._set_components(conn, set_id)]
        else:
            pids = [product_id]
        view = await database.stock_view(pids, user_id)
        if any(v["held"] > 0 for v in view.values()):
            if set_id is not None:
                return get_text("cart_held_limit_set", lang, hours=database.RESERVE_HOURS)
            await wait_for_hold(user_id, product_id, lang, "held")
            return get_text("cart_held_limit", lang, hours=database.RESERVE_HOURS)
    except Exception:
        logger.warning("cart limit reason lookup failed", exc_info=True)
    return get_text("cart_stock_limit", lang)


async def wait_for_hold(user_id: int, product_id: int, lang: str, source: str) -> bool:
    """Put a buyer who couldn't get a held product on its waitlist. True = on
    the list now (or already was). Never raises — a refused add still answers."""
    try:
        import restock_notify
        return await restock_notify.subscribe(user_id, int(product_id), lang, source) in ("added", "already")
    except Exception:
        logger.warning("held-product waitlist failed for %s / %s", user_id, product_id, exc_info=True)
        return False


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
    if released:
        # Whoever waited for these products hears now, not at the next
        # restock sweep (restock_notify claims each wait, so no double send).
        try:
            import restock_notify
            await restock_notify.run_once(bot)
        except Exception:
            logger.exception("Waitlist sweep after a hold release failed")
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
    parts = [f"🛒 <b>Savatlardagi bron</b> — {len(rows)} ta qator, {database.RESERVE_HOURS} soatlik",
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
