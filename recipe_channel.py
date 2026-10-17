"""
Saytdagi yangi retsept — kanalga e'lon (owner, 2026-10-17: "har safar saytga
yangi retsept chiqqanda uni rasmi va retseptni boshlanishi bilan kanalga ham
e'lon qilsak va to'liq retseptni ko'rishni bosgach saytga olib o'tadigan inline
tugma qoldirsak").

On the day a new recipe opens on the site (recipes.schedule: every EVERY_DAYS
from START), at POST_HOUR the channel gets the recipe's photo with its start —
title, the intro, time / servings / carbs, the first ingredients — and one
button, «📖 To'liq retseptni ko'rish».

A channel post can't carry a Mini App button (Telegram allows web_app buttons
in private chats only), so the button is a bot link, t.me/<bot>?start=retsept.
The bot answers it in private with the photo and a web_app button that opens
the Mini App straight on the recipe (/?recipe=<slug>) — one more tap, and the
reader is a bot user from then on.

The day is claimed in release_notes_sent before posting, so a restart can't
post twice; a failed post gives the claim back and is retried on the next
tick. The channel reads Cyrillic (product_of_day.CHANNEL_LANG).
"""
import asyncio
import html
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import (
    FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo,
)

import database
import recipes
from config import ADMIN_IDS, BOT_USERNAME, REQUIRED_CHANNEL_ID, WEBAPP_URL

logger = logging.getLogger(__name__)
router = Router()

TZ_OFFSET = timedelta(hours=5)
POST_HOUR = 11              # 11:00 Tashkent — clear of the 13:00 spotlight
LAST_HOUR = 22
CHECK_EVERY = 600
CHANNEL_LANG = "uz_cyr"
PAYLOAD = "retsept"
TEASER_INGREDIENTS = 4
PHOTO_DIR = Path(__file__).parent / "webapp" / "recipes"


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


def _t(uz: str, ru: str, lang: str) -> str:
    return recipes._pick({"uz": uz, "ru": ru}, lang)


def is_new_day(day: date) -> bool:
    """A new recipe opens on the site today."""
    return day >= recipes.START and (day - recipes.START).days % recipes.EVERY_DAYS == 0


def caption(recipe: dict, lang: str) -> str:
    """The recipe's start: title, intro, numbers, the first ingredients."""
    e = lambda s: html.escape(s, quote=False)  # noqa: E731
    L = recipes.labels(lang)
    pick = lambda entry: recipes._pick(entry, lang)  # noqa: E731
    meta = [L["minutes"].format(n=recipe["minutes"]), pick(recipe["servings"]),
            L["carbs"].format(n=recipe["per_serving"]["carbs"]),
            L["kcal"].format(n=recipe["per_serving"]["kcal"])]
    lines = [f"🍳 <b>{e(_t('Saytda yangi retsept', 'Новый рецепт на сайте', lang))}</b>", "",
             f"<b>{e(pick(recipe['title']))}</b>", "", e(pick(recipe["intro"])), "",
             "⏱ " + e(" · ".join(meta)) + f" <i>({e(L['per_serving'])})</i>", "",
             f"🧾 <b>{e(L['ingredients'])}:</b>"]
    ings = recipe["ingredients"]
    for i in ings[:TEASER_INGREDIENTS]:
        lines.append(f"• {e(pick(i['amount']))} — {e(pick(i['name']))}")
    if len(ings) > TEASER_INGREDIENTS:
        more = len(ings) - TEASER_INGREDIENTS
        lines.append(e(_t(f"… va yana {more} ta masalliq", f"… и ещё {more} ингредиента", lang)))
    lines += ["", e(_t("👇 Masalliqlar, qadamma-qadam tayyorlash va bir bosishda savatga — saytda",
                      "👇 Ингредиенты, пошаговое приготовление и всё в корзину одним нажатием — на сайте",
                      lang))]
    return "\n".join(lines)


def channel_keyboard(lang: str = CHANNEL_LANG) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=_t("📖 To'liq retseptni ko'rish", "📖 Смотреть полный рецепт", lang),
        url=f"https://t.me/{BOT_USERNAME}?start={PAYLOAD}")]])


