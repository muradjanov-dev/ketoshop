"""
Blogerlar — influencer partner programme (2026-09-01).

An admin registers a blogger in the admin panel (name → a personal deep link
is built from that name) and hands them the link:

    https://t.me/ketoshopbot?start=aziza

Everyone who first opens the bot through that link is tied to that blogger
for good (blogger_referrals.user_id is UNIQUE — the first link a person opens
is the only one that ever counts, exactly like the old contest referrals).

PAYOUT. For each referred buyer's first `max_orders` DELIVERED orders
(default 10, per buyer, editable per blogger), the blogger earns `percent` of
that order's PROFIT — profit being the order's own line items minus the
cost_price of the goods in them (the same basis the Excel report and the
dashboard use). Delivery fees aren't part of it (they're not line items) and
free aksiya bonus lines count as a cost, because that's what they are.

WHERE THE MONEY GOES. Into the blogger's Keto balance, 1 Keto = 1 so'm — the
shop's existing cashback wallet — so they can spend it on our own products at
checkout with no separate wallet to build or reconcile. Keto-as-discount is
globally off for ordinary buyers (gamification.is_redemption_enabled), so
bloggers get an explicit per-user exception: see gamification.py.

A blogger can be registered BEFORE they have ever opened the bot, so their
Telegram id is optional. Earnings still accrue in blogger_earnings with
credited=FALSE, and settle into their balance the moment an admin fills the
id in (settle_pending, called from the admin panel).

Public API:
  slugify(name) / suggest_code(name)   -> deep-link code from a blogger's name
  link(code)                           -> the full t.me link they publish
  parse_payload(payload)               -> a /start payload -> code (or None)
  attach_new_user(code, user_id, bot)  -> tie a brand-new buyer to a blogger
  award_for_order(order, bot)          -> pay the blogger, call on 'delivered'
  settle_pending(blogger, bot)         -> credit earnings banked before the id
  notify_registered(blogger, bot)      -> "you're in, here's your link" DM
  router                               -> the blogger's own in-bot cabinet
  has_cabinet(user_id)                 -> is this user an active blogger?
"""
import json
import logging
import re
from datetime import datetime, timedelta

from aiogram import Bot, Router, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message

import database
from config import ADMIN_IDS, BOT_USERNAME

logger = logging.getLogger(__name__)
router = Router()

DEFAULT_PERCENT = 10.0     # % of profit
DEFAULT_MAX_ORDERS = 10    # per referred buyer
TZ_OFFSET = timedelta(hours=5)   # Asia/Tashkent, fixed UTC+5, no DST

# 'ref123456789' is the Keto musobaqasi referral payload (referral_contest.py)
# — a blogger code must never be able to shadow one.
_RESERVED_PREFIXES = ("ref",)
_CODE_RE = re.compile(r"^[a-z0-9_]{2,48}$")

# Uzbek Latin niceties before the generic strip: o'/g' are letters, not
# punctuation, and dropping the apostrophe keeps "Gulnoza" readable.
_LATIN_FIXES = (("o'", "o"), ("g'", "g"), ("oʻ", "o"), ("gʻ", "g"), ("’", ""), ("'", ""))


def _fmt(n) -> str:
    return f"{int(n or 0):,}".replace(",", " ")


def _dt(value) -> str:
    if not value:
        return "—"
    try:
        return (value + TZ_OFFSET).strftime("%d.%m.%Y")
    except Exception:
        return "—"


def L(lang: str, uz: str, ru: str) -> str:
    return ru if lang == "ru" else uz


def _som(lang: str) -> str:
    return "сум" if lang == "ru" else "so'm"


# ───────────────────────────── link & code ──────────────────────────────────

def slugify(name: str) -> str:
    """'Aziza Blog' -> 'aziza_blog'. Cyrillic names are transliterated first
    (Азиза -> aziza) so the link stays typeable on any keyboard."""
    text = (name or "").strip()
    if not text:
        return ""
    if re.search(r"[Ѐ-ӿ]", text):
        try:
            from translit import cyr_to_lat
            text = cyr_to_lat(text)
        except Exception:
            pass
    text = text.lower()
    for src, dst in _LATIN_FIXES:
        text = text.replace(src, dst)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    text = re.sub(r"_{2,}", "_", text)
    return text[:48]


