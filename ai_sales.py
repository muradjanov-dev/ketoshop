"""
AI sotuvchi — mijoz bilan yozishib, buyurtmani o'zi rasmiylashtiradi.

Bot tugmalar bilan ishlaydi: katalog -> savat -> manzil -> tasdiq. Kim
tugmalarni bosmay, oddiy odamdek yozsa (meta_leads.py orqali kelgan reklama
mijozlari ko'pincha shunday qiladi), hozirgacha javob admin yozguncha kutardi.
Bu modul o'sha suhbatni Claude'ga topshiradi: mahsulotni tanlaydi, savatga
soladi, ism/telefon/manzilni so'raydi va buyurtmani xuddi tugmali yo'l kabi
rasmiylashtiradi.

TO'LOV. Mijoz karta orqali to'lamoqchi bo'lsa, AI do'konning karta raqamini
o'zi beradi (config.PAYMENT_CARD_NUMBER — tugmali checkout bilan bir xil karta)
va chek rasmini so'raydi. Lekin "to'lov o'tdi" degan qarorni AI hech qachon
qabul qilmaydi: chek rasmi to'g'ridan-to'g'ri adminlarga uzatiladi va bazada
buyurtma `payment_method="cash"` bo'lib qoladi — ya'ni "to'langan" deb
belgilanmaydi. Tugmali online oqim chek tekshirilgandan keyingina online deb
yoziladi (handlers/cart.py), AI uni yolg'on "to'landi" holatiga qo'ymasligi
uchun ataylab shunday. Egasining talabi: kartani AI tashlaydi, to'lovni admin
ko'radi (2026-09-12).

HOZIRCHA FAQAT ADMINLARDA. AI_SALES_ADMIN_ONLY=0 qo'yilmaguncha /ai faqat
ADMIN_IDS uchun ochiq — avval o'zingiz sinab ko'rasiz, keyin mijozlarga
ochasiz. Kalitsiz (ANTHROPIC_API_KEY) modul umuman jim: meta_leads.py bilan
bir xil xulq, deploy tokensiz ham buzilmaydi.

QANDAY ISHLAYDI
  /ai        — suhbatni yoqadi (shundan keyin oddiy matn AI ga boradi)
             Matndan tashqari: 📍 lokatsiya, 📞 kontakt va chek rasmi ham
             o'sha suhbatga tushadi.
  /ai_off    — o'chiradi, bot odatdagidek tugmalar bilan ishlaydi
  /ai_holat  — model, sessiyalar, narx sozlamalari

Modelga butun katalog (nomi, narxi, qoldig'i) tizim promptida beriladi — 105
mahsulot ~3K token, 5 daqiqaga keshlanadi — shuning uchun u narx yoki mahsulot
"o'ylab topa" olmaydi. Qo'lidagi vositalar faqat to'rtta: savatga solish,
savatni ko'rish, savatdan o'chirish, buyurtma rasmiylashtirish. Buyurtma
haqiqiy savatdan create_order() bilan tuziladi, ya'ni aksiya sovg'alari, Keto
chegirmasi va ombor hisobi tugmali yo'l bilan bir xil ishlaydi.

Env vars
--------
ANTHROPIC_API_KEY     majburiy — busiz modul o'chiq.
AI_SALES_MODEL        default "claude-opus-5".
AI_SALES_EFFORT       default "low" — suhbat uchun tez va arzon.
AI_SALES_ADMIN_ONLY   default "1". "0" — hamma mijozga ochiq.
AI_SALES_MAX_TURNS    bitta javobdagi vosita chaqiruvlari chegarasi (default 6).
AI_GROUP_CHATS        guruh id lari (vergul bilan) — o'sha guruhlarda bot
                      mention/reply bo'lsa savolga javob beradi. Bo'sh = o'chiq.
AI_GROUP_COOLDOWN     bitta guruhda javoblar orasidagi eng kam soniya (default 20).
"""
import html
import logging
import os
import time

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import Message

import database
from config import (ADMIN_IDS, BOT_USERNAME, PAYMENT_CARD_NUMBER,
                    PAYMENT_RECIPIENT_NAME, SUPPORT_PHONES)

logger = logging.getLogger(__name__)
router = Router()

API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
MODEL = os.getenv("AI_SALES_MODEL", "claude-opus-5").strip()
EFFORT = os.getenv("AI_SALES_EFFORT", "low").strip()
ADMIN_ONLY = os.getenv("AI_SALES_ADMIN_ONLY", "1").strip() != "0"
MAX_TURNS = max(2, int(os.getenv("AI_SALES_MAX_TURNS", "6")))
GROUP_CHATS = {
    int(part) for part in os.getenv("AI_GROUP_CHATS", "").replace(" ", "").split(",")
    if part.lstrip("-").isdigit()
}
GROUP_COOLDOWN = max(0, int(os.getenv("AI_GROUP_COOLDOWN", "20")))

MAX_TOKENS = 800          # javoblar qisqa — bu ham ortig'i bilan yetadi
CATALOG_TTL = 300         # katalog snapshotini 5 daqiqa saqlaymiz
SESSION_TTL = 3 * 3600    # 3 soat jim tursa, suhbat unutiladi
HISTORY_LIMIT = 40        # oxirgi 40 xabar — undan oldingisi kesiladi
DEFAULT_DELIVERY = "self"  # Ketoshop kuryeri

_client = None
_catalog_cache: tuple[float, str] | None = None
_sessions: dict[int, dict] = {}
_group_last: dict[int, float] = {}   # chat_id -> oxirgi javob vaqti (cooldown)


