"""
Catalog browsing and product viewing
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from database import get_active_sets_for_catalog, get_set
from database import (
    get_user_language, get_products_by_category, get_discounted_products,
    get_product, get_product_rating, add_product_view,
    effective_price, active_discount,
    get_cart_line_for_product, add_to_cart, set_cart_quantity, remove_from_cart,
    get_cart_count,
)
from locales import get_text, get_category_name, get_unit_name, get_display_unit, localize_product_text
from keyboards import categories_keyboard, back_to_menu_keyboard, cart_shortcut_row
from config import ITEMS_PER_PAGE

router = Router()

PRODUCTS_PER_PAGE = 10


@router.callback_query(F.data == "catalog")
async def show_catalog(callback: CallbackQuery):
    """Show product categories"""
    lang = await get_user_language(callback.from_user.id)
    text = get_text("categories_title", lang)
    cart_count = await get_cart_count(callback.from_user.id)
    keyboard = categories_keyboard(lang, cart_count)

    if callback.message.photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "discounts")
async def show_discounts(callback: CallbackQuery):
    """Discounts section — only products with an active discount, all categories."""
    await _show_product_list(callback, "discounts", 0)


@router.callback_query(F.data.startswith("cat:"))
async def show_category(callback: CallbackQuery):
    """Show product list as buttons"""
    parts = callback.data.split(":")
    category = parts[1]
    page = int(parts[2]) if len(parts) > 2 else 0
    await _show_product_list(callback, category, page)


@router.callback_query(F.data.startswith("product:"))
async def show_product_detail(callback: CallbackQuery):
    """Show single product detail card"""
    parts = callback.data.split(":")
    product_id = int(parts[1])
    back_category = parts[2] if len(parts) > 2 else ""
    back_page = int(parts[3]) if len(parts) > 3 else 0
    await _render_product_detail(callback, product_id, back_category, back_page, track_view=True)


async def _render_product_detail(callback: CallbackQuery, product_id: int,
                                 back_category: str, back_page: int,
                                 track_view: bool = False):
    """Build the product card (caption + stepper/add-to-cart row) and edit-or-resend.
    Shared by show_product_detail and the +/- handlers so the same bubble updates
    in place when the buyer bumps the quantity."""
    lang = await get_user_language(callback.from_user.id)
    product = await get_product(product_id)

    if not product:
        await callback.answer("Not found", show_alert=True)
        return

    # Track product view for analytics — only on first open, not on every +/-.
    if track_view:
        try:
            await add_product_view(product_id, callback.from_user.id)
        except Exception:
            pass

    seller_name = product.get("seller_name") or product.get("seller_username") or "—"
    prod_name = localize_product_text(product.get("name"), product.get("name_ru"), lang)
    prod_desc = localize_product_text(product.get("description"), product.get("description_ru"), lang) or "—"

    discount_until = product.get("discount_until")
    discount = active_discount(product.get("discount_percent"), discount_until)
    final_price = effective_price(product["price"], discount, discount_until)

    text = get_text("product_card", lang,
        name=prod_name,
        description=prod_desc,
        price=f"{int(final_price):,}".replace(",", " "),
        unit=get_display_unit(product["unit"], lang),
        available=product["quantity"],
        seller=seller_name,
    )

    if discount > 0:
        text += "\n" + get_text("product_discount_line", lang,
            percent=discount,
            old=f"{int(product['price']):,}".replace(",", " "),
            new=f"{int(final_price):,}".replace(",", " "),
            saved=f"{int(product['price'] - final_price):,}".replace(",", " "),
        )
        if discount_until:
            text += "\n" + get_text("product_discount_until", lang,
                date=discount_until.strftime("%d.%m.%Y %H:%M"),
            )

    out_of_stock = product["quantity"] <= 0
    if out_of_stock:
        text += "\n\n" + get_text("product_out_of_stock", lang)

    # Add rating
    avg_rating, review_count = await get_product_rating(product["id"])
    if review_count > 0:
        text += "\n" + get_text("product_rating_line", lang, rating=avg_rating, count=review_count)

    keyboard = await _detail_keyboard(callback.from_user.id, product_id, back_category, back_page, lang, out_of_stock)

    try:
        if product.get("photo_id"):
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer_photo(
                photo=product["photo_id"],
                caption=text,
                reply_markup=keyboard,
                parse_mode="HTML"
            )
        else:
            if callback.message.photo:
                try:
                    await callback.message.delete()
                except Exception:
                    pass
                await callback.message.answer(
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
            else:
                await callback.message.edit_text(
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML"
                )
    except Exception:
        await callback.message.answer(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )

    await callback.answer()


async def _detail_keyboard(user_id: int, product_id: int, back_category: str,
                           back_page: int, lang: str, out_of_stock: bool) -> InlineKeyboardMarkup:
    """Full keyboard for the product detail: primary row (add / stepper / soon),
    reviews row, and back row. Shared by the first render and the +/- handlers
    so a step click just swaps reply_markup — no need to re-send the photo."""
    _cart_id, cart_qty = await get_cart_line_for_product(user_id, product_id)
    ret = f":{back_category}:{back_page}"
    if out_of_stock:
        primary_row = [InlineKeyboardButton(text=get_text("btn_coming_soon", lang), callback_data="noop")]
    elif cart_qty > 0:
        qty_str = str(int(cart_qty)) if float(cart_qty).is_integer() else f"{cart_qty:.1f}"
        primary_row = [
            InlineKeyboardButton(text="➖", callback_data=f"detail_dec:{product_id}{ret}"),
            InlineKeyboardButton(text=get_text("btn_in_cart_qty", lang, n=qty_str), callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data=f"detail_inc:{product_id}{ret}"),
        ]
    else:
        primary_row = [InlineKeyboardButton(text=get_text("btn_add_to_cart", lang), callback_data=f"detail_inc:{product_id}{ret}")]

    # cart_qty > 0 already means this product is in the cart — reuse it to
    # skip an extra query when this product alone justifies the shortcut.
    cart_count = 1 if cart_qty > 0 else await get_cart_count(user_id)
    cart_row = cart_shortcut_row(lang, cart_count)

    back_cb = f"cat:{back_category}:{back_page}" if back_category else "catalog"
    rows = [primary_row, [InlineKeyboardButton(text=get_text("btn_reviews", lang), callback_data=f"reviews:{product_id}")]]
    if cart_row:
        rows.append(cart_row)
    rows.append([InlineKeyboardButton(text=get_text("btn_back", lang), callback_data=back_cb)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _parse_detail_step(data: str) -> tuple[int, str, int]:
    """Parse 'detail_inc:PID:BACK_CAT:PAGE' (back_cat may be empty)."""
    parts = data.split(":")
    pid = int(parts[1])
    bc = parts[2] if len(parts) > 2 else ""
    try:
        page = int(parts[3]) if len(parts) > 3 else 0
    except ValueError:
        page = 0
    return pid, bc, page


async def _refresh_detail_keyboard(callback: CallbackQuery, product_id: int,
                                   back_category: str, back_page: int) -> None:
    """Update just the inline keyboard on the detail bubble — caption stays.
    Avoids the delete+resend of a photo on every +/- tap."""
    lang = await get_user_language(callback.from_user.id)
    product = await get_product(product_id)
    if not product:
        return
    out_of_stock = product["quantity"] <= 0
    kb = await _detail_keyboard(callback.from_user.id, product_id,
                                back_category, back_page, lang, out_of_stock)
    try:
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        # "message is not modified" on a no-op tap, or the bubble is gone — ignore.
        pass


@router.callback_query(F.data.startswith("detail_inc:"))
async def detail_increment(callback: CallbackQuery):
    """+1 from the product detail view — creates the cart line on first tap."""
    lang = await get_user_language(callback.from_user.id)
    pid, bc, page = _parse_detail_step(callback.data)
    product = await get_product(pid)
    if not product:
        await callback.answer("❌")
        return
    stock = product.get("quantity") or 0
    _cart_id, current = await get_cart_line_for_product(callback.from_user.id, pid)
    if stock and current + 1 > stock:
        await callback.answer(get_text("cart_stock_limit", lang), show_alert=True)
        return
    await add_to_cart(callback.from_user.id, pid, 1)  # merges into existing line
    await _refresh_detail_keyboard(callback, pid, bc, page)
    await callback.answer()


@router.callback_query(F.data.startswith("detail_dec:"))
async def detail_decrement(callback: CallbackQuery):
    """-1 from the product detail view — removes the cart line below 1."""
    pid, bc, page = _parse_detail_step(callback.data)
    cart_id, current = await get_cart_line_for_product(callback.from_user.id, pid)
    if not cart_id or current <= 0:
        await callback.answer()
        return
    new_qty = current - 1
    if new_qty < 1:
        await remove_from_cart(cart_id)
    else:
        await set_cart_quantity(cart_id, new_qty)
    await _refresh_detail_keyboard(callback, pid, bc, page)
    await callback.answer()


async def _show_product_list(callback: CallbackQuery, category: str, page: int):
    """Display product list as buttons for a category (or the 'discounts'
    pseudo-category, which lists active-discount products across categories)."""
    lang = await get_user_language(callback.from_user.id)
    is_discounts = category == "discounts"
    is_sets = category == "sets"
    
    if is_discounts:
        products, total = await get_discounted_products(page=page, per_page=PRODUCTS_PER_PAGE)
    elif is_sets:
        all_sets = await get_active_sets_for_catalog()
        total = len(all_sets)
        products = all_sets[page * PRODUCTS_PER_PAGE : (page + 1) * PRODUCTS_PER_PAGE]
    else:
        products, total = await get_products_by_category(category, page=page, per_page=PRODUCTS_PER_PAGE)
    total_pages = max(1, (total + PRODUCTS_PER_PAGE - 1) // PRODUCTS_PER_PAGE)
    cart_count = await get_cart_count(callback.from_user.id)

    # Where the back button and the empty-state keyboard should point.
    back_cb = "main_menu" if is_discounts else "catalog"
    empty_kb = back_to_menu_keyboard(lang, cart_count) if is_discounts else categories_keyboard(lang, cart_count)

    if not products:
        empty_text = get_text("no_discounts", lang) if is_discounts else get_text("no_products", lang)
        if callback.message.photo:
            try:
                await callback.message.delete()
            except Exception:
                pass
            await callback.message.answer(empty_text, reply_markup=empty_kb, parse_mode="HTML")
        else:
            await callback.message.edit_text(empty_text, reply_markup=empty_kb, parse_mode="HTML")
        await callback.answer()
        return

    if is_discounts:
        text = f"{get_text('discounts_title', lang)}\n\n{get_text('products_list_title', lang)}"
    else:
        cat_name = get_category_name(category, lang)
        text = f"{cat_name}\n\n{get_text('products_list_title', lang)}"

    buttons = []
    for p in products:
        if is_sets:
            price_str = f"{int(p['set_price']):,}".replace(",", " ")
            prod_name = p["name_ru"] if lang == "ru" and p.get("name_ru") else p["name"]
            buttons.append([InlineKeyboardButton(
                text=f"🎁 {prod_name} — {price_str} so'm",
                callback_data=f"set:{p['id']}:{page}"
            )])
        else:
            discount = active_discount(p.get("discount_percent"), p.get("discount_until"))
            price_value = effective_price(p["price"], discount, p.get("discount_until"))
            price_str = f"{int(price_value):,}".replace(",", " ")
            prod_name = localize_product_text(p.get("name"), p.get("name_ru"), lang)
            badge = ""
            if discount > 0:
                badge = f" 🔥-{discount}%"
                du = p.get("discount_until")
                if du:
                    badge += f" ⏳{du.strftime('%d.%m')}"
            buttons.append([InlineKeyboardButton(
                text=f"{prod_name} — {price_str} so'm{badge}",
                callback_data=f"product:{p['id']}:{category}:{page}"
            )])

    # Pagination
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(
            text="⬅️",
            callback_data=f"cat:{category}:{page - 1}"
        ))
    if total_pages > 1:
        nav_row.append(InlineKeyboardButton(
            text=f"{page + 1}/{total_pages}",
            callback_data="noop"
        ))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(
            text="➡️",
            callback_data=f"cat:{category}:{page + 1}"
        ))
    if nav_row:
        buttons.append(nav_row)

    cart_row = cart_shortcut_row(lang, cart_count)
    if cart_row:
        buttons.append(cart_row)

    buttons.append([InlineKeyboardButton(
        text=get_text("btn_back", lang),
        callback_data=back_cb
    )])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    if callback.message.photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")

    await callback.answer()

@router.callback_query(F.data.startswith("set:"))
async def show_set_detail(callback: CallbackQuery):
    parts = callback.data.split(":")
    set_id = int(parts[1])
    page = int(parts[2]) if len(parts) > 2 else 0
    lang = await get_user_language(callback.from_user.id)
    
    s = await get_set(set_id)
    if not s or not s.get("is_active"):
        await callback.answer(get_text("no_products", lang), show_alert=True)
        return
        
    name = s["name_ru"] if lang == "ru" and s.get("name_ru") else s["name"]
    price = f"{int(s['set_price']):,}".replace(",", " ")
    
    desc_lines = [f"<b>🎁 {name}</b>", f"Narxi: {price} so'm", "", "Tarkibi:"]
    for item in s["items"]:
        iname = item["name_ru"] if lang == "ru" and item.get("name_ru") else item["name"]
        desc_lines.append(f"— {iname} ({item['quantity']} {get_unit_name(item['unit'], lang)})")
        
    text = "\n".join(desc_lines)
    
    # Keyboard
    cart_count = await get_cart_count(callback.from_user.id)
    buttons = []
    
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
    from locales import get_text
    
    # Check if in cart
    from database import get_cart_line_for_set
    cart_id, qty = await get_cart_line_for_set(callback.from_user.id, set_id)
    
    if cart_id:
        # Stepper
        buttons.append([
            InlineKeyboardButton(text="➖", callback_data=f"set_dec:{set_id}:{page}"),
            InlineKeyboardButton(text=f"{int(qty)} ta", callback_data="noop"),
            InlineKeyboardButton(text="➕", callback_data=f"set_inc:{set_id}:{page}")
        ])
    else:
        buttons.append([InlineKeyboardButton(text=get_text("btn_add_to_cart", lang), callback_data=f"set_inc:{set_id}:{page}")])
        
    cart_row = cart_shortcut_row(lang, cart_count)
    if cart_row:
        buttons.append(cart_row)
        
    buttons.append([InlineKeyboardButton(text=get_text("btn_back", lang), callback_data=f"cat:sets:{page}")])
    
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    from config import BASE_URL
    photo_url = f"{BASE_URL}/api/photo/{s['image_url']}" if s.get("image_url") else None
    
    try:
        if photo_url:
            from aiogram.types import URLInputFile
            await callback.message.delete()
            await callback.message.answer_photo(
                URLInputFile(photo_url),
                caption=text,
                reply_markup=kb,
                parse_mode="HTML"
            )
        else:
            if callback.message.photo:
                await callback.message.delete()
                await callback.message.answer(text, reply_markup=kb, parse_mode="HTML")
            else:
                await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        pass
    await callback.answer()

@router.callback_query(F.data.startswith("set_inc:"))
async def set_increment(callback: CallbackQuery):
    parts = callback.data.split(":")
    set_id = int(parts[1])
    page = int(parts[2])
    
    await add_to_cart(callback.from_user.id, set_id=set_id, quantity=1)
    
    parts[0] = "set"
    callback.data = ":".join(parts)
    await show_set_detail(callback)
    
@router.callback_query(F.data.startswith("set_dec:"))
async def set_decrement(callback: CallbackQuery):
    parts = callback.data.split(":")
    set_id = int(parts[1])
    page = int(parts[2])
    
    from database import get_cart_line_for_set
    cart_id, qty = await get_cart_line_for_set(callback.from_user.id, set_id)
    if cart_id:
        if qty > 1:
            await set_cart_quantity(cart_id, qty - 1)
        else:
            await remove_from_cart(cart_id)
            
    parts[0] = "set"
    callback.data = ":".join(parts)
    await show_set_detail(callback)
