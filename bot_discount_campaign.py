"""
10% chegirma e'loni — qizdirib, keyin e'lon (egasi so'rovi 2026-10-08).

Owner: "e'lon qilishdan avval 1-2 ta xabar bilan 2 soatda jo'nat oraliq bilan,
keyin chegirma xabarini barchaga inline '10% chegirmani olish' button bilan
jo'nat, faqat samimiy bo'lsin, sotishga harakat qilma". Bot orqali ham,
kanalga ham. Boshlanishi — PR merge bo'lib bot qayta ishga tushishi bilan.

Uch qadam, har biri bir marta:
  teaser1   — "Siz uchun bir yangilik tayyorlayapmiz"
  teaser2   — kamida 2 soatdan keyin: "yana ozgina qoldi, hech qanday shartsiz"
  announce  — yana kamida 2 soatdan keyin: chegirma YOQILADI (bot_discount),
              keyin hammaga e'lon + "🎁 10% chegirmani olish" tugmasi.

Har qadam botdagi hamma mijozga (o'z tilida: uz / uz_cyr / ru) va @ketoshop_uz
kanaliga (kirillda, kanal tili) boradi. Faqat 09:00–21:00 Toshkent oralig'ida;
vaqt tugasa, keyingi qadam ertalab davom etadi.

Kimga yuborilgani bazada (bot_discount_campaign_sent) bittalab yoziladi:
redeploy yoki qayta ishga tushish fan-out o'rtasida bo'lsa ham hech kim bir
xabarni ikki marta olmaydi — qolganlarga davom etadi.

Boshqaruv: /chegirma — holat · /chegirma_korish — uch xabarni ko'rish ·
/chegirma_toxtat — qolgan qadamlarni yubormaslik.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

import bot_discount
import database
from config import ADMIN_IDS, BOT_USERNAME, REQUIRED_CHANNEL_ID, WEBAPP_URL

logger = logging.getLogger(__name__)
router = Router(name="bot_discount_campaign")

STEPS = ("teaser1", "teaser2", "announce")
GAP = timedelta(hours=2)
SEND_FROM_HOUR = 9
SEND_UNTIL_HOUR = 21
TZ_OFFSET = timedelta(hours=5)
CHANNEL_LANG = "uz_cyr"
CHECK_EVERY = 60
SEND_DELAY = 0.05
SHOP_URL = f"https://t.me/{BOT_USERNAME}/shop"

_STEP_NAMES = {"teaser1": "1-xabar (qiziqtirish)", "teaser2": "2-xabar (qiziqtirish)",
               "announce": "Chegirma e'loni"}


def _now_utc() -> datetime:
    return datetime.utcnow()


def _now_tk() -> datetime:
    return _now_utc() + TZ_OFFSET


def _pick(entry: dict, lang: str) -> str:
    if lang == "ru":
        return entry["ru"]
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        return lat_to_cyr(entry["uz"])
    return entry["uz"]


# ───────────────────────────── matnlar ─────────────────────────────
# Samimiy, sotuvsiz: na "shoshiling", na "faqat bugun". Teaserlarda raqam yo'q.

_TEXT = {
    "teaser1": {
        "uz": "Assalomu alaykum! 🤍\n\n"
              "Ketoshop jamoasidan kichik bir xabar: Siz uchun bir yangilik tayyorlayapmiz.\n\n"
              "Bizni tanlaganingiz, savollaringiz va iliq so'zlaringiz uchun anchadan beri "
              "qandaydir yo'l bilan rahmat aytmoqchi edik. Shunday yo'lni topdik shekilli 🙂\n\n"
              "Tez orada hammasini aytamiz.",
        "ru": "Здравствуйте! 🤍\n\n"
              "Коротко от команды Ketoshop: мы готовим для Вас небольшую новость.\n\n"
              "Давно хотели как-то по-особенному сказать спасибо за то, что Вы выбираете нас, "
              "за Ваши вопросы и тёплые слова. Кажется, мы нашли способ 🙂\n\n"
              "Совсем скоро всё расскажем.",
    },
    "teaser2": {
        "uz": "Yana ozgina qoldi ⏳\n\n"
              "Bu yangilik hech qanday shartsiz bo'ladi — birinchi marta buyurtma "
              "beradiganlarga ham, doimiy mijozlarimizga ham birdek.\n\n"
              "Biz uchun eng qimmatli narsa — ishonchingiz. Bir ozdan keyin aytamiz 🤍",
        "ru": "Осталось совсем немного ⏳\n\n"
              "Эта новость будет без всяких условий — одинаково для тех, кто закажет у нас "
              "впервые, и для наших постоянных покупателей.\n\n"
              "Самое ценное для нас — Ваше доверие. Скоро расскажем 🤍",
    },
    "announce": {
        "uz": "🎁 <b>Bot orqali har bir buyurtmaga 10% chegirma</b>\n\n"
              "Assalomu alaykum! 🤍\n\n"
              "Bugundan boshlab bot orqali o'zingiz buyurtma bersangiz, "
              "<b>istalgan summaga 10% chegirma</b> olasiz.\n\n"
              "• Minimal summa yo'q — bitta mahsulotga ham.\n"
              "• Promokod kerak emas — chegirma savatda o'zi hisoblanadi.\n"
              "• Botda ham, do'kon sahifasida ham ishlaydi.\n\n"
              "Bu — bizni tanlaganingiz va ishonganingiz uchun kichik rahmatimiz. "
              "Sog'lom va xotirjam kunlar tilaymiz! 🌿",
        "ru": "🎁 <b>Скидка 10% на каждый заказ через бота</b>\n\n"
              "Здравствуйте! 🤍\n\n"
              "С сегодняшнего дня, оформляя заказ через бота самостоятельно, Вы получаете "
              "<b>скидку 10% на любую сумму</b>.\n\n"
              "• Никакой минимальной суммы — даже на один товар.\n"
              "• Промокод не нужен — скидка считается в корзине автоматически.\n"
              "• Работает и в боте, и в магазине внутри бота.\n\n"
              "Это наше небольшое спасибо за то, что Вы выбираете нас и доверяете нам. "
              "Здоровых и спокойных Вам дней! 🌿",
    },
}

_BUTTON = {"uz": "🎁 10% chegirmani olish", "ru": "🎁 Получить скидку 10%"}


def build_message(step: str, lang: str) -> tuple[str, InlineKeyboardMarkup | None]:
    """Botdagi mijoz uchun. Tugma faqat e'londa — teaserlar hech narsa sotmaydi."""
    text = _pick(_TEXT[step], lang)
    if step != "announce":
        return text, None
    label = _pick(_BUTTON, lang)
    button = (InlineKeyboardButton(text=label, web_app=WebAppInfo(url=WEBAPP_URL)) if WEBAPP_URL
              else InlineKeyboardButton(text=label, callback_data="catalog"))
    return text, InlineKeyboardMarkup(inline_keyboard=[[button]])


