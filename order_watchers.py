"""
Buyurtma kuzatuvchilari — the one-off test for a new order watcher.

An order watcher (config.ORDER_WATCHER_IDS) gets only the new-order card and
every order status card (order_admin_feed). When one is added the owner wants
them to see the cards straight away (2026-11-06: "test uchun hali yetkazib
berilmagan barcha buyurtmalarni shunga jo'natib qo'y"), so each watcher gets
every undelivered order once — claimed in release_notes_sent, so restarts
can't repeat it.

Telegram refuses to message someone who never pressed START, so a refused
send releases the claim and the loop tries again every few minutes for a
few days. The admins get one line when it went through.
"""
import asyncio
import logging

from aiogram import Bot

import database
import order_admin_feed
from config import ADMIN_IDS, ORDER_WATCHER_IDS

logger = logging.getLogger(__name__)

RETRY_EVERY = 600          # seconds
ATTEMPTS = 6 * 24 * 3      # ~3 days of tries for someone who hasn't pressed START yet


def _key(user_id: int) -> str:
    return f"order-watch-open-orders:{user_id}"


async def _try(bot: Bot, user_id: int) -> bool:
    """True when this watcher is done (sent now or earlier)."""
    key = _key(user_id)
    if not await database.claim_release_notes(key):
        return True
    try:
        sent, total = await order_admin_feed.send_open_orders(bot, user_id)
    except Exception as exc:
        await database.release_release_notes(key)
        logger.info("Order watcher %s not reachable yet: %s", user_id, exc)
        return False
    logger.info("Order watcher %s: %s/%s open orders sent", user_id, sent, total)
    text = (f"📦 Buyurtma kuzatuvchisi <code>{user_id}</code> ulandi: test uchun "
            f"{sent} / {total} ta yetkazilmagan buyurtma yuborildi. Endi unga faqat yangi "
            f"buyurtmalar va holat o'zgarishlari boradi.")
    for admin_id in list(dict.fromkeys(ADMIN_IDS)):
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception:
            pass
    return True


async def scheduler_loop(bot: Bot) -> None:
    pending = [w for w in ORDER_WATCHER_IDS if w not in ADMIN_IDS]
    for _ in range(ATTEMPTS):
        if not pending:
            return
        still = []
        for user_id in pending:
            try:
                if not await _try(bot, user_id):
                    still.append(user_id)
            except Exception:
                logger.exception("Order watcher %s test send failed", user_id)
                still.append(user_id)
        pending = still
        if pending:
            await asyncio.sleep(RETRY_EVERY)
