"""
Delivery terms (buyer-facing) and per-zone info popup.
Admin-side zone editing lives in handlers/admin.py.
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery

from config import SUPPORT_USERNAME
from database import get_user_language, get_delivery_zone
from locales import get_text
from keyboards import back_to_menu_keyboard

router = Router()


@router.callback_query(F.data == "delivery_zones")
async def show_delivery_terms(callback: CallbackQuery):
    """Show buyer-facing delivery terms (replaces the old city list).
    Callback name kept as `delivery_zones` so old inline buttons in users'
    chat history still resolve."""
    lang = await get_user_language(callback.from_user.id)
    await callback.message.edit_text(
        get_text("delivery_terms", lang, support_username=SUPPORT_USERNAME),
        reply_markup=back_to_menu_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("zone_info:"))
async def show_zone_info(callback: CallbackQuery):
    """Show specific zone info"""
    zone_id = int(callback.data.split(":")[1])
    lang = await get_user_language(callback.from_user.id)
    zone = await get_delivery_zone(zone_id)

    if not zone:
        await callback.answer("❌")
        return

    city = zone["city_name_uz"] if lang == "uz" else zone["city_name_ru"]
    price_str = f"{int(zone['price']):,}".replace(",", " ")
    min_free_str = f"{int(zone['min_free_delivery']):,}".replace(",", " ")

    text = get_text("delivery_zone_item", lang,
        city=city,
        price=price_str,
        min_free=min_free_str,
        days=zone["estimated_days"],
    )

    await callback.answer(f"📍 {city} — {price_str} so'm", show_alert=True)
