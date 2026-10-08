"""
Bot orqali buyurtmaga 10% chegirma — egasi so'rovi 2026-10-08:
"bot orqali buyurtma qilgan har bir mijoz (admin orqali emas, o'zi qilsa)
10% lik chegirma, barchaga, har qanday summaga". Hozircha muddatsiz.

Kimga: botdagi tugmali checkout, sayt (Mini App) va AI sotuvchi orqali O'ZI
buyurtma bergan har bir mijozga. Adminlar va ichki akkauntlar — yo'q: ular
mijoz nomidan buyurtma kiritadi. /admin dagi qo'lda va B2B buyurtmalar
create_order'dan o'tmaydi, ularga umuman tegmaydi.

Qanday: har bir pullik qatorning narxi katalog narxidan 10% kam bo'ladi.
Narx qatorning o'zida saqlanadi (price + original_price + discount_percent),
shuning uchun orders.total, foyda (line_cost), admin xabaridagi
"<s>eski</s> yangi 🔥-10%" va hisobotlar qo'shimcha kodsiz to'g'ri chiqadi.
Mahsulotning o'z 🔥 chegirmasi bilan qo'shilmaydi — qaysi biri arzon bo'lsa,
o'sha. Bepul yetkazish (800 000) chegirmagacha bo'lgan summadan hisoblanadi
(egasi tanlovi: chegirma mijozdan bepul yetkazishni olib qo'ymasin). Keto
tangachalar bilan to'lash avvalgidek ishlaydi.

Yoqilishi: chegirma e'loni yuborilayotganda o'zi yoqiladi
(bot_discount_campaign.py). Shu payt mahsulotlardagi 🔥 chegirmalar
to'xtatiladi (egasi: "agar bo'lsa ularni to'xtat") va adminlarga qaysilari
to'xtatilgani yoziladi.

Eslatma: reminder() — "Bot orqali buyurtma qilib, istalgan summaga 10%
chegirmaga ega bo'ling" (egasi so'zi bilan). Chegirma yoqilgan paytda
mahsulot kartochkasi, savat, Mini App, kanal postlari va rejalashtirilgan
xabarlar oxirida chiqadi; o'chirilsa — hamma joydan o'zi yo'qoladi.

Boshqaruv (adminlar): /chegirma — holat · /chegirma_on · /chegirma_off
"""
import logging
import time

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message

import database
from config import ADMIN_IDS, BOT_USERNAME

logger = logging.getLogger(__name__)
router = Router(name="bot_discount")

PERCENT = 10
CACHE_TTL = 30          # holat shuncha soniya eslab qolinadi — har narxda bazaga bormaslik uchun

_cache = {"at": 0.0, "active": False}
_table_ready = False


def _pick(entry: dict, lang: str) -> str:
    if lang == "ru":
        return entry["ru"]
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        return lat_to_cyr(entry["uz"])
    return entry["uz"]


def _som(amount) -> str:
    return f"{int(round(amount)):,}".replace(",", " ")


# ───────────────────────────── holat ─────────────────────────────

