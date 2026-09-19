"""Courier Kanban board — the server half of the /admin "Kuryer" tab.

The board shows every live order as a card in one of five columns and lets an
admin move a card forward (or back) by dragging it or tapping a button:

    🆕 Yangi        pending
    ✅ Qabul qilindi confirmed
    🚚 Tayyor + Yo'lda ready, shipped  ← 'ready' is new (2026-09-18)
    📦 Yetkazildi    delivered (24h in the "Faol" scope, recent history in "Hammasi")
    ❌ Bekor qilindi cancelled (only in the "Hammasi" scope)

There was a 'Tayyorlanmoqda' (preparing) column between Qabul qilindi and
Tayyor; the shop doesn't work in that step, so it was dropped on 2026-09-18.
The status itself is kept — orders stamped with it before the column went
away still land in the Tayyor + Yo'lda column, and the bot's own buttons
still accept it — so nothing in flight was stranded.

`preparing` and `ready` are new statuses that split the old confirmed →
shipped jump. Everything that used to read the pipeline still works: the bot's
own order buttons now accept an order arriving from any of the in-between
states (see handlers/seller.py), and every stats query keys off 'delivered'.

Moving a card is a guarded transition — the board sends the status it *saw* the
card in, so two admins dragging the same order at the same time can't both
win. The loser gets a "allaqachon o'zgargan" toast and a fresh board.

Every forward move also notifies the buyer in their own language, reusing the
same message builder as the bot's seller panel so the buyer sees one
consistent timeline no matter which surface moved the order.
"""
import asyncio
import json
import logging
import re
from datetime import datetime, timedelta

import database
from locales import get_text

logger = logging.getLogger(__name__)

TZ_OFFSET = timedelta(hours=5)   # Asia/Tashkent, fixed UTC+5, no DST

# How long a delivered card lingers in the last column before it drops off.
DELIVERED_WINDOW_HOURS = 24

# The board, left to right. `statuses` is what lands in the column; `target`
# is the status a card takes when dropped into it. The Tayyor/Yo'lda column
# holds two statuses — a card dropped there becomes 'ready', and the courier
# flips it to 'shipped' from the card itself.
COLUMNS = [
    {"key": "new",       "target": "pending",   "statuses": ["pending"],
     "title": "Yangi buyurtmalar", "icon": "🆕", "tone": "amber"},
    {"key": "accepted",  "target": "confirmed", "statuses": ["confirmed"],
     "title": "Qabul qilindi",     "icon": "✅", "tone": "blue"},
    {"key": "delivery",  "target": "ready",     "statuses": ["ready", "preparing", "shipped"],
     "title": "Tayyor + Yo'lda",   "icon": "🚚", "tone": "accent"},
    {"key": "done",      "target": "delivered", "statuses": ["delivered"],
     "title": "Yetkazildi",        "icon": "📦", "tone": "green"},
    # Only rendered in the "Hammasi" scope — a cancelled order is not work
    # anybody is doing, so it would just be noise on the working board.
    {"key": "cancelled", "target": "cancelled", "statuses": ["cancelled"],
     "title": "Bekor qilindi",     "icon": "❌", "tone": "red", "scope": "all"},
]

_COLUMN_OF_STATUS = {s: c["key"] for c in COLUMNS for s in c["statuses"]}
# A card the board cancels lands in a column that only the "Hammasi" scope
# renders; on the working board it simply drops off, which is what we want.


# Pipeline order, used to tell a forward move from a rollback.
# 'preparing' keeps its slot so an order still carrying that status sorts and
# steps forward correctly, even though no column targets it any more.
PIPELINE = ["pending", "confirmed", "preparing", "ready", "shipped", "delivered"]
_RANK = {s: i for i, s in enumerate(PIPELINE)}

# Which statuses a card may legally arrive from, per target. Deliberately
# generous: a card can be dragged backwards to fix a misclick, and 'shipped'
# accepts everything from confirmed onward so an order can skip straight to
# the courier on a quiet day. 'cancelled' is reachable from anywhere live.
ALLOWED_FROM = {
    "pending":   ["confirmed", "preparing", "ready", "shipped"],
    "confirmed": ["pending", "preparing", "ready", "shipped"],
    "preparing": ["pending", "confirmed", "ready", "shipped"],
    "ready":     ["pending", "confirmed", "preparing", "shipped"],
    # 'delivered' is here so a mis-clicked "Yetkazildi" can be rolled back —
    # a backward move never messages the buyer, so the undo is silent.
    "shipped":   ["confirmed", "preparing", "ready", "delivered"],
    "delivered": ["ready", "shipped"],
    "cancelled": ["pending", "confirmed", "preparing", "ready", "shipped"],
}

