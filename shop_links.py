"""
🔗 Sayt havolalari — reklama trafigini kuzatish (owner, 2026-11-07: "shu link
uchun alohida maxsus kepak deb link qilib ber, target uchun ishlatamiz
trafikni kuzatish uchun ... adminlarga o'zi maxsus link nomlarini qo'yish
bilan link yarata olish imkoni qo'sh").

    https://t.me/ketoshopbot/shop?startapp=kepak

Mini App'ning o'z havolasi (t.me/<bot>/shop) oxiriga ?startapp=<kod> qo'shilsa,
Telegram shu kodni ilovaga start_param qilib beradi — imzolangan initData
ichida, shuning uchun uni soxtalashtirib bo'lmaydi. Ilova ochilishi bilan
/api/bot-access chaqiriladi (START bosmagan odamda ham), ochilish shu yerda
yoziladi: bitta ishga tushirish = bitta ochilish (initData'ning auth_date'i
bilan), sahifani yangilash qayta sanalmaydi.

Bu ad_sources.py'dan (/reklama_havola) farqi: u odamni botning /start'iga
olib keladi, bu esa to'g'ridan-to'g'ri do'konga (Mini App).

Har bir havola bo'yicha: necha marta va necha kishi ochdi, ulardan nechtasi
botga yangi a'zo bo'ldi, nechtasi START bosmay ketdi, nechtasi 30 kun ichida
buyurtma berdi va qancha summaga. Adminlar va ichki akkauntlar sanalmaydi.

Adminlar:
  /sayt_havola Kepak   — havola yasaydi (bor bo'lsa — o'sha havolani beradi)
  /sayt_havolalar      — natijalar (7 kun / 30 kun / butun davr)
"""
import html
import logging
import re
import time
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import database
from config import ADMIN_IDS, BOT_USERNAME, ORDER_WATCHER_IDS
from channel_link import SHOP_URL

logger = logging.getLogger(__name__)
router = Router()

# Telegram: startapp — A-Z a-z 0-9 _ - , 64 belgigacha. Bizniki kichik harf,
# raqam va pastki chiziq: retseptlarning «recipe-<slug>» kodi (defis bilan)
# hech qachon sayt havolasi deb olinmaydi.
CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,47}$")

# Owner asked for these two on 2026-11-07 — ready from the first start.
DEFAULTS = (("kepak", "Kepak"), ("gluten_1_qism", "Gluten 1-qism"))

ORDER_WINDOW_DAYS = 30        # havoladan keyin shu kun ichidagi buyurtma sanaladi
NEW_USER_SLACK = timedelta(minutes=10)
REPORT_LIMIT = 25             # Telegram xabari 4096 belgidan oshmasin
NOTICE_WINDOW = timedelta(days=7)   # yangi a'zo xabarida — shu muddatdagi oxirgi havola

PERIODS = {
    "7":   ("7 kun", 7),
    "30":  ("30 kun", 30),
    "all": ("Butun davr", None),
}

_ready = False


def _internal() -> list[int]:
    return sorted({*ADMIN_IDS, *ORDER_WATCHER_IDS, *database.LEADERBOARD_EXCLUDED_USER_IDS})


def _fmt(n) -> str:
    return f"{int(round(float(n or 0))):,}".replace(",", " ")


def slugify(name: str) -> str:
    """'Gluten 1-qism' -> 'gluten_1_qism'; kirillcha nom avval lotinga."""
    from translit import cyr_to_lat
    text = cyr_to_lat((name or "").strip()).lower()
    for src, dst in (("o'", "o"), ("g'", "g"), ("oʻ", "o"), ("gʻ", "g"),
                     ("ö", "o"), ("ğ", "g"), ("ş", "sh"), ("ç", "ch"),
                     ("’", ""), ("ʼ", ""), ("'", "")):
        text = text.replace(src, dst)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return re.sub(r"_{2,}", "_", text)[:48].strip("_")


