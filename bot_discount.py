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
o'sha. Narx hech qachon tannarxdan (cost_price, set uchun tarkibi) arzonga
tushmaydi — egasi: "zararga sotilmasligi kerak". Marjasi 10% dan kam
mahsulotda chegirma marja qadar kichrayadi; tannarxi kiritilmagan mahsulotda
bot zararni bila olmaydi — ular /chegirma_marja ro'yxatida.
Bepul yetkazish (800 000) chegirmagacha bo'lgan summadan hisoblanadi
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

Boshqaruv (adminlar): /chegirma — holat · /chegirma_on · /chegirma_off ·
/chegirma_marja — marjasi 10% dan kam va tannarxi yo'q mahsulotlar
"""
import html
import logging
import math
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


async def preview_percent_for(user_id: int) -> int:
    """Admin savatni mijoz bilan bir xil ko'radi (−10% va chegirmali summa),
    lekin buyurtmasi to'liq narxda qoladi — egasi, 2026-10-08: "adminlar
    uchun ham huddi userlarga ko'rsatgandek ko'rsat, faqat chegirma amal
    qilmasin ohirida". Admin bo'lmagan yoki chegirma o'chiq bo'lsa — 0."""
    if eligible(user_id):
        return 0
    return PERCENT if await is_active() else 0


def line_price(base: float, current: float, percent: int, cost: float | None = None) -> float:
    """Katalog narxidan `percent` kam, lekin:
      • mahsulotning o'z chegirmali narxidan qimmat emas — ikkalasi
        qo'shilmaydi, arzoni qoladi;
      • TANNARXDAN ARZON EMAS (egasi, 2026-10-08: "zararga sotilmasligi
        kerak"). Marjasi 10% dan kam mahsulotga chegirma marja qadar
        kichrayadi, marjasi yo'q mahsulotga umuman qo'llanmaydi.
    `cost` — bir dona tannarxi; None/0 = noma'lum (tannarx kiritilmagan)."""
    current = float(current)
    if not percent or not base:
        return current
    new = float(round(float(base) * (100 - percent) / 100))
    if cost and cost > 0:
        new = max(new, float(math.ceil(cost)))
    return min(current, new)


async def _cost_maps(items: list[dict]) -> tuple[dict, dict]:
    """{product_id: (cost, known)}, {set_id: (cost, known)} — bitta so'rovda,
    hisobotlar ishlatadigan qoida bilan (database._order_cost_maps)."""
    try:
        async with database.pool.acquire() as conn:
            return await database._order_cost_maps(conn, items)
    except Exception:
        logger.warning("bot_discount: cost lookup failed", exc_info=True)
        return {}, {}


def _unit_cost(item: dict, product_costs: dict, set_costs: dict) -> float | None:
    if item.get("is_set"):
        cost, known = set_costs.get(database._line_set_id(item), (0.0, False))
    else:
        cost, known = product_costs.get(database._line_product_id(item), (0.0, False))
    return cost if known else None


async def apply(items: list[dict], percent: int) -> float:
    """Checkout qatorlariga (handlers/cart.py / webapp_server.py items_data)
    chegirmani yozadi. Qaytaradi: tejalgan summa. Sovg'a/bonus qatorlari
    (narxi 0) o'zgarmaydi; hech bir qator tannarxdan arzonga tushmaydi."""
    if not percent:
        return 0.0
    paid = [it for it in items if not (it.get("is_bonus") or it.get("is_gift"))]
    product_costs, set_costs = await _cost_maps(paid)
    saved = 0.0
    for item in paid:
        current = float(item.get("price") or 0)
        base = float(item.get("original_price") or current)
        new = line_price(base, current, percent, _unit_cost(item, product_costs, set_costs))
        if new >= current:
            continue
        saved += (current - new) * float(item.get("quantity") or 0)
        item["price"] = new
        item["original_price"] = base
        item["discount_percent"] = int(round((base - new) * 100 / base)) if base else percent
        item["bot_discount"] = percent
    return saved


