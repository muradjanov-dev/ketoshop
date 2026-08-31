"""
Inline keyboard builders
"""
from datetime import datetime, timezone, timedelta

from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
    ReplyKeyboardMarkup, KeyboardButton,
)
from locales import get_text, get_category_name, get_unit_name, get_month_name, CATEGORIES, UNITS
from config import WEBAPP_URL, SUPPORT_USERNAME
import promotions


def persistent_menu_keyboard(lang: str) -> ReplyKeyboardMarkup:
    """The always-there keyboard under the text input.

    Every other keyboard in this bot is inline: it lives on one message and
    scrolls away with it, so a buyer who lost the thread had no way back
    except typing /start — which most people never discover (owner report,
    2026-08-31). The chat's menu button can't help either, it's taken by the
    Mini App. A reply keyboard is the one surface Telegram keeps pinned above
    the input box across every message, so that's where the way home goes.

    Sent once per user (see handlers/start.ensure_menu_keyboard) and persists
    from then on — is_persistent keeps it open even after someone collapses it."""
    return ReplyKeyboardMarkup(
        keyboard=[[
            KeyboardButton(text=get_text("btn_kb_menu", lang)),
            KeyboardButton(text=get_text("btn_kb_cart", lang)),
        ]],
        resize_keyboard=True,
        is_persistent=True,
    )


def _current_month_label(lang: str) -> str:
    now_local = datetime.now(timezone.utc) + timedelta(hours=5)  # Asia/Tashkent
    return "📅 " + get_month_name(now_local.month, lang)


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🇺🇿 O'zbek (Lotin)", callback_data="lang:uz"),
            InlineKeyboardButton(text="🇺🇿 Ўзбек (Кирилл)", callback_data="lang:uz_cyr"),
        ],
        [
            InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
        ],
    ])


