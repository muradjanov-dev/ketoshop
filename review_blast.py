"""
Fikr so'rovi — every buyer is asked, once, what they think of everything they
bought (owner, 2026-10-24: "xar bir xarid qilganlardan bugunoq barcha
mahsulotlarni so'rab fikrlarini va maxsulotlarimiz ularga maqul kelgan yoki
yo'qligini so'ragin, va izoh ko'rinishida yozishlarini so'ragin").

Who: every customer with at least one delivered order they placed themself
(bot / Mini App). Admin-keyed and wholesale orders are left out — there is no
buyer on the other end of the chat — and so are admin / shop accounts
(database._customer_filter_ids) and banned users.

What: one message in the buyer's language (users.language; uz_cyr through
lat_to_cyr). Every product they bought and haven't reviewed yet is a button,
newest purchase first. A tap opens the stars in a NEW message, so the list
stays put and one product after another can be rated from it; the stars then
ask for a written comment, which handlers/reviews.process_comment saves like
any other review. A buyer who has reviewed everything already gets the
general question only.

A general opinion typed into the chat reaches the admins through the support
relay (handlers/support_relay.py), marked by reply_context() as an answer to
this survey. The AI seller (ai_sales.py) would take that text first, so it is
paused for REPLY_WINDOW_HOURS for every buyer the message reached;
restore_ai_pauses() puts the pauses back after a restart.

Rules:
  * once per buyer per ROUND — review_blast_sends is claimed before sending,
    so a restart can't send twice;
  * daytime only, SEND_FROM–SEND_UNTIL Tashkent, and never after LAST_DAY, so
    a deploy that lands late doesn't start a stale round;
  * every admin gets one summary when the round is done, and every written
    review from it is forwarded to them as it arrives;
  * REVIEW_BLAST=0 switches it off.

A new round later = a new ROUND and LAST_DAY; buyers asked in the old round
are asked again only about what they haven't reviewed since.
"""
import asyncio
import html
import json
import logging
import os
import re
from datetime import date, datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

import database
from config import ADMIN_IDS
from locales import get_text, localize_product_text
from translit import lat_to_cyr

logger = logging.getLogger(__name__)
router = Router(name="review_blast")

ROUND = "2026-10-24"
LAST_DAY = date(2026, 10, 26)
SEND_FROM = 9
SEND_UNTIL = 21
REPLY_WINDOW_HOURS = 48
MAX_BUTTONS = 8
NAME_MAX = 40
SEND_DELAY = 0.05          # ~20 messages a second, under Telegram's 30/s
CHECK_EVERY = 300
TZ_OFFSET = timedelta(hours=5)
_PLACEHOLDER = re.compile(r"(\{\w+\})")

