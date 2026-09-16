"""
Keto gamification — earn-only test rollout (2026-07-26).

Every delivered order placed by a real buyer through the bot/webapp earns
Keto coins (1% of the product subtotal, delivery fee excluded). No spending
mechanism yet — this is deliberately earn-only so the owner can watch whether
it moves engagement before building redemption. Toggle off instantly with
/keto_off (see handlers/broadcast_admin.py) without a redeploy.

Design notes:
  - keto_balance vs keto_lifetime (both on users): balance is spendable
    (currently == lifetime since nothing is ever deducted); lifetime drives
    levels/achievements so a future "spend" feature can't demote someone.
  - One order pays out at most once (keto_ledger partial unique index).
  - Admin/internal accounts and manual/B2B orders never earn — see
    LEADERBOARD_EXCLUDED_USER_IDS and add_manual_order/add_b2b_order notes.
  - Levels and achievement thresholds are tuned for this shop's real scale:
    ~250k so'm average order -> ~2500 Keto/order (see reward_calc in the
    2026-07-26 chat for the math this was validated against).

Public API:
  award_keto_for_order(order, bot)   -> called after an order flips to
                                         'delivered' (handlers/seller.py)
  ensure_pinned_card(bot, user_id)   -> (re)pin/refresh a user's Keto card
  scheduler_loop(bot)                -> daily 00:0x refresh of every pinned card
  get_level(keto_lifetime)           -> dict
  get_profile(user_id)               -> dict for the Kabinetim screen
"""
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest

import database
from config import ADMIN_IDS

logger = logging.getLogger(__name__)

EARN_RATE = 0.005  # 0.5% of product subtotal, as Keto (owner: 2026-07-27, down from 1%)

# Sadoqat darajalari (2026-09-17): the higher the buyer's level, the bigger
# the cashback on their next order — the rate is taken from the level they
# held BEFORE the order, so crossing a threshold pays off from the next one.
# Bronza keeps the original EARN_RATE.
EARN_RATES = {"bronze": EARN_RATE, "silver": 0.01, "gold": 0.02, "diamond": 0.03}

TZ_OFFSET = timedelta(hours=5)  # Asia/Tashkent, fixed UTC+5, no DST
PIN_REFRESH_HOUR = 0            # fires shortly after 00:00 Tashkent (checked every 15 min, like db_backup.py)
CHECK_EVERY = 900


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


async def is_enabled() -> bool:
    state = await database.get_gamification_state()
    return bool(state["enabled"])


async def is_redemption_enabled(user_id: int | None = None) -> bool:
    """Keto-as-discount at checkout — separate switch from earning above, off
    by default (2026-07-30: built for the owner to turn on later; real users
    can't use it while this is False, no matter their balance).

    Partner bloggers are the one standing exception (2026-09-01): their
    cashback IS a Keto balance and the whole point of it is that they spend
    it in the shop, so spending is open to them whether or not the global
    switch is on. Pass the buyer's user_id wherever it's known."""
    state = await database.get_gamification_state()
    if not state["enabled"]:
        return False
    if state["redemption_enabled"]:
        return True
    if user_id is not None:
        blogger = await database.get_blogger_by_user_id(user_id)
        return bool(blogger and blogger["active"])
    return False


def _fmt(n: int) -> str:
    return f"{int(n):,}".replace(",", " ")


# Ordered highest-threshold-first — get_level returns the first match.
LEVELS = [
    {"code": "diamond", "threshold": 30_000, "emoji": "💎", "label": {"uz": "Olmos", "ru": "Алмаз"}},
    {"code": "gold",     "threshold": 10_000, "emoji": "🥇", "label": {"uz": "Oltin", "ru": "Золото"}},
    {"code": "silver",   "threshold": 3_000,  "emoji": "🥈", "label": {"uz": "Kumush", "ru": "Серебро"}},
    {"code": "bronze",   "threshold": 0,      "emoji": "🥉", "label": {"uz": "Bronza", "ru": "Бронза"}},
]


def _L(lang: str):
    """uz / uz_cyr / ru picker — every buyer reads their own script."""
    def pick(uz: str, ru: str) -> str:
        if lang == "ru":
            return ru
        if lang == "uz_cyr":
            from translit import lat_to_cyr
            return lat_to_cyr(uz)
        return uz
    return pick


