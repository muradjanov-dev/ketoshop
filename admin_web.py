"""
Admin website — password-protected browser panel at /admin.

Lets shop admins manage products and build "sets" (bundles): several products
grouped under one name, sold at a discounted set price. The UI shows the
combined individual price struck through in red next to the set price.

Auth: a single shared password (ADMIN_WEB_PASSWORD env). On success we set a
signed, HttpOnly session cookie (HMAC over an expiry timestamp, keyed off the
bot token) valid for 7 days. No password stored in the cookie.

Routes (all mounted by setup_admin_routes):
  GET  /admin                     — panel HTML (login form shows if no session)
  POST /admin/api/login           — {password} -> sets session cookie
  POST /admin/api/logout
  GET  /admin/api/session         — {categories: [{key, name_uz, name_ru}, ...]}
  POST /admin/api/categories      — {name_uz, name_ru?} -> create a new product category
  GET  /admin/api/products        — all products (incl. archived)
  POST /admin/api/products        — create
  POST /admin/api/products/{id}   — update (partial)
  POST /admin/api/products/{id}/delete   — archive (is_active = 0)
  GET  /admin/api/sets            — all sets with items + computed totals
  POST /admin/api/sets            — create {name, set_price, items:[{product_id, quantity}], …}
  POST /admin/api/sets/{id}       — update (partial; optional items replace)
  POST /admin/api/sets/{id}/delete
  POST /admin/api/upload          — multipart image -> {url: "/img/N"}
  GET  /img/{id}                  — serve an uploaded image (public, cached)
  GET  /admin/api/promos          — every aksiya (campaign) with its bonus rules
  POST /admin/api/promos          — create {name, days, conditions, image_url, bonuses:[…]}
  POST /admin/api/promos/{id}     — update (partial; bonuses replace when supplied)
  POST /admin/api/promos/{id}/delete
  POST /admin/api/promos/{id}/start    — {days?} -> go live (stops any other running one)
  POST /admin/api/promos/{id}/stop     — end it early
  POST /admin/api/promos/{id}/announce — one-time "yangi aksiya" broadcast to all users
  GET  /admin/api/bloggers        — partner bloggers + their referral/earning stats
  POST /admin/api/bloggers        — create {name, code?, user_id?, percent?, max_orders?}
  GET  /admin/api/bloggers/suggest?name=  — the link code that name would get
  POST /admin/api/bloggers/{id}   — update (partial)
  POST /admin/api/bloggers/{id}/delete
  GET  /admin/api/bloggers/{id}/detail — referred buyers + every order + payout
  GET  /admin/api/keto/status     — redemption on/off + every user's Keto balance
  POST /admin/api/keto/redemption — {enabled} -> toggle Keto-as-discount at checkout
  GET  /admin/api/dashboard       — {period} -> KPI/trend/best-sellers/Keto snapshot for the Dashboard tab,
                                    plus b2b_sales: the wholesale orders behind the B2B KPI tile
  GET  /admin/api/ads             — {period} -> Meta Ads KPIs + per-ad/per-campaign rows + lead counters
  GET  /admin/api/ads/status      — ad-account health (account_status, balance) + per-ad issues_info
  GET  /admin/api/ads/leads       — {limit} -> stored Meta lead-form submissions, newest first
  POST /admin/api/ads/leads/{lead_id}/handled — claim a lead ("Bog'landim"), same as the Telegram button
  GET  /admin/api/courier/board   — Kanban snapshot; {scope} 'all' (default) adds every recent
                                    delivered/cancelled order, 'active' trims to today's deliveries
  POST /admin/api/courier/orders/{id}/move   — {status, from?, notify?} -> guarded status move
  POST /admin/api/courier/orders/{id}/courier — {courier_id|null} -> claim/release a card
  GET  /admin/api/courier/couriers — registered couriers for the card picker
  POST /admin/api/courier/orders/{id}/location — push the buyer's map pin to the admins' Telegram

Images are stored in Postgres (web_images) because Railway's filesystem is
ephemeral — see database.py.
"""
import asyncio
import functools
import hashlib
import hmac
import json
import logging
import time
from pathlib import Path

import aiohttp
from aiohttp import web

import courier_board
import database
from config import ADMIN_WEB_PASSWORD, BOT_TOKEN, ADMIN_IDS, BOT_USERNAME
from locales import CATEGORIES, get_item_unit
# Same tolerant JSON encoder the Mini App uses: aiohttp's default dumps cannot
# serialize the date / datetime / Decimal values asyncpg hands back, and every
# endpoint here that forgot to convert one 500s at render time with nothing to
# show the admin. `/admin/api/promos` was doing exactly that from the moment
# promotions.last_showcase_date (a DATE) was added — the whole Aksiya tab was
# dead. Handing web.json_response this encoder fixes the class of bug rather
# than the one instance.
from webapp_server import _json_default

logger = logging.getLogger(__name__)

_safe_dumps = functools.partial(json.dumps, default=_json_default)


def _json(data, **kwargs):
    """web.json_response that survives whatever asyncpg returns.

    setdefault, not a plain keyword: a couple of handlers used to pass their
    own `dumps=` before this helper existed, and hard-coding it here made
    json_response receive the argument twice — a 500 on exactly the endpoints
    that had been careful enough to handle their own serialisation.
    """
    kwargs.setdefault("dumps", _safe_dumps)
    return web.json_response(data, **kwargs)


SESSION_COOKIE = "safran_admin"
SESSION_TTL = 7 * 24 * 3600          # 7 days
MAX_UPLOAD_BYTES = 5 * 1024 * 1024   # 5 MB per image
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}

# Owner of products created through the website. Any admin id works — products
# are shared in this marketplace (admins are the sellers).
WEB_SELLER_ID = sorted(ADMIN_IDS)[0] if ADMIN_IDS else 0


# ─────────────────────────── session handling ───────────────────────────────

def _session_key() -> bytes:
    # Derive a stable signing key from the bot token (never sent to clients).
    return hashlib.sha256(f"admin-session|{BOT_TOKEN}".encode()).digest()


