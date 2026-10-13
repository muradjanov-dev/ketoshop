"""
Video qo'llanma — «bot va sayt orqali qanday buyurtma beriladi» (egasi,
2026-10-11): "yangi mijozlarga bot orqali buyurtma qilish qo'llanmasini
avtomatik yuboradigan qilishimiz kerak, menga tugma qo'shib ber, 2 ta video
tashlayman — har bir yangi foydalanuvchiga va hozirgi bor foydalanuvchilarga".

Qanday ishlaydi:
  • Admin: 🚀 Marketing va Aksiya → 🎬 Video qo'llanma. Videolarni shu yerga
    birma-bir yuboradi (Telegram file_id saqlanadi, fayl serverga
    yuklanmaydi), o'ziga sinab ko'radi, «Hammaga yuborish»ni tasdiqlaydi.
  • Yangi foydalanuvchi: tilni tanlagan zahoti, o'z tilida, bir marta
    (avtomatik yuborish yoqilgan bo'lsa — sukut bo'yicha yoqilgan).
  • Hozirgi foydalanuvchilar: admin tugmasi bilan, faqat hali olmaganlarga.
  • Har kim: «Qo'llanma» menyusida «🎬 Qanday buyurtma beriladi?» — videolar
    yuklangan bo'lsa.

Kim olgani onboarding_video_sent da: hech kimga ikki marta ketmaydi —
na avtomatik, na «Hammaga yuborish» qayta bosilganda.
"""
import asyncio
import html
import logging
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaVideo, Message,
)

import database
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router(name="onboarding_video")

MAX_VIDEOS = 4
SEND_DELAY = 0.1          # bir foydalanuvchiga 2 ta video = 2 xabar → ~20 xabar/s
TZ_OFFSET = timedelta(hours=5)

# Egasining so'zi bilan (2026-10-11).
CAPTION = {
    "uz": "🎬 <b>Ketoshop'dan qanday buyurtma beriladi?</b>\n\n"
          "Bot va sayt orqali Keto va sog'lom mahsulotlarni oson buyurtma qilishni "
          "shu videodan o'rganib olishingiz mumkin.",
    "ru": "🎬 <b>Как заказать в Ketoshop?</b>\n\n"
          "Из этого видео вы узнаете, как легко заказывать кето и полезные продукты "
          "через бота и сайт.",
}
BUTTON = {"uz": "🎬 Qanday buyurtma beriladi?", "ru": "🎬 Как сделать заказ?"}

_table_ready = False
_broadcast_running = False


class VideoStates(StatesGroup):
    waiting_video = State()


def _pick(entry: dict, lang: str) -> str:
    if lang == "ru":
        return entry["ru"]
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        return lat_to_cyr(entry["uz"])
    return entry["uz"]


def caption(lang: str) -> str:
    return _pick(CAPTION, lang)


def button_text(lang: str) -> str:
    return _pick(BUTTON, lang)


# ───────────────────────────── holat ─────────────────────────────

