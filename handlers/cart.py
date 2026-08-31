"""
Shopping cart, checkout flow, and order handlers
"""
import json
import re
from aiogram import Router, F, Bot
from aiogram.types import (
    CallbackQuery, Message, LabeledPrice, PreCheckoutQuery,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import (
    get_user_language, get_product, add_to_cart, get_cart,
    clear_cart, remove_from_cart, get_cart_total,
    get_cart_item, set_cart_quantity,
    set_order_cheque,
    create_order, get_user_orders, get_order, get_user,
    update_user_info, effective_price, active_discount,
    format_local_dt,
    InsufficientStockError, InsufficientKetoError,
)
from locales import get_text, get_unit_name, get_display_unit, get_order_status, get_delivery_method_name
from keyboards import (
    quantity_keyboard, cart_keyboard, back_to_menu_keyboard,
    main_menu_keyboard, payment_method_keyboard, delivery_method_keyboard,
    persistent_menu_keyboard,
)
from config import PAYMENT_PROVIDER_TOKEN, ADMIN_IDS, PAYMENT_CARD_NUMBER, PAYMENT_RECIPIENT_NAME

router = Router()


class CartStates(StatesGroup):
    waiting_custom_qty = State()


class CheckoutStates(StatesGroup):
    waiting_phone = State()
    waiting_location = State()
    confirming_location = State()
    waiting_address_note = State()
    waiting_delivery_method = State()
    waiting_secondary_phone = State()
    waiting_payment_method = State()
    waiting_cheque = State()
    confirming = State()
    waiting_keto_amount = State()


# Tashkent bounding box (approximate, with a ~5 km buffer around the city
# proper so addresses just outside the boundary — Yunusobod / Sergeli
# fringes, the airport area, near-suburbs — still count as "in Tashkent"
# for the self-delivery + cash flow. 1° lat ≈ 111 km; 1° lng @ 41.3° ≈ 83.5 km,
# so 0.05° lat ≈ 5.5 km and 0.06° lng ≈ 5 km.
TASHKENT_BOUNDS = {
    "lat_min": 41.10, "lat_max": 41.50,
    "lng_min": 69.04, "lng_max": 69.51,
}

# Flat delivery fee for Ketoshop's own courier ("self"), Tashkent only.
# Yandex Taxi and the out-of-city courier services (Yandex Market/BTS/EMU)
# aren't charged here — their delivery cost is between the buyer and courier.
SELF_DELIVERY_FEE = 25_000

# Uzbekistan bounding box (approximate — covers mainland UZ)
UZBEKISTAN_BOUNDS = {
    "lat_min": 37.0, "lat_max": 46.0,
    "lng_min": 55.9, "lng_max": 73.2,
}


def _is_tashkent(lat: float, lng: float) -> bool:
    """Check if coordinates are within Tashkent area"""
    return (TASHKENT_BOUNDS["lat_min"] <= lat <= TASHKENT_BOUNDS["lat_max"]
            and TASHKENT_BOUNDS["lng_min"] <= lng <= TASHKENT_BOUNDS["lng_max"])


def _is_in_uzbekistan(lat: float, lng: float) -> bool:
    """Fast bounding-box check — too loose; use _verify_uzbekistan for authoritative answer."""
    return (UZBEKISTAN_BOUNDS["lat_min"] <= lat <= UZBEKISTAN_BOUNDS["lat_max"]
            and UZBEKISTAN_BOUNDS["lng_min"] <= lng <= UZBEKISTAN_BOUNDS["lng_max"])


# Cache full Nominatim responses keyed by ~110m grid (round(lat/lng, 3))
_geo_cache: dict[tuple[float, float], dict | None] = {}
_GEO_CACHE_MAX = 1000


async def _reverse_geocode(lat: float, lng: float) -> dict | None:
    """Fetch street-level reverse-geocode from Nominatim (cached).
    Returns the full JSON dict (with `address` and `display_name`), or None
    on any network/HTTP error. Used for both country verification and
    pulling out human-readable street/district names."""
    key = (round(lat, 3), round(lng, 3))
    if key in _geo_cache:
        return _geo_cache[key]

    import aiohttp
    url = (
        "https://nominatim.openstreetmap.org/reverse"
        f"?lat={lat}&lon={lng}&format=json&zoom=18&addressdetails=1"
    )
    headers = {
        "User-Agent": "KetoshopBot/1.0 (https://t.me/ketoshopbot)",
        # Prefer Uzbek then Russian then English when Nominatim has translations.
        "Accept-Language": "uz,ru,en",
    }
    data: dict | None = None
    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as sess:
            async with sess.get(url, headers=headers) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
    except Exception:
        data = None

    if len(_geo_cache) >= _GEO_CACHE_MAX:
        _geo_cache.clear()
    _geo_cache[key] = data
    return data


def _format_readable_address(geo: dict | None) -> str | None:
    """Build a short, accountant-friendly address string from Nominatim's
    structured data. Falls back to display_name when fields are sparse,
    truncated to ~120 chars."""
    if not geo:
        return None
    addr = geo.get("address") or {}

    parts: list[str] = []
    house = addr.get("house_number")
    road = addr.get("road") or addr.get("pedestrian") or addr.get("residential")
    if road:
        parts.append(f"{road} {house}".strip() if house else road)

    locality = (addr.get("suburb") or addr.get("neighbourhood")
                or addr.get("village") or addr.get("hamlet"))
    if locality:
        parts.append(locality)

    district = addr.get("city_district") or addr.get("county") or addr.get("district")
    if district and district not in parts:
        parts.append(district)

    city = addr.get("city") or addr.get("town") or addr.get("state")
    if city and city not in parts:
        parts.append(city)

    short = ", ".join(parts) if parts else (geo.get("display_name") or "")
    short = short.strip()
    if not short:
        return None
    return short[:120]


async def verify_uzbekistan(lat: float, lng: float) -> bool:
    """Authoritative check: bounding box first, then Nominatim country_code == 'uz'.
    Falls back to the bounding box result if Nominatim is unreachable."""
    if not _is_in_uzbekistan(lat, lng):
        return False

    geo = await _reverse_geocode(lat, lng)
    if geo is None:
        # Network failure — be permissive (bbox already passed)
        return True
    cc = ((geo.get("address") or {}).get("country_code") or "").lower()
    return cc == "uz"


async def get_location_address_text(lat: float, lng: float) -> str | None:
    """Public helper: return a human-readable address (district + street +
    house) for given coords, or None if Nominatim has nothing useful."""
    geo = await _reverse_geocode(lat, lng)
    return _format_readable_address(geo)
    return ok


def _escape_html(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def payment_status_block(payment_method: str | None, status: str | None, lang: str) -> str:
    """One-line payment summary for an order card. Online orders only reach
    the seller after the cheque is uploaded, so online ⇒ paid. Cash is paid on
    delivery, so it shows 'paid' once delivered, else 'pay on delivery'."""
    if payment_method == "online":
        return get_text("pay_card_paid", lang)
    if status == "delivered":
        return get_text("pay_cash_paid", lang)
    return get_text("pay_cash_pending", lang)


def buyer_contact_link(user_id: int | None, username: str | None, name: str | None) -> str:
    """Return an HTML-formatted link the admin can tap to DM the buyer in Telegram.
    Prefers @username; falls back to a tg://user?id=... deep link."""
    if username:
        return f'<a href="https://t.me/{username}">@{username}</a>'
    if user_id:
        return f'<a href="tg://user?id={user_id}">{_escape_html(name) or "Telegram"}</a>'
    return _escape_html(name) or "—"


# ===== ADD TO CART =====

@router.callback_query(F.data.startswith("add_cart:"))
async def add_one_to_cart(callback: CallbackQuery):
    """Add 1 of the product to the cart straight away — no quantity prompt.
    The buyer bumps the count with the +/- steppers in the cart. (The qty:/
    custom_qty: handlers below stay for any other entry points.)"""
    product_id = int(callback.data.split(":")[1])
    lang = await get_user_language(callback.from_user.id)

    product = await get_product(product_id)
    if not product:
        await callback.answer("❌")
        return
    if (product.get("quantity") or 0) <= 0:
        await callback.answer(get_text("cart_stock_limit", lang), show_alert=True)
        return

    await add_to_cart(callback.from_user.id, product_id, 1)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_view_cart", lang), callback_data="cart")],
        [InlineKeyboardButton(text=get_text("btn_continue_shopping", lang), callback_data="catalog")],
    ])
    # New message (not edit): the product card may be a photo bubble.
    await callback.message.answer(
        get_text("added_to_cart", lang,
            name=product["name"], quantity=1,
            unit=get_display_unit(product["unit"], lang)),
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer("✅")


@router.callback_query(F.data.startswith("qty:"))
async def add_item_to_cart(callback: CallbackQuery):
    """Add item with selected quantity to cart"""
    _, product_id, quantity = callback.data.split(":")
    product_id = int(product_id)
    quantity = float(quantity)
    lang = await get_user_language(callback.from_user.id)

    product = await get_product(product_id)
    if not product:
        await callback.answer("❌")
        return

    await add_to_cart(callback.from_user.id, product_id, quantity)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=get_text("btn_view_cart", lang),
            callback_data="cart"
        )],
        [InlineKeyboardButton(
            text=get_text("btn_continue_shopping", lang),
            callback_data="catalog"
        )],
    ])

    await callback.message.edit_text(
        get_text("added_to_cart", lang,
            name=product["name"],
            quantity=quantity,
            unit=get_display_unit(product["unit"], lang)
        ),
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    await callback.answer("✅")


# ===== CUSTOM QUANTITY =====

@router.callback_query(F.data.startswith("custom_qty:"))
async def ask_custom_quantity(callback: CallbackQuery, state: FSMContext):
    """Ask user to type a custom quantity"""
    product_id = int(callback.data.split(":")[1])
    lang = await get_user_language(callback.from_user.id)
    await state.set_state(CartStates.waiting_custom_qty)
    await state.update_data(product_id=product_id, lang=lang)
    await callback.message.edit_text(get_text("enter_custom_qty", lang))
    await callback.answer()


@router.message(CartStates.waiting_custom_qty)
async def process_custom_quantity(message: Message, state: FSMContext):
    """Process custom quantity text input"""
    data = await state.get_data()
    lang = data.get("lang", "uz")
    product_id = data["product_id"]

    product = await get_product(product_id)
    unit = product["unit"] if product else ""
    available = product["quantity"] if product else 1000

    raw = (message.text or "").strip().replace(",", ".")
    try:
        quantity = float(raw)
    except (ValueError, TypeError):
        await message.answer(get_text("invalid_qty", lang))
        return

    if quantity <= 0:
        await message.answer(get_text("invalid_qty", lang))
        return

    if quantity > available:
        avail_display = int(available) if float(available).is_integer() else available
        await message.answer(
            get_text("qty_exceeds_stock", lang,
                available=avail_display,
                unit=get_display_unit(unit, lang),
            ),
            parse_mode="HTML",
        )
        return

    if unit in ("kg", "g") and not quantity.is_integer():
        await message.answer(get_text("qty_whole_only", lang))
        return

    await state.clear()

    if not product:
        await message.answer("❌")
        return

    await add_to_cart(message.from_user.id, product_id, quantity)

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_view_cart", lang), callback_data="cart")],
        [InlineKeyboardButton(text=get_text("btn_continue_shopping", lang), callback_data="catalog")],
    ])

    await message.answer(
        get_text("added_to_cart", lang,
            name=product["name"],
            quantity=quantity,
            unit=get_display_unit(product["unit"], lang)
        ),
        reply_markup=keyboard,
        parse_mode="HTML"
    )


