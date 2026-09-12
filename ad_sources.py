"""
Reklama manbasi — Facebook/Instagram reklamasidan to'g'ridan-to'g'ri botga.

meta_leads.py Instant Form leadlarini olib keladi: odam Facebookda forma
to'ldiradi, admin qo'ng'iroq qiladi. Bu modul boshqa yo'l — reklamaning
tugmasi odamni botning o'ziga olib keladi:

    https://t.me/ketoshopbot?start=fb_eritritol1

Shunda telefon raqami emas, xaridorning o'zi keladi: savat, katalog, Keto
ballari — hammasi birinchi daqiqadanoq. Formaga qaraganda biroz kamroq odam
bosadi (avtomatik to'ldirish yo'q), lekin kelganlari haqiqiy xaridor bo'ladi.

Har bir reklamaga alohida payload bering — o'shanda qaysi reklama nafaqat
lead, balki PUL keltirganini ko'rasiz (/reklama_manba).

Payload qoidasi: `fb_`, `ig_` yoki `ad_` bilan boshlanadi, keyin lotin
harflari/raqamlar/pastki chiziq. Shu prefikslar tufayli u bloger kodi bilan
ham, musobaqa havolasi (`ref<id>`) bilan ham hech qachon to'qnashmaydi.

Public API:
  parse_payload(payload)        -> manba kodi (yoki None)
  link(source)                  -> reklamaga qo'yiladigan to'liq havola
  attach_new_user(source, uid)  -> yangi foydalanuvchini manbaga bog'lash
  router                        -> /reklama_manba, /reklama_havola
"""
import html
import logging
import re
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import database
from config import ADMIN_IDS, BOT_USERNAME

logger = logging.getLogger(__name__)
router = Router()

# Faqat shu prefikslar reklama manbasi hisoblanadi. Bloger kodlari ham shu
# ko'rinishda bo'lgani uchun (bloggers.slugify -> 'aziza_blog') chegara aniq
# bo'lishi shart: prefikssiz payload bloger kodi bo'lib qolaveradi.
PREFIXES = ("fb_", "ig_", "ad_")
_SOURCE_RE = re.compile(r"^(?:fb|ig|ad)_[a-z0-9_]{1,56}$")

TZ_OFFSET = timedelta(hours=5)   # Asia/Tashkent, fixed UTC+5, no DST

PERIODS = {
    "7":   ("7 kun", 7),
    "30":  ("30 kun", 30),
    "all": ("Butun davr", None),
}


def _fmt(n) -> str:
    return f"{int(n or 0):,}".replace(",", " ")


def _dt(value) -> str:
    if not value:
        return "—"
    try:
        return (value + TZ_OFFSET).strftime("%d.%m.%Y")
    except Exception:
        return "—"


# ───────────────────────────── link & payload ───────────────────────────────

def slugify(name: str) -> str:
    """'Eritritol 1.1' -> 'eritritol_1_1'. Reklama nomini havolaga aylantiradi
    — prefiks qo'shilmaydi, buni link() qiladi."""
    text = (name or "").strip().lower()
    for src, dst in (("o'", "o"), ("g'", "g"), ("oʻ", "o"), ("gʻ", "g"),
                     ("’", ""), ("'", "")):
        text = text.replace(src, dst)
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return re.sub(r"_{2,}", "_", text)[:56]


def normalize(source: str) -> str | None:
    """Har qanday yozuvni ('FB_Eritritol', 'eritritol') yaroqli manba kodiga
    keltiradi. Prefiks yo'q bo'lsa `fb_` qo'shiladi, chunki amalda hamma
    reklama shu yerdan keladi."""
    code = slugify(source)
    if not code:
        return None
    if not code.startswith(PREFIXES):
        code = "fb_" + code
    return code if _SOURCE_RE.match(code) else None


def link(source: str) -> str:
    code = normalize(source) or ""
    return f"https://t.me/{BOT_USERNAME}?start={code}"


def parse_payload(payload: str | None) -> str | None:
    """/start payload -> reklama manbasi, yoki None (u holda chaqiruvchi
    bloger/musobaqa o'qigichlariga o'tadi)."""
    if not payload:
        return None
    candidate = payload.strip().lower().replace("-", "_")
    return candidate if _SOURCE_RE.match(candidate) else None


# ──────────────────────────────── joining ───────────────────────────────────

