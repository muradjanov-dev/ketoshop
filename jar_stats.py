"""
📦 All products and sets sold over the last 15 and 30 Tashkent days:
quantity, average price and goods revenue. Recorded postal charges are
shown separately by order; current tariff estimates never appear here.

Built live from the orders through database.get_product_sales — the
dashboard's «📦 Mahsulot savdosi» table, so the two always agree.
Pushed once to every admin after the deploy that carries
PUSH_KEY, during daytime, claimed in release_notes_sent so a restart never
repeats it; /mahsulot_savdosi (and the old /banka alias) shows it any time.
Long reports are split into messages without dropping products.
"""
import asyncio
import html
import logging
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

import database
from config import ADMIN_IDS
from tg_safety import strip_markup

logger = logging.getLogger(__name__)
router = Router(name="jar_stats")

PERIODS = (15, 30)
PUSH_KEY = "2026-10-25-barcha-mahsulotlar-statistika"
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


def _postage_blocks(postage_orders: list[dict] | None) -> list[str]:
    if not postage_orders:
        return []
    methods = {"uzpost": "UzPost", "bts": "BTS", "emu": "EMU"}
    lines = ["📮 <b>Buyurtmalarga hisoblangan pochta</b>"]
    for order in postage_orders:
        when = database.format_local_dt(order["created_at"])
        method = methods.get(order["method"], "Pochta")
        lines.append(f"#{order['id']} · {when} · {method}: <b>{_som(order['fee'])}</b> so'm")
    total = sum(order["fee"] for order in postage_orders)
    lines.append(f"<b>Pochta jami: {len(postage_orders)} ta buyurtma · {_som(total)} so'm</b>\n"
                 "<i>Buyurtmalarda saqlangan summa; yuqoridagi mahsulotlar jamiga qo'shilmagan.</i>")
    return lines


def _report_blocks(days: int, period: dict, rows: list[dict],
                   postage_orders: list[dict] | None = None) -> list[str]:
    """One period's full report: every product and set sold, most money first."""
    sold = sorted((r for r in rows if r.get("kind") in ("product", "set") and r.get("qty", 0) > 0),
                  key=lambda r: (-r["revenue"], r["name"]))
    start = datetime.fromisoformat(period["start"]).strftime("%d.%m")
    end = datetime.fromisoformat(period["end"]).strftime("%d.%m")
    head = f"📦 <b>Barcha mahsulotlar — oxirgi {days} kun ({start}–{end})</b>"
    if not sold:
        return [head, "Bu davrda mahsulotlar sotilmagan.", *_postage_blocks(postage_orders)]
    lines = []
    for i, r in enumerate(sold, 1):
        b2b = f" (shundan B2B {_qty(r['b2b_qty'])})" if r.get("b2b_qty") else ""
        kind = " (to'plam)" if r.get("kind") == "set" else ""
        lines.append(
            f"{i}. <b>{html.escape(r['name'], quote=False)}</b>{kind}\n"
            f"   Soni: {_qty(r['qty'])}{b2b} × ~{_som(r['revenue'] / r['qty'])} = "
            f"<b>{_som(r['revenue'])}</b> so'm")
    total = sum(r["revenue"] for r in sold)
    tail = (f"<b>Jami: {len(sold)} xil · {_som(total)} so'm</b>\n"
            "<i>Buyurtma yaratilgan sana bo'yicha, bekor qilinganlar va sovg'alar kirmaydi. "
            "Narx — o'rtacha (summa ÷ soni, B2B ham ichida).</i>")
    return [head, *lines, tail, *_postage_blocks(postage_orders)]


def report_text(days: int, period: dict, rows: list[dict],
                postage_orders: list[dict] | None = None) -> str:
    return "\n\n".join(_report_blocks(days, period, rows, postage_orders))


def _text_len(text: str) -> int:
    # Count UTF-16 units conservatively, including HTML markup.
    return len(text.encode("utf-16-le")) // 2


def report_messages(days: int, period: dict, rows: list[dict],
                    postage_orders: list[dict] | None = None) -> list[str]:
    """Split at product boundaries; keep every row, the total and valid HTML."""
    head, *body = _report_blocks(days, period, rows, postage_orders)
    prefix = head + "\n\n"
    budget = MAX_CHARS - _text_len(prefix)
    blocks = []
    for block in body:
        if _text_len(block) <= budget:
            blocks.append(block)
            continue
        # An unusually long product name must not break the entire report.
        # Drop only its formatting, splitting escaped characters safely.
        part = ""
        for char in strip_markup(block):
            escaped = html.escape(char, quote=False)
            if _text_len(part + escaped) > budget:
                blocks.append(part)
                part = ""
            part += escaped
        if part:
            blocks.append(part)
    out, current = [], prefix
    for block in blocks:
        separator = "\n\n" if current != prefix else ""
        if _text_len(current + separator + block) > MAX_CHARS:
            out.append(current)
            current, separator = prefix, ""
        current += separator + block
    out.append(current)
    return out


async def build_reports() -> list[str]:
    out = []
    today = _now_tk().date()
    for days in PERIODS:
        period = window(days, today)
        data = await database.get_product_sales(period)
        out.extend(report_messages(days, period, data.get("rows") or [], data.get("postage_orders")))
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
            logger.warning("Product sales report to admin %s failed: %s", admin_id, exc)
        await asyncio.sleep(0.05)
    logger.info("Product sales report %s: %d sent, %d failed", PUSH_KEY, sent, failed)
    return True


async def scheduler_loop(bot: Bot) -> None:
    while True:
        try:
            if await push_once(bot):
                return
        except Exception:
            logger.exception("Product sales report push failed")
        await asyncio.sleep(CHECK_EVERY)


@router.message(Command("mahsulot_savdosi", "banka"))
async def cmd_banka(message: Message):
    """Both command names show all products, for admins only."""
    if message.from_user.id not in ADMIN_IDS:
        return
    await _answer_reports(message)


@router.callback_query(F.data == "admin:product_sales")
async def show_product_sales(callback: CallbackQuery):
    await callback.answer()
    if callback.from_user.id not in ADMIN_IDS:
        return
    await _answer_reports(callback.message)


async def _answer_reports(message: Message):
    try:
        texts = await build_reports()
    except Exception:
        logger.exception("Product sales report failed")
        await message.answer("⚠️ Statistikani hisoblab bo'lmadi, birozdan keyin qayta urinib ko'ring.")
        return
    for text in texts:
        await message.answer(text, parse_mode=ParseMode.HTML)
