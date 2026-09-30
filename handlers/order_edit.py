"""
Admin order editor (2026-09-30) — owner's ask: "mijozdan tushgan buyurtmani
adminlar o'zgartira olsin: sonini, yangi narsa qo'shish yoki olib tashlash".

Flow, from the admin's order card (✏️ Tarkibni o'zgartirish):
    oedit:{id}   open the editor — a draft copy of the order's lines lives in
                 FSM data; nothing touches the DB until 💾 Saqlash.
    oe:inc/dec/rm/qty:{i}   change line i of the draft
    oe:add → type a name → oe:pick:{product_id}   add a catalogue product
    oe:save      database.admin_update_order_items — stock moves by the
                 difference, total moves by the goods difference (delivery fee
                 and spent Keto stay as charged), stale drafts are refused.
    oe:notify:{id}   optional: send the buyer the updated list.

Aksiya bonus / gift lines are shown but never edited: their eligibility and
expense booking are computed elsewhere (promotions.py, gift_campaign.py).
Quantities are whole numbers, like the buyer's cart.
"""
import html
import json
import logging

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import database
from config import ADMIN_IDS
from locales import get_item_unit, get_order_status, get_text, localize_product_text

logger = logging.getLogger(__name__)
router = Router()


class OrderEditStates(StatesGroup):
    editing = State()
    waiting_qty = State()
    waiting_search = State()


def _money(v: float) -> str:
    return f"{int(round(v)):,}".replace(",", " ")


def _qty(v) -> str:
    v = float(v or 0)
    return str(int(v)) if v.is_integer() else str(v)


def _is_fixed(item: dict) -> bool:
    """Bonus/gift lines ride along untouched."""
    return database.order_line_key(item) is None


def _items_of(order: dict) -> list[dict]:
    raw = order.get("items")
    return json.loads(raw) if isinstance(raw, str) else (raw or [])


async def _render(target, state: FSMContext, *, edit: bool):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    order_id = data["oe_order_id"]
    draft = data["oe_items"]
    orig = data["oe_orig"]

    lines, fixed = [], []
    for it in draft:
        row = f"• {html.escape(it.get('name') or '?')} — {_qty(it.get('quantity'))} × {_money(float(it.get('price') or 0))}"
        (fixed if _is_fixed(it) else lines).append(row)

    goods = database.order_goods_total(draft)
    old_goods = database.order_goods_total(orig)
    old_total = float(data["oe_old_total"])
    text = get_text("oe_title", lang, order_id=order_id) + "\n\n" + "\n".join(lines)
    if fixed:
        text += "\n\n" + get_text("oe_bonus_note", lang) + "\n" + "\n".join(fixed)
    text += "\n\n" + get_text(
        "oe_totals", lang,
        goods=_money(goods), old_goods=_money(old_goods),
        total=_money(old_total - old_goods + goods), old_total=_money(old_total),
    )

    rows = []
    for i, it in enumerate(draft):
        if _is_fixed(it):
            continue
        name = (it.get("name") or "?")[:22]
        rows.append([
            InlineKeyboardButton(text="➖", callback_data=f"oe:dec:{i}"),
            InlineKeyboardButton(text=f"{name} × {_qty(it.get('quantity'))}", callback_data=f"oe:qty:{i}"),
            InlineKeyboardButton(text="➕", callback_data=f"oe:inc:{i}"),
            InlineKeyboardButton(text="🗑", callback_data=f"oe:rm:{i}"),
        ])
    rows.append([InlineKeyboardButton(text=get_text("oe_btn_add", lang), callback_data="oe:add")])
    rows.append([
        InlineKeyboardButton(text=get_text("oe_btn_save", lang), callback_data="oe:save"),
        InlineKeyboardButton(text=get_text("oe_btn_cancel", lang), callback_data="oe:cancel"),
    ])
    kb = InlineKeyboardMarkup(inline_keyboard=rows)

    if edit and isinstance(target, CallbackQuery):
        msg = target.message
        # The card this was opened from is text, but never bare-edit a
        # message that could be a photo (see the order cheque below cards).
        if not msg.photo and not msg.document:
            try:
                await msg.edit_text(text, reply_markup=kb, parse_mode="HTML")
                return
            except Exception:
                pass
        await msg.answer(text, reply_markup=kb, parse_mode="HTML")
    else:
        msg = target.message if isinstance(target, CallbackQuery) else target
        await msg.answer(text, reply_markup=kb, parse_mode="HTML")


async def _draft_or_alert(callback: CallbackQuery, state: FSMContext) -> dict | None:
    data = await state.get_data()
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌", show_alert=True)
        return None
    if "oe_items" not in data:
        lang = await database.get_user_language(callback.from_user.id)
        await callback.answer(get_text("oe_session_lost", lang), show_alert=True)
        return None
    return data


