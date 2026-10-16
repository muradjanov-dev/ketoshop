"""
Keto savol — one question from the site's knowledge games to every buyer,
every two days (owner, 2026-10-16: "har 2 kunda 1 ta savolni bot orqali
berishni boshla hammaga, keyin davomi uchun saytga taklif qil ... sayt
ichiga qo'shganimiz yangi o'yinlardan random olib jo'nat bittasini").

The question comes from quiz_bank.py — the same bank the Mini App games use
— picked at random from the quiz, "Keto mi, emas mi?" or "Qaysi birida
uglevod kam?", never one that was already sent until its game runs out.

The buyer answers with a tap. The message then turns into the answer: the
right option ✅, theirs ❌ if it was wrong, a short explanation, how many
people answered and how many got it right — and a «🎮 Davom etish — saytda»
button that opens the same game in the Mini App (/?game=quiz|keto|duel).

Rules:
  * every INTERVAL_DAYS days, sent between 20:00 and 22:00 Tashkent — the
    evening is free of the other sends (tips 08:00, retention 09:30, reco
    10:00, spotlight 13:00, interest 18:00). A deploy after 22:00 waits for
    the next evening;
  * the day is claimed in daily_quiz_sends before the broadcast, so a
    restart can't send twice;
  * each buyer in their own language (users.language), banned users out;
  * one answer per buyer per question;
  * admins: /savol — status, the last rounds' results, a test question to
    yourself, and an on/off switch.
"""
import asyncio
import html
import logging
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo,
)

import database
import quiz_bank
from config import ADMIN_IDS, WEBAPP_URL

logger = logging.getLogger(__name__)
router = Router()

TZ_OFFSET = timedelta(hours=5)
SEND_HOUR = 20              # 20:00 Tashkent
LAST_HOUR = 22              # nothing starts after 21:59
INTERVAL_DAYS = 2           # owner: "har 2 kunda 1"
CHECK_EVERY = 600           # 10 min
SEND_DELAY = 0.05           # ~20 messages a second, under Telegram's limit
LETTERS = "ABCD"


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


def _txt(pair, lang: str) -> str:
    """[uz, ru] in the reader's language; uz_cyr is transliterated."""
    if lang == "ru":
        return pair[1]
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        return lat_to_cyr(pair[0])
    return pair[0]


def _h(pair, lang: str) -> str:
    return html.escape(_txt(pair, lang), quote=False)


def _option_label(item: dict, pos: int, opt: int, lang: str) -> str:
    text = _txt(item["options"][opt], lang)
    return f"{LETTERS[pos]}) {text}" if item["kind"] == "quiz" else text


# ─────────────────────────────── messages ───────────────────────────────────

_HEAD = ["🧠 Keto savol", "🧠 Кето-вопрос"]
_ASK = ["👇 Javobni tanlang — to'g'ri javob va qisqa izoh darhol chiqadi.",
        "👇 Выберите ответ — правильный ответ и короткое пояснение появятся сразу."]


def question_message(item: dict, send_id: int, lang: str) -> tuple[str, InlineKeyboardMarkup]:
    order = quiz_bank.option_order(item, send_id)
    text = f"<b>{_h(_HEAD, lang)}</b>\n\n<b>{_h(item['q'], lang)}</b>\n\n{_h(_ASK, lang)}"
    rows = [[InlineKeyboardButton(text=_option_label(item, pos, opt, lang),
                                  callback_data=f"dq:{send_id}:{pos}")]
            for pos, opt in enumerate(order)]
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


def game_url(item: dict) -> str | None:
    if not WEBAPP_URL:
        return None
    return f"{WEBAPP_URL.rstrip('/')}/?game={quiz_bank.GAME_OF_KIND[item['kind']]}"


def answer_message(item: dict, send_id: int, choice_pos: int, lang: str,
                   answered: int, right: int) -> tuple[str, InlineKeyboardMarkup | None]:
    """The question turned into its answer, with the invitation to the site."""
    order = quiz_bank.option_order(item, send_id)
    lines = [f"<b>{_h(_HEAD, lang)}</b>", "", f"<b>{_h(item['q'], lang)}</b>", ""]
    for pos, opt in enumerate(order):
        if opt == item["correct"]:
            mark = "✅"
        elif pos == choice_pos:
            mark = "❌"
        else:
            mark = "▫️"
        lines.append(f"{mark} {html.escape(_option_label(item, pos, opt, lang), quote=False)}")
    lines += ["", f"💡 {_h(item['e'], lang)}"]
    if answered:
        pct = round(right * 100 / answered)
        lines += ["", _h([f"📊 {answered} kishi javob berdi, {pct}% i to'g'ri topdi.",
                          f"📊 Ответили {answered} чел., верно — {pct}%."], lang)]
    lines += ["", _h(["🎮 Saytimizda yana ko'p savol va 4 ta bilim o'yini bor — davom eting!",
                      "🎮 На нашем сайте ещё много вопросов и 4 игры знаний — продолжайте!"], lang)]
    url = game_url(item)
    markup = None
    if url:
        markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text=_txt(["🎮 Davom etish — saytda", "🎮 Продолжить на сайте"], lang),
            web_app=WebAppInfo(url=url))]])
    return "\n".join(lines), markup


