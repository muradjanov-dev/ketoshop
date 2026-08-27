"""
Catch-all for free text typed straight into the bot chat, outside any menu
flow (owner complaint, 2026-08-12: some buyers treat the bot like a live
chat — typing questions instead of using the buttons — and used to get pure
silence back). Registered LAST in bot.py so every other router/FSM state
gets first crack at the message; this only fires once nothing else matched.

Relays the text to every admin with:
  1. a tap-to-DM link (buyer_contact_link, same helper the complaint flow
     uses) to reply outside the bot, and
  2. a "↩️ Javob berish" button so an admin can reply *through the bot*
     itself (owner follow-up request, same day) — whoever taps it first
     types a reply and it's sent to the buyer as a normal bot message.
"""
from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_IDS
from database import get_user_language
from locales import get_text
from keyboards import main_menu_keyboard

router = Router()


class SupportReplyStates(StatesGroup):
    waiting_text = State()


# (relay_freeform_text moved to bottom)


@router.callback_query(F.data.startswith("freereply:"))
async def start_freeform_reply(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer()
        return
    buyer_id = int(callback.data.split(":", 1)[1])
    await state.set_state(SupportReplyStates.waiting_text)
    await state.update_data(buyer_id=buyer_id)
    await callback.message.answer(f"✍️ Javobingizni yozing (buyer ID {buyer_id}):")
    await callback.answer()


@router.message(SupportReplyStates.waiting_text, F.text)
async def send_freeform_reply(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    buyer_id = data.get("buyer_id")
    await state.clear()
    if not buyer_id:
        return

    reply_text = (message.text or "").strip()
    if not reply_text:
        return

    buyer_lang = await get_user_language(buyer_id)
    try:
        await bot.send_message(
            buyer_id,
            get_text("freeform_reply_to_buyer", buyer_lang, text=reply_text),
            parse_mode="HTML",
        )
        await message.answer("✅ Yuborildi.")
    except Exception:
        await message.answer("⚠️ Yuborib bo'lmadi — foydalanuvchi botni bloklagan bo'lishi mumkin.")


@router.message(F.text)
async def relay_freeform_text(message: Message, bot: Bot):
    text = (message.text or "").strip()
    # Stray/mistyped commands aren't "chatting with the bot" — leave those alone.
    if not text or text.startswith("/"):
        return

    lang = await get_user_language(message.from_user.id)
    await message.answer(
        get_text("freeform_received", lang),
        reply_markup=main_menu_keyboard(lang),
    )

    from handlers.cart import buyer_contact_link
    buyer_id = message.from_user.id
    name = message.from_user.full_name or "—"
    contact = buyer_contact_link(buyer_id, message.from_user.username, name)

    reply_kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="↩️ Javob berish", callback_data=f"freereply:{buyer_id}"),
    ]])

    for admin_id in ADMIN_IDS:
        admin_lang = await get_user_language(admin_id)
        try:
            await bot.send_message(
                admin_id,
                get_text("freeform_from_buyer", admin_lang, name=name, contact=contact, text=text),
                parse_mode="HTML",
                reply_markup=reply_kb,
            )
        except Exception:
            pass
