"""
Telegram Mini App (WebApp) server — aiohttp API alongside the bot
"""
import datetime as _dt
import functools
import hashlib
import hmac
import json
import logging
import os
import time
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qsl, unquote

from aiohttp import web
from aiogram import Bot

import promotions


def _json_default(obj):
    """JSON fallback for types asyncpg returns that json.dumps can't handle.
    Without this, e.g. AVG() over a NUMERIC column comes back as Decimal and
    every endpoint that touches it 500s with a TypeError."""
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, (_dt.datetime, _dt.date, _dt.time)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


_safe_dumps = functools.partial(json.dumps, default=_json_default)


def _json(data, *, status=200, **kwargs):
    """Drop-in for web.json_response that tolerates Decimal/datetime."""
    return web.json_response(data, status=status, dumps=_safe_dumps, **kwargs)

from config import BOT_TOKEN, ITEMS_PER_PAGE, SUPPORT_USERNAME, PAYMENT_CARD_NUMBER, PAYMENT_RECIPIENT_NAME
from database import (
    get_products_by_category, get_discounted_products, get_product, search_products,
    get_top_ordered_products, get_top_active_customers, get_all_products_paginated,
    get_cart, add_to_cart, remove_from_cart, clear_cart,
    get_cart_item, set_cart_quantity,
    get_delivery_zones, get_product_rating, get_product_media,
    create_order, get_user_language, update_user_language,
    add_product_view, effective_price, active_discount,
    get_user_orders, get_order, cancel_order, get_user,
    get_product_reviews, add_review, delete_review, get_user_review,
    InsufficientStockError, InsufficientKetoError, LEADERBOARD_EXCLUDED_USER_IDS,
)
import gamification
from gamification import EARN_RATE as KETO_EARN_RATE
from locales import CATEGORIES, get_category_name, get_unit_name, get_display_unit, get_text, get_delivery_method_name, localize_product_text
from config import ADMIN_IDS

logger = logging.getLogger(__name__)

# Cache Telegram file URLs for 30 minutes
_photo_cache: dict[str, tuple[str, float]] = {}
PHOTO_CACHE_TTL = 1800


# Reject initData older than this. Telegram doesn't refresh initData while the
# Mini App is open (it's set once at launch), so 5-min was too aggressive and
# locked users out mid-browse. 24h matches Telegram's own published guidance.
def _parse_ttl() -> int:
    raw = os.getenv("WEBAPP_INIT_DATA_TTL", "").strip()
    if not raw:
        return 86400
    try:
        return int(raw)
    except ValueError:
        logger.warning("WEBAPP_INIT_DATA_TTL=%r is not an integer; falling back to 86400", raw)
        return 86400


INIT_DATA_MAX_AGE = _parse_ttl()


def _validate_init_data(init_data: str, bot_token: str) -> dict | None:
    """Validate Telegram WebApp initData and return parsed data.
    Returns dict with user info on success, None on failure (bad hash, expired,
    or malformed)."""
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", "")
        if not received_hash:
            return None

        # Build data-check-string: sorted key=value pairs joined by \n
        data_check = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed.items())
        )

        # HMAC-SHA256(secret_key, data_check_string)
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        computed_hash = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()

        if not hmac.compare_digest(computed_hash, received_hash):
            logger.info("initData rejected: HMAC mismatch")
            return None

        # Replay protection: reject initData older than INIT_DATA_MAX_AGE.
        # Without this, a captured initData stays valid forever — anyone with
        # a copy could impersonate the user (place orders, write reviews, etc.).
        try:
            auth_date = int(parsed.get("auth_date", "0"))
        except ValueError:
            logger.info("initData rejected: auth_date not parseable")
            return None
        age = time.time() - auth_date
        if auth_date <= 0 or age > INIT_DATA_MAX_AGE:
            logger.info("initData rejected: stale (age=%.0fs, limit=%ds)",
                        age, INIT_DATA_MAX_AGE)
            return None

        # Parse user JSON
        user_data = parsed.get("user")
        if user_data:
            parsed["user"] = json.loads(unquote(user_data))

        return parsed
    except Exception:
        logger.exception("initData validation failed")
        return None


