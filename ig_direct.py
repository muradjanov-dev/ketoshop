"""
Instagram Direct — har bir xabarga AI javob (egasi, 2026-11-16: "Direct'dagi
birorta xabar ham, birorta izoh ham javobsiz qolmasin. To'g'ri va mantiqiy
javob ber, sotayotgandek emas, lekin sotuvga olib bor. Direct'da mahsulotlar
ro'yxatini ham, chegirmadagilarni alohida ham yubor").

QANDAY ISHLAYDI
  * Tekshiruv — har EVERY soniyada (qulf ostida) sahifaning Instagram
    suhbatlari o'qiladi: GET /{PAGE_ID}/conversations?platform=instagram,
    har biridan oxirgi 10 ta xabar. Webhook shart emas; meta_comments
    webhook'iga Direct xabari kelsa — tekshiruv darhol uyg'otiladi (kick).
  * Javob kerak: suhbatning eng oxirgi xabar(lar)i mijozdan va eng yangisi
    SAFE_WINDOW (23,5 soat) dan yosh. Meta'ning oddiy oynasi — 24 soat;
    undan keyin hech narsa yuborilmaydi (xabar «expired», adminga kartochka).
  * Takror yo'q: har mijoz xabari ig_dm_messages jadvalida (message_id —
    kalit). Javob berilgani qayta ishga tushsa ham qayta javob olmaydi;
    yuborishdan oldin «new» → «sending» atomik egallanadi.
  * Bir nechta tez xabar — bitta javob: eng yangisi QUIET soniyadan eski
    bo'lguncha kutiladi (eng ko'pi MAX_WAIT), keyin hammasiga bitta javob.

JAVOB
  * GPT (comment_ai bilan bir kalit va model): oxirgi ~10 xabar, katalog,
    bilim bazasi, chegirmalar va aksiya. Ovoz — «biz», tabiiy; avval foyda:
    javob va bitta keto/PP maslahat, mahsulot faqat haqiqatan yordam bersa,
    bosimsiz (egasi: "faqat sotuvga yo'naltiraverma, bu qo'pollik").
    Havolalar to'liq (Direct'da bosiladi, @username esa ochilmaydi).
  * Ro'yxat: odam «nimalar bor / narxlar» desa (yoki yangi suhbat salom bilan
    boshlansa) — javobdan keyin alohida xabarlarda: 1) bo'limlar va do'kon
    havolasi, 2) chegirmadagi mahsulotlar (eski → yangi narx); chegirma
    bo'lmasa 2-xabar yo'q. Bir xabar ≤ 1000 belgi, bir navbatda ≤ 3 xabar.
  * Sog'liq, shikoyat, buyurtma muammosi, matnsiz xabar yoki AI ishlamasa —
    iliq «ushlab turuvchi» javob (Telegram bot havolasi, telefon) va
    adminlarga kartochka: odam davom ettiradi.
  * Spam va o'z xabarlarimizga javob yo'q; bir suhbatga soatiga PER_HOUR
    tadan ortiq javob yo'q; bir tekshiruvda PER_TICK suhbat, xabarlar orasida
    tanaffus, Meta tezlik chegarasida kutish. Sarf ai_usage da « · direct» bilan.

BOSHQARUV: /ig_direct (holat), /ig_direct on|off, /ig_direct test (token
suhbatlarni o'qiy oladimi — hech narsa yuborilmaydi).
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import random
import re
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import aiohttp
from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

import comment_ai
import database
import meta_comments as mc
from config import ADMIN_IDS, SUPPORT_PHONES

logger = logging.getLogger(__name__)
router = Router(name="ig_direct")

EVERY = max(30, int(os.getenv("IG_DIRECT_POLL_SECONDS", "60")))
WINDOW = timedelta(hours=24)                  # Meta: oddiy javob oynasi
SAFE_WINDOW = timedelta(hours=23, minutes=30)  # chegaraga yaqinlashmaymiz
QUIET = timedelta(seconds=int(os.getenv("IG_DIRECT_QUIET_SECONDS", "30")))
MAX_WAIT = timedelta(minutes=3)               # tinmay yozayotgan odamga ham shu vaqtda javob
AI_GIVEUP = timedelta(minutes=10)             # AI shuncha javob bermasa — ushlab turuvchi javob
STALE_CLAIM = timedelta(minutes=10)           # «sending» qolib ketgan (qayta ishga tushish)
PER_HOUR = max(1, int(os.getenv("IG_DIRECT_PER_HOUR", "10")))
PER_TICK = 6                                  # bir tekshiruvda ko'pi bilan shuncha suhbatga javob
# Instagram cheklamasin: xabarlar orasida odamdek tanaffus (soniya), tezlik
# chegarasi kelsa — 2, 4, 8 … 32 daqiqa kutish (_set_backoff).
PAUSE = (1.5, 4.0)
MAX_FAILS = 3
CATALOG_EVERY = timedelta(hours=6)            # ro'yxat bir suhbatga 6 soatda bir martadan ko'p emas
HISTORY = 10
TEXT_LIMIT = 1000                             # Instagram: bitta xabar matni
MAX_PARTS = 3                                 # bir navbatda ko'pi bilan 3 xabar
CONV_PAGE = 25
CONV_PAGES = 4
MAX_TOKENS = 2000
USAGE_TAG = " · direct"
CONV_FIELDS = "id,updated_time,participants,messages.limit(10){id,from,to,message,created_time}"

SHOP_LINK = comment_ai.SHOP_LINK
BOT_LINK = "https://t.me/ketoshopbot"
CHANNEL = comment_ai.CHANNEL                  # "@ketoshop_uz"
CHANNEL_LINK = "https://t.me/" + CHANNEL.lstrip("@")
LANGS = ("uz", "uz_cyr", "ru")

OPEN = ("new",)
ANSWERED = ("replied", "held")
HUMAN_INTENTS = {"salomatlik", "shikoyat", "buyurtma_muammo"}
INTENTS = ("salom", "katalog", "mahsulot", "buyurtma", "yetkazish", "manzil", "chegirma", "rahmat",
           "salomatlik", "shikoyat", "buyurtma_muammo", "optom", "spam", "boshqa")
REASONS = {
    "salomatlik": "🩺 Salomatlik savoli",
    "shikoyat": "⚠️ Shikoyat / norozilik",
    "buyurtma_muammo": "📦 Buyurtma muammosi",
    "nontext": "🖼 Matnsiz xabar (rasm, ovoz, stiker yoki ulashilgan post)",
    "ai_down": "🤖 AI javob bera olmadi",
    "unsure": "❓ AI aniq javob topolmadi",
    "closed": "⛔ Meta yuborishga ruxsat bermadi",
    "expired": "⌛ 24 soatlik oyna yopilgan — javob berilmagan",
    "failed": "❌ Yuborib bo'lmadi",
    "throttled": "⏸ Bir soatlik javoblar chegarasi",
}

_lock = asyncio.Lock()
_kick = asyncio.Event()
_errors: deque = deque(maxlen=5)
_backoff: dict = {"until": None, "n": 0}
_failures: Counter = Counter()
_throttle_noted: dict[str, datetime] = {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _tk(dt: datetime | None) -> str:
    return (dt + timedelta(hours=5)).strftime("%d.%m %H:%M") if dt else "—"


def _esc(v) -> str:
    return html.escape(str(v or ""), quote=False)


def _som(n) -> str:
    return f"{int(round(float(n or 0))):,}".replace(",", " ")


class Stop(Exception):
    """Tekshiruvni shu yerda to'xtatish (tezlik chegarasi yoki ruxsat yo'q)."""


# ─────────────────────────────── jadval ─────────────────────────────────────

_table_ready = False


async def _ensure(conn) -> None:
    global _table_ready
    if _table_ready:
        return
    # Bitta mijoz xabari — bitta qator. Holatlar: new (javob kutyapti),
    # sending (yuborilyapti), replied (AI javob berdi), held (ushlab turuvchi
    # javob + adminga kartochka), human (bizdan kimdir Instagram'da yozgan),
    # spam, closed (suhbat tabiiy yakunlangan), expired (24 soat o'tgan),
    # unavailable (Meta rad etdi).
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS ig_dm_messages (
            message_id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL,
            from_id TEXT,
            username TEXT,
            text TEXT,
            created_at TIMESTAMP,
            seen_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
            status TEXT NOT NULL DEFAULT 'new',
            intent TEXT,
            reply_text TEXT,
            replied_at TIMESTAMP,
            claimed_at TIMESTAMP,
            catalog_sent BOOLEAN NOT NULL DEFAULT FALSE,
            note TEXT
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ig_dm_conv ON ig_dm_messages(conversation_id, replied_at)")
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ig_dm_status ON ig_dm_messages(status, created_at)")
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS ig_dm_state (
            id INTEGER PRIMARY KEY DEFAULT 1,
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            last_poll_at TIMESTAMP,
            last_ok_at TIMESTAMP,
            last_error TEXT,
            last_error_at TIMESTAMP,
            CONSTRAINT ig_dm_state_single CHECK (id = 1)
        )
    """)
    await conn.execute("INSERT INTO ig_dm_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
    _table_ready = True


async def get_state() -> dict:
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        row = await conn.fetchrow("SELECT * FROM ig_dm_state WHERE id = 1")
    return dict(row) if row else {"enabled": True}


async def set_enabled(on: bool) -> None:
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        await conn.execute("UPDATE ig_dm_state SET enabled = $1 WHERE id = 1", bool(on))


async def note_poll(error: str | None = None) -> None:
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        if error is None:
            await conn.execute("UPDATE ig_dm_state SET last_poll_at = NOW() AT TIME ZONE 'UTC', "
                               "last_ok_at = NOW() AT TIME ZONE 'UTC' WHERE id = 1")
        else:
            await conn.execute("UPDATE ig_dm_state SET last_poll_at = NOW() AT TIME ZONE 'UTC', "
                               "last_error = $1, last_error_at = NOW() AT TIME ZONE 'UTC' WHERE id = 1",
                               error[:500])


async def store_messages(conversation_id: str, rows: list[dict]) -> None:
    """Yangi mijoz xabarlari; bor bo'lsa — tegilmaydi (takror yo'q)."""
    if not rows:
        return
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        await conn.executemany(
            """INSERT INTO ig_dm_messages (message_id, conversation_id, from_id, username, text,
                                           created_at, status)
               VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT (message_id) DO NOTHING""",
            [(r["message_id"], conversation_id, r.get("from_id"), r.get("username"), r.get("text") or "",
              r.get("created_at"), r.get("status") or "new") for r in rows])


async def statuses(message_ids: list[str]) -> dict[str, dict]:
    if not message_ids:
        return {}
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        rows = await conn.fetch("SELECT message_id, status, claimed_at, intent, note, text FROM ig_dm_messages "
                                "WHERE message_id = ANY($1::text[])", list(message_ids))
    return {r["message_id"]: dict(r) for r in rows}


_MARK_FIELDS = ("intent", "reply_text", "replied_at", "claimed_at", "catalog_sent", "note")


async def mark(message_ids: list[str], status: str, from_statuses: tuple, **fields) -> list[str]:
    """`from_statuses` dagi qatorlarni `status` ga o'tkazadi (atomik egallash
    ham shu). Qaysilari o'tganini qaytaradi."""
    if not message_ids:
        return []
    sets, args = ["status = $2"], [list(message_ids), status, list(from_statuses)]
    for key in _MARK_FIELDS:
        if key in fields:
            args.append(fields[key])
            sets.append(f"{key} = ${len(args)}")
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        rows = await conn.fetch(
            f"UPDATE ig_dm_messages SET {', '.join(sets)} "
            f"WHERE message_id = ANY($1::text[]) AND status = ANY($3::text[]) RETURNING message_id", *args)
    return [r["message_id"] for r in rows]


async def replies_since(conversation_id: str, since: datetime) -> int:
    """Shu suhbatga `since` dan beri nechta javob (bitta navbat — bitta replied_at)."""
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        return int(await conn.fetchval(
            "SELECT COUNT(DISTINCT replied_at) FROM ig_dm_messages "
            "WHERE conversation_id = $1 AND status IN ('replied', 'held') AND replied_at > $2",
            conversation_id, since) or 0)


async def catalog_recent(conversation_id: str, since: datetime) -> bool:
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        return bool(await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM ig_dm_messages WHERE conversation_id = $1 "
            "AND catalog_sent AND replied_at > $2)", conversation_id, since))


