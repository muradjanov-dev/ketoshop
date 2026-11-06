"""
Chek tasdig'i — rasm o'z-o'zidan to'lov cheki emas.

Egasi, 2026-11-06: "botdan kelgan har qanday rasmni tolov rasmi deb qabul
qilmasin, bu tolov cheki yoki yoqligini tizim so'rasin".

Chek kutilayotgan ikki joyda — tugmali checkout ning waiting_cheque holati
(handlers/cart.py) va AI suhbatidagi karta buyurtmasi (ai_sales.on_cheque) —
kelgan rasm yoki fayl darhol ishlatilmaydi. Bot o'sha rasmga javob qilib
"Bu to'lov chekimi?" deb so'raydi:

  * «✅ Ha, to'lov cheki» — eski oqim: buyurtma yaratiladi / chek biriktiriladi;
  * «❌ Yo'q, boshqa rasm» — rasm operatorga oddiy xabar bo'lib boradi
    (support_relay.relay_media), chek kutilishi davom etadi.

Rasm FSM ma'lumotida turadi (kalit — rasm xabarining id si), shuning uchun bot
qayta ishga tushsa ham tugma ishlaydi. Bitta albomdagi rasmlar uchun bitta savol.
"""
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from locales import get_text

KEEP = 5                       # javob kutayotgan rasmlar — oxirgi shunchasi saqlanadi
CAPTION_CHARS = 500
_busy: set[int] = set()        # "Ha" ishlanayotgan mijozlar — ikki marta bosish = bitta buyurtma


def file_of(message: Message) -> tuple[str, str] | None:
    """("photo" | "document", file_id) — rasm yoki fayl bo'lsa."""
    if message.photo:
        return "photo", message.photo[-1].file_id
    if message.document:
        return "document", message.document.file_id
    return None


async def remember(state: FSMContext, message: Message) -> int | None:
    """Rasmni javob kutayotganlar qatoriga qo'yadi. Kalit (rasm xabarining id si)
    qaytadi; shu albomdan avvalroq so'ralgan bo'lsa — None (yana so'ralmaydi)."""
    found = file_of(message)
    if found is None:
        return None
    data = await state.get_data()
    pending = dict(data.get("cheque_candidates") or {})
    album = message.media_group_id
    if album and any(c.get("album") == album for c in pending.values()):
        return None
    pending[str(message.message_id)] = {
        "kind": found[0], "file_id": found[1], "album": album,
        "caption": (message.caption or "")[:CAPTION_CHARS],
    }
    newest = sorted(pending, key=int)[-KEEP:]
    await state.update_data(cheque_candidates={k: pending[k] for k in newest})
    return message.message_id


async def take(state: FSMContext, key) -> dict | None:
    """Tugma bosilganda rasmni oladi va ro'yxatdan chiqaradi. Yo'q bo'lsa —
    savol eskirgan (buyurtma bekor qilingan, chek allaqachon olingan)."""
    data = await state.get_data()
    pending = dict(data.get("cheque_candidates") or {})
    found = pending.pop(str(key), None)
    if found is not None:
        await state.update_data(cheque_candidates=pending)
    return found


def begin(user_id: int) -> bool:
    """Bir mijozning "Ha" si bir vaqtda faqat bittadan ishlanadi."""
    if user_id in _busy:
        return False
    _busy.add(user_id)
    return True


def end(user_id: int) -> None:
    _busy.discard(user_id)


def parse(data: str) -> tuple[str, str, str] | None:
    """«chek:<yo'l>:<ha|yoq>:<kalit>» → (yo'l, javob, kalit)."""
    parts = (data or "").split(":")
    if len(parts) != 4 or parts[0] != "chek" or parts[2] not in ("ha", "yoq"):
        return None
    return parts[1], parts[2], parts[3]


def keyboard(path: str, key: int, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_cheque_yes", lang), callback_data=f"chek:{path}:ha:{key}")],
        [InlineKeyboardButton(text=get_text("btn_cheque_no", lang), callback_data=f"chek:{path}:yoq:{key}")],
    ])


async def ask(message: Message, state: FSMContext, path: str, lang: str) -> bool:
    """Rasmga javob qilib "Bu to'lov chekimi?" — tugmalari bilan. False — shu
    albom uchun allaqachon so'ralgan."""
    key = await remember(state, message)
    if key is None:
        return False
    await message.reply(get_text("cheque_confirm_question", lang),
                        reply_markup=keyboard(path, key, lang), parse_mode="HTML")
    return True


class Buyer:
    """Finalizerlar Message dan faqat mijozni (from_user) va unga javob yozishni
    (answer) ishlatadi. Tugma bosilganda callback.message — botning o'z xabari,
    shuning uchun o'rniga shu: javob mijozning chatiga ketadi."""

    def __init__(self, bot, user):
        self.bot, self.from_user = bot, user

    async def answer(self, text: str, **kwargs):
        return await self.bot.send_message(self.from_user.id, text, **kwargs)


async def close_question(callback, text: str | None = None) -> None:
    """Savol xabaridan tugmalarni oladi, `text` bo'lsa natijani yozadi (u matnli
    xabar — rasm emas)."""
    if text:
        try:
            await callback.message.edit_text(text, parse_mode="HTML")
            return
        except Exception:
            pass
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