def normalize_code(code: str) -> str:
    """What the admin typed -> a code we can actually put in a link, or ''."""
    slug = slugify(code)
    if not slug or not _CODE_RE.match(slug):
        return ""
    # A code that shadows the contest payload ('ref' + digits) is rewritten
    # rather than rejected, so the admin isn't left guessing why their name
    # "wasn't allowed".
    if any(slug.startswith(p) for p in _RESERVED_PREFIXES) and slug[3:].isdigit():
        slug = f"{slug}_b"
    return slug


async def suggest_code(name: str, exclude_id: int | None = None) -> str:
    """A free code derived from the blogger's own name — 'aziza', then
    'aziza2', 'aziza3'… if that name is already taken."""
    base = normalize_code(name) or "bloger"
    candidate, n = base, 1
    while True:
        existing = await database.get_blogger_by_code(candidate)
        if not existing or (exclude_id is not None and existing["id"] == exclude_id):
            return candidate
        n += 1
        candidate = f"{base}{n}"


def link(code: str) -> str:
    return f"https://t.me/{BOT_USERNAME}?start={code}"


def parse_payload(payload: str | None) -> str | None:
    """A /start deep-link payload -> a candidate blogger code. Returns None
    for anything that can't be one (including the contest's 'ref<id>'), so
    the caller can fall through to the other payload readers."""
    if not payload:
        return None
    candidate = payload.strip()
    if not re.match(r"^[A-Za-z0-9_-]{2,64}$", candidate):
        return None
    candidate = candidate.lower().replace("-", "_")
    if candidate.startswith("ref") and candidate[3:].isdigit():
        return None
    return candidate


# ─────────────────────────── joining & payout ───────────────────────────────

async def attach_new_user(code: str, user_id: int, bot: Bot | None = None) -> bool:
    """Tie a brand-new buyer to the blogger whose link they used. Call only
    for users who were just created (handlers/start.py::ensure_registered) —
    someone who was already a Ketoshop customer isn't a blogger's acquisition.
    Best-effort: never raises."""
    try:
        blogger = await database.get_blogger_by_code(code)
        if not blogger or not blogger["active"]:
            return False
        if blogger.get("user_id") == user_id:
            return False  # the blogger opened their own link
        if user_id in ADMIN_IDS or user_id in database.LEADERBOARD_EXCLUDED_USER_IDS:
            return False
        recorded = await database.record_blogger_referral(blogger["id"], user_id)
        if recorded:
            logger.info("Blogger %s (%s) referred user %s", blogger["id"], blogger["code"], user_id)
        return recorded
    except Exception:
        logger.exception("attach_new_user failed (code=%s, user=%s)", code, user_id)
        return False


def _is_eligible_order(order: dict) -> bool:
    """Mirrors gamification._is_eligible — internal/admin accounts and
    admin-keyed manual/B2B rows never pay a blogger."""
    user_id = order.get("user_id")
    if user_id in ADMIN_IDS or user_id in database.LEADERBOARD_EXCLUDED_USER_IDS:
        return False
    return (order.get("source") or "bot") not in ("manual", "b2b")


def _items(order: dict) -> list[dict]:
    raw = order.get("items")
    try:
        return json.loads(raw) if isinstance(raw, str) else (raw or [])
    except Exception:
        return []


async def order_profit(order: dict) -> float:
    """Revenue of this order's own line items minus the cost_price of the
    goods sold. Set lines are costed from the products they bundle; free
    aksiya bonus lines (price 0) count as pure cost, which is exactly what a
    giveaway is. Delivery fees are outside items and so outside profit."""
    items = _items(order)
    if not items:
        return 0.0
    cost_map = await database.get_all_cost_prices()
    set_costs = await database.get_set_costs() if any(it.get("is_set") for it in items) else {}

    profit = 0.0
    for item in items:
        qty = float(item.get("quantity") or 0)
        revenue = float(item.get("price") or 0) * qty
        if item.get("is_set"):
            set_id = item.get("set_id") or item.get("product_id") or item.get("id")
            unit_cost = float(set_costs.get(int(set_id), 0.0)) if set_id else 0.0
        else:
            pid = item.get("product_id") or item.get("id")
            # A bonus line's stock_quantity is what actually leaves the shelf
            # (e.g. 0.1 kg for a "100 gr" gift) — see promotions.to_stock_qty.
            if item.get("is_bonus"):
                qty = float(item.get("stock_quantity") or qty)
            unit_cost = float(cost_map.get(int(pid), 0.0)) if pid else 0.0
        profit += revenue - unit_cost * qty
    return profit


