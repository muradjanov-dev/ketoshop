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
     itself (owner follow-up request, same day).

One question, several admins — so the card is shared state, not a private
notice (owner request 2026-09-02: "bitta admin javob bersa unga javob
berilgani boshqa adminlarga ham ko'rinsin ... va boshqalar boshqa javob bera
olmasin"). Two mechanisms keep the copies honest:

  * a CLAIM, taken the moment someone taps Javob berish. It is a single row
    keyed by buyer, so two admins tapping together cannot both win; the loser
    is told who is writing. The claim expires (database.SUPPORT_CLAIM_TTL_
    MINUTES) so an abandoned one never freezes the question, and the holder
    gets a Bekor qilish button to hand it back early.
  * the RELAY COPIES table, which remembers where each admin's card landed.
    When the answer goes out, every card is rewritten in place with who
    answered and what they said, and its button is removed.

Both are best-effort around the actual send: a buyer's reply must never fail
because the bookkeeping did.
"""
from aiogram import Router, Bot, F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

import html
import logging

from config import ADMIN_IDS
from database import (
    get_user, get_user_language, log_support_message, mark_support_answered,
    count_open_support, record_support_relay, open_support_relays,
    close_support_relays, claim_support, release_support_claim,
    is_support_answered, last_support_reply,
)
from locales import get_text
from keyboards import main_menu_keyboard

logger = logging.getLogger(__name__)

router = Router()

# Long replies are quoted back to the other admins so they can see what was
# said without opening the thread; past this they get the opening of it.
ANSWER_PREVIEW_CHARS = 400


class SupportReplyStates(StatesGroup):
    waiting_text = State()


def _reply_kb(buyer_id: int) -> InlineKeyboardMarkup:
    """The relay card's button. The ":card" suffix is what tells
    start_freeform_reply this tap came from a pushed notification rather than
    from the Xabarlar screen — see the note there."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="↩️ Javob berish", callback_data=f"freereply:{buyer_id}:card"),
    ]])


def _cancel_kb(buyer_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="❌ Javob berishni bekor qilish",
                             callback_data=f"freecancel:{buyer_id}"),
    ]])


async def admin_display_name(admin_id: int) -> str:
    """How one admin should be named to the others."""
    user = await get_user(admin_id)
    if not user:
        return f"ID {admin_id}"
    if user.get("username"):
        return f"@{user['username']}"
    return user.get("full_name") or f"ID {admin_id}"


async def _rewrite_cards(bot: Bot, buyer_id: int, footer: str,
                         keyboard: InlineKeyboardMarkup | None = None,
                         skip_admin: int | None = None,
                         keyboard_for_skipped: InlineKeyboardMarkup | None = None) -> None:
    """Append `footer` to every live copy of this buyer's question.

    `skip_admin` is the admin who triggered the change: they get
    `keyboard_for_skipped` (usually their own Bekor qilish button) instead of
    the footer meant for the audience, since they already know what they just
    did. Telegram rejects an edit that changes nothing, and a card can have
    been deleted by hand — neither is worth failing over, so every edit is
    tried on its own."""
    for copy in await open_support_relays(buyer_id):
        is_actor = skip_admin is not None and copy["admin_id"] == skip_admin
        text = copy["body"] if (is_actor or not footer) else f"{copy['body']}\n\n{footer}"
        try:
            await bot.edit_message_text(
                chat_id=copy["chat_id"],
                message_id=copy["message_id"],
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard_for_skipped if is_actor else keyboard,
            )
        except Exception:
            logger.debug("Could not update support card for admin %s", copy["admin_id"])


async def announce_support_answer(bot: Bot, buyer_id: int, admin_id: int, reply_text: str) -> None:
    """Close this buyer's question out across every admin's chat.

    Called from wherever a reply actually reaches a buyer — the relay's own
    form and the order screen's "message the client" flow both end up here, so
    an answer sent from either place stops the other admins seeing a live
    reply button for something already handled. Purely bookkeeping: never
    raises, because the buyer's message has already gone out by this point."""
    try:
        await release_support_claim(buyer_id, admin_id)
        preview = (reply_text or "").strip()
        if len(preview) > ANSWER_PREVIEW_CHARS:
            preview = preview[:ANSWER_PREVIEW_CHARS].rstrip() + "…"
        footer = (f"✅ <b>{html.escape(await admin_display_name(admin_id))}</b> javob berdi:\n"
                  f"<i>«{html.escape(preview)}»</i>")
        await _rewrite_cards(bot, buyer_id, footer=footer, keyboard=None)
        await close_support_relays(buyer_id)
    except Exception:
        logger.exception("Could not close support cards for %s", buyer_id)


