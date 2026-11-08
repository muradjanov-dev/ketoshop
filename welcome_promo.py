"""
YANGI5 — every new bot member gets 5% off their first order for 8 hours
(owner, 2026-11-06: "Xar bir yangi qo'shilgan bot a'zolariga 5% lik
promokod chegirmasini beramiz, va buni vaqt tugaguncha botda va saytda urgent
qilib oddiy vaqt timer ko'rinishida ko'rsatib tursin, va bu 8 soat amal
qiladi, har 2 soatda ogohlantirib eslatsin, qancha tejab qolishi mumkin
ekanini").

The owner's choices, same day ("ha"):
  • automatic — nothing to type; it is shown under the name YANGI5;
  • only people who join after this release, 8 hours from the moment they
    pick a language;
  • the FIRST order only — any non-cancelled order of their own ends it;
  • only orders they place themselves (bot, site, AI seller): it rides on
    bot_discount.percent_for, which every self-service checkout already
    reads; manual and B2B orders never call it, admins never get it;
  • never on top of a product's own 🔥 price — the cheaper one wins
    (bot_discount.line_price); paying with Keto works as before;
  • a timer: a bot message edited every minute, a line in the bot cart,
    checkout and product card, a live countdown on the site;
  • reminders 2, 4 and 6 hours in, with what the cart would save — never
    22:00–08:00 Tashkent (a reminder due then is skipped, not delayed).
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

import database
from config import ADMIN_IDS, WEBAPP_URL

logger = logging.getLogger(__name__)

PERCENT = 5
CODE = "YANGI5"
HOURS = 8
REMIND_AFTER_HOURS = (2, 4, 6)
REMIND_LATE_MINUTES = 60      # a reminder more than this late (bot was down) is skipped
QUIET_FROM, QUIET_TO = 22, 8  # Tashkent hours: no reminders
TICK = 60                     # seconds between scheduler passes (and timer edits)
CACHE_TTL = 20
TZ = timedelta(hours=5)       # Asia/Tashkent, no DST
# Telegram's 🎉 message effect (confetti over the chat) on the timer message —
# "tabriklab tantana bilan e'lon qil" (owner, 2026-11-08). Private chats only;
# if Telegram ever refuses it, the message goes out without it.
PARTY_EFFECT = "5046509860389126442"
EXAMPLE_ORDER = 300_000       # "masalan" sum when the cart is empty

_table_ready = False
_cache: dict[int, tuple[float, datetime | None]] = {}
_shown: dict[int, str] = {}   # user_id → timer text last put on screen


def _now() -> datetime:
    return datetime.utcnow()


# ───────────────────────────── texts ─────────────────────────────

_T = {
    "timer": {
        "uz": ("🎉 <b>Tabriklaymiz!</b> Siz endi Ketoshop oilasidasiz.\n\n"
               "🎁 <b>Sizga sovg'a — {code}</b>\n\n"
               "<b>Birinchi buyurtmangizga {p}% chegirma</b>. Promokod kiritish "
               "shart emas — chegirma savatda o'zi hisoblanadi.\n\n"
               "⏳ <b>Qoldi: {left}</b>\n"
               "🕐 {until}"),
        "ru": ("🎉 <b>Поздравляем!</b> Теперь вы в семье Ketoshop.\n\n"
               "🎁 <b>Вам подарок — {code}</b>\n\n"
               "<b>Скидка {p}% на первый заказ</b>. Промокод вводить не нужно — "
               "скидка считается в корзине сама.\n\n"
               "⏳ <b>Осталось: {left}</b>\n"
               "🕐 {until}"),
    },
    "until_today": {"uz": "Bugun {clock} gacha", "ru": "До {clock} сегодня"},
    "until_tomorrow": {"uz": "Ertaga {clock} gacha", "ru": "До {clock} завтра"},
    "used": {
        "uz": "✅ <b>{code} ishlatildi</b>\n\n#{order} buyurtmangizda <b>{saved} so'm</b> tejadingiz. Rahmat!",
        "ru": "✅ <b>{code} использован</b>\n\nВ заказе #{order} вы сэкономили <b>{saved} сум</b>. Спасибо!",
    },
    "used_plain": {
        "uz": "✅ <b>{code}</b> — birinchi buyurtmangiz #{order} qabul qilindi. Rahmat!",
        "ru": "✅ <b>{code}</b> — ваш первый заказ #{order} принят. Спасибо!",
    },
    "expired": {
        "uz": ("⌛ <b>{code} muddati tugadi.</b>\n\n"
               "Sizni kutib qolamiz — yangi aksiyalar haqida bot va kanalda xabar beramiz."),
        "ru": ("⌛ <b>Срок {code} истёк.</b>\n\n"
               "Ждём вас — о новых акциях расскажем в боте и канале."),
    },
    "reminder": {
        "uz": ("⏳ <b>{code}: {p}% chegirmangiz tugashiga {left} qoldi</b>\n\n{body}\n\n"
               "Buyurtma bering — chegirma savatda o'zi hisoblanadi."),
        "ru": ("⏳ <b>{code}: до конца скидки {p}% осталось {left}</b>\n\n{body}\n\n"
               "Оформите заказ — скидка посчитается в корзине сама."),
    },
    "reminder_cart": {
        "uz": ("🛒 Savatingizda {total} so'mlik mahsulot bor — {p}% bilan <b>{saved} so'm tejaysiz</b>, "
               "to'lovga {pay} so'm."),
        "ru": ("🛒 В корзине товаров на {total} сум — со скидкой {p}% <b>вы сэкономите {saved} сум</b>, "
               "к оплате {pay} сум."),
    },
    "reminder_empty": {
        "uz": "Masalan, {example} so'mlik buyurtmada <b>{saved} so'm</b> tejaysiz.",
        "ru": "Например, на заказе в {example} сум <b>вы сэкономите {saved} сум</b>.",
    },
    "timer_line": {"uz": "⏳ {code} tugashiga: <b>{left}</b>", "ru": "⏳ До конца {code}: <b>{left}</b>"},
    "card_line": {
        "uz": "🎁 <b>{code}:</b> siz uchun <b>{price} so'm</b> (−{p}%) · ⏳ {left} qoldi",
        "ru": "🎁 <b>{code}:</b> для вас <b>{price} сум</b> (−{p}%) · ⏳ осталось {left}",
    },
    "label": {"uz": "🎁 {code} — yangi a'zo chegirmasi (−{p}%)",
              "ru": "🎁 {code} — скидка новому участнику (−{p}%)"},
    "site_label": {"uz": "🎁 {code} −{p}%", "ru": "🎁 {code} −{p}%"},
    "btn_shop": {"uz": "🛍 Do'konni ochish", "ru": "🛍 Открыть магазин"},
    "btn_cart": {"uz": "🛒 Savat", "ru": "🛒 Корзина"},
}


def _pick(key: str, lang: str, **kw) -> str:
    entry = _T[key]
    text = entry.get("ru" if lang == "ru" else "uz")
    text = text.format(code=CODE, p=PERCENT, **kw)
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        # The name stays YANGI5 in every language, like a brand.
        text = lat_to_cyr(text).replace(lat_to_cyr(CODE), CODE)
    return text


def _som(amount) -> str:
    return f"{int(round(float(amount))):,}".replace(",", " ")


def left_text(seconds: float, lang: str) -> str:
    seconds = max(0, int(seconds))
    h, m = seconds // 3600, (seconds % 3600) // 60
    if lang == "ru":
        return (f"{h} ч {m} мин" if m else f"{h} ч") if h else f"{m} мин"
    text = (f"{h} soat {m} daqiqa" if m else f"{h} soat") if h else f"{m} daqiqa"
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        text = lat_to_cyr(text)
    return text


def until_text(end_utc: datetime, lang: str, now_utc: datetime | None = None) -> str:
    end_tk = end_utc + TZ
    today_tk = ((now_utc or _now()) + TZ).date()
    key = "until_today" if end_tk.date() == today_tk else "until_tomorrow"
    return _pick(key, lang, clock=end_tk.strftime("%H:%M"))


def label(lang: str) -> str:
    """The checkout / cart line name — bot_discount.saving_label for 5%."""
    return _pick("label", lang)


def is_quiet(now_utc: datetime) -> bool:
    hour = (now_utc + TZ).hour
    return hour >= QUIET_FROM or hour < QUIET_TO


# ───────────────────────────── storage ─────────────────────────────

async def _ensure_table(conn) -> None:
    global _table_ready
    if _table_ready:
        return
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS welcome_promo (
            user_id BIGINT PRIMARY KEY,
            created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
            started_at TIMESTAMP,
            lang TEXT,
            timer_message_id BIGINT,
            reminders_done INTEGER NOT NULL DEFAULT 0,
            closed_at TIMESTAMP
        )
    """)
    _table_ready = True


