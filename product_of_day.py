"""
Kun mahsuloti — one product a day, to every buyer and to the channel.

Each day at SEND_HOUR Tashkent time the shop spotlights a single product: the
exact same card the catalogue shows (photo, description, price, stock, Keto
cashback, aksiya bonus, rating — see product_card.py), with working
«Savatga qo'shish» / «Sharhlar» / cart buttons, so a buyer orders straight
from the broadcast without opening the catalogue.

The same card goes to the channel at the same moment, in Cyrillic (owner,
2026-09-19), where a callback button would be meaningless — it carries one
url button instead, t.me/<bot>?start=prod_<id>, which lands the reader on
this very card in private (see product_card.open_from_link).

Which product: every eligible product gets exactly one turn per cycle, and
within a cycle the most promising go first — discounted, most-viewed and
best-selling first, nearly-out-of-stock last. Once every product has had its
turn the cycle rolls over and the ranking is recomputed from fresh numbers.
State lives in the DB, so restarts and redeploys can't repeat a day.

Language: every buyer reads it in their own (users.language), same rule as
the rest of the bot.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramBadRequest,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import database
import product_card
from config import ADMIN_IDS, REQUIRED_CHANNEL_ID

logger = logging.getLogger(__name__)

# Asia/Tashkent is a fixed UTC+5 offset (no DST) — avoid a tzdata dependency.
TZ_OFFSET = timedelta(hours=5)
SEND_HOUR = 13          # 13:00 Tashkent (owner's pick: lunchtime)
CHECK_EVERY = 900       # re-check every 15 minutes
SEND_DELAY = 0.05       # ~20 sends/sec, under Telegram's broadcast limit

# The channel reads Cyrillic (owner, 2026-09-19) — the personal messages
# still follow each buyer's own users.language.
CHANNEL_LANG = "uz_cyr"

_CHANNEL_BUTTON = {
    "uz": "🛒 Botda sotib olish",
    "ru": "🛒 Купить в боте",
}


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


# ───────────────────────────── choosing today's ─────────────────────────────

def score(product: dict, sold_month: dict[int, float]) -> float:
    """How strong a spotlight this product makes today. Attention and proven
    sales pull it forward, a deep discount more so; a nearly-empty shelf pushes
    it back — a spike on three units left is a cancelled order, not a sale."""
    qty = float(product.get("quantity") or 0)
    views = float(product.get("views_30d") or 0)
    sold = float(sold_month.get(product["id"], 0))

    s = min(views / 5.0, 4.0) + min(sold / 3.0, 3.0)
    if database.active_discount(product.get("discount_percent"),
                                product.get("discount_until")) > 0:
        s += 3.0
    if qty >= 10:
        s += 1.0
    elif qty < 3:
        s -= 2.0
    if product.get("photo_id"):
        s += 0.5          # a card without a photo sells far worse
    return s


async def pick_product() -> tuple[dict | None, int]:
    """Today's product and the cycle it belongs to. The cycle rolls over when
    every eligible product has already had its turn."""
    state = await database.get_product_of_day_state()
    cycle = int(state["cycle"])
    candidates = await database.get_product_of_day_candidates(cycle)
    if not candidates:
        cycle = await database.bump_product_of_day_cycle()
        candidates = await database.get_product_of_day_candidates(cycle)
    if not candidates:
        return None, cycle

    try:
        top = await database.get_top_products("30d", limit=500)
        sold_month = {t["product_id"]: t["qty"] for t in top}
    except Exception:
        logger.warning("Spotlight: monthly sales lookup failed", exc_info=True)
        sold_month = {}

    best = max(candidates, key=lambda p: (score(p, sold_month), p.get("views_30d") or 0, -p["id"]))
    return best, cycle


# ──────────────────────────────── sending ───────────────────────────────────

async def _send_to_user(bot: Bot, user_id: int, product: dict, lang: str,
                        captions: product_card.CaptionCache) -> bool:
    import gamification
    rate = await gamification.buyer_rate(user_id)
    caption = await captions.get(lang, rate)
    try:
        await product_card.send_card(bot, user_id, product, lang, rate=rate, caption=caption)
        return True
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        try:
            await product_card.send_card(bot, user_id, product, lang, rate=rate, caption=caption)
            return True
        except Exception:
            return False
    except (TelegramForbiddenError, TelegramBadRequest):
        # Blocked the bot / never started it / deactivated — skip quietly.
        return False
    except Exception:
        logger.exception("Spotlight send failed for user %s", user_id)
        return False


async def broadcast(bot: Bot, product: dict) -> tuple[int, int]:
    """Send the card to every eligible buyer, each in their own language."""
    user_ids = await database.get_all_user_ids()
    langs = await database.get_user_languages(user_ids)
    # "Bugun shundan nima tayyorlash mumkin" — one concrete idea under the
    # card. It is what turns a product announcement into something worth
    # reading, and it carries the product with it instead of selling it.
    import product_ideas
    name = product.get("name") or ""
    captions = product_card.CaptionCache(
        product, extra_for=lambda lang: product_ideas.idea_block(name, lang))
    sent = failed = 0
    for uid in user_ids:
        ok = await _send_to_user(bot, uid, product, langs.get(uid, "uz"), captions)
        sent += ok
        failed += not ok
        await asyncio.sleep(SEND_DELAY)
    return sent, failed


def channel_keyboard(product_id: int, lang: str = CHANNEL_LANG) -> InlineKeyboardMarkup:
    label = _CHANNEL_BUTTON["ru"] if lang == "ru" else _CHANNEL_BUTTON["uz"]
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        label = lat_to_cyr(label)
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, url=product_card.product_link(product_id))
    ]])


async def post_to_channel(bot: Bot, product: dict) -> bool:
    """The same card in the channel. Failure here never stops the broadcast —
    the channel is a bonus reach, the buyers are the point."""
    if not REQUIRED_CHANNEL_ID:
        return False
    import gamification
    try:
        # No single reader to rate, so the channel advertises the entry-level
        # cashback every buyer is guaranteed — never more than they'd get.
        rate = gamification.EARN_RATE if await gamification.is_enabled() else None
        import product_ideas
        caption = await product_card.build_caption(
            product, CHANNEL_LANG, rate,
            product_ideas.idea_block(product.get("name") or "", CHANNEL_LANG))
        markup = channel_keyboard(product["id"])
        if product.get("photo_id"):
            await bot.send_photo(REQUIRED_CHANNEL_ID, photo=product["photo_id"],
                                 caption=caption, reply_markup=markup,
                                 parse_mode=ParseMode.HTML)
        else:
            await bot.send_message(REQUIRED_CHANNEL_ID, caption, reply_markup=markup,
                                   parse_mode=ParseMode.HTML,
                                   disable_web_page_preview=True)
        return True
    except Exception:
        logger.exception("Spotlight channel post failed")
        return False


async def _notify_admins(bot: Bot, text: str):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception:
            pass


async def send_today(bot: Bot, day=None) -> dict | None:
    """Pick, post to the channel, broadcast, log. Returns a small summary, or
    None when there is nothing sendable (empty catalogue / everything out of
    stock). The day is stamped BEFORE the long broadcast, so a redeploy in the
    middle of one can't start it over."""
    product, cycle = await pick_product()
    if product is None:
        return None

    day = day or _now_tk().date()
    await database.record_product_of_day(product["id"], cycle, 0, 0, False, day)

    channel_ok = await post_to_channel(bot, product)
    sent, failed = await broadcast(bot, product)
    await database.record_product_of_day(product["id"], cycle, sent, failed, channel_ok, day)

    logger.info("Kun mahsuloti #%s '%s': %d ok, %d failed, channel=%s",
                product["id"], product.get("name"), sent, failed, channel_ok)
    return {"product": product, "cycle": cycle, "sent": sent,
            "failed": failed, "channel_ok": channel_ok}


