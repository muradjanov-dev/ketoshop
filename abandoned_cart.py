"""
Tashlab ketilgan savat eslatmasi — abandoned-cart reminders (2026-09-17).

A buyer puts products in the cart and leaves without ordering. Two gentle
touches bring them back:

    stage 1 — cart idle 3 h    "Savatingiz sizni kutyapti" + one-tap checkout
    stage 2 — cart idle 24 h   "Mahsulotlaringiz hali saqlanmoqda" (last one)

Rules that keep it from turning into spam:
  * "idle" is measured from the LAST time the buyer touched the cart (any add,
    +/- or removal resets it — see cart.updated_at). A buyer who comes back
    and edits the cart starts a fresh cycle; one who ignores both touches
    hears nothing more about that cart;
  * at most one message per (buyer, stage, cart state) — the slot is claimed
    in cart_reminders BEFORE sending, so a restart mid-batch can't double up;
  * quiet hours: only 09:00–21:00 Tashkent. A reminder that falls due at
    night waits for the morning (the stage windows are wide enough for that);
  * never for admin / shop accounts, banned users, a buyer who already
    ordered after touching the cart, or a cart whose products are all sold out;
  * carts that already existed before this feature shipped are never
    reminded about (their updated_at stays NULL — see database.init_db).

Every reminder carries the cart itself, its total, the 111 000 so'm gift
status (gift_campaign.py) and the checkout buttons, so the buyer can finish
the order from the reminder in one or two taps without looking for the cart.

Results are measured: each reminder is credited with the first order its
buyer places within 7 days. /savat_eslatma shows sent / converted / revenue.
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
import gift_campaign
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router()

TZ_OFFSET = timedelta(hours=5)
CHECK_EVERY = 600                 # 10 min
QUIET_START, QUIET_END = 21, 9    # no messages 21:00–09:00 Tashkent
SEND_DELAY = 0.05
MAX_LINES = 8                     # cart lines listed before "… va yana N ta"

# (stage, min idle minutes, max idle minutes). The upper bound is what lets a
# night-time reminder wait for the morning without ever firing days late.
STAGES = (
    (1, 3 * 60, 20 * 60),
    (2, 24 * 60, 60 * 60),
)


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


def _quiet_now() -> bool:
    h = _now_tk().hour
    return h >= QUIET_START or h < QUIET_END


def fmt_sum(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", " ")


def _t(uz: str, ru: str, lang: str) -> str:
    if lang == "ru":
        return ru
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        return lat_to_cyr(uz)
    return uz


# ─────────────────────────────── message ────────────────────────────────────

async def build_reminder(user_id: int, stage: int, lang: str) -> tuple[str, InlineKeyboardMarkup, float] | None:
    """(text, keyboard, cart total) or None when there's nothing worth sending."""
    from locales import get_display_unit, localize_product_text

    items = await database.get_cart(user_id)
    in_stock = [it for it in items if float(it.get("stock") or 0) > 0]
    if not in_stock:
        return None

    total = 0.0
    lines = []
    for it in items:
        discount = database.active_discount(it.get("discount_percent"), it.get("discount_until"))
        price = database.effective_price(it["price"], discount, it.get("discount_until"))
        total += price * float(it["cart_quantity"])
        qty = it["cart_quantity"]
        qty_s = str(int(qty)) if float(qty).is_integer() else f"{qty:.1f}"
        name = localize_product_text(it.get("name"), it.get("name_ru"), lang) or it.get("name") or ""
        sold_out = float(it.get("stock") or 0) <= 0
        mark = _t(" <i>(tugagan)</i>", " <i>(нет в наличии)</i>", lang) if sold_out else ""
        lines.append(f"• {html.escape(name)} × {qty_s} {get_display_unit(it['unit'], lang)}{mark}")

    shown = lines[:MAX_LINES]
    if len(lines) > MAX_LINES:
        shown.append(_t(f"… va yana {len(lines) - MAX_LINES} ta", f"… и ещё {len(lines) - MAX_LINES}", lang))

    if stage == 1:
        head = _t("🛒 <b>Savatingiz Sizni kutyapti!</b>",
                  "🛒 <b>Ваша корзина ждёт вас!</b>", lang)
        intro = _t("Tanlagan mahsulotlaringizni savatda saqlab qo'ydik:",
                   "Мы сохранили выбранные вами товары:", lang)
        push = _t("Buyurtmani 1 daqiqada rasmiylashtiring 👇",
                  "Оформите заказ за 1 минуту 👇", lang)
    else:
        head = _t("⏳ <b>Mahsulotlaringiz hali ham Siz uchun saqlanmoqda</b>",
                  "⏳ <b>Ваши товары всё ещё отложены для вас</b>", lang)
        intro = _t("Sog'lom tanlovingizni yarim yo'lda qoldirmang 🤍 Savatingizda:",
                   "Не оставляйте здоровый выбор на полпути 🤍 В корзине:", lang)
        push = _t("Mahsulotlar tugab qolmasidan buyurtma bering 👇",
                  "Оформите заказ, пока товары есть в наличии 👇", lang)

    parts = [head, "", intro, *shown, "",
             _t(f"💰 Jami: <b>{fmt_sum(total)} so'm</b>", f"💰 Итого: <b>{fmt_sum(total)} сум</b>", lang)]

    gift = await gift_campaign.cart_hint(user_id, total, lang)
    if gift:
        parts += ["", gift]
    parts += ["", push]

    rows = []
    # ⚡ one-tap checkout for repeat buyers — the same shortcut the cart shows.
    from handlers.cart import _quick_order_ready
    from locales import get_text
    if await _quick_order_ready(user_id):
        rows.append([InlineKeyboardButton(text=get_text("btn_quick_order", lang), callback_data="quick_order")])
    rows.append([InlineKeyboardButton(text=get_text("btn_checkout", lang), callback_data="checkout")])
    rows.append([InlineKeyboardButton(text=get_text("btn_view_cart", lang), callback_data="cart")])
    return "\n".join(parts), InlineKeyboardMarkup(inline_keyboard=rows), total


