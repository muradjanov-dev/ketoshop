"""📞 Call Centre — botdagi eshik va rollar (egasi, 2026-11-22).

* /callcentre — operator (yoki admin) uchun CRM sahifasini ochadigan tugma;
  boshqalarga bu buyruq umuman javob bermaydi (filtr o'tkazib yuboradi).
* apply_role / revoke_staff — admin paneldagi «huquqni o'zgartirish»:
  ADMIN_IDS ↔ OPERATOR_IDS ro'yxatlarini joyida yangilaydi (restart shart
  emas), "/" menyusini almashtiradi va odamning o'ziga xabar beradi.
* morning_loop — ish kunlari 09:00 (Toshkent) har bir operatorga: bugungi
  qayta qo'ng'iroqlar soni, reja va kun latifasi. Faqat xodimlarga.
"""
import asyncio
import html
import logging
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (BotCommandScopeChat, InlineKeyboardButton, InlineKeyboardMarkup,
                           Message, WebAppInfo)

import call_centre
import call_centre_content
import database
from config import ADMIN_IDS, OPERATOR_IDS, WEBAPP_URL

logger = logging.getLogger(__name__)
router = Router(name="call_centre")

ROLE_LABEL = {"admin": "👑 To'liq admin", "operator": "📞 Call Centre operatori"}

MORNING_HOUR = 9          # Toshkent vaqti
WORK_WEEKDAYS = {0, 1, 2, 3, 4, 5}   # Du–Sha; yakshanba dam


def is_staff(user_id: int) -> bool:
    return user_id in ADMIN_IDS or user_id in OPERATOR_IDS


def open_keyboard() -> InlineKeyboardMarkup | None:
    if not WEBAPP_URL:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="📞 Call Centre CRM ni ochish", web_app=WebAppInfo(url=f"{WEBAPP_URL}/callcentre"))]])


def _plan_line(s: dict) -> str:
    return (f"🎯 Bugungi reja: {s['daily_outbound']} qo'ng'iroq · "
            f"{s['daily_meaningful']} mazmunli suhbat · {s['daily_orders']} buyurtma")


@router.message(Command("callcentre"), F.chat.type == "private",
                F.from_user.func(lambda u: is_staff(u.id)))
async def cmd_callcentre(message: Message):
    keyboard = open_keyboard()
    if keyboard is None:
        await message.answer("⚠️ WEBAPP_URL sozlanmagan — CRM sahifasini ochib bo'lmaydi.")
        return
    today = call_centre.today_local()
    settings = await call_centre.get_settings()
    lines = ["📞 <b>Call Centre CRM</b>", ""]
    if message.from_user.id in OPERATOR_IDS:
        day = await call_centre.day_counts(message.from_user.id, today)
        due = await call_centre.due_followups(message.from_user.id, today)
        lines += [
            f"📤 {day['outbound']}/{settings['daily_outbound']} · "
            f"💬 {day['meaningful']}/{settings['daily_meaningful']} · "
            f"🛒 {day['orders']}/{settings['daily_orders']}",
            f"📅 Bugungi qayta qo'ng'iroqlar: <b>{len(due)}</b>",
            "",
        ]
    else:
        lines += ["Admin sifatida hamma operatorlarni, KPI va baholashni ko'rasiz.", ""]
    lines.append("😄 <i>" + html.escape(call_centre_content.joke_of_day(today.toordinal())) + "</i>")
    await message.answer("\n".join(lines), reply_markup=keyboard, parse_mode="HTML")


async def _set_commands(bot: Bot, user_id: int, role: str | None) -> None:
    from keyboards import ADMIN_COMMANDS, BLOGGER_COMMAND, BUYER_COMMANDS, OPERATOR_COMMAND
    scope = BotCommandScopeChat(chat_id=user_id)
    try:
        if role == "admin":
            await bot.set_my_commands(BUYER_COMMANDS + ADMIN_COMMANDS, scope=scope)
        elif role == "operator":
            await bot.set_my_commands(BUYER_COMMANDS + [OPERATOR_COMMAND], scope=scope)
        elif user_id in await database.get_blogger_user_ids():
            await bot.set_my_commands(BUYER_COMMANDS + [BLOGGER_COMMAND], scope=scope)
        else:
            await bot.delete_my_commands(scope=scope)
    except Exception:
        logger.warning("Could not set commands for %s (%s)", user_id, role, exc_info=True)


