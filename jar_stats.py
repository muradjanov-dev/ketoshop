"""
🫙 Banka mahsulotlari — what sold in a glass jar, bottle or tin over the last
15 and 30 days: how many, the average price, the money, and what posting one
with UzPost costs (owner, 2026-10-24: "15 kunlik va 30 kunlik statistikani
adminlarga botdan yubor").

Built live from the orders through database.get_product_sales — the
dashboard's «📦 Mahsulot savdosi» table, so the two always agree — and
uzpost.is_jar decides what is a jar (the same rule that doubles their weight
for the post). Pushed once to every admin after the deploy that carries
PUSH_KEY, during daytime, claimed in release_notes_sent so a restart never
repeats it; /banka shows it again any time.
"""
import asyncio
import html
import logging
from datetime import datetime, timedelta

from aiogram import Bot, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message

import database
import uzpost
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router(name="jar_stats")

PERIODS = (15, 30)
PUSH_KEY = "2026-10-24-banka-statistika"
SEND_WINDOW = (9, 21)          # Tashkent hours
CHECK_EVERY = 300
TZ_OFFSET = timedelta(hours=5)
MAX_CHARS = 4000


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


def _som(value: float) -> str:
    return f"{int(round(value or 0)):,}".replace(",", " ")


def _qty(value: float) -> str:
    value = float(value or 0)
    return str(int(value)) if value.is_integer() else f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def window(days: int, today=None) -> dict:
    """The last `days` Tashkent days, today included — get_product_sales'
    custom period, so «15 kun» on 24.10 is 10.10–24.10."""
    today = today or _now_tk().date()
    return {"start": (today - timedelta(days=days - 1)).isoformat(), "end": today.isoformat()}


def post_fee(row: dict) -> int:
    """What posting one of these costs the buyer with UzPost, box included."""
    return uzpost.buyer_fee([{"name": row.get("name"), "quantity": 1, "unit": row.get("unit")}])


def report_text(days: int, period: dict, rows: list[dict]) -> str:
    """One period's message: every jar product sold, most money first."""
    jars = sorted((r for r in rows if r.get("kind") == "product" and r.get("qty")
                   and uzpost.is_jar(r.get("name"))),
                  key=lambda r: (-r["revenue"], r["name"]))
    start = datetime.fromisoformat(period["start"]).strftime("%d.%m")
    end = datetime.fromisoformat(period["end"]).strftime("%d.%m")
    head = f"🫙 <b>Banka mahsulotlari — oxirgi {days} kun ({start}–{end})</b>\n\n"
    if not jars:
        return head + "Bu davrda banka mahsulotlari sotilmagan."
    lines = []
    for i, r in enumerate(jars, 1):
        b2b = f" (shundan B2B {_qty(r['b2b_qty'])})" if r.get("b2b_qty") else ""
        lines.append(
            f"{i}. <b>{html.escape(r['name'], quote=False)}</b>\n"
            f"   {_qty(r['qty'])} ta{b2b} × ~{_som(r['revenue'] / r['qty'])} = "
            f"<b>{_som(r['revenue'])}</b> so'm · pochta 1 dona: {_som(post_fee(r))}")
    total_qty = sum(r["qty"] for r in jars)
    total = sum(r["revenue"] for r in jars)
    tail = (f"\n\n<b>Jami: {_qty(total_qty)} ta · {_som(total)} so'm</b>\n"
            "<i>Narx — o'rtacha (summa ÷ soni, B2B ham ichida). «Pochta 1 dona» — shu mahsulotdan "
            "bittasini UzPost «Bir Qadam» bilan viloyatga jo'natish narxi; bankali mahsulot "
            "og'irligi 2 baravar hisoblanadi.</i>")
    # Telegram stops at 4096 characters — the smallest sellers give way.
    hidden = 0
    while len(head) + len("\n".join(lines)) + len(tail) + 40 > MAX_CHARS and len(lines) > 1:
        lines.pop()
        hidden += 1
    more = f"\n… va yana {hidden} ta (to'liq ro'yxat — admin panel, Dashboard)" if hidden else ""
    return head + "\n".join(lines) + more + tail


async def build_reports() -> list[str]:
    out = []
    for days in PERIODS:
        period = window(days)
        data = await database.get_product_sales(period)
        out.append(report_text(days, period, data.get("rows") or []))
    return out


async def _send_all(bot: Bot, chat_id: int, texts: list[str]) -> None:
    for text in texts:
        await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML)


async def push_once(bot: Bot) -> bool:
    """Send the report to every admin once per PUSH_KEY. True when done
    (sent now, or already sent before)."""
    if not SEND_WINDOW[0] <= _now_tk().hour < SEND_WINDOW[1]:
        return False
    if not await database.claim_release_notes(PUSH_KEY):
        return True
    try:
        texts = await build_reports()
    except Exception:
        await database.release_release_notes(PUSH_KEY)     # try again next tick
        raise
    sent = failed = 0
    for admin_id in list(dict.fromkeys(ADMIN_IDS)):
        try:
            await _send_all(bot, admin_id, texts)
            sent += 1
        except Exception as exc:
            failed += 1
            logger.warning("Jar stats to admin %s failed: %s", admin_id, exc)
        await asyncio.sleep(0.05)
    logger.info("Jar stats %s: %d sent, %d failed", PUSH_KEY, sent, failed)
    return True


async def scheduler_loop(bot: Bot) -> None:
    while True:
        try:
            if await push_once(bot):
                return
        except Exception:
            logger.exception("Jar stats push failed")
        await asyncio.sleep(CHECK_EVERY)


@router.message(Command("banka"))
async def cmd_banka(message: Message):
    """/banka — the same 15 / 30 day report, for an admin, any time."""
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        texts = await build_reports()
    except Exception:
        logger.exception("Jar stats for /banka failed")
        await message.answer("⚠️ Statistikani hisoblab bo'lmadi, birozdan keyin qayta urinib ko'ring.")
        return
    for text in texts:
        await message.answer(text, parse_mode=ParseMode.HTML)
