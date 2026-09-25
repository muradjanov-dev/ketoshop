"""
Qayta sotuv — kim qaytib keldi, qancha qoldirdi, asosan nima oladi.

Do'kon o'sishining ikki yo'li bor: yangi mijoz topish va bor mijozni qaytarish.
Botda birinchisi bo'yicha hamma narsa bor edi (reklama, bloger, referal), lekin
ikkinchisi — "mijozlarimizga qayta sotuv" — hech qayerda ko'rinmasdi. Bu modul
o'sha bo'shliqni yopadi:

  * nechta mijoz bir marta, nechtasi 2-3, nechtasi 4+ marta olgan
  * qayta sotuv umumiy tushumning qancha qismi
  * har bir mijoz: nechta buyurtma, qancha pul, o'rtacha chek, oxirgi xaridi
    qachon, buyurtmalari orasidagi o'rtacha necha kun
  * o'sha mijoz ASOSAN nima olishi (buyurtma tarkibidan yig'iladi)
  * qaytib keladigan mijozlar umuman nima olishi — ya'ni do'konni ushlab
    turgan mahsulotlar

Hisob database.py da (get_retention_summary / get_repeat_customers /
get_customer_purchase_profile / get_repeat_top_products), sayt paneli ham
o'shani chaqiradi. Hamma joyda asos bitta: BEKOR QILINMAGAN buyurtmalar
(database.SALE_SQL — savdo tushgan zahoti sanaladi, kuryerni kutmaydi),
admin qo'lda kiritgan va B2B qatorlarsiz, admin/ichki akkauntlarsiz.

Kirish: Admin panel -> Statistika -> 🔁 Qayta sotuv, yoki /qayta_sotuv.
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
    "30": ("30 kun", 30),
    "90": ("3 oy", 90),
    "all": ("Butun davr", None),
}
SORTS = {
    "revenue": "💰 Pul bo'yicha",
    "orders": "🔁 Soni bo'yicha",
    "recent": "🕒 Oxirgi xarid",
}
LIST_SIZE = 10
TZ_OFFSET = timedelta(hours=5)  # Asia/Tashkent


def _fmt(n) -> str:
    return f"{int(n or 0):,}".replace(",", " ")


def _pct(part, whole) -> str:
    return f"{(part / whole * 100):.0f}%" if whole else "0%"


def _dt(value) -> str:
    if not value:
        return "—"
    try:
        return (value + TZ_OFFSET).strftime("%d.%m.%Y")
    except Exception:
        return "—"


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


def _unit(unit_key: str) -> str:
    """Mahsulot birligi mijozga ko'rinadigan ko'rinishda (kg/g -> dona)."""
    from locales import get_display_unit
    return get_display_unit(unit_key or "", "uz")


def _since(period: str):
    _, days = PERIODS.get(period, PERIODS["all"])
    return datetime.utcnow() - timedelta(days=days) if days else None


async def build_report(period: str = "all", sort: str = "revenue") -> tuple[str, list[dict]]:
    label, _ = PERIODS.get(period, PERIODS["all"])
    since = _since(period)

    summary = await database.get_retention_summary(since)
    customers = int(summary.get("customers") or 0)
    orders = int(summary.get("orders") or 0)
    revenue = float(summary.get("revenue") or 0)
    repeat_orders = int(summary.get("repeat_orders") or 0)
    repeat_revenue = float(summary.get("repeat_revenue") or 0)
    once = int(summary.get("once") or 0)
    few = int(summary.get("few") or 0)
    loyal = int(summary.get("loyal") or 0)
    returning = few + loyal

    lines = [f"🔁 <b>Qayta sotuv — {label}</b>", ""]
    if not customers:
        lines.append("Bu davrda savdo yo'q.")
        return "\n".join(lines), []

    lines.append(f"👤 <b>Xaridorlar:</b> {_fmt(customers)} ta")
    lines.append(f"   1 marta olgan: {_fmt(once)} ({_pct(once, customers)})")
    lines.append(f"   2-3 marta: {_fmt(few)} ({_pct(few, customers)})")
    lines.append(f"   4+ marta: {_fmt(loyal)} ({_pct(loyal, customers)})")
    lines.append("")
    lines.append(f"🔁 <b>Qaytib kelgan:</b> {_fmt(returning)} ta ({_pct(returning, customers)})")
    lines.append(f"   Buyurtmalarning {_pct(repeat_orders, orders)} qismi · "
                 f"{_fmt(repeat_revenue)} so'm ({_pct(repeat_revenue, revenue)})")
    lines.append("")
    lines.append(f"🧾 <b>O'rtacha chek:</b> {_fmt(revenue / orders if orders else 0)} so'm")
    lines.append(f"📦 <b>1 mijozga:</b> {orders / customers:.1f} buyurtma · "
                 f"{_fmt(revenue / customers)} so'm")
    lines.append("")

    rows, total = await database.get_repeat_customers(since, limit=LIST_SIZE, sort=sort)
    if rows:
        lines.append(f"🏆 <b>Qaytib kelgan mijozlar</b> ({_fmt(total)} ta, "
                     f"{SORTS.get(sort, '')})")
        for i, r in enumerate(rows, 1):
            days = r.get("days_since")
            ago = f"{days} kun oldin" if days is not None else "—"
            lines.append(
                f"{i}. {_name(r)} — 🔁 {_fmt(r['orders'])} · 💰 {_fmt(r['revenue'])} so'm "
                f"· 🕒 {ago}"
            )
        lines.append("")

    products = await database.get_repeat_top_products(since, limit=5)
    if products:
        lines.append("🛒 <b>Qaytuvchilar asosan nima oladi</b>")
        for i, p in enumerate(products, 1):
            lines.append(f"{i}. {_esc(_short(p['name'], 32))} — {p['quantity']:g} "
                         f"{_unit(p['unit'])} · {_fmt(p['amount'])} so'm")
        lines.append("")

    lines.append("<i>Bekor qilinganlardan tashqari hamma savdo. Mijoz tafsiloti "
                 "uchun pastdagi tugmani bosing.</i>")
    return "\n".join(lines), rows


async def build_customer(user_id: int) -> str:
    profile = await database.get_customer_purchase_profile(user_id)
    user = profile.get("user") or {}
    orders = int(profile.get("orders") or 0)

    lines = [f"👤 <b>{_name(user, 64)}</b>", ""]
    if not orders:
        lines.append("Bu mijozda savdo yo'q.")
        return "\n".join(lines)

    lines.append(f"🔁 <b>Buyurtmalari:</b> {_fmt(orders)} ta")
    lines.append(f"💰 <b>Jami:</b> {_fmt(profile.get('revenue'))} so'm")
    lines.append(f"🧾 <b>O'rtacha chek:</b> {_fmt(profile.get('avg_check'))} so'm")
    lines.append(f"📅 Birinchi xarid: {_dt(profile.get('first_order'))}")
    lines.append(f"📅 Oxirgi xarid: {_dt(profile.get('last_order'))}")
    if profile.get("avg_gap_days") is not None:
        lines.append(f"⏳ Buyurtmalari orasida o'rtacha "
                     f"<b>{profile['avg_gap_days']} kun</b>")
    if user.get("phone"):
        lines.append(f"📞 <code>{_esc(user['phone'])}</code>")
    if user.get("username"):
        lines.append(f"💬 @{_esc(user['username'])}")
    lines.append("")

    products = profile.get("products") or []
    if products:
        lines.append("🛒 <b>Nima oladi</b>")
        for i, p in enumerate(products[:8], 1):
            lines.append(f"{i}. {_esc(_short(p['name'], 32))} — {p['quantity']:g} "
                         f"{_unit(p['unit'])} ({p['times']} marta) · {_fmt(p['amount'])} so'm")
    return "\n".join(lines)


def _keyboard(period: str, sort: str, rows: list[dict]) -> InlineKeyboardMarkup:
    periods = [
        InlineKeyboardButton(text=("• " if key == period else "") + label,
                             callback_data=f"retstat:p:{key}:{sort}")
        for key, (label, _) in PERIODS.items()
    ]
    sorts = [
        InlineKeyboardButton(text=("• " if key == sort else "") + label,
                             callback_data=f"retstat:s:{period}:{key}")
        for key, label in SORTS.items()
    ]
    keyboard = [periods, sorts]
    # Mijoz tugmalari — ikkitadan bir qatorda, ro'yxatdagi tartib bilan.
    buttons = [
        InlineKeyboardButton(text=f"{i}. {(r.get('full_name') or 'ID ' + str(r['user_id']))[:18]}",
                             callback_data=f"retstat:u:{r['user_id']}:{period}:{sort}")
        for i, r in enumerate(rows, 1)
    ]
    for i in range(0, len(buttons), 2):
        keyboard.append(buttons[i:i + 2])
    keyboard.append([InlineKeyboardButton(text="📊 Referallar", callback_data="admin:referrals")])
    keyboard.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_menu:stats")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def _render(callback: CallbackQuery, text: str, keyboard) -> None:
    try:
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
        else:
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data == "admin:retention")
async def open_from_menu(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        return
    await state.clear()
    await callback.answer()
    text, rows = await build_report("all", "revenue")
    await _render(callback, text, _keyboard("all", "revenue", rows))


@router.callback_query(F.data.startswith("retstat:p:") | F.data.startswith("retstat:s:"))
async def switch_view(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Faqat adminlar uchun", show_alert=True)
        return
    _, _, period, sort = callback.data.split(":", 3)
    if period not in PERIODS or sort not in SORTS:
        await callback.answer()
        return
    await callback.answer()
    text, rows = await build_report(period, sort)
    await _render(callback, text, _keyboard(period, sort, rows))


@router.callback_query(F.data.startswith("retstat:u:"))
async def show_customer(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Faqat adminlar uchun", show_alert=True)
        return
    _, _, user_id, period, sort = callback.data.split(":", 4)
    await callback.answer()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Yozish", url=f"tg://user?id={user_id}")],
        [InlineKeyboardButton(text="🔙 Ro'yxatga",
                              callback_data=f"retstat:p:{period}:{sort}")],
    ])
    await _render(callback, await build_customer(int(user_id)), keyboard)


@router.message(Command("qayta_sotuv"))
async def cmd_retention(message: Message, state: FSMContext):
    if message.from_user.id not in ADMIN_IDS:
        return
    await state.clear()
    text, rows = await build_report("all", "revenue")
    await message.answer(text, parse_mode="HTML",
                         reply_markup=_keyboard("all", "revenue", rows))