def main_menu_keyboard(lang: str, is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = []
    if WEBAPP_URL:
        buttons.append([InlineKeyboardButton(
            text=get_text("btn_store", lang),
            web_app=WebAppInfo(url=WEBAPP_URL)
        )])
    # Aksiya entry, 2nd from the top — only while a campaign is actually
    # running, and labelled with its name so the menu itself advertises it.
    # cached_active() is a plain dict read (no await, no query), which is what
    # lets this stay synchronous across all 25 main_menu_keyboard call sites.
    promo = promotions.cached_active()
    if promo:
        buttons.append([InlineKeyboardButton(
            text=f"🎁 {promotions.promo_name(promo, lang)}",
            callback_data="promo",
        )])

    buttons += [
        [InlineKeyboardButton(text=get_text("btn_catalog", lang), callback_data="catalog")],
        # Chegirmalar removed for now (owner request 2026-07-27) — Qidirish
        # gets the full row to itself until it's back.
        [InlineKeyboardButton(text=get_text("btn_search", lang), callback_data="search")],
        [
            InlineKeyboardButton(text=get_text("btn_cart", lang), callback_data="cart"),
            # "Mening buyurtmalarim" now lives inside Kabinetim alongside the
            # Keto balance/level — one place for everything personal.
            InlineKeyboardButton(text=get_text("btn_kabinetim", lang), callback_data="kabinetim"),
        ],
        [InlineKeyboardButton(text=get_text("btn_delivery", lang), callback_data="delivery_zones")],
        # Language switch now lives inside the Qo'llanma (Help) screen, so the
        # main menu shows a single full-width Help entry here.
        [InlineKeyboardButton(text=get_text("btn_help", lang), callback_data="help")],
    ]
    if is_admin:
        # Single unified panel — replaces the old separate Seller / Admin entries
        buttons.append([InlineKeyboardButton(text=get_text("btn_admin", lang), callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def cart_shortcut_row(lang: str, cart_count: int) -> list[InlineKeyboardButton]:
    """Single-button row linking straight to the cart — appended to browsing
    keyboards (categories, product lists, product detail, search) so buyers
    who've already added something don't have to go back to the main menu.
    Empty list when the cart has nothing in it (nothing to jump to)."""
    if cart_count <= 0:
        return []
    return [InlineKeyboardButton(text=get_text("btn_view_cart", lang), callback_data="cart")]


def categories_keyboard(lang: str, cart_count: int = 0) -> InlineKeyboardMarkup:
    buttons = []
    for i in range(0, len(CATEGORIES), 2):
        row = []
        for cat in CATEGORIES[i:i+2]:
            row.append(InlineKeyboardButton(
                text=get_category_name(cat, lang),
                callback_data=f"cat:{cat}"
            ))
        buttons.append(row)

    buttons.append([InlineKeyboardButton(
        text=get_text("btn_sets", lang),
        callback_data="cat:sets"
    )])

    cart_row = cart_shortcut_row(lang, cart_count)
    if cart_row:
        buttons.append(cart_row)
    buttons.append([InlineKeyboardButton(text=get_text("btn_back_to_menu", lang), callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def product_keyboard(lang: str, product_id: int, page: int, category: str, total_pages: int) -> InlineKeyboardMarkup:
    buttons = []

    # Add to cart + reviews
    buttons.append([
        InlineKeyboardButton(
            text=get_text("btn_add_to_cart", lang),
            callback_data=f"add_cart:{product_id}"
        ),
        InlineKeyboardButton(
            text=get_text("btn_reviews", lang),
            callback_data=f"reviews:{product_id}"
        ),
    ])

    # Navigation
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(
            text=get_text("btn_prev", lang),
            callback_data=f"page:{category}:{page - 1}"
        ))
    nav_row.append(InlineKeyboardButton(
        text=get_text("page_info", lang, current=page + 1, total=total_pages),
        callback_data="noop"
    ))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(
            text=get_text("btn_next", lang),
            callback_data=f"page:{category}:{page + 1}"
        ))
    if nav_row:
        buttons.append(nav_row)

    # Back
    buttons.append([
        InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="catalog")
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def quantity_keyboard(lang: str, product_id: int, unit: str = "", available: float | None = None) -> InlineKeyboardMarkup:
    # Weight-priced products (kg/g) are treated as pre-packaged — whole counts only.
    if unit in ("kg", "g"):
        options = [1, 2, 3, 5, 10, 20]
    else:
        options = [0.5, 1, 2, 3, 5, 10]

    # Drop options that exceed available stock
    if available is not None:
        options = [q for q in options if q <= available]

    rows = []
    for i in range(0, len(options), 3):
        row = []
        for q in options[i:i+3]:
            label = str(int(q)) if q == int(q) else str(q)
            row.append(InlineKeyboardButton(text=label, callback_data=f"qty:{product_id}:{q}"))
        rows.append(row)

    rows.append([
        InlineKeyboardButton(text=get_text("btn_custom_qty", lang), callback_data=f"custom_qty:{product_id}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cart_keyboard(lang: str, cart_items: list) -> InlineKeyboardMarkup:
    buttons = []

    # Per-item row: ➖ | name ×qty | ➕ | ❌
    for item in cart_items:
        qty = item["cart_quantity"]
        qty_label = str(int(qty)) if float(qty).is_integer() else f"{qty:.1f}"
        name = item["name"]
        short = (name[:16] + "…") if len(name) > 17 else name
        cid = item["cart_id"]
        buttons.append([
            InlineKeyboardButton(text="➖", callback_data=f"cart_dec:{cid}"),
            InlineKeyboardButton(text=f"{short} ×{qty_label}", callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data=f"cart_inc:{cid}"),
            InlineKeyboardButton(text="❌", callback_data=f"remove_cart:{cid}"),
        ])

    # Add more items without leaving the cart — opens search.
    buttons.append([
        InlineKeyboardButton(text=get_text("cart_add_more_btn", lang), callback_data="search"),
    ])
    buttons.append([
        InlineKeyboardButton(text=get_text("btn_clear_cart", lang), callback_data="clear_cart"),
    ])
    buttons.append([
        InlineKeyboardButton(text=get_text("btn_checkout", lang), callback_data="checkout"),
    ])
    buttons.append([
        InlineKeyboardButton(text=get_text("btn_back_to_menu", lang), callback_data="main_menu"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def payment_method_keyboard(lang: str, online_only: bool = False) -> InlineKeyboardMarkup:
    buttons = []
    if not online_only:
        buttons.append([InlineKeyboardButton(text=get_text("btn_pay_cash", lang), callback_data="pay:cash")])
    buttons.append([InlineKeyboardButton(text=get_text("btn_pay_online", lang), callback_data="pay:online")])
    buttons.append([InlineKeyboardButton(text=get_text("btn_cancel", lang), callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def delivery_method_keyboard(lang: str, in_tashkent: bool) -> InlineKeyboardMarkup:
    """In Tashkent: Ketoshop's own courier (cash/online, flat fee) or Yandex Taxi
    (online only). Outside: courier services (Yandex Market, BTS, EMU)."""
    if in_tashkent:
        options = [("self", "btn_delivery_self"), ("yandex_taxi", "btn_delivery_yandex_taxi")]
    else:
        options = [
            ("yandex_market", "btn_delivery_yandex_market"),
            ("bts", "btn_delivery_bts"),
            ("emu", "btn_delivery_emu"),
        ]
    buttons = [[InlineKeyboardButton(text=get_text(label_key, lang), callback_data=f"delivery:{code}")]
               for code, label_key in options]
    buttons.append([InlineKeyboardButton(text=get_text("btn_cancel", lang), callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_to_menu_keyboard(lang: str, cart_count: int = 0) -> InlineKeyboardMarkup:
    buttons = []
    cart_row = cart_shortcut_row(lang, cart_count)
    if cart_row:
        buttons.append(cart_row)
    buttons.append([InlineKeyboardButton(text=get_text("btn_back_to_menu", lang), callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ===== SELLER KEYBOARDS =====

def seller_panel_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Backwards-compat alias — the seller panel was merged into the admin
    panel (admins are sellers in this marketplace). All existing "back to
    panel" navigations land on the unified view."""
    return admin_panel_keyboard(lang)


def post_edit_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Shown after a product field is edited. Drops the user back at the
    product list (where they came from) instead of the admin panel."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_my_products", lang), callback_data="seller:my_products")],
        [InlineKeyboardButton(text=get_text("btn_back_to_menu", lang), callback_data="main_menu")],
    ])


def category_select_keyboard(lang: str, prefix: str = "selcat", allow_new: bool = False) -> InlineKeyboardMarkup:
    buttons = []
    for i in range(0, len(CATEGORIES), 2):
        row = []
        for cat in CATEGORIES[i:i+2]:
            row.append(InlineKeyboardButton(
                text=get_category_name(cat, lang),
                callback_data=f"{prefix}:{cat}"
            ))
        buttons.append(row)
    if allow_new:
        new_label = "➕ Yangi kategoriya" if lang != "ru" else "➕ Новая категория"
        buttons.append([InlineKeyboardButton(text=new_label, callback_data=f"{prefix}:__new__")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def unit_select_keyboard(lang: str) -> InlineKeyboardMarkup:
    buttons = []
    for i in range(0, len(UNITS), 3):
        row = []
        for unit in UNITS[i:i+3]:
            row.append(InlineKeyboardButton(
                text=get_unit_name(unit, lang),
                callback_data=f"unit:{unit}"
            ))
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def seller_product_keyboard(lang: str, product_id: int, page: int = 0) -> InlineKeyboardMarkup:
    """The page param is threaded through edit/delete callbacks so the
    seller is returned to the same My Products page after they finish."""
    back_cb = f"seller_prods_page:{page}" if page else "seller:my_products"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=get_text("btn_edit_product", lang), callback_data=f"edit_prod:{product_id}:{page}"),
            InlineKeyboardButton(text=get_text("btn_delete_product", lang), callback_data=f"del_prod:{product_id}:{page}"),
        ],
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data=back_cb)],
    ])


def confirm_delete_keyboard(lang: str, product_id: int, page: int = 0) -> InlineKeyboardMarkup:
    cancel_cb = f"seller_prods_page:{page}" if page else "seller:my_products"
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=get_text("btn_yes", lang), callback_data=f"confirm_del:{product_id}:{page}"),
            InlineKeyboardButton(text=get_text("btn_no", lang), callback_data=cancel_cb),
        ]
    ])


def seller_order_keyboard(lang: str, order_id: int, status: str,
                           buyer_username: str | None = None,
                           is_admin: bool = False) -> InlineKeyboardMarkup:
    buttons = []
    if buyer_username:
        buttons.append([
            InlineKeyboardButton(
                text=get_text("btn_contact_buyer", lang),
                url=f"https://t.me/{buyer_username}",
            ),
        ])
    if status == "pending":
        buttons.append([
            InlineKeyboardButton(text=get_text("btn_accept_order", lang), callback_data=f"order_act:confirm:{order_id}"),
            InlineKeyboardButton(text=get_text("btn_reject_order", lang), callback_data=f"order_act:cancel:{order_id}"),
        ])
    elif status == "confirmed":
        buttons.append([
            InlineKeyboardButton(text=get_text("btn_mark_shipped", lang), callback_data=f"order_act:ship:{order_id}"),
        ])
    elif status == "shipped":
        buttons.append([
            InlineKeyboardButton(text=get_text("btn_mark_delivered", lang), callback_data=f"order_act:delivered:{order_id}"),
        ])
    # Send a message to the buyer *through the bot* (shows as coming from the
    # shop, unlike the @username deep-link above which opens a personal DM).
    buttons.append([
        InlineKeyboardButton(text=get_text("btn_message_client", lang), callback_data=f"msgclient:{order_id}"),
    ])
    # Admin-only hard delete — for cleaning up orders created by mistake.
    # Regular sellers shouldn't see this; cancellation is the normal flow.
    if is_admin:
        buttons.append([
            InlineKeyboardButton(text=get_text("btn_delete_order", lang),
                                  callback_data=f"order_delete:{order_id}"),
        ])
    buttons.append([
        InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="seller:orders"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ===== REVIEW KEYBOARDS =====

def rating_keyboard(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐ 1", callback_data=f"rate:{product_id}:1"),
            InlineKeyboardButton(text="⭐ 2", callback_data=f"rate:{product_id}:2"),
            InlineKeyboardButton(text="⭐ 3", callback_data=f"rate:{product_id}:3"),
            InlineKeyboardButton(text="⭐ 4", callback_data=f"rate:{product_id}:4"),
            InlineKeyboardButton(text="⭐ 5", callback_data=f"rate:{product_id}:5"),
        ]
    ])


def review_back_keyboard(lang: str, product_id: int, cart_count: int = 0) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=get_text("btn_write_review", lang), callback_data=f"write_review:{product_id}")],
    ]
    cart_row = cart_shortcut_row(lang, cart_count)
    if cart_row:
        buttons.append(cart_row)
    buttons.append([InlineKeyboardButton(text=get_text("btn_back_to_menu", lang), callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def order_cancelled_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=get_text("btn_contact_admin", lang),
            url=f"https://t.me/{SUPPORT_USERNAME}",
        )],
        [InlineKeyboardButton(text=get_text("btn_back_to_menu", lang), callback_data="main_menu")],
    ])


def delivered_feedback_keyboard(lang: str, order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_leave_review", lang), callback_data=f"review_order:{order_id}")],
        [InlineKeyboardButton(text=get_text("btn_report_issue", lang), callback_data=f"complaint:{order_id}")],
        [InlineKeyboardButton(text=get_text("btn_back_to_menu", lang), callback_data="main_menu")],
    ])


def review_pick_product_keyboard(lang: str, items: list) -> InlineKeyboardMarkup:
    buttons = []
    for it in items:
        pid = it.get("product_id")
        name = it.get("name", "—")
        if pid is None:
            continue
        buttons.append([
            InlineKeyboardButton(text=f"⭐ {name}", callback_data=f"write_review:{pid}"),
        ])
    buttons.append([InlineKeyboardButton(text=get_text("btn_back_to_menu", lang), callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ===== DELIVERY KEYBOARDS =====

def delivery_zones_keyboard(lang: str, zones: list) -> InlineKeyboardMarkup:
    buttons = []
    for i in range(0, len(zones), 2):
        row = []
        for zone in zones[i:i+2]:
            city = zone["city_name_uz"] if lang == "uz" else zone["city_name_ru"]
            row.append(InlineKeyboardButton(
                text=f"📍 {city}",
                callback_data=f"zone_info:{zone['id']}"
            ))
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text=get_text("btn_back_to_menu", lang), callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ===== ADMIN KEYBOARDS =====

def stats_keyboard(lang: str, current: str = "today",
                   callback_prefix: str = "admin:stats",
                   back_callback: str = "admin_panel") -> InlineKeyboardMarkup:
    def label(period: str) -> str:
        text = get_text(f"stats_period_{period}", lang)
        return f"• {text} •" if period == current else text

    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=label("today"), callback_data=f"{callback_prefix}:today"),
            InlineKeyboardButton(text=label("7d"), callback_data=f"{callback_prefix}:7d"),
        ],
        [
            InlineKeyboardButton(text=label("30d"), callback_data=f"{callback_prefix}:30d"),
            InlineKeyboardButton(text=label("all"), callback_data=f"{callback_prefix}:all"),
        ],
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data=back_callback)],
    ])