async def award_for_order(order: dict, bot: Bot) -> None:
    """Pay the blogger who brought this buyer in. Call right after an order
    transitions to status='delivered' (same hook point as the buyer's own
    Keto award). Best-effort and idempotent: safe to call again for an order
    that already paid out, and a failure here never blocks the delivery
    notification the buyer is waiting on."""
    try:
        if not _is_eligible_order(order):
            return
        buyer_id = order["user_id"]
        blogger = await database.get_blogger_for_buyer(buyer_id)
        if not blogger or not blogger["active"]:
            return

        max_orders = int(blogger["max_orders"] or 0)
        already = await database.count_blogger_earnings_for_buyer(blogger["id"], buyer_id)
        if max_orders and already >= max_orders:
            return  # this buyer has paid out their full run

        percent = float(blogger["percent"] or 0)
        profit = await order_profit(order)
        amount = int(round(profit * percent / 100))
        if amount <= 0:
            return  # a loss-making or zero-profit order pays nothing

        blogger_user_id = blogger.get("user_id")
        recorded = await database.add_blogger_earning(
            blogger_id=blogger["id"], order_id=order["id"], user_id=buyer_id,
            order_no=already + 1, order_total=float(order.get("total") or 0),
            profit=profit, percent=percent, amount=amount,
            credited=bool(blogger_user_id),
        )
        if not recorded:
            return  # this order already paid out

        if not blogger_user_id:
            # Registered without a Telegram id yet — banked, paid on settle.
            logger.info("Blogger %s earned %s (order %s) — pending, no Telegram id",
                        blogger["id"], amount, order["id"])
            return

        await database.credit_keto(
            blogger_user_id, order_id=None, amount=amount, kind="blogger",
            note=f"Bloger keshbek: buyurtma #{order['id']}",
        )
        await _notify_earning(bot, blogger, buyer_id, order, amount, already + 1, max_orders)
    except Exception:
        logger.exception("award_for_order failed for order %s", order.get("id"))