def earn_rate(keto_lifetime: int) -> float:
    return EARN_RATES.get(get_level(keto_lifetime)["code"], EARN_RATE)


def rate_label(rate: float) -> str:
    pct = rate * 100
    return f"{pct:.1f}".rstrip("0").rstrip(".") + "%"


def keto_for(amount_som: float, rate: float) -> int:
    """Keto a purchase of `amount_som` earns — the exact rounding
    award_keto_for_order uses, so the badge never promises more."""
    return int(float(amount_som or 0) * rate)


async def buyer_rate(user_id: int) -> float | None:
    """The cashback rate to SHOW this buyer next to prices ("🥑 +250 Keto"),
    or None when there is nothing to show (program switched off, or a shop
    account that never earns)."""
    if user_id in database.LEADERBOARD_EXCLUDED_USER_IDS:
        return None
    try:
        if not await is_enabled():
            return None
        user = await database.get_user(user_id)
    except Exception:
        logger.warning("Keto rate lookup failed for %s", user_id, exc_info=True)
        return None
    return earn_rate(int((user or {}).get("keto_lifetime") or 0))


def reward_badge(keto: int) -> str:
    """'🥑+250' — the compact tag after a cart line; same in every language."""
    return f"🥑+{_fmt(keto)}" if keto > 0 else ""


def product_reward_line(keto: int, rate: float, lang: str) -> str:
    if keto <= 0:
        return ""
    return _L(lang)(
        f"🥑 <b>+{_fmt(keto)} Keto</b> tangacha qaytadi (keshbek {rate_label(rate)})",
        f"🥑 <b>+{_fmt(keto)} Keto</b> монеток вернётся (кешбэк {rate_label(rate)})",
    )


def order_reward_line(keto: int, lang: str) -> str:
    if keto <= 0:
        return ""
    return _L(lang)(
        f"🥑 Bu xariddan Sizga <b>+{_fmt(keto)} Keto</b> tangacha qaytadi",
        f"🥑 С этой покупки вам вернётся <b>+{_fmt(keto)} Keto</b>",
    )


def get_level(keto_lifetime: int) -> dict:
    for lvl in LEVELS:
        if keto_lifetime >= lvl["threshold"]:
            return lvl
    return LEVELS[-1]


def get_next_level(keto_lifetime: int) -> dict | None:
    """The next level up, or None if already at the top."""
    current = get_level(keto_lifetime)
    idx = LEVELS.index(current)
    return LEVELS[idx - 1] if idx > 0 else None