# Buyer notification copy per target status. Statuses absent here move
# silently (a rollback never messages the buyer — nobody wants "your order is
# being prepared" twice because an admin fixed a column).
BUYER_MESSAGE = {
    "confirmed": "buyer_order_confirmed",
    "preparing": "buyer_order_preparing",
    "ready":     "buyer_order_ready",
    "shipped":   "buyer_order_shipped",
    "delivered": "buyer_order_delivered",
    "cancelled": "buyer_order_cancelled",
}

# Short Uzbek label per status, for the toast the board shows after a move.
STATUS_LABEL_UZ = {
    "pending":   "Yangi",
    "confirmed": "Qabul qilindi",
    "preparing": "Tayyorlanmoqda",
    "ready":     "Tayyor",
    "shipped":   "Yo'lda",
    "delivered": "Yetkazildi",
    "cancelled": "Bekor qilindi",
}


# ───────────────────────────── snapshot ──────────────────────────────────────

def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else None


def _minutes_since(value) -> int | None:
    """Minutes elapsed since a naive-UTC DB stamp, floored at 0 so a clock
    skew of a few seconds doesn't render as "-1 daqiqa"."""
    if not isinstance(value, datetime):
        return None
    delta = datetime.utcnow() - value
    return max(0, int(delta.total_seconds() // 60))


def _parse_items(raw) -> list[dict]:
    if isinstance(raw, list):
        items = raw
    else:
        try:
            items = json.loads(raw or "[]")
        except (TypeError, ValueError):
            return []
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        out.append({
            "name": it.get("name") or "—",
            "quantity": it.get("quantity") or 0,
            "unit": it.get("unit") or "",
            "price": float(it.get("price") or 0),
            "is_gift": bool(it.get("is_gift") or it.get("is_bonus")),
        })
    return out


def _coord(value):
    """A latitude/longitude as a float, or None. Orders placed before the
    columns existed (and the odd hand-typed one) have them empty."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f else None


# "41.407165, 69.199902" — what the checkout writes into `address` when the
# buyer sends a Telegram pin instead of typing a street. Older orders have
# only that string, so the board digs the pin back out of it.
_COORD_RE = re.compile(r"^\s*(-?\d{1,2}\.\d+)\s*,\s*(-?\d{1,3}\.\d+)\s*$")


def order_pin(order: dict) -> tuple[float, float] | None:
    """The buyer's map pin for this order, from the columns or the address."""
    lat, lng = _coord(order.get("latitude")), _coord(order.get("longitude"))
    if lat is not None and lng is not None:
        return lat, lng
    m = _COORD_RE.match(str(order.get("address") or ""))
    if m:
        return float(m.group(1)), float(m.group(2))
    return None


def _stage_stamp(order: dict) -> datetime | None:
    """When the order entered the status it is in now — that's what the card's
    "shu bosqichda N daqiqa" counter measures, not the order's total age."""
    col = {
        "confirmed": "confirmed_at",
        "preparing": "preparing_at",
        "ready":     "ready_at",
        "shipped":   "shipped_at",
        "delivered": "delivered_at",
    }.get(order.get("status"))
    return order.get(col) if col else order.get("created_at")


def _card(order: dict) -> dict:
    items = _parse_items(order.get("items"))
    total = float(order.get("total") or 0)
    return {
        "id": order["id"],
        "status": order.get("status"),
        "column": _COLUMN_OF_STATUS.get(order.get("status")),
        "user_id": order.get("user_id"),
        "customer_name": order.get("customer_name") or order.get("buyer_full_name") or "—",
        "username": order.get("buyer_username"),
        "phone": order.get("phone"),
        "secondary_phone": order.get("secondary_phone"),
        "address": order.get("address"),
        "address_note": order.get("address_note"),
        "latitude": _coord(order.get("latitude")),
        "longitude": _coord(order.get("longitude")),
        "delivery_method": order.get("delivery_method"),
        "payment_method": order.get("payment_method"),
        "source": order.get("source") or "bot",
        "items": items,
        "items_count": sum(int(i["quantity"] or 0) for i in items),
        "total": total,
        "keto_redeemed": int(order.get("keto_redeemed") or 0),
        "courier_id": order.get("courier_id"),
        "courier_name": order.get("courier_name") or order.get("courier_username"),
        "created_at": _iso(order.get("created_at")),
        "confirmed_at": _iso(order.get("confirmed_at")),
        "preparing_at": _iso(order.get("preparing_at")),
        "ready_at": _iso(order.get("ready_at")),
        "shipped_at": _iso(order.get("shipped_at")),
        "delivered_at": _iso(order.get("delivered_at")),
        "age_minutes": _minutes_since(order.get("created_at")),
        "stage_minutes": _minutes_since(_stage_stamp(order)),
    }


async def board_snapshot(delivered_hours: int = DELIVERED_WINDOW_HOURS,
                         scope: str = "active") -> dict:
    """The whole board in one payload: every column with its cards, counts and
    summed value. One call so the tab renders without a request waterfall and
    so polling costs exactly one query.

    `scope` is "active" (live work plus today's deliveries) or "all" (the same
    live work plus recent delivered *and* cancelled orders, and the extra
    Bekor qilindi column to put them in).
    """
    orders = await database.get_courier_board_orders(delivered_hours, scope)
    shown = [c for c in COLUMNS if c.get("scope") in (None, scope)]
    buckets: dict[str, list[dict]] = {c["key"]: [] for c in shown}
    for order in orders:
        key = _COLUMN_OF_STATUS.get(order.get("status"))
        if key:
            buckets[key].append(_card(order))

    columns = []
    for c in shown:
        cards = buckets[c["key"]]
        # Oldest first everywhere except the finished columns, where the most
        # recently closed order is the interesting one.
        cards.sort(key=lambda x: x["created_at"] or "",
                   reverse=(c["key"] in ("done", "cancelled")))
        columns.append({
            "key": c["key"], "title": c["title"], "icon": c["icon"],
            "tone": c["tone"], "target": c["target"],
            "statuses": c["statuses"],
            "count": len(cards),
            "sum": sum(x["total"] for x in cards),
            "cards": cards,
        })

    live = [x for c in columns if c["key"] not in ("done", "cancelled")
            for x in c["cards"]]
    done = buckets.get("done", [])
    return {
        "columns": columns,
        "scope": scope,
        "server_time": datetime.utcnow().isoformat(),
        "totals": {
            "live": len(live),
            "live_sum": sum(x["total"] for x in live),
            "done_today": len(done),
            "done_sum": sum(x["total"] for x in done),
            "cancelled": len(buckets.get("cancelled", [])),
        },
    }


# ─────────────────────────────── moving ──────────────────────────────────────

async def _notify_buyer(bot, order: dict, new_status: str) -> None:
    """Send the buyer the status message for `new_status` in their language.

    Reuses handlers.seller's timeline builder so a move made from the board
    reads exactly like one made from the bot. Imported lazily — handlers pull
    in the whole aiogram router graph, which admin_web has no business
    importing at module load.
    """
    from handlers.seller import _build_buyer_status_block
    from keyboards import delivered_feedback_keyboard, order_cancelled_keyboard

    key = BUYER_MESSAGE.get(new_status)
    if not key:
        return
    lang = await database.get_user_language(order["user_id"])

    reply_markup = None
    if new_status == "delivered":
        reply_markup = delivered_feedback_keyboard(lang, order["id"])
    elif new_status == "cancelled":
        reply_markup = order_cancelled_keyboard(lang)

    when, timeline = _build_buyer_status_block(order, new_status, lang)
    text = get_text(key, lang, order_id=order["id"], when=when, timeline=timeline)

    # On delivery, close with one idea for what to make from what just
    # arrived. It rides inside this message on purpose — the buyer has the
    # product in their hands right now, and the shop's one-message-a-week
    # budget (retention.py) stays free for the messages that bring people back.
    if new_status == "delivered":
        import product_ideas
        idea = product_ideas.order_idea_block(_parse_items(order.get("items")), lang)
        if idea:
            text += "\n\n" + idea

    await bot.send_message(
        chat_id=order["user_id"],
        text=text,
        reply_markup=reply_markup,
        parse_mode="HTML",
    )


async def _after_delivered(bot, order: dict) -> None:
    """The same post-delivery side effects the bot's "Yetkazildi" button runs:
    the 2nd-order review nudge and the Keto reward. Both are best-effort — a
    failure here must never make the board look like the move didn't land."""
    from keyboards import InlineKeyboardMarkup, InlineKeyboardButton

    try:
        lang = await database.get_user_language(order["user_id"])
        delivered_count = await database.get_user_delivered_order_count(order["user_id"])
        if delivered_count == 2:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=get_text("btn_leave_review", lang),
                                     callback_data=f"review_order:{order['id']}"),
            ]])
            await bot.send_message(
                chat_id=order["user_id"],
                text=get_text("buyer_second_order_review_ask", lang),
                reply_markup=kb, parse_mode="HTML",
            )
    except Exception:
        logger.exception("courier board: second-order review nudge failed")

    try:
        from gamification import award_keto_for_order
        await award_keto_for_order(order, bot)
    except Exception:
        logger.exception("courier board: keto award failed")