async def settle_pending(blogger: dict, bot: Bot | None = None) -> int:
    """Credit everything this blogger earned before their Telegram id was
    known. Returns the total so'm settled. Called when an admin fills the id
    in from the panel."""
    user_id = blogger.get("user_id")
    if not user_id:
        return 0
    total = 0
    for earning in await database.get_uncredited_blogger_earnings(blogger["id"]):
        ok = await database.credit_keto(
            user_id, order_id=None, amount=int(earning["amount"]), kind="blogger",
            note=f"Bloger keshbek: buyurtma #{earning['order_id']}",
        )
        if ok:
            await database.mark_blogger_earning_credited(earning["id"])
            total += int(earning["amount"])
    if total and bot:
        lang = await database.get_user_language(user_id)
        try:
            await bot.send_message(
                user_id,
                L(lang,
                  f"🎉 <b>Bloger keshbegingiz hisoblandi!</b>\n\n"
                  f"💰 Balansingizga <b>{_fmt(total)} so'm</b> tushdi — "
                  f"undan Ketoshopdan xarid qilishda foydalanishingiz mumkin.",
                  f"🎉 <b>Ваш блогер-кешбэк начислен!</b>\n\n"
                  f"💰 На ваш баланс зачислено <b>{_fmt(total)} сум</b> — "
                  f"их можно потратить на покупки в Ketoshop."),
                reply_markup=_cabinet_button(lang),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            logger.warning("Settle notice failed for blogger user %s", user_id, exc_info=True)
    return total


async def _notify_earning(bot: Bot, blogger: dict, buyer_id: int, order: dict,
                           amount: int, order_no: int, max_orders: int) -> None:
    user_id = blogger["user_id"]
    lang = await database.get_user_language(user_id)
    buyer = await database.get_user(buyer_id)
    who = (buyer or {}).get("full_name") or L(lang, "Mijoz", "Клиент")
    who = who.split()[0] if who else who
    balance = int((await database.get_user(user_id) or {}).get("keto_balance") or 0)
    left = max(0, max_orders - order_no) if max_orders else None

    lines = [
        L(lang, "🎉 <b>Sizning havolangiz orqali xarid qilindi!</b>",
                "🎉 <b>По вашей ссылке совершена покупка!</b>"),
        L(lang, f"👤 Mijoz: <b>{who}</b>\n🧾 Buyurtma #{order['id']} — {_fmt(order.get('total'))} so'm",
                f"👤 Клиент: <b>{who}</b>\n🧾 Заказ #{order['id']} — {_fmt(order.get('total'))} сум"),
        L(lang, f"💰 Sizga keshbek: <b>+{_fmt(amount)} so'm</b>\n💳 Balansingiz: <b>{_fmt(balance)} so'm</b>",
                f"💰 Ваш кешбэк: <b>+{_fmt(amount)} сум</b>\n💳 Ваш баланс: <b>{_fmt(balance)} сум</b>"),
    ]
    if left is not None:
        lines.append(L(lang,
            f"ℹ️ Shu mijozdan yana <b>{left} ta</b> buyurtmadan keshbek olasiz.",
            f"ℹ️ С этого клиента вы получите кешбэк ещё с <b>{left}</b> заказ(ов)."))
    try:
        await bot.send_message(user_id, "\n\n".join(lines),
                                reply_markup=_cabinet_button(lang), parse_mode=ParseMode.HTML)
    except Exception:
        logger.warning("Earning notice failed for blogger user %s", user_id, exc_info=True)


async def notify_registered(blogger: dict, bot: Bot) -> None:
    """"You're a Ketoshop partner — here's your link" DM, sent when an admin
    saves a blogger with a Telegram id (or fills one in later)."""
    user_id = blogger.get("user_id")
    if not user_id:
        return
    lang = await database.get_user_language(user_id)
    percent = _pct(blogger["percent"])
    text = "\n\n".join([
        L(lang, "🤝 <b>Ketoshop bloger dasturiga xush kelibsiz!</b>",
                "🤝 <b>Добро пожаловать в блогер-программу Ketoshop!</b>"),
        L(lang, f"🔗 Sizning shaxsiy havolangiz:\n<code>{link(blogger['code'])}</code>",
                f"🔗 Ваша персональная ссылка:\n<code>{link(blogger['code'])}</code>"),
        L(lang,
          f"💰 Shu havola orqali kelgan har bir mijozning dastlabki "
          f"<b>{blogger['max_orders']} ta</b> xarididan olingan foydaning "
          f"<b>{percent}%</b> keshbek sifatida balansingizga tushadi.",
          f"💰 С первых <b>{blogger['max_orders']}</b> покупок каждого пришедшего по этой "
          f"ссылке клиента вам начисляется <b>{percent}%</b> от прибыли в виде кешбэка."),
        L(lang, "🛒 Keshbekni Ketoshopdan mahsulot sotib olishda ishlatishingiz mumkin.",
                "🛒 Кешбэк можно потратить на покупки в Ketoshop."),
    ])
    try:
        await bot.send_message(user_id, text, reply_markup=_cabinet_button(lang),
                                parse_mode=ParseMode.HTML)
    except Exception:
        logger.warning("Registration notice failed for blogger user %s", user_id, exc_info=True)


def _pct(value) -> str:
    value = float(value or 0)
    return str(int(value)) if value == int(value) else f"{value:g}"


async def has_cabinet(user_id: int) -> bool:
    blogger = await database.get_blogger_by_user_id(user_id)
    return bool(blogger and blogger["active"])


# ───────────────────────── the blogger's own cabinet ────────────────────────

def _cabinet_button(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=L(lang, "📢 Bloger kabinetim", "📢 Мой кабинет блогера"),
        callback_data="bloger:menu",
    )]])


def cabinet_row(lang: str) -> list[InlineKeyboardButton]:
    """The Kabinetim entry point — added only for actual bloggers."""
    return [InlineKeyboardButton(
        text=L(lang, "📢 Bloger kabinetim", "📢 Мой кабинет блогера"),
        callback_data="bloger:menu",
    )]


def _menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=L(lang, "👥 Mening mijozlarim", "👥 Мои клиенты"),
                               callback_data="bloger:buyers")],
        [InlineKeyboardButton(text=L(lang, "🧾 Buyurtmalar tarixi", "🧾 История заказов"),
                               callback_data="bloger:orders")],
        [InlineKeyboardButton(text=L(lang, "🔙 Kabinetim", "🔙 Кабинет"), callback_data="kabinetim")],
    ])


def _back_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=L(lang, "🔙 Orqaga", "🔙 Назад"), callback_data="bloger:menu",
    )]])


