"""
"Bepul xarid qilish" — mijozdan mijozga referal (2026-10-02).

Uch qism:
  - Start bonusi: har bir yangi foydalanuvchi birinchi /start da 100 Keto
    oladi (egasi, 2026-10-13: "barcha yangi qo'shilganlarga sovg'a qilib 100
    ta ketochalarni tantanali topshirgin va uni qanday yig'ish va ishlatishni
    tushuntirgin"; avval 10 edi). Referal havola orqali kelganlar uni
    award_referral'dan (referral_contest.py) oladi, qolganlarga
    grant_welcome_bonus beradi. Ikkalasi ham faqat "kutilmoqda" deb
    belgilaydi — tantanali xabar (celebrate) til tanlangan zahoti, o'sha
    tilda keladi: ro'yxatdan o'tish paytida til hali noma'lum.
  - Referal keshbegi: taklif qilingan odamning birinchi TO'LANGAN (ya'ni
    yetkazilgan) xaridining 3% i taklif qiluvchiga Keto bo'lib tushadi.
    Asos — mahsulotlar summasi, yetkazib berish va Keto bilan to'langan
    qismsiz. Birinchi buyurtma bekor bo'lsa, keyingi yetkazilgani hisoblanadi.
    Faqat dastur ishga tushgandan keyingi takliflar (referrals.cashback_eligible).
  - Asosiy menyudagi "🎁 Bepul xarid qilish" ekrani: shaxsiy havola, ulashish
    tugmasi, Keto balansi va taklif statistikasi.

Havola formati referral_contest.py dagi bilan bir xil (?start=ref<id>), shuning
uchun eski musobaqa havolalari ham shu tizimda ishlayveradi.
"""
import json
import logging
from urllib.parse import quote

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

import database
from config import ADMIN_IDS
from locales import get_text
from referral_contest import referral_link

logger = logging.getLogger(__name__)
router = Router()

WELCOME_KETO = 100
CASHBACK_PERCENT = 3

_pending_table_ready = False


def _fmt(n) -> str:
    return f"{int(n or 0):,}".replace(",", " ")


def _is_eligible_order(order: dict) -> bool:
    """bloggers._is_eligible_order bilan bir xil: admin/ichki akkauntlar va
    admin qo'lda kiritgan manual/B2B buyurtmalar keshbek bermaydi."""
    user_id = order.get("user_id")
    if user_id in ADMIN_IDS or user_id in database.LEADERBOARD_EXCLUDED_USER_IDS:
        return False
    return (order.get("source") or "bot") not in ("manual", "b2b")


def cashback_base(order: dict) -> float:
    """Mahsulotlar summasi (yetkazib berish narxisiz, gamification bilan bir
    xil) minus Keto bilan to'langan qism."""
    raw = order.get("items")
    try:
        items = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except Exception:
        items = []
    subtotal = sum(float(it.get("price") or 0) * float(it.get("quantity") or 0) for it in items)
    return max(0.0, subtotal - float(order.get("keto_redeemed") or 0))


async def grant_welcome_bonus(bot: Bot, user_id: int) -> None:
    """Yangi foydalanuvchiga 100 Keto. Referal orqali kelib, bonusni allaqachon
    olgan bo'lsa — hech narsa qilmaydi. Xabar keyin — celebrate(). Hech
    qachon xato tashlamaydi."""
    try:
        if await database.credit_welcome_keto(user_id, WELCOME_KETO):
            await mark_welcome_pending(user_id, WELCOME_KETO)
    except Exception:
        logger.exception("grant_welcome_bonus failed for user %s", user_id)


# ───────────────────── tantanali topshirish ─────────────────────