async def had_reply(conversation_id: str) -> bool:
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        return bool(await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM ig_dm_messages WHERE conversation_id = $1 "
            "AND status IN ('replied', 'held', 'human'))", conversation_id))


_TK_DAY = "(NOW() AT TIME ZONE 'UTC' + INTERVAL '5 hours')::date"


async def day_stats() -> dict:
    """Bugun (Toshkent): nechta xabar keldi, nechta suhbatga javob, odamga
    nechta topshirildi, spam, o'tkazib yuborilgan va hozir navbatda."""
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        row = await conn.fetchrow(f"""
            SELECT
              COUNT(*) FILTER (WHERE (created_at + INTERVAL '5 hours')::date = {_TK_DAY}) AS received,
              COUNT(DISTINCT conversation_id) FILTER (
                  WHERE status IN ('replied', 'held') AND (replied_at + INTERVAL '5 hours')::date = {_TK_DAY})
                  AS conversations,
              COUNT(DISTINCT (conversation_id, replied_at)) FILTER (
                  WHERE status IN ('replied', 'held') AND (replied_at + INTERVAL '5 hours')::date = {_TK_DAY})
                  AS replies,
              COUNT(DISTINCT conversation_id) FILTER (
                  WHERE status = 'held' AND (replied_at + INTERVAL '5 hours')::date = {_TK_DAY}) AS to_human,
              COUNT(*) FILTER (WHERE status = 'spam' AND (created_at + INTERVAL '5 hours')::date = {_TK_DAY})
                  AS spam,
              COUNT(*) FILTER (WHERE status IN ('expired', 'unavailable')
                               AND (created_at + INTERVAL '5 hours')::date = {_TK_DAY}) AS missed,
              COUNT(*) FILTER (WHERE status IN ('new', 'sending')) AS pending
            FROM ig_dm_messages""")
    return {k: int(v or 0) for k, v in dict(row).items()} if row else {}


async def recent_replies(limit: int = 3) -> list[dict]:
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        rows = await conn.fetch("""
            SELECT * FROM (
                SELECT DISTINCT ON (conversation_id, replied_at)
                       conversation_id, replied_at, username, text, reply_text, status
                  FROM ig_dm_messages
                 WHERE status IN ('replied', 'held') AND replied_at IS NOT NULL
                 ORDER BY conversation_id, replied_at, created_at DESC
            ) t ORDER BY replied_at DESC LIMIT $1""", limit)
    return [dict(r) for r in rows]


# ─────────────────────────────── Graph ──────────────────────────────────────

def parse_conversation(raw: dict, ident: dict) -> dict | None:
    """Graph suhbati → {conversation_id, updated_at, customer_id, username,
    messages (eskidan yangiga, har birida ours)}. Graph xabarlarni yangidan
    eskiga beradi."""
    if not isinstance(raw, dict) or not raw.get("id"):
        return None
    ig_id = str(ident.get("ig_id") or "")
    ig_user = (ident.get("ig_username") or "").lower()

    def ours(who: dict) -> bool:
        return bool((ig_id and str(who.get("id") or "") == ig_id) or
                    (ig_user and (who.get("username") or "").lower() == ig_user))

    msgs = []
    for m in reversed((raw.get("messages") or {}).get("data") or []):
        who = m.get("from") or {}
        if not m.get("id"):
            continue
        msgs.append({"message_id": str(m["id"]), "from_id": str(who.get("id") or ""),
                     "username": who.get("username"), "text": (m.get("message") or "").strip(),
                     "created_at": mc._parse_time(m.get("created_time")), "ours": ours(who)})
    msgs.sort(key=lambda m: m["created_at"] or datetime.min)
    people = [p for p in (raw.get("participants") or {}).get("data") or [] if not ours(p)]
    theirs = [m for m in msgs if not m["ours"]]
    customer = people[0] if people else {}
    customer_id = str(customer.get("id") or "") or (theirs[-1]["from_id"] if theirs else "")
    times = [m["created_at"] for m in msgs if m["created_at"]]
    return {"conversation_id": str(raw["id"]),
            "updated_at": mc._parse_time(raw.get("updated_time")) or (max(times) if times else None),
            "customer_id": customer_id,
            "username": customer.get("username") or (theirs[-1]["username"] if theirs else None),
            "messages": msgs}


async def fetch_conversations(session, ident: dict, now: datetime | None = None) -> list[dict]:
    """Oxirgi 24 soatda yangilangan Instagram suhbatlari (sahifalab)."""
    now = now or _utcnow()
    params = {"platform": "instagram", "fields": CONV_FIELDS, "limit": CONV_PAGE}
    out = []
    for _ in range(CONV_PAGES):
        data = await mc._graph(session, "GET", f"{mc.PAGE_ID}/conversations", ident["page_token"], params)
        page = data.get("data") or []
        fresh = 0
        for raw in page:
            conv = parse_conversation(raw, ident)
            if conv and conv["updated_at"] and now - conv["updated_at"] <= WINDOW:
                out.append(conv)
                fresh += 1
        paging = data.get("paging") or {}
        after = (paging.get("cursors") or {}).get("after")
        if not page or not fresh or not paging.get("next") or not after:
            break
        params = dict(params, after=after)
    return out


async def send_text(session, ident: dict, recipient_id: str, text: str) -> dict:
    return await mc._graph(session, "POST", f"{mc.PAGE_ID}/messages", ident["page_token"],
                           body={"recipient": {"id": recipient_id}, "messaging_type": "RESPONSE",
                                 "message": {"text": text}})


