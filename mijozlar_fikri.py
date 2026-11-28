"""💬 «Peshqadam mijozlarimiz fikri» — kanalda har 2 kunda bir eng yaxshi izoh.

Egasi, 2026-11-28: "endi peshqadam mijozlarimiz fikri rubrikasini ham
boshlaymiz, eng yaxshi izoh va tashakkurnomalarni kanalda xar 2 kunda 1 e'lon
qilib borishimiz kerak", "bot orqali kelgan xabarlardan ham olgin". Tanlov:
admin tasdiqlaydi; kanalda faqat ism (familiya, telefon, username — yo'q).

Manbalar (sources):
  * review — mahsulotga baho (4–5★) va izoh;
  * site   — saytdagi baho oynasi (4–5★) va izoh;
  * nps    — "tavsiya qilasizmi" 9–10 va izoh;
  * bot    — botga yozgan xabari (support_messages 'in', ai_dialog bot/sayt):
             faqat minnatdorchilik / maqtov so'zlari bo'lgan, shikoyatsiz matn.
Do'kon akkauntlari, /malumotlarim da o'chirganlar va havolali matnlar kirmaydi.

Ish tartibi: START dan har EVERY_DAYS kunda CANDIDATE_HOUR da eng yaxshi
nomzod hamma adminlarga keladi — kanalda qanday chiqishi bilan:
«✅ Kanalga chiqarish» / «⏭ Boshqasi». Birinchi bosgan admin hal qiladi.
✅ — darhol kanalga (09:00–21:00 oralig'ida; kechasi bosilsa — ertalab).
⏭ — bu izoh qayta taklif qilinmaydi, keyingisi chiqadi. Hech kim bosmasa —
o'sha kuni hech narsa chiqmaydi (o'zi chiqmaydi).

Har bir izohning holati (quote_picks) saqlanadi: bir izoh ikki marta chiqmaydi.
/mijoz_fikri — keyingi nomzodni hozir ko'rish (faqat adminlar).
"""
from __future__ import annotations

import asyncio
import html
import logging
import re
from datetime import date, datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import channel_link
import database
from config import ADMIN_IDS, REQUIRED_CHANNEL_ID

logger = logging.getLogger(__name__)
router = Router(name="mijozlar_fikri")

START = date(2026, 11, 29)
EVERY_DAYS = 2
CANDIDATE_HOUR = 11          # nomzod adminlarga; kanal: 10 (TOP-10), 11 (retsept), 16 (fakt)
POST_FROM, POST_TO = 9, 21   # kanalga shu soatlarda chiqadi
CHECK_EVERY = 600
TZ_OFFSET = timedelta(hours=5)
MIN_LEN, MAX_LEN = 20, 600
HASHTAG = "#мижозларфикри"
TITLE = "💬 <b>Пешқадам мижозларимиз фикри</b>"
CLOSING = "💚 Фикрингиз учун раҳмат! Сиз ҳам маҳсулотларимиз ҳақида изоҳда ёзиб қолдиринг."

_PRAISE = re.compile(
    r"rahmat|raxmat|рахмат|раҳмат|ташаккур|tashakkur|спасибо|благодар|"
    r"yoqdi|ёқди|ёкди|ёкти|понрав|zo'?r|зўр|зор\b|ajoyib|ажойиб|отличн|супер|super|"
    r"mazali|мазали|вкусн|sifatli|сифатли|качествен|rozi|рози|"
    r"yana ol|яна ол|doim ol|доим ол|tavsiya|тавсия|рекоменд|xursand|хурсанд|рад[аы]?\b",
    re.IGNORECASE)
_COMPLAINT = re.compile(
    r"yomon|ёмон|плох|shikoyat|шикоят|жалоб|kelmadi|келмади|не приш|qachon|қачон|качон|"
    r"buzil|бузил|испорч|qaytar|қайтар|вернит|aldad|алдад|обман|kech|кеч\b|опозд|"
    r"yo'q|йўқ|нет\b|xato|хато|ошибк",
    re.IGNORECASE)
