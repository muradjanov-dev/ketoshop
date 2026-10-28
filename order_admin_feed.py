"""
Buyurtma lentasi — every admin hears about every order move (2026-10-01).

Owner's ask: "buyurtmani statusi o'zgarganda har bir adminga qaysi buyurtma,
qaysi mahsulotlari bor, mijoz, qaysi statusga o'tgani haqida update" and
"adminlar qo'lda yangi buyurtma kirgazganda barcha ma'lumotlari bilan kim
kirgazgani bilan barcha adminlarga".

One card format for both, sent to EVERY admin (including the one who made
the change — the owner asked for all of them, and it doubles as a receipt):

    🔄 Buyurtma #512 — holat o'zgardi
    ✅ Qabul qilindi → 🚚 Yo'lda

    👤 Ali Valiyev
    🔁 2-buyurtmasi (oldingi 1 tasi yetkazilgan)
    📱 +998 90 …
    💬 @ali
    📍 Toshkent, Chilonzor … · 🗺 Yandex xaritada ochish   (a link, not digits)
    📝 Chilonzor 9-kvartal, 12-uy (buyer's own words)
    🚚 Yetkazib berish: Ketoshop kuryer
    💵 To'lov: Naqd — ⏳ Yetkazib berishda to'lanadi

    🛒 Mahsulotlar:
    • Bodom uni 1000gr × 2 — 300 000 so'm
    💰 Jami: 300 000 so'm
    ✍️ Kim: Nodir (@nodir)

Call sites (every place an order's status is written):
  handlers/seller.py   — the admin's Telegram buttons
  courier_board.py     — the website's Kuryer board (both directions)
  handlers/cart.py     — buyer cancel in the bot, Telegram Payments confirm
  webapp_server.py     — buyer cancel in the Mini App
  handlers/admin.py    — manual and B2B orders typed in by an admin

Sends never raise and never block the caller: a dead admin chat or a slow
Telegram must not undo or delay the status change that already happened.
"""
import asyncio
import html
import json
import logging
import re

from aiogram import Bot
from aiogram.enums import ParseMode

import database
from config import ADMIN_IDS
from locales import get_order_status, line_unit

logger = logging.getLogger(__name__)

ITEMS_SHOWN = 25          # a giant B2B order still fits one message
_tasks: set[asyncio.Task] = set()

_T = {
    "status_title": {"uz": "🔄 <b>Buyurtma #{id} — holat o'zgardi</b>",
                     "ru": "🔄 <b>Заказ #{id} — статус изменён</b>"},
    "manual_title": {"uz": "📝 <b>Qo'lda yangi buyurtma #{id}</b>",
                     "ru": "📝 <b>Новый заказ вручную #{id}</b>"},
    "b2b_title": {"uz": "🏢 <b>Yangi ulgurji (B2B) buyurtma #{id}</b>",
                  "ru": "🏢 <b>Новый оптовый (B2B) заказ #{id}</b>"},
    "status_now": {"uz": "📌 Holati: {status}", "ru": "📌 Статус: {status}"},
    "items": {"uz": "🛒 <b>Mahsulotlar:</b>", "ru": "🛒 <b>Товары:</b>"},
    "more": {"uz": "… yana {n} ta", "ru": "… ещё {n}"},
    "bonus": {"uz": "🎁 bepul", "ru": "🎁 бесплатно"},
    "total": {"uz": "💰 Jami: <b>{sum} so'm</b>", "ru": "💰 Итого: <b>{sum} сум</b>"},
    "by": {"uz": "✍️ Kim: {who}", "ru": "✍️ Кто: {who}"},
    "map": {"uz": "🗺 <a href=\"{url}\">Yandex xaritada ochish</a>",
            "ru": "🗺 <a href=\"{url}\">Открыть в Яндекс Картах</a>"},
    "delivery": {"uz": "🚚 Yetkazib berish: {delivery}", "ru": "🚚 Доставка: {delivery}"},
}


# ───────────────────────── manzil (2026-10-13) ─────────────────────────
# Owner: "birinchisida manzil nomi bor, ikkinchisida yo'q, boshqalarida ham
# manzil nomi bo'lsin va yandex maps da havola ham bo'lsin". One set of
# address lines for every admin order card: the place, the buyer's own
# words (📝 address_note) and a Yandex Maps pin.

