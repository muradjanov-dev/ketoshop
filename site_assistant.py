"""Saytdagi «Yordamchi» — AI suhbatdosh (egasi, 2026-11-15: "Saytga Yordamchi
nomli o'ng taraf pastda turadigan operator dumaloq belgisini qo'y u orqali ai
suhbatdosh ochilsin va bizni model u yerda ham ishlasin va buyurtmalarni endi
rasmlari bilan va barcha ma'lumotlari bilan chatda ko'rsatib bera olsin").

Botdagi AI sotuvchining (ai_sales) o'zi — bir xil qoidalar, katalog, mijoz
xotirasi va suhbat zanjiri; saytdan kelgan xabar shu odamning bot suhbatini
davom ettiradi. Farqlari:

  * Telegram'ga xos ikki vosita yo'q: buyurtma kartasi (botdagi tugmali
    checkout) va lokatsiya tugmasi. Saytda buyurtma savat → rasmiylashtirish
    orqali; AI savatga soladi va «🛒 Savatni ochish» ni taklif qiladi.
  * Vositalar natijasidan kartochkalar yig'iladi (WebMessage.web_cards):
    mahsulot (rasm, narx, «+ Savatga»), savat (rasmli qatorlar, jami) va
    buyurtma (raqam, holat, sana, rasmli mahsulotlar, jami, yetkazish, to'lov,
    manzil). Buyurtma faqat SHU odamniki — ai_sales.buyurtma_holati qoidasi.
  * Javob HTTP javobida qaytadi; suhbat adminlarning AI suhbatlari mavzusiga
    «🌐 Sayt» belgisi bilan tushadi (botdagidek).
  * Bir odamga bir vaqtda bitta so'rov; soatiga HOURLY_LIMIT tadan oshmaydi.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from types import SimpleNamespace

import ai_dialog
import ai_provider
import ai_sales
import ai_tone
import database
from locales import get_delivery_method_name, get_display_unit, get_order_status, localize_product_text

logger = logging.getLogger(__name__)

WEB_EXCLUDED_TOOLS = {"buyurtma_kartasi", "lokatsiya_tugmasi"}
WEB_TOOLS = [t for t in ai_sales.TOOLS if t.name not in WEB_EXCLUDED_TOOLS]
TEXT_MAX = 1000
HOURLY_LIMIT = 40
PRODUCT_CARDS_MAX = 4
ORDER_CARDS_MAX = 3

WEB_NOTE = ("[SAYT YORDAMCHISI: mijoz Keto shop saytidagi (Telegram Mini App) «Yordamchi» oynasidan "
            "yozyapti. Bu yerda buyurtma kartasi va lokatsiya tugmasi YO'Q: buyurtma uchun mahsulotni "
            "savatga sol va mijozga pastdagi «🛒 Savatni ochish» tugmasini bosib, saytda rasmiylashtirishini "
            "ayt. Siz eslagan mahsulot, savat va buyurtmalar javobing ostida rasmli kartochka bo'lib o'zi "
            "chiqadi — ularni matnda uzun sanab o'tirma, qisqa va tushunarli yoz.]")

_PAYMENT = {"cash": ("Naqd", "Наличными"), "online": ("Karta / onlayn", "Картой / онлайн"),
            "card": ("Karta orqali", "Картой")}

_locks: dict[int, asyncio.Lock] = {}
_recent: dict[int, list[float]] = {}


def _t(uz: str, ru: str, lang: str) -> str:
    if lang == "ru":
        return ru
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        return lat_to_cyr(uz)
    return uz


def who_line(user) -> str:
    """Kim yozyapti — guruhdagi hisobotda har bir sayt yozuvida (owner, 2026-11-21:
    "sayt: .... deb emas balki ism yoki id yoki username qisqasi kim yozayotganini
    ko'rsat"). Plain text: _mirror escapes it with the message."""
    name = getattr(user, "full_name", None) or "Ismsiz"
    username = getattr(user, "username", None)
    return f"{name}" + (f" @{username}" if username else "") + f" · id {user.id}"


async def _fill_who(user) -> None:
    """The site's Telegram profile can arrive without a name (the Android app's
    shop view, an empty profile) — take the name and @username we keep."""
    if getattr(user, "full_name", None) and getattr(user, "username", None):
        return
    try:
        row = await database.get_user(user.id) or {}
    except Exception:
        return
    if not getattr(user, "full_name", None) and row.get("full_name"):
        user.full_name = row["full_name"]
        user.first_name = user.first_name or row["full_name"].split()[0]
    if not getattr(user, "username", None) and row.get("username"):
        user.username = row["username"]


class WebMessage:
    """aiogram Message o'rnida — ai_sales._respond va vositalar ishlatadigan
    qismlari: from_user, chat, bot, answer(). web_cards — vositalar izi."""

    def __init__(self, bot, tg_user: dict, text: str):
        first, last = tg_user.get("first_name") or "", tg_user.get("last_name") or ""
        self.from_user = SimpleNamespace(
            id=int(tg_user["id"]), first_name=first, last_name=last,
            username=tg_user.get("username"), full_name=" ".join(p for p in (first, last) if p) or None,
            language_code=tg_user.get("language_code"), is_bot=False)
        self.chat = SimpleNamespace(id=int(tg_user["id"]), type="private")
        self.bot = bot
        self.text = text
        self.web_cards: list[tuple[str, dict, str]] = []
        self.answers: list[str] = []

    async def answer(self, text, **kwargs):
        self.answers.append(str(text))


def _limited(user_id: int, now: float | None = None) -> bool:
    now = time.time() if now is None else now
    stamps = [s for s in _recent.get(user_id, []) if now - s < 3600]
    if len(stamps) >= HOURLY_LIMIT:
        _recent[user_id] = stamps
        return True
    stamps.append(now)
    _recent[user_id] = stamps
    return False


def _photo(ref) -> str | None:
    if not ref:
        return None
    ref = str(ref).strip()
    return ref if ref.startswith(("/", "http://", "https://")) else f"/api/photo/{ref}"


def product_card(p: dict, lang: str) -> dict:
    discount = database.active_discount(p.get("discount_percent"), p.get("discount_until"))
    price = database.effective_price(float(p["price"]), discount, p.get("discount_until"))
    return {"type": "product", "id": p["id"],
            "name": localize_product_text(p["name"], p.get("name_ru"), lang),
            "price": price, "original_price": float(p["price"]), "discount_percent": discount or 0,
            "unit": get_display_unit(p.get("unit") or "", lang),
            "photo_url": _photo(p.get("photo_id")),
            "out_of_stock": float(p.get("quantity") or 0) <= 0}


async def cart_card(user_id: int, lang: str) -> dict | None:
    items = await database.get_cart(user_id)
    if not items:
        return {"type": "cart", "items": [], "total": 0}
    rows, total = [], 0.0
    for it in items:
        discount = database.active_discount(it.get("discount_percent"), it.get("discount_until"))
        unit_price = database.effective_price(it["price"], discount, it.get("discount_until"))
        line = unit_price * float(it["cart_quantity"])
        total += line
        rows.append({"name": localize_product_text(it["name"], it.get("name_ru"), lang),
                     "quantity": float(it["cart_quantity"]),
                     "unit": get_display_unit(it.get("unit") or "", lang),
                     "total": line, "photo_url": _photo(it.get("photo_id"))})
    return {"type": "cart", "items": rows, "total": total}


async def order_cards(user_id: int, lang: str, number: int | None) -> list[dict]:
    """Shu odamning buyurtmalari — buyurtma_holati bilan bir xil tanlov."""
    orders = await database.get_user_orders(user_id)
    if number:
        chosen = [o for o in orders if int(o.get("id") or 0) == number]
    else:
        open_orders = [o for o in orders if o.get("status") not in ("delivered", "cancelled")]
        chosen = open_orders[:ORDER_CARDS_MAX] or orders[:1]
    photos: dict[int, str | None] = {}
    out = []
    for o in chosen[:ORDER_CARDS_MAX]:
        raw = o.get("items")
        try:
            items = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except ValueError:
            items = []
        lines = []
        for it in items:
            pid = it.get("product_id")
            if pid and pid not in photos:
                try:
                    photos[pid] = _photo(((await database.get_product(int(pid))) or {}).get("photo_id"))
                except Exception:
                    photos[pid] = None
            qty = float(it.get("quantity") or 0)
            lines.append({"name": it.get("name"), "quantity": qty,
                          "unit": get_display_unit(it.get("unit") or "", lang),
                          "total": None if it.get("is_bonus") or it.get("is_gift")
                          else float(it.get("price") or 0) * qty,
                          "gift": bool(it.get("is_bonus") or it.get("is_gift")),
                          "photo_url": photos.get(pid)})
        pay = _PAYMENT.get(o.get("payment_method") or "", None)

        def iso(key):
            v = o.get(key)
            return v.isoformat() if hasattr(v, "isoformat") else None

        out.append({"type": "order", "id": o["id"], "status": o.get("status"),
                    "status_text": get_order_status(o.get("status") or "", lang),
                    "created_at": iso("created_at"), "confirmed_at": iso("confirmed_at"),
                    "shipped_at": iso("shipped_at"), "delivered_at": iso("delivered_at"),
                    "delivery": get_delivery_method_name(o.get("delivery_method"), lang),
                    "payment": (pay[1] if lang == "ru" else _t(pay[0], pay[1], lang)) if pay else None,
                    "address": o.get("address") if o.get("delivery_method") != "pickup" else None,
                    "total": float(o.get("total") or 0), "items": lines})
    return out


async def build_cards(user_id: int, lang: str, trace: list[tuple[str, dict, str]]) -> list[dict]:
    """Vositalar izidan kartochkalar: mahsulotlar, keyin savat, keyin buyurtmalar."""
    product_ids, cart, orders, order_number = [], False, False, None
    for name, args, output in trace:
        if output.startswith("Xato:"):
            continue
        if name in ("mahsulot_haqida", "savatga_qoshish", "retsept") and args.get("mahsulot_id"):
            pid = int(args["mahsulot_id"])
            if pid not in product_ids:
                product_ids.append(pid)
        if name in ("savatga_qoshish", "set_qoshish", "savatni_korish", "savatdan_ochirish"):
            cart = True
        if name == "buyurtma_holati":
            orders, order_number = True, int(args.get("buyurtma_raqami") or 0) or None
    cards = []
    for pid in product_ids[:PRODUCT_CARDS_MAX]:
        try:
            p = await database.get_product(pid)
        except Exception:
            p = None
        if p and p.get("is_active"):
            cards.append(product_card(p, lang))
    if cart:
        card = await cart_card(user_id, lang)
        if card:
            cards.append(card)
    if orders:
        cards += await order_cards(user_id, lang, order_number)
    return cards


def _offline(lang: str) -> str:
    return _t("Yordamchi hozir dam olyapti 🙂 Savolingizni Telegram botimiz @ketoshopbot ga yozing "
              "yoki qo'ng'iroq qiling: ", "Помощник сейчас отдыхает 🙂 Напишите в наш Telegram-бот "
              "@ketoshopbot или позвоните: ", lang) + ai_sales.SUPPORT_PHONES


async def ask(bot, tg_user: dict, text: str, lang: str) -> dict:
    """Bitta savol → {'reply': matn, 'cards': [...]} (yuborilmaydi — HTTP javobi)."""
    user_id = int(tg_user["id"])
    text = (text or "").strip()[:TEXT_MAX]
    if not text:
        return {"reply": "", "cards": []}
    if not await ai_sales._ready() or not await ai_sales._allowed(user_id):
        return {"reply": _offline(lang), "cards": [], "offline": True}
    if ai_sales._is_paused(user_id):
        return {"reply": _t("Hozir xodimimiz siz bilan Telegram botimizda gaplashyapti — javobni "
                            "o'sha yerda yozadi 🙂", "Сейчас с вами общается наш сотрудник в Telegram-боте — "
                            "ответ придёт туда 🙂", lang), "cards": []}
    if _limited(user_id):
        return {"reply": _t("Bir soatda juda ko'p savol bo'ldi — birozdan keyin yozing yoki Telegram "
                            "botimiz @ketoshopbot ga murojaat qiling 🙂", "Слишком много вопросов за час — "
                            "напишите чуть позже или в Telegram-бот @ketoshopbot 🙂", lang), "cards": []}
    message = WebMessage(bot, tg_user, text)
    await _fill_who(message.from_user)
    lock = _locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        try:
            reply = await ai_sales._respond(bot, message, f"{WEB_NOTE}\n\n{text}", tools=WEB_TOOLS)
        except Exception:
            logger.exception("site assistant turn failed for user %s", user_id)
            ai_provider.reset(ai_sales._session(user_id).setdefault("ai", {}))
            return {"reply": _t("Kechirasiz, hozir javob bera olmadik. Telegram botimiz @ketoshopbot ga "
                                "yozing yoki qo'ng'iroq qiling: ", "Извините, сейчас не получилось ответить. "
                                "Напишите в Telegram-бот @ketoshopbot или позвоните: ", lang)
                    + ai_sales.SUPPORT_PHONES, "cards": [], "error": True}
    session = ai_sales._sessions.get(user_id) or {}
    for key in ("card", "card_refresh", "keyboard"):      # botdagi karta/klaviatura — saytda yo'q
        session.pop(key, None)
    if reply:
        reply = ai_sales.polish_reply(reply, lang, customer_text=text)
        reply = ai_sales.naturalize(ai_sales.thank_politely(
            ai_sales.finish_address(reply, message.from_user, text, session)))
        reply = ai_tone.vary(reply, session.get("last_reply"))   # botdagidek — takror qolip yo'q
        reply = ai_tone.greet_back(reply, text)                   # salom berganga salom qaytadi
        midchat = await ai_sales.mid_conversation(user_id, session)
        reply = ai_tone.drop_midchat_greeting(reply, text, midchat)
        reply = ai_tone.greet_first(reply, lang, midchat is False)
        session["last_reply"] = reply
        await ai_dialog.record(user_id, "site", text, reply)     # bot va guruh ham ko'radi
        # "javdar uni kelmagan edi" (2026-11-26) — shikoyat adminlarga kartochka bo'lib boradi.
        await ai_sales._escalate_complaint(bot, message.from_user, "site", text, reply)
    try:
        cards = await build_cards(user_id, lang, message.web_cards)
    except Exception:
        logger.exception("site assistant cards failed for user %s", user_id)
        cards = []
    try:
        await ai_sales._mirror(bot, message, f"🌐 Sayt · {who_line(message.from_user)}: " + text, reply or "—")
    except Exception:
        logger.warning("site assistant mirror failed", exc_info=True)
    if user_id not in ai_sales.ADMIN_IDS and user_id not in database.LEADERBOARD_EXCLUDED_USER_IDS:
        try:
            import ai_stats
            await ai_stats.record_turn(user_id, "site", text)
        except Exception:
            pass
    return {"reply": reply or "", "cards": cards}
