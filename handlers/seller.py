"""
Seller panel — add products, manage listings, view orders & stats
"""
import html
import logging
from io import BytesIO

from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import (
    get_user_language, set_user_as_seller, add_product, get_seller_products,
    get_product, delete_product, get_seller_orders, get_order,
    update_order_status, transition_order_status, get_seller_stats, get_user, update_product,
    add_product_media, get_product_media, delete_product_media,
    cancel_order as db_cancel_order,
    format_local_dt, now_local_for_display,
    get_user_delivered_order_count,
)
from config import ADMIN_IDS
from locales import get_text, get_category_name, get_unit_name, get_order_status, get_delivery_method_name, localize_product_text, CATEGORIES
from keyboards import (
    seller_panel_keyboard, category_select_keyboard, unit_select_keyboard,
    seller_product_keyboard, confirm_delete_keyboard, seller_order_keyboard,
    back_to_menu_keyboard, main_menu_keyboard, post_edit_keyboard
)

router = Router()


def _clean_number(text: str) -> str:
    """Clean number input: handle both comma-as-decimal and comma-as-thousand separator.
    '1,5' or '1.5' → '1.5'   (decimal)
    '1 000' → '1000'          (thousand separator)
    '10,000' → '10000'        (thousand separator — has 3+ digits after comma)
    """
    s = text.strip().replace(" ", "")
    # If comma is used as decimal (e.g. "0,5", "1,5" — less than 3 digits after comma)
    if "," in s and "." not in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) < 3:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    return s


def _format_status_dt(dt) -> str:
    """Format an order lifecycle timestamp in Asia/Tashkent local time
    ('DD.MM.YYYY HH:MM') for buyer-facing notifications."""
    return format_local_dt(dt)


def _build_buyer_status_block(order: dict, new_status: str, lang: str) -> tuple[str, str]:
    """Return (when, timeline) for the buyer's status-change notification.

    `when` is the timestamp of the *current* status change (the headline
    date in the message). `timeline` is the compact dated history block
    rendered up to and including the current step.
    """
    from datetime import datetime
    from locales import get_text as _get_text  # local alias to avoid shadowing

    # Pick the source timestamp for the current event
    stamp_field = {
        "confirmed": "confirmed_at",
        "shipped":   "shipped_at",
        "delivered": "delivered_at",
    }.get(new_status)
    if stamp_field and order.get(stamp_field):
        when_dt = order[stamp_field]
    else:
        # Cancelled has no dedicated column → use UTC NOW so format_local_dt
        # adds the same +5h offset as it would to a real DB stamp.
        when_dt = now_local_for_display()
    when = _format_status_dt(when_dt)

    # Compose the timeline lines that are already known (created → ... → now).
    lines = []
    if order.get("created_at"):
        lines.append(_get_text("buyer_timeline_created", lang,
                               date=_format_status_dt(order["created_at"])))
    if order.get("confirmed_at") and new_status in ("confirmed", "shipped", "delivered"):
        lines.append(_get_text("buyer_timeline_confirmed", lang,
                               date=_format_status_dt(order["confirmed_at"])))
    if order.get("shipped_at") and new_status in ("shipped", "delivered"):
        lines.append(_get_text("buyer_timeline_shipped", lang,
                               date=_format_status_dt(order["shipped_at"])))
    if order.get("delivered_at") and new_status == "delivered":
        lines.append(_get_text("buyer_timeline_delivered", lang,
                               date=_format_status_dt(order["delivered_at"])))
    return when, "\n".join(lines)


async def _safe_edit_or_resend(message: Message, text: str, reply_markup=None) -> None:
    """edit_text fails on photo bubbles ("there is no text in the message to
    edit"). Used after the edit-product screen which now renders a photo:
    every editf: callback would otherwise look frozen. Try edit_text first,
    on failure delete the photo bubble and send a fresh text message."""
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception:
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer(text, reply_markup=reply_markup, parse_mode="HTML")


async def _send_with_optional_photo(message: Message, text: str, keyboard, photo_id: str | None) -> None:
    """Render text+buttons, attaching the product photo when there is one.
    Photo messages can't be edited to text, so we delete the previous bubble
    first when a photo is present (and we're not already on a photo message)."""
    if photo_id:
        try:
            await message.delete()
        except Exception:
            pass
        try:
            await message.answer_photo(
                photo=photo_id,
                caption=text,
                reply_markup=keyboard,
                parse_mode="HTML",
            )
            return
        except Exception:
            # Stale or invalid file_id — fall through to plain text
            pass
    # No photo path
    try:
        await message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


async def _doc_to_photo_id(message: Message, bot: Bot) -> str:
    """Download a document image and re-upload as photo to get a proper photo file_id."""
    try:
        file = await bot.get_file(message.document.file_id)
        data = BytesIO()
        await bot.download_file(file.file_path, data)
        data.seek(0)
        filename = message.document.file_name or "photo.jpg"
        # Send to same chat as photo, then delete — to get a photo file_id
        sent = await message.answer_photo(
            photo=BufferedInputFile(data.read(), filename=filename),
        )
        photo_id = sent.photo[-1].file_id
        try:
            await sent.delete()
        except Exception:
            pass
        return photo_id
    except Exception:
        logging.getLogger(__name__).warning("Failed to convert doc to photo, using doc file_id")
        return message.document.file_id


# Telegram photo captions max out at 1024 chars. The product card wraps the
# description in ~120 chars of chrome (name, price, unit, stock, rating, etc.),
# so once the description passes ~900 the full caption can exceed 1024 — at
# which point the card renders photo and text separately. We don't block it
# (sellers may want a long description), just warn so they can shorten it.
DESC_SOFT_LIMIT = 900


def _desc_warn_if_long(text: str, lang: str) -> str | None:
    """Return a soft warning message if a description risks the caption limit,
    else None."""
    n = len(text or "")
    return get_text("desc_too_long_warn", lang, n=n) if n > DESC_SOFT_LIMIT else None


class AddProductStates(StatesGroup):
    waiting_category = State()
    waiting_new_category = State()
    waiting_name = State()
    waiting_description = State()
    waiting_price = State()
    waiting_cost_price = State()
    waiting_unit = State()
    waiting_quantity = State()
    waiting_photo = State()
    waiting_extra_media = State()


class EditProductStates(StatesGroup):
    waiting_field = State()
    waiting_value = State()
    waiting_photo = State()
    waiting_extra_media = State()
    waiting_discount_days = State()


# ===== SELLER PANEL =====

