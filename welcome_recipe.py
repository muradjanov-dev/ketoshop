"""
Yangi foydalanuvchiga bugungi retsept — rasmi bilan, to'liq (egasi, 2026-10-14):

    "xar bir yangi foydalanuvchiga saytdagi faol bo'lib turgan retseptni
    to'liqligicha ularni ushlab qolish uchun rasmi bilan yuborish kerak
    tezda qo'shilishi bilan video qo'llanmadan keyin"

The welcome sequence after the language pick (handlers/start.set_language):
100 Keto ceremony → how-to-order video → this recipe.

  * Only brand-new users: a pending row is written at registration
    (handlers/start._process_new_user — /start, the channel gate, or a
    Mini App-first cart add) and taken with one DELETE when the language is
    picked, so a returning user switching language never gets it, and a
    double tap never sends it twice.
  * The recipe is the one the Mini App shows today (recipes.schedule), in
    the buyer's language: a photo with the title, intro, time and macros,
    then the full ingredient list, every step, the tip and when the next
    recipe comes out. The AI-photo note is part of it (owner, 2026-10-08).
  * "🛒 Barcha masalliqlarni savatga" puts one pack of every in-stock
    Ketoshop ingredient in the cart (recipes.add_all_to_cart — the same as
    the site), "🌐 Saytda ochish" opens the Mini App.
"""
import html
import logging
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.types import (
    CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo,
)

import database
import recipes

logger = logging.getLogger(__name__)
router = Router(name="welcome_recipe")

PHOTO_DIR = Path(__file__).parent / "webapp" / "recipes"
CAPTION_MAX = 1024
CALLBACK = "wrcp:"

_table_ready = False
_photo_ids: dict[str, str] = {}        # slug → Telegram file_id, so a photo is uploaded once


def _t(uz: str, ru: str, lang: str) -> str:
    return recipes._pick({"uz": uz, "ru": ru}, lang)


def _esc(text: str) -> str:
    return html.escape(text or "", quote=False)


def _num(v) -> str:
    v = float(v)
    return str(int(v)) if v.is_integer() else f"{v:g}"


# ───────────────────────────── pending ─────────────────────────────

