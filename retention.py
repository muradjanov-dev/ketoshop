"""
Qayta sotuv — mijozni to'g'ri paytda, bitta aniq sabab bilan qaytarish (2026-09-17).

Owner's brief: "5 dan tashqari qolgan hammasini qurib joriy qilishimiz kerak,
faqat mijozlar chalkashib ketmasliklari kerak". The five things built here:

  1. TUGASH ESLATMASI (replenish) — "Kokos unini 18 kun oldin olgan edingiz —
     tugab qolmadimi?" + one tap puts the same products, in the same amounts,
     back into the cart. The "when" is learnt from the data, most specific
     first: this buyer's own gap between purchases of that product → how long
     every buyer takes to come back for it → the shop-wide gap between orders.
  2. IKKINCHI BUYURTMA (second_checkin / second_lastcall) — 3 days after the
     first delivery: thank-you + a personal gift for the second order, valid
     14 days; a last call 3 days before it runs out.
  3. SOG'INDIK (winback_30 / 60 / 90) — soft hello at 30 days, a gift offer at
     60, the last one at 90. Nothing after that.
  4. DARAJA SOVG'ASI — reaching a new Keto level (gamification.py) opens a
     personal gift too. That rides inside the existing Keto award message, so
     it never costs an extra push.
  5. BOSHQALAR HAM OLISHYAPTI (cross-sell) — "Siz olgan X bilan boshqalar
     Y, Z ham olishyapti" + a button to each product's card. Never its own
     message: it rides inside the messages above and inside the Keto award
     sent on delivery. Picked from what other buyers actually ordered in the
     same basket; only in-stock products the buyer hasn't taken lately.

How confusion is prevented — the rules every send obeys:
  * ONE personal message per buyer per 7 days, whichever flow wants them —
    the most urgent wins (last call > check-in > replenish > win-back);
  * nothing while they have an order on its way, a cart they touched in the
    last 48 h (abandoned_cart.py talks to them then) or a cart reminder from
    the last day;
  * ONE gift at a time: an offer is never stacked on a live one, and an order
    carries at most one gift line — the campaign gift and a personal gift are
    the same Eritritol pack, so a qualifying order just consumes the offer;
  * one daily run at 09:30, before everything else that day; on a day a buyer
    hears from here, the 10:00 personal reco and the 18:00 interest nudge
    skip them (see recently_messaged_ids);
  * every message says exactly why it came, has one main button, and a
    "🔕 Kerak emas" opt-out (/eslatmalar turns it back on).

The gift itself is gift_campaign's line: gift_campaign.gift_lines() asks
active_offer() and tags the line with retention_offer_id, so the offer is
spent by the order that carries it (and comes back if that order is
cancelled while the offer is still valid). Delivered gifts are booked into
Chiqimlar by gift_campaign.book_delivered_gifts like any other.

Measured like the cart reminders: each message is credited with the first
order its buyer places within 7 days. /qaytarish shows it all.
"""
import asyncio
import html
import json
import logging
import statistics
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import database
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router(name="retention")

TZ_OFFSET = timedelta(hours=5)
RUN_AT = (9, 30)             # 09:30 Tashkent — ahead of the 10:00 reco
RUN_UNTIL_HOUR = 20          # a deploy after 20:00 waits for tomorrow
CHECK_EVERY = 300
SEND_DELAY = 0.05
MAX_PER_RUN = 300

MIN_GAP_DAYS = 7             # between two personal messages to one buyer
QUIET_AFTER_CART_HOURS = 48
ATTRIBUTION_DAYS = 7
OFFER_DAYS = 14
LEVELUP_OFFER_DAYS = 30
LAST_CALL_DAYS = 3           # "sovg'angiz 3 kundan keyin tugaydi"

# Replenish timing.
MIN_EVENT_GAP = 5            # two purchases closer than this are one restock
MIN_INTERVAL, MAX_INTERVAL = 10, 75
DEFAULT_INTERVAL = 30
DUE_EARLY, DUE_LATE = 2, 14  # window around the expected day
RECENT_ORDER_DAYS = 10       # ordered anything this recently → leave them be
MAX_REPLENISH_ITEMS = 2

SECOND_CHECKIN_DAYS = (3, 7)
WINBACK_STAGES = ((90, "winback_90"), (60, "winback_60"), (30, "winback_30"))
WINBACK_WINDOW = 7
OFFER_KINDS = {"second_checkin", "winback_60", "winback_90"}

OPEN_STATUSES = ("pending", "confirmed", "shipped", "delivering")
PRIORITY = ["second_lastcall", "second_checkin", "replenish",
            "winback_90", "winback_60", "winback_30"]

KIND_LABELS = {
    "replenish": "🔁 Tugash eslatmasi",
    "second_checkin": "🤍 2-buyurtma: rahmat + sovg'a",
    "second_lastcall": "⏳ 2-buyurtma: sovg'a tugayapti",
    "winback_30": "👋 30 kun: sog'indik",
    "winback_60": "🎁 60 kun: sovg'a bilan",
    "winback_90": "🎁 90 kun: oxirgi taklif",
}

_state_cache: dict | None = None


def _now_utc() -> datetime:
    return datetime.utcnow()


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


def fmt_sum(value: float) -> str:
    return f"{int(round(value or 0)):,}".replace(",", " ")


def _t(uz: str, ru: str, lang: str) -> str:
    if lang == "ru":
        return ru
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        return lat_to_cyr(uz)
    return uz


def _esc(value) -> str:
    return html.escape(str(value or ""))


# ─────────────────────────────── schema ─────────────────────────────────────

async def ensure_schema() -> None:
    async with database.pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS retention_state (
                id INTEGER PRIMARY KEY DEFAULT 1,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                last_run_date DATE,
                CONSTRAINT retention_state_single CHECK (id = 1)
            )
        """)
        await conn.execute("INSERT INTO retention_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
        # One row per message. `ref` names what the message was about (which
        # purchase, which offer), so the same reason is never sent twice.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS retention_messages (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                kind TEXT NOT NULL,
                ref TEXT NOT NULL,
                payload TEXT,
                offer_id INTEGER,
                delivered BOOLEAN NOT NULL DEFAULT FALSE,
                sent_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                clicked_at TIMESTAMP,
                converted_order_id INTEGER,
                converted_total DOUBLE PRECISION,
                UNIQUE (user_id, ref)
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_retention_messages_sent ON retention_messages(sent_at)")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS retention_offers (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                kind TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL,
                used_order_id INTEGER
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_retention_offers_user ON retention_offers(user_id, expires_at)")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS retention_optout (
                user_id BIGINT PRIMARY KEY,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)


async def get_state() -> dict:
    async with database.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT enabled, last_run_date FROM retention_state WHERE id = 1")
        return dict(row) if row else {"enabled": False, "last_run_date": None}


async def set_enabled(enabled: bool) -> None:
    async with database.pool.acquire() as conn:
        await conn.execute("UPDATE retention_state SET enabled = $1 WHERE id = 1", enabled)


async def _claim_run(day) -> bool:
    async with database.pool.acquire() as conn:
        row = await conn.fetchrow(
            """UPDATE retention_state SET last_run_date = $1
                WHERE id = 1 AND (last_run_date IS NULL OR last_run_date < $1)
                RETURNING id""", day)
        return row is not None


# ─────────────────────────────── offers ─────────────────────────────────────

# An offer counts as spent while a non-cancelled order carries its tag. json.
# dumps writes '"retention_offer_id": 12,' — the [,}] stops 12 matching 123.
_OFFER_SPENT_SQL = """EXISTS (SELECT 1 FROM orders o
                               WHERE o.user_id = r.user_id
                                 AND o.status <> 'cancelled'
                                 AND o.items ~ ('"retention_offer_id": ' || r.id || '[,}]'))"""


async def active_offer(user_id: int | None) -> dict | None:
    """The buyer's live personal gift offer, or None. Never raises — it sits
    on the checkout path."""
    if not user_id or user_id in ADMIN_IDS or user_id in database.LEADERBOARD_EXCLUDED_USER_IDS:
        return None
    try:
        async with database.pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""SELECT r.id, r.kind, r.expires_at FROM retention_offers r
                     WHERE r.user_id = $1 AND r.expires_at > CURRENT_TIMESTAMP
                       AND r.used_order_id IS NULL AND NOT {_OFFER_SPENT_SQL}
                     ORDER BY r.expires_at DESC LIMIT 1""",
                user_id,
            )
            return dict(row) if row else None
    except Exception:
        logger.warning("Could not read retention offer for %s", user_id, exc_info=True)
        return None


