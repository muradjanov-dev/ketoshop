import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext

import database
from config import ADMIN_IDS

router = Router()
logger = logging.getLogger(__name__)

async def is_courier(user_id: int) -> bool:
    couriers = await database.get_courier_ids()
    return user_id in couriers or user_id in ADMIN_IDS

def get_courier_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Yangi buyurtmalar", callback_data="courier:new_orders")],
        [InlineKeyboardButton(text="🚚 Mening buyurtmalarim", callback_data="courier:my_orders")]
    ])

@router.message(Command("addcourier"), F.chat.type == "private")
async def cmd_add_courier(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Format: /addcourier [user_id]")
        return
        
    courier_id = int(parts[1])
    await database.add_courier_db(courier_id, message.from_user.id)
    await message.answer(f"✅ Kuryer qo'shildi: {courier_id}")

@router.message(Command("rmcourier"), F.chat.type == "private")
async def cmd_rm_courier(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Format: /rmcourier [user_id]")
        return
        
    courier_id = int(parts[1])
    await database.remove_courier_db(courier_id)
    await message.answer(f"❌ Kuryer o'chirildi: {courier_id}")

@router.message(Command("courier"), F.chat.type == "private")
async def cmd_courier(message: Message, state: FSMContext):
    if not await is_courier(message.from_user.id):
        return
    
    lang = await database.get_user_language(message.from_user.id)
    await message.answer(
        "📦 <b>Kuryer paneli</b>\n\nQuyidagi menyudan kerakli bo'limni tanlang:",
        reply_markup=get_courier_keyboard(lang),
        parse_mode="HTML"
    )

@router.callback_query(F.data.startswith("courier:"))
async def courier_callback_handler(callback: CallbackQuery, bot: Bot):
    if not await is_courier(callback.from_user.id):
        await callback.answer("Ruxsat yo'q", show_alert=True)
        return
        
    parts = callback.data.split(":")
    action = parts[1]
    
    lang = await database.get_user_language(callback.from_user.id)
    
    async def get_new_orders():
        async with database.pool.acquire() as conn:
            return await conn.fetch("SELECT * FROM orders WHERE status = 'confirmed' AND courier_id IS NULL ORDER BY created_at ASC")
            
    async def get_my_orders():
        async with database.pool.acquire() as conn:
            return await conn.fetch("SELECT * FROM orders WHERE courier_id = $1 AND status = 'delivering' ORDER BY created_at ASC", callback.from_user.id)
            
    def build_text(row, total_count, current_idx, title="Yangi buyurtma"):
        return (
            f"📦 <b>{title}</b> ({current_idx + 1}/{total_count})\n\n"
            f"🛒 <b>Buyurtma #{row['id']}</b>\n"
            f"👤 Ism: {row['customer_name']}\n"
            f"📞 Telefon: {row['phone']}\n"
            f"📍 Manzil: {row['address']}\n"
            f"💵 Summa: {row['total']:,.0f} so'm\n"
            f"🕒 Vaqt: {row['created_at'].strftime('%d.%m %H:%M')}\n"
        )
        
    def build_nav_kb(action_type, current_idx, total_count, row_id):
        kb = []
        
        # Action buttons
        if action_type == "new":
            kb.append([InlineKeyboardButton(text="✅ Olib ketish (Pick up)", callback_data=f"courier:pickup:{row_id}:{current_idx}")])
        elif action_type == "my":
            kb.append([
                InlineKeyboardButton(text="🏁 Yetkazildi", callback_data=f"courier:delivered:{row_id}:{current_idx}"),
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"courier:cancel:{row_id}:{current_idx}")
            ])
            
        # Pagination buttons
        nav_row = []
        if total_count > 1:
            prev_idx = (current_idx - 1) % total_count
            next_idx = (current_idx + 1) % total_count
            nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"courier:nav_{action_type}:{prev_idx}"))
            nav_row.append(InlineKeyboardButton(text=f"{current_idx + 1}/{total_count}", callback_data="ignore"))
            nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"courier:nav_{action_type}:{next_idx}"))
            kb.append(nav_row)
            
        kb.append([InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="courier:menu")])
        return InlineKeyboardMarkup(inline_keyboard=kb)

    # Main Menu
    if action == "menu":
        await callback.message.edit_text(
            "📦 <b>Kuryer paneli</b>\n\nQuyidagi menyudan kerakli bo'limni tanlang:",
            reply_markup=get_courier_keyboard(lang),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    # Entry points
    if action in ("new_orders", "my_orders"):
        action_type = "new" if action == "new_orders" else "my"
        orders = await get_new_orders() if action_type == "new" else await get_my_orders()
        
        if not orders:
            await callback.answer("Hozircha buyurtmalar yo'q.", show_alert=True)
            return
            
        text = build_text(orders[0], len(orders), 0, "Yangi buyurtma" if action_type == "new" else "Mening buyurtmam")
        kb = build_nav_kb(action_type, 0, len(orders), orders[0]['id'])
        
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await callback.answer()
        return
        
    # Navigation
    if action in ("nav_new", "nav_my"):
        action_type = "new" if action == "nav_new" else "my"
        idx = int(parts[2])
        orders = await get_new_orders() if action_type == "new" else await get_my_orders()
        
        if not orders:
            await callback.message.edit_text("Buyurtmalar tugadi.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="courier:menu")]]))
            return
            
        if idx >= len(orders):
            idx = 0
            
        text = build_text(orders[idx], len(orders), idx, "Yangi buyurtma" if action_type == "new" else "Mening buyurtmam")
        kb = build_nav_kb(action_type, idx, len(orders), orders[idx]['id'])
        
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        await callback.answer()
        return

    # Actions: pickup
    if action == "pickup":
        order_id = int(parts[2])
        idx = int(parts[3])
        
        async with database.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM orders WHERE id = $1", order_id)
            if not row or row["courier_id"] is not None:
                await callback.answer("Bu buyurtma allaqachon boshqa kuryer tomonidan olingan yoki topilmadi!", show_alert=True)
            else:
                await conn.execute("UPDATE orders SET courier_id = $1, status = 'delivering' WHERE id = $2", callback.from_user.id, order_id)
                await callback.answer("Buyurtmani olib ketdingiz!", show_alert=True)
                # Notify user
                user_lang = await database.get_user_language(row["user_id"])
                try:
                    msg = f"🚚 Ваш заказ #{order_id} передан курьеру!" if user_lang == 'ru' else f"🚚 Buyurtmangiz #{order_id} kuryerga topshirildi!"
                    await bot.send_message(row["user_id"], msg)
                except Exception:
                    pass
        
        # Refresh the new orders list, staying at the same index (which now points to the next order)
        orders = await get_new_orders()
        if not orders:
            await callback.message.edit_text("Yangi buyurtmalar qolmadi.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="courier:menu")]]))
            return
            
        idx = min(idx, len(orders) - 1)
        text = build_text(orders[idx], len(orders), idx, "Yangi buyurtma")
        kb = build_nav_kb("new", idx, len(orders), orders[idx]['id'])
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        return

    # Actions: delivered / cancel
    if action in ("delivered", "cancel"):
        order_id = int(parts[2])
        idx = int(parts[3])
        
        async with database.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM orders WHERE id = $1 AND courier_id = $2", order_id, callback.from_user.id)
            if row:
                if action == "delivered":
                    await conn.execute("UPDATE orders SET status = 'delivered' WHERE id = $1", order_id)
                    await callback.answer("Yetkazib berildi!", show_alert=True)
                    user_lang = await database.get_user_language(row["user_id"])
                    try:
                        msg = f"✅ Ваш заказ #{order_id} доставлен!" if user_lang == 'ru' else f"✅ Buyurtmangiz #{order_id} yetkazib berildi!"
                        await bot.send_message(row["user_id"], msg)
                    except Exception:
                        pass
                else: # cancel
                    await conn.execute("UPDATE orders SET status = 'confirmed', courier_id = NULL WHERE id = $1", order_id)
                    await callback.answer("Buyurtma qaytarildi.", show_alert=True)
        
        # Refresh my orders list
        orders = await get_my_orders()
        if not orders:
            await callback.message.edit_text("Sizda boshqa yetkazilayotgan buyurtmalar qolmadi.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="courier:menu")]]))
            return
            
        idx = min(idx, len(orders) - 1)
        text = build_text(orders[idx], len(orders), idx, "Mening buyurtmam")
        kb = build_nav_kb("my", idx, len(orders), orders[idx]['id'])
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
        return