def admin_stats_keyboard(lang: str, current: str = "today") -> InlineKeyboardMarkup:
    return stats_keyboard(lang, current, "admin:stats", "admin_panel")


def admin_cancel_keyboard(lang: str) -> InlineKeyboardMarkup:
    """A generic cancel button returning to the admin panel."""
    label = "❌ Bekor qilish" if lang != "ru" else "❌ Отмена"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data="admin_panel")]
    ])

def admin_panel_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Statistika va Hisobot", callback_data="admin_menu:stats"),
            InlineKeyboardButton(text="📦 Mahsulot va Buyurtma", callback_data="admin_menu:products")
        ],
        [
            InlineKeyboardButton(text="👥 Foydalanuvchilar", callback_data="admin_menu:users"),
            InlineKeyboardButton(text="🚀 Marketing va Aksiya", callback_data="admin_menu:marketing")
        ],
        [InlineKeyboardButton(text=get_text("btn_back_to_menu", lang), callback_data="main_menu")],
    ])

def admin_stats_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_admin_website", lang), url=f"{WEBAPP_URL}/admin")],
        [
            InlineKeyboardButton(text=get_text("btn_admin_stats", lang), callback_data="admin:stats"),
            InlineKeyboardButton(text=_current_month_label(lang), callback_data="admin:monthly_stats")
        ],
        [
            InlineKeyboardButton(text=get_text("btn_admin_excel", lang), callback_data="admin:excel"),
            InlineKeyboardButton(text=get_text("btn_admin_list_quote", lang), callback_data="admin:list_quote")
        ],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_panel")],
    ])