async def _ensure_table(conn) -> None:
    global _table_ready
    if _table_ready:
        return
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_discount_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            active BOOLEAN NOT NULL DEFAULT FALSE,
            percent INTEGER NOT NULL DEFAULT 10,
            changed_at TIMESTAMP,
            changed_by BIGINT
        )
    """)
    _table_ready = True


async def is_active() -> bool:
    now = time.monotonic()
    if now - _cache["at"] < CACHE_TTL:
        return _cache["active"]
    try:
        async with database.pool.acquire() as conn:
            await _ensure_table(conn)
            active = bool(await conn.fetchval("SELECT active FROM bot_discount_state WHERE id = 1"))
    except Exception:
        # Baza javob bermasa — oxirgi ma'lum holat. Checkout to'xtamasin.
        logger.warning("bot_discount state read failed", exc_info=True)
        return _cache["active"]
    _cache.update(at=now, active=active)
    return active


async def set_active(on: bool, by: int | None = None) -> list[dict]:
    """Yoqadi/o'chiradi. Yoqilganda mahsulotlardagi 🔥 chegirmalar to'xtatiladi
    — qaytariladi: to'xtatilgan mahsulotlar (id, name, percent)."""
    stopped: list[dict] = []
    async with database.pool.acquire() as conn:
        await _ensure_table(conn)
        async with conn.transaction():
            await conn.execute(
                """INSERT INTO bot_discount_state (id, active, percent, changed_at, changed_by)
                   VALUES (1, $1, $2, (NOW() AT TIME ZONE 'UTC'), $3)
                   ON CONFLICT (id) DO UPDATE
                   SET active = EXCLUDED.active, percent = EXCLUDED.percent,
                       changed_at = EXCLUDED.changed_at, changed_by = EXCLUDED.changed_by""",
                on, PERCENT, by)
            if on:
                rows = await conn.fetch(
                    """UPDATE products SET discount_percent = 0, discount_until = NULL
                       WHERE COALESCE(discount_percent, 0) > 0
                       RETURNING id, name""")
                stopped = [dict(r) for r in rows]
    _cache.update(at=time.monotonic(), active=on)
    logger.info("Bot discount %s by %s; product discounts stopped: %d",
                "ON" if on else "OFF", by, len(stopped))
    return stopped


async def get_state() -> dict:
    async with database.pool.acquire() as conn:
        await _ensure_table(conn)
        row = await conn.fetchrow("SELECT * FROM bot_discount_state WHERE id = 1")
    return dict(row) if row else {"active": False, "percent": PERCENT}


# ───────────────────────────── narx ─────────────────────────────

def eligible(user_id: int) -> bool:
    """Admin va ichki akkauntlar o'zi uchun emas, mijoz nomidan buyurtma
    kiritadi — chegirma faqat mijoz o'zi bergan buyurtmaga."""
    return user_id not in ADMIN_IDS and user_id not in database.LEADERBOARD_EXCLUDED_USER_IDS


async def percent_for(user_id: int) -> int:
    if not eligible(user_id):
        return 0
    return PERCENT if await is_active() else 0


def line_price(base: float, current: float, percent: int) -> float:
    """Katalog narxidan `percent` kam, lekin mahsulotning o'z chegirmali
    narxidan qimmat emas — ikkalasi qo'shilmaydi, arzoni qoladi."""
    if not percent or not base:
        return current
    return min(float(current), float(round(float(base) * (100 - percent) / 100)))


def apply(items: list[dict], percent: int) -> float:
    """Checkout qatorlariga (handlers/cart.py / webapp_server.py items_data)
    chegirmani yozadi. Qaytaradi: tejalgan summa. Sovg'a/bonus qatorlari
    (narxi 0) o'zgarmaydi."""
    if not percent:
        return 0.0
    saved = 0.0
    for item in items:
        if item.get("is_bonus") or item.get("is_gift"):
            continue
        current = float(item.get("price") or 0)
        base = float(item.get("original_price") or current)
        new = line_price(base, current, percent)
        if new >= current:
            continue
        saved += (current - new) * float(item.get("quantity") or 0)
        item["price"] = new
        item["original_price"] = base
        item["discount_percent"] = int(round((base - new) * 100 / base)) if base else percent
        item["bot_discount"] = percent
    return saved


def cart_saving(cart_rows: list[dict], percent: int) -> float:
    """Savat ko'rinishi uchun: database.get_cart qatorlarida qancha tejaladi."""
    if not percent:
        return 0.0
    saved = 0.0
    for row in cart_rows:
        base = float(row["price"])
        if row.get("is_set"):
            current = base
        else:
            current = database.effective_price(base, row.get("discount_percent"), row.get("discount_until"))
        saved += (current - line_price(base, current, percent)) * float(row["cart_quantity"])
    return saved


# ───────────────────────────── matnlar ─────────────────────────────