def build_channel_message(step: str) -> tuple[str, InlineKeyboardMarkup | None]:
    """Kanal uchun: kirillda; kanalda web_app tugma ishlamaydi — Mini App
    havolasi (channel_posts.SHOP_URL bilan bir xil)."""
    text = _pick(_TEXT[step], CHANNEL_LANG)
    if step != "announce":
        return text, None
    text += f"\n\n👉 @{BOT_USERNAME}"
    return text, InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=_pick(_BUTTON, CHANNEL_LANG), url=SHOP_URL)]])


# ───────────────────────────── baza ─────────────────────────────

async def _ensure_tables(conn) -> None:
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_discount_campaign (
            step TEXT PRIMARY KEY,
            started_at TIMESTAMP NOT NULL,
            finished_at TIMESTAMP,
            sent INTEGER NOT NULL DEFAULT 0,
            failed INTEGER NOT NULL DEFAULT 0
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_discount_campaign_sent (
            step TEXT NOT NULL,
            chat_id BIGINT NOT NULL,
            ok BOOLEAN NOT NULL,
            sent_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (step, chat_id)
        )
    """)


async def _steps() -> dict[str, dict]:
    async with database.pool.acquire() as conn:
        await _ensure_tables(conn)
        rows = await conn.fetch("SELECT * FROM bot_discount_campaign")
    return {r["step"]: dict(r) for r in rows}


async def _claim(step: str) -> None:
    async with database.pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO bot_discount_campaign (step, started_at) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            step, _now_utc())


async def _finish(step: str, sent: int, failed: int) -> None:
    async with database.pool.acquire() as conn:
        await conn.execute(
            """UPDATE bot_discount_campaign
               SET finished_at = $2, sent = sent + $3, failed = failed + $4
               WHERE step = $1""",
            step, _now_utc(), sent, failed)


async def _mark(step: str, chat_id: int, ok: bool) -> None:
    async with database.pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO bot_discount_campaign_sent (step, chat_id, ok) VALUES ($1, $2, $3) "
            "ON CONFLICT DO NOTHING", step, chat_id, ok)


async def _done(step: str, chat_id: int) -> bool:
    async with database.pool.acquire() as conn:
        return bool(await conn.fetchval(
            "SELECT 1 FROM bot_discount_campaign_sent WHERE step = $1 AND chat_id = $2", step, chat_id))


async def _audience(step: str) -> list[dict]:
    """Botdagi hamma mijoz, ichki akkauntlarsiz, bu qadamni hali olmaganlar."""
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT user_id, COALESCE(language, 'uz') AS language
                 FROM users
                WHERE user_id NOT IN (SELECT user_id FROM banned_users)
                  AND user_id NOT IN (SELECT chat_id FROM bot_discount_campaign_sent WHERE step = $1)
                  AND user_id <> ALL($2::bigint[])
                ORDER BY user_id""",
            step, list(database.LEADERBOARD_EXCLUDED_USER_IDS))
    return [dict(r) for r in rows]


