"""
Admin panel → «📣 Reklama va havolalar» (owner, 2026-11-08: "/reklama bunday
yozishni bilmaydiganlar uchun admin panelda tushunarli qilib tugmalar ham
qo'sh"). Every ad and tracked-link command is a button here; the reports
come from the same functions the commands use, so both always agree.

  adm_ads:holat     /reklama_holat          (meta_ads.status_texts)
  adm_ads:bog       /reklama_bog            (ad_campaigns.links_text)
  adm_ads:newlink   /sayt_havola <nom>      — asks for the name
  adm_ads:leads     /leads                  (meta_leads.recent_text)
  adm_ads:token     /reklama_token          — status; «Tokenni yuborish»
                                              takes the token as a message
                                              and deletes it at once
  ads:* / shoplnk:* / adsrc:* are handled where they always were.
"""
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router()

BACK = InlineKeyboardMarkup(inline_keyboard=[[
    InlineKeyboardButton(text="🔙 Reklama menyusi", callback_data="admin_menu:ads")]])


class AdsMenuStates(StatesGroup):
    link_name = State()
    token = State()


def _cancel_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✖️ Bekor qilish", callback_data="adm_ads:cancel")]])


@router.callback_query(F.data.startswith("adm_ads:"))
async def cb_menu(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Faqat adminlar uchun", show_alert=True)
        return
    action = callback.data.split(":", 1)[1]
    msg = callback.message

    if action == "cancel":
        await state.clear()
        await callback.answer("Bekor qilindi")
        await msg.answer("Bekor qilindi.", reply_markup=BACK)
        return

    if action == "newlink":
        await state.set_state(AdsMenuStates.link_name)
        await callback.answer()
        await msg.answer("➕ <b>Yangi havola</b>\n\nHavola nomini yozing — masalan: <code>Chia urug'i</code>.\n"
                         "Har bir reklamaga alohida nom bering, shunda kim qaysi reklamadan kelgani ko'rinadi.",
                         parse_mode="HTML", reply_markup=_cancel_kb())
        return

    if action == "token_send":
        await state.set_state(AdsMenuStates.token)
        await callback.answer()
        await msg.answer("🔑 Meta tokenini shu yerga yuboring (EAA… bilan boshlanadi).\n"
                         "Xabaringiz darhol o'chiriladi — token chatda qolmaydi.", reply_markup=_cancel_kb())
        return

    await callback.answer("Yuklanmoqda…")
    try:
        if action == "holat":
            import meta_ads
            if not meta_ads.is_enabled():
                await meta_ads.load_token()
            if not meta_ads.is_enabled():
                await msg.answer(meta_ads.NO_TOKEN_TEXT, parse_mode="HTML", reply_markup=BACK)
                return
            texts = await meta_ads.status_texts()
            for i, text in enumerate(texts):
                await msg.answer(text, parse_mode="HTML", reply_markup=BACK if i == len(texts) - 1 else None)
        elif action == "bog":
            import ad_campaigns
            await msg.answer(await ad_campaigns.links_text(), parse_mode="HTML", reply_markup=BACK)
        elif action == "leads":
            import meta_leads
            await msg.answer(await meta_leads.recent_text(), parse_mode="HTML", reply_markup=BACK)
        elif action == "token":
            import meta_ads
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔑 Tokenni yuborish / almashtirish", callback_data="adm_ads:token_send")],
                [InlineKeyboardButton(text="🔙 Reklama menyusi", callback_data="admin_menu:ads")]])
            await msg.answer(await meta_ads.token_status_text(), parse_mode="HTML", reply_markup=kb)
    except Exception:
        logger.exception("Ads menu action %s failed", action)
        await msg.answer("❌ Hozir olib bo'lmadi — birozdan keyin qayta urinib ko'ring.", reply_markup=BACK)


@router.message(AdsMenuStates.link_name, F.text)
async def got_link_name(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    import shop_links
    name = (message.text or "").strip()
    try:
        made = await shop_links.create(name, message.from_user.id)
    except Exception:
        logger.exception("Shop link from the menu failed")
        await message.answer("❌ Havola saqlanmadi — birozdan keyin qayta urinib ko'ring.", reply_markup=BACK)
        await state.clear()
        return
    if not made:
        await message.answer("❌ Bu nomdan havola chiqmadi — harf yoki raqam bilan boshqa nom yozing.",
                             reply_markup=_cancel_kb())
        return
    await state.clear()
    await message.answer(shop_links.made_text(made), parse_mode="HTML", reply_markup=BACK,
                         disable_web_page_preview=True)


@router.message(AdsMenuStates.token, F.text, F.chat.type == "private")
async def got_token(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    await state.clear()
    import meta_ads
    # Checks it with Meta, saves it and deletes this message — same as /reklama_token.
    await meta_ads.apply_token(message, (message.text or "").strip())