# ─────────────────────────────── sending ────────────────────────────────────

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
            logger.exception("Cart reminder to %s failed", user_id)
            return False
    return False


async def run_once(bot: Bot) -> dict:
    """One pass over both stages. Returns counters (for logs and tests)."""
    stats = {"sent": 0, "failed": 0, "skipped": 0}
    try:
        await database.attribute_cart_reminder_conversions()
    except Exception:
        logger.exception("Cart reminder conversion attribution failed")

    if _quiet_now():
        return stats

    banned = set(await _banned_ids())
    for stage, min_idle, max_idle in STAGES:
        carts = await database.get_idle_carts(min_idle, max_idle)
        if not carts:
            continue
        langs = await database.get_user_languages([c["user_id"] for c in carts])
        for c in carts:
            uid, touched = c["user_id"], c["last_touch"]
            if (not gift_campaign.is_eligible_user(uid) or uid in banned
                    or await database.cart_reminder_sent(uid, stage, touched)
                    or await database.ordered_since(uid, touched)):
                stats["skipped"] += 1
                continue
            # Stage 2 only ever follows a stage 1 about the SAME cart state —
            # it's the second of two touches, never a buyer's first message.
            if stage == 2 and not await database.cart_reminder_sent(uid, 1, touched):
                stats["skipped"] += 1
                continue

            lang = langs.get(uid, "uz")
            built = await build_reminder(uid, stage, lang)
            if not built:
                stats["skipped"] += 1
                continue
            text, markup, total = built

            if not await database.record_cart_reminder(uid, stage, touched, total):
                stats["skipped"] += 1            # another pass got here first
                continue
            if await _send(bot, uid, text, markup):
                stats["sent"] += 1
            else:
                stats["failed"] += 1
            await asyncio.sleep(SEND_DELAY)
    return stats


async def _banned_ids() -> list[int]:
    async with database.pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM banned_users")
        return [r["user_id"] for r in rows]


async def scheduler_loop(bot: Bot) -> None:
    logger.info("Abandoned-cart reminder scheduler started")
    while True:
        try:
            stats = await run_once(bot)
            if stats["sent"] or stats["failed"]:
                logger.info("Cart reminders: %s", stats)
        except Exception:
            logger.exception("Abandoned-cart tick failed")
        await asyncio.sleep(CHECK_EVERY)


# ─────────────────────────────── admin view ─────────────────────────────────

def _stats_block(title: str, s: dict) -> str:
    rate = (s["converted"] / s["sent"] * 100) if s["sent"] else 0
    return (
        f"<b>{title}</b>\n"
        f"📨 Yuborildi: {s['sent']} ta (3 soatlik: {s['stage1']}, 24 soatlik: {s['stage2']})\n"
        f"🛒 Eslatilgan savatlar: {fmt_sum(s['reminded_value'])} so'm\n"
        f"✅ Buyurtmaga aylandi: <b>{s['converted']} ta ({rate:.0f}%)</b>\n"
        f"💰 Qaytarilgan savdo: <b>{fmt_sum(s['converted_value'])} so'm</b>"
    )


@router.message(Command("savat_eslatma"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_cart_reminder_stats(message: Message):
    await database.attribute_cart_reminder_conversions()
    week = await database.get_cart_reminder_stats(7)
    month = await database.get_cart_reminder_stats(30)
    await message.answer(
        "🛒 <b>Tashlab ketilgan savat eslatmalari</b>\n"
        "3 soat va 24 soat tegilmagan savatlarga, 09:00–21:00 oralig'ida.\n\n"
        + _stats_block("Oxirgi 7 kun", week) + "\n\n"
        + _stats_block("Oxirgi 30 kun", month),
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("sovga"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_gift_stats(message: Message):
    await gift_campaign.book_delivered_gifts()
    await message.answer(await gift_campaign.stats_text(), parse_mode=ParseMode.HTML)