async def _ensure_tables(conn) -> None:
    global _table_ready
    if _table_ready:
        return
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS onboarding_video_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            file_ids TEXT[] NOT NULL DEFAULT '{}',
            auto_new BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at TIMESTAMP,
            updated_by BIGINT
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS onboarding_video_sent (
            user_id BIGINT PRIMARY KEY,
            sent_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
        )
    """)
    _table_ready = True


async def get_state() -> dict:
    async with database.pool.acquire() as conn:
        await _ensure_tables(conn)
        row = await conn.fetchrow("SELECT file_ids, auto_new FROM onboarding_video_state WHERE id = 1")
    if row is None:
        return {"file_ids": [], "auto_new": True}
    return {"file_ids": list(row["file_ids"] or []), "auto_new": bool(row["auto_new"])}


async def _save(by: int | None, *, file_ids: list[str] | None = None,
                auto_new: bool | None = None) -> None:
    state = await get_state()
    if file_ids is None:
        file_ids = state["file_ids"]
    if auto_new is None:
        auto_new = state["auto_new"]
    async with database.pool.acquire() as conn:
        await _ensure_tables(conn)
        await conn.execute(
            """INSERT INTO onboarding_video_state (id, file_ids, auto_new, updated_at, updated_by)
               VALUES (1, $1, $2, (NOW() AT TIME ZONE 'UTC'), $3)
               ON CONFLICT (id) DO UPDATE
               SET file_ids = EXCLUDED.file_ids, auto_new = EXCLUDED.auto_new,
                   updated_at = EXCLUDED.updated_at, updated_by = EXCLUDED.updated_by""",
            file_ids, auto_new, by)


async def has_videos() -> bool:
    try:
        return bool((await get_state())["file_ids"])
    except Exception:
        logger.warning("onboarding video state read failed", exc_info=True)
        return False


async def _was_sent(user_id: int) -> bool:
    async with database.pool.acquire() as conn:
        await _ensure_tables(conn)
        return bool(await conn.fetchval(
            "SELECT 1 FROM onboarding_video_sent WHERE user_id = $1", user_id))


async def _mark_sent(user_id: int) -> None:
    async with database.pool.acquire() as conn:
        await _ensure_tables(conn)
        await conn.execute(
            "INSERT INTO onboarding_video_sent (user_id) VALUES ($1) ON CONFLICT (user_id) DO NOTHING",
            user_id)


async def _pending_user_ids() -> list[int]:
    """Everyone a broadcast may reach (banned excluded — get_all_user_ids)
    who has not had the videos yet."""
    all_ids = await database.get_all_user_ids()
    async with database.pool.acquire() as conn:
        await _ensure_tables(conn)
        done = {r["user_id"] for r in await conn.fetch("SELECT user_id FROM onboarding_video_sent")}
    return [u for u in all_ids if u not in done]


async def _sent_count() -> int:
    async with database.pool.acquire() as conn:
        await _ensure_tables(conn)
        return int(await conn.fetchval("SELECT COUNT(*) FROM onboarding_video_sent") or 0)


# ───────────────────────────── yuborish ─────────────────────────────

async def send_videos(bot: Bot, chat_id: int, lang: str, file_ids: list[str]) -> None:
    """One video → a captioned video; several → one album with the caption
    under it, so a buyer gets one block rather than a stream of messages.
    Buyer content — no admin mood line even when the chat is an admin's."""
    import admin_mood
    text = caption(lang)
    with admin_mood.quiet():
        if len(file_ids) == 1:
            await bot.send_video(chat_id, file_ids[0], caption=text, parse_mode=ParseMode.HTML)
            return
        media = [InputMediaVideo(media=fid) for fid in file_ids]
        media[0] = InputMediaVideo(media=file_ids[0], caption=text, parse_mode=ParseMode.HTML)
        await bot.send_media_group(chat_id, media)


async def _deliver(bot: Bot, user_id: int, lang: str, file_ids: list[str]) -> bool:
    """Send once and remember it. False when the user can't be reached."""
    for attempt in (1, 2):
        try:
            await send_videos(bot, user_id, lang, file_ids)
            await _mark_sent(user_id)
            return True
        except TelegramRetryAfter as e:
            if attempt == 2:
                return False
            await asyncio.sleep(e.retry_after + 1)
        except (TelegramForbiddenError, TelegramBadRequest):
            return False
        except Exception:
            logger.exception("onboarding video send failed for %s", user_id)
            return False
    return False


async def maybe_send_to_new_user(bot: Bot, user_id: int, lang: str) -> bool:
    """Called right after a user picks their language. Sends only when the
    videos exist, auto-send is on and this user has never had them. Never
    raises — onboarding must not break because of a video."""
    try:
        state = await get_state()
        if not state["auto_new"] or not state["file_ids"]:
            return False
        if await _was_sent(user_id):
            return False
        return await _deliver(bot, user_id, lang, state["file_ids"])
    except Exception:
        logger.exception("onboarding video for new user %s failed", user_id)
        return False


