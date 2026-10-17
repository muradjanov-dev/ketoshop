"""
Past baho sababini so'rash — a low rating gets a polite "what went wrong?"
(owner, 2026-10-17, about a 1★ for the sourdough starter left without a
word: "o'zing ai yordamida yoz va sababini aniqla muloyimlik bilan").

A buyer who rates a product 1–2★ and leaves no comment gets one warm,
personal message from the bot: we're sorry, what didn't you like, and an offer
to explain how to use the product. The wording is written once, here, by the
AI that built this feature — not generated per send — so every buyer gets the
same careful text, in their own language (users.language; uz_cyr through
lat_to_cyr).

The buyer's answer is ordinary free text, so it reaches the admins through the
support relay (handlers/support_relay.py) with its usual «↩️ Javob berish»
button; reply_context() puts a line on top of that card saying which review it
answers. The AI seller (ai_sales.py) would otherwise take that text first, so
it is paused for this buyer for REPLY_WINDOW_DAYS — the same pause an admin's
own reply sets. The pause lives in memory, so scheduler_loop() puts the open
ones back after a restart.

Rules:
  * 1–2★ with no comment, left in the last LOOKBACK_DAYS — a comment already
    says why;
  * the review is at least MIN_AGE_MINUTES old;
  * customers only — admin / shop accounts (database._customer_filter_ids)
    never get it;
  * once per review: review_followups is claimed before sending, so a
    restart can't send twice;
  * daytime only, SEND_FROM–SEND_UNTIL Tashkent;
  * banned buyers are skipped;
  * REVIEW_FOLLOWUP=0 switches it off;
  * every admin hears that it went out — or that it couldn't be delivered,
    with the buyer's contact so somebody can call.
"""
import asyncio
import html
import logging
import os
import re
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramRetryAfter

import database
from config import ADMIN_IDS
from locales import localize_product_text
from translit import lat_to_cyr

logger = logging.getLogger(__name__)

LOW_RATING = 2
LOOKBACK_DAYS = 30
MIN_AGE_MINUTES = 15
REPLY_WINDOW_DAYS = 7
SEND_FROM = 10
SEND_UNTIL = 20
CHECK_EVERY = 600
TZ_OFFSET = timedelta(hours=5)
_PLACEHOLDER = re.compile(r"(\{\w+\})")

_TEXT = {
    "uz": (
        "Assalomu alaykum{name}! 🌿\n\n"
        "Siz <b>{product}</b> uchun {stars} baho qo'ygansiz. Mahsulot kutganingizdek "
        "chiqmagani uchun chin dildan uzr so'raymiz 🙏\n\n"
        "Biz uchun har bir xaridorimizning fikri juda muhim. Nima yoqmaganini bir-ikki "
        "so'z bilan yozib bera olasizmi? Masalan: ta'mi, sifati, qadog'i, yetkazib "
        "berish yoki boshqa narsa.\n\n"
        "Agar mahsulotni ishlatishda qiyinchilik bo'lgan bo'lsa, qanday to'g'ri "
        "ishlatishni ham batafsil tushuntirib beramiz.\n\n"
        "Javobingizni shu chatga yozing — uni jamoamiz o'qiydi va albatta to'g'rilashga "
        "harakat qilamiz.\n\n"
        "Hurmat bilan, Ketoshop jamoasi 💚"
    ),
    "ru": (
        "Здравствуйте{name}! 🌿\n\n"
        "Вы поставили {stars} товару <b>{product}</b>. Нам очень жаль, что он не "
        "оправдал ваших ожиданий 🙏\n\n"
        "Для нас важно мнение каждого покупателя. Напишите, пожалуйста, в двух словах, "
        "что именно не понравилось: вкус, качество, упаковка, доставка или что-то другое?\n\n"
        "Если были сложности с использованием, мы подробно подскажем, как правильно "
        "его применять.\n\n"
        "Ответ напишите прямо в этот чат — его прочитает наша команда, и мы обязательно "
        "постараемся всё исправить.\n\n"
        "С уважением, команда Ketoshop 💚"
    ),
}


def enabled() -> bool:
    return os.getenv("REVIEW_FOLLOWUP", "1").strip() != "0"


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


def _first_name(full_name: str | None) -> str:
    return (full_name or "").strip().split(" ")[0][:40]


