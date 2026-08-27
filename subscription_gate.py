"""
Channel-subscription gate — owner request 2026-07-27: to use the bot at
all, a buyer must first be subscribed to the KETO Shop channel. Polite,
one-screen nudge: join button + a "✅ Tekshirish" button that re-checks.

Registered as an outer middleware (see bot.py) so it runs before every
handler — admins are exempt, and the gate's own Check button is always
let through so it can do its own (uncached) re-check.

Membership status is cached in-process (not persisted) with a short TTL:
losing the cache on redeploy just costs one extra Bot API call per active
user, which is fine at this bot's scale. Every check fails OPEN — if the
Bot API call errors (e.g. the bot isn't an admin in the channel, or the
channel ID is wrong), users are let through rather than locked out, since
a config mistake here must never take down the whole bot.
"""
import logging
import time

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from config import ADMIN_IDS, REQUIRED_CHANNEL_ID, REQUIRED_CHANNEL_USERNAME

logger = logging.getLogger(__name__)

CHECK_CALLBACK = "check_subscription"
CACHE_TTL = 3600  # 1 hour — see module docstring
_SUBSCRIBED_STATUSES = {"member", "administrator", "creator"}

_cache: dict[int, tuple[bool, float]] = {}

# A not-yet-subscribed user's very first /start never reaches handlers/
# start.py — this middleware returns before the router sees it — so a
# referral deep-link payload (/start ref<id>) would otherwise be lost the
# moment someone shares their Keto musobaqasi link with a new user who
# isn't already in the channel (the common case). Stash it here and replay
# it once they confirm subscription (see CHECK_CALLBACK branch below).
# In-process only, same durability tradeoff as the membership _cache above.
_pending_start_payload: dict[int, str] = {}


async def _is_subscribed(bot, user_id: int, force: bool = False) -> bool:
    now = time.monotonic()
    if not force:
        cached = _cache.get(user_id)
        if cached and now - cached[1] < CACHE_TTL:
            return cached[0]
    try:
        member = await bot.get_chat_member(REQUIRED_CHANNEL_ID, user_id)
        subscribed = member.status in _SUBSCRIBED_STATUSES
    except Exception:
        logger.warning("Could not verify channel membership for user %s — failing open", user_id, exc_info=True)
        subscribed = True
    _cache[user_id] = (subscribed, now)
    return subscribed


def _gate_text(lang: str) -> str:
    if lang == "ru":
        return (
            "🌿 <b>Добро пожаловать в Ketoshop!</b>\n\n"
            "Чтобы пользоваться ботом, пожалуйста, подпишитесь на наш канал "
            "<b>KETO Shop</b> — там полезные советы, скидки и новинки первыми. 💚\n\n"
            "После подписки нажмите кнопку <b>✅ Проверить</b> ниже."
        )
    return (
        "🌿 <b>Ketoshopga xush kelibsiz!</b>\n\n"
        "Botdan foydalanishdan oldin, iltimos, bizning <b>KETO Shop</b> "
        "kanalimizga obuna bo'ling — u yerda foydali maslahatlar, chegirmalar "
        "va yangiliklardan birinchi bo'lib xabardor bo'lasiz. 💚\n\n"
        "Obuna bo'lgach, pastdagi <b>✅ Tekshirish</b> tugmasini bosing."
    )


def _gate_keyboard(lang: str) -> InlineKeyboardMarkup:
    join_text = "📢 Kanalga o'tish" if lang != "ru" else "📢 Перейти в канал"
    check_text = "✅ Tekshirish" if lang != "ru" else "✅ Проверить"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=join_text, url=f"https://t.me/{REQUIRED_CHANNEL_USERNAME}")],
        [InlineKeyboardButton(text=check_text, callback_data=CHECK_CALLBACK)],
    ])


def _not_yet_text(lang: str) -> str:
    return ("😔 Hali obuna bo'lmagansiz. Kanalga qo'shilib, qayta urinib ko'ring."
            if lang != "ru" else "😔 Вы ещё не подписаны. Присоединитесь к каналу и попробуйте снова.")


def _confirmed_text(lang: str) -> str:
    return ("✅ Rahmat! Obuna tasdiqlandi — botdan bemalol foydalanishingiz mumkin."
            if lang != "ru" else "✅ Спасибо! Подписка подтверждена — теперь можно пользоваться ботом.")


def _continue_keyboard(lang: str) -> InlineKeyboardMarkup:
    text = "▶️ Davom etish" if lang != "ru" else "▶️ Продолжить"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, callback_data="main_menu")]])


class SubscriptionGateMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        user = getattr(event, "from_user", None)
        if user is None or user.id in ADMIN_IDS:
            return await handler(event, data)

        bot = data["bot"]
        # Best-effort language hint before any DB record exists — Telegram's
        # own client-reported language code, not the bot's saved preference.
        lang = "ru" if (user.language_code or "").startswith("ru") else "uz"

        if isinstance(event, CallbackQuery) and event.data == CHECK_CALLBACK:
            if await _is_subscribed(bot, user.id, force=True):
                # Replay a /start this user fired *before* subscribing, which
                # this middleware blocked outright (handlers/start.py never
                # ran, so they have no users row yet and any referral
                # payload was never processed) — see _pending_start_payload.
                try:
                    import referral_contest
                    from handlers.start import ensure_registered

                    referrer_id = referral_contest.parse_ref_payload(_pending_start_payload.pop(user.id, None))
                    await ensure_registered(bot, user, referrer_id)
                except Exception:
                    logger.warning("Deferred registration failed for user %s", user.id, exc_info=True)
                try:
                    await event.message.edit_text(_confirmed_text(lang), reply_markup=_continue_keyboard(lang))
                except Exception:
                    pass
                await event.answer()
            else:
                await event.answer(_not_yet_text(lang), show_alert=True)
            return

        if not await _is_subscribed(bot, user.id):
            if isinstance(event, Message) and (event.text or "").startswith("/start"):
                parts = event.text.split(maxsplit=1)
                if len(parts) > 1:
                    _pending_start_payload[user.id] = parts[1].strip()
            if isinstance(event, CallbackQuery):
                await event.answer()
                try:
                    await event.message.edit_text(_gate_text(lang), reply_markup=_gate_keyboard(lang), parse_mode="HTML")
                    return
                except Exception:
                    pass  # message not editable (e.g. it's a photo) — fall through to a fresh message
            chat_id = event.chat.id if isinstance(event, Message) else event.from_user.id
            try:
                await bot.send_message(chat_id, _gate_text(lang), reply_markup=_gate_keyboard(lang), parse_mode="HTML")
            except Exception:
                logger.warning("Could not send subscription gate to %s", chat_id, exc_info=True)
            return

        return await handler(event, data)
