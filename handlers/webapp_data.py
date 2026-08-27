"""
Handler for web_app_data messages from the Telegram Mini App
"""
import json
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from database import get_cart, get_user_language
from locales import get_text
from keyboards import main_menu_keyboard
from config import ADMIN_IDS

router = Router()


@router.message(F.web_app_data)
async def handle_webapp_data(message: Message, state: FSMContext):
    """Handle data sent from the WebApp via tg.sendData()."""
    try:
        data = json.loads(message.web_app_data.data)
    except (json.JSONDecodeError, AttributeError):
        return

    action = data.get("action")
    user_id = message.from_user.id
    lang = await get_user_language(user_id)

    if action == "checkout":
        # Verify cart has items
        cart_items = await get_cart(user_id)
        if not cart_items:
            await message.answer(
                get_text("cart_empty", lang),
                reply_markup=main_menu_keyboard(lang, is_admin=user_id in ADMIN_IDS),
                parse_mode="HTML"
            )
            return

        # Start checkout FSM — ask for name
        from handlers.cart import CheckoutStates
        await state.set_state(CheckoutStates.waiting_name)
        await state.update_data(lang=lang)
        await message.answer(get_text("enter_name", lang))