# ===== VIEW CART =====

@router.callback_query(F.data == "cart")
async def show_cart(callback: CallbackQuery):
    """Show user's cart"""
    lang = await get_user_language(callback.from_user.id)
    await _render_cart(callback, lang)
    await callback.answer()


async def build_cart_view(user_id: int, lang: str):
    """(text, keyboard) for the cart, or (None, None) when it's empty.

    Shared by the inline cart bubble, the 🛒 reply-keyboard button, and the
    Mini App's bot-side fallbacks so all three show the same aksiya banner and
    the same bonus lines."""
    import promotions

    cart_items = await get_cart(user_id)
    if not cart_items:
        return None, None

    text = await promotions.banner(lang) + get_text("cart_title", lang)
    total = 0
    saved_total = 0
    for i, item in enumerate(cart_items, 1):
        discount = active_discount(item.get("discount_percent"), item.get("discount_until"))
        unit_price = effective_price(item["price"], discount, item.get("discount_until"))
        item_total = unit_price * item["cart_quantity"]
        total += item_total
        if discount > 0:
            saved_total += (item["price"] - unit_price) * item["cart_quantity"]
            text += get_text("cart_item_discount", lang,
                i=i,
                name=item["name"],
                quantity=item["cart_quantity"],
                unit=get_display_unit(item["unit"], lang),
                old=f"{int(item['price']):,}".replace(",", " "),
                price=f"{int(unit_price):,}".replace(",", " "),
                percent=discount,
                total=f"{int(item_total):,}".replace(",", " "),
            )
        else:
            text += get_text("cart_item", lang,
                i=i,
                name=item["name"],
                quantity=item["cart_quantity"],
                unit=get_display_unit(item["unit"], lang),
                price=f"{int(unit_price):,}".replace(",", " "),
                total=f"{int(item_total):,}".replace(",", " "),
            )

    # Free aksiya bonuses earned by what's in the cart right now. Recomputed
    # on every render (not stored on the cart row) so a stepper tap, a
    # campaign edit, or a campaign ending is reflected immediately.
    bonus_input = [
        {"product_id": it.get("product_id"), "quantity": it["cart_quantity"], "is_set": it.get("is_set", False)}
        for it in cart_items
    ]
    promo = await promotions.get_active()
    text += promotions.bonus_lines_text(promotions.compute_bonuses(promo, bonus_input), lang)

    text += get_text("cart_total", lang, total=f"{int(total):,}".replace(",", " "))
    if saved_total > 0:
        text += get_text("cart_saved", lang, amount=f"{int(saved_total):,}".replace(",", " "))

    # "Yana 1 ta qo'shsangiz — sovg'a sizniki": only for products already in
    # the cart, so it reads as a heads-up rather than an ad. Placed after the
    # total so it can never push the price out of view.
    text += promotions.near_miss_text(promotions.compute_near_misses(promo, bonus_input), lang)
    return text, cart_keyboard(lang, cart_items)


async def render_cart_message(message: Message, lang: str):
    """Cart as a fresh message — the entry point for the 🛒 Savat button on
    the persistent reply keyboard, which arrives as a plain text message and
    so has no bubble to edit in place."""
    text, keyboard = await build_cart_view(message.from_user.id, lang)
    if text is None:
        await message.answer(
            get_text("cart_empty", lang),
            reply_markup=main_menu_keyboard(lang),
            parse_mode="HTML",
        )
        return
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