def map_url(order: dict) -> str | None:
    """Yandex Maps link to the buyer's pin — the same link the website's
    Kuryer board opens. None without a pin (pickup, hand-typed address)."""
    from courier_board import order_pin
    pin = order_pin(order)
    if not pin:
        return None
    lat, lng = pin
    return f"https://yandex.uz/maps/?pt={lng:.6f},{lat:.6f}&z=17&l=map"


def map_line(order: dict, lang: str) -> str:
    url = map_url(order)
    return _t("map", lang, url=html.escape(url, quote=True)) if url else ""


def plain_address(address) -> str:
    """The stored address without its leading 📍 — the cards put their own
    in front, which made "📍 📍 41.35…" on every location-shared order."""
    return str(address or "").strip().removeprefix("📍").strip()


# "41.018332, 71.676414" / "41.01, 71.67 — Chilonzor 9": the digits are for
# the map, not for reading (owner, 2026-10-14: "shuni o'rniga yandex xarita
# havolasi chiqara olamizmi?").
_COORD_PREFIX = re.compile(r"^\s*-?\d{1,2}\.\d+\s*,\s*-?\d{1,3}\.\d+\s*(?:[—–-]\s*)?")


def street(address) -> str:
    """The readable part of a stored address — coordinates dropped."""
    return _COORD_PREFIX.sub("", plain_address(address)).strip()


def address_html(order: dict, lang: str) -> str:
    """What follows "📍 " on an admin order card: the street and, in place of
    raw coordinates, a tappable Yandex Maps link. HTML-escaped; "" when the
    order has neither."""
    text = html.escape(street(order.get("address")), quote=False)[:200]
    link = map_line(order, lang)
    if text and link:
        return f"{text} · {link}"
    return text or link


def location_lines(order: dict, lang: str) -> list[str]:
    lines = []
    if where := address_html(order, lang):
        lines.append(f"📍 {where}")
    if note := str(order.get("address_note") or "").strip():
        lines.append(f"📝 {html.escape(note, quote=False)[:300]}")
    return lines


def is_typed_by_admin(order: dict) -> bool:
    """Manual/B2B orders carry the admin's own user_id — there is no buyer
    chat to link to and no buyer history to count."""
    return (order.get("source") or "") in ("manual", "b2b")


def customer_lines(order: dict, lang: str, *, history: str = "", contact: str = "") -> list[str]:
    """The buyer block of the new-order card, on every status card too
    (owner, 2026-10-13: "shu ma'lumotlar buyurtma statusi o'zgargan har bir
    xabarda chiqib turishi kerak"): who, which order of theirs, phones, chat,
    where, how it travels and how it is paid. `history` and `contact` are
    pre-rendered by the async caller (order_history_block, buyer_contact_link)."""
    from handlers.cart import payment_status_block
    from locales import get_delivery_method_name

    def esc(v) -> str:
        return html.escape(str(v), quote=False)

    lines = []
    if order.get("customer_name"):
        lines.append(f"👤 {esc(order['customer_name'])}")
    if history.strip():
        lines.append(history.strip())
    if order.get("phone"):
        lines.append(f"📱 {esc(order['phone'])}")
    if order.get("secondary_phone"):
        lines.append(f"📞 {esc(order['secondary_phone'])}")
    if contact:
        lines.append(f"💬 {contact}")
    lines.extend(location_lines(order, lang))
    if order.get("delivery_method"):
        lines.append(_t("delivery", lang, delivery=get_delivery_method_name(order["delivery_method"], lang)))
    # A cancelled order is not "paid on delivery" any more — no payment line.
    if order.get("payment_method") and order.get("status") != "cancelled":
        # address_note + cheque: an AI card order still waiting for its money
        # says "❗ TO'LANMAGAN", never "pay on delivery" (payment_state.py).
        lines.append(payment_status_block(order["payment_method"], order.get("status"), lang,
                                          order.get("address_note"), order.get("cheque_file_id")))
    return lines


def _lang_key(lang: str) -> str:
    return "ru" if lang == "ru" else "uz"


def _t(key: str, lang: str, **kw) -> str:
    # Transliterate the template only — names, phones and product titles go in
    # afterwards exactly as stored ("Nodir" must not turn into "Нодир").
    text = _T[key][_lang_key(lang)]
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        text = lat_to_cyr(text)
    return text.format(**kw)