async def move_order(order_id: int, target: str, *, expected_from: str | None = None,
                     notify: bool = True, bot=None) -> dict:
    """Move one card. Returns {"ok": True, "order": {...}} or
    {"ok": False, "error": ..., "stale": bool}.

    `expected_from` is the status the board *displayed*; when it no longer
    matches, nothing is written and the caller is told to refresh. That's the
    whole concurrency story — no locks, just a guarded UPDATE.
    """
    if target not in ALLOWED_FROM:
        return {"ok": False, "error": "noma'lum status"}

    order = await database.get_order(order_id)
    if not order:
        return {"ok": False, "error": "buyurtma topilmadi"}

    current = order.get("status")
    if current == target:
        return {"ok": True, "order": _card(order), "unchanged": True}
    if expected_from and expected_from != current:
        return {"ok": False, "stale": True,
                "error": f"Bu buyurtma allaqachon «{STATUS_LABEL_UZ.get(current, current)}» holatida"}
    if current not in ALLOWED_FROM[target]:
        return {"ok": False, "stale": True,
                "error": f"«{STATUS_LABEL_UZ.get(current, current)}» dan "
                         f"«{STATUS_LABEL_UZ.get(target, target)}» ga o'tkazib bo'lmaydi"}

    if target == "cancelled":
        # Atomic: flips status and restores stock in one transaction.
        await database.cancel_order(order_id)
    else:
        won = await database.transition_order_status(order_id, [current], target)
        if not won:
            return {"ok": False, "stale": True,
                    "error": "Buyurtma holati hozirgina o'zgardi — yangilang"}

    fresh = await database.get_order(order_id) or order

    # Only a forward move is worth a buyer's notification; dragging a card
    # back is an admin fixing the board, not news for the customer.
    forward = _RANK.get(target, -1) > _RANK.get(current, -1) or target == "cancelled"
    if notify and bot is not None and forward:
        async def _side_effects():
            try:
                await _notify_buyer(bot, fresh, target)
            except Exception:
                logger.exception("courier board: buyer notify failed (order %s)", order_id)
            if target == "delivered":
                await _after_delivered(bot, fresh)

        # Telegram sends are slow and can fail; the HTTP response shouldn't
        # wait on them — the status is already committed either way.
        asyncio.create_task(_side_effects())

    return {"ok": True, "order": _card(fresh),
            "notified": bool(notify and bot is not None and forward and BUYER_MESSAGE.get(target))}