async def mark_pending(user_id: int) -> None:
    """At registration (handlers/start.py, brand-new users only): the 8 hours
    start once they pick a language. Never raises."""
    if user_id in ADMIN_IDS:
        return
    try:
        async with database.pool.acquire() as conn:
            await _ensure_table(conn)
            await conn.execute(
                "INSERT INTO welcome_promo (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id)
    except Exception:
        logger.warning("YANGI5 mark_pending(%s) failed", user_id, exc_info=True)


async def _started_at(user_id: int) -> datetime | None:
    hit = _cache.get(user_id)
    if hit and time.monotonic() - hit[0] < CACHE_TTL:
        return hit[1]
    async with database.pool.acquire() as conn:
        await _ensure_table(conn)
        started = await conn.fetchval(
            "SELECT started_at FROM welcome_promo WHERE user_id = $1 AND closed_at IS NULL", user_id)
    _cache[user_id] = (time.monotonic(), started)
    return started


async def _first_order(user_id: int) -> dict | None:
    """The buyer's own first non-cancelled order, or None."""
    async with database.pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, items FROM orders
                WHERE user_id = $1 AND status <> 'cancelled'
                  AND COALESCE(source, '') NOT IN ('manual', 'b2b', 'test')
                ORDER BY id LIMIT 1""", user_id)
    return dict(row) if row else None


def order_saving(order: dict) -> float:
    import json
    items = order.get("items")
    items = json.loads(items) if isinstance(items, str) else (items or [])
    saved = 0.0
    for it in items:
        if not isinstance(it, dict) or int(it.get("bot_discount") or 0) != PERCENT:
            continue
        try:
            saved += (float(it.get("original_price") or 0) - float(it.get("price") or 0)) * float(it.get("quantity") or 0)
        except (TypeError, ValueError):
            continue
    return max(0.0, saved)


async def ends_at(user_id: int) -> datetime | None:
    """When this buyer's 5% runs out (UTC) — None if they have none now."""
    if user_id in ADMIN_IDS:
        return None
    started = await _started_at(user_id)
    if not started:
        return None
    end = started + timedelta(hours=HOURS)
    if _now() >= end:
        return None
    if await _first_order(user_id):
        return None
    return end


async def percent_for(user_id: int) -> int:
    """5 while the buyer's window is open, else 0. Never raises — checkout
    must not fail on a promotion."""
    try:
        return PERCENT if await ends_at(user_id) else 0
    except Exception:
        logger.warning("YANGI5 percent_for(%s) failed", user_id, exc_info=True)
        return 0


async def _seconds_left(user_id: int) -> float | None:
    try:
        end = await ends_at(user_id)
    except Exception:
        logger.warning("YANGI5 ends_at(%s) failed", user_id, exc_info=True)
        return None
    return (end - _now()).total_seconds() if end else None


# ───────────────────────────── where it shows ─────────────────────────────

async def timer_line(user_id: int, lang: str) -> str:
    """Bot cart / checkout: "⏳ YANGI5 tugashiga: 7 soat 42 daqiqa" or ""."""
    left = await _seconds_left(user_id)
    return _pick("timer_line", lang, left=left_text(left, lang)) if left else ""


async def card_line(user_id: int, product: dict, lang: str) -> str:
    """Product card in the bot: this buyer's own price and the time left, or
    "" — also when the product's own discount is already deeper."""
    left = await _seconds_left(user_id)
    if not left:
        return ""
    try:
        import bot_discount
        base = float(product["price"])
        current = database.effective_price(base, product.get("discount_percent"), product.get("discount_until"))
        mine = bot_discount.line_price(base, current, PERCENT)
    except Exception:
        return ""
    if mine >= current:
        return ""
    return _pick("card_line", lang, price=_som(mine), left=left_text(left, lang))


async def site_payload(user_id: int, lang: str) -> dict | None:
    """The Mini App's countdown: seconds left (the client counts down from
    its own clock, so a wrong phone clock can't shorten it) + its label."""
    left = await _seconds_left(user_id)
    if not left:
        return None
    return {"code": CODE, "percent": PERCENT, "seconds_left": int(left), "label": _pick("site_label", lang)}


async def ai_line(user_id: int) -> str:
    left = await _seconds_left(user_id)
    if not left:
        return ""
    return (f"{CODE}: mijoz yangi a'zo — birinchi buyurtmasiga {PERCENT}% chegirma, yana "
            f"{left_text(left, 'uz')} amal qiladi. Promokod kerak emas, savatda o'zi hisoblanadi; "
            "aniq summani savatni_korish beradi. Bir marta eslat, shoshiltirma.")


def keyboard(lang: str) -> InlineKeyboardMarkup:
    rows = []
    if WEBAPP_URL:
        rows.append([InlineKeyboardButton(text=_pick("btn_shop", lang), web_app=WebAppInfo(url=WEBAPP_URL))])
    rows.append([InlineKeyboardButton(text=_pick("btn_cart", lang), callback_data="cart")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def timer_text(lang: str, seconds_left: float, end_utc: datetime, now_utc: datetime | None = None) -> str:
    return _pick("timer", lang, left=left_text(seconds_left, lang), until=until_text(end_utc, lang, now_utc))


async def cart_numbers(user_id: int) -> tuple[float, float]:
    """(cart sum at shelf price, what 5% saves on it) — the checkout rule."""
    import bot_discount
    rows = await database.get_cart(user_id)
    total = 0.0
    for row in rows:
        base = float(row["price"])
        current = base if row.get("is_set") else database.effective_price(
            base, row.get("discount_percent"), row.get("discount_until"))
        total += current * float(row["cart_quantity"])
    return total, await bot_discount.cart_saving(rows, PERCENT)


async def reminder_text(user_id: int, lang: str, seconds_left: float) -> str:
    try:
        total, saved = await cart_numbers(user_id)
    except Exception:
        logger.warning("YANGI5 cart read failed for %s", user_id, exc_info=True)
        total, saved = 0.0, 0.0
    if total > 0 and saved > 0:
        body = _pick("reminder_cart", lang, total=_som(total), saved=_som(saved), pay=_som(total - saved))
    else:
        body = _pick("reminder_empty", lang, example=_som(EXAMPLE_ORDER),
                     saved=_som(EXAMPLE_ORDER * PERCENT / 100))
    return _pick("reminder", lang, left=left_text(seconds_left, lang), body=body)


# ───────────────────────────── start ─────────────────────────────

async def maybe_start(bot: Bot, user_id: int, lang: str) -> bool:
    """On the language pick (handlers/start.set_language) — or on their first
    visit to the site, for a new member who went there without picking one
    (webapp_server._welcome_promo, 2026-11-08): a pending new member's 8 hours
    start now and the timer message goes out. A no-op for anyone else,
    including a returning user switching language. Never raises."""
    try:
        async with database.pool.acquire() as conn:
            await _ensure_table(conn)
            started = await conn.fetchval(
                """UPDATE welcome_promo SET started_at = (NOW() AT TIME ZONE 'UTC'), lang = $2
                    WHERE user_id = $1 AND started_at IS NULL RETURNING started_at""", user_id, lang)
        if not started:
            return False
        _cache.pop(user_id, None)
        end = started + timedelta(hours=HOURS)
        text = timer_text(lang, (end - _now()).total_seconds(), end)
        try:
            msg = await bot.send_message(user_id, text, parse_mode=ParseMode.HTML, reply_markup=keyboard(lang),
                                         message_effect_id=PARTY_EFFECT)
        except Exception:
            logger.info("YANGI5 timer for %s: no 🎉 effect, sent plain", user_id, exc_info=True)
            msg = await bot.send_message(user_id, text, parse_mode=ParseMode.HTML, reply_markup=keyboard(lang))
        _shown[user_id] = text
        async with database.pool.acquire() as conn:
            await conn.execute("UPDATE welcome_promo SET timer_message_id = $2 WHERE user_id = $1",
                               user_id, msg.message_id)
        logger.info("YANGI5 started for %s", user_id)
        return True
    except Exception:
        logger.warning("YANGI5 start for %s failed", user_id, exc_info=True)
        return False


# ───────────────────────────── the clock ─────────────────────────────

async def _edit(bot: Bot, row: dict, text: str, markup) -> None:
    if not row.get("timer_message_id"):
        return
    try:
        await bot.edit_message_text(text, chat_id=row["user_id"], message_id=row["timer_message_id"],
                                    parse_mode=ParseMode.HTML, reply_markup=markup)
    except Exception as exc:
        if "not modified" not in str(exc).lower():
            logger.info("YANGI5 timer edit for %s failed: %s", row["user_id"], exc)


async def _close(bot: Bot, row: dict, text: str) -> None:
    async with database.pool.acquire() as conn:
        await conn.execute("UPDATE welcome_promo SET closed_at = (NOW() AT TIME ZONE 'UTC') WHERE user_id = $1",
                           row["user_id"])
    _cache.pop(row["user_id"], None)
    _shown.pop(row["user_id"], None)
    await _edit(bot, row, text, None)


async def step(bot: Bot, row: dict, now: datetime | None = None) -> None:
    """One buyer, one pass: close it when used or over, send a due reminder,
    move the timer on."""
    now = now or _now()
    user_id = row["user_id"]
    lang = row.get("lang") or "uz"
    try:
        # Their language now, if they switched after the start (buyer language rule).
        lang = await database.get_user_language(user_id) or lang
    except Exception:
        pass
    started = row["started_at"]
    end = started + timedelta(hours=HOURS)

    order = await _first_order(user_id)
    if order:
        saved = order_saving(order)
        text = (_pick("used", lang, order=order["id"], saved=_som(saved)) if saved > 0
                else _pick("used_plain", lang, order=order["id"]))
        await _close(bot, row, text)
        return
    if now >= end:
        await _close(bot, row, _pick("expired", lang))
        return

    left = (end - now).total_seconds()
    done = int(row.get("reminders_done") or 0)
    if done < len(REMIND_AFTER_HOURS):
        due = started + timedelta(hours=REMIND_AFTER_HOURS[done])
        if now >= due:
            # Counted first: a restart mid-send must not repeat it.
            async with database.pool.acquire() as conn:
                await conn.execute("UPDATE welcome_promo SET reminders_done = $2 WHERE user_id = $1",
                                   user_id, done + 1)
            late = (now - due).total_seconds() > REMIND_LATE_MINUTES * 60
            if not late and not is_quiet(now):
                try:
                    await bot.send_message(user_id, await reminder_text(user_id, lang, left),
                                           parse_mode=ParseMode.HTML, reply_markup=keyboard(lang))
                except Exception as exc:
                    logger.info("YANGI5 reminder to %s failed: %s", user_id, exc)

    text = timer_text(lang, left, end, now)
    if _shown.get(user_id) != text:
        _shown[user_id] = text
        await _edit(bot, row, text, keyboard(lang))


async def _open_rows() -> list[dict]:
    async with database.pool.acquire() as conn:
        await _ensure_table(conn)
        rows = await conn.fetch(
            "SELECT * FROM welcome_promo WHERE started_at IS NOT NULL AND closed_at IS NULL")
    return [dict(r) for r in rows]


async def scheduler_loop(bot: Bot) -> None:
    logger.info("YANGI5 scheduler: %s%% for %sh, reminders at %s h", PERCENT, HOURS, REMIND_AFTER_HOURS)
    while True:
        try:
            for row in await _open_rows():
                try:
                    await step(bot, row)
                except Exception:
                    logger.exception("YANGI5 step for %s failed", row.get("user_id"))
        except Exception:
            logger.exception("YANGI5 scheduler pass failed")
        await asyncio.sleep(TICK)
