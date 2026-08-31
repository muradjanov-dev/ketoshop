"""
Admin panel — stats, user management, order overview, broadcast, delivery zone management
"""
import html
import json
import logging
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_IDS
from database import (
    get_user_language, get_admin_stats, get_monthly_breakdown, get_month_stats, get_top_products, get_top_viewed_products,
    get_daily_active_users, get_top_actions, get_top_active_users,
    get_all_users, get_all_orders, get_order_counts_by_status,
    get_all_products, get_delivery_zones, get_delivery_zone, update_delivery_zone,
    ban_user, unban_user, get_order, update_order_status, get_user,
    count_active_products_in_category, bulk_set_category_discount,
    add_manual_order, add_b2b_order, get_products_by_category, get_product,
    effective_price, active_discount,
    get_all_active_products, set_cart_product_quantity,
    format_local_dt,
    add_admin_db,
    get_gamification_state, get_keto_balances_list, set_redemption_enabled,
    LEADERBOARD_EXCLUDED_USER_IDS, add_b2b_eritritol_order,
    list_promotions, get_promotion, create_promotion, update_promotion,
    set_promotion_bonuses, start_promotion, stop_promotion,
    search_products, save_web_image,
)
from locales import (
    get_text, get_order_status, get_unit_name, get_display_unit, get_delivery_method_name,
    get_category_name, get_month_name, localize_product_text, CATEGORIES,
)
from keyboards import (
    admin_panel_keyboard, admin_stats_menu_keyboard, admin_products_menu_keyboard,
    admin_users_menu_keyboard, admin_marketing_menu_keyboard,
    admin_cancel_keyboard, admin_order_filter_keyboard, admin_stats_keyboard,
    stats_keyboard, admin_delivery_zone_keyboard, admin_user_action_keyboard,
    back_to_menu_keyboard, category_select_keyboard,
)

router = Router()
logger = logging.getLogger(__name__)


class AdminStates(StatesGroup):
    broadcast_message = State()
    broadcast_confirm = State()
    ban_user_id = State()
    unban_user_id = State()
    edit_zone_price = State()
    bulk_discount_percent = State()
    bulk_discount_days = State()
    bulk_discount_confirm = State()
    list_quote_input = State()
    add_admin_id = State()
    # Manual order entry (offline orders received by phone / in-person)
    manual_name = State()
    manual_phone = State()
    manual_address = State()
    manual_pick_category = State()  # picking a category (with inline cart visible)
    manual_pick_product = State()   # picking a product within that category
    manual_quantity = State()       # entering quantity for the picked product
    manual_discount = State()       # optional per-line discount % (this order only)
    manual_payment = State()
    manual_delivery = State()
    manual_status = State()
    manual_confirm = State()
    # B2B (wholesale/company) sale entry — shares the manual-order category/
    # product picker states above (branched on order_type='b2b' in FSM data),
    # but skips phone/address/payment/delivery/status: just company name,
    # products, confirm.
    b2b_company = State()
    b2b_confirm = State()
    # B2B Eritritol order
    b2b_eritritol_address = State()
    b2b_eritritol_phone = State()
    b2b_eritritol_quantity = State()
    b2b_eritritol_total = State()
    b2b_eritritol_confirm = State()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ===== ADMIN PANEL =====

@router.callback_query(F.data == "admin_panel")
async def show_admin_panel(callback: CallbackQuery, state: FSMContext = None):
    if state:
        await state.clear()
    """Show admin panel"""
    if not is_admin(callback.from_user.id):
        lang = await get_user_language(callback.from_user.id)
        await callback.answer(get_text("admin_not_authorized", lang), show_alert=True)
        return

    lang = await get_user_language(callback.from_user.id)
    await callback.message.edit_text(
        get_text("admin_panel", lang),
        reply_markup=admin_panel_keyboard(lang),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_menu:"))
async def show_admin_submenu(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer()
        return

    menu_type = callback.data.split(":")[1]
    lang = await get_user_language(callback.from_user.id)
    
    if menu_type == "stats":
        kb = admin_stats_menu_keyboard(lang)
    elif menu_type == "products":
        kb = admin_products_menu_keyboard(lang)
    elif menu_type == "users":
        kb = admin_users_menu_keyboard(lang)
    elif menu_type == "marketing":
        kb = admin_marketing_menu_keyboard(lang)
    else:
        await callback.answer()
        return

    await callback.message.edit_text(
        get_text("admin_panel", lang),
        reply_markup=kb,
        parse_mode="HTML"
    )
    await callback.answer()


# ===== STATS =====

def _fmt_num(n: int) -> str:
    return f"{int(n):,}".replace(",", " ")


async def render_stats(callback: CallbackQuery, period: str,
                       callback_prefix: str = "admin:stats",
                       back_callback: str = "admin_panel"):
    """Shared renderer for the stats view — used by both admin and seller panels."""
    lang = await get_user_language(callback.from_user.id)
    stats = await get_admin_stats(period)
    top = await get_top_products(period, limit=5)
    top_viewed = await get_top_viewed_products(period, limit=5)

    if top:
        top_text = "\n".join(
            get_text("stats_top_item", lang,
                n=i,
                name=t["name"],
                qty=t["qty"],
                revenue=_fmt_num(t["revenue"]),
            )
            for i, t in enumerate(top, 1)
        )
    else:
        top_text = get_text("stats_top_empty", lang)

    viewed_header = get_text("stats_viewed_title", lang)
    if top_viewed:
        viewed_lines = "\n".join(
            get_text("stats_viewed_item", lang,
                n=i,
                name=v["name"],
                views=v["views"],
            )
            for i, v in enumerate(top_viewed, 1)
        )
    else:
        viewed_lines = get_text("stats_viewed_empty", lang)
    viewed_block = f"{viewed_header}\n{viewed_lines}"

    active_users = await get_daily_active_users(period)
    top_actions = await get_top_actions(period, limit=8)
    if top_actions:
        actions_text = "".join(
            get_text("stats_top_actions_item", lang, n=i, label=a["action"], clicks=a["clicks"])
            for i, a in enumerate(top_actions, 1)
        )
    else:
        actions_text = get_text("stats_top_actions_empty", lang)

    top_active_users = await get_top_active_users(period, limit=10)
    if top_active_users:
        no_product = get_text("stats_top_users_no_product", lang)
        top_users_text = "".join(
            get_text("stats_top_users_item", lang,
                n=i,
                name=html.escape(u["name"] or "—"),
                clicks=u["clicks"],
                product=html.escape(u["fav_product"]) if u["fav_product"] else no_product,
            )
            for i, u in enumerate(top_active_users, 1)
        )
    else:
        top_users_text = get_text("stats_top_users_empty", lang)

    activity_block = (
        f"{get_text('stats_activity_title', lang)}\n"
        f"{get_text('stats_active_users', lang, n=active_users)}\n\n"
        f"{get_text('stats_top_actions_title', lang)}\n{actions_text}\n\n"
        f"{get_text('stats_top_users_title', lang)}\n{top_users_text}"
    )

    # Total is always shown; the period-scoped "new" count (hidden on the
    # "all time" tab, where it'd just repeat the total) is what actually
    # moves when switching 7d/30d/all — see get_admin_stats.
    users_display = _fmt_num(stats["users_total"])
    reviews_display = _fmt_num(stats["reviews_total"])
    if period != "all":
        users_display += get_text("stats_new_suffix", lang, new=_fmt_num(stats["users_new"]))
        reviews_display += get_text("stats_new_suffix", lang, new=_fmt_num(stats["reviews_new"]))

    text = get_text("admin_stats", lang,
        period_label=get_text(f"stats_period_{period}", lang),
        users=users_display,
        products_active=stats["products_active"],
        products_in_stock=stats["products_in_stock"],
        reviews=reviews_display,
        orders_total=stats["orders_total"],
        orders_pending=stats["orders_pending"],
        orders_confirmed=stats["orders_confirmed"],
        orders_delivered=stats["orders_delivered"],
        orders_cancelled=stats["orders_cancelled"],
        revenue=_fmt_num(stats["revenue"]),
        b2b_revenue=_fmt_num(stats["b2b_revenue"]),
        b2b_orders=stats["b2b_orders"],
        aov=_fmt_num(stats["aov"]),
        top_products=top_text,
        top_viewed=viewed_block,
        activity_block=activity_block,
    )

    try:
        await callback.message.edit_text(
            text,
            reply_markup=stats_keyboard(lang, current=period,
                                        callback_prefix=callback_prefix,
                                        back_callback=back_callback),
            parse_mode="HTML",
        )
    except Exception:
        # Same period re-clicked → Telegram rejects "message not modified"
        pass


@router.callback_query(F.data == "admin:stats")
async def show_admin_stats(callback: CallbackQuery):
    """Default stats view — today"""
    if not is_admin(callback.from_user.id):
        return
    await render_stats(callback, "today", "admin:stats", "admin_panel")
    await callback.answer()


@router.callback_query(F.data.startswith("admin:stats:"))
async def switch_stats_period(callback: CallbackQuery):
    """Switch stats period (today / 7d / 30d / all)"""
    if not is_admin(callback.from_user.id):
        return
    period = callback.data.split(":", 2)[2]
    if period not in ("today", "7d", "30d", "all"):
        period = "today"
    await render_stats(callback, period, "admin:stats", "admin_panel")
    await callback.answer()


def _month_block_text(lang: str, m: dict) -> str:
    name = get_month_name(m["month"], lang)
    if m["is_current"]:
        from datetime import datetime as _dt, timezone as _tz, timedelta as _td
        today_local = (_dt.now(_tz.utc) + _td(hours=5)).day
        hozirgi = "hozirgi" if lang != "ru" else "текущий"
        label = f"🗓 <b>{name} {m['year']}</b> (1–{today_local}, {hozirgi})"
    else:
        label = f"🗓 <b>{name} {m['year']}</b>"
    savdo = "buyurtma" if lang != "ru" else "заказ(ов)"
    line = f"{label}\n💰 {_fmt_num(m['revenue'])} so'm — {m['orders']} ta {savdo}" if lang != "ru" else \
           f"{label}\n💰 {_fmt_num(m['revenue'])} сум — {m['orders']} {savdo}"
    if m["b2b_revenue"]:
        line += (f"\n🏢 shundan B2B: {_fmt_num(m['b2b_revenue'])} so'm" if lang != "ru"
                  else f"\n🏢 из них B2B: {_fmt_num(m['b2b_revenue'])} сум")
    return line


@router.callback_query(F.data == "admin:monthly_stats")
async def show_monthly_stats(callback: CallbackQuery):
    """Current calendar month up front (button label always shows the live
    month name, see admin_panel_keyboard) + inline buttons for whichever
    prior months actually have data — tap one to drill into it. Owner
    request 2026-07-27: rolling 30-day wasn't cutting it, wanted actual
    "iyul" vs "iyun" comparisons, navigable rather than one long list."""
    if not is_admin(callback.from_user.id):
        return
    lang = await get_user_language(callback.from_user.id)
    months = await get_monthly_breakdown(months_back=6)
    current, others = months[0], [m for m in months[1:] if m["orders"] > 0]

    text = "📅 <b>Oylik hisobot</b>\n\n" + _month_block_text(lang, current)

    rows = []
    for i in range(0, len(others), 3):
        row = [
            InlineKeyboardButton(
                text=get_month_name(m["month"], lang) + (f" {m['year']}" if m["year"] != current["year"] else ""),
                callback_data=f"admin:monthly_stats:{m['year']}:{m['month']}",
            )
            for m in others[i:i + 3]
        ]
        rows.append(row)
    rows.append([InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="admin_panel")])

    try:
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows), parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("admin:monthly_stats:"))
async def show_specific_month_stats(callback: CallbackQuery):
    """Drill-down into one past month, picked from show_monthly_stats."""
    if not is_admin(callback.from_user.id):
        return
    lang = await get_user_language(callback.from_user.id)
    try:
        _, _, year_s, month_s = callback.data.split(":")
        year, month = int(year_s), int(month_s)
    except ValueError:
        await callback.answer("❌")
        return

    m = await get_month_stats(year, month)
    text = "📅 <b>Oylik hisobot</b>\n\n" + _month_block_text(lang, m)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="admin:monthly_stats")],
    ])
    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()


# ===== USERS =====

USERS_PER_PAGE = 15


@router.callback_query(F.data == "admin:users")
async def show_admin_users(callback: CallbackQuery):
    """Entry point — render page 0."""
    await _render_users_page(callback, 0)


@router.callback_query(F.data.startswith("admin:users:"))
async def show_admin_users_page(callback: CallbackQuery):
    """Page navigation — admin:users:N."""
    try:
        page = int(callback.data.split(":")[2])
    except (ValueError, IndexError):
        page = 0
    await _render_users_page(callback, page)