async def grant_offer(user_id: int, kind: str, days: int) -> dict | None:
    """Open a gift offer — unless one is already live, which is returned
    instead (one gift at a time). None when there's no gift to give."""
    live = await active_offer(user_id)
    if live:
        return live
    if not await gift_available():
        return None
    async with database.pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO retention_offers (user_id, kind, expires_at)
               VALUES ($1, $2, CURRENT_TIMESTAMP + make_interval(days => $3))
               RETURNING id, kind, expires_at""",
            user_id, kind, days,
        )
        return dict(row)


async def _drop_offer(offer_id: int) -> None:
    async with database.pool.acquire() as conn:
        await conn.execute("DELETE FROM retention_offers WHERE id = $1 AND used_order_id IS NULL", offer_id)


async def gift_available() -> dict | None:
    """The gift pack to promise in a personal offer — or None. While the
    Eritritol campaign gives the same pack on EVERY order (MIN_ORDER 0), a
    personal "sovg'a" would promise nothing extra and only confuse, so no new
    offers are opened then."""
    import gift_campaign
    if gift_campaign.MIN_ORDER <= 0 and await gift_campaign.is_active():
        return None
    prod = await gift_campaign.gift_product()
    if prod and float(prod.get("quantity") or 0) >= 1:
        return prod
    return None


async def mark_used_offers() -> None:
    """Stamp offers whose order was delivered — for the stats; active_offer
    already treats a pending order as spending it."""
    async with database.pool.acquire() as conn:
        await conn.execute(
            """UPDATE retention_offers r
                  SET used_order_id = (SELECT o.id FROM orders o
                                        WHERE o.user_id = r.user_id AND o.status = 'delivered'
                                          AND o.items ~ ('"retention_offer_id": ' || r.id || '[,}]')
                                        ORDER BY o.id LIMIT 1)
                WHERE r.used_order_id IS NULL
                  AND r.created_at >= CURRENT_TIMESTAMP - INTERVAL '120 days'""")


def offer_until_text(offer: dict, lang: str) -> str:
    return (offer["expires_at"] + TZ_OFFSET).strftime("%d.%m.%Y")


async def levelup_offer_line(user_id: int, lang: str) -> str:
    """Called from gamification when a buyer reaches a new level. Returns the
    line to add to the award message, or '' (no gift in stock, or disabled)."""
    try:
        if not (await get_state()).get("enabled") or await _opted_out(user_id):
            return ""
        offer = await grant_offer(user_id, "levelup", LEVELUP_OFFER_DAYS)
        prod = await gift_available()
        if not offer or not prod:
            return ""
        return _t(
            f"🎁 <b>Yangi daraja sovg'asi:</b> keyingi buyurtmangizga <b>{_esc(prod['name'])}</b> "
            f"bepul qo'shiladi — summadan qat'i nazar, {offer_until_text(offer, lang)} gacha.",
            f"🎁 <b>Подарок за новый уровень:</b> к следующему заказу бесплатно добавится "
            f"<b>{_esc(prod.get('name_ru') or prod['name'])}</b> — на любую сумму, до {offer_until_text(offer, lang)}.",
            lang)
    except Exception:
        logger.exception("Level-up offer failed for %s", user_id)
        return ""


# ─────────────────────────────── planning (pure) ────────────────────────────

def _parse_items(raw) -> list[dict]:
    try:
        items = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except (TypeError, ValueError):
        return []
    return [it for it in items if isinstance(it, dict)]


def line_key(item: dict) -> tuple[str, int] | None:
    """('s', set_id) / ('p', product_id) for a paid line, None for gifts."""
    if item.get("is_bonus") or item.get("is_gift"):
        return None
    if item.get("is_set") and item.get("set_id"):
        return ("s", int(item["set_id"]))
    if item.get("product_id"):
        return ("p", int(item["product_id"]))
    return None


def _when(order: dict) -> datetime:
    return order.get("delivered_at") or order["created_at"]


def purchase_events(orders: list[dict]) -> dict[tuple, list[dict]]:
    """key -> [{at, qty, order_id, name}] from DELIVERED orders, oldest first."""
    events: dict[tuple, list[dict]] = {}
    for o in sorted((o for o in orders if o["status"] == "delivered"), key=_when):
        seen = set()
        for it in o["items"]:
            key = line_key(it)
            if key is None or key in seen:
                continue
            seen.add(key)
            events.setdefault(key, []).append({
                "at": _when(o), "qty": float(it.get("quantity") or 1),
                "order_id": o["id"], "name": it.get("name") or "",
            })
    return events


def _gaps(dates: list[datetime]) -> list[int]:
    out, prev = [], None
    for d in sorted(dates):
        if prev is not None:
            gap = (d - prev).days
            if gap < MIN_EVENT_GAP:
                continue          # same restock split across two orders
            out.append(gap)
        prev = d
    return out


def learn_intervals(orders_by_user: dict[int, list[dict]]) -> tuple[dict[tuple, int], int]:
    """(median repurchase days per product, shop-wide median days between
    orders). A product needs 3 observed gaps before its median is trusted."""
    per_product: dict[tuple, list[int]] = {}
    order_gaps: list[int] = []
    for orders in orders_by_user.values():
        for key, evs in purchase_events(orders).items():
            per_product.setdefault(key, []).extend(_gaps([e["at"] for e in evs]))
        order_gaps.extend(_gaps([_when(o) for o in orders if o["status"] == "delivered"]))
    medians = {k: int(statistics.median(v)) for k, v in per_product.items() if len(v) >= 3}
    shop = int(statistics.median(order_gaps)) if len(order_gaps) >= 5 else DEFAULT_INTERVAL
    return medians, shop


def _clamp(days: int) -> int:
    return max(MIN_INTERVAL, min(MAX_INTERVAL, int(days)))


def replenish_due(orders: list[dict], product_medians: dict, shop_median: int,
                  now: datetime, available: dict) -> list[dict]:
    """Products this buyer is probably running out of, most overdue first.
    `available` = {key: catalogue row} of things that can be sold right now."""
    due = []
    for key, evs in purchase_events(orders).items():
        if key not in available:
            continue
        own = _gaps([e["at"] for e in evs])
        if own:
            interval, source = _clamp(statistics.median(own)), "user"
        elif key in product_medians:
            interval, source = _clamp(product_medians[key]), "product"
        else:
            interval, source = _clamp(shop_median), "shop"
        last = evs[-1]
        days = (now - last["at"]).days
        if interval - DUE_EARLY <= days <= interval + DUE_LATE:
            due.append({"key": key, "days": days, "interval": interval, "source": source,
                        "qty": last["qty"], "order_id": last["order_id"],
                        "name": available[key].get("name") or last["name"],
                        "name_ru": available[key].get("name_ru"),
                        "ratio": days / interval})
    due.sort(key=lambda d: d["ratio"], reverse=True)
    return due


def cross_sell_pairs(orders_by_user: dict[int, list[dict]]) -> dict[tuple, list[tuple[tuple, int]]]:
    """key -> [(other key, times bought in the same order)], best first."""
    counts: dict[tuple, dict[tuple, int]] = {}
    for orders in orders_by_user.values():
        for o in orders:
            if o["status"] == "cancelled":
                continue
            keys = {k for k in (line_key(it) for it in o["items"]) if k and k[0] == "p"}
            for a in keys:
                for b in keys:
                    if a != b:
                        counts.setdefault(a, {}).setdefault(b, 0)
                        counts[a][b] += 1
    return {a: sorted(bs.items(), key=lambda kv: kv[1], reverse=True) for a, bs in counts.items()}


def pick_also_bought(anchor_keys: list[tuple], pairs: dict, owned_recently: set,
                     available: dict, limit: int = 3, min_count: int = 2) -> tuple[tuple | None, list[tuple]]:
    """(the anchor they were bought with, [up to `limit` products]) — the
    products other buyers most often ordered together with what this buyer
    took. Only in-stock products they haven't bought lately."""
    for anchor in anchor_keys:
        picked = []
        for other, n in pairs.get(anchor, []):
            if n < min_count or len(picked) >= limit:
                break
            if other in owned_recently or other in anchor_keys or other not in available:
                continue
            if float(available[other].get("quantity") or 0) < 1:
                continue
            picked.append(other)
        if picked:
            return anchor, picked
    return None, []