def message_text(lang: str, full_name: str | None, product: str, rating: int) -> str:
    """The buyer's message. The template is transliterated before the name
    and product go in, so a Latin name stays as the buyer wrote it."""
    template = _TEXT["ru"] if lang == "ru" else _TEXT["uz"]
    if lang == "uz_cyr":
        # {name}/{product}/{stars} must survive the transliteration.
        template = "".join(part if _PLACEHOLDER.fullmatch(part) else lat_to_cyr(part)
                           for part in _PLACEHOLDER.split(template))
    first = _first_name(full_name)
    return template.format(
        name=f", {html.escape(first, quote=False)}" if first else "",
        product=html.escape(product, quote=False),
        stars=f"{int(rating)} ⭐",
    )


def _product(row: dict, lang: str) -> str:
    return localize_product_text(row.get("product_name") or "", row.get("product_name_ru"), lang) or "—"


def _contact(row: dict) -> str:
    from handlers.cart import buyer_contact_link
    link = buyer_contact_link(row["user_id"], row.get("username"), row.get("full_name"))
    phone = (row.get("phone") or "").strip()
    return f"{link}, 📞 {html.escape(phone, quote=False)}" if phone else link


async def _notify_admins(bot: Bot, text: str) -> None:
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML,
                                   disable_web_page_preview=True)
        except Exception:
            pass


async def _send(bot: Bot, row: dict) -> bool:
    lang = row.get("language") if row.get("language") in ("uz", "uz_cyr", "ru") else "uz"
    text = message_text(lang, row.get("full_name"), _product(row, lang), row["rating"])
    for _ in range(2):
        try:
            await bot.send_message(row["user_id"], text, parse_mode=ParseMode.HTML)
            return True
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
        except Exception:
            logger.warning("Review follow-up to %s failed", row["user_id"], exc_info=True)
            return False
    return False


def _pause_ai(user_id: int, seconds: int) -> None:
    try:
        import ai_sales
        ai_sales.pause_for_human(user_id, max(1, int(seconds)))
    except Exception:
        logger.exception("Could not pause the AI seller for %s", user_id)


async def restore_ai_pauses() -> int:
    """After a restart: buyers asked in the last REPLY_WINDOW_DAYS go back to
    the admins, not the AI, for what is left of the window."""
    rows = await database.get_review_followup_pauses(REPLY_WINDOW_DAYS)
    for row in rows:
        _pause_ai(row["user_id"], row["seconds_left"])
    return len(rows)


async def run_once(bot: Bot) -> int:
    """One sweep. Returns how many buyers were written to."""
    if not enabled():
        return 0
    if not SEND_FROM <= _now_tk().hour < SEND_UNTIL:
        return 0
    rows = await database.get_low_reviews_to_follow_up(LOW_RATING, LOOKBACK_DAYS, MIN_AGE_MINUTES)
    sent = 0
    for row in rows:
        if await database.is_user_banned(row["user_id"]):
            continue
        if not await database.claim_review_followup(row["id"], row["user_id"]):
            continue
        delivered = await _send(bot, row)
        await database.set_review_followup_delivered(row["id"], delivered)
        product = html.escape(_product(row, "uz"), quote=False)
        when = row["created_at"].strftime("%d.%m") if row.get("created_at") else ""
        head = f"{_contact(row)} — <b>{product}</b>, {row['rating']}★ ({when})"
        if delivered:
            sent += 1
            _pause_ai(row["user_id"], REPLY_WINDOW_DAYS * 86400)
            await _notify_admins(bot, f"🤝 <b>Past baho sababi so'raldi</b>\n{head}\n"
                                      "Muloyim xabar yuborildi. Javobi «Xabarlar»ga keladi.")
        else:
            await _notify_admins(bot, f"⚠️ <b>Past baho: xaridorga yozib bo'lmadi</b>\n{head}\n"
                                      "Botni bloklagan bo'lishi mumkin — qo'ng'iroq qilib ko'ring.")
    return sent


async def reply_context(user_id: int) -> str:
    """A line for the top of the support card when this buyer was asked
    about a low rating in the last REPLY_WINDOW_DAYS; '' otherwise."""
    row = await database.get_recent_review_followup(user_id, REPLY_WINDOW_DAYS)
    if not row:
        return ""
    product = html.escape(_product(row, "uz"), quote=False)
    return f"⭐ <b>Past baho sababi:</b> {product}, {row['rating']}★ — savolimizga javob\n\n"


async def scheduler_loop(bot: Bot) -> None:
    logger.info("Review follow-up scheduler started (%02d:00–%02d:00, ≤%d★)",
                SEND_FROM, SEND_UNTIL, LOW_RATING)
    try:
        await restore_ai_pauses()
    except Exception:
        logger.exception("Could not restore review follow-up AI pauses")
    while True:
        try:
            await run_once(bot)
        except Exception:
            logger.exception("Review follow-up tick failed")
        await asyncio.sleep(CHECK_EVERY)