async def _render_users_page(callback: CallbackQuery, page: int) -> None:
    """Render the users list at a given page. Wrapped in a top-level try/except
    so any failure surfaces as a popup instead of a stuck loading spinner."""
    import logging
    logger = logging.getLogger(__name__)
    logger.info("admin:users page=%d invoked by user_id=%s", page, callback.from_user.id)

    # ACK the click immediately so the Telegram spinner stops regardless.
    try:
        await callback.answer()
    except Exception:
        pass

    try:
        if not is_admin(callback.from_user.id):
            await callback.answer("🚫 Admin only", show_alert=True)
            return

        lang = await get_user_language(callback.from_user.id)
        page = max(0, page)
        users, total = await get_all_users(page=page, per_page=USERS_PER_PAGE)
        total_pages = max(1, (total + USERS_PER_PAGE - 1) // USERS_PER_PAGE)
        page = min(page, total_pages - 1)  # clamp if user lingered on a stale page
        logger.info("admin:users fetched %d users (total=%s, page=%d/%d)",
                    len(users), total, page + 1, total_pages)

        text = get_text("admin_users_title", lang, total=total)
        buttons = []
        for u in users:
            role = "🏪" if u.get("is_seller") else "👤"
            # HTML-escape user-controlled fields so a name/username containing
            # `<`, `>`, or `&` doesn't break the parse_mode="HTML" send.
            name = html.escape(u.get("full_name") or "—")
            username = html.escape(u.get("username") or "—")
            u_lang = (u.get("language") or "?").upper()
            text += get_text("admin_user_item", lang,
                name=name,
                username=username,
                id=u["user_id"],
                role=role,
                user_lang=u_lang,
            )
            # Button text isn't HTML-parsed, so use the raw name (truncated).
            raw_name = (u.get("full_name") or "—")[:30]
            buttons.append([InlineKeyboardButton(
                text=f"{role} {raw_name} ({u['user_id']})",
                callback_data=f"admin:user_detail:{u['user_id']}"
            )])

        # Pagination row (only when there's more than one page)
        if total_pages > 1:
            nav_row = []
            if page > 0:
                nav_row.append(InlineKeyboardButton(
                    text="◀️", callback_data=f"admin:users:{page - 1}"
                ))
            nav_row.append(InlineKeyboardButton(
                text=f"{page + 1}/{total_pages}", callback_data="noop"
            ))
            if page < total_pages - 1:
                nav_row.append(InlineKeyboardButton(
                    text="▶️", callback_data=f"admin:users:{page + 1}"
                ))
            buttons.append(nav_row)

        buttons.append([InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="admin_panel")])
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

        try:
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception as exc:
            logger.warning("admin:users edit_text(HTML) failed: %s", exc)
            try:
                await callback.message.edit_text(text, reply_markup=keyboard)
            except Exception as exc2:
                logger.warning("admin:users edit_text(plain) failed: %s", exc2)
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as exc:
        logger.exception("admin:users handler crashed: %s", exc)
        try:
            await callback.message.answer(
                f"⚠️ Foydalanuvchilar ro'yxatini ochib bo'lmadi:\n<code>{html.escape(str(exc))}</code>",
                parse_mode="HTML",
            )
        except Exception:
            pass


@router.callback_query(F.data.startswith("admin:user_detail:"))
async def show_user_detail(callback: CallbackQuery):
    """Show user detail with ban/unban actions"""
    if not is_admin(callback.from_user.id):
        return

    user_id = int(callback.data.split(":")[2])
    lang = await get_user_language(callback.from_user.id)
    user = await get_user(user_id)

    if not user:
        await callback.answer("User not found", show_alert=True)
        return

    name = html.escape(user.get("full_name") or "—")
    username = html.escape(user.get("username") or "—")
    role = "🏪 Seller" if user.get("is_seller") else "👤 Buyer"
    phone = html.escape(user.get("phone") or "—")
    user_lang = (user.get("language") or "?").upper()
    created = user.get("created_at")
    joined = format_local_dt(created, "%d.%m.%Y") if created else "—"

    text = (
        f"👤 <b>{name}</b>\n"
        f"@{username}\n"
        f"ID: <code>{user_id}</code>\n"
        f"Role: {role}\n"
        f"Language: {user_lang}\n"
        f"Phone: {phone}\n"
        f"Joined: {joined}"
    )

    await callback.message.edit_text(
        text,
        reply_markup=admin_user_action_keyboard(lang, user_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:ban:"))
async def admin_ban_user(callback: CallbackQuery):
    """Ban a user"""
    if not is_admin(callback.from_user.id):
        return

    user_id = int(callback.data.split(":")[2])
    lang = await get_user_language(callback.from_user.id)

    await ban_user(user_id)
    await callback.message.edit_text(
        get_text("user_banned", lang, user_id=user_id),
        reply_markup=admin_panel_keyboard(lang),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:unban:"))
async def admin_unban_user(callback: CallbackQuery):
    """Unban a user"""
    if not is_admin(callback.from_user.id):
        return

    user_id = int(callback.data.split(":")[2])
    lang = await get_user_language(callback.from_user.id)

    await unban_user(user_id)
    await callback.message.edit_text(
        get_text("user_unbanned", lang, user_id=user_id),
        reply_markup=admin_panel_keyboard(lang),
        parse_mode="HTML"
    )
    await callback.answer()


# ===== ADD ADMIN =====

@router.callback_query(F.data == "admin:add_admin")
async def admin_add_admin_start(callback: CallbackQuery, state: FSMContext):
    """Prompt an existing admin for the Telegram numeric ID of the new admin."""
    if not is_admin(callback.from_user.id):
        return

    lang = await get_user_language(callback.from_user.id)
    await state.set_state(AdminStates.add_admin_id)
    await state.update_data(lang=lang)
    await callback.message.edit_text(
        get_text("add_admin_prompt", lang),
        reply_markup=back_to_menu_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.add_admin_id, F.text)
async def admin_add_admin_process(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    lang = data.get("lang", "uz")

    # Re-check admin status at submit time too — the requester could in
    # theory have been unadmin'd between the prompt and this reply.
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer(get_text("add_admin_invalid", lang), parse_mode="HTML")
        return

    new_admin_id = int(raw)
    if new_admin_id in ADMIN_IDS:
        await state.clear()
        await message.answer(
            get_text("add_admin_already", lang, user_id=new_admin_id),
            reply_markup=admin_panel_keyboard(lang),
            parse_mode="HTML",
        )
        return

    await add_admin_db(new_admin_id, message.from_user.id)
    # Mutate the shared list in place — every module that imported
    # ADMIN_IDS at startup sees this immediately, no restart needed.
    ADMIN_IDS.append(new_admin_id)

    await state.clear()
    await message.answer(
        get_text("add_admin_done", lang, user_id=new_admin_id),
        reply_markup=admin_panel_keyboard(lang),
        parse_mode="HTML",
    )

    # Best-effort — the new admin may never have started a chat with the bot.
    try:
        new_admin_lang = await get_user_language(new_admin_id)
        await bot.send_message(new_admin_id, get_text("you_are_now_admin", new_admin_lang), parse_mode="HTML")
    except Exception:
        pass


# ===== ORDERS =====

@router.callback_query(F.data == "admin:orders")
async def show_admin_orders_menu(callback: CallbackQuery):
    """Show order filter menu"""
    if not is_admin(callback.from_user.id):
        return

    lang = await get_user_language(callback.from_user.id)
    counts = await get_order_counts_by_status()
    await callback.message.edit_text(
        "📦 " + ("Buyurtmalar filtrini tanlang:" if lang == "uz" else "Выберите фильтр заказов:"),
        reply_markup=admin_order_filter_keyboard(lang, counts),
        parse_mode="HTML"
    )
    await callback.answer()


ORDERS_PER_PAGE = 15


@router.callback_query(F.data.startswith("admin:orders:"))
async def show_filtered_orders(callback: CallbackQuery):
    """Show filtered orders. Callback format:
       admin:orders:STATUS         → page 0
       admin:orders:STATUS:N       → page N
    """
    if not is_admin(callback.from_user.id):
        return

    parts = callback.data.split(":")
    status_filter = parts[2] if len(parts) > 2 else "all"
    try:
        page = int(parts[3]) if len(parts) > 3 else 0
    except ValueError:
        page = 0
    page = max(0, page)
    lang = await get_user_language(callback.from_user.id)
    await render_orders_list(callback, status_filter, page, lang)
    await callback.answer()


async def render_orders_list(callback: CallbackQuery, status_filter: str, page: int, lang: str):
    """Render one page of the admin order list (in place) for a status filter.

    Extracted so the order_act:* status-change buttons can refresh the list
    instead of bouncing the admin back to a panel — they re-call this with the
    same filter+page, so the row's action button advances to the next lifecycle
    step (or the order drops off, if the current filter no longer matches)."""
    page = max(0, page)
    status = None if status_filter == "all" else status_filter
    orders, total = await get_all_orders(page=page, per_page=ORDERS_PER_PAGE, status=status)
    total_pages = max(1, (total + ORDERS_PER_PAGE - 1) // ORDERS_PER_PAGE)
    page = min(page, total_pages - 1)

    title = "📦 " + ("Barcha buyurtmalar" if lang == "uz" else "Все заказы")
    if status:
        title += f" ({get_order_status(status, lang)})"
    text = f"<b>{title}</b> ({total})\n\n"

    for o in orders:
        status_text = get_order_status(o["status"], lang)
        total_str = f"{int(o['total']):,}".replace(",", " ")
        delivery_label = get_delivery_method_name(o.get("delivery_method"), lang)

        # Lifecycle: created → (confirmed) → (shipped) → (delivered)
        lifecycle = f"📅 {format_local_dt(o['created_at'])}"
        if o.get("confirmed_at"):
            lifecycle += f" → ✅ {format_local_dt(o['confirmed_at'])}"
        if o.get("shipped_at"):
            lifecycle += f" → 🚚 {format_local_dt(o['shipped_at'])}"
        if o.get("delivered_at"):
            lifecycle += f" → 📦 {format_local_dt(o['delivered_at'])}"

        text += (
            f"#{o['id']} | {status_text} | 💰 {total_str}\n"
            f"   👤 {html.escape(o.get('customer_name') or '—')} | 📱 {html.escape(o.get('phone') or '—')}\n"
            f"   🚚 {delivery_label}\n"
            f"   {lifecycle}\n\n"
        )

    # Each order gets a row with the title (opens the detail card) + a
    # quick-action button matching the *next* lifecycle step. Tapping the
    # action triggers the existing order_act:* handler, which updates the
    # status, stamps the timestamp, and pushes a notification to the buyer.
    # pending → confirmed → shipped → delivered.
    buttons = []
    for o in orders:
        status_text = get_order_status(o["status"], lang)
        total_str = f"{int(o['total']):,}".replace(",", " ")
        title_btn = InlineKeyboardButton(
            text=f"#{o['id']} — {status_text} — {total_str} so'm",
            callback_data=f"seller_order:{o['id']}",
        )
        # Return context appended so order_act refreshes this same list view
        # (filter+page) in place instead of switching to a panel.
        ret = f":list:{status_filter}:{page}"
        action_btn = None
        if o["status"] == "pending":
            action_btn = InlineKeyboardButton(
                text=get_text("btn_accept_order", lang),
                callback_data=f"order_act:confirm:{o['id']}{ret}",
            )
        elif o["status"] == "confirmed":
            action_btn = InlineKeyboardButton(
                text=get_text("btn_mark_shipped", lang),
                callback_data=f"order_act:ship:{o['id']}{ret}",
            )
        elif o["status"] == "shipped":
            action_btn = InlineKeyboardButton(
                text=get_text("btn_mark_delivered", lang),
                callback_data=f"order_act:delivered:{o['id']}{ret}",
            )
        if action_btn:
            buttons.append([title_btn])
            buttons.append([action_btn])
        else:
            buttons.append([title_btn])

    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(
                text="◀️", callback_data=f"admin:orders:{status_filter}:{page - 1}"
            ))
        nav_row.append(InlineKeyboardButton(
            text=f"{page + 1}/{total_pages}", callback_data="noop"
        ))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(
                text="▶️", callback_data=f"admin:orders:{status_filter}:{page + 1}"
            ))
        buttons.append(nav_row)
    buttons.append([InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="admin:orders")])

    try:
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            parse_mode="HTML",
        )
    except Exception:
        # Fallback to plain text on HTML-entity oddities (long customer names, etc.)
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        )
    # Note: caller is responsible for callback.answer() — order_act passes a
    # toast there, the list handler answers silently.


# ===== ADMIN: HARD-DELETE ORDER =====