async def _render_cart(callback: CallbackQuery, lang: str):
    """Render (in place) the cart message — shared by show_cart and the
    +/- quantity steppers so they refresh the same bubble."""
    text, keyboard = await build_cart_view(callback.from_user.id, lang)

    if text is None:
        if callback.message.photo:
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(
                get_text("cart_empty", lang),
                reply_markup=main_menu_keyboard(lang),
                parse_mode="HTML"
            )
        else:
            try:
                await callback.message.edit_text(
                    get_text("cart_empty", lang),
                    reply_markup=main_menu_keyboard(lang),
                    parse_mode="HTML"
                )
            except Exception:
                pass
        return

    if callback.message.photo:
        # Coming from a photo bubble (e.g. the product-detail card's "go to
        # cart" button) — edit_text can't turn a photo message into a text
        # one, so resend instead of silently failing.
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(
            text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        try:
            await callback.message.edit_text(
                text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        except Exception:
            # "message is not modified" when a stepper hit a stock/min bound — ignore.
            pass


@router.callback_query(F.data.startswith("cart_inc:"))
async def cart_increment(callback: CallbackQuery):
    """+1 on a cart line (capped at available stock)."""
    lang = await get_user_language(callback.from_user.id)
    cart_id = int(callback.data.split(":")[1])
    item = await get_cart_item(cart_id)
    if not item or item["user_id"] != callback.from_user.id:
        await callback.answer("❌", show_alert=True)
        return
    stock = item.get("stock") or 0
    new_qty = item["cart_quantity"] + 1
    if stock and new_qty > stock:
        await callback.answer(get_text("cart_stock_limit", lang), show_alert=True)
        return
    await set_cart_quantity(cart_id, new_qty)
    await _render_cart(callback, lang)
    await callback.answer()


@router.callback_query(F.data.startswith("cart_dec:"))
async def cart_decrement(callback: CallbackQuery):
    """-1 on a cart line; removing it when it would drop below 1."""
    lang = await get_user_language(callback.from_user.id)
    cart_id = int(callback.data.split(":")[1])
    item = await get_cart_item(cart_id)
    if not item or item["user_id"] != callback.from_user.id:
        await callback.answer("❌", show_alert=True)
        return
    new_qty = item["cart_quantity"] - 1
    if new_qty < 1:
        await remove_from_cart(cart_id)
    else:
        await set_cart_quantity(cart_id, new_qty)
    await _render_cart(callback, lang)
    await callback.answer()


@router.callback_query(F.data == "clear_cart")
async def clear_user_cart(callback: CallbackQuery):
    """Clear the entire cart"""
    lang = await get_user_language(callback.from_user.id)
    await clear_cart(callback.from_user.id)
    await callback.message.edit_text(
        get_text("cart_cleared", lang),
        reply_markup=main_menu_keyboard(lang),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("remove_cart:"))
async def remove_cart_item(callback: CallbackQuery):
    """Remove an item from cart"""
    cart_id = int(callback.data.split(":")[1])
    lang = await get_user_language(callback.from_user.id)
    await remove_from_cart(cart_id)
    await callback.answer(get_text("item_removed", lang))
    # Refresh cart view
    await show_cart(callback)


# ===== CHECKOUT FLOW =====
# Flow: checkout → saved info? → payment method → phone → location → create order

@router.callback_query(F.data == "checkout")
async def start_checkout(callback: CallbackQuery, state: FSMContext):
    """Start checkout — offer saved info or ask phone"""
    lang = await get_user_language(callback.from_user.id)
    cart_items = await get_cart(callback.from_user.id)

    if not cart_items:
        await callback.message.edit_text(
            get_text("cart_empty", lang),
            reply_markup=main_menu_keyboard(lang),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    await state.update_data(lang=lang)

    # Check if user has saved phone & address
    user = await get_user(callback.from_user.id)
    if user and user.get("phone") and user.get("address"):
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text=get_text("btn_use_saved_info", lang),
                callback_data="use_saved_info",
            )],
            [InlineKeyboardButton(
                text=get_text("btn_enter_new_info", lang),
                callback_data="enter_new_info",
            )],
        ])
        await state.set_state(CheckoutStates.waiting_phone)
        await callback.message.edit_text(
            get_text("saved_info_prompt", lang,
                phone=user["phone"],
                address=user["address"],
            ),
            reply_markup=keyboard,
            parse_mode="HTML"
        )
    else:
        await state.set_state(CheckoutStates.waiting_phone)
        await callback.message.edit_text(
            get_text("enter_phone", lang),
            parse_mode="HTML"
        )
    await callback.answer()


@router.callback_query(F.data == "use_saved_info", CheckoutStates.waiting_phone)
async def use_saved_info(callback: CallbackQuery, state: FSMContext):
    """Use saved phone & address — skip to payment method selection"""
    data = await state.get_data()
    lang = data.get("lang", "uz")

    user = await get_user(callback.from_user.id)
    if not user or not user.get("phone") or not user.get("address"):
        await state.set_state(CheckoutStates.waiting_phone)
        await callback.message.edit_text(
            get_text("enter_phone", lang),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    # Parse lat/lng from saved address if it matches coordinate format
    m = re.match(r"📍\s*([-\d.]+),\s*([-\d.]+)", user["address"])
    if m:
        lat, lng = float(m.group(1)), float(m.group(2))
        # If the saved location is outside Uzbekistan, force them to re-share
        if not await verify_uzbekistan(lat, lng):
            await state.set_state(CheckoutStates.waiting_location)
            location_kb = ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text=get_text("btn_share_location", lang), request_location=True)]],
                resize_keyboard=True,
                one_time_keyboard=True,
            )
            await state.update_data(phone=user["phone"])
            await callback.message.answer(
                get_text("location_outside_uzbekistan", lang),
                reply_markup=location_kb,
                parse_mode="HTML",
            )
            await callback.answer()
            return
        await state.update_data(phone=user["phone"], address=user["address"], latitude=lat, longitude=lng)
        online_only = not _is_tashkent(lat, lng)
    else:
        await state.update_data(phone=user["phone"], address=user["address"])
        online_only = True  # No coordinates — assume outside Tashkent

    in_tashkent = not online_only
    await state.update_data(online_only=online_only, in_tashkent=in_tashkent)

    # Ask for an optional address note first — even with saved info, the
    # courier may need fresh details for *this* delivery.
    await state.set_state(CheckoutStates.waiting_address_note)
    await callback.message.edit_text(
        get_text("enter_address_note", lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "enter_new_info", CheckoutStates.waiting_phone)
async def enter_new_info(callback: CallbackQuery, state: FSMContext):
    """User wants to enter new info — proceed with normal flow"""
    data = await state.get_data()
    lang = data.get("lang", "uz")

    await state.set_state(CheckoutStates.waiting_phone)
    await callback.message.edit_text(
        get_text("enter_phone", lang),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(CheckoutStates.waiting_phone)
async def process_phone(message: Message, state: FSMContext):
    """Process phone number"""
    data = await state.get_data()
    lang = data.get("lang", "uz")

    phone = message.text.strip()
    # Simple Uzbek phone validation
    if not re.match(r'^\+?998\d{9}$', phone.replace(" ", "").replace("-", "")):
        await message.answer(get_text("invalid_phone", lang))
        return

    await state.update_data(phone=phone)
    await update_user_info(message.from_user.id, phone=phone)
    await state.set_state(CheckoutStates.waiting_location)

    # Show keyboard with location share button
    location_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=get_text("btn_share_location", lang), request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await message.answer(get_text("enter_location", lang), reply_markup=location_kb, parse_mode="HTML")


@router.message(CheckoutStates.waiting_location, F.location)
async def process_location(message: Message, state: FSMContext):
    """Process delivery location — then ask payment method"""
    data = await state.get_data()
    lang = data.get("lang", "uz")

    lat = message.location.latitude
    lng = message.location.longitude

    # Reject locations outside Uzbekistan — we only deliver within the country
    if not await verify_uzbekistan(lat, lng):
        await message.answer(
            get_text("location_outside_uzbekistan", lang),
            parse_mode="HTML",
        )
        return  # keep FSM state; the share-location keyboard is still visible

    # Reverse-geocode to a readable street/district line — accountants and
    # couriers find "Yunusobod, Mustaqillik 12" much more useful than coords.
    # Cached, so the previous verify_uzbekistan call already populated it.
    readable = await get_location_address_text(lat, lng)
    address = f"📍 {lat:.6f}, {lng:.6f}"
    if readable:
        address += f" — {readable}"
    await state.update_data(address=address, latitude=lat, longitude=lng)

    # Swap the one-shot location keyboard back for the persistent 🏠/🛒 one.
    # A bare ReplyKeyboardRemove here used to leave the buyer with nothing
    # under the input box for the rest of the session — exactly the "I don't
    # know how to get back" problem the persistent keyboard exists to fix.
    await message.answer("✅", reply_markup=persistent_menu_keyboard(lang))

    # If we got a human-readable address, show it back and ask the buyer to
    # confirm — keeps them in control when GPS jitters or the wrong building
    # got tagged. No readable text → skip confirmation, save and continue.
    if readable:
        await state.set_state(CheckoutStates.confirming_location)
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=get_text("btn_loc_confirm_yes", lang),
                                 callback_data="loc_confirm:yes"),
            InlineKeyboardButton(text=get_text("btn_loc_confirm_no", lang),
                                 callback_data="loc_confirm:no"),
        ]])
        await message.answer(
            get_text("confirm_location_prompt", lang, address=readable),
            reply_markup=kb,
            parse_mode="HTML",
        )
        return

    # No readable text — proceed straight to the next step.
    await update_user_info(message.from_user.id, phone=data.get("phone"), address=address)
    await _advance_after_location(message, state, lat, lng, lang)


