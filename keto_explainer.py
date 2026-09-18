"""
Keto tangachalar — hammaga sodda tushuntirish + sarflashni yoqish (2026-09-18).

Owner, 2026-09-17: "barchaga ertaga keto tangachalari qanday ishlashini
tushuntirib kechga yaqin eslatmalar yubor bot orqali, faqat hammani o'z
tilida va 'dehqoncha' sodda tilda 5-6 yoshli bolaga tushuntirgandek. keyin
uni keshbek sifatida ishlatishni boshlaymiz yoqib qo'y, 0.5 foiz standart".

So, once, on 18.09.2026 at 17:30 Tashkent:
  1. spending Keto at checkout is switched ON (gamification_state.
     redemption_enabled) — right before the message, so nobody reads "you
     can spend them from today" while the button is still hidden;
  2. every user gets the explainer in their own language (uz / uz_cyr / ru),
     with their own balance in it;
  3. that day's 18:00 interest nudge is claimed, so the explainer is the
     evening's only push.

The key is claimed in release_notes_sent before sending, so a restart can
never send it twice. A bot that is down at 17:30 sends it later the same
evening (until 21:00), or on the next evening.

The standard rate stays 0.5% (gamification.EARN_RATE); higher Keto levels
earn more (gamification.EARN_RATES).

Admin: /keto_tushuntirish — status and a preview in all three languages.
"""
import asyncio
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
router = Router(name="keto_explainer")

KEY = "keto-explainer-2026-09-18"
SEND_AT = datetime(2026, 9, 18, 17, 30)   # Tashkent
SEND_UNTIL_HOUR = 21
TZ_OFFSET = timedelta(hours=5)
CHECK_EVERY = 120
SEND_DELAY = 0.05


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


def _fmt(n: int) -> str:
    return f"{int(n):,}".replace(",", " ")


_TEXT = {
    "uz": (
        "🥑 <b>Keto tangachalar — Sizga kichik minnatdorchiligimiz</b>\n\n"
        "Assalomu alaykum! 🤍\n"
        "Ketoshopni tanlaganingiz uchun chin dildan rahmat. Bugun Sizga bitta "
        "yoqimli yangilikni aytmoqchi edik.\n\n"
        "Har bir xaridingiz uchun Sizga <b>Keto tangachalar</b> qaytadi. "
        "Bu — bizning Sizga bo'lgan rahmatimiz.\n\n"
        "🛒 Siz buyurtma berasiz.\n"
        "📦 Buyurtma qo'lingizga yetib borgan kuni tangachalar hisobingizga tushadi.\n"
        "🥑 Har 100 000 so'mlik xaridga — <b>500 ta tangacha</b>.\n\n"
        "Tangachalar yo'qolmaydi — xuddi pul yig'adigan idishga ozroqdan solib "
        "borgandek, ular yig'ilib boraveradi.\n\n"
        "💰 <b>Eng muhimi:</b> bugundan boshlab tangachalaringizni ishlatsangiz bo'ladi.\n"
        "1 ta tangacha = 1 so'm. Buyurtma berayotganda «🥑 Ketochalarni ishlatish» "
        "tugmasini tanlasangiz, tangachalar pul o'rniga o'tadi va Siz kamroq to'laysiz.\n\n"
        "⭐ Qanchalik ko'p xarid qilsangiz, darajangiz shunchalik ko'tariladi va "
        "har safar ko'proq tangacha qaytadi.\n\n"
        "{balance_line}\n\n"
        "Sizga sog'liq va farovonlik tilaymiz!\n"
        "<i>Hurmat bilan, Ketoshop jamoasi</i>"
    ),
    "ru": (
        "🥑 <b>Keto-монетки — наша небольшая благодарность вам</b>\n\n"
        "Здравствуйте! 🤍\n"
        "Искренне благодарим вас за то, что выбираете Ketoshop. Сегодня хотим "
        "поделиться приятной новостью.\n\n"
        "За каждую покупку вам возвращаются <b>Keto-монетки</b>. "
        "Это наше спасибо вам.\n\n"
        "🛒 Вы оформляете заказ.\n"
        "📦 В день, когда заказ у вас в руках, монетки поступают на ваш счёт.\n"
        "🥑 За каждые 100 000 сум покупки — <b>500 монеток</b>.\n\n"
        "Монетки не сгорают — они копятся, как деньги, которые вы понемногу "
        "откладываете в баночку.\n\n"
        "💰 <b>Самое главное:</b> с сегодняшнего дня монетки можно тратить.\n"
        "1 монетка = 1 сум. При оформлении заказа выберите «🥑 Использовать Ketочки» — "
        "монетки пойдут вместо денег, и вы заплатите меньше.\n\n"
        "⭐ Чем больше вы покупаете, тем выше ваш уровень и тем больше монеток "
        "возвращается каждый раз.\n\n"
        "{balance_line}\n\n"
        "Желаем вам здоровья и благополучия!\n"
        "<i>С уважением, команда Ketoshop</i>"
    ),
}