@router.callback_query(F.data == "seller_panel")
async def show_seller_panel(callback: CallbackQuery):
    """Show seller panel (admin only)"""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("🚫", show_alert=True)
        return
    lang = await get_user_language(callback.from_user.id)

    await callback.message.edit_text(
        get_text("seller_panel", lang),
        reply_markup=seller_panel_keyboard(lang),
        parse_mode="HTML"
    )
    await callback.answer()


# ===== ADD PRODUCT FLOW =====

@router.callback_query(F.data == "seller:add_product")
async def start_add_product(callback: CallbackQuery, state: FSMContext):
    """Start adding a product — select category"""
    lang = await get_user_language(callback.from_user.id)
    await state.set_state(AddProductStates.waiting_category)
    await state.update_data(lang=lang)

    await callback.message.edit_text(
        get_text("select_product_category", lang),
        reply_markup=category_select_keyboard(lang, prefix="selcat", allow_new=True),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data == "selcat:__new__", AddProductStates.waiting_category)
async def prompt_new_category(callback: CallbackQuery, state: FSMContext):
    """Owner wants to add a brand-new category instead of picking an
    existing one — ask for its name, create it, then continue exactly like
    a normal category pick."""
    data = await state.get_data()
    lang = data.get("lang", "uz")
    await state.set_state(AddProductStates.waiting_new_category)
    prompt = ("🆕 Yangi kategoriya nomini kiriting (masalan: Go'sht mahsulotlari):"
              if lang != "ru" else "🆕 Введите название новой категории (например: Мясные продукты):")
    await callback.message.edit_text(prompt, parse_mode="HTML")
    await callback.answer()


@router.message(AddProductStates.waiting_new_category)
async def process_new_category(message: Message, state: FSMContext):
    """New category name typed — create it and drop straight into the
    normal "enter product name" step, same as picking an existing one."""
    import database

    data = await state.get_data()
    lang = data.get("lang", "uz")
    name = (message.text or "").strip()
    if not name:
        await message.answer(get_text("select_product_category", lang))
        return

    cat = await database.create_category(name_uz=name, name_ru=name)

    await state.update_data(category=cat["key"])
    await state.set_state(AddProductStates.waiting_name)
    await message.answer(get_text("enter_product_name", lang), parse_mode="HTML")


