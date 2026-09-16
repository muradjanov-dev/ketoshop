"""
Personalized recipe & product-benefit recommendations.

Every 2 days each buyer who has an order history gets a *personal* bonus
message built from what THEY actually bought: a keto/PP recipe featuring their
products plus a short "why this product is good for you" note. No external ML
service — the recommendation is a content library keyed to product profiles,
matched against the buyer's order history and rotated over time so each send
differs.

Public API:
  build_personal_message(lang, orders, cycle) -> str | None
  scheduler_loop(bot)                          -> runs forever
  send_personal_batch(bot, only_user=None)     -> (sent, failed)

Language: content is authored in Uzbek (Latin) + Russian; Cyrillic Uzbek is
auto-transliterated from the Latin source, same as the rest of the bot.
"""
import asyncio
import hashlib
import html
import json
import logging
import re
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramBadRequest,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

import database
from config import ADMIN_IDS, WEBAPP_URL
from locales import get_text, localize_product_text

logger = logging.getLogger(__name__)


# Rotating framing lines for the browse-only (most-viewed-product) spotlight
# — added 2026-07-27 so buyers who've never ordered still get reached every
# 2 days, via what they've actually looked at rather than order history.
# The underlying product/description doesn't change often, so instead of
# content variants (like the order-based recipes) we rotate the intro line;
# once all are exhausted the never-repeat guarantee below just skips them
# that round, same as the order-based path.
_VIEW_INTROS = [
    {"uz": "👀 Diqqatingizni tortgan mahsulot:", "ru": "👀 Товар, который вас заинтересовал:"},
    {"uz": "🛍 Yana bir bor eslatib o'tamiz:", "ru": "🛍 Напоминаем ещё раз:"},
    {"uz": "⭐ Sizni kutayotgan mahsulot:", "ru": "⭐ Товар, который вас ждёт:"},
    {"uz": "💡 Ehtimol, sizga qiziq bo'lar:", "ru": "💡 Возможно, вам будет интересно:"},
    {"uz": "🔎 Ko'rib chiqqan mahsulotingiz:", "ru": "🔎 Товар, который вы просматривали:"},
]


def build_viewed_product_message(lang: str, product: dict, cycle: int) -> str:
    intro = _VIEW_INTROS[cycle % len(_VIEW_INTROS)][lang if lang == "ru" else "uz"]
    name = localize_product_text(product.get("name"), product.get("name_ru"), lang)
    desc = (localize_product_text(product.get("description"), product.get("description_ru"), lang) or "").strip()
    if len(desc) > 300:
        desc = desc[:300].rsplit(" ", 1)[0] + "…"

    discount = database.active_discount(product.get("discount_percent"), product.get("discount_until"))
    price = database.effective_price(product["price"], discount, product.get("discount_until"))
    price_str = f"{int(price):,}".replace(",", " ")
    price_line = f"💰 Narxi: <b>{price_str} so'm</b>" if lang != "ru" else f"💰 Цена: <b>{price_str} сум</b>"

    lines = [intro, f"<b>{html.escape(name)}</b>"]
    if desc:
        lines.append(html.escape(desc))
    lines.append(price_line)
    return "\n\n".join(lines)


def _product_button(product: dict, lang: str) -> "InlineKeyboardMarkup":
    text = "🛒 Mahsulotni ko'rish" if lang != "ru" else "🛒 Смотреть товар"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=text, callback_data=f"product:{product['id']}")
    ]])


# Same cadence conventions as the tips broadcaster, but a different hour so the
# two 2-day messages don't land on top of each other.
TZ_OFFSET = timedelta(hours=5)   # Asia/Tashkent, fixed UTC+5
SEND_HOUR = 10                   # 10:00 Tashkent (tips go at 08:00)
# Owner request (2026-07-04): personal recos NEVER land on a
# day the 2-day tips broadcast fired — if the days collide, we slip to the
# next day.
# Interval cut from 4 to 2 days on 2026-09-17 (owner request). Tips also run
# every 2 days, so the first send after the change may collide and slip one
# day — after that the two stay on opposite days and never meet again.
INTERVAL_DAYS = 2
CHECK_EVERY = 900                # re-check every 15 min
MAX_VARIANT_TRIES = 24           # rotation offsets to try before skipping a buyer
SEND_DELAY = 0.05                # ~20 msgs/sec, under Telegram limits