_BALANCE = {
    "have": {"uz": "👛 Hozirda Sizda <b>{n} ta tangacha</b> to'plangan.",
             "ru": "👛 Сейчас у вас накоплено <b>{n} монеток</b>."},
    "none": {"uz": "👛 Birinchi tangachalaringiz birinchi xaridingizdan so'ng hisobingizga tushadi.",
             "ru": "👛 Первые монетки появятся у вас после первой покупки."},
}

_BUTTONS = {
    "wallet": {"uz": "👛 Tangachalarim", "ru": "👛 Мои монетки"},
    "shop": {"uz": "🛒 Xarid qilish", "ru": "🛒 За покупками"},
}


def _pick(entry: dict, lang: str) -> str:
    if lang == "ru":
        return entry["ru"]
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        return lat_to_cyr(entry["uz"])
    return entry["uz"]


def build_message(lang: str, balance: int) -> tuple[str, InlineKeyboardMarkup]:
    balance_line = (_pick(_BALANCE["have"], lang).replace("{n}", _fmt(balance)) if balance > 0
                    else _pick(_BALANCE["none"], lang))
    text = _pick(_TEXT, lang).replace("{balance_line}", balance_line)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=_pick(_BUTTONS["wallet"], lang), callback_data="kabinetim")],
        [InlineKeyboardButton(text=_pick(_BUTTONS["shop"], lang), callback_data="catalog")],
    ])
    return text, keyboard


async def _audience() -> list[dict]:
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT user_id, COALESCE(language, 'uz') AS language, COALESCE(keto_balance, 0) AS balance
                 FROM users
                WHERE user_id NOT IN (SELECT user_id FROM banned_users)
                  AND user_id <> ALL($1::bigint[])""",
            list(database.LEADERBOARD_EXCLUDED_USER_IDS),
        )
        return [dict(r) for r in rows]


async def _already_sent() -> bool:
    async with database.pool.acquire() as conn:
        return bool(await conn.fetchval("SELECT 1 FROM release_notes_sent WHERE key = $1", KEY))


async def _send_one(bot: Bot, uid: int, text: str, markup) -> bool:
    for attempt in range(2):
        try:
            await bot.send_message(uid, text, parse_mode=ParseMode.HTML, reply_markup=markup)
            return True
        except TelegramRetryAfter as exc:
            if attempt:
                return False
            await asyncio.sleep(exc.retry_after + 1)
        except (TelegramForbiddenError, TelegramBadRequest):
            return False
        except Exception:
            logger.exception("Keto explainer to %s failed", uid)
            return False
    return False


async def run(bot: Bot) -> tuple[int, int]:
    await database.set_gamification_enabled(True)
    await database.set_redemption_enabled(True)
    logger.info("Keto redemption switched ON for everyone")

    today = _now_tk().date()
    try:
        interest = await database.get_interest_state()
        if interest.get("last_sent_date") != today:
            await database.advance_interest(today, int(interest.get("cycle") or 0))
    except Exception:
        logger.exception("Could not claim today's interest nudge")

    sent = failed = 0
    for row in await _audience():
        text, markup = build_message(row["language"], int(row["balance"]))
        if await _send_one(bot, row["user_id"], text, markup):
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(SEND_DELAY)
    return sent, failed


async def _tick(bot: Bot) -> None:
    now = _now_tk()
    in_evening = (SEND_AT.hour, SEND_AT.minute) <= (now.hour, now.minute) and now.hour < SEND_UNTIL_HOUR
    if now < SEND_AT or not in_evening:
        return
    if not await database.claim_release_notes(KEY):
        return
    sent, failed = await run(bot)
    logger.info("Keto explainer: %d sent, %d failed", sent, failed)
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                "🥑 <b>Keto tangachalar tushuntirildi va sarflash yoqildi</b>\n"
                f"✅ {sent} ta yetkazildi · ⚠️ {failed} ta yetmadi\n"
                "Endi mijozlar buyurtmada «🥑 Ketochalarni ishlatish» tugmasini ko'radi (1 Keto = 1 so'm).",
                parse_mode=ParseMode.HTML)
        except Exception:
            pass


async def scheduler_loop(bot: Bot) -> None:
    if await _already_sent():
        return
    logger.info("Keto explainer scheduled for %s Tashkent", SEND_AT)
    while True:
        try:
            await _tick(bot)
            if await _already_sent():
                return
        except Exception:
            logger.exception("Keto explainer tick failed")
        await asyncio.sleep(CHECK_EVERY)


@router.message(Command("keto_tushuntirish"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_preview(message: Message):
    state = "✅ yuborilgan" if await _already_sent() else f"⏳ {SEND_AT:%d.%m.%Y %H:%M} da yuboriladi"
    gs = await database.get_gamification_state()
    await message.answer(
        f"🥑 <b>Keto tushuntirish xabari</b> — {state}\n"
        f"Sarflash hozir: {'✅ yoqilgan' if gs.get('redemption_enabled') else '⚪ o‘chiq (yuborilganda yoqiladi)'}\n"
        "Quyida uch tildagi ko'rinishi (Sizning balansingiz bilan):",
        parse_mode=ParseMode.HTML)
    user = await database.get_user(message.from_user.id)
    balance = int((user or {}).get("keto_balance") or 0)
    for lang in ("uz", "uz_cyr", "ru"):
        text, markup = build_message(lang, balance)
        await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)
