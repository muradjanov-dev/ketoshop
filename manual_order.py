"""Qo'lda buyurtma — admin saytidan (owner, 2026-11-09: "qo'lda kiritiladigan
buyurtmalarni ham dashboarddan ham kiritish imkonini qilib ber").

The bot's flow (handlers/admin.py, «📝 Qo'lda buyurtma») asks one question
per message; the site sends the whole order in one request. This module
checks that request against the same rules the bot enforces, so an order
typed on the site is indistinguishable from one typed in the bot:

  * phone — any unambiguous Uzbek spelling, stored as +998XXXXXXXXX;
  * a line's price defaults to the shelf price (active discount included);
    a lower price is a per-order discount (original_price + discount_percent
    on the line, as the bot writes it); a higher one is refused, exactly
    like the bot's «manual_discount_price_too_high»;
  * UzPost adds the buyer's parcel fee to the total (uzpost.buyer_fee, the
    region read from the typed address), like handlers.admin._manual_uzpost;
  * Ketoshop's courier adds the buyer's courier fee (handlers.cart.
    delivery_fee_for): 25 000 in the city (free from 800 000), plus 3 000 a
    km past the city line read from the location (owner, 2026-11-27:
    "qo'lda buyurtma kiritganda lokatsiyani ham kiritish imkoni bo'lsin va
    dostavkani shundan kelib chiqib hisoblasin");
  * stock is never touched — database.add_manual_order already says why.
"""
from __future__ import annotations

import re

import phone_utils

PAYMENTS = ("cash", "online")
DELIVERIES = ("self", "pickup", "yandex_taxi", "bts", "emu", "uzpost")
STATUSES = ("pending", "confirmed", "shipped", "delivered", "cancelled")

MAX_LINES = 60
MAX_QTY = 10_000
NAME_MAX = 200
ADDRESS_MAX = 500


class Invalid(ValueError):
    """A message the admin can act on, in Uzbek."""


def shelf_price(product: dict) -> float:
    """What the shop charges for one today — the price the bot offers first."""
    import database
    d = database.active_discount(product.get("discount_percent"), product.get("discount_until"))
    return float(database.effective_price(product.get("price") or 0, d, product.get("discount_until")))


def _number(value, what: str) -> float:
    if isinstance(value, bool):
        raise Invalid(f"{what} raqam bo'lishi kerak")
    try:
        number = float(str(value).replace(" ", "").replace(",", "."))
    except (TypeError, ValueError):
        raise Invalid(f"{what} raqam bo'lishi kerak") from None
    if number != number or number in (float("inf"), float("-inf")):
        raise Invalid(f"{what} raqam bo'lishi kerak")
    return number


def make_line(product: dict, quantity, price=None) -> dict:
    """One order line in the bot's shape: {product_id, name, quantity, price,
    unit} plus original_price/discount_percent when sold below the shelf."""
    name = product.get("name") or f"#{product.get('id')}"
    qty = _number(quantity, f"«{name}» soni")
    if qty <= 0 or qty > MAX_QTY:
        raise Invalid(f"«{name}» soni 0 dan katta bo'lishi kerak")
    base = shelf_price(product)
    if price is None or str(price).strip() == "":
        final = base
    else:
        final = _number(price, f"«{name}» narxi")
        if final <= 0:
            raise Invalid(f"«{name}» narxi 0 dan katta bo'lishi kerak")
        if base > 0 and final > base + 0.5:
            raise Invalid(f"«{name}» narxi do'kondagidan ({int(base):,} so'm) baland bo'lmasin — "
                          "chegirma narxni ko'tarmaydi".replace(",", " "))
        final = min(final, base) if base > 0 else final
    line = {
        "product_id": int(product["id"]),
        "name": name,
        "quantity": int(qty) if float(qty).is_integer() else qty,
        "price": final,
        "unit": product.get("unit") or "",
    }
    percent = round((base - final) / base * 100) if base > 0 else 0
    if final < base and percent > 0:
        line["original_price"] = base
        line["discount_percent"] = percent
    return line