# ─────────────────────────────────────────────────────────────────────────────
# Content library
#
# Lives in reco_content.py — profiles for every product family the shop sells,
# combo recipes that need several of them at once, complementary-ingredient
# suggestions, and the message copy. Imported here rather than inlined so the
# shop owner can rewrite recipes without touching the scheduler.
# ─────────────────────────────────────────────────────────────────────────────
from reco_content import (
    PROFILES, DEFAULT_PROFILE, COMBOS, PAIRINGS, PAIRINGS_DEFAULT, LABELS,
    CATEGORY_GENERIC_PROFILES, CATEGORY_PROFILE_KEYS,
)

# Combos are matched most-specific-first: a buyer who orders almond flour,
# cocoa AND sweetener should get the brownie, not the two-ingredient cookie.
_COMBOS_BY_SPECIFICITY = sorted(COMBOS, key=lambda c: -len(c["needs"]))


# ─────────────────────────────────────────────────────────────────────────────
# Message building
# ─────────────────────────────────────────────────────────────────────────────
def _loc(entry: dict, lang: str, **fmt) -> str:
    """Pick uz/ru text from a {uz, ru} entry; transliterate for uz_cyr.

    Cyrillic-Uzbek buyers read the same Latin source, converted at render time
    — so every string in reco_content.py only ever has to be written twice
    (uz + ru), never three times. Formatting is applied BEFORE transliteration
    so interpolated names and counts are converted along with the copy."""
    if lang == "ru":
        text = entry.get("ru") or entry.get("uz", "")
        return text.format(**fmt) if fmt else text

    text = entry.get("uz", "")
    if fmt:
        text = text.format(**fmt)
    if lang == "uz_cyr" and text:
        from translit import lat_to_cyr
        text = lat_to_cyr(text)
    return text


def _aggregate_products(orders: list[dict]) -> list[tuple[str, float]]:
    """Sum ordered quantity per product name across the buyer's orders.
    Returns [(name, total_qty), …] sorted by qty desc."""
    totals: dict[str, float] = {}
    for o in orders:
        raw = o.get("items")
        if not raw:
            continue
        try:
            items = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            continue
        for it in items or []:
            # Free aksiya bonuses and campaign gifts weren't CHOSEN by the
            # buyer, so they never headline "Siz tanlagan mahsulotlar".
            if it.get("is_bonus") or it.get("is_gift"):
                continue
            name = (it.get("name") or "").strip()
            if not name:
                continue
            try:
                qty = float(it.get("quantity") or 1)
            except (ValueError, TypeError):
                qty = 1.0
            totals[name] = totals.get(name, 0.0) + qty
    return sorted(totals.items(), key=lambda kv: kv[1], reverse=True)


def name_profile(name: str) -> dict | None:
    """The profile a product NAME matches by keyword, or None.

    Some products are keyed into the shop in Cyrillic ("Зайтун ёғи совуқ
    сиқим"), which used to fall through to the generic profile even though a
    perfectly good one exists — so a Cyrillic name is also matched in its
    Latin transliteration (2026-09-01)."""
    low = (name or "").lower()
    variants = [low]
    if re.search(r"[Ѐ-ӿ]", low):
        try:
            from translit import cyr_to_lat
            variants.append(cyr_to_lat(low).lower())
        except Exception:
            pass
    for prof in PROFILES:
        if any(kw in variant for kw in prof["match"] for variant in variants):
            return prof
    return None


# {lower-cased product name: shop category}, loaded from the live catalogue by
# refresh_categories() before every batch/preview. Lets a product whose name no
# profile recognises still get content for its own category instead of the
# generic note — so products added through the admin panel are covered the day
# they appear, without anyone editing reco_content.py.
_CATEGORY_BY_NAME: dict[str, str] = {}
_PROFILE_BY_KEY = {p["key"]: p for p in PROFILES}
_PROFILE_BY_KEY.update({p["key"]: p for p in CATEGORY_GENERIC_PROFILES.values()})


