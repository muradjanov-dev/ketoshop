"""
Ombor ogohlantirishlari — low / out-of-stock alerts to every admin (2026-09-17).

Owner's ask: tell ALL admins about products that are out of stock or have
fewer than 5 left, and do it again every time a product reaches that limit.

Why a watcher instead of the old per-order hook: stock also drops or changes
outside a buyer's checkout — aksiya bonuses and gifts decrement it without an
alert, admins edit quantities by hand, manual orders and the web panel write it
directly. Comparing each product's current level with the last level we
alerted about catches every one of those paths, including ones added later.

Levels per product:
    ok   — quantity ≥ limit
    low  — 0 < quantity < limit          ("⚠️ kam qoldi")
    out  — quantity ≤ 0                   ("🚫 tugadi")
The limit is the product's own low_stock_threshold when an admin set one in
the product editor, otherwise LOW_STOCK_THRESHOLD (5).

An alert goes out only when a product gets WORSE (ok→low, ok→out, low→out).
When it's restocked back to ok the level resets, so the next time it runs
down the admins hear about it again — "har safar limit shunga kelganda".

First run after deploy: the current levels are recorded silently and ONE
summary of everything already low/out goes to the admins (during daytime),
instead of a separate message for each of dozens of products.

Checkouts still call notify_low_stock() → check_now(), so an order that empties
a shelf alerts within seconds rather than at the next sweep.
"""
import asyncio
import html
import logging
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import admin_mood
import database
from config import ADMIN_IDS, LOW_STOCK_THRESHOLD

logger = logging.getLogger(__name__)
router = Router()

TZ_OFFSET = timedelta(hours=5)
CHECK_EVERY = 120                  # 2 min sweep for non-checkout stock changes
SUMMARY_HOURS = (8, 22)            # first-run summary only 08:00–21:59 Tashkent
_RANK = {"ok": 0, "low": 1, "out": 2}
_lock = asyncio.Lock()


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


def limit_for(product: dict) -> float:
    custom = product.get("low_stock_threshold")
    return float(custom) if custom else float(LOW_STOCK_THRESHOLD)


def level_for(product: dict) -> str:
    qty = float(product.get("quantity") or 0)
    if qty <= 0:
        return "out"
    if qty < limit_for(product):
        return "low"
    return "ok"


def _qty(value: float) -> str:
    value = float(value or 0)
    return str(int(value)) if value.is_integer() else f"{value:.1f}"


def _unit(product: dict, lang: str) -> str:
    from locales import get_display_unit
    try:
        return get_display_unit(product.get("unit") or "", lang)
    except Exception:
        return ""


