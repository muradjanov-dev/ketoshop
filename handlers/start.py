"""
Start, language selection, main menu, and help handlers
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, CommandObject, Command
from aiogram.fsm.context import FSMContext

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from database import (
    create_user, get_user_language, update_user_language, get_user, is_user_banned,
    mark_kabinetim_intro_seen, was_menu_keyboard_sent, mark_menu_keyboard_sent,
)
from locales import get_text
from keyboards import (
    language_keyboard, main_menu_keyboard, back_to_menu_keyboard,
    persistent_menu_keyboard,
)
from config import ADMIN_IDS, SUPPORT_USERNAME

_LANG_LABELS = {
    "uz": "🇺🇿 O'zbek (Lotin)", "uz_cyr": "🇺🇿 Ўзбек (Кирилл)", "ru": "🇷🇺 Русский",
}

router = Router()


# Every localized label of the two persistent-keyboard buttons. Pressing one
# arrives as an ordinary text message, so the handlers below have to recognise
# the button by its text in whichever language the user picked.
_MENU_BTN_TEXTS = {get_text("btn_kb_menu", lg) for lg in ("uz", "uz_cyr", "ru")}
_CART_BTN_TEXTS = {get_text("btn_kb_cart", lg) for lg in ("uz", "uz_cyr", "ru")}


async def ensure_menu_keyboard(bot, user_id: int, lang: str) -> None:
    """Put the persistent 🏠/🛒 keyboard under this user's input box, once.

    Telegram keeps a reply keyboard until it's replaced, so this only needs to
    happen a single time per chat — users.menu_keyboard_sent records that it
    did. Best-effort: a failure here must never derail /start."""
    try:
        if await was_menu_keyboard_sent(user_id):
            return
        await bot.send_message(
            user_id,
            get_text("persistent_kb_hint", lang),
            reply_markup=persistent_menu_keyboard(lang),
            parse_mode="HTML",
        )
        await mark_menu_keyboard_sent(user_id)
    except Exception:
        pass


@router.message(F.text.in_(_MENU_BTN_TEXTS))
async def menu_button_pressed(message: Message, state: FSMContext):
    """🏠 Bosh menyu — the way home from anywhere, including out of a stuck
    "waiting for X" flow (same escape-hatch behaviour as the inline
    main_menu button, which is why this clears the FSM too)."""
    await state.clear()
    lang = await get_user_language(message.from_user.id)
    await message.answer(
        get_text("welcome", lang),
        reply_markup=main_menu_keyboard(lang, is_admin=message.from_user.id in ADMIN_IDS),
        parse_mode="HTML",
    )


@router.message(F.text.in_(_CART_BTN_TEXTS))
async def cart_button_pressed(message: Message, state: FSMContext):
    """🛒 Savat — jumps straight to the cart from any screen."""
    await state.clear()
    from handlers.cart import render_cart_message
    lang = await get_user_language(message.from_user.id)
    await render_cart_message(message, lang)


@router.message(Command("menu"))
async def cmd_menu(message: Message, state: FSMContext):
    """/menu — the same landing spot as /start, minus the language prompt.
    Registered in the bot's command list so typing "/" offers it."""
    await state.clear()
    lang = await get_user_language(message.from_user.id)
    await ensure_menu_keyboard(message.bot, message.from_user.id, lang)
    await message.answer(
        get_text("welcome", lang),
        reply_markup=main_menu_keyboard(lang, is_admin=message.from_user.id in ADMIN_IDS),
        parse_mode="HTML",
    )