def pick_cross_sell(anchor_keys: list[tuple], pairs: dict, owned_recently: set,
                    available: dict, min_count: int = 2) -> tuple | None:
    _, picked = pick_also_bought(anchor_keys, pairs, owned_recently, available, 1, min_count)
    return picked[0] if picked else None


def also_bought_text(anchor: dict, products: list[dict], lang: str) -> str:
    names = ", ".join(f"<b>{_pname(p, lang)}</b>" for p in products)
    return _t(f"🧺 Siz olgan <b>{_pname(anchor, lang)}</b> bilan boshqalar {names} ham olishyapti 👇",
              f"🧺 Вы взяли <b>{_pname(anchor, lang)}</b> — другие покупатели к нему ещё берут {names} 👇",
              lang)


def also_bought_rows(products: list[dict], lang: str) -> list[list[InlineKeyboardButton]]:
    """One button per product, straight to its card in the catalogue."""
    return [[InlineKeyboardButton(text=_t(f"🛒 {html.unescape(_pname(p, lang))}",
                                          f"🛒 {html.unescape(_pname(p, lang))}", lang)[:60],
                                  callback_data=f"product:{p['id']}")] for p in products]


_PAIRS_TTL = 3600
_pairs_cache: tuple[float, dict] = (0.0, {})


async def _cached_pairs() -> dict:
    global _pairs_cache
    import time
    ts, pairs = _pairs_cache
    if time.monotonic() - ts > _PAIRS_TTL:
        pairs = cross_sell_pairs(await _load_orders())
        _pairs_cache = (time.monotonic(), pairs)
    return pairs


async def also_bought_for_order(user_id: int, items: list[dict], lang: str
                                ) -> tuple[str, list[list[InlineKeyboardButton]]]:
    """Block + buttons for a message about an order the buyer just received
    (the Keto award on delivery). ('', []) when there's nothing honest to say.
    Never raises."""
    try:
        anchors = [k for k in (line_key(it) for it in items) if k and k[0] == "p"]
        if not anchors:
            return "", []
        available = await _load_available()
        recent = set()
        for o in (await _load_orders(user_id)).get(user_id, []):
            if o["status"] != "cancelled" and (_now_utc() - o["created_at"]).days <= 60:
                recent.update(k for k in (line_key(it) for it in o["items"]) if k)
        anchor, picked = pick_also_bought(anchors, await _cached_pairs(), recent, available)
        if not picked:
            return "", []
        products = [available[k] for k in picked]
        return also_bought_text(available.get(anchor) or {"name": ""}, products, lang), \
            also_bought_rows(products, lang)
    except Exception:
        logger.exception("Also-bought block failed for %s", user_id)
        return "", []