@web.middleware
async def auth_middleware(request: web.Request, handler):
    """Validate Telegram WebApp initData on /api/* routes."""
    path = request.path

    # Skip auth for static files, root page, photo proxy, and the health probe.
    if not path.startswith("/api/") or path.startswith("/api/photo/") or path == "/healthz":
        return await handler(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("tma "):
        return _json({"error": "unauthorized"}, status=401)

    init_data_raw = auth_header[4:]
    bot_token = request.app["bot_token"]
    parsed = _validate_init_data(init_data_raw, bot_token)
    if not parsed:
        return _json({"error": "invalid initData"}, status=403)

    user = parsed.get("user", {})
    request["user_id"] = user.get("id")
    # Use saved language from DB, fall back to Telegram app language
    db_lang = await get_user_language(user.get("id")) if user.get("id") else None
    if db_lang and db_lang in ("uz", "uz_cyr", "ru"):
        request["user_lang"] = db_lang
    else:
        request["user_lang"] = user.get("language_code", "uz")
        if request["user_lang"] not in ("uz", "uz_cyr", "ru"):
            request["user_lang"] = "uz"

    return await handler(request)


# ===== ROUTES =====

async def healthz(request: web.Request):
    """Public health probe — returns 200 + a SELECT 1 ping so Railway
    (or any uptime monitor) can verify both the webapp and DB are alive."""
    import database
    try:
        if database.pool is not None:
            async with database.pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
        return _json({"status": "ok", "db": "ok"})
    except Exception as exc:
        logger.warning("Health check DB ping failed: %s", exc)
        return _json({"status": "degraded", "db": "down"}, status=503)


async def index(request: web.Request):
    """Serve the Mini App HTML (no-cache so updates deploy instantly)."""
    html_path = Path(__file__).parent / "webapp" / "index.html"
    html = html_path.read_text(encoding="utf-8")
    html = html.replace("{{SUPPORT_USERNAME}}", SUPPORT_USERNAME)
    return web.Response(
        text=html,
        content_type="text/html",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


async def api_categories(request: web.Request):
    """Return list of categories with localized names."""
    lang = request.get("user_lang", "uz")
    cats = []
    for key in CATEGORIES:
        name = get_category_name(key, lang)
        cats.append({"key": key, "name": name})
    
    # Add Sets category
    from locales import get_text
    cats.append({"key": "sets", "name": get_text("btn_sets", lang)})
    
    return _json(cats)


async def api_products(request: web.Request):
    """Return paginated products, optionally filtered by category."""
    lang = request.get("user_lang", "uz")
    category = request.query.get("category", "")
    page = int(request.query.get("page", "0"))
    # Home page requests every product in a category at once (no "N more"
    # pager there) — capped so a bad query string can't force a huge scan.
    per_page = min(int(request.query.get("per_page", ITEMS_PER_PAGE)), 200)

    # Discounts pseudo-category: active-discount products across all categories.
    if category == "discounts":
        products, total = await get_discounted_products(page=page, per_page=ITEMS_PER_PAGE)
        return _json({
            "products": _serialize_products(products, lang),
            "total": total,
            "page": page,
            "pages": (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE,
        })

    # Sets category
    if category == "sets":
        from database import get_active_sets_for_catalog
        sets = await get_active_sets_for_catalog()
        serialized = []
        for s in sets:
            serialized.append({
                "id": s["id"],
                "name": s["name_ru"] if lang == "ru" and s.get("name_ru") else s["name"],
                "price": s["set_price"],
                "photo_id": s["image_url"],
                "unit": "piece",
                "quantity": 999,
                "is_set": True,
            })
        
        # Paginate sets
        total = len(serialized)
        start = page * per_page
        sliced = serialized[start : start + per_page]
        
        return _json({
            "products": sliced,
            "total": total,
            "page": page,
            "pages": (total + per_page - 1) // per_page,
        })

    if not category or category not in CATEGORIES:
        # "Hammasi/All" tab — genuinely paginated across every category, not
        # just a first-page slice, so infinite scroll actually reaches everything.
        products, total = await get_all_products_paginated(page=page, per_page=per_page)
        return _json({
            "products": _serialize_products(products, lang),
            "total": total,
            "page": page,
            "pages": (total + per_page - 1) // per_page,
        })

    products, total = await get_products_by_category(category, page=page, per_page=per_page)
    return _json({
        "products": _serialize_products(products, lang),
        "total": total,
        "page": page,
        "pages": (total + per_page - 1) // per_page,
    })


async def api_product_detail(request: web.Request):
    """Return single product detail."""
    product_id = int(request.match_info["id"])
    lang = request.get("user_lang", "uz")
    p = await get_product(product_id)
    if not p or p.get("is_active", 0) == 0:
        return _json({"error": "not_found"}, status=404)
    
    try:
        await add_product_view(product_id, request.get("user_id"))
    except Exception:
        pass

    avg_rating, review_count = await get_product_rating(product_id)
    media = await get_product_media(product_id)
    data = _serialize_product(p, lang)
    data["rating"] = avg_rating
    data["review_count"] = review_count
    data["description"] = localize_product_text(
        p.get("description"), p.get("description_ru"), lang
    )
    # Seller identity is internal — admins only (owner request 2026-07-30),
    # never shown to regular buyers.
    data["seller_name"] = p.get("seller_name", "") if request.get("user_id") in ADMIN_IDS else ""
    data["quantity"] = p.get("quantity", 0)
    data["out_of_stock"] = p.get("quantity", 0) <= 0
    data["media"] = [
        {
            "url": f"/api/photo/{m['file_id']}",
            "type": m["media_type"],
        }
        for m in media
    ]
    return _json(data)


async def api_set_detail(request: web.Request):
    set_id = int(request.match_info["id"])
    lang = request.get("user_lang", "uz")
    from database import get_set
    s = await get_set(set_id)
    if not s or s.get("is_active", 0) == 0:
        return _json({"error": "not_found"}, status=404)
    
    # serialize set like a product
    return _json({
        "id": s["id"],
        "name": s["name_ru"] if lang == "ru" and s.get("name_ru") else s["name"],
        "description": "Tarkibi: " + ", ".join([f"{i['name_ru'] if lang == 'ru' and i.get('name_ru') else i['name']} ({i['quantity']})" for i in s["items"]]),
        "price": s["set_price"],
        "photo_id": s["image_url"],
        "unit": "piece",
        "quantity": 999,
        "is_set": True,
        "out_of_stock": False
    })


def _review_display_name(full_name: str | None, username: str | None) -> str:
    return full_name or (f"@{username}" if username else "Anonim")


async def api_product_reviews(request: web.Request):
    """Public — every buyer can read a product's reviews (owner request
    2026-07-30: "keyingi userlar shu izohlarni ko'rib xulosa qila olishadi").
    Includes is_admin so the Mini App shows a delete button only to admins;
    the actual delete is still authorized server-side, not just hidden."""
    product_id = int(request.match_info["id"])
    user_id = request["user_id"]
    reviews = await get_product_reviews(product_id)
    my_review = await get_user_review(user_id, product_id)
    return _json({
        "reviews": [
            {
                "id": r["id"],
                "rating": r["rating"],
                "comment": r.get("comment"),
                "name": _review_display_name(r.get("full_name"), r.get("username")),
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
                "is_mine": r["user_id"] == user_id,
            }
            for r in reviews
        ],
        "is_admin": user_id in ADMIN_IDS,
        "my_review": {"rating": my_review["rating"], "comment": my_review.get("comment")} if my_review else None,
    })


async def api_product_review_submit(request: web.Request):
    """Write (or update) the current user's own review for this product —
    one per buyer per product, same as the bot's flow (see handlers/reviews.py)."""
    product_id = int(request.match_info["id"])
    user_id = request["user_id"]
    if not await get_product(product_id):
        return _json({"error": "not found"}, status=404)

    try:
        b = await request.json()
        rating = int(b.get("rating"))
        if rating < 1 or rating > 5:
            raise ValueError
    except Exception:
        return _json({"error": "rating must be 1-5"}, status=400)

    comment = (b.get("comment") or "").strip()[:1000] or None
    await add_review(user_id=user_id, product_id=product_id, rating=rating, comment=comment)
    return _json({"ok": True})


async def api_review_delete(request: web.Request):
    """Admin-only moderation (owner request 2026-07-30: "xavfsizlik uchun")."""
    if request["user_id"] not in ADMIN_IDS:
        return _json({"error": "forbidden"}, status=403)
    review_id = int(request.match_info["id"])
    await delete_review(review_id)
    return _json({"ok": True})


async def api_top(request: web.Request):
    """Top-3 most-ordered active products for the home podium."""
    lang = request.get("user_lang", "uz")
    products = await get_top_ordered_products(limit=3)
    return _json(_serialize_products(products, lang))


def _leaderboard_display_name(full_name: str | None) -> str | None:
    """"First L." from a free-text Telegram display name — strips emoji/
    punctuation so a name like "❤️Umida❤️ Muhammadali❤️" becomes "Umida M."
    Returns None if nothing nameable is left."""
    if not full_name:
        return None
    cleaned = "".join(ch for ch in full_name if ch.isalpha() or ch in " '’-")
    words = [w for w in cleaned.split() if w]
    if not words:
        return None
    first = words[0].capitalize()
    if len(words) > 1:
        return f"{first} {words[-1][0].upper()}."
    return first


async def api_leaderboard(request: web.Request):
    """Top-5 most active real customers (last 30 days) for the marketing
    podium — first name + last initial only, no username/price/order count."""
    customers = await get_top_active_customers(days=30, limit=5)
    names = [n for c in customers if (n := _leaderboard_display_name(c["full_name"]))]
    return _json(names)


async def api_search(request: web.Request):
    """Search products by name."""
    lang = request.get("user_lang", "uz")
    q = request.query.get("q", "").strip()
    if len(q) < 2:
        return _json([])
    products, total = await search_products(q, page=0, per_page=20)
    return _json(_serialize_products(products, lang))


async def api_cart(request: web.Request):
    """Get user's cart."""
    user_id = request["user_id"]
    lang = request.get("user_lang", "uz")
    items = await get_cart(user_id)
    result = []
    total = 0
    for item in items:
        discount = active_discount(item.get("discount_percent"), item.get("discount_until"))
        unit_price = effective_price(item["price"], discount, item.get("discount_until"))
        item_total = unit_price * item["cart_quantity"]
        total += item_total
        result.append({
            "cart_id": item["cart_id"],
            "product_id": item["product_id"],
            "name": item["name"],
            "price": unit_price,
            "original_price": item["price"],
            "discount_percent": discount,
            "quantity": item["cart_quantity"],
            "unit": get_display_unit(item["unit"], lang),
            # kg/g products are sold as integer pieces; everything else allows
            # 0.5 increments. Frontend uses this to pick the qty-stepper step.
            "packaged": item["unit"] in ("kg", "g"),
            "available": float(item.get("stock") or 0),
            "total": item_total,
            "photo_url": f"/api/photo/{item['photo_id']}" if item.get("photo_id") else None,
        })

    # Free aksiya bonuses earned by what's in the cart. Recomputed on every
    # read rather than stored on the cart row, so a quantity change or a
    # campaign ending is reflected the moment the page refreshes.
    bonus_input = [
        {"product_id": it.get("product_id"), "quantity": it["cart_quantity"], "is_set": it.get("is_set", False)}
        for it in items
    ]
    promo = await promotions.get_active()
    bonuses = promotions.compute_bonuses(promo, bonus_input)
    misses = promotions.compute_near_misses(promo, bonus_input)

    def _nm(m):
        name = m.get("trigger_name_ru") if (lang == "ru" and m.get("trigger_name_ru")) else m.get("trigger_name")
        bname = m.get("bonus_name_ru") if (lang == "ru" and m.get("bonus_name_ru")) else m.get("bonus_name")
        return {
            "product_id": m["trigger_product_id"],
            "name": name,
            "needed": promotions.fmt_amount(m["needed"]),
            "needed_unit": promotions.trigger_unit_label(m, lang),
            "bonus": f"{promotions.fmt_amount(m['bonus_amount'])} {promotions.unit_label(m['bonus_unit'], lang)} {bname}",
        }

    return _json({
        "items": result,
        "total": total,
        "bonuses": [
            {"name": b.get("name_ru") if (lang == "ru" and b.get("name_ru")) else b.get("name"),
             "amount": promotions.fmt_amount(b["quantity"]),
             "unit": promotions.unit_label(b["unit"], lang),
             # Shelf price of the giveaway, struck through client-side so the
             # bonus reads as money saved rather than a valueless freebie.
             "value": round(float(b.get("bonus_value") or 0)),
             "photo_url": f"/api/photo/{b['photo_id']}" if b.get("photo_id") else None}
            for b in bonuses
        ],
        "bonuses_value": round(promotions.bonuses_total_value(bonuses)),
        "near_misses": [_nm(m) for m in misses[:3]],
    })


async def api_cart_add(request: web.Request):
    """Add item to cart. Mini App quantities are integers only — we round
    here as a defense in depth: even if a customised client sends 0.5, the
    server rounds it up to 1 before persisting so the cart stays on the
    integer grid the bot side already assumes."""
    user_id = request["user_id"]
    data = await request.json()
    product_id = data.get("product_id")
    set_id = data.get("set_id")
    quantity = float(data.get("quantity", 1.0))
    if quantity <= 0:
        return _json({"error": "invalid_quantity"}, status=400)
        
    if product_id:
        product_id = int(product_id)
        from database import get_product
        product = await get_product(product_id)
        if not product or (product.get("quantity") or 0) <= 0:
            return _json({"error": "out_of_stock"}, status=400)
        if quantity > product["quantity"]:
            return _json({"error": "exceeds_stock", "available": product["quantity"]}, status=400)
    elif set_id:
        set_id = int(set_id)

    await add_to_cart(user_id, product_id=product_id, quantity=quantity, set_id=set_id)
    return _json({"ok": True})


async def api_cart_remove(request: web.Request):
    """Remove item from cart."""
    body = await request.json()
    cart_id = int(body["cart_id"])
    await remove_from_cart(cart_id)
    return _json({"ok": True})


async def api_cart_update(request: web.Request):
    """Set a cart line's quantity. Validates ownership and stock.

    Quantities are integers only — the previous half-step path for non-kg
    units led to 0.5 entries that confused buyers and the bot side (which
    has always stepped by 1). We round the incoming value and clamp to a
    minimum of 1, regardless of unit."""
    user_id = request["user_id"]
    body = await request.json()
    cart_id = int(body["cart_id"])
    raw_quantity = float(body.get("quantity", 0))

    item = await get_cart_item(cart_id)
    if not item or item["user_id"] != user_id:
        return _json({"error": "not_found"}, status=404)

    # Quantity ≤ 0 → drop the line. Saves the user a separate × tap when
    # they decrement to zero.
    if raw_quantity <= 0:
        await remove_from_cart(cart_id)
        return _json({"ok": True, "removed": True})

    quantity = max(1, int(round(raw_quantity)))
    stock = float(item.get("stock") or 0)
    if quantity > stock:
        return _json({"error": "exceeds_stock", "available": stock}, status=400)

    await set_cart_quantity(cart_id, quantity)
    return _json({"ok": True, "quantity": quantity})


async def api_cart_clear(request: web.Request):
    """Clear user's cart."""
    user_id = request["user_id"]
    await clear_cart(user_id)
    return _json({"ok": True})


async def api_checkout(request: web.Request):
    """Process checkout from the webapp."""
    import re
    user_id = request["user_id"]
    lang = request.get("user_lang", "uz")
    body = await request.json()

    phone = (body.get("phone") or "").strip()
    address = (body.get("address") or "").strip()
    latitude = body.get("latitude")
    longitude = body.get("longitude")
    payment_method = body.get("payment_method", "cash")
    delivery_method = (body.get("delivery_method") or "").strip() or None
    # Optional buyer-reviewed/corrected address line. Coords stay
    # authoritative for the courier's pin; this is the human-readable
    # 📝 note alongside. Capped to 500 to match the bot's note flow.
    address_note = (body.get("address_note") or "").strip()[:500] or None

    if not phone or not re.match(r'^\+?998\d{9}$', phone.replace(" ", "").replace("-", "")):
        return _json({"error": "invalid_phone"}, status=400)
    if not latitude or not longitude:
        return _json({"error": "invalid_location"}, status=400)

    from handlers.cart import verify_uzbekistan, get_location_address_text, SELF_DELIVERY_FEE, _is_tashkent
    if not await verify_uzbekistan(float(latitude), float(longitude)):
        return _json({"error": "outside_uzbekistan"}, status=400)

    # "self" (Ketoshop's own courier) only exists inside Tashkent — reject it
    # if the submitted coords don't actually fall in that area, so a buyer
    # elsewhere can't claim the flat in-city fee / cash payment.
    if delivery_method == "self" and not _is_tashkent(float(latitude), float(longitude)):
        return _json({"error": "invalid_delivery_method"}, status=400)

    # Ketoshop's own courier ("self") takes cash or online. Every other
    # delivery method (Yandex Taxi/Market, BTS, EMU) is a third-party courier
    # that won't collect cash on our behalf — online only for those.
    if payment_method == "cash" and delivery_method != "self":
        return _json({"error": "cash_not_available"}, status=400)

    if not address:
        readable = await get_location_address_text(float(latitude), float(longitude))
        address = f"📍 {latitude:.6f}, {longitude:.6f}"
        if readable:
            address += f" — {readable}"

    cart_items = await get_cart(user_id)
    if not cart_items:
        return _json({"error": "cart_empty"}, status=400)

    items_data = []
    for item in cart_items:
        discount = active_discount(item.get("discount_percent"), item.get("discount_until"))
        unit_price = effective_price(item["price"], discount, item.get("discount_until"))
        items_data.append({
            "product_id": item.get("product_id"),
            "set_id": item.get("set_id"),
            "is_set": item.get("is_set", False),
            "name": item["name"],
            "quantity": item["cart_quantity"],
            "price": unit_price,
            "original_price": item["price"],
            "discount_percent": discount,
            "unit": item["unit"],
            "seller_id": item.get("seller_id"),
        })
    # Free aksiya bonuses become 0-so'm lines inside items_data, exactly as on
    # the bot side — create_order freezes them into orders.items and the
    # admin's order notification shows them to whoever packs the box. They add
    # nothing to the totals (price is 0).
    items_data.extend(await promotions.bonuses_for_items(items_data))

    total = sum(item["price"] * item["quantity"] for item in items_data)
    subtotal = total  # product-only, before delivery fee — what Keto earns off of
    if delivery_method == "self":
        total += SELF_DELIVERY_FEE

    # Preview of the Keto reward this order will earn once delivered (see
    # gamification.py) — shown on the order-success screen so the buyer
    # knows upfront, not just after delivery. Zero for admin/internal
    # accounts, which never actually earn (mirrors gamification._is_eligible).
    expected_keto = 0
    if user_id not in ADMIN_IDS and user_id not in LEADERBOARD_EXCLUDED_USER_IDS:
        expected_keto = int(subtotal * KETO_EARN_RATE)

    # Keto-as-discount (opt-in, off by default — see
    # gamification.is_redemption_enabled). Never trust the client's flag
    # state: re-derive whether this is even allowed server-side, and clamp
    # to the buyer's *current* balance regardless of what they requested.
    keto_redeem = 0
    if await gamification.is_redemption_enabled():
        try:
            requested = int(body.get("keto_redeem") or 0)
        except (TypeError, ValueError):
            requested = 0
        if requested > 0:
            buyer = await get_user(user_id)
            balance = int(buyer["keto_balance"]) if buyer else 0
            keto_redeem = max(0, min(requested, balance, int(total)))
    total -= keto_redeem

    # Get customer name from Telegram initData
    auth_header = request.headers.get("Authorization", "")
    init_data_raw = auth_header[4:] if auth_header.startswith("tma ") else ""
    parsed = _validate_init_data(init_data_raw, request.app["bot_token"])
    user = (parsed or {}).get("user", {})
    customer_name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")])) or "—"
    customer_username = user.get("username")

    bot: Bot = request.app["bot"]

    # Online payments: defer order creation until the cheque actually arrives.
    # Same model as the bot's _create_and_process_order — we stash everything
    # in FSM state and return without an order_id. The order is inserted by
    # /api/checkout/cheque (Mini App upload) or process_cheque_photo /
    # _document (bot chat upload). This guarantees no half-real orders sit
    # in the DB when a buyer abandons before paying.
    if payment_method == "online":
        storage = request.app.get("storage")
        if storage is None:
            logger.error("FSM storage unavailable — cannot defer online checkout for user %s", user_id)
            return _json({"error": "server_misconfigured"}, status=500)

        try:
            from aiogram.fsm.context import FSMContext
            from aiogram.fsm.storage.base import StorageKey
            from handlers.cart import CheckoutStates

            key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
            state = FSMContext(storage=storage, key=key)
            await state.set_state(CheckoutStates.waiting_cheque)
            await state.update_data(
                lang=lang,
                pending_items=items_data,
                pending_total=total,
                pending_customer_name=customer_name,
                pending_phone=phone,
                pending_address=address,
                pending_address_note=address_note,
                pending_secondary_phone=None,  # Mini App doesn't collect a backup number yet
                pending_delivery_method=delivery_method,
                pending_latitude=float(latitude),
                pending_longitude=float(longitude),
                pending_keto_redeem=keto_redeem,
            )
        except Exception:
            logger.exception("Failed to stash pending checkout for user %s", user_id)
            return _json({"error": "server_error"}, status=500)

        # No order_id here — the order doesn't exist yet. Card details come
        # back so the Mini App's cheque page can render them with copy buttons.
        return _json({
            "ok": True,
            "awaiting_cheque": True,
            "total": total,
            "expected_keto": expected_keto,
            "keto_redeemed": keto_redeem,
            "payment_card": PAYMENT_CARD_NUMBER,
            "payment_recipient": PAYMENT_RECIPIENT_NAME,
        })

    # Cash flow: create the order now, notify sellers.
    try:
        order_id, low_stock = await create_order(
            user_id=user_id,
            customer_name=customer_name,
            phone=phone,
            address=address,
            items=items_data,
            total=total,
            payment_method=payment_method,
            latitude=latitude,
            longitude=longitude,
            delivery_method=delivery_method,
            address_note=address_note,
            keto_redeem=keto_redeem,
        )
    except InsufficientStockError as exc:
        return _json(
            {"error": "stock_gone", "product_id": exc.product_id, "available": exc.available},
            status=409,
        )
    except InsufficientKetoError:
        return _json({"error": "keto_balance_changed"}, status=409)

    if low_stock:
        from handlers.cart import notify_low_stock
        await notify_low_stock(bot, low_stock)

    from handlers.cart import _notify_sellers
    await _notify_sellers(bot, order_id, items_data, {
        "customer_name": customer_name,
        "phone": phone,
        "secondary_phone": None,  # Mini App doesn't collect a backup number yet
        "address": address,
        "address_note": address_note,
        "total": total,
        "latitude": float(latitude) if latitude else None,
        "longitude": float(longitude) if longitude else None,
        "user_id": user_id,
        "username": customer_username,
        "delivery_method": delivery_method,
        "payment_method": payment_method,
    }, lang)

    return _json({"ok": True, "order_id": order_id, "total": total, "keto_redeemed": keto_redeem})


async def api_orders(request: web.Request):
    """Return the buyer's recent orders with full details for the Mini App
    "My Orders" page (status, lifecycle timestamps, items, delivery + payment)."""
    user_id = request["user_id"]
    lang = request.get("user_lang", "uz")
    rows = await get_user_orders(user_id)

    result = []
    for o in rows:
        items_raw = o.get("items")
        items = json.loads(items_raw) if isinstance(items_raw, str) else (items_raw or [])
        result.append({
            "id": o["id"],
            "status": o["status"],
            "total": o["total"],
            "created_at": o["created_at"].isoformat() if o.get("created_at") else None,
            "confirmed_at": o["confirmed_at"].isoformat() if o.get("confirmed_at") else None,
            "shipped_at": o["shipped_at"].isoformat() if o.get("shipped_at") else None,
            "delivered_at": o["delivered_at"].isoformat() if o.get("delivered_at") else None,
            "delivery_method": o.get("delivery_method"),
            "payment_method": o.get("payment_method"),
            "address": o.get("address"),
            "items": [
                {
                    "name": it.get("name"),
                    "quantity": it.get("quantity"),
                    "unit": get_display_unit(it.get("unit", ""), lang),
                    "price": it.get("price"),
                }
                for it in items
            ],
        })
    return _json(result)


async def api_order_cancel(request: web.Request):
    """Buyer-initiated cancel from the Mini App (parity with bot My Orders → ❌).

    Validates ownership + cancellable state, runs the atomic cancel_order
    helper (which restores stock in one tx), and notifies admins in parallel.
    """
    user_id = request["user_id"]
    try:
        order_id = int(request.match_info["id"])
    except (KeyError, ValueError):
        return _json({"error": "bad_request"}, status=400)

    order = await get_order(order_id)
    if not order or order["user_id"] != user_id:
        return _json({"error": "not_found"}, status=404)
    if order["status"] not in ("pending", "confirmed"):
        return _json({"error": "cannot_cancel"}, status=409)

    cancelled = await cancel_order(order_id)
    if cancelled is None:
        return _json({"error": "not_found"}, status=404)

    # Notify admins in parallel (same pattern as the bot path)
    bot: Bot = request.app["bot"]
    customer_name = order.get("customer_name") or "—"
    phone = order.get("phone") or "—"

    async def _notify(admin_id: int) -> None:
        admin_lang = await get_user_language(admin_id)
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=get_text("buyer_cancelled_by_user_admin", admin_lang,
                              order_id=order_id, name=customer_name, phone=phone),
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.warning("Buyer-cancel notice (Mini App) to admin %s failed: %s",
                           admin_id, exc)

    import asyncio
    await asyncio.gather(*(_notify(aid) for aid in ADMIN_IDS), return_exceptions=True)

    return _json({"ok": True, "order_id": order_id})


async def _read_cheque_upload(request: web.Request) -> tuple[bytes, str, str] | dict:
    """Pull the multipart 'file' field off the request and read it into
    memory with a 10 MB cap. Returns (bytes, content_type, filename) on
    success, or a dict {"error": ..., "status": int} ready to hand to _json
    on failure. Caps mirror Telegram's photo limit so we reject early
    instead of streaming megabytes only to bounce."""
    MAX_BYTES = 10 * 1024 * 1024
    reader = await request.multipart()
    file_field = None
    while True:
        part = await reader.next()
        if part is None:
            break
        if part.name == "file":
            file_field = part
            break
    if file_field is None:
        return {"error": "no_file", "status": 400}

    content_type = (file_field.headers.get("Content-Type") or "").lower()
    filename = file_field.filename or ("cheque.jpg" if content_type.startswith("image/") else "cheque.bin")

    buf = bytearray()
    while True:
        chunk = await file_field.read_chunk(64 * 1024)
        if not chunk:
            break
        buf.extend(chunk)
        if len(buf) > MAX_BYTES:
            return {"error": "file_too_large", "status": 413}
    if not buf:
        return {"error": "empty_file", "status": 400}
    return bytes(buf), content_type, filename


async def api_checkout_cheque(request: web.Request):
    """Upload payment cheque for a deferred online checkout.

    The order does NOT exist yet when this is called — /api/checkout for
    online stashes the order details in FSM state instead of inserting a
    row. This endpoint reads that stashed data, calls create_order (which
    reserves stock atomically), attaches the cheque, fans the notifications
    out, and clears the FSM state.

    If stock has run out between the checkout submission and the cheque
    upload, the order is never created — the FSM is preserved so the buyer
    can adjust their cart and retry."""
    user_id = request["user_id"]
    lang = request.get("user_lang", "uz")

    storage = request.app.get("storage")
    if storage is None:
        return _json({"error": "server_misconfigured"}, status=500)

    bot: Bot = request.app["bot"]

    from aiogram.fsm.context import FSMContext
    from aiogram.fsm.storage.base import StorageKey
    from handlers.cart import CheckoutStates

    key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
    state = FSMContext(storage=storage, key=key)
    data = await state.get_data()
    items_data = data.get("pending_items")
    if not items_data:
        # No deferred checkout pending — either the buyer never started one,
        # or the state expired. The Mini App should re-route them to the
        # checkout page so they start over.
        return _json({"error": "no_pending_checkout"}, status=409)

    upload = await _read_cheque_upload(request)
    if isinstance(upload, dict):
        return _json({"error": upload["error"]}, status=upload["status"])
    file_bytes, content_type, filename = upload
    is_image = content_type.startswith("image/")

    # Re-clamp the pledged Keto redemption against the *current* balance —
    # time may have passed between checkout submission and the cheque
    # actually arriving. Any shortfall is added back to the charged total
    # rather than silently handed out as an extra discount.
    total = data["pending_total"]
    keto_redeem = int(data.get("pending_keto_redeem") or 0)
    if keto_redeem > 0:
        buyer = await get_user(user_id)
        balance = int(buyer["keto_balance"]) if buyer else 0
        actual_redeem = min(keto_redeem, balance)
        if actual_redeem < keto_redeem:
            total += (keto_redeem - actual_redeem)
        keto_redeem = actual_redeem

    # Reserve stock + create order. If this fails the buyer keeps their FSM
    # so they can try again with a smaller cart — no cheque uploaded yet.
    try:
        order_id, low_stock = await create_order(
            user_id=user_id,
            customer_name=data.get("pending_customer_name") or "—",
            phone=data["pending_phone"],
            address=data["pending_address"],
            items=items_data,
            total=total,
            payment_method="online",
            latitude=data.get("pending_latitude"),
            longitude=data.get("pending_longitude"),
            delivery_method=data.get("pending_delivery_method"),
            address_note=data.get("pending_address_note"),
            secondary_phone=data.get("pending_secondary_phone"),
            keto_redeem=keto_redeem,
        )
    except InsufficientStockError as exc:
        return _json(
            {"error": "stock_gone", "product_id": exc.product_id, "available": exc.available},
            status=409,
        )
    except InsufficientKetoError:
        # Balance dropped again in the instant between the re-clamp above and
        # the transaction (vanishingly rare) — retry once with no redemption
        # rather than leave the buyer's paid-for order un-created.
        total += keto_redeem
        keto_redeem = 0
        try:
            order_id, low_stock = await create_order(
                user_id=user_id,
                customer_name=data.get("pending_customer_name") or "—",
                phone=data["pending_phone"],
                address=data["pending_address"],
                items=items_data,
                total=total,
                payment_method="online",
                latitude=data.get("pending_latitude"),
                longitude=data.get("pending_longitude"),
                delivery_method=data.get("pending_delivery_method"),
                address_note=data.get("pending_address_note"),
                secondary_phone=data.get("pending_secondary_phone"),
                keto_redeem=0,
            )
        except InsufficientStockError as exc:
            return _json(
                {"error": "stock_gone", "product_id": exc.product_id, "available": exc.available},
                status=409,
            )

    # Echo cheque back to buyer's chat to get a reusable Telegram file_id
    # (and so they have a copy in their history).
    from aiogram.types import BufferedInputFile
    input_file = BufferedInputFile(file_bytes, filename=filename)
    try:
        if is_image:
            sent = await bot.send_photo(
                chat_id=user_id,
                photo=input_file,
                caption=get_text("cheque_received", lang, order_id=order_id),
                parse_mode="HTML",
            )
            file_id = sent.photo[-1].file_id
            kind = "photo"
        else:
            sent = await bot.send_document(
                chat_id=user_id,
                document=input_file,
                caption=get_text("cheque_received", lang, order_id=order_id),
                parse_mode="HTML",
            )
            file_id = sent.document.file_id
            kind = "document"
    except Exception:
        logger.exception("Cheque echo to buyer %s failed (order %s already created)", user_id, order_id)
        return _json({"error": "telegram_upload_failed"}, status=502)

    from handlers.cart import _forward_cheque_to_admins, _notify_sellers, notify_low_stock
    from database import set_order_cheque

    await set_order_cheque(order_id, file_id, kind)

    if low_stock:
        await notify_low_stock(bot, low_stock)

    customer_name = data.get("pending_customer_name") or "—"
    await _forward_cheque_to_admins(bot, order_id, customer_name, kind, file_id)
    await _notify_sellers(bot, order_id, items_data, {
        "customer_name": customer_name,
        "phone": data["pending_phone"],
        "secondary_phone": data.get("pending_secondary_phone"),
        "address": data["pending_address"],
        "address_note": data.get("pending_address_note"),
        "total": total,
        "latitude": data.get("pending_latitude"),
        "longitude": data.get("pending_longitude"),
        "user_id": user_id,
        "username": None,
        "delivery_method": data.get("pending_delivery_method"),
        "payment_method": "online",
    }, lang)

    await state.clear()
    return _json({"ok": True, "order_id": order_id, "total": total, "keto_redeemed": keto_redeem})


async def api_order_cheque(request: web.Request):
    """Accept a payment-cheque upload from the Mini App for an online-paid
    order. Mirrors the bot's CheckoutStates.waiting_cheque flow:

    - Validates ownership + that the order is the right kind/status to accept a cheque
    - Sends the file to the buyer's bot chat to give them a record + grab a Telegram file_id
    - Forwards the cheque to admins via _forward_cheque_to_admins
    - Notifies sellers (deferred until cheque arrives, same as the bot path)
    - Clears the FSM "waiting_cheque" state so a follow-up bot photo doesn't double-fire
    """
    user_id = request["user_id"]
    lang = request.get("user_lang", "uz")
    try:
        order_id = int(request.match_info["id"])
    except (KeyError, ValueError):
        return _json({"error": "bad_request"}, status=400)

    order = await get_order(order_id)
    if not order or order["user_id"] != user_id:
        return _json({"error": "not_found"}, status=404)
    if order.get("payment_method") != "online":
        return _json({"error": "not_online_payment"}, status=409)
    if order["status"] not in ("pending", "confirmed"):
        return _json({"error": "wrong_status"}, status=409)

    upload = await _read_cheque_upload(request)
    if isinstance(upload, dict):
        return _json({"error": upload["error"]}, status=upload["status"])
    file_bytes, content_type, filename = upload
    is_image = content_type.startswith("image/")

    bot: Bot = request.app["bot"]

    # Telegram needs an InputFile wrapper for raw uploads. Sending to the buyer
    # first echoes the cheque back into their bot chat (so they have a record)
    # AND gives us a reusable file_id we can hand to every admin without
    # re-uploading bytes N times.
    from aiogram.types import BufferedInputFile
    input_file = BufferedInputFile(file_bytes, filename=filename)
    try:
        if is_image:
            sent = await bot.send_photo(
                chat_id=user_id,
                photo=input_file,
                caption=get_text("cheque_received", lang, order_id=order_id),
                parse_mode="HTML",
            )
            file_id = sent.photo[-1].file_id
            kind = "photo"
        else:
            sent = await bot.send_document(
                chat_id=user_id,
                document=input_file,
                caption=get_text("cheque_received", lang, order_id=order_id),
                parse_mode="HTML",
            )
            file_id = sent.document.file_id
            kind = "document"
    except Exception:
        logger.exception("Cheque upload echo to buyer %s failed", user_id)
        return _json({"error": "telegram_upload_failed"}, status=502)

    customer_name = order.get("customer_name") or "—"

    from handlers.cart import _forward_cheque_to_admins, _notify_sellers
    from database import set_order_cheque
    await set_order_cheque(order_id, file_id, kind)
    await _forward_cheque_to_admins(bot, order_id, customer_name, kind, file_id)

    items_raw = order.get("items")
    items = json.loads(items_raw) if isinstance(items_raw, str) else (items_raw or [])
    await _notify_sellers(bot, order_id, items, {
        "customer_name": customer_name,
        "phone": order.get("phone", ""),
        "secondary_phone": order.get("secondary_phone"),
        "address": order.get("address", ""),
        "address_note": order.get("address_note"),
        "total": order["total"],
        "latitude": order.get("latitude"),
        "longitude": order.get("longitude"),
        "user_id": user_id,
        "username": None,
        "delivery_method": order.get("delivery_method"),
        "payment_method": "online",
    }, lang)

    # Clear the FSM state — bot's photo handler watches for waiting_cheque
    # and would otherwise re-process if the buyer also sends a photo from
    # the bot chat after Mini App submission.
    storage = request.app.get("storage")
    if storage is not None:
        try:
            from aiogram.fsm.context import FSMContext
            from aiogram.fsm.storage.base import StorageKey

            key = StorageKey(bot_id=bot.id, chat_id=user_id, user_id=user_id)
            state = FSMContext(storage=storage, key=key)
            await state.clear()
        except Exception:
            logger.exception("Failed to clear waiting_cheque state for user %s", user_id)

    return _json({"ok": True, "order_id": order_id})


async def api_geocode(request: web.Request):
    """Reverse-geocode lat/lng to a human-readable address. Used by the
    Mini App's map picker so the buyer sees what address the pin is on
    while they're choosing it."""
    try:
        lat = float(request.query.get("lat", ""))
        lng = float(request.query.get("lng", ""))
    except ValueError:
        return _json({"error": "bad_coords"}, status=400)

    from handlers.cart import get_location_address_text
    try:
        address = await get_location_address_text(lat, lng)
    except Exception:
        logger.exception("Reverse geocode failed for %s,%s", lat, lng)
        address = None
    return _json({"address": address or ""})


async def api_get_lang(request: web.Request):
    """Return user's saved language preference."""
    lang = request.get("user_lang", "uz")
    return _json({"lang": lang})


async def api_keto_status(request: web.Request):
    """Whether Keto-as-discount is currently switched on (owner's admin-panel
    toggle, off by default) + this buyer's spendable balance — the checkout
    page uses this to decide whether to show the redemption option at all."""
    user_id = request["user_id"]
    enabled = await gamification.is_redemption_enabled()
    balance = 0
    if enabled:
        buyer = await get_user(user_id)
        balance = int(buyer["keto_balance"]) if buyer else 0
    return _json({"enabled": enabled, "balance": balance})


async def api_set_lang(request: web.Request):
    """Update user's language preference."""
    user_id = request["user_id"]
    body = await request.json()
    new_lang = body.get("lang", "uz")
    if new_lang not in ("uz", "uz_cyr", "ru"):
        new_lang = "uz"
    await update_user_language(user_id, new_lang)
    return _json({"ok": True, "lang": new_lang})


async def api_photo(request: web.Request):
    """Proxy Telegram file bytes (cached path for 30 min)."""
    import aiohttp as _aiohttp

    file_id = request.match_info["file_id"]
    bot: Bot = request.app["bot"]

    # Resolve file path (cached)
    now = time.time()
    url = None
    if file_id in _photo_cache:
        cached_url, ts = _photo_cache[file_id]
        if now - ts < PHOTO_CACHE_TTL:
            url = cached_url

    if not url:
        try:
            file = await bot.get_file(file_id)
            url = f"https://api.telegram.org/file/bot{bot.token}/{file.file_path}"
            _photo_cache[file_id] = (url, now)
        except Exception:
            return web.Response(status=404)

    # Proxy the actual bytes instead of redirecting
    try:
        async with _aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return web.Response(status=404)
                data = await resp.read()
                content_type = resp.content_type or "image/jpeg"
                return web.Response(
                    body=data,
                    content_type=content_type,
                    headers={"Cache-Control": "public, max-age=1800"},
                )
    except Exception:
        return web.Response(status=404)


# ===== HELPERS =====

async def api_promo(request: web.Request):
    """The running aksiya, or {"active": false}.

    Everything the Mini App needs to render the banner, the aksiya sheet and
    the 🎁 badges in one round trip — the badge list is sent as trigger_ids so
    the client can mark cards without a per-product lookup."""
    lang = request.get("user_lang", "uz")
    promo = await promotions.get_active()
    if not promo:
        return _json({"active": False})

    rules = promo.get("bonuses") or []
    return _json({
        "active": True,
        "name": promotions.promo_name(promo, lang),
        "conditions": promotions.promo_conditions(promo, lang),
        "days_left": promotions.days_left(promo),
        "image_url": promo.get("image_url"),
        "bonuses": [promotions.rule_line(r, lang) for r in rules],
        "trigger_ids": sorted({r["trigger_product_id"] for r in rules}),
    })


def _serialize_product(p: dict, lang: str) -> dict:
    # Russian translation when available; Latin → Cyrillic transliteration
    # for "uz_cyr" users; Latin source as-is for everyone else.
    name = localize_product_text(p.get("name"), p.get("name_ru"), lang)
    description = localize_product_text(p.get("description"), p.get("description_ru"), lang)

    discount_until = p.get("discount_until")
    discount = active_discount(p.get("discount_percent"), discount_until)
    final_price = effective_price(p["price"], discount, discount_until)

    # Aksiya bonus this product triggers, if any — read from the shared
    # in-process cache (no query, no await) so it costs nothing on the hot
    # path that serializes 200 products for the home page.
    bonus = promotions.bonus_hint(promotions.cached_active(), p["id"], lang)

    return {
        "id": p["id"],
        "name": name,
        "description": description,
        "price": final_price,
        "original_price": p["price"],
        "discount_percent": discount,
        "discount_until": discount_until.isoformat() if discount and discount_until else None,
        "unit": get_display_unit(p["unit"], lang),
        "packaged": p["unit"] in ("kg", "g"),
        "out_of_stock": (p.get("quantity") or 0) <= 0,
        "category": p["category"],
        "photo_url": f"/api/photo/{p['photo_id']}" if p.get("photo_id") else None,
        "bonus": bonus,
    }


def _serialize_products(products: list[dict], lang: str) -> list[dict]:
    return [_serialize_product(p, lang) for p in products]


# ===== APP FACTORY =====

def create_webapp(bot: Bot, storage=None) -> web.Application:
    """Create and return aiohttp Application."""
    app = web.Application(middlewares=[auth_middleware])
    app["bot"] = bot
    app["bot_token"] = BOT_TOKEN
    app["storage"] = storage

    app.router.add_get("/healthz", healthz)
    app.router.add_get("/", index)
    app.router.add_get("/api/categories", api_categories)
    app.router.add_get("/api/promo", api_promo)
    app.router.add_get("/api/products", api_products)
    app.router.add_get("/api/top", api_top)
    app.router.add_get("/api/leaderboard", api_leaderboard)
    app.router.add_get("/api/product/{id}", api_product_detail)
    app.router.add_get("/api/set/{id}", api_set_detail)
    app.router.add_get("/api/product/{id}/reviews", api_product_reviews)
    app.router.add_post("/api/product/{id}/reviews", api_product_review_submit)
    app.router.add_post("/api/reviews/{id}/delete", api_review_delete)
    app.router.add_get("/api/search", api_search)
    app.router.add_get("/api/cart", api_cart)
    app.router.add_post("/api/cart/add", api_cart_add)
    app.router.add_post("/api/cart/remove", api_cart_remove)
    app.router.add_post("/api/cart/update", api_cart_update)
    app.router.add_post("/api/cart/clear", api_cart_clear)
    app.router.add_post("/api/checkout", api_checkout)
    app.router.add_post("/api/checkout/cheque", api_checkout_cheque)
    app.router.add_get("/api/orders", api_orders)
    app.router.add_post("/api/orders/{id}/cancel", api_order_cancel)
    app.router.add_post("/api/orders/{id}/cheque", api_order_cheque)
    app.router.add_get("/api/geocode", api_geocode)
    app.router.add_get("/api/lang", api_get_lang)
    app.router.add_post("/api/lang", api_set_lang)
    app.router.add_get("/api/keto/status", api_keto_status)
    app.router.add_get("/api/photo/{file_id}", api_photo)

    # Admin website (/admin) + uploaded-image serving (/img/{id}).
    # Its own password auth (see admin_web.py); auth_middleware ignores these
    # paths because they don't start with /api/.
    from admin_web import setup_admin_routes
    setup_admin_routes(app)

    # Serve the webapp/ directory at /static/ so we can self-host vendor
    # assets (Leaflet, etc) instead of relying on a CDN — flaky CDN
    # reachability from Telegram webviews was the difference between the
    # map picker rendering and showing a blank modal.
    app.router.add_static("/static/", path=Path(__file__).parent / "webapp", show_index=False)

    return app