@router.callback_query(F.data.startswith("oedit:"))
async def open_editor(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌", show_alert=True)
        return
    order_id = int(callback.data.split(":")[1])
    lang = await database.get_user_language(callback.from_user.id)
    order = await database.get_order(order_id)
    if not order:
        await callback.answer("❌", show_alert=True)
        return
    if (order.get("source") or "bot") in ("manual", "b2b"):
        # Offline / wholesale rows are keyed in by admins with weights, not
        # buyer carts — this editor is for customers' own orders only.
        await callback.answer("❌", show_alert=True)
        return
    if order["status"] not in database.ORDER_EDITABLE_STATUSES:
        await callback.answer(
            get_text("oe_not_editable", lang, status=get_order_status(order["status"], lang)),
            show_alert=True)
        return
    items = _items_of(order)
    await state.clear()
    await state.set_state(OrderEditStates.editing)
    await state.update_data(
        lang=lang, oe_order_id=order_id, oe_orig=items,
        oe_items=[dict(it) for it in items], oe_old_total=float(order["total"] or 0),
    )
    await _render(callback, state, edit=True)
    await callback.answer()


@router.callback_query(F.data.regexp(r"^oe:(inc|dec|rm):\d+$"))
async def change_line(callback: CallbackQuery, state: FSMContext):
    data = await _draft_or_alert(callback, state)
    if data is None:
        return
    _, action, idx = callback.data.split(":")
    idx = int(idx)
    draft = data["oe_items"]
    if idx >= len(draft) or _is_fixed(draft[idx]):
        await callback.answer()
        return
    paid_lines = sum(1 for it in draft if not _is_fixed(it))
    qty = float(draft[idx].get("quantity") or 0)
    if action == "inc":
        draft[idx]["quantity"] = qty + 1
    elif action == "dec" and qty > 1:
        draft[idx]["quantity"] = qty - 1
    elif paid_lines <= 1:
        # rm, or ➖ on a single unit, of the only paid line
        await callback.answer(get_text("oe_last_line", data["lang"]), show_alert=True)
        return
    else:
        draft.pop(idx)
    await state.update_data(oe_items=draft)
    await _render(callback, state, edit=True)
    await callback.answer()


@router.callback_query(F.data.regexp(r"^oe:qty:\d+$"))
async def ask_qty(callback: CallbackQuery, state: FSMContext):
    data = await _draft_or_alert(callback, state)
    if data is None:
        return
    idx = int(callback.data.split(":")[2])
    draft = data["oe_items"]
    if idx >= len(draft) or _is_fixed(draft[idx]):
        await callback.answer()
        return
    await state.set_state(OrderEditStates.waiting_qty)
    await state.update_data(oe_qty_idx=idx)
    await callback.message.answer(
        get_text("oe_ask_qty", data["lang"], name=html.escape(draft[idx].get("name") or "?")))
    await callback.answer()


@router.message(OrderEditStates.waiting_qty, F.text)
async def got_qty(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    raw = (message.text or "").strip()
    if raw.lower() in ("/cancel", "cancel", "bekor"):
        await state.set_state(OrderEditStates.editing)
        await _render(message, state, edit=False)
        return
    if not raw.isdigit():
        await message.answer(get_text("oe_bad_qty", lang))
        return
    qty = int(raw)
    draft = data["oe_items"]
    idx = data.get("oe_qty_idx", -1)
    if 0 <= idx < len(draft):
        if qty == 0:
            if sum(1 for it in draft if not _is_fixed(it)) <= 1:
                await message.answer(get_text("oe_last_line", lang))
                return
            draft.pop(idx)
        else:
            draft[idx]["quantity"] = float(qty)
    await state.set_state(OrderEditStates.editing)
    await state.update_data(oe_items=draft)
    await _render(message, state, edit=False)


@router.callback_query(F.data == "oe:add")
async def ask_search(callback: CallbackQuery, state: FSMContext):
    data = await _draft_or_alert(callback, state)
    if data is None:
        return
    await state.set_state(OrderEditStates.waiting_search)
    await callback.message.answer(get_text("oe_ask_search", data["lang"]))
    await callback.answer()


@router.message(OrderEditStates.waiting_search, F.text)
async def got_search(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    raw = (message.text or "").strip()
    if raw.lower() in ("/cancel", "cancel", "bekor"):
        await state.set_state(OrderEditStates.editing)
        await _render(message, state, edit=False)
        return
    found = [p for p in await database.admin_search_products(raw, limit=30)
             if p.get("is_active") == 1 and float(p.get("price") or 0) > 0][:10]
    if not found:
        await message.answer(get_text("oe_no_results", lang))
        return
    rows = [[InlineKeyboardButton(
        text=f"{p['name'][:30]} — {_money(float(p['price']))} ({_qty(p.get('quantity'))})",
        callback_data=f"oe:pick:{p['id']}",
    )] for p in found]
    await message.answer(get_text("oe_pick", lang), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.regexp(r"^oe:pick:\d+$"))
async def pick_product(callback: CallbackQuery, state: FSMContext):
    data = await _draft_or_alert(callback, state)
    if data is None:
        return
    pid = int(callback.data.split(":")[2])
    draft = data["oe_items"]
    existing = next((it for it in draft
                     if database.order_line_key(it) == ("p", pid)), None)
    if existing:
        existing["quantity"] = float(existing.get("quantity") or 0) + 1
    else:
        p = await database.get_product(pid)
        if not p or not p.get("is_active"):
            await callback.answer("❌", show_alert=True)
            return
        discount = database.active_discount(p.get("discount_percent"), p.get("discount_until"))
        draft.append({
            "product_id": pid,
            "set_id": None,
            "is_set": False,
            "name": p["name"],
            "quantity": 1.0,
            "price": database.effective_price(p["price"], discount, p.get("discount_until")),
            "original_price": p["price"],
            "discount_percent": discount,
            "unit": p.get("unit"),
            "seller_id": p.get("seller_id"),
            "added_by_admin": True,
        })
    await state.set_state(OrderEditStates.editing)
    await state.update_data(oe_items=draft)
    await _render(callback, state, edit=True)
    await callback.answer()


@router.callback_query(F.data == "oe:cancel")
async def cancel_edit(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    order_id = data.get("oe_order_id")
    lang = data.get("lang") or await database.get_user_language(callback.from_user.id)
    await state.clear()
    kb = None
    if order_id:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text=get_text("oe_btn_back_order", lang), callback_data=f"seller_order:{order_id}")]])
    try:
        await callback.message.edit_text(get_text("oe_no_changes", lang), reply_markup=kb)
    except Exception:
        await callback.message.answer(get_text("oe_no_changes", lang), reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data == "oe:save")
