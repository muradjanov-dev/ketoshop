"""
NPS (1-10) satisfaction survey — buyer taps a score, is asked why (free
text, /skip to pass), and both the score and the reason are relayed to
every admin live as they come in. Survey is broadcast by /nps_now in
handlers/broadcast_admin.py (see nps_survey.py).
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import get_user_language, get_user, add_nps_response, set_nps_comment
from locales import get_text
from nps_survey import notify_admins_new_vote, notify_admins_reason

router = Router()


class NPSStates(StatesGroup):
    waiting_reason = State()


@router.callback_query(F.data.startswith("nps_score:"))
async def nps_score(callback: CallbackQuery, state: FSMContext):
    """Score tapped — record it, ask why, and tell admins right away so a
    vote is never lost even if the buyer never answers the follow-up."""
    score = int(callback.data.split(":")[1])
    user_id = callback.from_user.id
    lang = await get_user_language(user_id)

    response_id = await add_nps_response(user_id, score)
    await state.set_state(NPSStates.waiting_reason)
    await state.update_data(nps_response_id=response_id, nps_score=score)

    try:
        await callback.message.edit_text(
            get_text("nps_thanks_score", lang, score=score),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()

    user = await get_user(user_id)
    await notify_admins_new_vote(callback.bot, user, user_id, score)


@router.message(NPSStates.waiting_reason)
async def nps_reason(message: Message, state: FSMContext):
    """Free-text reason (or /skip) for the score just given."""
    data = await state.get_data()
    response_id = data.get("nps_response_id")
    score = data.get("nps_score")
    user_id = message.from_user.id
    lang = await get_user_language(user_id)

    raw = (message.text or "").strip()
    comment = None if raw == "/skip" else raw
    if response_id is not None:
        await set_nps_comment(response_id, comment)
    await state.clear()

    await message.answer(get_text("nps_thanks_reason", lang), parse_mode="HTML")

    user = await get_user(user_id)
    await notify_admins_reason(message.bot, user, user_id, score, comment)