async def send_pin_to_telegram(order_id: int, bot) -> dict:
    """Push the buyer's map pin to the admins' Telegram as a real location
    message.

    A browser can only offer a maps link; Telegram can open the pin straight
    into the courier's navigation app, which is what someone actually driving
    needs. Sent to every ADMIN_IDS chat because the web panel authenticates by
    a shared password and so has no idea which admin pressed the button.
    """
    from config import ADMIN_IDS

    order = await database.get_order(order_id)
    if not order:
        return {"ok": False, "error": "buyurtma topilmadi"}
    pin = order_pin(order)
    if not pin:
        return {"ok": False, "error": "bu buyurtmada lokatsiya yo'q"}

    lat, lng = pin
    caption = (f"📍 <b>Buyurtma #{order_id}</b> — mijoz lokatsiyasi\n"
               f"👤 {order.get('customer_name') or '—'}\n"
               f"📱 {order.get('phone') or '—'}")
    sent = 0
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, caption, parse_mode="HTML")
            await bot.send_location(admin_id, latitude=lat, longitude=lng)
            sent += 1
        except Exception:
            logger.exception("courier board: pin to admin %s failed", admin_id)
    if not sent:
        return {"ok": False, "error": "hech kimga yuborib bo'lmadi"}
    return {"ok": True, "sent": sent, "latitude": lat, "longitude": lng}


async def assign_courier(order_id: int, courier_id: int | None) -> bool:
    """Attach (or clear) the courier shown on a card. Kept separate from the
    status move so claiming an order doesn't message the buyer."""
    async with database.pool.acquire() as conn:
        await conn.execute("UPDATE orders SET courier_id = $1 WHERE id = $2",
                           courier_id, order_id)
    return True


async def courier_options() -> list[dict]:
    """Registered couriers (the /addcourier list) for the card's picker."""
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT c.user_id, u.full_name, u.username
               FROM couriers c LEFT JOIN users u ON u.user_id = c.user_id
               ORDER BY COALESCE(u.full_name, u.username, c.user_id::text)"""
        )
    return [{"user_id": r["user_id"],
             "name": r["full_name"] or r["username"] or str(r["user_id"])}
            for r in rows]