def is_enabled() -> bool:
    return bool(API_KEY)


def _allowed(user_id: int) -> bool:
    return (not ADMIN_ONLY) or user_id in ADMIN_IDS


def _get_client():
    """Klient birinchi so'rovda yaratiladi — kalitsiz deployda anthropic
    paketiga umuman tegilmaydi."""
    global _client
    if _client is None:
        from anthropic import AsyncAnthropic
        _client = AsyncAnthropic(api_key=API_KEY)
    return _client


def _fmt(n) -> str:
    return f"{int(n or 0):,}".replace(",", " ")


# ─────────────────────────────── katalog ────────────────────────────────────

async def _catalog_text() -> str:
    """Butun faol katalog bitta matnda: id, nomi, narxi, qoldig'i. Shu matn
    tizim promptida turadi va model faqat shundan gapiradi — qidiruv vositasi
    kerak emas, "yo'q narsani bor" deb aytish ehtimoli ham yo'qoladi."""
    global _catalog_cache
    now = time.time()
    if _catalog_cache and now - _catalog_cache[0] < CATALOG_TTL:
        return _catalog_cache[1]

    products, _ = await database.get_all_products_paginated(page=0, per_page=500)
    lines = []
    for p in products:
        stock = float(p.get("quantity") or 0)
        if stock <= 0:
            continue  # tugagan mahsulotni ko'rsatmaymiz — va'da berib bo'lmaydi
        discount = int(p.get("discount_percent") or 0)
        price = float(p["price"])
        badge = ""
        if discount:
            badge = f" (chegirma -{discount}%)"
        lines.append(
            f"{p['id']} | {p['name']} | {_fmt(price)} so'm / {p.get('unit') or 'dona'}"
            f" | qoldiq {stock:g}{badge}"
        )
    text = "\n".join(lines) if lines else "(katalog bo'sh)"
    _catalog_cache = (now, text)
    return text


