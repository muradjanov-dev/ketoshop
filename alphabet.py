"""
Yangi alifbo — the 2026 Uzbek Latin alphabet (Ö Ğ Ş Ç) on everything the
shop shows in Latin Uzbek (owner, 2026-10-28: "loyihani yangi alifboga
o'tkaz"; chose "hozirdan, o'chirish bilan" — now, with a switch).

The law (OʻRQ-1184) takes effect on 22.04.2027; the owner wants it shown
now. Nothing is rewritten at the source: the code, locales.py and the
database stay in the old Latin, and translit.to_new_latin runs where text
leaves for a reader —

  * the bot: NewAlphabetMiddleware on the HTTP session rewrites the text,
    caption, button labels, popup alerts and the "/" menu of everything
    sent to a reader of Latin Uzbek (users.language "uz", or a group or the
    channel — their posts are written in Latin Uzbek). Cyrillic and Russian
    readers are left alone. A message sent with explicit `entities` is left
    alone too: shortening "sh" to "ş" would move every offset;
  * the Mini App and the admin panel: the page converts its own text on
    screen (webapp/index.html, webapp/admin.html), told by the server
    whether the switch is on ({{NEW_ALPHABET}});
  * search takes a query in either alphabet (translit.to_old_latin).

/alifbo (admins) shows the state and flips it; the choice lives in
app_settings so it survives a restart. NEW_ALPHABET=0 in the environment
forces it off.
"""
import logging
import os
import time

from aiogram import F, Router
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import database
from config import ADMIN_IDS
from translit import to_new_latin

logger = logging.getLogger(__name__)
router = Router(name="alphabet")

SETTING = "new_alphabet"
LANG_TTL = 60                      # seconds a reader's language is trusted
_state = {"on": True}
_langs: dict[int, tuple[float, str]] = {}


def forced_off() -> bool:
    return os.getenv("NEW_ALPHABET", "1").strip() == "0"


def is_on() -> bool:
    return _state["on"] and not forced_off()


async def ensure_table() -> None:
    async with database.pool.acquire() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")


async def load() -> bool:
    """Read the switch at startup (default: on, the owner's choice)."""
    try:
        await ensure_table()
        async with database.pool.acquire() as conn:
            value = await conn.fetchval("SELECT value FROM app_settings WHERE key = $1", SETTING)
        _state["on"] = value != "0"
    except Exception:
        logger.exception("Could not read the alphabet switch — keeping %s", _state["on"])
    return is_on()


async def set_on(on: bool) -> None:
    await ensure_table()
    async with database.pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO app_settings (key, value) VALUES ($1, $2)
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
            SETTING, "1" if on else "0")
    _state["on"] = bool(on)


# ─────────────────────────────── the bot ────────────────────────────────────

async def _reader_lang(chat_id) -> str:
    """The language a chat reads in. Groups and channels (negative ids,
    @usernames) are written in Latin Uzbek; a person by users.language,
    "uz" when unknown — the bot's default."""
    if isinstance(chat_id, str) or not isinstance(chat_id, int) or chat_id < 0:
        return "uz"
    hit = _langs.get(chat_id)
    if hit and time.time() - hit[0] < LANG_TTL:
        return hit[1]
    try:
        lang = await database.get_user_language(chat_id) or "uz"
    except Exception:
        lang = "uz"
    _langs[chat_id] = (time.time(), lang)
    return lang


def convert_markup(markup):
    """Button labels of an inline or reply keyboard, in the new alphabet."""
    from aiogram.types import ReplyKeyboardMarkup
    if isinstance(markup, InlineKeyboardMarkup):
        rows = [[b.model_copy(update={"text": to_new_latin(b.text)}) for b in row]
                for row in markup.inline_keyboard]
        return markup.model_copy(update={"inline_keyboard": rows})
    if isinstance(markup, ReplyKeyboardMarkup):
        rows = [[b.model_copy(update={"text": to_new_latin(b.text)}) for b in row]
                for row in markup.keyboard]
        update = {"keyboard": rows}
        if markup.input_field_placeholder:
            update["input_field_placeholder"] = to_new_latin(markup.input_field_placeholder)
        return markup.model_copy(update=update)
    return markup


