"""
Instagram/Facebook izohlari botga tushadi, javob botdan yoziladi
(TZ «4-qism», 2026-11-09).

Nega: reklama izohlari asl postda emas, reklamaning alohida nusxasida
yoziladi — ko'rinmay, javobsiz qolib ketadi (09.11: 52 izohdan 3 tasi
javobsiz, 47 tasiga faqat avtomatik «Direct'ga yozdik»).

QANDAY KELADI
  * Webhook — /meta/webhook (Instagram «comments», sahifa «feed»): darhol.
    META_APP_SECRET (X-Hub-Signature-256) va META_WEBHOOK_VERIFY_TOKEN
    serverda bo'lsa ishlaydi.
  * Tekshiruv — har SYNC_EVERY soniyada reklama nusxalari (ads_read tokeni
    bilan reklamalar ro'yxati → creative'dagi IG media / FB post) va oxirgi
    organik postlar izohlari o'qiladi. Webhook sozlanmagan bo'lsa ham
    ishlaydi va o'tkazib yuborilganini tutadi. Birinchi marta — eski
    izohlarni yuklash: javobsizlari va faqat avtomatik «Direct'ga yozdik»
    olgan savollar adminlarga tushadi.

ADMIN KO'RADI
  💬 kartochka (har adminga; biri javob bersa — hammasida yangilanadi):
  ✅ Yuborish / ✏️ Tahrirlash (AI loyihasi bo'lsa) yoki ✍️ Javob yozish,
  📩 Shaxsiy xabar, 💰 Narx / 🚚 Yetkazish / 🤖 Bot shablonlari, 🙈 Yashirish,
  ✅ Ko'rildi. Kartochkaga reply qilib yozilgan matn — izohga ochiq javob.

AI (comment_ai.py: GPT, kerak bo'lsa Claude) — har izohga loyiha; rahmat va bilim bazasida aniq
javobi borini AI_DELAY dan keyin o'zi yuboradi (oldin izohga boshqa avtomat
javob yozganmi — tekshiradi; bitta izohga bitta javob). Qolgani tasdiqqa.

TOKEN — reklama statistikasi tokeniga (ads_read) tegilmaydi. Izohlar uchun
alohida system user tokeni: /izoh_token (yoki env META_COMMENTS_TOKEN).
Undan sahifa tokeni olinadi — javob, yashirish va shaxsiy xabar shu bilan.
"""
import asyncio
import hashlib
import hmac
import html
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import aiohttp
from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import (CallbackQuery, ForceReply, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)
from aiohttp import web

import comment_ai
import database
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router()

PAGE_ID = os.getenv("META_PAGE_ID", "582508891606220").strip()
ENV_TOKEN = os.getenv("META_COMMENTS_TOKEN", "").strip()
APP_SECRET = os.getenv("META_APP_SECRET", "").strip()
VERIFY_TOKEN = os.getenv("META_WEBHOOK_VERIFY_TOKEN", "").strip()
API_VERSION = (os.getenv("META_API_VERSION", "").strip().strip("/") or "v23.0")
GRAPH = f"https://graph.facebook.com/{API_VERSION}/"

SYNC_EVERY = max(120, int(os.getenv("META_COMMENTS_SYNC_SECONDS", "600")))
# AI o'zi yuborishdan oldin kutadi: boshqa avtomat (Business Suite, ManyChat)
# javob yozib ulgursa — AI yozmaydi, adminga tasdiqqa beradi.
AI_DELAY = int(os.getenv("META_COMMENTS_AI_DELAY", "90"))
FRESH_FOR = timedelta(days=2)         # bundan eski izohga AI o'zi yozmaydi
PRIVATE_WINDOW = timedelta(days=7)    # Meta: shaxsiy javob 7 kun ichida
ORGANIC_POSTS = 15
MAX_ADS = 100
TEXT_MAX = 1500
REPLY_MAX = 900                       # Instagram izohi ~2200 belgi; javob qisqa

OPEN = ("new", "pending")
DONE_LABELS = {
    "answered": "✅ Javob berildi",
    "ai_answered": "🤖 AI javob berdi",
    "seen": "👀 Ko'rildi",
    "skipped": "❌ Bekor qilindi (javobsiz)",
    "hidden": "🙈 Yashirildi",
    "sending": "⏳ Yuborilmoqda…",
}

_db_token = ""
_identity: dict = {}
_ad_names: dict[str, str] = {}        # ad_id → reklama nomi
_object_ads: dict[str, tuple] = {}    # IG media / FB post id → (ad_id, ad_name)
_prompts: dict[tuple[int, int], tuple[int, str]] = {}  # (chat, msg) → (izoh, public|private)
_tasks: set = set()


def _spawn(coro) -> None:
    task = asyncio.get_running_loop().create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def token() -> str:
    return _db_token or ENV_TOKEN


def is_admin(user_id: int | None) -> bool:
    return user_id in ADMIN_IDS