async def _advance_after_location(target, state: FSMContext, lat: float, lng: float, lang: str) -> None:
    """Shared transition: location is final → set in_tashkent flag, optionally
    show online-only notice, then ask for the address note."""
    online_only = not _is_tashkent(lat, lng)
    await state.update_data(online_only=online_only, in_tashkent=not online_only)

    if online_only:
        if hasattr(target, "answer") and not hasattr(target, "edit_text"):
            await target.answer(get_text("outside_tashkent_online_only", lang), parse_mode="HTML")
        else:
            await target.answer(get_text("outside_tashkent_online_only", lang), parse_mode="HTML")

    await state.set_state(CheckoutStates.waiting_address_note)
    if hasattr(target, "answer"):
        await target.answer(get_text("enter_address_note", lang), parse_mode="HTML")


@router.callback_query(F.data == "loc_confirm:yes", CheckoutStates.confirming_location)
async def confirm_location_yes(callback: CallbackQuery, state: FSMContext):
    """Buyer confirms the detected address — save and advance."""
    data = await state.get_data()
    lang = data.get("lang", "uz")
    lat = data.get("latitude")
    lng = data.get("longitude")
    address = data.get("address")

    await update_user_info(callback.from_user.id,
                           phone=data.get("phone"), address=address)
    # Replace the prompt with a tick so the chat stays clean
    try:
        await callback.message.edit_text(
            "✅ " + (data.get("address") or ""),
            parse_mode="HTML",
        )
    except Exception:
        pass
    await callback.answer()
    if lat is not None and lng is not None:
        await _advance_after_location(callback.message, state, lat, lng, lang)


@router.callback_query(F.data == "loc_confirm:no", CheckoutStates.confirming_location)
async def confirm_location_no(callback: CallbackQuery, state: FSMContext):
    """Buyer rejects the detected address — ask to share location again."""
    data = await state.get_data()
    lang = data.get("lang", "uz")
    await state.set_state(CheckoutStates.waiting_location)
    location_kb = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=get_text("btn_share_location", lang),
                                  request_location=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    try:
        await callback.message.edit_text(get_text("loc_resend", lang),
                                         parse_mode="HTML")
    except Exception:
        pass
    await callback.message.answer(get_text("enter_location", lang),
                                  reply_markup=location_kb, parse_mode="HTML")
    await callback.answer()


@router.message(CheckoutStates.waiting_address_note, F.text)
async def process_address_note(message: Message, state: FSMContext):
    """Save the optional address comment, then advance to delivery method."""
    data = await state.get_data()
    lang = data.get("lang", "uz")
    raw = (message.text or "").strip()

    if raw.lower() in ("/skip", "skip", "-"):
        note = None
    elif len(raw) > 500:
        await message.answer(get_text("address_note_too_long", lang))
        return
    else:
        note = raw

    await state.update_data(address_note=note)
    in_tashkent = data.get("in_tashkent", False)

    await state.set_state(CheckoutStates.waiting_delivery_method)
    await message.answer(
        get_text("choose_delivery", lang),
        reply_markup=delivery_method_keyboard(lang, in_tashkent=in_tashkent),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("delivery:"), CheckoutStates.waiting_delivery_method)
async def process_delivery_method(callback: CallbackQuery, state: FSMContext):
    """Delivery method selected — ask for an optional secondary phone next,
    then payment selection. The backup number lets the courier reach the
    buyer when their main phone is offline."""
    method = callback.data.split(":", 1)[1]
    data = await state.get_data()
    lang = data.get("lang", "uz")

    await state.update_data(delivery_method=method)
    await state.set_state(CheckoutStates.waiting_secondary_phone)
    await callback.message.edit_text(
        get_text("enter_secondary_phone", lang),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(CheckoutStates.waiting_secondary_phone, F.text)
async def process_secondary_phone(message: Message, state: FSMContext):
    """Validate or skip the courier-backup number, then go to payment."""
    data = await state.get_data()
    lang = data.get("lang", "uz")
    raw = (message.text or "").strip()

    if raw.lower() in ("/skip", "skip", "-"):
        secondary = None
    else:
        cleaned = raw.replace(" ", "").replace("-", "")
        if not re.match(r'^\+?998\d{9}$', cleaned):
            await message.answer(get_text("invalid_phone", lang))
            return
        secondary = cleaned

    await state.update_data(secondary_phone=secondary)
    delivery_method = data.get("delivery_method")
    # Yandex Taxi drivers aren't our staff — they can't take cash, so force
    # online when that delivery method is chosen even inside Tashkent.
    online_only = data.get("online_only", False) or delivery_method == "yandex_taxi"
    await state.set_state(CheckoutStates.waiting_payment_method)
    if delivery_method == "yandex_taxi" and not data.get("online_only", False):
        await message.answer(
            get_text("yandex_taxi_online_only", lang),
            parse_mode="HTML",
        )
    await message.answer(
        get_text("choose_payment", lang),
        reply_markup=payment_method_keyboard(lang, online_only=online_only),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("pay:"), CheckoutStates.waiting_payment_method)
async def process_payment_method(callback: CallbackQuery, state: FSMContext):
    """Payment method selected — show the review/confirm screen (buyer can
    still add more products or cancel from there) before anything is created."""
    payment_method = callback.data.split(":")[1]
    data = await state.get_data()
    lang = data.get("lang", "uz")

    await state.update_data(payment_method=payment_method)
    await update_user_info(callback.from_user.id, payment_method=payment_method)

    await state.set_state(CheckoutStates.confirming)
    await _show_order_confirmation(callback, state, lang)
    await callback.answer()


@router.callback_query(F.data == "cancel_order")
async def cancel_order(callback: CallbackQuery, state: FSMContext):
    """Cancel checkout"""
    lang = await get_user_language(callback.from_user.id)
    await state.clear()
    await callback.message.edit_text(
        get_text("order_cancelled", lang),
        reply_markup=main_menu_keyboard(lang),
        parse_mode="HTML"
    )
    await callback.answer()


# ===== TELEGRAM PAYMENTS =====

@router.pre_checkout_query()
async def process_pre_checkout(pre_checkout: PreCheckoutQuery, bot: Bot):
    """Approve pre-checkout query"""
    await bot.answer_pre_checkout_query(pre_checkout.id, ok=True)


@router.message(F.successful_payment)
async def process_payment(message: Message):
    """Handle successful payment"""
    payload = message.successful_payment.invoice_payload
    order_id = int(payload.replace("order_", ""))
    lang = await get_user_language(message.from_user.id)

    from database import update_order_status
    await update_order_status(order_id, "confirmed")

    await message.answer(
        get_text("payment_success", lang, order_id=order_id),
        reply_markup=main_menu_keyboard(lang),
        parse_mode="HTML"
    )


# ===== MY ORDERS =====

@router.callback_query(F.data == "my_orders")
async def show_my_orders(callback: CallbackQuery):
    """Show buyer's order history as plain text — no per-order action buttons.
    Only navigation back to the main menu."""
    lang = await get_user_language(callback.from_user.id)
    orders = await get_user_orders(callback.from_user.id)

    if not orders:
        await callback.message.edit_text(
            get_text("no_orders", lang),
            reply_markup=main_menu_keyboard(lang),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    text = get_text("my_orders_title", lang)
    for order in orders[:10]:
        text += get_text("order_item", lang,
            id=order["id"],
            date=format_local_dt(order["created_at"], "%d.%m.%Y"),
            status=get_order_status(order["status"], lang),
            total=f"{int(order['total']):,}".replace(",", " "),
        )

    await callback.message.edit_text(
        text,
        reply_markup=back_to_menu_keyboard(lang),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("reorder:"))
async def reorder(callback: CallbackQuery):
    """Re-add items from a previous order to cart"""
    order_id = int(callback.data.split(":")[1])
    lang = await get_user_language(callback.from_user.id)

    order = await get_order(order_id)
    # Reject if order doesn't exist OR doesn't belong to this user — without
    # the ownership check, a crafted callback like reorder:OTHER_ID would
    # leak another buyer's items into the requester's cart.
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer("❌")
        return

    items = json.loads(order["items"]) if isinstance(order["items"], str) else order["items"]

    added = 0
    for item in items:
        product = await get_product(item["product_id"])
        if product and product["is_active"] == 1 and product["quantity"] > 0:
            await add_to_cart(callback.from_user.id, item["product_id"], item["quantity"])
            added += 1

    if added > 0:
        await callback.message.edit_text(
            get_text("reorder_success", lang, count=added),
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=get_text("btn_view_cart", lang), callback_data="cart")],
                [InlineKeyboardButton(text=get_text("btn_back_to_menu", lang), callback_data="main_menu")],
            ]),
            parse_mode="HTML"
        )
    else:
        await callback.message.edit_text(
            get_text("reorder_empty", lang),
            reply_markup=back_to_menu_keyboard(lang),
            parse_mode="HTML"
        )
    await callback.answer()


