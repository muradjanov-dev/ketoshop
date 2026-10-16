"""
The product card — one format, in every place a product is shown.

The catalog's detail bubble, the daily "Kun mahsuloti" broadcast and the
channel post all render the same caption (name, description, price, unit,
stock, discount, Keto cashback, aksiya bonus, rating) and the same keyboard.
It used to live inside handlers/catalog.py; it moved here the day the daily
spotlight started sending the very same card, so the two can never drift.
"""
import asyncio
import html
import logging
from urllib.parse import urljoin

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import database
from database import (
    active_discount, effective_price, get_cart_badge, get_cart_line_for_product,
    get_product_rating,
)
from keyboards import cart_shortcut_row
from locales import get_text, get_display_unit, localize_product_text
from config import WEBAPP_URL
from tg_safety import strip_markup

logger = logging.getLogger(__name__)

# Kept for description-library guidance. Rendering no longer truncates text:
# cards over the photo-caption limit are sent as photo + complete text.
DESC_IN_CARD_MAX = 650

# Sold-out notes product_out_of_stock_0..N-1, picked by product id — the same
# five the Mini App's detail sheet shows (SOLD_OUT_NOTES in webapp/index.html).
SOLD_OUT_NOTES = 5


async def build_caption(product: dict, lang: str, rate: float | None,
                        extra: str | None = None, tip: str | None = None,
                        lead: str | None = None) -> str:
    """The card's text. `rate` is the Keto cashback to advertise (None = don't
    show that line at all); callers pass gamification.buyer_rate(user) for a
    buyer, or the base rate for an audience with no single reader.

    `extra` adds the daily spotlight's recipe idea. Keep the entire description;
    send_product_message handles Telegram's caption and message limits.

    `tip` is the buyer's personal advice line (product_tips). It goes right
    under the name, above the description — the first thing they read
    (owner, 2026-10-02).

    `lead` goes above everything — the "siz qiziqqan mahsulot qaytdi"
    headline of a restock notice (restock_notify.py).
    """
    import gamification
    import gift_campaign
    import mystery_gift
    import promotions

    # The standing promises close every card (owner, 2026-09-19): the
    # Eritritol on every order, the surprise from 400 000, free Tashkent
    # delivery from 800 000. Both the promises and the description are kept.
    import bot_discount
    gift = "\n".join(filter(None, [
        # 10% for ordering through the bot (owner, 2026-10-08) — leads the
        # promises while it is on, gone the moment it is switched off.
        await bot_discount.reminder(lang),
        await gift_campaign.card_line(lang),
        mystery_gift.card_line(lang),
        mystery_gift.free_delivery_card_line(lang),
    ]))

    seller_name = product.get("seller_name") or product.get("seller_username") or "—"
    name = localize_product_text(product.get("name"), product.get("name_ru"), lang)
    desc = localize_product_text(product.get("description"), product.get("description_ru"), lang) or "—"
    # Sold out: one of the warm notes, the same five the Mini App shows.
    sold_out = (get_text(f"product_out_of_stock_{abs(int(product.get('id') or 0)) % SOLD_OUT_NOTES}", lang)
                if product["quantity"] <= 0 else "")

    discount_until = product.get("discount_until")
    discount = active_discount(product.get("discount_percent"), discount_until)
    final_price = effective_price(product["price"], discount, discount_until)
    # 10% bot/site-order price on every card while it is on (owner,
    # 2026-10-12) — the very price checkout charges; its end date is in the
    # reminder line below, so no separate "until" line.
    bot_price = await bot_discount.display_price(product)
    if bot_price is not None:
        discount = bot_discount.shown_percent(product["price"], bot_price)
        final_price, discount_until = bot_price, None

    text = get_text("product_card", lang,
        name=html.escape(name or "", quote=False),
        description=html.escape(desc, quote=False),
        price=f"{int(final_price):,}".replace(",", " "),
        unit=get_display_unit(product["unit"], lang),
        available=product["quantity"],
        seller=html.escape(seller_name, quote=False),
    )
    if tip:
        import html as _html
        # The card template opens with the name, then a blank line — the tip
        # goes into that gap, ahead of the description.
        text = text.replace("\n\n", f"\n\n💡 <i>{_html.escape(tip, quote=False)}</i>\n\n", 1)

    if discount > 0:
        text += "\n" + get_text("product_discount_line", lang,
            percent=discount,
            old=f"{int(product['price']):,}".replace(",", " "),
            new=f"{int(final_price):,}".replace(",", " "),
            saved=f"{int(product['price'] - final_price):,}".replace(",", " "),
        )
        if discount_until:
            text += "\n" + get_text("product_discount_until", lang,
                date=discount_until.strftime("%d.%m.%Y %H:%M"),
            )

    # 🎁 +N Keto this product brings back, at this reader's own cashback rate.
    if rate:
        reward = gamification.product_reward_line(
            gamification.keto_for(final_price, rate), rate, lang)
        if reward:
            text += "\n" + reward

    if sold_out:
        text += "\n\n" + sold_out

    # Aksiya bonus this exact product triggers — on the card, so the buyer
    # sees the gift before deciding, not only once it lands in the cart.
    hint = promotions.bonus_hint(await promotions.get_active(), product["id"], lang)
    if hint:
        text += "\n\n" + hint

    avg_rating, review_count = await get_product_rating(product["id"])
    if review_count > 0:
        text += "\n" + get_text("product_rating_line", lang, rating=avg_rating, count=review_count)

    if extra:
        text += "\n\n" + extra

    # The promises have the last word on every card (owner, 2026-09-19) —
    # they are the reason to order now, so nothing follows them.
    if gift:
        text += "\n\n" + gift

    if lead:
        text = lead + "\n\n" + text
    return text