RATE_CODES = {1, 2, 4, 17, 32, 341, 368, 613}


def classify(e: Exception) -> str:
    """'closed' — bu odamga endi yozib bo'lmaydi (oyna yopilgan, 551):
    belgilab o'tamiz; 'rate' — keyinroq qayta; 'fatal' — token yoki ruxsat
    (hamma suhbatga tegishli: belgilamaymiz, tekshiruv to'xtaydi);
    'unknown' — keyinroq qayta, MAX_FAILS dan keyin adminga."""
    try:
        code = int(getattr(e, "code", None))
    except (TypeError, ValueError):
        code = None
    msg = str(getattr(e, "message", "") or e).lower()
    if code == 551 or "allowed window" in msg or "outside of the window" in msg:
        return "closed"
    if code == 100 and ("no matching user" in msg or "user not found" in msg or "isn't available" in msg):
        return "closed"
    if code in RATE_CODES or "rate limit" in msg or "too many" in msg or "temporarily" in msg:
        return "rate"
    if code == 10:
        return "fatal" if "permission" in msg else "closed"
    if code is None or code in (3, 190) or 200 <= code < 300 or "permission" in msg:
        return "fatal"
    return "unknown"


# ────────────────────────────── matn yordamchilari ──────────────────────────

def _ulen(text: str) -> int:
    """Meta belgilarni UTF-16 bo'yicha sanashi mumkin (emoji — 2): ehtiyotkor."""
    return len(text.encode("utf-16-le")) // 2


_LEVELS = ((re.compile(r"\n\s*\n"), "\n\n"), (re.compile(r"\n"), "\n"),
           (re.compile(r"(?<=[.!?…])\s+"), " "), (re.compile(r"\s+"), " "))


def _hard_cut(text: str, limit: int) -> list[str]:
    out, cur = [], ""
    for ch in text:
        if _ulen(cur + ch) > limit:
            out.append(cur)
            cur = ""
        cur += ch
    return out + ([cur] if cur else [])


def split_text(text: str | None, limit: int = TEXT_LIMIT, level: int = 0) -> list[str]:
    """Matnni ≤ limit bo'laklarga — avval xatboshi, keyin qator, gap, so'z
    chegarasida (so'z o'rtasidan faqat juda uzun «so'z» bo'lsa)."""
    text = (text or "").strip()
    if not text:
        return []
    if _ulen(text) <= limit:
        return [text]
    if level >= len(_LEVELS):
        return _hard_cut(text, limit)
    rx, joiner = _LEVELS[level]
    pieces = [p.strip() for p in rx.split(text) if p.strip()]
    if len(pieces) <= 1:
        return split_text(text, limit, level + 1)
    chunks, cur = [], ""
    for piece in pieces:
        for sub in split_text(piece, limit, level + 1):
            cand = f"{cur}{joiner}{sub}" if cur else sub
            if _ulen(cand) <= limit:
                cur = cand
            else:
                chunks.append(cur)
                cur = sub
    if cur:
        chunks.append(cur)
    return chunks


def assemble(reply: str, lists: list[str], max_parts: int = MAX_PARTS) -> list[str]:
    """Javob (kerak bo'lsa bo'lingan) + ro'yxat xabarlari, jami ≤ max_parts.
    Joy yetmasa javobning oxirgi bo'laklari tushadi — ro'yxatlar qoladi."""
    lists = [split_text(x)[0] for x in lists if (x or "").strip()][:max_parts - 1]
    parts = split_text(reply)[:max(1, max_parts - len(lists))]
    return parts + lists


_UZ_CYR_WORDS = re.compile(
    r"\b(салом\w*|ассалом\w*|рахмат|раҳмат|нарх\w*|канча|қанча|неча|бор|борми|йўқ|йук|керак\w*|"
    r"қандай|кандай|қаер\w*|каер\w*|манзил\w*|етказ\w*|мумкин\w*|ёки|учун|билан|сиз\w*|нима\w*|"
    r"олсам|оламан|буюртма\w*|дона|сўм|яхши|хоп|хўп|ака|опа)\b", re.IGNORECASE)
_RU_WORDS = re.compile(
    r"\b(здравствуй\w*|привет|добр\w*|сколько|цен\w*|стоит|есть|можно|доставк\w*|хочу|как|что|где|"
    r"это|спасибо|пожалуйста|нужн\w*|купить|заказ\w*|подскаж\w*|скажите|как\w*|у вас|вы)\b", re.IGNORECASE)


def detect_lang(text: str | None) -> str:
    """'uz' (lotin), 'uz_cyr' yoki 'ru' — mijoz yozuvi bo'yicha."""
    text = text or ""
    if not comment_ai.is_cyrillic(text):
        return "uz"
    if re.search(r"[ўқғҳ]", text, re.IGNORECASE):
        return "uz_cyr"
    uz, ru = len(_UZ_CYR_WORDS.findall(text)), len(_RU_WORDS.findall(text))
    if re.search(r"[ыщ]", text, re.IGNORECASE):
        ru += 1
    return "ru" if ru > uz else "uz_cyr"


def _to_cyr(text: str) -> str:
    """O'zbek lotin → kirill (havola va @handle'ga tegilmaydi), «сўм» to'g'ri."""
    from translit import lat_to_cyr
    text = comment_ai._DIRECT.sub("Direkt", text.translate(comment_ai._APOS)).replace("Direkt'", "Direkt")
    return comment_ai._fix_cyr_apos(lat_to_cyr(comment_ai._fix_cyr_apos(text)))


def in_lang(text: str, lang: str) -> str:
    return _to_cyr(text) if lang == "uz_cyr" else text


_BOT_PHRASE = re.compile(r"((?:Telegram|Телеграм)\S*\s+(?:bot|бот)\w*)\s*[:—–-]?\s*@ketoshopbot\b",
                         re.IGNORECASE)
_CH_PHRASE = re.compile(r"((?:Telegram|Телеграм)\S*\s+(?:kanal|канал)\w*)\s*[:—–-]?\s*@ketoshop_uz\b",
                        re.IGNORECASE)
_BARE_TME = re.compile(r"(?<![/\w.])t\.me/")


def telegram_links(text: str) -> str:
    """Instagram Direct'da @ketoshopbot bosilmaydi (egasi, 2026-11-16) —
    doim to'liq havola: «Telegram botimiz @ketoshopbot» → «Telegram botimiz:
    https://t.me/ketoshopbot», qolgan @ketoshopbot / @ketoshop_uz —
    comment_ai.direct_links (izohdan keyingi Direct bilan bir qoida)."""
    text = _BOT_PHRASE.sub(lambda m: f"{m.group(1)}: {BOT_LINK}", text)
    text = _CH_PHRASE.sub(lambda m: f"{m.group(1)}: {CHANNEL_LINK}", text)
    text = comment_ai.direct_links(text)
    return _BARE_TME.sub("https://t.me/", text)


_LEADING_YES = re.compile(r"^\s*(Ha|Да|Ҳа|Ха)\s*,\s*", re.IGNORECASE)


def finalize_dm(customer_text: str | None, reply: str | None, lang: str) -> str:
    """Direct'ga ketishdan oldin har javob: markdown yo'q, «Ha,» bilan
    boshlanmaydi, tabiiy «iltimos», «biz» nomidan, to'liq Telegram havolalari,
    mijoz yozuvida."""
    text = (reply or "").replace("**", "").replace("__", "")
    text = re.sub(r"(?m)^#+\s*", "", text).translate(comment_ai._APOS).strip()
    m = _LEADING_YES.match(text)
    if m and len(text) > m.end():
        rest = text[m.end():]
        text = rest[0].upper() + rest[1:]
    text = comment_ai._natural_polite(text, customer_text)
    text = comment_ai._plural(text)
    import ai_leak                     # ichki ma'lumot Direct'ga chiqmasin (2026-11-27)
    text = ai_leak.strip(text)
    text = telegram_links(text)
    return in_lang(text, lang).strip()


_SPAM = re.compile(
    r"(buy|get)\s+(real\s+)?followers|promot(e|ion)\s+(your|ur)\s+(page|account|profile)|\bcrypto\b|bitcoin|"
    r"\bforex\b|binary option|onlyfans|casino|казино|пассивн\w+ доход|заработ\w+ от \d", re.IGNORECASE)


def obvious_spam(text: str) -> bool:
    return bool(_SPAM.search(text or ""))


# ─────────────────────────────── ro'yxatlar ─────────────────────────────────