ACHIEVEMENTS = [
    {
        "code": "first_order",
        "emoji": "🌱",
        "title": {"uz": "Birinchi qadam", "ru": "Первый шаг"},
        "desc": {"uz": "Birinchi buyurtmangiz yetkazib berildi",
                 "ru": "Ваш первый заказ доставлен"},
        "check": lambda ctx: ctx["orders_delivered"] >= 1,
    },
    {
        "code": "loyal_5",
        "emoji": "🔥",
        "title": {"uz": "Doimiy mijoz", "ru": "Постоянный клиент"},
        "desc": {"uz": "5 marta buyurtma yetkazib berildi",
                 "ru": "5 доставленных заказов"},
        "check": lambda ctx: ctx["orders_delivered"] >= 5,
    },
    {
        "code": "loyal_10",
        "emoji": "💎",
        "title": {"uz": "Sodiq xaridor", "ru": "Верный покупатель"},
        "desc": {"uz": "10 marta buyurtma yetkazib berildi",
                 "ru": "10 доставленных заказов"},
        "check": lambda ctx: ctx["orders_delivered"] >= 10,
    },
    {
        "code": "big_order",
        "emoji": "💰",
        "title": {"uz": "Katta xarid", "ru": "Крупная покупка"},
        "desc": {"uz": "Bitta buyurtmada 500 000 so'mdan ortiq xarid",
                 "ru": "Заказ на сумму более 500 000 сум"},
        "check": lambda ctx: ctx["order_total"] >= 500_000,
    },
    {
        "code": "keto_1000",
        "emoji": "🥑",
        "title": {"uz": "Keto boshlang'ich", "ru": "Первые Keto"},
        "desc": {"uz": "1 000 Keto to'plandi", "ru": "Накоплено 1 000 Keto"},
        "check": lambda ctx: ctx["keto_lifetime"] >= 1_000,
    },
    {
        "code": "keto_10000",
        "emoji": "🏆",
        "title": {"uz": "Keto ustasi", "ru": "Мастер Keto"},
        "desc": {"uz": "10 000 Keto to'plandi", "ru": "Накоплено 10 000 Keto"},
        "check": lambda ctx: ctx["keto_lifetime"] >= 10_000,
    },
    {
        "code": "loyal_3",
        "emoji": "🌟",
        "title": {"uz": "Qaytib keldi", "ru": "Снова с нами"},
        "desc": {"uz": "3 marta buyurtma yetkazib berildi",
                 "ru": "3 доставленных заказа"},
        "check": lambda ctx: ctx["orders_delivered"] >= 3,
    },
    {
        "code": "loyal_20",
        "emoji": "👑",
        "title": {"uz": "Afsonaviy mijoz", "ru": "Легендарный клиент"},
        "desc": {"uz": "20 marta buyurtma yetkazib berildi",
                 "ru": "20 доставленных заказов"},
        "check": lambda ctx: ctx["orders_delivered"] >= 20,
    },
    {
        "code": "mega_order",
        "emoji": "💎",
        "title": {"uz": "VIP xarid", "ru": "VIP-покупка"},
        "desc": {"uz": "Bitta buyurtmada 1 000 000 so'mdan ortiq xarid",
                 "ru": "Заказ на сумму более 1 000 000 сум"},
        "check": lambda ctx: ctx["order_total"] >= 1_000_000,
    },
    {
        "code": "keto_5000",
        "emoji": "🥈",
        "title": {"uz": "Kumushga yo'l", "ru": "Путь к серебру"},
        "desc": {"uz": "5 000 Keto to'plandi", "ru": "Накоплено 5 000 Keto"},
        "check": lambda ctx: ctx["keto_lifetime"] >= 5_000,
    },
    {
        "code": "keto_20000",
        "emoji": "🥇",
        "title": {"uz": "Oltinga yaqin", "ru": "Близко к золоту"},
        "desc": {"uz": "20 000 Keto to'plandi", "ru": "Накоплено 20 000 Keto"},
        "check": lambda ctx: ctx["keto_lifetime"] >= 20_000,
    },
    {
        "code": "keto_50000",
        "emoji": "👑",
        "title": {"uz": "Keto qiroli", "ru": "Король Keto"},
        "desc": {"uz": "50 000 Keto to'plandi", "ru": "Накоплено 50 000 Keto"},
        "check": lambda ctx: ctx["keto_lifetime"] >= 50_000,
    },
    {
        "code": "diamond_level",
        "emoji": "💎",
        "title": {"uz": "Olmos maqomi", "ru": "Статус \"Алмаз\""},
        "desc": {"uz": "Eng yuqori — Olmos darajasiga yetdingiz",
                 "ru": "Достигнут высший уровень — Алмаз"},
        "check": lambda ctx: ctx["keto_lifetime"] >= 30_000,
    },
    {
        "code": "spend_1m",
        "emoji": "💰",
        "title": {"uz": "1 million klub", "ru": "Клуб 1 миллиона"},
        "desc": {"uz": "Umumiy xaridlaringiz 1 000 000 so'mdan oshdi",
                 "ru": "Ваши покупки на сумму более 1 000 000 сум"},
        "check": lambda ctx: ctx["lifetime_spend"] >= 1_000_000,
    },
    {
        "code": "spend_5m",
        "emoji": "🏅",
        "title": {"uz": "5 million klub", "ru": "Клуб 5 миллионов"},
        "desc": {"uz": "Umumiy xaridlaringiz 5 000 000 so'mdan oshdi",
                 "ru": "Ваши покупки на сумму более 5 000 000 сум"},
        "check": lambda ctx: ctx["lifetime_spend"] >= 5_000_000,
    },
    {
        "code": "spend_10m",
        "emoji": "🏆",
        "title": {"uz": "10 million klub", "ru": "Клуб 10 миллионов"},
        "desc": {"uz": "Umumiy xaridlaringiz 10 000 000 so'mdan oshdi",
                 "ru": "Ваши покупки на сумму более 10 000 000 сум"},
        "check": lambda ctx: ctx["lifetime_spend"] >= 10_000_000,
    },
]