# ───────────────────────────── yuborish ─────────────────────────────

async def _send_one(bot: Bot, chat_id: int, text: str, markup) -> bool:
    for attempt in range(2):
        try:
            await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML,
                                   reply_markup=markup, disable_web_page_preview=True)
            return True
        except TelegramRetryAfter as exc:
            if attempt:
                return False
            await asyncio.sleep(exc.retry_after + 1)
        except (TelegramForbiddenError, TelegramBadRequest):
            return False
        except Exception:
            logger.exception("Bot discount campaign %s failed", chat_id)
            return False
    return False


async def run_step(bot: Bot, step: str) -> tuple[int, int, list[dict]]:
    """Bitta qadam: (e'londa avval chegirmani yoqib) kanal, keyin mijozlar.
    Qaytaradi: (yetkazildi, yetmadi, to'xtatilgan 🔥 chegirmalar)."""
    stopped: list[dict] = []
    if step == "announce":
        # Avval yoqiladi: "bugundan 10%" deb o'qigan odam savatni ochganda
        # chegirma allaqachon ishlayotgan bo'lsin.
        if not await bot_discount.is_active():
            stopped = await bot_discount.set_active(True)
        # Shu kungi 18:00 qiziqish xabari o'tkazib yuboriladi — e'lon kechning
        # yagona xabari bo'lsin (keto_explainer.py dagi kabi).
        try:
            today = _now_tk().date()
            interest = await database.get_interest_state()
            if interest.get("last_sent_date") != today:
                await database.advance_interest(today, int(interest.get("cycle") or 0))
        except Exception:
            logger.exception("Could not claim today's interest nudge")

    if REQUIRED_CHANNEL_ID and not await _done(step, REQUIRED_CHANNEL_ID):
        text, markup = build_channel_message(step)
        ok = await _send_one(bot, REQUIRED_CHANNEL_ID, text, markup)
        if not ok:
            logger.warning("Bot discount campaign %s: channel post failed", step)
        await _mark(step, REQUIRED_CHANNEL_ID, ok)

    sent = failed = 0
    for row in await _audience(step):
        text, markup = build_message(step, row["language"])
        ok = await _send_one(bot, row["user_id"], text, markup)
        sent += ok
        failed += not ok
        # Bittalab, oxirida emas: fan-out o'rtasidagi redeploy kim olganini
        # yo'qotmasin. Bloklaganlar ham yoziladi — ularga qayta urinmaymiz.
        await _mark(step, row["user_id"], ok)
        await asyncio.sleep(SEND_DELAY)
    return sent, failed, stopped


async def _notify_admins(bot: Bot, step: str, sent: int, failed: int, stopped: list[dict]) -> None:
    text = (f"🎁 <b>10% chegirma kampaniyasi — {_STEP_NAMES[step]} yuborildi</b>\n"
            f"✅ {sent} ta yetkazildi · ⚠️ {failed} ta yetmadi · kanalga ham")
    if step == "announce":
        text += ("\n\n✅ Bot orqali buyurtmaga 10% chegirma YOQILDI (adminlarga emas).\n"
                 + bot_discount._stopped_text(stopped)
                 + "\n" + await bot_discount.margin_summary_line())
    else:
        nxt = STEPS[STEPS.index(step) + 1]
        text += f"\nKeyingisi — {_STEP_NAMES[nxt]}, kamida 2 soatdan keyin."
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception:
            pass


