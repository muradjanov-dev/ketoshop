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



@router.message(Command("kabinet"))
async def cmd_kabinet(message: Message, state: FSMContext):
    """Typed shortcut into Kabinetim — same screen as the menu button, minus
    the one-time intro (which only makes sense on a first visit)."""
    await state.clear()
    user_id = message.from_user.id
    lang = await get_user_language(user_id)
    user = await get_user(user_id)
    if not user:
        await ensure_registered(message.bot, message.from_user)
        user = await get_user(user_id)
    text, keyboard = await build_kabinetim_view(message.bot, user_id, lang, user or {})
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.message(Command("yordam"))
async def cmd_help(message: Message, state: FSMContext):
    await state.clear()
    lang = await get_user_language(message.from_user.id)
    await message.answer(
        get_text("help_text", lang, support_username=SUPPORT_USERNAME),
        reply_markup=build_help_keyboard(lang),
        parse_mode="HTML",
    )


@router.message(CommandStart(deep_link=True))
async def cmd_start_deep_link(message: Message, command: CommandObject):
    """A /start carrying a payload — a Facebook/Instagram ad link
    (?start=fb_<reklama>, see ad_sources.py), a blogger's personal link
    (?start=<bloger nomi>, see bloggers.py) or the older Keto musobaqasi
    share link (?start=ref<user_id>). The three shapes can't collide: the ad
    prefixes are reserved, and bloggers.parse_payload refuses both those and
    anything that looks like 'ref<digits>'."""
    import referral_contest
    import bloggers
    import ad_sources
    referrer_id = referral_contest.parse_ref_payload(command.args)
    blogger_code = bloggers.parse_payload(command.args)
    ad_source = ad_sources.parse_payload(command.args)
    await _handle_start(message, referrer_id, blogger_code, ad_source)


@router.message(CommandStart())
async def cmd_start(message: Message):
    """Handle /start — show language selection"""
    await _handle_start(message, None)


async def _handle_start(message: Message, referrer_id: int | None,
                        blogger_code: str | None = None,
                        ad_source: str | None = None):
    # Check if user is banned
    if await is_user_banned(message.from_user.id):
        lang = await get_user_language(message.from_user.id)
        await message.answer(get_text("you_are_banned", lang))
        return

    is_new = await ensure_registered(message.bot, message.from_user, referrer_id,
                                     blogger_code, ad_source)
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


async def ensure_registered(bot, tg_user, referrer_id: int | None = None,
                             blogger_code: str | None = None,
                             ad_source: str | None = None) -> bool:
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
    await _process_new_user(bot, tg_user, referrer_id, blogger_code, ad_source)
    return True