def admin_products_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=get_text("btn_admin_orders", lang), callback_data="admin:orders"),
            InlineKeyboardButton(text=get_text("btn_admin_manual_order", lang), callback_data="admin:manual_order")
        ],
        [
            InlineKeyboardButton(text="🏢 B2B Savdo", callback_data="admin:b2b_menu"),
        ],
        [
            InlineKeyboardButton(text=get_text("btn_add_product", lang), callback_data="seller:add_product"),
            InlineKeyboardButton(text="🎁 To'plam qo'shish", callback_data="seller:add_set"),
        ],
        [
            InlineKeyboardButton(text=get_text("btn_my_products", lang), callback_data="seller:my_products"),
        ],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_panel")],
    ])

def admin_users_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=get_text("btn_admin_users", lang), callback_data="admin:users"),
            InlineKeyboardButton(text=get_text("btn_admin_add_admin", lang), callback_data="admin:add_admin"),
        ],
        [
            InlineKeyboardButton(text=get_text("btn_admin_broadcast", lang), callback_data="admin:broadcast")
        ],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_panel")],
    ])

def admin_marketing_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=get_text("btn_admin_bulk_discount", lang), callback_data="admin:bulk_discount"),
            InlineKeyboardButton(text=get_text("btn_admin_keto", lang), callback_data="admin:keto")
        ],
        [
            InlineKeyboardButton(text=get_text("btn_admin_promo", lang), callback_data="admin:promo"),
        ],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_panel")],
    ])



