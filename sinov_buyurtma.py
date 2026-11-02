"""
🧪 Test buyurtma (owner, 2026-11-02: "test uchun bitta yo'lda bo'lgan
toshkentdagi istalgan lokatsiyaga buyurtma yaratib ber, faqat uni tushumlarga
qo'shma — kartasiga bosib sinab ko'rmoqchiman").

/test_buyurtma (admins only), the «🧪 Test buyurtma» button on the admin
site's Kuryer tab, and a one-off at the first startup (ensure_once) put ONE
order on the courier board:
  • status «Yo'lda» (shipped), Ketoshop courier, a pin on Amir Temur xiyoboni
    in Tashkent — so its 🧭 / map can be tried from the courier panel;
  • source 'test', no items, total 0 — the shop's money figures sum totals,
    so it adds nothing to revenue, and no stock moves;
  • the admin who asked is its "buyer", so any status message lands in
    their own chat, never a customer's;
  • written straight into the table — no new-order alerts, no gift, no
    buyer notice;
  • it can never become «Yetkazildi» (courier_board.move_order and the bot's
    order card refuse — see is_test), because delivery books the courier
    expense, Keto and cashback;
  • «🗑 O'chirish» deletes it for good; a new /test_buyurtma first removes
    any earlier test order, so there is only ever one.
"""
import html
import json
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import database
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router()

SOURCE = "test"
LAT, LON = 41.311151, 69.279737          # Amir Temur xiyoboni, Toshkent
PLACE = "Amir Temur xiyoboni (TEST)"
NAME = "🧪 TEST — sinov buyurtma"
NOTE = "Sinov buyurtma — yetkazilmaydi. Sinovdan keyin o'chiring."
NO_DELIVERY = ("🧪 Bu test buyurtma — «Yetkazildi» qilinmaydi. Sinovdan keyin o'chiring "
               "(saytda buyurtma ichidagi «🗑» yoki /test_buyurtma xabaridagi tugma).")
# One automatic test order after the deploy (owner, 2026-11-02, looking at an
# empty «Yo'lda» column on the admin site: "qara hechnima yo'q") — the card
# just appears, nobody has to send a command first.
ONCE_KEY = "test-buyurtma-2026-11-02"


def is_test(order: dict | None) -> bool:
    return bool(order) and (order.get("source") or "") == SOURCE


async def pick_buyer() -> int | None:
    """An admin account the bot knows — orders.user_id is a foreign key to
    users. Used when no one in particular asked (the admin site, the one-off)."""
    async with database.pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT user_id FROM users WHERE user_id = ANY($1::bigint[]) ORDER BY user_id LIMIT 1",
            [int(i) for i in ADMIN_IDS])


async def delete_all() -> list[int]:
    """Every test order, gone for good. Returns their ids."""
    async with database.pool.acquire() as conn:
        old = [r["id"] for r in await conn.fetch("SELECT id FROM orders WHERE source = $1", SOURCE)]
    for oid in old:
        await database.delete_order_permanently(oid)
    return old


async def create(admin_id: int) -> tuple[int, list[int]]:
    """Remove earlier test orders, insert a fresh one. Returns (id, removed ids)."""
    old = await delete_all()
    async with database.pool.acquire() as conn:
        order_id = await conn.fetchval(
            """INSERT INTO orders (user_id, seller_id, customer_name, phone, address, items, total,
                                   payment_method, latitude, longitude, delivery_method, address_note,
                                   status, source, confirmed_at, ready_at, shipped_at)
               VALUES ($1, NULL, $2, NULL, $3, $4, 0, 'cash', $5, $6, 'self', $7,
                       'shipped', $8, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
               RETURNING id""",
            admin_id, NAME, f"{LAT:.6f}, {LON:.6f} — {PLACE}", json.dumps([]),
            LAT, LON, NOTE, SOURCE,
        )
    return order_id, old


def _kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="🗑 Test buyurtmani o'chirish", callback_data=f"testord:del:{order_id}")]])


@router.message(Command("test_buyurtma"))
async def cmd_test_order(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        order_id, removed = await create(message.from_user.id)
    except Exception:
        logger.exception("test order: create failed")
        await message.answer("⚠️ Test buyurtmani yaratib bo'lmadi, birozdan keyin qayta urinib ko'ring.")
        return
    logger.info("Test order #%s created by admin %s (removed earlier: %s)",
                order_id, message.from_user.id, removed)
    await message.answer(_created_text(order_id, removed), parse_mode="HTML", reply_markup=_kb(order_id))


def _created_text(order_id: int, removed: list[int]) -> str:
    gone = f"\n♻️ Avvalgi test buyurtma o'chirildi: {', '.join('#' + str(i) for i in removed)}" if removed else ""
    return (
        f"🧪 <b>Test buyurtma #{order_id} yaratildi</b>\n\n"
        f"🚚 Holati: <b>Yo'lda</b> · Ketoshop kuryeri\n"
        f"📍 {html.escape(PLACE)}\n"
        f"💰 0 so'm, mahsulotsiz — <b>tushumga qo'shilmaydi</b>, ombor o'zgarmaydi.\n\n"
        f"Kuryer panelida «🚚 Tayyor + Yo'lda» ustunida turibdi: kartasidagi «🧭 Yo'l», "
        f"kichik xarita yoki «🗺 Xarita» → «🧭 Yandex'da yo'lga chiqish» ni bosib sinang.\n\n"
        f"⚠️ Uni «Yetkazildi» qilib bo'lmaydi. Sinovdan keyin pastdagi tugma bilan o'chiring."
        f"{gone}"
    )


async def ensure_once(bot) -> None:
    """Startup, once per ONCE_KEY: put the test order on the board and tell
    the admin it is filed under, with the 🗑 button."""
    try:
        if not await database.claim_release_notes(ONCE_KEY):
            return
        buyer = await pick_buyer()
        if not buyer:
            logger.warning("test order: no admin account in users — one-off skipped")
            return
        order_id, removed = await create(buyer)
        logger.info("Test order #%s created at startup for admin %s", order_id, buyer)
        try:
            await bot.send_message(buyer, _created_text(order_id, removed),
                                   parse_mode="HTML", reply_markup=_kb(order_id))
        except Exception:
            logger.warning("test order: notice to admin %s failed", buyer, exc_info=True)
    except Exception:
        logger.exception("test order: one-off create failed")


@router.callback_query(F.data.regexp(r"^testord:del:\d+$"))
async def delete_test_order(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌", show_alert=True)
        return
    order_id = int(callback.data.split(":")[2])
    order = await database.get_order(order_id)
    if order is None:
        await callback.answer("Allaqachon o'chirilgan ✅")
    elif not is_test(order):
        # Never a real order through this button.
        await callback.answer("❌ Bu test buyurtma emas", show_alert=True)
        return
    else:
        await database.delete_order_permanently(order_id)
        await callback.answer("🗑 O'chirildi")
    try:
        await callback.message.edit_text(f"🧪 Test buyurtma #{order_id} o'chirildi ✅")
    except Exception:
        pass
