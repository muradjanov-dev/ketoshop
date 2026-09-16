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
  router                               -> the blogger's own in-bot cabinet AND
                                          the admin's "Blogerlar" section
  has_cabinet(user_id)                 -> is this user an active blogger?

Admins manage the programme from either panel: the website (/admin ->
Blogerlar, see admin_web.py) or the bot itself (Admin panel -> Marketing ->
Blogerlar, or /blogerlar) — both drive the same tables.
"""
import json
import logging
import re
from datetime import datetime, timedelta

from aiogram import Bot, Router, F
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message

import database
from config import ADMIN_IDS, BOT_USERNAME, WEBAPP_URL

logger = logging.getLogger(__name__)
router = Router()

DEFAULT_PERCENT = 10.0     # % of profit
DEFAULT_MAX_ORDERS = 10    # per referred buyer
TZ_OFFSET = timedelta(hours=5)   # Asia/Tashkent, fixed UTC+5, no DST

# 'ref123456789' is the Keto musobaqasi referral payload (referral_contest.py)
# — a blogger code must never be able to shadow one. 'fb_'/'ig_'/'ad_' belong
# to the Facebook ad links (ad_sources.py) for the same reason.
_RESERVED_PREFIXES = ("ref",)
_AD_PREFIXES = ("fb_", "ig_", "ad_")
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
    if candidate.startswith(_AD_PREFIXES):
        return None
    return candidate


# ─────────────────────────── joining & payout ───────────────────────────────

async def attach_new_user(code: str, user_id: int, bot: Bot | None = None) -> dict | None:
    """Tie a brand-new buyer to the blogger whose link they used, and return
    that blogger (so the caller can name them in the admins' "yangi
    foydalanuvchi" notice). None when nobody was credited.

    Call only for users who were just created (handlers/start.py::
    ensure_registered) — someone who was already a Ketoshop customer isn't a
    blogger's acquisition. Best-effort: never raises."""
    try:
        blogger = await database.get_blogger_by_code(code)
        if not blogger or not blogger["active"]:
            return None
        if blogger.get("user_id") == user_id:
            return None  # the blogger opened their own link
        if user_id in ADMIN_IDS or user_id in database.LEADERBOARD_EXCLUDED_USER_IDS:
            return None
        if not await database.record_blogger_referral(blogger["id"], user_id):
            return None
        logger.info("Blogger %s (%s) referred user %s", blogger["id"], blogger["code"], user_id)
        return blogger
    except Exception:
        logger.exception("attach_new_user failed (code=%s, user=%s)", code, user_id)
        return None


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
            # Shared costing rule (database.item_cost_qty): bonus lines by
            # stock_quantity, and the 100 000 so'm gift not at all — it's booked
            # in Chiqimlar as Ketoshop's own expense, so it must not shrink the
            # blogger's cut.
            qty = database.item_cost_qty(item)
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
    await _publish_cabinet_command(bot, user_id)


async def _publish_cabinet_command(bot: Bot, user_id: int) -> None:
    """Put /bloger in this partner's own "/" menu right away, instead of only
    at the next restart (bot.py registers the same scope on boot). Best-effort:
    Telegram rejects the scope for a chat that doesn't exist yet, which is
    normal for a blogger who hasn't opened the bot."""
    try:
        from aiogram.types import BotCommandScopeChat
        from keyboards import BUYER_COMMANDS, BLOGGER_COMMAND
        await bot.set_my_commands(BUYER_COMMANDS + [BLOGGER_COMMAND],
                                   scope=BotCommandScopeChat(chat_id=user_id))
    except Exception:
        logger.info("Could not publish /bloger command for %s", user_id, exc_info=True)


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

# ═════════════════════ admin panel, inside the bot ══════════════════════════
# The website (/admin → Blogerlar) is the full-featured view; this is the same
# programme driven from a phone: list, add a blogger through a short chat
# wizard, edit the numbers, stop/delete, and read the same client and order
# lists. Callback namespace 'admin:bloger:*' — handlers/admin.py owns 'admin:'
# but registers no catch-all, so the two never collide.


class BloggerAdminStates(StatesGroup):
    new_name = State()
    new_tg = State()
    new_percent = State()
    new_orders = State()
    edit_value = State()      # data: {"field": …, "blogger_id": …}


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


_SKIP_HINT = "<i>O'tkazib yuborish uchun /skip bosing.</i>"


async def _render_admin_list() -> tuple[str, InlineKeyboardMarkup]:
    rows_data = await database.get_bloggers_with_stats()
    lines = ["📢 <b>Blogerlar</b>", ""]
    if not rows_data:
        lines.append("Hozircha bloger yo'q.")
        lines.append("")
        lines.append(
            "➕ tugmasini bosib qo'shing — ismini yozsangiz, havola avtomatik yasaladi "
            "(masalan <code>t.me/" + BOT_USERNAME + "?start=aziza</code>)."
        )
    else:
        total_buyers = sum(int(b["referred_count"] or 0) for b in rows_data)
        total_earned = sum(int(b["earned"] or 0) for b in rows_data)
        lines.append(
            f"Jami: <b>{len(rows_data)} ta</b> bloger · 👥 {total_buyers} mijoz · "
            f"💰 {_fmt(total_earned)} so'm keshbek"
        )
        lines.append("")
        for b in rows_data:
            mark = "🟢" if b["active"] else "⚪"
            lines.append(f"{mark} <b>{b['name']}</b>")
            lines.append(f"   🔗 <code>{link(b['code'])}</code>")
            lines.append(
                f"   👥 {b['referred_count']} · 🧾 {b['orders_count']} · "
                f"💰 {_fmt(b['earned'])} so'm"
                + ("" if b.get("user_id") else " · ⚠️ ID yo'q")
            )
        lines.append("")
        lines.append(
            "ℹ️ Keshbek har bir mijozning belgilangan birinchi N ta <b>yetkazilgan</b> "
            "buyurtmasi foydasidan hisoblanadi."
        )

    rows = [[InlineKeyboardButton(text=f"📊 {b['name']}", callback_data=f"admin:bloger:view:{b['id']}")]
            for b in rows_data[:20]]
    rows.append([InlineKeyboardButton(text="➕ Yangi bloger", callback_data="admin:bloger:new")])
    rows.append([InlineKeyboardButton(text="📊 Referal statistikasi", callback_data="admin:referrals")])
    rows.append([InlineKeyboardButton(text="🌐 Saytda ochish", url=f"{WEBAPP_URL}/admin")])
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_menu:marketing")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def _render_admin_view(blogger_id: int) -> tuple[str, InlineKeyboardMarkup] | tuple[None, None]:
    blogger = await database.get_blogger(blogger_id)
    if not blogger:
        return None, None
    summary = await database.get_blogger_summary(blogger_id)
    balance = 0
    if blogger.get("user_id"):
        user = await database.get_user(blogger["user_id"])
        balance = int((user or {}).get("keto_balance") or 0)

    lines = [
        f"📢 <b>{blogger['name']}</b> {'🟢 faol' if blogger['active'] else '⚪ to‘xtatilgan'}",
        "",
        f"🔗 <code>{link(blogger['code'])}</code>",
        (f"🆔 Telegram ID: <code>{blogger['user_id']}</code>" if blogger.get("user_id")
         else "🆔 Telegram ID: ⚠️ kiritilmagan — keshbek yig'ilib turadi"),
        f"💯 Foyda ulushi: <b>{_pct(blogger['percent'])}%</b> · "
        f"har bir mijozdan <b>{blogger['max_orders']} ta</b> buyurtma",
        "",
        f"👥 Taklif qilgan mijozlar: <b>{summary.get('referred_count', 0)} ta</b>",
        f"🧾 Buyurtmalari: <b>{summary.get('orders_count', 0)} ta</b> "
        f"(yetkazilgan: {summary.get('delivered_count', 0)})",
        f"💵 Savdo summasi: <b>{_fmt(summary.get('revenue'))} so'm</b>",
        f"💰 Jami keshbek: <b>{_fmt(summary.get('earned'))} so'm</b>",
        f"💳 Balansi: <b>{_fmt(balance)} so'm</b>",
    ]
    if summary.get("pending"):
        lines.append(f"⏳ To'lanmagan (ID kutilmoqda): <b>{_fmt(summary['pending'])} so'm</b>")
    if blogger.get("contact"):
        lines.append(f"📞 {blogger['contact']}")
    if blogger.get("note"):
        lines.append(f"📝 {blogger['note']}")

    bid = blogger_id
    rows = [
        [InlineKeyboardButton(text="🔗 Havolani yuborish",
                              callback_data=f"admin:bloger:send:{bid}")],
        [InlineKeyboardButton(text="👥 Mijozlari", callback_data=f"admin:bloger:buyers:{bid}"),
         InlineKeyboardButton(text="🧾 Buyurtmalari", callback_data=f"admin:bloger:orders:{bid}")],
        [InlineKeyboardButton(text="💯 Foizni o'zgartirish", callback_data=f"admin:bloger:edit:percent:{bid}"),
         InlineKeyboardButton(text="🔢 Buyurtma soni", callback_data=f"admin:bloger:edit:orders:{bid}")],
        [InlineKeyboardButton(text="🆔 Telegram ID", callback_data=f"admin:bloger:edit:tgid:{bid}"),
         InlineKeyboardButton(text="✏️ Ism", callback_data=f"admin:bloger:edit:name:{bid}")],
        [InlineKeyboardButton(
            text="⏹ To'xtatish" if blogger["active"] else "▶️ Yoqish",
            callback_data=f"admin:bloger:toggle:{bid}")],
        [InlineKeyboardButton(text="🗑 O'chirish", callback_data=f"admin:bloger:del:{bid}")],
        [InlineKeyboardButton(text="🔙 Blogerlar", callback_data="admin:bloger")],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "admin:bloger")
async def admin_bloger_list(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        return
    await state.clear()
    text, keyboard = await _render_admin_list()
    await _render(callback, text, keyboard)
    await callback.answer()


@router.message(Command("blogerlar"))
async def cmd_blogerlar(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    await state.clear()
    text, keyboard = await _render_admin_list()
    await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


@router.callback_query(F.data.startswith("admin:bloger:view:"))
async def admin_bloger_view(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        return
    await state.clear()
    text, keyboard = await _render_admin_view(int(callback.data.rsplit(":", 1)[1]))
    if text is None:
        await callback.answer("Bloger topilmadi", show_alert=True)
        return
    await _render(callback, text, keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("admin:bloger:buyers:"))
async def admin_bloger_buyers(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return
    bid = int(callback.data.rsplit(":", 1)[1])
    buyers = await database.get_blogger_referred_buyers(bid)
    lines = [f"👥 <b>Taklif qilingan mijozlar</b> — {len(buyers)} ta", ""]
    if not buyers:
        lines.append("Hozircha bu havola orqali hech kim qo'shilmagan.")
    for i, b in enumerate(buyers[:30], 1):
        who = b.get("full_name") or f"ID {b['user_id']}"
        contact = f" · @{b['username']}" if b.get("username") else ""
        phone = f" · {b['phone']}" if b.get("phone") else ""
        lines.append(f"{i}. <b>{who}</b>{contact}{phone}")
        lines.append(
            f"   🗓 {_dt(b.get('joined_at'))} · 🧾 {b['orders_count']} ta "
            f"(yetkazilgan {b['delivered_count']}) · 💵 {_fmt(b['spent'])} · 💰 {_fmt(b['earned'])} so'm"
        )
    if len(buyers) > 30:
        lines.append(f"\n… va yana {len(buyers) - 30} ta — to'liq ro'yxat saytda.")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"admin:bloger:view:{bid}")]])
    await _render(callback, "\n".join(lines), keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("admin:bloger:orders:"))
async def admin_bloger_orders(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return
    bid = int(callback.data.rsplit(":", 1)[1])
    orders = await database.get_blogger_orders(bid, limit=25)
    lines = ["🧾 <b>Mijozlarning buyurtmalari</b>", ""]
    if not orders:
        lines.append("Hozircha buyurtma yo'q.")
    for o in orders:
        status = _STATUS_LABEL.get(o["status"], (o["status"], o["status"]))[0]
        who = (o.get("full_name") or f"ID {o['user_id']}").split()[0]
        earned = int(o["earned"] or 0)
        tail = f" · 💰 +{_fmt(earned)} so'm" if earned else ""
        lines.append(
            f"#{o['id']} · {_dt(o.get('created_at'))} · <b>{who}</b>\n"
            f"   💵 {_fmt(o['total'])} so'm · {status}{tail}"
        )
    lines.append("\nℹ️ Keshbek faqat yetkazilgan buyurtmalardan beriladi.")
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 Orqaga", callback_data=f"admin:bloger:view:{bid}")]])
    await _render(callback, "\n".join(lines), keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("admin:bloger:toggle:"))
async def admin_bloger_toggle(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return
    bid = int(callback.data.rsplit(":", 1)[1])
    blogger = await database.get_blogger(bid)
    if not blogger:
        await callback.answer("Bloger topilmadi", show_alert=True)
        return
    await database.update_blogger(bid, active=not blogger["active"])
    text, keyboard = await _render_admin_view(bid)
    await _render(callback, text, keyboard)
    await callback.answer("⏹ To'xtatildi" if blogger["active"] else "▶️ Yoqildi")


@router.callback_query(F.data.startswith("admin:bloger:del:"))
async def admin_bloger_delete_ask(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return
    bid = int(callback.data.rsplit(":", 1)[1])
    blogger = await database.get_blogger(bid)
    if not blogger:
        await callback.answer("Bloger topilmadi", show_alert=True)
        return
    text = (
        f"🗑 <b>{blogger['name']}</b> o'chirilsinmi?\n\n"
        "Uning taklif qilgan mijozlari ro'yxati va keshbek tarixi ham o'chadi.\n"
        "Allaqachon to'langan keshbek balansida qoladi.\n\n"
        "<i>Vaqtincha to'xtatish uchun o'chirish emas, \"⏹ To'xtatish\" ni tanlang.</i>"
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🗑 Ha, o'chirilsin", callback_data=f"admin:bloger:delyes:{bid}")],
        [InlineKeyboardButton(text="🔙 Bekor qilish", callback_data=f"admin:bloger:view:{bid}")],
    ])
    await _render(callback, text, keyboard)
    await callback.answer()


@router.callback_query(F.data.startswith("admin:bloger:delyes:"))
async def admin_bloger_delete(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        return
    await database.delete_blogger(int(callback.data.rsplit(":", 1)[1]))
    await state.clear()
    text, keyboard = await _render_admin_list()
    await _render(callback, text, keyboard)
    await callback.answer("🗑 O'chirildi")


# ─────────────────────────── the "new blogger" wizard ───────────────────────

@router.callback_query(F.data == "admin:bloger:new")
async def admin_bloger_new(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        return
    await state.set_state(BloggerAdminStates.new_name)
    await _render(callback,
        "📢 <b>Yangi bloger</b>\n\n1/4 — Blogerning ismini yozing.\n"
        "<i>Havola shu ismdan yasaladi, masalan: Aziza Keto → "
        f"t.me/{BOT_USERNAME}?start=aziza_keto</i>",
        None)
    await callback.answer()


@router.message(BloggerAdminStates.new_name, F.text)
async def admin_bloger_new_name(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    name = message.text.strip()[:120]
    if not name:
        await message.answer("Ism bo'sh bo'lmasin. Qaytadan yozing.")
        return
    code = await suggest_code(name)
    await state.update_data(name=name, code=code)
    await state.set_state(BloggerAdminStates.new_tg)
    await message.answer(
        f"✅ Ism: <b>{name}</b>\n🔗 Havolasi: <code>{link(code)}</code>\n\n"
        f"2/4 — Blogerning <b>Telegram ID</b> raqamini yozing "
        f"(u o'z kabinetini botda ko'rishi uchun).\n"
        f"{_SKIP_HINT} Keyinroq ham kiritish mumkin — keshbek yig'ilib turadi.",
        parse_mode=ParseMode.HTML,
    )


@router.message(BloggerAdminStates.new_tg, F.text)
async def admin_bloger_new_tg(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    raw = message.text.strip()
    user_id = None
    if raw != "/skip":
        if not raw.lstrip("-").isdigit():
            await message.answer(
                "🆔 Telegram ID faqat raqamlardan iborat (masalan <code>123456789</code>).\n"
                "Blogerdan @userinfobot ga /start yozib, ID sini so'rashingiz mumkin.\n"
                f"{_SKIP_HINT}",
                parse_mode=ParseMode.HTML,
            )
            return
        user_id = int(raw)
        existing = await database.get_blogger_by_user_id(user_id)
        if existing:
            await message.answer(
                f"⚠️ Bu ID allaqachon <b>{existing['name']}</b> ga biriktirilgan. "
                f"Boshqa ID yozing yoki /skip bosing.",
                parse_mode=ParseMode.HTML,
            )
            return
    await state.update_data(user_id=user_id)
    await state.set_state(BloggerAdminStates.new_percent)
    await message.answer(
        f"3/4 — Foydaning necha <b>foizi</b> blogerga keshbek bo'lsin?\n"
        f"<i>Faqat raqam yozing, masalan: 10</i>\n{_SKIP_HINT} "
        f"(standart {_pct(DEFAULT_PERCENT)}%)",
        parse_mode=ParseMode.HTML,
    )


@router.message(BloggerAdminStates.new_percent, F.text)
async def admin_bloger_new_percent(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    raw = message.text.strip()
    percent = DEFAULT_PERCENT
    if raw != "/skip":
        try:
            percent = float(raw.replace(",", ".").rstrip("%"))
            if not 0 < percent <= 100:
                raise ValueError
        except ValueError:
            await message.answer(f"Foiz 0 dan katta, 100 dan kichik son bo'lsin. Qaytadan yozing.\n{_SKIP_HINT}",
                                  parse_mode=ParseMode.HTML)
            return
    await state.update_data(percent=percent)
    await state.set_state(BloggerAdminStates.new_orders)
    await message.answer(
        f"4/4 — Har bir mijozning nechta buyurtmasidan keshbek berilsin?\n"
        f"<i>Masalan: 10 — ya'ni o'sha mijozning birinchi 10 ta yetkazilgan xaridi.</i>\n"
        f"{_SKIP_HINT} (standart {DEFAULT_MAX_ORDERS} ta)",
        parse_mode=ParseMode.HTML,
    )


@router.message(BloggerAdminStates.new_orders, F.text)
async def admin_bloger_new_orders(message: Message, state: FSMContext, bot: Bot):
    if not _is_admin(message.from_user.id):
        return
    raw = message.text.strip()
    max_orders = DEFAULT_MAX_ORDERS
    if raw != "/skip":
        if not raw.isdigit() or int(raw) <= 0:
            await message.answer(f"Musbat butun son yozing (masalan 10).\n{_SKIP_HINT}",
                                  parse_mode=ParseMode.HTML)
            return
        max_orders = int(raw)

    data = await state.get_data()
    await state.clear()
    # The code was reserved several messages ago — re-derive it in case another
    # admin created a blogger with the same name in the meantime.
    code = await suggest_code(data["name"])
    blogger_id = await database.create_blogger(
        name=data["name"], code=code, user_id=data.get("user_id"),
        percent=data.get("percent", DEFAULT_PERCENT), max_orders=max_orders,
    )
    blogger = await database.get_blogger(blogger_id)
    if blogger.get("user_id"):
        try:
            await notify_registered(blogger, bot)
            await settle_pending(blogger, bot)
        except Exception:
            logger.exception("Blogger welcome failed for %s", blogger_id)

    text, keyboard = await _render_admin_view(blogger_id)
    await message.answer(
        f"✅ <b>Bloger qo'shildi!</b>\n\n"
        f"🔗 Havolasini blogerga yuboring (bosib nusxalasa bo'ladi):\n"
        f"<code>{link(code)}</code>\n\n"
        + ("📨 Blogerga tanishtiruv xabari yuborildi."
           if blogger.get("user_id")
           else "⚠️ Telegram ID kiritilmagan — bloger o'z kabinetini hozircha ko'ra olmaydi. "
                "Keyinroq kiritsangiz, yig'ilgan keshbek balansiga tushadi."),
        parse_mode=ParseMode.HTML,
    )
    await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


# ──────────────────────────── single-field edits ────────────────────────────

_EDIT_PROMPT = {
    "percent": "💯 Yangi foizni yozing (masalan 10):",
    "orders":  "🔢 Har bir mijozdan nechta buyurtmadan keshbek berilsin? (masalan 10):",
    "tgid":    ("🆔 Blogerning Telegram ID raqamini yozing.\n"
                "<i>O'chirish uchun 0 yozing.</i>"),
    "name":    "✏️ Blogerning yangi ismini yozing:\n<i>Havolasi o'zgarmaydi.</i>",
}


@router.callback_query(F.data.startswith("admin:bloger:edit:"))
async def admin_bloger_edit_ask(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        return
    _, _, _, field, raw_id = callback.data.split(":")
    if field not in _EDIT_PROMPT:
        await callback.answer()
        return
    blogger_id = int(raw_id)
    await state.set_state(BloggerAdminStates.edit_value)
    await state.update_data(field=field, blogger_id=blogger_id)
    await _render(callback, _EDIT_PROMPT[field], None)
    await callback.answer()


@router.message(BloggerAdminStates.edit_value, F.text)
async def admin_bloger_edit_save(message: Message, state: FSMContext, bot: Bot):
    if not _is_admin(message.from_user.id):
        return
    data = await state.get_data()
    field, blogger_id = data.get("field"), data.get("blogger_id")
    raw = message.text.strip()
    blogger = await database.get_blogger(blogger_id)
    if not blogger:
        await state.clear()
        await message.answer("Bloger topilmadi.")
        return

    notify = False
    if field == "percent":
        try:
            value = float(raw.replace(",", ".").rstrip("%"))
            if not 0 < value <= 100:
                raise ValueError
        except ValueError:
            await message.answer("Foiz 0 dan katta, 100 dan kichik son bo'lsin. Qaytadan yozing.")
            return
        await database.update_blogger(blogger_id, percent=value)
    elif field == "orders":
        if not raw.isdigit() or int(raw) <= 0:
            await message.answer("Musbat butun son yozing (masalan 10).")
            return
        await database.update_blogger(blogger_id, max_orders=int(raw))
    elif field == "name":
        if not raw:
            await message.answer("Ism bo'sh bo'lmasin.")
            return
        await database.update_blogger(blogger_id, name=raw[:120])
    elif field == "tgid":
        if raw == "0":
            await database.update_blogger(blogger_id, user_id=None)
        elif raw.lstrip("-").isdigit():
            user_id = int(raw)
            existing = await database.get_blogger_by_user_id(user_id)
            if existing and existing["id"] != blogger_id:
                await message.answer(f"⚠️ Bu ID <b>{existing['name']}</b> ga biriktirilgan. "
                                      f"Boshqa ID yozing.", parse_mode=ParseMode.HTML)
                return
            await database.update_blogger(blogger_id, user_id=user_id)
            notify = user_id != blogger.get("user_id")
        else:
            await message.answer(
                "🆔 Telegram ID faqat raqamlardan iborat (masalan <code>123456789</code>). "
                "O'chirish uchun 0 yozing.", parse_mode=ParseMode.HTML)
            return

    await state.clear()
    updated = await database.get_blogger(blogger_id)
    if notify:
        try:
            await notify_registered(updated, bot)
            settled = await settle_pending(updated, bot)
            if settled:
                await message.answer(
                    f"💰 Yig'ilib turgan <b>{_fmt(settled)} so'm</b> keshbek blogerning "
                    f"balansiga o'tkazildi.", parse_mode=ParseMode.HTML)
        except Exception:
            logger.exception("Blogger welcome failed for %s", blogger_id)

    text, keyboard = await _render_admin_view(blogger_id)
    await message.answer("✅ Saqlandi.")
    await message.answer(text, reply_markup=keyboard, parse_mode=ParseMode.HTML)


# ─────────────────────── havolani blogerga yetkazish ────────────────────────

def share_text(blogger: dict) -> str:
    """Blogerga o'zi uchun tayyor xabar — admin nusxalab yoki forward qilib
    yuborishi uchun. notify_registered bilan bir xil gap, lekin DM emas,
    admin qo'liga beriladi (Telegram id hali ma'lum bo'lmaganda yagona yo'l)."""
    percent = _pct(blogger["percent"])
    return "\n\n".join([
        "🤝 <b>Ketoshop bloger dasturi</b>",
        f"🔗 Sizning shaxsiy havolangiz:\n<code>{link(blogger['code'])}</code>",
        f"💰 Shu havola orqali kelgan har bir mijozning dastlabki "
        f"<b>{blogger['max_orders']} ta</b> xarididan olingan foydaning "
        f"<b>{percent}%</b> keshbek sifatida balansingizga tushadi.",
        "🛒 Keshbekni Ketoshopdan mahsulot sotib olishda ishlatishingiz mumkin.",
    ])


@router.callback_query(F.data.startswith("admin:bloger:send:"))
async def admin_bloger_send_link(callback: CallbackQuery, bot: Bot):
    """Havolani blogerning o'ziga yuboradi. Telegram id bo'lmasa — adminga
    tayyor xabar beradi, u forward qiladi: bloger hali botga kirmagan bo'lishi
    mumkin va bu normal holat (bloggers.user_id ixtiyoriy)."""
    if not _is_admin(callback.from_user.id):
        return
    blogger_id = int(callback.data.rsplit(":", 1)[1])
    blogger = await database.get_blogger(blogger_id)
    if not blogger:
        await callback.answer("Bloger topilmadi", show_alert=True)
        return

    user_id = blogger.get("user_id")
    if not user_id:
        await callback.answer()
        await callback.message.answer(
            "🆔 Bu blogerning Telegram ID si kiritilmagan — pastdagi xabarni "
            "nusxalab yoki forward qilib o'zingiz yuboring:",
            parse_mode=ParseMode.HTML,
        )
        await callback.message.answer(share_text(blogger), parse_mode=ParseMode.HTML)
        return

    try:
        await notify_registered(blogger, bot)
    except Exception:
        logger.warning("Link DM to blogger %s failed", blogger_id, exc_info=True)
        await callback.answer("Yuborilmadi — bloger botni bloklagan bo'lishi mumkin",
                              show_alert=True)
        await callback.message.answer(share_text(blogger), parse_mode=ParseMode.HTML)
        return
    await callback.answer("✅ Havola blogerga yuborildi")
