"""📦 Oylik savat — har oy o'zi yig'gan savat uyiga keladi (obuna).

Egasi, 2026-11-27: kanalda "eng ko'p ishlatadigan 10 ta mahsulotingiz" deb
so'ralgan edi. Shundan "oylik paket obunasi" g'oyasi chiqdi, keyin: "konstruktor
qilish imkoni bormi? saytda qilsak va botda faqat juda qulay animatsiya bilan
bo'lishi kerak kattalar ham tushunadigan harid savatiga mahsulot rasmlarini
qo'shib". Chegirma: avval 5/8/10/11%, keyin "chegirma summasi ko'p ekan, 11+ ga
10%, undan avvalgisiga 9%, undan avvalgisiga kamroq" — TIERS.
"buni hozir saytda va botda faqat adminlarga ko'rinadigan qil ommaga chiqarma",
"ishlatib testlab ko'raylik".

Qanday ishlaydi
  * Saytda (webapp/savat.html): mijoz mahsulotlarni rasm bilan savatga
    tashlaydi. Chegirma savatdagi DONA soniga qarab (TIERS). 10 donadan
    Ketoshop kuryeri bepul: asosiy 25 000 olinmaydi, shahardan tashqaridagi km
    haqi (courier_zone) odatdagidek. Oyning qaysi kuni kelishini tanlaydi
    (1–28), qayerga yetkazishni tasdiqlaydi.
  * Botda: /oylik_savat — o'z savatining animatsiyasi (GIF: rasmlar birma-bir
    savatga tushadi) va katta tugmalar: ✅ Olib keling / ✏️ O'zgartirish /
    ⏭ Bu oy kerak emas / ⏸ To'xtatish. Kelish kunidan 2 kun oldin bot shu
    xabarni o'zi yuboradi (REMIND_DAYS_BEFORE). Buyurtma faqat mijoz
    «Olib keling» ni bosganda tuziladi, o'zi tuzilmaydi.
  * Buyurtma oddiy buyurtma kabi: ombordan ayriladi, adminlarga kartochka
    keladi (izohda «📦 Oylik savat»). Mijozning oddiy savatiga tegilmaydi.

Hozircha faqat adminlar (ADMIN_IDS) uchun: OYLIK_SAVAT_PUBLIC=1 qilinmaguncha
saytda ham, botda ham boshqa hech kim ko'rmaydi.

Jadval shu modulda yaratiladi (ai_dialog dagidek). Eslatma va GIF xato
ko'tarmaydi.
"""
from __future__ import annotations

import html
import io
import json
import logging
import os
from datetime import date, datetime, timedelta, timezone

import database

logger = logging.getLogger(__name__)

PUBLIC = os.getenv("OYLIK_SAVAT_PUBLIC", "0").strip() == "1"

# (kamida shuncha dona, chegirma %) — kattasidan boshlab.
TIERS = ((11, 10), (10, 9), (8, 7), (5, 4))
MIN_PIECES = 5
FREE_COURIER_PIECES = 10
MAX_LINES = 40
MAX_QTY = 20
DAY_MIN, DAY_MAX = 1, 28
REMIND_DAYS_BEFORE = 2
METHODS = ("self", "pickup", "uzpost")
TZ = timezone(timedelta(hours=5))

# Kanalda odamlar eng ko'p yozganlari (2026-11-23 post) — konstruktorda
# «⭐ Odamlar ko'p oladi» va «Standart» tayyor savat shu ro'yxatdan.
FEATURED = (
    "bodom uni 500", "kokos uni 1000", "zaytun yog'i(qovurish", "psillium sheluxa",
    "eritritol 500", "steviya 200", "himalay tuz 1000", "no'xat uni 1kg",
    "zig'ir uni 500", "kepak. -o",
)
MINI = FEATURED[:1] + ("eritritol 500", "steviya 200", "zig'ir uni 500", "himalay tuz 1000")

_table_ready = False


def allowed(user_id: int | None) -> bool:
    if user_id is None:
        return False
    if PUBLIC:
        return True
    from config import ADMIN_IDS
    return int(user_id) in ADMIN_IDS


