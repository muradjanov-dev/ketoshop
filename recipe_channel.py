"""
Saytdagi yangi retsept — kanalga e'lon (owner, 2026-10-17: "har safar saytga
yangi retsept chiqqanda uni rasmi va retseptni boshlanishi bilan kanalga ham
e'lon qilsak va to'liq retseptni ko'rishni bosgach saytga olib o'tadigan inline
tugma qoldirsak").

On the day a new recipe opens on the site (recipes.schedule: every EVERY_DAYS
from START), at POST_HOUR the channel gets the recipe's photo with its start —
title, the intro, time / servings / carbs, the first ingredients — and a big
«👉 TO'LIQ RETSEPTNI SAYTIMIZ ORQALI KO'RING 👈» link in the text itself.

No inline button (owner, same day): a button hides the post's comments and is
lost when the post is forwarded; a link in the text survives both. The title
is the same link.

The link must open the recipe in one tap, and the site only works inside
Telegram (its API wants initData). So when the bot has a main Mini App
(BotFather → Bot Settings → Configure Mini App) the link is
t.me/<bot>?startapp=recipe-<slug>, which opens the Mini App straight on that
recipe. Without one it falls back to t.me/<bot>?start=retsept_<slug>: the bot
answers in private with the photo and a web_app button — one more tap. Either
way the link names the recipe, so a post forwarded days later still opens the
recipe it shows (recipes.find: published ones only).

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
START_APP_PREFIX = "recipe-"
TEASER_INGREDIENTS = 4
PHOTO_DIR = Path(__file__).parent / "webapp" / "recipes"


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


def _t(uz: str, ru: str, lang: str) -> str:
    return recipes._pick({"uz": uz, "ru": ru}, lang)


def is_new_day(day: date) -> bool:
    """A new recipe opens on the site today."""
    return day >= recipes.START and (day - recipes.START).days % recipes.EVERY_DAYS == 0


def caption(recipe: dict, lang: str, link: str) -> str:
    """The recipe's start: title, intro, numbers, the first ingredients — and
    the link to the whole recipe, twice: on the title and as a big line."""
    e = lambda s: html.escape(s, quote=False)  # noqa: E731
    href = html.escape(link, quote=True)
    L = recipes.labels(lang)
    pick = lambda entry: recipes._pick(entry, lang)  # noqa: E731
    meta = [L["minutes"].format(n=recipe["minutes"]), pick(recipe["servings"]),
            L["carbs"].format(n=recipe["per_serving"]["carbs"]),
            L["kcal"].format(n=recipe["per_serving"]["kcal"])]
    lines = [f"🍳 <b>{e(_t('Saytda yangi retsept', 'Новый рецепт на сайте', lang))}</b>", "",
             f'<b><a href="{href}">{e(pick(recipe["title"]))}</a></b>', "", e(pick(recipe["intro"])), "",
             "⏱ " + e(" · ".join(meta)) + f" <i>({e(L['per_serving'])})</i>", "",
             f"🧾 <b>{e(L['ingredients'])}:</b>"]
    ings = recipe["ingredients"]
    for i in ings[:TEASER_INGREDIENTS]:
        lines.append(f"• {e(pick(i['amount']))} — {e(pick(i['name']))}")
    if len(ings) > TEASER_INGREDIENTS:
        more = len(ings) - TEASER_INGREDIENTS
        lines.append(e(_t(f"… va yana {more} ta masalliq", f"… и ещё {more} ингредиента", lang)))
    cta = e(_t("TO'LIQ RETSEPTNI SAYTIMIZ ORQALI KO'RING", "СМОТРИТЕ ПОЛНЫЙ РЕЦЕПТ НА НАШЕМ САЙТЕ", lang))
    lines += ["", "━━━━━━━━━━━━━━━━",
              f'👉 <b><a href="{href}">{cta}</a></b> 👈',
              "━━━━━━━━━━━━━━━━",
              e(_t("Masalliqlar, qadamma-qadam tayyorlash va bir bosishda savatga qo'shish — hammasi saytimizda.",
                   "Ингредиенты, пошаговое приготовление и всё в корзину одним нажатием — на нашем сайте.",
                   lang))]
    return "\n".join(lines)


def full_recipe_link(recipe: dict, one_tap: bool) -> str:
    """t.me link to this recipe: straight into the Mini App when the bot has a
    main Mini App, else via the bot's private answer."""
    if one_tap:
        return f"https://t.me/{BOT_USERNAME}?startapp={START_APP_PREFIX}{recipe['slug']}"
    return f"https://t.me/{BOT_USERNAME}?start={PAYLOAD}_{recipe['slug']}"