# ===== BUYER SELF-CANCEL =====

@router.callback_query(F.data.startswith("buyer_cancel:"))
async def buyer_cancel_prompt(callback: CallbackQuery):
    """Step 1 — confirm the buyer really wants to cancel."""
    order_id = int(callback.data.split(":")[1])
    lang = await get_user_language(callback.from_user.id)

    order = await get_order(order_id)
    # Ownership + cancellable-state check
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer("❌", show_alert=True)
        return
    if order["status"] not in ("pending", "confirmed"):
        await callback.answer(get_text("buyer_cancel_too_late", lang), show_alert=True)
        return

    await callback.message.edit_text(
        get_text("buyer_cancel_confirm", lang, order_id=order_id),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text=get_text("btn_yes", lang), callback_data=f"buyer_cancel_do:{order_id}"),
                InlineKeyboardButton(text=get_text("btn_no", lang), callback_data="my_orders"),
            ],
        ]),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("buyer_cancel_do:"))
async def buyer_cancel_do(callback: CallbackQuery, bot: Bot):
    """Step 2 — atomically cancel + restore stock + notify admins + show support."""
    from database import cancel_order as db_cancel_order
    from keyboards import order_cancelled_keyboard

    order_id = int(callback.data.split(":")[1])
    lang = await get_user_language(callback.from_user.id)

    # Re-fetch + validate ownership/state at confirm time (prevents stale UI bypass)
    order = await get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer("❌", show_alert=True)
        return
    if order["status"] not in ("pending", "confirmed"):
        await callback.answer(get_text("buyer_cancel_too_late", lang), show_alert=True)
        return

    await db_cancel_order(order_id)

    await callback.message.edit_text(
        get_text("buyer_cancel_done", lang, order_id=order_id),
        reply_markup=order_cancelled_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()

    # Notify admins so they don't prep an order that's already cancelled
    import asyncio
    import logging
    logger = logging.getLogger(__name__)
    customer_name = callback.from_user.full_name or "—"

    async def _notify_admin(admin_id: int) -> None:
        admin_lang = await get_user_language(admin_id)
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=get_text("buyer_cancelled_by_user_admin", admin_lang,
                    order_id=order_id,
                    name=customer_name,
                    phone=order.get("phone", "—"),
                ),
                parse_mode="HTML",
            )
        except Exception as exc:
            logger.warning("Buyer-cancel notice to admin %s failed: %s", admin_id, exc)

    await asyncio.gather(*(_notify_admin(aid) for aid in ADMIN_IDS), return_exceptions=True)


# ===== HELPERS =====

async def _show_payment_selection(callback: CallbackQuery, state: FSMContext, lang: str, online_only: bool):
    """Show payment method keyboard.

    Previously this would auto-skip the choice for buyers who had a saved
    payment_method, but that backfired: a buyer who once paid online for a
    region delivery would later be silently forced into online when picking
    self-delivery in Tashkent. We now always show the selector, so the
    payment matches the *current* delivery context."""
    await state.set_state(CheckoutStates.waiting_payment_method)
    await callback.message.edit_text(
        get_text("choose_payment", lang),
        reply_markup=payment_method_keyboard(lang, online_only=online_only),
        parse_mode="HTML",
    )


async def _build_order_summary(user_id: int, data: dict, lang: str):
    """Compute the live cart total + build the order-summary text.

    Reads the cart fresh from the DB every time it's called (not a frozen
    snapshot) — this is what lets the confirm-screen "add more products"
    flow work with no extra merging logic: whatever's in the cart when the
    buyer finally confirms is exactly what gets ordered.

    Returns (text, total, items_data, keto_redeem) — keto_redeem is the
    buyer's requested Keto-as-discount amount from FSM data, re-clamped
    against their *current* balance and the order total every time this
    runs (so it self-corrects if either changed since they picked it).
    Or (None, 0, [], 0) if the cart is empty."""
    cart_items = await get_cart(user_id)
    if not cart_items:
        return None, 0, [], 0

    items_data = []
    for item in cart_items:
        discount = active_discount(item.get("discount_percent"), item.get("discount_until"))
        unit_price = effective_price(item["price"], discount, item.get("discount_until"))
        items_data.append({
            "product_id": item.get("product_id"),
            "set_id": item.get("set_id"),
            "is_set": item.get("is_set", False),
            "name": item["name"],
            "quantity": item["cart_quantity"],
            "price": unit_price,
            "original_price": item["price"],
            "discount_percent": discount,
            "unit": item["unit"],
            "seller_id": item.get("seller_id"),
        })

    # Free aksiya bonuses ride along inside items_data as 0-so'm lines, so
    # create_order freezes them into orders.items and _notify_sellers shows
    # them to whoever packs the box — no extra plumbing at either call site.
    # They add nothing to the totals below (price is 0) and are skipped when
    # the priced item list is rendered.
    import promotions
    bonuses = await promotions.bonuses_for_items(items_data)
    items_data.extend(bonuses)

    items_subtotal = sum(item["price"] * item["quantity"] for item in items_data)
    total = items_subtotal

    delivery_method = data.get("delivery_method")
    delivery_fee = SELF_DELIVERY_FEE if delivery_method == "self" else 0
    total += delivery_fee

    # Keto-as-discount (opt-in, off by default — see gamification.is_redemption_enabled).
    # Re-clamped against the *current* balance and total every render, so it
    # self-corrects if the cart or balance changed since the buyer picked it.
    keto_redeem = int(data.get("keto_redeem") or 0)
    if keto_redeem > 0:
        buyer = await get_user(user_id)
        balance = int(buyer["keto_balance"]) if buyer else 0
        keto_redeem = max(0, min(keto_redeem, balance, int(total)))
        if keto_redeem > 0:
            total -= keto_redeem

    items_text = ""
    for i, item in enumerate([it for it in items_data if not it.get("is_bonus")], 1):
        item_total = item["price"] * item["quantity"]
        badge = f" 🔥-{item['discount_percent']}%" if item.get("discount_percent") else ""
        items_text += f"{i}. {item['name']} — {item['quantity']} {get_display_unit(item['unit'], lang)} × {int(item['price']):,}{badge} = {int(item_total):,}\n".replace(",", " ")
    items_text += promotions.bonus_lines_text(bonuses, lang)
    items_text += promotions.near_miss_text(
        promotions.compute_near_misses(await promotions.get_active(), items_data), lang
    )

    payment_method = data["payment_method"]
    payment_label = get_text("btn_pay_cash", lang) if payment_method == "cash" else get_text("btn_pay_online", lang)
    delivery_label = get_delivery_method_name(delivery_method, lang)
    delivery_fee_block = get_text("delivery_fee_line", lang, fee=f"{delivery_fee:,}".replace(",", " ")) if delivery_fee else ""
    keto_block = get_text("keto_redeemed_line", lang, amount=f"{keto_redeem:,}".replace(",", " ")) if keto_redeem else ""
    address_note = data.get("address_note")
    note_block = f"\n📝 {address_note}" if address_note else ""
    secondary_phone = data.get("secondary_phone")
    secondary_block = f"\n📞 {secondary_phone}" if secondary_phone else ""

    text = get_text("order_summary", lang,
        phone=data["phone"],
        secondary_block=secondary_block,
        address=data["address"],
        note_block=note_block,
        payment=payment_label,
        delivery=delivery_label,
        items=items_text,
        delivery_fee_block=delivery_fee_block,
        keto_block=keto_block,
        total=f"{int(total):,}".replace(",", " "),
    )
    return text, total, items_data, keto_redeem