@router.callback_query(F.data.startswith("selcat:"), AddProductStates.waiting_category)
async def select_category(callback: CallbackQuery, state: FSMContext):
    """Category selected — ask for name"""
    category = callback.data.split(":")[1]
    data = await state.get_data()
    lang = data.get("lang", "uz")

    await state.update_data(category=category)
    await state.set_state(AddProductStates.waiting_name)

    await callback.message.edit_text(
        get_text("enter_product_name", lang),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(AddProductStates.waiting_name)
async def process_product_name(message: Message, state: FSMContext):
    """Process product name"""
    data = await state.get_data()
    lang = data.get("lang", "uz")

    await state.update_data(name=message.text.strip())
    await state.set_state(AddProductStates.waiting_description)
    await message.answer(get_text("enter_product_desc", lang), parse_mode="HTML")


@router.message(AddProductStates.waiting_description)
async def process_product_desc(message: Message, state: FSMContext):
    """Process product description"""
    data = await state.get_data()
    lang = data.get("lang", "uz")

    desc = message.text.strip()
    await state.update_data(description=desc)
    warn = _desc_warn_if_long(desc, lang)
    if warn:
        await message.answer(warn)
    await state.set_state(AddProductStates.waiting_price)
    await message.answer(get_text("enter_product_price", lang))


@router.message(AddProductStates.waiting_price, F.text)
async def process_product_price(message: Message, state: FSMContext):
    """Process product price, then ask for cost price (admin-only, /skip OK)."""
    data = await state.get_data()
    lang = data.get("lang", "uz")

    try:
        price = float(_clean_number(message.text))
        # 0 is allowed as a placeholder — the seller fills the real price in
        # via edit later. Only negatives are rejected.
        if price < 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer(get_text("invalid_price", lang))
        return

    await state.update_data(price=price)
    await state.set_state(AddProductStates.waiting_cost_price)
    await message.answer(get_text("enter_cost_price", lang), parse_mode="HTML")


@router.message(AddProductStates.waiting_cost_price, F.text)
async def process_product_cost_price(message: Message, state: FSMContext):
    """Cost price (what we paid to acquire). 0 or /skip both leave it empty."""
    data = await state.get_data()
    lang = data.get("lang", "uz")
    raw = (message.text or "").strip()

    if raw.lower() in ("/skip", "skip", "-"):
        cost = 0.0
    else:
        try:
            cost = float(_clean_number(raw))
            if cost < 0:
                raise ValueError
        except (ValueError, AttributeError):
            await message.answer(get_text("invalid_cost_price", lang))
            return

    # Unit picker removed — sellers found litr/gramm/kg/… confusing, so every
    # product now defaults to "piece" (dona) and the seller just enters a count.
    # (select_unit below stays as a no-op fallback for any FSM mid-add at deploy.)
    await state.update_data(cost_price=cost, unit="piece")
    await state.set_state(AddProductStates.waiting_quantity)
    await message.answer(get_text("enter_product_quantity", lang))


@router.callback_query(F.data.startswith("unit:"), AddProductStates.waiting_unit)
async def select_unit(callback: CallbackQuery, state: FSMContext):
    """Process unit selection"""
    unit = callback.data.split(":")[1]
    data = await state.get_data()
    lang = data.get("lang", "uz")

    await state.update_data(unit=unit)
    await state.set_state(AddProductStates.waiting_quantity)
    await callback.message.edit_text(get_text("enter_product_quantity", lang))
    await callback.answer()


@router.message(AddProductStates.waiting_quantity, F.text)
async def process_product_quantity(message: Message, state: FSMContext):
    """Process available quantity"""
    data = await state.get_data()
    lang = data.get("lang", "uz")

    try:
        quantity = float(_clean_number(message.text))
        # 0 is allowed as a placeholder (product shows as out-of-stock until
        # the seller edits the real quantity later). Only negatives rejected.
        if quantity < 0:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer(get_text("invalid_quantity", lang))
        return

    await state.update_data(quantity=quantity)
    await state.set_state(AddProductStates.waiting_photo)
    await message.answer(get_text("enter_product_photo", lang))


@router.message(AddProductStates.waiting_photo, F.photo)
async def process_product_photo(message: Message, state: FSMContext):
    """Process product photo"""
    photo_id = message.photo[-1].file_id  # Highest resolution
    await _save_product(message, state, photo_id)


@router.message(AddProductStates.waiting_photo, F.document.mime_type.startswith("image/"))
async def process_product_photo_as_doc(message: Message, state: FSMContext, bot: Bot):
    """Process product photo sent as document (uncompressed)"""
    photo_id = await _doc_to_photo_id(message, bot)
    await _save_product(message, state, photo_id)


@router.message(AddProductStates.waiting_photo, F.text.in_(["/skip", "skip"]))
async def skip_product_photo(message: Message, state: FSMContext):
    """Skip photo"""
    await _save_product(message, state, None)


async def _save_product(message: Message, state: FSMContext, photo_id: str | None):
    """Save product to database"""
    data = await state.get_data()
    lang = data.get("lang", "uz")

    try:
        # Ensure seller exists in users table (may be missing after DB migration)
        from database import create_user
        await create_user(
            message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        )

        # Auto-translate to Russian
        from translator import translate_product_fields
        name_ru, desc_ru = await translate_product_fields(data["name"], data["description"])

        product_id = await add_product(
            seller_id=message.from_user.id,
            name=data["name"],
            description=data["description"],
            price=data["price"],
            unit=data["unit"],
            quantity=data["quantity"],
            category=data["category"],
            photo_id=photo_id,
            name_ru=name_ru,
            description_ru=desc_ru,
            cost_price=data.get("cost_price", 0) or 0,
        )

        await set_user_as_seller(message.from_user.id)
        await state.update_data(new_product_id=product_id)
        await state.set_state(AddProductStates.waiting_extra_media)
        await message.answer(
            get_text("enter_extra_media", lang),
            parse_mode="HTML"
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Failed to save product: {e}")
        await state.clear()
        await message.answer(f"Error saving product: {e}")


@router.message(AddProductStates.waiting_extra_media, F.photo)
async def process_extra_media_photo(message: Message, state: FSMContext):
    """Save additional photo for the product"""
    data = await state.get_data()
    product_id = data["new_product_id"]
    photo_id = message.photo[-1].file_id
    await add_product_media(product_id, photo_id, "photo")
    lang = data.get("lang", "uz")
    await message.answer(get_text("extra_media_saved", lang))


@router.message(AddProductStates.waiting_extra_media, F.video)
async def process_extra_media_video(message: Message, state: FSMContext):
    """Save additional video for the product"""
    data = await state.get_data()
    product_id = data["new_product_id"]
    video_id = message.video.file_id
    await add_product_media(product_id, video_id, "video")
    lang = data.get("lang", "uz")
    await message.answer(get_text("extra_media_saved", lang))


@router.message(AddProductStates.waiting_extra_media, F.document.mime_type.startswith("image/"))
async def process_extra_media_doc_photo(message: Message, state: FSMContext, bot: Bot):
    """Save additional photo sent as document"""
    data = await state.get_data()
    product_id = data["new_product_id"]
    photo_id = await _doc_to_photo_id(message, bot)
    await add_product_media(product_id, photo_id, "photo")
    lang = data.get("lang", "uz")
    await message.answer(get_text("extra_media_saved", lang))


@router.message(AddProductStates.waiting_extra_media, F.document.mime_type.startswith("video/"))
async def process_extra_media_doc_video(message: Message, state: FSMContext):
    """Save additional video sent as document"""
    data = await state.get_data()
    product_id = data["new_product_id"]
    await add_product_media(product_id, message.document.file_id, "video")
    lang = data.get("lang", "uz")
    await message.answer(get_text("extra_media_saved", lang))


@router.message(AddProductStates.waiting_extra_media, F.text.in_(["/done", "done", "/skip", "skip"]))
async def finish_extra_media(message: Message, state: FSMContext):
    """Finish adding extra media"""
    data = await state.get_data()
    lang = data.get("lang", "uz")
    await state.clear()
    await message.answer(
        get_text("product_added", lang),
        reply_markup=seller_panel_keyboard(lang),
        parse_mode="HTML"
    )


# ===== MY PRODUCTS =====

PRODUCTS_PER_PAGE = 8


@router.callback_query(F.data == "seller:my_products")
async def show_my_products(callback: CallbackQuery):
    """Show seller's products (page 0)"""
    await _show_my_products_page(callback, 0)


@router.callback_query(F.data.startswith("seller_prods_page:"))
async def show_my_products_page(callback: CallbackQuery):
    """Show seller's products at a specific page"""
    page = int(callback.data.split(":")[1])
    await _show_my_products_page(callback, page)


async def _build_my_products_view(user_id: int, lang: str, page: int = 0):
    """Return (text, keyboard) for the My Products list at the given page,
    or (text, fallback_kb) when there are no products. Pure function — caller
    decides whether to edit_text, delete + answer, or whatever fits its
    context."""
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    is_admin = user_id in ADMIN_IDS
    products = await get_seller_products(user_id, all_products=is_admin)

    if not products:
        return get_text("no_seller_products", lang), seller_panel_keyboard(lang)

    total = len(products)
    total_pages = (total + PRODUCTS_PER_PAGE - 1) // PRODUCTS_PER_PAGE
    page = max(0, min(page, total_pages - 1))
    start = page * PRODUCTS_PER_PAGE
    page_products = products[start:start + PRODUCTS_PER_PAGE]

    if lang == "ru":
        title = "Мои товары"
    elif lang == "uz_cyr":
        title = "Менинг маҳсулотларим"
    else:
        title = "Mening mahsulotlarim"
    text = f"📋 <b>{title}</b> ({total}):\n\n"
    for i, p in enumerate(page_products, start + 1):
        display_name = localize_product_text(p.get("name"), p.get("name_ru"), lang)
        text += (
            f"{i}. <b>{display_name}</b>\n"
            f"   💰 {int(p['price']):,} so'm | "
            f"📦 {p['quantity']} {get_unit_name(p['unit'], lang)}\n\n"
        ).replace(",", " ")

    buttons: list[list[InlineKeyboardButton]] = []
    for p in page_products:
        # Page number is appended so we can return the seller to the same
        # page after they edit/delete this product.
        display_name = localize_product_text(p.get("name"), p.get("name_ru"), lang)
        buttons.append([InlineKeyboardButton(
            text=f"📦 {display_name}",
            callback_data=f"view_prod:{p['id']}:{page}"
        )])

    if total_pages > 1:
        nav_row = []
        if page > 0:
            nav_row.append(InlineKeyboardButton(text="◀️", callback_data=f"seller_prods_page:{page - 1}"))
        nav_row.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
        if page < total_pages - 1:
            nav_row.append(InlineKeyboardButton(text="▶️", callback_data=f"seller_prods_page:{page + 1}"))
        buttons.append(nav_row)
    buttons.append([InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="seller_panel")])
    return text, InlineKeyboardMarkup(inline_keyboard=buttons)


async def send_my_products_after_edit(message: Message, user_id: int, lang: str,
                                       prefix: str | None = None,
                                       page: int = 0) -> None:
    """After-edit nav: render the My Products list directly as a NEW message.
    `page` defaults to 0 but callers usually pass state['edit_page'] so the
    seller is returned to whichever page they were browsing."""
    text, kb = await _build_my_products_view(user_id, lang, page=page)
    if prefix:
        text = f"{prefix}\n\n{text}"
    await message.answer(text, reply_markup=kb, parse_mode="HTML")


async def _show_my_products_page(callback: CallbackQuery, page: int):
    """Display paginated product list for seller/admin (callback context)."""
    lang = await get_user_language(callback.from_user.id)
    text, kb = await _build_my_products_view(callback.from_user.id, lang, page=page)

    try:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


def _parse_id_page(data: str, default_page: int = 0) -> tuple[int, int]:
    """Pull `id` and optional `page` out of callback data like
    'view_prod:42:3' or 'view_prod:42'. Older messages without the page
    suffix fall back to default_page so they keep working."""
    parts = data.split(":")
    pid = int(parts[1])
    try:
        page = int(parts[2]) if len(parts) > 2 else default_page
    except ValueError:
        page = default_page
    return pid, page


@router.callback_query(F.data.startswith("view_prod:"))
async def view_product(callback: CallbackQuery):
    """View seller's product details"""
    product_id, page = _parse_id_page(callback.data)
    lang = await get_user_language(callback.from_user.id)
    product = await get_product(product_id)

    if not product:
        await callback.answer("❌")
        return

    text = get_text("product_card", lang,
        name=localize_product_text(product.get("name"), product.get("name_ru"), lang),
        description=localize_product_text(product.get("description"), product.get("description_ru"), lang) or "—",
        price=f"{int(product['price']):,}".replace(",", " "),
        unit=get_unit_name(product["unit"], lang),
        available=product["quantity"],
        seller=product.get("seller_name", "—"),
    )
    keyboard = seller_product_keyboard(lang, product_id, page=page)
    await _send_with_optional_photo(callback.message, text, keyboard, product.get("photo_id"))
    await callback.answer()


@router.callback_query(F.data.startswith("edit_prod:"))
async def start_edit_product(callback: CallbackQuery, state: FSMContext):
    """Show edit options for a product"""
    product_id, page = _parse_id_page(callback.data)
    lang = await get_user_language(callback.from_user.id)

    product = await get_product(product_id)
    is_admin = callback.from_user.id in ADMIN_IDS
    if not product or (product["seller_id"] != callback.from_user.id and not is_admin):
        await callback.answer("❌", show_alert=True)
        return

    # Stash the originating page so all nested edit handlers (including the
    # ones triggered by text input later) can put the seller back where they
    # were browsing.
    await state.update_data(edit_page=page)

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=get_text("btn_edit_name", lang), callback_data=f"editf:name:{product_id}"),
            InlineKeyboardButton(text=get_text("btn_edit_price", lang), callback_data=f"editf:price:{product_id}"),
        ],
        [
            InlineKeyboardButton(text=get_text("btn_edit_desc", lang), callback_data=f"editf:description:{product_id}"),
            InlineKeyboardButton(text=get_text("btn_edit_quantity", lang), callback_data=f"editf:quantity:{product_id}"),
        ],
        [
            InlineKeyboardButton(text=get_text("btn_edit_photo", lang), callback_data=f"editf:photo_id:{product_id}"),
            InlineKeyboardButton(text=get_text("btn_edit_media", lang), callback_data=f"edit_media:{product_id}"),
        ],
        [
            InlineKeyboardButton(text=get_text("btn_edit_discount", lang), callback_data=f"editf:discount_percent:{product_id}"),
            InlineKeyboardButton(text=get_text("btn_edit_low_stock", lang), callback_data=f"editf:low_stock_threshold:{product_id}"),
        ],
        [InlineKeyboardButton(text=get_text("btn_edit_cost_price", lang), callback_data=f"editf:cost_price:{product_id}")],
        [InlineKeyboardButton(text=get_text("btn_edit_category", lang), callback_data=f"editf:category:{product_id}")],
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data=f"view_prod:{product_id}")],
    ])

    await _send_with_optional_photo(
        callback.message,
        get_text("edit_product_choose", lang, name=product["name"]),
        keyboard,
        product.get("photo_id"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("editf:"))
async def select_edit_field(callback: CallbackQuery, state: FSMContext):
    """Field selected for editing — ask for new value"""
    _, field, product_id = callback.data.split(":")
    product_id = int(product_id)
    lang = await get_user_language(callback.from_user.id)

    if field == "photo_id":
        await state.set_state(EditProductStates.waiting_photo)
        await state.update_data(edit_product_id=product_id, lang=lang)
        await _safe_edit_or_resend(
            callback.message,
            get_text("enter_product_photo_edit", lang),
        )
        await callback.answer()
        return

    if field == "category":
        # Category is a multi-choice — show the same selector used at add time,
        # but with a special prefix so we can route the chosen value back here.
        await _safe_edit_or_resend(
            callback.message,
            get_text("select_product_category", lang),
            reply_markup=category_select_keyboard(lang, prefix=f"editcat:{product_id}"),
        )
        await callback.answer()
        return

    prompts = {
        "name": "enter_product_name",
        "description": "enter_product_desc",
        "price": "enter_product_price",
        "quantity": "enter_product_quantity",
        "discount_percent": "enter_product_discount",
        "low_stock_threshold": "enter_low_stock_threshold",
        "cost_price": "enter_cost_price",
    }

    await state.set_state(EditProductStates.waiting_value)
    await state.update_data(edit_field=field, edit_product_id=product_id, lang=lang)

    await _safe_edit_or_resend(
        callback.message,
        get_text(prompts[field], lang),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("editcat:"))
async def process_edit_category(callback: CallbackQuery, state: FSMContext):
    """Handle category-pick from the edit flow: callback is editcat:PID:CAT."""
    parts = callback.data.split(":")
    if len(parts) < 3:
        await callback.answer("❌")
        return
    try:
        product_id = int(parts[1])
    except ValueError:
        await callback.answer("❌")
        return
    category = parts[2]
    if category not in CATEGORIES:
        await callback.answer("❌")
        return

    lang = await get_user_language(callback.from_user.id)
    product = await get_product(product_id)
    is_admin = callback.from_user.id in ADMIN_IDS
    if not product or (product["seller_id"] != callback.from_user.id and not is_admin):
        await callback.answer("❌", show_alert=True)
        return

    data = await state.get_data()
    await update_product(product_id, category=category)
    await send_my_products_after_edit(
        callback.message, callback.from_user.id, lang,
        prefix=("✅ Mahsulot yangilandi" if lang == "uz" else "✅ Товар обновлён"),
        page=data.get("edit_page", 0),
    )
    await callback.answer()


@router.message(EditProductStates.waiting_value, F.text)
async def process_edit_value(message: Message, state: FSMContext):
    """Process the new value for the edited field"""
    data = await state.get_data()
    lang = data.get("lang", "uz")
    field = data["edit_field"]
    product_id = data["edit_product_id"]

    value = message.text.strip()

    # Validate numeric fields
    if field in ("price", "quantity"):
        try:
            value = float(_clean_number(value))
            # 0 allowed (placeholder price / out-of-stock quantity); reject only
            # negatives — matches the add-product flow.
            if value < 0:
                raise ValueError
        except (ValueError, AttributeError):
            error_key = "invalid_price" if field == "price" else "invalid_quantity"
            await message.answer(get_text(error_key, lang))
            return
    elif field == "cost_price":
        # /skip clears it (sets to 0); otherwise must be 0+ number
        raw_str = (value or "").strip()
        if raw_str.lower() in ("/skip", "skip", "-"):
            cost = 0.0
        else:
            try:
                cost = float(_clean_number(raw_str))
                if cost < 0:
                    raise ValueError
            except (ValueError, AttributeError):
                await message.answer(get_text("invalid_cost_price", lang))
                return
        await update_product(product_id, cost_price=cost)
        await state.clear()
        await send_my_products_after_edit(
            message, message.from_user.id, lang,
            prefix=("✅ Mahsulot yangilandi" if lang == "uz" else "✅ Товар обновлён"),
            page=data.get("edit_page", 0),
        )
        return

    elif field == "low_stock_threshold":
        try:
            n = int(float(_clean_number(value)))
            if n < 0:
                raise ValueError
        except (ValueError, AttributeError):
            await message.answer(get_text("invalid_low_stock_threshold", lang))
            return
        # 0 = use global default → store NULL so COALESCE picks it up
        await update_product(product_id, low_stock_threshold=(None if n == 0 else n))
        await state.clear()
        await send_my_products_after_edit(
            message, message.from_user.id, lang,
            prefix=("✅ Mahsulot yangilandi" if lang == "uz" else "✅ Товар обновлён"),
            page=data.get("edit_page", 0),
        )
        return

    elif field == "discount_percent":
        try:
            value = int(float(_clean_number(value)))
            if value < 0 or value > 100:
                raise ValueError
        except (ValueError, AttributeError):
            await message.answer(get_text("invalid_discount", lang))
            return

        if value == 0:
            # Clearing the discount also clears any existing expiry
            await update_product(product_id, discount_percent=0, discount_until=None)
            await state.clear()
            await send_my_products_after_edit(
            message, message.from_user.id, lang,
            prefix=("✅ Mahsulot yangilandi" if lang == "uz" else "✅ Товар обновлён"),
            page=data.get("edit_page", 0),
        )
            return

        # Discount > 0: ask for validity days as a follow-up
        await state.update_data(pending_discount=value)
        await state.set_state(EditProductStates.waiting_discount_days)
        await message.answer(get_text("enter_discount_days", lang))
        return

    await update_product(product_id, **{field: value})

    # Auto-translate name/description to Russian
    if field in ("name", "description"):
        from translator import translate
        ru_value = await translate(value, "uz", "ru")
        ru_field = f"{field}_ru" if field == "description" else "name_ru"
        await update_product(product_id, **{ru_field: ru_value})

    await state.clear()

    if field == "description":
        warn = _desc_warn_if_long(value, lang)
        if warn:
            await message.answer(warn)

    await send_my_products_after_edit(
            message, message.from_user.id, lang,
            prefix=("✅ Mahsulot yangilandi" if lang == "uz" else "✅ Товар обновлён"),
            page=data.get("edit_page", 0),
        )


@router.message(EditProductStates.waiting_discount_days, F.text)
async def process_discount_days(message: Message, state: FSMContext):
    """Second step of discount edit: how many days the discount stays valid."""
    from datetime import datetime, timedelta, timezone

    data = await state.get_data()
    lang = data.get("lang", "uz")
    product_id = data["edit_product_id"]
    percent = data.get("pending_discount", 0)

    try:
        days = int(float(_clean_number(message.text.strip())))
        if days < 0 or days > 365:
            raise ValueError
    except (ValueError, AttributeError):
        await message.answer(get_text("invalid_discount_days", lang))
        return

    if days == 0:
        discount_until = None
    else:
        discount_until = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=days)

    await update_product(product_id, discount_percent=percent, discount_until=discount_until)
    await state.clear()
    await send_my_products_after_edit(
            message, message.from_user.id, lang,
            prefix=("✅ Mahsulot yangilandi" if lang == "uz" else "✅ Товар обновлён"),
            page=data.get("edit_page", 0),
        )