_TEXT = {
    "uz": {
        "products": (
            "Assalomu alaykum{name}! 🌿\n\n"
            "Ketoshop do'konidan xarid qilganingiz uchun katta rahmat 💚 Bugun sizdan bitta "
            "iltimosimiz bor: <b>olgan mahsulotlarimiz sizga ma'qul keldimi?</b>\n\n"
            "Har biri haqida qisqa izoh yozib qoldiring: ta'mi, sifati, qadog'i, "
            "nima tayyorladingiz, yana olasizmi. Maqtov ham, tanqid ham biz uchun "
            "birdek qimmatli — har bir izohni o'zimiz o'qib chiqamiz.\n\n"
            "👇 Mahsulotni tanlang, baho qo'ying va izohingizni yozing.\n"
            "Umumiy fikringiz bo'lsa, shu chatga matn bilan yozib yuboring.\n\n"
            "Hurmat bilan, Ketoshop jamoasi"
        ),
        "general": (
            "Assalomu alaykum{name}! 🌿\n\n"
            "Ketoshop do'konidan xarid qilganingiz va mahsulotlarimizga baho "
            "qo'yganingiz uchun katta rahmat 💚\n\n"
            "Bugun umumiy fikringizni bilmoqchimiz: <b>mahsulotlarimiz sizga "
            "ma'qul keldimi?</b> Nimasi yoqdi, nimani yaxshilashimiz kerak, yana "
            "qaysi mahsulotlarni ko'rishni xohlaysiz?\n\n"
            "Shu chatga matn bilan yozib yuboring — har bir izohni o'zimiz o'qib "
            "chiqamiz.\n\n"
            "Hurmat bilan, Ketoshop jamoasi"
        ),
        "stars": "<b>{product}</b>\n\n⭐ Mahsulot sizga qanchalik ma'qul keldi? Baho qo'ying:",
        "comment": (
            "<b>{product}</b> — {stars}\n\n"
            "💬 Endi izohingizni yozing: ta'mi, sifati, qadog'i qanday edi, "
            "nima tayyorladingiz, yana olasizmi?\n\n"
            "Izohsiz saqlash uchun /skip bosing."
        ),
        "more": "Yana bir mahsulot haqida yozish uchun yuqoridagi ro'yxatdan tanlang 👆",
    },
    "ru": {
        "products": (
            "Здравствуйте{name}! 🌿\n\n"
            "Большое спасибо, что покупаете в Ketoshop 💚 Сегодня у нас к вам одна "
            "просьба: <b>понравились ли вам наши продукты?</b>\n\n"
            "Напишите о каждом пару слов: вкус, качество, упаковка, что "
            "приготовили, возьмёте ли ещё. И похвала, и критика для нас одинаково "
            "ценны — каждый отзыв мы читаем сами.\n\n"
            "👇 Выберите продукт, поставьте оценку и напишите отзыв.\n"
            "Если хотите поделиться общим впечатлением — напишите текстом прямо в этот чат.\n\n"
            "С уважением, команда Ketoshop"
        ),
        "general": (
            "Здравствуйте{name}! 🌿\n\n"
            "Большое спасибо за покупки в Ketoshop и за ваши оценки 💚\n\n"
            "Сегодня хотим узнать ваше общее впечатление: <b>понравились ли вам "
            "наши продукты?</b> Что понравилось, что нам стоит улучшить, какие "
            "ещё продукты вы хотели бы у нас видеть?\n\n"
            "Напишите текстом прямо в этот чат — каждый отзыв мы читаем сами.\n\n"
            "С уважением, команда Ketoshop"
        ),
        "stars": "<b>{product}</b>\n\n⭐ Насколько вам понравился продукт? Поставьте оценку:",
        "comment": (
            "<b>{product}</b> — {stars}\n\n"
            "💬 Теперь напишите отзыв: какой вкус, качество, упаковка, что "
            "приготовили, возьмёте ли ещё?\n\n"
            "Чтобы сохранить без отзыва, нажмите /skip."
        ),
        "more": "Чтобы написать о другом продукте, выберите его в списке выше 👆",
    },
}


def enabled() -> bool:
    return os.getenv("REVIEW_BLAST", "1").strip() != "0"


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


def in_window(now_tk: datetime) -> bool:
    """Daytime on a day the round is still valid."""
    return now_tk.date() <= LAST_DAY and SEND_FROM <= now_tk.hour < SEND_UNTIL


def _lang(lang: str | None) -> str:
    return lang if lang in ("uz", "uz_cyr", "ru") else "uz"


def say(key: str, lang: str, **values) -> str:
    """One of the texts above, in the buyer's language. The template is
    transliterated before the values go in, so a Latin name or a product
    name stays exactly as it is spelled."""
    lang = _lang(lang)
    template = _TEXT["ru" if lang == "ru" else "uz"][key]
    if lang == "uz_cyr":
        template = "".join(part if _PLACEHOLDER.fullmatch(part) else lat_to_cyr(part)
                           for part in _PLACEHOLDER.split(template))
    return template.format(**values) if values else template


def _first_name(full_name: str | None) -> str:
    return (full_name or "").strip().split(" ")[0][:40]


def message_text(lang: str, full_name: str | None, has_products: bool) -> str:
    first = _first_name(full_name)
    return say("products" if has_products else "general", lang,
                name=f", {html.escape(first, quote=False)}" if first else "")


def _short(name: str) -> str:
    name = " ".join((name or "").split())
    return name if len(name) <= NAME_MAX else name[:NAME_MAX - 1].rstrip() + "…"


def product_name(product: dict, lang: str) -> str:
    return localize_product_text(product.get("name") or "", product.get("name_ru"), _lang(lang)) or "—"