async def _tick(bot: Bot):
    state = await database.get_product_of_day_state()
    if not state["enabled"]:
        return

    now_tk = _now_tk()
    if now_tk.hour < SEND_HOUR:
        return
    if state["last_sent_date"] == now_tk.date():
        return  # already went out today

    result = await send_today(bot, now_tk.date())
    if result is None:
        await _notify_admins(
            bot,
            "⚠️ <b>Kun mahsuloti yuborilmadi</b>\n"
            "Zaxirada bor mahsulot topilmadi — omborni to'ldiring.",
        )
        return

    p = result["product"]
    await _notify_admins(
        bot,
        f"📦 <b>Kun mahsuloti:</b> {p.get('name')}\n"
        f"✅ {result['sent']} ta yetkazildi, ⚠️ {result['failed']} ta yetmadi.\n"
        f"📣 Kanal: {'yuborildi' if result['channel_ok'] else 'yuborilmadi'}\n"
        f"🔄 Aylanma: {result['cycle'] + 1}-doira",
    )


async def scheduler_loop(bot: Bot):
    """Background task: every CHECK_EVERY seconds, is today's spotlight due?"""
    logger.info("Product-of-the-day scheduler started (%02d:00 Tashkent)", SEND_HOUR)
    while True:
        try:
            await _tick(bot)
        except Exception:
            logger.exception("Product-of-the-day tick failed")
        await asyncio.sleep(CHECK_EVERY)
