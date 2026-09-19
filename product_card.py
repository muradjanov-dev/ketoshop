"""
The product card — one format, in every place a product is shown.

The catalog's detail bubble, the daily "Kun mahsuloti" broadcast and the
channel post all render the same caption (name, description, price, unit,
stock, discount, Keto cashback, aksiya bonus, rating) and the same keyboard.
It used to live inside handlers/catalog.py; it moved here the day the daily
spotlight started sending the very same card, so the two can never drift.
"""
import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import database
from database import (
    active_discount, effective_price, get_cart_badge, get_cart_line_for_product,
    get_product_rating,
)
from keyboards import cart_shortcut_row
from locales import get_text, get_display_unit, localize_product_text

logger = logging.getLogger(__name__)

# Longest description that still leaves room for the rest of the card inside
# Telegram's 1024-character photo caption.
DESC_IN_CARD_MAX = 650


async def build_caption(product: dict, lang: str, rate: float | None,
                        extra: str | None = None) -> str:
    """The card's text. `rate` is the Keto cashback to advertise (None = don't
    show that line at all); callers pass gamification.buyer_rate(user) for a
    buyer, or the base rate for an audience with no single reader.

    `extra` is appended at the end — the daily spotlight uses it for "what to
    make with this today" (product_ideas). It is budgeted against the same
    1024-character caption limit, so a long idea shortens the description
    rather than pushing the price off the card.
    """
    import gamification
    import gift_campaign
    import mystery_gift
    import promotions

    # The three standing promises close every card (owner, 2026-09-19): the
    # Eritritol on every order, the surprise from 400 000, free Tashkent
    # delivery from 800 000. Built first because, like `extra`, their length
    # is budgeted before the description is trimmed — the promises are the
    # reason to order, so they never lose room to a long description.
    gift = "\n".join(filter(None, [
        await gift_campaign.card_line(lang),
        mystery_gift.card_line(lang),
        mystery_gift.free_delivery_card_line(lang),
    ]))

    seller_name = product.get("seller_name") or product.get("seller_username") or "—"
    name = localize_product_text(product.get("name"), product.get("name_ru"), lang)
    desc = localize_product_text(product.get("description"), product.get("description_ru"), lang) or "—"
    # Trim here, not in tg_safety's net: that would save the message by
    # dropping the price lines below instead of the tail of the description.
    desc_budget = DESC_IN_CARD_MAX - (len(extra) + 2 if extra else 0) \
                                   - (len(gift) + 2 if gift else 0)
    if len(desc) > desc_budget:
        desc = desc[: max(40, desc_budget - 1)].rstrip() + "…"

    discount_until = product.get("discount_until")
    discount = active_discount(product.get("discount_percent"), discount_until)
    final_price = effective_price(product["price"], discount, discount_until)

    text = get_text("product_card", lang,
        name=name,
        description=desc,
        price=f"{int(final_price):,}".replace(",", " "),
        unit=get_display_unit(product["unit"], lang),
        available=product["quantity"],
        seller=seller_name,
    )

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

    if product["quantity"] <= 0:
        text += "\n\n" + get_text("product_out_of_stock", lang)

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

    return text


async def detail_keyboard(user_id: int, product_id: int, back_category: str,
                          back_page: int, lang: str, out_of_stock: bool,
                          keep: bool = False) -> InlineKeyboardMarkup:
    """Primary row (add / stepper / soon), reviews row, cart shortcut, back row.
    Shared by the first render and the +/- handlers, so a step click just swaps
    reply_markup — no need to re-send the photo."""
    _cart_id, cart_qty = await get_cart_line_for_product(user_id, product_id)
    ret = f":{back_category}:{back_page}"
    if out_of_stock:
        primary_row = [InlineKeyboardButton(text=get_text("btn_coming_soon", lang), callback_data="noop")]
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


async def send_card(bot: Bot, chat_id: int, product: dict, lang: str,
                    rate: float | None = None, back_category: str = "",
                    back_page: int = 0, caption: str | None = None):
    """Send the full card into a private chat: photo + caption + live keyboard.
    Used by the daily spotlight and by the channel's «Botda sotib olish» link.
    `caption` lets a broadcast hand in a pre-built text — see CaptionCache."""
    import gamification
    if rate is None:
        rate = await gamification.buyer_rate(chat_id)
    if caption is None:
        caption = await build_caption(product, lang, rate)
    keyboard = await detail_keyboard(chat_id, product["id"], back_category, back_page,
                                     lang, product["quantity"] <= 0, keep=True)
    if product.get("photo_id"):
        return await bot.send_photo(chat_id, photo=product["photo_id"], caption=caption,
                                    reply_markup=keyboard, parse_mode="HTML")
    return await bot.send_message(chat_id, caption, reply_markup=keyboard,
                                  parse_mode="HTML", disable_web_page_preview=True)


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