async def broadcast(bot: Bot, admin_id: int) -> tuple[int, int]:
    """Everyone who hasn't had the videos, each in their own language."""
    global _broadcast_running
    _broadcast_running = True
    sent = failed = 0
    try:
        state = await get_state()
        file_ids = state["file_ids"]
        if not file_ids:
            return 0, 0
        user_ids = await _pending_user_ids()
        langs = await database.get_user_languages(user_ids)
        for uid in user_ids:
            ok = await _deliver(bot, uid, langs.get(uid, "uz"), file_ids)
            sent += ok
            failed += not ok
            await asyncio.sleep(SEND_DELAY * len(file_ids))
    finally:
        _broadcast_running = False
    logger.info("Onboarding video broadcast by %s: %d sent, %d failed", admin_id, sent, failed)
    try:
        await bot.send_message(
            admin_id,
            f"🎬 <b>Video qo'llanma yuborildi</b>\n✅ {sent} ta yetkazildi\n⚠️ {failed} ta yetmadi "
            f"(botni bloklagan yoki o'chirgan)",
            parse_mode=ParseMode.HTML)
    except Exception:
        pass
    return sent, failed


# ───────────────────────────── admin ekrani ─────────────────────────────

def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def _screen() -> tuple[str, InlineKeyboardMarkup]:
    state = await get_state()
    n = len(state["file_ids"])
    total = len(await database.get_all_user_ids())
    got = await _sent_count()
    lines = ["🎬 <b>Video qo'llanma</b>", "",
             "Bot va sayt orqali qanday buyurtma berishni ko'rsatadigan video(lar).", "",
             f"📼 Yuklangan: <b>{n} ta</b>" + ("" if n else " — avval videoni yuklang"),
             "🆕 Yangi foydalanuvchilarga avtomatik: <b>"
             + ("✅ yoqilgan" if state["auto_new"] else "⛔ o'chirilgan") + "</b>",
             f"👥 Olganlar: <b>{got}</b> / {total}"]
    if _broadcast_running:
        lines += ["", "⏳ Hozir hammaga yuborilmoqda…"]
    rows = [[InlineKeyboardButton(text="➕ Video qo'shish", callback_data="ovid:add")]]
    if n:
        rows.append([InlineKeyboardButton(text="👀 O'zimga yuborish", callback_data="ovid:test"),
                     InlineKeyboardButton(text="🗑 Tozalash", callback_data="ovid:clear")])
        rows.append([InlineKeyboardButton(text="📣 Hammaga yuborish", callback_data="ovid:all")])
    rows.append([InlineKeyboardButton(
        text="🆕 Avtomatik: " + ("o'chirish" if state["auto_new"] else "yoqish"),
        callback_data="ovid:auto")])
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_menu:marketing")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def _show(callback: CallbackQuery) -> None:
    text, kb = await _screen()
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML)
    except TelegramBadRequest:
        # Photo/video message or unchanged text — send a fresh one instead.
        await callback.message.answer(text, reply_markup=kb, parse_mode=ParseMode.HTML)


