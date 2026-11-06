"""
Yarim qadoq — one message to every admin about orders that came in with half
packs (owner, 2026-11-06: "yarim kgni yarmini hisoblayapti degan shikoyatlar
keldi find error and fix everywhere").

The shop sells whole packs only: «Bodom uni 500gr» is kept with unit "kg" but
its price is for one 500 g pack. The AI seller read that as "0.5 kg" and
quoted and carted 0.5 of it at half price, and the bot's quantity buttons
offered "0.5" for dona/litr/banka goods. Both are fixed (whole packs only, and
database._put_cart_line rounds any fraction up). Orders already placed keep
their half packs, so the admins get the list once: open ones to correct before
they ship, finished ones for the record.

Read-only: nothing in an order is changed here.
"""
import asyncio
import html
import json
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.enums import ParseMode

import database
from config import ADMIN_IDS

logger = logging.getLogger(__name__)

KEY = "2026-11-06-yarim-qadoq-buyurtmalar"
DAYS = 30
TZ_OFFSET = timedelta(hours=5)
SEND_WINDOW = (8, 22)          # admins are not woken up at night
CHECK_EVERY = 300
MAX_LISTED = 25


def _fmt(n) -> str:
    return f"{int(round(float(n or 0))):,}".replace(",", " ")


def _qty(q) -> str:
    return f"{float(q):g}"


def half_pack_lines(items) -> list[dict]:
    """Retail lines whose quantity is not a whole number of packs. A wholesale
    line (`bulk`) is a real weight and stays out, so do free gifts."""
    out = []
    for item in items or []:
        if item.get("bulk") or item.get("is_bonus") or item.get("is_gift"):
            continue
        try:
            qty = float(item.get("quantity") or 0)
        except (TypeError, ValueError):
            continue
        if qty > 0 and not qty.is_integer():
            out.append(item)
    return out


async def find_orders(days: int = DAYS) -> tuple[list[dict], list[dict]]:
    """(open orders, finished orders) from the last `days` days with half packs."""
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, status, items, total FROM orders
                WHERE created_at > (NOW() AT TIME ZONE 'UTC') - ($1 || ' days')::interval
                  AND COALESCE(source, 'bot') NOT IN ('manual', 'b2b')
                ORDER BY id""",
            str(int(days)),
        )
    open_orders, finished = [], []
    for row in rows:
        try:
            items = json.loads(row["items"]) if isinstance(row["items"], str) else row["items"]
        except ValueError:
            continue
        lines = half_pack_lines(items)
        if not lines:
            continue
        entry = {"id": row["id"], "status": row["status"], "total": row["total"], "lines": lines}
        (finished if row["status"] in ("delivered", "cancelled") else open_orders).append(entry)
    return open_orders, finished


def report_text(open_orders: list[dict], finished: list[dict]) -> str:
    parts = ["⚠️ <b>Yarim qadoq bilan tushgan buyurtmalar</b>",
             "AI sotuvchi 500 g li qadoqni «0.5 kg» deb hisoblagan, botda ham dona/litr "
             "mahsulotlarga «0.5» tugmasi bor edi — narx yarmi bo'lib chiqqan. Tuzatildi: endi faqat "
             "butun qadoq."]
    if open_orders:
        parts += ["", "<b>Ochiq buyurtmalar — yuborishdan oldin miqdorni to'g'rilang:</b>"]
        for order in open_orders[:MAX_LISTED]:
            for line in order["lines"]:
                price = float(line.get("price") or 0)
                parts.append(f"• #{order['id']} — {html.escape(str(line.get('name') or '?'))} × "
                             f"{_qty(line.get('quantity'))} = {_fmt(price * float(line['quantity']))} so'm "
                             f"(1 qadoq: {_fmt(price)} so'm)")
        if len(open_orders) > MAX_LISTED:
            parts.append(f"… va yana {len(open_orders) - MAX_LISTED} ta buyurtma")
    else:
        parts += ["", "✅ Ochiq buyurtmalarda yarim qadoq yo'q."]
    if finished:
        ids = ", ".join(f"#{o['id']}" for o in finished[:40])
        parts += ["", f"Oxirgi {DAYS} kunda yakunlangan ({len(finished)} ta): {ids}"]
    return "\n".join(parts)


async def run_once(bot: Bot) -> bool:
    """Send the report if there is anything to report. True = done for good."""
    open_orders, finished = await find_orders()
    logger.info("Half-pack audit: %d open, %d finished orders", len(open_orders), len(finished))
    if not await database.claim_release_notes(KEY):
        return True
    if not open_orders and not finished:
        return True
    text = report_text(open_orders, finished)
    for admin_id in list(dict.fromkeys(ADMIN_IDS)):
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception as exc:
            logger.warning("Half-pack report to admin %s failed: %s", admin_id, exc)
        await asyncio.sleep(0.05)
    return True


async def scheduler_loop(bot: Bot) -> None:
    while True:
        try:
            hour = (datetime.utcnow() + TZ_OFFSET).hour
            if SEND_WINDOW[0] <= hour < SEND_WINDOW[1] and await run_once(bot):
                return
        except Exception:
            logger.exception("Half-pack audit failed")
        await asyncio.sleep(CHECK_EVERY)