def recipe_url(recipe: dict) -> str | None:
    if not WEBAPP_URL:
        return None
    return f"{WEBAPP_URL.rstrip('/')}/?recipe={recipe['slug']}"


def photo(recipe: dict) -> FSInputFile:
    return FSInputFile(PHOTO_DIR / f"{recipe['slug']}.jpg")


async def post_to_channel(bot: Bot, recipe: dict, chat_id: int | None = None) -> bool:
    """The announcement — to the channel, or to `chat_id` for a preview."""
    target = chat_id or REQUIRED_CHANNEL_ID
    if not target:
        return False
    try:
        await bot.send_photo(target, photo(recipe), caption=caption(recipe, CHANNEL_LANG),
                             reply_markup=channel_keyboard(), parse_mode=ParseMode.HTML)
        return True
    except Exception:
        logger.exception("Recipe channel post failed (%s)", recipe["slug"])
        return False


# ─────────────────────── the button's way into the Mini App ─────────────────

def parse_payload(payload: str | None) -> bool:
    return (payload or "").strip().lower() == PAYLOAD


async def open_from_link(bot: Bot, user_id: int, lang: str) -> bool:
    """Private answer to the channel button: photo + «Retseptni ochish» that
    opens the Mini App on today's recipe. False if there's no site to open."""
    recipe = recipes.schedule()[0]
    url = recipe_url(recipe)
    if not url:
        return False
    text = (f"🍳 <b>{html.escape(recipes._pick(recipe['title'], lang), quote=False)}</b>\n\n"
            + html.escape(_t("To'liq retsept, masalliqlar va bir bosishda savatga qo'shish — pastdagi tugmada.",
                             "Полный рецепт, ингредиенты и добавление в корзину одним нажатием — по кнопке ниже.",
                             lang), quote=False))
    markup = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=_t("📖 Retseptni ochish", "📖 Открыть рецепт", lang), web_app=WebAppInfo(url=url))]])
    try:
        await bot.send_photo(user_id, photo(recipe), caption=text, reply_markup=markup,
                             parse_mode=ParseMode.HTML)
        return True
    except Exception:
        logger.warning("Recipe deep link for %s failed", user_id, exc_info=True)
        return False


# ──────────────────────────────── schedule ──────────────────────────────────

async def _notify_admins(bot: Bot, text: str) -> None:
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception:
            pass


async def _tick(bot: Bot) -> None:
    now = _now_tk()
    if not POST_HOUR <= now.hour < LAST_HOUR or not is_new_day(now.date()):
        return
    recipe = recipes.schedule(now.date())[0]
    key = f"recipe-channel-{recipe['slug']}-{now.date().isoformat()}"
    if not await database.claim_release_notes(key):
        return
    if not await post_to_channel(bot, recipe):
        await database.release_release_notes(key)       # retried on the next tick
        return
    title = html.escape(recipe["title"]["uz"], quote=False)
    await _notify_admins(bot, f"📣 <b>Kanalga yangi retsept e'lon qilindi:</b> {title}\n"
                              "Tugma botga olib keladi va saytda retseptni ochadi. Ko'rish: /retsept_kanal")


async def scheduler_loop(bot: Bot) -> None:
    logger.info("Recipe channel scheduler started (%02d:00 on new-recipe days)", POST_HOUR)
    while True:
        try:
            await _tick(bot)
        except Exception:
            logger.exception("Recipe channel tick failed")
        await asyncio.sleep(CHECK_EVERY)


@router.message(Command("retsept_kanal"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_preview(message: Message):
    """The announcement of today's recipe, to the admin who asked only."""
    recipe = recipes.schedule()[0]
    day = recipes.today_tk()
    nxt = day
    while not is_new_day(nxt) or nxt <= day:
        nxt += timedelta(days=1)
    await message.answer(
        f"👀 Kanal e'loni shunday ko'rinadi (faqat sizga). Yangi retsept chiqqan kuni soat "
        f"{POST_HOUR}:00 da kanalga avtomatik chiqadi. Keyingisi: {nxt:%d.%m.%Y}.")
    await post_to_channel(message.bot, recipe, chat_id=message.from_user.id)
