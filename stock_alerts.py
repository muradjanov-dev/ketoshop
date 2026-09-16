"""
Ombor ogohlantirishlari — low / out-of-stock alerts to every admin (2026-09-17).

Owner's ask: tell ALL admins about products that are out of stock or have
fewer than 5 left, and do it again every time a product reaches that limit.

Why a watcher instead of the old per-order hook: stock also drops or changes
outside a buyer's checkout — aksiya bonuses and gifts decrement it without an
alert, admins edit quantities by hand, manual orders and the web panel write it
directly. Comparing each product's current level with the last level we
alerted about catches every one of those paths, including ones added later.

Levels per product:
    ok   — quantity ≥ limit
    low  — 0 < quantity < limit          ("⚠️ kam qoldi")
    out  — quantity ≤ 0                   ("🚫 tugadi")
The limit is the product's own low_stock_threshold when an admin set one in
the product editor, otherwise LOW_STOCK_THRESHOLD (5).

An alert goes out only when a product gets WORSE (ok→low, ok→out, low→out).
When it's restocked back to ok the level resets, so the next time it runs
down the admins hear about it again — "har safar limit shunga kelganda".

First run after deploy: the current levels are recorded silently and ONE
summary of everything already low/out goes to the admins (during daytime),
instead of a separate message for each of dozens of products.

Checkouts still call notify_low_stock() → check_now(), so an order that empties
a shelf alerts within seconds rather than at the next sweep.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message

import database
from config import ADMIN_IDS, LOW_STOCK_THRESHOLD

logger = logging.getLogger(__name__)
router = Router()

TZ_OFFSET = timedelta(hours=5)
CHECK_EVERY = 120                  # 2 min sweep for non-checkout stock changes
SUMMARY_HOURS = (8, 22)            # first-run summary only 08:00–21:59 Tashkent
_RANK = {"ok": 0, "low": 1, "out": 2}
_lock = asyncio.Lock()


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


def limit_for(product: dict) -> float:
    custom = product.get("low_stock_threshold")
    return float(custom) if custom else float(LOW_STOCK_THRESHOLD)


def level_for(product: dict) -> str:
    qty = float(product.get("quantity") or 0)
    if qty <= 0:
        return "out"
    if qty < limit_for(product):
        return "low"
    return "ok"


def _qty(value: float) -> str:
    value = float(value or 0)
    return str(int(value)) if value.is_integer() else f"{value:.1f}"


def _unit(product: dict, lang: str) -> str:
    from locales import get_display_unit
    try:
        return get_display_unit(product.get("unit") or "", lang)
    except Exception:
        return ""


def _alert_text(product: dict, level: str, lang: str) -> str:
    name = product["name"]
    limit = _qty(limit_for(product))
    if lang == "ru":
        if level == "out":
            return (f"🚫 <b>Товар закончился!</b>\n\n📦 {name}\n\n"
                    "Пока склад не пополнен, покупатели не смогут его заказать.")
        return (f"⚠️ <b>Заканчивается товар!</b>\n\n📦 {name}\n"
                f"🔢 Осталось: <b>{_qty(product['quantity'])} {_unit(product, lang)}</b> "
                f"(порог: {limit})\n\nПожалуйста, пополните склад.")
    if level == "out":
        text = (f"🚫 <b>Mahsulot tugadi!</b>\n\n📦 {name}\n\n"
                "Omborni to'ldirmaguncha xaridorlar uni buyurtma qila olmaydi.")
    else:
        text = (f"⚠️ <b>Mahsulot kam qoldi!</b>\n\n📦 {name}\n"
                f"🔢 Qolgan: <b>{_qty(product['quantity'])} {_unit(product, lang)}</b> "
                f"(chegara: {limit})\n\nIltimos, omborni to'ldiring.")
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        text = lat_to_cyr(text)
    return text


def summary_text(products: list[dict]) -> str:
    out = [p for p in products if level_for(p) == "out"]
    low = [p for p in products if level_for(p) == "low"]
    if not out and not low:
        return "✅ <b>Ombor holati</b>\n\nBarcha faol mahsulotlar yetarli miqdorda."
    lines = ["📦 <b>Ombor holati</b>", ""]
    if out:
        lines.append(f"🚫 <b>Tugagan ({len(out)} ta):</b>")
        lines += [f"• {p['name']}" for p in sorted(out, key=lambda p: p["name"].lower())]
        lines.append("")
    if low:
        lines.append(f"⚠️ <b>Kam qolgan ({len(low)} ta):</b>")
        lines += [f"• {p['name']} — <b>{_qty(p['quantity'])} {_unit(p, 'uz')}</b>"
                  for p in sorted(low, key=lambda p: float(p["quantity"] or 0))]
        lines.append("")
    lines.append("Mahsulot shu holatga har safar tushganda alohida ogohlantirish keladi.")
    return "\n".join(lines)


async def _send_all(bot: Bot, build) -> None:
    """build(lang) -> text. One message per admin in their own language."""
    for admin_id in ADMIN_IDS:
        try:
            lang = await database.get_user_language(admin_id)
        except Exception:
            lang = "uz"
        try:
            await bot.send_message(admin_id, build(lang), parse_mode=ParseMode.HTML)
        except Exception as exc:
            logger.warning("Stock alert to admin %s failed: %s", admin_id, exc)


def _chunks(text: str, size: int = 3800) -> list[str]:
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > size:
            parts.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        parts.append(cur)
    return parts


async def check_now(bot: Bot) -> int:
    """Compare every active product with its last alerted level; alert the
    ones that got worse. Returns how many alerts went out."""
    async with _lock:
        products = await database.get_stock_snapshot()

        if not await database.stock_alerts_initialized():
            # First run: record silently, one summary goes out separately.
            await database.set_stock_alert_levels({p["id"]: level_for(p) for p in products})
            await database.init_stock_alerts()
            return 0

        known = await database.get_stock_alert_levels()

        changed, worse = {}, []
        for p in products:
            new = level_for(p)
            old = known.get(p["id"], "ok")
            if new != old:
                changed[p["id"]] = new
                if _RANK[new] > _RANK[old]:
                    worse.append((p, new))
        if changed:
            await database.set_stock_alert_levels(changed)

    for product, level in worse:
        await _send_all(bot, lambda lang, p=product, lv=level: _alert_text(p, lv, lang))
    return len(worse)


async def _maybe_send_summary(bot: Bot) -> None:
    hour = _now_tk().hour
    if not (SUMMARY_HOURS[0] <= hour < SUMMARY_HOURS[1]):
        return
    if not await database.claim_stock_summary():
        return
    text = summary_text(await database.get_stock_snapshot())
    for part in _chunks(text):
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, part, parse_mode=ParseMode.HTML)
            except Exception as exc:
                logger.warning("Stock summary to admin %s failed: %s", admin_id, exc)


async def scheduler_loop(bot: Bot) -> None:
    logger.info("Stock alert watcher started (limit %s)", LOW_STOCK_THRESHOLD)
    while True:
        try:
            await check_now(bot)
            await _maybe_send_summary(bot)
        except Exception:
            logger.exception("Stock alert sweep failed")
        await asyncio.sleep(CHECK_EVERY)


@router.message(Command("ombor"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_stock(message: Message):
    """Current low / out-of-stock list on demand."""
    for part in _chunks(summary_text(await database.get_stock_snapshot())):
        await message.answer(part, parse_mode=ParseMode.HTML)