TEXTS = {
    "catalog_head": {"uz": "🛒 Keto shop'da hozir {n} xil mahsulot bor — bo'limlar bo'yicha:",
                     "ru": "🛒 Сейчас в Keto shop {n} товаров — по разделам:"},
    "catalog_row": {"uz": "{name} — {n} xil", "ru": "{name} — {n}"},
    "catalog_foot": {"uz": "Hammasini narxi va rasmi bilan ko'rish va buyurtma berish — Telegram'dagi "
                           "do'konimizda:\n👉 {link}",
                     "ru": "Все товары с ценами и фото, заказ — в нашем магазине в Telegram:\n👉 {link}"},
    "disc_head": {"uz": "🔥 Hozir chegirmada:", "ru": "🔥 Сейчас со скидкой:"},
    "disc_row": {"uz": "• {name} — {old} → {new} so'm (−{d}%)", "ru": "• {name} — {old} → {new} сум (−{d}%)"},
    "disc_more": {"uz": "… va yana {n} ta", "ru": "… и ещё {n}"},
    "disc_foot": {"uz": "Buyurtma: 👉 {link}", "ru": "Заказать: 👉 {link}"},
    "hello": {"uz": "Assalomu alaykum! ", "ru": "Здравствуйте! "},
    "holding": {"uz": "Xabaringiz uchun rahmat 🌿 Savolingizni mutaxassisimizga yetkazdik — tez orada shu "
                      "yerda javob beramiz. Shoshilinch bo'lsa, Telegram botimiz: {bot} yoki telefon: {phone}.",
                "ru": "Спасибо за сообщение 🌿 Мы передали ваш вопрос специалисту — скоро ответим здесь же. "
                      "Если срочно — наш Telegram-бот: {bot} или телефон: {phone}."},
}


def tr(key: str, lang: str, **kw) -> str:
    entry = TEXTS[key]
    text = (entry["ru"] if lang == "ru" else entry["uz"]).format(**kw)
    return in_lang(text, lang)


def holding_text(lang: str, first_contact: bool = True) -> str:
    phone = (SUPPORT_PHONES or "").split(",")[0].strip() or SUPPORT_PHONES
    return (tr("hello", lang) if first_contact else "") + tr("holding", lang, bot=BOT_LINK, phone=phone)


def _retail(products: list[dict]) -> list[dict]:
    return [p for p in products if not p.get("b2b_only") and float(p.get("quantity") or 0) > 0]


def _name(p: dict, lang: str) -> str:
    import locales
    return locales.localize_product_text(p.get("name"), p.get("name_ru"), "ru" if lang == "ru" else "uz")


def discounted(products: list[dict]) -> list[dict]:
    """Bot bilan bir qoida: database.active_discount / effective_price."""
    out = []
    for p in _retail(products):
        d = database.active_discount(p.get("discount_percent"), p.get("discount_until"))
        if not d:
            continue
        old = float(p.get("price") or 0)
        new = float(database.effective_price(old, d, p.get("discount_until")))
        if old > 0 and new < old:
            out.append(dict(p, old=old, new=new, d=int(d)))
    out.sort(key=lambda p: (-p["d"], p.get("name") or ""))
    return out


def catalog_message(products: list[dict], lang: str) -> str:
    """1-xabar: bo'limlar va har birida nechta mahsulot + do'kon havolasi
    (~140 mahsulot bitta Direct xabariga sig'maydi)."""
    import locales
    counts = Counter(p.get("category") or "" for p in _retail(products))
    if not counts:
        return ""
    order = {k: i for i, k in enumerate(locales.CATEGORIES)}
    head = tr("catalog_head", lang, n=sum(counts.values()))
    foot = tr("catalog_foot", lang, link=SHOP_LINK)
    rows = []
    for key, n in sorted(counts.items(), key=lambda kv: (order.get(kv[0], 999), -kv[1])):
        name = locales.get_category_name(key, "ru" if lang == "ru" else "uz") if key else ""
        if not name or name.startswith("[cat_"):
            name = "📦 " + (key or "Boshqa")
        rows.append(in_lang(TEXTS["catalog_row"]["ru" if lang == "ru" else "uz"].format(name=name, n=n), lang))
    text = head
    for row in rows:
        if _ulen(f"{text}\n{row}\n\n{foot}") > TEXT_LIMIT:
            break
        text = f"{text}\n{row}"
    return f"{text}\n\n{foot}"


def discount_message(items: list[dict], lang: str) -> str:
    """2-xabar (alohida): chegirmadagilar, eski → yangi narx. Bo'lmasa — ''."""
    if not items:
        return ""
    key = "ru" if lang == "ru" else "uz"
    head, foot = tr("disc_head", lang), tr("disc_foot", lang, link=SHOP_LINK)
    text, shown = head, 0
    for p in items:
        row = in_lang(TEXTS["disc_row"][key].format(name=_name(p, lang), old=_som(p["old"]),
                                                    new=_som(p["new"]), d=p["d"]), lang)
        more = tr("disc_more", lang, n=len(items) - shown - 1)
        if _ulen(f"{text}\n{row}\n{more}\n\n{foot}") > TEXT_LIMIT:
            break
        text, shown = f"{text}\n{row}", shown + 1
    if shown < len(items):
        text += "\n" + tr("disc_more", lang, n=len(items) - shown)
    return f"{text}\n\n{foot}"


def discount_block(items: list[dict]) -> str:
    """AI uchun (nima chegirmada ekanini bilsin, o'ylab topmasin)."""
    return "\n".join(f"- {p.get('name')} — {_som(p['old'])} → {_som(p['new'])} so'm (−{p['d']}%)"
                     for p in items) or "hozir yo'q"


# ─────────────────────────────── AI ─────────────────────────────────────────