def _sync_lists(user_id: int, role: str | None) -> None:
    """Bitta umumiy ro'yxatlar — hamma modul shu zahoti yangisini ko'radi."""
    while user_id in ADMIN_IDS and role != "admin":
        ADMIN_IDS.remove(user_id)
    while user_id in OPERATOR_IDS and role != "operator":
        OPERATOR_IDS.remove(user_id)
    if role == "admin" and user_id not in ADMIN_IDS:
        ADMIN_IDS.append(user_id)
    if role == "operator" and user_id not in OPERATOR_IDS:
        OPERATOR_IDS.append(user_id)


async def apply_role(bot: Bot, user_id: int, role: str, by: int) -> None:
    """Qo'shish yoki huquqni almashtirish. Doimiy (kod/env) adminlarga
    chaqirilmaydi — tekshiruv chaqiruvchida (handlers/admin.py)."""
    await database.add_admin_db(user_id, by, role)
    _sync_lists(user_id, role)
    await _set_commands(bot, user_id, role)
    logger.info("Staff %s set to %s by %s", user_id, role, by)
    try:
        if role == "operator":
            text = ("📞 <b>Siz Keto Shop Call Centre operatorisiz!</b>\n\n"
                    "Ish joyingiz — CRM: qo'ng'iroqlar, qayta aloqalar, kunlik hisobot, "
                    "KPI va daromadingiz bir joyda. Kichik maqsadlarga yetganingizda "
                    "salyut bor 🎆\n\nIstalgan payt /callcentre buyrug'i bilan oching.")
            await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=open_keyboard())
        else:
            from locales import get_text
            lang = await database.get_user_language(user_id)
            await bot.send_message(user_id, get_text("you_are_now_admin", lang), parse_mode="HTML")
    except Exception:
        pass   # botni hali ochmagan bo'lishi mumkin


async def revoke_staff(bot: Bot, user_id: int) -> bool:
    """Bot orqali berilgan huquqni olib tashlash. False — doimiy admin."""
    if not await database.remove_admin_db(user_id):
        return False
    _sync_lists(user_id, None)
    await _set_commands(bot, user_id, None)
    return True


# ───────────────────────────── ertalabki xabar ───────────────────────────────

async def send_morning(bot: Bot, now: datetime | None = None) -> int:
    local = (now or datetime.utcnow()) + call_centre.TZ_OFFSET
    today = local.date()
    if local.weekday() not in WORK_WEEKDAYS or not OPERATOR_IDS:
        return 0
    settings = await call_centre.get_settings()
    joke = call_centre_content.joke_of_day(today.toordinal())
    tip = call_centre_content.MOTIVATION[today.toordinal() % len(call_centre_content.MOTIVATION)]
    sent = 0
    for operator_id in list(OPERATOR_IDS):
        async with database.pool.acquire() as conn:
            fresh = await conn.fetchval(
                """INSERT INTO cc_morning_sent (operator_id, day) VALUES ($1, $2)
                   ON CONFLICT DO NOTHING RETURNING operator_id""", operator_id, today)
        if fresh is None:
            continue
        due = await call_centre.due_followups(operator_id, today)
        text = "\n".join([
            "☀️ <b>Xayrli tong! Call Centre ish kuni boshlandi.</b>",
            "",
            _plan_line(settings),
            f"📅 Bugun qayta qo'ng'iroq qilinadiganlar: <b>{len(due)}</b> ta",
            "",
            f"💡 {html.escape(tip)}",
            "",
            "😄 <b>Kun latifasi</b>",
            f"<i>{html.escape(joke)}</i>",
        ])
        try:
            await bot.send_message(operator_id, text, parse_mode="HTML", reply_markup=open_keyboard())
            sent += 1
        except Exception:
            logger.info("Morning message to operator %s failed", operator_id, exc_info=True)
    return sent


async def morning_loop(bot: Bot) -> None:
    while True:
        try:
            local = datetime.utcnow() + call_centre.TZ_OFFSET
            if local.hour == MORNING_HOUR:
                await send_morning(bot)
        except Exception:
            logger.exception("call centre morning loop")
        await asyncio.sleep(300)