async def _ensure(conn) -> None:
    global _table_ready
    if _table_ready:
        return
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS oylik_savat (
            user_id BIGINT PRIMARY KEY,
            items JSONB NOT NULL DEFAULT '[]',
            day SMALLINT NOT NULL DEFAULT 1,
            delivery JSONB NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
            updated_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
            reminded_month TEXT,
            done_month TEXT,
            last_order_id INTEGER
        )
    """)
    _table_ready = True


# ───────────────────────── narx ─────────────────────────

def tier_percent(pieces: float) -> int:
    for need, percent in TIERS:
        if pieces >= need:
            return percent
    return 0


def next_tier(pieces: float) -> dict | None:
    """Keyingi pog'ona: {need: yana nechta, percent} yoki None (eng yuqorisida)."""
    for need, percent in sorted(TIERS):
        if pieces < need:
            return {"need": int(need - pieces + 0.999), "percent": percent,
                    "free_courier": need >= FREE_COURIER_PIECES}
    return None


def _shelf(product: dict) -> float:
    d = database.active_discount(product.get("discount_percent"), product.get("discount_until"))
    return float(database.effective_price(product.get("price") or 0, d, product.get("discount_until")))


def clean_items(raw) -> list[dict]:
    """[{product_id, quantity}] — butun dona, 1..MAX_QTY, takrorlar birlashtiriladi."""
    out: dict[int, int] = {}
    for it in raw if isinstance(raw, list) else []:
        try:
            pid, qty = int(it.get("product_id")), int(float(it.get("quantity") or 0))
        except (AttributeError, TypeError, ValueError):
            continue
        if pid > 0 and qty > 0:
            out[pid] = min(MAX_QTY, out.get(pid, 0) + qty)
    return [{"product_id": p, "quantity": q} for p, q in list(out.items())[:MAX_LINES]]


def price(items: list[dict], products: dict[int, dict], delivery: dict | None = None) -> dict:
    """Savat narxi: har qator chegirma bilan, yetkazish, jami va mijoz qancha tejaydi."""
    delivery = delivery or {}
    lines, shelf_total, pieces = [], 0.0, 0
    for it in items:
        p = products.get(it["product_id"])
        if not p or not p.get("is_active"):
            continue
        pieces += it["quantity"]
    percent = tier_percent(pieces)
    for it in items:
        p = products.get(it["product_id"])
        if not p or not p.get("is_active"):
            continue
        shelf = _shelf(p)
        final = round(shelf * (100 - percent) / 100) if percent else shelf
        line = {"product_id": int(p["id"]), "name": p.get("name"), "quantity": it["quantity"],
                "price": float(final), "unit": p.get("unit") or "", "seller_id": p.get("seller_id")}
        if percent:
            line["original_price"] = shelf
            line["discount_percent"] = percent
        lines.append(line)
        shelf_total += shelf * it["quantity"]
    subtotal = sum(l["price"] * l["quantity"] for l in lines)
    method = delivery.get("method") or "self"
    lat, lng = delivery.get("lat"), delivery.get("lng")
    from handlers.cart import SELF_DELIVERY_FEE, delivery_fee_for
    fee, saved_delivery = 0, 0
    if method == "self":
        import courier_zone
        extra = courier_zone.extra_fee(lat, lng)
        normal = delivery_fee_for("self", subtotal, lat=lat, lng=lng)
        if pieces >= FREE_COURIER_PIECES:
            fee = extra
            saved_delivery = max(0, normal - extra)
        else:
            fee = normal
    elif method == "uzpost":
        import regions
        import uzpost
        far = uzpost.is_far(regions.region_from_pin(lat, lng) or regions.region_from_text(delivery.get("address")))
        fee = delivery_fee_for("uzpost", subtotal, items=lines, far=far)
    savings = round(shelf_total - subtotal) + saved_delivery
    return {
        "lines": lines, "pieces": pieces, "percent": percent, "next": next_tier(pieces),
        "shelf_total": round(shelf_total), "subtotal": round(subtotal),
        "delivery_fee": int(fee), "delivery_saved": int(saved_delivery),
        "free_courier": pieces >= FREE_COURIER_PIECES and method == "self",
        "total": round(subtotal + fee), "savings": savings, "savings_year": savings * 12,
        "ready": pieces >= MIN_PIECES, "min_pieces": MIN_PIECES,
        "self_fee": SELF_DELIVERY_FEE,
    }