async def build_cabinet_text(blogger: dict, lang: str) -> str:
    summary = await database.get_blogger_summary(blogger["id"])
    user = await database.get_user(blogger["user_id"]) if blogger.get("user_id") else None
    balance = int((user or {}).get("keto_balance") or 0)
    pending = int(summary.get("pending") or 0)

    lines = [
        L(lang, f"📢 <b>Bloger kabineti</b>\n👤 {blogger['name']}",
                f"📢 <b>Кабинет блогера</b>\n👤 {blogger['name']}"),
        L(lang, f"🔗 <b>Sizning havolangiz:</b>\n<code>{link(blogger['code'])}</code>",
                f"🔗 <b>Ваша ссылка:</b>\n<code>{link(blogger['code'])}</code>"),
        L(lang,
          f"👥 Taklif qilganlar: <b>{summary.get('referred_count', 0)} kishi</b>\n"
          f"🧾 Ularning buyurtmalari: <b>{summary.get('orders_count', 0)} ta</b> "
          f"(yetkazilgan: {summary.get('delivered_count', 0)})\n"
          f"💵 Xaridlar summasi: <b>{_fmt(summary.get('revenue'))} so'm</b>",
          f"👥 Приглашено: <b>{summary.get('referred_count', 0)} чел.</b>\n"
          f"🧾 Их заказы: <b>{summary.get('orders_count', 0)}</b> "
          f"(доставлено: {summary.get('delivered_count', 0)})\n"
          f"💵 Сумма покупок: <b>{_fmt(summary.get('revenue'))} сум</b>"),
        L(lang,
          f"💰 Jami ishlangan keshbek: <b>{_fmt(summary.get('earned'))} so'm</b>\n"
          f"💳 Ishlatish mumkin bo'lgan balans: <b>{_fmt(balance)} so'm</b>",
          f"💰 Всего заработано кешбэка: <b>{_fmt(summary.get('earned'))} сум</b>\n"
          f"💳 Доступный баланс: <b>{_fmt(balance)} сум</b>"),
    ]
    if pending:
        lines.append(L(lang,
            f"⏳ Hisoblanmoqda: {_fmt(pending)} so'm",
            f"⏳ В обработке: {_fmt(pending)} сум"))
    lines.append(L(lang,
        f"ℹ️ Har bir mijozning dastlabki <b>{blogger['max_orders']} ta</b> yetkazilgan "
        f"xarididan olingan foydaning <b>{_pct(blogger['percent'])}%</b> sizga keshbek "
        f"bo'lib tushadi. Uni Ketoshopdan xarid qilishda ishlatasiz.",
        f"ℹ️ С первых <b>{blogger['max_orders']}</b> доставленных покупок каждого клиента "
        f"вам начисляется <b>{_pct(blogger['percent'])}%</b> от прибыли. Кешбэк можно "
        f"потратить на покупки в Ketoshop."))
    return "\n\n".join(lines)


async def _open_cabinet(user_id: int, lang: str):
    """(text, keyboard) for the cabinet, or (None, None) if this user isn't
    an active blogger — a stale button from a deactivated partner."""
    blogger = await database.get_blogger_by_user_id(user_id)
    if not blogger or not blogger["active"]:
        return None, None
    return await build_cabinet_text(blogger, lang), _menu_keyboard(lang)


async def _render(callback: CallbackQuery, text: str, keyboard) -> None:
    if callback.message.photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
        return
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


def _not_a_blogger(lang: str) -> str:
    return L(lang,
             "Bu bo'lim faqat Ketoshop hamkor blogerlari uchun.",
             "Этот раздел доступен только партнёрам-блогерам Ketoshop.")


@router.message(Command("bloger"))
async def cmd_bloger(message: Message):
    lang = await database.get_user_language(message.from_user.id)
    text, keyboard = await _open_cabinet(message.from_user.id, lang)
    if text is None:
        await message.answer(_not_a_blogger(lang))
        return
    await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "bloger:menu")
async def cabinet_menu(callback: CallbackQuery):
    lang = await database.get_user_language(callback.from_user.id)
    text, keyboard = await _open_cabinet(callback.from_user.id, lang)
    if text is None:
        await callback.answer(_not_a_blogger(lang), show_alert=True)
        return
    await _render(callback, text, keyboard)
    await callback.answer()