def plan_for_user(uid: int, orders: list[dict], now: datetime, ctx: dict) -> dict | None:
    """The single message this buyer should get today, or None.

    ctx: product_medians, shop_median, available, pairs, sent_refs (set of
    refs already used for this user), offer (live offer or None),
    last_message_at, cart_touched_at, cart_reminded_at, opted_out."""
    if ctx.get("opted_out"):
        return None
    live = [o for o in orders if o["status"] != "cancelled"]
    if not live:
        return None
    if any(o["status"] in OPEN_STATUSES for o in live):
        return None
    last_msg = ctx.get("last_message_at")
    if last_msg and (now - last_msg).days < MIN_GAP_DAYS:
        return None
    for field, hours in (("cart_touched_at", QUIET_AFTER_CART_HOURS), ("cart_reminded_at", 24)):
        at = ctx.get(field)
        if at and now - at < timedelta(hours=hours):
            return None

    sent = ctx.get("sent_refs") or set()
    delivered = [o for o in live if o["status"] == "delivered"]
    if not delivered:
        return None
    last_order = max(live, key=lambda o: o["created_at"])
    days_since_order = (now - last_order["created_at"]).days
    offer = ctx.get("offer")
    candidates = []

    # 2. Second order.
    if len(live) == 1:
        first = delivered[0]
        d = (now - _when(first)).days
        ref = f"second_checkin:{first['id']}"
        if SECOND_CHECKIN_DAYS[0] <= d <= SECOND_CHECKIN_DAYS[1] and ref not in sent:
            candidates.append({"kind": "second_checkin", "ref": ref, "order_id": first["id"], "days": d})
        if offer and offer.get("kind") == "second_checkin":
            left = (offer["expires_at"] - now).total_seconds() / 86400
            ref = f"second_lastcall:{offer['id']}"
            if 0 < left <= LAST_CALL_DAYS and ref not in sent:
                candidates.append({"kind": "second_lastcall", "ref": ref, "order_id": first["id"],
                                   "days_left": max(1, round(left))})

    # 1. Replenish — only for buyers who haven't just ordered.
    if days_since_order >= RECENT_ORDER_DAYS:
        due = [d for d in replenish_due(delivered, ctx["product_medians"], ctx["shop_median"],
                                        now, ctx["available"])
               if f"replenish:{d['key'][0]}{d['key'][1]}:{d['order_id']}" not in sent]
        if due:
            picked = due[:MAX_REPLENISH_ITEMS]
            candidates.append({"kind": "replenish", "items": picked,
                               "ref": f"replenish:{picked[0]['key'][0]}{picked[0]['key'][1]}:{picked[0]['order_id']}",
                               "extra_refs": [f"replenish:{d['key'][0]}{d['key'][1]}:{d['order_id']}"
                                              for d in picked[1:]],
                               "order_id": picked[0]["order_id"]})

    # 3. Win-back.
    for threshold, kind in WINBACK_STAGES:
        ref = f"{kind}:{last_order['id']}"
        if threshold <= days_since_order < threshold + WINBACK_WINDOW and ref not in sent:
            last_delivered = max(delivered, key=_when)
            candidates.append({"kind": kind, "ref": ref, "order_id": last_delivered["id"],
                               "days": days_since_order})
            break

    if not candidates:
        return None
    best = min(candidates, key=lambda c: PRIORITY.index(c["kind"]))

    # 5. "Siz olgan X bilan boshqalar Y ham olishyapti", anchored on what the
    # message is about. Not on the gift reminders — one ask per message.
    if best["kind"] in ("replenish", "second_checkin", "winback_30"):
        if best["kind"] == "replenish":
            anchors = [d["key"] for d in best["items"]]
        else:
            anchors = [k for k in (line_key(it) for it in
                       next(o for o in delivered if o["id"] == best["order_id"])["items"]) if k]
        recent = {k for o in live if (now - o["created_at"]).days <= 60
                  for k in (line_key(it) for it in o["items"]) if k}
        anchor, picked = pick_also_bought([a for a in anchors if a[0] == "p"], ctx.get("pairs") or {},
                                          recent, ctx["available"], limit=2)
        if picked:
            best["also"] = (anchor, picked)
    return best


# ─────────────────────────────── data loading ───────────────────────────────

def _excluded_ids() -> list[int]:
    return list(set(ADMIN_IDS) | set(database.LEADERBOARD_EXCLUDED_USER_IDS))