@router.callback_query(F.data.startswith("order_delete:"))
async def admin_delete_order_prompt(callback: CallbackQuery):
    """Step 1 — confirm before nuking the order row.

    This is a hard delete (DELETE FROM orders) intended for cleaning up
    orders that shouldn't exist (mistakes, tests). Stock is restored if the
    order wasn't already cancelled. Admin-only.
    """
    if not is_admin(callback.from_user.id):
        await callback.answer("❌", show_alert=True)
        return

    order_id = int(callback.data.split(":")[1])
    lang = await get_user_language(callback.from_user.id)

    await callback.message.edit_text(
        get_text("confirm_delete_order", lang, order_id=order_id),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=get_text("btn_yes", lang),
                                      callback_data=f"order_delete_do:{order_id}"),
                InlineKeyboardButton(text=get_text("btn_no", lang),
                                      callback_data=f"seller_order:{order_id}"),
            ],
        ]),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("order_delete_do:"))
async def admin_delete_order_do(callback: CallbackQuery):
    """Step 2 — actually delete the row (and restore stock)."""
    if not is_admin(callback.from_user.id):
        await callback.answer("❌", show_alert=True)
        return

    from database import delete_order_permanently  # local import — avoids touching the big top-level group
    order_id = int(callback.data.split(":")[1])
    lang = await get_user_language(callback.from_user.id)

    deleted = await delete_order_permanently(order_id)
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_back", lang),
                               callback_data="admin:orders")],
    ])
    if deleted is None:
        await callback.message.edit_text(
            get_text("order_not_found", lang),
            reply_markup=back_kb,
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        get_text("order_deleted", lang, order_id=order_id),
        reply_markup=back_kb,
        parse_mode="HTML",
    )
    await callback.answer()


# ===== PRODUCTS =====

@router.callback_query(F.data == "admin:products")
async def show_admin_products(callback: CallbackQuery):
    """Show all products"""
    if not is_admin(callback.from_user.id):
        return

    lang = await get_user_language(callback.from_user.id)
    products, total = await get_all_products(page=0, per_page=20)

    text = f"🛒 <b>{'Barcha mahsulotlar' if lang == 'uz' else 'Все товары'}</b> ({total})\n\n"

    for p in products:
        price_str = f"{int(p['price']):,}".replace(",", " ")
        seller = p.get("seller_name") or "—"
        text += (
            f"• <b>{p['name']}</b> — {price_str} so'm\n"
            f"  📦 {p['quantity']} {get_unit_name(p['unit'], lang)} | 👤 {seller}\n\n"
        )

    buttons = [[InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="admin_panel")]]

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()


# ===== DELIVERY ZONES =====

@router.callback_query(F.data == "admin:delivery")
async def show_admin_delivery(callback: CallbackQuery):
    """Show delivery zones for editing"""
    if not is_admin(callback.from_user.id):
        return

    lang = await get_user_language(callback.from_user.id)
    zones = await get_delivery_zones(active_only=False)

    await callback.message.edit_text(
        "🚚 " + ("Yetkazish zonalari — tahrirlash uchun tanlang:" if lang == "uz"
                  else "Зоны доставки — выберите для редактирования:"),
        reply_markup=admin_delivery_zone_keyboard(lang, zones),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:edit_zone:"))
async def edit_zone_start(callback: CallbackQuery, state: FSMContext):
    """Start editing a delivery zone price"""
    if not is_admin(callback.from_user.id):
        return

    zone_id = int(callback.data.split(":")[2])
    lang = await get_user_language(callback.from_user.id)

    await state.set_state(AdminStates.edit_zone_price)
    await state.update_data(zone_id=zone_id, lang=lang)

    zone = await get_delivery_zone(zone_id)
    city = zone["city_name_uz"] if lang == "uz" else zone["city_name_ru"]

    await callback.message.edit_text(
        f"📍 <b>{city}</b>\n\n" + get_text("admin_edit_zone_price", lang),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(AdminStates.edit_zone_price)
async def process_zone_price(message: Message, state: FSMContext):
    """Update zone delivery price"""
    data = await state.get_data()
    lang = data.get("lang", "uz")

    try:
        price = float(message.text.strip().replace(" ", "").replace(",", ""))
        if price < 0:
            raise ValueError
    except ValueError:
        await message.answer(get_text("invalid_price", lang))
        return

    await update_delivery_zone(data["zone_id"], price=price)
    await state.clear()

    await message.answer(
        get_text("zone_updated", lang),
        reply_markup=admin_panel_keyboard(lang),
        parse_mode="HTML"
    )


# ===== KETO-AS-DISCOUNT (checkout) =====

async def _render_keto_admin(lang: str) -> tuple[str, InlineKeyboardMarkup]:
    """Same content as the website admin panel's Keto tab, reachable
    in-chat too — the owner mostly lives in the Telegram admin panel."""
    state = await get_gamification_state()
    on = bool(state.get("redemption_enabled"))
    balances = await get_keto_balances_list()

    if lang == "ru":
        status_line = (
            "🟢 <b>Включено</b> — покупатели могут использовать Keto как скидку при оформлении заказа."
            if on else
            "⚪ <b>Выключено</b> — эта функция никому не видна."
        )
        no_balances = "Пока ни у кого нет Keto."
        top_label = "📊 Балансы (топ {}):"
        more_label = "… и ещё {} чел."
    else:
        status_line = (
            "🟢 <b>Yoqilgan</b> — xaridorlar checkout paytida Ketochalarini chegirma sifatida ishlata oladi."
            if on else
            "⚪ <b>O'chirilgan</b> — bu imkoniyat hech kimga ko'rinmaydi."
        )
        no_balances = "Hozircha hech kimda Keto yo'q."
        top_label = "📊 Balanslar (top {}):"
        more_label = "… va yana {} kishi"

    shown = balances[:15]
    lines = ["🥑 <b>Keto-chegirma (checkout)</b>", "", status_line, ""]
    if not balances:
        lines.append(no_balances)
    else:
        lines.append(top_label.format(len(shown)))
        for i, r in enumerate(shown, 1):
            name = f"@{r['username']}" if r.get("username") else (r.get("full_name") or f"ID {r['user_id']}")
            lines.append(f"{i}. {name} — {_fmt_num(r['keto_balance'])} Keto")
        if len(balances) > len(shown):
            lines.append(more_label.format(len(balances) - len(shown)))

    text = "\n".join(lines)
    toggle_label = get_text("btn_keto_toggle_off", lang) if on else get_text("btn_keto_toggle_on", lang)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=toggle_label, callback_data="admin:keto:toggle")],
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="admin_panel")],
    ])
    return text, keyboard


@router.callback_query(F.data == "admin:keto")
async def show_keto_admin(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    lang = await get_user_language(callback.from_user.id)
    text, keyboard = await _render_keto_admin(lang)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "admin:keto:toggle")
async def toggle_keto_redemption(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    lang = await get_user_language(callback.from_user.id)
    state = await get_gamification_state()
    new_value = not bool(state.get("redemption_enabled"))
    await set_redemption_enabled(new_value)
    text, keyboard = await _render_keto_admin(lang)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer("🚀 Yoqildi" if new_value else "⏹ O'chirildi")


# ===== AKSIYA / BONUS (2026-08-31) — the bot's own in-chat version of the
# website's "🎁 Aksiya / Bonus" tab. Both write the same promotions /
# promotion_bonuses rows, so a campaign drafted here can be started from the
# website and vice versa.
#
# The creation flow is a chat wizard: nom → kun → shartlar → rasm → bonus
# qoidalari. Products are picked by typing part of a name and tapping a match,
# which keeps the flow the same size whether the shop has 20 products or 500.
# Every optional step takes /skip. =====

class PromoAdminStates(StatesGroup):
    waiting_name = State()
    waiting_days = State()
    waiting_conditions = State()
    waiting_image = State()
    waiting_trigger_query = State()
    waiting_trigger_qty = State()
    waiting_bonus_query = State()
    waiting_bonus_amount = State()
    waiting_image_update = State()


# The units an admin can attach to a bonus amount, matching the website's
# dropdown (promotions._UNIT_BASE knows how to convert each into stock units).
PROMO_BONUS_UNITS = ["gr", "kg", "ml", "litr", "dona", "banka"]


def _promo_pname(product: dict, lang: str) -> str:
    return localize_product_text(product.get("name"), product.get("name_ru"), lang)


async def _render_promo_admin(lang: str) -> tuple[str, InlineKeyboardMarkup]:
    """Status screen: what's running, what's saved, and what can be done."""
    import promotions

    promos = await list_promotions()
    active = next((p for p in promos if p.get("active")), None)

    lines = ["🎁 <b>Aksiya / Bonus</b>", ""]
    if active:
        left = promotions.days_left(active)
        lines.append(f"🟢 <b>Faol:</b> {active['name']}")
        lines.append(f"⏳ {left} kun qoldi")
        if active.get("conditions"):
            lines.append("")
            lines.append(f"📋 {active['conditions']}")
        rules = active.get("bonuses") or []
        if rules:
            lines.append("")
            lines.append("🎁 <b>Bonuslar:</b>")
            for rule in rules:
                lines.append(f"   • {promotions.rule_line(rule, lang)}")
    else:
        lines.append("⚪ Hozircha faol aksiya yo'q.")

    saved = [p for p in promos if not p.get("active")]
    if saved:
        lines.append("")
        lines.append(f"💾 Saqlangan aksiyalar: {len(saved)} ta — boshlash uchun tanlang.")

    rows = []
    if active:
        rows.append([InlineKeyboardButton(text="⏹ To'xtatish", callback_data=f"admin:promo:stop:{active['id']}")])
        rows.append([InlineKeyboardButton(text="📤 Hammaga e'lon qilish", callback_data=f"admin:promo:announce:{active['id']}")])
        rows.append([InlineKeyboardButton(text="🖼 Rasmni almashtirish", callback_data=f"admin:promo:image:{active['id']}")])
    for promo in saved[:8]:
        rows.append([InlineKeyboardButton(
            text=f"🚀 Boshlash: {promo['name'][:30]} ({promo['days']} kun)",
            callback_data=f"admin:promo:start:{promo['id']}",
        )])
    rows.append([InlineKeyboardButton(text="➕ Yangi aksiya yaratish", callback_data="admin:promo:new")])
    rows.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_panel")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


@router.callback_query(F.data == "admin:promo")
async def show_promo_admin(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.clear()
    lang = await get_user_language(callback.from_user.id)
    text, keyboard = await _render_promo_admin(lang)
    await _promo_show(callback, text, keyboard)
    await callback.answer()


async def _promo_show(callback: CallbackQuery, text: str, keyboard: InlineKeyboardMarkup) -> None:
    """A campaign screen may follow a photo bubble (the image-preview step),
    and edit_text can't turn a photo into text — delete + resend when so."""
    if callback.message.photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        try:
            await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
        except Exception:
            await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data.startswith("admin:promo:start:"))
async def promo_start(callback: CallbackQuery):
    import promotions
    if not is_admin(callback.from_user.id):
        return
    promo_id = int(callback.data.split(":")[3])
    await start_promotion(promo_id)
    await promotions.refresh()
    lang = await get_user_language(callback.from_user.id)
    text, keyboard = await _render_promo_admin(lang)
    await _promo_show(callback, text, keyboard)
    await callback.answer("🚀 Aksiya boshlandi!")


@router.callback_query(F.data.startswith("admin:promo:stop:"))
async def promo_stop(callback: CallbackQuery):
    import promotions
    if not is_admin(callback.from_user.id):
        return
    await stop_promotion(int(callback.data.split(":")[3]))
    await promotions.refresh()
    lang = await get_user_language(callback.from_user.id)
    text, keyboard = await _render_promo_admin(lang)
    await _promo_show(callback, text, keyboard)
    await callback.answer("⏹ To'xtatildi")


@router.callback_query(F.data.startswith("admin:promo:announce:"))
async def promo_announce(callback: CallbackQuery, bot: Bot):
    """Fire-and-forget: the fan-out to every user takes minutes at Telegram's
    rate limits, far longer than a callback may stay unanswered."""
    import asyncio
    import promotions

    if not is_admin(callback.from_user.id):
        return
    promo = await get_promotion(int(callback.data.split(":")[3]))
    if not promo:
        await callback.answer("❌ Topilmadi", show_alert=True)
        return
    await callback.answer("📤 Yuborilmoqda — tugagach xabar keladi", show_alert=True)

    async def _run():
        try:
            sent, failed = await promotions.announce(bot, promo)
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"📤 Aksiya e'lon qilindi: <b>{promo['name']}</b>\n"
                        f"✅ {sent} ta yetkazildi, ⚠️ {failed} ta yetmadi.",
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
        except Exception:
            logger.exception("Aksiya announcement failed")

    asyncio.create_task(_run())


# ───────────────────── create-a-campaign wizard ─────────────────────────────

@router.callback_query(F.data == "admin:promo:new")
async def promo_new(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    lang = await get_user_language(callback.from_user.id)
    await state.set_state(PromoAdminStates.waiting_name)
    await state.update_data(lang=lang, promo_rules=[])
    await callback.message.edit_text(
        "🎁 <b>Yangi aksiya</b>\n\n1/5 — Aksiya nomini yozing.\n"
        "<i>Masalan: Bodom uni haftaligi</i>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(PromoAdminStates.waiting_name, F.text)
async def promo_name_entered(message: Message, state: FSMContext):
    name = (message.text or "").strip()
    if not name or name.startswith("/"):
        await message.answer("Aksiya nomini yozing (masalan: Bodom uni haftaligi).")
        return
    await state.update_data(promo_name=name[:200])
    await state.set_state(PromoAdminStates.waiting_days)
    await message.answer("2/5 — Aksiya necha kun davom etsin? (raqam kiriting, masalan: 7)")


@router.message(PromoAdminStates.waiting_days, F.text)
async def promo_days_entered(message: Message, state: FSMContext):
    try:
        days = int((message.text or "").strip())
        if days <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Musbat butun son kiriting (masalan: 7).")
        return
    await state.update_data(promo_days=days)
    await state.set_state(PromoAdminStates.waiting_conditions)
    await message.answer(
        "3/5 — Aksiya shartlarini yozing.\n"
        "<i>Masalan: Aksiya faqat yetkazib berish buyurtmalarida amal qiladi. "
        "Bonus savatga avtomatik qo'shiladi.</i>\n\n"
        "O'tkazib yuborish uchun /skip yoki quyidagi tugma.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data="admin:promo:skipcond"),
        ]]),
    )


