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
  GET  /admin/api/contest/status  — Keto musobaqasi state + live leaderboard
  POST /admin/api/contest/upload-video — multipart video -> {file_id} (relayed through the
                                    bot to get a Telegram file_id; bytes are never stored)
  POST /admin/api/contest/start   — {days, image_url, video_file_id, prize_1, prize_2, prize_3} -> launch/relaunch
  POST /admin/api/contest/stop    — deactivate the contest early
  GET  /admin/api/keto/status     — redemption on/off + every user's Keto balance
  POST /admin/api/keto/redemption — {enabled} -> toggle Keto-as-discount at checkout
  GET  /admin/api/dashboard       — {period} -> KPI/trend/best-sellers/Keto snapshot for the Dashboard tab
  GET  /admin/api/ads             — {period} -> Meta Ads KPIs + per-ad/per-campaign rows + lead counters
  GET  /admin/api/ads/status      — ad-account health (account_status, balance) + per-ad issues_info
  GET  /admin/api/ads/leads       — {limit} -> stored Meta lead-form submissions, newest first
  POST /admin/api/ads/leads/{lead_id}/handled — claim a lead ("Bog'landim"), same as the Telegram button

Images are stored in Postgres (web_images) because Railway's filesystem is
ephemeral — see database.py.
"""
import asyncio
import hashlib
import hmac
import json
import logging
import time
from pathlib import Path

import aiohttp
from aiohttp import web

import database
from config import ADMIN_WEB_PASSWORD, BOT_TOKEN, ADMIN_IDS
from locales import CATEGORIES

logger = logging.getLogger(__name__)

SESSION_COOKIE = "safran_admin"
SESSION_TTL = 7 * 24 * 3600          # 7 days
MAX_UPLOAD_BYTES = 5 * 1024 * 1024   # 5 MB per image
MAX_VIDEO_BYTES = 45 * 1024 * 1024   # 45 MB — under Telegram's 50 MB bot-upload cap; never stored, just relayed
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm"}

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
            return web.json_response({"error": "admin panel disabled: ADMIN_WEB_PASSWORD not set"}, status=503)
        if not _authed(request):
            return web.json_response({"error": "unauthorized"}, status=401)
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
        return web.json_response({"error": "ADMIN_WEB_PASSWORD is not configured on the server"}, status=503)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "bad request"}, status=400)
    password = str(body.get("password", ""))
    # Constant-time compare + a small delay to blunt brute-forcing.
    ok = hmac.compare_digest(password.encode(), ADMIN_WEB_PASSWORD.encode())
    if not ok:
        import asyncio
        await asyncio.sleep(1.0)
        return web.json_response({"error": "wrong password"}, status=403)
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
    return web.json_response({"ok": True, "categories": categories})


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
        return web.json_response({"error": "name_uz is required"}, status=400)

    cat = await database.create_category(name_uz=name_uz, name_ru=_clean_str(b.get("name_ru"), 200))
    if cat.get("created_at"):
        cat["created_at"] = cat["created_at"].isoformat()
    return web.json_response({"ok": True, "category": cat})


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
    return web.json_response({"products": products})


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
        return web.json_response({"error": "name, price, category are required"}, status=400)

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
        discount_percent=int(b.get("discount_percent") or 0),
        image_url=_clean_str(b.get("image_url"), 300),
    )
    return web.json_response({"ok": True, "id": pid})


@require_auth
async def api_products_update(request: web.Request):
    pid = int(request.match_info["id"])
    if not await database.get_product(pid):
        return web.json_response({"error": "not found"}, status=404)
    try:
        b = await request.json()
    except Exception:
        return web.json_response({"error": "bad request"}, status=400)

    fields = {}
    if "name" in b:             fields["name"] = _clean_str(b["name"], 200)
    if "name_ru" in b:          fields["name_ru"] = _clean_str(b["name_ru"], 200)
    if "description" in b:      fields["description"] = _clean_str(b["description"], 2000)
    if "description_ru" in b:   fields["description_ru"] = _clean_str(b["description_ru"], 2000)
    if "price" in b:            fields["price"] = float(b["price"])
    if "cost_price" in b:       fields["cost_price"] = float(b["cost_price"] or 0)
    if "quantity" in b:         fields["quantity"] = float(b["quantity"] or 0)
    if "unit" in b:             fields["unit"] = _clean_str(b["unit"], 20) or "kg"
    if "discount_percent" in b: fields["discount_percent"] = int(b["discount_percent"] or 0)
    if "image_url" in b:        fields["image_url"] = _clean_str(b["image_url"], 300)
    if "is_active" in b:        fields["is_active"] = 1 if b["is_active"] else 0
    if "category" in b:
        if b["category"] not in CATEGORIES:
            return web.json_response({"error": "bad category"}, status=400)
        fields["category"] = b["category"]
    if not fields:
        return web.json_response({"error": "nothing to update"}, status=400)

    await database.update_product(pid, **fields)
    return web.json_response({"ok": True})


@require_auth
async def api_products_delete(request: web.Request):
    pid = int(request.match_info["id"])
    await database.delete_product(pid)  # soft delete: is_active = 0
    return web.json_response({"ok": True})


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
    return web.json_response({"sets": sets})


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
        return web.json_response({"error": f"invalid payload: {e}"}, status=400)

    # Every member product must exist and be active.
    for it in items:
        p = await database.get_product(it["product_id"])
        if not p or not p["is_active"]:
            return web.json_response({"error": f"product {it['product_id']} not found or archived"}, status=400)

    sid = await database.create_set(
        name=name, set_price=set_price, items=items,
        name_ru=_clean_str(b.get("name_ru"), 200),
        description=_clean_str(b.get("description"), 2000),
        description_ru=_clean_str(b.get("description_ru"), 2000),
        image_url=_clean_str(b.get("image_url"), 300),
    )
    return web.json_response({"ok": True, "id": sid})


@require_auth
async def api_sets_update(request: web.Request):
    sid = int(request.match_info["id"])
    if not await database.get_set(sid):
        return web.json_response({"error": "not found"}, status=404)
    try:
        b = await request.json()
    except Exception:
        return web.json_response({"error": "bad request"}, status=400)

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
            return web.json_response({"error": f"invalid items: {e}"}, status=400)

    await database.update_set(sid, items=items, **fields)
    return web.json_response({"ok": True})


@require_auth
async def api_sets_delete(request: web.Request):
    sid = int(request.match_info["id"])
    await database.delete_set(sid)
    return web.json_response({"ok": True})


# ────────────────────── personal recommendations control ────────────────────

@require_auth
async def api_reco_on(request: web.Request):
    await database.set_reco_enabled(True)
    return web.json_response({"ok": True, "enabled": True})


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
    return web.json_response({"ok": True, "started": True,
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
        return web.json_response({"error": "bad request"}, status=400)

    marked = 0
    for uid in await database.get_user_ids_with_orders():
        orders = await database.get_user_orders(uid)
        lang = await database.get_user_language(uid)
        text = personal_recommend.build_personal_message(lang, orders, cycle)
        if text:
            h = hashlib.sha256(text.encode()).hexdigest()
            await database.mark_reco_sent(uid, h)
            marked += 1
    return web.json_response({"ok": True, "cycle": cycle, "marked": marked})


# ───────────────────────── Keto musobaqasi (referral contest) ───────────────

@require_auth
async def api_contest_status(request: web.Request):
    state = await database.get_referral_contest_state()
    excluded = set(ADMIN_IDS) | database.LEADERBOARD_EXCLUDED_USER_IDS
    leaderboard = []
    if state.get("started_at"):
        rows = await database.get_contest_leaderboard(
            state["started_at"], state["ends_at"], excluded, limit=20
        )
        leaderboard = [
            {"user_id": r["user_id"], "username": r["username"], "full_name": r["full_name"], "invites": r["invites"]}
            for r in rows
        ]
    out = dict(state)
    for k in ("started_at", "ends_at"):
        if out.get(k):
            out[k] = out[k].isoformat()
    if out.get("last_reminder_date"):
        out["last_reminder_date"] = out["last_reminder_date"].isoformat()
    out["leaderboard"] = leaderboard
    return web.json_response(out)


@require_auth
async def api_contest_upload_video(request: web.Request):
    """Relays the admin's video through the bot once, purely to get back a
    Telegram file_id — the bytes are never written to Postgres. Telegram's
    own CDN hosts the file from then on, so re-sending it in reminders costs
    nothing on our side. Mirrors how products already use a Telegram
    photo_id alongside the web-hosted image_url (see database.py)."""
    from aiogram.types import BufferedInputFile

    reader = await request.multipart()
    field = await reader.next()
    if field is None or field.name != "file":
        return web.json_response({"error": "send multipart field named 'file'"}, status=400)

    content_type = (field.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_VIDEO_TYPES:
        return web.json_response({"error": f"unsupported video type: {content_type or 'unknown'} (mp4/mov/webm only)"}, status=400)

    data = bytearray()
    while True:
        chunk = await field.read_chunk(64 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > MAX_VIDEO_BYTES:
            return web.json_response({"error": f"video too large (max {MAX_VIDEO_BYTES // (1024 * 1024)} MB)"}, status=413)

    if not data:
        return web.json_response({"error": "empty file"}, status=400)

    bot = request.app["bot"]
    try:
        sent = await bot.send_video(
            WEB_SELLER_ID, BufferedInputFile(bytes(data), filename="contest_video.mp4"),
            caption="🏆 Keto musobaqasi videosi (admin panel orqali yuklandi)",
        )
    except Exception:
        logger.exception("Contest video relay-upload failed")
        return web.json_response({"error": "video yuklab bo'lmadi"}, status=502)

    file_id = sent.video.file_id
    try:
        await sent.delete()  # cleanup only — the file_id stays valid regardless
    except Exception:
        pass

    return web.json_response({"ok": True, "file_id": file_id})


@require_auth
async def api_contest_start(request: web.Request):
    try:
        b = await request.json()
        days = int(b.get("days") or 10)
        if days <= 0:
            raise ValueError
    except Exception:
        return web.json_response({"error": "days must be a positive integer"}, status=400)

    # image_file_id is the bot admin panel's own media slot (a bot-uploaded
    # photo) — this form doesn't manage it, so carry the current value
    # through unchanged rather than wiping it out.
    current = await database.get_referral_contest_state()
    state = await database.start_referral_contest(
        days=days,
        image_url=_clean_str(b.get("image_url"), 300),
        prize_1=_clean_str(b.get("prize_1"), 500),
        prize_2=_clean_str(b.get("prize_2"), 500),
        prize_3=_clean_str(b.get("prize_3"), 500),
        video_file_id=_clean_str(b.get("video_file_id"), 300),
        image_file_id=current.get("image_file_id"),
    )
    state["started_at"] = state["started_at"].isoformat()
    state["ends_at"] = state["ends_at"].isoformat()
    return web.json_response({"ok": True, "state": state})


@require_auth
async def api_contest_stop(request: web.Request):
    await database.stop_referral_contest()
    return web.json_response({"ok": True})


# ───────────────────────────── expenses ──────────────────────────────────────

@require_auth
async def api_expenses_list(request: web.Request):
    expenses = await database.get_expenses(100)
    return web.json_response({"expenses": expenses}, dumps=lambda obj: json.dumps(obj, default=str))

@require_auth
async def api_expenses_add(request: web.Request):
    try:
        b = await request.json()
        name = (b.get("name") or "").strip()
        amount = float(b.get("amount") or 0)
        if not name or amount <= 0:
            raise ValueError
    except Exception:
        return web.json_response({"error": "invalid name or amount"}, status=400)
    
    eid = await database.add_expense(name, amount)
    return web.json_response({"ok": True, "id": eid})


# ───────────────────────────── dashboard ─────────────────────────────────────

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
        
    stats, monthly, top_products, keto, abc_analysis = await asyncio.gather(
        database.get_admin_stats(period_arg),
        database.get_monthly_breakdown(5),
        database.get_top_products(period_arg, limit=5),
        database.get_keto_program_stats(),
        database.get_abc_analysis(period_arg),
    )
    return web.json_response({
        "stats": stats,
        "monthly": monthly,
        "top_products": top_products,
        "keto": keto,
        "abc_analysis": abc_analysis,
    })


# ───────────────────── Keto-as-discount at checkout ──────────────────────────

@require_auth
async def api_keto_status(request: web.Request):
    """Redemption on/off + every user with any Keto, highest first — so the
    owner can see who holds what without asking (2026-07-30, built dormant:
    `redemption_enabled` defaults FALSE, see gamification.is_redemption_enabled)."""
    state = await database.get_gamification_state()
    balances = await database.get_keto_balances_list()
    return web.json_response({
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
        return web.json_response({"error": "bad request"}, status=400)
    await database.set_redemption_enabled(enabled)
    return web.json_response({"ok": True, "enabled": enabled})


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
        return web.json_response({"enabled": False})

    period = request.query.get("period", "today")
    if period not in meta_ads.PRESETS:
        period = "today"
    label = meta_ads.PRESETS[period][0]

    if not meta_ads.is_enabled():
        return web.json_response({"enabled": False, "period": period, "label": label})

    # Lead counters come from our own Postgres, so they stay live — only the
    # Graph half of the payload is cached.
    leads = await database.get_meta_leads_summary()

    cached = _ads_cached("ads:" + period)
    if cached is not None:
        return web.json_response({**cached, "leads": leads})

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
        return web.json_response({**base, "error": "Meta bilan bog'lanib bo'lmadi", "leads": leads})

    if isinstance(account_res, meta_ads.GraphError):
        return web.json_response({**base, "error": str(account_res), "leads": leads})
    if isinstance(account_res, BaseException):
        logger.error("Ads account insights failed", exc_info=account_res)
        return web.json_response({**base, "error": "Meta bilan bog'lanib bo'lmadi", "leads": leads})

    ad_rows = ad_res if isinstance(ad_res, list) else []
    camp_rows = camp_res if isinstance(camp_res, list) else []

    payload = {
        **base,
        "account": _insight_row(meta_ads, account_res[0]) if account_res else None,
        "ads": _by_spend([_insight_row(meta_ads, r, "ad_name") for r in ad_rows]),
        "campaigns": _by_spend([_insight_row(meta_ads, r, "campaign_name") for r in camp_rows]),
    }
    _ads_store("ads:" + period, payload)
    return web.json_response({**payload, "leads": leads})


@require_auth
async def api_ads_status(request: web.Request):
    """Diagnostic view: why delivery stopped. account_status is resolved against
    meta_ads.ACCOUNT_STATUS here rather than in the browser, so the Telegram
    report and the panel always word it the same way."""
    try:
        import meta_ads
    except Exception:
        logger.exception("meta_ads import failed")
        return web.json_response({"enabled": False})

    if not meta_ads.is_enabled():
        return web.json_response({"enabled": False})

    cached = _ads_cached("status")
    if cached is not None:
        return web.json_response(cached)

    try:
        async with aiohttp.ClientSession() as session:
            account_res, ads_res = await asyncio.gather(
                meta_ads.fetch_account(session),
                meta_ads.fetch_ads_status(session),
                return_exceptions=True,
            )
    except Exception:
        logger.exception("Ads status request failed")
        return web.json_response({"enabled": True, "error": "Meta bilan bog'lanib bo'lmadi"})

    if isinstance(account_res, meta_ads.GraphError):
        return web.json_response({"enabled": True, "error": str(account_res)})
    if isinstance(account_res, BaseException):
        logger.error("Ad account status failed", exc_info=account_res)
        return web.json_response({"enabled": True, "error": "Meta bilan bog'lanib bo'lmadi"})

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

    return web.json_response(_ads_store("status", {"enabled": True, "account": account, "ads": ads}))


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
    return web.json_response({"leads": [_lead_json(r) for r in rows], "total": total})


@require_auth
async def api_ads_lead_handled(request: web.Request):
    """Claim a lead from the browser exactly like the "✅ Bog'landim" button in
    Telegram does. ok=false means another admin got there first — the UPDATE's
    WHERE handled_by IS NULL settles that race in Postgres, not here."""
    lead_id = request.match_info["lead_id"]
    ok = await database.mark_meta_lead_handled(lead_id, WEB_SELLER_ID)
    return web.json_response({"ok": bool(ok), "handled_by": WEB_SELLER_ID if ok else None})


# ─────────────────────────── image upload / serve ───────────────────────────

@require_auth
async def api_upload(request: web.Request):
    reader = await request.multipart()
    field = await reader.next()
    if field is None or field.name != "file":
        return web.json_response({"error": "send multipart field named 'file'"}, status=400)

    content_type = (field.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if content_type not in ALLOWED_IMAGE_TYPES:
        return web.json_response({"error": f"unsupported image type: {content_type or 'unknown'} (jpeg/png/webp only)"}, status=400)

    data = bytearray()
    while True:
        chunk = await field.read_chunk(64 * 1024)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > MAX_UPLOAD_BYTES:
            return web.json_response({"error": "image too large (max 5 MB)"}, status=413)

    if not data:
        return web.json_response({"error": "empty file"}, status=400)

    image_id = await database.save_web_image(bytes(data), content_type)
    return web.json_response({"ok": True, "url": f"/img/{image_id}"})


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


# ─────────────────────────────── wiring ─────────────────────────────────────

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
    app.router.add_get("/admin/api/contest/status", api_contest_status)
    app.router.add_post("/admin/api/contest/upload-video", api_contest_upload_video)
    app.router.add_post("/admin/api/contest/start", api_contest_start)
    app.router.add_post("/admin/api/contest/stop", api_contest_stop)
    app.router.add_get("/admin/api/keto/status", api_keto_status)
    app.router.add_post("/admin/api/keto/redemption", api_keto_redemption_toggle)
    app.router.add_get("/admin/api/ads", api_ads)
    app.router.add_get("/admin/api/ads/status", api_ads_status)
    app.router.add_get("/admin/api/ads/leads", api_ads_leads)
    app.router.add_post("/admin/api/ads/leads/{lead_id}/handled", api_ads_lead_handled)
    app.router.add_get("/img/{id:\\d+}", serve_image)
