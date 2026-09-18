"""
A net under every outgoing Telegram message.

Almost everything this bot sends is parse_mode="HTML", and the templates in
locales.py carry the markup while the values interpolated into them come from
people: a buyer's Telegram display name, the address and note they typed at
checkout, an admin's reply text. Telegram rejects the whole message if one of
those values contains a bare "<" or "&" — and the call sites uniformly treat a
send failure as "the buyer must have blocked us", swallow it, and move on.

The consequence is not a cosmetic glitch. A buyer whose address contains "&"
places an order and NO admin is ever told about it; the order sits in the
database while everyone assumes the shop is quiet. That failure has now
appeared twice (the support relay in September, the new-order notification
found in the same audit), because getting it right depends on remembering to
escape at every one of ~15 render sites, forever.

So the guarantee is moved to the one place every message passes through. On a
"can't parse entities" rejection — and only then, so a healthy send is
untouched — the text is stripped of its markup and sent again as plain text.
The formatting is lost; the message arrives. That trade is the right way
round: a plain-text order notification is worth infinitely more than a
correctly-bolded one nobody receives.

Escaping properly at the render site is still the better fix where the values
are known, and stays in place — this catches what that misses.
"""
import html
import logging
import re

from aiogram import Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)

# The fields that carry parse_mode-formatted bodies across the Bot API.
_TEXT_FIELDS = ("text", "caption")

# Telegram's hard limits per field. A body over them is rejected outright —
# the same silent-failure shape as the parse error above, and one a long
# product description walks straight into: the description column allows
# 2000 characters while a photo caption is capped at 1024, so one verbose
# product makes its whole card un-openable.
_MAX_LEN = {"text": 4096, "caption": 1024}
_ELLIPSIS = "…"

# A real tag, not merely a pair of angle brackets: the "<" has to be followed
# by an optional "/" and then a letter. Without that letter requirement,
# "narx < 50000 va a > b" reads as one big tag and the whole middle of the
# sentence disappears — which is how people actually write, so it matters.
_TAG = re.compile(r"</?[a-zA-Z][^<>]{0,200}?>")


def strip_markup(value: str) -> str:
    """Turn a failed HTML body into readable plain text.

    Tags go, entities become the characters they stand for — so a message that
    was already correctly escaped reads normally, and one that was not still
    shows the user's own "<" and "&" the way they typed them.
    """
    return html.unescape(_TAG.sub("", value or ""))


def truncate(value: str, limit: int) -> str:
    """Cut a body to `limit` characters, markup stripped first.

    Stripping before cutting is what makes this safe: slicing HTML at an
    arbitrary offset can leave a half-written tag, which Telegram rejects in
    turn, and a retry that fails the same way is no retry at all.
    """
    plain = strip_markup(value or "")
    if len(plain) <= limit:
        return plain
    return plain[: max(0, limit - len(_ELLIPSIS))].rstrip() + _ELLIPSIS


class HtmlFallbackMiddleware(BaseRequestMiddleware):
    """Retry a rejected message once: as plain text, or trimmed to fit."""

    async def __call__(self, make_request, bot: Bot, method):
        try:
            return await make_request(bot, method)
        except TelegramBadRequest as exc:
            message = str(exc).lower()
            too_long = "too long" in message
            unparseable = ("can't parse entities" in message
                           or "unsupported start tag" in message)
            if not (too_long or unparseable):
                raise

            field = next(
                (f for f in _TEXT_FIELDS if isinstance(getattr(method, f, None), str)), None
            )
            if field is None:
                raise

            original = getattr(method, field)
            if too_long:
                fixed = truncate(original, _MAX_LEN.get(field, 4096))
                why = f"over the {field} length limit"
            else:
                fixed = strip_markup(original)
                why = "rejected as HTML"
            retry = method.model_copy(update={field: fixed, "parse_mode": None})
            logger.warning(
                "%s %s (%s); resent as plain text. Offending body starts: %.120r",
                type(method).__name__, why, exc.message, original,
            )
            return await make_request(bot, retry)


def install(bot: Bot) -> None:
    """Attach the net. Call once, right after the Bot is constructed."""
    bot.session.middleware(HtmlFallbackMiddleware())