def _system_prompt(catalog: str) -> list[dict]:
    """Tizim prompti ikki bo'lakda: o'zgarmas qoidalar (keshlanadi) va
    katalog (5 daqiqada bir yangilanadi, o'zi ham keshlanadi)."""
    rules = (
        "Sen Ketoshop (@ketoshopbot) internet-do'konining sotuvchisisan. "
        "Ketoshop Toshkentda keto va PP mahsulotlari sotadi.\n\n"
        "SEN KIMSAN\n"
        "- Sen Ketoshopning sotuv yordamchisisan. O'zingni robot, bot, AI yoki "
        "sun'iy intellekt deb tanishtirma va 'men dasturman', 'model sifatida' "
        "kabi gaplarni ishlatma — mijoz do'kon xodimi bilan yozishayotgandek "
        "his qilsin.\n"
        "- Jonli odamdek yoz: tabiiy, iliq, sodda jumlalar. Shablon javoblar va "
        "har safar takrorlanadigan bir xil iboralar bo'lmasin.\n"
        "- Mijoz to'g'ridan-to'g'ri 'robotmisan / odammisan?' deb so'rasa, "
        "bahslashma va o'zingni odam deb ham atama: 'Men Ketoshop yordamchisiman, "
        "xodimimiz bilan bevosita ham gaplashsangiz bo'ladi' de va raqamni ber:\n"
        "  " + SUPPORT_PHONES + "\n\n"
        "GAPIRISH USLUBI\n"
        "- QISQA yoz: 1-3 ta jumla, ortiqcha muqaddimasiz. Bu Telegram chat, maqola emas.\n"
        "- Mijoz qaysi tilda yozsa, o'sha tilda javob ber (o'zbekcha yoki ruscha).\n"
        "- Iliq va sodda gapir, emoji ni oz ishlat (javobiga bittadan ko'p emas).\n"
        "- Bir vaqtda bitta narsa so'ra: hammasini birdan so'rab ro'yxat yozma.\n\n"
        "MAHSULOTLAR\n"
        "- Faqat quyidagi katalogdagi mahsulotlarni taklif qil. Katalogda yo'q narsani "
        "yo'q deb ayt va yaqin muqobilini taklif qil.\n"
        "- Narxni ham, qoldiqni ham faqat katalogdan ol. Chegirma, yetkazish narxi yoki "
        "aksiya haqida o'zingdan hech narsa o'ylab topma.\n"
        "- Mijoz nima uchun kerakligini aytsa (masalan 'shirinlik pishirmoqchiman'), "
        "katalogdan 2-3 ta mosini taklif qil, ro'yxatni to'kib tashlama.\n\n"
        "MASLAHAT (keto va PP)\n"
        "- Keto va to'g'ri ovqatlanish bo'yicha savollarga qisqa, aniq javob ber: "
        "qanday mahsulot nimaga ishlatiladi, un o'rniga nima bo'ladi, shakar o'rniga "
        "qaysi shirinlatgich, qanday pishiriladi.\n"
        "- Maslahatni har doim katalogdagi aniq mahsulotga ulab qo'y — bu maqola emas, "
        "savdo suhbati. Masalan: 'bodom uni bilan pishiriladi, bizda 1 kg — 149 000 so'm'.\n"
        "- Kaloriya, uglevod yoki tarkib raqamlarini bilmasang, o'ylab topma.\n\n"
        "SALOMLASHISH — BIRINCHI XABAR\n"
        "- Mijoz salom bermay to'g'ridan-to'g'ri gap boshlasa, javobni shunday boshla:\n"
        "  'Assalomu alaykum, Keto shopga xush kelibsiz!'\n"
        "- Mijoz o'zi salom bersa (assalomu alaykum, salom, salomatmisiz):\n"
        "  'Vaalaykum assalom! Assalomu alaykum, Keto shopga xush kelibsiz!'\n"
        "- Ruscha yozgan mijozga shu salomning ruschasini ber: "
        "'Ассалому алайкум, добро пожаловать в Keto shop!'\n"
        "- Salomdan keyin darrov ishga o't: mijozning savoliga javob ber yoki "
        "bitta qisqa savol bilan mavzuga burib yubor ('nima qidiryapsiz?').\n"
        "- Salomni FAQAT suhbatning birinchi javobida ayt, keyingi har bir "
        "xabarda takrorlama.\n\n"
        "BUYURTMA\n"
        "- Mahsulot tanlangach savatga_qoshish bilan savatga sol va qisqacha tasdiqla.\n"
        "- Buyurtma uchun uchta narsa kerak: ISM, TELEFON raqam, MANZIL. "
        "Ularni birma-bir so'ra.\n"
        "- MANZILNI so'raganda mijozdan Telegram lokatsiyasini yuborishni so'ra "
        "(skrepka 📎 -> Location), kuryerga eng aniq shu bo'ladi. Lokatsiya yubora "
        "olmasa, manzilni matn bilan yozsin — ikkalasi ham bo'ladi.\n"
        "- Telefonni ham kontakt tugmasi orqali yuborsa bo'ladi.\n"
        "- Hammasi yig'ilgach savatni va umumiy summani qisqa takrorlab, mijozdan "
        "tasdiq so'ra. Mijoz 'ha' degandan keyingina buyurtma_rasmiylashtirish ni chaqir.\n"
        "- Buyurtma tushgach raqamini ayt va 'operatorimiz tez orada bog'lanadi' de.\n\n"
        "TO'LOV\n"
        "- Ikki yo'l bor: NAQD (kuryerga qo'lma-qo'l) yoki KARTA orqali oldindan. "
        "Buyurtmani rasmiylashtirishdan oldin qaysi biri ekanini so'ra va "
        "buyurtma_rasmiylashtirish da tolov_turi ni to'g'ri ko'rsat.\n"
        f"- Karta tanlansa, buyurtma tushgandan KEYIN karta raqamini o'zing ber:\n"
        f"  {PAYMENT_CARD_NUMBER} — {PAYMENT_RECIPIENT_NAME}\n"
        "  va to'lov chekining rasmini shu chatga yuborishni so'ra.\n"
        "- LEKIN to'lovni sen tasdiqlamaysan. 'Pul tushdi', 'to'lov o'tdi', "
        "'tasdiqladim' dema. Chek kelgach: 'rahmat, operatorimiz tekshirib "
        "tasdiqlaydi' de. Tekshirishni faqat admin qiladi.\n"
        "- Karta raqamini buyurtmasiz, shunchaki so'ragan odamga ham ayta olasan, "
        "lekin avval nimaga to'lamoqchi ekanini aniqlashtir.\n"
        "- Yetkazib berish muddati, aksiya shartlari yoki qaytarish bo'yicha aniq "
        "ma'lumoting bo'lmasa, va'da berma — operator aniqlashtirishini ayt.\n\n"
        "NOQULAY HOLAT — TELEFON RAQAMNI BER\n"
        "- Quyidagi hollarda bahslashma va cho'zma: qisqa uzr so'ra, "
        "'Batafsil ma\'lumot olish uchun:' deb yozib, shu raqamni ber — "
        + SUPPORT_PHONES + "\n"
        "  * mijoz norozi, jahli chiqqan yoki shikoyat qilyapti;\n"
        "  * buyurtma, to'lov yoki yetkazib berishda muammo chiqqan "
        "(kech qoldi, mahsulot yetib bormadi, pul yechildi-yu buyurtma yo'q);\n"
        "  * mahsulotni qaytarish, almashtirish yoki pulni qaytarish masalasi;\n"
        "  * ulgurji/hamkorlik, hujjat, shartnoma yoki hisob-faktura so'ralsa;\n"
        "  * savolga aniq javobni bilmasang yoki javob berishga huquqing yo'q;\n"
        "  * mijoz tirik odam bilan gaplashmoqchi bo'lsa.\n"
        "- Raqamni bergandan keyin ham muloyim qol: 'qo'shimcha savolingiz bo'lsa "
        "shu yerda ham yozavering' de.\n"
        "- Va'da berma: 'pulingizni qaytaramiz', 'ertaga yetkazamiz' kabi qarorlarni "
        "sen qabul qilmaysan — buni xodimlarimiz kelishadi.\n\n"
        "BOSHQA\n"
        "- Tibbiy maslahat berma (dori, davolash, diagnoz). Keto mahsulot sifatida "
        "gapir, shifokor o'rnini bosma. Kasallik haqida so'rashsa shifokorga "
        "murojaat qilishni ayt va raqamimizni ber.\n"
    )
    return [
        {"type": "text", "text": rules, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "KATALOG (id | nomi | narxi | qoldiq):\n" + catalog,
         "cache_control": {"type": "ephemeral"}},
    ]


