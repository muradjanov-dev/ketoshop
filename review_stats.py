"""
Sharhlar — mijozlar do'kon haqida nima deb yozgani, bir ekranda.

Sharhlar bazaga 2026-07 dan beri tushardi, lekin adminlar uchun hech qayerda
ko'rinmasdi: Statistika ekranida faqat umumiy SONI bor edi. Ya'ni "nechta
yulduz qo'yishdi", "kim nima yozdi", "qaysi mahsulot past baho oldi" degan
savollarga javob beradigan joy yo'q edi — do'konning eng arzon va eng to'g'ri
ma'lumoti o'qilmay yotardi.

Bu ekran shuni ochadi:
  * umumiy soni, o'rtacha baho, yulduzlar taqsimoti (ustunchalar bilan)
  * yetkazilgan buyurtma olgan mijozlarning necha foizi sharh yozgani
  * eng yuqori va eng PAST baholi mahsulotlar — ikkinchisi harakat talab qiladi
  * oxirgi sharhlar, matni bilan
  * sotilgan, lekin sharh olmagan mahsulotlar — so'ralmagan sharhlar

Hamma joyda mijoz filtri bitta: admin va ichki do'kon akkauntlari hisobga
olinmaydi (database._customer_filter_ids), aks holda o'z sharhimiz o'rtacha
bahoni ko'tarib yuborardi.

Kirish: /sharhlar
"""
import html
import logging
from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import database
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router()

TZ_OFFSET = timedelta(hours=5)          # Asia/Tashkent
BAR_WIDTH = 10


def _esc(text) -> str:
    return html.escape(str(text or ""), quote=False)


def _fmt(n) -> str:
    return f"{int(n or 0):,}".replace(",", " ")


def _pct(part, whole) -> str:
    return f"{(part / whole * 100):.0f}%" if whole else "0%"


def _short(text, limit: int = 34) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _dt(value) -> str:
    if not value:
        return "—"
    try:
        return f"{value + TZ_OFFSET:%d.%m.%Y}"
    except TypeError:
        return "—"


def _stars(rating) -> str:
    r = max(0, min(5, int(rating or 0)))
    return "⭐" * r + "☆" * (5 - r)


def _bar(part: int, whole: int) -> str:
    """Ulushni ko'rsatadigan ustuncha — raqamdan ko'ra tezroq o'qiladi."""
    if not whole:
        return "▫️" * BAR_WIDTH
    filled = max(0, min(BAR_WIDTH, round(BAR_WIDTH * part / whole)))
    return "🟩" * filled + "⬜" * (BAR_WIDTH - filled)


def _name(row) -> str:
    full = (row.get("full_name") or "").strip()
    user = (row.get("username") or "").strip()
    if full and user:
        return f"{_esc(_short(full, 22))} (@{_esc(user)})"
    if full:
        return _esc(_short(full, 28))
    if user:
        return f"@{_esc(user)}"
    return f"ID {row.get('user_id')}"


def _verdict(avg: float) -> str:
    """Bahoni bir jumlada aytamiz. Raqamning o'zi «4.30» hech kimga nima
    qilish kerakligini aytmaydi — yaxshi yoki yomonligini aytish kerak."""
    if avg >= 4.5:
        return "Bu — juda yaxshi natija. 👏"
    if avg >= 4.0:
        return "Bu — yaxshi natija."
    if avg >= 3.5:
        return "Bu — o'rtacha. Yaxshilash mumkin."
    return "Bu — past. Sabablarini ko'rish kerak. ⚠️"


