"""
Sovg'a kampaniyasi — free 100 gr Eritritol on every big-enough order (2026-09-17).

Owner's brief, verbatim decisions:
  * who     — anyone who places their OWN order through the bot or its Mini
              App during the campaign; admin and shop accounts never get it
              (their orders are internal and would wreck the accounting);
  * when    — every order, any size (was ≥111 000 so'm until 17.09 11:30 —
              see MIN_ORDER), not once per person;
  * how     — the gift is put into the order automatically as a 0-so'm line,
              no code or button needed;
  * money   — each delivered gift is booked into Chiqimlar at cost, and kept
              OUT of cost-of-goods (database.item_cost_qty) so profit isn't
              charged for it twice;
  * launch  — starts by itself the first time the bot boots with this module,
              announced to every user at 09:00 Tashkent, runs 30 days from
              that announcement.

Gift lines reuse the aksiya bonus shape (is_bonus=True, price 0) so every
existing renderer, the seller's packing notification and create_order's
best-effort stock decrement handle them unchanged; `is_gift` is what tells
the accounting apart.

Public API:
  ensure_started()                  -> create the campaign row on first boot
  is_active()                       -> bool, 60s cached
  gift_lines(user_id, items)        -> [] or [gift line] for an order item list
  cart_hint(user_id, subtotal, lang)-> "🎁 sovg'a qo'shiladi" / "yana X so'm" / ""
  scheduler_loop(bot)               -> announce, expire, book expenses, stock alerts
"""
import asyncio
import logging
import re
import time
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

import database
from config import ADMIN_IDS, WEBAPP_URL

logger = logging.getLogger(__name__)

CAMPAIGN_KEY = "eritritol_100gr_2026_09"
# Owner, 2026-09-17 11:30: "111.000 so'mga emas balki har qanday bot orqali
# qilingan buyurtmaga" — the threshold is gone, every order gets the gift.
# (Was 111 000 from launch until then.) Kept as a knob: >0 brings the
# "yana X so'm qo'shsangiz" hint back automatically.
MIN_ORDER = 0                # so'm, goods subtotal
DURATION_DAYS = 30           # counted from the announcement
ANNOUNCE_HOUR = 9            # 09:00 Tashkent
ANNOUNCE_WINDOW_HOURS = 3    # 09:00-11:59; a deploy at 14:00 waits for tomorrow 09:00
TZ_OFFSET = timedelta(hours=5)
CHECK_EVERY = 300            # 5 min: announce on time, book expenses promptly
CACHE_TTL = 60
SEND_DELAY = 0.05

# The gift product is looked up by name so it survives a re-import of the
# catalogue with new ids. The pattern insists on exactly 100 gr — "Eritritol
# 1000gr" must never be handed out by accident.
_NAME_FRAGMENT = "eritr"
_SIZE_RE = re.compile(r"(?<!\d)100\s*(gr|g|г|гр)\b", re.IGNORECASE)

_state_cache: tuple[float, dict | None] = (0.0, None)
_product_cache: tuple[float, dict | None] = (0.0, None)


# ─────────────────────────────── state ──────────────────────────────────────

def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