async def _lifetime_spend(user_id: int) -> float:
    """So'm spent on the buyer's own delivered orders (manual/B2B excluded)."""
    async with database.pool.acquire() as conn:
        return float(await conn.fetchval(
            "SELECT COALESCE(SUM(total), 0) FROM orders WHERE user_id = $1 AND status = 'delivered' "
            "AND COALESCE(source, 'bot') NOT IN ('manual', 'b2b')",
            user_id,
        ) or 0)


async def _check_new_achievements(user_id: int, ctx: dict) -> list[dict]:
    unlocked = await database.get_user_achievement_codes(user_id)
    newly = []
    for ach in ACHIEVEMENTS:
        if ach["code"] in unlocked:
            continue
        if ach["check"](ctx):
            if await database.unlock_achievement(user_id, ach["code"]):
                newly.append(ach)
    return newly


def _order_subtotal(order: dict) -> float:
    """Product-only total, excluding any delivery fee baked into order.total
    (webapp_server.py adds SELF_DELIVERY_FEE before saving self-courier
    orders) — recomputed from the line items themselves, the source of truth."""
    import json
    raw = order.get("items")
    items = json.loads(raw) if isinstance(raw, str) else (raw or [])
    return sum(float(it.get("price", 0)) * float(it.get("quantity", 0)) for it in items)


def _is_eligible(order: dict) -> bool:
    user_id = order.get("user_id")
    source = order.get("source")
    if user_id in ADMIN_IDS or user_id in database.LEADERBOARD_EXCLUDED_USER_IDS:
        return False
    if (source or "bot") in ("manual", "b2b"):
        return False
    return True


def build_award_message(lang: str, amount: int, new_balance: int, level: dict,
                         leveled_up: bool, new_achievements: list[dict],
                         lifetime: int | None = None, extra: str = "") -> str:
    L = _L(lang)
    lines = [
        L("🎉 <b>Tabriklaymiz! Sizga Keto berildi!</b>", "🎉 <b>Поздравляем! Вам начислены Keto!</b>"),
        L(f"🥑 +{_fmt(amount)} Keto", f"🥑 +{_fmt(amount)} Keto"),
        L(f"💰 Joriy balansingiz: <b>{_fmt(new_balance)} Keto</b>",
          f"💰 Ваш баланс: <b>{_fmt(new_balance)} Keto</b>"),
        L(f"{level['emoji']} Darajangiz: <b>{level['label']['uz']}</b>",
          f"{level['emoji']} Ваш уровень: <b>{level['label']['ru']}</b>"),
    ]
    if leveled_up:
        new_rate = rate_label(EARN_RATES.get(level["code"], EARN_RATE))
        lines.append(L(
            f"🎊 Yangi daraja ochildi: {level['emoji']} <b>{level['label']['uz']}</b>!\n"
            f"Endi har buyurtmangizdan <b>{new_rate}</b> Keto qaytadi.",
            f"🎊 Новый уровень открыт: {level['emoji']} <b>{level['label']['ru']}</b>!\n"
            f"Теперь с каждого заказа возвращается <b>{new_rate}</b> Keto.",
        ))
    if extra:
        lines.append(extra)
    if lifetime is not None:
        progress = next_level_progress(lifetime, lang)
        if progress:
            lines.append(progress)
    for ach in new_achievements:
        title = ach["title"]["ru" if lang == "ru" else "uz"]
        desc = ach["desc"]["ru" if lang == "ru" else "uz"]
        lines.append(L(
            f"🏆 Yangi yutuq: <b>{ach['emoji']} {title}</b>\n<i>{desc}</i>",
            f"🏆 Новое достижение: <b>{ach['emoji']} {title}</b>\n<i>{desc}</i>",
        ))
    lines.append(L(
        "👤 Barcha ma'lumot — <b>Kabinetim</b> bo'limida.",
        "👤 Все данные — в разделе <b>Кабинет</b>.",
    ))
    return "\n\n".join(lines)