TOOLS = [
    {
        "name": "savatga_qoshish",
        "description": "Mahsulotni mijozning savatiga qo'shadi. Katalogdagi id ni ishlat. "
                       "Miqdor — kg uchun 0.5/1/2 kabi, dona uchun butun son.",
        "input_schema": {
            "type": "object",
            "properties": {
                "mahsulot_id": {"type": "integer", "description": "Katalogdagi mahsulot id"},
                "miqdor": {"type": "number", "description": "Necha kg yoki dona"},
            },
            "required": ["mahsulot_id", "miqdor"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "savatni_korish",
        "description": "Savatdagi mahsulotlar va umumiy summani qaytaradi.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "savatdan_ochirish",
        "description": "Mahsulotni savatdan olib tashlaydi.",
        "input_schema": {
            "type": "object",
            "properties": {"mahsulot_id": {"type": "integer"}},
            "required": ["mahsulot_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "buyurtma_rasmiylashtirish",
        "description": "Savatdagi mahsulotlardan haqiqiy buyurtma yaratadi va adminlarga "
                       "yuboradi. Faqat mijoz savat va summani tasdiqlagandan keyin chaqir. "
                       "tolov_turi='karta' bo'lsa, javobda karta raqami qaytadi — uni "
                       "mijozga aytasan, lekin to'lovni admin tekshiradi.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ism": {"type": "string", "description": "Mijozning ismi"},
                "telefon": {"type": "string", "description": "Telefon raqami"},
                "manzil": {"type": "string", "description": "Yetkazish manzili matn bilan. "
                           "Mijoz Telegram lokatsiyasini yuborgan bo'lsa bo'sh qoldirsa "
                           "ham bo'ladi — lokatsiya avtomatik ishlatiladi."},
                "tolov_turi": {"type": "string", "enum": ["naqd", "karta"],
                               "description": "Mijoz qanday to'laydi"},
                "izoh": {"type": "string", "description": "Qo'shimcha izoh (ixtiyoriy)"},
            },
            "required": ["ism", "telefon", "tolov_turi"],
            "additionalProperties": False,
        },
    },
]


# ──────────────────────────────── vositalar ─────────────────────────────────

async def _tool_add(user_id: int, args: dict) -> str:
    product_id = int(args.get("mahsulot_id") or 0)
    qty = float(args.get("miqdor") or 0)
    if qty <= 0:
        return "Xato: miqdor 0 dan katta bo'lishi kerak."
    product = await database.get_product(product_id)
    if not product or not product.get("is_active"):
        return f"Xato: {product_id} raqamli mahsulot katalogda yo'q."
    stock = float(product.get("quantity") or 0)
    if qty > stock:
        return (f"Xato: omborda {product['name']} dan atigi {stock:g} "
                f"{product.get('unit') or 'dona'} qolgan. Mijozga shuni ayt.")
    await database.add_to_cart(user_id, product_id=product_id, quantity=qty)
    return (f"OK: {product['name']} — {qty:g} {product.get('unit') or 'dona'} "
            f"savatga qo'shildi.")


async def _tool_cart(user_id: int) -> str:
    items = await database.get_cart(user_id)
    if not items:
        return "Savat bo'sh."
    lines, total = [], 0.0
    for item in items:
        line_total = float(item["price"]) * float(item["cart_quantity"])
        total += line_total
        lines.append(f"- {item['name']}: {item['cart_quantity']:g} {item['unit']} = "
                     f"{_fmt(line_total)} so'm (id {item.get('product_id')})")
    lines.append(f"JAMI: {_fmt(total)} so'm (yetkazish narxi hisobga olinmagan)")
    return "\n".join(lines)


async def _tool_remove(user_id: int, args: dict) -> str:
    product_id = int(args.get("mahsulot_id") or 0)
    cart_id, _ = await database.get_cart_line_for_product(user_id, product_id)
    if not cart_id:
        return "Bu mahsulot savatda yo'q edi."
    await database.remove_from_cart(cart_id)
    return "OK: savatdan o'chirildi."


async def _tool_order(bot: Bot, message: Message, args: dict) -> str:
    """Haqiqiy buyurtma. Tugmali checkout bilan bitta yo'ldan yuradi
    (handlers/cart.py::_build_order_summary -> database.create_order ->
    _notify_sellers), shuning uchun aksiya sovg'alari, chegirmalar va ombor
    hisobi o'z-o'zidan to'g'ri bo'ladi."""
    from handlers.cart import _build_order_summary, _notify_sellers

    user_id = message.from_user.id
    lang = await database.get_user_language(user_id) or "uz"
    data = {"delivery_method": DEFAULT_DELIVERY}

    text, total, items_data, keto_redeem = await _build_order_summary(user_id, data, lang)
    if not items_data:
        return "Xato: savat bo'sh — avval mahsulot qo'shish kerak."

    session = _session(user_id)
    location = session.get("location")   # (lat, lon, o'qiladigan manzil) yoki None

    name = (args.get("ism") or message.from_user.full_name or "—").strip()
    phone = (args.get("telefon") or session.get("phone") or "").strip()
    address = (args.get("manzil") or "").strip()
    payment = (args.get("tolov_turi") or "naqd").strip().lower()
    note = (args.get("izoh") or "").strip() or None

    # Lokatsiya bo'lsa u manzilning o'zi bo'la oladi — kuryerga eng aniq shu.
    # Mijoz ham lokatsiya, ham matn bergan bo'lsa ikkalasi ham yoziladi.
    if location:
        pin = location[2] or f"📍 {location[0]:.6f}, {location[1]:.6f}"
        address = f"{pin} — {address}" if address else pin
    if not phone:
        return "Xato: telefon raqami kerak. Mijozdan so'ra."
    if not address:
        return ("Xato: manzil yo'q. Mijozdan Telegram lokatsiyasini yuborishni yoki "
                "manzilni yozishni so'ra.")

    # Karta tanlansa ham bazada payment_method 'cash' bo'lib qoladi: 'online'
    # tugmali oqimda "chek tekshirilgan" degani (handlers/cart.py), va AI uni
    # to'langan deb belgilay olmaydi. Tanlov izohda ko'rinadi.
    if payment == "karta":
        note = f"To'lov: KARTA (chek kutilmoqda){' · ' + note if note else ''}"

    try:
        order_id, low_stock = await database.create_order(
            user_id=user_id,
            customer_name=name,
            phone=phone,
            address=address,
            items=items_data,
            total=total,
            payment_method="cash",   # to'lovni admin tasdiqlaydi — AI hech qachon emas
            latitude=location[0] if location else None,
            longitude=location[1] if location else None,
            delivery_method=DEFAULT_DELIVERY,
            address_note=note,
            keto_redeem=keto_redeem,
        )
    except database.InsufficientStockError:
        return ("Xato: mahsulot omborda tugab qolibdi. Mijozdan uzr so'ra va "
                "savatni qayta ko'rib chiq.")
    except database.InsufficientKetoError:
        return "Xato: Keto balansi yetmadi, chegirmasiz qayta urinib ko'r."
    except Exception:
        logger.exception("AI order creation failed for %s", user_id)
        return "Xato: buyurtma yaratilmadi. Mijozga operator bog'lanishini ayt."

    await database.clear_cart(user_id)

    try:
        from handlers.cart import notify_low_stock
        if low_stock:
            await notify_low_stock(bot, low_stock)
    except Exception:
        logger.warning("low-stock notice failed", exc_info=True)

    try:
        await _notify_sellers(bot, order_id, items_data, {
            "customer_name": name,
            "phone": phone,
            "address": address,
            "address_note": note,
            "latitude": location[0] if location else None,
            "longitude": location[1] if location else None,
            "total": total,
            "user_id": user_id,
            "username": message.from_user.username,
            "delivery_method": DEFAULT_DELIVERY,
            "payment_method": "cash",
            "status": "pending",
        }, lang)
    except Exception:
        # Buyurtma allaqachon bazada — admin xabari ketmasa ham uni yo'qotmaymiz.
        logger.exception("AI order %s: admin notification failed", order_id)

    logger.info("AI sales created order %s for user %s (payment=%s)", order_id, user_id, payment)
    session["location"] = None   # keyingi buyurtma o'z lokatsiyasini so'rasin

    result = (f"OK: buyurtma #{order_id} qabul qilindi, jami {_fmt(total)} so'm. "
              f"Mijozga raqamni ayt va operator bog'lanishini bildir.")
    if payment == "karta":
        session["awaiting_cheque"] = order_id
        result += (f"\nTO'LOV: mijozga shu kartani ayt — {PAYMENT_CARD_NUMBER} "
                   f"({PAYMENT_RECIPIENT_NAME}), summa {_fmt(total)} so'm, va chek "
                   f"rasmini shu chatga yuborishni so'ra. To'lovni O'ZING tasdiqlama.")
    else:
        result += " To'lov naqd — kuryerga beradi."
    return result


async def _run_tool(bot: Bot, message: Message, name: str, args: dict) -> str:
    user_id = message.from_user.id
    if name == "savatga_qoshish":
        return await _tool_add(user_id, args)
    if name == "savatni_korish":
        return await _tool_cart(user_id)
    if name == "savatdan_ochirish":
        return await _tool_remove(user_id, args)
    if name == "buyurtma_rasmiylashtirish":
        return await _tool_order(bot, message, args)
    return f"Xato: '{name}' degan vosita yo'q."


# ──────────────────────────────── suhbat ────────────────────────────────────

def _prune_sessions() -> None:
    cutoff = time.time() - SESSION_TTL
    for user_id in [u for u, s in _sessions.items() if s["last"] < cutoff]:
        _sessions.pop(user_id, None)


def _session(user_id: int) -> dict:
    _prune_sessions()
    session = _sessions.get(user_id)
    if session is None:
        session = {"messages": [], "last": time.time(), "orders": 0,
                   "location": None, "phone": None, "awaiting_cheque": None}
        _sessions[user_id] = session
    return session


async def _respond(bot: Bot, message: Message, user_text: str) -> str:
    """Bitta mijoz xabari -> bitta javob. Ichida vosita chaqiruvlari tsikli:
    model savatga soladi/buyurtma beradi, natijani o'qiydi va yakuniy matnni
    yozadi. MAX_TURNS — cheksiz tsiklga qarshi to'siq."""
    session = _session(message.from_user.id)
    session["last"] = time.time()
    history = session["messages"]
    history.append({"role": "user", "content": user_text})
    if len(history) > HISTORY_LIMIT:
        del history[: len(history) - HISTORY_LIMIT]

    client = _get_client()
    system = _system_prompt(await _catalog_text())

    reply_text = ""
    for _ in range(MAX_TURNS):
        response = await client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=TOOLS,
            output_config={"effort": EFFORT},
            messages=history,
        )
        history.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "refusal":
            logger.warning("AI sales refusal for user %s", message.from_user.id)
            return ("Kechirasiz, bu savolga bu yerda javob bera olmayman.\n"
                    "Batafsil ma'lumot olish uchun: " + SUPPORT_PHONES)

        reply_text = "\n".join(
            block.text for block in response.content if block.type == "text"
        ).strip()

        if response.stop_reason != "tool_use":
            return reply_text

        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            try:
                output = await _run_tool(bot, message, block.name, dict(block.input))
                is_error = output.startswith("Xato:")
            except Exception:
                logger.exception("AI tool %s failed", block.name)
                output, is_error = "Xato: ichki nosozlik.", True
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
                "is_error": is_error,
            })
        # Hamma natija BITTA user xabarida qaytadi — bo'lib yuborilsa model
        # keyingi safar parallel chaqiruvni tashlab ketadi.
        history.append({"role": "user", "content": results})

    logger.warning("AI sales hit the tool-turn limit for user %s", message.from_user.id)
    return reply_text or ("Bir daqiqa kutib turing.\n"
                          "Batafsil ma'lumot olish uchun: " + SUPPORT_PHONES)