@router.callback_query(F.data == "admin:promo:skipcond")
async def promo_conditions_skipped(callback: CallbackQuery, state: FSMContext):
    """Button twin of typing /skip — the same step, one tap instead."""
    if not is_admin(callback.from_user.id):
        return
    await state.update_data(promo_conditions=None)
    await callback.message.edit_text("3/5 — Shartlar o'tkazib yuborildi.")
    await _ask_promo_image(callback.message, state)
    await callback.answer()


@router.message(PromoAdminStates.waiting_conditions, F.text)
async def promo_conditions_entered(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if text == "/skip":
        await state.update_data(promo_conditions=None)
    else:
        await state.update_data(promo_conditions=text[:2000])
    await _ask_promo_image(message, state)


async def _ask_promo_image(message: Message, state: FSMContext) -> None:
    await state.set_state(PromoAdminStates.waiting_image)
    await message.answer(
        "4/5 — Aksiya rasmini yuboring.\n\n"
        "Bu rasm aksiya ekranida, saytdagi aksiya oynasida va e'lon xabarida ko'rinadi.\n"
        "Rasmsiz davom etish uchun /skip yoki quyidagi tugma.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="⏭ Rasmsiz davom etish", callback_data="admin:promo:skipimg"),
        ]]),
    )


@router.callback_query(F.data == "admin:promo:skipimg")
async def promo_image_skipped_button(callback: CallbackQuery, state: FSMContext):
    """Button twin of typing /skip at the photo step."""
    if not is_admin(callback.from_user.id):
        return
    await state.update_data(promo_image_url=None)
    await callback.message.edit_text("4/5 — Rasmsiz davom etilmoqda.")
    await _ask_promo_first_rule(callback.message, state)
    await callback.answer()


@router.message(PromoAdminStates.waiting_image, F.photo)
async def promo_image_received(message: Message, state: FSMContext):
    """Store the photo in web_images (same table the website's uploads use) so
    a single image_url works for the bot, the Mini App and the announcement.
    A Telegram file_id alone would be useless to the Mini App."""
    try:
        image_url = await _promo_store_photo(message)
    except Exception:
        logger.exception("Aksiya photo upload failed")
        await message.answer("⚠️ Rasmni saqlab bo'lmadi. Qayta yuboring yoki /skip bosing.")
        return
    await state.update_data(promo_image_url=image_url)
    await message.answer("✅ Rasm saqlandi.")
    await _ask_promo_first_rule(message, state)


@router.message(PromoAdminStates.waiting_image, F.text == "/skip")
async def promo_image_skipped(message: Message, state: FSMContext):
    await state.update_data(promo_image_url=None)
    await _ask_promo_first_rule(message, state)


@router.message(PromoAdminStates.waiting_image)
async def promo_image_invalid(message: Message, state: FSMContext):
    await message.answer("Rasm yuboring yoki /skip bosing.")


async def _promo_store_photo(message: Message) -> str:
    """Download the largest size of a Telegram photo and put it in web_images,
    returning the /img/N URL. Mirrors what the website's upload endpoint does,
    just sourced from a chat message instead of a multipart form."""
    import io as _io

    photo = message.photo[-1]
    buf = _io.BytesIO()
    await message.bot.download(photo, destination=buf)
    image_id = await save_web_image(buf.getvalue(), "image/jpeg")
    return f"/img/{image_id}"


async def _ask_promo_first_rule(message: Message, state: FSMContext) -> None:
    await state.set_state(PromoAdminStates.waiting_trigger_query)
    await message.answer(
        "5/5 — Endi bonus qoidalarini qo'shamiz.\n\n"
        "🎁 <b>Bonus qoidasi:</b> qaysi mahsulotdan qancha olinsa, qaysi bonus beriladi.\n"
        "<i>Masalan: 1 kg bodom uniga 100 gr eritritol.</i>\n\n"
        "Avval <b>asosiy mahsulot</b> nomini (yoki bir qismini) yozing:",
        parse_mode="HTML",
    )


async def _promo_product_picker(message: Message, query: str, prefix: str) -> bool:
    """Show up to 8 matching products as buttons. Returns False when nothing
    matched, so the caller can keep the same state and let them retype."""
    products, _ = await search_products(query, page=0, per_page=8)
    if not products:
        await message.answer("❌ Hech narsa topilmadi. Boshqa nom yozing:")
        return False
    lang = await get_user_language(message.from_user.id)
    rows = [[InlineKeyboardButton(
        text=f"{_promo_pname(p, lang)} ({get_unit_name(p['unit'], lang)})",
        callback_data=f"{prefix}{p['id']}",
    )] for p in products]
    rows.append([InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="admin:promo")])
    await message.answer("Mahsulotni tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    return True


@router.message(PromoAdminStates.waiting_trigger_query, F.text)
async def promo_trigger_query(message: Message, state: FSMContext):
    await _promo_product_picker(message, (message.text or "").strip(), "admin:promo:trig:")


@router.callback_query(F.data.startswith("admin:promo:trig:"))
async def promo_trigger_chosen(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    product_id = int(callback.data.split(":")[3])
    product = await get_product(product_id)
    lang = (await state.get_data()).get("lang", "uz")
    await state.update_data(rule_trigger_id=product_id, rule_trigger_name=_promo_pname(product, lang))
    await state.set_state(PromoAdminStates.waiting_trigger_qty)
    await callback.message.edit_text(
        f"✅ Asosiy mahsulot: <b>{_promo_pname(product, lang)}</b>\n\n"
        f"Necha <b>{get_unit_name(product['unit'], lang)}</b> olinganda bonus berilsin? "
        f"(raqam kiriting, masalan: 1)",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(PromoAdminStates.waiting_trigger_qty, F.text)
async def promo_trigger_qty(message: Message, state: FSMContext):
    try:
        qty = float((message.text or "").strip().replace(",", "."))
        if qty <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Musbat raqam kiriting (masalan: 1 yoki 0.5).")
        return
    await state.update_data(rule_trigger_qty=qty)
    await state.set_state(PromoAdminStates.waiting_bonus_query)
    await message.answer("🎁 Endi <b>bonus mahsulot</b> nomini yozing:", parse_mode="HTML")


@router.message(PromoAdminStates.waiting_bonus_query, F.text)
async def promo_bonus_query(message: Message, state: FSMContext):
    await _promo_product_picker(message, (message.text or "").strip(), "admin:promo:bon:")


@router.callback_query(F.data.startswith("admin:promo:bon:"))
async def promo_bonus_chosen(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    product_id = int(callback.data.split(":")[3])
    product = await get_product(product_id)
    lang = (await state.get_data()).get("lang", "uz")
    await state.update_data(rule_bonus_id=product_id, rule_bonus_name=_promo_pname(product, lang))
    await state.set_state(PromoAdminStates.waiting_bonus_amount)
    await callback.message.edit_text(
        f"✅ Bonus mahsulot: <b>{_promo_pname(product, lang)}</b>\n\n"
        f"Qancha bonus berilsin? Miqdor va birlikni birga yozing.\n"
        f"<i>Masalan: 100 gr — yoki 0.5 kg, 2 dona</i>\n\n"
        f"Mumkin birliklar: {', '.join(PROMO_BONUS_UNITS)}",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(PromoAdminStates.waiting_bonus_amount, F.text)
async def promo_bonus_amount(message: Message, state: FSMContext):
    """Parses "100 gr" / "0.5 kg" / "2 dona" in one go — two separate prompts
    for the number and the unit would double the length of an already long
    wizard, and this shape is how the owner writes it anyway."""
    import promotions

    raw = (message.text or "").strip().lower().replace(",", ".")
    parts = raw.split()
    amount, unit = None, None
    if len(parts) >= 2:
        try:
            amount = float(parts[0])
            unit = parts[1]
        except ValueError:
            amount = None
    if amount is None or amount <= 0 or unit not in PROMO_BONUS_UNITS:
        await message.answer(
            "Miqdor va birlikni birga yozing — masalan: <b>100 gr</b>\n"
            f"Mumkin birliklar: {', '.join(PROMO_BONUS_UNITS)}",
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    bonus_product = await get_product(data["rule_bonus_id"])
    rules = list(data.get("promo_rules") or [])
    rules.append({
        "trigger_product_id": data["rule_trigger_id"],
        "trigger_quantity": data["rule_trigger_qty"],
        "bonus_product_id": data["rule_bonus_id"],
        "bonus_amount": amount,
        "bonus_unit": unit,
        "bonus_stock_qty": promotions.to_stock_qty(amount, unit, bonus_product.get("unit") or "kg"),
        "max_bonus_amount": None,
        "_label": f"{data['rule_trigger_qty']:g} × {data['rule_trigger_name']} → {amount:g} {unit} {data['rule_bonus_name']}",
    })
    await state.update_data(promo_rules=rules)

    listing = "\n".join(f"   • {r['_label']}" for r in rules)
    await state.set_state(PromoAdminStates.waiting_trigger_query)
    await message.answer(
        f"✅ Qoida qo'shildi.\n\n🎁 <b>Hozirgi qoidalar:</b>\n{listing}\n\n"
        f"Yana qoida qo'shish uchun keyingi <b>asosiy mahsulot</b> nomini yozing, "
        f"yoki tugatish uchun quyidagi tugmani bosing.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Tugatish va saqlash", callback_data="admin:promo:save"),
        ]]),
    )


@router.callback_query(F.data == "admin:promo:save")
async def promo_save(callback: CallbackQuery, state: FSMContext):
    """Saves the campaign INACTIVE. Going live is a separate, deliberate tap —
    same as the website, so a half-finished draft never reaches buyers."""
    if not is_admin(callback.from_user.id):
        return
    data = await state.get_data()
    rules = data.get("promo_rules") or []
    if not rules:
        await callback.answer("Kamida bitta bonus qoidasi qo'shing", show_alert=True)
        return

    promo_id = await create_promotion(
        name=data["promo_name"],
        name_ru=None,
        conditions=data.get("promo_conditions"),
        conditions_ru=None,
        days=data["promo_days"],
        image_url=data.get("promo_image_url"),
    )
    await set_promotion_bonuses(promo_id, [{k: v for k, v in r.items() if not k.startswith("_")} for r in rules])
    await state.clear()

    lang = await get_user_language(callback.from_user.id)
    text, keyboard = await _render_promo_admin(lang)
    await callback.message.edit_text(
        "✅ Aksiya saqlandi (hali boshlanmagan).\n\n" + text,
        reply_markup=keyboard, parse_mode="HTML",
    )
    await callback.answer("✅ Saqlandi")


# ───────────────────── swap the image on a live campaign ────────────────────

@router.callback_query(F.data.startswith("admin:promo:image:"))
async def promo_image_update_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    promo_id = int(callback.data.split(":")[3])
    lang = await get_user_language(callback.from_user.id)
    await state.set_state(PromoAdminStates.waiting_image_update)
    await state.update_data(lang=lang, promo_image_target=promo_id)
    await callback.message.edit_text(
        "🖼 Yangi rasmni yuboring.\n\nRasmni butunlay olib tashlash uchun /skip yoki quyidagi tugma.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🗑 Rasmni olib tashlash", callback_data="admin:promo:imgclear"),
        ]]),
    )
    await callback.answer()