async def attach_new_user(source: str, user_id: int, payload: str | None = None) -> str | None:
    """Yangi foydalanuvchini kelgan reklamasiga bog'laydi va o'sha manbani
    qaytaradi (chaqiruvchi adminlarga xabarda ko'rsatishi uchun).

    Faqat endi yaratilgan foydalanuvchi uchun chaqiriladi (handlers/start.py::
    ensure_registered) — eski xaridor reklamadan qayta kirsa, uni yangi
    mijoz deb yozish statistikani buzadi. Hech qachon xato ko'tarmaydi."""
    try:
        if user_id in ADMIN_IDS or user_id in database.LEADERBOARD_EXCLUDED_USER_IDS:
            return None
        if not await database.record_ad_referral(user_id, source, payload):
            return None
        logger.info("Ad source %s -> user %s", source, user_id)
        return source
    except Exception:
        logger.exception("attach_new_user failed (source=%s, user=%s)", source, user_id)
        return None


# ──────────────────────────────── hisobot ───────────────────────────────────

async def build_report(period: str = "30") -> str:
    label, days = PERIODS.get(period, PERIODS["30"])
    since = None
    if days:
        since = datetime.utcnow() - timedelta(days=days)
    rows = await database.get_ad_source_stats(since)

    lines = [f"🔗 <b>Reklama manbalari — {label}</b>", ""]
    if not rows:
        lines.append("Hozircha hech kim reklama havolasidan kelmagan.")
        lines.append("")
        lines.append("Havola yasash: <code>/reklama_havola Eritritol 1</code>")
        return "\n".join(lines)

    t_users = sum(int(r["users"]) for r in rows)
    t_buyers = sum(int(r["buyers"]) for r in rows)
    t_revenue = sum(float(r["revenue"]) for r in rows)
    conv = (t_buyers / t_users * 100) if t_users else 0

    lines.append(f"👥 <b>Kelgan:</b> {_fmt(t_users)} ta")
    lines.append(f"🛒 <b>Xarid qilgan:</b> {_fmt(t_buyers)} ta ({conv:.0f}%)")
    lines.append(f"💰 <b>Tushum:</b> {_fmt(t_revenue)} so'm")
    lines.append("")

    for r in rows:
        users = int(r["users"])
        buyers = int(r["buyers"])
        rate = (buyers / users * 100) if users else 0
        revenue = float(r["revenue"])
        lines.append(f"<b>{html.escape(r['source'])}</b>")
        lines.append(
            f"   👥 {_fmt(users)} · 🛒 {_fmt(buyers)} ({rate:.0f}%) · "
            f"📦 {_fmt(r['orders'])} · 💰 {_fmt(revenue)} so'm"
        )
        if buyers:
            lines.append(f"   1 xaridor = {_fmt(revenue / buyers)} so'm")
        lines.append(f"   <i>{_dt(r['first_seen'])} — {_dt(r['last_seen'])}</i>")
        lines.append("")

    lines.append("<i>Tushum — yetkazilgan buyurtmalar bo'yicha. Sarfni "
                 "/reklama dan qarang.</i>")
    return "\n".join(lines)


def _period_keyboard(active: str = "30") -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(
            text=("• " if key == active else "") + label,
            callback_data=f"adsrc:{key}",
        )
        for key, (label, _) in PERIODS.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=[row])


@router.message(Command("reklama_manba"))
async def cmd_sources(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await message.answer(await build_report("30"), parse_mode="HTML",
                         reply_markup=_period_keyboard("30"))


@router.callback_query(F.data.startswith("adsrc:"))
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
                                         reply_markup=_period_keyboard(period))
    except Exception:
        # Telegram rejects an edit that changes nothing, and an admin message
        # can be a photo — never bare-edit one, answer instead.
        await callback.message.answer(text, parse_mode="HTML",
                                      reply_markup=_period_keyboard(period))


@router.message(Command("reklama_havola"))
async def cmd_make_link(message: Message):
    """/reklama_havola Eritritol 1  ->  tayyor havola + qo'llanma."""
    if message.from_user.id not in ADMIN_IDS:
        return
    raw = (message.text or "").split(maxsplit=1)
    if len(raw) < 2:
        await message.answer(
            "🔗 <b>Reklama havolasi</b>\n\n"
            "Reklama nomini yozing:\n"
            "<code>/reklama_havola Eritritol 1</code>\n\n"
            "Javobiga tayyor havola beraman — uni Ads Manager'da reklamaning "
            "tugmasiga (Website URL) qo'ying. Har bir reklamaga alohida nom "
            "bering, shunda qaysi biri pul keltirganini ko'rasiz.",
            parse_mode="HTML",
        )
        return
    code = normalize(raw[1])
    if not code:
        await message.answer("❌ Bu nomdan havola chiqmadi — lotin harflari bilan yozing.")
        return
    await message.answer(
        f"🔗 <b>{html.escape(code)}</b>\n\n"
        f"<code>{html.escape(link(code))}</code>\n\n"
        "Ads Manager → reklama → <b>Website URL</b> maydoniga shuni qo'ying "
        "(Instant Form o'rniga). Natijani <code>/reklama_manba</code> dan "
        "kuzatasiz.",
        parse_mode="HTML",
    )