# ──────────────────────────────── handlerlar ────────────────────────────────

@router.message(Command("ai"))
async def cmd_ai_on(message: Message):
    if not _allowed(message.from_user.id):
        return
    if not is_enabled():
        await message.answer("⚠️ ANTHROPIC_API_KEY o'rnatilmagan — AI sotuvchi o'chiq.")
        return
    _sessions.pop(message.from_user.id, None)   # har /ai yangi suhbat
    _session(message.from_user.id)
    if ADMIN_ONLY:
        # Admin sinov rejimi — bu yerda nima ishlayotgani ochiq aytiladi.
        text = ("🤖 <b>AI sotuvchi yoqildi</b> (sinov rejimi).\n\n"
                "Oddiy mijozdek yozing: mahsulot tanlaydi, savatga soladi, "
                "lokatsiya/telefon so'raydi va buyurtmani rasmiylashtiradi.\n\n"
                "O'chirish: /ai_off")
    else:
        # Mijoz ko'radigan matn — kim bilan yozishayotgani haqida ortiqcha gap yo'q.
        text = ("Assalomu alaykum, Keto shopga xush kelibsiz! 🌿\n\n"
                "Nima qidiryapsiz? Yozing — mahsulot tanlashga yordam beraman va "
                "buyurtmangizni rasmiylashtiraman.\n\n"
                "📞 Batafsil ma'lumot uchun: " + SUPPORT_PHONES)
    await message.answer(text, parse_mode="HTML")