def convert_method(method):
    """The same Telegram call with its Latin Uzbek in the new alphabet."""
    from aiogram.methods import AnswerCallbackQuery, SetMyCommands
    if isinstance(method, SetMyCommands):
        if method.language_code not in (None, "", "uz"):
            return method
        commands = [c.model_copy(update={"description": to_new_latin(c.description)})
                    for c in method.commands]
        return method.model_copy(update={"commands": commands})
    if getattr(method, "entities", None) or getattr(method, "caption_entities", None):
        return method                       # offsets would point at the wrong letters
    update = {}
    for field in ("text", "caption"):
        value = getattr(method, field, None)
        if isinstance(value, str) and value:
            new = to_new_latin(value)
            if new != value:
                update[field] = new
    markup = getattr(method, "reply_markup", None)
    if markup is not None:
        new_markup = convert_markup(markup)
        if new_markup is not markup:
            update["reply_markup"] = new_markup
    if isinstance(method, AnswerCallbackQuery) and not update.get("text"):
        update.pop("text", None)
    return method.model_copy(update=update) if update else method


class NewAlphabetMiddleware(BaseRequestMiddleware):
    """bot.session.middleware — registered AFTER admin_mood's, so it runs on
    the final text (the cheer line included)."""

    async def __call__(self, make_request, bot, method):
        try:
            method = await self._convert(method)
        except Exception:
            logger.exception("New-alphabet conversion failed — sending as written")
        return await make_request(bot, method)

    async def _convert(self, method):
        if not is_on():
            return method
        from aiogram.methods import AnswerCallbackQuery, SetMyCommands
        if isinstance(method, SetMyCommands):
            return convert_method(method)
        if isinstance(method, AnswerCallbackQuery):
            import admin_mood
            chat_id = admin_mood._current_user.get()
            if chat_id is None:
                return method
        else:
            chat_id = getattr(method, "chat_id", None)
            if chat_id is None:
                return method               # inline-message edits: no reader to ask
        if await _reader_lang(chat_id) != "uz":
            return method
        return convert_method(method)


# ─────────────────────────────── /alifbo ────────────────────────────────────

def _status_text() -> str:
    if forced_off():
        return ("🔤 <b>Yangi alifbo</b> serverda NEW_ALPHABET=0 bilan o'chirilgan — "
                "tugma bilan yoqib bo'lmaydi.")
    state = ("✅ <b>yoqilgan</b> — lotin yozuvidagi hamma matn Ö, Ğ, Ş, Ç bilan chiqadi"
             if is_on() else "⚪ <b>o'chirilgan</b> — eski lotin (oʻ, gʻ, sh, ch)")
    return ("🔤 <b>Yangi alifbo</b> (qonun OʻRQ-1184, 22.04.2027 dan majburiy)\n\n"
            f"Holati: {state}.\n\n"
            "Bot, sayt va admin panel birga o'zgaradi. Kirill va rus tili o'zgarmaydi.")


def _keyboard() -> InlineKeyboardMarkup:
    if is_on():
        button = InlineKeyboardButton(text="⚪ Eski alifboga qaytarish", callback_data="alifbo:off")
    else:
        button = InlineKeyboardButton(text="✅ Yangi alifboni yoqish", callback_data="alifbo:on")
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


@router.message(Command("alifbo"))
async def cmd_alifbo(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer(_status_text(), reply_markup=_keyboard(), parse_mode="HTML")


@router.callback_query(F.data.in_({"alifbo:on", "alifbo:off"}))
async def toggle(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer()
        return
    await set_on(callback.data == "alifbo:on")
    logger.info("New alphabet switched %s by %s", "on" if is_on() else "off", callback.from_user.id)
    try:
        await callback.message.edit_text(_status_text(), reply_markup=_keyboard(), parse_mode="HTML")
    except Exception:
        pass
    await callback.answer("✅")