async def build_report() -> str:
    s = await database.get_review_summary()
    total = int(s.get("total") or 0)

    lines = ["⭐ <b>SHARHLAR</b>", ""]
    if not total:
        lines.append("Hozircha bironta sharh yo'q.")
        lines.append("")
        lines.append("Mijoz buyurtmasi yetkazilgandan keyin mahsulot "
                     "kartochkasidan sharh qoldira oladi.")
        return "\n".join(lines)

    avg = float(s.get("avg_rating") or 0)
    buyers = int(s.get("buyers") or 0)
    reviewers = int(s.get("reviewers") or 0)
    r5, r4 = int(s.get("r5") or 0), int(s.get("r4") or 0)
    r3 = int(s.get("r3") or 0)
    r2, r1 = int(s.get("r2") or 0), int(s.get("r1") or 0)
    happy, middle, unhappy = r5 + r4, r3, r2 + r1

    # 1. Bitta jumlada javob: yaxshimi yoki yomonmi.
    lines.append(f"Mijozlar do'konni <b>{avg:.1f}</b> ⭐ ga baholagan "
                 f"({_fmt(total)} ta sharh asosida).")
    lines.append(_verdict(avg))
    lines.append("")

    # 2. Uch guruh — 5 qatorli taqsimotdan ko'ra tezroq tushuniladi.
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append(f"👍 <b>Mamnun:</b> {_fmt(happy)} ta ({_pct(happy, total)}) — 4-5 yulduz")
    lines.append(f"😐 <b>O'rtacha:</b> {_fmt(middle)} ta ({_pct(middle, total)}) — 3 yulduz")
    lines.append(f"👎 <b>Norozi:</b> {_fmt(unhappy)} ta ({_pct(unhappy, total)}) — 1-2 yulduz")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("")

    # 3. Batafsil taqsimot — kim xohlasa shu yerda ko'radi.
    lines.append("<b>Har bir yulduz alohida:</b>")
    for star in (5, 4, 3, 2, 1):
        cnt = int(s.get(f"r{star}") or 0)
        lines.append(f"{star}⭐ {_bar(cnt, total)} {_fmt(cnt)} ta")
    lines.append("")

    # 4. Eng muhimi: endi nima qilish kerak. Har bir band — bitta harakat.
    todo: list[str] = []

    if unhappy:
        todo.append(f"<b>{_fmt(unhappy)} ta mijoz norozi qolgan.</b>\n"
                    f"   Ular nima yozganini o'qing va javob bering —\n"
                    f"   pastdagi «😕 Past baholar» tugmasi.")

    low = await database.get_product_ratings(limit=3, worst=True)
    low = [p for p in low if float(p["avg_rating"]) < 4.0]
    if low:
        worst = low[0]
        names = ", ".join(_esc(_short(p["name"], 26)) for p in low)
        todo.append(f"<b>Eng past baholi mahsulot: {_esc(_short(worst['name'], 26))} "
                    f"— {float(worst['avg_rating']):.1f} ⭐.</b>\n"
                    f"   Sabab: qadoq, sifat yoki tavsif noto'g'ri bo'lishi mumkin.\n"
                    f"   Ro'yxat: {names}")

    if buyers and reviewers < buyers:
        silent = buyers - reviewers
        todo.append(f"<b>{_fmt(buyers)} ta mijozdan faqat {_fmt(reviewers)} tasi "
                    f"sharh yozgan.</b>\n"
                    f"   Qolgan {_fmt(silent)} tasidan hech kim so'ramagan.\n"
                    f"   Har bir sharh — yangi mijoz uchun ishonch.")

    if todo:
        lines.append("📣 <b>NIMA QILISH KERAK</b>")
        lines.append("")
        for i, item in enumerate(todo, 1):
            lines.append(f"{i}. {item}")
            lines.append("")

    # 5. Maqtov oxirida — ishlayotgan narsani ham bilish kerak.
    top = await database.get_product_ratings(limit=3, worst=False, min_reviews=2)
    top = [p for p in top if float(p["avg_rating"]) >= 4.5]
    if top:
        lines.append("🏆 <b>Eng yoqqan mahsulotlar</b> — reklamada shularni ishlating:")
        for p in top:
            lines.append(f"   • {_esc(_short(p['name']))} — "
                         f"{float(p['avg_rating']):.1f} ⭐ ({_fmt(p['cnt'])} ta sharh)")
        lines.append("")

    recent = await database.get_recent_reviews(limit=3, with_text_only=True)
    if recent:
        lines.append("💬 <b>Oxirgi yozilganlar</b>")
        for r in recent:
            lines.append(f"{_stars(r['rating'])} {_esc(_short(r['product_name'], 28))} "
                         f"· {_dt(r['created_at'])}")
            lines.append(f"   «{_esc(_short(r['comment'], 110))}» — {_name(r)}")
        lines.append("")

    lines.append(f"<i>{_dt(s.get('first_at'))} dan {_dt(s.get('last_at'))} gacha. "
                 f"Admin va ichki akkauntlar hisobga olinmagan.</i>")
    return "\n".join(lines)


