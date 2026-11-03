"""
Kanal postlari — tugmasiz, havola matn ichida (egasi, 2026-11-03: "botga
inlinesiz xabarlar yuborgin kanalga, izoh yozish mumkin bo'lsin; saytga link
bo'lsin faqat matn ichida").

An inline keyboard under a channel post hides its comments bar, and it is
lost when the post is forwarded — a link inside the text survives both. The
recipe post (recipe_channel.py, PR #90) and the TOP-20 already worked this
way; every other channel post now does too: no reply_markup, the way into the
shop / bot / product is the last line of the text.
"""
import html

from config import BOT_USERNAME

# The Mini App's named link — opens the shop straight from the channel.
SHOP_URL = f"https://t.me/{BOT_USERNAME}/shop"
SHOP_LABEL = "🛒 Дўконни очиш"          # the channel reads Cyrillic Uzbek


def link_line(url: str, label: str = SHOP_LABEL) -> str:
    """«👉 Дўконни очиш 👈» — bold, tappable, in the text itself."""
    return f'👉 <b><a href="{html.escape(url, quote=True)}">{html.escape(label, quote=False)}</a></b> 👈'


def with_link(text: str, url: str = SHOP_URL, label: str = SHOP_LABEL, limit: int = 4096) -> str:
    """`text` with the link as its last line — unchanged if that would not fit."""
    out = f"{(text or '').rstrip()}\n\n{link_line(url, label)}"
    return out if len(out) <= limit else text