def picks_for(orders: list[dict], reviewed: set[int], catalog: dict[int, dict]) -> list[int]:
    """Products to ask this buyer about, newest purchase first.

    `orders` are the buyer's delivered orders as {"at": datetime, "items":
    [...]}. Gift and aksiya bonus lines were never chosen, a set line has no
    product of its own to rate, and a product reviewed already or gone from
    the catalogue can't be asked about."""
    seen: set[int] = set()
    out: list[int] = []
    for order in sorted(orders, key=lambda o: o["at"], reverse=True):
        for item in order["items"]:
            if not isinstance(item, dict) or item.get("is_gift") or item.get("is_bonus") \
                    or item.get("is_set"):
                continue
            try:
                pid = int(item.get("product_id"))
            except (TypeError, ValueError):
                continue
            if pid in seen or pid in reviewed or pid not in catalog:
                continue
            seen.add(pid)
            out.append(pid)
    return out


def keyboard(pids: list[int], catalog: dict[int, dict], lang: str) -> InlineKeyboardMarkup | None:
    rows = [[InlineKeyboardButton(text=f"⭐ {_short(product_name(catalog[pid], lang))}",
                                  callback_data=f"rbl:{pid}")]
            for pid in pids[:MAX_BUTTONS]]
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def stars_keyboard(pid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"⭐ {n}", callback_data=f"rbs:{pid}:{n}") for n in range(1, 6)
    ]])


# ─────────────────────────────── storage ────────────────────────────────────

async def ensure_tables() -> None:
    async with database.pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS review_blast_sends (
                round_key TEXT NOT NULL,
                user_id BIGINT NOT NULL,
                products INTEGER NOT NULL DEFAULT 0,
                delivered BOOLEAN NOT NULL DEFAULT FALSE,
                sent_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (round_key, user_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS review_blast_rounds (
                round_key TEXT PRIMARY KEY,
                finished_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)


async def _round_finished() -> bool:
    async with database.pool.acquire() as conn:
        return bool(await conn.fetchval(
            "SELECT 1 FROM review_blast_rounds WHERE round_key = $1", ROUND))


async def _load_audience() -> tuple[dict[int, list[dict]], dict[int, dict], dict[int, set[int]], dict[int, dict]]:
    """(orders per buyer not yet asked this round, their user rows, what each
    has reviewed, the catalogue)."""
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT o.user_id, o.items, COALESCE(o.delivered_at, o.created_at) AS at
                  FROM orders o
                 WHERE o.status = 'delivered'
                   AND {database._REAL_ORDER}
                   AND o.user_id <> ALL($1::bigint[])
                   AND o.user_id NOT IN (SELECT user_id FROM banned_users)
                   AND o.user_id NOT IN (SELECT user_id FROM review_blast_sends
                                          WHERE round_key = $2)""",
            database._customer_filter_ids(), ROUND)
        orders: dict[int, list[dict]] = {}
        for r in rows:
            raw = r["items"]
            try:
                items = json.loads(raw) if isinstance(raw, str) else (raw or [])
            except Exception:
                items = []
            orders.setdefault(r["user_id"], []).append({"at": r["at"], "items": items or []})
        ids = list(orders)
        users = {r["user_id"]: dict(r) for r in await conn.fetch(
            "SELECT user_id, full_name, username, language FROM users WHERE user_id = ANY($1::bigint[])",
            ids)}
        reviewed: dict[int, set[int]] = {}
        for r in await conn.fetch(
                "SELECT user_id, product_id FROM reviews WHERE user_id = ANY($1::bigint[])", ids):
            reviewed.setdefault(r["user_id"], set()).add(r["product_id"])
        catalog = {r["id"]: dict(r) for r in await conn.fetch("SELECT id, name, name_ru FROM products")}
    return orders, users, reviewed, catalog


async def _claim(user_id: int, products: int) -> bool:
    async with database.pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO review_blast_sends (round_key, user_id, products)
               VALUES ($1, $2, $3) ON CONFLICT DO NOTHING RETURNING TRUE""",
            ROUND, user_id, products) is not None


async def _set_delivered(user_id: int) -> None:
    async with database.pool.acquire() as conn:
        await conn.execute(
            "UPDATE review_blast_sends SET delivered = TRUE, sent_at = CURRENT_TIMESTAMP "
            "WHERE round_key = $1 AND user_id = $2", ROUND, user_id)


async def _finish_round() -> bool:
    """True for the one call that closes the round."""
    async with database.pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO review_blast_rounds (round_key) VALUES ($1) ON CONFLICT DO NOTHING RETURNING TRUE",
            ROUND) is not None