async def _ensure_pending_table(conn) -> None:
    global _pending_table_ready
    if _pending_table_ready:
        return
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS welcome_keto_pending (
            user_id BIGINT PRIMARY KEY,
            amount INTEGER NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
        )
    """)
    _pending_table_ready = True


async def mark_welcome_pending(user_id: int, amount: int) -> None:
    """Start bonusi berildi — tabrik xabari til tanlangach yuboriladi.
    Faqat ro'yxatdan o'tish paytida chaqiriladi, shuning uchun eski
    foydalanuvchi tilini almashtirsa, unga hech narsa kelmaydi."""
    async with database.pool.acquire() as conn:
        await _ensure_pending_table(conn)
        await conn.execute(
            "INSERT INTO welcome_keto_pending (user_id, amount) VALUES ($1, $2) "
            "ON CONFLICT (user_id) DO NOTHING", user_id, amount)


async def _pop_welcome_pending(user_id: int) -> int | None:
    """Kutilayotgan tabrikni oladi va o'chiradi — bitta DELETE, shuning uchun
    ikki marta bosilgan til tugmasi ham ikkita xabar yubormaydi."""
    async with database.pool.acquire() as conn:
        await _ensure_pending_table(conn)
        return await conn.fetchval(
            "DELETE FROM welcome_keto_pending WHERE user_id = $1 RETURNING amount", user_id)


_CEREMONY = {
    "uz": (
        "🎉 <b>Tabriklaymiz, {name}!</b>\n\n"
        "Ketoshop oilasiga xush kelibsiz! 🤍\n"
        "Shu quvonchli kun munosabati bilan Sizga birinchi sovg'amizni topshiramiz:\n\n"
        "🎁 <b>{amount} ta Keto tangacha</b> hisobingizga tushdi!\n"
        "👛 Hozir hisobingizda: <b>{balance} ta tangacha</b>"
    ),
    "ru": (
        "🎉 <b>Поздравляем, {name}!</b>\n\n"
        "Добро пожаловать в семью Ketoshop! 🤍\n"
        "В честь этого радостного дня вручаем вам наш первый подарок:\n\n"
        "🎁 На ваш счёт поступило <b>{amount} Keto-монеток</b>!\n"
        "👛 Сейчас на вашем счёте: <b>{balance} монеток</b>"
    ),
}
_WHAT = {
    "uz": ("🪙 <b>Keto tangacha nima?</b>\n"
           "Bu — Ketoshopning sovg'a pullari: <b>1 ta tangacha = 1 so'm</b>. Ular yo'qolmaydi — "
           "xuddi pul yig'adigan idishga ozroqdan solib borgandek, yig'ilib boraveradi."),
    "ru": ("🪙 <b>Что такое Keto-монетки?</b>\n"
           "Это подарочные деньги Ketoshop: <b>1 монетка = 1 сум</b>. Они не сгорают — "
           "копятся, как деньги, которые вы понемногу откладываете в баночку."),
}
_EARN = {
    "uz": ("📥 <b>Qanday yig'iladi?</b>\n"
           "🛒 Har bir xaridingizdan tangacha qaytadi — buyurtma qo'lingizga yetib borgan kuni "
           "hisobingizga tushadi.\n"
           "⭐ Har 100 000 so'mlik xaridga <b>{bronze} ta</b>. Xarid qilgan sari darajangiz oshadi va "
           "ko'proq qaytadi: 🥈 Kumush — {silver}, 🥇 Oltin — {gold}, 💎 Olmos — {diamond} ta.\n"
           "👥 Do'stlaringizni taklif qiling: ular birinchi xaridini qilganda, xarid summasining "
           "<b>{ref}%</b> i Sizga tangacha bo'lib tushadi — «🎁 Bepul xarid qilish» tugmasida."),
    "ru": ("📥 <b>Как копить?</b>\n"
           "🛒 С каждой покупки возвращаются монетки — они поступают на счёт в день, когда заказ "
           "у вас в руках.\n"
           "⭐ За каждые 100 000 сум покупки — <b>{bronze} монеток</b>. Чем больше покупок, тем выше "
           "уровень и тем больше возврат: 🥈 Серебро — {silver}, 🥇 Золото — {gold}, 💎 Алмаз — {diamond}.\n"
           "👥 Приглашайте друзей: когда они сделают первую покупку, <b>{ref}%</b> от суммы придут "
           "вам монетками — кнопка «🎁 Бесплатные покупки»."),
}
_SPEND = {
    "uz": ("🛒 <b>Qanday ishlatiladi?</b>\n"
           "Buyurtma berayotganda «Ketochalarni ishlatish» ni tanlang — botda ham, saytda ham. "
           "Tangachalar pul o'rniga o'tadi va Siz shuncha kam to'laysiz."),
    "ru": ("🛒 <b>Как потратить?</b>\n"
           "При оформлении заказа выберите «Использовать Ketочки» — и в боте, и на сайте. "
           "Монетки пойдут вместо денег, и вы заплатите меньше."),
}
_CLOSING = {
    "uz": "Balansingiz va darajangiz doim «👤 Kabinetim» da.\n\n<i>Hurmat bilan, Ketoshop jamoasi</i>",
    "ru": "Баланс и уровень всегда в «👤 Кабинет».\n\n<i>С уважением, команда Ketoshop</i>",
}
_CEREMONY_BUTTONS = {
    "wallet": {"uz": "👛 Tangachalarim", "ru": "👛 Мои монетки"},
    "shop": {"uz": "🛒 Xarid qilish", "ru": "🛒 За покупками"},
}
_NAME_MARK = "§"   # o'girishdan omon qoladi — ism keyin o'z holicha qo'yiladi


def _loc(entry: dict, lang: str) -> str:
    if lang == "ru":
        return entry["ru"]
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        return lat_to_cyr(entry["uz"])
    return entry["uz"]


def ceremony_text(lang: str, name: str, amount: int, balance: int,
                  earning: bool = True, spending: bool = True) -> str:
    """Tantanali tabrik + tangachalar nima, qanday yig'iladi, qanday
    ishlatiladi. Stavkalar gamification.EARN_RATES dan — matn hech qachon
    haqiqiy qoidadan farq qilmaydi. `earning`/`spending` — Keto o'chirilgan
    bo'lsa, va'da qilinmaydi."""
    import html as _html
    import gamification
    values = {"{name}": _NAME_MARK, "{amount}": _fmt(amount), "{balance}": _fmt(balance),
              "{ref}": str(CASHBACK_PERCENT)}
    for code, rate in gamification.EARN_RATES.items():
        values["{" + code + "}"] = _fmt(100_000 * rate)
    blocks = [_CEREMONY, _WHAT] + ([_EARN] if earning else []) + ([_SPEND] if spending else []) + [_CLOSING]
    text = "\n\n".join(b["ru" if lang == "ru" else "uz"] for b in blocks)
    # Values first, then Cyrillic — lat_to_cyr would turn "{amount}" into
    # "{амоунт}"; the name goes in last so it is never transliterated.
    for key, value in values.items():
        text = text.replace(key, value)
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        text = lat_to_cyr(text)
    shown = _html.escape(name, quote=False) if name else _loc({"uz": "do'stim", "ru": "друг"}, lang)
    return text.replace(_NAME_MARK, shown)


def ceremony_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=_loc(_CEREMONY_BUTTONS["wallet"], lang), callback_data="kabinetim")],
        [InlineKeyboardButton(text=_loc(_CEREMONY_BUTTONS["shop"], lang), callback_data="catalog")],
    ])


async def celebrate(bot: Bot, user_id: int, lang: str, name: str | None) -> bool:
    """Til tanlangan zahoti (handlers/start.set_language): start bonusi
    kutilayotgan bo'lsa — tantanali tabrik, o'sha tilda, bir marta.
    Hech qachon xato tashlamaydi."""
    try:
        amount = await _pop_welcome_pending(user_id)
        if not amount:
            return False
        import gamification
        user = await database.get_user(user_id)
        balance = int((user or {}).get("keto_balance") or amount)
        text = ceremony_text(lang, name or "", amount, balance,
                             earning=await gamification.is_enabled(),
                             spending=await gamification.is_redemption_enabled(user_id))
        await bot.send_message(user_id, text, parse_mode=ParseMode.HTML,
                               reply_markup=ceremony_keyboard(lang))
        return True
    except Exception:
        logger.exception("welcome Keto ceremony failed for user %s", user_id)
        return False


async def award_order_cashback(order: dict, bot: Bot) -> None:
    """Buyurtma 'delivered' bo'lgandan keyin chaqiriladi (bloger keshbegi
    bilan bir joyda). Idempotent: har bir taklif qilingan odam uchun faqat
    bir marta to'lanadi. Hech qachon xato tashlamaydi."""
    try:
        if not _is_eligible_order(order):
            return
        amount = int(round(cashback_base(order) * CASHBACK_PERCENT / 100))
        if amount <= 0:
            return  # to'liq Keto bilan to'langan — keyingi xarid hisoblanadi
        buyer_id = order["user_id"]
        referrer_id = await database.claim_referral_cashback(buyer_id, order["id"], amount)
        if not referrer_id:
            return
        logger.info("Referral cashback %s Keto -> %s (buyer %s, order %s)",
                    amount, referrer_id, buyer_id, order["id"])

        referrer = await database.get_user(referrer_id) or {}
        buyer = await database.get_user(buyer_id) or {}
        lang = referrer.get("language") or "uz"
        who = (buyer.get("full_name") or "").split()
        who = who[0] if who else (f"@{buyer['username']}" if buyer.get("username") else "—")
        try:
            await bot.send_message(
                referrer_id,
                get_text("referral_cashback_earned", lang, name=who, amount=_fmt(amount),
                         percent=CASHBACK_PERCENT, balance=_fmt(referrer.get("keto_balance"))),
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text=get_text("btn_free_buy", lang), callback_data="free_buy"),
                ]]),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            logger.warning("Referral cashback notice failed for %s", referrer_id, exc_info=True)
    except Exception:
        logger.exception("award_order_cashback failed for order %s", order.get("id"))


def _share_url(user_id: int, lang: str) -> str:
    link = referral_link(user_id)
    text = get_text("free_buy_share_text", lang)
    return f"https://t.me/share/url?url={quote(link, safe='')}&text={quote(text, safe='')}"


@router.callback_query(F.data == "free_buy")
async def show_free_buy(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = await database.get_user_language(user_id)
    user = await database.get_user(user_id) or {}
    summary = await database.get_user_referral_summary(user_id)
    text = get_text(
        "free_buy_screen", lang,
        percent=CASHBACK_PERCENT, link=referral_link(user_id),
        balance=_fmt(user.get("keto_balance")),
        invited=summary["invited"], bought=summary["bought"], earned=_fmt(summary["cashback"]),
    )
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_free_buy_share", lang), url=_share_url(user_id, lang))],
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data="main_menu")],
    ])
    await callback.answer()
    if callback.message.photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML",
                                      disable_web_page_preview=True)
        return
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML",
                                         disable_web_page_preview=True)
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML",
                                      disable_web_page_preview=True)