def popup_text(item: dict, correct: bool, lang: str) -> str:
    if correct:
        return _txt(["🎉 To'g'ri! Barakalla!", "🎉 Верно! Молодец!"], lang)
    right = _txt(item["options"][item["correct"]], lang)
    return _txt(["😅 Afsus! To'g'ri javob: ", "😅 Увы! Правильный ответ: "], lang)[:60] + right[:120]


# ─────────────────────────────── answering ──────────────────────────────────

@router.callback_query(F.data.startswith("dq:"))
async def on_answer(callback: CallbackQuery):
    try:
        _, send_s, pos_s = callback.data.split(":")
        send_id, pos = int(send_s), int(pos_s)
    except ValueError:
        await callback.answer()
        return
    send = await database.get_daily_quiz_send(send_id)
    item = quiz_bank.build_item(send["item_key"]) if send else None
    if not item or not 0 <= pos < len(item["options"]):
        await callback.answer()
        return

    user_id = callback.from_user.id
    lang = await database.get_user_language(user_id)
    choice = quiz_bank.option_order(item, send_id)[pos]
    correct = choice == item["correct"]
    if not await database.record_daily_quiz_answer(send_id, user_id, choice, correct):
        await callback.answer(_txt(["Siz bu savolga javob bergansiz 🙂", "Вы уже ответили на этот вопрос 🙂"], lang))
        return

    await callback.answer(popup_text(item, correct, lang), show_alert=not correct)
    answered, right = await database.daily_quiz_stats(send_id)
    text, markup = answer_message(item, send_id, pos, lang, answered, right)
    try:
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup,
                                         disable_web_page_preview=True)
    except Exception:
        logger.warning("Keto savol answer edit failed for %s", user_id, exc_info=True)


# ──────────────────────────────── sending ───────────────────────────────────

async def _send(bot: Bot, user_id: int, text: str, markup) -> bool:
    for attempt in range(2):
        try:
            await bot.send_message(user_id, text, parse_mode=ParseMode.HTML, reply_markup=markup,
                                   disable_web_page_preview=True)
            return True
        except TelegramRetryAfter as exc:
            if attempt:
                return False
            await asyncio.sleep(exc.retry_after + 1)
        except (TelegramForbiddenError, TelegramBadRequest):
            return False            # blocked the bot / never pressed START
        except Exception:
            logger.exception("Keto savol to %s failed", user_id)
            return False
    return False


async def send_round(bot: Bot, day=None, test_user: int | None = None) -> dict | None:
    """Pick a question and send it — to everyone for `day`, or only to
    `test_user` (an admin's test, kept out of the rotation and the stats).
    None when the day was already claimed."""
    key = quiz_bank.pick_key(await database.daily_quiz_sent_keys())
    item = quiz_bank.build_item(key)
    send_id = await database.start_daily_quiz(None if test_user else day, key, is_test=bool(test_user))
    if send_id is None:
        return None
    users = [test_user] if test_user else await database.get_all_user_ids()
    langs = await database.get_user_languages(users)
    sent = failed = 0
    for uid in users:
        text, markup = question_message(item, send_id, langs.get(uid, "uz"))
        if await _send(bot, uid, text, markup):
            sent += 1
        else:
            failed += 1
        if not test_user:
            await asyncio.sleep(SEND_DELAY)
    await database.finish_daily_quiz(send_id, sent, failed)
    logger.info("Keto savol #%s %s: %d ok, %d failed%s", send_id, key, sent, failed,
                " (test)" if test_user else "")
    return {"send_id": send_id, "item": item, "sent": sent, "failed": failed}


def _round_line(r: dict) -> str:
    item = quiz_bank.build_item(r["item_key"])
    q = item["q"][0] if item else r["item_key"]
    if len(q) > 60:
        q = q[:57].rstrip() + "…"
    answered = int(r["answered"] or 0)
    pct = f", {round(int(r['right_answers']) * 100 / answered)}% to'g'ri" if answered else ""
    day = r["day"].strftime("%d.%m") if r.get("day") else "—"
    return (f"• {day} — {html.escape(q)}\n"
            f"   📨 {r['sent']} ta yetkazildi · 🙋 {answered} ta javob{pct}")