async def load_token() -> None:
    global _db_token
    try:
        _db_token = ((await database.get_meta_comments_state()).get("token") or "").strip()
    except Exception:
        logger.warning("Could not read the comments token", exc_info=True)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_time(value) -> datetime | None:
    """Graph vaqti ('2026-11-09T10:15:00+0000') yoki unix soniya → naive UTC."""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            return datetime.fromtimestamp(int(value), timezone.utc).replace(tzinfo=None)
        dt = datetime.strptime(str(value).replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except (ValueError, OverflowError, OSError):
        return None


# ──────────────────────────────── Graph API ─────────────────────────────────

class GraphError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(f"[{code}] {message}")


async def _graph(session: aiohttp.ClientSession, method: str, path: str, access_token: str,
                 params: dict | None = None, body: dict | None = None) -> dict:
    query = dict(params or {})
    query["access_token"] = access_token
    async with session.request(method, GRAPH + path, params=query, json=body,
                               timeout=aiohttp.ClientTimeout(total=45)) as resp:
        data = await resp.json(content_type=None)
    if isinstance(data, dict) and "error" in data:
        err = data["error"]
        raise GraphError(err.get("code"), err.get("message", "unknown"))
    return data if isinstance(data, dict) else {"data": data}


async def identity(session: aiohttp.ClientSession, force: bool = False,
                   access_token: str | None = None) -> dict:
    """Sahifa tokeni, sahifa nomi, Instagram hisob id/username. System user
    tokenidan sahifa tokeni olinadi; token o'zi sahifa tokeni bo'lsa — o'zi."""
    global _identity
    if _identity and not force and access_token is None:
        return _identity
    tok = access_token or token()
    if not tok:
        raise GraphError("no_token", "izohlar tokeni berilmagan (/izoh_token)")
    data = await _graph(session, "GET", PAGE_ID, tok,
                        {"fields": "name,access_token,instagram_business_account{id,username}"})
    ig = data.get("instagram_business_account") or {}
    ident = {"page_token": data.get("access_token") or tok, "page_name": data.get("name"),
             "ig_id": str(ig.get("id") or ""), "ig_username": ig.get("username") or ""}
    if access_token is None:
        _identity = ident
    return ident


def is_own(c: dict, ident: dict) -> bool:
    """Bizning hisobdan yozilganmi. Webhook'da Instagram hisob id si entry.id
    da keladi (account_id) — token ishlamay qolsa ham o'z javobimiz kartochka
    bo'lib qaytmaydi."""
    sender = str(c.get("from_id") or "")
    if c.get("platform") == "fb":
        return sender == PAGE_ID
    ours = {i for i in (ident.get("ig_id"), c.get("account_id")) if i}
    return (bool(sender) and sender in ours) or \
           (bool(ident.get("ig_username")) and (c.get("username") or "").lower() == ident["ig_username"].lower())


async def reply_public(session, ident: dict, c: dict, text: str) -> str:
    """Izohning o'zi ostiga — reklama nusxasining o'ziga — ochiq javob."""
    path = f"{c['comment_id']}/replies" if c["platform"] == "ig" else f"{c['comment_id']}/comments"
    data = await _graph(session, "POST", path, ident["page_token"], {"message": text[:REPLY_MAX * 2]})
    return str(data.get("id") or "")


async def reply_private(session, ident: dict, c: dict, text: str) -> None:
    """Izoh egasiga Direct/Messenger: bitta izohga bitta, 7 kun ichida."""
    await _graph(session, "POST", f"{PAGE_ID}/messages", ident["page_token"],
                 body={"recipient": {"comment_id": c["comment_id"]}, "message": {"text": text}})


async def hide(session, ident: dict, c: dict) -> None:
    flag = {"hide": "true"} if c["platform"] == "ig" else {"is_hidden": "true"}
    await _graph(session, "POST", c["comment_id"], ident["page_token"], flag)


async def our_existing_reply(session, ident: dict, c: dict) -> str | None:
    """Izohga bizning hisobdan javob bormi (boshqa avtomat yoki qo'lda)."""
    if c["platform"] == "ig":
        data = await _graph(session, "GET", f"{c['comment_id']}/replies", ident["page_token"],
                            {"fields": "id,text,username,from"})
        for r in data.get("data", []):
            mine = {"platform": "ig", "from_id": (r.get("from") or {}).get("id"), "username": r.get("username")}
            if is_own(mine, ident):
                return r.get("text") or ""
    else:
        data = await _graph(session, "GET", f"{c['comment_id']}/comments", ident["page_token"],
                            {"fields": "id,message,from"})
        for r in data.get("data", []):
            if str((r.get("from") or {}).get("id") or "") == PAGE_ID:
                return r.get("message") or ""
    return None


async def _ad_name(session, ad_id: str | None) -> str | None:
    if not ad_id:
        return None
    if ad_id in _ad_names:
        return _ad_names[ad_id]
    try:
        import meta_ads
        if meta_ads.is_enabled():
            data = await meta_ads._get(session, ad_id, fields="name")
            _ad_names[ad_id] = data.get("name")
    except Exception:
        logger.info("Ad name lookup failed for %s", ad_id, exc_info=True)
    return _ad_names.get(ad_id)


async def _permalink(session, ident: dict, c: dict) -> str | None:
    if c.get("post_link"):
        return c["post_link"]
    if c["platform"] == "fb":
        post = c.get("media_id") or ""
        return f"https://www.facebook.com/{post}" if post else None
    if not c.get("media_id"):
        return None
    try:
        data = await _graph(session, "GET", c["media_id"], ident["page_token"], {"fields": "permalink"})
        return data.get("permalink")
    except GraphError:
        return None


# ──────────────────────────── webhook payloads ──────────────────────────────

def from_ig_change(value: dict) -> dict | None:
    if not isinstance(value, dict) or not value.get("id"):
        return None
    media = value.get("media") or {}
    sender = value.get("from") or {}
    is_ad = (media.get("media_product_type") or "").upper() == "AD" or bool(media.get("ad_id"))
    return {
        "comment_id": str(value["id"]), "platform": "ig",
        "parent_id": value.get("parent_id"),
        "media_id": str(media.get("id") or "") or None,
        "ad_id": str(media.get("ad_id") or "") or None,
        "ad_name": media.get("ad_title") if is_ad else None,
        "from_id": str(sender.get("id") or "") or None,
        "username": sender.get("username"),
        "text": value.get("text") or "",
        "created_at": _parse_time(value.get("timestamp")) or _utcnow(),
    }


def from_fb_change(value: dict) -> dict | None:
    if not isinstance(value, dict) or value.get("item") != "comment" or value.get("verb") != "add":
        return None
    sender = value.get("from") or {}
    post_id = str(value.get("post_id") or "")
    parent = value.get("parent_id")
    return {
        "comment_id": str(value.get("comment_id") or ""), "platform": "fb",
        "parent_id": parent if parent and parent != post_id else None,
        "media_id": post_id or None,
        "from_id": str(sender.get("id") or "") or None,
        "username": sender.get("name"),
        "text": value.get("message") or "",
        "created_at": _parse_time(value.get("created_time")) or _utcnow(),
    }


def parse_webhook(body: dict) -> list[dict]:
    out = []
    obj = (body or {}).get("object")
    for entry in (body or {}).get("entry") or []:
        for change in entry.get("changes") or []:
            field, value = change.get("field"), change.get("value")
            c = None
            if obj == "instagram" and field in ("comments", "live_comments"):
                c = from_ig_change(value)
                if c and entry.get("id"):
                    c["account_id"] = str(entry["id"])
            elif obj == "page" and field == "feed":
                c = from_fb_change(value)
            if c and c.get("comment_id"):
                out.append(c)
    return out


def signature_ok(raw: bytes, header: str | None, secret: str) -> bool:
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


async def webhook_verify(request: web.Request):
    q = request.query
    if q.get("hub.mode") == "subscribe" and VERIFY_TOKEN and \
            hmac.compare_digest(q.get("hub.verify_token", ""), VERIFY_TOKEN):
        return web.Response(text=q.get("hub.challenge", ""))
    return web.Response(status=403, text="forbidden")


async def webhook_receive(request: web.Request):
    raw = await request.read()
    if not APP_SECRET:
        return web.Response(status=503, text="META_APP_SECRET is not set")
    if not signature_ok(raw, request.headers.get("X-Hub-Signature-256"), APP_SECRET):
        return web.Response(status=403, text="bad signature")
    try:
        body = json.loads(raw.decode("utf-8"))
    except ValueError:
        return web.Response(status=400, text="bad json")
    comments = parse_webhook(body)
    bot = request.app.get("bot")
    try:
        await database.mark_meta_comments_state(webhook=True)
    except Exception:
        logger.warning("webhook mark failed", exc_info=True)
    for c in comments:
        _spawn(ingest(bot, c, source="webhook"))
    return web.Response(text="ok")


def setup_routes(app: web.Application) -> None:
    app.router.add_get("/meta/webhook", webhook_verify)
    app.router.add_post("/meta/webhook", webhook_receive)


# ─────────────────────────────── ingesting ──────────────────────────────────

_QUESTION_RE = re.compile(
    r"\?|narx|qancha|qanch|necha|manzil|adres|qayer|bormi|bor mi|yetkaz|dostav|olsa|buyurtma|"
    r"нарх|қанча|канча|неча|манзил|адрес|қаер|каер|борми|етказ|доставк|сколько|цена|где|есть ли",
    re.IGNORECASE)
_AUTO_DIRECT_RE = re.compile(r"direct|директ", re.IGNORECASE)


def needs_answer_after_auto(text: str | None, our_reply: str | None) -> bool:
    """Savolga faqat «Direct'ga yozdik» degan avtomatik javob bo'lgan — ochiq
    javob ham kerak (boshqalar ham shu savolni o'qiydi)."""
    return bool(our_reply and _AUTO_DIRECT_RE.search(our_reply) and _QUESTION_RE.search(text or ""))


async def _enrich(session, ident: dict, c: dict) -> dict:
    c = dict(c)
    ad = _object_ads.get(c.get("media_id") or "")
    if ad and not c.get("ad_id"):
        c["ad_id"], c["ad_name"] = ad
    if c.get("ad_id") and not c.get("ad_name"):
        c["ad_name"] = await _ad_name(session, c["ad_id"])
    c["post_link"] = await _permalink(session, ident, c)
    return c


async def ingest(bot: Bot | None, c: dict, *, source: str, our_reply: str | None = None,
                 backfill: bool = False) -> dict | None:
    """Yangi izohni saqlash va adminlarga yuborish. Allaqachon bo'lsa — None."""
    if is_own(c, _identity):
        return None
    try:
        async with aiohttp.ClientSession() as session:
            ident = await identity(session)
            if is_own(c, ident):
                return None
            c = await _enrich(session, ident, c)
    except GraphError as e:
        logger.warning("comment %s: Graph lookup failed: %s", c.get("comment_id"), e)
    c.pop("account_id", None)
    c["source"] = source
    if our_reply is not None and not needs_answer_after_auto(c.get("text"), our_reply):
        # Bizdan javob olgan (qo'lda yoki Business Suite'dan) — faqat tarix uchun.
        c.update(status="answered", reply_text=our_reply, reply_kind="public")
        await database.insert_meta_comment(c)
        return None
    if our_reply is not None:
        c["note"] = f"⚠️ Faqat avtomatik javob olgan: «{our_reply[:120]}»"
    row = await database.insert_meta_comment(c)
    if row is None:
        return None
    fresh = not backfill and (row.get("created_at") or _utcnow()) > _utcnow() - FRESH_FOR
    await route(bot, row, fresh=fresh and our_reply is None)
    return row


async def route(bot: Bot | None, row: dict, fresh: bool) -> None:
    state = await database.get_meta_comments_state()
    mode = state.get("ai_mode") or "avto"
    d = None
    if mode != "off" and (row.get("text") or "").strip():
        try:
            d = await comment_ai.draft(row, comment_ai.kb_with_defaults(state.get("kb")))
        except Exception:
            logger.exception("comment AI draft failed for %s", row.get("comment_id"))
    action = comment_ai.decide(d.category, d.confident, mode, fresh) if d else "approve"
    if d:
        row = await database.update_meta_comment(
            row["id"], category=d.category, ai_draft=d.reply or None, ai_model=d.model) or row
    if action == "auto" and d and d.reply:
        _spawn(auto_send(bot, row["id"]))
        return
    await send_cards(bot, row)


async def auto_send(bot: Bot | None, key: int, delay: float | None = None) -> None:
    await asyncio.sleep(AI_DELAY if delay is None else delay)
    row = await database.get_meta_comment(key)
    if not row or row["status"] != "new" or not row.get("ai_draft"):
        return
    try:
        async with aiohttp.ClientSession() as session:
            ident = await identity(session)
            other = await our_existing_reply(session, ident, row)
            if other is not None:
                row = await database.update_meta_comment(
                    key, note=f"⚠️ Boshqa avtomat allaqachon javob yozgan: «{other[:120]}» — AI yozmadi")
                await send_cards(bot, row)
                return
            if not await database.claim_meta_comment(key, ("new",), "sending"):
                return
            text = comment_ai.in_script_of(row.get("text"), row["ai_draft"])
            await reply_public(session, ident, row, text)
    except GraphError as e:
        await database.claim_meta_comment(key, ("sending",), "new")
        row = await database.update_meta_comment(key, note=f"❌ AI yubora olmadi: {e}")
        await send_cards(bot, row)
        return
    row = await database.update_meta_comment(key, status="ai_answered", reply_text=text, reply_kind="public")
    await send_cards(bot, row)


# ─────────────────────────────── the card ───────────────────────────────────

def _esc(v) -> str:
    return html.escape(str(v or ""), quote=False)


async def _who(user_id) -> str:
    if not user_id:
        return ""
    try:
        u = await database.get_user(int(user_id))
        return (u or {}).get("full_name") or str(user_id)
    except Exception:
        return str(user_id)


def _private_allowed(row: dict) -> bool:
    created = row.get("created_at") or row.get("received_at") or _utcnow()
    return not row.get("private_sent") and created > _utcnow() - PRIVATE_WINDOW


async def render(row: dict) -> tuple[str, InlineKeyboardMarkup | None]:
    platform = "Instagram" if row["platform"] == "ig" else "Facebook"
    kind = "REKLAMA" if row.get("ad_id") or row.get("ad_name") else "post"
    status = row.get("status") or "new"
    title = "💬 <b>Yangi izoh</b>" if status in OPEN or status == "sending" else "💬 Izoh"
    lines = [f"{title} · {platform} · {kind}"]
    if row.get("ad_name"):
        lines.append(f"📣 Reklama: {_esc(row['ad_name'])}")
    who = row.get("username") or "—"
    lines.append(f"👤 {'@' if row['platform'] == 'ig' and row.get('username') else ''}{_esc(who)}")
    lines.append(f"«{_esc((row.get('text') or '').strip()[:TEXT_MAX])}»")
    if row.get("post_link"):
        lines.append(f"🔗 <a href=\"{html.escape(row['post_link'])}\">post havolasi</a>")
    if row.get("category"):
        lines.append(f"🏷 {comment_ai.CATEGORY_LABELS.get(row['category'], row['category'])}")
    if row.get("note"):
        lines.append(_esc(row["note"]))

    rows: list[list[InlineKeyboardButton]] = []
    key = row["id"]
    if status in OPEN:
        if row.get("ai_draft"):
            lines += ["", f"🤖 <b>AI loyiha</b> ({_esc(row.get('ai_model') or 'AI')}):",
                      f"«{_esc(row['ai_draft'])}»"]
            rows.append([InlineKeyboardButton(text="✅ Yuborish", callback_data=f"mc:ok:{key}"),
                         InlineKeyboardButton(text="✏️ Tahrirlash", callback_data=f"mc:ed:{key}")])
        elif row.get("category") != "spam":
            rows.append([InlineKeyboardButton(text="✍️ Javob yozish", callback_data=f"mc:ed:{key}")])
        if _private_allowed(row) and row.get("category") != "spam":
            label = "📩 Direct'ga yuborish" if row.get("ai_draft") else "📩 Shaxsiy xabar"
            rows.append([InlineKeyboardButton(text=label, callback_data=f"mc:dm:{key}")])
        if row.get("category") != "spam":
            rows.append([InlineKeyboardButton(text="💰 Narx", callback_data=f"mc:t:narx:{key}"),
                         InlineKeyboardButton(text="🚚 Yetkazish", callback_data=f"mc:t:yetkazish:{key}"),
                         InlineKeyboardButton(text="🤖 Bot", callback_data=f"mc:t:bot:{key}")])
        rows.append([InlineKeyboardButton(text="🙈 Yashirish", callback_data=f"mc:hide:{key}"),
                     InlineKeyboardButton(text="✅ Ko'rildi", callback_data=f"mc:seen:{key}"),
                     InlineKeyboardButton(text="❌ Bekor", callback_data=f"mc:no:{key}")])
        lines += ["", "<i>Javob yozish uchun shu xabarga reply qiling.</i>"]
    else:
        label = DONE_LABELS.get(status, status)
        by = await _who(row.get("replied_by"))
        when = row.get("replied_at")
        stamp = (when + timedelta(hours=5)).strftime("%d.%m %H:%M") if when else ""
        lines += ["", f"<b>{label}</b>" + (f" — {_esc(by)}" if by else "") + (f", {stamp}" if stamp else "")]
        if row.get("reply_text"):
            kind_txt = "📩 shaxsiy" if row.get("reply_kind") == "private" else "ochiq"
            lines.append(f"↪️ ({kind_txt}) «{_esc(row['reply_text'][:REPLY_MAX])}»")
        extra = []
        if _private_allowed(row) and status != "hidden":
            extra.append(InlineKeyboardButton(text="📩 Shaxsiy xabar", callback_data=f"mc:dm:{key}"))
        if not row.get("hidden"):
            extra.append(InlineKeyboardButton(text="🙈 Yashirish", callback_data=f"mc:hide:{key}"))
        if extra:
            rows.append(extra)
    if row.get("private_sent") and row.get("reply_kind") != "private":
        lines.append("📩 Shaxsiy xabar ham yuborilgan")
    return "\n".join(lines), (InlineKeyboardMarkup(inline_keyboard=rows) if rows else None)


async def send_cards(bot: Bot | None, row: dict | None) -> None:
    """Yangi bo'lsa — har adminga yuboradi; bo'lsa — hammasini yangilaydi."""
    if bot is None or not row:
        return
    text, kb = await render(row)
    sent = list(row.get("tg_messages") or [])
    if not sent:
        for admin_id in ADMIN_IDS:
            try:
                msg = await bot.send_message(admin_id, text, reply_markup=kb, parse_mode="HTML",
                                             disable_web_page_preview=True)
                sent.append({"c": admin_id, "m": msg.message_id})
            except Exception as exc:
                logger.info("comment card → %s failed: %s", admin_id, exc)
        await database.update_meta_comment(row["id"], tg_messages=sent)
        return
    for ref in sent:
        try:
            await bot.edit_message_text(text, chat_id=ref["c"], message_id=ref["m"], reply_markup=kb,
                                        parse_mode="HTML", disable_web_page_preview=True)
        except Exception as exc:
            if "not modified" not in str(exc):
                logger.info("comment card edit %s failed: %s", ref, exc)


# ───────────────────────────── admin actions ────────────────────────────────

async def _kb() -> dict:
    return comment_ai.kb_with_defaults((await database.get_meta_comments_state()).get("kb"))


async def answer(bot: Bot, key: int, text: str, admin_id: int, private: bool = False) -> str | None:
    """Admin nomidan javob. Xato matni yoki None (muvaffaqiyat)."""
    row = await database.get_meta_comment(key)
    if not row:
        return "Izoh topilmadi"
    text = (text or "").strip()
    if not text:
        return "Matn bo'sh"
    if private:
        if not _private_allowed(row):
            return "Shaxsiy xabar faqat bir marta va 7 kun ichida yuboriladi"
        try:
            async with aiohttp.ClientSession() as session:
                ident = await identity(session)
                await reply_private(session, ident, row, text)
        except GraphError as e:
            return f"Meta: {e}"
        fields = {"private_sent": True, "replied_by": admin_id}
        if row["status"] in OPEN:
            fields.update(status="answered", reply_text=text, reply_kind="private")
        row = await database.update_meta_comment(key, **fields)
        await send_cards(bot, row)
        return None
    if not await database.claim_meta_comment(key, OPEN + ("answered", "ai_answered", "seen", "skipped"), "sending"):
        return "Bu izohga hozir javob yuborilyapti yoki u yashirilgan"
    prev = row["status"]
    try:
        async with aiohttp.ClientSession() as session:
            ident = await identity(session)
            await reply_public(session, ident, row, text)
    except GraphError as e:
        await database.claim_meta_comment(key, ("sending",), prev)
        return f"Meta: {e}"
    row = await database.update_meta_comment(key, status="answered", reply_text=text,
                                             reply_kind="public", replied_by=admin_id)
    await send_cards(bot, row)
    return None


async def _cmd_target(message: Message) -> dict | bool:
    """Admin kartochkaga yoki «matnni yozing» so'roviga reply qildimi."""
    if not message.reply_to_message or not is_admin(getattr(message.from_user, "id", None)):
        return False
    ref = (message.chat.id, message.reply_to_message.message_id)
    if ref in _prompts:
        key, mode = _prompts[ref]
        return {"mc_key": key, "mc_mode": mode}
    try:
        row = await database.find_meta_comment_by_card(*ref)
    except Exception:
        return False
    return {"mc_key": row["id"], "mc_mode": "public"} if row else False


@router.message(F.text, _cmd_target)
async def on_reply(message: Message, mc_key: int, mc_mode: str):
    err = await answer(message.bot, mc_key, message.text, message.from_user.id, private=(mc_mode == "private"))
    _prompts.pop((message.chat.id, message.reply_to_message.message_id), None)
    if err:
        await message.reply(f"❌ Yuborilmadi: {_esc(err)}", parse_mode="HTML")
    else:
        await message.reply("✅ Yuborildi" + (" (shaxsiy xabar)" if mc_mode == "private" else " (izohga javob)"))


@router.callback_query(F.data.startswith("mc:"))
async def on_button(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    parts = callback.data.split(":")
    try:
        key = int(parts[-1])
    except ValueError:
        await callback.answer("❌")
        return
    action = parts[1]
    row = await database.get_meta_comment(key)
    if not row:
        await callback.answer("Izoh topilmadi", show_alert=True)
        return
    bot = callback.bot
    uid = callback.from_user.id

    if action == "ok":
        if not row.get("ai_draft"):
            await callback.answer("AI loyihasi yo'q", show_alert=True)
            return
        err = await answer(bot, key, comment_ai.in_script_of(row.get("text"), row["ai_draft"]), uid)
        await callback.answer(f"❌ {err}" if err else "✅ Yuborildi", show_alert=bool(err))
    elif action == "t":
        kb = await _kb()
        text = (kb.get(f"tpl_{parts[2]}") or "").strip()
        if not text:
            await callback.answer("Shablon bo'sh — /izoh_bilim", show_alert=True)
            return
        err = await answer(bot, key, comment_ai.in_script_of(row.get("text"), text), uid)
        await callback.answer(f"❌ {err}" if err else "✅ Shablon yuborildi", show_alert=bool(err))
    elif action in ("ed", "dm"):
        private = action == "dm"
        if private and row.get("ai_draft") and row["status"] in OPEN:
            err = await answer(bot, key, comment_ai.in_script_of(row.get("text"), row["ai_draft"]), uid,
                               private=True)
            await callback.answer(f"❌ {err}" if err else "📩 Shaxsiy xabar yuborildi", show_alert=bool(err))
            return
        prompt = await bot.send_message(
            callback.message.chat.id,
            ("📩 Shaxsiy xabar matnini" if private else "✍️ Izohga javob matnini") +
            f" shu xabarga reply qilib yozing (@{_esc(row.get('username') or '—')}):",
            reply_markup=ForceReply(selective=True), parse_mode="HTML")
        _prompts[(prompt.chat.id, prompt.message_id)] = (key, "private" if private else "public")
        await callback.answer()
    elif action == "hide":
        try:
            async with aiohttp.ClientSession() as session:
                ident = await identity(session)
                await hide(session, ident, row)
        except GraphError as e:
            await callback.answer(f"❌ Meta: {e}"[:190], show_alert=True)
            return
        fields = {"hidden": True}
        if row["status"] in OPEN:
            fields.update(status="hidden", replied_by=uid)
        await send_cards(bot, await database.update_meta_comment(key, **fields))
        await callback.answer("🙈 Yashirildi")
    elif action in ("seen", "no"):
        to = "seen" if action == "seen" else "skipped"
        if await database.claim_meta_comment(key, OPEN, to):
            await send_cards(bot, await database.update_meta_comment(key, replied_by=uid))
        await callback.answer("👀 Ko'rildi" if to == "seen" else "❌ Bekor qilindi")
    else:
        await callback.answer()


# ─────────────────────────────── sync / backfill ────────────────────────────

async def _ad_targets(session) -> list[dict]:
    """Reklamalar → ularning IG media va FB post nusxalari (ads_read tokeni)."""
    import meta_ads
    await meta_ads.load_token()
    if not meta_ads.is_enabled():
        return []
    out = []
    fields = "name,effective_status,creative{effective_instagram_media_id,effective_object_story_id}"
    statuses = json.dumps(["ACTIVE", "PAUSED", "CAMPAIGN_PAUSED", "ADSET_PAUSED", "IN_PROCESS", "WITH_ISSUES"])
    for account in await meta_ads.account_ids(session):
        try:
            data = await meta_ads._get(session, f"act_{account}/ads", fields=fields,
                                       effective_status=statuses, limit=MAX_ADS)
        except Exception as e:
            logger.info("comments sync: ads of %s unreadable: %s", account, e)
            continue
        for ad in data.get("data", []):
            creative = ad.get("creative") or {}
            _ad_names[str(ad.get("id"))] = ad.get("name")
            if creative.get("effective_instagram_media_id"):
                out.append({"platform": "ig", "object": str(creative["effective_instagram_media_id"]),
                            "ad_id": str(ad.get("id")), "ad_name": ad.get("name")})
            if creative.get("effective_object_story_id"):
                out.append({"platform": "fb", "object": str(creative["effective_object_story_id"]),
                            "ad_id": str(ad.get("id")), "ad_name": ad.get("name")})
    return out


async def _organic_targets(session, ident: dict) -> list[dict]:
    out = []
    try:
        if ident.get("ig_id"):
            data = await _graph(session, "GET", f"{ident['ig_id']}/media", ident["page_token"],
                                {"fields": "id,permalink", "limit": ORGANIC_POSTS})
            out += [{"platform": "ig", "object": str(m["id"]), "link": m.get("permalink")}
                    for m in data.get("data", [])]
    except GraphError as e:
        logger.info("comments sync: IG media unreadable: %s", e)
    try:
        data = await _graph(session, "GET", f"{PAGE_ID}/posts", ident["page_token"],
                            {"fields": "id,permalink_url", "limit": ORGANIC_POSTS})
        out += [{"platform": "fb", "object": str(p["id"]), "link": p.get("permalink_url")}
                for p in data.get("data", [])]
    except GraphError as e:
        logger.info("comments sync: page posts unreadable: %s", e)
    return out


def comments_from_listing(target: dict, data: dict, ident: dict) -> list[tuple[dict, str | None]]:
    """(izoh, bizning javobimiz yoki None) — top-level izohlar va foydalanuvchi
    javoblari (bizning hisobdan emas)."""
    out = []
    ig = target["platform"] == "ig"
    for item in data.get("data", []):
        sender = item.get("from") or {}
        base = {
            "platform": target["platform"], "media_id": target["object"],
            "ad_id": target.get("ad_id"), "ad_name": target.get("ad_name"),
            "post_link": target.get("link"),
        }
        c = dict(base, comment_id=str(item.get("id")), parent_id=None,
                 from_id=str(sender.get("id") or "") or None,
                 username=item.get("username") if ig else sender.get("name"),
                 text=item.get("text") if ig else item.get("message"),
                 created_at=_parse_time(item.get("timestamp") if ig else item.get("created_time")))
        replies = ((item.get("replies") if ig else item.get("comments")) or {}).get("data", [])
        ours, theirs = None, []
        for r in replies:
            rs = r.get("from") or {}
            rc = dict(base, comment_id=str(r.get("id")), parent_id=c["comment_id"],
                      from_id=str(rs.get("id") or "") or None,
                      username=r.get("username") if ig else rs.get("name"),
                      text=r.get("text") if ig else r.get("message"),
                      created_at=_parse_time(r.get("timestamp") if ig else r.get("created_time")))
            if is_own(rc, ident):
                ours = ours if ours is not None else (rc.get("text") or "")
            else:
                theirs.append((rc, None))
        if not is_own(c, ident):
            out.append((c, ours))
        out += theirs
    return out


async def sync(bot: Bot | None) -> dict:
    """Reklama nusxalari va oxirgi postlar izohlarini o'qiydi. Birinchi marta —
    eski izohlarni yuklash (javobsizlari kartochka bo'lib keladi, lekin AI
    o'zi yozmaydi)."""
    state = await database.get_meta_comments_state()
    first = not state.get("backfilled")
    stats = {"targets": 0, "seen": 0, "new": 0, "errors": 0}
    async with aiohttp.ClientSession() as session:
        ident = await identity(session, force=True)
        targets, known = [], set()
        for t in await _ad_targets(session) + await _organic_targets(session, ident):
            if t["object"] in known:
                continue
            known.add(t["object"])
            targets.append(t)
            if t.get("ad_id"):
                _object_ads[t["object"]] = (t["ad_id"], t.get("ad_name"))
        stats["targets"] = len(targets)
        for t in targets:
            try:
                if t["platform"] == "ig":
                    if not t.get("link"):
                        t["link"] = (await _graph(session, "GET", t["object"], ident["page_token"],
                                                  {"fields": "permalink"})).get("permalink")
                    data = await _graph(session, "GET", f"{t['object']}/comments", ident["page_token"],
                                        {"fields": "id,text,username,from,timestamp,"
                                                   "replies{id,text,username,from,timestamp}", "limit": 50})
                else:
                    t["link"] = t.get("link") or f"https://www.facebook.com/{t['object']}"
                    data = await _graph(session, "GET", f"{t['object']}/comments", ident["page_token"],
                                        {"fields": "id,message,from,created_time,"
                                                   "comments{id,message,from,created_time}",
                                         "filter": "toplevel", "limit": 100})
            except GraphError as e:
                stats["errors"] += 1
                logger.info("comments sync: %s %s unreadable: %s", t["platform"], t["object"], e)
                continue
            for c, ours in comments_from_listing(t, data, ident):
                stats["seen"] += 1
                if c.get("created_at") and c["created_at"] < _utcnow() - timedelta(days=60):
                    continue
                row = await ingest(bot, c, source="backfill" if first else "sync",
                                   our_reply=ours, backfill=first)
                stats["new"] += bool(row)
    await database.mark_meta_comments_state(backfilled=True, synced=True)
    return stats


async def scheduler_loop(bot: Bot) -> None:
    await asyncio.sleep(30)
    logger.info("Comments loop started (every %ds)", SYNC_EVERY)
    while True:
        try:
            await load_token()
            if token():
                stats = await sync(bot)
                logger.info("comments sync: %s", stats)
        except GraphError as e:
            logger.warning("comments sync: %s", e)
        except Exception:
            logger.exception("comments sync failed")
        await asyncio.sleep(SYNC_EVERY)


# ─────────────────────────────── commands ───────────────────────────────────

async def status_text() -> str:
    await load_token()
    state = await database.get_meta_comments_state()
    counts = await database.meta_comment_counts()
    open_ig = sum(n for (p, s), n in counts.items() if p == "ig" and s in OPEN)
    open_fb = sum(n for (p, s), n in counts.items() if p == "fb" and s in OPEN)
    ai_n = sum(n for (p, s), n in counts.items() if s == "ai_answered")
    done = sum(n for (p, s), n in counts.items() if s in ("answered", "ai_answered"))
    lines = ["💬 <b>Instagram/Facebook izohlari</b>", "",
             f"⏳ Javobsiz: <b>{open_ig + open_fb}</b> (Instagram {open_ig} · Facebook {open_fb})",
             f"✅ Javob berilgan: {done} (shundan AI: {ai_n})", ""]
    if token():
        lines.append("🔑 Token: bor")
    else:
        lines.append("🔑 Token: <b>yo'q</b> — /izoh_token &lt;token&gt; (bot bilan shaxsiy chatda)")
    mode = state.get("ai_mode") or "avto"
    mode_txt = {"avto": "avto (rahmat va aniq javoblarni o'zi yuboradi)",
                "tasdiq": "faqat loyiha — hammasi admin tasdig'i bilan", "off": "o'chiq"}[mode]
    label = await comment_ai.provider_label()
    ai_key = f" · {label}" if label else " — ⚠️ AI kaliti yo'q (/ai_kalit)"
    lines.append(f"🤖 AI: {mode_txt}{ai_key} · /izoh_ai")
    hook = state.get("last_webhook_at")
    lines.append("📡 Webhook: " + ((hook + timedelta(hours=5)).strftime("oxirgi %d.%m %H:%M") if hook else
                                  ("sozlanmagan" if not (APP_SECRET and VERIFY_TOKEN) else "hali kelmadi")))
    synced = state.get("last_sync_at")
    lines.append("🔄 Tekshiruv: " + ((synced + timedelta(hours=5)).strftime("oxirgi %d.%m %H:%M")
                                    if synced else "hali bo'lmagan") + f", har {SYNC_EVERY // 60} daqiqada")
    pending = await database.list_meta_comments(OPEN, 10)
    if pending:
        lines += ["", "<b>Javobsizlar:</b>"]
        for r in pending:
            link = f" <a href=\"{html.escape(r['post_link'])}\">🔗</a>" if r.get("post_link") else ""
            lines.append(f"• {'📷' if r['platform'] == 'ig' else '📘'} {_esc(r.get('username') or '—')}: "
                         f"«{_esc((r.get('text') or '')[:60])}»{link}")
    lines += ["", "Bilim bazasi va shablonlar: /izoh_bilim"]
    return "\n".join(lines)


def status_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Hozir tekshirish", callback_data="mcs:sync"),
         InlineKeyboardButton(text="📤 Javobsizlarni qayta yuborish", callback_data="mcs:resend")],
        [InlineKeyboardButton(text="🔙 Reklama menyusi", callback_data="admin_menu:ads")],
    ])