@router.callback_query(F.data.startswith("freereply:"))
async def start_freeform_reply(callback: CallbackQuery, state: FSMContext, bot: Bot):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer()
        return
    # "freereply:<buyer>" from the Xabarlar panel, "freereply:<buyer>:card"
    # from a relay card. The panel is a deliberate visit to a thread the admin
    # has just read in full, so a follow-up message from there is fine; the
    # card is the one that must not produce a second answer to a question
    # somebody else has already handled.
    parts = callback.data.split(":")
    buyer_id = int(parts[1])
    from_card = len(parts) > 2 and parts[2] == "card"
    me = callback.from_user.id

    if from_card and await is_support_answered(buyer_id):
        previous = await last_support_reply(buyer_id) or {}
        who = await admin_display_name(previous.get("admin_id") or 0)
        said = (previous.get("text") or "").strip()
        if len(said) > 150:
            said = said[:150].rstrip() + "…"
        await callback.answer(f"✅ Javob berilgan — {who}:\n\n{said}", show_alert=True)
        return

    holder = await claim_support(buyer_id, me)
    if holder != me:
        # Somebody else is already writing. Say who, and don't open the form.
        await callback.answer(
            f"⛔ {await admin_display_name(holder)} bu xabarga javob yozmoqda.",
            show_alert=True,
        )
        return

    await state.set_state(SupportReplyStates.waiting_text)
    await state.update_data(buyer_id=buyer_id, from_card=from_card)

    # Tell the other admins the question is taken before anything is typed —
    # that is the whole point of claiming it early rather than at send time.
    await _rewrite_cards(
        bot, buyer_id,
        footer=f"✍️ <b>{html.escape(await admin_display_name(me))}</b> javob yozmoqda…",
        keyboard=None,
        skip_admin=me,
        keyboard_for_skipped=_cancel_kb(buyer_id),
    )

    await callback.message.answer(f"✍️ Javobingizni yozing (buyer ID {buyer_id}):")
    await callback.answer()


@router.callback_query(F.data.startswith("freecancel:"))
async def cancel_freeform_reply(callback: CallbackQuery, state: FSMContext, bot: Bot):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer()
        return
    buyer_id = int(callback.data.split(":", 1)[1])
    await release_support_claim(buyer_id, callback.from_user.id)

    current = await state.get_state()
    if current == SupportReplyStates.waiting_text.state:
        await state.clear()

    # Hand it back: everyone's button returns, including the canceller's.
    await _rewrite_cards(bot, buyer_id, footer="", keyboard=_reply_kb(buyer_id),
                         skip_admin=callback.from_user.id,
                         keyboard_for_skipped=_reply_kb(buyer_id))
    await callback.answer("Bekor qilindi — xabar yana ochiq.")


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

    me = message.from_user.id

    # The claim is taken when the button is tapped, but an admin can sit on
    # the form long enough for it to expire and someone else to answer. Check
    # before sending rather than after, so the buyer never gets two answers.
    # Only for replies started from a relay card: a follow-up deliberately
    # started from the Xabarlar screen is allowed to go out regardless.
    if data.get("from_card") and await is_support_answered(buyer_id):
        previous = await last_support_reply(buyer_id)
        who = await admin_display_name((previous or {}).get("admin_id") or 0)
        body = html.escape(((previous or {}).get("text") or "").strip())
        await release_support_claim(buyer_id, me)
        await message.answer(
            f"⛔ Bu xabarga allaqachon javob berilgan — <b>{html.escape(who)}</b>:\n\n{body}",
            parse_mode="HTML",
        )
        return

    buyer_lang = await get_user_language(buyer_id)
    try:
        await bot.send_message(
            buyer_id,
            # Escaped for the same reason as the inbound card, and the way
            # seller.py's message-the-client flow already does it: an admin
            # typing "<" or "&" must not turn into a failed delivery.
            get_text("freeform_reply_to_buyer", buyer_lang, text=html.escape(reply_text)),
            parse_mode="HTML",
        )
    except Exception:
        await release_support_claim(buyer_id, me)
        await message.answer("⚠️ Yuborib bo'lmadi — foydalanuvchi botni bloklagan bo'lishi mumkin.")
        return

    # Delivered. Everything below is bookkeeping — a failure here must not
    # read to the admin as a failed reply.
    try:
        await log_support_message(buyer_id, "out", reply_text, admin_id=me)
        await mark_support_answered(buyer_id)
    except Exception:
        logger.exception("Could not log support reply to %s", buyer_id)

    await announce_support_answer(bot, buyer_id, me, reply_text)
    await message.answer("✅ Yuborildi.")


@router.message(F.text, F.chat.type == "private")
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

    # Keep the question itself, not just the relay — the admins' copy scrolls
    # away in their chat, and until now nothing was left to review.
    open_count = 0
    try:
        await log_support_message(buyer_id, "in", text)
        open_count = await count_open_support()
    except Exception:
        logger.exception("Could not log inbound support message from %s", buyer_id)

    # A new question reopens the conversation: a claim left over from the
    # previous exchange must not keep the button hidden. The earlier cards are
    # deliberately NOT closed — if two questions are still waiting, one reply
    # answers both, and both cards should say so.
    try:
        await release_support_claim(buyer_id)
    except Exception:
        logger.exception("Could not reset support claim for %s", buyer_id)

    for admin_id in ADMIN_IDS:
        admin_lang = await get_user_language(admin_id)
        try:
            waiting = f"\n\n⏳ Javobsiz xabarlar: <b>{open_count}</b> ta" if open_count > 1 else ""
            # The card is sent as HTML, so the buyer's own words have to be
            # escaped: a question containing "<" used to make send_message
            # fail outright, and the bare except below turned that into the
            # admins simply never hearing about it. `contact` is markup on
            # purpose (buyer_contact_link escapes the name inside it).
            body = get_text("freeform_from_buyer", admin_lang,
                            name=html.escape(name), contact=contact,
                            text=html.escape(text)) + waiting
            sent = await bot.send_message(
                admin_id, body, parse_mode="HTML", reply_markup=_reply_kb(buyer_id),
            )
            # Remember where it landed so a reply can rewrite every copy.
            try:
                await record_support_relay(buyer_id, admin_id, sent.chat.id, sent.message_id, body)
            except Exception:
                logger.exception("Could not record support relay copy for admin %s", admin_id)
        except Exception:
            pass