def next_due(steps: dict[str, dict], now_utc: datetime) -> str | None:
    """Hozir qaysi qadam ishlashi kerak (yoki None). Tugallanmagan qadam —
    qayta ishga tushishdan keyin davom ettiriladi; yangisi esa oldingisi
    tugagan va boshlanganiga kamida GAP bo'lgandagina."""
    for i, step in enumerate(STEPS):
        row = steps.get(step)
        if row and row.get("finished_at"):
            continue
        if row:
            return step
        if i == 0:
            return step
        prev = steps[STEPS[i - 1]]
        return step if prev["started_at"] + GAP <= now_utc else None
    return None


def in_window(now_tk: datetime) -> bool:
    return SEND_FROM_HOUR <= now_tk.hour < SEND_UNTIL_HOUR


async def _tick(bot: Bot) -> None:
    if not in_window(_now_tk()):
        return
    step = next_due(await _steps(), _now_utc())
    if step is None:
        return
    await _claim(step)
    sent, failed, stopped = await run_step(bot, step)
    await _finish(step, sent, failed)
    logger.info("Bot discount campaign %s: %d sent, %d failed", step, sent, failed)
    await _notify_admins(bot, step, sent, failed, stopped)


async def _all_done() -> bool:
    steps = await _steps()
    return all(steps.get(s, {}).get("finished_at") for s in STEPS)


async def scheduler_loop(bot: Bot) -> None:
    try:
        if await _all_done():
            logger.info("Bot discount campaign already finished — scheduler not needed")
            return
    except Exception:
        logger.exception("Bot discount campaign state read failed")
    logger.info("Bot discount campaign scheduler started")
    while True:
        try:
            await _tick(bot)
            if await _all_done():
                return
        except Exception:
            logger.exception("Bot discount campaign tick failed")
        await asyncio.sleep(CHECK_EVERY)


async def status_text() -> str:
    try:
        steps = await _steps()
    except Exception:
        return "Kampaniya holati o'qilmadi."
    lines = ["<b>E'lon kampaniyasi:</b>"]
    for step in STEPS:
        row = steps.get(step)
        if not row:
            mark = "⏳ navbatda"
        elif not row.get("finished_at"):
            mark = "📤 yuborilmoqda"
        elif row.get("sent", 0) < 0:
            mark = "⛔ to'xtatilgan"
        else:
            tk = row["finished_at"] + TZ_OFFSET
            mark = f"✅ {tk:%d.%m %H:%M} · {row['sent']} ta yetkazildi"
        lines.append(f"• {_STEP_NAMES[step]}: {mark}")
    return "\n".join(lines)


# ───────────────────────────── adminlar ─────────────────────────────

@router.message(Command("chegirma_korish"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_preview(message: Message):
    await message.answer("👀 Mijozlar ko'radigan uchta xabar (Sizning tilingizda) va kanal e'loni:")
    lang = await database.get_user_language(message.from_user.id) or "uz"
    for step in STEPS:
        text, markup = build_message(step, lang)
        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    text, markup = build_channel_message("announce")
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)


@router.message(Command("chegirma_toxtat"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_stop(message: Message):
    """Hali ketmagan qadamlarni yubormaslik. Chegirmaning o'ziga tegmaydi —
    uni /chegirma_on bilan yoqish mumkin."""
    steps = await _steps()
    pending = [s for s in STEPS if not steps.get(s)]
    async with database.pool.acquire() as conn:
        for step in pending:
            await conn.execute(
                """INSERT INTO bot_discount_campaign (step, started_at, finished_at, sent)
                   VALUES ($1, $2, $2, -1) ON CONFLICT DO NOTHING""", step, _now_utc())
    if pending:
        await message.answer("⛔ To'xtatildi: " + ", ".join(_STEP_NAMES[s] for s in pending)
                             + " yuborilmaydi.")
    else:
        await message.answer("ℹ️ To'xtatadigan qadam qolmagan.")
