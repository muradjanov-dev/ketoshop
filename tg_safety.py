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


class HtmlFallbackMiddleware(BaseRequestMiddleware):
    """Retry a parse-rejected message once, as plain text."""

    async def __call__(self, make_request, bot: Bot, method):
        try:
            return await make_request(bot, method)
        except TelegramBadRequest as exc:
            message = str(exc).lower()
            if "can't parse entities" not in message and "unsupported start tag" not in message:
                raise

            field = next(
                (f for f in _TEXT_FIELDS if isinstance(getattr(method, f, None), str)), None
            )
            if field is None:
                raise

            original = getattr(method, field)
            retry = method.model_copy(update={field: strip_markup(original), "parse_mode": None})
            logger.warning(
                "%s rejected as HTML (%s); resent as plain text. Offending body starts: %.120r",
                type(method).__name__, exc.message, original,
            )
            return await make_request(bot, retry)


def install(bot: Bot) -> None:
    """Attach the net. Call once, right after the Bot is constructed."""
    bot.session.middleware(HtmlFallbackMiddleware())