@router.message(EditProductStates.waiting_photo, F.photo)
async def process_edit_photo(message: Message, state: FSMContext):
    """Process the new photo for the product"""
    data = await state.get_data()
    lang = data.get("lang", "uz")
    product_id = data["edit_product_id"]

    photo_id = message.photo[-1].file_id
    await update_product(product_id, photo_id=photo_id)
    await state.clear()

    await send_my_products_after_edit(
            message, message.from_user.id, lang,
            prefix=("✅ Mahsulot yangilandi" if lang == "uz" else "✅ Товар обновлён"),
            page=data.get("edit_page", 0),
        )


@router.message(EditProductStates.waiting_photo, F.document.mime_type.startswith("image/"))
async def process_edit_photo_as_doc(message: Message, state: FSMContext, bot: Bot):
    """Process the new photo sent as document (uncompressed)"""
    data = await state.get_data()
    lang = data.get("lang", "uz")
    product_id = data["edit_product_id"]

    photo_id = await _doc_to_photo_id(message, bot)
    await update_product(product_id, photo_id=photo_id)
    await state.clear()

    await send_my_products_after_edit(
            message, message.from_user.id, lang,
            prefix=("✅ Mahsulot yangilandi" if lang == "uz" else "✅ Товар обновлён"),
            page=data.get("edit_page", 0),
        )