def link(code: str) -> str:
    return f"{SHOP_URL}?startapp={code}"


def bot_link(code: str) -> str:
    """t.me/<bot>?start=<kod> (owner, 2026-11-08) — the one for Instagram and
    Facebook: the person presses START, so the bot counts every arrival and
    can write to them later; the bot answers with «🛍 Do'konni ochish»."""
    return f"https://t.me/{BOT_USERNAME}?start={code}"


# /start payloads other readers own (handlers/start.py) — never a link's code.
RESERVED = ("sayt", "retsept")
_RESERVED_RE = re.compile(r"^(?:fb_|ig_|ad_|prod_|retsept_|ref\d)")


def _reserved(code: str) -> bool:
    return code in RESERVED or bool(_RESERVED_RE.match(code))


async def ensure() -> None:
    global _ready
    if _ready:
        return
    async with database.pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS shop_links (
                code       TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                created_by BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )""")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS shop_link_opens (
                code      TEXT NOT NULL,
                user_id   BIGINT NOT NULL,
                auth_date BIGINT NOT NULL,
                opened_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (code, user_id, auth_date)
            )""")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS shop_link_opens_user ON shop_link_opens (user_id)")
        # 'app' — the Mini App opened through ?startapp=; 'bot' — /start <kod>.
        await conn.execute(
            "ALTER TABLE shop_link_opens ADD COLUMN IF NOT EXISTS via TEXT NOT NULL DEFAULT 'app'")
        for code, name in DEFAULTS:
            await conn.execute(
                "INSERT INTO shop_links (code, name) VALUES ($1, $2) ON CONFLICT (code) DO NOTHING",
                code, name)
    _ready = True


async def record_open(user_id: int | None, start_param: str | None, auth_date) -> bool:
    """One Mini App launch through a known link. Never raises — the shop
    must open whatever happens here."""
    code = (start_param or "").strip()
    if not user_id or not CODE_RE.match(code):
        return False
    try:
        auth = int(auth_date or 0)
        await ensure()
        async with database.pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO shop_link_opens (code, user_id, auth_date)
                   SELECT $1, $2, $3 WHERE EXISTS (SELECT 1 FROM shop_links WHERE code = $1)
                   ON CONFLICT DO NOTHING RETURNING code""",
                code, int(user_id), auth)
        return row is not None
    except Exception:
        logger.warning("shop link open %s by %s not recorded", code, user_id, exc_info=True)
        return False


async def code_for_start(payload: str | None) -> str | None:
    """/start <kod> -> that tracked link's code, or None. Never raises."""
    code = (payload or "").strip().lower().replace("-", "_")
    if not CODE_RE.match(code) or _reserved(code):
        return None
    try:
        await ensure()
        async with database.pool.acquire() as conn:
            return await conn.fetchval("SELECT code FROM shop_links WHERE code = $1", code)
    except Exception:
        logger.warning("shop link lookup for /start %r failed", payload, exc_info=True)
        return None


async def note_start(user_id: int, payload: str | None) -> str | None:
    """A /start through a tracked link: counted (every press of START is one
    arrival) and the link's code returned. Called before the channel gate
    too, so people who never join are counted as well. Never raises."""
    code = await code_for_start(payload)
    if not code:
        return None
    try:
        async with database.pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO shop_link_opens (code, user_id, auth_date, via)
                   VALUES ($1, $2, $3, 'bot') ON CONFLICT DO NOTHING""",
                code, int(user_id), time.time_ns() // 1_000_000)
    except Exception:
        logger.warning("bot start %s by %s not recorded", code, user_id, exc_info=True)
    return code


async def last_open(user_id: int) -> dict | None:
    """The link this person last opened the shop through (within
    NOTICE_WINDOW) — for the admins' «Yangi foydalanuvchi» notice. The bot
    is reached from the site's START screen without the code, so it is
    looked up by user id. Never raises."""
    try:
        await ensure()
        async with database.pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT o.code, l.name
                     FROM shop_link_opens o JOIN shop_links l ON l.code = o.code
                    WHERE o.user_id = $1 AND o.opened_at >= LOCALTIMESTAMP - $2::interval
                    ORDER BY o.opened_at DESC LIMIT 1""",
                int(user_id), NOTICE_WINDOW)
        return dict(row) if row else None
    except Exception:
        logger.warning("shop link lookup for %s failed", user_id, exc_info=True)
        return None


