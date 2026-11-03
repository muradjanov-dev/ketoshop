"""
Every channel post ends with «💚 @ketoshop_uz — Сизнинг Кето дўконингиз»
(owner, 2026-11-03: "… shunday tugasin").

A bot.session middleware, so the rule holds for every post the bot puts in
the channel — scheduled (daily content, recipe, spotlight, TOP lists,
«Keto fakt», announcements) or sent by an admin command, today's modules and
future ones — instead of each module remembering it:

  • SendMessage → the text gets the line at the end;
  • SendPhoto / SendVideo / SendAnimation / SendDocument → the caption does,
    but only a caption that exists — a photo sent bare (its text follows as
    the next message) is not signed twice;
  • never twice (already there), and never past Telegram's limits (4096 text,
    1024 caption, counted as Telegram does) — then the post goes as written;
  • edits and everything else pass through untouched.

Registered after alphabet.NewAlphabetMiddleware, so it signs the final text.
"""
import logging

from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods import SendAnimation, SendDocument, SendMessage, SendPhoto, SendVideo

from config import REQUIRED_CHANNEL_ID, REQUIRED_CHANNEL_USERNAME

logger = logging.getLogger(__name__)

SIGNATURE = f"💚 @{REQUIRED_CHANNEL_USERNAME} — Сизнинг Кето дўконингиз"
_MARK = "Сизнинг Кето дўконингиз"
TEXT_LIMIT, CAPTION_LIMIT = 4096, 1024
_CAPTIONED = (SendPhoto, SendVideo, SendAnimation, SendDocument)


def is_channel(chat_id) -> bool:
    if not REQUIRED_CHANNEL_ID or chat_id is None:
        return False
    if isinstance(chat_id, str):
        name = chat_id.lstrip("@").lower()
        return name == str(REQUIRED_CHANNEL_ID) or name == (REQUIRED_CHANNEL_USERNAME or "").lower()
    return chat_id == REQUIRED_CHANNEL_ID


def _visible_length(text: str) -> int:
    """What Telegram counts: the text after HTML parsing, in UTF-16 units."""
    from tg_safety import strip_markup
    return len(strip_markup(text).encode("utf-16-le")) // 2


def signed(text: str, limit: int) -> str:
    """`text` ending with the signature — or `text` itself when it already has
    it or the signature would not fit."""
    if not text or _MARK in text:
        return text
    out = f"{text.rstrip()}\n\n{SIGNATURE}"
    return out if _visible_length(out) <= limit else text


def sign_method(method):
    """The same Telegram call, signed if it is a post in the channel."""
    if isinstance(method, SendMessage) and is_channel(method.chat_id):
        text = signed(method.text, TEXT_LIMIT)
        return method if text == method.text else method.model_copy(update={"text": text})
    if isinstance(method, _CAPTIONED) and is_channel(method.chat_id) and method.caption:
        caption = signed(method.caption, CAPTION_LIMIT)
        return method if caption == method.caption else method.model_copy(update={"caption": caption})
    return method


class ChannelSignatureMiddleware(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        try:
            method = sign_method(method)
        except Exception:
            logger.exception("Channel signature failed — sending as written")
        return await make_request(bot, method)
