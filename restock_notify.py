"""
Qaytdi eslatmasi — "tell me when it's back" for sold-out products (2026-10-14).

Owner's ask: sold-out products stay in the shop and can't be ordered, but a
buyer who wanted one and found it gone hears from us once it is restocked —
"Siz qiziqqan mahsulot do'konimizga qaytdi".

How a buyer asks:
  * bot: the sold-out card's main button "🔔 Kelganda menga xabar bering"
    (callback restock_wait:PID:BACK_CAT:PAGE — product_card.detail_keyboard);
  * Mini App: the same button in the product sheet (POST /api/restock-wait).
Either way one open row lands in restock_waitlist; asking twice is a no-op.

Since 2026-10-16 the same list covers a product whose last pieces sit in other
buyers' carts (Savat broni, "⏳ band"): the band card offers "🔔 Bo'shasa xabar
bering", and a buyer whose add-to-cart was refused because of a hold is put
on the list by itself (cart_reservations.limit_text, the Mini App, the AI
seller). When the hold runs out they hear "siz so'ragan mahsulot sotuvga
qaytdi" (owner: "so'ragan odamga push borsin").

How they hear back: a sweep every 10 minutes finds open waits whose product
is active and has stock again, and sends each buyer the product card with a
"siz qiziqqan mahsulot qaytdi" headline and a live add-to-cart button. The
wait is marked told BEFORE sending, so a restart can't send it twice; after
that the buyer may ask again the next time the product sells out.

Rules:
  * quiet hours 21:00–09:00 Tashkent — a product restocked in the evening is
    announced in the morning (if it is still in stock by then);
  * the buyer's own language (users.language, else the one they asked in);
  * banned buyers are skipped;
  * every admin gets one line per product: who was waiting and how many were
    told, so the owner sees the feature work.

Watching stock this way (polling the waitlist against products.quantity)
catches every restock path — the admin site, the bot's product editor, an
order cancelled back into stock — without hooking into any of them.
"""
import asyncio
import html
import logging
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import CallbackQuery

import database
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router()

TZ_OFFSET = timedelta(hours=5)
CHECK_EVERY = 600                 # 10 min
QUIET_START, QUIET_END = 21, 9    # no messages 21:00–09:00 Tashkent
SEND_DELAY = 0.05


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


def _quiet_now() -> bool:
    h = _now_tk().hour
    return h >= QUIET_START or h < QUIET_END


# ─────────────────────────────── asking ─────────────────────────────────────

async def subscribe(user_id: int, product_id: int, lang: str, source: str) -> str:
    """Put the buyer on the list. Returns:
    "added" | "already" | "in_stock" (nothing to wait for) | "not_found".

    Waiting works for a sold-out product and for one whose last pieces sit in
    other buyers' carts (Savat broni, 2026-10-16) — that wait is kept as
    source "held" and is told "siz so'ragan mahsulot sotuvga qaytdi" when the
    hold runs out."""
    product = await database.get_product(product_id)
    if not product or not product.get("is_active") or product.get("b2b_only"):
        return "not_found"
    if float(product.get("quantity") or 0) > 0:
        if (await database.stock_view([product_id], user_id))[product_id]["free"] > 0:
            return "in_stock"
        source = "held"
    if await database.add_restock_wait(user_id, product_id, lang, source):
        return "added"
    return "already"


@router.callback_query(F.data.startswith("restock_wait:"))
async def restock_wait_button(callback: CallbackQuery):
    """The sold-out card's "🔔 Kelganda menga xabar bering" button."""
    from locales import get_text
    from product_card import detail_keyboard

    parts = callback.data.split(":")
    try:
        product_id = int(parts[1])
    except (IndexError, ValueError):
        await callback.answer()
        return
    back_category = parts[2] if len(parts) > 2 else ""
    try:
        back_page = int(parts[3]) if len(parts) > 3 else 0
    except ValueError:
        back_page = 0

    user_id = callback.from_user.id
    lang = await database.get_user_language(user_id)
    status = await subscribe(user_id, product_id, lang, "bot")
    if status == "not_found":
        await callback.answer()
        return
    key = {"added": "restock_wait_added", "already": "restock_wait_already",
           "in_stock": "restock_wait_in_stock"}[status]
    await callback.answer(get_text(key, lang), show_alert=True)

    # Repaint the card's buttons: the promise, or add-to-cart if it's back.
    product = await database.get_product(product_id)
    if not product:
        return
    product = (await database.apply_holds([product], user_id))[0]   # what this buyer can take
    try:
        kb = await detail_keyboard(user_id, product_id, back_category, back_page, lang,
                                   float(product.get("quantity") or 0) <= 0,
                                   keep=not back_category)
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        pass            # "message is not modified", or the bubble is gone


