"""
Yangiliklar e'loni — the shop's standing offers, announced to buyers.

release_notes.py tells the ADMINS what changed in the code. This tells the
BUYERS what changed for them, which is a different list and a different voice:
no commands, no panels, no fixes — only what they get and what it takes to get
it. Sent on demand (the owner picks the moment), never on a schedule.

  /yangilik_test    — the three languages, to the admin who asked
  /yangilik_kanal   — the channel post (Cyrillic), nobody's private chat
  /yangilik_hammaga — every buyer, each in their own users.language

The channel post carries a url button, because a channel reader may never have
opened the bot; the private copy carries the Mini App button the rest of the
bot uses.
"""
import asyncio
import logging

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramBadRequest,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

import database
from config import (BOT_USERNAME, FREE_DELIVERY_FROM, MYSTERY_GIFT_FROM,
                    REQUIRED_CHANNEL_ID, WEBAPP_URL)

logger = logging.getLogger(__name__)

SEND_DELAY = 0.05        # ~20 sends/sec, under Telegram's broadcast limit
CHANNEL_LANG = "uz_cyr"  # the channel reads Cyrillic (owner, 2026-09-19)


def _som(amount) -> str:
    return f"{int(amount):,}".replace(",", " ")


_TEXT = {
    "uz": (
        "🎁 <b>Ketoshopda yangi imkoniyatlar</b>\n\n"

        "🤫 <b>Sirli sovg'a</b>\n"
        "{mystery} so'mdan yuqori har bir buyurtmaga Ketoshop jamoasi nomidan "
        "<b>sirli sovg'a</b> qo'shamiz. Nima ekanini oldindan aytmaymiz — "
        "qutini ochganingizda bilasiz.\n\n"

        "🚚 <b>Bepul yetkazib berish</b>\n"
        "{delivery} so'mdan yuqori buyurtmalar Toshkent bo'ylab <b>bepul</b> "
        "yetkaziladi.\n\n"

        "🍬 <b>Har bir buyurtmaga 100 gr Eritritol</b>\n"
        "Summasidan qat'i nazar — har safar, mutlaqo bepul.\n\n"

        "🌟 <b>Kun mahsuloti</b>\n"
        "Har kuni soat 13:00 da bitta mahsulotni tanlab, siz uchun alohida "
        "e'lon qilamiz: tarkibi, foydasi va shundan nima tayyorlash mumkinligi "
        "bilan. Xabarning o'zidan turib savatga qo'shasiz.\n\n"

        "🎁 <b>Keto tangachalar</b>\n"
        "Har xariddan pulingizning bir qismi Keto tangacha bo'lib qaytadi va "
        "keyingi buyurtmada chegirma bo'lib ishlatiladi.\n\n"

        "Sog'lig'ingiz uchun eng yaxshisini tanlayapsiz — biz esa buni "
        "qadrlaymiz 💚"
    ),
    "ru": (
        "🎁 <b>Новые возможности в Ketoshop</b>\n\n"

        "🤫 <b>Таинственный подарок</b>\n"
        "К каждому заказу от {mystery} сум команда Ketoshop добавляет "
        "<b>таинственный подарок</b>. Что внутри — заранее не скажем: "
        "узнаете, когда откроете коробку.\n\n"

        "🚚 <b>Бесплатная доставка</b>\n"
        "Заказы от {delivery} сум доставляем по Ташкенту <b>бесплатно</b>.\n\n"

        "🍬 <b>100 гр Эритритола к каждому заказу</b>\n"
        "На любую сумму — каждый раз и совершенно бесплатно.\n\n"

        "🌟 <b>Товар дня</b>\n"
        "Каждый день в 13:00 выбираем один товар и рассказываем о нём отдельно: "
        "состав, польза и что из него приготовить. Добавить в корзину можно "
        "прямо из сообщения.\n\n"

        "🎁 <b>Keto-монетки</b>\n"
        "С каждой покупки часть суммы возвращается монетками — и работает как "
        "скидка в следующем заказе.\n\n"

        "Вы выбираете лучшее для своего здоровья — и мы это ценим 💚"
    ),
}

_BUTTON = {"uz": "🌿 Do'konga o'tish", "ru": "🌿 В магазин"}
_CHANNEL_BUTTON = {"uz": "🛒 Botni ochish", "ru": "🛒 Открыть бота"}


def text_for(lang: str) -> str:
    """The announcement in `lang`. Cyrillic Uzbek is transliterated from the
    Latin source, the same rule the rest of the bot follows."""
    raw = _TEXT["ru"] if lang == "ru" else _TEXT["uz"]
    out = raw.format(mystery=_som(MYSTERY_GIFT_FROM), delivery=_som(FREE_DELIVERY_FROM))
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        out = lat_to_cyr(out)
    return out


def buyer_keyboard(lang: str) -> InlineKeyboardMarkup | None:
    if not WEBAPP_URL:
        return None
    label = _BUTTON["ru"] if lang == "ru" else _BUTTON["uz"]
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        label = lat_to_cyr(label)
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, web_app=WebAppInfo(url=WEBAPP_URL))
    ]])


def channel_keyboard(lang: str = CHANNEL_LANG) -> InlineKeyboardMarkup:
    label = _CHANNEL_BUTTON["ru"] if lang == "ru" else _CHANNEL_BUTTON["uz"]
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        label = lat_to_cyr(label)
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=label, url=f"https://t.me/{BOT_USERNAME}")
    ]])


async def send_to_user(bot: Bot, user_id: int, lang: str) -> bool:
    try:
        await bot.send_message(user_id, text_for(lang), parse_mode=ParseMode.HTML,
                               reply_markup=buyer_keyboard(lang),
                               disable_web_page_preview=True)
        return True
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after + 1)
        try:
            await bot.send_message(user_id, text_for(lang), parse_mode=ParseMode.HTML,
                                   reply_markup=buyer_keyboard(lang),
                                   disable_web_page_preview=True)
            return True
        except Exception:
            return False
    except (TelegramForbiddenError, TelegramBadRequest):
        return False                       # blocked / never started / deleted
    except Exception:
        logger.exception("News announcement to %s failed", user_id)
        return False


async def broadcast(bot: Bot) -> tuple[int, int]:
    """Every buyer, each in their own language."""
    user_ids = await database.get_all_user_ids()
    langs = await database.get_user_languages(user_ids)
    sent = failed = 0
    for uid in user_ids:
        ok = await send_to_user(bot, uid, langs.get(uid, "uz"))
        sent += ok
        failed += not ok
        await asyncio.sleep(SEND_DELAY)
    return sent, failed


async def post_to_channel(bot: Bot) -> bool:
    if not REQUIRED_CHANNEL_ID:
        return False
    try:
        await bot.send_message(REQUIRED_CHANNEL_ID, text_for(CHANNEL_LANG),
                               parse_mode=ParseMode.HTML,
                               reply_markup=channel_keyboard(),
                               disable_web_page_preview=True)
        return True
    except Exception:
        logger.exception("News announcement to the channel failed")
        return False