DM_RULES = """Sen Keto shop jamoasi nomidan Instagram Direct'dagi (@ketoshop.uz) xabarlarga javob yozasan.
Keto shop Toshkentda keto, glyutensiz va PP mahsulotlari sotadi. Buyurtma — Telegram'dagi do'konimiz orqali.

MAQSAD — AVVAL FOYDA, keyin savdo (egasi, 2026-11-16: "faqat sotuvga yo'naltiraverma, bu qo'pollik —
tavsiyalar ham ber, keto tavsiyalar ham"). Maslahatchi do'stdek yoz, sotuvchidek emas.
- Avval aynan so'ralganiga aniq javob ber.
- O'rinli joyda BITTA qisqa, amaliy maslahat qo'sh: keto yoki PP bo'yicha tavsiya, mahsulotni qanday
  ishlatish, retsept g'oyasi yoki almashtirish (masalan, shakar o'rniga eritritol, pishiriqda bug'doy uni
  o'rniga bodom uni).
- Mahsulotni FAQAT haqiqatan yordam bersa tilga ol: bir javobda ko'pi bilan bitta yumshoq taklif (1–3 ta mos
  mahsulot KATALOGdagi nomi va narxi bilan, har biri alohida qatorda "•" bilan). Har xabarda sotuv taklifi
  yo'q.
- Salom-alik, rahmat yoki shunchaki suhbat — iliq javob, mahsulotsiz va havolasiz.
- Bosim yo'q: shoshiltirish ("faqat bugun", "tez tugaydi", "oxirgi imkoniyat") yo'q, "sotib oling",
  "buyurtma bering" degan qayta-qayta chaqiriqlar yo'q. Bir xabarda ko'pi bilan bitta savol.
- Do'kon havolasini ({shop}) faqat mahsulot, narx yoki buyurtma haqida gap bo'lganda ber.
- Mahsulot noma'lum bo'lsa (masalan "narxi qancha?" — qaysi post yoki storis ekanini ko'rmaymiz): qaysi
  mahsulot qiziqtirayotganini to'g'ridan-to'g'ri so'ra ("Qaysi mahsulot qiziqtiryapti?") va send_catalog=true.

KIM NOMIDAN: har doim "biz" — Keto shop jamoasi: "yuboramiz", "tavsiya qilamiz", "xursandmiz", "bizda bor".
Hech qachon "men", "aytaman". O'zingni bot, AI yoki dastur deb tanishtirma. Ichki so'zlarni (katalog, bilim
bazasi, kategoriya) ishlatma.

HAVOLALAR — Direct'da havola bosiladi, @username esa Instagram'da ochilmaydi (egasi, 2026-11-16):
- Do'kon (barcha mahsulotlar, narxlar, buyurtma): {shop}
- Telegram botimiz: {bot}
- Telegram kanalimiz (bepul retseptlar): {channel_link}
- Do'kon manzili xaritada: {address}
- "@ketoshopbot" yoki "{channel}" deb YOZMA — doim to'liq havola. Ular Telegram'da ekanini ayt:
  "Telegram botimiz: {bot}".

TIL: mijozning oxirgi xabari qaysi tilda va yozuvda bo'lsa — o'shanda yoz: o'zbek lotin (uz), o'zbek kirill
(uz_cyr) yoki rus (ru); lang ga shuni yoz. Kirillda yozsa — mahsulot nomlari ham kirillda.

USLUB
- Iliq, sodda, jonli — do'kon jamoasidan odam yozgandek. Shablon gaplar va har safar bir xil boshlanish yo'q.
- "Ha," bilan boshlama. Suhbat davom etayotgan bo'lsa, qayta salom berma; YANGI SUHBATda qisqa salom bilan boshla.
- "Iltimos" faqat odamdan aniq bir ish so'raganda, ko'pi bilan bir marta; ma'lumot va taklifda kerak emas.
  Rahmatga "Iltimos" emas — "Arzimaydi", "Sizga ham rahmat".
- Savolni to'g'ridan-to'g'ri ber: "agar sir bo'lmasa", "agar mumkin bo'lsa", "imkoningiz bo'lsa" kabi
  qo'shimchalarsiz.
- Qisqa: odatda 2–6 qator, 700 belgidan oshmasin. O'rinli bo'lsa 1–2 emoji. Markdown (**, #) yo'q.
- Mijoz ketma-ket bir nechta xabar yozgan bo'lsa — hammasiga bitta javobda javob ber.

FAKTLAR
- Faqat BILIM BAZASI, KATALOG, CHEGIRMALAR va AKSIYAdagi faktlar. Narx, muddat, manzil, telefon yoki
  chegirmani o'ylab topma.
- "tugagan" mahsulotni bor dema: hozir tugaganini, tez orada kelishini ayt va o'xshashini taklif qil.
- Uglevod, kaloriya, tarkib — faqat KATALOG qatoridagi «100 g: …» va «tarkibi: …» dan, "100 g da taxminan …"
  deb. Bo'lmasa — o'ylab topma.
- Tibbiy va'da berma ("davolaydi", "qandni tushiradi" kabi gaplar yo'q).

RO'YXAT XABARLARI — kod o'zi javobingdan keyin alohida xabar qilib yuboradi (har xabarda EMAS):
- send_catalog=true faqat: odam "nimalar bor", "narxlar", "prays", "katalog", "assortiment" kabi umumiy
  so'rasa; mahsulot noma'lum bo'lsa; yoki YANGI SUHBATning birinchi javobida tabiiy tushsa (salom yoki
  umumiy qiziqish). Aniq bitta mahsulot haqidagi savolda, rahmatda, suhbat davomida — false. true bo'lsa
  reply ichida ro'yxatni takrorlama — "bo'limlar ro'yxatini quyida yubordik" mazmunida bir gap yetadi.
- send_discounts=true: chegirma, aksiya, skidka so'ralsa. CHEGIRMALAR bo'sh bo'lsa — hozir chegirma yo'qligini
  halol ayt.

ODAM KERAK (needs_human=true): sog'liq savoli (kasallik, dori, homiladorlik, emizish, bolalar, diabet,
tashxis); shikoyat yoki norozilik; buyurtma muammosi (kelmadi, kechikdi, noto'g'ri keldi, sifat, pul
qaytarish, to'lov); optom yoki maxsus kelishuv; javobi faktlarda yo'q yoki tushunarsiz savol. Shunda reply —
iliq va halol "ushlab turuvchi" javob: odamni tushunganingni bildir, mutaxassisimiz tez orada shu yerda javob
berishini ayt; shoshilinch bo'lsa — Telegram botimiz: {bot} yoki telefon: {phone}.
- Sog'liqda umumiy ma'lumot berish mumkin, lekin shifokor bilan maslahatlashishni ham ayt.
- Shikoyatda avval samimiy kechirim so'ra yoki tushunishingni bildir, oqlanma, bahslashma; mahsulot reklama qilma.
Ikkilansang — needs_human=true.

intent — xabar turi: salom, katalog (umumiy: nimalar bor, narxlar), mahsulot (aniq mahsulot: narxi,
bor-yo'qligi, tarkibi), buyurtma (qanday buyurtma beriladi), yetkazish, manzil, chegirma, rahmat, salomatlik,
shikoyat, buyurtma_muammo, optom, spam, boshqa.
- spam: reklama, "followers/promotion" takliflari, kripto, havola tarqatish, haqorat — reply bo'sh.

end=true faqat biz oxirgi javobda savolga javob berib bo'lganmiz va mijoz faqat "ok", "👍", "xo'p" kabi bir
so'zli tasdiq yozgan bo'lsa. Rahmatga — qisqa iliq javob yoz (end=false)."""

SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string"},
        "intent": {"type": "string", "enum": list(INTENTS)},
        "needs_human": {"type": "boolean"},
        "send_catalog": {"type": "boolean"},
        "send_discounts": {"type": "boolean"},
        "end": {"type": "boolean"},
        "lang": {"type": "string", "enum": list(LANGS)},
    },
    "required": ["reply", "intent", "needs_human", "send_catalog", "send_discounts", "end", "lang"],
    "additionalProperties": False,
}


def rules() -> str:
    from ai_sales import SHOP_ADDRESS_URL
    phone = (SUPPORT_PHONES or "").split(",")[0].strip() or SUPPORT_PHONES
    return (DM_RULES.replace("{shop}", SHOP_LINK).replace("{bot}", BOT_LINK)
            .replace("{channel_link}", CHANNEL_LINK).replace("{channel}", CHANNEL)
            .replace("{address}", SHOP_ADDRESS_URL).replace("{phone}", phone)
            + "\n\nSAMIMIYLIK (egasi, 2026-11-27: \"zo'r deb ikki marotaba ... boshlapsan bu notabiiy, "
              "bir xillikdan qoch\"): javobni 'Zo'r', 'Ajoyib', 'Juda yaxshi' kabi maqtov so'zi bilan "
              "boshlama va oldingi xabarimizdagi kirish so'zini takrorlama. Mijozning gapiga to'g'ridan-to'g'ri, "
              "iliq va har safar boshqacha javob ber.")


NONTEXT = "[matnsiz xabar: rasm, ovoz, stiker, storis yoki ulashilgan post]"


def transcript(conv: dict, pending_ids: set[str]) -> str:
    lines = []
    for m in conv["messages"][-HISTORY:]:
        who = "Biz" if m["ours"] else "Mijoz"
        mark_ = "   ← JAVOB KERAK" if m["message_id"] in pending_ids else ""
        lines.append(f"[{_tk(m['created_at'])}] {who}: {(m['text'] or NONTEXT)[:800]}{mark_}")
    return "\n".join(lines)


def user_prompt(conv: dict, pending: list[dict], first_contact: bool) -> str:
    who = conv.get("username") or "mijoz"
    return (f"Instagram Direct · mijoz: {who}\n"
            f"YANGI SUHBAT: {'ha — biz bu odamga hali yozmaganmiz' if first_contact else 'yoq'}\n\n"
            f"SUHBAT (eskidan yangiga; «Biz» — Keto shop):\n"
            f"{transcript(conv, {m['message_id'] for m in pending})}\n\n"
            "«JAVOB KERAK» belgili xabarlarga bitta javob yoz.")


_openai_client: tuple[str, object] | None = None


async def ask_ai(instructions: str, user: str) -> dict | None:
    """GPT (Responses API, qat'iy JSON). None — kalit yo'q, xato yoki rad."""
    global _openai_client
    if await comment_ai.provider() != "openai":
        return None
    import ai_provider
    import openai
    key = await comment_ai._openai_key()
    model = comment_ai.openai_model()
    if _openai_client is None or _openai_client[0] != key:
        _openai_client = (key, openai.AsyncOpenAI(api_key=key, timeout=60.0, max_retries=2))
    try:
        resp = await _openai_client[1].responses.create(
            model=model, instructions=instructions,
            input=[{"role": "user", "content": [{"type": "input_text", "text": user}]}],
            reasoning={"effort": "low"}, max_output_tokens=MAX_TOKENS, prompt_cache_key="ketoshop-direct",
            text={"format": {"type": "json_schema", "name": "direct_javob", "schema": SCHEMA, "strict": True}})
    except (openai.RateLimitError, openai.APIStatusError, openai.APIConnectionError) as e:
        logger.warning("ig direct AI error (%s): %s", model, e)
        return None
    usage = ai_provider._openai_usage(getattr(resp, "usage", None))
    try:
        await database.record_ai_usage(model + USAGE_TAG, "openai", usage.input, usage.cached, usage.output,
                                       ai_provider.estimate_cost(model, usage.input, usage.cached, usage.output))
    except Exception:
        logger.warning("ig direct AI usage not recorded", exc_info=True)
    if getattr(resp, "status", "completed") == "incomplete":
        return None
    try:
        data = json.loads(getattr(resp, "output_text", "") or "")
    except (TypeError, ValueError):
        logger.warning("ig direct AI returned non-JSON")
        return None
    if not isinstance(data, dict) or not isinstance(data.get("reply"), str) or data.get("intent") not in INTENTS:
        return None
    return data


async def _offers() -> str:
    try:
        import comment_followup
        return await comment_followup.offers_text()
    except Exception:
        logger.info("ig direct: offers unavailable", exc_info=True)
        return ""


@dataclass
class Plan:
    status: str                       # replied | held | spam | closed
    messages: list[str] = field(default_factory=list)
    intent: str = ""
    lang: str = "uz"
    reason: str = ""                  # adminga kartochka sababi (held)
    catalog: bool = False