async def refresh_categories() -> None:
    global _CATEGORY_BY_NAME
    try:
        _CATEGORY_BY_NAME = await database.get_product_category_map()
    except Exception:
        logger.exception("Could not load product categories for recommendations")


def category_profile(name: str) -> dict | None:
    cat = _CATEGORY_BY_NAME.get((name or "").strip().lower())
    key = CATEGORY_PROFILE_KEYS.get(cat) if cat else None
    return _PROFILE_BY_KEY.get(key) if key else None


def _profile_for(name: str) -> dict:
    """Name keyword match first (most precise), then the product's shop
    category, then the generic default."""
    return name_profile(name) or category_profile(name) or DEFAULT_PROFILE


def _pick(seq: list, cycle: int):
    """Deterministic rotation so returning buyers get fresh content each send."""
    return seq[cycle % len(seq)] if seq else None


def _owned_keys(products: list[tuple[str, float]]) -> set[str]:
    return {_profile_for(name)["key"] for name, _ in products}


def _recipe_pool(star: dict, owned: set[str]) -> list[tuple[str, dict]]:
    """(heading label key, recipe) candidates for this buyer, best first.

    Combo recipes the buyer can actually cook — every family in `needs` is one
    they order — come first, so the message leads with something built from
    their basket as a whole rather than from one product in it. The star
    profile's own recipes follow as the always-available fallback."""
    pool = [("recipe_combo", c["recipe"])
            for c in _COMBOS_BY_SPECIFICITY if c["needs"] <= owned]
    pool += [("recipe_single", r) for r in star["recipes"]]
    return pool


def _buyer_name(orders: list[dict]) -> str | None:
    """First name off the most recent order, or None. Anything that doesn't
    look like a name (a phone number someone typed into the name field, a
    stray digit) is dropped rather than pasted into the greeting."""
    for o in orders:
        raw = (o.get("customer_name") or "").strip()
        if not raw or len(raw) > 40:
            continue
        first = raw.split()[0]
        if len(first) < 2 or any(ch.isdigit() for ch in first):
            continue
        # An HTML-special character would be escaped into an entity, and the
        # uz_cyr pass transliterates entities into nonsense (&amp; -> &амп;).
        # No real first name needs them, so drop the name instead.
        if any(ch in first for ch in "&<>"):
            continue
        return first
    return None


def _ru_plural(n: int, one: str, few: str, many: str) -> str:
    """Russian count agreement — 1 заказ / 2 заказа / 5 заказов. Without it the praise
    line read "уже 2 раз", which undercuts a message whose whole point is
    that it was written for this one person."""
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def _praise(lang: str, orders: list[dict]) -> str:
    """Warm, specific thanks — the shop owner's ask (2026-09-17) was that these
    messages read as written by Ketoshop for this one person, and that they
    credit the buyer for choosing a healthier life rather than just selling."""
    n = len(orders)
    if n <= 1:
        return _loc(LABELS["praise_first"], lang)
    if n < 5:
        return _loc(LABELS["praise_regular"], lang, n=n,
                    word=_ru_plural(n, "раз", "раза", "раз"))
    return _loc(LABELS["praise_loyal"], lang, n=n,
                word=_ru_plural(n, "заказ", "заказа", "заказов"))


def shop_term_for(key: str) -> str:
    """Catalogue search term behind the CTA button for a profile key."""
    for prof in PROFILES:
        if prof["key"] == key:
            return prof.get("shop") or prof["name"]["uz"]
    return DEFAULT_PROFILE["shop"]


# Product names that fell through to DEFAULT_PROFILE in the latest batch. The
# catalogue grows through the admin panel without anyone touching
# reco_content.py, so a new product would otherwise quietly get the generic
# "healthy products" note forever. _tick reports these to the admins after
# every send — that list IS the to-do for the next profile to write.
LAST_UNCOVERED: set[str] = set()


def uncovered_report() -> str:
    """Admin-facing block listing products with no content profile, or ''."""
    if not LAST_UNCOVERED:
        return ""
    names = sorted(LAST_UNCOVERED)
    shown = "\n".join(f"• {html.escape(n)}" for n in names[:15])
    more = f"\n… va yana {len(names) - 15} ta" if len(names) > 15 else ""
    return ("\n\n⚠️ <b>Maxsus retsept profili yo'q mahsulotlar</b> "
            "(kategoriyasi bo'yicha retsept oldi — aniqroq bo'lishi uchun reco_content.py ga profil qo'shsa bo'ladi):\n"
            + shown + more)


