"""OpenAI balansi kamayganda adminlarga ogohlantirish (egasi, 2026-11-26 —
kredit tugab AI bir kun jim qoldi: "ai balansimizda $1 qolganda botdan hamma
adminlarga xabar ber, ai hisobini to'ldirish uchun").

OpenAI oddiy API kaliti bilan balansni ko'rsatmaydi. Shuning uchun:
* /ai_balans 20 — to'ldirgandan keyin balansni botga aytasiz. Bot o'sha
  paytdagi jami OpenAI sarfini (ai_usage, provider='openai') eslab qoladi va
  qoldiqni o'zi hisoblaydi: balans − shundan keyingi sarf.
* Har EVERY soniyada: qoldiq ≤ THRESHOLD bo'lsa — hamma adminlarga bitta
  xabar (yangi /ai_balans gacha qayta yubormaydi).
* Zaxira: OpenAI "kredit tugadi" (credit_balance_exhausted / insufficient_quota)
  qaytarsa — darhol adminlarga, ALERT_GAP da bir martadan ko'p emas.
  Taxmin adashsa ham (auto-recharge, yurist sarfi hisobda yo'q) — shu ishlaydi.
"""
from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

import database

logger = logging.getLogger(__name__)
router = Router(name="ai_balance")

THRESHOLD = 1.0
EVERY = 600
ALERT_GAP = 3 * 3600
BALANCE_KEY, BASE_KEY, ALERTED_KEY = "balance_usd", "balance_base", "balance_alerted"
BILLING = "https://platform.openai.com/settings/organization/billing/overview"
EXHAUSTED_MARKS = ("credit_balance_exhausted", "insufficient_quota", "no credits remaining",
                   "exceeded your current quota")

_bot: dict = {"bot": None}
_last_exhausted = {"at": 0.0}


async def total_openai_spend() -> float:
    async with database.pool.acquire() as conn:
        return float(await conn.fetchval(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM ai_usage WHERE provider = 'openai'") or 0)


async def _values() -> dict:
    import ai_sales
    return await ai_sales._load_settings()


async def remaining() -> float | None:
    """Taxminiy qoldiq ($) yoki None — /ai_balans hali berilmagan."""
    values = await _values()
    if not values.get(BALANCE_KEY):
        return None
    balance = float(values[BALANCE_KEY])
    base = float(values.get(BASE_KEY) or 0)
    return balance - (await total_openai_spend() - base)


def low_text(left: float) -> str:
    return (f"⚠️ <b>AI balansi tugayapti</b>\n\n"
            f"OpenAI hisobida taxminan <b>${max(left, 0):.2f}</b> qoldi. Tugasa AI sotuvchi, sayt "
            f"yordamchisi, Instagram izoh va Direct javoblari to'xtaydi.\n\n"
            f"👉 To'ldirish: {BILLING}\n"
            f"To'ldirgach botga yozing: <code>/ai_balans SUMMA</code> (masalan <code>/ai_balans 20</code>)")


EXHAUSTED_TEXT = (f"🛑 <b>AI krediti tugadi</b> — OpenAI so'rovlarni rad etyapti.\n\n"
                  f"AI sotuvchi, sayt yordamchisi va Instagram javoblari hozir ishlamayapti "
                  f"(savollar adminlarga tushadi; AI qaytgach javobsizlariga o'zi javob beradi).\n\n"
                  f"👉 To'ldirish: {BILLING}\n"
                  f"Keyin: <code>/ai_balans SUMMA</code>")


async def notify_admins(text: str) -> int:
    bot = _bot["bot"]
    if bot is None:
        return 0
    from config import ADMIN_IDS
    n = 0
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML", disable_web_page_preview=True)
            n += 1
        except Exception as exc:
            logger.info("ai balance alert → %s failed: %s", admin_id, exc)
    return n


def is_exhausted(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(mark in text for mark in EXHAUSTED_MARKS)


def note_error(exc: BaseException) -> None:
    """AI chaqiruvi xatosi — kredit tugagan bo'lsa adminlarga (fonda, bloklamasdan)."""
    if not is_exhausted(exc):
        return
    now = time.monotonic()
    if _last_exhausted["at"] and now - _last_exhausted["at"] < ALERT_GAP:
        return
    _last_exhausted["at"] = now
    try:
        asyncio.get_running_loop().create_task(notify_admins(EXHAUSTED_TEXT))
    except RuntimeError:
        pass


async def check() -> str:
    """'none' | 'ok' | 'alerted' | 'already'."""
    import ai_sales
    left = await remaining()
    if left is None:
        return "none"
    if left > THRESHOLD:
        return "ok"
    if (await _values()).get(ALERTED_KEY) == "1":
        return "already"
    if await notify_admins(low_text(left)):
        await ai_sales.set_setting(ALERTED_KEY, "1")
    return "alerted"


async def loop(bot: Bot) -> None:
    _bot["bot"] = bot
    await asyncio.sleep(120)
    while True:
        try:
            await check()
        except Exception:
            logger.warning("ai balance check failed", exc_info=True)
        await asyncio.sleep(EVERY)


async def status_line() -> str:
    try:
        left = await remaining()
    except Exception:
        return ""
    if left is None:
        return "Balans: noma'lum — to'ldirgach /ai_balans SUMMA"
    mark = "⚠️ " if left <= THRESHOLD else ""
    return f"Balans (taxminiy): {mark}<b>${max(left, 0):.2f}</b> · /ai_balans"


@router.message(Command("ai_balans"))
async def cmd_balance(message: Message):
    import ai_sales
    from config import ADMIN_IDS
    if message.from_user.id not in ADMIN_IDS:
        return
    _bot["bot"] = _bot["bot"] or message.bot
    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer(
            (await status_line()) + f"\n\nOgohlantirish: qoldiq ${THRESHOLD:g} ga tushganda hamma adminlarga.\n"
            "To'ldirgach: <code>/ai_balans 20</code> — OpenAI Billing sahifasidagi «Credit balance».",
            parse_mode="HTML")
        return
    try:
        amount = float(parts[1].replace(",", ".").lstrip("$"))
        if not 0 <= amount < 100_000:
            raise ValueError
    except ValueError:
        await message.answer("Summa noto'g'ri. Masalan: <code>/ai_balans 20</code>", parse_mode="HTML")
        return
    base = await total_openai_spend()
    await ai_sales.set_setting(BALANCE_KEY, f"{amount:.4f}", message.from_user.id)
    await ai_sales.set_setting(BASE_KEY, f"{base:.6f}", message.from_user.id)
    await ai_sales.set_setting(ALERTED_KEY, "0", message.from_user.id)
    _last_exhausted["at"] = 0.0
    await message.answer(f"✅ Balans saqlandi: <b>${amount:.2f}</b>. Qoldiq ${THRESHOLD:g} ga tushganda "
                         "hamma adminlarga xabar boradi.", parse_mode="HTML")