def _holding(lang: str, first_contact: bool, reason: str, intent: str = "") -> Plan:
    return Plan("held", [holding_text(lang, first_contact)], intent=intent, lang=lang, reason=reason)


async def compose(conv: dict, pending: list[dict], *, first_contact: bool, catalog_ok: bool,
                  now: datetime) -> Plan | None:
    """_compose + bot havolasiga shu odamning kodi (person_folder: Telegram ↔ Instagram
    papkalari bog'lanadi, egasi 2026-11-27)."""
    plan = await _compose(conv, pending, first_contact=first_contact, catalog_ok=catalog_ok, now=now)
    if plan is not None and any(BOT_LINK in m for m in plan.messages):
        import person_folder
        try:
            token = await person_folder.ig_token(conv.get("username"))
        except Exception:
            logger.warning("ig direct: personal bot link failed", exc_info=True)
            token = None
        plan.messages = [person_folder.personal_links(m, token) for m in plan.messages]
    return plan


async def _compose(conv: dict, pending: list[dict], *, first_contact: bool, catalog_ok: bool,
                   now: datetime) -> Plan | None:
    """Shu navbatdagi javob rejasi. None — AI hozircha javob bermadi, keyingi
    tekshiruvda yana uriniladi."""
    joined = "\n".join(m["text"] for m in pending if m["text"])
    last_text = next((m["text"] for m in reversed(conv["messages"]) if not m["ours"] and m["text"]), "")
    lang = detect_lang(joined or last_text)
    if not joined:
        return _holding(lang, first_contact, "nontext")
    if obvious_spam(joined):
        return Plan("spam", intent="spam", lang=lang)
    products = await database.admin_list_products(include_inactive=False)
    sale = discounted(products)
    if await comment_ai.provider() != "openai":
        return _holding(lang, first_contact, "ai_down")
    state = await database.get_meta_comments_state()
    kb = comment_ai.kb_with_defaults(state.get("kb"))
    instructions = (rules() + "\n\n" + comment_ai.kb_block(kb, await comment_ai.catalog_text())
                    + "\n\nCHEGIRMALAR (hozir)\n" + discount_block(sale)
                    + "\n\nAKSIYA\n" + (await _offers() or "hozir yo'q"))
    # Mijoz papkasi (egasi, 2026-11-27): avvalgi izoh va Direct suhbatlari + 5 soatlik salom qoidasi.
    import person_folder
    folder, hours = await person_folder.block("ig", conv.get("username"))
    user = user_prompt(conv, pending, first_contact) + ("\n\n" + folder if folder else "")
    data = await ask_ai(instructions, user)
    if data is None:
        oldest = min((m["created_at"] for m in pending if m["created_at"]), default=now)
        return _holding(lang, first_contact, "ai_down") if now - oldest >= AI_GIVEUP else None
    if lang != "uz" and data.get("lang") in ("uz_cyr", "ru"):
        lang = data["lang"]
    intent = data.get("intent") or "boshqa"
    if intent == "spam":
        return Plan("spam", intent=intent, lang=lang)
    short = all(len(m["text"]) <= 20 for m in pending)
    if data.get("end") and not first_contact and short:
        return Plan("closed", intent=intent, lang=lang)
    human = bool(data.get("needs_human")) or intent in HUMAN_INTENTS
    reply = finalize_dm(joined, data.get("reply"), lang)
    # Ketma-ket "Zo'r…", "Ha, …" bilan boshlamaslik (egasi, 2026-11-27) — oldingi javobimizga qarab.
    previous = next((m["text"] for m in reversed(conv["messages"]) if m["ours"] and m.get("text")), None)
    if reply:
        import ai_tone
        reply = ai_tone.vary(reply, previous)
        greet = person_folder.needs_greeting(hours) if folder else first_contact
        reply = ai_tone.drop_midchat_greeting(reply, joined, not greet)
        reply = ai_tone.greet_first(reply, lang, greet)
    if human:
        plan = _holding(lang, first_contact, intent if intent in HUMAN_INTENTS else "unsure", intent)
        if reply:
            plan.messages = split_text(reply)[:MAX_PARTS]
        return plan
    if not reply:
        return _holding(lang, first_contact, "unsure", intent)
    lists = []
    if data.get("send_catalog") and catalog_ok:
        lists = [catalog_message(products, lang), discount_message(sale, lang)]
    elif data.get("send_discounts"):
        lists = [discount_message(sale, lang)]
    lists = [x for x in lists if x]
    return Plan("replied", assemble(reply, lists), intent=intent, lang=lang,
                catalog=bool(data.get("send_catalog") and catalog_ok and lists))


# ─────────────────────────────── admin kartochkasi ──────────────────────────

def card_text(conv: dict, pending: list[dict], reason: str, sent: list[str] | None = None,
              note: str | None = None) -> str:
    who = conv.get("username")
    lines = ["📩 <b>Instagram Direct — odam kerak</b>",
             f"👤 {('@' + _esc(who)) if who else _esc(conv.get('customer_id') or '—')}"
             + (f" · <a href=\"https://www.instagram.com/{html.escape(who)}/\">profil</a>" if who else ""),
             f"🏷 {REASONS.get(reason, reason)}"]
    for m in pending[-5:]:
        lines.append(f"💬 «{_esc((m.get('text') or NONTEXT)[:400])}» ({_tk(m.get('created_at'))})")
    if sent:
        lines.append(f"🤖 Biz yozdik: «{_esc(' / '.join(sent)[:500])}»")
    if note:
        lines.append(f"⚠️ {_esc(note)[:300]}")
    lines += ["", "👉 Javobni Instagram'da @ketoshop.uz Direct'ida yozing (oxirgi xabaridan 24 soat ichida)."]
    return "\n".join(lines)


async def notify_admins(bot: Bot | None, text: str) -> int:
    if bot is None:
        return 0
    n = 0
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML", disable_web_page_preview=True)
            n += 1
        except Exception as exc:
            logger.info("ig direct card → %s failed: %s", admin_id, exc)
    return n


def _note_error(text: str) -> None:
    _errors.append((_utcnow(), text))


async def _pause() -> None:
    if PAUSE[1] > 0:
        await asyncio.sleep(random.uniform(*PAUSE))


def _set_backoff(now: datetime) -> None:
    _backoff["n"] = min(_backoff["n"] + 1, 5)
    _backoff["until"] = now + timedelta(minutes=2 ** _backoff["n"])


# ─────────────────────────────── bitta suhbat ───────────────────────────────

def split_turns(conv: dict) -> tuple[list[dict], list[dict]]:
    """(oxirgi javobimizdan oldingi mijoz xabarlari, undan keyingilari)."""
    msgs = conv["messages"]
    last = max((i for i, m in enumerate(msgs) if m["ours"]), default=-1)
    return ([m for m in msgs[:last + 1] if not m["ours"]],
            [m for m in msgs[last + 1:] if not m["ours"]])


def batch_ready(pending: list[dict], now: datetime) -> bool:
    times = [m["created_at"] for m in pending if m["created_at"]]
    if not times:
        return True
    return now - max(times) >= QUIET or now - min(times) >= MAX_WAIT


def in_window(trailing: list[dict], now: datetime) -> bool:
    times = [m["created_at"] for m in trailing if m["created_at"]]
    return not times or now - max(times) < SAFE_WINDOW