_LINK = re.compile(r"https?://|t\.me/|www\.|@\w{4,}", re.IGNORECASE)
_PHONE = re.compile(r"\+?\d[\d \-()]{8,}\d")

_cards: dict[str, list[tuple[int, int]]] = {}       # key -> [(admin chat, message id)]
_table_ready = False


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


def is_day(day: date) -> bool:
    return day >= START and (day - START).days % EVERY_DAYS == 0


async def _ensure(conn) -> None:
    global _table_ready
    if _table_ready:
        return
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS quote_picks (
            key TEXT PRIMARY KEY,
            status TEXT NOT NULL,                    -- shown | posted | skipped | approved
            decided_by BIGINT,
            post_text TEXT,
            channel_message_id BIGINT,
            created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
            decided_at TIMESTAMP
        )
    """)
    _table_ready = True


# ───────────────────────── nomzodlar ─────────────────────────

def clean(text: str | None) -> str:
    """Mijozning o'z so'zlari — telefon raqami yashiriladi, ortiqcha bo'shliq olinadi."""
    t = " ".join(str(text or "").split())
    t = _PHONE.sub("…", t)
    if len(t) > MAX_LEN:
        t = t[:MAX_LEN].rsplit(" ", 1)[0] + "…"
    return t


def usable(text: str) -> bool:
    return MIN_LEN <= len(text) and not _LINK.search(text)


def praise_only(text: str) -> bool:
    """Botga yozilgan xabar: maqtov/minnatdorchilik bor, shikoyat yo'q."""
    return bool(_PRAISE.search(text)) and not _COMPLAINT.search(text)


def score(c: dict) -> float:
    s = {"review": 3.0, "nps": 2.5, "site": 1.5, "bot": 1.0}[c["source"]]
    if c.get("rating"):
        s += (c["rating"] - 4) * 1.5
    s += min(len(c["text"]), 320) / 110
    if _PRAISE.search(c["text"]):
        s += 0.7
    try:
        age = (datetime.utcnow() - c["created_at"].replace(tzinfo=None)).days
        s += 1.0 if age <= 14 else 0.0
    except Exception:
        pass
    return s


async def _bot_messages(internal: set[int]) -> list[dict]:
    rows = []
    async with database.pool.acquire() as conn:
        for sql, src in (
            ("SELECT id, user_id, text, created_at FROM support_messages WHERE direction = 'in' "
             "AND created_at > NOW() - INTERVAL '120 days'", "sm"),
            ("SELECT id, user_id, question AS text, created_at FROM ai_dialog "
             "WHERE channel IN ('bot', 'site') AND created_at > NOW() - INTERVAL '120 days'", "ai"),
        ):
            try:
                for r in await conn.fetch(sql):
                    rows.append((src, dict(r)))
            except Exception:
                logger.info("mijozlar fikri: %s not readable", src, exc_info=True)
    out = []
    for src, r in rows:
        if r["user_id"] in internal:
            continue
        text = clean(r["text"])
        if usable(text) and praise_only(text):
            out.append({"key": f"bot:{src}:{r['id']}", "source": "bot", "user_id": r["user_id"],
                        "text": text, "rating": None, "created_at": r["created_at"], "product_id": None})
    return out