@router.message(CommandStart(deep_link=True))
async def cmd_start_deep_link(message: Message, command: CommandObject):
    """/start ref<user_id> — someone opened a Keto musobaqasi share link."""
    import referral_contest
    referrer_id = referral_contest.parse_ref_payload(command.args)
    await _handle_start(message, referrer_id)


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Handle /start — show language selection"""
    await _handle_start(message, None)


async def _handle_start(message: Message, referrer_id: int | None):
    # Check if user is banned
    if await is_user_banned(message.from_user.id):
        lang = await get_user_language(message.from_user.id)
        await message.answer(get_text("you_are_banned", lang))
        return

    is_new = await ensure_registered(message.bot, message.from_user, referrer_id)
    # Returning users get the persistent keyboard here — many have been using
    # the bot since before it existed and have nothing under their input box.
    # A brand-new user is skipped on purpose: they're about to pick a language
    # one tap from now, and set_language sends it in that language instead, so
    # doing it here too would just mean the same explainer twice.
    if not is_new:
        lang = await get_user_language(message.from_user.id)
        await ensure_menu_keyboard(message.bot, message.from_user.id, lang)
    await message.answer(
        get_text("choose_language", "uz"),
        reply_markup=language_keyboard()
    )


async def ensure_registered(bot, tg_user, referrer_id: int | None = None) -> bool:
    """Create the user row if this is their very first contact with the bot,
    wiring up referral crediting + the owner's "who joined / who invited
    them" admin notification. Returns True if a new row was created.

    Shared by cmd_start (the normal path) and subscription_gate.py: a
    not-yet-channel-subscribed user's /start gets blocked by that middleware
    before this router ever sees it, so their referral payload would
    otherwise be silently lost — the gate calls this directly once they
    confirm subscription (see subscription_gate.py's CHECK_CALLBACK branch)."""
    user = await get_user(tg_user.id)
    if user:
        return False
    await create_user(
        user_id=tg_user.id,
        username=tg_user.username,
        full_name=tg_user.full_name,
        language="uz",
    )
    await _process_new_user(bot, tg_user, referrer_id)
    return True


async def _process_new_user(bot, tg_user, referrer_id: int | None) -> None:
    """Best-effort: referral crediting + the owner's "who joined / who
    invited them" notification must never block registration itself."""
    import referral_contest

    valid_referrer = None
    try:
        if referrer_id and referrer_id != tg_user.id:
            if await get_user(referrer_id):
                valid_referrer = referrer_id
    except Exception:
        pass

    try:
        await referral_contest.notify_admins_new_user(
            bot, tg_user.id, tg_user.username, tg_user.full_name, valid_referrer,
        )
    except Exception:
        pass

    if valid_referrer:
        try:
            await referral_contest.award_referral(valid_referrer, tg_user.id, bot)
        except Exception:
            pass


async def _resend_menu_keyboard(bot, user_id: int, lang: str) -> None:
    """Same as ensure_menu_keyboard but unconditional — used after a language
    switch, where the already-sent keyboard is now in the wrong language."""
    try:
        await bot.send_message(
            user_id,
            get_text("persistent_kb_hint", lang),
            reply_markup=persistent_menu_keyboard(lang),
            parse_mode="HTML",
        )
        await mark_menu_keyboard_sent(user_id)
    except Exception:
        pass


@router.callback_query(F.data.startswith("lang:"))
async def set_language(callback: CallbackQuery):
    """Set user language"""
    # Check if user is banned
    if await is_user_banned(callback.from_user.id):
        lang = callback.data.split(":")[1]
        await callback.message.edit_text(get_text("you_are_banned", lang))
        await callback.answer()
        return

    lang = callback.data.split(":")[1]
    await create_user(
        user_id=callback.from_user.id,
        username=callback.from_user.username,
        full_name=callback.from_user.full_name,
        language=lang
    )
    await update_user_language(callback.from_user.id, lang)
    is_admin = callback.from_user.id in ADMIN_IDS
    # Re-send in the language just chosen, so the persistent buttons aren't
    # left labelled in whatever the previous pick was.
    await _resend_menu_keyboard(callback.bot, callback.from_user.id, lang)
    await callback.message.edit_text(
        get_text("welcome", lang),
        reply_markup=main_menu_keyboard(lang, is_admin=is_admin),
        parse_mode="HTML"
    )
    await callback.answer(get_text("language_set", lang))


@router.callback_query(F.data == "change_lang")
async def change_language(callback: CallbackQuery):
    """Show language selection"""
    await callback.message.edit_text(
        get_text("choose_language", "uz"),
        reply_markup=language_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "main_menu")
async def show_main_menu(callback: CallbackQuery, state: FSMContext):
    """Show main menu — also the buyer's escape hatch out of any stuck
    "waiting for X" flow (owner complaint, 2026-08-12), so it always forgets
    whatever the bot was previously waiting for."""
    await state.clear()
    lang = await get_user_language(callback.from_user.id)
    is_admin = callback.from_user.id in ADMIN_IDS
    text = get_text("welcome", lang)
    keyboard = main_menu_keyboard(lang, is_admin=is_admin)

    if callback.message.photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


async def _send_or_edit(callback: CallbackQuery, text: str, keyboard) -> None:
    """A photo-message can't take edit_text (Telegram rejects it) — delete +
    resend instead. See ketoshop-photo-message-edit-bug memory."""
    if callback.message.photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        try:
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data == "kabinetim")
async def show_kabinetim(callback: CallbackQuery):
    """Personal-data hub: name/phone/language + Keto balance/level + link to
    order history — everything about "me" in one place (owner request,
    2026-07-26). First-ever visit shows a one-time explainer instead (owner
    request 2026-07-27), tracked via users.kabinetim_intro_seen."""
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    user = await get_user(user_id)

    if user and not user.get("kabinetim_intro_seen"):
        await mark_kabinetim_intro_seen(user_id)
        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=get_text("btn_kabinetim_intro_continue", lang), callback_data="kabinetim:go"),
        ]])
        await _send_or_edit(callback, get_text("kabinetim_intro", lang), keyboard)
        await callback.answer()
        return

    await _render_kabinetim(callback, user_id, lang, user)


