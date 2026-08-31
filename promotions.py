"""
Aksiya / Bonus campaigns (2026-08-31).

An admin writes a campaign in the admin panel — name, how many days it runs,
the shartlar (terms) — attaches a list of bonus rules, and presses "Boshlash".
A bonus rule is read literally as:

    buy `trigger_quantity` of <trigger product>  ->  get `bonus_amount bonus_unit`
    of <bonus product> free

e.g. "1 kg Bodom uni -> 100 gr Eritritol". The bonus SCALES with the amount
bought (3 kg -> 300 gr), optionally capped per rule by max_bonus_amount.

Only one campaign runs at a time (see database.start_promotion) because the
bot and the Mini App both show "the current aksiya" in a single banner slot.

Bonuses are applied automatically, not just advertised: compute_bonuses()
turns a cart into free 0-so'm order lines that both checkout paths (the bot's
handlers/cart.py and the Mini App's webapp_server.py) append to the order
before create_order runs. Those lines are frozen into orders.items as JSON, so
editing or deleting a campaign later never rewrites an order already placed.

Public API:
  get_active()                       -> the running campaign (dict) or None, 60s cached
  compute_bonuses(promo, items)      -> free bonus lines for a cart/order item list
  bonuses_for_items(items)           -> the same, fetching the active campaign for you
  bonus_hint(promo, product_id, lang)-> "🎁 1 kg olsangiz — 100 gr Eritritol sovg'a!"
  banner(lang) / screen_text(lang)   -> short banner line / full aksiya screen
  to_stock_qty(amount, unit, product_unit) -> display amount -> products.quantity units
  announce(bot, promo)               -> one-time broadcast of a freshly started campaign
  scheduler_loop(bot)                -> closes campaigns out when their window ends
"""
import asyncio
import logging
import time
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import database
from config import ADMIN_IDS
from locales import get_display_unit

logger = logging.getLogger(__name__)

TZ_OFFSET = timedelta(hours=5)   # Asia/Tashkent, fixed UTC+5, no DST
CHECK_EVERY = 600                # expiry re-check, every 10 minutes
CACHE_TTL = 60                   # get_active() cache, seconds
SEND_DELAY = 0.05                # between announcement sends (Telegram rate limits)

# Units the admin can pick for a bonus amount, mapped to (dimension, factor to
# that dimension's base unit). Used only to translate the human amount ("100
# gr") into the bonus product's own stock unit ("0.1" when it's stocked in kg)
# — a cross-dimension or unknown pairing falls back to 1:1 rather than
# guessing, which is the safe direction: the admin still sees the real
# quantity in the order and can correct it while packing.
_UNIT_BASE = {
    "gr": ("mass", 0.001), "g": ("mass", 0.001), "kg": ("mass", 1.0),
    "ml": ("volume", 0.001), "l": ("volume", 1.0), "litr": ("volume", 1.0), "liter": ("volume", 1.0),
    "dona": ("count", 1.0), "piece": ("count", 1.0), "bundle": ("count", 1.0),
    "bog'lam": ("count", 1.0), "jar": ("count", 1.0), "banka": ("count", 1.0),
}

# Bonus-unit labels. Deliberately separate from locales.get_display_unit,
# which rewrites kg/g as "dona" for pre-packaged products — a 100 gr bonus has
# to read as "100 gr", not "100 dona".
_UNIT_LABEL = {
    "gr": {"uz": "gr", "ru": "гр"},
    "g": {"uz": "gr", "ru": "гр"},
    "kg": {"uz": "kg", "ru": "кг"},
    "ml": {"uz": "ml", "ru": "мл"},
    "l": {"uz": "litr", "ru": "л"},
    "litr": {"uz": "litr", "ru": "л"},
    "liter": {"uz": "litr", "ru": "л"},
    "dona": {"uz": "dona", "ru": "шт"},
    "piece": {"uz": "dona", "ru": "шт"},
    "bundle": {"uz": "bog'lam", "ru": "пучок"},
    "jar": {"uz": "banka", "ru": "банка"},
}

_cache: tuple[float, dict | None] = (0.0, None)


# ───────────────────────────── formatting ───────────────────────────────────

def unit_label(unit: str, lang: str) -> str:
    entry = _UNIT_LABEL.get((unit or "").lower())
    if not entry:
        return unit or ""
    return entry["ru"] if lang == "ru" else entry["uz"]