def _make_session() -> str:
    expires = int(time.time()) + SESSION_TTL
    sig = hmac.new(_session_key(), str(expires).encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{sig}"


def _check_session(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    expires_str, _, sig = token.partition(".")
    if not expires_str.isdigit():
        return False
    expected = hmac.new(_session_key(), expires_str.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return False
    return int(expires_str) > time.time()


def _authed(request: web.Request) -> bool:
    return _check_session(request.cookies.get(SESSION_COOKIE))


def require_auth(handler):
    async def wrapped(request: web.Request):
        if not ADMIN_WEB_PASSWORD:
            return _json({"error": "admin panel disabled: ADMIN_WEB_PASSWORD not set"}, status=503)
        if not _authed(request):
            return _json({"error": "unauthorized"}, status=401)
        return await handler(request)
    return wrapped


# ─────────────────────────────── pages ──────────────────────────────────────

async def admin_page(request: web.Request):
    html_path = Path(__file__).parent / "webapp" / "admin.html"
    html = html_path.read_text(encoding="utf-8")
    return web.Response(
        text=html, content_type="text/html",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


async def api_login(request: web.Request):
    if not ADMIN_WEB_PASSWORD:
        return _json({"error": "ADMIN_WEB_PASSWORD is not configured on the server"}, status=503)
    try:
        body = await request.json()
    except Exception:
        return _json({"error": "bad request"}, status=400)
    password = str(body.get("password", ""))
    # Constant-time compare + a small delay to blunt brute-forcing.
    ok = hmac.compare_digest(password.encode(), ADMIN_WEB_PASSWORD.encode())
    if not ok:
        import asyncio
        await asyncio.sleep(1.0)
        return _json({"error": "wrong password"}, status=403)
    resp = web.json_response({"ok": True})
    resp.set_cookie(
        SESSION_COOKIE, _make_session(),
        max_age=SESSION_TTL, httponly=True, samesite="Strict",
        secure=request.headers.get("X-Forwarded-Proto", request.scheme) == "https",
        path="/",
    )
    return resp


async def api_logout(request: web.Request):
    resp = web.json_response({"ok": True})
    resp.del_cookie(SESSION_COOKIE, path="/")
    return resp


@require_auth
async def api_session(request: web.Request):
    categories = await database.get_categories()
    for c in categories:
        if c.get("created_at"):
            c["created_at"] = c["created_at"].isoformat()
    # bot_username lets the Blogerlar tab preview a partner link
    # (t.me/<bot>?start=<name>) as the admin types, without hardcoding the
    # bot's name into the page.
    return _json({"ok": True, "categories": categories,
                              "bot_username": BOT_USERNAME})


@require_auth
async def api_categories_create(request: web.Request):
    """Admin-added category (2026-07-30) — used to be a fixed list. Slugs a
    `key` from name_uz automatically; see database.create_category."""
    try:
        b = await request.json()
        name_uz = _clean_str(b.get("name_uz"), 200)
        if not name_uz:
            raise ValueError
    except Exception:
        return _json({"error": "name_uz is required"}, status=400)

    cat = await database.create_category(name_uz=name_uz, name_ru=_clean_str(b.get("name_ru"), 200))
    if cat.get("created_at"):
        cat["created_at"] = cat["created_at"].isoformat()
    return _json({"ok": True, "category": cat})


# ────────────────────────────── products ────────────────────────────────────

@require_auth
async def api_products_list(request: web.Request):
    products = await database.admin_list_products(include_inactive=True)
    for p in products:
        # datetime → isoformat for JSON
        if p.get("created_at"):
            p["created_at"] = p["created_at"].isoformat()
        if p.get("discount_until"):
            p["discount_until"] = p["discount_until"].isoformat()
    return _json({"products": products})


def _clean_str(v, max_len=500) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s[:max_len] if s else None


@require_auth
async def api_products_create(request: web.Request):
    try:
        b = await request.json()
        name = _clean_str(b.get("name"), 200)
        price = float(b.get("price"))
        category = str(b.get("category"))
        if not name or price < 0 or category not in CATEGORIES:
            raise ValueError
    except Exception:
        return _json({"error": "name, price, category are required"}, status=400)

    await database.ensure_user_exists(WEB_SELLER_ID, "Ketoshop Admin")
    pid = await database.admin_create_product(
        seller_id=WEB_SELLER_ID,
        name=name,
        price=price,
        category=category,
        unit=_clean_str(b.get("unit"), 20) or "kg",
        quantity=float(b.get("quantity") or 0),
        description=_clean_str(b.get("description"), 2000),
        name_ru=_clean_str(b.get("name_ru"), 200),
        description_ru=_clean_str(b.get("description_ru"), 2000),
        cost_price=float(b.get("cost_price") or 0),
        b2b_price=float(b.get("b2b_price") or 0),
        discount_percent=int(b.get("discount_percent") or 0),
        image_url=_clean_str(b.get("image_url"), 300),
    )
    return _json({"ok": True, "id": pid})


@require_auth
async def api_products_update(request: web.Request):
    pid = int(request.match_info["id"])
    if not await database.get_product(pid):
        return _json({"error": "not found"}, status=404)
    try:
        b = await request.json()
    except Exception:
        return _json({"error": "bad request"}, status=400)

    fields = {}
    if "name" in b:             fields["name"] = _clean_str(b["name"], 200)
    if "name_ru" in b:          fields["name_ru"] = _clean_str(b["name_ru"], 200)
    if "description" in b:      fields["description"] = _clean_str(b["description"], 2000)
    if "description_ru" in b:   fields["description_ru"] = _clean_str(b["description_ru"], 2000)
    if "price" in b:            fields["price"] = float(b["price"])
    if "cost_price" in b:       fields["cost_price"] = float(b["cost_price"] or 0)
    # Wholesale price per kg. Admin-only, like cost_price — the buyer
    # serializers never read it.
    if "b2b_price" in b:        fields["b2b_price"] = float(b["b2b_price"] or 0)
    if "quantity" in b:         fields["quantity"] = float(b["quantity"] or 0)
    if "unit" in b:             fields["unit"] = _clean_str(b["unit"], 20) or "kg"
    if "discount_percent" in b: fields["discount_percent"] = int(b["discount_percent"] or 0)
    if "image_url" in b:        fields["image_url"] = _clean_str(b["image_url"], 300)
    if "is_active" in b:        fields["is_active"] = 1 if b["is_active"] else 0
    if "category" in b:
        if b["category"] not in CATEGORIES:
            return _json({"error": "bad category"}, status=400)
        fields["category"] = b["category"]
    if not fields:
        return _json({"error": "nothing to update"}, status=400)

    await database.update_product(pid, **fields)
    return _json({"ok": True})


@require_auth
async def api_products_delete(request: web.Request):
    pid = int(request.match_info["id"])
    await database.delete_product(pid)  # soft delete: is_active = 0
    return _json({"ok": True})


# ──────────────────────────────── sets ──────────────────────────────────────

def _parse_set_items(raw) -> list[dict]:
    """Validate items payload: non-empty list of {product_id, quantity>0}."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("items must be a non-empty list")
    items = []
    for it in raw:
        pid = int(it["product_id"])
        qty = float(it.get("quantity", 1))
        if qty <= 0:
            raise ValueError("quantity must be positive")
        items.append({"product_id": pid, "quantity": qty})
    return items


@require_auth
async def api_sets_list(request: web.Request):
    sets = await database.get_sets(active_only=False)
    for s in sets:
        if s.get("created_at"):
            s["created_at"] = s["created_at"].isoformat()
    return _json({"sets": sets})


@require_auth
async def api_sets_create(request: web.Request):
    try:
        b = await request.json()
        name = _clean_str(b.get("name"), 200)
        set_price = float(b.get("set_price"))
        items = _parse_set_items(b.get("items"))
        if not name or set_price < 0:
            raise ValueError
    except Exception as e:
        return _json({"error": f"invalid payload: {e}"}, status=400)

    # Every member product must exist and be active.
    for it in items:
        p = await database.get_product(it["product_id"])
        if not p or not p["is_active"]:
            return _json({"error": f"product {it['product_id']} not found or archived"}, status=400)

    sid = await database.create_set(
        name=name, set_price=set_price, items=items,
        name_ru=_clean_str(b.get("name_ru"), 200),
        description=_clean_str(b.get("description"), 2000),
        description_ru=_clean_str(b.get("description_ru"), 2000),
        image_url=_clean_str(b.get("image_url"), 300),
    )
    return _json({"ok": True, "id": sid})


@require_auth
async def api_sets_update(request: web.Request):
    sid = int(request.match_info["id"])
    if not await database.get_set(sid):
        return _json({"error": "not found"}, status=404)
    try:
        b = await request.json()
    except Exception:
        return _json({"error": "bad request"}, status=400)

    fields = {}
    if "name" in b:           fields["name"] = _clean_str(b["name"], 200)
    if "name_ru" in b:        fields["name_ru"] = _clean_str(b["name_ru"], 200)
    if "description" in b:    fields["description"] = _clean_str(b["description"], 2000)
    if "description_ru" in b: fields["description_ru"] = _clean_str(b["description_ru"], 2000)
    if "set_price" in b:      fields["set_price"] = float(b["set_price"])
    if "image_url" in b:      fields["image_url"] = _clean_str(b["image_url"], 300)
    if "is_active" in b:      fields["is_active"] = 1 if b["is_active"] else 0

    items = None
    if "items" in b:
        try:
            items = _parse_set_items(b["items"])
        except Exception as e:
            return _json({"error": f"invalid items: {e}"}, status=400)

    await database.update_set(sid, items=items, **fields)
    return _json({"ok": True})


@require_auth
async def api_sets_delete(request: web.Request):
    sid = int(request.match_info["id"])
    await database.delete_set(sid)
    return _json({"ok": True})


# ────────────────────── personal recommendations control ────────────────────

@require_auth
async def api_reco_on(request: web.Request):
    await database.set_reco_enabled(True)
    return _json({"ok": True, "enabled": True})


@require_auth
async def api_reco_send_now(request: web.Request):
    """Send the personalized batch to every buyer immediately (manual trigger,
    bypasses the schedule and the tips-day slip). Runs in the background —
    a full batch takes minutes and would time out the HTTP request."""
    import personal_recommend

    bot = request.app["bot"]
    state = await database.get_reco_state()
    buyers = await database.get_user_ids_with_orders()

    async def run():
        try:
            sent, failed = await personal_recommend.send_personal_batch(bot)
            await database.advance_reco()
            await personal_recommend._notify_admins(
                bot,
                f"🎁 Shaxsiy tavsiyalar yuborildi (admin panel orqali).\n"
                f"✅ {sent} ta yetkazildi, ⚠️ {failed} ta yetmadi.",
            )
        except Exception:
            logger.exception("Manual reco batch failed")

    import asyncio
    asyncio.create_task(run())
    return _json({"ok": True, "started": True,
                              "buyers": len(buyers), "cycle": state.get("cycle", 0)})


@require_auth
async def api_reco_backfill(request: web.Request):
    """Recompute and record message fingerprints for a past cycle. One-time
    maintenance: the dedupe table was added after the first batch went out, so
    that batch's messages need registering to guarantee they never repeat."""
    import hashlib
    import personal_recommend

    try:
        body = await request.json()
        cycle = int(body.get("cycle", 0))
    except Exception:
        return _json({"error": "bad request"}, status=400)

    marked = 0
    for uid in await database.get_user_ids_with_orders():
        orders = await database.get_user_orders(uid)
        lang = await database.get_user_language(uid)
        text = personal_recommend.build_personal_message(lang, orders, cycle)
        if text:
            h = hashlib.sha256(text.encode()).hexdigest()
            await database.mark_reco_sent(uid, h)
            marked += 1
    return _json({"ok": True, "cycle": cycle, "marked": marked})


# ─────────────────────────── Aksiya / Bonus ─────────────────────────────────
# The owner writes a campaign here (name, kun, shartlar + bonus rules) and
# presses Boshlash to put it live. See promotions.py for how the rules turn
# into free order lines at checkout.


def _promo_json(promo: dict) -> dict:
    """Datetime columns -> ISO strings so the panel's JS can format them."""
    out = dict(promo)
    for key in ("started_at", "ends_at", "announced_at", "created_at"):
        if out.get(key):
            out[key] = out[key].isoformat()
    for bonus in out.get("bonuses") or []:
        if bonus.get("created_at"):
            bonus["created_at"] = bonus["created_at"].isoformat()
    return out


async def _parse_bonus_rules(raw) -> list[dict]:
    """Validate the submitted rule rows and pre-compute each one's stock
    quantity. The admin types a human amount ("100 gr"); products.quantity is
    kept in the bonus product's own unit ("0.1" when it is stocked in kg), so
    the conversion happens once here rather than at every checkout.

    Raises ValueError with a Uzbek message the panel shows verbatim."""
    import promotions

    if not isinstance(raw, list):
        raise ValueError("bonuslar ro'yxati noto'g'ri")
    rules = []
    for row in raw:
        try:
            trigger_id = int(row["trigger_product_id"])
            bonus_id = int(row["bonus_product_id"])
            trigger_qty = float(row.get("trigger_quantity") or 1)
            bonus_amount = float(row.get("bonus_amount") or 0)
        except (KeyError, TypeError, ValueError):
            raise ValueError("bonus qatorida mahsulot yoki miqdor to'ldirilmagan")
        if trigger_qty <= 0 or bonus_amount <= 0:
            raise ValueError("miqdorlar 0 dan katta bo'lishi kerak")

        bonus_product = await database.get_product(bonus_id)
        trigger_product = await database.get_product(trigger_id)
        if not bonus_product or not trigger_product:
            raise ValueError("tanlangan mahsulot topilmadi")

        bonus_unit = (_clean_str(row.get("bonus_unit"), 20) or "dona").lower()
        max_amount = row.get("max_bonus_amount")
        try:
            max_amount = float(max_amount) if max_amount not in (None, "", 0) else None
        except (TypeError, ValueError):
            max_amount = None

        rules.append({
            "trigger_product_id": trigger_id,
            "trigger_quantity": trigger_qty,
            "bonus_product_id": bonus_id,
            "bonus_amount": bonus_amount,
            "bonus_unit": bonus_unit,
            "bonus_stock_qty": promotions.to_stock_qty(bonus_amount, bonus_unit, bonus_product.get("unit") or "kg"),
            "max_bonus_amount": max_amount,
        })
    return rules


@require_auth
async def api_promos_list(request: web.Request):
    promos = await database.list_promotions()
    return _json({"promos": [_promo_json(p) for p in promos]})


@require_auth
async def api_promos_create(request: web.Request):
    b = await request.json()
    name = _clean_str(b.get("name"), 200)
    if not name:
        return _json({"error": "aksiya nomi kiritilmagan"}, status=400)
    # `or 7` would swallow an explicit 0 and silently run the campaign for a
    # week the admin never asked for — only an ABSENT/blank days field falls
    # back to the default; a supplied one has to be valid.
    raw_days = b.get("days")
    try:
        days = 7 if raw_days in (None, "") else int(raw_days)
        if days <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return _json({"error": "kunlar soni musbat butun son bo'lishi kerak"}, status=400)

    try:
        rules = await _parse_bonus_rules(b.get("bonuses") or [])
    except ValueError as exc:
        return _json({"error": str(exc)}, status=400)

    promo_id = await database.create_promotion(
        name=name,
        name_ru=_clean_str(b.get("name_ru"), 200),
        conditions=_clean_str(b.get("conditions"), 2000),
        conditions_ru=_clean_str(b.get("conditions_ru"), 2000),
        days=days,
        image_url=_clean_str(b.get("image_url"), 300),
    )
    await database.set_promotion_bonuses(promo_id, rules)
    return _json({"ok": True, "id": promo_id})


@require_auth
async def api_promos_update(request: web.Request):
    promo_id = int(request.match_info["id"])
    b = await request.json()

    fields = {}
    if "name" in b:
        name = _clean_str(b.get("name"), 200)
        if not name:
            return _json({"error": "aksiya nomi kiritilmagan"}, status=400)
        fields["name"] = name
    for key, limit in (("name_ru", 200), ("conditions", 2000), ("conditions_ru", 2000), ("image_url", 300)):
        if key in b:
            fields[key] = _clean_str(b.get(key), limit)
    if "days" in b:
        try:
            days = int(b.get("days") or 0)
            if days <= 0:
                raise ValueError
            fields["days"] = days
        except (TypeError, ValueError):
            return _json({"error": "kunlar soni musbat butun son bo'lishi kerak"}, status=400)

    if fields:
        await database.update_promotion(promo_id, **fields)
    if "bonuses" in b:
        try:
            rules = await _parse_bonus_rules(b.get("bonuses") or [])
        except ValueError as exc:
            return _json({"error": str(exc)}, status=400)
        await database.set_promotion_bonuses(promo_id, rules)

    import promotions
    await promotions.refresh()   # an edit to the running campaign shows up at once
    return _json({"ok": True})


@require_auth
async def api_promos_delete(request: web.Request):
    import promotions
    await database.delete_promotion(int(request.match_info["id"]))
    await promotions.refresh()
    return _json({"ok": True})


@require_auth
async def api_promos_start(request: web.Request):
    import promotions

    promo_id = int(request.match_info["id"])
    body = await request.json() if request.can_read_body else {}
    days = body.get("days")
    if days is not None:
        try:
            days = int(days)
            if days <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return _json({"error": "kunlar soni musbat butun son bo'lishi kerak"}, status=400)

    promo = await database.start_promotion(promo_id, days)
    if promo is None:
        return _json({"error": "aksiya topilmadi"}, status=404)
    await promotions.refresh()
    return _json({"ok": True, "promo": _promo_json(promo)})


@require_auth
async def api_promos_stop(request: web.Request):
    import promotions
    await database.stop_promotion(int(request.match_info["id"]))
    await promotions.refresh()
    return _json({"ok": True})


@require_auth
async def api_promos_announce(request: web.Request):
    """Fire the one-time "yangi aksiya" broadcast. Runs in the background —
    fanning out to every user takes minutes at Telegram's rate limits, far
    longer than an HTTP request should hold open, so this returns straight
    away and the panel re-reads announced_at to see it landed."""
    import promotions

    promo_id = int(request.match_info["id"])
    promo = await database.get_promotion(promo_id)
    if promo is None:
        return _json({"error": "aksiya topilmadi"}, status=404)
    if not promo.get("active"):
        return _json({"error": "avval aksiyani boshlang"}, status=400)

    bot = request.app["bot"]

    async def _run():
        try:
            sent, failed = await promotions.announce(bot, promo)
            logger.info("Aksiya #%s announced: %d ok, %d failed", promo_id, sent, failed)
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"📤 Aksiya e'lon qilindi: <b>{promo.get('name')}</b>\n"
                        f"✅ {sent} ta yetkazildi, ⚠️ {failed} ta yetmadi.",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
        except Exception:
            logger.exception("Aksiya announcement failed")

    asyncio.create_task(_run())
    return _json({"ok": True})


# ───────────────────────────── expenses ──────────────────────────────────────

@require_auth
async def api_expenses_list(request: web.Request):
    expenses = await database.get_expenses(100)
    return _json({"expenses": expenses})

@require_auth
async def api_expenses_add(request: web.Request):
    try:
        b = await request.json()
        name = (b.get("name") or "").strip()
        amount = float(b.get("amount") or 0)
        if not name or amount <= 0:
            raise ValueError
    except Exception:
        return _json({"error": "invalid name or amount"}, status=400)
    
    eid = await database.add_expense(name, amount)
    return _json({"ok": True, "id": eid})


# ───────────────────────────── dashboard ─────────────────────────────────────

def _b2b_sale_json(o: dict) -> dict:
    """One wholesale sale, ready for the browser.

    The date is formatted here, not in JS: orders carry naive UTC timestamps,
    and handing one to the browser unmarked would have it read as local time
    and shift every B2B sale by five hours. Units come from get_item_unit for
    the same reason the bot screen uses it — a wholesale line's quantity is a
    weight, so 0.5 kg must not render as "0.5 dona".
    """
    return {
        "id": o["id"],
        "when": database.format_local_dt(o["dt"], "%d.%m.%Y %H:%M") if o["dt"] else "",
        "customer_name": o["customer_name"],
        "phone": o["phone"],
        "total": o["total"],
        "cost": o["cost"],
        "profit": o["profit"],
        "cost_known": o["cost_known"],
        "items": [{
            "name": it.get("name") or "",
            "quantity": float(it.get("quantity") or 0),
            "unit": get_item_unit(it, "uz"),
        } for it in o["items"]],
    }


@require_auth
async def api_dashboard(request: web.Request):
    """Aggregated snapshot for the visual dashboard tab (2026-08-12): KPIs for
    the selected period, a 6-month revenue/orders trend, best sellers, and a
    Keto-program snapshot. One call so the tab renders without a waterfall."""
    period = request.query.get("period", "30d")
    if period == "custom":
        start_date = request.query.get("start")
        end_date = request.query.get("end")
        period_arg = {"start": start_date, "end": end_date}
    else:
        if period not in ("today", "7d", "30d", "all"):
            period = "30d"
        period_arg = period
        
    stats, monthly, top_products, keto, abc_analysis, b2b = await asyncio.gather(
        database.get_admin_stats(period_arg),
        database.get_monthly_breakdown(5),
        database.get_top_products(period_arg, limit=5),
        database.get_keto_program_stats(),
        database.get_abc_analysis(period_arg),
        database.get_b2b_orders(period_arg),
    )
    return _json({
        "stats": stats,
        "monthly": monthly,
        "top_products": top_products,
        "keto": keto,
        "abc_analysis": abc_analysis,
        "b2b_sales": [_b2b_sale_json(o) for o in b2b],
    })


# ───────────────────── Keto-as-discount at checkout ──────────────────────────

@require_auth
async def api_keto_status(request: web.Request):
    """Redemption on/off + every user with any Keto, highest first — so the
    owner can see who holds what without asking (2026-07-30, built dormant:
    `redemption_enabled` defaults FALSE, see gamification.is_redemption_enabled)."""
    state = await database.get_gamification_state()
    balances = await database.get_keto_balances_list()
    return _json({
        "redemption_enabled": bool(state.get("redemption_enabled")),
        "gamification_enabled": bool(state.get("enabled")),
        "balances": balances,
    })


@require_auth
async def api_keto_redemption_toggle(request: web.Request):
    try:
        b = await request.json()
        enabled = bool(b.get("enabled"))
    except Exception:
        return _json({"error": "bad request"}, status=400)
    await database.set_redemption_enabled(enabled)
    return _json({"ok": True, "enabled": enabled})


# ────────────────────────── Reklama (Meta Ads) ───────────────────────────────
# The same numbers /reklama, /reklama_holat and /leads already answer in
# Telegram, readable in the browser. meta_ads is imported inside the handlers
# on purpose: the panel — and every other tab — must keep working even if the
# Graph integration is missing, misconfigured or down.

ADS_CACHE_TTL = 45          # seconds. Meta's own insights lag minutes anyway,
                            # so this only spares the API the period-switch
                            # clicking; it never shows meaningfully older data.
_ads_cache: dict[str, tuple[float, dict]] = {}


def _ads_cached(key: str):
    hit = _ads_cache.get(key)
    if hit and time.time() - hit[0] < ADS_CACHE_TTL:
        return hit[1]
    return None


def _ads_store(key: str, payload: dict) -> dict:
    _ads_cache[key] = (time.time(), payload)
    return payload


def _f(v):
    """Graph sends every metric as a string; JSON should carry numbers."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _insight_row(meta_ads, row: dict, name_key: str | None = None) -> dict:
    """One insights row -> flat JSON. Lead extraction stays in meta_ads
    (_leads_from knows the three action_type spellings Meta uses) so the
    browser and the bot can never disagree about what counts as a lead."""
    leads, cpl = meta_ads._leads_from(row)
    return {
        "name": (row.get(name_key) or "—") if name_key else None,
        "spend": _f(row.get("spend")) or 0.0,
        "impressions": _f(row.get("impressions")) or 0.0,
        "reach": _f(row.get("reach")),
        "frequency": _f(row.get("frequency")),
        "clicks": _f(row.get("inline_link_clicks")) or _f(row.get("clicks")) or 0.0,
        "ctr": _f(row.get("ctr")),
        "cpm": _f(row.get("cpm")),
        "cpc": _f(row.get("cpc")),
        "leads": leads,
        "cost_per_lead": cpl,
    }


def _by_spend(rows: list) -> list:
    return sorted(rows, key=lambda r: r.get("spend") or 0.0, reverse=True)


def _cents(v):
    """balance / amount_spent / spend_cap arrive in the currency's minor unit."""
    f = _f(v)
    return None if f is None else f / 100


@require_auth
async def api_ads(request: web.Request):
    """KPIs plus per-ad and per-campaign breakdown for the Reklama tab.

    Never raises to the browser: a Graph failure comes back as HTTP 200 with an
    `error` string so the tab renders a red card instead of a blank screen. The
    three insight calls run with return_exceptions=True — a breakdown level the
    token may not read must not blank out the account totals."""
    try:
        import meta_ads
    except Exception:
        logger.exception("meta_ads import failed")
        return _json({"enabled": False})

    period = request.query.get("period", "today")
    if period not in meta_ads.PRESETS:
        period = "today"
    label = meta_ads.PRESETS[period][0]

    if not meta_ads.is_enabled():
        return _json({"enabled": False, "period": period, "label": label})

    # Lead counters come from our own Postgres, so they stay live — only the
    # Graph half of the payload is cached.
    leads = await database.get_meta_leads_summary()

    cached = _ads_cached("ads:" + period)
    if cached is not None:
        return _json({**cached, "leads": leads})

    base = {"enabled": True, "period": period, "label": label}
    try:
        async with aiohttp.ClientSession() as session:
            account_res, ad_res, camp_res = await asyncio.gather(
                meta_ads.fetch_insights(session, period, "account"),
                meta_ads.fetch_insights(session, period, "ad"),
                meta_ads.fetch_insights(session, period, "campaign"),
                return_exceptions=True,
            )
    except Exception:
        logger.exception("Ads insights request failed")
        return _json({**base, "error": "Meta bilan bog'lanib bo'lmadi", "leads": leads})

    if isinstance(account_res, meta_ads.GraphError):
        return _json({**base, "error": str(account_res), "leads": leads})
    if isinstance(account_res, BaseException):
        logger.error("Ads account insights failed", exc_info=account_res)
        return _json({**base, "error": "Meta bilan bog'lanib bo'lmadi", "leads": leads})

    ad_rows = ad_res if isinstance(ad_res, list) else []
    camp_rows = camp_res if isinstance(camp_res, list) else []

    payload = {
        **base,
        "account": _insight_row(meta_ads, account_res[0]) if account_res else None,
        "ads": _by_spend([_insight_row(meta_ads, r, "ad_name") for r in ad_rows]),
        "campaigns": _by_spend([_insight_row(meta_ads, r, "campaign_name") for r in camp_rows]),
    }
    _ads_store("ads:" + period, payload)
    return _json({**payload, "leads": leads})


@require_auth
async def api_ads_status(request: web.Request):
    """Diagnostic view: why delivery stopped. account_status is resolved against
    meta_ads.ACCOUNT_STATUS here rather than in the browser, so the Telegram
    report and the panel always word it the same way."""
    try:
        import meta_ads
    except Exception:
        logger.exception("meta_ads import failed")
        return _json({"enabled": False})

    if not meta_ads.is_enabled():
        return _json({"enabled": False})

    cached = _ads_cached("status")
    if cached is not None:
        return _json(cached)

    try:
        async with aiohttp.ClientSession() as session:
            account_res, ads_res = await asyncio.gather(
                meta_ads.fetch_account(session),
                meta_ads.fetch_ads_status(session),
                return_exceptions=True,
            )
    except Exception:
        logger.exception("Ads status request failed")
        return _json({"enabled": True, "error": "Meta bilan bog'lanib bo'lmadi"})

    if isinstance(account_res, meta_ads.GraphError):
        return _json({"enabled": True, "error": str(account_res)})
    if isinstance(account_res, BaseException):
        logger.error("Ad account status failed", exc_info=account_res)
        return _json({"enabled": True, "error": "Meta bilan bog'lanib bo'lmadi"})

    code = account_res.get("account_status")
    emoji, status_label = meta_ads.ACCOUNT_STATUS.get(code, ("❔", "Noma'lum (%s)" % code))
    account = {
        "name": account_res.get("name"),
        "status_code": code,
        "status_emoji": emoji,
        "status_label": status_label,
        "disable_reason": account_res.get("disable_reason"),
        "currency": account_res.get("currency") or "USD",
        "balance": _cents(account_res.get("balance")),
        "amount_spent": _cents(account_res.get("amount_spent")),
        "spend_cap": _cents(account_res.get("spend_cap")),
    }

    ads = []
    for a in (ads_res if isinstance(ads_res, list) else []):
        ads.append({
            "name": a.get("name") or "—",
            "effective_status": a.get("effective_status") or "?",
            "configured_status": a.get("configured_status"),
            "issues": [
                (i.get("error_summary") or i.get("error_message") or "").strip()
                for i in (a.get("issues_info") or [])
                if (i.get("error_summary") or i.get("error_message"))
            ],
        })

    return _json(_ads_store("status", {"enabled": True, "account": account, "ads": ads}))


def _lead_json(row: dict) -> dict:
    """`raw` is the whole Graph payload — kept in Postgres for forensics, never
    shipped to the browser."""
    out = {k: v for k, v in row.items() if k != "raw"}
    for k in ("created_time", "received_at", "handled_at"):
        if out.get(k) is not None:
            out[k] = out[k].isoformat()
    return out


@require_auth
async def api_ads_leads(request: web.Request):
    try:
        limit = int(request.query.get("limit", "50"))
    except ValueError:
        limit = 50
    limit = max(1, min(limit, 200))
    rows, total = await asyncio.gather(
        database.get_recent_meta_leads(limit),
        database.count_meta_leads(),
    )
    return _json({"leads": [_lead_json(r) for r in rows], "total": total})


@require_auth
async def api_ads_lead_handled(request: web.Request):
    """Claim a lead from the browser exactly like the "✅ Bog'landim" button in
    Telegram does. ok=false means another admin got there first — the UPDATE's
    WHERE handled_by IS NULL settles that race in Postgres, not here."""
    lead_id = request.match_info["lead_id"]
    ok = await database.mark_meta_lead_handled(lead_id, WEB_SELLER_ID)
    return _json({"ok": bool(ok), "handled_by": WEB_SELLER_ID if ok else None})


# ───────────────────────────── blogerlar ────────────────────────────────────
# Influencer partner programme — see bloggers.py for the rules. The panel is
# the only place a blogger is created: everything downstream (their link, the
# cashback, their own in-bot cabinet) keys off the row written here.

def _blogger_json(b: dict) -> dict:
    import bloggers
    return {
        "id": b["id"],
        "name": b["name"],
        "code": b["code"],
        "link": bloggers.link(b["code"]),
        "user_id": b.get("user_id"),
        "tg_name": b.get("tg_name"),
        "tg_username": b.get("tg_username"),
        "contact": b.get("contact"),
        "note": b.get("note"),
        "percent": float(b.get("percent") or 0),
        "max_orders": int(b.get("max_orders") or 0),
        "active": bool(b.get("active")),
        "created_at": b.get("created_at"),
        "referred_count": int(b.get("referred_count") or 0),
        "orders_count": int(b.get("orders_count") or 0),
        "revenue": float(b.get("revenue") or 0),
        "earned": int(b.get("earned") or 0),
        "pending": int(b.get("pending") or 0),
        "balance": int(b.get("balance") or 0),
    }


def _parse_tg_id(raw):
    """'' / None -> None (no Telegram id yet), '@name' -> error. Bloggers are
    often registered before they've ever opened the bot, so blank is a valid
    answer here — but a half-typed id must not silently become None."""
    if raw in (None, "", "-"):
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ValueError("Telegram ID faqat raqamlardan iborat bo'lishi kerak (masalan: 123456789)")
    if value <= 0:
        raise ValueError("Telegram ID noto'g'ri")
    return value


def _parse_percent(raw, default=None):
    if raw in (None, ""):
        if default is None:
            raise ValueError("foiz kiritilmagan")
        return default
    try:
        value = float(str(raw).replace(",", "."))
    except (TypeError, ValueError):
        raise ValueError("foiz noto'g'ri kiritilgan")
    if not 0 < value <= 100:
        raise ValueError("foiz 0 dan katta va 100 dan kichik bo'lishi kerak")
    return value


def _parse_max_orders(raw, default=None):
    if raw in (None, ""):
        if default is None:
            raise ValueError("buyurtmalar soni kiritilmagan")
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError("buyurtmalar soni butun son bo'lishi kerak")
    if value <= 0:
        raise ValueError("buyurtmalar soni musbat bo'lishi kerak")
    return value


@require_auth
async def api_bloggers_list(request: web.Request):
    rows = await database.get_bloggers_with_stats()
    return _json({"bloggers": [_blogger_json(b) for b in rows]})


@require_auth
async def api_bloggers_create(request: web.Request):
    import bloggers

    b = await request.json()
    name = _clean_str(b.get("name"), 120)
    if not name:
        return _json({"error": "bloger ismi kiritilmagan"}, status=400)

    # The link carries the blogger's own name: the code defaults to a slug of
    # it ("Aziza Blog" -> aziza_blog -> t.me/<bot>?start=aziza_blog). A clash
    # on an auto-derived code just gets a number appended ("aziza2"); a code
    # the admin typed out themselves is refused instead, so nobody hands a
    # blogger a link that quietly isn't the one they asked for.
    raw_code = _clean_str(b.get("code"), 48)
    if raw_code:
        code = bloggers.normalize_code(raw_code)
        if not code:
            return _json(
                {"error": "havola nomi faqat lotin harflari, raqam va _ dan iborat bo'lsin"}, status=400)
        if await database.get_blogger_by_code(code):
            return _json({"error": "bu havola nomi band, boshqasini tanlang"}, status=400)
    else:
        code = await bloggers.suggest_code(name)

    try:
        user_id = _parse_tg_id(b.get("user_id"))
        percent = _parse_percent(b.get("percent"), bloggers.DEFAULT_PERCENT)
        max_orders = _parse_max_orders(b.get("max_orders"), bloggers.DEFAULT_MAX_ORDERS)
    except ValueError as exc:
        return _json({"error": str(exc)}, status=400)

    if user_id is not None and await database.get_blogger_by_user_id(user_id):
        return _json({"error": "bu Telegram ID boshqa blogerga biriktirilgan"}, status=400)

    blogger_id = await database.create_blogger(
        name=name, code=code, user_id=user_id,
        contact=_clean_str(b.get("contact"), 120),
        note=_clean_str(b.get("note"), 500),
        percent=percent, max_orders=max_orders,
    )
    blogger = await database.get_blogger(blogger_id)
    if user_id:
        asyncio.create_task(_blogger_welcome(request.app["bot"], blogger))
    return _json({"ok": True, "id": blogger_id, "code": code,
                              "link": bloggers.link(code)})


@require_auth
async def api_bloggers_update(request: web.Request):
    import bloggers

    blogger_id = int(request.match_info["id"])
    existing = await database.get_blogger(blogger_id)
    if existing is None:
        return _json({"error": "bloger topilmadi"}, status=404)
    b = await request.json()

    fields = {}
    if "name" in b:
        name = _clean_str(b.get("name"), 120)
        if not name:
            return _json({"error": "bloger ismi kiritilmagan"}, status=400)
        fields["name"] = name
    if "code" in b:
        code = bloggers.normalize_code(_clean_str(b.get("code"), 48) or "")
        if not code:
            return _json(
                {"error": "havola nomi faqat lotin harflari, raqam va _ dan iborat bo'lsin"}, status=400)
        if code.lower() != (existing["code"] or "").lower():
            clash = await database.get_blogger_by_code(code)
            if clash and clash["id"] != blogger_id:
                return _json({"error": "bu havola nomi band, boshqasini tanlang"}, status=400)
        fields["code"] = code
    for key, limit in (("contact", 120), ("note", 500)):
        if key in b:
            fields[key] = _clean_str(b.get(key), limit)
    try:
        if "percent" in b:
            fields["percent"] = _parse_percent(b.get("percent"))
        if "max_orders" in b:
            fields["max_orders"] = _parse_max_orders(b.get("max_orders"))
        if "user_id" in b:
            user_id = _parse_tg_id(b.get("user_id"))
            if user_id is not None and user_id != existing.get("user_id"):
                clash = await database.get_blogger_by_user_id(user_id)
                if clash and clash["id"] != blogger_id:
                    return _json({"error": "bu Telegram ID boshqa blogerga biriktirilgan"}, status=400)
            fields["user_id"] = user_id
    except ValueError as exc:
        return _json({"error": str(exc)}, status=400)
    if "active" in b:
        fields["active"] = bool(b.get("active"))

    if fields:
        await database.update_blogger(blogger_id, **fields)

    # A Telegram id that was just filled in turns a "banked" blogger into a
    # payable one: greet them and settle everything they earned while we
    # didn't know who they were (see bloggers.settle_pending).
    new_user_id = fields.get("user_id")
    if new_user_id and new_user_id != existing.get("user_id"):
        blogger = await database.get_blogger(blogger_id)
        asyncio.create_task(_blogger_welcome(request.app["bot"], blogger))
    return _json({"ok": True})


async def _blogger_welcome(bot, blogger: dict) -> None:
    """Greeting + settle-up, in the background: both hit Telegram, which has
    no business holding the admin's save request open."""
    import bloggers
    try:
        await bloggers.notify_registered(blogger, bot)
        settled = await bloggers.settle_pending(blogger, bot)
        if settled:
            logger.info("Blogger %s settled %s so'm on registration", blogger["id"], settled)
    except Exception:
        logger.exception("Blogger welcome failed for %s", blogger.get("id"))


@require_auth
async def api_bloggers_delete(request: web.Request):
    """Full delete — their referral links and earning history go with them.
    Cashback already paid stays in the person's Keto balance."""
    await database.delete_blogger(int(request.match_info["id"]))
    return _json({"ok": True})


@require_auth
async def api_bloggers_detail(request: web.Request):
    """Everything behind one blogger: who they brought in, every order those
    people placed, and what each one paid the blogger."""
    import bloggers

    blogger_id = int(request.match_info["id"])
    blogger = await database.get_blogger(blogger_id)
    if blogger is None:
        return _json({"error": "bloger topilmadi"}, status=404)

    buyers = await database.get_blogger_referred_buyers(blogger_id)
    orders = await database.get_blogger_orders(blogger_id, limit=300)
    summary = await database.get_blogger_summary(blogger_id)
    return _json({
        "blogger": {**blogger, "link": bloggers.link(blogger["code"])},
        "summary": summary,
        "buyers": [dict(x) for x in buyers],
        "orders": [dict(x) for x in orders],
    })


@require_auth
async def api_bloggers_suggest(request: web.Request):
    """Live "this is what the link will look like" for the create form."""
    import bloggers
    name = request.query.get("name", "")
    code = await bloggers.suggest_code(name) if name.strip() else ""
    return _json({"code": code, "link": bloggers.link(code) if code else ""})


# ─────────────────────────── image upload / serve ───────────────────────────

@require_auth
async def api_upload(request: web.Request):
    reader = await request.multipart()
    field = await reader.next()
    if field is None or field.name != "file":
        return _json({"error": "send multipart field named 'file'"}, status=400)

    content_type = (field.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_IMAGE_TYPES:
        return _json({"error": f"unsupported image type: {content_type or 'unknown'} (jpeg/png/webp only)"}, status=400)

    data = bytearray()
    while True:
        chunk = await field.read_chunk(64 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > MAX_UPLOAD_BYTES:
            return _json({"error": "image too large (max 5 MB)"}, status=413)

    if not data:
        return _json({"error": "empty file"}, status=400)

    image_id = await database.save_web_image(bytes(data), content_type)
    return _json({"ok": True, "url": f"/img/{image_id}"})


async def serve_image(request: web.Request):
    """Public image endpoint — used by the admin panel now and available to the
    Mini App later (image_url on products/sets points here)."""
    try:
        image_id = int(request.match_info["id"])
    except ValueError:
        raise web.HTTPNotFound
    img = await database.get_web_image(image_id)
    if not img:
        raise web.HTTPNotFound
    return web.Response(
        body=img["data"], content_type=img["content_type"],
        headers={"Cache-Control": "public, max-age=86400"},  # images are immutable
    )


# ──────────────────── qayta sotuv + referal statistikasi ─────────────────────
# Bot paneli (retention_stats.py / referral_stats.py) bilan bir xil
# funksiyalarni chaqiradi — sayt va bot bir xil raqamni ko'rsatishi uchun.

def _retention_since(period: str):
    from datetime import datetime, timedelta
    days = {"30d": 30, "90d": 90, "365d": 365}.get(period)
    return datetime.utcnow() - timedelta(days=days) if days else None


@require_auth
async def api_retention(request: web.Request):
    """Qayta sotuv tabi uchun hamma narsa bitta chaqiruvda: umumiy manzara,
    qaytib kelgan mijozlar ro'yxati, ular nima olishi va referal kanallari."""
    period = request.query.get("period", "all")
    sort = request.query.get("sort", "revenue")
    if sort not in ("revenue", "orders", "recent"):
        sort = "revenue"
    since = _retention_since(period)

    summary, (customers, total), products, channels = await asyncio.gather(
        database.get_retention_summary(since),
        database.get_repeat_customers(since, limit=100, sort=sort, min_orders=1),
        database.get_repeat_top_products(since, limit=10),
        database.get_referral_channel_stats(since),
    )
    return _json({
        "summary": summary,
        "customers": customers,
        "total": total,
        "products": products,
        "channels": channels,
        "period": period,
        "sort": sort,
    })


@require_auth
async def api_retention_customer(request: web.Request):
    """Bitta mijozning savdo profili — jadvaldagi qatorni bosganda ochiladi."""
    user_id = int(request.match_info["user_id"])
    return _json({"profile": await database.get_customer_purchase_profile(user_id)})


# ─────────────────────────────── wiring ─────────────────────────────────────

# ───────────────────────────── courier board ─────────────────────────────────

@require_auth
async def api_courier_board(request: web.Request):
    """Whole Kanban board in one payload — see courier_board.board_snapshot.
    The tab polls this every few seconds so two admins watching the same board
    see each other's moves without a websocket."""
    try:
        hours = int(request.query.get("hours", courier_board.DELIVERED_WINDOW_HOURS))
    except ValueError:
        hours = courier_board.DELIVERED_WINDOW_HOURS
    hours = max(1, min(hours, 24 * 14))
    scope = "active" if request.query.get("scope") == "active" else "all"
    snapshot = await courier_board.board_snapshot(hours, scope)
    return _json(snapshot)


@require_auth
async def api_courier_move(request: web.Request):
    """Move a card. Body: {status, from?, notify?}.

    `from` is the status the board was showing — when it no longer matches,
    the move is rejected as stale instead of silently overwriting whatever a
    second admin just did.
    """
    order_id = int(request.match_info["id"])
    try:
        body = await request.json()
    except Exception:
        body = {}
    target = str(body.get("status") or "").strip()
    expected = body.get("from") or None
    notify = body.get("notify", True) is not False

    result = await courier_board.move_order(
        order_id, target,
        expected_from=str(expected) if expected else None,
        notify=notify, bot=request.app.get("bot"),
    )
    if not result.get("ok"):
        return _json(result, status=409 if result.get("stale") else 400)
    return _json(result)


@require_auth
async def api_courier_assign(request: web.Request):
    """Claim or release a card for a courier. Body: {courier_id} (null clears)."""
    order_id = int(request.match_info["id"])
    try:
        body = await request.json()
    except Exception:
        body = {}
    raw = body.get("courier_id")
    courier_id = None
    if raw not in (None, "", "null"):
        try:
            courier_id = int(raw)
        except (TypeError, ValueError):
            return _json({"error": "noto'g'ri kuryer"}, status=400)
    await courier_board.assign_courier(order_id, courier_id)
    order = await database.get_order(order_id)
    return _json({"ok": True, "order": courier_board._card(order) if order else None})


@require_auth
async def api_courier_couriers(request: web.Request):
    return _json({"couriers": await courier_board.courier_options()})


@require_auth
async def api_courier_location(request: web.Request):
    """Send the buyer's Telegram pin for this order to the admins' chats, so
    it opens in a navigation app instead of only as a maps link in a browser."""
    order_id = int(request.match_info["id"])
    bot = request.app.get("bot")
    if bot is None:
        return _json({"error": "bot ulanmagan"}, status=503)
    result = await courier_board.send_pin_to_telegram(order_id, bot)
    return _json(result, status=200 if result.get("ok") else 400)


def setup_admin_routes(app: web.Application):
    app.router.add_get("/admin", admin_page)
    app.router.add_post("/admin/api/login", api_login)
    app.router.add_post("/admin/api/logout", api_logout)
    app.router.add_get("/admin/api/session", api_session)
    app.router.add_post("/admin/api/categories", api_categories_create)
    app.router.add_get("/admin/api/products", api_products_list)
    app.router.add_post("/admin/api/products", api_products_create)
    app.router.add_post("/admin/api/products/{id:\\d+}", api_products_update)
    app.router.add_post("/admin/api/products/{id:\\d+}/delete", api_products_delete)
    app.router.add_get("/admin/api/sets", api_sets_list)
    app.router.add_post("/admin/api/sets", api_sets_create)
    app.router.add_post("/admin/api/sets/{id:\\d+}", api_sets_update)
    app.router.add_post("/admin/api/sets/{id:\\d+}/delete", api_sets_delete)
    app.router.add_post("/admin/api/upload", api_upload)
    app.router.add_post("/admin/api/reco/on", api_reco_on)
    app.router.add_post("/admin/api/reco/now", api_reco_send_now)
    app.router.add_post("/admin/api/reco/backfill", api_reco_backfill)
    app.router.add_get("/admin/api/expenses", api_expenses_list)
    app.router.add_post("/admin/api/expenses", api_expenses_add)
    app.router.add_get("/admin/api/dashboard", api_dashboard)
    app.router.add_get("/admin/api/promos", api_promos_list)
    app.router.add_post("/admin/api/promos", api_promos_create)
    app.router.add_post("/admin/api/promos/{id:\\d+}", api_promos_update)
    app.router.add_post("/admin/api/promos/{id:\\d+}/delete", api_promos_delete)
    app.router.add_post("/admin/api/promos/{id:\\d+}/start", api_promos_start)
    app.router.add_post("/admin/api/promos/{id:\\d+}/stop", api_promos_stop)
    app.router.add_post("/admin/api/promos/{id:\\d+}/announce", api_promos_announce)
    app.router.add_get("/admin/api/keto/status", api_keto_status)
    app.router.add_post("/admin/api/keto/redemption", api_keto_redemption_toggle)
    app.router.add_get("/admin/api/ads", api_ads)
    app.router.add_get("/admin/api/ads/status", api_ads_status)
    app.router.add_get("/admin/api/ads/leads", api_ads_leads)
    app.router.add_post("/admin/api/ads/leads/{lead_id}/handled", api_ads_lead_handled)
    app.router.add_get("/admin/api/retention", api_retention)
    app.router.add_get("/admin/api/retention/customer/{user_id:\\d+}", api_retention_customer)
    app.router.add_get("/admin/api/bloggers", api_bloggers_list)
    app.router.add_post("/admin/api/bloggers", api_bloggers_create)
    app.router.add_get("/admin/api/bloggers/suggest", api_bloggers_suggest)
    app.router.add_post("/admin/api/bloggers/{id:[0-9]+}", api_bloggers_update)
    app.router.add_post("/admin/api/bloggers/{id:[0-9]+}/delete", api_bloggers_delete)
    app.router.add_get("/admin/api/bloggers/{id:[0-9]+}/detail", api_bloggers_detail)
    app.router.add_get("/admin/api/courier/board", api_courier_board)
    app.router.add_get("/admin/api/courier/couriers", api_courier_couriers)
    app.router.add_post("/admin/api/courier/orders/{id:\\d+}/move", api_courier_move)
    app.router.add_post("/admin/api/courier/orders/{id:\\d+}/courier", api_courier_assign)
    app.router.add_post("/admin/api/courier/orders/{id:\\d+}/location", api_courier_location)
    app.router.add_get("/img/{id:\\d+}", serve_image)