def uzpost_fee(items: list[dict], address: str, delivery: str) -> tuple[int, float]:
    """(buyer's parcel fee, kg) for UzPost, else (0, 0) — handlers.admin._manual_uzpost."""
    if delivery != "uzpost" or not items:
        return 0, 0.0
    import regions
    import uzpost
    far = uzpost.is_far(regions.region_from_text(address))
    return uzpost.buyer_fee(items, far), uzpost.parcel_kg(items)


# Uzbekistan's box — tells a "lat, lng" pair from a "lng, lat" one.
_LAT = (37.0, 46.0)
_LNG = (55.0, 74.0)
# Decimals required: "Chilonzor 5, 12-uy" is a street, not a point.
_PAIR = r"(-?\d{1,3}\.\d+)\s*(?:,|%2C|\s)\s*(-?\d{1,3}\.\d+)"


def _in_uz(lat: float, lng: float) -> bool:
    return _LAT[0] <= lat <= _LAT[1] and _LNG[0] <= lng <= _LNG[1]


def parse_location(text) -> tuple[float, float] | None:
    """A location the admin pasted → (lat, lng), or None when the text holds
    none. Takes "41.31, 69.27", a Yandex Maps link (ll= / pt= / whatshere —
    those are lng,lat), a Google Maps link (@lat,lng / q=lat,lng) or a
    Telegram-style "📍 41.31, 69.27 — street". The order of the two numbers
    is read from Uzbekistan's box, so a swapped pair still lands right.
    Raises Invalid for a short link (it hides the point) or a point outside
    Uzbekistan."""
    s = str(text or "").strip()
    if not s:
        return None
    pairs: list[tuple[str, tuple[str, str]]] = []
    for key in ("whatshere%5Bpoint%5D=", "whatshere[point]=", "pt=", "ll="):
        m = re.search(re.escape(key) + _PAIR, s)
        if m:
            pairs.append(("lnglat", (m.group(1), m.group(2))))
    for m in re.finditer(r"[@=:/]" + _PAIR, s):
        pairs.append(("latlng", (m.group(1), m.group(2))))
    m = re.search(_PAIR, s)
    if m:
        pairs.append(("latlng", (m.group(1), m.group(2))))
    for order, (a, b) in pairs:
        try:
            x, y = float(a), float(b)
        except ValueError:
            continue
        lat, lng = (y, x) if order == "lnglat" else (x, y)
        if _in_uz(lat, lng):
            return lat, lng
        if _in_uz(lng, lat):
            return lng, lat
    if re.search(r"(yandex\.[a-z]+/maps/-/|maps\.app\.goo\.gl|goo\.gl/maps)", s):
        raise Invalid("Qisqa havoladan nuqtani o'qib bo'lmaydi — xaritada «Ulashish» → "
                      "koordinatalarni (masalan 41.311, 69.279) nusxalab qo'ying")
    if pairs:
        raise Invalid("Lokatsiya O'zbekistondan tashqarida chiqdi — koordinatalarni tekshiring")
    if re.search(r"https?://", s):
        raise Invalid("Havolada koordinata topilmadi — masalan 41.311, 69.279 ko'rinishida yozing")
    return None


def courier_fee(subtotal: float, delivery: str, lat=None, lng=None) -> dict:
    """The buyer's courier fee for Ketoshop's own courier, by the bot's rule
    (handlers.cart.delivery_fee_for); {} for any other method.
    {fee, base, km, extra, far} — far: past the 40 km the courier goes."""
    if delivery != "self":
        return {}
    import courier_zone
    from handlers.cart import FREE_DELIVERY_FROM, SELF_DELIVERY_FEE, delivery_fee_for
    base = 0 if subtotal >= FREE_DELIVERY_FROM else SELF_DELIVERY_FEE
    km = courier_zone.billable_km(lat, lng)
    known = lat is not None and lng is not None
    return {
        "fee": delivery_fee_for("self", subtotal, lat=lat, lng=lng),
        "base": base,
        "km": km,
        "extra": km * courier_zone.PER_KM,
        "far": known and not courier_zone.courier_ok(lat, lng),
        "free_from": FREE_DELIVERY_FROM,
    }