def admin_order_filter_keyboard(lang: str, counts: dict | None = None) -> InlineKeyboardMarkup:
    """Order filter menu. If `counts` (a {status: int} dict, including
    "all") is provided, append the count to each label so the admin sees
    workload at a glance: e.g. "Yetkazildi · 24"."""
    counts = counts or {}

    def _label(status: str, base: str) -> str:
        n = counts.get(status)
        return f"{base} · {n}" if n is not None else base

    all_label = _label("all", "📋 Hammasi" if lang == "uz" else "📋 Все")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=all_label, callback_data="admin:orders:all")],
        [
            InlineKeyboardButton(text=_label("pending", get_text("order_status_pending", lang)), callback_data="admin:orders:pending"),
            InlineKeyboardButton(text=_label("confirmed", get_text("order_status_confirmed", lang)), callback_data="admin:orders:confirmed"),
        ],
        [
            InlineKeyboardButton(text=_label("shipped", get_text("order_status_shipped", lang)), callback_data="admin:orders:shipped"),
            InlineKeyboardButton(text=_label("delivered", get_text("order_status_delivered", lang)), callback_data="admin:orders:delivered"),
        ],
        [InlineKeyboardButton(text=_label("cancelled", get_text("order_status_cancelled", lang)), callback_data="admin:orders:cancelled")],
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="admin_panel")],
    ])


def admin_delivery_zone_keyboard(lang: str, zones: list) -> InlineKeyboardMarkup:
    buttons = []
    for zone in zones:
        city = zone["city_name_uz"] if lang == "uz" else zone["city_name_ru"]
        buttons.append([InlineKeyboardButton(
            text=f"📍 {city} — {int(zone['price']):,} so'm".replace(",", " "),
            callback_data=f"admin:edit_zone:{zone['id']}"
        )])
    buttons.append([InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_user_action_keyboard(lang: str, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=get_text("btn_admin_ban", lang), callback_data=f"admin:ban:{user_id}"),
            InlineKeyboardButton(text=get_text("btn_admin_unban", lang), callback_data=f"admin:unban:{user_id}"),
        ],
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="admin:users")],
    ])
