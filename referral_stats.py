"""
Referal statistikasi — hamma kanal bitta ekranda.

Mijoz botga to'rt yo'ldan kelishi mumkin va har birining o'z bo'limi bor edi:
bloger havolasi (bloggers.py), reklama havolasi (ad_sources.py), mijozning
do'stiga bergan havolasi (referral_contest.py) va hech qanday havolasiz.
Egasi "barcha referallar haqida statistika tursin" degani shu: qaysi yo'l
qancha odam, qancha XARIDOR va qancha PUL keltirganini yonma-yon ko'rish.

Hisob database.get_referral_channel_stats da — sayt paneli ham o'sha
funksiyani chaqiradi, shunda ikki joyda ikki xil raqam chiqmaydi. Tushum
faqat yetkazilgan buyurtmalar bo'yicha, admin qo'lda kiritgan va B2B
qatorlarsiz.

Kirish: Admin panel -> Marketing -> 📊 Referal statistikasi, yoki /referallar.
"""
import logging
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import database
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router()

PERIODS = {
    "7": ("7 kun", 7),
    "30": ("30 kun", 30),
    "all": ("Butun davr", None),
}

CHANNELS = [
    ("bloger", "📢 Bloger"),
    ("reklama", "📣 Reklama"),
    ("dost", "🤝 Do'st taklifi"),
    ("togridan", "➡️ To'g'ridan"),
]


def _fmt(n) -> str:
    return f"{int(n or 0):,}".replace(",", " ")


def _pct(part, whole) -> str:
    return f"{(part / whole * 100):.0f}%" if whole else "0%"


def _esc(text) -> str:
    """Telegram HTML uchun: faqat &, <, > — apostrof va tirnoqqa tegilmaydi,
    aks holda "zig'ir" xabarda &#x27; bo'lib ko'rinadi (handlers/cart.py dagi
    _escape_html bilan bir xil)."""
    return (str(text or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _short(text: str, limit: int = 28) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _name(row: dict, limit: int = 28) -> str:
    label = row.get("full_name") or (f"@{row['username']}" if row.get("username") else None)
    return _esc(_short(label or f"ID {row.get('user_id')}", limit))


async def build_report(period: str = "30") -> str:
    label, days = PERIODS.get(period, PERIODS["30"])
    since = datetime.utcnow() - timedelta(days=days) if days else None

    channels = {r["channel"]: r for r in await database.get_referral_channel_stats(since)}
    total_users = sum(int(r["users"]) for r in channels.values())
    total_buyers = sum(int(r["buyers"]) for r in channels.values())
    total_revenue = sum(float(r["revenue"]) for r in channels.values())

    lines = [f"📊 <b>Referal statistikasi — {label}</b>", ""]
    lines.append(f"👥 <b>Yangi foydalanuvchi:</b> {_fmt(total_users)} ta")
    lines.append(f"🛒 <b>Xarid qilgan:</b> {_fmt(total_buyers)} ta ({_pct(total_buyers, total_users)})")
    lines.append(f"💰 <b>Tushum:</b> {_fmt(total_revenue)} so'm")
    lines.append("")

    for key, title in CHANNELS:
        row = channels.get(key)
        users = int(row["users"]) if row else 0
        buyers = int(row["buyers"]) if row else 0
        revenue = float(row["revenue"]) if row else 0
        lines.append(
            f"{title}: <b>{_fmt(users)}</b> ta · 🛒 {_fmt(buyers)} ({_pct(buyers, users)}) · "
            f"💰 {_fmt(revenue)} so'm"
        )
    lines.append("")

    leaders = await database.get_blogger_referral_leaders(since, limit=5)
    if leaders:
        lines.append("🏆 <b>Blogerlar</b>")
        for i, b in enumerate(leaders, 1):
            mark = "" if b["active"] else " ⚪"
            lines.append(f"{i}. {_esc(_short(b['name'], 24))}{mark} — {_fmt(b['referred'])} mijoz · "
                         f"{_fmt(b['revenue'])} so'm")
        lines.append("")

    referrers = await database.get_top_referrers(since, limit=5)
    if referrers:
        lines.append("🤝 <b>Eng ko'p do'st taklif qilganlar</b>")
        for i, r in enumerate(referrers, 1):
            lines.append(f"{i}. {_name(r)} — {_fmt(r['invites'])} ta")
        lines.append("")

    sources = await database.get_ad_source_stats(since)
    if sources:
        lines.append("📣 <b>Reklama manbalari</b>")
        for s in sources[:5]:
            lines.append(f"• <code>{_esc(s['source'])}</code> — {_fmt(s['users'])} ta · "
                         f"{_fmt(s['revenue'])} so'm")
        lines.append("")

    lines.append("<i>Tushum — yetkazilgan buyurtmalar bo'yicha. Foydalanuvchi qaysi davrda "
                 "QO'SHILGANIGA qarab sanaladi.</i>")
    return "\n".join(lines)


def _keyboard(active: str) -> InlineKeyboardMarkup:
    periods = [
        InlineKeyboardButton(text=("• " if key == active else "") + label,
                             callback_data=f"refstat:{key}")
        for key, (label, _) in PERIODS.items()
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        periods,
        [InlineKeyboardButton(text="📢 Blogerlar", callback_data="admin:bloger"),
         InlineKeyboardButton(text="🔁 Qayta sotuv", callback_data="admin:retention")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_menu:marketing")],
    ])


@router.callback_query(F.data == "admin:referrals")
async def open_from_menu(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await state.clear()
    await callback.answer()
    await _render(callback, await build_report("30"), _keyboard("30"))


@router.callback_query(F.data.startswith("refstat:"))
async def switch_period(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Faqat adminlar uchun", show_alert=True)
        return
    period = callback.data.split(":", 1)[1]
    if period not in PERIODS:
        await callback.answer()
        return
    await callback.answer()
    await _render(callback, await build_report(period), _keyboard(period))


@router.message(Command("referallar"))
async def cmd_referrals(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    await state.clear()
    await message.answer(await build_report("30"), parse_mode="HTML",
                         reply_markup=_keyboard("30"))


async def _render(callback: CallbackQuery, text: str, keyboard) -> None:
    """Rasmli xabarni bare edit_text bilan tahrirlab bo'lmaydi — admin panel
    ba'zi ekranlarda rasm yuboradi, shuning uchun avval tekshiramiz."""
    try:
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
