"""Bitta manzilga bitta yetkazish (egasi, 2026-11-27: "bu opa avval ham buyurtma bergan edilar
lekin bitta joyga bo'lgani uchun dostavka bitta bo'ladi ... 2 ta dostavka narxi kerak emas";
"bitta hisoblansin agar hali yo'lda statusiga o'tmagan bo'lsa"; "dostavka yetib borgach yana
qilsa unda alohida hisoblanadi").

Qoida: mijozning Ketoshop kuryeri orqali, shu joyga (lokatsiya JOINT_METERS ichida yoki manzil
matni bir xil) boradigan va hali «🚚 Yo'lda» ga o'tmagan buyurtmasi bo'lsa (pending, confirmed,
preparing, ready), yangi buyurtma u bilan birga yetkaziladi: yetkazish narxi olinmaydi.
Oldingi buyurtma yo'lga chiqqan, yetkazilgan yoki bekor qilingan bo'lsa — yangi buyurtma alohida,
odatdagi narx bilan.

Birga yetkaziladigan buyurtma orders.delivery_joined_with da belgilanadi: kuryer xarajati
(delivery_costs.py, 25 000) ikkinchi marta yozilmaydi, admin kartochkasida "🔗 #N bilan birga".
"""
from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timedelta

import database

logger = logging.getLogger(__name__)

JOINT_METERS = 300
OPEN_STATUSES = ("pending", "confirmed", "preparing", "ready")
LOOKBACK_DAYS = 14
METHOD = "self"


def distance_m(lat1, lng1, lat2, lng2) -> float | None:
    try:
        lat1, lng1, lat2, lng2 = (float(v) for v in (lat1, lng1, lat2, lng2))
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (lat1, lng1, lat2, lng2)):
        return None
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _norm(address) -> str:
    return re.sub(r"[\W_]+", " ", str(address or "").lower()).strip()


def same_place(order: dict, lat, lng, address) -> bool:
    d = distance_m(order.get("latitude"), order.get("longitude"), lat, lng)
    if d is not None:
        return d <= JOINT_METERS
    a, b = _norm(order.get("address")), _norm(address)
    return bool(a) and len(a) >= 8 and a == b


async def open_order_at(user_id, lat, lng, address=None, exclude_id=None, conn=None) -> int | None:
    """Shu mijozning shu joyga boradigan, hali yo'lga chiqmagan kuryer buyurtmasi (eng yangisi)."""
    if not user_id:
        return None
    sql = ("SELECT id, latitude, longitude, address FROM orders "
           "WHERE user_id = $1 AND delivery_method = $2 AND status = ANY($3::text[]) "
           "AND created_at > $4 AND ($5::int IS NULL OR id <> $5) ORDER BY id DESC LIMIT 10")
    args = (int(user_id), METHOD, list(OPEN_STATUSES), datetime.utcnow() - timedelta(days=LOOKBACK_DAYS),
            exclude_id)
    try:
        if conn is not None:
            rows = await conn.fetch(sql, *args)
        else:
            async with database.pool.acquire() as c:
                rows = await c.fetch(sql, *args)
    except Exception:
        logger.warning("joint delivery lookup failed for %s", user_id, exc_info=True)
        return None
    for r in rows:
        if same_place(dict(r), lat, lng, address):
            return int(r["id"])
    return None


async def waive(method, user_id, lat, lng, address=None) -> int | None:
    """Checkout uchun: yetkazish narxi olinmaydigan bo'lsa — birga ketadigan buyurtma raqami."""
    if method != METHOD:
        return None
    return await open_order_at(user_id, lat, lng, address)


def fee_paid(total, keto_redeem, items) -> float:
    goods = sum(float(it.get("price") or 0) * float(it.get("quantity") or 0) for it in items or [])
    return float(total or 0) + float(keto_redeem or 0) - goods


async def mark_created(conn, order_id: int, user_id, delivery_method, lat, lng, address,
                       total, keto_redeem, items) -> int | None:
    """create_order ichida, yangi buyurtma yozilgach: kuryer buyurtmasi, yetkazish narxi
    olinmagan va shu joyga ochiq buyurtma bor bo'lsa — birga deb belgilaydi."""
    if delivery_method != METHOD or fee_paid(total, keto_redeem, items) > 0.5:
        return None
    joined = await open_order_at(user_id, lat, lng, address, exclude_id=order_id, conn=conn)
    if joined:
        await conn.execute("UPDATE orders SET delivery_joined_with = $1 WHERE id = $2", joined, order_id)
    return joined


NOTE = {
    "uz": "🔗 #{id} buyurtmangiz bilan birga yetkaziladi — yetkazish narxi olinmaydi",
    "ru": "🔗 Доставим вместе с заказом #{id} — доставка не оплачивается",
}
ADMIN_NOTE = "🔗 #{id} bilan birga yetkaziladi — yetkazish narxi olinmadi"


def note(order_id: int, lang: str) -> str:
    text = NOTE["ru" if lang == "ru" else "uz"].format(id=order_id)
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        text = lat_to_cyr(text)
    return text