def star_profile_for(orders: list[dict]) -> dict | None:
    """The profile the buyer's message is built around — what the CTA button
    shops for. None when there's no recognizable history."""
    products = _aggregate_products(orders)
    if not products:
        return None
    return _profile_for(products[0][0])


def build_personal_message(lang: str, orders: list[dict], cycle: int) -> str | None:
    """Compose one buyer's personalized message, or None if they have no
    recognizable order history.

    Shape (rebuilt 2026-09-17):
        from Ketoshop, for you  →  greeting by name  →  thanks for choosing a
        healthy life, with their real order count  →  what they bought  →  a
        recipe built from those products  →  why it's good for them  →  what
        pairs with it  →  call to action  →  sign-off.
    """
    products = _aggregate_products(orders)
    if not products:
        return None

    star_name = products[0][0]
    star_profile = _profile_for(star_name)
    owned = _owned_keys(products)

    second_profile = None
    for name, _ in products[1:]:
        prof = _profile_for(name)
        if prof["key"] != star_profile["key"]:
            second_profile = prof
            break

    def esc(s: str) -> str:
        return html.escape(s, quote=False)

    lines: list[str] = []

    # 1. Who it's from and who it's for.
    lines.append(_loc(LABELS["header"], lang))
    lines.append("")

    name = _buyer_name(orders)
    lines.append(_loc(LABELS["greet_named"], lang, name=esc(name)) if name
                 else _loc(LABELS["greet"], lang))
    lines.append("")

    # 2. Sincere, specific thanks.
    lines.append(_praise(lang, orders))
    lines.append("")

    # 3. Their own basket, echoed back with each family's emoji.
    lines.append(_loc(LABELS["your_picks"], lang))
    for pname, _qty in products[:4]:
        prof = _profile_for(pname)
        lines.append(f"{prof['emoji']} {esc(pname)}")
    lines.append("")

    # Content rotation uses a MIXED-RADIX decomposition of `cycle` — recipe is
    # the fastest "digit", then star benefit, then the rest. Rotating every
    # section with the same counter would sync them (period = LCM of lengths,
    # often just 2); decomposing walks the full Cartesian product of variants,
    # which the never-repeat dedupe in send_personal_batch depends on to find
    # fresh messages for as long as possible.
    pool = _recipe_pool(star_profile, owned)
    r_len = max(1, len(pool))
    heading_key, recipe = pool[cycle % r_len] if pool else ("recipe_single", None)
    if recipe:
        lines.append(_loc(LABELS[heading_key], lang))
        lines.append(_loc(recipe, lang))
        lines.append("")

    # 5. Why it's good for them — star family, plus a second one when they buy
    #    from more than one, so the note reflects the breadth of the basket.
    b_len = max(1, len(star_profile["benefits"]))
    rest = cycle // r_len
    star_benefit = _pick(star_profile["benefits"], rest % b_len)
    rest //= b_len
    lines.append(_loc(LABELS["benefit"], lang))
    if star_benefit:
        lines.append(f"{star_profile['emoji']} {_loc(star_benefit, lang)}")
    if second_profile:
        sb_len = max(1, len(second_profile["benefits"]))
        sb = _pick(second_profile["benefits"], (rest + 1) % sb_len)
        rest //= sb_len
        if sb:
            lines.append(f"{second_profile['emoji']} {_loc(sb, lang)}")
    lines.append("")

    # 6. Complementary ingredients they DON'T already buy.
    candidates = [s for s in PAIRINGS.get(star_profile["key"], PAIRINGS_DEFAULT)
                  if s["profile"] not in owned]
    if candidates:
        start = rest % len(candidates)
        picked = [candidates[(start + i) % len(candidates)]
                  for i in range(min(2, len(candidates)))]
        lines.append(_loc(LABELS["pairs"], lang))
        for s in picked:
            lines.append(f"{s['emoji']} <b>{_loc(s['name'], lang)}</b> — {_loc(s['why'], lang)}")
        lines.append("")

    # 7. Call to action, then the sign-off.
    lines.append(_loc(LABELS["cta"], lang))
    lines.append("")
    lines.append(_loc(LABELS["closing"], lang))
    return "\n".join(lines)