async def _notify_admins(bot: Bot, text: str) -> None:
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception:
            pass


async def _tick(bot: Bot) -> None:
    if not await database.daily_quiz_enabled():
        return
    now = _now_tk()
    if not SEND_HOUR <= now.hour < LAST_HOUR:
        return
    last = await database.daily_quiz_last_day()
    if last is not None and (now.date() - last).days < INTERVAL_DAYS:
        return
    result = await send_round(bot, now.date())
    if not result:
        return
    recent = await database.daily_quiz_recent(2)
    prev = f"\n\nOldingi savol:\n{_round_line(recent[1])}" if len(recent) > 1 else ""
    await _notify_admins(
        bot,
        f"🧠 <b>Keto savol yuborildi</b>\n{html.escape(result['item']['q'][0])}\n"
        f"✅ {result['sent']} ta yetkazildi, ⚠️ {result['failed']} ta yetmadi.{prev}\n\n"
        "Boshqarish: /savol",
    )


async def scheduler_loop(bot: Bot) -> None:
    logger.info("Keto savol scheduler started (every %d days, %02d:00 Tashkent)", INTERVAL_DAYS, SEND_HOUR)
    try:
        if await database.claim_release_notes("daily-quiz-armed-2026-10"):
            await _notify_admins(
                bot,
                "🧠 <b>Keto savol yoqildi</b>\n"
                f"Har {INTERVAL_DAYS} kunda soat {SEND_HOUR}:00 da barcha mijozlarga sayt o'yinlaridan "
                "bitta savol boradi. Javob bergach, to'g'ri javob, izoh va «🎮 Davom etish — saytda» "
                "tugmasi chiqadi.\nBoshqarish va natijalar: /savol",
            )
    except Exception:
        logger.exception("Keto savol arming note failed")
    while True:
        try:
            await _tick(bot)
        except Exception:
            logger.exception("Keto savol tick failed")
        await asyncio.sleep(CHECK_EVERY)


# ─────────────────────────────── admin view ─────────────────────────────────

def _next_day(last, now: datetime):
    today = now.date() if now.hour < LAST_HOUR else now.date() + timedelta(days=1)
    if last is None:
        return today
    return max(last + timedelta(days=INTERVAL_DAYS), today)


async def status_text() -> tuple[str, InlineKeyboardMarkup]:
    enabled = await database.daily_quiz_enabled()
    last = await database.daily_quiz_last_day()
    recent = await database.daily_quiz_recent(5)
    state = "✅ yoqilgan" if enabled else "⏸ to'xtatilgan"
    lines = ["🧠 <b>Keto savol</b>",
             f"Har {INTERVAL_DAYS} kunda soat {SEND_HOUR}:00 da barcha mijozlarga bitta savol.",
             f"Holat: {state}"]
    if enabled:
        lines.append(f"Keyingisi: {_next_day(last, _now_tk()):%d.%m.%Y} soat {SEND_HOUR}:00")
    if recent:
        lines += ["", "<b>Oxirgi savollar:</b>"] + [_round_line(r) for r in recent]
    rows = [[InlineKeyboardButton(text="🧪 Menga sinov savoli", callback_data="dqa:test")],
            [InlineKeyboardButton(text="⏸ To'xtatish" if enabled else "▶️ Yoqish",
                                  callback_data="dqa:off" if enabled else "dqa:on")]]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("savol"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_status(message: Message):
    text, markup = await status_text()
    await message.answer(text, parse_mode=ParseMode.HTML, reply_markup=markup)


@router.callback_query(F.data.startswith("dqa:"), F.from_user.id.in_(ADMIN_IDS))
async def on_admin(callback: CallbackQuery, bot: Bot):
    action = callback.data.split(":", 1)[1]
    if action == "test":
        result = await send_round(bot, test_user=callback.from_user.id)
        await callback.answer("🧪 Sinov savoli yuborildi" if result and result["sent"]
                              else "❌ Yuborilmadi", show_alert=False)
        return
    if action in ("on", "off"):
        await database.set_daily_quiz_enabled(action == "on")
    text, markup = await status_text()
    try:
        await callback.message.edit_text(text, parse_mode=ParseMode.HTML, reply_markup=markup)
    except Exception:
        pass
    await callback.answer("✅ Yoqildi" if action == "on" else "⏸ To'xtatildi" if action == "off" else "")
