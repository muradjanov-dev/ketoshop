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
    👤 Ali Valiyev · +998 90 …
    📍 Toshkent, Chilonzor …
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

from aiogram import Bot
from aiogram.enums import ParseMode

import database
from config import ADMIN_IDS
from locales import get_order_status

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
}


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
               old_status: str | None = None, new_status: str | None = None) -> str:
    def esc(v: str) -> str:
        return html.escape(v, quote=False)

    lines = [_t(title, lang, id=order["id"])]

    if old_status and new_status:
        lines.append(f"{get_order_status(old_status, lang)} → <b>{get_order_status(new_status, lang)}</b>")
    elif order.get("status"):
        lines.append(_t("status_now", lang, status=get_order_status(order["status"], lang)))

    who = " · ".join(esc(str(v)) for v in (order.get("customer_name"), order.get("phone")) if v)
    if who:
        lines.append(f"👤 {who}")
    if order.get("address"):
        lines.append(f"📍 {esc(str(order['address']))[:200]}")

    items = _items(order)
    if items:
        lines.append("")
        lines.append(_t("items", lang))
        for it in items[:ITEMS_SHOWN]:
            name = esc(str(it.get("name") or "—"))
            unit = esc(str(it.get("unit") or ""))
            row = f"• {name} × {_qty(it.get('quantity'))}"
            if unit and unit not in ("dona", "piece"):
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

        async def one(admin_id: int) -> None:
            try:
                lang = await database.get_user_language(admin_id)
                await bot.send_message(admin_id, build_card(order, lang, **card_kw),
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