@router.message(Command("ai_off"))
async def cmd_ai_off(message: Message):
    if not _allowed(message.from_user.id):
        return
    had = _sessions.pop(message.from_user.id, None) is not None
    await message.answer("🤖 AI sotuvchi o'chirildi." if had else "AI sotuvchi yoqilmagan edi.")


@router.message(Command("ai_holat"))
async def cmd_ai_status(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    _prune_sessions()
    catalog = await _catalog_text() if is_enabled() else ""
    lines = [
        "🤖 <b>AI sotuvchi</b>", "",
        f"Holat: {'✅ yoqilgan' if is_enabled() else '⚠️ kalit yo`q (o`chiq)'}",
        f"Model: <code>{html.escape(MODEL)}</code> (effort: {EFFORT})",
        f"Kirish: {'faqat adminlar' if ADMIN_ONLY else 'hamma mijozlar'}",
        f"Ochiq suhbatlar: {len(_sessions)}",
        f"Guruh rejimi: {('✅ ' + str(len(GROUP_CHATS)) + ' ta guruh') if GROUP_CHATS else '⚪ o`chiq'}"
        f" (mention/reply, {GROUP_COOLDOWN}s tanaffus)",
        f"Katalogda: {len(catalog.splitlines()) if catalog else 0} ta mahsulot",
        "",
        "<i>Mijozlarga ochish uchun Railway'da AI_SALES_ADMIN_ONLY=0 qo'ying.</i>",
        "<i>Guruhda javob berishi uchun AI_GROUP_CHATS=-100... qo'ying. "
        "Guruhda sotuv yo'q — faqat savol-javob, xarid uchun botga yo'naltiradi.</i>",
    ]
    await message.answer("\n".join(lines), parse_mode="HTML")


def _has_session(message: Message) -> bool:
    """FILTR sifatida ishlatiladi, handler ichidagi tekshiruv sifatida emas —
    va bu ataylab. aiogram'da mos kelgan handler `return` qilsa ham xabar
    "ishlangan" hisoblanadi va support_relay ga yetib bormaydi. Ya'ni suhbat
    yoqilmagan odamning savoli jimgina yo'qolardi."""
    user = message.from_user
    return bool(user and user.id in _sessions and is_enabled() and _allowed(user.id))


@router.message(_has_session, F.text & ~F.text.startswith("/"))
async def on_text(message: Message, bot: Bot):
    """Suhbat yoqilgan odamning oddiy matni. Router bot.py da support_relay
    dan OLDIN, qolgan hammasidan KEYIN turadi: menyu tugmalari va FSM oqimlari
    avvalgidek ishlayveradi, faqat hech kim ushlamagan matn AI ga tushadi."""
    await message.bot.send_chat_action(message.chat.id, "typing")
    await _reply(bot, message, message.text)

@router.message(_has_session, F.location)
async def on_location(message: Message, bot: Bot):
    """Mijoz manzilni Telegram lokatsiyasi bilan yubordi. Tugmali checkout
    bilan bir xil ishlov: O'zbekiston chegarasi tekshiriladi va koordinata
    o'qiladigan manzilga aylantiriladi (handlers/cart.py::process_location) —
    kuryer 'Yunusobod, Mustaqillik 12' ni koordinatadan afzal ko'radi."""
    lat = message.location.latitude
    lng = message.location.longitude
    try:
        from handlers.cart import verify_uzbekistan, get_location_address_text
        if not await verify_uzbekistan(lat, lng):
            await message.answer("📍 Bu manzil O'zbekistondan tashqarida ko'rinyapti. "
                                 "Yetkazib berish faqat O'zbekiston ichida.")
            return
        readable = await get_location_address_text(lat, lng)
    except Exception:
        logger.warning("AI location lookup failed", exc_info=True)
        readable = None

    pin = f"📍 {lat:.6f}, {lng:.6f}"
    if readable:
        pin += f" — {readable}"
    _session(message.from_user.id)["location"] = (lat, lng, pin)

    await message.bot.send_chat_action(message.chat.id, "typing")
    note = f"[Mijoz yetkazish lokatsiyasini yubordi: {pin}]"
    await _reply(bot, message, note)


@router.message(_has_session, F.contact)
async def on_contact(message: Message, bot: Bot):
    """Kontakt tugmasi orqali kelgan telefon — qo'lda yozishdan ishonchliroq."""
    phone = (message.contact.phone_number or "").strip()
    if phone and not phone.startswith("+"):
        phone = "+" + phone
    session = _session(message.from_user.id)
    session["phone"] = phone
    await message.bot.send_chat_action(message.chat.id, "typing")
    await _reply(bot, message, f"[Mijoz telefon raqamini yubordi: {phone}]")


@router.message(_has_session, F.photo | F.document)
async def on_cheque(message: Message, bot: Bot):
    """To'lov cheki. AI uni KO'RMAYDI va tasdiqlamaydi — rasm to'g'ridan-to'g'ri
    adminlarga uzatiladi, qaror ularniki. Buyurtma bazada 'cash' bo'lib qoladi,
    ya'ni hech qachon yolg'on 'to'landi' holatiga tushmaydi."""
    session = _session(message.from_user.id)
    order_id = session.get("awaiting_cheque")
    user = message.from_user
    caption = (f"🧾 <b>AI suhbatidan to'lov cheki</b>\n"
               f"👤 {html.escape(user.full_name or '')}"
               + (f" (@{html.escape(user.username)})" if user.username else "")
               + f"\n🆔 <code>{user.id}</code>"
               + (f"\n📦 Buyurtma: <b>#{order_id}</b>" if order_id else
                  "\n⚠️ Buyurtmaga bog'lanmagan"))
    sent = 0
    for admin_id in ADMIN_IDS:
        try:
            await message.forward(admin_id)
            await bot.send_message(admin_id, caption, parse_mode="HTML")
            sent += 1
        except Exception:
            logger.warning("Cheque forward to admin %s failed", admin_id, exc_info=True)

    if not sent:
        await message.answer("Rahmat! Chekni oldim, operatorimiz tez orada bog'lanadi.")
        return
    session["awaiting_cheque"] = None
    await message.answer(
        "✅ Rahmat! Chek qabul qilindi — operatorimiz to'lovni tekshirib tasdiqlaydi."
    )


async def _reply(bot: Bot, message: Message, user_text: str) -> None:
    """Xabarni AI ga uzatib, javobini yozadi — matn, lokatsiya va kontakt
    handlerlari shu bitta yo'ldan yuradi."""
    try:
        reply = await _respond(bot, message, user_text)
    except Exception:
        logger.exception("AI sales turn failed for user %s", message.from_user.id)
        await message.answer("Kechirasiz, kichik nosozlik bo'ldi.\n"
                             "Batafsil ma'lumot olish uchun: " + SUPPORT_PHONES)
        return
    if reply:
        await message.answer(reply)


# ────────────────────────────── guruh rejimi ────────────────────────────────
# Guruhda SOTUV YO'Q (egasining talabi 2026-09-12): AI faqat umumiy savollarga
# javob beradi va suhbatlashadi, xarid qilmoqchi bo'lgan odamni botga
# yo'naltiradi. Shuning uchun bu yerda vositalar umuman berilmaydi — savat ham,
# buyurtma ham yo'q, ya'ni guruhdan turib hech narsa sotib bo'lmaydi.
#
# Har bir xabarga javob bermaydi: faqat botni @mention qilishsa yoki botning
# xabariga reply yozishsa. Aks holda AI guruhni bosib ketadi va har bir xabar
# pul turadi.

GROUP_HISTORY_LIMIT = 16
_group_history: dict[int, list] = {}


def _group_system(catalog: str) -> list[dict]:
    rules = (
        "Sen Ketoshop (@" + BOT_USERNAME + ") do'konining guruhdagi yordamchisisan. "
        "Ketoshop Toshkentda keto va PP mahsulotlari sotadi.\n\n"
        "BU GURUH — SOTUV JOYI EMAS\n"
        "- Guruhda savat ham, buyurtma ham yo'q. Sen hech kimdan ism, telefon yoki "
        "manzil so'ramaysan va buyurtma qabul qilmaysan.\n"
        "- Kimdir sotib olmoqchi bo'lsa yoki narx/buyurtma so'rasa, javobni ber va "
        "botga yo'naltir: 'buyurtma uchun @" + BOT_USERNAME + " ga yozing'.\n"
        "- Karta raqami, to'lov, chek — bular haqida guruhda gaplashma, botga yubor.\n\n"
        "SALOMLASHISH\n"
        "- Kimdir salom bersa: 'Vaalaykum assalom! Assalomu alaykum, Keto shopga "
        "xush kelibsiz!' deb boshla, keyin savoliga javob ber.\n"
        "- Salom bermay savol bersa, salomni qisqa qil yoki umuman tashlab ket — "
        "guruhda har javobda salomlashish g'ashga tegadi.\n\n"
        "SEN KIMSAN\n"
        "- Sen Ketoshop jamoasining yordamchisisan. O'zingni robot, bot yoki "
        "sun'iy intellekt deb tanishtirma. Robotmisan deb so'rashsa: "
        "'Men Ketoshop yordamchisiman' de va xodim bilan bog'lanish uchun "
        "raqamni ber: " + SUPPORT_PHONES + "\n\n"
        "NOQULAY HOLAT\n"
        "- Shikoyat, janjal, buyurtma yoki to'lov muammosi, javobini bilmagan savol "
        "bo'lsa, guruhda muhokama qilma: qisqa uzr so'rab "
        "'Batafsil ma\'lumot olish uchun: " + SUPPORT_PHONES + "' deb yoz va "
        "shaxsiy yozishga taklif qil.\n\n"
        "GAPIRISH USLUBI\n"
        "- Odamdek, muloyim va samimiy yoz. Quruq robot javobi emas.\n"
        "- QISQA: 1-3 jumla. Guruhda uzun matn o'qilmaydi.\n"
        "- Kim qaysi tilda yozsa, o'sha tilda javob ber (o'zbekcha yoki ruscha).\n"
        "- Emoji ni oz ishlat — javobiga bittadan ko'p emas.\n"
        "- Suhbatni davom ettir: oldingi xabarlarni hisobga ol, savol berilsa "
        "javob ber, hazilga hazil bilan javob berishing mumkin.\n\n"
        "NIMA HAQIDA GAPIRASAN\n"
        "- Keto va to'g'ri ovqatlanish: nima mumkin, nima yo'q, un/shakar o'rniga nima, "
        "qanday pishiriladi — qisqa va foydali javob ber.\n"
        "- Mahsulotlar: faqat quyidagi katalogdan gapir. Narxni katalogdan ol, "
        "o'zingdan narx yoki chegirma o'ylab topma.\n"
        "- Bilmagan narsangni bilmayman de va operatorga/botga yo'naltir.\n\n"
        "QAT'IY CHEGARALAR\n"
        "- Tibbiy maslahat berma (dori, davolash, diagnoz, dozalar). Kasallik haqida "
        "so'rashsa: shifokor bilan maslahatlashishni ayt.\n"
        "- Guruhda janjal chiqsa yoki kimdir norozi bo'lsa, tortishma: uzr so'ra va "
        "operatorga yozishni taklif qil.\n"
        "- Siyosat, din va shaxsiy mavzulardan chetlan.\n"
    )
    return [
        {"type": "text", "text": rules, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "KATALOG (id | nomi | narxi | qoldiq):\n" + catalog,
         "cache_control": {"type": "ephemeral"}},
    ]


def _group_trigger(message: Message) -> bool:
    """FILTR: bu guruh xabariga javob beramizmi? Uch shart — guruh ro'yxatda,
    bot chaqirilgan (mention yoki reply) va cooldown o'tgan."""
    if not is_enabled() or not GROUP_CHATS:
        return False
    if message.chat.id not in GROUP_CHATS:
        return False
    text = message.text or ""
    mentioned = ("@" + BOT_USERNAME).lower() in text.lower()
    reply = message.reply_to_message
    replied_to_bot = bool(
        reply and reply.from_user and reply.from_user.is_bot
        and (reply.from_user.username or "").lower() == BOT_USERNAME.lower()
    )
    if not (mentioned or replied_to_bot):
        return False
    return time.time() - _group_last.get(message.chat.id, 0) >= GROUP_COOLDOWN


async def _group_respond(chat_id: int, author: str, text: str) -> str:
    history = _group_history.setdefault(chat_id, [])
    history.append({"role": "user", "content": f"{author}: {text}"})
    if len(history) > GROUP_HISTORY_LIMIT:
        del history[: len(history) - GROUP_HISTORY_LIMIT]

    response = await _get_client().messages.create(
        model=MODEL,
        max_tokens=400,                      # guruh javobi qisqa bo'lishi kerak
        system=_group_system(await _catalog_text()),
        output_config={"effort": EFFORT},
        messages=history,
    )
    if response.stop_reason == "refusal":
        history.pop()
        return ""
    reply = "\n".join(b.text for b in response.content if b.type == "text").strip()
    history.append({"role": "assistant", "content": reply or "…"})
    return reply


@router.message(_group_trigger, F.text)
async def on_group_question(message: Message):
    """Guruhda botga murojaat qilingan xabar. Javob reply bo'lib tushadi, ya'ni
    suhbat ipi ko'rinib turadi va keyingi savolni ham shu ipdan ushlaymiz."""
    _group_last[message.chat.id] = time.time()
    try:
        await message.bot.send_chat_action(message.chat.id, "typing")
        author = message.from_user.first_name or "Mijoz"
        text = (message.text or "").replace("@" + BOT_USERNAME, "").strip()
        reply = await _group_respond(message.chat.id, author, text)
    except Exception:
        logger.exception("AI group turn failed in chat %s", message.chat.id)
        return
    if reply:
        await message.reply(reply)
