"""
Lightweight interaction logging for the admin activity dashboard — tracks
how many distinct users touch the bot per day and which buttons/sections
get used the most. Logging is fire-and-forget (a background task) so it
never adds latency to the actual handler or breaks a request on DB hiccups.
"""
import asyncio
import logging
import re

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery

import database

logger = logging.getLogger(__name__)

# Curated labels for the top-level actions worth naming individually.
# Anything else falls back to its callback_data prefix (before the first
# ':') — still human-readable, and keeps thousands of distinct product/
# category IDs from exploding into one row each in the ranking.
_ACTION_LABELS = {
    "main_menu": "Bosh menyu",
    "catalog": "Katalog",
    "discounts": "Chegirmalar",
    "search": "Qidiruv",
    "cart": "Savat",
    "checkout": "Buyurtma rasmiylashtirish",
    "clear_cart": "Savatni tozalash",
    "my_orders": "Buyurtmalarim",
    "delivery_zones": "Yetkazib berish hududlari",
    "help": "Yordam (Qo'llanma)",
    "admin_panel": "Admin panel",
}

_PREFIX_LABELS = {
    "cat": "Kategoriya sahifasi",
    "product": "Mahsulot sahifasi",
    "page": "Mahsulotlar ro'yxati (sahifalash)",
    "reviews": "Sharhlar sahifasi",
    "write_review": "Sharh yozish",
    "rate": "Mahsulotni baholash",
    "review_order": "Buyurtmadan sharh qoldirish",
    "detail_inc": "Mahsulot +/- (kartadan)",
    "detail_dec": "Mahsulot +/- (kartadan)",
    "add_cart": "Savatga qo'shish",
    "cart_inc": "Savatda +/-",
    "cart_dec": "Savatda +/-",
    "remove_cart": "Savatdan o'chirish",
    "search_page": "Qidiruv (sahifalash)",
    "qty": "Miqdor tanlash",
    "custom_qty": "Miqdor tanlash",
    "pay": "To'lov usuli",
    "delivery": "Yetkazib berish usuli",
    "zone_info": "Yetkazib berish hududi",
    "lang": "Til tanlash",
    "seller": "Sotuvchi paneli",
    "admin": "Admin bo'limi",
    "order_act": "Buyurtma holatini o'zgartirish",
    "complaint": "Shikoyat",
    "msgclient": "Xaridorga xabar",
    "nps_score": "NPS so'rovnomasi",
    "mancat": "Qo'lda buyurtma: kategoriya tanlash",
    "manprod": "Qo'lda buyurtma: mahsulot tanlash",
    "manualdel": "Qo'lda buyurtma: yetkazib berish turi",
    "manualstatus": "Qo'lda buyurtma: holat tanlash",
    "manualconfirm": "Qo'lda buyurtma: tasdiqlash",
    "manualfinish": "Qo'lda buyurtma: yakunlash",
}

# Non-events: disabled/no-op buttons (page-number display, etc.) aren't
# real interactions worth ranking.
_IGNORED = {"noop"}


# Mini App actions for the same report (owner, 2026-10-18). Every opening
# preloads products, top sellers, the promo, the cart, the recipe list and the
# Keto rate, so those calls say nothing about the buyer — GET /api/categories
# (once per opening) stands for "opened the shop", the rest are things the
# buyer chose to do. Logged only when the request succeeded.
_SITE_ACTIONS = tuple((method, re.compile(pattern), label) for method, pattern, label in (
    ("GET", r"/api/categories", "Saytni ochdi"),
    ("GET", r"/api/product/\d+", "Mahsulot sahifasi"),
    ("GET", r"/api/set/\d+", "To'plam sahifasi"),
    ("POST", r"/api/product/\d+/reviews", "Sharh yozish"),
    ("GET", r"/api/search", "Qidiruv"),
    ("POST", r"/api/cart/add", "Savatga qo'shish"),
    ("POST", r"/api/cart/update", "Savatda +/-"),
    ("POST", r"/api/cart/remove", "Savatdan o'chirish"),
    ("POST", r"/api/cart/clear", "Savatni tozalash"),
    ("POST", r"/api/checkout", "Buyurtma berdi"),
    ("POST", r"/api/checkout/cheque", "Chek yubordi"),
    ("POST", r"/api/orders/\d+/cheque", "Chek yubordi"),
    ("POST", r"/api/checkout/pay-in-chat", "Chatda to'lash"),
    ("GET", r"/api/orders", "Buyurtmalarim"),
    ("POST", r"/api/orders/\d+/cancel", "Buyurtmani bekor qilish"),
    ("GET", r"/api/recipes/[^/]+", "Retsept ochildi"),
    ("POST", r"/api/recipes/[^/]+/cart", "Retseptdan savatga"),
    ("POST", r"/api/restock-wait", "Kelganda xabar bering"),
    ("POST", r"/api/site-feedback", "Saytga baho"),
    ("POST", r"/api/lang", "Til tanlash"),
))


def site_action(method: str, path: str) -> str | None:
    for m, pattern, label in _SITE_ACTIONS:
        if m == method and pattern.fullmatch(path):
            return label
    return None


def log_site(user_id: int, action: str) -> None:
    async def _go():
        try:
            await database.log_site_activity(user_id, action)
        except Exception:
            logger.exception("Failed to log site activity")
    asyncio.create_task(_go())


def _label_for_callback(data: str) -> str | None:
    if not data or data in _IGNORED:
        return None
    if data in _ACTION_LABELS:
        return _ACTION_LABELS[data]
    prefix = data.split(":", 1)[0]
    return _PREFIX_LABELS.get(prefix, prefix)


def _fire(user_id: int, kind: str, action: str) -> None:
    async def _go():
        try:
            await database.log_activity(user_id, kind, action)
        except Exception:
            logger.exception("Failed to log bot activity")
    asyncio.create_task(_go())


class ActivityMiddleware(BaseMiddleware):
    """Outer middleware registered for both message and callback_query
    updates — logs the interaction, then always runs the real handler."""

    async def __call__(self, handler, event: TelegramObject, data: dict):
        try:
            if isinstance(event, CallbackQuery) and event.from_user:
                label = _label_for_callback(event.data)
                if label:
                    _fire(event.from_user.id, "callback", label)
            elif isinstance(event, Message) and event.from_user and event.chat.type == "private":
                # Group chatter (link_guard.py) isn't engagement with the bot.
                _fire(event.from_user.id, "message", "message")
        except Exception:
            logger.exception("Activity middleware failed")
        return await handler(event, data)