def reco_keyboard(lang: str, orders: list[dict]) -> "InlineKeyboardMarkup":
    """Buttons under a personal recommendation.

    Top row shops the buyer's own dominant family (reco_shop: runs that
    profile's catalogue search — see handlers/search.py), so the recipe they
    just read is one tap from the products it needs. The Mini App button
    follows when the shop has one. Without a star profile — or without a
    WEBAPP_URL — whichever rows are meaningful still render."""
    rows = []
    star = star_profile_for(orders)
    if star:
        rows.append([InlineKeyboardButton(
            text=_loc(LABELS["btn_shop_profile"], lang, name=_loc(star["name"], lang)),
            callback_data=f"reco_shop:{star['key']}",
        )])
    if WEBAPP_URL:
        rows.append([InlineKeyboardButton(
            text=get_text("btn_store", lang), web_app=WebAppInfo(url=WEBAPP_URL))])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


# ─────────────────────────────────────────────────────────────────────────────
# Sending
# ─────────────────────────────────────────────────────────────────────────────
def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


async def _notify_admins(bot: Bot, text: str):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception:
            pass


async def send_personal_batch(bot: Bot, only_user: int | None = None) -> tuple[int, int]:
    """Build and send each eligible buyer's personalized message.

    `only_user` restricts the send to a single user id (used by /reco_test and
    /reco_now previews). Returns (sent, failed).

    Two populations: buyers with order history get the rich recipe/benefit
    message below; browse-only users (viewed products but never ordered —
    previously skipped entirely) get a lighter most-viewed-product spotlight,
    sent in the second loop further down (owner request 2026-07-27: reach
    "barcha foydalanuvchilar", not just past buyers)."""
    state = await database.get_reco_state()
    cycle = state.get("cycle", 0)
    await refresh_categories()

    if only_user is not None:
        user_ids = [only_user]
    else:
        user_ids = await database.get_user_ids_with_orders()

    # Never repeat: try successive rotation offsets until we find a message
    # this buyer hasn't received; if every variant was already sent, skip them
    # this round rather than send a duplicate. Test previews (only_user) skip
    # the bookkeeping so they don't burn variants.
    record = only_user is None

    # One query for the whole audience instead of a SELECT * per recipient.
    langs = await database.get_user_languages(user_ids)

    sent = failed = skipped = 0
    for uid in user_ids:
        try:
            orders = await database.get_user_orders(uid)
            if record:
                for pname, _ in _aggregate_products(orders):
                    if name_profile(pname) is None:
                        LAST_UNCOVERED.add(pname)
            lang = langs.get(uid, "uz")

            seen = await database.get_reco_hashes(uid) if record else set()
            text = msg_hash = None
            for shift in range(MAX_VARIANT_TRIES):
                candidate = build_personal_message(lang, orders, cycle + shift)
                if not candidate:
                    break
                h = hashlib.sha256(candidate.encode()).hexdigest()
                if h not in seen:
                    text, msg_hash = candidate, h
                    break
            if not text:
                skipped += 1
                continue

            delivered = False
            # CTA under every personal reco — the recipe above is one tap from
            # the products it calls for (owner request 2026-09-17).
            markup = reco_keyboard(lang, orders)
            try:
                await bot.send_message(uid, text, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                                        reply_markup=markup)
                delivered = True
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                await bot.send_message(uid, text, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                                        reply_markup=markup)
                delivered = True
            except (TelegramForbiddenError, TelegramBadRequest):
                failed += 1

            if delivered:
                sent += 1
                if record:
                    await database.mark_reco_sent(uid, msg_hash)
        except Exception:
            logger.exception("Personal reco send failed for user %s", uid)
            failed += 1
        await asyncio.sleep(SEND_DELAY)

    # Second population: browse-only users (no orders, but have viewed at
    # least one product) — most-viewed-product spotlight instead of a
    # recipe. Same never-repeat/skip bookkeeping, same reco_sent table.
    #
    # Rotates over BOTH their top-3 recently-viewed products AND the intro
    # line (owner request 2026-07-27: must adapt as interest shifts, not
    # freeze on one product forever) — get_user_top_viewed_products re-ranks
    # from the last 30 days fresh every send, so as a buyer's browsing moves
    # on, the spotlight follows. Their #1 current interest is tried first
    # (with all its intro variants) before falling back to #2/#3, so the
    # product only changes once genuinely-new content is needed.
    if only_user is None:
        view_only_ids = await database.get_user_ids_with_views_no_orders()
        view_langs = await database.get_user_languages(view_only_ids)
        for uid in view_only_ids:
            try:
                products = await database.get_user_top_viewed_products(uid, limit=3, recent_days=30)
                if not products:
                    skipped += 1
                    continue
                lang = view_langs.get(uid, "uz")
                seen = await database.get_reco_hashes(uid)

                text = msg_hash = product = None
                for p in products:
                    for shift in range(len(_VIEW_INTROS)):
                        candidate = build_viewed_product_message(lang, p, cycle + shift)
                        h = hashlib.sha256(candidate.encode()).hexdigest()
                        if h not in seen:
                            text, msg_hash, product = candidate, h, p
                            break
                    if text:
                        break
                if not text:
                    skipped += 1
                    continue

                delivered = False
                markup = _product_button(product, lang)
                try:
                    await bot.send_message(uid, text, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                                            reply_markup=markup)
                    delivered = True
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
                    await bot.send_message(uid, text, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                                            reply_markup=markup)
                    delivered = True
                except (TelegramForbiddenError, TelegramBadRequest):
                    failed += 1

                if delivered:
                    sent += 1
                    await database.mark_reco_sent(uid, msg_hash)
            except Exception:
                logger.exception("Viewed-product reco send failed for user %s", uid)
                failed += 1
            await asyncio.sleep(SEND_DELAY)

    if skipped:
        logger.info("Personal reco: %d buyer(s) skipped — all content variants already sent", skipped)
    return sent, failed