@router.callback_query(F.data == "kabinetim:go")
async def kabinetim_after_intro(callback: CallbackQuery):
    """Continue button from the one-time intro screen."""
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    user = await get_user(user_id)
    await _render_kabinetim(callback, user_id, lang, user)


async def _render_kabinetim(callback: CallbackQuery, user_id: int, lang: str, user: dict) -> None:
    import gamification

    profile = await gamification.get_profile(user_id)

    level = profile["level"]
    next_level = profile["next_level"]
    level_label = level["label"]["ru"] if lang == "ru" else level["label"]["uz"]
    level_line = f"{level['emoji']} <b>{level_label}</b>"
    if next_level:
        remaining = next_level["threshold"] - profile["lifetime"]
        progress_line = get_text("kabinetim_progress", lang, remaining=f"{remaining:,}".replace(",", " "))
    else:
        progress_line = get_text("kabinetim_top_level", lang)

    name = user.get("full_name") or callback.from_user.full_name or "—"
    phone = user.get("phone") or get_text("kabinetim_no_phone", lang)
    lang_label = _LANG_LABELS.get(lang, lang)

    # Lazy-create the pinned Keto card the first time this user opens
    # Kabinetim, rather than only on their first earned award — otherwise a
    # buyer who hasn't ordered yet never gets one (owner report 2026-07-27).
    try:
        if not user.get("keto_pin_message_id") and await gamification.is_enabled():
            await gamification.ensure_pinned_card(callback.bot, user_id, lang)
    except Exception:
        pass

    text = get_text("kabinetim_title", lang,
        name=name, phone=phone, lang_label=lang_label,
        balance=f"{profile['balance']:,}".replace(",", " "),
        level_line=level_line,
        progress_line=progress_line,
        unlocked=profile["achievements_unlocked"],
        total=profile["achievements_total"],
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_my_orders", lang), callback_data="my_orders")],
        [InlineKeyboardButton(text=get_text("btn_achievements", lang), callback_data="kabinetim:achievements")],
        [InlineKeyboardButton(text=get_text("btn_back_to_menu", lang), callback_data="main_menu")],
    ])
    await _send_or_edit(callback, text, keyboard)
    await callback.answer()