async def cart_saving(cart_rows: list[dict], percent: int) -> float:
    """Savat ko'rinishi uchun: database.get_cart qatorlarida qancha tejaladi
    (checkout bilan bir xil qoida, tannarx chegarasi bilan)."""
    if not percent:
        return 0.0
    product_costs, set_costs = await _cost_maps(cart_rows)
    saved = 0.0
    for row in cart_rows:
        base = float(row["price"])
        if row.get("is_set"):
            current = base
        else:
            current = database.effective_price(base, row.get("discount_percent"), row.get("discount_until"))
        new = line_price(base, current, percent, _unit_cost(row, product_costs, set_costs))
        saved += (current - new) * float(row["cart_quantity"])
    return saved


async def margin_report() -> dict:
    """Sotuvdagi mahsulot va setlar: 10% to'liq qo'llanmaydiganlari
    (marja < 10%) va tannarxi kiritilmaganlari (ularda chegara ishlamaydi)."""
    async with database.pool.acquire() as conn:
        rows = [dict(r) for r in await conn.fetch(
            """SELECT id, name, price, COALESCE(cost_price, 0) AS cost_price
                 FROM products
                WHERE is_active = 1 AND (b2b_only IS NOT TRUE) AND COALESCE(price, 0) > 0
                ORDER BY name""")]
        sets = [dict(r) for r in await conn.fetch(
            """SELECT id AS set_id, name, set_price AS price, TRUE AS is_set
                 FROM product_sets WHERE is_active = 1 AND COALESCE(set_price, 0) > 0
                ORDER BY name""")]
        product_costs, set_costs = await database._order_cost_maps(conn, rows + sets)
    capped, no_cost = [], []
    for item in rows + sets:
        base = float(item["price"])
        cost = _unit_cost(item, product_costs, set_costs)
        label = ("🧺 " if item.get("is_set") else "") + str(item["name"])
        if cost is None:
            no_cost.append({"name": label, "price": base})
            continue
        new = line_price(base, base, PERCENT, cost)
        if new > round(base * (100 - PERCENT) / 100):
            capped.append({"name": label, "price": base, "cost": cost, "new": new,
                           "percent": round((base - new) * 100 / base, 1)})
    return {"capped": capped, "no_cost": no_cost, "total": len(rows) + len(sets)}


def margin_report_text(report: dict, limit: int = 40) -> str:
    def _cut(lines: list[str]) -> str:
        more = f"\n… yana {len(lines) - limit} ta" if len(lines) > limit else ""
        return "\n".join(lines[:limit]) + more

    capped, no_cost = report["capped"], report["no_cost"]
    parts = [f"🛡 <b>10% chegirma — tannarx himoyasi</b>\n"
             f"Sotuvdagi {report['total']} ta mahsulot/setdan:"]
    if capped:
        parts.append(
            f"\n⚠️ <b>Marjasi 10% dan kam — chegirma kamaytirildi ({len(capped)} ta):</b>\n"
            "Narx tannarxdan pastga tushmaydi.\n" + _cut([
                f"• {html.escape(p['name'], quote=False)} — {_som(p['price'])} → {_som(p['new'])} "
                f"(tannarx {_som(p['cost'])}, chegirma {p['percent']:g}%)" for p in capped]))
    else:
        parts.append("\n✅ Tannarxi kiritilgan hamma mahsulotda 10% chegirma zararsiz.")
    if no_cost:
        parts.append(
            f"\n❓ <b>Tannarxi kiritilmagan ({len(no_cost)} ta)</b> — bularda zarar bor-yo'qligini "
            "bot bila olmaydi, chegirma to'liq 10%. /admin → Mahsulotlar → tannarxni kiriting:\n"
            + _cut([f"• {html.escape(p['name'], quote=False)} — {_som(p['price'])}" for p in no_cost]))
    return "\n".join(parts)


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
    # Saytdagi (Mini App) bosh sahifa e'loni — egasi: "10% lik e'lonni
    # saytga ham qo'shishni unutma".
    "banner_title": {
        "uz": "Bot orqali buyurtmaga 10% chegirma",
        "ru": "Скидка 10% на заказ через бота",
    },
    "banner_sub": {
        "uz": "Istalgan summaga, promokodsiz — chegirma savatda o'zi hisoblanadi",
        "ru": "На любую сумму, без промокода — скидка считается в корзине сама",
    },
    # Egasi: "adminlar uchun ham huddi userlarga ko'rsatgandek ko'rsat,
    # faqat chegirma amal qilmasin ohirida".
    "admin_cart_note": {
        "uz": "ℹ️ Mijozlar savatni aynan shunday ko'radi. Admin buyurtmasiga chegirma qo'llanmaydi — "
              "rasmiylashtirishda summa to'liq narxda bo'ladi.",
        "ru": "ℹ️ Клиенты видят корзину именно так. К заказам админов скидка не применяется — "
              "при оформлении сумма будет по полной цене.",
    },
    "admin_checkout_note": {
        "uz": "ℹ️ Admin buyurtmasi — {p}% chegirma qo'llanmadi, summa to'liq narxda.",
        "ru": "ℹ️ Заказ админа — скидка {p}% не применена, сумма по полной цене.",
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


async def site_banner(lang: str) -> dict | None:
    """Mini App bosh sahifasidagi e'lon kartochkasi; o'chiq bo'lsa None."""
    if not await is_active():
        return None
    return {"title": _pick(_TEXT["banner_title"], lang), "sub": _pick(_TEXT["banner_sub"], lang)}


def saving_label(lang: str, percent: int) -> str:
    return _pick(_TEXT["label"], lang).replace("{p}", str(percent))


def saving_line(lang: str, percent: int, amount: float) -> str:
    sum_text = _pick(_TEXT["amount"], lang).replace("{amount}", _som(amount))
    return f"{saving_label(lang, percent)}: <b>{sum_text}</b>"


def admin_cart_note(lang: str) -> str:
    return _pick(_TEXT["admin_cart_note"], lang)


def admin_checkout_note(lang: str, percent: int) -> str:
    return _pick(_TEXT["admin_checkout_note"], lang).replace("{p}", str(percent))


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
        "Kimga: botda va saytda o'zi buyurtma bergan mijozlarga (adminlarga emas).\n"
        f"{await margin_summary_line()}\n\n"
        f"{await bot_discount_campaign.status_text()}\n\n"
        "/chegirma_off — o'chirish · /chegirma_on — yoqish",
        parse_mode=ParseMode.HTML)