_TEXT = {
    # Egasi so'zi bilan, 2026-10-08.
    "reminder": {
        "uz": "🎁 Bot orqali buyurtma qilib, istalgan summaga 10% chegirmaga ega bo'ling!",
        "ru": "🎁 Оформляйте заказ через бота и получайте скидку 10% на любую сумму!",
    },
    "label": {
        "uz": "🎁 Bot orqali buyurtma chegirmasi (−{p}%)",
        "ru": "🎁 Скидка за заказ через бота (−{p}%)",
    },
    "amount": {
        "uz": "−{amount} so'm",
        "ru": "−{amount} сум",
    },
    "cart_pay": {
        "uz": "💚 <b>Chegirma bilan to'lovga: {total} so'm</b>",
        "ru": "💚 <b>К оплате со скидкой: {total} сум</b>",
    },
}


def reminder_text(lang: str) -> str:
    return _pick(_TEXT["reminder"], lang)


async def reminder(lang: str) -> str:
    """Eslatma qatori yoki "" (chegirma o'chiq bo'lsa)."""
    return reminder_text(lang) if await is_active() else ""


async def footer(lang: str) -> str:
    """Xabar oxiriga qo'shiladigan blok: "\\n\\n🎁 ..." yoki ""."""
    line = await reminder(lang)
    return f"\n\n{line}" if line else ""


async def channel_footer(lang: str = "uz_cyr") -> str:
    """Kanal posti uchun — bot manzili bilan, chunki kanal o'quvchisi hali
    botda bo'lmasligi mumkin."""
    line = await reminder(lang)
    return f"\n\n{line}\n👉 @{BOT_USERNAME}" if line else ""


def saving_label(lang: str, percent: int) -> str:
    return _pick(_TEXT["label"], lang).replace("{p}", str(percent))


def saving_line(lang: str, percent: int, amount: float) -> str:
    sum_text = _pick(_TEXT["amount"], lang).replace("{amount}", _som(amount))
    return f"{saving_label(lang, percent)}: <b>{sum_text}</b>"


def cart_pay_line(lang: str, total: float) -> str:
    return _pick(_TEXT["cart_pay"], lang).replace("{total}", _som(total))


# ───────────────────────────── adminlar ─────────────────────────────

def _stopped_text(stopped: list[dict]) -> str:
    if not stopped:
        return "Mahsulotlarda 🔥 chegirma yo'q edi — hech narsa to'xtatilmadi."
    names = "\n".join(f"• #{p['id']} {p['name']}" for p in stopped[:30])
    more = f"\n… yana {len(stopped) - 30} ta" if len(stopped) > 30 else ""
    return f"To'xtatilgan 🔥 chegirmalar ({len(stopped)} ta):\n{names}{more}"


@router.message(Command("chegirma"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_status(message: Message):
    state = await get_state()
    on = bool(state.get("active"))
    changed = state.get("changed_at")
    when = f"\nOxirgi o'zgarish: {changed:%d.%m.%Y %H:%M} UTC" if changed else ""
    import bot_discount_campaign
    await message.answer(
        f"🎁 <b>Bot orqali buyurtmaga {PERCENT}% chegirma</b>\n"
        f"Holat: {'✅ yoqilgan' if on else '⚪ o‘chiq'}{when}\n"
        "Kimga: botda va saytda o'zi buyurtma bergan mijozlarga (adminlarga emas).\n\n"
        f"{await bot_discount_campaign.status_text()}\n\n"
        "/chegirma_off — o'chirish · /chegirma_on — yoqish",
        parse_mode=ParseMode.HTML)


@router.message(Command("chegirma_on"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_on(message: Message):
    stopped = await set_active(True, message.from_user.id)
    await message.answer(f"✅ {PERCENT}% chegirma yoqildi.\n{_stopped_text(stopped)}")


@router.message(Command("chegirma_off"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_off(message: Message):
    await set_active(False, message.from_user.id)
    await message.answer(
        f"⚪ {PERCENT}% chegirma o'chirildi. Yangi buyurtmalar katalog narxida, "
        "eslatmalar ham hamma joydan yo'qoladi.")