async def post_office(delivery: str, lat, lng, address) -> str | None:
    """The UzPost office line for a manual order: the nearest «Bir Qadam»
    office to the pin, else the index typed in the address, else None."""
    if delivery != "uzpost":
        return None
    import uzpost
    office = None
    if lat is not None and lng is not None:
        try:
            office = await uzpost.nearest_office(lat, lng)
        except Exception:
            office = None
    return uzpost.office_line(office) or uzpost.index_in_text(address)


def items_total(items: list[dict]) -> float:
    return sum(float(it["price"]) * float(it["quantity"]) for it in items)


def parse(body: dict, products: dict[int, dict], *, need_customer: bool = True) -> dict:
    """The site's request → the arguments add_manual_order takes, plus the
    figures the form shows. `products` maps id → product row for every id
    the request names. need_customer=False lets the live total be priced
    before the name/phone/address boxes are filled."""
    if not isinstance(body, dict):
        raise Invalid("so'rov noto'g'ri")

    name = str(body.get("name") or "").strip()
    raw_phone = str(body.get("phone") or "").strip()
    phone = phone_utils.normalize_uz_phone(raw_phone)
    address = str(body.get("address") or "").strip()
    point = parse_location(body.get("location"))
    if point and not address:
        address = f"📍 {point[0]:.6f}, {point[1]:.6f}"
    if need_customer:
        if not name:
            raise Invalid("Mijoz ismini kiriting")
        if not phone:
            raise Invalid("Telefon raqam noto'g'ri — masalan +998 90 123 45 67")
        if not address:
            raise Invalid("Manzilni kiriting (do'kondan olib ketgan bo'lsa — «Olib ketdi»)")
    if len(name) > NAME_MAX or len(address) > ADDRESS_MAX:
        raise Invalid("Ism yoki manzil juda uzun")

    # The bot makes the admin pick all three; so does a save here. Only the
    # running total may be priced before they are chosen.
    payment = body.get("payment") or ("" if need_customer else "cash")
    delivery = body.get("delivery") or ("" if need_customer else "self")
    status = body.get("status") or ("" if need_customer else "pending")
    if payment not in PAYMENTS:
        raise Invalid("To'lov turini tanlang")
    if delivery not in DELIVERIES:
        raise Invalid("Yetkazish turini tanlang")
    if status not in STATUSES:
        raise Invalid("Holatni tanlang")

    raw_items = body.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise Invalid("Kamida bitta mahsulot qo'shing")
    if len(raw_items) > MAX_LINES:
        raise Invalid(f"Bitta buyurtmada {MAX_LINES} tadan ko'p qator bo'lmaydi")
    items = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise Invalid("Mahsulot qatori noto'g'ri")
        try:
            pid = int(raw.get("product_id"))
        except (TypeError, ValueError):
            raise Invalid("Mahsulot tanlanmagan") from None
        product = products.get(pid)
        if not product:
            raise Invalid(f"#{pid} mahsulot topilmadi — sahifani yangilang")
        items.append(make_line(product, raw.get("quantity"), raw.get("price")))

    fee, kg = uzpost_fee(items, address, delivery)
    subtotal = items_total(items)
    lat, lng = point if point else (None, None)
    courier = courier_fee(subtotal, delivery, lat, lng)
    return {
        "customer_name": name,
        "phone": phone or raw_phone,
        "address": address,
        "items": items,
        "payment_method": payment,
        "delivery_method": delivery,
        "status": status,
        "subtotal": subtotal,
        "uzpost_fee": fee,
        "uzpost_kg": kg,
        "latitude": lat,
        "longitude": lng,
        "courier": courier,
        "courier_fee": courier.get("fee", 0),
        "total": subtotal + fee + courier.get("fee", 0),
    }