async def candidates() -> list[dict]:
    """Hali ko'rsatilmagan hamma nomzod, eng yaxshisi birinchi."""
    overview = await database.get_feedback_overview()
    internal = set(database.LEADERBOARD_EXCLUDED_USER_IDS) | set(ADMIN_IDS)
    out: list[dict] = []
    for r in overview.get("reviews") or []:
        text = clean(r.get("comment"))
        if r.get("internal") or (r.get("rating") or 0) < 4 or not usable(text):
            continue
        out.append({"key": f"review:{r['id']}", "source": "review", "user_id": r.get("user_id"),
                    "text": text, "rating": r.get("rating"), "created_at": _dt(r.get("created_at")),
                    "product_id": r.get("product_id"), "product_name": r.get("product_name"),
                    "full_name": r.get("full_name"), "username": r.get("username")})
    for r in overview.get("site") or []:
        text = clean(r.get("comment"))
        if r.get("internal") or (r.get("rating") or 0) < 4 or not usable(text):
            continue
        out.append({"key": f"site:{r['id']}", "source": "site", "user_id": r.get("user_id"),
                    "text": text, "rating": r.get("rating"), "created_at": _dt(r.get("created_at")),
                    "product_id": None, "full_name": r.get("full_name"), "username": r.get("username")})
    for r in overview.get("nps") or []:
        text = clean(r.get("comment"))
        if r.get("internal") or (r.get("score") or 0) < 9 or not usable(text):
            continue
        out.append({"key": f"nps:{r['id']}", "source": "nps", "user_id": r.get("user_id"),
                    "text": text, "rating": None, "created_at": _dt(r.get("created_at")),
                    "product_id": None, "full_name": r.get("full_name"), "username": r.get("username")})
    out += await _bot_messages(internal)
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        done = {r["key"] for r in await conn.fetch("SELECT key FROM quote_picks")}
    import customer_portrait
    fresh, seen_text = [], set()
    for c in sorted(out, key=score, reverse=True):
        norm = c["text"].lower()[:80]
        if c["key"] in done or norm in seen_text:
            continue
        if c.get("user_id") and await customer_portrait.is_opted_out(c["user_id"]):
            continue
        seen_text.add(norm)
        fresh.append(c)
    return fresh


def _dt(v):
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "")).replace(tzinfo=None)
    except Exception:
        return datetime.utcnow()


# ───────────────────────── post ─────────────────────────

def first_name(full_name: str | None) -> str | None:
    word = (str(full_name or "").strip().split() or [""])[0]
    word = word.strip(".,!-_")
    if 2 <= len(word) <= 20 and re.fullmatch(r"[A-Za-zА-Яа-яЁёЎўҚқҒғҲҳ'ʻʼ‘’-]+", word):
        return word[0].upper() + word[1:].lower()      # «НАФИСА» → «Нафиса»
    return None


async def _who(c: dict) -> tuple[str, str | None]:
    """(kanalda ko'rinadigan ism, hudud) — faqat ism, familiyasiz."""
    full = c.get("full_name")
    region = None
    if c.get("user_id"):
        async with database.pool.acquire() as conn:
            if not full:
                full = await conn.fetchval("SELECT full_name FROM users WHERE user_id = $1", c["user_id"])
            row = await conn.fetchrow(
                """SELECT address, latitude, longitude FROM orders
                   WHERE user_id = $1 AND COALESCE(source, 'bot') NOT IN ('manual', 'b2b')
                   ORDER BY created_at DESC LIMIT 1""", c["user_id"])
        if row:
            import regions
            key = regions.region_of(dict(row))
            if key != regions.UNKNOWN_KEY:
                region = regions.region_name(key, "uz")
    return first_name(full) or "Mijozimiz", region


async def post_text(c: dict) -> str:
    from translit import lat_to_cyr
    name, region = await _who(c)
    who = lat_to_cyr(name + (f", {region}" if region else ""))
    lines = [TITLE, "", f"<blockquote>{html.escape(c['text'], quote=False)}</blockquote>",
             f"— {html.escape(who, quote=False)}"]
    if c.get("rating"):
        lines.append("⭐" * int(c["rating"]))
    link = None
    if c.get("product_id"):
        try:
            p = await database.get_product(int(c["product_id"]))
            if p and p.get("is_active") == 1:
                import product_card
                link = channel_link.link_line(product_card.product_link(p["id"]),
                                              "🛒 " + lat_to_cyr(p.get("name") or ""))
        except Exception:
            logger.warning("mijozlar fikri: product link failed", exc_info=True)
    lines += ["", link or channel_link.link_line(channel_link.SHOP_URL, channel_link.SHOP_LABEL),
              "", CLOSING, "", HASHTAG]
    return "\n".join(lines)