@router.callback_query(F.data == "admin:video")
async def open_screen(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        return
    await state.clear()
    await _show(callback)
    await callback.answer()


@router.callback_query(F.data == "ovid:add")
async def add_prompt(callback: CallbackQuery, state: FSMContext):
    if not _is_admin(callback.from_user.id):
        return
    current = (await get_state())["file_ids"]
    if len(current) >= MAX_VIDEOS:
        await callback.answer(f"Ko'pi bilan {MAX_VIDEOS} ta video. Avval tozalang.", show_alert=True)
        return
    await state.set_state(VideoStates.waiting_video)
    await callback.message.answer(
        "📼 Videoni shu yerga yuboring (birma-bir; oddiy video yoki fayl sifatida).\n"
        "Har biri qabul qilingach xabar beraman. Tugatgach — «✅ Tayyor».",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Tayyor", callback_data="admin:video")]]))
    await callback.answer()


def _video_file_id(message: Message) -> str | None:
    if message.video:
        return message.video.file_id
    doc = message.document
    if doc and (doc.mime_type or "").startswith("video/"):
        return doc.file_id
    return None


@router.message(StateFilter(VideoStates.waiting_video))
async def receive_video(message: Message, state: FSMContext):
    if not _is_admin(message.from_user.id):
        return
    fid = _video_file_id(message)
    if not fid:
        await message.answer("Bu video emas. Videoni yuboring yoki «✅ Tayyor» ni bosing.")
        return
    current = (await get_state())["file_ids"]
    if len(current) >= MAX_VIDEOS:
        await state.clear()
        await message.answer(f"Ko'pi bilan {MAX_VIDEOS} ta video — bu qabul qilinmadi.")
        return
    current.append(fid)
    await _save(message.from_user.id, file_ids=current)
    await message.answer(
        f"✅ {len(current)}-video saqlandi. Yana yuboring yoki «✅ Tayyor».",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Tayyor", callback_data="admin:video")]]))


@router.callback_query(F.data == "ovid:test")
async def test_send(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return
    file_ids = (await get_state())["file_ids"]
    if not file_ids:
        await callback.answer("Video yuklanmagan.", show_alert=True)
        return
    lang = await database.get_user_language(callback.from_user.id)
    # Preview only — not marked as sent, so the admin still gets the real one.
    await send_videos(callback.bot, callback.from_user.id, lang, file_ids)
    await callback.answer("Yuborildi — mijozlar aynan shuni ko'radi.")


@router.callback_query(F.data == "ovid:clear")
async def clear_videos(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return
    await _save(callback.from_user.id, file_ids=[])
    await callback.answer("🗑 Videolar tozalandi.")
    await _show(callback)


@router.callback_query(F.data == "ovid:auto")
async def toggle_auto(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return
    state = await get_state()
    await _save(callback.from_user.id, auto_new=not state["auto_new"])
    await callback.answer("Yoqildi" if not state["auto_new"] else "O'chirildi")
    await _show(callback)


@router.callback_query(F.data == "ovid:all")
async def confirm_all(callback: CallbackQuery):
    if not _is_admin(callback.from_user.id):
        return
    if _broadcast_running:
        await callback.answer("Hozir yuborilmoqda — tugashini kuting.", show_alert=True)
        return
    state = await get_state()
    if not state["file_ids"]:
        await callback.answer("Video yuklanmagan.", show_alert=True)
        return
    pending = len(await _pending_user_ids())
    if not pending:
        await callback.answer("Hamma allaqachon olgan.", show_alert=True)
        return
    now = datetime.utcnow() + TZ_OFFSET
    minutes = max(1, round(pending * SEND_DELAY * len(state["file_ids"]) / 60))
    lines = [f"📣 <b>{pending} ta foydalanuvchiga</b> yuboriladi — hali olmaganlarga, har biriga o'z tilida.",
             f"⏱ Taxminan {minutes} daqiqa davom etadi.",
             "Qayta bosilsa ham hech kimga ikki marta bormaydi."]
    if now.hour >= 22 or now.hour < 8:
        lines.append(f"\n⚠️ Hozir {now:%H:%M} — mijozlar uxlayotgan bo'lishi mumkin. Ertalab yuborish yaxshiroq.")
    lines.append("\nTasdiqlaysizmi?")
    await callback.message.answer(
        "\n".join(lines), parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Ha, yuborish", callback_data="ovid:all:go"),
            InlineKeyboardButton(text="❌ Bekor", callback_data="admin:video"),
        ]]))
    await callback.answer()


@router.callback_query(F.data == "ovid:all:go")
async def start_all(callback: CallbackQuery):
    global _broadcast_running
    if not _is_admin(callback.from_user.id):
        return
    if _broadcast_running:
        await callback.answer("Allaqachon yuborilmoqda.", show_alert=True)
        return
    _broadcast_running = True    # set before the task starts — a double tap can't launch two
    asyncio.create_task(broadcast(callback.bot, callback.from_user.id))
    try:
        await callback.message.edit_text("🚀 Yuborish boshlandi. Tugagach natijasini yozaman.")
    except TelegramBadRequest:
        pass
    await callback.answer()


# ───────────────────────────── mijoz tugmasi ─────────────────────────────

@router.callback_query(F.data == "howto_video")
async def show_to_user(callback: CallbackQuery):
    file_ids = (await get_state())["file_ids"]
    lang = await database.get_user_language(callback.from_user.id)
    if not file_ids:
        await callback.answer("🎬", show_alert=False)
        return
    try:
        await send_videos(callback.bot, callback.from_user.id, lang, file_ids)
        await _mark_sent(callback.from_user.id)
    except Exception:
        logger.exception("howto video for %s failed", callback.from_user.id)
    await callback.answer()