async def _ensure_table(conn) -> None:
    global _table_ready
    if _table_ready:
        return
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS welcome_recipe_pending (
            user_id BIGINT PRIMARY KEY,
            created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
        )
    """)
    _table_ready = True


async def mark_pending(user_id: int) -> None:
    """At registration: this brand-new user gets today's recipe once they
    pick a language. Never raises — registration must not fail on it."""
    try:
        async with database.pool.acquire() as conn:
            await _ensure_table(conn)
            await conn.execute(
                "INSERT INTO welcome_recipe_pending (user_id) VALUES ($1) ON CONFLICT DO NOTHING", user_id)
    except Exception:
        logger.warning("welcome recipe mark_pending(%s) failed", user_id, exc_info=True)


async def _pop_pending(user_id: int) -> bool:
    async with database.pool.acquire() as conn:
        await _ensure_table(conn)
        return await conn.fetchval(
            "DELETE FROM welcome_recipe_pending WHERE user_id = $1 RETURNING user_id", user_id) is not None


# ───────────────────────────── message ─────────────────────────────

def caption_text(recipe: dict, lang: str) -> str:
    """The photo's caption: what it is, why it's worth making, time, macros."""
    L = recipes.labels(lang)
    title = recipes._pick(recipe["title"], lang)
    intro = recipes._pick(recipe["intro"], lang)
    macros = recipe.get("per_serving") or {}
    facts = [f"⏱ {L['minutes'].replace('{n}', str(recipe['minutes']))}",
             f"🍽 {recipes._pick(recipe['servings'], lang)}"]
    lines = [
        _t("🍳 Sizga bugungi keto retseptimiz — Ketoshop mahsulotlari bilan uyda oson tayyorlanadi:",
           "🍳 Наш сегодняшний кето-рецепт — легко готовится дома из продуктов Ketoshop:", lang),
        "",
        f"<b>{_esc(title)}</b>",
        "",
        _esc(intro),
        "",
        " · ".join(_esc(f) for f in facts),
    ]
    if macros.get("carbs") is not None or macros.get("kcal") is not None:
        parts = []
        if macros.get("carbs") is not None:
            parts.append(L["carbs"].replace("{n}", _num(macros["carbs"])))
        if macros.get("kcal") is not None:
            parts.append(L["kcal"].replace("{n}", _num(macros["kcal"])))
        lines.append(f"📊 {_esc(L['per_serving'])}: {_esc(' · '.join(parts))}")
    lines += ["", f"<i>{_esc(recipes._pick(recipes.AI_NOTE, lang))}</i>"]
    text = "\n".join(lines)
    if len(text) > CAPTION_MAX:                      # the intro gives way, nothing else
        over = len(text) - CAPTION_MAX + 1
        text = text.replace(_esc(intro), _esc(intro)[: max(0, len(_esc(intro)) - over)].rstrip() + "…", 1)
    return text


def recipe_text(recipe: dict, lang: str) -> str:
    """Everything else, in full: ingredients, every step, the tip, the next one."""
    L = recipes.labels(lang)
    lines = [f"🛒 <b>{_esc(L['ingredients'])}</b>"]
    for item in recipe["ingredients"]:
        row = f"• {_esc(recipes._pick(item['amount'], lang))} — {_esc(recipes._pick(item['name'], lang))}"
        if not item.get("match"):
            row += f" <i>({_esc(L['from_home'])})</i>"
        lines.append(row)
    lines += ["", f"👩‍🍳 <b>{_esc(L['steps'])}</b>"]
    lines += [f"{i}. {_esc(recipes._pick(step, lang))}" for i, step in enumerate(recipe["steps"], 1)]
    if recipe.get("tip"):
        lines += ["", f"<b>{_esc(L['tip'])}:</b> {_esc(recipes._pick(recipe['tip'], lang))}"]
    _current, _earlier, next_at = recipes.schedule()
    lines += ["", f"🗓 {_esc(L['next'].replace('{date}', next_at.strftime('%d.%m')))}"]
    return "\n".join(lines)


def keyboard(recipe: dict, lang: str) -> InlineKeyboardMarkup:
    from config import WEBAPP_URL
    L = recipes.labels(lang)
    rows = [[InlineKeyboardButton(text=L["add_all"], callback_data=f"{CALLBACK}{recipe['slug']}")]]
    if WEBAPP_URL:
        rows.append([InlineKeyboardButton(text=_t("🌐 Saytda ochish", "🌐 Открыть на сайте", lang),
                                          web_app=WebAppInfo(url=WEBAPP_URL))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_recipe(bot: Bot, user_id: int, lang: str, recipe: dict | None = None) -> None:
    recipe = recipe or recipes.schedule()[0]
    caption = caption_text(recipe, lang)
    slug = recipe["slug"]
    photo = _photo_ids.get(slug) or (PHOTO_DIR / f"{slug}.jpg")
    if isinstance(photo, Path) and not photo.exists():
        # No picture on disk — the text still goes, with the caption on top.
        await bot.send_message(user_id, caption + "\n\n" + recipe_text(recipe, lang),
                               parse_mode=ParseMode.HTML, reply_markup=keyboard(recipe, lang))
        return
    sent = await bot.send_photo(user_id, FSInputFile(photo) if isinstance(photo, Path) else photo,
                                caption=caption, parse_mode=ParseMode.HTML)
    try:
        _photo_ids[slug] = sent.photo[-1].file_id
    except Exception:
        pass
    await bot.send_message(user_id, recipe_text(recipe, lang), parse_mode=ParseMode.HTML,
                           reply_markup=keyboard(recipe, lang), disable_web_page_preview=True)


async def maybe_send(bot: Bot, user_id: int, lang: str) -> bool:
    """Right after the onboarding video: today's recipe for a brand-new user,
    once. Never raises — onboarding must not break on a recipe."""
    try:
        if not await _pop_pending(user_id):
            return False
        await send_recipe(bot, user_id, lang)
        return True
    except Exception:
        logger.exception("welcome recipe for %s failed", user_id)
        return False


# ───────────────────────────── "all to cart" ─────────────────────────────

@router.callback_query(F.data.startswith(CALLBACK))
async def add_all(callback: CallbackQuery):
    lang = await database.get_user_language(callback.from_user.id)
    L = recipes.labels(lang)
    recipe = recipes.find(callback.data[len(CALLBACK):])
    if not recipe:
        await callback.answer("—")
        return
    res = await recipes.add_all_to_cart(callback.from_user.id, recipe, lang)
    lines = []
    if res["added"]:
        lines.append(L["added"].replace("{n}", str(len(res["added"]))))
    elif res["already"]:
        lines.append(L["already"])
    if res["missing"]:
        lines.append(L["missing"].replace("{names}", ", ".join(res["missing"])))
    from locales import get_text
    await callback.message.answer(
        _esc("\n".join(lines) or L["already"]), parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_text("btn_checkout", lang), callback_data="checkout")],
            [InlineKeyboardButton(text=get_text("btn_view_cart", lang), callback_data="cart")],
        ]))
    await callback.answer()
