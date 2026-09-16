"""
Guruhda havola qo'riqchisi — egasi so'rovi 2026-09-17: bot guruhga admin
qilib qo'shilsa, adminlardan boshqa hech kim havola tashlay olmasin.

Nima havola hisoblanadi: Telegram o'zi belgilagan url / text_link
entity lari (matnda ham, rasm/video izohida ham), yashirin havolali inline
tugmalar, va Telegram entity qilmagan "t.me/..." yozuvlari (bo'sh joy
bilan bo'lib yuborilgan spam). Oddiy @mention havola emas — odamlar bir-
birini chaqiradi.

Kim tashlay oladi: guruh egasi va adminlari (Telegram'dagi ro'yxat, 10
daqiqa keshlanadi), bot adminlari (config.ADMIN_IDS), guruh nomidan yozgan
anonim admin va guruhga bog'langan kanaldan avtomatik tushgan postlar.
Qolgan hamma — boshqa botlar ham — havolasi bilan o'chiriladi.

Bot guruhda "Xabarlarni o'chirish" huquqi bilan admin bo'lishi shart —
aks holda o'chira olmaydi, xato jurnalga yoziladi va boshqa hech narsa
buzilmaydi. Tahrirlangan xabarlar ham tekshiriladi: spamchilar oddiy xabar
yozib, keyin unga havola qo'shib tahrirlaydi.

Sozlama (ixtiyoriy):
  LINK_GUARD=0           qo'riqchini butunlay o'chiradi
  LINK_GUARD_CHATS       faqat shu guruh id larida ishlasin (vergul bilan);
                         bo'sh bo'lsa — bot admin bo'lgan hamma guruhda.
"""
import asyncio
import logging
import os
import re
import time

from aiogram import Router, F, Bot
from aiogram.types import Message

from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router(name="link_guard")

ENABLED = os.getenv("LINK_GUARD", "1").strip() not in ("0", "false", "off", "")
ONLY_CHATS = {
    int(part) for part in os.getenv("LINK_GUARD_CHATS", "").replace(" ", "").split(",")
    if part.lstrip("-").isdigit()
}

ADMIN_CACHE_TTL = 600      # guruh adminlari ro'yxati shuncha soniya eslab qolinadi
WARN_COOLDOWN = 60         # bitta odamga bir daqiqada bittadan ortiq ogohlantirish yo'q
WARN_LIFETIME = 15         # ogohlantirish shuncha soniyadan keyin o'zi o'chadi

_LINK_ENTITY_TYPES = {"url", "text_link"}
# Entity bo'lmay qolgan havolalar: "t . me/kanal", "telegram.me/..", "tg://..".
_RAW_LINK_RE = re.compile(
    r"(?:t\s*\.\s*me|telegram\s*\.\s*(?:me|dog))\s*/\s*\w|tg://|https?://",
    re.IGNORECASE,
)

_admin_cache: dict[int, tuple[set[int], float]] = {}
_last_warned: dict[tuple[int, int], float] = {}


def _is_group(message: Message) -> bool:
    return message.chat.type in ("group", "supergroup")


def has_link(message: Message) -> bool:
    """Xabarda havola bormi — matn, izoh yoki inline tugmada."""
    for entity in (message.entities or []) + (message.caption_entities or []):
        if entity.type in _LINK_ENTITY_TYPES:
            return True
    text = (message.text or "") + "\n" + (message.caption or "")
    if _RAW_LINK_RE.search(text):
        return True
    markup = message.reply_markup
    for row in (getattr(markup, "inline_keyboard", None) or []):
        for button in row:
            if getattr(button, "url", None):
                return True
    return False


async def _chat_admin_ids(bot: Bot, chat_id: int) -> set[int] | None:
    now = time.monotonic()
    cached = _admin_cache.get(chat_id)
    if cached and now - cached[1] < ADMIN_CACHE_TTL:
        return cached[0]
    try:
        admins = await bot.get_chat_administrators(chat_id)
    except Exception:
        logger.warning("Could not load admins of chat %s", chat_id, exc_info=True)
        return cached[0] if cached else None
    ids = {member.user.id for member in admins}
    _admin_cache[chat_id] = (ids, now)
    return ids


async def is_privileged(bot: Bot, message: Message) -> bool | None:
    """Havola tashlashga ruxsat bormi. None — bilib bo'lmadi (adminlar
    ro'yxati olinmadi); bunda xavfsiz tomonga — hech narsani o'chirmaymiz."""
    # Anonim admin (guruh nomidan) va bog'langan kanal posti.
    if message.sender_chat is not None:
        if message.sender_chat.id == message.chat.id or message.is_automatic_forward:
            return True
    user = message.from_user
    if user is None:
        return False
    if user.id in ADMIN_IDS or user.id == bot.id:
        return True
    admin_ids = await _chat_admin_ids(bot, message.chat.id)
    if admin_ids is None:
        return None
    return user.id in admin_ids


async def _should_guard(message: Message, bot: Bot) -> bool:
    """FILTR: guruh + havola bor + muallif admin emas."""
    if not ENABLED or not _is_group(message):
        return False
    if ONLY_CHATS and message.chat.id not in ONLY_CHATS:
        return False
    if not has_link(message):
        return False
    return await is_privileged(bot, message) is False


async def _delete_later(bot: Bot, chat_id: int, message_id: int) -> None:
    await asyncio.sleep(WARN_LIFETIME)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass


async def _remove(message: Message, bot: Bot) -> None:
    try:
        await message.delete()
    except Exception:
        logger.warning(
            "Link guard could not delete message %s in chat %s — is the bot an "
            "admin with 'Delete messages' right?", message.message_id, message.chat.id,
            exc_info=True,
        )
        return

    user = message.from_user
    if user is None:
        return
    key = (message.chat.id, user.id)
    now = time.monotonic()
    if now - _last_warned.get(key, 0) < WARN_COOLDOWN:
        return
    _last_warned[key] = now
    name = (user.first_name or "Foydalanuvchi").replace("<", "").replace("&", "")
    try:
        warning = await bot.send_message(
            message.chat.id,
            f'<a href="tg://user?id={user.id}">{name}</a>, guruhda havola '
            f"tashlash mumkin emas — xabaringiz o'chirildi.",
            parse_mode="HTML",
        )
    except Exception:
        return
    asyncio.create_task(_delete_later(bot, message.chat.id, warning.message_id))


@router.message(_should_guard)
async def on_group_link(message: Message, bot: Bot):
    await _remove(message, bot)


@router.edited_message(_should_guard)
async def on_group_link_edited(message: Message, bot: Bot):
    await _remove(message, bot)