async def handle_conversation(bot: Bot | None, session, ident: dict, conv: dict, now: datetime) -> str:
    """Bitta suhbat: saqlash, holatlarni tuzatish va kerak bo'lsa javob.
    Natija: 'none' | 'wait' | 'throttled' | 'retry' | 'replied' | 'held' |
    'spam' | 'closed' | 'expired' | 'unavailable' | 'busy'."""
    cid = conv["conversation_id"]
    earlier, trailing = split_turns(conv)
    await store_messages(cid, [dict(m, status="human") for m in earlier] + [dict(m, status="new") for m in trailing])
    if earlier:
        ids = [m["message_id"] for m in earlier]
        # Bizdan javob ketgan (qayta ishga tushishdan oldin yuborilgan bo'lsa ham) yoki
        # kimdir Instagram'ning o'zida yozgan — bular endi javob kutmaydi.
        await mark(ids, "replied", ("sending",))
        await mark(ids, "human", OPEN, note="Instagram'da bizdan javob bor")
    if not trailing:
        return await late_reply(session, ident, conv, now)
    rows = await statuses([m["message_id"] for m in trailing])
    stale = [i for i, r in rows.items() if r["status"] == "sending" and
             (r.get("claimed_at") is None or now - r["claimed_at"] > STALE_CLAIM)]
    if stale:
        await mark(stale, "new", ("sending",), note="qayta ishga tushgandan keyin qayta navbatga")
        rows = await statuses([m["message_id"] for m in trailing])
    pending = [m for m in trailing if (rows.get(m["message_id"]) or {}).get("status") == "new"]
    if not pending:
        return "none"
    ids = [m["message_id"] for m in pending]
    if not in_window(trailing, now):
        done = await mark(ids, "expired", OPEN, note="24 soatlik oyna yopilgan")
        if done:
            await notify_admins(bot, card_text(conv, pending, "expired"))
        return "expired"
    if not batch_ready(pending, now):
        return "wait"
    if await replies_since(cid, now - timedelta(hours=1)) >= PER_HOUR:
        noted = _throttle_noted.get(cid)
        if not noted or now - noted > timedelta(hours=1):
            _throttle_noted[cid] = now
            await notify_admins(bot, card_text(conv, pending, "throttled",
                                               note=f"Bir soatda {PER_HOUR} ta javob — keyingisi keyinroq"))
        return "throttled"
    first_contact = not any(m["ours"] for m in conv["messages"]) and not await had_reply(cid)
    catalog_ok = not await catalog_recent(cid, now - CATALOG_EVERY)
    plan = await compose(conv, pending, first_contact=first_contact, catalog_ok=catalog_ok, now=now)
    if plan is None:
        return "retry"
    if plan.status in ("spam", "closed"):
        await mark(ids, plan.status, OPEN, intent=plan.intent)
        return plan.status
    claimed = await mark(ids, "sending", OPEN, claimed_at=now)
    if not claimed:
        return "busy"
    recipient = conv.get("customer_id") or pending[-1]["from_id"]
    sent: list[str] = []
    for part in plan.messages:
        if sent:
            await _pause()
        try:
            await send_text(session, ident, recipient, part)
            sent.append(part)
        except mc.GraphError as e:
            kind = classify(e)
            if sent:
                # Birinchi xabar ketdi — qolgani ketmadi: javob berilgan deb hisoblaymiz.
                logger.info("ig direct %s: partial send: %s", cid, e)
                break
            if kind == "closed":
                await mark(claimed, "unavailable", ("sending",), note=str(e)[:300])
                await notify_admins(bot, card_text(conv, pending, "closed", note=str(e)))
                return "unavailable"
            await mark(claimed, "new", ("sending",), note=str(e)[:300])
            if kind == "unknown":
                _failures[cid] += 1
                _note_error(f"yuborish: {e}")
                if _failures[cid] >= MAX_FAILS:
                    _failures.pop(cid, None)
                    await mark(claimed, "unavailable", OPEN, note=str(e)[:300])
                    await notify_admins(bot, card_text(conv, pending, "failed", note=str(e)))
                    return "unavailable"
                return "retry"
            raise
    _failures.pop(cid, None)
    status = "held" if plan.status == "held" else "replied"
    extra = {"note": plan.reason} if status == "held" and plan.reason else {}
    await mark(claimed, status, ("sending",), reply_text="\n\n".join(sent), replied_at=now,
               intent=plan.intent, catalog_sent=plan.catalog, **extra)
    if status == "held":
        await notify_admins(bot, card_text(conv, pending, plan.reason, sent))
    return status


# ───────────────────── kechikkan javob (AI ishlamagan payt) ─────────────────
# Egasi, 2026-11-26 (OpenAI krediti tugab, AI bir kun javob bermadi): "barcha
# javob yozilmagan xabarlarga javob yozib chiqishi kerak ... instagram
# directda". O'sha payt mijoz faqat ushlab turuvchi javob olgan (held,
# ai_down) — AI qaytgach, 24 soatlik oyna ichida bo'lsa, haqiqiy javob.

LATE_SORRY = {
    "uz": "Javobimiz biroz kechikdi, uzr 🙏\n\n",
    "uz_cyr": "Жавобимиз бироз кечикди, узр 🙏\n\n",
    "ru": "Извините, что ответ немного задержался 🙏\n\n",
}
LATE_DONE = "kechikkan javob"


def _held_for_ai(row: dict | None) -> bool:
    """AI ishlamagani uchun ushlab turuvchi javob olgan xabar. Eski qatorlarda
    sabab yozilmagan: intent bo'sh + matn bor = ai_down (nontext matnsiz,
    unsure/odam kerak — intent bilan)."""
    if not row or row.get("status") != "held":
        return False
    if row.get("note") == "ai_down":
        return True
    return not row.get("note") and not row.get("intent") and bool((row.get("text") or "").strip())


def last_customer_batch(conv: dict) -> list[dict]:
    """Oxirgi javobimizdan oldingi, ketma-ket mijoz xabarlari."""
    msgs = conv["messages"]
    last = max((i for i, m in enumerate(msgs) if m["ours"]), default=-1)
    batch = []
    for m in reversed(msgs[:max(last, 0)]):
        if m["ours"]:
            break
        batch.insert(0, m)
    return batch


async def late_reply(session, ident: dict, conv: dict, now: datetime) -> str:
    batch = last_customer_batch(conv)
    if not batch or not in_window(batch, now):
        return "none"
    rows = await statuses([m["message_id"] for m in batch])
    late = [m for m in batch if _held_for_ai(rows.get(m["message_id"]))]
    if not late:
        return "none"
    ids = [m["message_id"] for m in late]
    cid = conv["conversation_id"]
    if await replies_since(cid, now - timedelta(hours=1)) >= PER_HOUR:
        return "throttled"
    plan = await compose(conv, late, first_contact=False,
                         catalog_ok=not await catalog_recent(cid, now - CATALOG_EVERY), now=now)
    if plan is None or plan.reason == "ai_down":
        return "retry"                                  # AI hali ham ishlamayapti
    if plan.status != "replied":
        # Odam kerak / yakunlangan / spam — kartochka allaqachon adminlarda, qayta so'ramaymiz.
        await mark(ids, "held", ("held",), note=f"{LATE_DONE}: {plan.status}")
        return "none"
    claimed = await mark(ids, "sending", ("held",), claimed_at=now)
    if not claimed:
        return "busy"
    recipient = conv.get("customer_id") or late[-1]["from_id"]
    parts = list(plan.messages)
    parts[0] = LATE_SORRY.get(plan.lang, LATE_SORRY["uz"]) + parts[0]
    sent: list[str] = []
    for part in parts:
        if sent:
            await _pause()
        try:
            await send_text(session, ident, recipient, part)
            sent.append(part)
        except mc.GraphError as e:
            if sent:
                break
            back = "unavailable" if classify(e) == "closed" else "held"
            await mark(claimed, back, ("sending",), note=f"{LATE_DONE}: {str(e)[:250]}")
            return "unavailable" if back == "unavailable" else "retry"
    await mark(claimed, "replied", ("sending",), reply_text="\n\n".join(sent), replied_at=now,
               intent=plan.intent, catalog_sent=plan.catalog, note=LATE_DONE)
    return "replied"


# ─────────────────────────────── tekshiruv ──────────────────────────────────

def _pending_age(conv: dict) -> datetime:
    _, trailing = split_turns(conv)
    times = [m["created_at"] for m in trailing if m["created_at"]]
    return max(times) if times else datetime.max


async def tick(bot: Bot | None, now: datetime | None = None) -> dict:
    """Bitta tekshiruv (qulf ostida; ikkinchi chaqiruv kutmaydi)."""
    if _lock.locked():
        return {"busy": 1}
    stats: Counter = Counter()
    async with _lock:
        now = now or _utcnow()
        if _backoff["until"] and now < _backoff["until"]:
            return {"backoff": 1}
        if not (await get_state()).get("enabled", True):
            return {"off": 1}
        await mc.load_token()
        if not mc.token():
            return {"no_token": 1}
        try:
            async with aiohttp.ClientSession() as session:
                ident = await mc.identity(session)
                if not ident.get("ig_id"):
                    raise mc.GraphError("no_ig", "Instagram hisob sahifaga ulanmagan")
                convs = await fetch_conversations(session, ident, now)
                stats["conversations"] = len(convs)
                answered = 0
                # Oynasi birinchi yopiladigan suhbat birinchi.
                for conv in sorted(convs, key=_pending_age):
                    if answered >= PER_TICK:
                        stats["later"] += 1
                        continue
                    result = await handle_conversation(bot, session, ident, conv, now)
                    stats[result] += 1
                    if result in ("replied", "held"):
                        answered += 1
                        await _pause()
            _backoff.update(until=None, n=0)
            await note_poll()
        except mc.GraphError as e:
            kind = classify(e)
            if kind == "rate":
                _set_backoff(now)
            _note_error(str(e))
            stats["error"] += 1
            try:
                await note_poll(str(e))
            except Exception:
                logger.warning("ig direct: state not saved", exc_info=True)
            logger.warning("ig direct: %s (%s)", e, kind)
    return dict(stats)


def kick() -> None:
    """Webhook'dan: Direct xabari keldi — tekshiruvni kutmasdan uyg'otamiz."""
    _kick.set()


def webhook_has_messages(body: dict) -> bool:
    """Instagram webhook'ida mijozdan Direct xabari bormi (bizning echo emas)."""
    if (body or {}).get("object") != "instagram":
        return False
    for entry in body.get("entry") or []:
        for ev in entry.get("messaging") or []:
            msg = ev.get("message") or {}
            if msg and not msg.get("is_echo"):
                return True
        for change in entry.get("changes") or []:
            if change.get("field") == "messages":
                return True
    return False