def _short_name(full_name: str | None, user_id: int, lang: str) -> str:
    """Bloggers see who bought, not how to reach them — first name only, no
    username or phone (those stay in the admin panel)."""
    if not full_name:
        return L(lang, f"Mijoz #{user_id % 10000}", f"Клиент #{user_id % 10000}")
    parts = full_name.split()
    return parts[0] + (f" {parts[1][0]}." if len(parts) > 1 and parts[1] else "")


@router.callback_query(F.data == "bloger:buyers")
async def cabinet_buyers(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = await database.get_user_language(user_id)
    blogger = await database.get_blogger_by_user_id(user_id)
    if not blogger or not blogger["active"]:
        await callback.answer(_not_a_blogger(lang), show_alert=True)
        return

    buyers = await database.get_blogger_referred_buyers(blogger["id"])
    header = L(lang, f"👥 <b>Mening mijozlarim</b> — {len(buyers)} kishi",
                     f"👥 <b>Мои клиенты</b> — {len(buyers)} чел.")
    if not buyers:
        body = L(lang,
                 "Hozircha hech kim havolangiz orqali qo'shilmagan.\n"
                 "Havolani ulashing — har bir yangi mijoz shu yerda ko'rinadi.",
                 "Пока никто не присоединился по вашей ссылке.\n"
                 "Поделитесь ссылкой — каждый новый клиент появится здесь.")
        await _render(callback, f"{header}\n\n{body}", _back_keyboard(lang))
        await callback.answer()
        return

    lines = [header, ""]
    for i, b in enumerate(buyers[:40], 1):
        lines.append(
            f"{i}. <b>{_short_name(b.get('full_name'), b['user_id'], lang)}</b> · {_dt(b.get('joined_at'))}\n"
            + L(lang,
                f"   🧾 {b['orders_count']} ta buyurtma · 💵 {_fmt(b['spent'])} so'm · 💰 {_fmt(b['earned'])} so'm keshbek",
                f"   🧾 {b['orders_count']} заказ(ов) · 💵 {_fmt(b['spent'])} сум · 💰 {_fmt(b['earned'])} сум кешбэка")
        )
    if len(buyers) > 40:
        lines.append(L(lang, f"\n… va yana {len(buyers) - 40} kishi",
                             f"\n… и ещё {len(buyers) - 40} чел."))
    await _render(callback, "\n".join(lines), _back_keyboard(lang))
    await callback.answer()


_STATUS_LABEL = {
    "pending":   ("⏳ kutilmoqda", "⏳ ожидает"),
    "confirmed": ("✅ tasdiqlangan", "✅ подтверждён"),
    "shipped":   ("🚚 yo'lda", "🚚 в пути"),
    "delivered": ("📦 yetkazilgan", "📦 доставлен"),
    "cancelled": ("❌ bekor qilingan", "❌ отменён"),
}


@router.callback_query(F.data == "bloger:orders")
async def cabinet_orders(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = await database.get_user_language(user_id)
    blogger = await database.get_blogger_by_user_id(user_id)
    if not blogger or not blogger["active"]:
        await callback.answer(_not_a_blogger(lang), show_alert=True)
        return

    orders = await database.get_blogger_orders(blogger["id"], limit=30)
    header = L(lang, "🧾 <b>Mijozlarim buyurtmalari</b>", "🧾 <b>Заказы моих клиентов</b>")
    if not orders:
        body = L(lang, "Hozircha buyurtma yo'q.", "Пока заказов нет.")
        await _render(callback, f"{header}\n\n{body}", _back_keyboard(lang))
        await callback.answer()
        return

    lines = [header, ""]
    for o in orders:
        status = _STATUS_LABEL.get(o["status"], (o["status"], o["status"]))
        earned = int(o["earned"] or 0)
        earned_line = (
            L(lang, f" · 💰 +{_fmt(earned)} so'm", f" · 💰 +{_fmt(earned)} сум")
            if earned else ""
        )
        lines.append(
            f"#{o['id']} · {_dt(o.get('created_at'))} · "
            f"<b>{_short_name(o.get('full_name'), o['user_id'], lang)}</b>\n"
            f"   💵 {_fmt(o['total'])} {_som(lang)} · "
            f"{L(lang, status[0], status[1])}{earned_line}"
        )
    lines.append(L(lang,
        "\nℹ️ Keshbek faqat yetkazib berilgan buyurtmalardan hisoblanadi.",
        "\nℹ️ Кешбэк начисляется только с доставленных заказов."))
    await _render(callback, "\n".join(lines), _back_keyboard(lang))
    await callback.answer()