# Owner request 2026-09-30: say it with a smile. Each alert picks one opener
# at random; the facts (name, what's left, the limit, what it means for
# buyers) stay in fixed lines underneath so nothing gets lost in the joke.
# Templates are Latin Uzbek / Russian; uz_cyr is transliterated before the
# product name goes in, so the name keeps the spelling the admins typed.
_OUT_OPENERS = {
    "uz": [
        "🏆 <b>Sotuv chempioni!</b> «{name}» javondan oxirgi donasigacha uchib ketdi.",
        "🎉 <b>Tabriklaymiz — to'liq sotildi!</b> «{name}» xaridorlarga shunchalik yoqdiki, bittasi ham qolmadi.",
        "🏁 <b>Marra!</b> «{name}» hammadan oldin tugab, g'olib bo'ldi.",
        "🕳 <b>Javonda bo'sh joy paydo bo'ldi</b> — «{name}» o'rni yangi partiyani kutyapti.",
        "😴 <b>«{name}» ta'tilga chiqdi</b> — omborni to'ldirsak, darhol ishga qaytadi.",
    ],
    "ru": [
        "🏆 <b>Чемпион продаж!</b> «{name}» разлетелся до последней штуки.",
        "🎉 <b>Поздравляем — продано всё!</b> «{name}» так понравился покупателям, что не осталось ни одного.",
        "🏁 <b>Финиш!</b> «{name}» закончился раньше всех и победил.",
        "🕳 <b>На полке освободилось место</b> — «{name}» ждёт новую партию.",
        "😴 <b>«{name}» ушёл в отпуск</b> — пополним склад, и он сразу вернётся к работе.",
    ],
}
_LOW_OPENERS = {
    "uz": [
        "🔥 <b>«{name}» qizg'in sotilyapti!</b> Javonda uzoq turolmayapti.",
        "⏳ <b>Qum soat ishga tushdi:</b> «{name}» tugab borayapti.",
        "🐿 <b>Olmaxon ham qishga g'amlaydi</b> — «{name}» uchun ham g'amlash vaqti keldi.",
        "📉 <b>Yaxshi xabar:</b> «{name}» zaxirasi kamaydi — demak, sotuv ketyapti! 🚀",
        "🍪 <b>Diqqat, «{name}» sevimlilar ro'yxatida!</b> Xaridorlarni xafa qilmaylik.",
    ],
    "ru": [
        "🔥 <b>«{name}» продаётся на ура!</b> На полке не задерживается.",
        "⏳ <b>Песочные часы запущены:</b> «{name}» заканчивается.",
        "🐿 <b>Даже белка делает запасы</b> — пора запастись и «{name}».",
        "📉 <b>Хорошая новость:</b> запас «{name}» тает — значит, продажи идут! 🚀",
        "🍪 <b>Внимание, «{name}» в списке любимчиков!</b> Не будем расстраивать покупателей.",
    ],
}


def _alert_text(product: dict, level: str, lang: str) -> str:
    import random
    name = html.escape(product["name"])
    limit = _qty(limit_for(product))
    base = "ru" if lang == "ru" else "uz"
    opener = random.choice((_OUT_OPENERS if level == "out" else _LOW_OPENERS)[base])
    if level == "out":
        tail = ("🚫 Omborda qolmadi — to'ldirmaguncha xaridorlar uni buyurtma qila olmaydi."
                if base == "uz" else
                "🚫 На складе ноль — пока не пополним, покупатели не смогут его заказать.")
    else:
        left = f"{_qty(product['quantity'])} {_unit(product, lang)}"
        tail = (f"🔢 Qolgan: <b>{left}</b> (chegara: {limit})\n📝 Yangi partiyani hozirdan rejalashtirsak bo'ladi."
                if base == "uz" else
                f"🔢 Осталось: <b>{left}</b> (порог: {limit})\n📝 Самое время запланировать новую партию.")
    # "{name}" would be transliterated with the rest — park it on a NUL.
    template = f"{opener}\n\n{tail}".replace("{name}", "\x00")
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        template = lat_to_cyr(template)
    return template.replace("\x00", name)


def summary_text(products: list[dict]) -> str:
    out = [p for p in products if level_for(p) == "out"]
    low = [p for p in products if level_for(p) == "low"]
    if not out and not low:
        return "✅ <b>Ombor holati</b>\n\nBarcha faol mahsulotlar yetarli miqdorda."
    lines = ["📦 <b>Ombor holati</b>", ""]
    if out:
        lines.append(f"🚫 <b>Tugagan ({len(out)} ta):</b>")
        lines += [f"• {p['name']}" for p in sorted(out, key=lambda p: p["name"].lower())]
        lines.append("")
    if low:
        lines.append(f"⚠️ <b>Kam qolgan ({len(low)} ta):</b>")
        lines += [f"• {p['name']} — <b>{_qty(p['quantity'])} {_unit(p, 'uz')}</b>"
                  for p in sorted(low, key=lambda p: float(p["quantity"] or 0))]
        lines.append("")
    lines.append("Mahsulot shu holatga har safar tushganda alohida ogohlantirish keladi.")
    return "\n".join(lines)