async def _tick(bot: Bot):
    state = await database.get_reco_state()
    if not state["enabled"]:
        return

    last = state["last_sent_at"]
    now_tk = _now_tk()
    if now_tk.hour < SEND_HOUR:
        # Daytime only (owner, 2026-09-17: "kunduz kunidan boshla"). This also
        # covers the first send after arming, which used to go out on the very
        # next check — at 02:00 if that's when the bot was deployed.
        return
    if last is None:
        due = True  # first send after arming — goes out on the next check
    else:
        last_tk = last + TZ_OFFSET
        elapsed_days = (now_tk.date() - last_tk.date()).days
        due = elapsed_days >= INTERVAL_DAYS

    if not due:
        return

    # Never share a day with the keto-tips broadcast: if a tip already went out
    # today (Tashkent date), slip to tomorrow. `due` stays true, so the next
    # tick after midnight sends. Tips fire at 08:00 and we check at 10:00+, so
    # "sent today" is a reliable signal by the time we get here.
    try:
        tips = await database.get_broadcast_state()
        tips_last = tips.get("last_sent_at")
        if tips_last and (tips_last + TZ_OFFSET).date() == _now_tk().date():
            logger.info("Personal reco postponed: tips broadcast already sent today")
            return
    except Exception:
        logger.exception("Could not read tips state; sending reco anyway")

    LAST_UNCOVERED.clear()
    sent, failed = await send_personal_batch(bot)
    await database.advance_reco()
    await _notify_admins(
        bot,
        f"🎁 Shaxsiy tavsiyalar yuborildi.\n"
        f"✅ {sent} ta yetkazildi, ⚠️ {failed} ta yetmadi."
        + uncovered_report(),
    )
    logger.info("Personal recommendations sent: %d ok, %d failed", sent, failed)


async def scheduler_loop(bot: Bot):
    """Background task: every CHECK_EVERY seconds, send personalized recos if due."""
    logger.info("Personal-recommendation scheduler started (%d profiles)", len(PROFILES))
    while True:
        try:
            await _tick(bot)
        except Exception:
            logger.exception("Personal reco tick failed")
        await asyncio.sleep(CHECK_EVERY)