async def ensure_code(code: str, name: str) -> bool:
    """Make `code` a tracked link if it is not one — an ad's button already
    carries it (ad_campaigns.py), and an unknown code is never counted.
    An existing link keeps its name. True when it was created."""
    if not CODE_RE.match(code) or _reserved(code):
        return False
    await ensure()
    async with database.pool.acquire() as conn:
        made = await conn.fetchval(
            "INSERT INTO shop_links (code, name) VALUES ($1, $2) ON CONFLICT (code) DO NOTHING RETURNING code",
            code, (name or code).strip()[:80])
    return made is not None


async def create(name: str, by: int | None) -> tuple[str, str, bool] | None:
    """(code, name, created). An existing code keeps its first name."""
    code = slugify(name)
    if not CODE_RE.match(code) or _reserved(code):
        return None
    await ensure()
    async with database.pool.acquire() as conn:
        made = await conn.fetchval(
            """INSERT INTO shop_links (code, name, created_by) VALUES ($1, $2, $3)
               ON CONFLICT (code) DO NOTHING RETURNING code""",
            code, name.strip()[:80], by)
        if made:
            return code, name.strip()[:80], True
        old = await conn.fetchval("SELECT name FROM shop_links WHERE code = $1", code)
    return code, old or name.strip(), False


async def people_between(codes: list[str], start: datetime | None,
                         end: datetime | None) -> dict[str, dict]:
    """{code: {"bot": n, "app": m}} — distinct people who came through each
    link in [start, end): by pressing START (?start=) and by opening the shop
    (?startapp=). The same people as /sayt_havolalar counts, for a window —
    ad_campaigns.py sets it beside Meta's numbers for the same day."""
    out = {c: {"bot": 0, "app": 0} for c in codes}
    if not codes:
        return out
    await ensure()
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT code,
                      COUNT(DISTINCT user_id) FILTER (WHERE via = 'bot')  AS bot,
                      COUNT(DISTINCT user_id) FILTER (WHERE via <> 'bot') AS app
                 FROM shop_link_opens
                WHERE code = ANY($1::text[])
                  AND ($2::timestamp IS NULL OR opened_at >= $2)
                  AND ($3::timestamp IS NULL OR opened_at < $3)
                  AND user_id <> ALL($4::bigint[])
                GROUP BY code""",
            list(codes), start, end, _internal())
    for r in rows:
        out[r["code"]] = {"bot": int(r["bot"]), "app": int(r["app"])}
    return out


async def stats(since: datetime | None) -> list[dict]:
    """Per link, people whose launches fall in the period: launches, people,
    new members, people who never pressed START, and their orders placed
    within ORDER_WINDOW_DAYS of their first launch through it (not
    cancelled, self-placed — the shop's sale basis)."""
    await ensure()
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            f"""WITH o AS (
                    SELECT code, user_id, MIN(opened_at) AS first_at, COUNT(*) AS opens,
                           bool_or(via = 'bot') AS by_bot, bool_or(via <> 'bot') AS by_app
                      FROM shop_link_opens
                     WHERE ($1::timestamp IS NULL OR opened_at >= $1)
                       AND user_id <> ALL($2::bigint[])
                     GROUP BY code, user_id)
                SELECT l.code, l.name, l.created_at,
                       COALESCE(SUM(o.opens), 0)                              AS opens,
                       COUNT(o.user_id)                                       AS people,
                       COUNT(o.user_id) FILTER (WHERE o.by_bot)               AS people_bot,
                       COUNT(o.user_id) FILTER (WHERE o.by_app)               AS people_app,
                       COUNT(o.user_id) FILTER (
                           WHERE u.user_id IS NOT NULL AND u.created_at >= o.first_at - $3::interval)
                                                                              AS new_users,
                       COUNT(o.user_id) FILTER (WHERE o.user_id IS NOT NULL AND u.user_id IS NULL)
                                                                              AS no_start,
                       COUNT(o.user_id) FILTER (WHERE t.orders > 0)           AS buyers,
                       COALESCE(SUM(t.orders), 0)                             AS orders,
                       COALESCE(SUM(t.revenue), 0)                            AS revenue,
                       MAX(o.first_at)                                        AS last_at
                  FROM shop_links l
                  LEFT JOIN o ON o.code = l.code
                  LEFT JOIN users u ON u.user_id = o.user_id
                  LEFT JOIN LATERAL (
                       SELECT COUNT(*) AS orders, COALESCE(SUM(x.total), 0) AS revenue
                         FROM orders x
                        WHERE x.user_id = o.user_id
                          AND x.created_at >= o.first_at
                          AND x.created_at < o.first_at + $4::interval
                          AND {database.sale_sql("x")}
                          AND COALESCE(x.source, 'bot') NOT IN ('manual', 'b2b', 'test')
                  ) t ON TRUE
                 GROUP BY l.code, l.name, l.created_at
                 ORDER BY COUNT(o.user_id) DESC, l.created_at DESC""",
            since, _internal(), NEW_USER_SLACK, timedelta(days=ORDER_WINDOW_DAYS))
    return [dict(r) for r in rows]