async def _render_confirmation(user_id: int, state: FSMContext, lang: str):
    """Shared by the callback and message entry points into the confirm
    screen. Returns (text, keyboard) or (None, None) if the cart emptied out
    from under the buyer."""
    data = await state.get_data()
    text, total, items_data, keto_redeem = await _build_order_summary(user_id, data, lang)
    if text is None:
        return None, None

    rows = [[InlineKeyboardButton(text=get_text("btn_confirm_order", lang), callback_data="order_confirm:yes")]]

    # Keto-as-discount row — only rendered when the owner has switched
    # redemption on (off by default) and this buyer actually has a balance.
    # No DB reads happen here otherwise, so a disabled feature costs nothing.
    import gamification
    if await gamification.is_redemption_enabled():
        buyer = await get_user(user_id)
        keto_balance = int(buyer["keto_balance"]) if buyer else 0
        if keto_redeem > 0:
            rows.insert(0, [InlineKeyboardButton(text=get_text("btn_keto_redeem_clear", lang), callback_data="keto_redeem:clear")])
        elif keto_balance > 0:
            rows.insert(0, [InlineKeyboardButton(
                text=get_text("btn_keto_redeem_start", lang, balance=f"{keto_balance:,}".replace(",", " ")),
                callback_data="keto_redeem:start",
            )])

    rows.append([InlineKeyboardButton(text=get_text("btn_add_more_before_order", lang), callback_data="order_confirm:add_more")])
    rows.append([InlineKeyboardButton(text=get_text("btn_cancel", lang), callback_data="cancel_order")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_order_confirmation(callback: CallbackQuery, state: FSMContext, lang: str):
    """Review screen shown right before the order is placed — lets the
    buyer confirm, cancel, or go add more products first (cart stays live
    in the DB while they browse; re-entering this screen recomputes the
    total from whatever's in the cart at that moment)."""
    text, keyboard = await _render_confirmation(callback.from_user.id, state, lang)
    if text is None:
        await state.clear()
        await callback.message.edit_text(
            get_text("cart_empty", lang),
            reply_markup=main_menu_keyboard(lang),
            parse_mode="HTML"
        )
        return
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data == "keto_redeem:start", CheckoutStates.confirming)
async def keto_redeem_start(callback: CallbackQuery, state: FSMContext):
    """Buyer tapped "use my Keto" on the confirm screen — ask how much."""
    import gamification

    lang = await get_user_language(callback.from_user.id)
    if not await gamification.is_redemption_enabled():
        # Toggled off by the admin between rendering the button and this tap
        # — extremely unlikely, but don't leave the buyer stuck typing into
        # a feature that just got disabled.
        await callback.answer()
        await _show_order_confirmation(callback, state, lang)
        return

    buyer = await get_user(callback.from_user.id)
    balance = int(buyer["keto_balance"]) if buyer else 0
    data = await state.get_data()
    _, total, _, _ = await _build_order_summary(callback.from_user.id, {**data, "keto_redeem": 0}, lang)
    cap = min(balance, int(total))

    await state.set_state(CheckoutStates.waiting_keto_amount)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=get_text("btn_cancel", lang), callback_data="keto_redeem:cancel_input"),
    ]])
    await callback.message.edit_text(
        get_text("keto_redeem_prompt", lang,
                  balance=f"{balance:,}".replace(",", " "), max=f"{cap:,}".replace(",", " ")),
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(CheckoutStates.waiting_keto_amount, F.text)
async def keto_redeem_amount_entered(message: Message, state: FSMContext):
    lang = await get_user_language(message.from_user.id)
    raw = (message.text or "").strip().replace(" ", "")

    data = await state.get_data()
    buyer = await get_user(message.from_user.id)
    balance = int(buyer["keto_balance"]) if buyer else 0
    _, total, _, _ = await _build_order_summary(message.from_user.id, {**data, "keto_redeem": 0}, lang)
    cap = min(balance, int(total))

    if not raw.isdigit() or not (0 <= int(raw) <= cap):
        await message.answer(get_text("keto_redeem_invalid", lang, max=f"{cap:,}".replace(",", " ")))
        return

    await state.update_data(keto_redeem=int(raw))
    await state.set_state(CheckoutStates.confirming)
    text, keyboard = await _render_confirmation(message.from_user.id, state, lang)
    if text is None:
        await state.clear()
        await message.answer(get_text("cart_empty", lang), reply_markup=main_menu_keyboard(lang), parse_mode="HTML")
        return
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data == "keto_redeem:cancel_input", CheckoutStates.waiting_keto_amount)
async def keto_redeem_cancel_input(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    await state.set_state(CheckoutStates.confirming)
    await _show_order_confirmation(callback, state, lang)
    await callback.answer()


@router.callback_query(F.data == "keto_redeem:clear", CheckoutStates.confirming)
async def keto_redeem_clear(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    await state.update_data(keto_redeem=0)
    await _show_order_confirmation(callback, state, lang)
    await callback.answer()


@router.callback_query(F.data == "order_confirm:yes", CheckoutStates.confirming)
async def order_confirm_yes(callback: CallbackQuery, state: FSMContext, bot: Bot):
    await _create_and_process_order(callback, state, bot)


@router.callback_query(F.data == "order_confirm:add_more", CheckoutStates.confirming)
async def order_confirm_add_more(callback: CallbackQuery, state: FSMContext):
    """Let the buyer browse/add products without disturbing the in-flight
    checkout — state stays `confirming` so phone/address/delivery/payment
    already collected survive the trip. A follow-up message with a single
    "finish order" button is the buyer's way back, since it works no matter
    how deep they wander into categories/search/product detail."""
    from handlers.catalog import show_catalog

    lang = await get_user_language(callback.from_user.id)
    await show_catalog(callback)
    await callback.message.answer(
        get_text("add_more_before_order_hint", lang),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_text("btn_finish_adding", lang), callback_data="order_confirm:review")],
        ]),
    )


@router.callback_query(F.data == "order_confirm:review", CheckoutStates.confirming)
async def order_confirm_review(callback: CallbackQuery, state: FSMContext):
    lang = await get_user_language(callback.from_user.id)
    await _show_order_confirmation(callback, state, lang)
    await callback.answer()