@router.callback_query(F.data == "kabinetim:achievements")
async def show_achievements(callback: CallbackQuery):
    import gamification

    user_id = callback.from_user.id
    lang = await get_user_language(user_id)
    profile = await gamification.get_profile(user_id)
    unlocked_codes = profile["unlocked_codes"]

    lines = [get_text("achievements_title", lang,
                       unlocked=profile["achievements_unlocked"], total=profile["achievements_total"])]
    for ach in gamification.ACHIEVEMENTS:
        title = ach["title"]["uz" if lang != "ru" else "ru"]
        desc = ach["desc"]["uz" if lang != "ru" else "ru"]
        if ach["code"] in unlocked_codes:
            lines.append(get_text("achievement_unlocked", lang, emoji=ach["emoji"], title=title, desc=desc))
        else:
            lines.append(get_text("achievement_locked", lang, title=title, desc=desc))
    text = "\n".join(lines)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="kabinetim")],
    ])
    await _send_or_edit(callback, text, keyboard)
    await callback.answer()


@router.callback_query(F.data == "help")
async def show_help(callback: CallbackQuery):
    """Show help"""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    lang = await get_user_language(callback.from_user.id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        # Language switch moved here from the main menu (per request): the
        # guide is where users look for "how do I change things".
        [InlineKeyboardButton(
            text=get_text("btn_language", lang),
            callback_data="change_lang"
        )],
        [InlineKeyboardButton(
            text=get_text("btn_contact_admin", lang),
            url=f"https://t.me/{SUPPORT_USERNAME}"
        )],
        [InlineKeyboardButton(
            text=get_text("btn_back_to_menu", lang),
            callback_data="main_menu"
        )],
    ])
    await callback.message.edit_text(
        get_text("help_text", lang, support_username=SUPPORT_USERNAME),
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "promo")
async def show_promo(callback: CallbackQuery):
    """The "🎁 <aksiya nomi>" main-menu entry — the campaign's full terms and
    every bonus rule spelled out, with its image when the admin uploaded one.

    The button only appears while a campaign is running (see
    keyboards.main_menu_keyboard), but a stale menu from before it ended can
    still be tapped, so the "no aksiya" fallback is a real path, not dead code."""
    import promotions
    from config import WEBAPP_URL

    lang = await get_user_language(callback.from_user.id)
    text = await promotions.screen_text(lang)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=get_text("btn_catalog", lang), callback_data="catalog"),
    ], [
        InlineKeyboardButton(text=get_text("btn_back_to_menu", lang), callback_data="main_menu"),
    ]])

    if not text:
        await _send_or_edit(callback, get_text("promo_none", lang), keyboard)
        await callback.answer()
        return

    promo = await promotions.get_active()
    image_url = (promo or {}).get("image_url")
    if image_url and not image_url.startswith("http") and WEBAPP_URL:
        image_url = WEBAPP_URL.rstrip("/") + "/" + image_url.lstrip("/")

    if image_url and image_url.startswith("http"):
        # A photo can't be edited into a text bubble — delete + resend.
        # Telegram caps captions at 1024 chars, so a long shartlar block
        # goes out as its own follow-up message instead of being truncated.
        try:
            await callback.message.delete()
        except Exception:
            pass
        try:
            if len(text) <= 1024:
                await callback.message.answer_photo(image_url, caption=text, parse_mode="HTML", reply_markup=keyboard)
            else:
                await callback.message.answer_photo(image_url, parse_mode="HTML")
                await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
        except Exception:
            await callback.message.answer(text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await _send_or_edit(callback, text, keyboard)
    await callback.answer()


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    """Do nothing — used for page info buttons"""
    await callback.answer()