# ─────────────────────────────── telling ────────────────────────────────────

async def _send_card(bot: Bot, user_id: int, product: dict, lang: str, source: str | None = None) -> bool:
    """The product card with the "qaytdi" headline on top. True = delivered.
    A wait for a product held in another cart gets its own headline: it
    didn't come back from the warehouse, a cart let it go."""
    import gamification
    from locales import get_text
    from product_card import build_caption, detail_keyboard, send_product_message

    rate = await gamification.buyer_rate(user_id)
    lead = (get_text("restock_held_lead", lang, hours=database.RESERVE_HOURS) if source == "held"
            else get_text("restock_back_lead", lang))
    caption = await build_caption(product, lang, rate, lead=lead)
    keyboard = await detail_keyboard(user_id, product["id"], "", 0, lang, False, keep=True)
    try:
        # The shop's card sender: photo caption when it fits, otherwise
        # photo + complete text — a long card is never refused.
        await send_product_message(bot, user_id, product, caption, keyboard)
        return True
    except (TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter):
        return False                # blocked the bot / never pressed START
    except Exception:
        logger.exception("Restock notice to %s failed", user_id)
        return False


def admin_line(product: dict, sent: int, failed: int) -> str:
    name = html.escape(product.get("name") or f"#{product.get('id')}")
    text = (f"🔔 <b>«{name}» qaytdi</b> — uni kutgan {sent + failed} ta mijozga "
            f"«siz qiziqqan mahsulot qaytdi» xabari ketdi.")
    if failed:
        text += f"\n({sent} tasiga yetib bordi, {failed} tasi botni bloklagan yoki START bosmagan.)"
    return text


async def run_once(bot: Bot) -> dict:
    """One pass: tell everyone whose product is back. Counters for logs/tests."""
    stats = {"sent": 0, "failed": 0, "skipped": 0}
    if _quiet_now():
        return stats
    due = await database.get_restock_due()
    if not due:
        return stats

    langs = await database.get_user_languages({w["user_id"] for w in due})
    by_product: dict[int, list[dict]] = {}
    for w in due:
        by_product.setdefault(w["product_id"], []).append(w)

    for product_id, waits in by_product.items():
        product = await database.get_product(product_id)
        if not product or float(product.get("quantity") or 0) <= 0:
            stats["skipped"] += len(waits)      # sold out again since the query
            continue
        sent = failed = 0
        for w in waits:
            # Free for THIS buyer — shelf minus what other carts hold right now.
            view = await database.stock_view([product_id], w["user_id"])
            if view[product_id]["free"] <= 0:
                stats["skipped"] += 1           # another cart took it since the query
                continue
            if not await database.claim_restock_notice(w["id"]):
                stats["skipped"] += 1           # another pass got here first
                continue
            lang = langs.get(w["user_id"]) or w.get("lang") or "uz"
            if await _send_card(bot, w["user_id"], product, lang, w.get("source")):
                sent += 1
            else:
                failed += 1
            await asyncio.sleep(SEND_DELAY)
        stats["sent"] += sent
        stats["failed"] += failed
        if sent or failed:
            await _tell_admins(bot, admin_line(product, sent, failed))
    return stats


async def _tell_admins(bot: Bot, text: str) -> None:
    import admin_mood
    for admin_id in ADMIN_IDS:
        try:
            with admin_mood.quiet():
                await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception as exc:
            logger.warning("Restock admin note to %s failed: %s", admin_id, exc)


async def scheduler_loop(bot: Bot) -> None:
    logger.info("Restock notice scheduler started")
    while True:
        try:
            stats = await run_once(bot)
            if stats["sent"] or stats["failed"]:
                logger.info("Restock notices: %s", stats)
        except Exception:
            logger.exception("Restock notice tick failed")
        await asyncio.sleep(CHECK_EVERY)