@router.callback_query(F.data.startswith("edit_media:"))
async def show_edit_media(callback: CallbackQuery, state: FSMContext):
    """Show current media and offer to add more"""
    product_id = int(callback.data.split(":")[1])
    lang = await get_user_language(callback.from_user.id)
    media = await get_product_media(product_id)

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    buttons = []
    for m in media:
        emoji = "📸" if m["media_type"] == "photo" else "🎬"
        buttons.append([InlineKeyboardButton(
            text=f"❌ {emoji} #{m['sort_order'] + 1}",
            callback_data=f"del_media:{m['id']}:{product_id}"
        )])

    buttons.append([InlineKeyboardButton(
        text=get_text("btn_add_media", lang),
        callback_data=f"add_media:{product_id}"
    )])
    buttons.append([InlineKeyboardButton(
        text=get_text("btn_back", lang),
        callback_data=f"edit_prod:{product_id}"
    )])

    count = len(media)
    text = get_text("media_list", lang, count=count)
    await _safe_edit_or_resend(callback.message, text,
                                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()


@router.callback_query(F.data.startswith("del_media:"))
async def do_delete_media(callback: CallbackQuery):
    """Delete a media item"""
    _, media_id, product_id = callback.data.split(":")
    await delete_product_media(int(media_id))
    # Refresh the media list
    callback.data = f"edit_media:{product_id}"
    await show_edit_media(callback, None)


@router.callback_query(F.data.startswith("add_media:"))
async def start_add_media(callback: CallbackQuery, state: FSMContext):
    """Start adding extra media to existing product"""
    product_id = int(callback.data.split(":")[1])
    lang = await get_user_language(callback.from_user.id)
    await state.set_state(EditProductStates.waiting_extra_media)
    await state.update_data(edit_product_id=product_id, lang=lang)
    await _safe_edit_or_resend(callback.message, get_text("enter_extra_media", lang))
    await callback.answer()


@router.message(EditProductStates.waiting_extra_media, F.photo)
async def edit_extra_media_photo(message: Message, state: FSMContext):
    """Add extra photo to existing product"""
    data = await state.get_data()
    product_id = data["edit_product_id"]
    await add_product_media(product_id, message.photo[-1].file_id, "photo")
    lang = data.get("lang", "uz")
    await message.answer(get_text("extra_media_saved", lang))


@router.message(EditProductStates.waiting_extra_media, F.video)
async def edit_extra_media_video(message: Message, state: FSMContext):
    """Add extra video to existing product"""
    data = await state.get_data()
    product_id = data["edit_product_id"]
    await add_product_media(product_id, message.video.file_id, "video")
    lang = data.get("lang", "uz")
    await message.answer(get_text("extra_media_saved", lang))


@router.message(EditProductStates.waiting_extra_media, F.document.mime_type.startswith("image/"))
async def edit_extra_media_doc_photo(message: Message, state: FSMContext, bot: Bot):
    """Add extra photo sent as document"""
    data = await state.get_data()
    product_id = data["edit_product_id"]
    photo_id = await _doc_to_photo_id(message, bot)
    await add_product_media(product_id, photo_id, "photo")
    lang = data.get("lang", "uz")
    await message.answer(get_text("extra_media_saved", lang))


@router.message(EditProductStates.waiting_extra_media, F.document.mime_type.startswith("video/"))
async def edit_extra_media_doc_video(message: Message, state: FSMContext):
    """Add extra video sent as document"""
    data = await state.get_data()
    product_id = data["edit_product_id"]
    await add_product_media(product_id, message.document.file_id, "video")
    lang = data.get("lang", "uz")
    await message.answer(get_text("extra_media_saved", lang))


@router.message(EditProductStates.waiting_extra_media, F.text.in_(["/done", "done", "/skip", "skip"]))
async def finish_edit_extra_media(message: Message, state: FSMContext):
    """Finish adding extra media"""
    data = await state.get_data()
    lang = data.get("lang", "uz")
    await state.clear()
    await send_my_products_after_edit(
            message, message.from_user.id, lang,
            prefix=("✅ Mahsulot yangilandi" if lang == "uz" else "✅ Товар обновлён"),
            page=data.get("edit_page", 0),
        )


@router.callback_query(F.data.startswith("del_prod:"))
async def ask_delete_product(callback: CallbackQuery):
    """Confirm product deletion"""
    product_id, page = _parse_id_page(callback.data)
    lang = await get_user_language(callback.from_user.id)

    await _safe_edit_or_resend(
        callback.message,
        get_text("confirm_delete", lang),
        reply_markup=confirm_delete_keyboard(lang, product_id, page=page),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_del:"))
async def do_delete_product(callback: CallbackQuery):
    """Actually delete the product"""
    product_id, page = _parse_id_page(callback.data)
    lang = await get_user_language(callback.from_user.id)

    product = await get_product(product_id)
    is_admin = callback.from_user.id in ADMIN_IDS
    if not product or (product["seller_id"] != callback.from_user.id and not is_admin):
        await callback.answer("❌", show_alert=True)
        return

    await delete_product(product_id)
    # Drop the confirmation bubble and render the refreshed products list
    try:
        await callback.message.delete()
    except Exception:
        pass
    prefix = "✅ Mahsulot o'chirildi" if lang == "uz" else "✅ Товар удалён"
    await send_my_products_after_edit(
        callback.message, callback.from_user.id, lang, prefix=prefix, page=page,
    )
    await callback.answer()


# ===== SELLER ORDERS =====

@router.callback_query(F.data == "seller:orders")
async def show_seller_orders(callback: CallbackQuery):
    """Show orders for this seller"""
    lang = await get_user_language(callback.from_user.id)
    is_admin = callback.from_user.id in ADMIN_IDS
    orders = await get_seller_orders(callback.from_user.id, all_orders=is_admin)

    if not orders:
        await callback.message.edit_text(
            get_text("seller_no_orders", lang),
            reply_markup=seller_panel_keyboard(lang),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    text = "📦 <b>" + ("Buyurtmalar" if lang == "uz" else "Заказы") + ":</b>\n\n"
    buttons = []
    for order in orders[:10]:
        status = get_order_status(order["status"], lang)
        total_str = f"{int(order['total']):,}".replace(",", " ")
        delivery_label = get_delivery_method_name(order.get("delivery_method"), lang)

        # Lifecycle: created → (confirmed) → (shipped) → (delivered) — same
        # shape the admin orders list uses, so sellers see the full timeline.
        lifecycle = f"📅 {format_local_dt(order['created_at'])}"
        if order.get("confirmed_at"):
            lifecycle += f" → ✅ {format_local_dt(order['confirmed_at'])}"
        if order.get("shipped_at"):
            lifecycle += f" → 🚚 {format_local_dt(order['shipped_at'])}"
        if order.get("delivered_at"):
            lifecycle += f" → 📦 {format_local_dt(order['delivered_at'])}"

        text += (
            f"#{order['id']} | {status} | 💰 {total_str}\n"
            f"   👤 {html.escape(order.get('customer_name') or '—')} | 📱 {html.escape(order.get('phone') or '—')}\n"
            f"   🚚 {delivery_label}\n"
            f"   {lifecycle}\n\n"
        )
        buttons.append([InlineKeyboardButton(
            text=f"#{order['id']} — {status}",
            callback_data=f"seller_order:{order['id']}"
        )])

    buttons.append([InlineKeyboardButton(
        text=get_text("btn_back", lang), callback_data="seller_panel"
    )])

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("seller_order:"))
async def view_seller_order(callback: CallbackQuery):
    """View order details for seller"""
    import json
    order_id = int(callback.data.split(":")[1])
    lang = await get_user_language(callback.from_user.id)
    order = await get_order(order_id)

    if not order:
        await callback.answer("❌")
        return

    items = json.loads(order["items"]) if isinstance(order["items"], str) else order["items"]
    items_text = ""
    saved_total = 0
    for item in items:
        new_p = f"{int(item['price']):,}".replace(",", " ")
        op = item.get("original_price")
        dp = item.get("discount_percent")
        if dp and op and op > item["price"]:
            old_p = f"{int(op):,}".replace(",", " ")
            price_part = f"<s>{old_p}</s> {new_p} 🔥-{dp}%"
            saved_total += (op - item["price"]) * item["quantity"]
        else:
            price_part = new_p
        items_text += f"• {item['name']} — {item['quantity']} {item.get('unit', '')} × {price_part}\n"
    saved_block = ""
    if saved_total > 0:
        saved_block = get_text("new_order_discount_total", lang,
                               amount=f"{int(saved_total):,}".replace(",", " "))

    from handlers.cart import buyer_contact_link, payment_status_block, SELF_DELIVERY_FEE
    buyer = await get_user(order["user_id"])
    contact = buyer_contact_link(
        order["user_id"],
        buyer.get("username") if buyer else None,
        order["customer_name"],
    )

    note = order.get("address_note")
    note_block = f"\n📝 {note}" if note else ""
    sec = order.get("secondary_phone")
    secondary_block = f"\n📞 {sec}" if sec else ""
    delivery_fee = SELF_DELIVERY_FEE if order.get("delivery_method") == "self" else 0
    delivery_fee_block = get_text("delivery_fee_line", lang, fee=f"{delivery_fee:,}".replace(",", " ")) if delivery_fee else ""
    text = get_text("new_order_notification", lang,
        order_id=order["id"],
        name=order["customer_name"],
        phone=order["phone"],
        secondary_block=secondary_block,
        contact=contact,
        address=order["address"],
        note_block=note_block,
        delivery=get_delivery_method_name(order.get("delivery_method"), lang),
        payment_block=payment_status_block(order.get("payment_method"), order.get("status"), lang),
        items=items_text,
        delivery_fee_block=delivery_fee_block,
        total=f"{int(order['total']):,}".replace(",", " "),
        saved_block=saved_block,
    )

    # Lifecycle timestamps block
    created_label = "📅 Buyurtma:" if lang == "uz" else "📅 Заказ:"
    confirmed_label = "✅ Qabul qilindi:" if lang == "uz" else "✅ Принят:"
    shipped_label = "🚚 Yo'lga chiqdi:" if lang == "uz" else "🚚 Отправлен:"
    delivered_label = "📦 Yetkazildi:" if lang == "uz" else "📦 Доставлен:"
    lifecycle_lines = [f"{created_label} {format_local_dt(order['created_at'])}"]
    if order.get("confirmed_at"):
        lifecycle_lines.append(f"{confirmed_label} {format_local_dt(order['confirmed_at'])}")
    if order.get("shipped_at"):
        lifecycle_lines.append(f"{shipped_label} {format_local_dt(order['shipped_at'])}")
    if order.get("delivered_at"):
        lifecycle_lines.append(f"{delivered_label} {format_local_dt(order['delivered_at'])}")
    text += "\n\n" + "\n".join(lifecycle_lines)

    is_admin = callback.from_user.id in ADMIN_IDS
    await callback.message.edit_text(
        text,
        reply_markup=seller_order_keyboard(lang, order_id, order["status"], is_admin=is_admin),
        parse_mode="HTML"
    )

    # Drop the delivery pin and, for online orders, the payment cheque right
    # below the card so the admin can act on them without digging.
    if order.get("latitude") and order.get("longitude"):
        try:
            await callback.message.answer_location(
                latitude=order["latitude"], longitude=order["longitude"])
        except Exception:
            pass
    cheque_id = order.get("cheque_file_id")
    if cheque_id:
        cap = get_text("order_cheque_caption", lang, order_id=order_id)
        try:
            if order.get("cheque_type") == "document":
                await callback.message.answer_document(cheque_id, caption=cap, parse_mode="HTML")
            else:
                await callback.message.answer_photo(cheque_id, caption=cap, parse_mode="HTML")
        except Exception:
            pass

    await callback.answer()


@router.callback_query(F.data.startswith("order_act:"))
async def handle_order_action(callback: CallbackQuery, bot: Bot):
    """Handle seller order actions (accept, reject, mark delivered).

    Callback: order_act:ACTION:ID  with an optional return context
    order_act:ACTION:ID:list:FILTER:PAGE — appended by the admin order list so
    we refresh that list in place instead of switching to a panel."""
    parts = callback.data.split(":")
    action = parts[1]
    order_id = int(parts[2])
    # (status_filter, page) of the admin list to return to, or None.
    list_ctx = None
    if len(parts) >= 6 and parts[3] == "list":
        try:
            list_ctx = (parts[4], int(parts[5]))
        except ValueError:
            list_ctx = None
    lang = await get_user_language(callback.from_user.id)

    order = await get_order(order_id)
    is_admin = callback.from_user.id in ADMIN_IDS
    if not order or (order["seller_id"] != callback.from_user.id and not is_admin):
        await callback.answer("❌", show_alert=True)
        return

    status_map = {
        "confirm": "confirmed",
        "ship": "shipped",
        "cancel": "cancelled",
        "delivered": "delivered",
    }
    new_status = status_map.get(action, "pending")

    if new_status == "cancelled":
        # Atomic: flips status + restores stock in one transaction (idempotent)
        await db_cancel_order(order_id)
    else:
        # Guard against two admins racing on the same order — only one of the
        # conditional UPDATEs lands; the loser short-circuits with a toast.
        expected_from = {"confirmed": "pending", "shipped": "confirmed", "delivered": "shipped"}.get(new_status)
        won = await transition_order_status(order_id, expected_from, new_status)
        if not won:
            if list_ctx is not None and is_admin:
                from handlers.admin import render_orders_list
                status_filter, page = list_ctx
                await render_orders_list(callback, status_filter, page, lang)
            await callback.answer(get_text("order_act_already_done", lang), show_alert=True)
            return

    order = await get_order(order_id)

    # Notify buyer with a status-specific message
    if order:
        buyer_lang = await get_user_language(order["user_id"])
        buyer_key = {
            "confirmed": "buyer_order_confirmed",
            "shipped": "buyer_order_shipped",
            "cancelled": "buyer_order_cancelled",
            "delivered": "buyer_order_delivered",
        }.get(new_status)
        try:
            if buyer_key:
                reply_markup = None
                if new_status == "delivered":
                    from keyboards import delivered_feedback_keyboard
                    reply_markup = delivered_feedback_keyboard(buyer_lang, order_id)
                elif new_status == "cancelled":
                    from keyboards import order_cancelled_keyboard
                    reply_markup = order_cancelled_keyboard(buyer_lang)

                when, timeline = _build_buyer_status_block(order, new_status, buyer_lang)
                await bot.send_message(
                    chat_id=order["user_id"],
                    text=get_text(buyer_key, buyer_lang,
                                  order_id=order_id, when=when, timeline=timeline),
                    reply_markup=reply_markup,
                    parse_mode="HTML",
                )
            else:
                await bot.send_message(
                    chat_id=order["user_id"],
                    text=get_text("order_status_updated", buyer_lang,
                        order_id=order_id,
                        status=get_order_status(new_status, buyer_lang),
                    ),
                    parse_mode="HTML",
                )
        except Exception:
            pass

        # Extra warm nudge exactly on a repeat buyer's 2nd delivered order —
        # on top of the standard delivered_feedback_keyboard prompt above.
        # Reuses the existing review_order flow (product picker + rating +
        # comment FSM) rather than duplicating it.
        if new_status == "delivered":
            try:
                delivered_count = await get_user_delivered_order_count(order["user_id"])
                if delivered_count == 2:
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text=get_text("btn_leave_review", buyer_lang),
                                              callback_data=f"review_order:{order_id}")],
                    ])
                    await bot.send_message(
                        chat_id=order["user_id"],
                        text=get_text("buyer_second_order_review_ask", buyer_lang),
                        reply_markup=kb,
                        parse_mode="HTML",
                    )
            except Exception:
                pass

            # Keto gamification (test rollout) — separate celebratory message,
            # sent after the delivery notification so the reward stands out
            # on its own. Best-effort/self-guarded: see gamification.py.
            from gamification import award_keto_for_order
            await award_keto_for_order(order, bot)

    msg_key = {
        "confirm": "order_accepted",
        "ship": "order_marked_shipped",
        "cancel": "order_rejected",
        "delivered": "order_marked_delivered",
    }.get(action, "order_accepted")

    # Came from the admin order list → refresh that same list (filter+page) in
    # place and surface the result as a toast, so the admin keeps working
    # through the list instead of being bounced to a panel.
    if list_ctx is not None and is_admin:
        from handlers.admin import render_orders_list
        status_filter, page = list_ctx
        await render_orders_list(callback, status_filter, page, lang)
        await callback.answer(get_text(msg_key, lang))
        return

    await callback.message.edit_text(
        get_text(msg_key, lang),
        reply_markup=seller_panel_keyboard(lang),
        parse_mode="HTML"
    )
    await callback.answer()