# ───────────────────────────── bot ─────────────────────────────

async def build_report(period: str = "30") -> str:
    label, days = PERIODS.get(period, PERIODS["30"])
    since = datetime.utcnow() - timedelta(days=days) if days else None
    rows = await stats(since)
    lines = [f"🔗 <b>Sayt havolalari — {label}</b>", ""]
    if not rows:
        lines.append("Hozircha havola yo'q. Yasash: <code>/sayt_havola Kepak</code>")
        return "\n".join(lines)
    for r in rows[:REPORT_LIMIT]:
        people, buyers = int(r["people"]), int(r["buyers"])
        lines.append(f"<b>{html.escape(r['name'])}</b>")
        lines.append(f"🤖 <code>{html.escape(bot_link(r['code']))}</code>")
        lines.append(f"🛍 <code>{html.escape(link(r['code']))}</code>")
        if not people:
            lines.append("   Hali hech kim kelmagan")
        else:
            rate = buyers / people * 100
            lines.append(f"   👁 Keldi: {_fmt(r['opens'])} marta · {_fmt(people)} kishi "
                         f"(🤖 botga {_fmt(r['people_bot'])} · 🛍 do'konga {_fmt(r['people_app'])})")
            lines.append(f"   🆕 Yangi a'zo: {_fmt(r['new_users'])} · 🚪 Ro'yxatdan o'tmagan: {_fmt(r['no_start'])}")
            lines.append(f"   🛒 Buyurtma: {_fmt(r['orders'])} ta · {_fmt(buyers)} kishi ({rate:.0f}%)"
                         f" · 💰 {_fmt(r['revenue'])} so'm")
        lines.append("")
    if len(rows) > REPORT_LIMIT:
        lines.append(f"… yana {len(rows) - REPORT_LIMIT} ta havola")
        lines.append("")
    lines.append("<i>Adminlar va ichki akkauntlar sanalmaydi. Buyurtma — havola orqali "
                 f"kirgandan keyin {ORDER_WINDOW_DAYS} kun ichida berilgan, bekor qilinmagan "
                 "buyurtmalar (qo'lda kiritilganlarsiz). Ro'yxatdan o'tmagan — havolani ochgan, "
                 "lekin botda START bosmagan yoki kanalga a'zo bo'lmagan.</i>")
    lines.append("<i>Reklamaga 🤖 bot havolasini qo'ying: har bir kelgan START bosadi — "
                 "aniq sanaladi va keyin unga xabar yuborish mumkin.</i>")
    lines.append("Yangi havola: <code>/sayt_havola Nomi</code>")
    return "\n".join(lines)