async def _load_orders(user_id: int | None = None) -> dict[int, list[dict]]:
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT o.id, o.user_id, o.status, o.created_at, o.delivered_at, o.items
                  FROM orders o
                 WHERE {database._REAL_ORDER}
                   AND o.created_at >= CURRENT_TIMESTAMP - INTERVAL '400 days'
                   AND o.user_id <> ALL($1::bigint[])
                   AND ($2::bigint IS NULL OR o.user_id = $2)""",
            _excluded_ids(), user_id,
        )
    out: dict[int, list[dict]] = {}
    for r in rows:
        d = dict(r)
        d["items"] = _parse_items(d["items"])
        out.setdefault(d["user_id"], []).append(d)
    return out


async def _load_available() -> dict[tuple, dict]:
    async with database.pool.acquire() as conn:
        prods = await conn.fetch(
            "SELECT id, name, name_ru, quantity, price, unit FROM products WHERE is_active = 1 AND quantity > 0")
        sets = await conn.fetch("SELECT id, name, name_ru FROM product_sets WHERE is_active = 1")
    out = {("p", r["id"]): dict(r) for r in prods}
    out.update({("s", r["id"]): dict(r) for r in sets})
    return out


async def _load_context(user_ids: list[int]) -> dict:
    async with database.pool.acquire() as conn:
        sent = await conn.fetch(
            "SELECT user_id, ref, sent_at FROM retention_messages WHERE user_id = ANY($1::bigint[])", user_ids)
        offers = await conn.fetch(
            f"""SELECT r.id, r.user_id, r.kind, r.expires_at FROM retention_offers r
                 WHERE r.user_id = ANY($1::bigint[]) AND r.expires_at > CURRENT_TIMESTAMP
                   AND r.used_order_id IS NULL AND NOT {_OFFER_SPENT_SQL}""", user_ids)
        carts = await conn.fetch(
            "SELECT user_id, MAX(updated_at) AS at FROM cart WHERE user_id = ANY($1::bigint[]) "
            "GROUP BY user_id", user_ids)
        reminders = await conn.fetch(
            "SELECT user_id, MAX(sent_at) AS at FROM cart_reminders WHERE user_id = ANY($1::bigint[]) "
            "GROUP BY user_id", user_ids)
        optout = await conn.fetch(
            "SELECT user_id FROM retention_optout WHERE user_id = ANY($1::bigint[])", user_ids)
        banned = await conn.fetch("SELECT user_id FROM banned_users")
        users = await conn.fetch(
            "SELECT user_id, full_name, language FROM users WHERE user_id = ANY($1::bigint[])", user_ids)
    ctx: dict = {"sent": {}, "last": {}, "offers": {}, "cart": {}, "reminded": {},
                 "optout": {r["user_id"] for r in optout} | {r["user_id"] for r in banned},
                 "users": {r["user_id"]: dict(r) for r in users}}
    for r in sent:
        ctx["sent"].setdefault(r["user_id"], set()).add(r["ref"])
        prev = ctx["last"].get(r["user_id"])
        if prev is None or r["sent_at"] > prev:
            ctx["last"][r["user_id"]] = r["sent_at"]
    for r in offers:
        ctx["offers"][r["user_id"]] = dict(r)
    ctx["cart"] = {r["user_id"]: r["at"] for r in carts if r["at"]}
    ctx["reminded"] = {r["user_id"]: r["at"] for r in reminders if r["at"]}
    return ctx


async def build_plans(only_user: int | None = None, ignore_limits: bool = False) -> list[tuple[int, dict]]:
    """[(user_id, plan)] for today, most urgent kinds first. The intervals and
    pairs are always learnt from every buyer, even for a one-user preview."""
    orders_by_user = await _load_orders()
    medians, shop = learn_intervals(orders_by_user)
    pairs = cross_sell_pairs(orders_by_user)
    available = await _load_available()
    targets = [only_user] if only_user is not None else list(orders_by_user)
    targets = [u for u in targets if u in orders_by_user]
    if not targets:
        return []
    c = await _load_context(targets)
    now = _now_utc()
    plans = []
    for uid in targets:
        ctx = {
            "product_medians": medians, "shop_median": shop, "available": available,
            "pairs": pairs, "offer": c["offers"].get(uid),
            "sent_refs": set() if ignore_limits else c["sent"].get(uid, set()),
            "last_message_at": None if ignore_limits else c["last"].get(uid),
            "cart_touched_at": None if ignore_limits else c["cart"].get(uid),
            "cart_reminded_at": None if ignore_limits else c["reminded"].get(uid),
            "opted_out": (not ignore_limits) and uid in c["optout"],
        }
        plan = plan_for_user(uid, orders_by_user[uid], now, ctx)
        if plan:
            user = c["users"].get(uid) or {}
            plan["lang"] = user.get("language") or "uz"
            plan["first_name"] = ((user.get("full_name") or "").split() or [""])[0]
            plan["offer"] = c["offers"].get(uid)
            plans.append((uid, plan))
    plans.sort(key=lambda p: PRIORITY.index(p[1]["kind"]))
    return plans


# ─────────────────────────────── messages ───────────────────────────────────

def _pname(row: dict, lang: str) -> str:
    """Product name in the buyer's language. For uz_cyr the Latin name is
    returned: the whole message is transliterated by _t afterwards."""
    from locales import localize_product_text
    base = "uz" if lang == "uz_cyr" else lang
    return _esc(localize_product_text(row.get("name"), row.get("name_ru"), base))


def _qty(q: float) -> str:
    return str(int(q)) if float(q).is_integer() else f"{q:.1f}"


def _hello(plan: dict, lang: str) -> str:
    name = _esc(plan.get("first_name"))
    return (_t(f"{name}, ", f"{name}, ", lang) if name else "")


def _offer_block(prod: dict, offer: dict, lang: str, second: bool) -> str:
    until = offer_until_text(offer, lang)
    gift = _pname(prod, lang)
    if second:
        return _t(f"🎁 <b>Ikkinchi buyurtmangizga sovg'a:</b> {gift} — summadan qat'i nazar, "
                  f"buyurtmaga o'zi qo'shiladi.\n⏳ {until} gacha amal qiladi.",
                  f"🎁 <b>Подарок ко второму заказу:</b> {gift} — на любую сумму, "
                  f"добавится к заказу сам.\n⏳ Действует до {until}.", lang)
    return _t(f"🎁 <b>Sizga sovg'a:</b> keyingi buyurtmangizga {gift} — summadan qat'i nazar, "
              f"buyurtmaga o'zi qo'shiladi.\n⏳ {until} gacha amal qiladi.",
              f"🎁 <b>Подарок для вас:</b> к следующему заказу {gift} — на любую сумму, "
              f"добавится к заказу сам.\n⏳ Действует до {until}.", lang)


def build_text(plan: dict, lang: str, *, gift: dict | None, offer: dict | None,
               also: tuple[dict, list[dict]] | None, quick_ready: bool,
               new_products: list[dict] | None = None) -> str:
    kind = plan["kind"]
    hi = _hello(plan, lang)
    parts: list[str] = []

    if kind == "replenish":
        items = plan["items"]
        names = [_pname(d, lang) for d in items]
        joined = _t(" va ", " и ", lang).join(names)
        days = items[0]["days"]
        parts.append(_t(f"🔁 <b>{hi}{joined} tugab qolmadimi?</b>",
                        f"🔁 <b>{hi}{joined} — ещё не закончилось?</b>", lang))
        why = _t(f"{joined}ni <b>{days} kun oldin</b> olgan edingiz.",
                 f"Вы брали {joined} <b>{days} дн. назад</b>.", lang)
        if items[0]["source"] == "user":
            why += _t(f" Odatda Siz uni har ~{items[0]['interval']} kunda olasiz.",
                      f" Обычно вы берёте его примерно раз в {items[0]['interval']} дн.", lang)
        else:
            why += _t(" Odatda shu vaqtda yangisi kerak bo'ladi.",
                      " Обычно как раз к этому времени нужен новый.", lang)
        parts.append(why)
        lines = "\n".join(f"• {_pname(d, lang)} × {_qty(d['qty'])}" for d in items)
        parts.append(_t(lines, lines, lang))
        parts.append(_t("Bir tugma bilan xuddi shu miqdorda savatga solamiz"
                        + (" — manzil va to'lov oldingidek qoladi ⚡" if quick_ready else " 👇"),
                        "Одной кнопкой положим то же количество в корзину"
                        + (" — адрес и оплата останутся прежними ⚡" if quick_ready else " 👇"), lang))

    elif kind == "second_checkin":
        parts.append(_t(f"🤍 <b>{hi}Ketoshopni tanlaganingiz uchun rahmat!</b>",
                        f"🤍 <b>{hi}спасибо, что выбрали Ketoshop!</b>", lang))
        parts.append(_t(f"Birinchi buyurtmangiz yetib borganiga {plan['days']} kun bo'ldi. "
                        "Mahsulotlar yoqdi degan umiddamiz.",
                        f"Ваш первый заказ доставлен {plan['days']} дн. назад. "
                        "Надеемся, продукты вам понравились.", lang))
        if gift and offer:
            parts.append(_offer_block(gift, offer, lang, second=True))
        parts.append(_t("Yoqqan bo'lsa — o'sha buyurtmani bir tugmada takrorlashingiz mumkin 👇",
                        "Если понравилось — тот же заказ можно повторить одной кнопкой 👇", lang))

    elif kind == "second_lastcall":
        left = plan["days_left"]
        gift_name = _pname(gift, lang) if gift else ""
        parts.append(_t(f"⏳ <b>{hi}sovg'angiz {left} kundan keyin tugaydi</b>",
                        f"⏳ <b>{hi}ваш подарок сгорит через {left} дн.</b>", lang))
        parts.append(_t(f"Ikkinchi buyurtmangizga <b>{gift_name}</b> bepul qo'shiladi — summadan "
                        f"qat'i nazar, {offer_until_text(offer, lang)} gacha.",
                        f"Ко второму заказу бесплатно добавится <b>{gift_name}</b> — на любую сумму, "
                        f"до {offer_until_text(offer, lang)}.", lang))
        parts.append(_t("Oldingi buyurtmangizni bir tugmada takrorlash mumkin 👇",
                        "Прошлый заказ можно повторить одной кнопкой 👇", lang))

    else:  # win-back
        days = plan["days"]
        if kind == "winback_90":
            parts.append(_t(f"🤍 <b>{hi}Sizni kutib qolamiz</b>", f"🤍 <b>{hi}мы вас ждём</b>", lang))
        else:
            parts.append(_t(f"👋 <b>{hi}Sizni sog'indik!</b>", f"👋 <b>{hi}мы соскучились!</b>", lang))
        parts.append(_t(f"Oxirgi buyurtmangizga {days} kun bo'ldi.",
                        f"С вашего последнего заказа прошло {days} дн.", lang))
        if new_products:
            names = ", ".join(_pname(p, lang) for p in new_products[:3])
            parts.append(_t(f"🆕 Shu orada do'konimizga yangi mahsulotlar keldi: {names}.",
                            f"🆕 За это время в магазине появились новинки: {names}.", lang))
        if gift and offer and kind in ("winback_60", "winback_90"):
            parts.append(_offer_block(gift, offer, lang, second=False))
        if kind == "winback_90":
            parts.append(_t("Bu mavzuda boshqa bezovta qilmaymiz — kerak bo'lsa, bot doim shu yerda.",
                            "Больше не будем беспокоить на эту тему — бот всегда здесь, если понадобится.",
                            lang))
        parts.append(_t("Oldingi buyurtmangizni bir tugmada takrorlash mumkin 👇",
                        "Прошлый заказ можно повторить одной кнопкой 👇", lang))

    if also:
        parts.append(also_bought_text(also[0], also[1], lang))
    return "\n\n".join(parts)


def build_keyboard(plan: dict, lang: str, message_id: int, also_products: list[dict] | None) -> InlineKeyboardMarkup:
    if plan["kind"] == "replenish":
        main = _t("🔁 Xuddi shuni qayta buyurtma qilish", "🔁 Заказать то же самое", lang)
    else:
        main = _t("🔁 O'sha buyurtmani takrorlash", "🔁 Повторить тот заказ", lang)
    rows = [[InlineKeyboardButton(text=main, callback_data=f"rt_rep:{message_id}")]]
    if also_products:
        rows += also_bought_rows(also_products, lang)
    if plan["kind"] != "replenish" and not also_products:
        rows.append([InlineKeyboardButton(text=_t("🛍 Katalog", "🛍 Каталог", lang), callback_data="catalog")])
    rows.append([InlineKeyboardButton(text=_t("🔕 Bunday eslatma kerak emas", "🔕 Не присылать такие напоминания", lang),
                                      callback_data="rt_off")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def repeat_lines(plan: dict, orders: list[dict]) -> list[dict]:
    """What the main button puts into the cart: the due products for a
    replenish, the whole referenced order otherwise."""
    if plan["kind"] == "replenish":
        return [{"type": d["key"][0], "id": d["key"][1], "qty": d["qty"]} for d in plan["items"]]
    order = next((o for o in orders if o["id"] == plan["order_id"]), None)
    return order_lines(order["items"]) if order else []


def order_lines(items: list[dict]) -> list[dict]:
    out = []
    for it in items:
        key = line_key(it)
        if key:
            out.append({"type": key[0], "id": key[1], "qty": float(it.get("quantity") or 1)})
    return out


async def _new_products(days: int = 45) -> list[dict]:
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, name, name_ru FROM products
                WHERE is_active = 1 AND quantity > 0
                  AND created_at >= CURRENT_TIMESTAMP - make_interval(days => $1)
                ORDER BY created_at DESC LIMIT 3""", days)
        return [dict(r) for r in rows]


