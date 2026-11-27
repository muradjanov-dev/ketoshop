"""Mijoz papkasi — har bir odam bilan suhbat yangidan boshlanmaydi (egasi, 2026-11-27:
"har bir odam bilan gaplashish uchun alohida bir papkacha ochib avvalgi suhbatlar
asosida ham suhbatni davom ettir ... lekin 5 soatdan keyin gaplashsang salom ber").

Papka kaliti:
  * ("tg", user_id)  — bot, sayt va kanal guruhi (ai_dialog, bitta zanjir);
  * ("ig", username) — Instagram/Facebook izohlari (meta_comments) va Direct
    (ig_dm_messages), username bo'yicha.

Hamma narsa bazada to'liq qoladi (egasi: "hech narsani o'chirma"). Promptga esa:
  * XULOSA — eski suhbatlardan arzon model tuzgan qisqa xulosa (nima so'ragan,
    nima olgan/qiziqqan, nima va'da qilinganmiz, ohangi). Har SUMMARY_EVERY ta
    yangi gapdan keyin fonda yangilanadi — javobni kutdirmaydi;
  * OXIRGI GAPLAR — so'nggi RAW_KEEP tasi so'zma-so'z (izoh va Direct uchun; Telegram'da
    oxirgi gaplar ai_dialog.context_block orqali allaqachon bor);
  * SALOM qoidasi — oxirgi javobimizdan GREET_AFTER_HOURS (5) soat o'tgan bo'lsa yoki
    birinchi marta bo'lsa — qisqa salom bilan boshlanadi, aks holda salomsiz davom.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
from datetime import datetime

import database

logger = logging.getLogger(__name__)

GREET_AFTER_HOURS = 5
SUMMARY_EVERY = 6         # shuncha yangi gapdan keyin xulosa yangilanadi
RAW_KEEP = 8              # promptga so'zma-so'z tushadigan oxirgi gaplar
HISTORY_MAX = 400         # xulosaga beriladigan eng ko'p gap (eng yangilari)
TEXT_MAX = 400
SUMMARY_MODEL = os.getenv("AI_FOLDER_MODEL", "gpt-5.4-mini").strip()
USAGE_TAG = " · papka"

SUMMARY_RULES = """Sen Keto shop (keto, PP, glyutensiz, qandsiz mahsulotlar do'koni) sotuvchisining yordamchisisan.
Bitta mijoz bilan bo'lgan barcha suhbatlardan uning "papkasi" uchun qisqa xulosa yoz (o'zbekcha, 4–8 qator,
har biri "- " bilan): kimligi va maqsadi (aytgan bo'lsa), nimalarni so'ragan va qiziqqan, nima olgan yoki olmoqchi
bo'lgan, bizdan nima va'da qilingan yoki hal qilinmay qolgan, e'tiroz/shikoyatlari, qaysi tilda va qanday
ohangda yozadi. Faqat suhbatda borini yoz, taxmin qilma. Telefon, karta, manzil raqamlarini yozma.
"OLDINGI XULOSA" berilgan bo'lsa — uni yangi gaplar bilan yangilab, bitta xulosa qilib qaytar."""

_table_ready = False
_refreshing: set[str] = set()

# Telegram ↔ Instagram bog'lash (egasi, 2026-11-27: "bitta mijoz ham instagramdan ham botdan ...
# yozsa?"). Direct'dagi bot havolasiga shu odamning kodi qo'shiladi: t.me/ketoshopbot?start=igu<kod>.
# Shu havola bilan START bosgan Telegram hisobi o'sha Instagram username'ga bog'lanadi — ikkala
# papka bitta bo'ladi. Bitta Instagram — bitta Telegram (oxirgisi qoladi).
LINK_PREFIX = "igu"
_TOKEN_RE = re.compile(r"^igu([a-z0-9]{10})$")
_BOT_URL = re.compile(r"https://t\.me/ketoshopbot(?![/?\w])")
_TOKEN_ABC = "abcdefghijkmnpqrstuvwxyz23456789"


def folder_key(kind: str, ident) -> str | None:
    if ident in (None, ""):
        return None
    ident = str(ident).strip().lstrip("@").lower() if kind == "ig" else str(int(ident))
    return f"{kind}:{ident}" if ident else None


async def _ensure(conn) -> None:
    global _table_ready
    if _table_ready:
        return
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS person_folder (
            key TEXT PRIMARY KEY,
            summary TEXT NOT NULL DEFAULT '',
            turns INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS person_link_token (
            token TEXT PRIMARY KEY,
            ig_username TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS person_link (
            ig_username TEXT PRIMARY KEY,
            tg_id BIGINT NOT NULL,
            linked_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_person_link_tg ON person_link(tg_id)")
    _table_ready = True


def _clean(text) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= TEXT_MAX else text[:TEXT_MAX - 1] + "…"


# ─────────────────────────── Telegram ↔ Instagram ───────────────────────────

async def ig_token(username: str | None) -> str | None:
    """Shu Instagram username'ning doimiy kodi (bo'lmasa — yaratiladi)."""
    key = folder_key("ig", username)
    if key is None:
        return None
    name = key.split(":", 1)[1]
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        token = await conn.fetchval("SELECT token FROM person_link_token WHERE ig_username = $1", name)
        if token:
            return token
        for _ in range(5):
            token = "".join(secrets.choice(_TOKEN_ABC) for _ in range(10))
            got = await conn.fetchval(
                "INSERT INTO person_link_token (token, ig_username) VALUES ($1, $2) "
                "ON CONFLICT DO NOTHING RETURNING token", token, name)
            if got:
                return got
            existing = await conn.fetchval("SELECT token FROM person_link_token WHERE ig_username = $1", name)
            if existing:
                return existing
    return None


def personal_links(text: str, token: str | None) -> str:
    """Direct javobidagi oddiy bot havolasi → shu odamning havolasi."""
    if not text or not token:
        return text
    return _BOT_URL.sub(f"https://t.me/ketoshopbot?start={LINK_PREFIX}{token}", text)


def parse_payload(payload: str | None) -> str | None:
    m = _TOKEN_RE.match((payload or "").strip().lower())
    return m.group(1) if m else None


async def link_from_start(tg_id: int, payload: str | None) -> str | None:
    """/start igu<kod> — Telegram hisobini Instagram username'ga bog'laydi.
    Bog'langan username yoki None. Hech qachon xato ko'tarmaydi."""
    token = parse_payload(payload)
    if not token:
        return None
    try:
        async with database.pool.acquire() as conn:
            await _ensure(conn)
            name = await conn.fetchval("SELECT ig_username FROM person_link_token WHERE token = $1", token)
            if not name:
                return None
            await conn.execute(
                "INSERT INTO person_link (ig_username, tg_id) VALUES ($1, $2) "
                "ON CONFLICT (ig_username) DO UPDATE SET tg_id = $2, linked_at = NOW() AT TIME ZONE 'UTC'",
                name, int(tg_id))
        logger.info("person folder: tg %s linked to ig %s", tg_id, name)
        return name
    except Exception:
        logger.warning("person link failed for %s", tg_id, exc_info=True)
        return None


async def linked(kind: str, ident) -> list[tuple[str, object]]:
    """Shu odamning boshqa hisoblari: [("ig", username), ...] yoki [("tg", id)]."""
    key = folder_key(kind, ident)
    if key is None:
        return []
    ident = key.split(":", 1)[1]
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        if kind == "tg":
            rows = await conn.fetch("SELECT ig_username FROM person_link WHERE tg_id = $1", int(ident))
            return [("ig", r["ig_username"]) for r in rows]
        tg = await conn.fetchval("SELECT tg_id FROM person_link WHERE ig_username = $1", ident)
        return [("tg", tg)] if tg else []


# ─────────────────────────────── tarix ──────────────────────────────────────

async def _own_rows(conn, kind: str, ident: str) -> list[dict]:
    rows: list[dict] = []
    if kind == "tg":
        for r in await conn.fetch(
                "SELECT created_at, channel, question, answer FROM ai_dialog WHERE user_id = $1 "
                "ORDER BY id DESC LIMIT $2", int(ident), HISTORY_MAX):
            rows.append({"at": r["created_at"], "channel": r["channel"], "them": r["question"],
                         "us": r["answer"]})
        return rows
    for sql, channel in (
            ("SELECT COALESCE(replied_at, created_at) AS at, platform AS ch, text, reply_text "
             "FROM meta_comments WHERE lower(username) = $1 ORDER BY created_at DESC LIMIT $2", None),
            ("SELECT COALESCE(replied_at, created_at) AS at, 'direct' AS ch, text, reply_text "
             "FROM ig_dm_messages WHERE lower(username) = $1 ORDER BY created_at DESC LIMIT $2", "direct")):
        try:
            found = await conn.fetch(sql, ident, HISTORY_MAX)
        except Exception:        # jadval hali yo'q (yangi baza) — papka bo'sh
            logger.debug("folder history query failed", exc_info=True)
            continue
        for r in found:
            rows.append({"at": r["at"], "channel": channel or ("izoh" if r["ch"] == "ig" else "fb izoh"),
                         "them": r["text"] or "", "us": r["reply_text"] or ""})
    return rows


async def history(kind: str, ident, *, public: bool = False) -> list[dict]:
    """Shu odam bilan barcha gaplar, eskidan yangiga: {at, channel, them, us}.
    at — biz javob bergan (yoki u yozgan) vaqt, UTC. Bog'langan hisob (Telegram ↔
    Instagram) gaplari ham qo'shiladi — ochiq izoh javobi (public) bundan mustasno:
    botdagi shaxsiy gaplar ochiq izohga hech qachon kirmaydi."""
    key = folder_key(kind, ident)
    if key is None:
        return []
    ident = key.split(":", 1)[1]
    others = []
    if not public:
        try:
            others = await linked(kind, ident)
        except Exception:
            logger.debug("folder links unavailable", exc_info=True)
    rows: list[dict] = []
    async with database.pool.acquire() as conn:
        rows += await _own_rows(conn, kind, ident)
        for other_kind, other in others:
            extra = await _own_rows(conn, other_kind, str(other).lower() if other_kind == "ig" else str(other))
            for r in extra:
                r["channel"] = ("instagram " if other_kind == "ig" else "telegram ") + r["channel"]
            rows += extra
    rows = [r for r in rows if r["at"] is not None]
    rows.sort(key=lambda r: r["at"])
    return rows[-HISTORY_MAX:]


def hours_since_reply(rows: list[dict], now: datetime | None = None) -> float | None:
    """Oxirgi javobimizdan beri soat. None — hali hech javob bermaganmiz."""
    last = next((r["at"] for r in reversed(rows) if (r.get("us") or "").strip()), None)
    if last is None:
        return None
    return ((now or datetime.utcnow()) - last).total_seconds() / 3600


def needs_greeting(hours: float | None) -> bool:
    return hours is None or hours >= GREET_AFTER_HOURS


def greeting_rule(hours: float | None) -> str:
    if hours is None:
        return ("[SALOM: bu odam bilan birinchi marta gaplashyapsan — javobni qisqa, samimiy salom bilan "
                "boshla.]")
    if hours >= GREET_AFTER_HOURS:
        ago = f"{int(hours // 24)} kun" if hours >= 48 else f"{int(hours)} soat"
        return (f"[SALOM: oxirgi gaplashganimizga {ago} bo'ldi — qisqa salom bilan boshla (mijoz salom bergan "
                "bo'lsa — alik ol). Avvalgi suhbatni eslab, o'rinli bo'lsa bir og'iz bog'la; yangidan tanishma.]")
    mins = max(1, int(hours * 60))
    ago = f"{mins} daqiqa" if mins < 60 else f"{int(hours)} soat"
    return (f"[SALOM BERMA: suhbat davom etyapti ({ago} oldin gaplashgansiz) — salomsiz, to'g'ridan javob ber; "
            "mijoz o'zi salom bersa — qisqa alik.]")


def _lines(rows: list[dict]) -> list[str]:
    out = []
    for r in rows:
        when = (r["at"].replace(microsecond=0) if isinstance(r["at"], datetime) else r["at"])
        line = f"[{when:%d.%m %H:%M}] {r['channel']} | MIJOZ: {_clean(r['them']) or '—'}"
        if (r.get("us") or "").strip():
            line += f" | BIZ: {_clean(r['us'])}"
        out.append(line)
    return out


async def get_summary(key: str) -> dict | None:
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        row = await conn.fetchrow("SELECT summary, turns FROM person_folder WHERE key = $1", key)
    return dict(row) if row else None


async def _summarise(previous: str, rows: list[dict]) -> str | None:
    import ai_provider
    import comment_ai
    import openai
    key = await comment_ai._openai_key()
    if not key:
        return None
    user = ("OLDINGI XULOSA:\n" + (previous or "—") + "\n\nSUHBATLAR (eskidan yangiga):\n"
            + "\n".join(_lines(rows)))[:40000]
    try:
        client = openai.AsyncOpenAI(api_key=key, timeout=90.0, max_retries=1)
        resp = await client.responses.create(
            model=SUMMARY_MODEL, instructions=SUMMARY_RULES,
            input=[{"role": "user", "content": [{"type": "input_text", "text": user}]}],
            reasoning={"effort": "low"}, max_output_tokens=1500)
    except Exception as exc:
        try:
            import ai_balance
            ai_balance.note_error(exc)
        except Exception:
            pass
        logger.info("folder summary failed: %s", exc)
        return None
    try:
        usage = ai_provider._openai_usage(getattr(resp, "usage", None))
        await database.record_ai_usage(SUMMARY_MODEL + USAGE_TAG, "openai", usage.input, usage.cached, usage.output,
                                       ai_provider.estimate_cost(SUMMARY_MODEL, usage.input, usage.cached,
                                                                 usage.output))
    except Exception:
        logger.debug("folder usage not recorded", exc_info=True)
    text = (getattr(resp, "output_text", "") or "").strip()
    return text[:3000] or None


async def refresh(key: str, rows: list[dict], stored: dict | None) -> None:
    """Xulosani yangilaydi (fonda). Bir papka bir vaqtda bir marta."""
    if key in _refreshing:
        return
    _refreshing.add(key)
    try:
        older = rows[:-RAW_KEEP] if len(rows) > RAW_KEEP else []
        if not older:
            return
        text = await _summarise((stored or {}).get("summary") or "", older)
        if not text:
            return
        async with database.pool.acquire() as conn:
            await _ensure(conn)
            await conn.execute(
                "INSERT INTO person_folder (key, summary, turns, updated_at) "
                "VALUES ($1, $2, $3, NOW() AT TIME ZONE 'UTC') "
                "ON CONFLICT (key) DO UPDATE SET summary = $2, turns = $3, updated_at = NOW() AT TIME ZONE 'UTC'",
                key, text, len(rows))
    except Exception:
        logger.warning("folder refresh failed for %s", key, exc_info=True)
    finally:
        _refreshing.discard(key)


def _stale(rows: list[dict], stored: dict | None) -> bool:
    if len(rows) <= RAW_KEEP:
        return False
    return len(rows) - int((stored or {}).get("turns") or 0) >= SUMMARY_EVERY


async def block(kind: str, ident, *, with_recent: bool = True, public: bool = False,
                now: datetime | None = None) -> tuple[str, float | None]:
    """Promptga papka matni va oxirgi javobdan beri soat. Hech qachon xato ko'tarmaydi.

    Har papkaning xulosasi faqat o'z kanallaridan tuziladi (tg — bot/sayt/guruh, ig —
    izoh/Direct). Bog'langan hisob bo'lsa, shaxsiy suhbatda ikkala xulosa va ikkala
    tomonning oxirgi gaplari birga beriladi; ochiq izohda (public) — faqat o'zi."""
    key = folder_key(kind, ident)
    if key is None:
        return "", None
    try:
        own = await history(kind, ident, public=True)
        rows = own if public else await history(kind, ident)
        stored = await get_summary(key)
        summaries = [stored["summary"]] if (stored or {}).get("summary") else []
        others = []
        if not public:
            try:
                others = await linked(kind, ident)
            except Exception:
                logger.debug("folder links unavailable", exc_info=True)
        for other_kind, other in others:
            got = await get_summary(folder_key(other_kind, other))
            if (got or {}).get("summary"):
                where = "Instagram" if other_kind == "ig" else "Telegram"
                summaries.append(f"({where}dagi suhbatlari)\n" + got["summary"])
    except Exception:
        logger.warning("folder read failed for %s", key, exc_info=True)
        return "", None
    hours = hours_since_reply(rows, now)
    if _stale(own, stored):
        asyncio.get_running_loop().create_task(refresh(key, own, stored))
    parts = ["MIJOZ PAPKASI (shu odam bilan avvalgi barcha suhbatlar — yangidan tanishma, so'raganini "
             "qayta so'rama, va'da qilinganini esla; bu ma'lumotni mijozga «papka» deb aytma):"]
    if summaries:
        parts.append("XULOSA:\n" + "\n".join(summaries))
    if with_recent and rows:
        parts.append("OXIRGI GAPLAR:\n" + "\n".join(_lines(rows[-RAW_KEEP:])))
    if len(parts) == 1:
        parts.append("— avval gaplashmaganmiz.")
    parts.append(greeting_rule(hours))
    if public:
        parts.append("[OCHIQ IZOH: javobni hamma ko'radi — Direct'dagi shaxsiy gaplar, buyurtma, manzil, "
                     "telefon va narxlarni izohda tilga olma; papkani faqat odamni tushunish uchun ishlat.]")
    return "\n".join(parts), hours