@router.callback_query(F.data == "admin:promo:imgclear")
async def promo_image_clear_button(callback: CallbackQuery, state: FSMContext):
    """Button twin of typing /skip at the image-swap step."""
    import promotions

    if not is_admin(callback.from_user.id):
        return
    data = await state.get_data()
    target = data.get("promo_image_target")
    if not target:
        await callback.answer("❌", show_alert=True)
        return
    await update_promotion(target, image_url=None)
    await promotions.refresh()
    await state.clear()
    text, keyboard = await _render_promo_admin(data.get("lang", "uz"))
    await callback.message.edit_text("🗑 Rasm olib tashlandi.\n\n" + text,
                                     reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.message(PromoAdminStates.waiting_image_update, F.photo)
async def promo_image_update_received(message: Message, state: FSMContext):
    import promotions

    data = await state.get_data()
    try:
        image_url = await _promo_store_photo(message)
    except Exception:
        logger.exception("Aksiya photo update failed")
        await message.answer("⚠️ Rasmni saqlab bo'lmadi. Qayta yuboring yoki /skip bosing.")
        return
    await update_promotion(data["promo_image_target"], image_url=image_url)
    await promotions.refresh()
    await state.clear()
    text, keyboard = await _render_promo_admin(data.get("lang", "uz"))
    await message.answer("✅ Rasm yangilandi.\n\n" + text, reply_markup=keyboard, parse_mode="HTML")


@router.message(PromoAdminStates.waiting_image_update, F.text == "/skip")
async def promo_image_update_cleared(message: Message, state: FSMContext):
    import promotions

    data = await state.get_data()
    await update_promotion(data["promo_image_target"], image_url=None)
    await promotions.refresh()
    await state.clear()
    text, keyboard = await _render_promo_admin(data.get("lang", "uz"))
    await message.answer("🗑 Rasm olib tashlandi.\n\n" + text, reply_markup=keyboard, parse_mode="HTML")


@router.message(PromoAdminStates.waiting_image_update)
async def promo_image_update_invalid(message: Message, state: FSMContext):
    await message.answer("Rasm yuboring yoki /skip bosing.")


# ===== BULK DISCOUNT =====

def _bulk_clean_int(text: str) -> int:
    """Strip spaces/commas and parse to int — raises ValueError on bad input."""
    return int(float(text.strip().replace(" ", "").replace(",", ".")))


@router.callback_query(F.data == "admin:bulk_discount")
async def start_bulk_discount(callback: CallbackQuery, state: FSMContext):
    """Step 1 — pick a category."""
    if not is_admin(callback.from_user.id):
        return
    lang = await get_user_language(callback.from_user.id)
    await state.update_data(lang=lang)

    await callback.message.edit_text(
        get_text("bulk_discount_pick_category", lang),
        reply_markup=category_select_keyboard(lang, prefix="bulkcat"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("bulkcat:"))
async def bulk_discount_category(callback: CallbackQuery, state: FSMContext):
    """Step 2 — show count + prompt for percent."""
    if not is_admin(callback.from_user.id):
        return
    category = callback.data.split(":", 1)[1]
    if category not in CATEGORIES:
        await callback.answer("❌", show_alert=True)
        return
    lang = await get_user_language(callback.from_user.id)

    count = await count_active_products_in_category(category)
    if count == 0:
        await callback.message.edit_text(
            get_text("bulk_discount_no_products", lang),
            reply_markup=admin_panel_keyboard(lang),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    await state.update_data(category=category, lang=lang, product_count=count)
    await state.set_state(AdminStates.bulk_discount_percent)

    await callback.message.edit_text(
        get_text("bulk_discount_enter_percent", lang,
            category=get_category_name(category, lang),
            count=count,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.bulk_discount_percent)
async def bulk_discount_percent(message: Message, state: FSMContext):
    """Step 3 — validate percent. 0 → confirm clear; >0 → ask for days."""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    lang = data.get("lang", "uz")

    try:
        percent = _bulk_clean_int(message.text or "")
        if percent < 0 or percent > 100:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer(get_text("invalid_discount", lang))
        return

    await state.update_data(percent=percent)

    if percent == 0:
        # Skip the days prompt — we're clearing.
        await state.set_state(AdminStates.bulk_discount_confirm)
        await message.answer(
            get_text("bulk_discount_clear_confirm", lang,
                category=get_category_name(data["category"], lang),
                count=data["product_count"],
            ),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text=get_text("btn_yes", lang), callback_data="bulkdisc:apply"),
                    InlineKeyboardButton(text=get_text("btn_no", lang), callback_data="bulkdisc:cancel"),
                ],
            ]),
            parse_mode="HTML",
        )
        return

    await state.set_state(AdminStates.bulk_discount_days)
    await message.answer(get_text("enter_discount_days", lang))


@router.message(AdminStates.bulk_discount_days)
async def bulk_discount_days(message: Message, state: FSMContext):
    """Step 4 — validate days, then show preview/confirm."""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    lang = data.get("lang", "uz")

    try:
        days = _bulk_clean_int(message.text or "")
        if days < 0 or days > 365:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer(get_text("invalid_discount_days", lang))
        return

    if days == 0:
        discount_until = None
        validity = get_text("bulk_discount_validity_forever", lang)
    else:
        from datetime import datetime, timedelta, timezone
        discount_until = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=days)
        validity = get_text("bulk_discount_validity_until", lang,
                            date=discount_until.strftime("%d.%m.%Y %H:%M"))

    await state.update_data(days=days, discount_until_iso=discount_until.isoformat() if discount_until else None)
    await state.set_state(AdminStates.bulk_discount_confirm)

    await message.answer(
        get_text("bulk_discount_confirm", lang,
            category=get_category_name(data["category"], lang),
            count=data["product_count"],
            percent=data["percent"],
            validity=validity,
        ),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=get_text("btn_yes", lang), callback_data="bulkdisc:apply"),
                InlineKeyboardButton(text=get_text("btn_no", lang), callback_data="bulkdisc:cancel"),
            ],
        ]),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "bulkdisc:apply", AdminStates.bulk_discount_confirm)