# ─────────────────────────────── sending ────────────────────────────────────

async def recently_messaged_ids(hours: int = 20) -> set[int]:
    """Buyers who got a personal message recently — the 10:00 reco and the
    18:00 interest nudge skip them, so that day stays at one push."""
    try:
        async with database.pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT DISTINCT user_id FROM retention_messages
                    WHERE delivered AND sent_at >= CURRENT_TIMESTAMP - make_interval(hours => $1)""",
                hours)
            return {r["user_id"] for r in rows}
    except Exception:
        logger.warning("Could not read recent retention messages", exc_info=True)
        return set()


async def _opted_out(user_id: int) -> bool:
    async with database.pool.acquire() as conn:
        return bool(await conn.fetchval("SELECT 1 FROM retention_optout WHERE user_id = $1", user_id))


async def _claim_message(uid: int, plan: dict, payload: dict, offer_id: int | None) -> int | None:
    async with database.pool.acquire() as conn:
        async with conn.transaction():
            mid = await conn.fetchval(
                """INSERT INTO retention_messages (user_id, kind, ref, payload, offer_id)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (user_id, ref) DO NOTHING RETURNING id""",
                uid, plan["kind"], plan["ref"], json.dumps(payload), offer_id)
            if mid is None:
                return None
            # The second product of a two-product reminder is covered too.
            for ref in plan.get("extra_refs") or []:
                await conn.execute(
                    """INSERT INTO retention_messages (user_id, kind, ref, delivered)
                       VALUES ($1, 'replenish_extra', $2, FALSE) ON CONFLICT DO NOTHING""",
                    uid, ref)
            return mid


async def _send(bot: Bot, uid: int, text: str, markup) -> bool:
    for attempt in range(2):
        try:
            await bot.send_message(uid, text, parse_mode=ParseMode.HTML,
                                   reply_markup=markup, disable_web_page_preview=True)
            return True
        except TelegramRetryAfter as exc:
            if attempt:
                return False
            await asyncio.sleep(exc.retry_after + 1)
        except (TelegramForbiddenError, TelegramBadRequest):
            return False
        except Exception:
            logger.exception("Retention message to %s failed", uid)
            return False
    return False


async def render(uid: int, plan: dict, *, grant: bool) -> tuple[str, dict, dict | None]:
    """(text, payload, offer). `grant` opens the gift offer for real; a
    preview only shows what it would say."""
    lang = plan["lang"]
    available = await _load_available()
    offer = plan.get("offer")
    gift = await gift_available() if plan["kind"] in OFFER_KINDS | {"second_lastcall"} else None
    if plan["kind"] in OFFER_KINDS and gift and not offer:
        if grant:
            offer = await grant_offer(uid, plan["kind"], OFFER_DAYS)
        else:
            offer = {"id": 0, "kind": plan["kind"], "expires_at": _now_utc() + timedelta(days=OFFER_DAYS)}
    if plan["kind"] == "second_lastcall" and not (gift and offer):
        return "", {}, None
    also = _resolve_also(plan, available)
    from handlers.cart import _quick_order_ready
    quick = await _quick_order_ready(uid)
    news = await _new_products() if plan["kind"].startswith("winback") else None
    orders = (await _load_orders(uid)).get(uid, [])
    text = build_text(plan, lang, gift=gift, offer=offer, also=also, quick_ready=quick, new_products=news)
    payload = {"lines": repeat_lines(plan, orders), "order_id": plan.get("order_id"),
               "also": [p["id"] for p in also[1]] if also else []}
    return text, payload, offer


def _resolve_also(plan: dict, available: dict) -> tuple[dict, list[dict]] | None:
    """plan["also"] keys → catalogue rows, dropping anything sold out since."""
    if not plan.get("also"):
        return None
    anchor, keys = plan["also"]
    products = [available[k] for k in keys if k in available]
    if not products or anchor not in available:
        return None
    return available[anchor], products


async def run_once(bot: Bot) -> dict:
    stats = {"sent": 0, "failed": 0, "skipped": 0, "by_kind": {}}
    plans = await build_plans()
    for uid, plan in plans[:MAX_PER_RUN]:
        try:
            had_offer = plan.get("offer")
            text, payload, offer = await render(uid, plan, grant=True)
            if not text:
                stats["skipped"] += 1
                continue
            new_offer_id = offer["id"] if offer and not had_offer and plan["kind"] in OFFER_KINDS else None
            mid = await _claim_message(uid, plan, payload, offer["id"] if offer else None)
            if mid is None:
                if new_offer_id:
                    await _drop_offer(new_offer_id)
                stats["skipped"] += 1
                continue
            also = _resolve_also(plan, await _load_available())
            ok = await _send(bot, uid, text, build_keyboard(plan, plan["lang"], mid, also[1] if also else None))
            if ok:
                async with database.pool.acquire() as conn:
                    await conn.execute("UPDATE retention_messages SET delivered = TRUE WHERE id = $1", mid)
                stats["sent"] += 1
                stats["by_kind"][plan["kind"]] = stats["by_kind"].get(plan["kind"], 0) + 1
            else:
                if new_offer_id:
                    await _drop_offer(new_offer_id)
                stats["failed"] += 1
        except Exception:
            logger.exception("Retention send failed for %s", uid)
            stats["failed"] += 1
        await asyncio.sleep(SEND_DELAY)
    return stats


async def attribute_conversions() -> None:
    async with database.pool.acquire() as conn:
        await conn.execute(
            f"""WITH firsts AS (
                   SELECT m.id AS mid, m.sent_at,
                          (SELECT o.id FROM orders o
                            WHERE o.user_id = m.user_id AND {database._REAL_ORDER}
                              AND o.created_at >= m.sent_at
                              AND o.created_at <= m.sent_at + make_interval(days => $1)
                              AND o.status <> 'cancelled'
                            ORDER BY o.created_at LIMIT 1) AS oid
                     FROM retention_messages m
                    WHERE m.delivered AND m.converted_order_id IS NULL
                      AND m.sent_at >= CURRENT_TIMESTAMP - make_interval(days => $1 + 1)
               ), latest AS (
                   SELECT DISTINCT ON (f.oid) f.mid, f.oid FROM firsts f
                    WHERE f.oid IS NOT NULL
                      AND NOT EXISTS (SELECT 1 FROM retention_messages x WHERE x.converted_order_id = f.oid)
                    ORDER BY f.oid, f.sent_at DESC
               )
               UPDATE retention_messages m
                  SET converted_order_id = l.oid,
                      converted_total = (SELECT total FROM orders WHERE id = l.oid)
                 FROM latest l WHERE m.id = l.mid""",
            ATTRIBUTION_DAYS)


async def _notify_admins(bot: Bot, text: str) -> None:
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception:
            pass


async def _tick(bot: Bot) -> None:
    try:
        await attribute_conversions()
        await mark_used_offers()
    except Exception:
        logger.exception("Retention bookkeeping failed")
    state = await get_state()
    if not state.get("enabled"):
        return
    now = _now_tk()
    if (now.hour, now.minute) < RUN_AT or now.hour >= RUN_UNTIL_HOUR:
        return
    if state.get("last_run_date") == now.date():
        return
    if not await _claim_run(now.date()):          # claimed before sending
        return
    stats = await run_once(bot)
    logger.info("Retention run: %s", stats)
    if stats["sent"] or stats["failed"]:
        kinds = "\n".join(f"• {KIND_LABELS.get(k, k)}: {n} ta" for k, n in stats["by_kind"].items())
        await _notify_admins(bot, (
            "🔁 <b>Qayta sotuv xabarlari yuborildi</b>\n"
            f"✅ {stats['sent']} ta · ⚠️ {stats['failed']} ta yetmadi\n"
            + (kinds + "\n" if kinds else "") + "Natija: /qaytarish"))


async def scheduler_loop(bot: Bot) -> None:
    logger.info("Retention scheduler started (%02d:%02d Tashkent)", *RUN_AT)
    while True:
        try:
            await _tick(bot)
        except Exception:
            logger.exception("Retention tick failed")
        await asyncio.sleep(CHECK_EVERY)


# ─────────────────────────────── buyer buttons ──────────────────────────────

async def add_lines_to_cart(user_id: int, lines: list[dict]) -> int:
    """Put lines into the cart at today's prices. Products are capped by stock
    and skipped when inactive or sold out. Returns how many lines made it."""
    added = 0
    async with database.pool.acquire() as conn:
        for line in lines:
            qty = float(line.get("qty") or 1)
            if line["type"] == "s":
                ok = await conn.fetchval("SELECT 1 FROM product_sets WHERE id = $1 AND is_active = 1", line["id"])
                if not ok:
                    continue
                _, have = await database.get_cart_line_for_set(user_id, line["id"])
                if have <= 0:
                    await database.add_to_cart(user_id, set_id=line["id"], quantity=qty)
                added += 1
            else:
                stock = await conn.fetchval(
                    "SELECT quantity FROM products WHERE id = $1 AND is_active = 1", line["id"])
                if not stock or float(stock) <= 0:
                    continue
                qty = min(qty, float(stock))
                _, have = await database.get_cart_line_for_product(user_id, line["id"])
                # Already in the cart → leave that amount alone; tapping twice
                # must not double the order.
                if have <= 0:
                    await database.add_to_cart(user_id, line["id"], qty)
                added += 1
    return added


async def _message_row(mid: int, user_id: int) -> dict | None:
    async with database.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM retention_messages WHERE id = $1 AND user_id = $2", mid, user_id)
        if row:
            await conn.execute(
                "UPDATE retention_messages SET clicked_at = COALESCE(clicked_at, CURRENT_TIMESTAMP) WHERE id = $1",
                mid)
        return dict(row) if row else None


async def _show_cart(callback: CallbackQuery, lang: str) -> None:
    from handlers.cart import build_cart_view
    text, keyboard = await build_cart_view(callback.from_user.id, lang)
    if text:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


def _added_toast(n: int, lang: str) -> str:
    return _t(f"✅ {n} ta mahsulot savatda", f"✅ Товаров в корзине: {n}", lang)


def _none_toast(lang: str) -> str:
    return _t("😔 Bu mahsulotlar hozir mavjud emas", "😔 Этих товаров сейчас нет в наличии", lang)


@router.callback_query(F.data.startswith("rt_rep:"))
async def on_repeat(callback: CallbackQuery):
    lang = await database.get_user_language(callback.from_user.id)
    row = await _message_row(int(callback.data.split(":")[1]), callback.from_user.id)
    if not row:
        await callback.answer("❌")
        return
    lines = (json.loads(row["payload"] or "{}")).get("lines") or []
    n = await add_lines_to_cart(callback.from_user.id, lines)
    if not n:
        await callback.answer(_none_toast(lang), show_alert=True)
        return
    await callback.answer(_added_toast(n, lang))
    await _show_cart(callback, lang)


@router.callback_query(F.data.startswith("rt_ord:"))
async def on_repeat_order(callback: CallbackQuery):
    """🔁 under "Mening buyurtmalarim" — the whole past order back in the cart."""
    lang = await database.get_user_language(callback.from_user.id)
    order = await database.get_order(int(callback.data.split(":")[1]))
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer("❌")
        return
    n = await add_lines_to_cart(callback.from_user.id, order_lines(_parse_items(order["items"])))
    if not n:
        await callback.answer(_none_toast(lang), show_alert=True)
        return
    await callback.answer(_added_toast(n, lang))
    await _show_cart(callback, lang)


async def repeat_order_rows(user_id: int, lang: str, limit: int = 3) -> list[list[InlineKeyboardButton]]:
    """Buttons for the order history screen: the last few delivered orders."""
    try:
        async with database.pool.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT o.id FROM orders o WHERE o.user_id = $1 AND o.status = 'delivered'
                      AND {database._REAL_ORDER} ORDER BY o.created_at DESC LIMIT $2""",
                user_id, limit)
    except Exception:
        logger.warning("Could not load repeatable orders for %s", user_id, exc_info=True)
        return []
    return [[InlineKeyboardButton(text=_t(f"🔁 #{r['id']} ni takrorlash", f"🔁 Повторить #{r['id']}", lang),
                                  callback_data=f"rt_ord:{r['id']}")] for r in rows]