SOURCE_LABEL = {"review": "mahsulotga baho", "site": "saytdagi baho", "nps": "tavsiya so'rovi",
                "bot": "botga yozgan xabari"}


def _admin_card(c: dict, post: str) -> str:
    who = " ".join(x for x in (c.get("full_name") or "", f"@{c['username']}" if c.get("username") else "") if x)
    meta = [f"Manba: {SOURCE_LABEL[c['source']]}"]
    if c.get("rating"):
        meta.append(f"{c['rating']}★")
    if c.get("product_name"):
        meta.append(html.escape(c["product_name"], quote=False))
    return ("🗳 <b>Rubrika nomzodi</b> — kanalga shunday chiqadi:\n\n" + post +
            "\n\n━━━━━━━━━━\n" + " · ".join(meta) +
            (f"\n👤 {html.escape(who, quote=False)} (faqat sizga ko'rinadi)" if who else "") +
            "\n\n✅ — kanalga chiqadi · ⏭ — bu izoh qayta taklif qilinmaydi, keyingisi keladi.")


def _kb(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Kanalga chiqarish", callback_data=f"mfk:ok:{key}"[:64]),
        InlineKeyboardButton(text="⏭ Boshqasi", callback_data=f"mfk:next:{key}"[:64]),
    ]])


_pending: dict[str, dict] = {}            # key -> candidate (+ post) shown to admins


async def offer(bot: Bot, chat_ids=None) -> bool:
    """Eng yaxshi nomzodni adminlarga yuboradi. False — nomzod qolmagan."""
    pool = await candidates()
    if not pool:
        for admin in chat_ids or ADMIN_IDS:
            try:
                await bot.send_message(admin, "💬 «Peshqadam mijozlarimiz fikri»: yangi yaxshi izoh hozircha yo'q.")
            except Exception:
                pass
        return False
    c = pool[0]
    post = await post_text(c)
    c["post"] = post
    _pending[c["key"]] = c
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        await conn.execute("INSERT INTO quote_picks (key, status, post_text) VALUES ($1, 'shown', $2) "
                           "ON CONFLICT (key) DO NOTHING", c["key"], post)
    _cards[c["key"]] = []
    for admin in chat_ids or ADMIN_IDS:
        try:
            m = await bot.send_message(admin, _admin_card(c, post), parse_mode=ParseMode.HTML,
                                       reply_markup=_kb(c["key"]), disable_web_page_preview=True)
            _cards[c["key"]].append((admin, m.message_id))
        except Exception:
            logger.warning("mijozlar fikri: card to %s failed", admin, exc_info=True)
    return True


async def _decide(key: str, status: str, admin_id: int) -> bool:
    """Birinchi qaror yutadi."""
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        row = await conn.fetchrow(
            """UPDATE quote_picks SET status = $2, decided_by = $3, decided_at = NOW() AT TIME ZONE 'UTC'
               WHERE key = $1 AND status = 'shown' RETURNING key""", key, status, admin_id)
    return row is not None


async def publish(bot: Bot, key: str) -> int | None:
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        post = await conn.fetchval("SELECT post_text FROM quote_picks WHERE key = $1", key)
    if not post or not REQUIRED_CHANNEL_ID:
        return None
    m = await bot.send_message(REQUIRED_CHANNEL_ID, post, parse_mode=ParseMode.HTML,
                               disable_web_page_preview=True)
    async with database.pool.acquire() as conn:
        await conn.execute("UPDATE quote_picks SET status = 'posted', channel_message_id = $2 WHERE key = $1",
                           key, m.message_id)
    return m.message_id