async def _process_new_user(bot, tg_user, referrer_id: int | None,
                             blogger_code: str | None = None,
                             ad_source: str | None = None) -> None:
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

    # Blogger partner link (bloggers.py) — ties this brand-new buyer to the
    # blogger whose link they came through, for good. Self-guarded, so a
    # mistyped code just means no attribution, never a broken registration.
    # Runs BEFORE the notification below, which names whoever brought them in.
    blogger = None
    if blogger_code:
        import bloggers
        blogger = await bloggers.attach_new_user(blogger_code, tg_user.id, bot)

    # Facebook/Instagram ad link (ad_sources.py) — the same shape as the
    # blogger attribution above, and equally self-guarded. A payload can only
    # ever be one of the two, so at most one of these actually records.
    source = None
    if ad_source:
        import ad_sources
        source = await ad_sources.attach_new_user(ad_source, tg_user.id, ad_source)

    try:
        await referral_contest.notify_admins_new_user(
            bot, tg_user.id, tg_user.username, tg_user.full_name, valid_referrer,
            blogger, source,
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


async def build_kabinetim_view(bot, user_id: int, lang: str, user: dict):
    """(text, keyboard) for Kabinetim — shared by the inline button and the
    /kabinet command."""
    import gamification

    profile = await gamification.get_profile(user_id)

    level = profile["level"]
    next_level = profile["next_level"]
    # Level + its cashback, and the way to the next one in so'm rather than
    # Keto points (sadoqat darajalari, 2026-09-17) — in the buyer's own script.
    rate = gamification.rate_label(gamification.earn_rate(profile["lifetime"]))
    level_line = f"{level['emoji']} " + gamification._L(lang)(
        f"<b>{level['label']['uz']}</b> · keshbek {rate}",
        f"<b>{level['label']['ru']}</b> · кешбэк {rate}",
    )
    if next_level:
        progress_line = gamification.next_level_progress(profile["lifetime"], lang)
    else:
        progress_line = get_text("kabinetim_top_level", lang)

    name = user.get("full_name") or "—"
    phone = user.get("phone") or get_text("kabinetim_no_phone", lang)
    lang_label = _LANG_LABELS.get(lang, lang)

    # Lazy-create the pinned Keto card the first time this user opens
    # Kabinetim, rather than only on their first earned award — otherwise a
    # buyer who hasn't ordered yet never gets one (owner report 2026-07-27).
    try:
        if not user.get("keto_pin_message_id") and await gamification.is_enabled():
            await gamification.ensure_pinned_card(bot, user_id, lang)
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
    rows = [
        [InlineKeyboardButton(text=get_text("btn_my_orders", lang), callback_data="my_orders")],
        [InlineKeyboardButton(text=get_text("btn_achievements", lang), callback_data="kabinetim:achievements")],
    ]
    # Bloger kabineti — shown only to registered partner bloggers, whose own
    # link/clients/earnings live one tap from here (see bloggers.py). This is
    # the section's only entry point besides the /bloger command, which is why
    # it hangs off Kabinetim (async) rather than the synchronous main menu.
    import bloggers
    if await bloggers.has_cabinet(user_id):
        rows.append(bloggers.cabinet_row(lang))
    rows.append([InlineKeyboardButton(text=get_text("btn_back_to_menu", lang), callback_data="main_menu")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def _render_kabinetim(callback: CallbackQuery, user_id: int, lang: str, user: dict) -> None:
    text, keyboard = await build_kabinetim_view(callback.bot, user_id, lang, user)
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
        pick = gamification._L(lang)
        title = pick(ach["title"]["uz"], ach["title"]["ru"])
        desc = pick(ach["desc"]["uz"], ach["desc"]["ru"])
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


def build_help_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Shared by the Qo'llanma button and the /yordam command."""
    return InlineKeyboardMarkup(inline_keyboard=[
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


@router.callback_query(F.data == "help")
async def show_help(callback: CallbackQuery):
    """Show help"""
    lang = await get_user_language(callback.from_user.id)
    await callback.message.edit_text(
        get_text("help_text", lang, support_username=SUPPORT_USERNAME),
        reply_markup=build_help_keyboard(lang),
        parse_mode="HTML"
    )
    await callback.answer()


def _promo_keyboard(lang: str, page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Catalog + back, plus a page strip when the campaign's rules don't fit
    in one Telegram message (see promotions.screen_pages)."""
    rows = []
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"promo:p:{page - 1}"))
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton(text="➡️", callback_data=f"promo:p:{page + 1}"))
        rows.append(nav)
    rows.append([InlineKeyboardButton(text=get_text("btn_catalog", lang), callback_data="catalog")])
    rows.append([InlineKeyboardButton(text=get_text("btn_back_to_menu", lang), callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _render_promo(callback: CallbackQuery, page: int) -> None:
    """One page of the aksiya screen. The campaign image rides along with the
    first page only — it belongs to the campaign, not to every page."""
    import promotions
    from config import WEBAPP_URL

    lang = await get_user_language(callback.from_user.id)
    pages = await promotions.screen_pages(lang)

    if not pages:
        await _send_or_edit(callback, get_text("promo_none", lang), _promo_keyboard(lang, 0, 1))
        await callback.answer()
        return

    page = max(0, min(page, len(pages) - 1))
    text = pages[page]
    keyboard = _promo_keyboard(lang, page, len(pages))

    promo = await promotions.get_active()
    image_url = (promo or {}).get("image_url") if page == 0 else None
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


@router.callback_query(F.data == "promo")
async def show_promo(callback: CallbackQuery):
    """The "🎁 <aksiya nomi>" main-menu entry — the campaign's full terms and
    every bonus rule spelled out, with its image when the admin uploaded one.

    The button only appears while a campaign is running (see
    keyboards.main_menu_keyboard), but a stale menu from before it ended can
    still be tapped, so the "no aksiya" fallback is a real path, not dead code."""
    await _render_promo(callback, 0)


@router.callback_query(F.data.startswith("promo:p:"))
async def show_promo_page(callback: CallbackQuery):
    """⬅️/➡️ through a campaign whose bonus list is too long for one message."""
    try:
        page = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        page = 0
    await _render_promo(callback, page)


@router.callback_query(F.data == "noop")
async def noop(callback: CallbackQuery):
    """Do nothing — used for page info buttons"""
    await callback.answer()