@router.message(Command("izohlar"))
async def cmd_status(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer(await status_text(), parse_mode="HTML", reply_markup=status_keyboard(),
                         disable_web_page_preview=True)


@router.callback_query(F.data.startswith("mcs:"))
async def on_status_button(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return
    action = callback.data.split(":", 1)[1]
    if action == "show":
        await callback.message.answer(await status_text(), parse_mode="HTML", reply_markup=status_keyboard(),
                                      disable_web_page_preview=True)
        await callback.answer()
    elif action == "sync":
        await load_token()
        if not token():
            await callback.answer("Token yo'q — /izoh_token", show_alert=True)
            return
        await callback.answer("🔄 Tekshirilyapti…")
        try:
            stats = await sync(callback.bot)
            await callback.message.answer(
                f"🔄 Tekshirildi: {stats['targets']} ta post/reklama, {stats['seen']} ta izoh, "
                f"yangi: <b>{stats['new']}</b>" + (f", o'qib bo'lmadi: {stats['errors']}" if stats["errors"] else ""),
                parse_mode="HTML")
        except GraphError as e:
            await callback.message.answer(f"❌ Meta: <code>{_esc(e)}</code>", parse_mode="HTML")
    elif action == "resend":
        rows = await database.list_meta_comments(OPEN, 20)
        for r in rows:
            await database.update_meta_comment(r["id"], tg_messages=[])
            r["tg_messages"] = []
            await send_cards(callback.bot, r)
        await callback.answer(f"📤 {len(rows)} ta kartochka qayta yuborildi")
    else:
        await callback.answer()


@router.message(Command("izoh_token"))
async def cmd_token(message: Message):
    if not is_admin(message.from_user.id):
        return
    if message.chat.type != "private":
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer("⚠️ Tokenni faqat bot bilan shaxsiy chatda yuboring.")
        return
    arg = (message.text or "").split(maxsplit=1)[1].strip() if len((message.text or "").split()) > 1 else ""
    if not arg:
        await message.answer(
            "🔑 <b>Izohlar tokeni</b>\n\n"
            "Reklama statistikasi tokeniga tegmang — bu alohida token: system user'ga sahifa "
            "«Keto market.uz» va Instagram @ketoshop.uz ulanadi (izohlarni boshqarish huquqi bilan), "
            "ruxsatlar: instagram_basic, instagram_manage_comments, instagram_manage_messages, "
            "pages_show_list, pages_read_engagement, pages_manage_engagement, pages_manage_metadata, "
            "pages_messaging.\n\n"
            "Yuborish: <code>/izoh_token TOKEN</code> — xabar darhol o'chiriladi.\n"
            "O'chirish: <code>/izoh_token off</code>\n\n" + ("Hozir: bor ✅" if token() else "Hozir: yo'q"),
            parse_mode="HTML")
        return
    try:
        await message.delete()
        deleted = True
    except Exception:
        deleted = False
    global _db_token, _identity
    if arg.lower() in ("off", "o'chir", "ochir", "-"):
        await database.set_meta_comments_token(None, message.from_user.id)
        _db_token, _identity = "", {}
        await message.answer("🗑 Izohlar tokeni o'chirildi.")
        return
    candidate = arg.split()[0]
    try:
        async with aiohttp.ClientSession() as session:
            ident = await identity(session, access_token=candidate)
    except GraphError as e:
        await message.answer(f"❌ Token ishlamadi, saqlanmadi:\n<code>{_esc(e)}</code>"
                             + await token_hints(candidate), parse_mode="HTML")
        return
    except Exception:
        logger.exception("comments token check failed")
        await message.answer("❌ Meta bilan bog'lanib bo'lmadi — birozdan keyin qayta yuboring.")
        return
    await database.set_meta_comments_token(candidate, message.from_user.id)
    _db_token, _identity = candidate, ident
    logger.info("Meta comments token set by admin %s", message.from_user.id)
    lines = ["✅ Izohlar tokeni saqlandi.",
             f"📘 Sahifa: {_esc(ident.get('page_name') or '?')}",
             f"📷 Instagram: {'@' + _esc(ident['ig_username']) if ident.get('ig_username') else '❌ ulanmagan'}",
             "", "Birinchi tekshiruv boshlandi — eski javobsiz izohlar kartochka bo'lib keladi. Holat: /izohlar"]
    if not deleted:
        lines += ["", "⚠️ Tokenli xabarni o'chira olmadim — uni qo'lda o'chiring."]
    await message.answer("\n".join(lines), parse_mode="HTML")
    _spawn(_first_sync(message.bot))


NEEDED_PERMISSIONS = ("pages_show_list", "pages_read_engagement", "pages_manage_engagement",
                      "pages_manage_metadata", "pages_messaging", "instagram_basic",
                      "instagram_manage_comments", "instagram_manage_messages")


async def token_hints(candidate: str) -> str:
    """Meta '(#100) … requires pages_read_engagement' degan bitta xabarni ikki
    sababga beradi (2026-11-11 da egasi aynan shuni oldi): tokenda ruxsat
    yo'q, yoki sahifa tizim foydalanuvchisiga tayinlanmagan. Qaysi biri
    ekanini aytamiz — nimani tuzatishni bilsin."""
    lines = []
    try:
        async with aiohttp.ClientSession() as session:
            try:
                perms = await _graph(session, "GET", "me/permissions", candidate)
                granted = {p.get("permission") for p in perms.get("data", []) if p.get("status") == "granted"}
                missing = [p for p in NEEDED_PERMISSIONS if p not in granted]
                if missing:
                    lines.append("🔒 Tokenda yo'q ruxsatlar: <code>" + ", ".join(missing) + "</code> — "
                                 "token yaratishda shularga ham belgi qo'ying.")
            except GraphError:
                pass
            try:
                accounts = await _graph(session, "GET", "me/accounts", candidate, {"fields": "id,name", "limit": 100})
                pages = {str(a.get("id")): a.get("name") for a in accounts.get("data", [])}
                if PAGE_ID not in pages:
                    seen = ", ".join(_esc(n or i) for i, n in pages.items()) or "hech qaysi"
                    lines.append("📘 «Keto market.uz» sahifasi bu tokenga ulanmagan (token ko'rayotgan sahifalar: "
                                 f"{seen}). Business sozlamalarida tizim foydalanuvchisiga sahifani aktiv "
                                 "sifatida tayinlang (to'liq boshqaruv), keyin tokenni qayta yarating.")
            except GraphError:
                pass
    except Exception:
        logger.info("token hints failed", exc_info=True)
        return ""
    if not lines:
        return ""
    return "\n\n" + "\n".join(lines) + "\n\nTuzatgach, yangi tokenni yana <code>/izoh_token TOKEN</code> bilan yuboring."


async def _first_sync(bot: Bot) -> None:
    try:
        await sync(bot)
    except Exception:
        logger.exception("first comments sync failed")


@router.message(Command("izoh_ai"))
async def cmd_ai(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) > 1 and parts[1].lower() in comment_ai.AI_MODES:
        await database.set_meta_comments_ai_mode(parts[1].lower())
    mode = (await database.get_meta_comments_state()).get("ai_mode") or "avto"
    label = await comment_ai.provider_label()
    await message.answer(
        f"🤖 <b>Izohlarga AI javob</b>: <b>{mode}</b>"
        + (f" · {html.escape(label)}" if label else "") + "\n\n"
        "<code>/izoh_ai avto</code> — rahmat va bilim bazasida aniq javobi borini o'zi yuboradi, "
        "qolganiga loyiha + tasdiq\n"
        "<code>/izoh_ai tasdiq</code> — hammasiga faqat loyiha, yuborishni admin bosadi\n"
        "<code>/izoh_ai off</code> — AI ishlamaydi, adminlar o'zi yozadi"
        + ("" if label else "\n\n⚠️ AI kaliti yo'q — AI sotuvchidagi GPT kaliti (/ai_kalit) ishlatiladi."),
        parse_mode="HTML")


@router.message(Command("izoh_bilim"))
async def cmd_kb(message: Message):
    if not is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=2)
    state = await database.get_meta_comments_state()
    stored = dict(state.get("kb") or {})
    if len(parts) >= 2:
        key = parts[1].lower()
        if key not in comment_ai.KB_KEYS:
            await message.answer("Bunday bo'lim yo'q. Bo'limlar: " + ", ".join(comment_ai.KB_KEYS))
            return
        value = parts[2].strip() if len(parts) > 2 else ""
        if not value:
            await message.answer(f"Matn yozing: <code>/izoh_bilim {key} …</code> "
                                 f"(asl matnga qaytarish: <code>/izoh_bilim {key} -</code>)", parse_mode="HTML")
            return
        if value == "-":
            stored.pop(key, None)
        else:
            stored[key] = value
        await database.set_meta_comments_kb(stored)
        comment_ai._catalog_cache = (0.0, "")
        await message.answer(f"✅ «{comment_ai.KB_KEYS[key]}» saqlandi.")
        return
    kb = comment_ai.kb_with_defaults(stored)
    empty = "— bo'sh —"
    lines = ["📚 <b>Izohlar uchun bilim bazasi</b> (AI va shablon tugmalari shundan oladi)", ""]
    for key, label in comment_ai.KB_KEYS.items():
        mark = "✏️" if key in stored else "▫️"
        lines.append(f"{mark} <b>{label}</b> (<code>{key}</code>): {_esc(kb.get(key) or empty)}")
    lines += ["", "O'zgartirish: <code>/izoh_bilim kalit yangi matn</code>",
              "Asliga qaytarish: <code>/izoh_bilim kalit -</code>",
              "Narx va mahsulotlar — katalogdan avtomatik (bazadagi narx va qoldiq)."]
    await message.answer("\n".join(lines), parse_mode="HTML")