async def save_edit(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await _draft_or_alert(callback, state)
    if data is None:
        return
    lang = data["lang"]
    order_id = data["oe_order_id"]
    orig, draft = data["oe_orig"], data["oe_items"]
    if draft == orig:
        await cancel_edit(callback, state)
        return
    try:
        result = await database.admin_update_order_items(order_id, orig, draft)
    except database.InsufficientStockError as e:
        p = await database.get_product(e.product_id)
        await callback.answer(get_text(
            "oe_out_of_stock", lang, name=(p or {}).get("name", e.product_id),
            need=_qty(e.requested), available=_qty(e.available)), show_alert=True)
        return
    except database.OrderChangedError:
        await state.clear()
        await callback.answer(get_text("oe_changed", lang), show_alert=True)
        return
    except ValueError:
        await callback.answer("❌", show_alert=True)
        return
    await state.clear()
    logger.info("Order #%s edited by admin %s: total %s -> %s",
                order_id, callback.from_user.id, result["old_total"], result["new_total"])

    if result["low_stock"]:
        try:
            import stock_alerts
            await stock_alerts.check_now(bot)
        except Exception:
            logger.exception("stock check after order edit failed")

    order = await database.get_order(order_id)
    paid_note = ""
    if order and order.get("payment_method") == "online" \
            and abs(result["new_total"] - result["old_total"]) > 0.5:
        paid_note = get_text("oe_paid_note", lang)
    text = get_text("oe_saved", lang, order_id=order_id,
                    old_total=_money(result["old_total"]),
                    new_total=_money(result["new_total"]), paid_note=paid_note)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("oe_btn_notify", lang), callback_data=f"oe:notify:{order_id}")],
        [InlineKeyboardButton(text=get_text("oe_btn_back_order", lang), callback_data=f"seller_order:{order_id}")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.regexp(r"^oe:notify:\d+$"))
async def notify_buyer(callback: CallbackQuery, bot: Bot):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("❌", show_alert=True)
        return
    order_id = int(callback.data.split(":")[2])
    lang = await database.get_user_language(callback.from_user.id)
    order = await database.get_order(order_id)
    if not order:
        await callback.answer("❌", show_alert=True)
        return
    buyer_lang = await database.get_user_language(order["user_id"])
    lines = []
    for it in _items_of(order):
        name = html.escape(localize_product_text(it.get("name"), None, buyer_lang) or "?")
        qty = f"{_qty(it.get('quantity'))} {get_item_unit(it, buyer_lang)}"
        if float(it.get("price") or 0) > 0:
            lines.append(f"• {name} — {qty} × {_money(float(it['price']))}")
        else:
            lines.append(f"🎁 {name} — {qty}")
    text = get_text("buyer_order_edited", buyer_lang, order_id=order_id,
                    items="\n".join(lines), total=_money(float(order["total"] or 0)))
    try:
        await bot.send_message(order["user_id"], text, parse_mode="HTML")
        await callback.answer(get_text("oe_notified", lang), show_alert=True)
        try:
            await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=get_text("oe_btn_back_order", lang),
                                     callback_data=f"seller_order:{order_id}")]]))
        except Exception:
            pass
    except Exception as exc:
        logger.warning("Order-edit notice to buyer %s failed: %s", order["user_id"], exc)
        await callback.answer(get_text("oe_notify_failed", lang), show_alert=True)