def _som(value) -> str:
    try:
        return f"{int(round(float(value))):,}".replace(",", " ")
    except (TypeError, ValueError):
        return "—"


def _qty(value) -> str:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value or "")
    return str(int(v)) if v.is_integer() else f"{v:g}"


def _items(order: dict) -> list[dict]:
    raw = order.get("items")
    try:
        items = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except (TypeError, ValueError):
        items = []
    return [i for i in items if isinstance(i, dict)]


def actor(user) -> str:
    """'Nodir (@nodir)' for an aiogram User; plain text is passed through."""
    if user is None:
        return "—"
    if isinstance(user, str):
        return user
    name = getattr(user, "full_name", None) or str(getattr(user, "id", "—"))
    username = getattr(user, "username", None)
    return f"{name} (@{username})" if username else name


def build_card(order: dict, lang: str, *, title: str, by: str,
               old_status: str | None = None, new_status: str | None = None,
               history: str = "", contact: str = "") -> str:
    def esc(v: str) -> str:
        return html.escape(v, quote=False)

    lines = [_t(title, lang, id=order["id"])]

    if old_status and new_status:
        lines.append(f"{get_order_status(old_status, lang)} → <b>{get_order_status(new_status, lang)}</b>")
    elif order.get("status"):
        lines.append(_t("status_now", lang, status=get_order_status(order["status"], lang)))

    lines.append("")
    lines.extend(customer_lines(order, lang, history=history, contact=contact))

    items = _items(order)
    if items:
        lines.append("")
        lines.append(_t("items", lang))
        for it in items[:ITEMS_SHOWN]:
            name = esc(str(it.get("name") or "—"))
            unit = esc(line_unit(it, lang))
            row = f"• {name} × {_qty(it.get('quantity'))}"
            if unit:
                row += f" {unit}"
            if it.get("is_bonus"):
                row += f" — {_t('bonus', lang)}"
            elif it.get("price") is not None:
                try:
                    row += f" — {_som(float(it['price']) * float(it.get('quantity') or 0))}"
                except (TypeError, ValueError):
                    pass
            lines.append(row)
        if len(items) > ITEMS_SHOWN:
            lines.append(_t("more", lang, n=len(items) - ITEMS_SHOWN))

    lines.append("")
    lines.append(_t("total", lang, sum=_som(order.get("total"))))
    lines.append(_t("by", lang, who=esc(by or "—")))
    return "\n".join(lines)


async def _send_all(bot: Bot, order_id: int, **card_kw) -> None:
    try:
        order = await database.get_order(order_id)
        if not order:
            return
        from handlers.cart import buyer_contact_link, order_history_block
        contact = ""
        if not is_typed_by_admin(order) and order.get("user_id"):
            try:
                buyer = await database.get_user(order["user_id"])
            except Exception:
                buyer = None
            contact = buyer_contact_link(order["user_id"], (buyer or {}).get("username"),
                                         order.get("customer_name"))

        async def one(admin_id: int) -> None:
            try:
                lang = await database.get_user_language(admin_id)
                history = ("" if is_typed_by_admin(order)
                           else await order_history_block(order.get("user_id"), order_id, lang))
                await bot.send_message(admin_id, build_card(order, lang, history=history,
                                                            contact=contact, **card_kw),
                                       parse_mode=ParseMode.HTML,
                                       disable_web_page_preview=True)
            except Exception as exc:
                logger.warning("order feed #%s → admin %s failed: %s", order_id, admin_id, exc)

        await asyncio.gather(*(one(a) for a in list(ADMIN_IDS)), return_exceptions=True)
    except Exception:
        logger.exception("order feed #%s failed", order_id)


def _spawn(coro) -> None:
    """Fire and forget, keeping a strong reference until it finishes."""
    task = asyncio.get_running_loop().create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def status_changed(bot: Bot | None, order_id: int, old_status: str | None,
                   new_status: str, by) -> None:
    if bot is None or old_status == new_status:
        return
    _spawn(_send_all(bot, order_id, title="status_title", by=actor(by),
                     old_status=old_status, new_status=new_status))


def manual_created(bot: Bot | None, order_id: int, by, *, b2b: bool = False) -> None:
    if bot is None:
        return
    _spawn(_send_all(bot, order_id, title="b2b_title" if b2b else "manual_title", by=actor(by)))
