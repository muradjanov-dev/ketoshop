"""
"Bepul xarid qilish" — mijozdan mijozga referal (2026-10-02).

Uch qism:
  - Start bonusi: har bir yangi foydalanuvchi birinchi /start da 10 Keto
    oladi. Referal havola orqali kelganlar uni award_referral'dan
    (referral_contest.py) oladi, qolganlarga grant_welcome_bonus beradi.
  - Referal keshbegi: taklif qilingan odamning birinchi TO'LANGAN (ya'ni
    yetkazilgan) xaridining 3% i taklif qiluvchiga Keto bo'lib tushadi.
    Asos — mahsulotlar summasi, yetkazib berish va Keto bilan to'langan
    qismsiz. Birinchi buyurtma bekor bo'lsa, keyingi yetkazilgani hisoblanadi.
    Faqat dastur ishga tushgandan keyingi takliflar (referrals.cashback_eligible).
  - Asosiy menyudagi "🎁 Bepul xarid qilish" ekrani: shaxsiy havola, ulashish
    tugmasi, Keto balansi va taklif statistikasi.

Havola formati referral_contest.py dagi bilan bir xil (?start=ref<id>), shuning
uchun eski musobaqa havolalari ham shu tizimda ishlayveradi.
"""
import json
import logging
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

import database
from config import ADMIN_IDS
from locales import get_text
from referral_contest import referral_link

logger = logging.getLogger(__name__)
router = Router()

WELCOME_KETO = 10
CASHBACK_PERCENT = 3


def _fmt(n) -> str:
    return f"{int(n or 0):,}".replace(",", " ")


def _is_eligible_order(order: dict) -> bool:
    """bloggers._is_eligible_order bilan bir xil: admin/ichki akkauntlar va
    admin qo'lda kiritgan manual/B2B buyurtmalar keshbek bermaydi."""
    user_id = order.get("user_id")
    if user_id in ADMIN_IDS or user_id in database.LEADERBOARD_EXCLUDED_USER_IDS:
        return False
    return (order.get("source") or "bot") not in ("manual", "b2b")


def cashback_base(order: dict) -> float:
    """Mahsulotlar summasi (yetkazib berish narxisiz, gamification bilan bir
    xil) minus Keto bilan to'langan qism."""
    raw = order.get("items")
    try:
        items = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except Exception:
        items = []
    subtotal = sum(float(it.get("price") or 0) * float(it.get("quantity") or 0) for it in items)
    return max(0.0, subtotal - float(order.get("keto_redeemed") or 0))


async def grant_welcome_bonus(bot: Bot, user_id: int) -> None:
    """Yangi foydalanuvchiga 10 Keto. Referal orqali kelib, bonusni allaqachon
    olgan bo'lsa — hech narsa qilmaydi. Hech qachon xato tashlamaydi."""
    try:
        if not await database.credit_welcome_keto(user_id, WELCOME_KETO):
            return
        lang = await database.get_user_language(user_id)
        await bot.send_message(
            user_id, get_text("welcome_keto_bonus", lang, amount=WELCOME_KETO),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        logger.exception("grant_welcome_bonus failed for user %s", user_id)


async def award_order_cashback(order: dict, bot: Bot) -> None:
    """Buyurtma 'delivered' bo'lgandan keyin chaqiriladi (bloger keshbegi
    bilan bir joyda). Idempotent: har bir taklif qilingan odam uchun faqat
    bir marta to'lanadi. Hech qachon xato tashlamaydi."""
    try:
        if not _is_eligible_order(order):
            return
        amount = int(round(cashback_base(order) * CASHBACK_PERCENT / 100))
        if amount <= 0:
            return  # to'liq Keto bilan to'langan — keyingi xarid hisoblanadi
        buyer_id = order["user_id"]
        referrer_id = await database.claim_referral_cashback(buyer_id, order["id"], amount)
        if not referrer_id:
            return
        logger.info("Referral cashback %s Keto -> %s (buyer %s, order %s)",
                    amount, referrer_id, buyer_id, order["id"])

        referrer = await database.get_user(referrer_id) or {}
        buyer = await database.get_user(buyer_id) or {}
        lang = referrer.get("language") or "uz"
        who = (buyer.get("full_name") or "").split()
        who = who[0] if who else (f"@{buyer['username']}" if buyer.get("username") else "—")
        try:
            await bot.send_message(
                referrer_id,
                get_text("referral_cashback_earned", lang, name=who, amount=_fmt(amount),
                         percent=CASHBACK_PERCENT, balance=_fmt(referrer.get("keto_balance"))),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text=get_text("btn_free_buy", lang), callback_data="free_buy"),
                ]]),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            logger.warning("Referral cashback notice failed for %s", referrer_id, exc_info=True)
    except Exception:
        logger.exception("award_order_cashback failed for order %s", order.get("id"))


def _share_url(user_id: int, lang: str) -> str:
    link = referral_link(user_id)
    text = get_text("free_buy_share_text", lang)
    return f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(text, safe='')}"


@router.callback_query(F.data == "free_buy")
async def show_free_buy(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = await database.get_user_language(user_id)
    user = await database.get_user(user_id) or {}
    summary = await database.get_user_referral_summary(user_id)
    text = get_text(
        "free_buy_screen", lang,
        percent=CASHBACK_PERCENT, link=referral_link(user_id),
        balance=_fmt(user.get("keto_balance")),
        invited=summary["invited"], bought=summary["bought"], earned=_fmt(summary["cashback"]),
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_free_buy_share", lang), url=_share_url(user_id, lang))],
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="main_menu")],
    ])
    await callback.answer()
    if callback.message.photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML",
                                      disable_web_page_preview=True)
        return
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML",
                                         disable_web_page_preview=True)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML",
                                      disable_web_page_preview=True)
