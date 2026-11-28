"""30-day TOP-10 to the channel every 15 days at 10:00 Tashkent (was every 3;
owner, 2026-11-28: "bu e'lon har 15 kunda 1 chiqsin").

Starts 23 October 2026. Names and the amount sold in those 30 days are
public (owner, 2026-11-06: "Количествасиниям ёзиш керак"); stock is not.
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
import channel_link

import database
from config import REQUIRED_CHANNEL_ID
from translit import lat_to_cyr

logger = logging.getLogger(__name__)
START = date(2026, 10, 23)
EVERY_DAYS = 15
SEND_HOUR = 10
LAST_HOUR = 22
CHECK_EVERY = 300


def _now_tk() -> datetime:
    return datetime.now(timezone(timedelta(hours=5)))


def _amount(value: float) -> str:
    value = round(float(value), 1)
    if value.is_integer():
        return f"{int(value):,}".replace(",", " ")
    return f"{value:.1f}".replace(".", ",")


_TO_KG = {"кг": 1.0, "г": 0.001, "гр": 0.001, "л": 1.0, "мл": 0.001}


def merged(sold: dict, name: str | None = None, unit: str | None = None) -> dict:
    """Packs and kilos as ONE number (owner, 2026-11-28: «53 та + 5 кг» → yes,
    merge). The kilos (wholesale / fractional lines) become packs when the
    name says the pack size («Ҳималай туз 1000гр»: 53 + 5/1 = 58 та); a
    product sold by the kilo with no size in its name (unit kg: one «та» is
    one kilo) becomes kilos («Кепак»: 190 + 226 = 416 кг). Anything else
    stays apart."""
    sold = {k: v for k, v in (sold or {}).items() if v > 0}
    packs = sold.get("", 0.0)
    kilos = sum(q * _TO_KG[u] for u, q in sold.items() if u in _TO_KG)
    if not packs or not kilos:
        return sold
    rest = {u: q for u, q in sold.items() if u and u not in _TO_KG}
    import uzpost
    pack = uzpost.pack_kg(name)
    if pack:
        return {"": packs + kilos / pack, **rest}
    if unit in ("kg", "кг"):
        return {"кг": packs + kilos, **rest}
    return sold


def sold_text(sold: dict, name: str | None = None, unit: str | None = None) -> str:
    """ "37 та", "50 кг", "58 та" (packs and kilos merged — see merged())."""
    parts = []
    for u, qty in sorted(merged(sold, name, unit).items(), key=lambda kv: (kv[0] != "", kv[0])):
        if qty <= 0:
            continue
        if u == "" and qty >= 1:
            qty = round(qty)               # whole packs read better: 57,6 та → 58 та
        parts.append(f"{_amount(qty)} {u or 'та'}")
    return " + ".join(parts)


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
        amount = sold_text(product.get("sold"), product.get("name"), product.get("unit"))
        lines.append(f"{rank}. {html.escape(name, quote=False)}" + (f" — <b>{amount}</b>" if amount else ""))
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
    # The shop link in the text, no button — a button hides the comments.
    text = channel_link.with_link(build_text(products))
    key = f"channel-bestsellers:{day.isoformat()}"
    if not await database.claim_release_notes(key):
        return
    try:
        await bot.send_message(REQUIRED_CHANNEL_ID, text, parse_mode=ParseMode.HTML,
                               disable_web_page_preview=True)
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