async def _close_cards(bot: Bot, key: str, note: str, except_msg=None) -> None:
    for chat, mid in _cards.pop(key, []):
        if except_msg and (chat, mid) == except_msg:
            continue
        try:
            await bot.edit_message_reply_markup(chat_id=chat, message_id=mid, reply_markup=None)
            await bot.send_message(chat, note, reply_to_message_id=mid, parse_mode=ParseMode.HTML)
        except Exception:
            pass


@router.callback_query(F.data.startswith("mfk:"))
async def on_button(cb: CallbackQuery):
    if cb.from_user.id not in ADMIN_IDS:
        await cb.answer()
        return
    _, action, key = cb.data.split(":", 2)
    who = html.escape(cb.from_user.full_name or str(cb.from_user.id), quote=False)
    here = (cb.message.chat.id, cb.message.message_id)
    if action == "ok":
        hour = _now_tk().hour
        status = "approved"
        if not await _decide(key, status, cb.from_user.id):
            await cb.answer("Bu izoh bo'yicha qaror qilingan.", show_alert=True)
            return
        await cb.answer("✅")
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        if POST_FROM <= hour < POST_TO:
            try:
                await publish(cb.bot, key)
                await cb.message.answer("✅ Kanalga chiqdi.")
                await _close_cards(cb.bot, key, f"✅ {who} kanalga chiqardi.", here)
            except Exception:
                logger.exception("mijozlar fikri: publish failed")
                await cb.message.answer("⚠️ Kanalga chiqmadi — 10 daqiqadan keyin bot qayta urinadi.")
        else:
            await cb.message.answer(f"✅ Tasdiqlandi — kanalga ertalab {POST_FROM:02d}:00 dan keyin chiqadi.")
            await _close_cards(cb.bot, key, f"✅ {who} tasdiqladi (ertalab chiqadi).", here)
        return
    if action == "next":
        if not await _decide(key, "skipped", cb.from_user.id):
            await cb.answer("Bu izoh bo'yicha qaror qilingan.", show_alert=True)
            return
        await cb.answer("⏭")
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await _close_cards(cb.bot, key, f"⏭ {who} boshqasini so'radi.", here)
        await offer(cb.bot)
        return
    await cb.answer()


@router.message(Command("mijoz_fikri"))
async def cmd_next(message: Message):
    if message.chat.type != "private" or message.from_user.id not in ADMIN_IDS:
        return
    left = len(await candidates())
    await message.answer(f"💬 «Peshqadam mijozlarimiz fikri»: tayyor nomzodlar — {left} ta. "
                         f"Kanalga har {EVERY_DAYS} kunda bittadan, tasdiqlaganingizdan keyin chiqadi.")
    if left:
        await offer(message.bot, [message.from_user.id])


# ───────────────────────── jadval ─────────────────────────

async def _tick(bot: Bot) -> None:
    now = _now_tk()
    # Kechasi tasdiqlanganlari — ertalab.
    if POST_FROM <= now.hour < POST_TO and database.pool is not None:
        async with database.pool.acquire() as conn:
            await _ensure(conn)
            waiting = [r["key"] for r in await conn.fetch("SELECT key FROM quote_picks WHERE status = 'approved'")]
        for key in waiting:
            try:
                await publish(bot, key)
            except Exception:
                logger.exception("mijozlar fikri: queued publish failed (%s)", key)
    day = now.date()
    if not REQUIRED_CHANNEL_ID or not is_day(day) or not CANDIDATE_HOUR <= now.hour < POST_TO:
        return
    claim = f"mijozlar-fikri-{day.isoformat()}"
    if not await database.claim_release_notes(claim):
        return
    try:
        await offer(bot)
    except Exception:
        await database.release_release_notes(claim)
        logger.exception("mijozlar fikri: offer failed")


async def scheduler_loop(bot: Bot) -> None:
    await asyncio.sleep(120)
    while True:
        try:
            await _tick(bot)
        except Exception:
            logger.exception("mijozlar fikri tick failed")
        await asyncio.sleep(CHECK_EVERY)