@router.callback_query(F.data == "rt_off")
async def on_opt_out(callback: CallbackQuery):
    lang = await database.get_user_language(callback.from_user.id)
    async with database.pool.acquire() as conn:
        await conn.execute("INSERT INTO retention_optout (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
                           callback.from_user.id)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer()
    await callback.message.answer(_t(
        "🔕 Tushunarli, bunday eslatmalarni endi yubormaymiz.\nQayta yoqish uchun: /eslatmalar",
        "🔕 Понятно, больше не будем присылать такие напоминания.\nВключить снова: /eslatmalar", lang))


@router.message(Command("eslatmalar"))
async def cmd_toggle_reminders(message: Message):
    lang = await database.get_user_language(message.from_user.id)
    async with database.pool.acquire() as conn:
        removed = await conn.fetchval(
            "DELETE FROM retention_optout WHERE user_id = $1 RETURNING user_id", message.from_user.id)
        if not removed:
            await conn.execute("INSERT INTO retention_optout (user_id) VALUES ($1) ON CONFLICT DO NOTHING",
                               message.from_user.id)
    if removed:
        await message.answer(_t("🔔 Eslatmalar yoqildi: mahsulot tugay deganda va sovg'alar haqida xabar beramiz.",
                                "🔔 Напоминания включены: сообщим, когда товар пора обновить, и о подарках.", lang))
    else:
        await message.answer(_t("🔕 Eslatmalar o'chirildi. Qayta yoqish uchun yana /eslatmalar yuboring.",
                                "🔕 Напоминания выключены. Чтобы включить, снова отправьте /eslatmalar.", lang))


