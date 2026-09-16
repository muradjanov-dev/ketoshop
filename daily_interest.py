"""
Kunlik qiziqish eslatmasi — daily interest reminder (2026-09-01).

The admin dashboard's "Eng faol foydalanuvchilar … Qiziqishi: <mahsulot>"
column already knows what each person keeps coming back to look at. This
turns that into an outbound nudge: once a day, everyone we know an interest
for gets ONE message about that exact product — what it is, what it costs,
why it's good for them, and, when that product happens to trigger a bonus in
the running aksiya, the aksiya offer on top (owner request: "har kuni o'sha
maxsulotni va foydalarini eslatib xabar yubor va agar bu maxsulotlar aksiyada
bo'lsa unda aksiyani ham eslat").

Interest = their most-viewed product in the last 30 days (all-time as a
fallback), re-ranked on every send — so the nudge follows them as their
browsing moves on, rather than freezing on whatever they opened once.

The benefit copy is NOT a new content library: it reuses the product profiles
personal_recommend.py already maintains (bodom uni, kokos, yog'lar, shirin-
lashtirgichlar …), rotated by day so the same product doesn't read identically
two days running.

Where it sits in the day (all Asia/Tashkent):
    08:00  tips broadcast, every 2 days           (broadcast.py)
    10:00  personal recommendations, every 2 days (personal_recommend.py)
    12:00  aksiya "bugungi sovg'alar", daily      (promotions.py)
    18:00  THIS — daily, unless TWO of the above already went out today.
           A veto on "anything else went out" would have made it dead code,
           since the showcase runs every day; the cap is what keeps a buyer
           from ever seeing more than two pushes in a day.

Public API:
  build_message(product, lang, cycle, promo) -> (text, keyboard) | (None, None)
  send_batch(bot, only_user=None)            -> (sent, failed, skipped)
  scheduler_loop(bot)                        -> runs forever
"""
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import database
from config import ADMIN_IDS
from locales import localize_product_text

logger = logging.getLogger(__name__)

TZ_OFFSET = timedelta(hours=5)   # Asia/Tashkent, fixed UTC+5, no DST
SEND_HOUR = 18                   # 18:00 — clear of tips (08), reco (10), showcase (12)
CHECK_EVERY = 900                # re-check every 15 minutes
SEND_DELAY = 0.05                # ~20 msgs/sec, under Telegram's limits
RECENT_DAYS = 30                 # window that defines "current interest"

# Rotating openers, so a daily message about the same product doesn't read
# word-for-word identical every time.
_INTROS = [
    {"uz": "👀 Siz qiziqqan mahsulot:", "ru": "👀 Товар, которым вы интересовались:"},
    {"uz": "💚 Bu mahsulot hali ham sizni kutmoqda:", "ru": "💚 Этот товар всё ещё ждёт вас:"},
    {"uz": "⭐ Eslatib o'tamiz:", "ru": "⭐ Напоминаем:"},
    {"uz": "🔎 Siz ko'rib chiqqan mahsulot:", "ru": "🔎 Товар, который вы смотрели:"},
    {"uz": "🌿 Sizga mos mahsulot:", "ru": "🌿 Товар, который вам подходит:"},
    {"uz": "🛍 Tanlovingizni eslatib qo'yamiz:", "ru": "🛍 Напоминаем о вашем выборе:"},
]

_BENEFIT_LABEL = {"uz": "💡 <b>Foydasi:</b>", "ru": "💡 <b>Польза:</b>"}
_PRICE_LABEL = {"uz": "💰 Narxi:", "ru": "💰 Цена:"}
_OUT_OF_STOCK = {"uz": "⏳ Hozircha tugagan — tez orada qaytadi.",
                 "ru": "⏳ Пока закончился — скоро вернётся."}


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


def _fmt(n) -> str:
    return f"{int(n or 0):,}".replace(",", " ")


def _loc(entry: dict, lang: str) -> str:
    """uz/ru from a {uz, ru} pair, transliterating for Cyrillic Uzbek — the
    same convention personal_recommend uses for its own content."""
    if lang == "ru":
        return entry.get("ru") or entry.get("uz", "")
    text = entry.get("uz", "")
    if lang == "uz_cyr" and text:
        from translit import lat_to_cyr
        return lat_to_cyr(text)
    return text


