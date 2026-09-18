"""Kuryer xarajati — the courier fee Ketoshop pays out of its own pocket on
every delivered order, booked into Chiqimlar automatically (2026-09-18).

Two fees, owner's rule:

    self       25 000 so'm — Ketoshop's own courier inside Tashkent
    bts / emu   5 000 so'm — handing a regional parcel to the post office

What the *buyer* pays for delivery is a separate thing and already sits in
the order total. These are the amounts that leave the till, so they are
booked even when the buyer got free delivery (800 000 so'm and up) — the
courier is paid either way. The two happen to be 25 000 today; they are
separate constants because they are separate numbers. Yandex Taxi is not in
the table on purpose: the buyer pays that ride directly.

Booked on **delivered**, not on shipped, for two reasons: a cancelled order
never reaches it, so nothing has to be un-booked, and every profit figure in
the shop is already computed on delivered orders — booking earlier would put
a cost in a period that has no revenue to match it.

Like gift_campaign, the sweep reconciles from the orders table instead of
hooking into each "delivered" code path (admin bot, courier board, seller
panel and web panel all set that status), so a path added later can't be
missed. One expenses row per order, guarded by a unique index, which is what
makes running the sweep every few minutes safe.
"""
import asyncio
import logging
import os
from datetime import datetime

from aiogram import Bot

import database

logger = logging.getLogger(__name__)

# so'm paid per delivered order, by delivery_method
COURIER_COST = {
    "self": 25_000,     # Tashkent — Ketoshop's own courier
    "bts":  5_000,      # regional parcel handed to the post office
    "emu":  5_000,
}

# Human label per method, for the Chiqimlar row.
_LABEL = {
    "self": "Toshkent kuryeri",
    "bts":  "BTS pochtaga eltish",
    "emu":  "EMU pochtaga eltish",
}

# Only orders delivered from here on are booked. An expenses row is stamped
# with the time it is written, not the time of the order, so sweeping the
# whole archive would dump years of courier fees onto a single day and make
# that day's profit look catastrophic. Owner's call (2026-09-18): start now,
# and if the past is ever wanted, backfill it deliberately with a script.
# Override with DELIVERY_COST_FROM=YYYY-MM-DDTHH:MM:SS (UTC).
_DEFAULT_START = "2026-09-18T17:00:00"


def _start_from() -> datetime:
    raw = (os.getenv("DELIVERY_COST_FROM") or _DEFAULT_START).strip()
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        logger.warning("DELIVERY_COST_FROM noto'g'ri (%r) — %s ishlatildi", raw, _DEFAULT_START)
        return datetime.fromisoformat(_DEFAULT_START)


CHECK_EVERY = 600          # seconds between sweeps
_BATCH = 200               # orders reconciled per sweep


def fee_for(delivery_method: str | None) -> int:
    """The fee this delivery method costs Ketoshop, or 0 if it costs nothing."""
    return COURIER_COST.get(delivery_method or "", 0)


async def book_delivered_courier_costs() -> tuple[int, float]:
    """Book every delivered order that still owes a courier fee.

    Returns (rows booked, so'm booked). Safe to call as often as you like —
    an order already booked is skipped by the unique index.
    """
    orders = await database.get_unbooked_delivery_orders(
        list(COURIER_COST), _start_from(), _BATCH)
    if not orders:
        return 0, 0.0

    booked, total = 0, 0.0
    for o in orders:
        method = o.get("delivery_method")
        amount = fee_for(method)
        if amount <= 0:                       # method dropped from the table
            continue
        name = f"🚚 Kuryer: {_LABEL.get(method, method)} — buyurtma #{o['id']}"
        if await database.book_delivery_expense(int(o["id"]), name, amount):
            booked += 1
            total += amount
    if booked:
        logger.info("Kuryer xarajati: %d ta buyurtma, %d so'm", booked, int(total))
    return booked, total


# ─────────────────────────────── scheduler ──────────────────────────────────

async def scheduler_loop(bot: Bot) -> None:
    """Sweep every CHECK_EVERY seconds. Quiet by design — the rows show up in
    Chiqimlar, and an admin ping every ten minutes would be noise."""
    while True:
        try:
            await book_delivered_courier_costs()
        except Exception:
            logger.exception("Kuryer xarajati hisobi ishlamadi")
        await asyncio.sleep(CHECK_EVERY)