def fmt_amount(value: float) -> str:
    """Drop the ".0" on whole numbers — "100 gr", not "100.0 gr"."""
    value = float(value)
    return str(int(value)) if abs(value - round(value)) < 1e-9 else f"{value:g}"


def to_stock_qty(amount: float, unit: str, product_unit: str) -> float:
    """Convert a bonus amount as the admin typed it into the bonus product's
    own stock unit, so create_order can take it off products.quantity.
    Computed once when the rule is saved (not at checkout) so a later unit
    change on the product can't silently rewrite orders already placed."""
    src = _UNIT_BASE.get((unit or "").lower())
    dst = _UNIT_BASE.get((product_unit or "").lower())
    if not src or not dst or src[0] != dst[0]:
        return float(amount)
    return float(amount) * src[1] / dst[1]


def promo_name(promo: dict, lang: str) -> str:
    if lang == "ru" and promo.get("name_ru"):
        return promo["name_ru"]
    return promo.get("name") or ""


def promo_conditions(promo: dict, lang: str) -> str:
    if lang == "ru" and promo.get("conditions_ru"):
        return promo["conditions_ru"]
    return promo.get("conditions") or ""


def _product_name(rule: dict, side: str, lang: str) -> str:
    ru = rule.get(f"{side}_name_ru")
    if lang == "ru" and ru:
        return ru
    return rule.get(f"{side}_name") or ""


