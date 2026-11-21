"""
«Savolingiz bo'lsa — botga yozing» — every post ends with an invitation to talk
to the bot (owner, 2026-11-21: "Botdan yuboriladigan xar qanday post oxiriga
botda gaplashish imkoni borligini bildirib agar mavzu bo'yicha tushunmagan
joyingiz bo'lsa shu yerda yozing Sizga tushuntirib beramiz yoki qaysidur
mahsulot haqida foyda va zararlarini yoki boshqa mahsulotlardan farqini ...
bilmoqchi bo'lsangiz botdan istalgan savolni so'rashingiz mumkin ... odamlar
yozishlari kerak botga").

A bot.session middleware, like channel_signature, so no module has to
remember it:

  • a post in the channel — the line (Cyrillic, with @bot) goes before the
    channel signature, which channel_signature adds after it;
  • a scheduled post to a buyer — every one of them passes push_cap.claim()
    right before it is sent; claim() marks that buyer in a context variable,
    and the next text or captioned message to that buyer in the same task
    gets the line in the buyer's language. Replies, order messages, the AI's
    own answers never go through claim(), so they stay as they are;
  • never twice, never past Telegram's limits (then the post goes as written).
"""
from __future__ import annotations

import contextvars
import html
import logging
import random

from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods import SendAnimation, SendDocument, SendMessage, SendPhoto, SendVideo

logger = logging.getLogger(__name__)

_MARK_UZ = "istalgan savolingizni"
_MARK_RU = "любой вопрос"
_MARK_CYR = "исталган саволингизни"
TEXT_LIMIT, CAPTION_LIMIT = 4096, 1024
_CAPTIONED = (SendPhoto, SendVideo, SendAnimation, SendDocument)

_pending: contextvars.ContextVar[int | None] = contextvars.ContextVar("post_ask_pending", default=None)

DM = {
    "uz": ("💬 Mavzu bo'yicha tushunmagan joyingiz bo'lsa yoki biror mahsulotning foydasi, zarari, "
           "boshqasidan farqini bilmoqchi bo'lsangiz — shu yerga istalgan savolingizni yozing, "
           "tushuntirib beramiz 🙂"),
    "ru": ("💬 Если что-то непонятно по теме или хотите узнать о пользе и вреде продукта, чем он "
           "отличается от других, — напишите здесь любой вопрос, мы всё объясним 🙂"),
}


def channel_line() -> str:
    from config import BOT_USERNAME
    return (f"💬 Тушунмаган жойингиз бўлса ёки бирор маҳсулотнинг фойдаси, зарари, бошқасидан фарқини "
            f"билмоқчи бўлсангиз — @{BOT_USERNAME} га исталган саволингизни ёзинг, тушунтириб берамиз.")


def dm_line(lang: str | None) -> str:
    if lang == "ru":
        return DM["ru"]
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        return lat_to_cyr(DM["uz"])
    return DM["uz"]


# Owner, 2026-11-21: "🛍️ Соғлом маҳсулотлар дунёси: saytga link (postlar oxirida ...
# bazida shu iborani ishlat bu yoqimliroq)". About every second channel post, the plain
# «🛒 Дўконни очиш» shop link reads like this instead — same link.
WORLD_CHANCE = 0.5
_rng = random.Random()


def world_line(url: str) -> str:
    shown = url.replace("https://", "")
    return (f'🛍️ <b>Соғлом маҳсулотлар дунёси:</b> '
            f'<a href="{html.escape(url, quote=True)}">{html.escape(shown, quote=False)}</a>')


def vary_shop_link(text: str | None) -> str | None:
    import channel_link
    if not text:
        return text
    plain = channel_link.link_line(channel_link.SHOP_URL, channel_link.SHOP_LABEL)
    if plain not in text or _rng.random() >= WORLD_CHANCE:
        return text
    return text.replace(plain, world_line(channel_link.SHOP_URL), 1)


def mark(user_id: int) -> None:
    """push_cap.claim() said yes: the next post to this buyer is a scheduled one."""
    _pending.set(user_id)


def _has(text: str) -> bool:
    return any(m in text for m in (_MARK_UZ, _MARK_RU, _MARK_CYR))


def _visible_length(text: str) -> int:
    from tg_safety import strip_markup
    return len(strip_markup(text).encode("utf-16-le")) // 2


def with_line(text: str | None, line: str, limit: int) -> str | None:
    if not text or _has(text):
        return text
    import html
    out = f"{text.rstrip()}\n\n{html.escape(line, quote=False)}"
    return out if _visible_length(out) <= limit else text


async def _lang(user_id: int) -> str:
    try:
        import database
        return await database.get_user_language(user_id) or "uz"
    except Exception:
        return "uz"


async def add_line(method):
    from channel_signature import is_channel
    if isinstance(method, SendMessage):
        field, limit = "text", TEXT_LIMIT
    elif isinstance(method, _CAPTIONED) and method.caption:
        field, limit = "caption", CAPTION_LIMIT
    else:
        return method
    text = getattr(method, field)
    if is_channel(method.chat_id):
        new = with_line(vary_shop_link(text), channel_line(), limit)
    elif _pending.get() is not None and method.chat_id == _pending.get():
        _pending.set(None)
        new = with_line(text, dm_line(await _lang(method.chat_id)), limit)
    else:
        return method
    return method if new == text else method.model_copy(update={field: new})


class PostAskMiddleware(BaseRequestMiddleware):
    async def __call__(self, make_request, bot, method):
        try:
            method = await add_line(method)
        except Exception:
            logger.exception("post ask line failed — sending as written")
        return await make_request(bot, method)