async def award_keto_for_order(order: dict, bot: Bot) -> None:
    """Call right after an order transitions to status='delivered'. Best-effort:
    failures are logged, never raised, so a Keto bug can't block the buyer's
    real delivery notification."""
    try:
        state = await database.get_gamification_state()
        if not state["enabled"]:
            return
        if not _is_eligible(order):
            return

        subtotal = _order_subtotal(order)
        user_id = order["user_id"]
        prev_user = await database.get_user(user_id)
        prev_lifetime = int(prev_user.get("keto_lifetime") or 0) if prev_user else 0
        amount = int(subtotal * earn_rate(prev_lifetime))
        if amount <= 0:
            return

        credited = await database.credit_keto(
            user_id, order["id"], amount, kind="order",
            note=f"Buyurtma #{order['id']}",
        )
        if not credited:
            return  # already paid out for this order

        user = await database.get_user(user_id)
        new_balance = int(user["keto_balance"])
        new_lifetime = int(user["keto_lifetime"])
        level = get_level(new_lifetime)
        prev_level = get_level(prev_lifetime)
        leveled_up = level["code"] != prev_level["code"]

        orders_delivered = await database.count_user_delivered_orders(user_id)
        new_achievements = await _check_new_achievements(user_id, {
            "orders_delivered": orders_delivered,
            "keto_lifetime": new_lifetime,
            "order_total": subtotal,
            # The "1/5/10 million klub" checks read this. It was never passed,
            # so their KeyError aborted the award right after the Keto was
            # credited — no message, no pin refresh (found 2026-09-17).
            "lifetime_spend": await _lifetime_spend(user_id),
        })

        lang = await database.get_user_language(user_id)
        # A new level also opens a personal gift (retention.py) — announced
        # here, inside the award, so it never costs the buyer another push.
        extra = ""
        if leveled_up:
            import retention
            extra = await retention.levelup_offer_line(user_id, lang)
        if await is_redemption_enabled(user_id):
            spend = _L(lang)(
                f"🛒 Tangachalarni keyingi buyurtmada pul o'rniga ishlatishingiz mumkin: 1 Keto = 1 so'm.",
                f"🛒 Монетки можно потратить в следующем заказе вместо денег: 1 Keto = 1 сум.",
            )
            extra = f"{extra}\n\n{spend}" if extra else spend
        text = build_award_message(lang, amount, new_balance, level, leveled_up, new_achievements,
                                   lifetime=new_lifetime, extra=extra)
        # "Siz olgan X bilan boshqalar Y ham olishyapti" + a button to each —
        # the moment the order is in their hands is when it's most relevant.
        import json
        import retention
        raw = order.get("items")
        items = json.loads(raw) if isinstance(raw, str) else (raw or [])
        also_text, also_rows = await retention.also_bought_for_order(user_id, items, lang)
        markup = None
        if also_text:
            text += "\n\n" + also_text
            from aiogram.types import InlineKeyboardMarkup
            markup = InlineKeyboardMarkup(inline_keyboard=also_rows)
        try:
            await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            logger.warning("Keto award message failed for user %s", user_id, exc_info=True)

        await ensure_pinned_card(bot, user_id, lang)
    except Exception:
        logger.exception("award_keto_for_order failed for order %s", order.get("id"))