async def _send_all(bot: Bot, build) -> None:
    """build(lang) -> text. One message per admin in their own language."""
    for admin_id in ADMIN_IDS:
        try:
            lang = await database.get_user_language(admin_id)
        except Exception:
            lang = "uz"
        try:
            # Already written in the cheerful tone — no extra admin_mood line.
            with admin_mood.quiet():
                await bot.send_message(admin_id, build(lang), parse_mode=ParseMode.HTML)
        except Exception as exc:
            logger.warning("Stock alert to admin %s failed: %s", admin_id, exc)


def _chunks(text: str, size: int = 3800) -> list[str]:
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > size:
            parts.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        parts.append(cur)
    return parts


async def check_now(bot: Bot) -> int:
    """Compare every active product with its last alerted level; alert the
    ones that got worse. Returns how many alerts went out."""
    async with _lock:
        products = await database.get_stock_snapshot()

        if not await database.stock_alerts_initialized():
            # First run: record silently, one summary goes out separately.
            await database.set_stock_alert_levels({p["id"]: level_for(p) for p in products})
            await database.init_stock_alerts()
            return 0

        known = await database.get_stock_alert_levels()

        changed, worse = {}, []
        for p in products:
            new = level_for(p)
            old = known.get(p["id"], "ok")
            if new != old:
                changed[p["id"]] = new
                if _RANK[new] > _RANK[old]:
                    worse.append((p, new))
        if changed:
            await database.set_stock_alert_levels(changed)

    for product, level in worse:
        await _send_all(bot, lambda lang, p=product, lv=level: _alert_text(p, lv, lang))
    return len(worse)


async def _maybe_send_summary(bot: Bot) -> None:
    hour = _now_tk().hour
    if not (SUMMARY_HOURS[0] <= hour < SUMMARY_HOURS[1]):
        return
    if not await database.claim_stock_summary():
        return
    text = summary_text(await database.get_stock_snapshot())
    for part in _chunks(text):
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, part, parse_mode=ParseMode.HTML)
            except Exception as exc:
                logger.warning("Stock summary to admin %s failed: %s", admin_id, exc)


async def scheduler_loop(bot: Bot) -> None:
    logger.info("Stock alert watcher started (limit %s)", LOW_STOCK_THRESHOLD)
    while True:
        try:
            await check_now(bot)
            await _maybe_send_summary(bot)
        except Exception:
            logger.exception("Stock alert sweep failed")
        await asyncio.sleep(CHECK_EVERY)


def _low_or_out(products: list[dict]) -> bool:
    return any(level_for(p) != "ok" for p in products)


@router.message(Command("ombor"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_stock(message: Message):
    """Current low / out-of-stock list on demand — with a button that sends
    the same full list to every admin (owner request 2026-09-30)."""
    products = await database.get_stock_snapshot()
    parts = _chunks(summary_text(products))
    kb = None
    if _low_or_out(products):
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text="📤 Barcha adminlarga yuborish", callback_data="ombor:send_all")]])
    for i, part in enumerate(parts):
        await message.answer(part, parse_mode=ParseMode.HTML,
                             reply_markup=kb if i == len(parts) - 1 else None)


@router.callback_query(F.data == "ombor:send_all", F.from_user.id.in_(ADMIN_IDS))
async def send_stock_to_all_admins(callback: CallbackQuery, bot: Bot):
    """Fan the full low/out list (fresh snapshot, not the one on screen) to
    every admin, tagged with who sent it."""
    products = await database.get_stock_snapshot()
    who = html.escape(callback.from_user.full_name or str(callback.from_user.id))
    parts = _chunks(summary_text(products))
    parts[0] = f"📤 Yuboruvchi: {who}\n\n" + parts[0]
    sent = 0
    for admin_id in ADMIN_IDS:
        try:
            for part in parts:
                await bot.send_message(admin_id, part, parse_mode=ParseMode.HTML)
            sent += 1
        except Exception as exc:
            logger.warning("Stock list to admin %s failed: %s", admin_id, exc)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.answer(f"✅ {sent}/{len(ADMIN_IDS)} ta adminga yuborildi", show_alert=True)