async def _create_and_process_order(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Create the order (cash) or defer creation until the cheque arrives
    (online). Called only from the confirm screen (order_confirm:yes).

    Why deferral matters for online: previously we created the DB row up
    front and asked for the cheque after. If the buyer never sent the
    cheque, the row sat in the DB as a half-real order. Now the row is only
    inserted once we actually have proof of payment — the FSM holds all the
    order details in the meantime, and stock is only reserved at cheque-
    arrival time (so two buyers competing for the last unit can't both
    "succeed" — whoever uploads the cheque first wins)."""
    data = await state.get_data()
    lang = data.get("lang", "uz")
    payment_method = data["payment_method"]
    address = data["address"]

    text, total, items_data, keto_redeem = await _build_order_summary(callback.from_user.id, data, lang)
    if text is None:
        await state.clear()
        await callback.message.edit_text(
            get_text("cart_empty", lang),
            reply_markup=main_menu_keyboard(lang),
            parse_mode="HTML"
        )
        return

    customer_name = callback.from_user.full_name or "—"
    delivery_method = data.get("delivery_method")
    address_note = data.get("address_note")
    secondary_phone = data.get("secondary_phone")

    if payment_method == "cash":
        # Cash → create the order now (atomic stock + Keto-balance reservation), notify sellers.
        try:
            order_id, low_stock = await create_order(
                user_id=callback.from_user.id,
                customer_name=customer_name,
                phone=data["phone"],
                address=address,
                items=items_data,
                total=total,
                payment_method=payment_method,
                latitude=data.get("latitude"),
                longitude=data.get("longitude"),
                delivery_method=delivery_method,
                address_note=address_note,
                secondary_phone=secondary_phone,
                keto_redeem=keto_redeem,
            )
        except InsufficientStockError:
            await state.clear()
            await callback.message.edit_text(
                get_text("checkout_stock_gone", lang),
                reply_markup=main_menu_keyboard(lang),
                parse_mode="HTML",
            )
            await callback.answer()
            return
        except InsufficientKetoError:
            # Balance shifted between the confirm screen render and this tap
            # (e.g. two tabs). Drop the redemption and let them re-confirm
            # rather than silently charging the wrong total.
            await state.update_data(keto_redeem=0)
            await _show_order_confirmation(callback, state, lang)
            await callback.answer(get_text("keto_redeem_race", lang), show_alert=True)
            return

        if low_stock:
            await notify_low_stock(bot, low_stock)

        await state.clear()
        await callback.message.edit_text(
            text + "\n\n" + get_text("order_created", lang, order_id=order_id),
            reply_markup=main_menu_keyboard(lang),
            parse_mode="HTML"
        )

        await _notify_sellers(bot, order_id, items_data, {
            "customer_name": customer_name,
            "phone": data["phone"],
            "secondary_phone": secondary_phone,
            "address": address,
            "address_note": address_note,
            "total": total,
            "latitude": data.get("latitude"),
            "longitude": data.get("longitude"),
            "user_id": callback.from_user.id,
            "username": callback.from_user.username,
            "delivery_method": delivery_method,
            "payment_method": "cash",
        }, lang)

    elif payment_method == "online":
        # Online → DON'T create the order yet. Stash everything we'll need in
        # FSM state and ask for the cheque. The row is inserted in
        # process_cheque_photo / process_cheque_document once we have proof.
        await state.set_state(CheckoutStates.waiting_cheque)
        await state.update_data(
            pending_items=items_data,
            pending_total=total,
            pending_customer_name=customer_name,
            pending_phone=data["phone"],
            pending_address=address,
            pending_address_note=address_note,
            pending_secondary_phone=secondary_phone,
            pending_delivery_method=delivery_method,
            pending_latitude=data.get("latitude"),
            pending_longitude=data.get("longitude"),
            pending_summary_text=text,
            pending_keto_redeem=keto_redeem,
        )

        cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_text("btn_cancel_checkout", lang),
                                   callback_data="checkout_cancel")],
        ])
        await callback.message.edit_text(
            text + "\n\n" + get_text(
                "send_payment_cheque", lang,
                total=f"{int(total):,}".replace(",", " "),
                card=PAYMENT_CARD_NUMBER,
                recipient=PAYMENT_RECIPIENT_NAME,
            ),
            reply_markup=cancel_kb,
            parse_mode="HTML",
        )

    await callback.answer()


async def _finalize_legacy_order(message: Message, state: FSMContext, bot: Bot,
                                  order_id: int, cheque_file_id: str,
                                  cheque_kind: str, lang: str) -> None:
    """Compat path for online orders inserted before the cheque-deferral
    change (FSM has only `order_id`, the row already exists with stock
    reserved). Just attach the cheque, notify, clear state."""
    order = await get_order(order_id)
    if not order:
        await state.clear()
        await message.answer(
            get_text("cart_empty", lang),
            reply_markup=main_menu_keyboard(lang),
            parse_mode="HTML",
        )
        return

    await state.clear()
    await set_order_cheque(order_id, cheque_file_id, cheque_kind)
    await message.answer(
        get_text("cheque_received", lang, order_id=order_id),
        reply_markup=main_menu_keyboard(lang),
        parse_mode="HTML",
    )

    items = json.loads(order["items"]) if isinstance(order["items"], str) else order["items"]
    customer_name = order.get("customer_name") or message.from_user.full_name or "—"

    await _forward_cheque_to_admins(bot, order_id, customer_name, cheque_kind, cheque_file_id)
    await _notify_sellers(bot, order_id, items, {
        "customer_name": customer_name,
        "phone": order.get("phone", ""),
        "secondary_phone": order.get("secondary_phone"),
        "address": order.get("address", ""),
        "address_note": order.get("address_note"),
        "total": order["total"],
        "latitude": order.get("latitude"),
        "longitude": order.get("longitude"),
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "delivery_method": order.get("delivery_method"),
        "payment_method": "online",
    }, lang)


async def _finalize_online_order(message: Message, state: FSMContext, bot: Bot,
                                  cheque_file_id: str, cheque_kind: str) -> None:
    """Shared finalizer for online checkout: create the order row now (with
    stock reservation), attach the cheque, notify sellers, forward to admins.

    Returns silently on success. On stock-exhausted we tell the buyer the
    order can't be placed; on missing FSM data we drop back to the main menu.
    """
    data = await state.get_data()
    lang = data.get("lang", "uz")

    items_data = data.get("pending_items")
    if not items_data:
        # Backwards-compat: an in-flight order from before the deferral
        # change (or from a stale Mini App checkout) put only `order_id` in
        # the FSM and inserted the row up front. Attach the cheque to that
        # existing row instead of dropping the buyer's payment on the floor.
        legacy_order_id = data.get("order_id")
        if legacy_order_id:
            await _finalize_legacy_order(message, state, bot, int(legacy_order_id),
                                          cheque_file_id, cheque_kind, lang)
            return
        # No pending items, no legacy order — nothing we can do safely.
        await state.clear()
        await message.answer(
            get_text("cart_empty", lang),
            reply_markup=main_menu_keyboard(lang),
            parse_mode="HTML",
        )
        return

    customer_name = data.get("pending_customer_name") or message.from_user.full_name or "—"

    # Re-clamp the pledged Keto redemption against the *current* balance —
    # time may have passed between confirming and the cheque actually
    # arriving. Any shortfall is added back to the charged total rather than
    # silently handed out as an extra discount.
    total = data["pending_total"]
    keto_redeem = int(data.get("pending_keto_redeem") or 0)
    if keto_redeem > 0:
        buyer = await get_user(message.from_user.id)
        balance = int(buyer["keto_balance"]) if buyer else 0
        actual_redeem = min(keto_redeem, balance)
        if actual_redeem < keto_redeem:
            total += (keto_redeem - actual_redeem)
        keto_redeem = actual_redeem

    try:
        order_id, low_stock = await create_order(
            user_id=message.from_user.id,
            customer_name=customer_name,
            phone=data["pending_phone"],
            address=data["pending_address"],
            items=items_data,
            total=total,
            payment_method="online",
            latitude=data.get("pending_latitude"),
            longitude=data.get("pending_longitude"),
            delivery_method=data.get("pending_delivery_method"),
            address_note=data.get("pending_address_note"),
            secondary_phone=data.get("pending_secondary_phone"),
            keto_redeem=keto_redeem,
        )
    except InsufficientStockError:
        await state.clear()
        await message.answer(
            get_text("checkout_stock_gone", lang),
            reply_markup=main_menu_keyboard(lang),
            parse_mode="HTML",
        )
        return
    except InsufficientKetoError:
        # Balance dropped again in the instant between the re-clamp above and
        # the transaction (vanishingly rare) — retry once with no redemption
        # at all rather than leave the buyer's paid-for order un-created.
        # (total/keto_redeem invariant: total already has keto_redeem
        # subtracted out, so adding it back yields the zero-redemption total.)
        total += keto_redeem
        keto_redeem = 0
        try:
            order_id, low_stock = await create_order(
                user_id=message.from_user.id,
                customer_name=customer_name,
                phone=data["pending_phone"],
                address=data["pending_address"],
                items=items_data,
                total=total,
                payment_method="online",
                latitude=data.get("pending_latitude"),
                longitude=data.get("pending_longitude"),
                delivery_method=data.get("pending_delivery_method"),
                address_note=data.get("pending_address_note"),
                secondary_phone=data.get("pending_secondary_phone"),
                keto_redeem=0,
            )
        except InsufficientStockError:
            await state.clear()
            await message.answer(
                get_text("checkout_stock_gone", lang),
                reply_markup=main_menu_keyboard(lang),
                parse_mode="HTML",
            )
            return

    await state.clear()
    await set_order_cheque(order_id, cheque_file_id, cheque_kind)

    if low_stock:
        await notify_low_stock(bot, low_stock)

    await message.answer(
        get_text("cheque_received", lang, order_id=order_id),
        reply_markup=main_menu_keyboard(lang),
        parse_mode="HTML",
    )

    await _forward_cheque_to_admins(bot, order_id, customer_name, cheque_kind, cheque_file_id)

    await _notify_sellers(bot, order_id, items_data, {
        "customer_name": customer_name,
        "phone": data["pending_phone"],
        "secondary_phone": data.get("pending_secondary_phone"),
        "address": data["pending_address"],
        "address_note": data.get("pending_address_note"),
        "total": total,
        "latitude": data.get("pending_latitude"),
        "longitude": data.get("pending_longitude"),
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "delivery_method": data.get("pending_delivery_method"),
        "payment_method": "online",
    }, lang)


@router.message(CheckoutStates.waiting_cheque, F.photo)
async def process_cheque_photo(message: Message, state: FSMContext, bot: Bot):
    """Cheque arrived as a photo → create the order, attach the cheque."""
    await _finalize_online_order(
        message, state, bot, message.photo[-1].file_id, "photo",
    )


@router.message(CheckoutStates.waiting_cheque, F.document)
async def process_cheque_document(message: Message, state: FSMContext, bot: Bot):
    """Cheque arrived as a document (PDF/screenshot) → create the order."""
    await _finalize_online_order(
        message, state, bot, message.document.file_id, "document",
    )


@router.message(CheckoutStates.waiting_cheque)
async def process_cheque_invalid(message: Message, state: FSMContext):
    """Anything other than a photo or document while we're waiting on the
    cheque — remind the buyer what format we accept, and offer a cancel.
    Without this, a stray text message would silently fall through and the
    buyer would think the bot is stuck."""
    lang = (await state.get_data()).get("lang", "uz")
    await message.answer(
        get_text("cheque_must_be_photo_or_doc", lang),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=get_text("btn_cancel_checkout", lang),
                                   callback_data="checkout_cancel")],
        ]),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "checkout_cancel", CheckoutStates.waiting_cheque)
async def cancel_online_checkout(callback: CallbackQuery, state: FSMContext):
    """Buyer backed out before sending the cheque → drop the FSM state. No
    order was ever inserted, so there is nothing to roll back; the cart is
    preserved so they can try again."""
    lang = (await state.get_data()).get("lang", "uz")
    await state.clear()
    await callback.message.edit_text(
        get_text("checkout_cancelled", lang),
        reply_markup=main_menu_keyboard(lang),
        parse_mode="HTML",
    )
    await callback.answer()


async def _forward_cheque_to_admins(bot: Bot, order_id: int, customer_name: str,
                                     kind: str, file_id: str) -> None:
    """Forward a payment cheque (photo or document) to every admin in parallel."""
    import asyncio
    import logging
    logger = logging.getLogger(__name__)

    async def _send(admin_id: int) -> None:
        try:
            admin_lang = await get_user_language(admin_id)
            caption = get_text("cheque_from_customer", admin_lang,
                               order_id=order_id, name=customer_name)
            if kind == "photo":
                await bot.send_photo(chat_id=admin_id, photo=file_id,
                                     caption=caption, parse_mode="HTML")
            else:
                await bot.send_document(chat_id=admin_id, document=file_id,
                                        caption=caption, parse_mode="HTML")
        except Exception as exc:
            logger.warning("Cheque forward to admin %s failed: %s", admin_id, exc)

    await asyncio.gather(*(_send(aid) for aid in ADMIN_IDS), return_exceptions=True)


async def notify_low_stock(bot: Bot, low_stock: list[dict]) -> None:
    """Push one alert per just-crossed product to every admin, in parallel.
    Logs failures instead of swallowing — an admin who blocked the bot is
    routine; anything else we want to see."""
    import asyncio
    import logging
    logger = logging.getLogger(__name__)

    if not low_stock:
        return

    async def _send_one(admin_id: int, item: dict) -> None:
        admin_lang = await get_user_language(admin_id)
        qty = item["quantity"]
        qty_str = str(int(qty)) if float(qty).is_integer() else f"{qty:.1f}"
        key = "out_of_stock_alert" if qty <= 0 else "low_stock_alert"
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=get_text(key, admin_lang, name=item["name"], quantity=qty_str),
                parse_mode="HTML",
            )
        except Exception as exc:
            # Bot blocked / chat not started → fine. Anything else → worth logging.
            logger.warning("Low-stock alert to admin %s failed: %s", admin_id, exc)

    tasks = [_send_one(admin_id, item) for admin_id in ADMIN_IDS for item in low_stock]
    await asyncio.gather(*tasks, return_exceptions=True)


async def _notify_sellers(bot: Bot, order_id: int, items: list, data: dict, lang: str):
    """Notify admins (who act as sellers) about a new order"""
    contact = buyer_contact_link(
        data.get("user_id"),
        data.get("username"),
        data.get("customer_name"),
    )
    import asyncio
    import logging
    from keyboards import seller_order_keyboard
    logger = logging.getLogger(__name__)

    async def _push_one(admin_id: int) -> None:
        admin_lang = await get_user_language(admin_id)
        items_text = ""
        saved_total = 0
        import promotions
        for item in items:
            if item.get("is_bonus"):
                # Free aksiya line — no price to show, and it has to stand out
                # so whoever packs the order actually puts the gift in the box.
                items_text += (f"🎁 <b>BONUS:</b> {promotions.bonus_label(item, admin_lang)} — "
                               f"{promotions.bonus_price_html(item, admin_lang)}\n")
                continue
            unit = get_display_unit(item['unit'], admin_lang)
            new_p = f"{int(item['price']):,}".replace(",", " ")
            op = item.get("original_price")
            dp = item.get("discount_percent")
            if dp and op and op > item["price"]:
                # Show old → new with the badge so the seller sees the discount.
                old_p = f"{int(op):,}".replace(",", " ")
                price_part = f"<s>{old_p}</s> {new_p} 🔥-{dp}%"
                saved_total += (op - item["price"]) * item["quantity"]
            else:
                price_part = new_p
            items_text += f"• {item['name']} — {item['quantity']} {unit} × {price_part}\n"
        saved_block = ""
        if saved_total > 0:
            saved_block = get_text("new_order_discount_total", admin_lang,
                                   amount=f"{int(saved_total):,}".replace(",", " "))
        note = data.get("address_note")
        note_block = f"\n📝 {note}" if note else ""
        sec = data.get("secondary_phone")
        secondary_block = f"\n📞 {sec}" if sec else ""
        delivery_fee = SELF_DELIVERY_FEE if data.get("delivery_method") == "self" else 0
        delivery_fee_block = get_text("delivery_fee_line", admin_lang, fee=f"{delivery_fee:,}".replace(",", " ")) if delivery_fee else ""
        try:
            text = get_text("new_order_notification", admin_lang,
                order_id=order_id,
                name=data["customer_name"],
                phone=data["phone"],
                secondary_block=secondary_block,
                contact=contact,
                address=data["address"],
                note_block=note_block,
                delivery=get_delivery_method_name(data.get("delivery_method"), admin_lang),
                payment_block=payment_status_block(data.get("payment_method"), data.get("status"), admin_lang),
                items=items_text,
                delivery_fee_block=delivery_fee_block,
                total=f"{int(data['total']):,}".replace(",", " "),
                saved_block=saved_block,
            )
            await bot.send_message(
                chat_id=admin_id,
                text=text,
                reply_markup=seller_order_keyboard(
                    admin_lang, order_id, "pending",
                    buyer_username=data.get("username"),
                    is_admin=True,  # _notify_sellers fans out only to ADMIN_IDS
                ),
                parse_mode="HTML",
            )
            # Send location pin right after the order text so they group together
            if data.get("latitude") and data.get("longitude"):
                await bot.send_location(
                    chat_id=admin_id,
                    latitude=data["latitude"],
                    longitude=data["longitude"],
                )
        except Exception as exc:
            # Bot blocked / chat never started → expected. Anything else worth seeing.
            logger.warning("New-order notification to admin %s failed: %s", admin_id, exc)

    await asyncio.gather(*(_push_one(aid) for aid in ADMIN_IDS), return_exceptions=True)