def days_left(promo: dict) -> int:
    """Whole days remaining, floor-at-0. Same naive-UTC arithmetic the rest of
    the codebase uses (CURRENT_TIMESTAMP columns are stored naive)."""
    ends_at = promo.get("ends_at")
    if not ends_at:
        return 0
    if isinstance(ends_at, str):
        try:
            ends_at = datetime.fromisoformat(ends_at)
        except ValueError:
            return 0
    delta = ends_at - datetime.utcnow()
    return max(0, int(delta.total_seconds() // 86400) + (1 if delta.total_seconds() % 86400 else 0))


def trigger_unit_label(rule: dict, lang: str) -> str:
    """The trigger side must use the SHOP's display unit, not the raw column.
    Packaged goods are stored with unit='kg'/'g' but sold and counted as
    pieces, which is why get_display_unit rewrites those to "dona" everywhere
    else in the app. Reading the raw unit here produced "2 kg Kokos shakari
    250gr" for what is really two packets — misleading, in a context where
    the buyer is counting out what to add to qualify for a gift."""
    return get_display_unit(rule.get("trigger_unit") or "piece", lang)


def rule_line(rule: dict, lang: str) -> str:
    """One bonus rule as a readable line:
    "1 dona Bodom uni → 100 gr Eritritol sovg'a" """
    trig_qty = fmt_amount(rule["trigger_quantity"])
    trig_unit = trigger_unit_label(rule, lang)
    trig_name = _product_name(rule, "trigger", lang)
    bonus = f"{fmt_amount(rule['bonus_amount'])} {unit_label(rule['bonus_unit'], lang)}"
    bonus_name = _product_name(rule, "bonus", lang)
    arrow = "→"
    if lang == "ru":
        return f"{trig_qty} {trig_unit} {trig_name} {arrow} {bonus} {bonus_name} в подарок"
    return f"{trig_qty} {trig_unit} {trig_name} {arrow} {bonus} {bonus_name} sovg'a"


def bonus_hint(promo: dict | None, product_id: int, lang: str) -> str | None:
    """The badge line for a product that triggers a bonus, or None. Shown on
    the bot's product card, in the catalog list, and on the Mini App card."""
    if not promo:
        return None
    for rule in promo.get("bonuses") or []:
        if rule["trigger_product_id"] == product_id:
            return "🎁 " + rule_line(rule, lang)
    return None


# ─────────────────────────── campaign lookup ────────────────────────────────

async def get_active(force: bool = False) -> dict | None:
    """The running campaign, cached for CACHE_TTL seconds. Every product card,
    cart render and catalog page asks for this, so the cache keeps a dormant
    or steady-state campaign from adding a query per view. Admin actions call
    invalidate() so a start/stop shows up immediately."""
    global _cache
    now = time.monotonic()
    if not force and _cache[0] > now:
        return _cache[1]
    try:
        promo = await database.get_active_promotion()
    except Exception:
        logger.exception("get_active_promotion failed")
        return _cache[1]
    _cache = (now + CACHE_TTL, promo)
    return promo


def invalidate() -> None:
    global _cache
    _cache = (0.0, None)


async def refresh() -> dict | None:
    """Force a re-read and update the shared cache. Called after every admin
    start/stop/edit so the change is live everywhere at once — including the
    synchronous keyboard builders below, which can't await."""
    return await get_active(force=True)


def cached_active() -> dict | None:
    """Last-known campaign with no DB round-trip, for synchronous callers —
    keyboards.py builds the main menu without an event loop to await on, and
    threading async through its 25 call sites would buy nothing: the value is
    refreshed on every admin action (refresh()) and on every scheduler tick,
    so the worst case here is a stale button for one tick."""
    return _cache[1]


# ────────────────────────── bonus computation ───────────────────────────────

def compute_bonuses(promo: dict | None, items: list[dict]) -> list[dict]:
    """Free bonus lines earned by `items` (cart rows or order items).

    Multiplies: 3 kg of a "1 kg -> 100 gr" trigger earns 300 gr, capped by the
    rule's max_bonus_amount when set. Rules pointing at the same bonus product
    are merged into one line so the buyer sees "300 gr Eritritol", not three
    separate 100 gr rows.

    Quantities of the same trigger product are summed across cart rows first,
    so two separate 1 kg lines earn the same bonus as one 2 kg line. Set
    (to'plam) rows are skipped — their member products are not exploded here,
    since a set already carries its own bundled discount."""
    if not promo:
        return []
    rules = promo.get("bonuses") or []
    if not rules:
        return []

    bought: dict[int, float] = {}
    for item in items:
        if item.get("is_bonus") or item.get("is_set"):
            continue
        pid = item.get("product_id") or item.get("id")
        if not pid:
            continue
        bought[int(pid)] = bought.get(int(pid), 0.0) + float(item.get("quantity") or 0)

    merged: dict[tuple[int, str], dict] = {}
    for rule in rules:
        trigger_qty = float(rule["trigger_quantity"]) or 1.0
        have = bought.get(int(rule["trigger_product_id"]), 0.0)
        # +1e-9 so float noise (0.30000000000000004 // 0.1) can't eat a step.
        times = int((have + 1e-9) // trigger_qty)
        if times <= 0:
            continue

        per_step = float(rule["bonus_amount"])
        amount = per_step * times
        cap = rule.get("max_bonus_amount")
        if cap:
            amount = min(amount, float(cap))
        if amount <= 0 or per_step <= 0:
            continue
        # Scale the pre-computed stock quantity by the same factor the display
        # amount grew by, so the two never drift apart.
        stock_qty = float(rule["bonus_stock_qty"]) * (amount / per_step)

        # What this giveaway is actually worth at shelf price — shown struck
        # through beside 0 so the bonus reads as money saved, not as a
        # nice-sounding "bepul" with no number attached. Scales with the
        # amount, in the bonus product's own stock units.
        unit_price = float(rule.get("bonus_price") or 0)
        value = unit_price * stock_qty

        key = (int(rule["bonus_product_id"]), rule["bonus_unit"])
        if key in merged:
            merged[key]["quantity"] += amount
            merged[key]["stock_quantity"] += stock_qty
            merged[key]["bonus_value"] += value
        else:
            merged[key] = {
                "product_id": int(rule["bonus_product_id"]),
                "set_id": None,
                "is_set": False,
                "is_bonus": True,
                "name": rule.get("bonus_name") or "",
                "name_ru": rule.get("bonus_name_ru"),
                "quantity": amount,
                "unit": rule["bonus_unit"],
                "stock_quantity": stock_qty,
                "price": 0,
                "original_price": 0,
                "discount_percent": 0,
                # What the buyer would have paid for it — display only. It is
                # deliberately NOT `original_price`, which the discount
                # renderers would pick up and turn into a fake "-100%" badge.
                "bonus_value": value,
                "photo_id": rule.get("bonus_photo_id"),
                "promo_name": promo.get("name"),
                "promo_name_ru": promo.get("name_ru"),
            }
    return list(merged.values())


def compute_near_misses(promo: dict | None, items: list[dict]) -> list[dict]:
    """Rules the cart is *close* to earning: "1 ta ko'proq oling — bonus sizniki".

    Only for trigger products already in the cart — nudging someone toward a
    product they never looked at would be an ad, not a helpful reminder. Rules
    already capped out are skipped (buying more earns nothing).

    Returns [{needed, unit, trigger_name(_ru), bonus_*, ...}] sorted by how
    little is missing, so the closest one can be shown first."""
    if not promo:
        return []

    bought: dict[int, float] = {}
    for item in items:
        if item.get("is_bonus") or item.get("is_set"):
            continue
        pid = item.get("product_id") or item.get("id")
        if not pid:
            continue
        bought[int(pid)] = bought.get(int(pid), 0.0) + float(item.get("quantity") or 0)

    out = []
    for rule in promo.get("bonuses") or []:
        pid = int(rule["trigger_product_id"])
        have = bought.get(pid, 0.0)
        if have <= 0:
            continue
        trigger_qty = float(rule["trigger_quantity"]) or 1.0
        times = int((have + 1e-9) // trigger_qty)

        cap = rule.get("max_bonus_amount")
        per_step = float(rule["bonus_amount"])
        if cap and per_step > 0 and times * per_step >= float(cap):
            continue  # already at the cap — one more unit earns nothing

        needed = trigger_qty * (times + 1) - have
        if needed <= 1e-9:
            continue
        out.append({
            "trigger_product_id": pid,
            "needed": needed,
            "trigger_unit": rule.get("trigger_unit"),
            "trigger_name": rule.get("trigger_name"),
            "trigger_name_ru": rule.get("trigger_name_ru"),
            "bonus_name": rule.get("bonus_name"),
            "bonus_name_ru": rule.get("bonus_name_ru"),
            "bonus_amount": per_step,
            "bonus_unit": rule["bonus_unit"],
        })
    out.sort(key=lambda r: r["needed"])
    return out


async def near_misses_for_items(items: list[dict]) -> list[dict]:
    return compute_near_misses(await get_active(), items)


def near_miss_text(misses: list[dict], lang: str, limit: int = 3) -> str:
    """"Yana 1 ta Bodom uni qo'shsangiz — 100 gr Eritritol sovg'a!" — the
    block shown under the cart. Empty string when there's nothing close."""
    if not misses:
        return ""
    head = "✨ <b>Bonusga oz qoldi:</b>" if lang != "ru" else "✨ <b>До бонуса совсем немного:</b>"
    lines = []
    for m in misses[:limit]:
        name = m.get("trigger_name_ru") if (lang == "ru" and m.get("trigger_name_ru")) else m.get("trigger_name")
        bonus_name = m.get("bonus_name_ru") if (lang == "ru" and m.get("bonus_name_ru")) else m.get("bonus_name")
        need = f"{fmt_amount(m['needed'])} {trigger_unit_label(m, lang)}"
        bonus = f"{fmt_amount(m['bonus_amount'])} {unit_label(m['bonus_unit'], lang)} {bonus_name}"
        if lang == "ru":
            lines.append(f"   • Ещё {need} «{name}» → {bonus} в подарок!")
        else:
            lines.append(f"   • Yana {need} «{name}» qo'shsangiz → {bonus} sovg'a!")
    return f"\n{head}\n" + "\n".join(lines) + "\n"


async def bonuses_for_items(items: list[dict]) -> list[dict]:
    """compute_bonuses against whatever campaign is running right now."""
    return compute_bonuses(await get_active(), items)


def bonus_label(bonus: dict, lang: str) -> str:
    """"Eritritol — 300 gr" — the product + amount half of a bonus line."""
    name = bonus.get("name_ru") if (lang == "ru" and bonus.get("name_ru")) else bonus.get("name")
    return f"{name} — {fmt_amount(bonus['quantity'])} {unit_label(bonus['unit'], lang)}"


def fmt_sum(value: float) -> str:
    """25000 -> "25 000" — the thin-space money format used everywhere else."""
    return f"{int(round(value)):,}".replace(",", " ")


def bonus_price_html(bonus: dict, lang: str) -> str:
    """"<s>25 000</s> 0 so'm" — the giveaway's shelf price struck through next
    to what the buyer actually pays. The strikethrough is the whole point: a
    plain "bepul" reads as worthless, the crossed-out number reads as money
    saved. Falls back to just "bepul" when we have no price to show."""
    free = "bepul" if lang != "ru" else "бесплатно"
    value = float(bonus.get("bonus_value") or 0)
    if value <= 0:
        return free
    return f"<s>{fmt_sum(value)}</s> <b>0</b> — {free}"


def bonuses_total_value(bonuses: list[dict]) -> float:
    return sum(float(b.get("bonus_value") or 0) for b in bonuses)


def bonus_lines_text(bonuses: list[dict], lang: str) -> str:
    """Bonus block appended to the cart, the order-confirm screen and the
    admin's new-order notification. Empty string when there are none, so
    callers can concatenate unconditionally."""
    if not bonuses:
        return ""
    head = "🎁 <b>SOVG'ALAR (aksiya):</b>" if lang != "ru" else "🎁 <b>ПОДАРКИ (акция):</b>"
    lines = "\n".join(f"   🎁 {bonus_label(b, lang)} — {bonus_price_html(b, lang)}" for b in bonuses)
    block = f"\n{head}\n{lines}\n"
    total = bonuses_total_value(bonuses)
    if total > 0:
        label = ("💚 Sovg'alar qiymati: <b>{v} so'm</b> — siz uchun bepul!"
                 if lang != "ru" else
                 "💚 Стоимость подарков: <b>{v} сум</b> — для вас бесплатно!")
        block += label.format(v=fmt_sum(total)) + "\n"
    return block


# ───────────────────────────── buyer-facing text ────────────────────────────

async def banner(lang: str) -> str:
    """One-line teaser prepended to the main menu / cart / catalog headers.
    Empty string when nothing is running, so every call site can just
    concatenate it in."""
    promo = await get_active()
    if not promo:
        return ""
    left = days_left(promo)
    if lang == "ru":
        tail = f" · осталось {left} дн." if left else ""
        return f"🎁 <b>АКЦИЯ:</b> {promo_name(promo, lang)}{tail}\n\n"
    tail = f" · {left} kun qoldi" if left else ""
    return f"🎁 <b>AKSIYA:</b> {promo_name(promo, lang)}{tail}\n\n"


async def screen_text(lang: str) -> str | None:
    """The full aksiya screen: name, remaining days, shartlar, and every bonus
    rule spelled out. None when no campaign is running."""
    promo = await get_active()
    if not promo:
        return None
    left = days_left(promo)
    parts = [f"🎁 <b>{promo_name(promo, lang)}</b>", ""]
    if left:
        parts.append(("⏳ Aksiyaga {n} kun qoldi" if lang != "ru" else "⏳ До конца акции {n} дн.").format(n=left))
        parts.append("")
    conditions = promo_conditions(promo, lang)
    if conditions:
        parts.append("📋 <b>Shartlar:</b>" if lang != "ru" else "📋 <b>Условия:</b>")
        parts.append(conditions)
        parts.append("")
    rules = promo.get("bonuses") or []
    if rules:
        parts.append("🎁 <b>Bonus mahsulotlar:</b>" if lang != "ru" else "🎁 <b>Бонусные товары:</b>")
        for rule in rules:
            parts.append(f"   • {rule_line(rule, lang)}")
        parts.append("")
        parts.append(
            "Bonus savatga avtomatik qo'shiladi — hech narsa qilishingiz shart emas."
            if lang != "ru" else
            "Бонус добавляется в корзину автоматически — ничего делать не нужно."
        )
    return "\n".join(parts).strip()


# ───────────────────────────── announcement ─────────────────────────────────

async def announce(bot: Bot, promo: dict) -> tuple[int, int]:
    """One-time "aksiya boshlandi" broadcast to every registered user.

    Returns (sent, failed). Marks the campaign announced so the admin panel
    can grey the button out and a stray second press can't spam everyone."""
    user_ids = await database.get_all_user_ids()
    sent = failed = 0
    for user_id in user_ids:
        # Per-user language, like every other broadcast in the bot — everyone
        # reads this in their own saved uz/uz_cyr/ru, not one site-wide default.
        lang = await database.get_user_language(user_id)
        text = _announcement_text(promo, lang)
        try:
            if promo.get("image_url"):
                # image_url is our own /img/N route; Telegram can't fetch a
                # relative path, so fall back to text when there's no public
                # base URL configured.
                photo = _absolute_image(promo["image_url"])
                if photo:
                    await bot.send_photo(user_id, photo, caption=text[:1024], parse_mode=ParseMode.HTML)
                else:
                    await bot.send_message(user_id, text, parse_mode=ParseMode.HTML)
            else:
                await bot.send_message(user_id, text, parse_mode=ParseMode.HTML)
            sent += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)
            failed += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            failed += 1          # blocked the bot / never started it
        except Exception:
            logger.exception("Aksiya announcement to %s failed", user_id)
            failed += 1
        await asyncio.sleep(SEND_DELAY)

    await database.mark_promotion_announced(promo["id"])
    await refresh()
    return sent, failed


def _absolute_image(image_url: str) -> str | None:
    from config import WEBAPP_URL
    if image_url.startswith("http"):
        return image_url
    if not WEBAPP_URL:
        return None
    return WEBAPP_URL.rstrip("/") + "/" + image_url.lstrip("/")


def _announcement_text(promo: dict, lang: str) -> str:
    left = days_left(promo)
    head = "🎉 <b>YANGI AKSIYA!</b>" if lang != "ru" else "🎉 <b>НОВАЯ АКЦИЯ!</b>"
    parts = [head, "", f"🎁 <b>{promo_name(promo, lang)}</b>"]
    if left:
        parts.append(("⏳ {n} kun davom etadi" if lang != "ru" else "⏳ Длится {n} дн.").format(n=left))
    conditions = promo_conditions(promo, lang)
    if conditions:
        parts += ["", conditions]
    rules = promo.get("bonuses") or []
    if rules:
        parts += ["", "🎁 <b>Bonuslar:</b>" if lang != "ru" else "🎁 <b>Бонусы:</b>"]
        for rule in rules:
            parts.append(f"   • {rule_line(rule, lang)}")
    parts += ["", "👇 /start — do'konni oching" if lang != "ru" else "👇 /start — откройте магазин"]
    return "\n".join(parts)


# ────────────────────────────── scheduler ───────────────────────────────────

# ─────────────────── daily "bugungi sovg'alar" showcase ─────────────────────
# Owner request 2026-08-31: announce 3 bonuses a day, celebratory, with a
# button straight to each product — and explicitly "odamlarni asabiga
# tegmaydigan qilib". So: ONE message a day (not three), at midday rather than
# first thing, only while a campaign is running, only if the campaign has more
# than SHOWCASE_PER_DAY rules to be worth rotating, and never on a day the
# 2-day tips broadcast already went out (broadcast.py) — two pushes in one day
# is exactly what makes people mute a bot. Per-campaign kill switch on top.

SHOWCASE_HOUR = 12          # 12:00 Asia/Tashkent — clear of the 08:00 tips slot
SHOWCASE_PER_DAY = 3


def _showcase_slice(rules: list[dict], cursor: int, count: int) -> tuple[list[dict], int]:
    """`count` rules starting at `cursor`, wrapping around the end of the list.
    Returns (rules, next_cursor) — so every rule gets its turn over the run of
    the campaign instead of the first three being announced every day."""
    if not rules:
        return [], 0
    n = len(rules)
    count = min(count, n)
    picked = [rules[(cursor + i) % n] for i in range(count)]
    return picked, (cursor + count) % n


def showcase_text(promo: dict, rules: list[dict], lang: str) -> str:
    left = days_left(promo)
    if lang == "ru":
        parts = [f"🎉 <b>{promo_name(promo, lang)}</b>", "", "🎁 <b>Подарки дня:</b>", ""]
    else:
        parts = [f"🎉 <b>{promo_name(promo, lang)}</b>", "", "🎁 <b>Bugungi sovg'alar:</b>", ""]
    for rule in rules:
        parts.append(f"   🎁 {rule_line(rule, lang)}")
    parts.append("")
    if left:
        parts.append(("⏳ Aksiyaga {n} kun qoldi" if lang != "ru" else "⏳ До конца акции {n} дн.").format(n=left))
    parts.append(
        "👇 Mahsulotni ko'rish uchun bosing" if lang != "ru" else "👇 Нажмите, чтобы открыть товар"
    )
    return "\n".join(parts)


def showcase_keyboard(rules: list[dict], lang: str) -> InlineKeyboardMarkup:
    """One button per showcased product, straight to its card in the bot.
    `product:<id>` is the catalog handler's own callback (back_category and
    back_page default sensibly when omitted), so this needs no new handler."""
    rows = []
    seen = set()
    for rule in rules:
        pid = int(rule["trigger_product_id"])
        if pid in seen:
            continue
        seen.add(pid)
        name = _product_name(rule, "trigger", lang)
        rows.append([InlineKeyboardButton(text=f"🛒 {name[:40]}", callback_data=f"product:{pid}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _showcase_tick(bot: Bot) -> None:
    promo = await get_active()
    if not promo or not promo.get("showcase_enabled", True):
        return
    rules = promo.get("bonuses") or []
    if len(rules) <= SHOWCASE_PER_DAY:
        return  # nothing to rotate — the aksiya screen already lists them all

    now_tk = datetime.utcnow() + TZ_OFFSET
    if now_tk.hour < SHOWCASE_HOUR:
        return
    today = now_tk.date()
    if promo.get("last_showcase_date") == today:
        return

    # Don't stack on top of the 2-day tips broadcast — see broadcast.py.
    # last_sent_at is a naive-UTC timestamp, so compare it in Tashkent-local
    # terms, the same day boundary this showcase uses.
    try:
        state = await database.get_broadcast_state()
        last_tips = (state or {}).get("last_sent_at")
        if last_tips and (last_tips + TZ_OFFSET).date() == today:
            logger.info("Showcase skipped: tips broadcast already went out today")
            # Still claim the day, so tomorrow starts fresh rather than the
            # showcase firing the moment the tips guard stops matching.
            await database.advance_promotion_showcase(
                promo["id"], int(promo.get("showcase_cursor") or 0), today
            )
            await refresh()
            return
    except Exception:
        logger.exception("Could not read broadcast state; sending showcase anyway")

    picked, next_cursor = _showcase_slice(rules, int(promo.get("showcase_cursor") or 0), SHOWCASE_PER_DAY)
    if not picked:
        return

    # Claim the day BEFORE sending: a crash halfway through a fan-out must not
    # re-announce to everyone who already got it on the next tick.
    await database.advance_promotion_showcase(promo["id"], next_cursor, today)
    await refresh()

    user_ids = await database.get_all_user_ids()
    sent = failed = 0
    for user_id in user_ids:
        lang = await database.get_user_language(user_id)
        try:
            await bot.send_message(
                user_id,
                showcase_text(promo, picked, lang),
                parse_mode=ParseMode.HTML,
                reply_markup=showcase_keyboard(picked, lang),
            )
            sent += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)
            failed += 1
        except (TelegramForbiddenError, TelegramBadRequest):
            failed += 1
        except Exception:
            logger.exception("Showcase send to %s failed", user_id)
            failed += 1
        await asyncio.sleep(SEND_DELAY)

    logger.info("Aksiya showcase sent: %d ok, %d failed", sent, failed)
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                f"🎁 Bugungi sovg'alar e'lon qilindi ({len(picked)} ta bonus).\n"
                f"✅ {sent} ta yetkazildi, ⚠️ {failed} ta yetmadi.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


async def _tick(bot: Bot) -> None:
    ended = await database.expire_promotions()
    # Keep the shared cache warm on every tick, whether or not anything
    # expired — cached_active() is what the synchronous keyboard builders read.
    await refresh()

    # Daily 3-bonus announcement. Its own guards decide whether today is a
    # send day; failure here must not stop expiry from being reported.
    try:
        await _showcase_tick(bot)
    except Exception:
        logger.exception("Showcase tick failed")

    if not ended:
        return
    for promo in ended:
        text = f"⏹ Aksiya tugadi: <b>{promo.get('name')}</b>\n\nBonuslar endi berilmaydi."
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
            except Exception:
                pass


async def scheduler_loop(bot: Bot) -> None:
    """Closes a campaign out the moment its window ends, so bonuses stop being
    granted even if nobody touches the admin panel. Cheap no-op tick when
    nothing is running (one UPDATE that matches no rows)."""
    await asyncio.sleep(30)  # let startup settle
    while True:
        try:
            await _tick(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Promotion scheduler tick failed")
        await asyncio.sleep(CHECK_EVERY)
