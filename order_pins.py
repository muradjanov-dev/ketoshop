"""
Yangi (tasdiqlanmagan) buyurtmalar adminlar chatida pin qilinadi.

Egasi, 2026-11-11: "yangi tushgan buyurtmalarni va hali tasdiqlanmaganlarni
adminlar uchun pinned qil, u tasdiqlanishi bilan, pindan olib tashla, pinda
faqat yangi buyurtmalar tursin".

  * Yangi buyurtma kartochkasi (handlers/cart._notify_sellers) har adminda
    pin qilinadi — tepadagi pin bosilsa, «Qabul qilish» tugmali kartochkaga
    olib boradi.
  * Buyurtma 'pending'dan chiqishi bilan (tasdiqlandi, bekor qilindi,
    o'chirildi …) pin olinadi: order_admin_feed.status_changed / deleted
    darhol chaqiradi; holat boshqa yo'l bilan o'zgarsa ham har CHECK_EVERY
    soniyada tekshiruv qoldiqlarni tozalaydi.
  * Shu o'zgarish chiqqanda allaqachon kutib turgan buyurtmalar uchun bir
    marta kartochka yuborilib, pin qilinadi.

Faqat shu modul pin qilgan xabarlar olinadi — admin o'zi pin qilgan boshqa
narsalarga tegilmaydi.
"""
import asyncio
import logging

from aiogram import Bot

import database
from config import ADMIN_IDS

logger = logging.getLogger(__name__)

CHECK_EVERY = 60
INITIAL_KEY = "order_pins_waiting_2026_11_11"
_tasks: set = set()


def _spawn(coro) -> None:
    try:
        task = asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def pin(bot: Bot, order_id: int, chat_id: int, message_id: int) -> bool:
    try:
        await bot.pin_chat_message(chat_id, message_id, disable_notification=True)
    except Exception as exc:
        logger.info("order #%s pin in %s failed: %s", order_id, chat_id, exc)
        return False
    await database.add_order_pin(order_id, chat_id, message_id)
    return True


async def release(bot: Bot, order_id: int) -> int:
    """Shu buyurtmaning hamma pinlarini olib tashlaydi."""
    rows = await database.take_order_pins(order_id)
    for r in rows:
        try:
            await bot.unpin_chat_message(r["chat_id"], message_id=r["message_id"])
        except Exception as exc:
            logger.info("order #%s unpin in %s failed: %s", order_id, r["chat_id"], exc)
    return len(rows)


def status_changed(bot: Bot | None, order_id: int, new_status: str | None) -> None:
    """order_admin_feed chaqiradi: buyurtma 'pending'dan chiqdi — pin olinadi."""
    if bot is None or new_status == "pending":
        return
    _spawn(release(bot, order_id))


async def reconcile(bot: Bot) -> int:
    """Holati endi 'pending' bo'lmagan (yoki o'chirilgan) buyurtmalarning pinlari."""
    done = 0
    for order_id in await database.order_pins_to_release():
        done += await release(bot, order_id)
    return done


async def pin_waiting_once(bot: Bot) -> int:
    """Shu o'zgarishgacha kelib, hali tasdiqlanmagan buyurtmalar — bir marta."""
    if not await database.claim_release_notes(INITIAL_KEY):
        return 0
    import order_admin_feed
    from keyboards import seller_order_keyboard
    pinned = 0
    for order in await database.pending_orders_without_pins():
        for admin_id in ADMIN_IDS:
            try:
                lang = await database.get_user_language(admin_id)
                text = order_admin_feed.build_card(order, lang, title="waiting_title", by="")
                kb = seller_order_keyboard(lang, order["id"], "pending", is_admin=True,
                                           source=order.get("source"))
                msg = await bot.send_message(admin_id, text, reply_markup=kb, parse_mode="HTML",
                                             disable_web_page_preview=True)
            except Exception as exc:
                logger.info("waiting order #%s → %s failed: %s", order["id"], admin_id, exc)
                continue
            pinned += await pin(bot, order["id"], admin_id, msg.message_id)
    return pinned


async def loop(bot: Bot) -> None:
    await asyncio.sleep(20)
    try:
        n = await pin_waiting_once(bot)
        if n:
            logger.info("order pins: %d waiting-order card(s) pinned", n)
    except Exception:
        logger.exception("pinning waiting orders failed")
    while True:
        try:
            await reconcile(bot)
        except Exception:
            logger.exception("order pins reconcile failed")
        await asyncio.sleep(CHECK_EVERY)