# ===== SELLER STATS =====
# Seller stats now reuse the admin stats view (time windows, funnel, top products).

@router.callback_query(F.data == "seller:stats")
async def show_seller_stats(callback: CallbackQuery):
    """Show stats inside the seller panel — same view as admin stats."""
    from handlers.admin import render_stats
    await render_stats(callback, "today", "seller:stats", "seller_panel")
    await callback.answer()


@router.callback_query(F.data.startswith("seller:stats:"))
async def switch_seller_stats_period(callback: CallbackQuery):
    from handlers.admin import render_stats
    period = callback.data.split(":", 2)[2]
    if period not in ("today", "7d", "30d", "all"):
        period = "today"
    await render_stats(callback, period, "seller:stats", "seller_panel")
    await callback.answer()


# ===== MESSAGE A CLIENT THROUGH THE BOT =====
# From an order's card the admin/seller can send the buyer a free-text message
# that arrives *from the bot* (the shop), not from a personal account.
class MessageClientStates(StatesGroup):
    waiting_message = State()


@router.callback_query(F.data.startswith("msgclient:"))
async def message_client_start(callback: CallbackQuery, state: FSMContext):
    order_id = int(callback.data.split(":")[1])
    order = await get_order(order_id)
    is_admin = callback.from_user.id in ADMIN_IDS
    if not order or (order["seller_id"] != callback.from_user.id and not is_admin):
        await callback.answer("❌", show_alert=True)
        return
    lang = await get_user_language(callback.from_user.id)
    await state.set_state(MessageClientStates.waiting_message)
    await state.update_data(mc_order_id=order_id, mc_target=order["user_id"], lang=lang)
    await callback.message.answer(
        get_text("message_client_prompt", lang, order_id=order_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(MessageClientStates.waiting_message, F.text)
async def message_client_send(message: Message, state: FSMContext, bot: Bot):
    import html
    data = await state.get_data()
    lang = data.get("lang", "uz")
    raw = (message.text or "").strip()
    if raw.lower() in ("/cancel", "cancel", "bekor"):
        await state.clear()
        await message.answer(get_text("message_client_cancelled", lang))
        return
    order_id = data.get("mc_order_id")
    target = data.get("mc_target")
    await state.clear()
    if not target:
        await message.answer(get_text("message_client_failed", lang))
        return
    buyer_lang = await get_user_language(target)
    header = get_text("message_client_received", buyer_lang, order_id=order_id)
    try:
        await bot.send_message(
            chat_id=target,
            text=f"{header}\n\n{html.escape(raw)}",
            parse_mode="HTML",
        )
        await message.answer(get_text("message_client_sent", lang))
    except Exception:
        await message.answer(get_text("message_client_failed", lang))