async def _round_counts() -> dict:
    async with database.pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT COUNT(*) FILTER (WHERE delivered)                   AS delivered,
                      COUNT(*) FILTER (WHERE delivered AND products > 0)  AS with_products,
                      COUNT(*) FILTER (WHERE NOT delivered)               AS failed
                 FROM review_blast_sends WHERE round_key = $1""", ROUND)
    return dict(row) if row else {"delivered": 0, "with_products": 0, "failed": 0}


async def _recent_send(user_id: int):
    async with database.pool.acquire() as conn:
        return await conn.fetchrow(
            """SELECT sent_at FROM review_blast_sends
                WHERE user_id = $1 AND delivered
                  AND sent_at >= CURRENT_TIMESTAMP - make_interval(hours => $2)
                ORDER BY sent_at DESC LIMIT 1""", user_id, REPLY_WINDOW_HOURS)


# ─────────────────────────────── sending ────────────────────────────────────

def _pause_ai(user_id: int, seconds: int) -> None:
    try:
        import ai_sales
        ai_sales.pause_for_human(user_id, max(1, int(seconds)))
    except Exception:
        logger.exception("Could not pause the AI seller for %s", user_id)


async def restore_ai_pauses() -> int:
    """After a restart: buyers asked in the last REPLY_WINDOW_HOURS go on
    talking to the admins, not the AI, for what is left of the window."""
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT user_id,
                      EXTRACT(EPOCH FROM (sent_at + make_interval(hours => $1)
                                          - CURRENT_TIMESTAMP))::int AS seconds_left
                 FROM review_blast_sends
                WHERE delivered
                  AND sent_at >= CURRENT_TIMESTAMP - make_interval(hours => $1)""",
            REPLY_WINDOW_HOURS)
    for row in rows:
        _pause_ai(row["user_id"], row["seconds_left"])
    return len(rows)


async def _send(bot: Bot, user_id: int, body: str, markup) -> bool:
    for _ in range(2):
        try:
            await bot.send_message(user_id, body, parse_mode=ParseMode.HTML,
                                   reply_markup=markup, disable_web_page_preview=True)
            return True
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except TelegramForbiddenError:
            return False
        except Exception:
            logger.warning("Review blast to %s failed", user_id, exc_info=True)
            return False
    return False


async def _notify_admins(bot: Bot, body: str) -> None:
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, body, parse_mode=ParseMode.HTML,
                                   disable_web_page_preview=True)
        except Exception:
            pass


def summary_text(counts: dict) -> str:
    return (
        "📨 <b>Fikr so'rovi yuborildi</b>\n\n"
        f"✅ {counts['delivered']} ta xaridorga yetdi "
        f"({counts['with_products']} tasida hali baholanmagan mahsulot bor edi)\n"
        f"⚠️ {counts['failed']} tasiga yetmadi — botni bloklagan bo'lishi mumkin\n\n"
        "So'rovdan kelgan har bir sharh sizga shu yerga keladi, hammasi /sharhlar va admin "
        "paneldagi «💬 Izohlar»da ham turadi. Umumiy fikrlar «Xabarlar»ga "
        f"«💬 Fikr so'roviga javob» belgisi bilan tushadi; bu xaridorlar uchun AI "
        f"sotuvchi {REPLY_WINDOW_HOURS} soat jim turadi."
    )


async def run_once(bot: Bot, now_tk: datetime | None = None) -> int:
    """One sweep. Returns how many buyers the message reached."""
    if not enabled() or not in_window(now_tk or _now_tk()):
        return 0
    if await _round_finished():
        return 0
    orders, users, reviewed, catalog = await _load_audience()
    sent = 0
    for user_id, user_orders in orders.items():
        if not in_window(_now_tk()):
            return sent                      # evening came — the rest go tomorrow
        user = users.get(user_id)
        if not user:
            continue
        lang = _lang(user.get("language"))
        pids = picks_for(user_orders, reviewed.get(user_id, set()), catalog)
        if not await _claim(user_id, len(pids)):
            continue
        body = message_text(lang, user.get("full_name"), bool(pids))
        if await _send(bot, user_id, body, keyboard(pids, catalog, lang)):
            await _set_delivered(user_id)
            _pause_ai(user_id, REPLY_WINDOW_HOURS * 3600)
            sent += 1
        await asyncio.sleep(SEND_DELAY)
    if await _finish_round():
        await _notify_admins(bot, summary_text(await _round_counts()))
    return sent


