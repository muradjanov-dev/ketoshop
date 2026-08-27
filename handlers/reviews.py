"""
Product reviews and ratings handler + post-delivery feedback (reviews & complaints)
"""
import json
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import ADMIN_IDS
from database import (
    get_user_language, get_product, get_product_reviews, get_product_rating,
    has_user_reviewed, has_user_purchased, add_review, get_order, get_user,
    get_cart_count,
)
from locales import get_text
from keyboards import (
    rating_keyboard, review_back_keyboard, back_to_menu_keyboard,
    review_pick_product_keyboard, main_menu_keyboard,
)

router = Router()


class ReviewStates(StatesGroup):
    waiting_rating = State()
    waiting_comment = State()


class ComplaintStates(StatesGroup):
    waiting_message = State()


@router.callback_query(F.data.startswith("reviews:"))
async def show_reviews(callback: CallbackQuery):
    """Show reviews for a product"""
    product_id = int(callback.data.split(":")[1])
    lang = await get_user_language(callback.from_user.id)
    product = await get_product(product_id)

    if not product:
        await callback.answer("❌")
        return

    avg_rating, count = await get_product_rating(product_id)
    reviews = await get_product_reviews(product_id)

    if not reviews:
        text = get_text("no_reviews", lang)
    else:
        text = get_text("reviews_title", lang,
            name=product["name"],
            rating=avg_rating,
            count=count,
        )
        for r in reviews[:10]:
            stars = "⭐" * r["rating"]
            user_name = r.get("full_name") or r.get("username") or "Anonymous"
            comment = r.get("comment") or "—"
            date = str(r["created_at"])[:10] if r.get("created_at") else ""
            text += f"{stars} — <b>{user_name}</b>\n{comment}\n<i>{date}</i>\n\n"

    cart_count = await get_cart_count(callback.from_user.id)
    await callback.message.answer(
        text,
        reply_markup=review_back_keyboard(lang, product_id, cart_count),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("write_review:"))
async def start_review(callback: CallbackQuery, state: FSMContext):
    """Start writing a review — check eligibility first"""
    product_id = int(callback.data.split(":")[1])
    lang = await get_user_language(callback.from_user.id)

    # Check if already reviewed
    if await has_user_reviewed(callback.from_user.id, product_id):
        await callback.answer(get_text("review_already_exists", lang), show_alert=True)
        return

    # Check if user has purchased this product (optional — can be removed for open reviews)
    # Uncomment the following to require purchase before review:
    # if not await has_user_purchased(callback.from_user.id, product_id):
    #     await callback.answer(get_text("review_not_purchased", lang), show_alert=True)
    #     return

    await state.set_state(ReviewStates.waiting_rating)
    await state.update_data(product_id=product_id, lang=lang)

    await callback.message.edit_text(
        get_text("review_select_rating", lang),
        reply_markup=rating_keyboard(product_id),
        parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("rate:"), ReviewStates.waiting_rating)
async def process_rating(callback: CallbackQuery, state: FSMContext):
    """Process star rating"""
    _, product_id, rating = callback.data.split(":")
    data = await state.get_data()
    lang = data.get("lang", "uz")

    await state.update_data(rating=int(rating), product_id=int(product_id))
    await state.set_state(ReviewStates.waiting_comment)

    await callback.message.edit_text(
        get_text("review_enter_comment", lang),
        parse_mode="HTML"
    )
    await callback.answer()


@router.message(ReviewStates.waiting_comment)
async def process_comment(message: Message, state: FSMContext):
    """Process review comment and save"""
    data = await state.get_data()
    lang = data.get("lang", "uz")
    comment = message.text.strip()

    if comment.lower() in ("/skip", "skip"):
        comment = None

    await add_review(
        user_id=message.from_user.id,
        product_id=data["product_id"],
        rating=data["rating"],
        comment=comment,
    )

    await state.clear()

    await message.answer(
        get_text("review_saved", lang),
        reply_markup=back_to_menu_keyboard(lang),
        parse_mode="HTML"
    )


# ===== POST-DELIVERY FEEDBACK =====

@router.callback_query(F.data.startswith("review_order:"))
async def review_order(callback: CallbackQuery):
    """Let the buyer pick which product from the order they want to review."""
    order_id = int(callback.data.split(":")[1])
    lang = await get_user_language(callback.from_user.id)

    order = await get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer("❌")
        return

    items = order["items"]
    items = json.loads(items) if isinstance(items, str) else items
    items = items or []

    # Deduplicate by product_id (an order can list the same product twice)
    seen = set()
    unique = []
    for it in items:
        pid = it.get("product_id")
        if pid is None or pid in seen:
            continue
        seen.add(pid)
        unique.append(it)

    if not unique:
        await callback.answer("❌")
        return

    await callback.message.edit_text(
        get_text("review_pick_product", lang),
        reply_markup=review_pick_product_keyboard(lang, unique),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("complaint:"))
async def start_complaint(callback: CallbackQuery, state: FSMContext):
    """User wants to report an issue with a delivered order."""
    order_id = int(callback.data.split(":")[1])
    lang = await get_user_language(callback.from_user.id)

    order = await get_order(order_id)
    if not order or order["user_id"] != callback.from_user.id:
        await callback.answer("❌")
        return

    await state.set_state(ComplaintStates.waiting_message)
    await state.update_data(order_id=order_id, lang=lang)

    await callback.message.edit_text(
        get_text("complaint_prompt", lang, order_id=order_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ComplaintStates.waiting_message)
async def process_complaint(message: Message, state: FSMContext, bot: Bot):
    """Forward the complaint to all admins, thank the user."""
    data = await state.get_data()
    lang = data.get("lang", "uz")
    order_id = data["order_id"]

    complaint_text = (message.text or "").strip()
    if not complaint_text:
        # Ignore empty/non-text; keep state
        return

    await state.clear()

    # Thank the buyer
    await message.answer(
        get_text("complaint_received", lang),
        reply_markup=main_menu_keyboard(lang),
        parse_mode="HTML",
    )

    # Forward to admins
    order = await get_order(order_id)
    phone = (order or {}).get("phone", "—")
    customer_name = message.from_user.full_name or "—"

    from handlers.cart import buyer_contact_link
    contact = buyer_contact_link(
        message.from_user.id,
        message.from_user.username,
        customer_name,
    )

    for admin_id in ADMIN_IDS:
        admin_lang = await get_user_language(admin_id)
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=get_text("complaint_from_buyer", admin_lang,
                    order_id=order_id,
                    name=customer_name,
                    contact=contact,
                    phone=phone,
                    text=complaint_text,
                ),
                parse_mode="HTML",
            )
        except Exception:
            pass