async def products_for(items: list[dict]) -> dict[int, dict]:
    out = {}
    for it in items:
        p = await database.get_product(it["product_id"])
        if p:
            out[int(p["id"])] = p
    return out


# ───────────────────────── saqlash ─────────────────────────

def clean_delivery(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    method = raw.get("method") if raw.get("method") in METHODS else "self"

    def num(v):
        try:
            v = float(v)
            return v if v == v else None
        except (TypeError, ValueError):
            return None
    import phone_utils
    return {
        "method": method,
        "name": str(raw.get("name") or "").strip()[:100],
        "phone": phone_utils.normalize_uz_phone(str(raw.get("phone") or "")) or "",
        "address": str(raw.get("address") or "").strip()[:300],
        "lat": num(raw.get("lat")), "lng": num(raw.get("lng")),
    }


async def get(user_id: int) -> dict | None:
    if database.pool is None:
        return None
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        row = await conn.fetchrow("SELECT * FROM oylik_savat WHERE user_id = $1", user_id)
    if not row:
        return None
    sub = dict(row)
    for key in ("items", "delivery"):
        if isinstance(sub.get(key), str):
            sub[key] = json.loads(sub[key])
    return sub


async def save(user_id: int, items: list[dict], day: int, delivery: dict) -> None:
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        await conn.execute(
            """INSERT INTO oylik_savat (user_id, items, day, delivery, status)
               VALUES ($1, $2::jsonb, $3, $4::jsonb, 'active')
               ON CONFLICT (user_id) DO UPDATE SET items = EXCLUDED.items, day = EXCLUDED.day,
                   delivery = EXCLUDED.delivery, status = 'active',
                   updated_at = NOW() AT TIME ZONE 'UTC'""",
            user_id, json.dumps(items), day, json.dumps(delivery, ensure_ascii=False))


async def set_status(user_id: int, status: str) -> None:
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        await conn.execute("UPDATE oylik_savat SET status = $2, updated_at = NOW() AT TIME ZONE 'UTC' "
                           "WHERE user_id = $1", user_id, status)


async def mark(user_id: int, *, reminded: str | None = None, done: str | None = None,
               order_id: int | None = None) -> None:
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        if reminded:
            await conn.execute("UPDATE oylik_savat SET reminded_month = $2 WHERE user_id = $1", user_id, reminded)
        if done:
            await conn.execute("UPDATE oylik_savat SET done_month = $2, last_order_id = COALESCE($3, last_order_id) "
                               "WHERE user_id = $1", user_id, done, order_id)


def month_key(d: date) -> str:
    return d.strftime("%Y-%m")


def next_date(day: int, today: date) -> date:
    """Shu oyning `day`-sanasi, o'tib ketgan bo'lsa keyingi oyniki."""
    if today.day <= day:
        return today.replace(day=day)
    y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
    return date(y, m, day)


# ───────────────────────── sayt uchun katalog ─────────────────────────

async def catalog(lang: str) -> dict:
    """Konstruktorga: sotuvdagi mahsulotlar bo'limlari bilan, «⭐» lar va tayyor savatlar."""
    from webapp_server import photo_url
    from locales import localize_product_text
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT * FROM products
               WHERE is_active = 1 AND COALESCE(b2b_only, FALSE) = FALSE AND quantity >= 1
               ORDER BY name""")
    cats = await database.get_categories()
    names = {c["key"]: (c.get("name_ru") if lang == "ru" and c.get("name_ru") else c["name_uz"]) for c in cats}
    order = {c["key"]: i for i, c in enumerate(cats)}
    products = []
    for r in rows:
        p = dict(r)
        shelf = _shelf(p)
        if shelf <= 0:
            continue
        products.append({
            "id": p["id"], "name": localize_product_text(p.get("name"), p.get("name_ru"), lang),
            "price": round(shelf), "unit": p.get("unit") or "", "stock": float(p.get("quantity") or 0),
            "category": p.get("category"), "photo_url": photo_url(p.get("image_url") or p.get("photo_id")),
            "raw_name": (p.get("name") or "").lower(),
        })

    def pick(keys):
        ids = []
        for k in keys:
            hit = next((p["id"] for p in products if k in p["raw_name"] and p["id"] not in ids), None)
            if hit:
                ids.append(hit)
        return ids
    # Both lists before raw_name is dropped (2026-11-28: pick(MINI) after the
    # pop raised KeyError — every /api/savat was a 500, «Ulanib bo'lmadi»).
    featured = pick(FEATURED)
    mini = pick(MINI)
    for p in products:
        p.pop("raw_name", None)
    used = sorted({p["category"] for p in products}, key=lambda k: order.get(k, 999))
    return {"products": products,
            "categories": [{"key": k, "name": names.get(k, k)} for k in used],
            "featured": featured,
            "presets": {"mini": mini, "standart": featured}}


async def defaults(user_id: int) -> dict:
    prefs = await database.get_last_order_prefs(user_id) or {}
    phone = await database.get_checkout_phone(user_id) or ""
    user = await database.get_user(user_id) if hasattr(database, "get_user") else None
    method = prefs.get("delivery_method") if prefs.get("delivery_method") in METHODS else "self"
    return clean_delivery({
        "method": method, "phone": phone,
        "name": (user or {}).get("full_name") or (user or {}).get("first_name") or "",
        "address": prefs.get("address") or "", "lat": prefs.get("latitude"), "lng": prefs.get("longitude"),
    })


# ───────────────────────── buyurtma ─────────────────────────

class NotReady(Exception):
    pass


async def place_order(bot, user_id: int) -> dict:
    """Obunadagi savatdan buyurtma: chegirmali narx, oddiy buyurtma kabi.
    {order_id, total} yoki {error: 'stock', name, available} / NotReady."""
    sub = await get(user_id)
    if not sub or sub.get("status") != "active":
        raise NotReady("no subscription")
    items = clean_items(sub["items"])
    products = await products_for(items)
    delivery = clean_delivery(sub.get("delivery"))
    quote = price(items, products, delivery)
    if not quote["ready"] or not quote["lines"]:
        raise NotReady("too few")
    if not delivery["phone"] or (delivery["method"] != "pickup" and not delivery["address"]):
        raise NotReady("no address")
    address = delivery["address"]
    pickup = {}
    if delivery["method"] == "pickup":
        settings = await database.get_pickup_settings()
        address = settings.get("address") or "Do'kondan olib ketish"
        pickup = {"pickup_map_url": settings.get("map_url") or None}
    post_office = None
    if delivery["method"] == "uzpost":
        import uzpost
        office = await uzpost.nearest_office(delivery["lat"], delivery["lng"]) if delivery["lat"] else None
        post_office = uzpost.office_line(office) or uzpost.index_in_text(address)
    note = f"📦 Oylik savat (obuna) · {quote['pieces']} dona · −{quote['percent']}%"
    try:
        order_id, low_stock = await database.create_order(
            user_id=user_id, customer_name=delivery["name"] or "—", phone=delivery["phone"],
            address=address, items=quote["lines"], total=quote["total"], payment_method="cash",
            latitude=delivery["lat"], longitude=delivery["lng"], delivery_method=delivery["method"],
            address_note=note, post_office=post_office, clear_cart=False, **pickup)
    except database.InsufficientStockError as exc:
        p = products.get(int(exc.product_id)) or {}
        return {"error": "stock", "name": p.get("name") or str(exc.product_id),
                "available": float(exc.available or 0)}
    await mark(user_id, done=month_key(datetime.now(TZ).date()), order_id=order_id)
    from handlers.cart import _notify_sellers, notify_low_stock, send_order_thanks
    if low_stock:
        await notify_low_stock(bot, low_stock)
    await _notify_sellers(bot, order_id, quote["lines"], {
        "placed": "bot", "customer_name": delivery["name"], "phone": delivery["phone"],
        "secondary_phone": None, "address": address, "address_note": note, "total": quote["total"],
        "latitude": delivery["lat"], "longitude": delivery["lng"], "user_id": user_id,
        "username": None, "delivery_method": delivery["method"], "payment_method": "cash",
        "post_office_line": post_office, **pickup,
    }, "uz")
    await send_order_thanks(bot, user_id, order_id, delivery["method"])
    return {"order_id": order_id, "total": quote["total"]}


# ───────────────────────── animatsiya (GIF) ─────────────────────────

async def _image_bytes(bot, ref) -> bytes | None:
    if not ref:
        return None
    ref = str(ref)
    try:
        if ref.startswith("/img/"):
            row = await database.get_web_image(int(ref.rsplit("/", 1)[1].split("?")[0]))
            return bytes(row["data"]) if row else None
        if ref.startswith("http"):
            return None
        buf = io.BytesIO()
        await bot.download(ref, destination=buf)
        return buf.getvalue()
    except Exception:
        logger.warning("Oylik savat: image %s could not be loaded", ref[:40], exc_info=True)
        return None


def _som(v) -> str:
    return f"{int(round(v)):,}".replace(",", " ")


def render_gif(photos: list[bytes | None], percent: int, total: int, shelf: int) -> bytes | None:
    """Savat va unga birma-bir tushayotgan mahsulot rasmlari. Matnsiz (faqat
    raqamlar) — har tilda tushunarli; gapni xabar matni aytadi."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None
    W = H = 480
    bg, ink, basket, rim, leaf = (250, 246, 239), (58, 49, 41), (201, 138, 99), (166, 94, 64), (110, 154, 106)
    try:
        big = ImageFont.load_default(size=46)
        small = ImageFont.load_default(size=26)
    except TypeError:
        big = small = ImageFont.load_default()
    tiles = []
    for raw in photos[:12]:
        tile = Image.new("RGB", (92, 92), (243, 237, 227))
        if raw:
            try:
                im = Image.open(io.BytesIO(raw)).convert("RGB")
                side = min(im.size)
                im = im.crop(((im.width - side) // 2, (im.height - side) // 2,
                              (im.width + side) // 2, (im.height + side) // 2)).resize((92, 92))
                tile = im
            except Exception:
                pass
        mask = Image.new("L", (92, 92), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, 91, 91), fill=255)
        tiles.append((tile, mask))
    n = len(tiles)
    cols = 4 if n > 6 else 3
    slots = []
    for i in range(n):
        r, c = divmod(i, cols)
        row_n = min(cols, n - r * cols)
        x0 = W // 2 - (row_n * 84) // 2 + c * 84
        slots.append((x0 - 4, 300 - r * 62))

    def base(fill_to: int):
        img = Image.new("RGB", (W, H), bg)
        d = ImageDraw.Draw(img)
        for i in range(fill_to):
            tile, mask = tiles[i]
            img.paste(tile, slots[i], mask)
        # savat: trapetsiya, to'qima chiziqlar, dasta
        d.arc((130, 150, 350, 370), 200, 340, fill=rim, width=10)
        d.polygon([(70, 330), (410, 330), (370, 450), (110, 450)], fill=basket)
        for y in range(350, 450, 22):
            d.line([(80 + (y - 330) // 3, y), (400 - (y - 330) // 3, y)], fill=rim, width=3)
        for x in range(110, 380, 34):
            d.line([(x, 332), (x + 8, 448)], fill=rim, width=2)
        d.rounded_rectangle((62, 318, 418, 342), 10, fill=rim)
        return img, d

    frames, durations = [], []
    for i in range(n):
        tile, mask = tiles[i]
        tx, ty = slots[i]
        for k in range(6):
            img, d = base(i)
            y = int(-100 + (ty + 100) * (k + 1) / 6)
            img.paste(tile, (tx, y), mask)
            frames.append(img)
            durations.append(45)
        img, d = base(i + 1)
        frames.append(img)
        durations.append(160)
    img, d = base(n)
    if percent:
        d.rounded_rectangle((300, 24, 456, 92), 20, fill=leaf)
        d.text((378, 58), f"-{percent}%", fill=(255, 255, 255), font=big, anchor="mm")
    d.text((W // 2 - 80, 58), f"{_som(total)}", fill=ink, font=big, anchor="mm")
    if shelf and shelf > total:
        d.text((W // 2 - 80, 108), _som(shelf), fill=(143, 130, 117), font=small, anchor="mm")
        box = d.textbbox((W // 2 - 80, 108), _som(shelf), font=small, anchor="mm")
        d.line([(box[0] - 4, 108), (box[2] + 4, 108)], fill=(184, 92, 103), width=3)
    frames.append(img)
    durations.append(4000)
    out = io.BytesIO()
    frames[0].save(out, "GIF", save_all=True, append_images=frames[1:], duration=durations, loop=0,
                   optimize=True)
    return out.getvalue()


async def gif_for(bot, items: list[dict], products: dict[int, dict], quote: dict) -> bytes | None:
    photos = []
    for it in items:
        p = products.get(it["product_id"]) or {}
        photos.append(await _image_bytes(bot, p.get("image_url") or p.get("photo_id")))
    try:
        return render_gif(photos, quote["percent"], quote["total"],
                          quote["shelf_total"] + quote["delivery_fee"] + quote["delivery_saved"])
    except Exception:
        logger.warning("Oylik savat GIF failed", exc_info=True)
        return None


# ───────────────────────── matnlar ─────────────────────────

TEXTS = {
    "uz": {
        "title": "📦 <b>Oylik savatingiz</b>",
        "pieces": "{pieces} ta mahsulot · <b>−{percent}%</b> chegirma",
        "total": "💰 Har oy: <b>{total} so'm</b>",
        "shelf": "Do'konda: <s>{shelf} so'm</s>",
        "savings": "💚 Siz har oy <b>{savings} so'm</b> tejaysiz (yiliga {year} so'm)",
        "free": "🚚 Yetkazish bepul",
        "when": "📅 Har oy {day}-sanada · keyingisi: {next}",
        "paused": "⏸ Hozir to'xtatilgan",
        "none": ("📦 <b>Oylik savat</b>\n\nKerakli mahsulotlarni bir marta yig'ing, har oy o'zi uyingizga "
                 "keladi. Qancha ko'p bo'lsa, shuncha arzon:\n"
                 "• 5 ta — −4%\n• 8 ta — −7%\n• 10 ta — −9% va bepul yetkazish\n• 11 ta va ko'p — −10%"),
        "btn_build": "📦 Savatni yig'ish",
        "btn_order": "✅ Olib keling",
        "btn_edit": "✏️ O'zgartirish",
        "btn_skip": "⏭ Bu oy kerak emas",
        "btn_pause": "⏸ To'xtatish",
        "btn_resume": "▶️ Qayta yoqish",
        "reminder": "🔔 {date} kuni oylik savatingizni olib boramiz. Hammasi joyidami?",
        "ordered": "✅ Buyurtma #{order_id} qabul qilindi — {total} so'm. Tez orada bog'lanamiz.",
        "skipped": "⏭ Bu oy olib bormaymiz. Keyingi oy yana eslatamiz.",
        "paused_ok": "⏸ Obuna to'xtatildi. Xohlagan payt «▶️ Qayta yoqish» ni bosing.",
        "resumed": "▶️ Obuna yana yoqildi.",
        "stock": "⚠️ «{name}» yetarli emas (bor: {available}). Savatni o'zgartirib qayta bosing.",
        "not_ready": "⚠️ Savatda kamida 5 ta mahsulot, telefon va manzil bo'lishi kerak — «✏️ O'zgartirish».",
        "no_webapp": "Sayt manzili sozlanmagan (WEBAPP_URL).",
        "test_note": "🧪 Sinov: hozircha faqat adminlar ko'radi.",
    },
    "ru": {
        "title": "📦 <b>Ваша ежемесячная корзина</b>",
        "pieces": "{pieces} товаров · скидка <b>−{percent}%</b>",
        "total": "💰 Каждый месяц: <b>{total} сум</b>",
        "shelf": "В магазине: <s>{shelf} сум</s>",
        "savings": "💚 Вы экономите <b>{savings} сум</b> в месяц ({year} сум в год)",
        "free": "🚚 Доставка бесплатно",
        "when": "📅 Каждый месяц {day}-го · следующая: {next}",
        "paused": "⏸ Сейчас на паузе",
        "none": ("📦 <b>Ежемесячная корзина</b>\n\nСоберите нужные продукты один раз — каждый месяц они "
                 "сами приедут к вам. Чем больше, тем выгоднее:\n"
                 "• 5 шт — −4%\n• 8 шт — −7%\n• 10 шт — −9% и бесплатная доставка\n• 11 шт и больше — −10%"),
        "btn_build": "📦 Собрать корзину",
        "btn_order": "✅ Привезите",
        "btn_edit": "✏️ Изменить",
        "btn_skip": "⏭ В этом месяце не нужно",
        "btn_pause": "⏸ Остановить",
        "btn_resume": "▶️ Включить снова",
        "reminder": "🔔 {date} привезём вашу ежемесячную корзину. Всё верно?",
        "ordered": "✅ Заказ #{order_id} принят — {total} сум. Скоро свяжемся.",
        "skipped": "⏭ В этом месяце не привезём. Напомним в следующем.",
        "paused_ok": "⏸ Подписка остановлена. Нажмите «▶️ Включить снова», когда захотите.",
        "resumed": "▶️ Подписка снова включена.",
        "stock": "⚠️ «{name}» недостаточно (есть: {available}). Измените корзину и нажмите снова.",
        "not_ready": "⚠️ В корзине должно быть минимум 5 товаров, телефон и адрес — «✏️ Изменить».",
        "no_webapp": "Адрес сайта не настроен (WEBAPP_URL).",
        "test_note": "🧪 Тест: пока видят только админы.",
    },
}


def t(key: str, lang: str, **kw) -> str:
    table = TEXTS["ru" if lang == "ru" else "uz"]
    text = table[key].format(**kw) if kw else table[key]
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        text = lat_to_cyr(text)
    return text


def summary_text(sub: dict, quote: dict, lang: str, today: date) -> str:
    lines = [t("title", lang), ""]
    for l in quote["lines"]:
        lines.append(f"• {html.escape(str(l['name']))} × {l['quantity']}")
    lines += ["", t("pieces", lang, pieces=quote["pieces"], percent=quote["percent"]),
              t("total", lang, total=_som(quote["total"])),
              t("shelf", lang, shelf=_som(quote["shelf_total"] + quote["delivery_fee"] + quote["delivery_saved"]))]
    if quote["savings"]:
        lines.append(t("savings", lang, savings=_som(quote["savings"]), year=_som(quote["savings_year"])))
    if quote["free_courier"]:
        lines.append(t("free", lang))
    lines.append(t("when", lang, day=sub["day"], next=next_date(int(sub["day"]), today).strftime("%d.%m")))
    if sub.get("status") != "active":
        lines.append(t("paused", lang))
    if not PUBLIC:
        lines += ["", t("test_note", lang)]
    return "\n".join(lines)


# ───────────────────────── bot ─────────────────────────

from aiogram import F, Router  # noqa: E402
from aiogram.filters import Command  # noqa: E402
from aiogram.types import (BufferedInputFile, CallbackQuery, InlineKeyboardButton,  # noqa: E402
                           InlineKeyboardMarkup, Message, WebAppInfo)

router = Router(name="oylik_savat")
REMIND_HOUR = 9          # Toshkent, 09:00 dan keyin
_sent_today: set[tuple[int, str]] = set()


def page_url() -> str | None:
    from config import WEBAPP_URL
    return (WEBAPP_URL.rstrip("/") + "/static/savat.html") if WEBAPP_URL else None


def keyboard(sub: dict | None, lang: str) -> InlineKeyboardMarkup:
    url = page_url()
    edit = [InlineKeyboardButton(text=t("btn_edit" if sub else "btn_build", lang), web_app=WebAppInfo(url=url))] \
        if url else []
    if not sub:
        return InlineKeyboardMarkup(inline_keyboard=[edit] if edit else [])
    rows = []
    if sub.get("status") == "active":
        rows.append([InlineKeyboardButton(text=t("btn_order", lang), callback_data="osav:order")])
        if edit:
            rows.append(edit)
        rows.append([InlineKeyboardButton(text=t("btn_skip", lang), callback_data="osav:skip"),
                     InlineKeyboardButton(text=t("btn_pause", lang), callback_data="osav:pause")])
    else:
        rows.append([InlineKeyboardButton(text=t("btn_resume", lang), callback_data="osav:resume")])
        if edit:
            rows.append(edit)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_card(bot, user_id: int, lang: str, head: str | None = None) -> None:
    """Mijozga o'z savati: GIF (rasmlar savatga tushadi) + yozuv + tugmalar."""
    sub = await get(user_id)
    if not sub:
        await bot.send_message(user_id, t("none", lang), parse_mode="HTML", reply_markup=keyboard(None, lang))
        return
    items = clean_items(sub["items"])
    products = await products_for(items)
    quote = price(items, products, clean_delivery(sub.get("delivery")))
    text = summary_text(sub, quote, lang, datetime.now(TZ).date())
    if head:
        text = head + "\n\n" + text
    kb = keyboard(sub, lang)
    gif = await gif_for(bot, items, products, quote)
    if gif and len(text) <= 1024:
        try:
            await bot.send_animation(user_id, BufferedInputFile(gif, "oylik_savat.gif"), caption=text,
                                     parse_mode="HTML", reply_markup=kb)
            return
        except Exception:
            logger.warning("Oylik savat animation failed for %s", user_id, exc_info=True)
    await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=kb)


@router.message(Command("oylik_savat"))
async def cmd_oylik_savat(message: Message):
    if message.chat.type != "private" or not allowed(message.from_user.id):
        return
    lang = await database.get_user_language(message.from_user.id) or "uz"
    await send_card(message.bot, message.from_user.id, lang)


async def _reply(cb: CallbackQuery, text: str) -> None:
    try:
        await cb.message.answer(text, parse_mode="HTML")
    except Exception:
        pass


@router.callback_query(F.data.startswith("osav:"))
async def cb_oylik_savat(cb: CallbackQuery):
    user_id = cb.from_user.id
    if not allowed(user_id):
        await cb.answer()
        return
    lang = await database.get_user_language(user_id) or "uz"
    action = cb.data.split(":", 1)[1]
    month = month_key(datetime.now(TZ).date())
    if action == "order":
        await cb.answer("⏳")
        try:
            result = await place_order(cb.bot, user_id)
        except NotReady:
            await _reply(cb, t("not_ready", lang))
            return
        if result.get("error") == "stock":
            await _reply(cb, t("stock", lang, name=html.escape(result["name"]),
                               available=f"{result['available']:g}"))
            return
        await _reply(cb, t("ordered", lang, order_id=result["order_id"], total=_som(result["total"])))
        return
    if action == "skip":
        await mark(user_id, done=month)
        await cb.answer()
        await _reply(cb, t("skipped", lang))
        return
    if action in ("pause", "resume"):
        await set_status(user_id, "paused" if action == "pause" else "active")
        await cb.answer()
        await _reply(cb, t("paused_ok" if action == "pause" else "resumed", lang))
        try:
            await cb.message.edit_reply_markup(reply_markup=keyboard(await get(user_id), lang))
        except Exception:
            pass
        return
    await cb.answer()


async def due(today: date) -> list[dict]:
    """Bugun eslatiladiganlar: faol, kelish kuniga REMIND_DAYS_BEFORE kun qolgan
    (yoki kelish kuni o'zi, eslatma hali ketmagan), bu oy buyurtma/o'tkazish yo'q."""
    if database.pool is None:
        return []
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        rows = await conn.fetch("SELECT * FROM oylik_savat WHERE status = 'active'")
    out = []
    for r in rows:
        sub = dict(r)
        when = next_date(int(sub["day"]), today)
        key = month_key(when)
        if sub.get("done_month") == key or sub.get("reminded_month") == key:
            continue
        if 0 <= (when - today).days <= REMIND_DAYS_BEFORE and allowed(sub["user_id"]):
            out.append({**sub, "_when": when, "_key": key})
    return out


async def tick(bot) -> int:
    now = datetime.now(TZ)
    if now.hour < REMIND_HOUR or now.hour >= 21:
        return 0
    sent = 0
    for sub in await due(now.date()):
        uid = sub["user_id"]
        lang = await database.get_user_language(uid) or "uz"
        try:
            await send_card(bot, uid, lang, head=t("reminder", lang, date=sub["_when"].strftime("%d.%m")))
            sent += 1
        except Exception:
            logger.warning("Oylik savat reminder to %s failed", uid, exc_info=True)
        await mark(uid, reminded=sub["_key"])
    return sent


async def scheduler_loop(bot) -> None:
    import asyncio
    await asyncio.sleep(90)
    while True:
        try:
            await tick(bot)
        except Exception:
            logger.exception("oylik savat tick failed")
        await asyncio.sleep(600)