async def reply_context(user_id: int) -> str:
    """A line for the top of the support card when this buyer got the survey
    in the last REPLY_WINDOW_HOURS; '' otherwise."""
    if not await _recent_send(user_id):
        return ""
    return "💬 <b>Fikr so'roviga javob</b> — mahsulotlarimiz haqida umumiy fikr\n\n"


async def scheduler_loop(bot: Bot) -> None:
    try:
        await ensure_tables()
        await restore_ai_pauses()
    except Exception:
        logger.exception("Review blast setup failed")
    logger.info("Review blast %s scheduler started (%02d:00–%02d:00 until %s)",
                ROUND, SEND_FROM, SEND_UNTIL, LAST_DAY.isoformat())
    while True:
        try:
            await run_once(bot)
        except Exception:
            logger.exception("Review blast tick failed")
        if _now_tk().date() > LAST_DAY:
            return
        await asyncio.sleep(CHECK_EVERY)


# ─────────────────────────────── buttons ────────────────────────────────────

async def notify_review(bot: Bot, user, product_id: int, rating: int, comment: str | None) -> None:
    """Every review written from the survey goes to the admins as it lands."""
    try:
        from handlers.cart import buyer_contact_link
        product = await database.get_product(product_id)
        name = html.escape(product_name(product, "uz") if product else f"#{product_id}", quote=False)
        contact = buyer_contact_link(user.id, user.username, user.full_name)
        said = f"\n«{html.escape(comment, quote=False)}»" if comment else "\n<i>izohsiz</i>"
        await _notify_admins(bot, f"💬 <b>Fikr so'rovi: yangi sharh</b>\n{contact} — "
                                  f"<b>{name}</b>, {'⭐' * int(rating)}{said}")
    except Exception:
        logger.exception("Could not forward survey review to admins")


@router.callback_query(F.data.startswith("rbl:"))
async def pick_product(callback: CallbackQuery, state: FSMContext):
    """A product from the survey list: the stars go in a new message, so the
    list stays where it is for the next product."""
    from handlers.reviews import ReviewStates
    try:
        product_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("❌")
        return
    user_id = callback.from_user.id
    lang = _lang(await database.get_user_language(user_id))
    if await database.has_user_reviewed(user_id, product_id):
        await callback.answer(get_text("review_already_exists", lang), show_alert=True)
        return
    product = await database.get_product(product_id)
    if not product:
        await callback.answer("❌")
        return
    name = product_name(product, lang)
    await state.set_state(ReviewStates.waiting_rating)
    await state.update_data(product_id=product_id, lang=lang, src="blast", product_name=name)
    await callback.message.answer(
        say("stars", lang, product=html.escape(name, quote=False)),
        reply_markup=stars_keyboard(product_id), parse_mode=ParseMode.HTML)
    await callback.answer()


@router.callback_query(F.data.startswith("rbs:"))
async def pick_stars(callback: CallbackQuery, state: FSMContext):
    """Stars chosen — now ask for the written comment. Works from the
    message's own data too, so a tap after a restart (FSM forgotten) still
    lands in the right product."""
    from handlers.reviews import ReviewStates
    try:
        _, pid, n = callback.data.split(":")
        product_id, rating = int(pid), max(1, min(5, int(n)))
    except ValueError:
        await callback.answer("❌")
        return
    user_id = callback.from_user.id
    data = await state.get_data()
    lang = _lang(data.get("lang") or await database.get_user_language(user_id))
    if await database.has_user_reviewed(user_id, product_id):
        await callback.answer(get_text("review_already_exists", lang), show_alert=True)
        return
    name = data.get("product_name") if data.get("product_id") == product_id else None
    if not name:
        product = await database.get_product(product_id)
        name = product_name(product, lang) if product else "—"
    await state.set_state(ReviewStates.waiting_comment)
    await state.update_data(product_id=product_id, rating=rating, lang=lang,
                            src="blast", product_name=name)
    await callback.message.edit_text(
        say("comment", lang, product=html.escape(name, quote=False), stars="⭐" * rating),
        parse_mode=ParseMode.HTML)
    await callback.answer()