def fmt_sum(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", " ")


async def ensure_started() -> dict:
    """Idempotent: first boot creates the row, later boots only read it."""
    global _state_cache
    row = await database.ensure_gift_campaign(CAMPAIGN_KEY)
    _state_cache = (time.monotonic(), row)
    return row


async def _state(force: bool = False) -> dict | None:
    global _state_cache
    ts, row = _state_cache
    if force or time.monotonic() - ts > CACHE_TTL:
        row = await database.get_gift_campaign(CAMPAIGN_KEY)
        _state_cache = (time.monotonic(), row)
    return row


def _active_row(row: dict | None) -> bool:
    if not row:
        return False
    # The gift starts together with the 09:00 announcement, not at deploy
    # (owner, 2026-09-17: "eritritol sovg'asini ham 9 dan boshla ertalab") —
    # nobody gets a gift they were never told about, and a night-time deploy
    # doesn't quietly start the 30 days early.
    ends = row.get("ends_at")
    if row.get("announced_at") is None or ends is None:
        return False
    return datetime.utcnow() < ends


async def is_active() -> bool:
    return _active_row(await _state())


def is_eligible_user(user_id: int | None) -> bool:
    """Admin and shop accounts never get the gift — their orders are placed on
    behalf of someone else or are tests, and would book fake giveaways."""
    if not user_id:
        return False
    return user_id not in ADMIN_IDS and user_id not in database.LEADERBOARD_EXCLUDED_USER_IDS


async def gift_product(force: bool = False) -> dict | None:
    """The live "Eritritol 100gr" product row, or None if it's not in the
    catalogue (renamed, deactivated). Cached briefly — it's read on every cart
    render."""
    global _product_cache
    ts, prod = _product_cache
    if force or time.monotonic() - ts > CACHE_TTL:
        prod = None
        for cand in await database.find_products_by_name_fragment(_NAME_FRAGMENT):
            if _SIZE_RE.search(cand["name"] or ""):
                prod = cand
                break
        _product_cache = (time.monotonic(), prod)
    return prod


def paid_subtotal(items: list[dict]) -> float:
    """Goods total that counts toward the threshold — bonus/gift lines are 0
    anyway, delivery and Keto discounts live outside items."""
    total = 0.0
    for it in items:
        if it.get("is_bonus") or it.get("is_gift"):
            continue
        qty = it.get("quantity", it.get("cart_quantity", 0))
        total += float(it.get("price") or 0) * float(qty or 0)
    return total


# ─────────────────────────────── gift line ──────────────────────────────────

async def gift_lines(user_id: int | None, items: list[dict]) -> list[dict]:
    """The gift as a 0-so'm order line when this order qualifies, else [].

    Qualifies = campaign running, buyer not an admin/shop account, goods
    subtotal ≥ MIN_ORDER, gift product in the catalogue with at least one in
    stock. Out of stock means no line (a promised gift that can't be packed
    is worse than none) — the scheduler tells the admins so they restock.

    A personal gift offer (retention.py — 2nd order, win-back, new Keto level)
    gives the same pack on an order of ANY size. It never adds a second gift:
    when the order already qualifies for the campaign, the one line carries
    the offer's tag and spends the offer."""
    if not is_eligible_user(user_id):
        return []
    if any(it.get("is_gift") for it in items):
        return []                                   # never twice in one order
    import retention
    offer = await retention.active_offer(user_id)
    subtotal = paid_subtotal(items)
    campaign = await is_active() and subtotal > 0 and subtotal >= MIN_ORDER
    if not campaign and not offer:
        return []
    prod = await gift_product()
    if not prod or float(prod.get("quantity") or 0) < 1:
        return []
    line = _gift_line(prod)
    if offer:
        line["retention_offer_id"] = int(offer["id"])
        if not campaign:
            line["promo_name"], line["promo_name_ru"] = "Shaxsiy sovg'a", "Личный подарок"
    return [line]


def _gift_line(prod: dict) -> dict:
    return {
        "product_id": int(prod["id"]),
        "set_id": None,
        "is_set": False,
        "is_bonus": True,
        "is_gift": True,
        "name": prod["name"],
        "name_ru": prod.get("name_ru"),
        # One pre-packed 100 gr pack. Unit "dona" (not the product's kg/g
        # stock unit) so the bonus renderers print "1 dona", never "1 kg".
        "quantity": 1,
        "unit": "dona",
        "stock_quantity": 1,
        "price": 0,
        "original_price": 0,
        "discount_percent": 0,
        "bonus_value": float(prod.get("price") or 0),
        "photo_id": prod.get("photo_id"),
        "promo_name": "Sovg'a",
        "promo_name_ru": "Подарок",
        "seller_id": None,
    }


_HINT = {
    "personal": {
        "uz": "🎁 <b>Shaxsiy sovg'angiz:</b> bu buyurtmaga <b>{name}</b> bepul qo'shiladi — summadan qat'i nazar ({until} gacha).",
        "ru": "🎁 <b>Ваш личный подарок:</b> к этому заказу бесплатно добавится <b>{name}</b> — на любую сумму (до {until}).",
    },
    "added": {
        "uz": "🎁 <b>Sovg'a!</b> Bu buyurtmaga <b>{name}</b> bepul qo'shiladi.",
        "ru": "🎁 <b>Подарок!</b> К этому заказу бесплатно добавится <b>{name}</b>.",
    },
    "missing": {
        "uz": "🎁 Yana <b>{left} so'm</b>lik mahsulot qo'shsangiz — <b>{name}</b> sovg'a!",
        "ru": "🎁 Добавьте товаров ещё на <b>{left} сум</b> — и <b>{name}</b> в подарок!",
    },
}

# The standing promise, printed at the foot of every product card so a buyer
# meets it while they are still choosing — not only once the cart is full.
# It says "per order" because that is what gift_lines() actually adds: one
# pack per order, however many products are in it.
_CARD = {
    "uz": "🎁 Botdan bergan <b>har bir buyurtmangizga</b> <b>{name}</b> sovg'a!",
    "ru": "🎁 <b>К каждому заказу</b> в боте — <b>{name}</b> в подарок!",
}


async def card_line(lang: str) -> str:
    """The gift line for a product card, or '' when there is nothing to
    promise (campaign over, or the gift itself out of stock — a promise that
    can't be packed is worse than none)."""
    if not await is_active():
        return ""
    prod = await gift_product()
    if not prod or float(prod.get("quantity") or 0) < 1:
        return ""
    from locales import localize_product_text
    name = localize_product_text(prod["name"], prod.get("name_ru"),
                                 "uz" if lang == "uz_cyr" else lang)
    return _loc(_CARD, lang, name=name)


def _loc(entry: dict, lang: str, **fmt) -> str:
    text = (entry.get("ru") if lang == "ru" else entry.get("uz")) or entry.get("uz", "")
    text = text.format(**fmt)
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        text = lat_to_cyr(text)
    return text


async def cart_hint(user_id: int | None, subtotal: float, lang: str) -> str:
    """One line for the cart / checkout / reminder: the gift is already earned,
    or how much more to add to earn it. '' when the campaign doesn't apply.

    A buyer with a personal gift offer (retention.py) gets it whatever the
    sum, so they're told that — never "add X more", which would contradict
    the offer they were sent."""
    if not is_eligible_user(user_id):
        return ""
    import retention
    offer = await retention.active_offer(user_id)
    if not offer and not await is_active():
        return ""
    prod = await gift_product()
    if not prod or float(prod.get("quantity") or 0) < 1:
        return ""
    from locales import localize_product_text
    name = localize_product_text(prod["name"], prod.get("name_ru"), "uz" if lang == "uz_cyr" else lang)
    if offer:
        return _loc(_HINT["personal"], lang, name=name,
                    until=retention.offer_until_text(offer, lang))
    if subtotal >= MIN_ORDER or MIN_ORDER <= 0:
        return _loc(_HINT["added"], lang, name=name)
    return _loc(_HINT["missing"], lang, left=fmt_sum(MIN_ORDER - subtotal), name=name)


# ─────────────────────────────── announcement ───────────────────────────────

_ANNOUNCE = {
    "uz": (
        "🎁 <b>Ketoshopdan sovg'a — 30 kun davomida!</b>\n\n"
        "Assalomu alaykum! Sog'lom hayotni biz bilan tanlaganingiz uchun "
        "Sizga rahmat aytmoqchimiz 🤍\n\n"
        "Bugundan boshlab <b>30 kun</b> davomida bot orqali "
        "<b>{min_order} so'm va undan ortiq</b> buyurtma bergan har bir "
        "mijozimizga <b>100 gr Eritritol</b> — mutlaqo <b>BEPUL!</b>\n\n"
        "✅ Hech qanday kod shart emas — sovg'a buyurtmangizga "
        "<b>avtomatik qo'shiladi</b>\n"
        "✅ Har safar {min_order} so'm va undan ortiq buyurtma berganingizda — yana sovg'a\n"
        "✅ Shakarsiz shirinlik: pishiriq, choy va desertlar uchun\n\n"
        "⏳ Aksiya {until} gacha amal qiladi.\n\n"
        "👇 Hoziroq tanlang:"
    ),
    "ru": (
        "🎁 <b>Подарок от Ketoshop — целых 30 дней!</b>\n\n"
        "Здравствуйте! Хотим поблагодарить вас за то, что вы выбираете "
        "здоровую жизнь вместе с нами 🤍\n\n"
        "С сегодняшнего дня в течение <b>30 дней</b> каждому, кто оформит "
        "заказ через бот на <b>{min_order} сум и больше</b>, — "
        "<b>100 г эритрита</b> совершенно <b>БЕСПЛАТНО!</b>\n\n"
        "✅ Никаких промокодов — подарок <b>добавится к заказу автоматически</b>\n"
        "✅ Каждый раз при заказе от {min_order} сум — снова подарок\n"
        "✅ Сладость без сахара: для выпечки, чая и десертов\n\n"
        "⏳ Акция действует до {until}.\n\n"
        "👇 Выбирайте прямо сейчас:"
    ),
}


def announcement_text(lang: str, until: datetime) -> str:
    until_str = until.strftime("%d.%m.%Y")
    if lang == "ru":
        return _ANNOUNCE["ru"].format(until=until_str, min_order=fmt_sum(MIN_ORDER))
    text = _ANNOUNCE["uz"].format(until=until_str, min_order=fmt_sum(MIN_ORDER))
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        text = lat_to_cyr(text)
    return text


def announcement_keyboard(lang: str) -> InlineKeyboardMarkup:
    from locales import get_text
    rows = []
    if WEBAPP_URL:
        rows.append([InlineKeyboardButton(text=get_text("btn_store", lang),
                                          web_app=WebAppInfo(url=WEBAPP_URL))])
    rows.append([InlineKeyboardButton(text=get_text("btn_catalog", lang), callback_data="catalog")])
    rows.append([InlineKeyboardButton(text=get_text("btn_cart", lang), callback_data="cart")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send(bot: Bot, user_id: int, text: str, markup) -> bool:
    for attempt in range(2):
        try:
            await bot.send_message(user_id, text, parse_mode=ParseMode.HTML,
                                   reply_markup=markup, disable_web_page_preview=True)
            return True
        except TelegramRetryAfter as exc:
            if attempt:
                return False
            await asyncio.sleep(exc.retry_after + 1)
        except (TelegramForbiddenError, TelegramBadRequest):
            return False
        except Exception:
            logger.exception("Gift announcement to %s failed", user_id)
            return False
    return False


# ──────────────── "now on EVERY order" — the festive re-announcement ─────────
# Owner, 2026-09-17: drop the 111 000 so'm minimum and tell everyone
# "tantanali ravishda, rasmi bilan". Sent once (key claimed first), daytime
# only, with the gift product's own photo; text-only if it has none.

UPGRADE_KEY = "gift-no-minimum-2026-09-17"
UPGRADE_WINDOW = (9, 21)

_UPGRADE = {
    "uz": (
        "🎉🎁 <b>SOVG'A ENDI HAR BIR BUYURTMAGA!</b>\n\n"
        "Aziz mijozlarimiz, Sizga katta quvonchli xabarimiz bor! 🥳\n\n"
        "Bugundan boshlab Ketoshop botida berilgan <b>HAR QANDAY buyurtmaga</b> — "
        "summasidan qat'i nazar — <b>100 gr Eritritol</b> mutlaqo <b>BEPUL!</b>\n\n"
        "✨ Minimal summa yo'q — bitta mahsulot olsangiz ham sovg'a\n"
        "✨ Hech qanday kod kerak emas — sovg'a buyurtmangizga o'zi qo'shiladi\n"
        "✨ Har safar buyurtma berganingizda — yana sovg'a\n"
        "🍬 Eritritol — shakarsiz shirinlik: choy, qahva, pishiriq va desertlar uchun\n\n"
        "⏳ Aksiya <b>{until}</b> gacha davom etadi.\n\n"
        "Sog'lom hayotni biz bilan tanlaganingiz uchun rahmat! 🤍\n"
        "👇 Hoziroq buyurtma bering:"
    ),
    "ru": (
        "🎉🎁 <b>ПОДАРОК ТЕПЕРЬ К КАЖДОМУ ЗАКАЗУ!</b>\n\n"
        "Дорогие покупатели, у нас для вас большая радостная новость! 🥳\n\n"
        "С сегодняшнего дня к <b>ЛЮБОМУ заказу</b> в боте Ketoshop — "
        "на любую сумму — <b>100 г эритрита</b> совершенно <b>БЕСПЛАТНО!</b>\n\n"
        "✨ Никакой минимальной суммы — подарок даже за один товар\n"
        "✨ Никаких промокодов — подарок добавится к заказу сам\n"
        "✨ Каждый новый заказ — снова подарок\n"
        "🍬 Эритрит — сладость без сахара: для чая, кофе, выпечки и десертов\n\n"
        "⏳ Акция действует до <b>{until}</b>.\n\n"
        "Спасибо, что выбираете здоровую жизнь вместе с нами! 🤍\n"
        "👇 Оформите заказ прямо сейчас:"
    ),
}


def upgrade_text(lang: str, until: datetime) -> str:
    until_str = until.strftime("%d.%m.%Y")
    if lang == "ru":
        return _UPGRADE["ru"].replace("{until}", until_str)
    text = _UPGRADE["uz"].replace("{until}", until_str)
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        text = lat_to_cyr(text)
    return text


async def _send_photo(bot: Bot, user_id: int, photo: str | None, text: str, markup) -> bool:
    """Photo with the announcement as its caption; a plain message when the
    product has no photo or Telegram refuses it."""
    if not photo:
        return await _send(bot, user_id, text, markup)
    for attempt in range(2):
        try:
            await bot.send_photo(user_id, photo, caption=text, parse_mode=ParseMode.HTML, reply_markup=markup)
            return True
        except TelegramRetryAfter as exc:
            if attempt:
                return False
            await asyncio.sleep(exc.retry_after + 1)
        except TelegramForbiddenError:
            return False
        except TelegramBadRequest as exc:
            if "photo" in str(exc).lower() or "file" in str(exc).lower():
                return await _send(bot, user_id, text, markup)
            return False
        except Exception:
            logger.exception("Gift upgrade announcement to %s failed", user_id)
            return False
    return False


async def _product_photo(prod: dict | None) -> str | None:
    """Telegram file_id of the gift product, or its admin-site image as a
    public URL. None when it has neither."""
    if not prod:
        return None
    if prod.get("photo_id"):
        return prod["photo_id"]
    try:
        full = await database.get_product(int(prod["id"]))
        if full and full.get("photo_id"):
            return full["photo_id"]
        if full and full.get("image_url"):
            import promotions
            return promotions._absolute_image(full["image_url"])
    except Exception:
        logger.warning("Gift product photo lookup failed", exc_info=True)
    return None


async def announce_upgrade(bot: Bot) -> tuple[int, int]:
    row = await _state(force=True)
    until = (row["ends_at"] + TZ_OFFSET) if row and row.get("ends_at") else _now_tk() + timedelta(days=DURATION_DAYS)
    prod = await gift_product(force=True)
    photo = await _product_photo(prod)
    user_ids = await database.get_all_user_ids()
    langs = await database.get_user_languages(user_ids)
    bodies = {lang: (upgrade_text(lang, until), announcement_keyboard(lang)) for lang in ("uz", "uz_cyr", "ru")}
    sent = failed = 0
    for uid in user_ids:
        text, markup = bodies.get(langs.get(uid, "uz")) or bodies["uz"]
        if await _send_photo(bot, uid, photo, text, markup):
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(SEND_DELAY)
    return sent, failed


async def announce(bot: Bot) -> tuple[int, int]:
    # Stamp FIRST: a crash or redeploy halfway through the broadcast must not
    # re-announce to the people who already got it on the next boot.
    await database.mark_gift_announced(CAMPAIGN_KEY, DURATION_DAYS)
    row = await _state(force=True)
    until = (row["ends_at"] + TZ_OFFSET) if row and row.get("ends_at") else _now_tk() + timedelta(days=DURATION_DAYS)

    user_ids = await database.get_all_user_ids()
    langs = await database.get_user_languages(user_ids)
    sent = failed = 0
    for uid in user_ids:
        lang = langs.get(uid, "uz")
        if await _send(bot, uid, announcement_text(lang, until), announcement_keyboard(lang)):
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(SEND_DELAY)
    return sent, failed


# ─────────────────────────────── accounting ─────────────────────────────────

async def book_delivered_gifts() -> tuple[int, float]:
    """Chiqimlar row for every delivered order carrying a gift line.

    Reconciled from the orders table rather than hooked into each "delivered"
    code path (admin bot, courier, seller, web panel all set it) — one sweep
    here can't miss a path that's added later. Cancelled orders are never
    delivered, so they're never booked. Cost is the product's cost_price; if
    that was never filled in, the shelf price stands in and the row says so."""
    orders = await database.get_unbooked_gift_orders()
    if not orders:
        return 0, 0.0
    cost_map = await database.get_all_cost_prices()
    booked, total = 0, 0.0
    for o in orders:
        try:
            import json
            items = json.loads(o["items"] or "[]")
        except (ValueError, TypeError):
            continue
        for it in items:
            if not it.get("is_gift"):
                continue
            pid = it.get("product_id")
            qty = float(it.get("stock_quantity") or 1)
            unit_cost = float(cost_map.get(int(pid), 0.0)) if pid else 0.0
            note = ""
            if unit_cost <= 0:
                unit_cost = float(it.get("bonus_value") or 0) / max(qty, 1)
                note = " (tannarx kiritilmagan — sotuv narxi bo'yicha)"
            amount = round(unit_cost * qty)
            name = f"🎁 Sovg'a: {it.get('name') or 'Eritritol 100gr'} — buyurtma #{o['id']}{note}"
            if await database.book_gift_expense(int(o["id"]), name, amount):
                booked += 1
                total += amount
            break                                   # one gift per order
    return booked, total


# ─────────────────────────────── scheduler ──────────────────────────────────

async def _notify_admins(bot: Bot, text: str) -> None:
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception:
            pass


async def _tick(bot: Bot) -> None:
    row = await _state(force=True)
    if not row:
        row = await ensure_started()
    now_tk = _now_tk()

    # 1. Announce at the first 09:00 on or after launch.
    if (row.get("announced_at") is None
            and ANNOUNCE_HOUR <= now_tk.hour < ANNOUNCE_HOUR + ANNOUNCE_WINDOW_HOURS):
        prod = await gift_product(force=True)
        if not prod:
            # Don't announce a gift we can't find — tell the admins instead,
            # once a day, and keep checking.
            if await database.claim_gift_stock_alert(CAMPAIGN_KEY, now_tk.date()):
                await _notify_admins(bot, (
                    "⚠️ <b>Sovg'a kampaniyasi e'lon qilinmadi</b>\n"
                    "Katalogda faol <b>Eritritol 100gr</b> mahsuloti topilmadi. "
                    "Mahsulotni faollashtiring — e'lon avtomatik ketadi."))
            return
        sent, failed = await announce(bot)
        await _notify_admins(bot, (
            "🎁 <b>Sovg'a kampaniyasi boshlandi</b>\n"
            f"{fmt_sum(MIN_ORDER)} so'm va undan yuqori har bir buyurtmaga {prod['name']} — 30 kun.\n"
            f"📣 E'lon: ✅ {sent} ta yetkazildi, ⚠️ {failed} ta yetmadi.\n"
            f"📦 Ombordagi qoldiq: {fmt_sum(float(prod.get('quantity') or 0))}"))
        row = await _state(force=True)

    # 1b. The minimum was dropped mid-campaign: announce "now on EVERY order"
    # once, in daytime, to everyone (claimed before sending).
    if (_active_row(row) and MIN_ORDER <= 0
            and UPGRADE_WINDOW[0] <= now_tk.hour < UPGRADE_WINDOW[1]
            and await gift_product() is not None
            and await database.claim_release_notes(UPGRADE_KEY)):
        prod = await gift_product(force=True)
        sent, failed = await announce_upgrade(bot)
        await _notify_admins(bot, (
            "🎉 <b>E'lon yuborildi: Eritritol sovg'asi endi HAR BIR buyurtmaga</b>\n"
            "Minimal summa yo'q — botdagi istalgan buyurtmaga 100 gr Eritritol.\n"
            f"📣 ✅ {sent} ta yetkazildi, ⚠️ {failed} ta yetmadi.\n"
            f"📦 Ombordagi qoldiq: {fmt_sum(float((prod or {}).get('quantity') or 0))} — "
            "endi har buyurtmaga ketadi, zaxirani kuzatib boring."))

    # 2. Book every delivered gift into Chiqimlar.
    try:
        await book_delivered_gifts()
    except Exception:
        logger.exception("Gift expense booking failed")

    # 3. Campaign over → one wrap-up for the admins.
    if not _active_row(row) and row.get("ends_at") and row.get("ended_notified_at") is None:
        await book_delivered_gifts()
        stats = await database.get_gift_campaign_stats(CAMPAIGN_KEY)
        await database.mark_gift_ended_notified(CAMPAIGN_KEY)
        await _notify_admins(bot, (
            "🏁 <b>Sovg'a kampaniyasi tugadi</b>\n"
            f"🛒 Sovg'ali buyurtmalar: {stats['orders']} ta "
            f"(yetkazilgan: {stats['delivered']})\n"
            f"💰 Ularning summasi: {fmt_sum(stats['revenue'])} so'm\n"
            f"🎁 Chiqimlarga yozilgan sovg'alar: {fmt_sum(stats['cost'])} so'm"))
        return

    # Low / out-of-stock alerts for the gift product come from stock_alerts.py,
    # which watches every product the same way — no second alert from here.


async def stats_text() -> str:
    row = await _state(force=True)
    if not row:
        return "🎁 Sovg'a kampaniyasi hali boshlanmagan."
    stats = await database.get_gift_campaign_stats(CAMPAIGN_KEY)
    prod = await gift_product(force=True)
    if row.get("ends_at"):
        until = (row["ends_at"] + TZ_OFFSET).strftime("%d.%m.%Y %H:%M")
        status = "🟢 faol" if _active_row(row) else "🔴 tugagan"
        window = f"{status}, {until} gacha"
    else:
        window = f"⏳ hali boshlanmagan — {ANNOUNCE_HOUR:02d}:00 dagi e'lon bilan boshlanadi"
    return (
        "🎁 <b>Sovg'a kampaniyasi — Eritritol 100gr</b>\n"
        f"Holat: {window}\n"
        + (f"Shart: {fmt_sum(MIN_ORDER)} so'm va undan ortiq buyurtma\n\n" if MIN_ORDER > 0
           else "Shart: botdagi har qanday buyurtma (minimal summa yo'q)\n\n")
        + f"🛒 Sovg'ali buyurtmalar: <b>{stats['orders']}</b> "
        f"(yetkazilgan: {stats['delivered']})\n"
        f"👥 Sovg'a olgan mijozlar: <b>{stats['buyers']}</b> ta "
        f"(qo'lida: {stats['buyers_delivered']} ta)\n"
        f"💰 Ularning summasi: <b>{fmt_sum(stats['revenue'])} so'm</b>\n"
        f"🎁 Chiqimlarga yozildi: <b>{fmt_sum(stats['cost'])} so'm</b>\n"
        f"📦 Omborda: {fmt_sum(float(prod['quantity'])) + ' ta' if prod else 'mahsulot topilmadi'}"
    )


async def scheduler_loop(bot: Bot) -> None:
    try:
        await ensure_started()
        logger.info("Gift campaign %s armed", CAMPAIGN_KEY)
    except Exception:
        logger.exception("Gift campaign could not start")
    while True:
        try:
            await _tick(bot)
        except Exception:
            logger.exception("Gift campaign tick failed")
        await asyncio.sleep(CHECK_EVERY)