def _period_keyboard(active: str = "30") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=("• " if key == active else "") + label,
                             callback_data=f"shoplnk:{key}")
        for key, (label, _) in PERIODS.items()
    ], [InlineKeyboardButton(text="➕ Yangi havola", callback_data="adm_ads:newlink"),
        InlineKeyboardButton(text="🔙 Reklama menyusi", callback_data="admin_menu:ads")]])


@router.message(Command("sayt_havola"), F.chat.type == "private")
async def cmd_make(message: Message):
    """/sayt_havola Gluten 1-qism -> tayyor havola."""
    if message.from_user.id not in ADMIN_IDS:
        return
    raw = (message.text or "").split(maxsplit=1)
    if len(raw) < 2:
        await message.answer(
            "🔗 <b>Sayt havolasi</b>\n\n"
            "Havola nomini yozing:\n<code>/sayt_havola Kepak</code>\n\n"
            "Javobiga do'konni (Mini App) to'g'ridan-to'g'ri ochadigan havola beraman — "
            "uni reklamaga qo'ying. Har bir reklamaga alohida nom bering: kim ochgani, "
            "kim sotib olgani <code>/sayt_havolalar</code> da ko'rinadi.",
            parse_mode="HTML")
        return
    try:
        made = await create(raw[1], message.from_user.id)
    except Exception:
        logger.exception("shop link create failed")
        await message.answer("❌ Havola saqlanmadi — birozdan keyin qayta urinib ko'ring.")
        return
    if not made:
        await message.answer("❌ Bu nomdan havola chiqmadi — harf yoki raqam bilan yozing.")
        return
    await message.answer(made_text(made), parse_mode="HTML", disable_web_page_preview=True)


def made_text(made: tuple[str, str, bool]) -> str:
    """The reply to a new link — /sayt_havola and «➕ Yangi havola yasash»."""
    code, name, created = made
    head = "✅ Havola tayyor" if created else "ℹ️ Bu havola avval yaratilgan"
    return (
        f"{head}: <b>{html.escape(name)}</b>\n\n"
        "🤖 <b>Reklama uchun (bot orqali)</b> — har bir kelgan sanaladi va botga "
        "obuna bo'lib qoladi, keyin «🛍 Do'konni ochish» tugmasi chiqadi:\n"
        f"<code>{html.escape(bot_link(code))}</code>\n\n"
        "🛍 To'g'ridan-to'g'ri do'kon:\n"
        f"<code>{html.escape(link(code))}</code>\n\n"
        "Natijani <code>/sayt_havolalar</code> dan kuzatasiz.")


@router.message(Command("sayt_havolalar"), F.chat.type == "private")
async def cmd_report(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer(await build_report("30"), parse_mode="HTML",
                         reply_markup=_period_keyboard("30"), disable_web_page_preview=True)


@router.callback_query(F.data.startswith("shoplnk:"))
async def cb_period(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Faqat adminlar uchun", show_alert=True)
        return
    period = callback.data.split(":", 1)[1]
    if period not in PERIODS:
        await callback.answer()
        return
    await callback.answer()
    text = await build_report(period)
    try:
        await callback.message.edit_text(text, parse_mode="HTML",
                                         reply_markup=_period_keyboard(period),
                                         disable_web_page_preview=True)
    except Exception:
        # An unchanged report can't be "edited" — send it fresh instead.
        await callback.message.answer(text, parse_mode="HTML",
                                      reply_markup=_period_keyboard(period),
                                      disable_web_page_preview=True)