def on_webhook(body: dict) -> None:
    if webhook_has_messages(body):
        kick()


async def loop(bot: Bot) -> None:
    await asyncio.sleep(45)
    logger.info("Instagram Direct loop started (every %ds)", EVERY)
    while True:
        try:
            stats = await tick(bot)
            if any(k in stats for k in ("replied", "held", "error", "unavailable", "expired")):
                logger.info("ig direct: %s", stats)
        except Exception:
            logger.exception("ig direct tick failed")
            _note_error("tekshiruv xatosi (logda)")
        try:
            await asyncio.wait_for(_kick.wait(), timeout=EVERY)
            _kick.clear()
            await asyncio.sleep(QUIET.total_seconds() + 2)   # ketma-ket xabarlar yig'ilsin
        except asyncio.TimeoutError:
            pass


# ─────────────────────────────── hisobot ────────────────────────────────────

def summary_line(s: dict | None) -> str | None:
    """Kunlik hisobot (targets.py) va /ig_direct uchun bitta qator."""
    if not s or not (s.get("conversations") or s.get("received")):
        return None
    line = (f"📩 <b>Instagram Direct: bugun {s.get('conversations', 0)} ta suhbatga javob berildi</b> "
            f"({s.get('replies', 0)} ta javob) · 👤 odamga topshirildi: {s.get('to_human', 0)} ta")
    if s.get("missed"):
        line += f" · ⌛ javobsiz qolgan: {s['missed']} ta"
    return line


# ─────────────────────────────── /ig_direct ─────────────────────────────────

DM_PERMISSIONS = ("instagram_basic", "instagram_manage_messages", "pages_manage_metadata",
                  "pages_messaging", "pages_show_list")
ACCESS_HINT = ("📱 Instagram ilovasida (@ketoshop.uz): Sozlamalar → Xabarlar va storis javoblari → "
               "Xabarlarni boshqarish → Ulangan vositalar → «Xabarlarga kirishga ruxsat berish» "
               "(Allow access to messages) — yoqilgan bo'lsin.")


def error_hints(e: Exception) -> list[str]:
    msg = str(getattr(e, "message", "") or e).lower()
    code = getattr(e, "code", None)
    hints = []
    if code == "no_token":
        return ["🔑 Token yo'q: <code>/izoh_token TOKEN</code>"]
    if code == "no_ig":
        return ["📘 Instagram @ketoshop.uz «Keto market.uz» sahifasiga ulanmagan (Business sozlamalari)."]
    if code == 190 or "expired" in msg or "session" in msg:
        hints.append("🔑 Token eskirgan yoki bekor qilingan — yangisini <code>/izoh_token</code> bilan yuboring.")
    if code in (3, 10, 200) or "permission" in msg or "access" in msg or "capability" in msg:
        hints.append("🔒 Tokenda Direct ruxsatlari bo'lsin: <code>" + ", ".join(DM_PERMISSIONS) + "</code> — "
                     "token yaratishda belgi qo'yib, <code>/izoh_token</code> bilan qayta yuboring.")
        hints.append(ACCESS_HINT)
    if not hints:
        hints.append(ACCESS_HINT)
    return hints


async def missing_permissions(session) -> list[str] | None:
    try:
        perms = await mc._graph(session, "GET", "me/permissions", mc.token())
    except mc.GraphError:
        return None
    granted = {p.get("permission") for p in perms.get("data", []) if p.get("status") == "granted"}
    return [p for p in DM_PERMISSIONS if p not in granted]


async def test_text() -> str:
    """Token Instagram suhbatlarini o'qiy oladimi — faqat GET, hech narsa
    yuborilmaydi. Xato bo'lsa — Meta'ning aynan o'z xabari va nima yoqish kerak."""
    lines = ["🧪 <b>Instagram Direct tekshiruvi</b> (hech narsa yuborilmaydi)", ""]
    await mc.load_token()
    if not mc.token():
        return "\n".join(lines + error_hints(mc.GraphError("no_token", "")))
    try:
        async with aiohttp.ClientSession() as session:
            missing = await missing_permissions(session)
            try:
                ident = await mc.identity(session, force=True)
                lines.append(f"📘 Sahifa: {_esc(ident.get('page_name') or '?')}")
                if not ident.get("ig_id"):
                    raise mc.GraphError("no_ig", "Instagram hisob sahifaga ulanmagan")
                lines.append(f"📷 Instagram: @{_esc(ident.get('ig_username') or ident['ig_id'])}")
                data = await mc._graph(session, "GET", f"{mc.PAGE_ID}/conversations", ident["page_token"],
                                       {"platform": "instagram", "limit": 5,
                                        "fields": "id,updated_time,messages.limit(1){id,created_time}"})
            except mc.GraphError as e:
                lines += ["", f"❌ Meta: <code>{_esc(e)}</code>", ""] + error_hints(e)
                if missing:
                    lines.append("🔒 Tokenda yo'q ruxsatlar: <code>" + ", ".join(missing) + "</code>")
                return "\n".join(lines)
    except Exception as e:
        logger.exception("ig direct test failed")
        return "\n".join(lines + [f"❌ Meta bilan bog'lanib bo'lmadi: <code>{_esc(e)}</code>"])
    convs = data.get("data") or []
    newest = mc._parse_time(convs[0].get("updated_time")) if convs else None
    lines.append(f"✅ Direct suhbatlarini o'qiyapti: oxirgi {len(convs)} ta"
                 + (f" (eng yangisi {_tk(newest)})" if newest else ""))
    if missing:
        lines += ["", "⚠️ Tokenda yo'q ruxsatlar: <code>" + ", ".join(missing) + "</code> — javob yuborish uchun "
                      "<code>pages_messaging</code> va <code>instagram_manage_messages</code> shart."]
    return "\n".join(lines)


async def status_text() -> str:
    state = await get_state()
    s = await day_stats()
    await mc.load_token()
    label = await comment_ai.provider_label()
    on = state.get("enabled", True)
    lines = ["📩 <b>Instagram Direct — AI javoblar</b>", "",
             f"Holat: <b>{'yoqilgan ✅' if on else 'o‘chiq ⏸'}</b>",
             "🔑 Token: " + ("bor" if mc.token() else "<b>yo'q</b> — /izoh_token"),
             "🤖 AI: " + (_esc(label) if label.startswith("GPT") else
                          "⚠️ GPT kaliti yo'q (/ai_kalit) — har xabarga ushlab turuvchi javob + adminga kartochka"),
             f"🔄 Tekshiruv: har {EVERY} soniyada · oxirgi muvaffaqiyatli: {_tk(state.get('last_ok_at'))}",
             "",
             f"Bugun: 📨 keldi {s.get('received', 0)} ta xabar · ✅ {s.get('conversations', 0)} ta suhbatga "
             f"javob ({s.get('replies', 0)} ta) · 👤 odamga: {s.get('to_human', 0)} · 🚫 spam: {s.get('spam', 0)}"
             + (f" · ⌛ javobsiz qolgan: {s['missed']}" if s.get("missed") else ""),
             f"⏳ Hozir navbatda: {s.get('pending', 0)} ta xabar"]
    if _backoff.get("until"):
        lines.append(f"⏸ Meta tezlik chegarasi — {_tk(_backoff['until'])} gacha kutyapmiz")
    errs = list(_errors)
    if not errs and state.get("last_error"):
        errs = [(state.get("last_error_at"), state["last_error"])]
    if errs:
        lines += ["", "<b>Oxirgi xatolar:</b>"]
        for when, text in errs[-3:]:
            lines.append(f"• {_tk(when)}: {_esc(text)[:200]}")
    recent = await recent_replies(3)
    if recent:
        lines += ["", "<b>Oxirgi javoblar:</b>"]
        for r in recent:
            icon = "👤" if r.get("status") == "held" else "🤖"
            lines.append(f"{icon} {_esc(r.get('username') or '—')}: «{_esc((r.get('text') or '')[:60])}» → "
                         f"«{_esc((r.get('reply_text') or '')[:140])}»")
    lines += ["", "<code>/ig_direct off</code> — to'xtatish · <code>/ig_direct on</code> — yoqish",
              "<code>/ig_direct test</code> — token Direct'ni o'qiy oladimi (hech narsa yuborilmaydi)"]
    return "\n".join(lines)


@router.message(Command("ig_direct"))
async def cmd_ig_direct(message: Message):
    if not mc.is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    arg = parts[1].lower() if len(parts) > 1 else ""
    if arg == "test":
        await message.answer(await test_text(), parse_mode="HTML", disable_web_page_preview=True)
        return
    if arg in ("on", "yoq", "yoqish"):
        await set_enabled(True)
        kick()
    elif arg in ("off", "ochir", "o'chir", "stop"):
        await set_enabled(False)
    await message.answer(await status_text(), parse_mode="HTML", disable_web_page_preview=True)