async def main_app_enabled(bot: Bot) -> bool:
    """Does the bot have a main Mini App (needed for ?startapp=)? get_me, not
    the cached bot.me(), so switching it on in BotFather counts without a
    restart."""
    try:
        me = await bot.get_me()
    except Exception:
        logger.warning("get_me failed; recipe link falls back to the bot", exc_info=True)
        return False
    return bool(getattr(me, "has_main_web_app", False))


def recipe_url(recipe: dict) -> str | None:
    if not WEBAPP_URL:
        return None
    return f"{WEBAPP_URL.rstrip('/')}/?recipe={recipe['slug']}"


def photo(recipe: dict) -> FSInputFile:
    return FSInputFile(PHOTO_DIR / f"{recipe['slug']}.jpg")


async def post_to_channel(bot: Bot, recipe: dict, chat_id: int | None = None) -> bool:
    """The announcement — to the channel, or to `chat_id` for a preview. No
    reply_markup on purpose: comments stay open (see the module note)."""
    target = chat_id or REQUIRED_CHANNEL_ID
    if not target:
        return False
    link = full_recipe_link(recipe, await main_app_enabled(bot))
    try:
        await bot.send_photo(target, photo(recipe), caption=caption(recipe, CHANNEL_LANG, link),
                             parse_mode=ParseMode.HTML)
        return True
    except Exception:
        logger.exception("Recipe channel post failed (%s)", recipe["slug"])
        return False


# ─────────────────────── the button's way into the Mini App ─────────────────

def parse_payload(payload: str | None) -> str | None:
    """?start=retsept_<slug> → that slug; bare ?start=retsept (the first
    posts' button) → today's. None when the payload isn't ours."""
    value = (payload or "").strip().lower()
    if value == PAYLOAD:
        return recipes.schedule()[0]["slug"]
    if value.startswith(PAYLOAD + "_") and len(value) > len(PAYLOAD) + 1:
        return value[len(PAYLOAD) + 1:]
    return None


async def open_from_link(bot: Bot, user_id: int, lang: str, slug: str | None = None) -> bool:
    """Private answer to the channel link: photo + «Retseptni ochish» that
    opens the Mini App on that recipe (today's if it isn't published yet or
    is unknown). False if there's no site to open."""
    recipe = (recipes.find(slug) if slug else None) or recipes.schedule()[0]
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
                              "Havola matnning ichida, tugma yo'q — izohlar ochiq. Ko'rish: /retsept_kanal")


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
    if await main_app_enabled(message.bot):
        how = "✅ Havola bir bosishda saytni shu retseptda ochadi."
    else:
        how = ("⚠️ Havola hozir avval botni ochadi, sayt tugmasi u yerda (2 bosish). Bir bosishda "
               "ochilishi uchun: @BotFather → /mybots → @" + BOT_USERNAME + " → Bot Settings → "
               "Configure Mini App → Enable Mini App, manzil: " + (WEBAPP_URL or "sayt manzili") + ". "
               "Yoqilgach, keyingi post o'zi bir bosishli havola bilan chiqadi.")
    await message.answer(
        f"👀 Kanal e'loni shunday ko'rinadi (faqat sizga). Yangi retsept chiqqan kuni soat "
        f"{POST_HOUR}:00 da kanalga avtomatik chiqadi. Keyingisi: {nxt:%d.%m.%Y}.\n\n{how}")
    await post_to_channel(message.bot, recipe, chat_id=message.from_user.id)
