"""
Product search handler
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import get_user_language, search_products, effective_price, active_discount, get_cart_count
from locales import get_text, get_unit_name, get_display_unit, localize_product_text
from keyboards import back_to_menu_keyboard, cart_shortcut_row

router = Router()

SEARCH_PER_PAGE = 5


class SearchStates(StatesGroup):
    waiting_query = State()


@router.callback_query(F.data == "search")
async def start_search(callback: CallbackQuery, state: FSMContext):
    """Prompt user to enter search query"""
    lang = await get_user_language(callback.from_user.id)
    await state.set_state(SearchStates.waiting_query)
    await state.update_data(lang=lang)

    await callback.message.edit_text(
        get_text("search_prompt", lang),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(SearchStates.waiting_query)
async def process_search(message: Message, state: FSMContext):
    """Execute search and show results"""
    data = await state.get_data()
    lang = data.get("lang", "uz")
    query = message.text.strip()

    # Minimum length validation
    if len(query) < 2:
        await message.answer(get_text("search_too_short", lang))
        return

    await state.clear()
    await _show_search_results(message, query, lang, page=0, user_id=message.from_user.id)


@router.callback_query(F.data.startswith("search_page:"))
async def search_navigate(callback: CallbackQuery):
    """Navigate search result pages"""
    parts = callback.data.split(":", 2)
    page = int(parts[1])
    query = parts[2]
    lang = await get_user_language(callback.from_user.id)

    await callback.message.delete()
    await _show_search_results(callback.message, query, lang, page=page, is_callback=True, user_id=callback.from_user.id)
    await callback.answer()


async def _show_search_results(message: Message, query: str, lang: str, page: int = 0,
                                is_callback: bool = False, user_id: int | None = None):
    """Show search results with pagination"""
    products, total = await search_products(query, page=page, per_page=SEARCH_PER_PAGE)
    cart_count = await get_cart_count(user_id) if user_id is not None else 0

    if not products:
        await message.answer(
            get_text("search_empty", lang, query=query),
            reply_markup=back_to_menu_keyboard(lang, cart_count),
            parse_mode="HTML"
        )
        return

    total_pages = (total + SEARCH_PER_PAGE - 1) // SEARCH_PER_PAGE
    start_num = page * SEARCH_PER_PAGE

    text = get_text("search_results", lang, query=query, count=total)

    buttons = []
    for i, p in enumerate(products, start_num + 1):
        discount = active_discount(p.get("discount_percent"), p.get("discount_until"))
        unit_price = effective_price(p["price"], discount, p.get("discount_until"))
        price_str = f"{int(unit_price):,}".replace(",", " ")
        if discount > 0:
            price_str += f" 🔥-{discount}%"
        prod_name = localize_product_text(p.get("name"), p.get("name_ru"), lang)
        text += get_text("search_item", lang,
            i=i,
            name=prod_name,
            price=price_str,
            unit=get_display_unit(p["unit"], lang),
        )
        # Open the detail card first (price, description, reviews, photo)
        # instead of jumping straight to quantity selection — that's the same
        # contract the catalog uses.
        buttons.append([InlineKeyboardButton(
            text=prod_name,
            callback_data=f"product:{p['id']}"
        )])

    # Pagination row
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(
            text="◀️",
            callback_data=f"search_page:{page - 1}:{query}"
        ))
    nav_row.append(InlineKeyboardButton(
        text=f"{page + 1}/{total_pages}",
        callback_data="noop"
    ))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(
            text="▶️",
            callback_data=f"search_page:{page + 1}:{query}"
        ))
    if total_pages > 1:
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton(
        text=get_text("btn_search", lang),
        callback_data="search"
    )])
    cart_row = cart_shortcut_row(lang, cart_count)
    if cart_row:
        buttons.append(cart_row)
    buttons.append([InlineKeyboardButton(
        text=get_text("btn_back_to_menu", lang),
        callback_data="main_menu"
    )])

    await message.answer(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