# ─────────────────────────────── admin ──────────────────────────────────────

async def get_stats(days: int) -> dict:
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT kind, COUNT(*) AS sent, COUNT(clicked_at) AS clicked,
                      COUNT(converted_order_id) AS converted,
                      COALESCE(SUM(converted_total), 0) AS revenue
                 FROM retention_messages
                WHERE delivered AND sent_at >= CURRENT_TIMESTAMP - make_interval(days => $1)
                GROUP BY kind""", days)
        offers = await conn.fetchrow(
            """SELECT COUNT(*) AS granted, COUNT(used_order_id) AS used
                 FROM retention_offers WHERE created_at >= CURRENT_TIMESTAMP - make_interval(days => $1)""",
            days)
        optout = await conn.fetchval("SELECT COUNT(*) FROM retention_optout")
    return {"kinds": {r["kind"]: dict(r) for r in rows}, "offers": dict(offers), "optout": int(optout or 0)}


def _stats_block(title: str, s: dict) -> str:
    lines = [f"<b>{title}</b>"]
    total = {"sent": 0, "clicked": 0, "converted": 0, "revenue": 0.0}
    for kind in PRIORITY:
        k = s["kinds"].get(kind)
        if not k:
            continue
        for f in total:
            total[f] += k[f]
        rate = k["converted"] / k["sent"] * 100 if k["sent"] else 0
        lines.append(f"{KIND_LABELS[kind]}: {k['sent']} ta → 👆 {k['clicked']} · ✅ {k['converted']} "
                     f"({rate:.0f}%) · 💰 {fmt_sum(k['revenue'])}")
    if not total["sent"]:
        lines.append("Hali xabar yuborilmagan.")
    else:
        rate = total["converted"] / total["sent"] * 100
        lines.append(f"<b>Jami: {total['sent']} ta → ✅ {total['converted']} ({rate:.0f}%) · "
                     f"💰 {fmt_sum(total['revenue'])} so'm</b>")
    lines.append(f"🎁 Sovg'a taklifi: {s['offers']['granted']} ta ochildi, {s['offers']['used']} tasi ishlatildi")
    return "\n".join(lines)


@router.message(Command("qaytarish"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_stats(message: Message):
    await attribute_conversions()
    await mark_used_offers()
    state = await get_state()
    week, month = await get_stats(7), await get_stats(30)
    status = "✅ yoqilgan" if state.get("enabled") else "⚪ o'chirilgan"
    await message.answer(
        "🔁 <b>Qayta sotuv xabarlari</b> — " + status + "\n"
        f"Har kuni {RUN_AT[0]:02d}:{RUN_AT[1]:02d} da. Bitta mijozga 7 kunda ko'pi bilan 1 ta.\n"
        "Konversiya = xabardan keyin 7 kun ichidagi buyurtma.\n\n"
        + _stats_block("Oxirgi 7 kun", week) + "\n\n" + _stats_block("Oxirgi 30 kun", month)
        + f"\n\n🔕 Eslatmani o'chirgan mijozlar: {month['optout']} ta\n\n"
        "/qaytarish_test — bugun kimga nima ketishini ko'rish\n"
        "/qaytarish_test ID — bitta mijozning xabarini ko'rish\n"
        "/qaytarish_off · /qaytarish_on",
        parse_mode=ParseMode.HTML)


@router.message(Command("qaytarish_on"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_on(message: Message):
    await set_enabled(True)
    await message.answer("✅ Qayta sotuv xabarlari yoqildi.")


@router.message(Command("qaytarish_off"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_off(message: Message):
    await set_enabled(False)
    await message.answer("⚪ Qayta sotuv xabarlari o'chirildi. Sovg'a takliflari muddati tugaguncha ishlaydi.")


@router.message(Command("qaytarish_test"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_test(message: Message, command: CommandObject):
    arg = (command.args or "").strip()
    if arg.lstrip("-").isdigit():
        uid = int(arg)
        plans = await build_plans(only_user=uid, ignore_limits=True)
        if not plans:
            await message.answer("Bu mijozga hozir mos xabar yo'q (buyurtmasi yo'q yoki hech bir shart mos kelmadi).")
            return
        _, plan = plans[0]
        text, _, _ = await render(uid, plan, grant=False)
        if not text:
            await message.answer("Bu mijozda faol sovg'a taklifi yo'q — xabar chiqmaydi.")
            return
        await message.answer(f"👁 <b>Ko'rinish</b> — {KIND_LABELS[plan['kind']]} (yuborilmadi)",
                             parse_mode=ParseMode.HTML)
        await message.answer(text, parse_mode=ParseMode.HTML,
                             reply_markup=build_keyboard(plan, plan["lang"], 0, None))
        return

    plans = await build_plans()
    if not plans:
        await message.answer("Bugun hech kimga qayta sotuv xabari tushmaydi.")
        return
    by_kind: dict[str, list[int]] = {}
    for uid, plan in plans:
        by_kind.setdefault(plan["kind"], []).append(uid)
    lines = [f"🔁 <b>Hozir ishga tushsa: {len(plans)} ta xabar</b>"]
    for kind in PRIORITY:
        if kind in by_kind:
            ids = ", ".join(f"<code>{u}</code>" for u in by_kind[kind][:5])
            lines.append(f"{KIND_LABELS[kind]}: {len(by_kind[kind])} ta (masalan {ids})")
    lines.append("\nBittasini ko'rish: /qaytarish_test ID")
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)