def next_level_progress(lifetime: int, lang: str) -> str:
    """'📈 Kumush darajasigacha ~120 000 so'mlik xarid' — Keto points turned
    into the money a buyer actually thinks in, at their current rate."""
    nxt = get_next_level(lifetime)
    if not nxt:
        return ""
    remaining = nxt["threshold"] - lifetime
    som = remaining / earn_rate(lifetime)
    som = int(-(-som // 10_000) * 10_000)          # round up to 10 000
    return _L(lang)(
        f"📈 {nxt['emoji']} {nxt['label']['uz']} darajasigacha: ~<b>{_fmt(som)} so'm</b>lik xarid "
        f"(keshbek {rate_label(EARN_RATES[nxt['code']])} bo'ladi)",
        f"📈 До уровня {nxt['emoji']} {nxt['label']['ru']}: покупки на ~<b>{_fmt(som)} сум</b> "
        f"(кешбэк станет {rate_label(EARN_RATES[nxt['code']])})",
    )


def build_pin_text(lang: str, full_name: str | None, balance: int, lifetime: int) -> str:
    level = get_level(lifetime)
    next_level = get_next_level(lifetime)
    L = _L(lang)
    name = full_name or L("Xaridor", "Покупатель")
    lines = [
        L("🥑 <b>Keto kartam</b>", "🥑 <b>Моя карта Keto</b>"),
        f"👤 {name}",
        L(f"💰 Balans: <b>{_fmt(balance)} Keto</b>", f"💰 Баланс: <b>{_fmt(balance)} Keto</b>"),
        f"{level['emoji']} " + L(f"Daraja: <b>{level['label']['uz']}</b> · keshbek {rate_label(earn_rate(lifetime))}",
                                 f"Уровень: <b>{level['label']['ru']}</b> · кешбэк {rate_label(earn_rate(lifetime))}"),
    ]
    if next_level:
        remaining = next_level["threshold"] - lifetime
        lines.append(L(
            f"📈 Keyingi darajagacha ({next_level['emoji']} {next_level['label']['uz']}): <b>{_fmt(remaining)} Keto</b>",
            f"📈 До следующего уровня ({next_level['emoji']} {next_level['label']['ru']}): <b>{_fmt(remaining)} Keto</b>",
        ))
    else:
        lines.append(L("🎉 Siz eng yuqori darajadasiz!", "🎉 Вы на самом высоком уровне!"))
    lines.append(L(
        f"\n🕐 Yangilandi: {_now_tk().strftime('%d.%m.%Y %H:%M')}",
        f"\n🕐 Обновлено: {_now_tk().strftime('%d.%m.%Y %H:%M')}",
    ))
    return "\n".join(lines)


async def ensure_pinned_card(bot: Bot, user_id: int, lang: str | None = None) -> None:
    """Edit the user's existing pinned Keto card in place, or create + pin a
    fresh one if they don't have one yet (first-ever award, or the old
    message got deleted/unpinned)."""
    user = await database.get_user(user_id)
    if not user:
        return
    if lang is None:
        lang = await database.get_user_language(user_id)
    text = build_pin_text(lang, user.get("full_name"), int(user["keto_balance"]), int(user["keto_lifetime"]))

    pin_id = user.get("keto_pin_message_id")
    if pin_id:
        try:
            await bot.edit_message_text(chat_id=user_id, message_id=pin_id, text=text, parse_mode="HTML")
            return
        except TelegramBadRequest as e:
            if "message is not modified" in str(e).lower():
                return  # content identical (e.g. two refreshes same minute) — nothing to do
            # otherwise the message is probably gone — fall through and recreate
        except Exception:
            pass  # unexpected — safest default is to fall through and recreate

    try:
        msg = await bot.send_message(user_id, text, parse_mode="HTML")
        await bot.pin_chat_message(chat_id=user_id, message_id=msg.message_id, disable_notification=True)
        await database.set_keto_pin_message_id(user_id, msg.message_id)
    except Exception:
        logger.warning("Could not create/pin Keto card for user %s", user_id, exc_info=True)


async def refresh_all_pins(bot: Bot) -> None:
    user_ids = await database.get_users_with_keto_pin()
    for uid in user_ids:
        try:
            await ensure_pinned_card(bot, uid)
        except Exception:
            logger.warning("Pin refresh failed for user %s", uid, exc_info=True)
        await asyncio.sleep(0.05)


async def scheduler_loop(bot: Bot) -> None:
    """Background task: refreshes every pinned Keto card once per Tashkent
    calendar day, shortly after 00:00 (checked every CHECK_EVERY seconds,
    same pattern as db_backup.py)."""
    logger.info("Keto pin-refresh scheduler started")
    while True:
        try:
            state = await database.get_gamification_state()
            now = _now_tk()
            today = now.date()
            already_done = state.get("last_pin_refresh_date") == today
            if state["enabled"] and not already_done and now.hour >= PIN_REFRESH_HOUR:
                await refresh_all_pins(bot)
                await database.set_gamification_pin_refresh_date(today)
                logger.info("Daily Keto pin refresh done")
        except Exception:
            logger.exception("Keto pin-refresh loop failed")
        await asyncio.sleep(CHECK_EVERY)


async def get_profile(user_id: int) -> dict:
    """Everything the Kabinetim screen needs in one call."""
    user = await database.get_user(user_id)
    balance = int(user["keto_balance"]) if user else 0
    lifetime = int(user["keto_lifetime"]) if user else 0
    level = get_level(lifetime)
    next_level = get_next_level(lifetime)
    unlocked_codes = await database.get_user_achievement_codes(user_id)
    return {
        "balance": balance,
        "lifetime": lifetime,
        "level": level,
        "next_level": next_level,
        "unlocked_codes": unlocked_codes,
        "achievements_unlocked": len(unlocked_codes),
        "achievements_total": len(ACHIEVEMENTS),
    }