def build_message(product: dict, lang: str, cycle: int, promo: dict | None):
    """(text, keyboard) for one person's daily nudge, or (None, None) when
    there's nothing worth sending (no product)."""
    import promotions
    from personal_recommend import _profile_for

    if not product:
        return None, None

    name = localize_product_text(product.get("name"), product.get("name_ru"), lang)
    profile = _profile_for(product.get("name") or "")
    emoji = profile.get("emoji", "🌿")

    discount = database.active_discount(product.get("discount_percent"), product.get("discount_until"))
    price = database.effective_price(product["price"], discount, product.get("discount_until"))

    lines = [_loc(_INTROS[cycle % len(_INTROS)], lang), "", f"{emoji} <b>{name}</b>"]

    currency = "сум" if lang == "ru" else "so'm"
    price_label = _PRICE_LABEL["ru" if lang == "ru" else "uz"]
    price_line = f"{price_label} <b>{_fmt(price)} {currency}</b>"
    if discount:
        price_line += f"  <s>{_fmt(product['price'])}</s>  🔥−{int(discount)}%"
    lines.append(price_line)
    if float(product.get("quantity") or 0) <= 0:
        lines.append(_loc(_OUT_OF_STOCK, lang))

    # The aksiya reminder, but only when THIS product is the one that triggers
    # a bonus — a generic "there's a campaign on" line would be noise.
    hint = promotions.bonus_hint(promo, product["id"], lang)
    if hint:
        promo_name = promotions.promo_name(promo, lang)
        lines.append("")
        lines.append(f"🎉 <b>{promo_name}</b>")
        lines.append(hint)

    benefits = profile.get("benefits") or []
    if benefits:
        lines.append("")
        lines.append(_BENEFIT_LABEL["ru" if lang == "ru" else "uz"])
        lines.append(_loc(benefits[cycle % len(benefits)], lang))

    rows = [[InlineKeyboardButton(
        text="🛒 Mahsulotni ko'rish" if lang != "ru" else "🛒 Смотреть товар",
        callback_data=f"product:{product['id']}",
    )]]
    if hint:
        rows.append([InlineKeyboardButton(
            text="🎁 Aksiya shartlari" if lang != "ru" else "🎁 Условия акции",
            callback_data="promo",
        )])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def send_batch(bot: Bot, only_user: int | None = None) -> tuple[int, int, int]:
    """Send everyone their own nudge. `only_user` previews it for one person
    (admin /qiziqish_test) without touching any bookkeeping.
    Returns (sent, failed, skipped)."""
    import promotions

    promo = await promotions.get_active()
    state = await database.get_interest_state()
    cycle = int(state.get("cycle") or 0)

    if only_user is not None:
        user_ids = [only_user]
    else:
        user_ids = await database.get_user_ids_with_views(RECENT_DAYS)
        # A buyer who got a personal qayta-sotuv message today (retention.py,
        # 09:30) has had their push for the day.
        import retention
        heard = await retention.recently_messaged_ids()
        user_ids = [u for u in user_ids if u not in heard]

    # One query for the whole audience instead of a SELECT * per recipient.
    langs = await database.get_user_languages(user_ids)

    sent = failed = skipped = 0
    for uid in user_ids:
        try:
            products = await database.get_user_top_viewed_products(uid, limit=1, recent_days=RECENT_DAYS)
            if not products:
                skipped += 1
                continue
            lang = langs.get(uid, "uz")
            text, keyboard = build_message(products[0], lang, cycle, promo)
            if not text:
                skipped += 1
                continue
            try:
                await bot.send_message(uid, text, parse_mode=ParseMode.HTML,
                                        disable_web_page_preview=True, reply_markup=keyboard)
                sent += 1
            except TelegramRetryAfter as exc:
                await asyncio.sleep(exc.retry_after + 1)
                await bot.send_message(uid, text, parse_mode=ParseMode.HTML,
                                        disable_web_page_preview=True, reply_markup=keyboard)
                sent += 1
            except (TelegramForbiddenError, TelegramBadRequest):
                failed += 1      # blocked the bot / never started it
        except Exception:
            logger.exception("Daily interest nudge failed for user %s", uid)
            failed += 1
        await asyncio.sleep(SEND_DELAY)

    return sent, failed, skipped


MAX_PUSHES_PER_DAY = 2


async def _pushes_today(today) -> list[str]:
    """Which other broadcasts have already reached everyone today.

    The rule this feeds is a CAP, not a veto: the aksiya showcase runs every
    single day, so standing down whenever anything else had gone out would
    have kept this nudge permanently dormant (caught on the first deploy).
    Two pushes in a day is the ceiling — beyond that people mute the bot."""
    out = []
    try:
        tips = await database.get_broadcast_state()
        last = (tips or {}).get("last_sent_at")
        if last and (last + TZ_OFFSET).date() == today:
            out.append("tips")
    except Exception:
        logger.exception("Could not read broadcast state")
    try:
        reco = await database.get_reco_state()
        last = (reco or {}).get("last_sent_at")
        if last and (last + TZ_OFFSET).date() == today:
            out.append("reco")
    except Exception:
        logger.exception("Could not read reco state")
    try:
        import promotions
        promo = await promotions.get_active()
        if promo and promo.get("last_showcase_date") == today:
            out.append("aksiya showcase")
    except Exception:
        logger.exception("Could not read showcase state")
    return out


async def _tick(bot: Bot) -> None:
    state = await database.get_interest_state()
    if not state.get("enabled"):
        return

    now_tk = _now_tk()
    if now_tk.hour < SEND_HOUR:
        return
    today = now_tk.date()
    if state.get("last_sent_date") == today:
        return

    others = await _pushes_today(today)
    if len(others) >= MAX_PUSHES_PER_DAY:
        # Claim the day anyway, so tomorrow starts clean instead of this
        # firing the moment the other broadcasts' guards stop matching.
        await database.advance_interest(today, int(state.get("cycle") or 0))
        logger.info("Interest nudge skipped: %s already went out today", ", ".join(others))
        return

    # Claim the day BEFORE sending: a crash halfway through a fan-out must
    # not re-send to everyone who already got it on the next tick.
    await database.advance_interest(today, int(state.get("cycle") or 0) + 1)
    sent, failed, skipped = await send_batch(bot)
    logger.info("Daily interest nudge: %d sent, %d failed, %d skipped", sent, failed, skipped)

    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"📤 <b>Kunlik qiziqish eslatmasi yuborildi</b>\n"
                f"✅ {sent} ta yetkazildi · ⚠️ {failed} ta yetmadi · ⏭ {skipped} ta o'tkazildi",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


async def scheduler_loop(bot: Bot) -> None:
    logger.info("Daily interest scheduler started (%02d:00 Asia/Tashkent)", SEND_HOUR)
    while True:
        try:
            await _tick(bot)
        except Exception:
            logger.exception("Daily interest tick failed")
        await asyncio.sleep(CHECK_EVERY)