async def build_complaints() -> str:
    """1-2 yulduzli hamma sharh, matni bilan — shikoyatlar bir joyda."""
    rows = await database.get_recent_reviews(limit=20, max_rating=2)
    lines = ["😕 <b>Past baholar (1-2 ⭐)</b>", ""]
    if not rows:
        lines.append("Bittasi ham yo'q — hamma baho 3 va undan yuqori. 👏")
        return "\n".join(lines)
    for r in rows:
        lines.append(f"{_stars(r['rating'])} <b>{_esc(_short(r['product_name'], 28))}</b>"
                     f" · {_dt(r['created_at'])}")
        comment = (r.get("comment") or "").strip()
        body = f"«{_esc(_short(comment, 160))}»" if comment else "(matn yozilmagan)"
        lines.append(f"   {body}")
        lines.append(f"   — {_name(r)}")
        lines.append("")
    lines.append("<i>Har biriga javob bersangiz, mijoz qaytadi.</i>")
    return "\n".join(lines)


async def build_missing() -> str:
    """Sotilgan, lekin sharh olmagan mahsulotlar."""
    rows = await database.get_unreviewed_products(limit=15)
    lines = ["🔇 <b>Sharh olmagan mahsulotlar</b>", ""]
    if not rows:
        lines.append("Sotilgan hamma mahsulotning sharhi bor. 👏")
        return "\n".join(lines)
    lines.append("Sotilgan, lekin hali bironta sharh yo'q — ko'p sotilganidan:")
    lines.append("")
    for i, p in enumerate(rows, 1):
        lines.append(f"{i}. {_esc(_short(p['name'], 36))} — {_fmt(p['orders'])} ta buyurtma")
    lines.append("")
    lines.append("<i>So'ramaganimiz uchun yozilmagan — so'rasak, yoziladi.</i>")
    return "\n".join(lines)


def _keyboard(screen: str = "main") -> InlineKeyboardMarkup:
    rows = []
    if screen != "main":
        rows.append([InlineKeyboardButton(text="⬅️ Orqaga", callback_data="sharh:main")])
    if screen != "low":
        rows.append([InlineKeyboardButton(text="😕 Past baholar", callback_data="sharh:low")])
    if screen != "missing":
        rows.append([InlineKeyboardButton(text="🔇 Sharhsizlar", callback_data="sharh:missing")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("sharhlar"))
async def cmd_reviews(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        text = await build_report()
    except Exception:
        logger.exception("Sharhlar hisoboti tuzilmadi")
        await message.answer("⚠️ Sharhlar hisobotini tuzib bo'lmadi.")
        return
    await message.answer(text, parse_mode="HTML", reply_markup=_keyboard("main"))


@router.callback_query(F.data.startswith("sharh:"))
async def on_screen(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer()
        return
    screen = callback.data.split(":", 1)[1]
    builders = {"main": build_report, "low": build_complaints, "missing": build_missing}
    builder = builders.get(screen)
    if builder is None:
        await callback.answer()
        return
    try:
        text = await builder()
    except Exception:
        logger.exception("Sharhlar ekrani tuzilmadi (%s)", screen)
        await callback.answer("Xatolik", show_alert=True)
        return
    try:
        await callback.message.edit_text(text, parse_mode="HTML",
                                         reply_markup=_keyboard(screen))
    except Exception:
        # Rasmli xabarni edit_text qila olmaydi — yangisini yuboramiz.
        await callback.message.answer(text, parse_mode="HTML",
                                      reply_markup=_keyboard(screen))
    await callback.answer()
