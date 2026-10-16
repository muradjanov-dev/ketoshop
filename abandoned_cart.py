"""
Tashlab ketilgan savat eslatmasi — abandoned-cart reminders (2026-09-17).

A buyer puts products in the cart and leaves without ordering. A touch
brings them back — and warns before the cart hold ends (Savat broni,
cart_reservations.py; database.RESERVE_HOURS):

    6 h hold (owner, 2026-10-16) — ONE message, cart idle 3 h:
        "⏳ Savatingiz bugun 18:40 gacha siz uchun band" + one-tap checkout;
        after 6 h the products go back on sale with a release notice.
    12 h+ hold — stage 1 at 3 h "Savatingiz sizni kutyapti", stage 2 (the
        warning) 4 h before the hold ends.
    If the warning falls at night, it goes at 20:30 to everyone whose hold
    ends before the morning (idle at least an hour).

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
# Both end with the hold itself (database.RESERVE_HOURS): at its end the cart
# is released, not reminded.
#   * 6 h hold (owner, 2026-10-16): ONE message at 3 h — "⏳ savatingiz HH:MM
#     gacha band, keyin sotuvga qaytadi" — then the release notice. A gentle
#     touch and a warning 2 h apart would be two messages in one afternoon;
#   * a long hold (12 h+): the gentle touch at 3 h, the warning 4 h before
#     the end.
HOLD_MINUTES = database.RESERVE_HOURS * 60
if HOLD_MINUTES >= 12 * 60:
    STAGES = ((1, 3 * 60, HOLD_MINUTES - 4 * 60), (2, HOLD_MINUTES - 4 * 60, HOLD_MINUTES))
    WARN_STAGE = 2
else:
    STAGES = ((1, min(3 * 60, HOLD_MINUTES // 2), HOLD_MINUTES),)
    WARN_STAGE = 1
LAST_CALL = (20, 30)               # the last daytime half hour
LAST_CALL_MIN_IDLE = 60            # a cart touched minutes ago isn't warned yet


def warn_min_idle(default: int, now_tk: datetime | None = None) -> int:
    """The warning stage goes at `default` idle minutes. When that moment
    would fall in tonight's quiet hours, the last half hour of the day warns
    everyone whose hold ends before the morning (idle at least an hour) — a
    release at night is never the first the buyer hears of it."""
    now = now_tk or _now_tk()
    if (now.hour, now.minute) < LAST_CALL or now.hour >= QUIET_START:
        return default
    morning = (now + timedelta(days=1)).replace(hour=QUIET_END, minute=0, second=0, microsecond=0)
    until_morning = int((morning - now).total_seconds() // 60)
    return max(LAST_CALL_MIN_IDLE, min(default, HOLD_MINUTES - until_morning))


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

    if stage != WARN_STAGE:
        head = _t("🛒 <b>Savatingiz Sizni kutyapti!</b>",
                  "🛒 <b>Ваша корзина ждёт вас!</b>", lang)
        intro = _t("Tanlagan mahsulotlaringizni savatda saqlab qo'ydik:",
                   "Мы сохранили выбранные вами товары:", lang)
        push = _t("Buyurtma 1 daqiqada rasmiylashtiriladi 👇",
                  "Заказ оформляется за 1 минуту 👇", lang)
    else:
        until = await database.cart_hold_until(user_id)
        if until:
            # The warning before the hold ends (Savat broni).
            import cart_reservations
            when = cart_reservations.hold_end_text(until, "ru" if lang == "ru" else "uz")
            head = _t(f"⏳ <b>Savatingiz {when} gacha siz uchun band</b>",
                      f"⏳ <b>Ваша корзина закреплена за вами до {when}</b>", lang)
            intro = _t("Savatingizda:", "В корзине:", lang)
            push = _t("Shu vaqtgacha rasmiylashtirmasangiz, bu mahsulotlar boshqa xaridorlar uchun "
                      "sotuvga qaytadi. Buyurtma bir necha bosishda 👇",
                      "Если не оформить заказ до этого времени, товары вернутся в продажу для других "
                      "покупателей. Оформление — в пару нажатий 👇", lang)
        else:
            head = _t("🛒 <b>Savatingizdagi mahsulotlar shu yerda turibdi</b>",
                      "🛒 <b>Товары по-прежнему в вашей корзине</b>", lang)
            intro = _t("Savatingizda:", "В корзине:", lang)
            push = _t("Kerak bo'lsa, buyurtmani bir necha bosishda rasmiylashtirish mumkin 👇",
                      "Если нужно — заказ оформляется в пару нажатий 👇", lang)

    parts = [head, "", intro, *shown, "",
             _t(f"💰 Jami: <b>{fmt_sum(total)} so'm</b>", f"💰 Итого: <b>{fmt_sum(total)} сум</b>", lang)]

    # 10% for ordering through the bot (bot_discount.py) — what they'd pay.
    import bot_discount
    bot_pct = await bot_discount.percent_for(user_id)
    bot_saved = await bot_discount.cart_saving(items, bot_pct)
    if bot_saved > 0:
        parts += [bot_discount.saving_line(lang, bot_pct, bot_saved),
                  bot_discount.cart_pay_line(lang, total - bot_saved)]

    gift = await gift_campaign.cart_hint(user_id, total - bot_saved, lang)
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
        if stage == WARN_STAGE:
            min_idle = warn_min_idle(min_idle)
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

def _hours(minutes: int) -> str:
    return f"{minutes / 60:g}"


def _schedule_line() -> str:
    hold = _hours(HOLD_MINUTES)
    if WARN_STAGE == 1:
        return (f"{_hours(STAGES[0][1])} soat tegilmagan savatlarga — bron ({hold} soat) "
                "tugashidan oldin ogohlantirish")
    return (f"{_hours(STAGES[0][1])} soat va {_hours(STAGES[1][1])} soat tegilmagan savatlarga "
            f"(bron {hold} soat)")


def _stage_counts(s: dict) -> str:
    if WARN_STAGE == 1:
        return f"ogohlantirish: {s['stage1']}" + (f", eski 2-bosqich: {s['stage2']}" if s.get("stage2") else "")
    return (f"{_hours(STAGES[0][1])} soatlik: {s['stage1']}, "
            f"{_hours(STAGES[1][1])} soatlik: {s['stage2']}")


def _stats_block(title: str, s: dict) -> str:
    rate = (s["converted"] / s["sent"] * 100) if s["sent"] else 0
    return (
        f"<b>{title}</b>\n"
        f"📨 Yuborildi: {s['sent']} ta ({_stage_counts(s)})\n"
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
        f"{_schedule_line()}, 09:00–21:00 oralig'ida.\n\n"
        + _stats_block("Oxirgi 7 kun", week) + "\n\n"
        + _stats_block("Oxirgi 30 kun", month),
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("sovga"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_gift_stats(message: Message):
    await gift_campaign.book_delivered_gifts()
    await message.answer(await gift_campaign.stats_text(), parse_mode=ParseMode.HTML)


@router.message(Command("sovga_elon"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_gift_upgrade_preview(message: Message):
    """Preview of the "sovg'a endi har bir buyurtmaga" announcement in all
    three languages, exactly as buyers get it (photo + caption)."""
    from datetime import timedelta as _td
    row = await gift_campaign._state(force=True)
    until = (row["ends_at"] + gift_campaign.TZ_OFFSET) if row and row.get("ends_at") \
        else gift_campaign._now_tk() + _td(days=gift_campaign.DURATION_DAYS)
    photo = await gift_campaign._product_photo(await gift_campaign.gift_product(force=True))
    for lang in ("uz", "uz_cyr", "ru"):
        await gift_campaign._send_photo(message.bot, message.from_user.id, photo,
                                        gift_campaign.upgrade_text(lang, until),
                                        gift_campaign.announcement_keyboard(lang))