def product_photo(product: dict) -> str | None:
    """Accept admin website uploads and Telegram photos without manual conversion.

    A web replacement takes precedence over a legacy Telegram file_id. Bot
    photo edits clear image_url, so the latest bot upload also takes effect.
    """
    ref = (product.get("image_url") or product.get("photo_id") or "").strip()
    if ref.startswith("/"):
        return urljoin(WEBAPP_URL, ref) if WEBAPP_URL else None
    return ref or None


def _telegram_length(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


async def _send_with_retry(send, *args, **kwargs):
    # Retry the individual request, never an already partially delivered card.
    try:
        return await send(*args, **kwargs)
    except TelegramRetryAfter as exc:
        await asyncio.sleep(exc.retry_after + 1)
        return await send(*args, **kwargs)


async def send_product_message(bot: Bot, chat_id: int, product: dict,
                               text: str, keyboard):
    """Photo caption when it fits; otherwise photo + complete text and buttons.

    Extremely long cards are split as plain text to avoid cutting HTML tags.
    The actionable keyboard stays on the final message, next to the price.
    """
    plain = strip_markup(text)
    photo = product_photo(product)
    in_caption = _telegram_length(plain) <= 1024
    if photo:
        try:
            sent = await _send_with_retry(bot.send_photo,
                chat_id, photo=photo, caption=text if in_caption else None,
                reply_markup=keyboard if in_caption else None, parse_mode="HTML")
        except TelegramBadRequest:
            logger.warning("Product %s photo rejected; sending complete text", product.get("id"))
        else:
            if in_caption:
                return sent

    if _telegram_length(plain) <= 4096:
        return await _send_with_retry(bot.send_message, chat_id, text, reply_markup=keyboard,
                                      parse_mode="HTML", disable_web_page_preview=True)

    parts, start, size = [], 0, 0
    for index, char in enumerate(plain):
        width = 2 if ord(char) > 0xFFFF else 1
        if size + width > 4096:
            parts.append(plain[start:index])
            start, size = index, 0
        size += width
    parts.append(plain[start:])
    for index, part in enumerate(parts):
        sent = await _send_with_retry(bot.send_message,
            chat_id, part, reply_markup=keyboard if index == len(parts) - 1 else None,
            parse_mode=None, disable_web_page_preview=True)
    return sent


async def detail_keyboard(user_id: int, product_id: int, back_category: str,
                          back_page: int, lang: str, out_of_stock: bool,
                          keep: bool = False) -> InlineKeyboardMarkup:
    """Primary row (add / stepper / soon), reviews row, cart shortcut, back row.
    Shared by the first render and the +/- handlers, so a step click just swaps
    reply_markup — no need to re-send the photo."""
    _cart_id, cart_qty = await get_cart_line_for_product(user_id, product_id)
    ret = f":{back_category}:{back_page}"
    shelf = None
    if out_of_stock:
        raw = await database.get_product(product_id)
        shelf = float((raw or {}).get("quantity") or 0)
    if out_of_stock and shelf and shelf > 0:
        # On the shelf, but every piece is in other buyers' carts (Savat
        # broni): "⏳ band", not sold out — and the buyer may wait for the
        # hold to run out (owner, 2026-10-16), restock_notify.py tells them.
        waiting = await database.is_waiting_restock(user_id, product_id)
        primary_row = [InlineKeyboardButton(
            text=get_text("btn_held_waiting" if waiting else "btn_held_wait", lang),
            callback_data=f"restock_wait:{product_id}{ret}")]
    elif out_of_stock:
        # Sold out: "tell me when it's back" (owner, 2026-10-14), or the
        # promise once they asked — restock_notify.py sends the message.
        waiting = await database.is_waiting_restock(user_id, product_id)
        primary_row = [InlineKeyboardButton(
            text=get_text("btn_restock_waiting" if waiting else "btn_restock_wait", lang),
            callback_data=f"restock_wait:{product_id}{ret}")]
    elif cart_qty > 0:
        qty_str = str(int(cart_qty)) if float(cart_qty).is_integer() else f"{cart_qty:.1f}"
        primary_row = [
            InlineKeyboardButton(text="➖", callback_data=f"detail_dec:{product_id}{ret}"),
            InlineKeyboardButton(text=get_text("btn_in_cart_qty", lang, n=qty_str), callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data=f"detail_inc:{product_id}{ret}"),
        ]
    else:
        primary_row = [InlineKeyboardButton(text=get_text("btn_add_to_cart", lang),
                                            callback_data=f"detail_inc:{product_id}{ret}")]

    cart_count, cart_total = await get_cart_badge(user_id)
    cart_row = cart_shortcut_row(lang, cart_count, cart_total)

    # A card the shop SENT (the daily spotlight, a channel link) is the
    # buyer's own message history — «Orqaga» must not delete it the way it
    # does for a card they opened themselves while browsing. `catalog_keep`
    # opens the catalogue in a new message and leaves the card where it is.
    back_cb = f"cat:{back_category}:{back_page}" if back_category else (
        "catalog_keep" if keep else "catalog")
    rows = [primary_row, [InlineKeyboardButton(text=get_text("btn_reviews", lang),
                                               callback_data=f"reviews:{product_id}")]]
    if cart_row:
        rows.append(cart_row)
    rows.append([InlineKeyboardButton(text=get_text("btn_back", lang), callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def mark_held(text: str, product: dict, lang: str) -> str:
    """Savat broni (2026-10-13): a product whose last pieces all sit in other
    buyers' carts (database.apply_holds → held_out) is "⏳ band", not sold
    out — it may come back within the hold (database.RESERVE_HOURS). Swaps
    the card's sold-out note for the band note, whichever sold-out wording
    the card used."""
    if not product.get("held_out"):
        return text
    from locales import TEXTS
    held = get_text("product_held_out", lang, hours=database.RESERVE_HOURS)
    for key in [k for k in TEXTS if k.startswith("product_out_of_stock")]:
        note = get_text(key, lang)
        if note and note in text:
            return text.replace(note, held)
    return f"{text}\n\n{held}"


async def send_card(bot: Bot, chat_id: int, product: dict, lang: str,
                    rate: float | None = None, back_category: str = "",
                    back_page: int = 0, caption: str | None = None):
    """Send the full card into a private chat: photo + caption + live keyboard.
    Used by the daily spotlight and by the channel's «Botda sotib olish» link.
    `caption` lets a broadcast hand in a pre-built text — see CaptionCache."""
    import gamification
    if rate is None:
        rate = await gamification.buyer_rate(chat_id)
    # What this buyer can still take — other buyers' carts hold the rest.
    product = (await database.apply_holds([product], chat_id))[0]
    if caption is None:
        caption = mark_held(await build_caption(product, lang, rate), product, lang)
    keyboard = await detail_keyboard(chat_id, product["id"], back_category, back_page,
                                     lang, product["quantity"] <= 0, keep=True)
    return await send_product_message(bot, chat_id, product, caption, keyboard)


class CaptionCache:
    """One product's caption, per (language, cashback rate).

    A broadcast of the same product to thousands of buyers would otherwise
    re-read the active aksiya and the product's rating once per recipient for
    a text that only ever differs by those two things — and there are at most
    a handful of combinations (3 languages x 4 Keto levels).
    """

    def __init__(self, product: dict, extra_for=None):
        self.product = product
        # Called per language to produce the trailing block (the daily
        # spotlight's "what to make with this today"). A callable rather than
        # a string because the block is language-specific, and part of the
        # cache key so the first recipient's text is not served to everyone.
        self.extra_for = extra_for
        self._texts: dict[tuple[str, float | None], str] = {}

    async def get(self, lang: str, rate: float | None) -> str:
        key = (lang, rate)
        if key not in self._texts:
            extra = self.extra_for(lang) if self.extra_for else None
            self._texts[key] = await build_caption(self.product, lang, rate, extra)
        return self._texts[key]


# ─────────────────────── the channel post's deep link ───────────────────────
# A channel post can't carry callback buttons that mean anything to a reader
# who has never opened the bot, so it carries one url button instead:
# t.me/<bot>?start=prod_<id>, which lands them on this very card in private.
PAYLOAD_PREFIX = "prod_"


def product_link(product_id: int) -> str:
    from config import BOT_USERNAME
    return f"https://t.me/{BOT_USERNAME}?start={PAYLOAD_PREFIX}{product_id}"


def parse_product_payload(payload: str | None) -> int | None:
    """'prod_42' -> 42. None for every other /start payload, so the caller
    falls through to the blogger/ad/referral readers."""
    if not payload:
        return None
    raw = payload.strip().lower()
    if not raw.startswith(PAYLOAD_PREFIX):
        return None
    tail = raw[len(PAYLOAD_PREFIX):]
    return int(tail) if tail.isdigit() else None


async def open_from_link(bot: Bot, user_id: int, product_id: int, lang: str) -> bool:
    """Open the card a channel reader tapped through to. False when the
    product is gone — the caller then just leaves them on the menu."""
    product = await database.get_product(product_id)
    if not product or not product.get("is_active"):
        return False
    try:
        await send_card(bot, user_id, product, lang)
        await database.add_product_view(product_id, user_id)
        return True
    except Exception:
        logger.warning("prod_ deep link for %s failed", product_id, exc_info=True)
        return False