async def margin_summary_line() -> str:
    try:
        report = await margin_report()
    except Exception:
        logger.warning("bot_discount: margin report failed", exc_info=True)
        return "🛡 Tannarx himoyasi: hisobot o'qilmadi."
    return (f"🛡 Tannarxdan arzonga sotilmaydi: {len(report['capped'])} ta mahsulotda chegirma "
            f"kamaytirilgan, {len(report['no_cost'])} tasida tannarx yo'q — /chegirma_marja")


async def send_long(bot, chat_id: int, text: str) -> None:
    """Telegram 4096 belgidan uzun matnni qatorlar bo'yicha bo'lib yuboradi."""
    chunk = ""
    for line in text.split("\n"):
        if len(chunk) + len(line) + 1 > 4000:
            await bot.send_message(chat_id, chunk, parse_mode=ParseMode.HTML)
            chunk = ""
        chunk += line + "\n"
    if chunk.strip():
        await bot.send_message(chat_id, chunk, parse_mode=ParseMode.HTML)


@router.message(Command("chegirma_marja"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_margin(message: Message):
    await send_long(message.bot, message.chat.id, margin_report_text(await margin_report(), limit=200))


MARGIN_REPORT_KEY = "bot-discount-margin-2026-10-08"


async def margin_report_once(bot) -> None:
    """Bir martalik: deploydan keyin kunduzi adminlarga tannarx hisoboti —
    egasi so'radi, qaysi mahsulotlar marjasi 10% dan kam."""
    from datetime import datetime, timedelta
    import asyncio
    while True:
        try:
            hour = (datetime.utcnow() + timedelta(hours=5)).hour
            if 8 <= hour < 22:
                if await database.claim_release_notes(MARGIN_REPORT_KEY):
                    text = margin_report_text(await margin_report(), limit=200)
                    for admin_id in list(dict.fromkeys(ADMIN_IDS)):
                        try:
                            await send_long(bot, admin_id, text)
                        except Exception:
                            pass
                return
        except Exception:
            logger.exception("bot_discount: margin report send failed")
            return
        await asyncio.sleep(300)


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