async def bulk_discount_apply(callback: CallbackQuery, state: FSMContext):
    """Final step — execute the bulk update."""
    if not is_admin(callback.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    lang = data.get("lang", "uz")
    category = data["category"]
    percent = data["percent"]

    discount_until = None
    if data.get("discount_until_iso"):
        from datetime import datetime
        discount_until = datetime.fromisoformat(data["discount_until_iso"])

    updated = await bulk_set_category_discount(category, percent, discount_until)
    await state.clear()

    await callback.message.edit_text(
        get_text("bulk_discount_done", lang, count=updated),
        reply_markup=admin_panel_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "bulkdisc:cancel", AdminStates.bulk_discount_confirm)
async def bulk_discount_cancel(callback: CallbackQuery, state: FSMContext):
    lang = (await state.get_data()).get("lang", "uz")
    await state.clear()
    await callback.message.edit_text(
        get_text("admin_panel", lang),
        reply_markup=admin_panel_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()


# ===== EXCEL REPORT =====

@router.callback_query(F.data == "admin:excel")
async def show_excel_period(callback: CallbackQuery):
    """Show period picker for the Excel orders report."""
    if not is_admin(callback.from_user.id):
        return
    lang = await get_user_language(callback.from_user.id)

    def label(period: str) -> str:
        return get_text(f"stats_period_{period}", lang)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=label("today"), callback_data="admin:excel:today"),
            InlineKeyboardButton(text=label("7d"),    callback_data="admin:excel:7d"),
        ],
        [
            InlineKeyboardButton(text=label("30d"),   callback_data="admin:excel:30d"),
            InlineKeyboardButton(text=label("all"),   callback_data="admin:excel:all"),
        ],
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="admin_panel")],
    ])
    await callback.message.edit_text(
        get_text("excel_pick_period", lang),
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin:excel:"))
async def send_excel_report(callback: CallbackQuery, bot: Bot):
    """Build and send the .xlsx file as a document."""
    if not is_admin(callback.from_user.id):
        return
    period = callback.data.split(":", 2)[2]
    if period not in ("today", "7d", "30d", "all"):
        period = "all"
    lang = await get_user_language(callback.from_user.id)

    # Acknowledge fast and show "generating..." while we build the file.
    try:
        await callback.message.edit_text(get_text("excel_generating", lang), parse_mode="HTML")
    except Exception:
        pass
    await callback.answer()

    import logging
    logger = logging.getLogger(__name__)

    try:
        from reports import generate_orders_excel, PERIOD_LABELS
        buf, filename = await generate_orders_excel(period=period, lang=lang)
        # Empty period — file is still valid (just headers); show a hint instead.
        from database import get_orders_for_export
        orders = await get_orders_for_export(period)
        if not orders:
            await callback.message.edit_text(
                get_text("excel_empty", lang),
                reply_markup=admin_panel_keyboard(lang),
                parse_mode="HTML",
            )
            return

        from aiogram.types import BufferedInputFile
        period_label = PERIOD_LABELS.get(period, {}).get(lang, period)
        await bot.send_document(
            chat_id=callback.from_user.id,
            document=BufferedInputFile(buf.read(), filename=filename),
            caption=get_text("excel_caption", lang, period=period_label),
            parse_mode="HTML",
        )
        # Replace the "generating..." with the panel so the admin can keep navigating
        try:
            await callback.message.edit_text(
                get_text("admin_panel", lang),
                reply_markup=admin_panel_keyboard(lang),
                parse_mode="HTML",
            )
        except Exception:
            pass
    except Exception as exc:
        logger.exception("Excel report failed: %s", exc)
        try:
            await callback.message.edit_text(
                get_text("excel_failed", lang),
                reply_markup=admin_panel_keyboard(lang),
                parse_mode="HTML",
            )
        except Exception:
            pass


# ===== MANUAL ORDER ENTRY =====

import re as _re

_PHONE_RE = _re.compile(r"^\+?998\d{9}$")


@router.callback_query(F.data == "admin:manual_order")
async def manual_order_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    lang = await get_user_language(callback.from_user.id)
    await state.update_data(lang=lang)
    await state.set_state(AdminStates.manual_name)
    await callback.message.edit_text(
        get_text("manual_order_intro", lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin:b2b_menu")
async def b2b_submenu(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    lang = await get_user_language(callback.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Optom Eritritol", callback_data="admin:b2b_eritritol")],
        [InlineKeyboardButton(text="📦 Boshqa Maxsulotlar (B2B)", callback_data="admin:b2b_order")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_panel")]
    ])
    await callback.message.edit_text("B2B Savdo turini tanlang:", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "admin:b2b_order")
async def b2b_order_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    lang = await get_user_language(callback.from_user.id)
    await state.update_data(lang=lang, order_type="b2b")
    await state.set_state(AdminStates.b2b_company)
    await callback.message.edit_text(
        get_text("b2b_order_intro", lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin:b2b_eritritol")
async def b2b_eritritol_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    lang = await get_user_language(callback.from_user.id)
    await state.update_data(lang=lang, order_type="b2b_eritritol")
    await state.set_state(AdminStates.b2b_eritritol_address)
    await callback.message.edit_text(
        get_text("b2b_eritritol_address", lang),
        parse_mode="HTML",
        reply_markup=admin_cancel_keyboard(lang)
    )
    await callback.answer()


@router.message(AdminStates.b2b_eritritol_address, F.text)
async def b2b_eritritol_address(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    data = await state.get_data()
    lang = data.get("lang", "uz")
    await state.update_data(address=message.text)
    await state.set_state(AdminStates.b2b_eritritol_phone)
    await message.answer(get_text("b2b_eritritol_phone", lang), reply_markup=admin_cancel_keyboard(lang))

@router.message(AdminStates.b2b_eritritol_phone, F.text)
async def b2b_eritritol_phone(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    data = await state.get_data()
    lang = data.get("lang", "uz")
    await state.update_data(phone=message.text)
    await state.set_state(AdminStates.b2b_eritritol_quantity)
    await message.answer(get_text("b2b_eritritol_quantity", lang), reply_markup=admin_cancel_keyboard(lang))

@router.message(AdminStates.b2b_eritritol_quantity, F.text)
async def b2b_eritritol_quantity(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    data = await state.get_data()
    lang = data.get("lang", "uz")
    try:
        qty = float(message.text.replace(',', '.'))
    except ValueError:
        return
    await state.update_data(quantity=qty)
    await state.set_state(AdminStates.b2b_eritritol_total)
    await message.answer(get_text("b2b_eritritol_total", lang), reply_markup=admin_cancel_keyboard(lang))

@router.message(AdminStates.b2b_eritritol_total, F.text)
async def b2b_eritritol_total(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    data = await state.get_data()
    lang = data.get("lang", "uz")
    try:
        total = float(message.text.replace(',', '.'))
    except ValueError:
        return
    await state.update_data(total=total)
    await state.set_state(AdminStates.b2b_eritritol_confirm)
    
    data = await state.get_data()
    text = get_text("b2b_eritritol_confirm", lang,
        address=html.escape(data["address"]),
        phone=html.escape(data["phone"]),
        quantity=data["quantity"],
        total=_fmt_num(total),
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=get_text("btn_yes", lang), callback_data="b2beritritol:yes"),
            InlineKeyboardButton(text=get_text("btn_no", lang), callback_data="b2beritritol:no"),
        ],
    ])
    await message.answer(text, reply_markup=kb, parse_mode="HTML")

@router.callback_query(F.data.startswith("b2beritritol:"), AdminStates.b2b_eritritol_confirm)
async def b2b_eritritol_confirm(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split(":")[1]
    data = await state.get_data()
    lang = data.get("lang", "uz")
    
    if action == "no":
        await state.clear()
        await callback.message.edit_text("❌", reply_markup=admin_panel_keyboard(lang))
        await callback.answer()
        return

    order_id = await add_b2b_eritritol_order(
        admin_user_id=callback.from_user.id,
        address=data["address"],
        phone=data["phone"],
        quantity=data["quantity"],
        total=data["total"]
    )
    await state.clear()
    await callback.message.edit_text(get_text("b2b_saved", lang, order_id=order_id), reply_markup=admin_panel_keyboard(lang))
    await callback.answer()

@router.message(AdminStates.b2b_company, F.text)
async def b2b_company_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    name = (message.text or "").strip()
    if not name:
        return
    data = await state.get_data()
    lang = data.get("lang", "uz")
    # Reuses the manual-order category/product picker states below — they
    # only touch `items`/`lang`/`pending_*`, never phone/address, so they
    # work unchanged for the B2B flow.
    await state.update_data(name=name, items=[])
    await state.set_state(AdminStates.manual_pick_category)
    await _show_manual_category_picker(message, state, lang)


@router.message(AdminStates.manual_name, F.text)
async def manual_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    name = (message.text or "").strip()
    if not name:
        return
    data = await state.get_data()
    lang = data.get("lang", "uz")
    await state.update_data(name=name)
    await state.set_state(AdminStates.manual_phone)
    await message.answer(get_text("manual_enter_phone", lang), reply_markup=admin_cancel_keyboard(lang))


@router.message(AdminStates.manual_phone, F.text)
async def manual_phone(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    phone = (message.text or "").strip().replace(" ", "").replace("-", "")
    if not _PHONE_RE.match(phone):
        await message.answer(get_text("invalid_phone", lang))
        return
    await state.update_data(phone=phone)
    await state.set_state(AdminStates.manual_address)
    await message.answer(get_text("manual_enter_address", lang), reply_markup=admin_cancel_keyboard(lang))


@router.message(AdminStates.manual_address, F.text)
async def manual_address(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    address = (message.text or "").strip()
    if not address:
        return
    await state.update_data(address=address, items=[])
    await state.set_state(AdminStates.manual_pick_category)
    await _show_manual_category_picker(message, state, lang)


def _fmt_price(value: float | int) -> str:
    return f"{int(value):,}".replace(",", " ")


def _items_total(items: list[dict]) -> float:
    return sum(float(it["price"]) * float(it["quantity"]) for it in items)


async def _show_manual_category_picker(target, state: FSMContext, lang: str) -> None:
    """Show categories + a Finish button (when at least one item is in the cart).
    `target` may be a Message (initial entry) or a CallbackQuery message (loop)."""
    data = await state.get_data()
    items: list[dict] = data.get("items", []) or []

    rows: list[list[InlineKeyboardButton]] = []
    for i in range(0, len(CATEGORIES), 2):
        row = []
        for cat in CATEGORIES[i:i + 2]:
            row.append(InlineKeyboardButton(
                text=get_category_name(cat, lang),
                callback_data=f"mancat:{cat}",
            ))
        rows.append(row)

    if items:
        total_str = _fmt_price(_items_total(items))
        rows.append([InlineKeyboardButton(
            text=get_text("btn_manual_finish", lang, count=len(items), total=total_str),
            callback_data="manualfinish",
        )])
        rows.append([InlineKeyboardButton(
            text=get_text("btn_manual_remove_last", lang),
            callback_data="manualpop",
        )])

    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    text = get_text("manual_pick_category", lang)
    if hasattr(target, "edit_text"):
        try:
            await target.edit_text(text, reply_markup=kb, parse_mode="HTML")
            return
        except Exception:
            pass
    await target.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("mancat:"), AdminStates.manual_pick_category)
async def manual_pick_category(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    cat = callback.data.split(":", 1)[1]
    if cat not in CATEGORIES:
        await callback.answer("❌")
        return
    data = await state.get_data()
    lang = data.get("lang", "uz")

    products, _total = await get_products_by_category(cat, page=0, per_page=50)
    if not products:
        await callback.answer(get_text("manual_no_products_in_cat", lang), show_alert=True)
        return

    rows = []
    for p in products:
        d = active_discount(p.get("discount_percent"), p.get("discount_until"))
        unit_price = effective_price(p["price"], d, p.get("discount_until"))
        badge = f" 🔥-{d}%" if d > 0 else ""
        rows.append([InlineKeyboardButton(
            text=f"{p['name']} — {_fmt_price(unit_price)} so'm{badge}",
            callback_data=f"manprod:{p['id']}",
        )])
    rows.append([InlineKeyboardButton(
        text=get_text("btn_back", lang),
        callback_data="manualback",
    )])

    await state.set_state(AdminStates.manual_pick_product)
    await callback.message.edit_text(
        get_text("manual_pick_product", lang),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "manualback", AdminStates.manual_pick_product)
async def manual_back_to_categories(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    await state.set_state(AdminStates.manual_pick_category)
    await _show_manual_category_picker(callback.message, state, lang)
    await callback.answer()


@router.callback_query(F.data.startswith("manprod:"), AdminStates.manual_pick_product)
async def manual_pick_product(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    try:
        pid = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("❌")
        return
    product = await get_product(pid)
    if not product:
        await callback.answer("❌")
        return

    data = await state.get_data()
    lang = data.get("lang", "uz")
    d = active_discount(product.get("discount_percent"), product.get("discount_until"))
    unit_price = effective_price(product["price"], d, product.get("discount_until"))

    await state.update_data(
        pending_product_id=pid,
        pending_product_name=product["name"],
        pending_product_price=unit_price,
        pending_product_unit=product.get("unit") or "",
    )
    await state.set_state(AdminStates.manual_quantity)
    await callback.message.edit_text(
        get_text("manual_enter_quantity", lang,
                 name=product["name"],
                 price=_fmt_price(unit_price),
                 unit=get_display_unit(product.get("unit") or "", lang)),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.manual_quantity, F.text)
async def manual_quantity(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    lang = data.get("lang", "uz")
    raw = (message.text or "").strip().replace(",", ".").replace(" ", "")
    try:
        qty = float(raw)
        if qty <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer(get_text("manual_invalid_quantity", lang), reply_markup=admin_cancel_keyboard(lang))
        return

    # Quantity captured — hop to the optional per-line discount step.
    await state.update_data(pending_qty=qty)
    await state.set_state(AdminStates.manual_discount)
    await message.answer(
        get_text("manual_enter_discount", lang,
                 name=data.get("pending_product_name") or "",
                 price=_fmt_price(float(data.get("pending_product_price") or 0))),
        parse_mode="HTML",
    )


@router.message(AdminStates.manual_discount, F.text)
async def manual_discount(message: Message, state: FSMContext):
    """Optional per-line discount — applies only to this manual/B2B order,
    leaves the product's catalog price untouched. Accepts either a percent
    (0-100, e.g. "8") or the final so'm price directly (e.g. "92000" for a
    100 000 so'm item — owner request 2026-08-01: entering the actual sold
    price is often easier than computing the percent by hand). A plain
    number >100 is read as an absolute price rather than a percent, since no
    real product is priced at 100 so'm or under. 0 / /skip / - mean no discount."""
    if not is_admin(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    lang = data.get("lang", "uz")
    raw = (message.text or "").strip().lower()
    base_price = float(data.get("pending_product_price") or 0)

    if raw in ("/skip", "skip", "-", ""):
        d = 0
        final_price = base_price
    else:
        is_percent_syntax = "%" in raw
        try:
            num = float(raw.replace(",", ".").replace("%", "").replace(" ", "").strip())
            if num < 0:
                raise ValueError
        except (ValueError, AttributeError):
            await message.answer(get_text("manual_invalid_discount", lang), reply_markup=admin_cancel_keyboard(lang))
            return

        if is_percent_syntax or num <= 100:
            if num > 100:
                await message.answer(get_text("manual_invalid_discount", lang), reply_markup=admin_cancel_keyboard(lang))
                return
            d = int(num)
            final_price = base_price * (100 - d) / 100 if d > 0 else base_price
        else:
            # Absolute final price in so'm.
            if base_price > 0 and num > base_price:
                await message.answer(get_text(
                    "manual_discount_price_too_high", lang,
                    entered=_fmt_price(num), base=_fmt_price(base_price),
                ))
                return
            final_price = num
            d = round((base_price - final_price) / base_price * 100) if base_price > 0 else 0

    pid = data.get("pending_product_id")
    name = data.get("pending_product_name")
    unit = data.get("pending_product_unit") or ""
    qty = float(data.get("pending_qty") or 0)

    items: list[dict] = list(data.get("items") or [])
    item: dict = {
        "product_id": pid,
        "name": name,
        "quantity": qty,
        "price": final_price,
        "unit": unit,
    }
    # Per-line discount applies to this order only; keeping original_price +
    # discount_percent on the item lets the order card render the 🔥 badge
    # and feed into the total-saved line.
    if d > 0:
        item["original_price"] = base_price
        item["discount_percent"] = d
    items.append(item)
    await state.update_data(items=items, pending_qty=None)

    line_total = qty * final_price
    qty_str = int(qty) if float(qty).is_integer() else f"{qty:.2f}"
    if d > 0:
        body = get_text("manual_item_added_discount", lang,
                        name=name, qty=qty_str, unit=get_display_unit(unit, lang),
                        old=_fmt_price(base_price), price=_fmt_price(final_price),
                        percent=d, line_total=_fmt_price(line_total))
    else:
        body = get_text("manual_item_added", lang,
                        name=name, qty=qty_str, unit=get_display_unit(unit, lang),
                        price=_fmt_price(final_price), line_total=_fmt_price(line_total))
    await message.answer(body, parse_mode="HTML")

    # Loop back to category picker so the admin can keep adding.
    await state.set_state(AdminStates.manual_pick_category)
    await _show_manual_category_picker(message, state, lang)


@router.callback_query(F.data == "manualpop", AdminStates.manual_pick_category)
async def manual_remove_last(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    items: list[dict] = list(data.get("items") or [])
    if items:
        items.pop()
        await state.update_data(items=items)
        await callback.answer(get_text("manual_last_removed", lang))
    await _show_manual_category_picker(callback.message, state, lang)


@router.callback_query(F.data == "manualfinish", AdminStates.manual_pick_category)
async def manual_finish_items(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    items: list[dict] = data.get("items") or []
    if not items:
        await callback.answer(get_text("manual_no_items_yet", lang), show_alert=True)
        return

    await state.update_data(total=_items_total(items))

    if data.get("order_type") == "b2b":
        await state.set_state(AdminStates.b2b_confirm)
        items_block = "\n".join(
            f"• {html.escape(it['name'])} — "
            f"{(int(it['quantity']) if float(it['quantity']).is_integer() else it['quantity'])} "
            f"{get_display_unit(it.get('unit') or '', lang)} × {_fmt_price(it['price'])} = "
            f"<b>{_fmt_price(float(it['quantity']) * float(it['price']))}</b>"
            for it in items
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=get_text("btn_yes", lang), callback_data="b2bconfirm:yes"),
            InlineKeyboardButton(text=get_text("btn_no", lang), callback_data="b2bconfirm:no"),
        ]])
        await callback.message.edit_text(
            get_text("b2b_confirm", lang,
                company=html.escape(data["name"]),
                items=items_block,
                total=_fmt_price(_items_total(items)),
            ),
            reply_markup=kb,
            parse_mode="HTML",
        )
        await callback.answer()
        return

    # Returning from "Yana mahsulot qo'shish" — payment/delivery/status were
    # already picked on a prior pass, so skip straight back to confirm
    # instead of re-asking them.
    if data.get("payment") and data.get("delivery") and data.get("status"):
        await _show_manual_confirm(callback.message, state, lang)
        await callback.answer()
        return

    await state.set_state(AdminStates.manual_payment)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_pay_cash", lang), callback_data="manualpay:cash")],
        [InlineKeyboardButton(text=get_text("btn_pay_online", lang), callback_data="manualpay:online")],
    ])
    await callback.message.edit_text(
        get_text("choose_payment", lang),
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("manualpay:"), AdminStates.manual_payment)
async def manual_payment(callback: CallbackQuery, state: FSMContext):
    payment = callback.data.split(":", 1)[1]
    if payment not in ("cash", "online"):
        await callback.answer("❌")
        return
    data = await state.get_data()
    lang = data.get("lang", "uz")
    await state.update_data(payment=payment)
    await state.set_state(AdminStates.manual_delivery)
    # Manual orders bypass the Tashkent geofence — admin saw the address text
    # already, so let them pick from the full list of methods.
    options = [
        ("self", "btn_delivery_self"),
        ("yandex_taxi", "btn_delivery_yandex_taxi"),
        ("yandex_market", "btn_delivery_yandex_market"),
        ("bts", "btn_delivery_bts"),
        ("emu", "btn_delivery_emu"),
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text(label_key, lang), callback_data=f"manualdel:{code}")]
        for code, label_key in options
    ])
    await callback.message.edit_text(
        get_text("choose_delivery", lang),
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("manualdel:"), AdminStates.manual_delivery)
async def manual_delivery(callback: CallbackQuery, state: FSMContext):
    method = callback.data.split(":", 1)[1]
    data = await state.get_data()
    lang = data.get("lang", "uz")
    await state.update_data(delivery=method)
    await state.set_state(AdminStates.manual_status)

    statuses = [
        ("pending",   "order_status_pending"),
        ("confirmed", "order_status_confirmed"),
        ("shipped",   "order_status_shipped"),
        ("delivered", "order_status_delivered"),
        ("cancelled", "order_status_cancelled"),
    ]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text(label_key, lang), callback_data=f"manualstatus:{code}")]
        for code, label_key in statuses
    ])
    await callback.message.edit_text(
        get_text("manual_choose_status", lang),
        reply_markup=kb,
        parse_mode="HTML",
    )
    await callback.answer()


async def _show_manual_confirm(target, state: FSMContext, lang: str) -> None:
    """Render the final 'Saqlaysizmi?' screen. `target` may be a Message
    (rarely) or a CallbackQuery message — reused both on first arrival
    (manual_status) and when looping back after adding more items
    (manualconfirm:addmore -> manualfinish)."""
    data = await state.get_data()
    await state.set_state(AdminStates.manual_confirm)

    pay_label = get_text("btn_pay_cash" if data["payment"] == "cash" else "btn_pay_online", lang)
    delivery_label = get_delivery_method_name(data["delivery"], lang)
    status_label = get_order_status(data["status"], lang)

    items: list[dict] = data.get("items") or []
    items_lines = []
    for it in items:
        qty = float(it["quantity"])
        qty_str = str(int(qty)) if qty.is_integer() else f"{qty:.2f}"
        line_total = qty * float(it["price"])
        items_lines.append(
            f"• {html.escape(it['name'])} — {qty_str} {get_display_unit(it.get('unit') or '', lang)} "
            f"× {_fmt_price(it['price'])} = <b>{_fmt_price(line_total)}</b>"
        )
    items_block = "\n".join(items_lines) if items_lines else "—"

    total_str = _fmt_price(_items_total(items))

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_manual_add_more", lang), callback_data="manualconfirm:addmore")],
        [
            InlineKeyboardButton(text=get_text("btn_yes", lang), callback_data="manualconfirm:yes"),
            InlineKeyboardButton(text=get_text("btn_no", lang), callback_data="manualconfirm:no"),
        ],
    ])
    text = get_text("manual_confirm", lang,
        name=html.escape(data["name"]),
        phone=html.escape(data["phone"]),
        address=html.escape(data["address"]),
        items=items_block,
        total=total_str,
        payment=pay_label,
        delivery=delivery_label,
        status=status_label,
    )
    if hasattr(target, "edit_text"):
        try:
            await target.edit_text(text, reply_markup=kb, parse_mode="HTML")
            return
        except Exception:
            pass
    await target.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data.startswith("manualstatus:"), AdminStates.manual_status)
async def manual_status(callback: CallbackQuery, state: FSMContext):
    status = callback.data.split(":", 1)[1]
    if status not in ("pending", "confirmed", "shipped", "delivered", "cancelled"):
        await callback.answer("❌")
        return
    data = await state.get_data()
    lang = data.get("lang", "uz")
    await state.update_data(status=status)
    await _show_manual_confirm(callback.message, state, lang)
    await callback.answer()


@router.callback_query(F.data == "manualconfirm:addmore", AdminStates.manual_confirm)
async def manual_confirm_add_more(callback: CallbackQuery, state: FSMContext):
    """Loop back to the category picker without losing name/phone/address/
    payment/delivery/status — so admins don't have to redo the whole manual
    order just to tack on one more product (owner request 2026-08-12)."""
    data = await state.get_data()
    lang = data.get("lang", "uz")
    await state.set_state(AdminStates.manual_pick_category)
    await _show_manual_category_picker(callback.message, state, lang)
    await callback.answer()


@router.callback_query(F.data == "manualconfirm:yes", AdminStates.manual_confirm)
async def manual_save(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    items: list[dict] = data.get("items") or []
    order_id = await add_manual_order(
        admin_user_id=callback.from_user.id,
        customer_name=data["name"],
        phone=data["phone"],
        address=data["address"],
        items_data=items,
        total=_items_total(items),
        payment_method=data["payment"],
        delivery_method=data["delivery"],
        status=data["status"],
    )
    await state.clear()
    await callback.message.edit_text(
        get_text("manual_saved", lang, order_id=order_id),
        reply_markup=admin_panel_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "manualconfirm:no", AdminStates.manual_confirm)
async def manual_cancel(callback: CallbackQuery, state: FSMContext):
    lang = (await state.get_data()).get("lang", "uz")
    await state.clear()
    await callback.message.edit_text(
        get_text("admin_panel", lang),
        reply_markup=admin_panel_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "b2bconfirm:yes", AdminStates.b2b_confirm)
async def b2b_save(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    items: list[dict] = data.get("items") or []
    order_id = await add_b2b_order(
        admin_user_id=callback.from_user.id,
        company_name=data["name"],
        items_data=items,
        total=_items_total(items),
    )
    await state.clear()
    await callback.message.edit_text(
        get_text("b2b_saved", lang, order_id=order_id),
        reply_markup=admin_panel_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "b2bconfirm:no", AdminStates.b2b_confirm)
async def b2b_cancel(callback: CallbackQuery, state: FSMContext):
    lang = (await state.get_data()).get("lang", "uz")
    await state.clear()
    await callback.message.edit_text(
        get_text("admin_panel", lang),
        reply_markup=admin_panel_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()


# ===== BROADCAST =====

@router.callback_query(F.data == "admin:broadcast")
async def start_broadcast(callback: CallbackQuery, state: FSMContext):
    """Start broadcast — ask for message"""
    if not is_admin(callback.from_user.id):
        return

    lang = await get_user_language(callback.from_user.id)
    await state.set_state(AdminStates.broadcast_message)
    await state.update_data(lang=lang)

    await callback.message.edit_text(
        get_text("broadcast_enter_message", lang),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(AdminStates.broadcast_message)
async def process_broadcast(message: Message, state: FSMContext):
    """Store broadcast text and ask for confirmation"""
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    lang = data.get("lang", "uz")
    broadcast_text = message.text.strip()

    users, total = await get_all_users(page=0, per_page=10000)

    await state.update_data(broadcast_text=broadcast_text)
    await state.set_state(AdminStates.broadcast_confirm)

    await message.answer(
        get_text("broadcast_confirm", lang, count=total),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=get_text("btn_yes", lang), callback_data="broadcast:yes"),
                InlineKeyboardButton(text=get_text("btn_no", lang), callback_data="broadcast:no"),
            ]
        ]),
        parse_mode="HTML"
    )


@router.callback_query(F.data == "broadcast:yes", AdminStates.broadcast_confirm)
async def confirm_broadcast(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Send the broadcast in parallel batches with classified results.

    Telegram caps bulk sends at ~30/sec across distinct chats. We batch 25 in
    parallel + sleep 1s between batches to stay under that ceiling. Failures
    are classified — TelegramForbiddenError / 'user is deactivated' /
    'chat not found' bucket as 'blocked' (expected); RetryAfter is honoured
    with one in-place retry; everything else is logged.
    """
    import asyncio
    import logging

    from aiogram.exceptions import (
        TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter,
    )

    logger = logging.getLogger(__name__)

    if not is_admin(callback.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    lang = data.get("lang", "uz")
    broadcast_text = data.get("broadcast_text", "")
    await state.clear()

    users, total = await get_all_users(page=0, per_page=10000)
    body = f"📢 {broadcast_text}"

    BATCH_SIZE = 25
    BATCH_PAUSE = 1.0  # seconds

    async def send_one(user_id: int) -> str:
        """Returns 'sent' / 'blocked' / 'failed' for a single recipient."""
        try:
            await bot.send_message(chat_id=user_id, text=body, parse_mode="HTML")
            return "sent"
        except TelegramForbiddenError:
            return "blocked"  # User blocked the bot
        except TelegramBadRequest as exc:
            msg = str(exc).lower()
            if "deactivated" in msg or "chat not found" in msg or "user_id_invalid" in msg:
                return "blocked"
            logger.warning("Broadcast send to %s failed: %s", user_id, exc)
            return "failed"
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            try:
                await bot.send_message(chat_id=user_id, text=body, parse_mode="HTML")
                return "sent"
            except Exception as retry_exc:
                logger.warning("Broadcast retry to %s failed: %s", user_id, retry_exc)
                return "failed"
        except Exception as exc:
            logger.warning("Broadcast send to %s failed: %s", user_id, exc)
            return "failed"

    sent = blocked = failed = 0

    # Initial progress edit (replaces the confirm-buttons message)
    await callback.message.edit_text(
        get_text("broadcast_progress", lang, sent=0, total=total),
        parse_mode="HTML",
    )
    await callback.answer()

    for i in range(0, total, BATCH_SIZE):
        batch = users[i:i + BATCH_SIZE]
        results = await asyncio.gather(*(send_one(u["user_id"]) for u in batch))
        for r in results:
            if r == "sent":
                sent += 1
            elif r == "blocked":
                blocked += 1
            else:
                failed += 1

        # Live progress — best-effort, ignore "message not modified" / edit rate-limits
        try:
            await callback.message.edit_text(
                get_text("broadcast_progress", lang,
                         sent=sent + blocked + failed, total=total),
                parse_mode="HTML",
            )
        except Exception:
            pass

        if i + BATCH_SIZE < total:
            await asyncio.sleep(BATCH_PAUSE)

    await callback.message.edit_text(
        get_text("broadcast_done_detailed", lang,
                 sent=sent, blocked=blocked, failed=failed, total=total),
        reply_markup=admin_panel_keyboard(lang),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "broadcast:no", AdminStates.broadcast_confirm)
async def cancel_broadcast(callback: CallbackQuery, state: FSMContext):
    """Cancel the broadcast"""
    data = await state.get_data()
    lang = data.get("lang", "uz")
    await state.clear()

    await callback.message.edit_text(
        get_text("admin_panel", lang),
        reply_markup=admin_panel_keyboard(lang),
        parse_mode="HTML"
    )
    await callback.answer()


# ===== LIST-TO-QUOTE (admin tool) =====
# Older clients send their order as a free-text list. This parses each line,
# fuzzy-matches it to a catalog product, prices it, and offers an "add to cart"
# button so the admin can place the order on the client's behalf.

_LIST_QUOTE_THRESHOLD = 0.45


def _lq_norm(s: str) -> str:
    """Normalize for matching: Cyrillic→Latin, lowercase, drop apostrophes and
    punctuation, collapse whitespace."""
    import re
    from translit import cyr_to_lat
    s = cyr_to_lat(s or "").lower()
    s = s.replace("'", "").replace("ʻ", "").replace("`", "")
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _lq_best(qn: str, products: list, norms: dict, ptoks: dict):
    """Best head-gated match → (product, score) or (None, 0.0).

    The most distinctive query token (the longest — usually the product head
    like 'bodom' / 'zigir' / 'gimalay') must appear in the product's name
    tokens: exactly, as a substring, or a close fuzzy match (≥0.8, so g/h and
    minor typos pass). Without this gate, shared filler like 'uni' or '500gr'
    matched the wrong product and absent items never showed as 'not found'."""
    import difflib
    qtokens = qn.split()
    if not qtokens:
        return None, 0.0
    head = max(qtokens, key=len)
    best, best_score = None, 0.0
    for p in products:
        head_ok = any(
            head == t or head in t or t in head
            or difflib.SequenceMatcher(None, head, t).ratio() >= 0.8
            for t in ptoks[p["id"]]
        )
        if not head_ok:
            continue
        score = difflib.SequenceMatcher(None, qn, norms[p["id"]]).ratio()
        if score > best_score:
            best, best_score = p, score
    return best, best_score


@router.callback_query(F.data == "admin:list_quote")
async def list_quote_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    lang = await get_user_language(callback.from_user.id)
    await state.set_state(AdminStates.list_quote_input)
    await state.update_data(lang=lang)
    await callback.message.edit_text(
        get_text("list_quote_prompt", lang),
        reply_markup=back_to_menu_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminStates.list_quote_input, F.text)
async def list_quote_process(message: Message, state: FSMContext):
    import re
    data = await state.get_data()
    lang = data.get("lang", "uz")

    lines = [ln.strip() for ln in (message.text or "").splitlines() if ln.strip()]
    if not lines:
        await message.answer(get_text("list_quote_empty", lang), parse_mode="HTML")
        return

    products = await get_all_active_products()
    norms = {p["id"]: _lq_norm(f"{p['name']} {p.get('name_ru') or ''}") for p in products}
    ptoks = {p["id"]: norms[p["id"]].split() for p in products}

    matched = []      # list of (product, qty)
    not_found = []
    for raw in lines:
        # strip leading bullets / numbering: "• ", "- ", "1) ", "1. "
        cleaned = re.sub(r"^\s*([•\-\*]|\d+[\.\)])\s*", "", raw)
        qn = _lq_norm(cleaned)
        best, best_score = _lq_best(qn, products, norms, ptoks)
        if best and best_score >= _LIST_QUOTE_THRESHOLD:
            matched.append((best, 1))
        else:
            not_found.append(raw)

    if not matched:
        await message.answer(get_text("list_quote_empty", lang), parse_mode="HTML")
        return

    text = "🧾\n\n"
    total = 0
    cart_items = []
    for p, qty in matched:
        discount = active_discount(p.get("discount_percent"), p.get("discount_until"))
        unit_price = effective_price(p["price"], discount, p.get("discount_until"))
        line_total = unit_price * qty
        total += line_total
        cart_items.append({"product_id": p["id"], "qty": qty})
        badge = f" 🔥-{discount}%" if discount > 0 else ""
        text += (f"✅ {html.escape(p['name'])} — {qty} × {int(unit_price):,}{badge}"
                 f" = {int(line_total):,}\n").replace(",", " ")
    text += get_text("list_quote_total", lang, total=f"{int(total):,}".replace(",", " "))
    if not_found:
        text += "\n" + get_text("list_quote_not_found_hdr", lang) + "\n"
        for nf in not_found:
            text += f"❓ {html.escape(nf)}\n"

    await state.update_data(lq_matched=cart_items, lq_not_found=not_found)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("list_quote_add_btn", lang), callback_data="listquote:add")],
        [InlineKeyboardButton(text=get_text("btn_back_to_menu", lang), callback_data="main_menu")],
    ])
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


@router.callback_query(F.data == "listquote:add")
async def list_quote_add(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    data = await state.get_data()
    lang = data.get("lang", "uz")
    matched = data.get("lq_matched") or []
    not_found = data.get("lq_not_found") or []
    # Aggregate duplicate lines, then SET (not increment) each product's qty so
    # re-running a list stays at the listed count instead of stacking up.
    from collections import defaultdict
    agg = defaultdict(float)
    for it in matched:
        agg[it["product_id"]] += it["qty"]
    added = 0
    for pid, qty in agg.items():
        try:
            await set_cart_product_quantity(callback.from_user.id, pid, qty)
            added += 1
        except Exception:
            pass
    await state.clear()

    text = get_text("list_quote_added", lang, n=added)
    # Surface the unmatched lines again so the admin knows what still needs
    # adding by hand, and give a one-tap path into search to find them.
    if not_found:
        text += "\n\n" + get_text("list_quote_manual_hdr", lang) + "\n"
        for nf in not_found:
            text += f"❓ {html.escape(nf)}\n"

    # Search-and-add is always offered so the admin can add more by hand even
    # when everything matched.
    rows = [
        [InlineKeyboardButton(text=get_text("list_quote_search_btn", lang), callback_data="search")],
        [InlineKeyboardButton(text=get_text("btn_cart", lang), callback_data="cart")],
        [InlineKeyboardButton(text=get_text("btn_back_to_menu", lang), callback_data="main_menu")],
    ]
    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML",
    )
    await callback.answer()


# --- ADD SET FLOW ---
class AddSetStates(StatesGroup):
    name = State()
    price = State()
    pick_category = State()
    pick_product = State()
    quantity = State()
    photo = State()

@router.callback_query(F.data == "seller:add_set")
async def add_set_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    lang = await get_user_language(callback.from_user.id)
    await state.clear()
    await state.update_data(lang=lang, items=[])
    await state.set_state(AddSetStates.name)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_panel")]
    ])
    await callback.message.edit_text("To'plam (Set) uchun qisqa nom kiriting:\n\nMasalan: <i>Keto Start To'plami</i>", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.message(AddSetStates.name, F.text)
async def add_set_name(message: Message, state: FSMContext):
    await state.update_data(set_name=message.text)
    await state.set_state(AddSetStates.price)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin_panel")]
    ])
    await message.answer(f"To'plam nomi saqlandi: <b>{message.text}</b>\n\nEndi to'plamning maxsus (skidkali) narxini kiriting:\n<i>Faqat son bilan, masalan: 120000</i>", reply_markup=kb, parse_mode="HTML")

@router.message(AddSetStates.price, F.text)
async def add_set_price(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("lang", "uz")
    try:
        price = float(message.text.replace(" ", "").replace(",", "."))
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Iltimos, to'g'ri narx kiriting (faqat son, masalan 150000):")
        return
    
    await state.update_data(set_price=price)
    await _show_set_category_picker(message, state, lang)

async def _show_set_category_picker(target, state: FSMContext, lang: str):
    data = await state.get_data()
    items = data.get("items", [])
    text = "Kategoriyani tanlang:\n"
    if items:
        text = "<b>Qo'shilgan mahsulotlar:</b>\n"
        for i, item in enumerate(items, 1):
            text += f"{i}. {item['name']} - {item['quantity']} dona\n"
        text += "\nYana qaysi kategoriyadan mahsulot qo'shamiz?"

    cats = await get_categories()
    kb = []
    for c in cats:
        c_name = c["name_uz"] if lang == "uz" else (c["name_ru"] or c["name_uz"])
        kb.append([InlineKeyboardButton(text=c_name, callback_data=f"setcat:{c['key']}")])
    
    if items:
        kb.append([InlineKeyboardButton(text="✅ To'plamni yig'ib bo'ldim", callback_data="set_finish_items")])
        if len(items) > 0:
            kb.append([InlineKeyboardButton(text="❌ Oxirgisini olib tashlash", callback_data="set_remove_last")])
    kb.append([InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="admin_panel")])
    
    markup = InlineKeyboardMarkup(inline_keyboard=kb)
    await state.set_state(AddSetStates.pick_category)
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    else:
        await target.answer(text, reply_markup=markup, parse_mode="HTML")

@router.callback_query(F.data.startswith("setcat:"), AddSetStates.pick_category)
async def set_pick_category(callback: CallbackQuery, state: FSMContext):
    cat = callback.data.split(":")[1]
    prods, _ = await search_products(query="", page=0, per_page=100)
    prods = [p for p in prods if p["category"] == cat]
    
    if not prods:
        await callback.answer("Bu kategoriyada mahsulot yo'q", show_alert=True)
        return
        
    lang = (await state.get_data()).get("lang", "uz")
    kb = []
    for p in prods:
        kb.append([InlineKeyboardButton(text=f"{p['name']} ({p['price']} so'm)", callback_data=f"setprod:{p['id']}")])
    kb.append([InlineKeyboardButton(text="🔙 Orqaga", callback_data="set_back_to_cats")])
    
    await state.set_state(AddSetStates.pick_product)
    await callback.message.edit_text("Mahsulotni tanlang:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@router.callback_query(F.data == "set_back_to_cats", AddSetStates.pick_product)
async def set_back_to_cats(callback: CallbackQuery, state: FSMContext):
    lang = (await state.get_data()).get("lang", "uz")
    await _show_set_category_picker(callback, state, lang)
    await callback.answer()

@router.callback_query(F.data.startswith("setprod:"), AddSetStates.pick_product)
async def set_pick_product(callback: CallbackQuery, state: FSMContext):
    pid = int(callback.data.split(":")[1])
    prod = await get_product(pid)
    if not prod:
        await callback.answer("Mahsulot topilmadi", show_alert=True)
        return
    
    await state.update_data(temp_prod_id=pid, temp_prod_name=prod["name"], temp_prod_price=prod["price"])
    await state.set_state(AddSetStates.quantity)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Orqaga", callback_data="set_back_to_cats")]])
    await callback.message.edit_text(f"Nechta <b>{prod['name']}</b> qo'shasiz?\n<i>Son kiriting:</i>", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@router.message(AddSetStates.quantity, F.text)
async def set_quantity(message: Message, state: FSMContext):
    try:
        qty = float(message.text.replace(",", "."))
        if qty <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Iltimos, miqdorni to'g'ri son ko'rinishida kiriting:")
        return
        
    data = await state.get_data()
    lang = data.get("lang", "uz")
    items = data.get("items", [])
    items.append({
        "product_id": data["temp_prod_id"],
        "name": data["temp_prod_name"],
        "quantity": qty,
        "price": data["temp_prod_price"]
    })
    await state.update_data(items=items)
    await _show_set_category_picker(message, state, lang)

@router.callback_query(F.data == "set_remove_last", AddSetStates.pick_category)
async def set_remove_last(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    items = data.get("items", [])
    if items:
        items.pop()
        await state.update_data(items=items)
    lang = data.get("lang", "uz")
    await _show_set_category_picker(callback, state, lang)
    await callback.answer("Oxirgi qo'shilgan mahsulot o'chirildi")

@router.callback_query(F.data == "set_finish_items", AddSetStates.pick_category)
async def set_finish_items(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    items = data.get("items", [])
    if not items:
        await callback.answer("Kamida 1 ta mahsulot qo'shing!", show_alert=True)
        return
        
    await state.set_state(AddSetStates.photo)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Rasmsiz saqlash", callback_data="set_skip_photo")],
        [InlineKeyboardButton(text="🔙 Bekor qilish", callback_data="admin_panel")]
    ])
    await callback.message.edit_text("To'plam uchun rasm yuboring (yoki rasmsiz saqlang):", reply_markup=kb)
    await callback.answer()

async def _save_set(target, state: FSMContext, photo_id: str | None):
    data = await state.get_data()
    set_name = data["set_name"]
    set_price = data["set_price"]
    items = data["items"]
    
    await create_set(name=set_name, set_price=set_price, items=items, image_file_id=photo_id, is_active=True)
    await state.clear()
    
    lang = data.get("lang", "uz")
    text = f"✅ To'plam muvaffaqiyatli saqlandi!\n\nNomi: <b>{set_name}</b>\nNarxi: {set_price} so'm"
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=admin_panel_keyboard(lang), parse_mode="HTML")
        await target.answer()
    else:
        await target.answer(text, reply_markup=admin_panel_keyboard(lang), parse_mode="HTML")

@router.message(AddSetStates.photo, F.photo)
async def set_photo(message: Message, state: FSMContext):
    photo_id = message.photo[-1].file_id
    await _save_set(message, state, photo_id)

@router.message(AddSetStates.photo, F.document.mime_type.startswith("image/"))
async def set_photo_doc(message: Message, state: FSMContext, bot: Bot):
    from database import save_web_image
    file = await bot.get_file(message.document.file_id)
    stream = await bot.download_file(file.file_path)
    data = stream.read()
    image_id = await save_web_image(data, message.document.mime_type)
    await _save_set(message, state, f"web:{image_id}")

@router.callback_query(F.data == "set_skip_photo", AddSetStates.photo)
async def set_skip_photo(callback: CallbackQuery, state: FSMContext):
    await _save_set(callback, state, None)
