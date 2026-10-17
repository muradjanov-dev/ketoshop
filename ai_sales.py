"""
AI sotuvchi — mijoz bilan yozishib, uni buyurtma kartasigacha olib boradi.

Bot tugmalar bilan ishlaydi: katalog -> savat -> manzil -> tasdiq. Kim
tugmalarni bosmay, oddiy odamdek yozsa (meta_leads.py orqali kelgan reklama
mijozlari ko'pincha shunday qiladi), hozirgacha javob admin yozguncha kutardi.
Bu modul o'sha suhbatni modelga topshiradi: mahsulotni tanlaydi, savatga
soladi, yetkazish usuli, raqam va lokatsiyani so'raydi va tugmali checkout ning
tasdiq kartasini ochadi (buyurtma_kartasi). Summa, chegirma, Keto va buyurtmaning
o'zi — handlers/cart.py da: mijoz «✅ Tasdiqlash» ni bosadi yoki 'ha' deb yozadi
(egasi, 2026-10-16: "galyutsinatsiya bo'lyapti ... maksimal sodda qilishimiz kerak").

QAYERDA ISHLAYDI (egasi, 2026-10-12: "kanalga ulangan guruh va botga yozilgan
xabarlarga AI o'zi javob berishi kerak, biz vaqt ajrata olmayapmiz")
  * Botda — hamma mijozga. Mijoz oddiy matn yozsa, support_relay ga emas,
    shu yerga tushadi. Admin /ai_holat dagi tugma bilan bir zumda o'chiradi
    (bazada saqlanadi, server sozlamasi shart emas). Kuryerlarga AI javob
    bermaydi. Adminlar va ichki akkauntlarga — faqat /ai_holat dagi
    "Adminlarga ham javob (sinov)" yoqilganda (hozircha yoqilgan, egasi
    2026-10-13: "testlash uchun"); o'chirilsa admin /ai bilan sinaydi.
  * @ketoshop_uz kanaliga ulangan muhokama guruhida — guruh id si kanalning
    linked_chat_id sidan o'zi topiladi (+ AI_GROUP_CHATS dagi guruhlar).
    Faqat begona odamning SAVOLIGA — guruhda adminlar yozganiga hech qachon
    (egasi, 2026-10-13), sinov tugmasi ham bunga ta'sir qilmaydi. Guruhda SOTUV
    YO'Q: savol-javob va botga yo'naltirish, xolos.

TOKEN TEJASH (egasi: "maksimal token effektiv")
  * Guruhda savolga o'xshamagan xabar modelga umuman bormaydi (looks_like_question).
  * Guruh javobi zanjirsiz — har savol butun guruh tarixini qayta to'lamaydi.
  * Katalogda aniq qoldiq yo'q — prompt boshi o'zgarmay, provayder keshidan
    10% narxda o'qiladi.
  * Ketma-ket xabarlar bitta javobga yig'iladi; yolg'iz "rahmat" ga model
    chaqirilmaydi; mijoz xotirasi suhbatga bir marta beriladi.
  * Model /ai_holat da tanlanadi (arzonroq gpt-5.4-mini va h.k.).

SINOV REJIMI ("darhol test rejimida ishlatib ko'raylik, lekin AI gapirayotgani
bilinmasin")
  * Botdagi har bir suhbat xodimlar guruhining "Mijoz va AI suhbati" mavzusiga
    tushadi (joy — o'sha mavzuda /ai_mavzu): bitta mijoz — bitta xabar, har yangi
    savol-javob tahrirlab qo'shiladi; limit to'lsa yoki 1 soat jimlikdan keyin —
    yangi xabar. Admin javoblari va AI javob bermagan xabarlar ham shu yerda.
    Tugmalar: "↩️ Javob berish" (support_relay oqimi), "⏸ AI to'xtasin",
    "🧠 Xotira". Mavzu belgilanmaguncha nusxa adminlarga boradi.
  * Admin mijozga javob bersa (support_relay yoki buyurtma ekranidan), AI shu
    mijoz uchun HUMAN_PAUSE soat jim turadi — odam bilan AI ustma-ust
    gapirmaydi. Pauza xotirada; bot qayta ishga tushsa tozalanadi.
  * Mijozga ko'rinadigan matnlarda "AI", "bot", 🤖 yo'q. Lekin model mijoz
    chin dildan "robotmisan?" deb so'rasa o'zini odam deb aytmaydi — "Ketoshop
    yordamchisi" ekanini aytib, xodim raqamini beradi. Bu chegara ataylab qoldirilgan.
  * Do'kon nomidan "biz" deb gapiradi: beramiz, qilamiz, aytamiz (egasi, 2026-10-13).

XOTIRA (ai_memory.py) — har bir Telegram ID ning buyurtmalari, qiziqishlari va
mahsulotlar haqidagi fikri suhbat boshida modelga beriladi. Yetkazilgan
mahsulot haqida bir marta fikr so'raladi.

TO'LOV. Kartada naqd yoki karta tanlanadi (Yandex va pochtada faqat karta).
Karta bilan to'lovda tugmali checkout ning o'z yo'li ishlaydi: tasdiqdan keyin
karta raqami chiqadi, buyurtma chek kelgach tuziladi va chek adminlarga boradi.
"To'lov o'tdi" degan qarorni AI hech qachon qabul qilmaydi. 2026-10-16 gacha
AI tuzgan karta buyurtmalari (izohida "To'lov: KARTA") uchun chek AI orqali
qabul qilinadi (_open_order_for_cheque) va "✅ To'lov tasdiqlandi" tugmasi qoladi.

BILIM. Modelga butun katalog (nomi, narxi, qoldig'i, kategoriyasi, mahsulot
oilasi), setlar, oilalarning tavsifi (product_descriptions.py), keto/PP
asoslari, yetkazish va to'lov shartlari, faol aksiya va bot chegirmasi
beriladi. Batafsil tavsif `mahsulot_haqida` vositasida. Narx va jami summani
model o'zi hisoblamaydi — `savatni_korish` checkout bilan bir xil hisobni
(_build_order_summary) qaytaradi.

O'RGANIB BORISH. Model o'zi o'qitilmaydi — buning o'rniga do'kon bilimi
bazada o'sib boradi: AI javobini bilmagan savolni `javobsiz_savol` bilan
yozib qo'yadi, admin /ai_bilim da ko'radi va /ai_orgat bilan javobni
o'rgatadi.

AKSIYA. Faol aksiya katalog bilan birga promptga tushadi, savat vositalari
esa promotions.compute_near_misses bilan "yana 1 ta olsa sovg'a" ni aniq
hisoblab qaytaradi. Qoidasi: bir marta, bosimsiz eslatish.

BUYRUQLAR (adminlar)
  /ai_holat  — holat, sarf va yoqish/o'chirish tugmalari
  /ai_kalit sk-... — OpenAI kalitini serverga kirmasdan berish (xabar o'chiriladi)
  /ai, /ai_off — o'z suhbatingizni yangidan boshlash / o'chirish
  /ai_orgat, /ai_bilim, /ai_unut — do'kon bilimi
  /ai_mijoz <id> — mijoz xotirasi, /ai_mijoz_unut <id> — o'chirish

KUNLIK SARF HISOBOTI — har kuni 23:58 (Toshkent) da barcha adminlarga ovozsiz:
o'sha kungi so'rov, token va $ (so'mda ham), oy boshidan jami. Bot o'sha payt
o'chiq bo'lsa, ertasi kuni kunduzi yuboriladi. /ai_holat dan o'chiriladi.

Env vars
--------
OPENAI_API_KEY        yoki ANTHROPIC_API_KEY — bittasi majburiy, busiz modul o'chiq.
                      /ai_kalit bilan botga berilgan OpenAI kaliti env dan ustun.
AI_PROVIDER           openai | anthropic. Bo'sh = qaysi kalit bor bo'lsa (ai_provider.py).
AI_SALES_MODEL        default: openai -> "gpt-5.4-mini", anthropic -> "claude-opus-5".
                      /ai_holat dagi model tugmasi (bazada) ikkalasidan ustun.
AI_SALES_EFFORT       default "low" — suhbat uchun tez va arzon.
AI_SALES_MAX_TURNS    bitta javobdagi vosita chaqiruvlari chegarasi (default 8).
AI_SALES_DEBOUNCE     ketma-ket xabarlarni bitta javobga yig'ish, soniya (default 2.5).
AI_HUMAN_PAUSE_HOURS  admin javob bergach AI necha soat jim turadi (default 6).
AI_GROUP_CHATS        qo'shimcha guruh id lari (vergul bilan).
AI_CHANNEL_GROUP      "0" — kanal guruhini avtomatik topmaslik.
AI_GROUP_MAX_PER_HOUR bitta guruhda soatiga eng ko'p model chaqiruvi (default 30).
"""
import asyncio
import contextlib
import html
import logging
import os
import re
import time

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, Message, ReplyKeyboardMarkup)
from aiogram.utils.chat_action import ChatActionSender

import ai_memory
import ai_stats
import ai_provider
import database
from config import (ADMIN_IDS, BOT_USERNAME, FREE_DELIVERY_FROM, LOW_STOCK_THRESHOLD,
                    PAYMENT_CARD_NUMBER, PAYMENT_RECIPIENT_NAME, REQUIRED_CHANNEL_ID,
                    SUPPORT_PHONES)

logger = logging.getLogger(__name__)
router = Router()

EFFORT = os.getenv("AI_SALES_EFFORT", "low").strip()
PROVIDER = ai_provider.build(os.getenv("AI_SALES_MODEL", "").strip(), EFFORT)
MODEL = PROVIDER.model if PROVIDER else ""
MAX_TURNS = max(2, int(os.getenv("AI_SALES_MAX_TURNS", "8")))
GROUP_CHATS = {
    int(part) for part in os.getenv("AI_GROUP_CHATS", "").replace(" ", "").split(",")
    if part.lstrip("-").isdigit()
}
CHANNEL_GROUP = os.getenv("AI_CHANNEL_GROUP", "1").strip() != "0"
GROUP_MAX_PER_HOUR = max(1, int(os.getenv("AI_GROUP_MAX_PER_HOUR", "30")))
DEBOUNCE = max(0.0, float(os.getenv("AI_SALES_DEBOUNCE", "2.5")))
HUMAN_PAUSE = max(1, int(float(os.getenv("AI_HUMAN_PAUSE_HOURS", "6")) * 3600))
# Egasi "salom" yozib javob kutdi (2026-09-13): /ai ni bilmagan odam uchun AI
# yo'qdek. Shuning uchun ruxsati bor foydalanuvchining oddiy matni /ai siz ham
# AI ga tushadi. "0" — eski xulq, faqat /ai dan keyin.
AUTOSTART = os.getenv("AI_SALES_AUTOSTART", "1").strip() != "0"

MAX_TOKENS = 800          # javoblar qisqa — bu ham ortig'i bilan yetadi
CATALOG_TTL = 300         # katalog snapshotini 5 daqiqa saqlaymiz
SESSION_TTL = 3 * 3600    # 3 soat jim tursa, suhbat unutiladi (xotira qoladi)
HISTORY_LIMIT = 40        # oxirgi 40 xabar — undan oldingisi kesiladi
GROUP_CONTEXT_TTL = 24 * 3600  # guruhdagi savol botdagi suhbatga shuncha ulanadi
MIRROR_TEXT_MAX = 1500
# Do'kon manzili (egasi, 2026-10-13: "manzil so'ralganda shu linkni bergin
# hammaga" + mo'ljal). Mijoz DO'KON qayerda deb so'raganda — botda ham, guruhda ham.
SHOP_ADDRESS_URL = os.getenv("SHOP_ADDRESS_URL", "https://t.me/ketoshop_uz/1071").strip()
SHOP_LANDMARK = os.getenv("SHOP_LANDMARK", "Toshkent shahri, Ko'kcha masjidi ro'parasi").strip()

# Mijoz tanlaydigan yetkazish -> bazadagi delivery_method. Tugmali checkout
# bilan bir xil to'plam (keyboards.delivery_method_keyboard).
DELIVERY = {"toshkent_kuryer": "self", "olib_ketish": "pickup", "yandex_taxi": "yandex_taxi",
            "bts": "bts", "emu": "emu"}
# Naqd faqat shu ikkisida — kuryerga yoki do'konda qo'lma-qo'l. Qolganida karta oldindan.
CASH_OK = {"self", "pickup"}

# AI sozlamalarini (tugmalar, model, kalit, suhbatlar joyi) faqat do'kon egasi
# o'zgartiradi (egasi, 2026-10-13: "bu tugmalarni faqat men o'zgartira olishim
# kerak"). Boshqa adminlar /ai_holat ni ko'radi, lekin o'zgartira olmaydi.
OWNER_IDS = {
    int(part) for part in os.getenv("AI_OWNER_IDS", "917456291").replace(" ", "").split(",")
    if part.lstrip("-").isdigit()
}
OWNER_DENIED = "🔒 Bu sozlamani faqat do'kon egasi o'zgartira oladi."


def is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS


_catalog_cache: tuple[float, str] | None = None
_sessions: dict[int, dict] = {}
_opted_out: set[int] = set()         # /ai_off bosganlar — avtomatik ochilmaydi
_paused: dict[int, float] = {}       # user_id -> shu vaqtgacha AI jim (admin javob berdi)
_inboxes: dict[tuple, dict] = {}     # ketma-ket xabarlarni yig'ish
_group_context: dict[int, tuple[float, str, str]] = {}   # user_id -> (vaqt, savol, javob)


def is_enabled() -> bool:
    return PROVIDER is not None


def _fmt(n) -> str:
    return f"{int(round(float(n or 0))):,}".replace(",", " ")


def _short(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _t(uz: str, ru: str, lang: str) -> str:
    """Mijozga ketadigan qat'iy matn — uning tilida (uz / uz_cyr / ru)."""
    if lang == "ru":
        return ru
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        return lat_to_cyr(uz)
    return uz


async def _lang(user_id: int) -> str:
    try:
        return await database.get_user_language(user_id) or "uz"
    except Exception:
        return "uz"


_CYR_CHAR = re.compile(r"[\u0400-\u04FF]")
_LAT_CHAR = re.compile(r"[A-Za-z]")
_CYR_RUN = re.compile(r"[\u0400-\u04FF]+")
_LAT_RUN = re.compile(r"[A-Za-z'ʻ’]+")
_WORD = re.compile(r"[\w'ʻ’ʼ`‘]+")
# Kirill matn ichida ham lotincha qoladigan nomlar ("Keto shopга").
_KEEP_LATIN = {"keto", "shop", "ketoshop", "yandex", "taxi", "telegram", "bts", "emu", "uzs"}


def fix_mixed_script(text: str) -> str:
    """Model ba'zan bitta so'z ichida lotin va kirill harflarini aralashtiradi
    ("shahар" — egasi, 2026-10-13). Har bir ARALASH so'z javobning asosiy
    yozuviga keltiriladi; toza so'zlarga, brendlarga tegilmaydi."""
    latin, cyrillic = len(_LAT_CHAR.findall(text or "")), len(_CYR_CHAR.findall(text or ""))
    if not latin or not cyrillic:
        return text
    from translit import cyr_to_lat, lat_to_cyr
    to_latin = latin >= cyrillic

    def fix_word(match):
        word = match.group(0)
        if not (_LAT_CHAR.search(word) and _CYR_CHAR.search(word)):
            return word
        if to_latin:
            return _CYR_RUN.sub(lambda run: cyr_to_lat(run.group(0)), word)
        return _LAT_RUN.sub(lambda run: run.group(0) if run.group(0).lower() in _KEEP_LATIN
                            else lat_to_cyr(run.group(0)), word)

    return _WORD.sub(fix_word, text)


_UZ_CYR_LETTERS = re.compile(r"[ўқғҳЎҚҒҲ]")
_SOM_LATIN = re.compile(r"\bso['ʻ’`‘]?m\b", re.IGNORECASE)
_BUTTON_LINES = re.compile(r"^[ \t•\-]*(?:📍 Lokatsiyani yuborish|📞 Raqamni yuborish|"
                           r"📍 Отправить локацию|📞 Отправить номер)[ \t]*\n?", re.MULTILINE)
_LANDMARK_RE = re.compile(r"Ko[ʻ'’`‘]?kcha|Кўкча|Кукча|Кокча", re.IGNORECASE)


def _script(text: str | None) -> str | None:
    """Mijoz xabari qaysi yozuvda: "lat" / "cyr" / None (harf kam yoki yo'q).
    "[Mijoz lokatsiyasini yubordi ...]" kabi tizim belgilari hisobga olinmaydi."""
    text = re.sub(r"\[[^\]]*\]", " ", text or "")
    latin, cyrillic = len(_LAT_CHAR.findall(text)), len(_CYR_CHAR.findall(text))
    if latin + cyrillic < 3:
        return None
    return "cyr" if cyrillic > latin else "lat"


def polish_reply(text: str, lang: str | None = None, customer_text: str | None = None) -> str:
    """Mijozga ketishdan oldingi oxirgi tekshiruv (jonli sinov, 2026-10-13):
      * aralash lotin/kirill so'zlar — fix_mixed_script;
      * o'zbekcha kirill javobdagi lotin qoldiqlar (mahsulot nomi, "so'm") —
        kirillga; ruscha javobda "so'm" — "сум";
      * pastdagi tugma nomlari matnda alohida qator bo'lib takrorlanmasin;
      * do'kon mo'ljali aytilib, havola unutilgan bo'lsa — havola qo'shiladi."""
    text = fix_mixed_script(text or "")
    latin, cyrillic = len(_LAT_CHAR.findall(text)), len(_CYR_CHAR.findall(text))
    letters = latin + cyrillic
    customer = _script(customer_text)
    uzbek_cyrillic = cyrillic and cyrillic >= 0.4 * letters and (
        _UZ_CYR_LETTERS.search(text) or (lang == "uz_cyr" and cyrillic >= latin))
    if customer == "lat" and cyrillic:
        # Mijoz lotinda yozdi: model kirillda javob bergan yoki lotin javob ichida
        # kirill bo'lak qolgan ("Саватга қўшамизми?") — hammasi lotinga.
        from translit import cyr_to_lat
        text = _CYR_RUN.sub(lambda run: cyr_to_lat(run.group(0)), text)
    elif (customer == "cyr" and _UZ_CYR_LETTERS.search(customer_text or "")
          and latin > cyrillic):
        # Mijoz o'zbekcha kirillda yozdi, model lotinda javob berdi — kirillga.
        from translit import lat_to_cyr
        text = lat_to_cyr(text)
    elif uzbek_cyrillic:
        from translit import lat_to_cyr
        text = lat_to_cyr(text)
    elif cyrillic > latin:
        text = _SOM_LATIN.sub("сум", text)
    text = _BUTTON_LINES.sub("", text)
    if SHOP_ADDRESS_URL and SHOP_ADDRESS_URL not in text and _LANDMARK_RE.search(text):
        text = text.rstrip() + f"\n\n📍 {SHOP_ADDRESS_URL}"
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ─────────────────────── ruscha yozganga — ruscha ────────────────────────
# Modellarni solishtirish (2026-10-16): gpt-5.4-mini ruscha "сколько стоит
# миндальная мука?" ga o'zbekcha javob berdi; promptdagi qoida yetmadi. Mijoz
# ruscha yozsa-yu, javob o'zbekcha chiqsa — bir marta ruscha qayta so'raladi,
# qolgan o'zbekcha qator ("Yana nima olamiz? 😊") olib tashlanadi.

_RU_WORDS = {
    "и", "в", "на", "с", "для", "не", "что", "как", "это", "вы", "вам", "вас", "мы", "нам", "ваш",
    "пожалуйста", "спасибо", "да", "нет", "есть", "можно", "будет", "если", "или", "по", "от", "до",
    "при", "уже", "ещё", "еще", "тоже", "также", "нужна", "нужно", "нужен", "сколько", "стоит",
    "здравствуйте", "привет", "доставка", "доставку", "доставим", "заказ", "заказа", "корзину",
    "сум", "кнопку", "отправьте", "номер", "адрес", "хорошо", "конечно", "больше", "ничего",
    "хочу", "хотел", "хотела", "купить", "где", "когда", "какой", "какая", "мне", "меня",
    "наличными", "картой", "курьером", "оформить", "подойдёт", "подойдет", "добавим",
    "про", "напиши", "напишите", "помогите", "помоги", "расскажи", "расскажите", "сделай",
    "решить", "реши", "скажите", "подскажите", "почему", "зачем",
}
_UZ_CYR_WORDS = {
    "салом", "ассалому", "алайкум", "бор", "борми", "йук", "йўқ", "керак", "канча", "қанча",
    "нархи", "нарх", "ха", "ҳа", "раҳмат", "рахмат", "нима", "кандай", "қандай", "учун", "билан",
    "ва", "ёки", "мумкинми", "етказиб", "олиб", "беринг", "яхши", "майли", "хоп", "хўп", "менга",
    "сизларда", "сизда", "борми", "олмоқчиман", "олмокчиман", "буюртма",
}
_UZ_REPLY_LATIN = {
    "va", "bilan", "uchun", "ham", "yoki", "bor", "kerak", "qanday", "nima", "yana", "beramiz",
    "qilamiz", "yetkazamiz", "yetkazib", "yetkazish", "olasiz", "olamiz", "yuboring", "iltimos",
    "rahmat", "marhamat", "albatta", "savatga", "buyurtma", "buyurtmani", "buyurtmangizni",
    "tugma", "tugmani", "tugmalar", "pastdagi", "raqamingiz", "raqamingizni", "lokatsiya",
    "lokatsiyani", "lokatsiyangizni", "manzil", "sizga", "bo'lsa", "bo'ladi", "mumkin", "xo'p",
    "mayli", "to'g'rimi", "yozing", "qaysi", "usul", "qulay", "bepul", "ichida", "soat", "kuryer",
    "do'kondan", "ketish", "tushundik", "oldik", "qo'shildi", "qo'shamizmi", "keldi",
}


def _words(text: str) -> list[str]:
    return re.findall(r"[\w']+", _same_apostrophes(re.sub(r"\[[^\]]*\]", " ", text or "")).lower())


def _uz_reply_words() -> set[str]:
    global _UZ_REPLY_ALL
    if _UZ_REPLY_ALL is None:
        from translit import lat_to_cyr
        _UZ_REPLY_ALL = _UZ_REPLY_LATIN | {lat_to_cyr(w).lower() for w in _UZ_REPLY_LATIN}
    return _UZ_REPLY_ALL


_UZ_REPLY_ALL: set[str] | None = None


def customer_language(text: str) -> str | None:
    """Mijoz xabari tili: 'ru', 'uz_cyr', 'lat' (o'zbekcha yoki inglizcha lotin)
    yoki None — aniqlab bo'lmadi ("кв 5", tizim belgisi)."""
    clean = re.sub(r"\[[^\]]*\]", " ", text or "")
    latin, cyrillic = len(_LAT_CHAR.findall(clean)), len(_CYR_CHAR.findall(clean))
    if latin + cyrillic < 2:
        return None
    if cyrillic <= latin:
        return "lat"
    if _UZ_CYR_LETTERS.search(clean):
        return "uz_cyr"
    words = _words(clean)
    ru = sum(w in _RU_WORDS for w in words) + 2 * bool(re.search("[ыщ]", clean.lower()))
    uz = sum(w in _UZ_CYR_WORDS for w in words)
    if ru > uz:
        return "ru"
    if uz > ru:
        return "uz_cyr"
    return None


def uzbek_reply(reply: str) -> bool:
    """Javob asosan o'zbekcha (lotin yoki kirill) — ruscha yozgan mijozga emas.
    O'zbekcha belgi so'zlardan boshqa har bir kirill so'z ruscha hisoblanadi."""
    uz_words = _uz_reply_words() | _UZ_CYR_WORDS
    words = _words(reply)
    uz = sum(w in uz_words for w in words)
    ru = sum(1 for w in words if len(w) > 1 and _CYR_CHAR.search(w) and w not in uz_words)
    return uz >= 2 and uz > ru


def drop_uzbek_lines(reply: str) -> str:
    """Ruscha javobda qolgan o'zbekcha lotin qatorlar ("Yana nima olamiz? 😊")
    olib tashlanadi; kirill harfi bor qator (mahsulot nomi + "сум") qoladi."""
    kept = []
    for line in (reply or "").split("\n"):
        words = _words(line)
        if (not _CYR_CHAR.search(line) and any(w in _UZ_REPLY_LATIN for w in words)
                and not any(w in _RU_WORDS for w in words)):
            continue
        kept.append(line)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    return text or (reply or "").strip()


RU_FIX = ("[TIZIM: mijoz RUSCHA yozyapti — oxirgi javobingni to'liq rus tilida qayta yoz: mahsulot "
          "nomlari ham ruscha (katalogda 'ru:' nomi bo'lsa — o'sha), narxlar 'сум'. Mazmunni "
          "o'zgartirma va vosita chaqirma.]")


_EMOJI_OR_END = r"(?=\s*(?:[!.?,;:…)]|[\U0001F300-\U0001FAFF\u2600-\u27BF]|$))"
_HONORIFIC = r"(?:hurmatli|qadrli|aziz|азиз|ҳурматли|қадрли|уважаемый|уважаемая|dear)"
_NAME_GIVEN = re.compile(r"\b(?:ismim|ism|исмим|исм|имя|меня зовут|my name is)\s*[:\-]?\s*"
                         r"([A-ZА-ЯЎҚҒҲ][\w'ʻ’]{2,})", re.IGNORECASE)


_THANKS_LAT = re.compile(r"(^|[.!?]\s+|\n)(katta\s+)?(?:rahmat|raxmat)\b(?!\s+sizga)",
                         re.IGNORECASE | re.MULTILINE)
_THANKS_CYR = re.compile(r"(^|[.!?]\s+|\n)(катта\s+)?(?:раҳмат|рахмат)\b(?!\s+сизга)",
                         re.IGNORECASE | re.MULTILINE)


def thank_politely(text: str) -> str:
    """Gap boshidagi yolg'iz "Rahmat" / "Katta rahmat" → "Sizga rahmat" /
    "Sizga katta rahmat" (kirillda ham). "Xaridingiz uchun katta rahmat" kabi
    to'liq gapga tegilmaydi — u gap boshida emas."""
    text = _THANKS_LAT.sub(lambda m: m.group(1) + "Sizga " + ("katta " if m.group(2) else "") + "rahmat",
                           text or "")
    return _THANKS_CYR.sub(lambda m: m.group(1) + "Сизга " + ("катта " if m.group(2) else "") + "раҳмат",
                           text)


def customer_names(user, text: str | None = None, extra=()) -> set[str]:
    """Mijozning ism(lar)i: Telegram ismi, yozishmada aytgani ("Ism Bobur") va
    buyurtmaga yozilgani. 3 harfdan qisqasi olinmaydi."""
    names = set(extra or ())
    for part in (getattr(user, "first_name", None), getattr(user, "full_name", None)):
        names.update((part or "").split())
    for match in _NAME_GIVEN.finditer(text or ""):
        names.add(match.group(1))
    return {n.strip(",.!?") for n in names if len(n.strip(",.!?")) >= 3}


def strip_name_address(text: str, names) -> str:
    """Egasi, 2026-10-14: "mijozni ismi bilan murojaat qilma". Model baribir
    yozsa: "Rahmat, Bobur 😊" → "Rahmat 😊", "Bobur, buyurtmangiz…" →
    "Buyurtmangiz…", "Hurmatli Bobur" → "Hurmatli mijoz". "Ism: Bobur" kabi
    ma'lumot qatoriga tegilmaydi."""
    for name in sorted(names or (), key=len, reverse=True):
        # "Bobur aka" / "Dilnoza opa" ham — egasi: "ism ishlatma" (aka/opa ham emas).
        n = re.escape(name) + r"(?:\s+(?:aka|opa|ака|опа))?"
        text = re.sub(rf",\s*(?:{_HONORIFIC}\s+)?{n}{_EMOJI_OR_END}", "", text, flags=re.IGNORECASE)
        text = re.sub(rf"(^|[.!?]\s+|[\U0001F300-\U0001FAFF\u2600-\u27BF]\s+)"
                      rf"(?:{_HONORIFIC}\s+)?{n},\s*(\w)",
                      lambda m: m.group(1) + m.group(2).upper(), text,
                      flags=re.IGNORECASE | re.MULTILINE)
        text = re.sub(rf"\b({_HONORIFIC})\s+{n}\b", lambda m: m.group(1) + " mijoz", text,
                      flags=re.IGNORECASE)
    return text


def _strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


# ─────────────────────────────── sozlamalar ─────────────────────────────────
# Uchta kalit bazada (ai_settings) — admin /ai_holat dagi tugma bilan bir zumda
# o'zgartiradi, deploy ham, server sozlamasi ham kerak emas. Default — yoqilgan
# (egasi: "darhol test rejimida ishlatib ko'raylik").

# "admins" — sinov uchun adminlarga ham javob (egasi, 2026-10-13: "hozircha
# adminlarga ham javob bersin, testlash uchun"). Sinov tugagach /ai_holat dan
# o'chiriladi — shunda adminlarga yana faqat /ai bilan.
_SETTING_DEFAULTS = {"customers": True, "group": True, "mirror": True, "report": True,
                     "admins": True}
_SETTING_LABELS = {
    "customers": "Botda mijozlarga javob",
    "group": "Kanal guruhida javob",
    "mirror": "Suhbatlar guruh mavzusiga (/ai_mavzu)",
    "report": "Kunlik sarf hisoboti (23:58)",
    "admins": "Adminlarga ham javob (sinov, faqat botda)",
}
SETTINGS_TTL = 60
_settings: dict = {"at": float("-inf"), "values": {}, "staff": set()}
_settings_table_ready = False


async def _ensure_settings(conn) -> None:
    global _settings_table_ready
    if _settings_table_ready:
        return
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            changed_by BIGINT,
            changed_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
        )
    """)
    _settings_table_ready = True


async def _load_settings() -> dict:
    """Sozlamalar + kuryerlar ro'yxati, 60 soniya keshlanadi. Baza javob
    bermasa — oxirgi ma'lum holat (yoki default), suhbat to'xtamaydi."""
    now = time.monotonic()
    if now - _settings["at"] < SETTINGS_TTL:
        return _settings["values"]
    _settings["at"] = now
    try:
        async with database.pool.acquire() as conn:
            await _ensure_settings(conn)
            rows = await conn.fetch("SELECT key, value FROM ai_settings")
        _settings["values"] = {r["key"]: r["value"] for r in rows}
    except Exception:
        logger.warning("AI settings could not be loaded", exc_info=True)
    _apply_key(_settings["values"].get(KEY_SETTING))
    _apply_model(_settings["values"].get("model"))
    try:
        _settings["staff"] = set(await database.get_courier_ids())
    except Exception:
        logger.warning("Courier list could not be loaded for AI", exc_info=True)
    return _settings["values"]


async def setting(key: str) -> bool:
    values = await _load_settings()
    if key not in values:
        return _SETTING_DEFAULTS[key]
    return values[key] == "1"


async def set_setting(key: str, value: str, by: int | None = None) -> None:
    async with database.pool.acquire() as conn:
        await _ensure_settings(conn)
        await conn.execute(
            """INSERT INTO ai_settings (key, value, changed_by, changed_at)
               VALUES ($1, $2, $3, NOW() AT TIME ZONE 'UTC')
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value,
                   changed_by = EXCLUDED.changed_by, changed_at = EXCLUDED.changed_at""",
            key, value, by)
    _settings["values"][key] = value
    # Qiymat yozilmaydi — kalit sozlamasi ham shu yo'ldan o'tadi.
    logger.info("AI setting %s changed by %s", key, by)


async def _delete_setting(key: str) -> None:
    async with database.pool.acquire() as conn:
        await _ensure_settings(conn)
        await conn.execute("DELETE FROM ai_settings WHERE key = $1", key)
    _settings["values"].pop(key, None)


async def _ready() -> bool:
    """Filtrlar boshida: sozlamalar (va /ai_kalit bilan berilgan kalit)
    yuklangan bo'lsin, keyin AI yoqilganmi. 60 soniya keshlanadi."""
    await _load_settings()
    return is_enabled()


# ─────────────────────── OpenAI kaliti — bot orqali ───────────────────────
# Egasi serverga kira olmaydi, env ni faqat dasturchi o'zgartiradi (meta_ads
# /reklama_token bilan bir xil muammo va yechim). /ai_kalit sk-... — bot kalitni
# OpenAI da tekshiradi (bepul models.retrieve), bazaga saqlaydi va kalitli
# xabarni o'chiradi. Bot orqali berilgani env dagidan ustun — egasining eng
# so'nggi qarori. Kalit hech qachon jurnalga yozilmaydi, faqat oxirgi 4 belgisi
# ko'rsatiladi.

KEY_SETTING = "openai_key"
_KEY_OFF_WORDS = {"off", "o'chir", "ochir", "delete", "yoq", "0"}
_key_source = {"from_bot": False}


def _openai_model() -> str:
    """Kalit almashganda qaysi model: hozirgi OpenAI modeli, bo'lmasa env
    yoki default (gpt-5.4-mini)."""
    if PROVIDER is not None and PROVIDER.name == "openai":
        return PROVIDER.model
    env = os.getenv("AI_SALES_MODEL", "").strip()
    return env if env.startswith("gpt") else ai_provider.DEFAULT_MODELS["openai"]


def _apply_key(key: str | None) -> None:
    global PROVIDER, MODEL
    key = (key or "").strip()
    if not key:
        return
    _key_source["from_bot"] = True
    if PROVIDER is not None and PROVIDER.name == "openai" and getattr(PROVIDER, "api_key", "") == key:
        return
    PROVIDER = ai_provider.OpenAIProvider(key, _openai_model(), EFFORT)
    MODEL = PROVIDER.model
    for session in _sessions.values():
        ai_provider.reset(session.setdefault("ai", {}))
    logger.info("AI: OpenAI key from the bot settings applied (…%s)", key[-4:])


def _drop_bot_key() -> None:
    """Bot orqali berilgan kalit o'chirildi — serverdagi env ga qaytamiz."""
    global PROVIDER, MODEL
    _key_source["from_bot"] = False
    PROVIDER = ai_provider.build(os.getenv("AI_SALES_MODEL", "").strip(), EFFORT)
    MODEL = PROVIDER.model if PROVIDER else ""
    for session in _sessions.values():
        ai_provider.reset(session.setdefault("ai", {}))


def _key_status() -> str:
    if PROVIDER is None:
        return "yo'q — /ai_kalit bilan bering"
    tail = html.escape((getattr(PROVIDER, "api_key", "") or "")[-4:])
    where = "bot orqali berilgan" if _key_source["from_bot"] else "serverdagi env"
    return f"{where} (…{tail})"


async def _verify_key(key: str, model: str) -> str | None:
    """None — kalit ishlaydi va model ochiq; aks holda qisqa xato matni.
    models.retrieve token sarflamaydi."""
    try:
        from openai import AsyncOpenAI
        await AsyncOpenAI(api_key=key, timeout=20).models.retrieve(model)
        return None
    except Exception as exc:
        return f"{type(exc).__name__}: {str(exc)[:200]}"


def model_options() -> list[str]:
    """Shu provayderning narxi ma'lum modellari (ai_provider.PRICES) — /ai_holat
    da tugma bo'lib chiqadi, egasi dasturchisiz almashtiradi."""
    if not PROVIDER:
        return []
    prefix = "gpt" if PROVIDER.name == "openai" else "claude"
    return [m for m in ai_provider.PRICES if m.startswith(prefix)]


def _apply_model(name: str | None) -> None:
    """Bazadagi tanlangan modelni ishga tushiradi. Ochiq suhbatlarning
    provayder zanjiri tozalanadi (boshqa model zanjiri), lekin sessiya —
    lokatsiya, telefon, chek kutish — qoladi; savat bazada."""
    global MODEL
    if not PROVIDER or not name or name == PROVIDER.model or name not in model_options():
        return
    logger.info("AI model %s -> %s", PROVIDER.model, name)
    PROVIDER.model = name
    MODEL = name
    for session in _sessions.values():
        ai_provider.reset(session.setdefault("ai", {}))


async def _allowed(user_id: int) -> bool:
    """Botda AI kimga javob beradi. Adminlar — har doim (sinab ko'rish uchun).
    Kuryerlar va do'konning ichki akkauntlari — hech qachon: ular ish yuzasidan
    yozadi va xabari avvalgidek adminlarga borishi kerak."""
    if user_id in ADMIN_IDS:
        return True
    if user_id in database.LEADERBOARD_EXCLUDED_USER_IDS:
        return False
    if not await setting("customers"):
        return False
    return user_id not in _settings["staff"]


# ─────────────────────────── odam javob berganda ────────────────────────────

def pause_for_human(user_id: int, seconds: int | None = None) -> None:
    """Admin mijozga o'zi javob berdi yoki "⏸" ni bosdi — AI shu mijoz uchun
    jim turadi, xabarlari support_relay orqali adminlarga boradi. Suhbat
    tarixi tashlanadi: unda adminning gapi yo'q, AI qaytganda xotira va
    buyurtmalardan davom etadi."""
    _paused[user_id] = time.time() + (HUMAN_PAUSE if seconds is None else seconds)
    _sessions.pop(user_id, None)


def resume(user_id: int) -> None:
    _paused.pop(user_id, None)


def _is_paused(user_id: int) -> bool:
    until = _paused.get(user_id)
    if until is None:
        return False
    if until > time.time():
        return True
    _paused.pop(user_id, None)
    return False


# ─────────────────────────────── katalog ────────────────────────────────────

async def _catalog_text() -> str:
    """Butun faol katalog: oilalar tavsifi, setlar, keyin kategoriya bo'yicha
    mahsulotlar (id, nomi, narxi, oilasi). Shu matn tizim promptida turadi va
    model faqat shundan gapiradi — "yo'q narsani bor" deb aytish ehtimoli
    yo'qoladi.

    TOKEN TEJASH: provayder kesh faqat o'zgarmagan BOSHLANG'ICH qismni arzon
    (10%) hisoblaydi. Shuning uchun aniq qoldiq soni bu yerda YO'Q — u har
    buyurtmada o'zgarib, keshni buzardi. "kam qoldi" belgisi yetadi, aniq
    qoldiqni savatga_qoshish o'zi tekshiradi. Eng kam o'zgaradigan bloklar
    (oilalar, setlar) oldinda."""
    global _catalog_cache
    now = time.time()
    if _catalog_cache and now - _catalog_cache[0] < CATALOG_TTL:
        return _catalog_cache[1]

    products, _ = await database.get_all_products_paginated(page=0, per_page=500)
    try:
        categories = {c["key"]: c["name_uz"] for c in await database.get_categories(active_only=False)}
    except Exception:
        categories = {}
    try:
        import product_descriptions
    except Exception:
        product_descriptions = None

    by_category: dict[str, list[str]] = {}
    families: dict[str, str] = {}
    for p in products:
        stock = float(p.get("quantity") or 0)
        if stock <= 0:
            continue  # tugagan mahsulotni ko'rsatmaymiz — va'da berib bo'lmaydi
        discount = database.active_discount(p.get("discount_percent"), p.get("discount_until"))
        price = database.effective_price(float(p["price"]), discount, p.get("discount_until"))
        badge = f" (asl narxi {_fmt(p['price'])}, -{discount}%)" if discount else ""
        low = " | kam qoldi" if stock < LOW_STOCK_THRESHOLD else ""
        family = ""
        if product_descriptions is not None:
            try:
                key = product_descriptions.family_key(p["name"])
                entry = product_descriptions.FAMILY.get(key) if key else None
                if entry:
                    family = f" | [{key}]"
                    if key not in families:
                        uz = entry["uz"]
                        families[key] = (f"[{key}] {uz['intro']} Foydasi: {'; '.join(uz['benefits'])}. "
                                         f"Ishlatilishi: {uz['use']} Saqlash: {uz['keep']}")
            except Exception:
                logger.debug("family lookup failed for %s", p.get("name"), exc_info=True)
        category = categories.get(p.get("category")) or p.get("category") or "Boshqa"
        # Ruscha yozgan mijozga mahsulot nomi ham ruscha bo'lsin — admin kiritgan
        # kirillcha nom bo'lsa (lotincha "ru" nomlar hisobga olinmaydi).
        name_ru = (p.get("name_ru") or "").strip()
        ru = f" (ru: {name_ru})" if name_ru and name_ru != p["name"] and _CYR_CHAR.search(name_ru) else ""
        by_category.setdefault(category, []).append(
            f"{p['id']} | {p['name']}{ru} | {_fmt(price)} so'm / {p.get('unit') or 'dona'}{badge}"
            f"{family}{low}"
        )

    blocks = []
    if families:
        blocks.append("MAHSULOT OILALARI (katalogdagi [oila] belgisi shu tavsifga ishora qiladi):\n"
                      + "\n".join(families[k] for k in sorted(families)))

    try:
        sets = await database.get_active_sets_for_catalog()
    except Exception:
        logger.warning("Sets could not be loaded for AI", exc_info=True)
        sets = []
    if sets:
        set_lines = []
        for s in sets:
            items = ", ".join(f"{i['name']} ×{float(i['quantity']):g}" for i in s.get("items") or [])
            separate = float(s.get("original_total") or 0)
            extra = f" (alohida olsa {_fmt(separate)} so'm)" if separate > float(s["set_price"]) else ""
            set_lines.append(f"S{s['id']} | {s['name']} | {_fmt(s['set_price'])} so'm{extra} | tarkibi: {items}")
        blocks.append("SETLAR (set_qoshish bilan, S harfidan keyingi raqam):\n" + "\n".join(set_lines))
    products_text = "\n".join(f"# {cat}\n" + "\n".join(lines) for cat, lines in by_category.items())
    blocks.append("MAHSULOTLAR (id | nomi | narxi | [oila]); ro'yxatda faqat bor mahsulotlar:\n"
                  + (products_text or "(katalog bo'sh)"))
    text = "\n\n".join(blocks)
    _catalog_cache = (now, text)
    return text


async def _step(state: dict, rules: str, catalog: str, tools, **kwargs):
    """PROVIDER.step + sarfni bazaga yozish. Hisob yozilmay qolsa ham suhbat
    to'xtamasin — xarajat statistikasi javobdan muhim emas."""
    turn = await PROVIDER.step(state, rules, catalog, tools, **kwargs)
    usage = getattr(turn, "usage", None)
    if usage and (usage.input or usage.output):
        try:
            cost = ai_provider.estimate_cost(PROVIDER.model, usage.input, usage.cached, usage.output)
            await database.record_ai_usage(PROVIDER.model, PROVIDER.name, usage.input,
                                           usage.cached, usage.output, cost)
        except Exception:
            logger.warning("AI usage could not be recorded", exc_info=True)
    return turn


_knowledge_cache: tuple[float, str] | None = None


def invalidate_knowledge() -> None:
    global _knowledge_cache
    _knowledge_cache = None


async def _knowledge_text() -> str:
    """Admin o'rgatgan faktlar. Katalog bilan bir xil 5 daqiqalik kesh, lekin
    /ai_orgat va /ai_unut darrov tozalaydi — o'rgatilgan narsa keyingi
    xabardan ishlasin."""
    global _knowledge_cache
    now = time.time()
    if _knowledge_cache and now - _knowledge_cache[0] < CATALOG_TTL:
        return _knowledge_cache[1]
    try:
        facts = await database.list_ai_facts()
    except Exception:
        logger.warning("AI knowledge could not be loaded", exc_info=True)
        facts = []
    text = "\n".join(f"- {f['text']}" for f in facts)
    _knowledge_cache = (now, text)
    return text


async def _promo_text() -> str:
    """Faol aksiya — nomi, necha kun qolgani va qoidalari. Aksiya yo'q bo'lsa
    bo'sh: model yo'q aksiyani eslatmasligi uchun blok umuman chiqmaydi."""
    try:
        import promotions
        promo = await promotions.get_active()
        if not promo:
            return ""
        lines = [f"Nomi: {promotions.promo_name(promo, 'uz')}",
                 ("Muddati: o'chirilguncha" if not promo.get("ends_at")
                  else f"Tugashiga: {promotions.days_left(promo)} kun")]
        conditions = (promotions.promo_conditions(promo, "uz") or "").strip()
        if conditions:
            lines.append(f"Shartlari: {conditions}")
        for rule in promo.get("bonuses") or []:
            lines.append("- " + promotions.rule_line(rule, "uz"))
        return "\n".join(lines)
    except Exception:
        logger.warning("Active promotion could not be loaded for AI", exc_info=True)
        return ""


async def _bot_discount_text() -> str:
    """Bot orqali o'zi buyurtma berganga chegirma (bot_discount.py). Faqat
    faol bo'lsa chiqadi; aniq narxni baribir savatni_korish beradi."""
    try:
        import bot_discount
        if not await bot_discount.is_active():
            return ""
        return (f"BOT CHEGIRMASI: botda o'zi buyurtma bergan mijozga barcha mahsulotlar "
                f"-{bot_discount.PERCENT}% ({bot_discount.end_date_text('uz')} soat 23:59 gacha). "
                "Ba'zi mahsulotda chegirma kichikroq bo'lishi mumkin. Katalogdagi narxlar "
                "chegirmasiz — aniq narx va jami summani faqat savatni_korish dan ol.")
    except Exception:
        logger.warning("Bot discount state could not be loaded for AI", exc_info=True)
        return ""


async def _dynamic_block(catalog: str) -> str:
    """Promptning o'zgaruvchan qismi: katalog, faol aksiya, bot chegirmasi,
    o'rgatilgan bilimlar. Qoidalar (o'zgarmas) alohida — kesh shunday yaxshi
    ishlaydi."""
    parts = ["KATALOG\n" + catalog]
    promo = await _promo_text()
    parts.append("FAOL AKSIYA:\n" + promo if promo else "FAOL AKSIYA: hozir yo'q.")
    discount = await _bot_discount_text()
    if discount:
        parts.append(discount)
    knowledge = await _knowledge_text()
    if knowledge:
        parts.append("DO'KON BILIMLARI (adminlar o'rgatgan — shularga tayan, "
                     "katalogdan keyin eng ishonchli manba):\n" + knowledge)
    return "\n\n".join(parts)


# ──────────────────────────────── bilim ─────────────────────────────────────

def _keto_knowledge() -> str:
    """Keto va PP asoslari — model bularni umuman biladi, bu blok do'kon
    ohangini va ehtiyot chegaralarini belgilaydi."""
    return (
        "KETO VA PP BILIMLARI\n"
        "- Keto: uglevod keskin kamaytiriladi (odatda kuniga 20-50 g sof uglevod), energiya "
        "asosan yog'dan olinadi, oqsil o'rtacha. Sof uglevod = umumiy uglevod - tola. "
        "Eritritol sof uglevodga qo'shilmaydi.\n"
        "- Keto'da yeyiladi: go'sht, baliq, tuxum, pishloq, qaymoq, sariyog', ghee, zaytun va kokos "
        "yog'i, yong'oq va urug'lar, avokado, kraxmalsiz sabzavotlar (karam, brokkoli, bodring, "
        "qovoqcha, ko'katlar), rezavorlar oz miqdorda.\n"
        "- Keto'da yeyilmaydi: shakar, asal, bug'doy uni va non, guruch, makaron, kartoshka, "
        "shirin mevalar, shirin ichimliklar, sharbatlar.\n"
        "- Boshida 'keto gripp' (holsizlik, bosh og'rig'i) bo'lishi mumkin — ko'proq suv, tuz va "
        "elektrolitlar yordam beradi; odatda 1-2 haftada o'tadi.\n"
        "- Shirinlatgichlar: eritritol — kaloriyasi va glikemik indeksi deyarli 0, shakardan "
        "taxminan 30% kam shirin; pishiriqda shakar o'rniga 1:1 yoki biroz ko'proq qo'yiladi, "
        "juda ko'p yeyilsa qorin dam bo'lishi mumkin. Steviya shakardan yuzlab marta shirin — "
        "juda oz miqdorda ishlatiladi.\n"
        "- Keto unlar: bodom uni — asosiy keto un, pishiriqda bug'doy unini to'liq almashtira "
        "oladi. Kokos uni suyuqlikni juda ko'p shimadi — bodom unining 1/4-1/3 qismi yetadi, "
        "tuxum va suyuqlik ko'proq kerak. Zig'ir uni — tolaga boy. Psillium — bog'lovchi, "
        "glyutensiz xamirni elastik qiladi.\n"
        "- PP (to'g'ri ovqatlanish): har ovqatda oqsil + sabzavot + foydali yog'; oq shakar va oq "
        "unni kamaytirish; to'liq don, tola, yetarli suv, muntazam ovqatlanish. PP keto'dan "
        "yumshoqroq: don va meva mumkin.\n"
        "- Ozish uchun asosiy narsa — kaloriya defitsiti; keto ishtahani kamaytirishga yordam "
        "berishi mumkin. 'N kunda N kg' kabi va'da berma.\n"
        "- EHTIYOT: homiladorlik va emizish, qandli diabet (ayniqsa dori yoki insulin ichsa), "
        "buyrak, jigar, o't pufagi kasalliklari va bolalar — keto'ni shifokor bilan kelishib "
        "boshlash kerakligini ayt. Mahsulot tavsiya qilsa bo'ladi (masalan shakar o'rniga "
        "eritritol), lekin davolash, dori yoki doza haqida gapirma.\n"
        "- Kaloriya, uglevod yoki tarkib raqamlarini faqat mahsulot_haqida qaytargan "
        "ma'lumotda bo'lsa ayt; bo'lmasa o'ylab topma.\n"
    )


def _shop_knowledge() -> str:
    """Yetkazish va to'lov shartlari — checkout bilan bir xil manbadan
    (config.FREE_DELIVERY_FROM, handlers/cart.SELF_DELIVERY_FEE)."""
    from handlers.cart import SELF_DELIVERY_FEE
    return (
        "YETKAZISH VA TO'LOV (do'kon qoidalari — boshqacha va'da berma)\n"
        f"- Toshkent bo'ylab Ketoshop kuryeri: {_fmt(SELF_DELIVERY_FEE)} so'm; mahsulotlar "
        f"{_fmt(FREE_DELIVERY_FROM)} so'mdan oshsa — bepul. 24 soat ichida yetkaziladi. "
        "To'lov naqd (kuryerga) yoki karta orqali oldindan.\n"
        "- 'QACHON YETKAZASIZLAR?' deb so'rashsa (egasi, 2026-10-13): zarur va shoshilinch "
        "buyurtmani Yandex Taxi orqali tez yetkazib beramiz; juda shoshilinch bo'lmasa — 1 kun "
        "ichida yetkazib beramiz. Shu ikki variantni ayt va qaysi biri qulayligini so'ra.\n"
        "- Toshkentda Yandex Taxi bilan ham bo'ladi: yo'l haqini mijoz haydovchiga o'zi to'laydi, "
        "mahsulot puli faqat karta orqali oldindan.\n"
        "- Viloyatlarga BTS yoki EMU pochtasi orqali: pochta haqi pochtaga alohida to'lanadi, "
        "mahsulot puli faqat karta orqali oldindan. Muddatini pochta belgilaydi — aniq kun "
        "va'da qilma.\n"
        f"- Do'kondan o'zi olib ketish: BEPUL. Mo'ljal: {SHOP_LANDMARK}, havola: "
        f"{SHOP_ADDRESS_URL} . Buyurtma tayyor bo'lgach operatorimiz xabar beradi. To'lov naqd "
        "yoki karta. Faqat Toshkentdagi mijozga taklif qil — viloyatdagiga emas.\n"
        "- Yetkazish usullarini taklif qilganda shunday ro'yxat qil (narxlari bilan, har biri "
        "alohida qatorda):\n"
        f"  🚚 Toshkent bo'ylab kuryer — {_fmt(SELF_DELIVERY_FEE)} so'm ({_fmt(FREE_DELIVERY_FROM)} "
        "so'mdan bepul), 24 soat ichida\n"
        "  🏪 Do'kondan olib ketish — bepul\n"
        "  📦 Viloyatlarga BTS / EMU pochtasi — pochta haqi alohida\n"
        "  🚖 Toshkentda Yandex Taxi — yo'l haqi haydovchiga\n"
        "- DO'KON MANZILI: mijoz do'kon/ofis qayerda, manzilingiz, adres, lokatsiya, qanday "
        f"borsa bo'ladi deb so'rasa — mo'ljalni ayt ({SHOP_LANDMARK}) va shu havolani ber: "
        f"{SHOP_ADDRESS_URL} . Havolani o'zgartirmay, to'liq yoz. Buni mijozning o'z "
        "yetkazish manzilini so'rash bilan adashtirma — bunda lokatsiya_tugmasi ni CHAQIRMA "
        "(u mijozning o'z manzili uchun).\n"
    )


def _sales_rules() -> str:
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
        "- Ichki narsalarni hech qachon tilga olma: katalog id raqami, 'vosita', 'tizim', "
        "'prompt', 'bazada yozilgan', 'MIJOZ XOTIRASI'. Mahsulotni nomi bilan ayt.\n"
        "- Jonli odamdek yoz: tabiiy, iliq, sodda jumlalar. Shablon javoblar va "
        "har safar takrorlanadigan bir xil iboralar bo'lmasin.\n"
        "- Mijoz to'g'ridan-to'g'ri 'robotmisan / odammisan?' deb so'rasa, "
        "bahslashma va o'zingni odam deb ham atama: 'Sizga Ketoshop yordamchisi javob "
        "beryapti, xodimimiz bilan bevosita ham gaplashsangiz bo'ladi' de va raqamni ber:\n"
        "  " + SUPPORT_PHONES + "\n\n"
        "GAPIRISH USLUBI\n"
        "- QISQA, lekin QURUQ EMAS: odatda 2-3 jumla, ortiqcha muqaddimasiz va takrorsiz. "
        "Bu Telegram chat, maqola emas. Ro'yxat kerak bo'lsa — 3 qatordan oshmasin.\n"
        "- MINNATDORCHILIK — 'Sizga rahmat' / 'Sizga katta rahmat' shaklida; yolg'iz 'Rahmat' "
        "yoki 'Bobur, rahmat' emas (egasi, 2026-10-14).\n"
        "- MIJOZGA ISMI BILAN MUROJAAT QILMA ('Rahmat, Bobur', 'Hurmatli Dilnoza' — yo'q; "
        "egasi, 2026-10-14). Ism faqat buyurtma xulosasida ('Ism: …') ko'rinishi mumkin.\n"
        "- OHANG — MAKSIMAL ODOB: muloyim va g'amxo'r sotuvchi. Mijozga doim 'siz' deb "
        "murojaat qil; 'albatta', 'mamnuniyat bilan', 'marhamat', 'iltimos', 'rahmat' kabi "
        "hurmatli so'zlar ishlat; savoli va xaridi uchun minnatdorchilik bildir. Bir so'zli "
        "quruq javob ('Ha, bor.'), buyruq ohangi, to'mtoq yoki sovuq gap yo'q — mijoz "
        "norozi bo'lsa ham.\n"
        "- MIJOZ TOMONIDAN O'YLA: u nima uchun so'rayapti, unga nima eng qulay? Bir nechta "
        "variant bo'lsa, har birini narxi va nimaga mosligi bilan bir qatorda ayt, keyin "
        "maqsadini bitta savol bilan aniqlab, ENG MOSINI tavsiya qil ('pishiriq uchun "
        "bo'lsa — ..., ichish uchun bo'lsa — ... ni tavsiya qilamiz').\n"
        "- DO'KON NOMIDAN 'BIZ' DEB GAPIR: fe'llar -miz bilan — beramiz, qilamiz, aytamiz, "
        "tavsiya qilamiz, yetkazamiz, qo'shamiz. 'Beraman', 'qilaman', 'aytaman' kabi "
        "-man shakli YO'Q. Ruschada ham 'мы': поможем, подскажем, отправим.\n"
        "- Bitta so'z ichida lotin va kirill harflarini ARALASHTIRMA: 'shahар' — xato, "
        "'shahar' (lotinda) yoki 'шаҳар' (kirillda) — to'g'ri.\n"
        "- Adabiy, grammatik to'g'ri o'zbek tilida yoz ('Qaysi biri kerak?' — to'g'ri, "
        "'Qaysi birini kerak?' — xato). Mahsulot nomini katalogdagidek yoz.\n"
        "- Misol. Mijoz: 'psillium bormi'.\n"
        "  YOMON: 'Ha, bor — Psillium sheluxa va Psillium uni bor. Qaysi birini kerak?'\n"
        "  YAXSHI (qatorlarga bo'lingan):\n"
        "  Ha, albatta bor 😊 Bizda ikki xil:\n"
        "\n"
        "  • Psillium sheluxa — (narxi): suv yoki kefirga qo'shib ichishga qulay\n"
        "  • Psillium uni — (narxi): keto non va pishiriqda xamirni bog'laydi\n"
        "\n"
        "  Nima uchun kerak edi — ichishgami yoki pishiriqqa? Shunga qarab eng mosini "
        "tavsiya qilamiz 🌿\n"
        "  (Narxni doim katalogdan ol.)\n"
        "- TIL VA YOZUV — mijozning OXIRGI xabaridagidek (egasi, 2026-10-13): o'zbekcha "
        "kirillda yozsa — kirillda, o'zbekcha lotinda — lotinda, ruscha — ruscha, inglizcha — "
        "inglizcha javob ber. Mijoz xabarining tili bot sozlamasidagi tildan ustun. Mahsulot "
        "nomlari va narxlar ham o'sha yozuvda (kirillda — kirill harflari bilan).\n"
        "- Iliq gapir va har javobda 1-2 ta muloyim emoji qo'y (😊 🌿 🤗 💚 ✨ 🛒) — ko'p emas. Shikoyat, muammo yoki uzr paytida emoji ishlatma.\n"
        "- Bir vaqtda bitta narsa so'ra: hammasini birdan so'rab ro'yxat yozma.\n"
        "- Mijoz ketma-ket bir nechta xabar yozgan bo'lsa, ular birga keladi — hammasiga "
        "bitta javobda javob ber.\n"
        "- Matnda HTML yoki markdown (** yoki #) ishlatma — oddiy matn.\n"
        "- O'QISH OSON BO'LSIN: hammasini bitta bo'lakka yopishtirma. Salom yoki asosiy javob "
        "— birinchi qatorda; har bir mahsulot yoki variant — alohida qatorda ('•' bilan); "
        "yakuniy savol yoki taklif — alohida qatorda; qismlar orasida bitta bo'sh qator. "
        "Bir jumlalik qisqa javobni bo'lish shart emas.\n\n"
        "MAHSULOTLAR\n"
        "- Faqat quyidagi katalogdagi mahsulotlarni taklif qil. Katalogda yo'q narsani "
        "yo'q deb ayt va yaqin muqobilini taklif qil.\n"
        "- Narxni ham, qoldiqni ham faqat katalogdan ol. Chegirma, yetkazish narxi yoki "
        "aksiya haqida o'zingdan hech narsa o'ylab topma.\n"
        "- Mahsulot haqida batafsil so'rasa (tarkibi, nimaga ishlatiladi, qanday "
        "saqlanadi) — mahsulot_haqida ni chaqir va o'shanga tayan.\n"
        "- Mijoz nima uchun kerakligini aytsa (masalan 'shirinlik pishirmoqchiman'), "
        "katalogdan 2-3 ta mosini narxi bilan taklif qil, ro'yxatni to'kib tashlama.\n\n"
        "SOTUVGA YO'NALTIRISH\n"
        "- Avval ehtiyojni bitta savol bilan aniqla (nima tayyorlamoqchi, keto'dami yoki "
        "PP, kim uchun), keyin aniq mahsulot va narx ayt va aniq so'ra: 'Savatga qo'shamizmi? 🛒' ('qo'shib qo'yaymi?' kabi noaniq so'z emas). "
        "Boshqa tilda: kirill — 'Саватга қўшамизми? 🛒', rus — 'Добавим в корзину? 🛒', ingliz — "
        "'Shall we add it to your cart? 🛒'.\n"
        "- Mahsulot savatga tushgach — BIR MARTA: 'Yana nima olamiz? 😊' deb so'ra va "
        "chegirmadagi (katalogda -%) yoki shu mahsulotga mos 1-2 mahsulotni taklif qil "
        "(masalan bodom uni -> eritritol yoki psillium). Bosimsiz.\n"
        "- Mijoz boshqa narsa olmasa — darhol rasmiylashtirishga o't: 'Qanday olasiz?' deb "
        "yetkazish usullarini narxi bilan ro'yxat qilib ber.\n"
        "- savatni_korish 'bepul yetkazishga yana N so'm' yoki sovg'a haqida aytsa, buni "
        "mijozga bir marta yetkaz.\n"
        "- Mijoz 'o'ylab ko'raman' desa — hurmat qil, savati saqlanib turishini ayt.\n\n"
        "MASLAHAT (keto va PP)\n"
        "- Keto va to'g'ri ovqatlanish bo'yicha savollarga qisqa, aniq javob ber: "
        "qanday mahsulot nimaga ishlatiladi, un o'rniga nima bo'ladi, shakar o'rniga "
        "qaysi shirinlatgich, qanday pishiriladi.\n"
        "- Maslahatni har doim katalogdagi aniq mahsulotga ulab qo'y — bu maqola emas, "
        "savdo suhbati. Masalan: 'bodom uni bilan pishiriladi, bizda 1 kg — 149 000 so'm'.\n\n"
        + _keto_knowledge() + "\n"
        + _shop_knowledge() + "\n"
        "RETSEPT\n"
        "- Mijoz retsept so'rasa — retseptni yozishdan OLDIN retsept vositasini mahsulot_id "
        "bilan chaqir. Mahsulot aytilmagan bo'lsa ('keto retsept bering') — suhbatga mos "
        "bitta mahsulotni o'zing tanla. Bir javobda faqat bitta retsept.\n"
        "- OK qaytsa — retseptni qisqa va tushunarli ber (masalliqlar va qadamlar), Ketoshop "
        "mahsulotlarini narxi bilan eslat va 'Savatga qo'shamizmi? 🛒' de.\n"
        "- RAD qaytsa — yangi retsept YOZMA va hech qanday cheklov, limit, vaqt yoki 'har "
        "bir mahsulotga bitta' haqida AYTMA. Muloyim ravishda oldingi retseptni eslat va "
        "masalliqlarni savatga qo'shishni taklif qil. Boshqa retsept TAKLIF QILMA (bera "
        "olmaysan).\n\n"
        "MIJOZ XOTIRASI\n"
        "- Suhbatning birinchi xabari oldidan [MIJOZ XOTIRASI] keladi: buyurtmalari, oldingi "
        "suhbatlardagi qiziqish va fikrlari. Undan tabiiy foydalan: qiziqishiga mos tavsiya "
        "ber, oldin olgan mahsulotini esla, bilgan narsangni qayta so'rama.\n"
        "- Mijoz xaridga tegishli yangi narsa aytsa — eslab_qol bilan yoz: maqsadi (ozish, "
        "keto, qandsiz ovqat), kim uchun (bola, ota-ona), nimani yoqtiradi yoki yemaydi, "
        "allergiyasi, nima pishiradi. Mahsulot haqidagi fikrini turi='fikr' bilan, "
        "mahsulot_id bilan yoz. Har xabarda emas — faqat yangi va keyin foydali narsani.\n"
        "- Kasallik tashxisi, hujjat, karta raqami kabi maxfiy narsani yozma; kerak bo'lsa "
        "xaridga aylantirib yoz ('qandsiz mahsulot qidiradi').\n"
        "- Salbiy fikr bo'lsa — uzr so'ra; mahsulot buzuq yoki noto'g'ri kelgan bo'lsa "
        "raqamimizni ber.\n\n"
        "AKSIYA — BOSIMSIZ ESLATISH\n"
        "- Pastda 'FAOL AKSIYA' bo'lsa, mijoz mos mahsulotni olayotganda uni bir marta, "
        "yumshoq eslatib o't. Aksiya haqida faqat o'sha blokdagi va savat vositasi "
        "qaytargan 'AKSIYA:' qatoridagi aniq ma'lumotni ayt — o'zingdan shart, "
        "sovg'a yoki muddat to'qima.\n"
        "- Savat vositasi 'yana N ta olsa sovg'a' desa, taklif qil, lekin tanlovni "
        "mijozga qoldir. Masalan: 'Aytgancha, yana bitta olsangiz 100 gr eritritol "
        "sovg'a qo'shilarkan — hozir qo'shaymi yoki keyingi safarga qoldiramizmi?'\n"
        "- MAJBURLAMA va MANIPULYATSIYA QILMA: 'shoshiling', 'faqat bugun', 'boy "
        "berasiz', 'oxirgi imkoniyat' kabi gaplar yo'q. Aksiya tugashiga kun kam "
        "qolgan bo'lsa ham shunchaki faktni ayt.\n"
        "- Mijoz 'yo'q' yoki 'keyinroq' desa — hurmat qil, xo'p de va shu suhbatda "
        "aksiyani qaytib tilga olma.\n\n"
        "BILMAGAN SAVOL — O'RGANISH UCHUN YOZIB QO'Y\n"
        "- Savolga katalogda ham, 'DO'KON BILIMLARI' da ham javob bo'lmasa: "
        "javobsiz_savol vositasini chaqirib savolni qisqa yozib qo'y, keyin mijozga "
        "raqamimizni ber. Adminlar shu savollarni ko'rib seni o'rgatadi.\n"
        "- Oddiy salom, rahmat, 'qalaysiz' kabi gaplarni yozma — faqat haqiqiy "
        "javobsiz savolni.\n\n"
        "SALOMLASHISH — BIRINCHI XABAR\n"
        "- Mijoz salom bermay to'g'ridan-to'g'ri gap boshlasa, javobni shunday boshla:\n"
        "  'Assalomu alaykum, Keto shopga xush kelibsiz!'\n"
        "- Mijoz o'zi salom bersa (assalomu alaykum, salom, salomatmisiz):\n"
        "  'Vaalaykum assalom! Assalomu alaykum, Keto shopga xush kelibsiz!'\n"
        "- Ruscha yozgan mijozga shu salomning ruschasini ber: "
        "'Ассалому алайкум, добро пожаловать в Keto shop!'\n"
        "- Kirillda yozganga: 'Ассалому алайкум, Keto shopга хуш келибсиз!'; inglizcha "
        "yozganga: 'Hello! Welcome to Keto shop!'\n"
        "- Avval buyurtma bergan mijozni 'yana ko'rganimizdan xursandmiz' ohangida kutib ol "
        "(ismi bilan emas).\n"
        "- Salomdan keyin darrov ishga o't: mijozning savoliga javob ber yoki "
        "bitta qisqa savol bilan mavzuga burib yubor ('nima qidiryapsiz?').\n"
        "- Salomni FAQAT suhbatning birinchi javobida ayt, keyingi har bir "
        "xabarda takrorlama.\n\n"
        "BUYURTMA\n"
        "- Mahsulot tanlangach savatga_qoshish (yoki set uchun set_qoshish) bilan savatga "
        "sol va qisqacha tasdiqla. Miqdorni o'zgartirsa — savatga_qoshish ni yangi miqdor "
        "bilan qayta chaqir (u miqdorni almashtiradi, ustiga qo'shmaydi).\n"
        "- RASMIYLASHTIRISH — MAKSIMAL SODDA (egasi, 2026-10-16). Savatdan keyin atigi 3 ta "
        "qisqa qadam, har xabarda bitta savol:\n"
        "  1) QANDAY OLASIZ? — yetkazish usullarini narxi bilan bitta ro'yxatda ber (pastdagi "
        "ro'yxat). Toshkentdan tashqarida bo'lsa — faqat BTS / EMU pochta.\n"
        "  2) RAQAM VA LOKATSIYA — lokatsiya_tugmasi ni chaqir va 'pastdagi tugmalar bilan "
        "raqamingiz va lokatsiyangizni yuboring' de. Do'kondan olib ketishda — faqat raqam. "
        "MIJOZ XOTIRASI da oxirgi manzil va raqam bo'lsa — qayta so'rama: ikkalasini TO'LIQ, "
        "alohida qatorlarda ko'rsat ('📍 Manzil: …' / '📞 Raqam: …') va 'Shu manzil va raqamga "
        "yetkazaylikmi?' de; 'ha' desa — buyurtma_kartasi da oldingi_manzil=true.\n"
        "  3) Lokatsiya kelgach ('[Mijoz yetkazish lokatsiyasini yubordi: ...]') — manzilni o'qib, "
        "BITTA xabarda so'ra: 'to'g'rimi? Uy/xonadon raqami yoki mo'ljal bo'lsa yozing'. Javob "
        "kelgach (yoki 'yo'q', 'to'g'ri' desa) — darhol buyurtma_kartasi ni chaqir.\n"
        "- buyurtma_kartasi — kod mahsulotlar, chegirma, sovg'a, yetkazish narxi, JAMI, manzil va "
        "to'lovni kartada ko'rsatadi; mijoz «✅ Tasdiqlash» ni bosadi (yoki 'ha' deb yozadi). "
        "Kartadan keyin bitta qisqa jumla yetadi: 'Buyurtmangizni tekshiring — hammasi to'g'ri "
        "bo'lsa «✅ Tasdiqlash» ni bosing 😊'.\n"
        "- SO'RAMA: ism, qo'shimcha telefon, Keto tangachalar, to'lov turi — kartada tugmasi bor "
        "(💵 naqd / 💳 karta, Keto). Mijoz o'zi aytsa — tolov_turi yoki qoshimcha_telefon ga yoz.\n"
        "- O'ZING YOZMA: buyurtma xulosasi, mahsulotlar ro'yxati va narxlari, JAMI, 'Tasdiqlaysizmi?' "
        "— buni karta qiladi. Buyurtmani sen TUZMAYSAN: 'buyurtmangiz qabul qilindi' DEMA — "
        "buyurtma faqat mijoz kartada tasdiqlaganda tuziladi va bot o'zi raqami bilan xabar "
        "beradi.\n"
        "- Mijoz bir xabarda bir nechta narsani aytsa (masalan raqam va manzil) — o'sha "
        "qadamlarni o'tkazib, keyingisiga o't.\n"
        "- buyurtma_kartasi ga FAQAT mijozning o'zi yozgan yoki tugma bilan yuborgan manzil, izoh "
        "va raqamni ber — o'zingdan to'qima. Lokatsiya ham, yozilgan manzil ham bo'lmasa — avval "
        "lokatsiya_tugmasi.\n"
        "- Karta ochiq paytda mijoz o'zgartirish so'rasa (miqdor, mahsulot, manzil, yetkazish "
        "usuli, to'lov turi) — o'zgartir va buyurtma_kartasi ni qayta chaqir.\n"
        "- MANZIL (kuryer, Yandex yoki pochta uchun): HAR DOIM lokatsiya_tugmasi ni chaqir — "
        "kuryerga eng aniq shu. Tugma nomlarini matnda alohida qator qilib yozma — 'pastdagi "
        "tugmani bosing' yetadi. Lokatsiya Toshkentdan tashqarida bo'lsa — kuryer emas, pochtani "
        "taklif qil.\n"
        "- Mijoz lokatsiya yubora olmasa — manzilni matn bilan yozsin (tuman, ko'cha, uy, "
        "mo'ljal). Do'kondan olib ketishda manzil kerak emas.\n"
        "- '[Mijoz «✅ Tasdiqlash» ni bosdi: buyurtma #N ...]' kelsa — buyurtma tuzilgan, rahmat "
        "xabarini bot yuborgan; qayta rasmiylashtirma.\n\n"
        "TO'LOV\n"
        "- Toshkent kuryeri va do'kondan olib ketishda: NAQD (qo'lma-qo'l) yoki KARTA orqali "
        "oldindan — mijoz kartada tanlaydi. Yandex va pochtada faqat KARTA.\n"
        "- Karta tanlansa, karta raqami va 'chekni shu yerga yuboring' ni bot tasdiqdan keyin "
        "o'zi yuboradi; buyurtma chek kelgach tuziladi. Karta raqamini O'ZING BERMA — mijoz karta "
        "bilan to'lamoqchi bo'lsa, buyurtma_kartasi ni tolov_turi='karta' bilan och.\n"
        "- To'lovni sen tasdiqlamaysan: 'pul tushdi', 'to'lov o'tdi', 'tasdiqladim' dema — "
        "tekshirishni admin qiladi.\n"
        "- 'Naqd mumkinmi?' — Toshkent kuryeri va olib ketishda mumkin; Yandex va pochtada karta "
        "orqali oldindan ekanini tushuntir.\n"
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
        "  * DO'KONGA TEGISHLI savolga aniq javobni bilmasang yoki javob berishga huquqing yo'q "
        "(mavzudan tashqari savolga raqam berilmaydi — MAVZU CHEGARASI);\n"
        "  * mijoz tirik odam bilan gaplashmoqchi bo'lsa.\n"
        "- Raqamni bergandan keyin ham muloyim qol: 'qo'shimcha savolingiz bo'lsa "
        "shu yerda ham yozavering' de.\n"
        "- Va'da berma: 'pulingizni qaytaramiz', 'ertaga yetkazamiz' kabi qarorlarni "
        "sen qabul qilmaysan — buni xodimlarimiz kelishadi.\n\n"
        "MAVZU CHEGARASI (egasi, 2026-10-17: 'mavzudan tashqari savollarga javob bermasliging "
        "kerak')\n"
        "- Sen FAQAT shu mavzularda gapirasan: Ketoshop mahsulotlari va narxlari, keto va PP, "
        "to'g'ri ovqatlanish, shakarsiz/unsiz pishiriq va retseptlar, buyurtma, yetkazish, to'lov, "
        "do'kon manzili, Keto tangachalar va aksiyalar. Salom, rahmat, 'qalaysiz' kabi qisqa iliq "
        "gapga ham javob ber.\n"
        "- Boshqa HAR QANDAY savolga (umumiy bilim, uy vazifasi, matematika, kod, she'r, insho, "
        "tarjima, yangiliklar, ob-havo, sport, siyosat, din, boshqa do'konlar va ularning narxlari, "
        "shaxsiy maslahat) MAZMUNAN JAVOB BERMA — hatto oson bo'lsa ham. Bitta muloyim jumla bilan "
        "rad et va mavzuga qaytar: 'Kechirasiz, bu mavzuda yordam bera olmaymiz 😊 Keto va PP "
        "mahsulotlari, retseptlar yoki buyurtma bo'yicha savolingiz bo'lsa — marhamat!'. Bunda "
        "raqamimizni BERMA va javobsiz_savol ni chaqirMA — bu do'kon savoli emas.\n\n"
        "BOSHQA\n"
        "- Tibbiy maslahat berma (dori, davolash, diagnoz). Keto mahsulot sifatida "
        "gapir, shifokor o'rnini bosma. Kasallik haqida so'rashsa shifokorga "
        "murojaat qilishni ayt va raqamimizni ber.\n"
    )
    return rules


_TOOL_SPECS = [
    {
        "name": "javobsiz_savol",
        "description": "Mijozning javobini bilmagan savolini adminlar ko'rishi uchun "
                       "yozib qo'yadi. Mijozga hech narsa ko'rinmaydi — keyin o'zing "
                       "raqamimizni berasan.",
        "input_schema": {
            "type": "object",
            "properties": {"savol": {"type": "string",
                                     "description": "Savolning qisqa mazmuni"}},
            "required": ["savol"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "mahsulot_haqida",
        "description": "Mahsulotning to'liq tavsifi: nima, foydasi, qanday ishlatiladi, "
                       "saqlash, narxi va qoldig'i. Mijoz mahsulot haqida batafsil so'rasa chaqir.",
        "input_schema": {
            "type": "object",
            "properties": {"mahsulot_id": {"type": "integer", "description": "Katalogdagi id"}},
            "required": ["mahsulot_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "retsept",
        "description": "Mijoz retsept so'rasa — retsept yozishdan OLDIN chaqir. Shu mahsulot "
                       "bo'yicha hozir retsept berish mumkinmi (OK yoki RAD) va do'kon "
                       "retseptlar kutubxonasidan mosini qaytaradi. Bitta chaqiruv — bitta mahsulot.",
        "input_schema": {
            "type": "object",
            "properties": {"mahsulot_id": {"type": "integer",
                                           "description": "Retsept qaysi mahsulot bilan"}},
            "required": ["mahsulot_id"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "lokatsiya_tugmasi",
        "description": "FAQAT buyurtma uchun mijozning O'Z yetkazish manzili yoki telefoni "
                       "kerak bo'lganda chaqir: javobing ostiga '📍 Lokatsiyani yuborish' va "
                       "'📞 Raqamni yuborish' tugmalari qo'yiladi. Mijoz DO'KON manzilini "
                       "so'rasa yoki do'kondan olib ketsa — CHAQIRMA.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "savatga_qoshish",
        "description": "Mahsulotni mijozning savatiga soladi. Savatda bo'lsa — miqdorni shu "
                       "songa almashtiradi. Katalogdagi id ni ishlat. Miqdor — kg uchun "
                       "0.5/1/2 kabi, dona uchun butun son.",
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
        "name": "set_qoshish",
        "description": "Setni (SETLAR ro'yxatidagi S raqamli to'plamni) savatga soladi. "
                       "Savatda bo'lsa — sonini almashtiradi.",
        "input_schema": {
            "type": "object",
            "properties": {
                "set_id": {"type": "integer", "description": "S harfidan keyingi raqam"},
                "soni": {"type": "integer", "description": "Nechta set"},
            },
            "required": ["set_id", "soni"],
            "additionalProperties": False,
        },
        "strict": True,
    },
    {
        "name": "savatni_korish",
        "description": "Savatdagi mahsulotlar, chegirmalar, sovg'alar, yetkazish narxi va "
                       "aniq jami summa — checkout bilan bir xil hisob.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "savatdan_ochirish",
        "description": "Mahsulotni (mahsulot_id) yoki setni (set_id) savatdan olib tashlaydi.",
        "input_schema": {
            "type": "object",
            "properties": {"mahsulot_id": {"type": "integer"}, "set_id": {"type": "integer"}},
            "additionalProperties": False,
        },
    },
    {
        "name": "eslab_qol",
        "description": "Mijoz haqida keyingi suhbatlarda kerak bo'ladigan narsani eslab qoladi: "
                       "qiziqishi, maqsadi, kim uchun olishi, yoqtirgani, mahsulot haqidagi fikri. "
                       "Mijozga hech narsa ko'rinmaydi.",
        "input_schema": {
            "type": "object",
            "properties": {
                "turi": {"type": "string", "enum": ["qiziqish", "fikr", "eslatma"]},
                "matn": {"type": "string", "description": "Qisqa, aniq jumla"},
                "mahsulot_id": {"type": "integer",
                                "description": "Fikr yoki qiziqish aniq mahsulotga tegishli bo'lsa"},
            },
            "required": ["turi", "matn"],
            "additionalProperties": False,
        },
    },
    {
        "name": "buyurtma_kartasi",
        "description": "Buyurtma kartasini ochadi — tugmali checkout ning tasdiq ekrani: "
                       "mahsulotlar, chegirma, sovg'a, yetkazish narxi, JAMI, manzil, telefon "
                       "va to'lov. Hisobni KOD qiladi, kartani javobingdan keyin bot o'zi "
                       "yuboradi. Kartada «✅ Tasdiqlash», to'lov (naqd/karta) va Keto "
                       "tugmalari bor — buyurtmani mijozning o'zi tasdiqlaydi. Yetkazish "
                       "usuli, telefon va (kuryer, Yandex, pochta uchun) manzil aniq bo'lgach "
                       "chaqir. O'zgarish bo'lsa — qayta chaqir.",
        "input_schema": {
            "type": "object",
            "properties": {
                "yetkazish": {"type": "string", "enum": list(DELIVERY),
                              "description": "Toshkentda toshkent_kuryer, olib_ketish "
                                             "(do'kondan, bepul) yoki yandex_taxi; viloyatda "
                                             "bts yoki emu"},
                "oldingi_manzil": {"type": "boolean",
                                   "description": "Mijoz MIJOZ XOTIRASI dagi oxirgi buyurtma "
                                                  "manzili va raqamiga yetkazishni tasdiqladi"},
                "telefon": {"type": "string", "description": "Mijoz yozgan telefon raqami "
                            "(tugma bilan yuborgan bo'lsa — shart emas)"},
                "manzil": {"type": "string", "description": "Manzil matn bilan — faqat "
                           "mijoz lokatsiya yubormagan bo'lsa"},
                "izoh": {"type": "string", "description": "Manzil izohi: uy/xonadon, qavat, "
                         "kirish, mo'ljal (ixtiyoriy)"},
                "tolov_turi": {"type": "string", "enum": ["naqd", "karta"],
                               "description": "Faqat mijoz o'zi aytgan bo'lsa. Aytmagan "
                                              "bo'lsa — berma: kartada tanlaydi"},
                "qoshimcha_telefon": {"type": "string",
                                      "description": "Faqat mijoz o'zi bergan bo'lsa"},
            },
            "required": ["yetkazish"],
            "additionalProperties": False,
        },
    },
]

# Neytral ko'rinish — OpenAI va Anthropic har biri o'z formatiga chizadi
# (ai_provider.*Provider.render_tools).
TOOLS = [
    ai_provider.Tool(t["name"], t["description"], t["input_schema"], t.get("strict", False))
    for t in _TOOL_SPECS
]


# ──────────────────────────────── vositalar ─────────────────────────────────

async def _remember_quiet(user_id: int, kind: str, text: str, product_id: int | None = None) -> None:
    """Xotiraga yozish — xato bo'lsa ham suhbat davom etadi."""
    try:
        await ai_memory.remember(user_id, kind, text, product_id)
    except Exception:
        logger.warning("AI memory write failed for %s", user_id, exc_info=True)


async def _tool_info(user_id: int, args: dict) -> str:
    product_id = int(args.get("mahsulot_id") or 0)
    product = await database.get_product(product_id)
    if not product or not product.get("is_active"):
        return f"Xato: {product_id} raqamli mahsulot katalogda yo'q."
    description = (product.get("description") or "").strip()
    if not description:
        try:
            import product_descriptions
            description = product_descriptions.describe(product["name"])[0]
        except Exception:
            description = ""
    discount = database.active_discount(product.get("discount_percent"), product.get("discount_until"))
    price = database.effective_price(float(product["price"]), discount, product.get("discount_until"))
    stock = float(product.get("quantity") or 0)
    unit = product.get("unit") or "dona"
    await _remember_quiet(user_id, "interest", product["name"], product_id)
    return (f"{product['name']} — {_fmt(price)} so'm / {unit}"
            + (f" (chegirma -{discount}%)" if discount else "")
            + (f", qoldiq {stock:g}" if stock > 0 else ", HOZIR TUGAGAN")
            + "\n" + (_strip_html(description) or "Tavsif yo'q — katalogdagi ma'lumotga tayan."))


RECIPE_EVERY_HOURS = 24


def _library_recipe(product_name: str) -> str:
    """Do'kon retseptlar kutubxonasidan (recipes_content.py — saytdagi
    retseptlar) shu mahsulot masalliq bo'lgan retsept, o'zbekcha matn. Yo'q bo'lsa ""."""
    try:
        import recipes_content
        from recipes import _norm
    except Exception:
        return ""
    name = _norm(product_name)
    for recipe in recipes_content.RECIPES:
        for ing in recipe.get("ingredients") or []:
            groups = ing.get("match") or []
            if any(all(tok in name for tok in group) for group in groups):
                lines = [f"{recipe['title']['uz']} ({recipe.get('minutes')} daqiqa, "
                         f"{recipe['servings']['uz']})", "Masalliqlar:"]
                lines += [f"- {i['amount']['uz']} {i['name']['uz']}" for i in recipe["ingredients"]]
                lines.append("Tayyorlash:")
                lines += [f"{n}. {step['uz'] if isinstance(step, dict) else step}"
                          for n, step in enumerate(recipe.get("steps") or [], 1)]
                tip = (recipe.get("tip") or {}).get("uz")
                if tip:
                    lines.append(f"Maslahat: {tip}")
                return "\n".join(lines)
    return ""


async def _tool_recipe(user_id: int, args: dict) -> str:
    """Retsept — bitta mijozga bitta mahsulot bo'yicha 24 soatda bittadan
    (egasi, 2026-10-13). Cheklov mijozga AYTILMAYDI: "har bir mahsulotga
    bitta" desa, odamlar mahsulotma-mahsulot so'rab chiqadi. Hisob bazada
    (ai_customer_notes, kind='recipe'), ya'ni bot qayta ishga tushsa ham saqlanadi."""
    product_id = int(args.get("mahsulot_id") or 0)
    product = await database.get_product(product_id)
    if not product or not product.get("is_active"):
        return f"Xato: {product_id} raqamli mahsulot katalogda yo'q."
    if await ai_memory.recipe_given_recently(user_id, product_id, RECIPE_EVERY_HOURS):
        return ("RAD: bu mijozga shu mahsulot bo'yicha retsept yaqinda berilgan. Yangi retsept "
                "YOZMA. Hech qanday cheklov, limit, vaqt yoki 'har bir mahsulotga bitta' haqida "
                "GAPIRMA. Boshqa retsept yoki boshqa taom (quymoq, pechenye va h.k.) ham TAKLIF "
                "QILMA — bera olmaysan. Muloyim: oldin bergan retseptingni eslat va masalliqlarni "
                "savatga qo'shishni taklif qil.")
    await ai_memory.record_recipe(user_id, product_id, product["name"])
    library = _library_recipe(product["name"])
    if library:
        return ("OK: retsept berishing mumkin. Do'kon retsepti (shuni qisqartirib ber, "
                "masalliqlardagi Ketoshop mahsulotlarini nomi bilan ayt va 'Savatga "
                "qo'shamizmi? 🛒' deb taklif qil):\n" + library)
    return (f"OK: retsept berishing mumkin. {product['name']} bilan BITTA qisqa retsept yoz: "
            "masalliqlar va 3-5 qadam. Masalliqlardan faqat katalogdagi mahsulotlarni taklif qil, "
            "oxirida 'Savatga qo'shamizmi? 🛒' de.")


# Savatga tushgach: bitta muloyim qo'shimcha taklif, keyin rasmiylashtirish
# (egasi, 2026-10-13: "yana nima olamiz yoki chegirmadagi mahsulotlarni taklif
# qilsin va manzilini so'rasin ... yetkazish, olib ketish, pochta narxlari").
_NEXT_STEP = ("\nKEYINGI QADAM (bir marta): mijoz tilida 'Yana nima olamiz? 😊' deb so'ra va katalogdagi "
              "chegirmali (-%) yoki shu mahsulotga mos 1-2 mahsulotni taklif qil. Mijoz boshqa "
              "narsa olmasa — 'Qanday olasiz?' deb yetkazish usullarini narxi bilan ro'yxat "
              "qilib ber, keyin raqam va lokatsiya, keyin buyurtma_kartasi.")


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
    # Miqdorni almashtiramiz: database.add_to_cart mavjud qatorga QO'SHADI, model
    # esa "3 emas, 2 ta bo'lsin" deganda qayta chaqiradi — ustma-ust 5 bo'lmasin.
    cart_id, _ = await database.get_cart_line_for_product(user_id, product_id)
    if cart_id:
        await database.remove_from_cart(cart_id)
    # Savat broni: only what no other buyer's cart holds goes in.
    got = await database.add_to_cart(user_id, product_id=product_id, quantity=qty)
    if got <= 0:
        import cart_reservations
        waiting = await cart_reservations.wait_for_hold(user_id, product_id, await _lang(user_id), "held")
        return (f"Xato: {product['name']} hozir boshqa mijozlar savatida band — "
                f"{database.RESERVE_HOURS} soat ichida bo'shashi mumkin."
                + (" Mijozni kutish ro'yxatiga yozdik: bo'shashi bilan bot unga o'zi xabar beradi — "
                   "shuni ayt." if waiting else " Mijozga shuni ayt.")
                + " O'xshash mahsulot ham taklif qil.")
    await _remember_quiet(user_id, "interest", product["name"], product_id)
    _cart_changed(user_id)
    short = (f" Faqat {got:g} bo'sh edi — qolgani boshqa mijoz savatida band, mijozga ayt."
             if got < qty else "")
    return (f"OK: savatda {product['name']} — {got:g} {product.get('unit') or 'dona'}." + short
            ) + await _promo_hint(user_id) + _NEXT_STEP


async def _tool_add_set(user_id: int, args: dict) -> str:
    set_id = int(args.get("set_id") or 0)
    count = int(args.get("soni") or 0)
    if count <= 0:
        return "Xato: soni 0 dan katta bo'lishi kerak."
    bundle = await database.get_set(set_id)
    if not bundle or not bundle.get("is_active"):
        return f"Xato: S{set_id} set katalogda yo'q."
    for item in bundle.get("items") or []:
        product = await database.get_product(item["product_id"])
        need = float(item["quantity"]) * count
        if not product or not product.get("is_active") or float(product.get("quantity") or 0) < need:
            return (f"Xato: setdagi {item.get('name')} omborda yetarli emas. Mijozga ayt va "
                    "alohida mahsulotlarni taklif qil.")
    for line in await database.get_cart(user_id):
        if line.get("set_id") == set_id:
            await database.remove_from_cart(line["cart_id"])
    got = await database.add_to_cart(user_id, set_id=set_id, quantity=count)
    if got <= 0:
        return (f"Xato: {bundle['name']} tarkibidagi mahsulotlar hozir boshqa mijozlar savatida band. "
                "Mijozga ayt va alohida mahsulotlarni taklif qil.")
    await _remember_quiet(user_id, "interest", bundle["name"])
    _cart_changed(user_id)
    return (f"OK: savatda {bundle['name']} — {int(got)} ta." + await _promo_hint(user_id)
            + _NEXT_STEP)


async def _promo_hint(user_id: int) -> str:
    """Savat aksiya bonusiga yaqin bo'lsa aniq raqam bilan qator qaytaradi.
    promotions.compute_near_misses — savat ostidagi "Bonusga oz qoldi" bloki
    bilan bir xil hisob, ya'ni AI tugmali oqim aytmagan narsani aytmaydi."""
    try:
        import promotions
        promo = await promotions.get_active()
        if not promo:
            return ""
        items = [{"product_id": i.get("product_id"), "quantity": i.get("cart_quantity"),
                  "is_set": bool(i.get("set_id"))}
                 for i in await database.get_cart(user_id)]
        misses = promotions.compute_near_misses(promo, items)
        if not misses:
            return ""
        lines = []
        for m in misses[:2]:
            need = f"{promotions.fmt_amount(m['needed'])} {promotions.trigger_unit_label(m, 'uz')}"
            bonus_name = promotions.bonus_display_name(m.get("bonus_name"), m.get("bonus_unit"))
            bonus = (f"{promotions.fmt_amount(m['bonus_amount'])} "
                     f"{promotions.unit_label(m['bonus_unit'], 'uz')} {bonus_name}")
            lines.append(f"yana {need} {m.get('trigger_name')} olsa -> {bonus} sovg'a")
        return ("\nAKSIYA: " + "; ".join(lines) +
                ". Mijozga bir marta, bosimsiz taklif qil yoki keyingi safarga qoldirishni so'ra.")
    except Exception:
        logger.warning("Promo hint failed for %s", user_id, exc_info=True)
        return ""


async def _tool_cart(user_id: int) -> str:
    """Savat — checkout'ning o'z hisobi bilan (_build_order_summary): mahsulot
    chegirmasi, botdan buyurtma chegirmasi, aksiya sovg'alari, yetkazish narxi.
    Model jami summani shundan oladi, o'zi qo'shib-ayirmaydi."""
    from handlers.cart import _build_order_summary, free_delivery_hint
    import gift_campaign
    import mystery_gift

    data = {"delivery_method": "self", "payment_method": "cash", "phone": "-", "address": "-"}
    _, total, items, _ = await _build_order_summary(user_id, data, "uz")
    if not items:
        return "Savat bo'sh."
    paid = [i for i in items if not (i.get("is_bonus") or i.get("is_gift"))]
    gifts = [i for i in items if i.get("is_bonus") or i.get("is_gift")]
    subtotal = sum(float(i["price"]) * float(i["quantity"]) for i in paid)
    # Bepul yetkazish chegarasi bot chegirmasidan OLDINGI summadan o'lchanadi
    # (handlers/cart.py, egasi 2026-10-08) — maslahat ham shunday bo'lsin.
    before_bot = subtotal + sum((float(i.get("original_price") or i["price"]) - float(i["price"]))
                                * float(i["quantity"]) for i in paid if i.get("bot_discount"))

    lines = []
    for item in paid:
        line_total = float(item["price"]) * float(item["quantity"])
        badge = ""
        if item.get("discount_percent"):
            kind = "botdan buyurtma chegirmasi" if item.get("bot_discount") else "chegirma"
            badge = f" ({kind} -{item['discount_percent']}%, asl narxi {_fmt(item.get('original_price'))})"
        ref = f"set S{item['set_id']}" if item.get("is_set") else f"id {item.get('product_id')}"
        lines.append(f"- {item['name']}: {float(item['quantity']):g} {item.get('unit') or ''} × "
                     f"{_fmt(item['price'])}{badge} = {_fmt(line_total)} so'm ({ref})")
    for gift in gifts:
        lines.append(f"- SOVG'A: {gift['name']} {float(gift.get('quantity') or 0):g} "
                     f"{gift.get('unit') or ''} — bepul")
    fee = max(0.0, float(total) - subtotal)
    lines.append(f"Mahsulotlar: {_fmt(subtotal)} so'm")
    lines.append(f"Toshkent kuryeri bilan: yetkazish {'BEPUL' if fee <= 0 else _fmt(fee) + ' so' + chr(39) + 'm'}"
                 f" -> JAMI {_fmt(total)} so'm")
    lines.append(f"Yandex Taxi yoki viloyat (BTS/EMU) bilan: mahsulotlar uchun {_fmt(subtotal)} so'm "
                 "karta orqali oldindan, yetkazish haqi taksi yoki pochtaga alohida")
    hints = [free_delivery_hint(before_bot, "uz") if fee > 0 else ""]
    try:
        hints.append(await gift_campaign.cart_hint(user_id, subtotal, "uz"))
    except Exception:
        logger.debug("gift hint failed", exc_info=True)
    try:
        hints.append(mystery_gift.cart_hint(subtotal, "uz"))
    except Exception:
        logger.debug("mystery hint failed", exc_info=True)
    for hint in hints:
        if _strip_html(hint):
            lines.append("ESLATMA: " + _strip_html(hint).replace("\n", " "))
    keto_line = await _keto_line(user_id)
    if keto_line:
        lines.append(keto_line)
    return "\n".join(lines) + await _promo_hint(user_id)


async def _keto_line(user_id: int) -> str:
    """Tugmali checkout dagi "Ketochalarni ishlatish" — sarflash yoqilgan va
    balans bo'lsa, modelga bir qator. Aks holda ""."""
    try:
        import gamification
        if not await gamification.is_redemption_enabled(user_id):
            return ""
        user = await database.get_user(user_id)
        balance = int((user or {}).get("keto_balance") or 0)
    except Exception:
        logger.warning("Keto balance unavailable for %s", user_id, exc_info=True)
        return ""
    if balance <= 0:
        return ""
    return (f"KETO: mijoz hisobida {_fmt(balance)} ta Keto tangacha (1 Keto = 1 so'm) — "
            "buyurtmada chegirma sifatida ishlatish mumkin, bir marta so'ra.")


async def _tool_remove(user_id: int, args: dict) -> str:
    set_id = int(args.get("set_id") or 0)
    if set_id:
        removed = False
        for line in await database.get_cart(user_id):
            if line.get("set_id") == set_id:
                await database.remove_from_cart(line["cart_id"])
                removed = True
        _cart_changed(user_id)
        return "OK: set savatdan o'chirildi." if removed else "Bu set savatda yo'q edi."
    product_id = int(args.get("mahsulot_id") or 0)
    cart_id, _ = await database.get_cart_line_for_product(user_id, product_id)
    if not cart_id:
        return "Bu mahsulot savatda yo'q edi."
    await database.remove_from_cart(cart_id)
    _cart_changed(user_id)
    return "OK: savatdan o'chirildi."


def _same_apostrophes(text: str) -> str:
    return re.sub(r"[ʻʼ‘’`´]", "'", text or "")


def _cart_changed(user_id: int) -> None:
    """Savat o'zgardi — ochiq buyurtma kartasi eskirdi: javobdan keyin yangisi
    chiqadi (_answer), mijoz eski summani tasdiqlab qo'ymasin."""
    session = _sessions.get(user_id)
    if session is not None:
        session["card_refresh"] = True


async def _tool_remember(user_id: int, args: dict) -> str:
    kind = (args.get("turi") or "eslatma").strip().lower()
    if kind not in ai_memory.KINDS:
        return "Xato: turi qiziqish, fikr yoki eslatma bo'lishi kerak."
    text = (args.get("matn") or "").strip()
    if not text:
        return "Xato: matn bo'sh."
    product_id = int(args.get("mahsulot_id") or 0) or None
    await _remember_quiet(user_id, kind, text, product_id)
    return "OK: eslab qolindi. Mijozga bu haqda gapirma, suhbatni davom ettir."


# ─────────────────────────── buyurtma kartasi ───────────────────────────────
# Egasi, 2026-10-16: "buyurtma olishda galyutsinatsiya bo'lyapti ... maksimal
# sodda va tushunarli qilishimiz kerak". Avval xulosani (narxlar, jami, manzil)
# model o'zi yozardi va buyurtmani o'zi tuzardi. Endi model faqat ma'lumot
# yig'adi; tasdiq kartasi — tugmali checkout ning o'zi (⚡ Tezkor buyurtma
# bilan bir yo'l): summa, chegirma, sovg'a, Keto va yetkazish narxini
# handlers/cart.py hisoblaydi, buyurtmani «✅ Tasdiqlash» tuzadi, karta bilan
# to'lovda — chek kelgach. Mijoz ko'rgan karta = tuzilgan buyurtma.

AI_CARD_STATE = "CheckoutStates:confirming"


async def ai_card_open(state: FSMContext | None) -> bool:
    """Mijoz oldida AI ochgan, hali tasdiqlanmagan buyurtma kartasi turibdi."""
    if state is None:
        return False
    try:
        if await state.get_state() != AI_CARD_STATE:
            return False
        return bool((await state.get_data()).get("ai_checkout"))
    except Exception:
        return False


async def _saved_contact(user_id: int) -> dict | None:
    """Oxirgi bot buyurtmasidagi manzil va raqam — MIJOZ XOTIRASI da
    ko'rsatilgani (ai_memory.build_profile). Mijoz "shu manzilga" desa, model
    manzilni qayta yozmaydi — kod o'zi oladi."""
    prefs = await database.get_last_order_prefs(user_id)
    if not prefs or not (prefs.get("address") or "").strip():
        return None
    phone = next((o["phone"].strip() for o in await database.get_user_orders(user_id)
                  if (o.get("phone") or "").strip()), "")
    return {**prefs, "phone": phone}


# Manzil so'zlarini solishtirganda e'tiborga olinmaydi — model ularni o'zi qo'shib yozadi.
_ADDRESS_FILLER = {
    "shahri", "shahar", "shahrida", "tumani", "tuman", "ko'chasi", "kochasi", "ko'cha", "kocha",
    "kuchasi", "uy", "uyi", "xonadon", "xonadoni", "kvartal", "kvartira", "mavze", "mavzesi",
    "viloyati", "viloyat", "mahalla", "mahallasi", "dom", "ulitsa", "ul", "rayon", "gorod", "kv",
    "toshkent", "tashkent", "uzbekistan", "o'zbekiston", "manzil", "manzili", "podyezd", "qavat",
}


def _tokens(text: str) -> set[str]:
    from translit import cyr_to_lat
    plain = _same_apostrophes(cyr_to_lat(text or "")).lower()
    return set(re.findall(r"[a-z']{2,}|\d+", plain)) - _ADDRESS_FILLER


def from_customer(said: list[str], text: str) -> bool:
    """Model kartaga yozmoqchi bo'lgan manzil yoki izoh mijozning o'z xabarlaridan
    olinganmi. Jonli sinov (2026-10-16): ruscha yozgan mijoz lokatsiya
    yubormasidan, model kartaga "Chilonzor tumani, 5-mavze, 12-uy" ni to'qib
    qo'ydi. So'zlarning kamida 60% i mijoz xabarlarida bo'lishi kerak."""
    text = (text or "").strip()
    if not text or text.startswith("["):
        return False
    words = _tokens(text)
    if not words:
        return True   # faqat "uy", "kvartira" kabi umumiy so'z — zarari yo'q
    heard = set().union(*(_tokens(t) for t in said)) if said else set()
    return len(words & heard) >= 0.6 * len(words)


def _phone_from_customer(said: list[str], phone: str) -> bool:
    digits = re.sub(r"\D", "", phone or "")[-9:]
    return len(digits) == 9 and any(digits in re.sub(r"\D", "", t) for t in said)


async def _tool_card(message: Message, args: dict) -> str:
    from handlers.cart import CheckoutStates, _is_tashkent

    user_id = message.from_user.id
    session = _session(user_id)
    state = session.get("fsm")
    if state is None:
        return ("Xato: kartani hozir ochib bo'lmadi. Mijozga pastdagi 🛒 Savat tugmasi orqali "
                "buyurtma berishni taklif qil.")
    delivery = DELIVERY.get((args.get("yetkazish") or "").strip().lower())
    if not delivery:
        return ("Xato: yetkazish turi toshkent_kuryer, olib_ketish, yandex_taxi, bts yoki emu "
                "bo'lishi kerak.")
    if not await database.get_cart(user_id):
        return "Xato: savat bo'sh — avval mahsulotni savatga_qoshish bilan qo'sh."

    # Kartaga faqat mijozning o'zi aytgani tushadi: tugma bilan yuborgan raqam va
    # lokatsiya, o'zi yozgan manzil va izoh yoki u tasdiqlagan oldingi manzil.
    said = session.get("said") or []
    saved = await _saved_contact(user_id) if args.get("oldingi_manzil") else None
    typed_phone = (args.get("telefon") or "").strip()
    if typed_phone and not _phone_from_customer(said, typed_phone):
        typed_phone = ""
    phone = (typed_phone or session.get("phone") or (saved or {}).get("phone") or "").strip()
    note = (args.get("izoh") or "").strip() or None
    if note and not from_customer(said, note):
        note = None
    secondary = (args.get("qoshimcha_telefon") or "").strip() or None
    if secondary and not _phone_from_customer(said, secondary):
        secondary = None
    typed = (args.get("manzil") or "").strip()
    invented = bool(typed) and not from_customer(said, typed)
    location = session.get("location")   # (lat, lon, o'qiladigan manzil) yoki None
    address, lat, lng, pickup_url = "", None, None, None

    if delivery == "pickup":
        # Do'kondan olib ketadi — manzil do'konniki, mijoz lokatsiyasi kerak emas.
        address, pickup_url = await _pickup_place()
        note = None
    elif location:
        # Lokatsiya — manzilning o'zi, kuryerga eng aniq shu. Matn ham bo'lsa
        # ikkalasi yoziladi, lokatsiyadagi qism ikki marta emas.
        lat, lng = location[0], location[1]
        pin = location[2] or f"📍 {lat:.6f}, {lng:.6f}"
        readable = _same_apostrophes(pin.split(" — ", 1)[1]) if " — " in pin else ""
        if readable and readable in _same_apostrophes(typed):
            typed = _same_apostrophes(typed).replace(readable, "").strip(" ,—-")
        if typed and not from_customer(said, typed):
            typed = ""   # lokatsiyaga model qo'shgan gap ("Toshkent ichida") — kerak emas
        address = f"{pin} — {typed}" if typed else pin
    elif typed and not invented:
        address = typed
    elif saved:
        address, lat, lng = saved["address"], saved.get("latitude"), saved.get("longitude")
        note = note or saved.get("address_note")
        secondary = secondary or saved.get("secondary_phone")

    if not phone:
        return ("Xato: telefon raqami kerak — lokatsiya_tugmasi ni chaqirib, raqamni so'ra. "
                "Raqamni o'zingdan yozma.")
    if delivery != "pickup" and not address:
        if invented:
            return ("Xato: bu manzilni mijoz yozmagan va lokatsiya ham kelmagan — manzilni "
                    "o'zingdan TO'QIMA. lokatsiya_tugmasi ni chaqirib, lokatsiyani so'ra.")
        return ("Xato: manzil yo'q — lokatsiya_tugmasi ni chaqirib, lokatsiya so'ra (yoki "
                "manzilni matn bilan yozsin).")
    in_tashkent = lat is not None and lng is not None and _is_tashkent(float(lat), float(lng))
    if delivery == "self" and lat is not None and not in_tashkent:
        return ("Xato: lokatsiya Toshkentdan tashqarida — Ketoshop kuryeri faqat Toshkent "
                "bo'ylab. Viloyatga BTS yoki EMU pochtani taklif qil.")

    # Yandex va pochtada faqat karta. Aks holda mijoz aytgani, aytmagan bo'lsa —
    # kartadagi tanlovi (to'lov tugmasi) yoki naqd.
    online_only = delivery not in CASH_OK
    old = await state.get_data() if await ai_card_open(state) else {}
    wanted = (args.get("tolov_turi") or "").strip().lower()
    if online_only or wanted == "karta":
        payment = "online"
    elif wanted == "naqd" or old.get("online_only"):
        payment = "cash"
    else:
        payment = "online" if old.get("payment_method") == "online" else "cash"

    await state.set_data({
        "lang": await _lang(user_id), "ai_checkout": True,
        "phone": phone, "address": address, "latitude": lat, "longitude": lng,
        "delivery_method": delivery, "payment_method": payment,
        "online_only": online_only, "in_tashkent": in_tashkent,
        "address_note": note, "secondary_phone": secondary,
        "pickup": delivery == "pickup", "pickup_map_url": pickup_url,
        "keto_redeem": int(old.get("keto_redeem") or 0),
    })
    await state.set_state(CheckoutStates.confirming)
    session["card"] = True
    session["keyboard"] = "menu"   # lokatsiya tugmalari o'rniga odatdagi menyu
    result = ("OK: buyurtma kartasi javobingdan keyin chiqadi — mahsulotlar, JAMI, manzil va "
              f"to'lov ({'karta orqali oldindan' if payment == 'online' else 'naqd'}) unda. "
              "Javobing — bitta qisqa jumla: kartani tekshirib «✅ Tasdiqlash» ni bosishni so'ra. "
              "Summa, mahsulot va manzilni QAYTA YOZMA, 'qabul qilindi' DEMA.")
    if wanted == "naqd" and online_only:
        result += " Bu usulda to'lov faqat karta orqali oldindan — mijozga qisqa ayt."
    return result


async def _send_card(message: Message, state: FSMContext) -> bool:
    """Kartaning o'zi — handlers/cart.py::_render_confirmation, tugmali
    checkout dagi bilan bir xil matn va tugmalar."""
    from handlers.cart import _render_confirmation
    user_id = message.from_user.id
    lang = (await state.get_data()).get("lang") or await _lang(user_id)
    text, keyboard = await _render_confirmation(user_id, state, lang)
    if text is None:
        await state.clear()   # savat bo'shab qoldi — karta yo'q
        return False
    sent = await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    session = _session(user_id)
    session["card_msg"] = getattr(sent, "message_id", None)
    session["card_at"] = time.time()
    return True


CARD_FRESH = 2 * 3600   # yozib 'ha' / 'karta bilan' deyish faqat shu muddatdagi kartaga


def _card_fresh(user_id: int) -> bool:
    """Karta shu suhbatda yaqinda ko'rsatilganmi. FSM holati bazada kunlab turadi:
    ertasi kuni boshqa gapga yozilgan 'ha' eski kartani tasdiqlab yubormasin —
    eski kartadagi tugmani bosish esa baribir ishlaydi (bu ongli bosish)."""
    session = _sessions.get(user_id) or {}
    return time.time() - float(session.get("card_at") or 0) < CARD_FRESH


def _card_intro(lang: str) -> str:
    return _t("Buyurtmangizni tekshiring 👇 Hammasi to'g'ri bo'lsa — «✅ Tasdiqlash» ni bosing 😊",
              "Проверьте заказ 👇 Если всё верно — нажмите «✅ Подтвердить» 😊", lang)


# Mijoz kartani yozib tasdiqlasa — tugma bosilgandek (modelsiz).
_CONFIRM_WORDS = {
    "ha", "xa", "ha tasdiqlayman", "xa tasdiqlayman", "tasdiqlayman", "tasdiqlaymiz", "tasdiqlash",
    "tasdiq", "ha togri", "togri", "hammasi togri", "ha hammasi togri", "ok", "okey", "mayli",
    "ha mayli", "xop", "ha xop", "roziman", "ha roziman", "albatta", "ha albatta",
    "ҳа", "ха", "тасдиқлайман", "ҳа тасдиқлайман", "тасдиқлаймиз", "тўғри", "ҳа тўғри",
    "ҳаммаси тўғри", "майли", "ҳа майли", "хўп", "розиман",
    "да", "подтверждаю", "да подтверждаю", "всё верно", "все верно", "верно", "да верно",
    "yes", "confirm", "yes confirm",
}


def is_confirmation(text: str) -> bool:
    norm = re.sub(r"[ʻʼ‘’`´']", "", (text or "").lower())
    norm = " ".join(re.sub(r"[^\w\s]", " ", norm).split())
    return norm in _CONFIRM_WORDS


_CARD_PAY = re.compile(r"\b(?:karta\w*|kartochka\w*|plastik\w*|o'tkazaman|o'tkazamiz|o'tkazib\s+beraman|"
                       r"perevod\w*|карт\w*|перевод\w*|переведу|card|click|payme)\b", re.IGNORECASE)
_CASH_PAY = re.compile(r"\b(?:naqd\w*|нақд\w*|налич\w*|cash)\b", re.IGNORECASE)


def payment_choice(text: str) -> str | None:
    """Karta ochiq paytdagi qisqa 'karta bilan' / 'naqd' — kartadagi to'lov
    tugmasi bosilgandek. Jonli sinov (2026-10-16): mijoz 'kartaga o'tkazaman'
    dedi, model karta raqamini o'zi berdi, kartada esa naqd qolib, buyurtma naqd
    tushdi. Uzun gap modelga qoladi (u kartani tolov_turi bilan qayta ochadi)."""
    norm = _same_apostrophes(text or "").lower()
    if len(norm.split()) > 6:
        return None
    card, cash = bool(_CARD_PAY.search(norm)), bool(_CASH_PAY.search(norm))
    if card == cash:
        return None
    return "online" if card else "cash"


async def _switch_card_payment(bot: Bot | None, message: Message, state: FSMContext,
                               choice: str) -> None:
    user = message.from_user
    data = await state.get_data()
    lang = data.get("lang") or await _lang(user.id)
    if data.get("online_only") and choice == "cash":
        reply = _t("Bu yetkazish usulida to'lov faqat karta orqali oldindan 😊",
                   "При этом способе доставки оплата только картой заранее 😊", lang)
    else:
        await state.update_data(payment_method=choice)
        reply = (_t("Mayli, karta orqali to'laysiz 😊 «✅ Tasdiqlash» dan keyin karta raqami chiqadi.",
                    "Хорошо, оплата картой 😊 После «✅ Подтвердить» придут реквизиты карты.", lang)
                 if choice == "online" else
                 _t("Mayli, naqd to'laysiz 😊", "Хорошо, оплата наличными 😊", lang))
        _session(user.id)["note"] = (f"[Mijoz kartada to'lovni {'karta' if choice == 'online' else 'naqd'}"
                                     "ga o'zgartirdi — karta yangilandi.]")
    await message.answer(reply)
    await _send_card(message, state)
    await log_conversation(bot, user, f"👤 {_esc(_short(message.text, 200))}\n🤖 {_esc(reply)}")


class _CardMessage:
    """CallbackQuery.message o'rnida: tasdiq handleri kartani tahrirlaydi."""

    def __init__(self, bot: Bot | None, message: Message, card_id: int | None):
        self._bot, self._message, self._card_id = bot, message, card_id

    async def edit_text(self, text, reply_markup=None, parse_mode=None, **_):
        if self._bot is not None and self._card_id:
            try:
                await self._bot.edit_message_text(text=text, chat_id=self._message.chat.id,
                                                  message_id=self._card_id,
                                                  reply_markup=reply_markup, parse_mode=parse_mode)
                return
            except Exception:
                logger.debug("AI card edit failed — sending anew", exc_info=True)
        await self._message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)

    async def answer(self, text, **kwargs):
        return await self._message.answer(text, **kwargs)


class _TypedConfirm:
    """CallbackQuery o'rnida: mijoz «✅ Tasdiqlash» o'rniga 'ha' deb yozdi."""

    def __init__(self, bot: Bot | None, message: Message, card_id: int | None):
        self.from_user = message.from_user
        self.bot = bot
        self.message = _CardMessage(bot, message, card_id)
        self._message = message

    async def answer(self, text=None, show_alert=False, **_):
        if text and show_alert:
            await self._message.answer(text)


async def _confirm_typed(bot: Bot | None, message: Message, state: FSMContext) -> None:
    """Karta ochiq, mijoz 'ha' deb yozdi — tugmali checkout ning o'z tasdiq
    handleri ishlaydi. Model chaqirilmaydi: na qaror, na buyurtma uniki."""
    from handlers.cart import order_confirm_yes
    await log_conversation(bot, message.from_user, f"👤 {_esc(_short(message.text, 200))}")
    await order_confirm_yes(_TypedConfirm(bot, message, _session(message.from_user.id).get("card_msg")),
                            state, bot)


async def checkout_event(bot: Bot | None, user, event: str, order_id: int | None = None,
                         items: list[dict] | None = None, total: float = 0,
                         payment_method: str | None = None) -> None:
    """handlers/cart.py dan: AI ochgan kartaning taqdiri. Buyurtma — AI savdosi
    (🎉 va kunlik hisob); ikkala holda ham AI keyingi javobida biladi."""
    session = _sessions.get(user.id)
    if event == "placed":
        paid = "karta (chek keldi)" if payment_method == "online" else "naqd"
        if session is not None:
            session["placed"] = order_id
            session["note"] = (f"[Mijoz «✅ Tasdiqlash» ni bosdi: buyurtma #{order_id} tuzildi, jami "
                               f"{_fmt(total)} so'm, to'lov {paid}. Rahmat xabari va yetkazish "
                               "vaqtini bot yubordi.]")
        await _celebrate(bot, user, order_id, items or [], total,
                         "karta" if payment_method == "online" else "naqd")
    elif event == "cancelled":
        if session is not None:
            session["note"] = "[Mijoz buyurtma kartasini bekor qildi — savat saqlanib turibdi.]"
        await log_conversation(bot, user, "❌ Buyurtma kartasini bekor qildi")


# Model o'zi qilmagan ishni "qildik" desa — bir marta qayta so'raladi.
_ORDER_CLAIM = re.compile(
    r"(?:buyurtma\w*|буюртма\w*)\s+(?:[#№]?\s?\d+\s+)?(?:qabul\s+qilindi|rasmiylashtirildi|tuzildi|"
    r"yaratildi|қабул\s+қилинди|расмийлаштирилди)"
    r"|заказ\w*\s+(?:[#№]?\s?\d+\s+)?(?:принят|оформлен|создан)"
    r"|order\s+(?:[#№]?\s?\d+\s+)?(?:has\s+been\s+|is\s+)?(?:placed|confirmed)",
    re.IGNORECASE)
_CART_CLAIM = re.compile(
    r"savat\w*\s+(?:\S+\s+){0,3}?(?:qo['ʻ’`‘]?shildi|qo['ʻ’`‘]?shdik|solindi|soldik)"
    r"|сават\w*\s+(?:\S+\s+){0,3}?(?:қўшилди|қўшдик|солинди)"
    r"|(?:добавил[иа]?|добавлен[аоы]?)\s+(?:\S+\s+){0,3}?в\s+корзину"
    r"|added\s+(?:\S+\s+){0,4}?to\s+(?:your\s+)?cart",
    re.IGNORECASE)
_ADD_TOOLS = {"savatga_qoshish", "set_qoshish"}


def false_claim(reply: str, done: set[str], session: dict) -> str | None:
    """Javob vositasiz bajarilgan ishni aytsa — modelga tuzatish izohi, aks holda None."""
    if _CART_CLAIM.search(reply or "") and not done & _ADD_TOOLS:
        return ("[TIZIM: bu javobda savatga hech narsa qo'shilmadi. Mijoz mahsulot olmoqchi "
                "bo'lsa — savatga_qoshish ni chaqir; aks holda 'qo'shdik' dema. Javobni qayta yoz.]")
    if _ORDER_CLAIM.search(reply or "") and not session.get("placed"):
        return ("[TIZIM: bu suhbatda buyurtma tuzilmagan — 'qabul qilindi' dema. Buyurtma faqat "
                "mijoz buyurtma_kartasi dagi «✅ Tasdiqlash» ni bosganda tuziladi. Mijoz oldingi "
                "buyurtmasini so'rayotgan bo'lsa — MIJOZ XOTIRASI dagi raqami va holatini ayt. "
                "Javobni qayta yoz.]")
    return None


def drop_order_claims(reply: str) -> str:
    """Qayta so'ralgandan keyin ham "buyurtma qabul qilindi" qolsa — o'sha gap olib
    tashlanadi: mijoz tuzilmagan buyurtmani tuzildi deb o'ylamasin."""
    parts = re.split(r"(?<=[.!?…])\s+|\n", reply or "")
    return "\n".join(p for p in parts if not _ORDER_CLAIM.search(p)).strip()


async def _pickup_place() -> tuple[str, str]:
    """Olib ketish manzili: admin panelidagi pickup sozlamasi yoqilgan bo'lsa —
    o'sha (tugmali checkout bilan bir xil), aks holda egasi bergan mo'ljal va havola."""
    try:
        import pickup
        config = pickup.public_config(await database.get_pickup_settings())
        if config["enabled"]:
            return config["address"], config["map_url"]
    except Exception:
        logger.warning("Pickup settings unavailable for AI", exc_info=True)
    return f"Do'kondan olib ketadi: {SHOP_LANDMARK}", SHOP_ADDRESS_URL


async def _run_tool(bot: Bot, message: Message, name: str, args: dict) -> str:
    user_id = message.from_user.id
    if name == "mahsulot_haqida":
        return await _tool_info(user_id, args)
    if name == "retsept":
        return await _tool_recipe(user_id, args)
    if name == "lokatsiya_tugmasi":
        _session(user_id)["keyboard"] = "location"
        return ("OK: javobing ostida '📍 Lokatsiyani yuborish' va '📞 Raqamni yuborish' "
                "tugmalari chiqadi. Mijozga pastdagi tugmani bosishini qisqa ayt.")
    if name == "savatga_qoshish":
        return await _tool_add(user_id, args)
    if name == "set_qoshish":
        return await _tool_add_set(user_id, args)
    if name == "savatni_korish":
        return await _tool_cart(user_id)
    if name == "savatdan_ochirish":
        return await _tool_remove(user_id, args)
    if name == "eslab_qol":
        return await _tool_remember(user_id, args)
    if name == "buyurtma_kartasi":
        return await _tool_card(message, args)
    if name == "javobsiz_savol":
        await database.log_ai_question(str(args.get("savol") or ""), user_id)
        return ("OK: savol adminlarga yozib qo'yildi. Endi mijozga uzr so'rab "
                "raqamimizni ber.")
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
        session = {"ai": {}, "last": time.time(), "orders": 0, "profiled": False,
                   "location": None, "phone": None, "awaiting_cheque": None}
        _sessions[user_id] = session
    return session


async def _opening_context(user_id: int) -> str:
    """Suhbat boshida modelga bir marta: mijoz xotirasi (buyurtmalar,
    qiziqishlar, fikr so'rash) va guruhda yaqinda nima so'ragani."""
    parts = []
    try:
        parts.append(await ai_memory.build_profile(user_id, await _lang(user_id)))
    except Exception:
        logger.warning("AI memory profile failed for %s", user_id, exc_info=True)
    carried = _group_context.pop(user_id, None)
    if carried and time.time() - carried[0] < GROUP_CONTEXT_TTL:
        parts.append(f"[Bu mijoz kanal guruhida yaqinda yozgan: «{_short(carried[1], 400)}». "
                     f"Unga guruhda shunday javob berilgan: «{_short(carried[2], 400)}». "
                     "Suhbatni shu yerdan davom ettir.]")
    return "\n\n".join(p for p in parts if p)


async def _respond(bot: Bot, message: Message, user_text: str) -> str:
    """Bitta mijoz xabari -> bitta javob. Ichida vosita chaqiruvlari tsikli:
    model savatga soladi/kartani ochadi, natijani o'qiydi va yakuniy matnni
    yozadi. MAX_TURNS — cheksiz tsiklga qarshi to'siq. Model qaysi
    provayderdan ekani bu yerda ahamiyatsiz — ai_provider.step() ikkalasini
    bir xil Turn ga keltiradi."""
    user_id = message.from_user.id
    session = _session(user_id)
    session["last"] = time.time()
    state = session.setdefault("ai", {})
    if not session.get("profiled"):
        session["profiled"] = True
        opening = await _opening_context(user_id)
        if opening:
            user_text = f"{opening}\n\n[MIJOZ XABARI]\n{user_text}"
    note = session.pop("note", None)   # karta tasdiqlandi / bekor qilindi (checkout_event)
    if note:
        user_text = f"{note}\n\n{user_text}"
    rules, catalog = _sales_rules(), await _dynamic_block(await _catalog_text())
    lang = await _lang(user_id)

    turn = await _step(state, rules, catalog, TOOLS, user=user_text,
                       max_tokens=MAX_TOKENS, history_limit=HISTORY_LIMIT)
    reply_text = ""
    done: set[str] = set()     # shu xabarda muvaffaqiyatli ishlagan vositalar
    corrected: set[str] = set()   # har tuzatish turi bir martadan
    russian = (session.get("cust_lang") or ("ru" if lang == "ru" else None)) == "ru"
    for attempt in range(MAX_TURNS):
        if turn.refused:
            logger.warning("AI sales refusal for user %s", user_id)
            return _t("Kechirasiz, bu savolga bu yerda javob bera olmayman.\n"
                      "Batafsil ma'lumot olish uchun: ",
                      "Извините, на этот вопрос здесь ответить не могу.\n"
                      "Подробнее по телефону: ", lang) + SUPPORT_PHONES
        reply_text = turn.text or reply_text
        if not turn.calls:
            # Jonli sinov va egasi (2026-10-16): model ba'zan vositani chaqirmay
            # "savatga qo'shdik" yoki "buyurtma qabul qilindi" deydi. Bir marta
            # qayta so'raymiz; buyurtma haqidagi yolg'on gap baribir qolmaydi.
            fix, kind = None, None
            if attempt < MAX_TURNS - 1:
                if "claim" not in corrected:
                    fix, kind = false_claim(reply_text, done, session), "claim"
                # Karta chiqadigan javob baribir qat'iy jumla bilan almashadi (_answer).
                if (fix is None and "lang" not in corrected and russian and not session.get("card")
                        and uzbek_reply(reply_text)):
                    fix, kind = RU_FIX, "lang"
            if fix is None:
                if not session.get("placed") and _ORDER_CLAIM.search(reply_text or ""):
                    reply_text = drop_order_claims(reply_text)
                if russian:
                    reply_text = drop_uzbek_lines(reply_text)
                return reply_text
            corrected.add(kind)
            logger.warning("AI sales reply needs a fix (%s, user %s) — asking again", kind, user_id)
            turn = await _step(state, rules, catalog, TOOLS, user=fix,
                               max_tokens=MAX_TOKENS, history_limit=HISTORY_LIMIT)
            continue

        results = []
        for call in turn.calls:
            try:
                output = await _run_tool(bot, message, call.name, call.args)
                is_error = output.startswith("Xato:")
            except Exception:
                logger.exception("AI tool %s failed", call.name)
                output, is_error = "Xato: ichki nosozlik.", True
            if not is_error:
                done.add(call.name)
            results.append(ai_provider.ToolResult(call.id, output, is_error))

        if attempt == MAX_TURNS - 1:
            break
        turn = await _step(state, rules, catalog, TOOLS, results=results,
                           max_tokens=MAX_TOKENS, history_limit=HISTORY_LIMIT)

    # Chegara: oxirgi vosita natijalari modelga qaytmadi. OpenAI zanjirida
    # javobsiz function_call qolsa keyingi xabar 400 beradi — tozalaymiz.
    ai_provider.reset(state)
    logger.warning("AI sales hit the tool-turn limit for user %s", user_id)
    return reply_text or (_t("Bir daqiqa kutib turing.\nBatafsil ma'lumot olish uchun: ",
                             "Минутку, пожалуйста.\nПодробнее по телефону: ", lang)
                          + SUPPORT_PHONES)


def _typing(bot: Bot | None, chat_id: int):
    """"yozmoqda..." — javob tayyor bo'lguncha. Testlarda bot yo'q."""
    if bot is None:
        return contextlib.nullcontext()
    return ChatActionSender.typing(bot=bot, chat_id=chat_id)


async def _batch(key: tuple, message: Message, text: str, handler) -> None:
    """Odam ketma-ket yozadi: "salom" / "eritritol bormi" / "narxi qancha".
    Har biriga alohida javob — robotning belgisi va ortiqcha pul. Xabarlar
    DEBOUNCE soniya jimlikkacha yig'iladi va bitta javob oladi.

    Bitta kalit (mijoz) uchun bir vaqtda bitta ishchi: javob tayyorlanayotganda
    kelgan xabar navbatga tushadi va keyingi aylanishda javob oladi. Bu provayder
    zanjirini ham himoya qiladi — ikki parallel so'rov bitta previous_response_id
    dan tarmoqlanib ketmaydi."""
    box = _inboxes.setdefault(key, {"texts": [], "busy": False})
    box["texts"].append(text)
    box["message"] = message
    box["at"] = time.monotonic()
    if box["busy"]:
        return
    box["busy"] = True
    try:
        while box["texts"]:
            while (wait := DEBOUNCE - (time.monotonic() - box["at"])) > 0:
                await asyncio.sleep(wait)
            texts, box["texts"] = box["texts"], []
            await handler(box["message"], "\n".join(texts))
    finally:
        box["busy"] = False
        if not box["texts"]:
            _inboxes.pop(key, None)


async def _reply(bot: Bot, message: Message, user_text: str) -> None:
    """Xabarni AI ga uzatadi — matn, lokatsiya va kontakt handlerlari shu
    bitta yo'ldan yuradi."""
    _session(message.from_user.id)
    await _batch(("p", message.from_user.id), message, user_text,
                 lambda msg, text: _answer(bot, msg, text))


async def _answer(bot: Bot, message: Message, user_text: str) -> None:
    user_id = message.from_user.id
    try:
        async with _typing(bot, message.chat.id):
            reply = await _respond(bot, message, user_text)
    except Exception:
        logger.exception("AI sales turn failed for user %s", user_id)
        ai_provider.reset(_session(user_id).setdefault("ai", {}))
        await _fallback_to_admins(bot, message, user_text)
        return
    session = _sessions.get(user_id) or {}
    fsm = session.get("fsm")
    # Karta shu xabarda ochildi yoki savat o'zgarib, ochiq karta eskirdi.
    want_card = session.pop("card", False) | session.pop("card_refresh", False)
    card_open = await ai_card_open(fsm)
    card = want_card and card_open
    if _is_paused(user_id):
        return   # javob tayyorlanguncha admin o'zi gapga kirdi — ustidan gapirmaymiz
    lang = await _lang(user_id)
    card_digits = re.sub(r"\D", "", PAYMENT_CARD_NUMBER or "")
    if card:
        # Kartadan oldin qat'iy jumla, mijoz tilida. Model yozgan xulosa yoki summa
        # kartadagidan farq qilishi mumkin edi — raqamlar faqat kartada.
        reply = _card_intro(lang)
    elif card_open and card_digits and card_digits in re.sub(r"\D", "", reply or ""):
        # Karta ochiq — to'lov kartada tanlanadi, karta raqamini tasdiqdan keyin
        # checkout o'zi beradi (aks holda mijoz to'laydi-yu, buyurtma naqd tushadi).
        reply = _t("Karta bilan to'lash uchun kartadagi «💳 Karta orqali to'layman» ni bosing — "
                   "«✅ Tasdiqlash» dan keyin karta raqami o'zi chiqadi 😊",
                   "Чтобы оплатить картой, нажмите в заказе «💳 Оплачу картой» — после "
                   "«✅ Подтвердить» придут реквизиты 😊", lang)
    elif reply:
        # Modelning o'z matni — yozuv, ism va minnatdorchilik tekshiruvidan o'tadi.
        reply = polish_reply(reply, lang, customer_text=user_text)
        names = customer_names(message.from_user, user_text, session.get("names", ()))
        session.setdefault("names", set()).update(names)
        reply = thank_politely(strip_name_address(reply, names))
    if not reply:
        return
    session = _sessions.get(user_id)
    if session and session.get("keyboard") == "location" and SHOP_ADDRESS_URL in reply:
        session.pop("keyboard", None)   # do'kon manzili haqida — mijoz lokatsiyasi kerak emas
    await message.answer(reply, reply_markup=await _reply_keyboard(user_id))
    if card and await _send_card(message, fsm):
        reply += "\n🧾 [buyurtma kartasi ko'rsatildi]"
    await _mirror(bot, message, user_text, reply)
    if user_id not in ADMIN_IDS and user_id not in database.LEADERBOARD_EXCLUDED_USER_IDS:
        await ai_stats.record_turn(user_id, "bot", user_text)   # /ai_hisobot


async def _reply_keyboard(user_id: int):
    """Javob ostidagi pastki klaviatura: AI lokatsiya so'ragan bo'lsa —
    '📍 Lokatsiyani yuborish' + '📞 Raqamni yuborish'; lokatsiya/kontakt kelgach
    yoki buyurtma tushgach — odatdagi 🏠/🛒 menyu qaytadi. Boshqa paytda None —
    klaviatura o'zgarmaydi."""
    session = _sessions.get(user_id) or {}
    want = session.pop("keyboard", None)
    if not want:
        return None
    lang = await _lang(user_id)
    if want == "location":
        return ReplyKeyboardMarkup(keyboard=[
            [KeyboardButton(text=_t("📍 Lokatsiyani yuborish", "📍 Отправить локацию", lang),
                            request_location=True)],
            [KeyboardButton(text=_t("📞 Raqamni yuborish", "📞 Отправить номер", lang),
                            request_contact=True)],
        ], resize_keyboard=True, one_time_keyboard=True)
    try:
        from keyboards import persistent_menu_keyboard
        return persistent_menu_keyboard(lang)
    except Exception:
        return None


async def _fallback_to_admins(bot: Bot | None, message: Message, user_text: str) -> None:
    """Model javob bera olmadi (API o'chiq, kalit yoki model xatosi). Mijoz
    uzr emas, odatdagi "xabaringiz qabul qilindi" ni oladi, savoli esa
    support_relay kartochkasi bo'lib adminlarga boradi — hech narsa yo'qolmaydi."""
    try:
        from handlers.support_relay import relay_text
        await relay_text(message, bot, user_text)
    except Exception:
        logger.exception("AI fallback relay failed for %s", message.from_user.id)
        await message.answer(_t("Xabaringiz qabul qilindi. Batafsil ma'lumot olish uchun: ",
                                "Сообщение получено. Подробнее по телефону: ",
                                await _lang(message.from_user.id)) + SUPPORT_PHONES)


# ───────────────────────── sinov rejimi: adminlarga nusxa ─────────────────────

def _mirror_kb(user_id: int, paused: bool = False) -> InlineKeyboardMarkup:
    toggle = (InlineKeyboardButton(text="▶️ AI qaytsin", callback_data=f"airesume:{user_id}")
              if paused else
              InlineKeyboardButton(text="⏸ AI to'xtasin", callback_data=f"aipause:{user_id}"))
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ Javob berish", callback_data=f"freereply:{user_id}"), toggle],
        [InlineKeyboardButton(text="🧠 Mijoz xotirasi", callback_data=f"aimem:{user_id}")],
    ])


# ───────────────────── mijozlar suhbatlari — guruh mavzusi ─────────────────────
# Egasi, 2026-10-13: "hadeb adminlarga mijozlar bilan bo'lgan suhbat kelavermasin,
# guruhga yubor ... bitta mijozni suhbatini edit qilib qo'shib bitta xabarda qil,
# character limitga urilsa keyingi xabar, o'sha mijoz 1 soatdan keyin yozsa yangi
# xabar". Joy — admin o'sha mavzu (topic) ichida /ai_mavzu yozganda saqlanadi.
# Belgilanmaguncha nusxa avvalgidek adminlarga boradi (har javob alohida).

LOG_CHAT_SETTING, LOG_THREAD_SETTING = "log_chat", "log_thread"
LOG_MAX_CHARS = 3800          # Telegram chegarasi 4096 — sarlavha va HTML uchun zaxira
LOG_NEW_AFTER = 3600          # 1 soat jimlikdan keyin — yangi xabar
_chat_logs: dict[int, dict] = {}     # user_id -> {"msg": (chat, id) | None, "entries", "part", "last", "who"}
_last_question: dict[int, str] = {}  # user_id -> mijozning oxirgi o'z matni ("AI ga o'rgat" uchun)
_chat_log_locks: dict[int, asyncio.Lock] = {}


async def _log_destination() -> tuple[int, int | None] | None:
    """(chat_id, thread_id) — /ai_mavzu bilan belgilangan joy, yo'q bo'lsa None."""
    values = await _load_settings()
    chat = values.get(LOG_CHAT_SETTING)
    if not chat:
        return None
    thread = int(values.get(LOG_THREAD_SETTING) or 0)
    return int(chat), (thread or None)


def _esc(text) -> str:
    """Matn ichida apostrof va qo'shtirnoq escape shart emas — o'zbekcha matn
    o'qiladigan qolsin va 4096 belgiga ko'proq sig'sin."""
    return html.escape(str(text), quote=False)


def _who(user) -> str:
    return (_esc(getattr(user, "full_name", None) or "—")
            + (f" (@{_esc(user.username)})" if getattr(user, "username", None) else ""))


def _log_render(user_id: int, log: dict) -> str:
    part = f" · davomi {log['part']}" if log["part"] > 1 else ""
    return (f"💬 <b>{log['who']}</b> · <code>{user_id}</code>{part}\n\n"
            + "\n\n".join(log["entries"]))


async def log_conversation(bot: Bot | None, user, entry: str) -> bool:
    """Mijoz suhbatiga bitta yozuv qo'shadi (`entry` — tayyor HTML). Joy belgilangan
    bo'lsa — mijozning hozirgi xabarini tahrirlaydi yoki yangisini ochadi va True;
    belgilanmagan yoki yetib bo'lmasa — False (chaqiruvchi o'zi hal qiladi)."""
    if bot is None or user is None:
        return False
    try:
        if not await setting("mirror"):
            return True    # o'chirilgan — hech qayerga yubormaymiz
        dest = await _log_destination()
    except Exception:
        return False
    if dest is None:
        return False
    lock = _chat_log_locks.setdefault(user.id, asyncio.Lock())
    async with lock:
        now = time.time()
        log = _chat_logs.get(user.id)
        if log is None or now - log["last"] > LOG_NEW_AFTER or log.get("dest") != dest:
            log = {"msg": None, "entries": [], "part": 1, "last": now, "who": _who(user), "dest": dest}
            _chat_logs[user.id] = log
        stamp = time.strftime("%H:%M", time.gmtime(now + 5 * 3600))   # Toshkent
        log["entries"].append(f"<i>{stamp}</i>\n{entry}")
        log["last"] = now
        text = _log_render(user.id, log)
        if log["msg"] and len(text) > LOG_MAX_CHARS:
            log.update(msg=None, entries=log["entries"][-1:], part=log["part"] + 1)
            text = _log_render(user.id, log)
        if len(text) > LOG_MAX_CHARS:
            text = text[:LOG_MAX_CHARS] + "…"
        keyboard = _mirror_kb(user.id, paused=_is_paused(user.id))
        if log["msg"]:
            chat, message_id = log["msg"]
            try:
                await bot.edit_message_text(text=text, chat_id=chat, message_id=message_id,
                                            parse_mode="HTML", reply_markup=keyboard)
                return True
            except Exception:
                logger.debug("AI chat log edit failed for %s — sending a new one", user.id)
                log["msg"] = None
        chat, thread = dest
        try:
            sent = await bot.send_message(chat, text, message_thread_id=thread, parse_mode="HTML",
                                          reply_markup=keyboard, disable_notification=True)
        except Exception:
            logger.warning("AI chat log to %s/%s failed", chat, thread, exc_info=True)
            return False
        log["msg"] = (chat, sent.message_id)
        return True


async def log_admin_reply(bot: Bot | None, buyer_id: int, admin_name: str, text: str) -> None:
    """Admin mijozga javob berdi (support_relay / buyurtma ekrani) — shu suhbatga."""
    try:
        user = await database.get_user(buyer_id)
        who = type("U", (), {"id": buyer_id, "full_name": (user or {}).get("full_name") or "—",
                             "username": (user or {}).get("username")})()
        await log_conversation(bot, who, f"👨‍💼 <b>{_esc(admin_name)}</b>: "
                                         f"{_esc(_short(text, 1200))}")
    except Exception:
        logger.warning("AI chat log: admin reply for %s not logged", buyer_id, exc_info=True)


async def log_customer_message(bot: Bot | None, user, text: str) -> None:
    """AI javob bermagan mijoz xabari (AI to'xtatilgan, o'chiq yoki xato) — shu
    suhbatga, adminlarga boradigan relay kartochkasidan tashqari."""
    _remember_question(user.id, text)
    try:
        await log_conversation(bot, user, f"👤 {_esc(_short(text, 900))}\n"
                                          "<i>↪️ operatorlarga yuborildi</i>")
    except Exception:
        logger.warning("AI chat log: customer message not logged", exc_info=True)


async def _mirror(bot: Bot | None, message: Message, user_text: str, reply: str) -> None:
    """Har bir AI javobi mijoz xabari bilan birga mijozlar suhbatlari mavzusiga
    (bitta suhbat — bitta xabar). Mavzu belgilanmagan bo'lsa — eski yo'l:
    adminlarga ovozsiz alohida nusxa."""
    user = message.from_user
    if bot is None or user.id in ADMIN_IDS:
        return
    _remember_question(user.id, user_text)
    entry = (f"👤 {_esc(_short(user_text, 900))}\n"
             f"🤖 {_esc(_short(reply, MIRROR_TEXT_MAX))}")
    if await log_conversation(bot, user, entry):
        return
    try:
        if not await setting("mirror"):
            return
    except Exception:
        return
    body = f"💬 <b>AI suhbati</b> · {_who(user)} · <code>{user.id}</code>\n\n{entry}"
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, body, parse_mode="HTML",
                                   reply_markup=_mirror_kb(user.id), disable_notification=True)
        except Exception:
            logger.debug("AI mirror to admin %s failed", admin_id)


# ─────────────────────────── "🧠 AI ga o'rgat" ────────────────────────────
# Egasi, 2026-10-13: admin mijozga to'g'ri javob yozsa, bir bosishda u AI
# bilimiga aylansin. "✅ Yuborildi." ostida tugma chiqadi; bosilsa mijozning
# oxirgi savoli + adminning javobi /ai_orgat bilan bir xil faktga aylanadi
# (har suhbatda promptda, /ai_unut bilan o'chiriladi). Juftlik xotirada
# saqlanadi — bot qayta ishga tushsa tugma "muddati o'tdi" deydi.

TEACH_TTL = 24 * 3600
_teach_pending: dict[str, tuple[str, str, float]] = {}


def _remember_question(user_id: int, text: str) -> None:
    text = (text or "").strip()
    # "[Mijoz lokatsiyasini yubordi ...]" kabi tizim belgilari savol emas.
    if text and not text.startswith("["):
        _last_question[user_id] = text


def teach_keyboard(buyer_id: int, answer: str) -> InlineKeyboardMarkup | None:
    """Admin javobi ostidagi "🧠 AI ga o'rgat" tugmasi — mijozning oxirgi savoli
    ma'lum bo'lsa. Yo'q bo'lsa None (tugma chiqmaydi)."""
    import secrets
    question = _last_question.get(buyer_id)
    answer = (answer or "").strip()
    if not question or not answer:
        return None
    now = time.time()
    for token in [t for t, item in _teach_pending.items() if now - item[2] > TEACH_TTL]:
        _teach_pending.pop(token, None)
    token = secrets.token_hex(4)
    _teach_pending[token] = (_short(question, 400), _short(answer, 600), now)
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🧠 AI ga o'rgat (hammaga tegishli javob bo'lsa)",
                             callback_data=f"aiteach:{token}"),
    ]])


@router.callback_query(F.data.startswith("aiteach:"))
async def cb_teach(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer()
        return
    item = _teach_pending.pop(callback.data.split(":", 1)[1], None)
    if item is None:
        await callback.answer("Muddati o'tdi — /ai_orgat bilan o'rgating.", show_alert=True)
        return
    question, answer, _ = item
    fact = f"Mijoz so'rasa: «{question}» — to'g'ri javob: «{answer}»"[:1000]
    try:
        item_id = await database.add_ai_fact(fact, callback.from_user.id)
    except Exception:
        logger.exception("AI teach from a reply failed")
        _teach_pending[callback.data.split(":", 1)[1]] = item
        await callback.answer("⚠️ Saqlab bo'lmadi, qayta urinib ko'ring.", show_alert=True)
        return
    invalidate_knowledge()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await callback.message.answer(
        f"🧠 AI ga o'rgatildi (#{item_id}) — keyingi suhbatdan boshlab shunday javob beradi.\n"
        f"O'chirish: <code>/ai_unut {item_id}</code>", parse_mode="HTML")
    await callback.answer("🧠 O'rgatildi")


# ───────────────────── AI karta buyurtmasi: to'lov tasdig'i ─────────────────────
# AI buyurtmani pul kelmasdan tuzadi (payment_method='cash', izoh "To'lov: KARTA").
# Kartochkalarda "❗ TO'LANMAGAN" (handlers/cart.card_payment_state); chek kelgach
# admin chek ostidagi tugmani bosadi — buyurtma tugmali karta buyurtmasi kabi
# 'online' (to'langan) bo'ladi. To'lov holatini faqat admin o'zgartiradi.

def _paid_kb(order_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ To'lov tasdiqlandi", callback_data=f"aipaid:{order_id}"),
    ]])


async def mark_card_paid(order_id: int) -> bool:
    """AI karta buyurtmasini to'langan qiladi. Faqat hali to'lanmagan KARTA
    buyurtmasiga ta'sir qiladi; ikkinchi bosish hech narsa o'zgartirmaydi."""
    async with database.pool.acquire() as conn:
        result = await conn.execute(
            """UPDATE orders
                  SET payment_method = 'online',
                      address_note = REPLACE(address_note, 'KARTA (chek kutilmoqda)', 'KARTA (to''langan)')
                WHERE id = $1 AND COALESCE(payment_method, 'cash') <> 'online'
                  AND COALESCE(address_note, '') LIKE '%KARTA%'""", order_id)
    return str(result).strip().endswith(" 1")


@router.callback_query(F.data.startswith("aipaid:"))
async def cb_card_paid(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer()
        return
    order_id = int(callback.data.split(":", 1)[1])
    try:
        changed = await mark_card_paid(order_id)
    except Exception:
        logger.exception("Card payment of order %s could not be confirmed", order_id)
        await callback.answer("⚠️ Saqlab bo'lmadi, qayta urinib ko'ring.", show_alert=True)
        return
    who = callback.from_user.username and f"@{callback.from_user.username}" or (callback.from_user.full_name or "admin")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
        caption = (callback.message.caption or "").strip()
        await callback.message.edit_caption(
            caption=f"{html.escape(caption)}\n\n✅ To'lov tasdiqlandi — {html.escape(who)}", parse_mode="HTML")
    except Exception:
        pass
    await callback.answer(f"✅ #{order_id} to'langan deb belgilandi." if changed
                          else f"#{order_id} allaqachon to'langan.", show_alert=not changed)


@router.message(Command("ai_mavzu"))
async def cmd_ai_topic(message: Message, bot: Bot):
    """Mijozlar suhbatlari tushadigan joyni belgilash: admin shu buyruqni kerakli
    guruh mavzusi (topic) ichida yozadi — bot guruh va mavzu id sini saqlaydi.
    group_quiet guruhdagi buyruqni faqat ADMIN_COMMANDS da bo'lsa o'tkazadi."""
    user = message.from_user
    if user is None or user.id not in ADMIN_IDS or message.sender_chat is not None:
        return
    if not is_owner(user.id):
        await message.answer(OWNER_DENIED)
        return
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Bu buyruqni mijozlar suhbatlari tushishi kerak bo'lgan guruh "
                             "mavzusining (topic) ichida yozing.")
        return
    thread = message.message_thread_id if getattr(message, "is_topic_message", False) else None
    await set_setting(LOG_CHAT_SETTING, str(message.chat.id), user.id)
    await set_setting(LOG_THREAD_SETTING, str(thread or 0), user.id)
    _chat_logs.clear()    # keyingi yozuvlar yangi joyda yangi xabardan boshlansin
    try:
        await message.delete()
    except Exception:
        pass
    await bot.send_message(message.chat.id,
                           "✅ Mijozlar bilan bot suhbatlari endi shu yerga tushadi: har bir "
                           "mijoz — bitta xabar (yangilanib boradi), 1 soat jimlikdan keyin — "
                           "yangi xabar.", message_thread_id=thread, disable_notification=True)


@router.callback_query(F.data.startswith("aipause:"))
async def cb_pause(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer()
        return
    user_id = int(callback.data.split(":")[1])
    pause_for_human(user_id)
    try:
        await callback.message.edit_reply_markup(reply_markup=_mirror_kb(user_id, paused=True))
    except Exception:
        pass
    await callback.answer(f"⏸ Bu mijozga AI {HUMAN_PAUSE // 3600} soat javob bermaydi — "
                          f"yozsa, xabari sizga keladi.", show_alert=True)


@router.callback_query(F.data.startswith("airesume:"))
async def cb_resume(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer()
        return
    user_id = int(callback.data.split(":")[1])
    resume(user_id)
    try:
        await callback.message.edit_reply_markup(reply_markup=_mirror_kb(user_id))
    except Exception:
        pass
    await callback.answer("▶️ AI bu mijozga yana javob beradi.")


@router.callback_query(F.data.startswith("aimem:"))
async def cb_memory(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer()
        return
    user_id = int(callback.data.split(":")[1])
    await callback.message.answer(await _memory_card(user_id), parse_mode="HTML")
    await callback.answer()


async def _memory_card(user_id: int) -> str:
    try:
        text = await ai_memory.build_profile(user_id, await _lang(user_id), mark_asked=False)
    except Exception:
        logger.exception("AI memory card failed for %s", user_id)
        return "⚠️ Xotirani o'qib bo'lmadi."
    lines = text.splitlines()[1:]   # birinchi qator — modelga ko'rsatma
    paused = " · ⏸ AI to'xtatilgan" if _is_paused(user_id) else ""
    return (f"🧠 <b>Mijoz xotirasi</b> · <code>{user_id}</code>{paused}\n\n"
            + html.escape(_short("\n".join(lines), 3500))
            + f"\n\n<i>O'chirish: /ai_mijoz_unut {user_id}</i>")


# ──────────────────────────────── handlerlar ────────────────────────────────

@router.message(Command("ai"))
async def cmd_ai_on(message: Message):
    user_id = message.from_user.id
    if not await _allowed(user_id):
        return
    if not await _ready():
        if user_id in ADMIN_IDS:
            await message.answer("⚠️ AI kaliti yo'q — AI sotuvchi o'chiq. OpenAI kalitini botga "
                                 "shaxsiy chatda yuboring: <code>/ai_kalit sk-...</code>",
                                 parse_mode="HTML")
        return
    _opted_out.discard(user_id)
    resume(user_id)
    _sessions.pop(user_id, None)   # har /ai yangi suhbat
    _session(user_id)
    if user_id in ADMIN_IDS:
        text = ("🤖 <b>AI sotuvchi — yangi suhbat.</b>\n\n"
                "Oddiy mijozdek yozing: mahsulot tanlaydi, savatga soladi, "
                "lokatsiya/telefon so'raydi va buyurtma kartasini ochadi.\n\n"
                "O'chirish: /ai_off · Holat: /ai_holat")
    else:
        # Mijoz ko'radigan matn — kim bilan yozishayotgani haqida ortiqcha gap yo'q.
        text = _t("Assalomu alaykum, Keto shopga xush kelibsiz! 🌿\n\n"
                  "Nima qidiryapsiz? Yozing — mahsulot tanlashga yordam beramiz va "
                  "buyurtmangizni rasmiylashtiramiz.",
                  "Ассалому алайкум, добро пожаловать в Keto shop! 🌿\n\n"
                  "Что ищете? Напишите — помогу выбрать и оформлю заказ.",
                  await _lang(user_id))
    await message.answer(text, parse_mode="HTML")


@router.message(Command("ai_off"))
async def cmd_ai_off(message: Message):
    user_id = message.from_user.id
    if not await _allowed(user_id):
        return
    _sessions.pop(user_id, None)
    _opted_out.add(user_id)
    if user_id in ADMIN_IDS:
        await message.answer("🤖 AI sizning chatingizda o'chdi. Qayta yoqish: /ai")
    else:
        await message.answer(_t("Xo'p! Endi xabarlaringizga xodimimiz javob beradi.",
                                "Хорошо! Теперь на ваши сообщения ответит наш сотрудник.",
                                await _lang(user_id)))


def _settings_kb(values: dict) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"{'✅' if values.get(key, '1' if default else '0') == '1' else '⚪'} "
                 f"{_SETTING_LABELS[key]}",
            callback_data=f"aiset:{key}")]
        for key, default in _SETTING_DEFAULTS.items()
    ]
    for name in model_options():
        price = ai_provider.price_for(name)
        mark = "✅ " if PROVIDER and name == PROVIDER.model else ""
        rows.append([InlineKeyboardButton(
            text=f"{mark}{name} · ${price[0]:g} / ${price[2]:g} (1M token)",
            callback_data=f"aimodel:{name}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _log_status() -> str:
    chat = _settings["values"].get(LOG_CHAT_SETTING)
    if not chat:
        return "mavzu belgilanmagan — adminlarga boradi (mavzu ichida /ai_mavzu yozing)"
    thread = int(_settings["values"].get(LOG_THREAD_SETTING) or 0)
    return f"guruh <code>{html.escape(chat)}</code>" + (f", mavzu <code>{thread}</code>" if thread else "")


async def _status_text() -> str:
    _prune_sessions()
    catalog = await _catalog_text() if await _ready() else ""
    linked = _linked["id"]
    groups = sorted(GROUP_CHATS | ({linked} if linked else set()))
    lines = [
        "🤖 <b>AI sotuvchi</b>", "",
        f"Holat: {'✅ yoqilgan' if is_enabled() else '⚠️ kalit yo`q (o`chiq)'}",
        f"Kalit: {_key_status()}",
        f"Suhbatlar: {_log_status()}",
        f"Provayder: <b>{PROVIDER.name if PROVIDER else '—'}</b> · "
        f"model <code>{html.escape(MODEL or '—')}</code> (effort: {EFFORT})",
        f"Ochiq suhbatlar: {len(_sessions)} · to'xtatilgan mijozlar: "
        f"{sum(1 for u in list(_paused) if _is_paused(u))}",
        f"Guruhlar: {', '.join(f'<code>{g}</code>' for g in groups) if groups else 'topilmadi'}"
        f" (soatiga ≤{GROUP_MAX_PER_HOUR} javob)",
        f"Katalogda: {sum(1 for l in catalog.splitlines() if l[:1].isdigit())} ta mahsulot",
    ]
    try:
        lines += [""] + usage_lines(await database.get_ai_usage_today(),
                                    await database.get_ai_usage_month())
    except Exception:
        logger.warning("AI usage lookup failed", exc_info=True)
    lines += [
        "",
        "<i>Tugmalar bir zumda yoqadi/o'chiradi va modelni almashtiradi (narx — "
        "kirish / chiqish, 1M token uchun; arzon model kamroq aqlli bo'lishi mumkin, "
        "nusxalarda javob sifatini kuzating). Adminlar uchun AI har doim ochiq. Siz "
        f"mijozga javob bersangiz, AI unga {HUMAN_PAUSE // 3600} soat jim turadi.</i>",
    ]
    return "\n".join(lines)


@router.message(Command("ai_holat"))
async def cmd_ai_status(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    await _load_settings()
    if CHANNEL_GROUP:
        await _channel_group(message.bot)
    owner = is_owner(message.from_user.id)
    await message.answer(await _status_text() + ("" if owner else "\n\n" + OWNER_DENIED),
                         parse_mode="HTML",
                         reply_markup=_settings_kb(_settings["values"]) if owner else None)


@router.callback_query(F.data.startswith("aiset:"))
async def cb_setting(callback: CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer(OWNER_DENIED, show_alert=True)
        return
    key = callback.data.split(":", 1)[1]
    if key not in _SETTING_DEFAULTS:
        await callback.answer()
        return
    new = not await setting(key)
    try:
        await set_setting(key, "1" if new else "0", callback.from_user.id)
    except Exception:
        logger.exception("AI setting %s could not be saved", key)
        await callback.answer("⚠️ Saqlab bo'lmadi, qayta urinib ko'ring.", show_alert=True)
        return
    try:
        await callback.message.edit_text(await _status_text(), parse_mode="HTML",
                                         reply_markup=_settings_kb(_settings["values"]))
    except Exception:
        pass
    await callback.answer(f"{_SETTING_LABELS[key]}: {'yoqildi ✅' if new else 'o`chirildi ⚪'}")


@router.callback_query(F.data.startswith("aimodel:"))
async def cb_model(callback: CallbackQuery):
    if not is_owner(callback.from_user.id):
        await callback.answer(OWNER_DENIED, show_alert=True)
        return
    name = callback.data.split(":", 1)[1]
    if name not in model_options():
        await callback.answer("Bu model mavjud emas.", show_alert=True)
        return
    try:
        await set_setting("model", name, callback.from_user.id)
    except Exception:
        logger.exception("AI model choice could not be saved")
        await callback.answer("⚠️ Saqlab bo'lmadi, qayta urinib ko'ring.", show_alert=True)
        return
    _apply_model(name)
    try:
        await callback.message.edit_text(await _status_text(), parse_mode="HTML",
                                         reply_markup=_settings_kb(_settings["values"]))
    except Exception:
        pass
    await callback.answer(f"Model: {name} ✅")


@router.message(Command("ai_kalit"))
async def cmd_ai_key(message: Message):
    """/ai_kalit sk-... — kalitni berish; /ai_kalit — holat; /ai_kalit off —
    bot orqali berilganini o'chirish (serverdagi env ga qaytadi)."""
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = (message.text or "").split(maxsplit=1)
    arg = parts[1].strip() if len(parts) > 1 else ""

    if message.chat.type != "private":
        # Guruhda kalit hammaga ko'rinadi — saqlamaymiz, xabarni o'chiramiz.
        if arg:
            try:
                await message.delete()
            except Exception:
                pass
        await message.answer("⚠️ Kalitni faqat bot bilan shaxsiy chatda yuboring.")
        return

    if not arg:
        _settings["at"] = float("-inf")
        await _load_settings()
        await message.answer(f"🔑 <b>AI kaliti:</b> {_key_status()}\n"
                             f"Model: <code>{html.escape(MODEL or '—')}</code>\n\n"
                             "Yangi kalit: <code>/ai_kalit sk-...</code> · o'chirish: "
                             "<code>/ai_kalit off</code>", parse_mode="HTML")
        return

    if not is_owner(message.from_user.id):
        # Kalit xabari baribir o'chirilsin — chatda qolmasin.
        try:
            await message.delete()
        except Exception:
            pass
        await message.answer(OWNER_DENIED)
        return

    if arg.lower() in _KEY_OFF_WORDS:
        await _delete_setting(KEY_SETTING)
        _drop_bot_key()
        await message.answer("🗑 Bot orqali berilgan kalit o'chirildi. Hozir: " + _key_status(),
                             parse_mode="HTML")
        return

    # Avval xabarni o'chiramiz — kalit chat tarixida qolmasin.
    try:
        await message.delete()
        deleted = True
    except Exception:
        deleted = False
    candidate = arg.split()[0]
    if not candidate.startswith("sk-"):
        await message.answer("❌ Bu OpenAI kalitiga o'xshamaydi (u <code>sk-</code> bilan "
                             "boshlanadi). Saqlanmadi.", parse_mode="HTML")
        return
    model = _openai_model()
    error = await _verify_key(candidate, model)
    if error:
        await message.answer(f"❌ Kalit ishlamadi, saqlanmadi:\n<code>{html.escape(error)}</code>",
                             parse_mode="HTML")
        return
    await set_setting(KEY_SETTING, candidate, message.from_user.id)
    _apply_key(candidate)
    text = (f"✅ Kalit saqlandi (…{html.escape(candidate[-4:])}). Model: <code>{html.escape(MODEL)}</code>.\n"
            "AI sotuvchi ishlayapti — holat va tugmalar: /ai_holat")
    if not deleted:
        text += "\n\n⚠️ Kalitli xabaringizni o'chira olmadim — uni qo'lda o'chiring."
    await message.answer(text, parse_mode="HTML")


# ─────────────────────────── kunlik sarf hisoboti ────────────────────────────
# Egasi, 2026-10-13: "har kuni adminlarga o'sha kun qancha token va $
# ishlatilganini hisobotini berib bor". 20:00 dagi maqsad hisobotidagi AI
# bloki kun tugamasdan yoziladi va maqsadlar o'chirilsa umuman chiqmaydi —
# bu alohida, kun yakunidagi to'liq raqam.

REPORT_AT = (23, 58)            # Toshkent vaqti
REPORT_CATCHUP_FROM = 8         # o'tkazib yuborilgan kechagi hisobot — ertalabdan
REPORT_DAY_SETTING = "usage_report_day"
REPORT_CHECK_EVERY = 60


def _now_tk():
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=5)


async def _usage_for_day(day) -> tuple[list[dict], dict, int]:
    """(model bo'yicha qatorlar, oy boshidan shu kungacha jami, javobsiz savollar)."""
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT model, provider, requests, input_tokens, cached_tokens,
                      output_tokens, cost_usd
                 FROM ai_usage WHERE day = $1 ORDER BY cost_usd DESC""", day)
        month = await conn.fetchrow(
            """SELECT COALESCE(SUM(requests), 0) AS requests,
                      COALESCE(SUM(input_tokens), 0) AS input_tokens,
                      COALESCE(SUM(output_tokens), 0) AS output_tokens,
                      COALESCE(SUM(cost_usd), 0) AS cost_usd
                 FROM ai_usage WHERE day >= $1 AND day <= $2""", day.replace(day=1), day)
        questions = await conn.fetchval(
            """SELECT COALESCE(SUM(times), 0) FROM ai_knowledge
                WHERE kind = 'question' AND (created_at + INTERVAL '5 hours')::date = $1""", day)
    return [dict(r) for r in rows], dict(month) if month else {}, int(questions or 0)


def usage_report_text(day, rows: list[dict], month: dict, questions: int,
                      usd_rate: float | None, sales: dict | None = None, talks: str = "") -> str:
    requests = sum(int(r["requests"]) for r in rows)
    tokens_in = sum(int(r["input_tokens"]) for r in rows)
    cached = sum(int(r["cached_tokens"]) for r in rows)
    tokens_out = sum(int(r["output_tokens"]) for r in rows)
    cost = sum(float(r["cost_usd"]) for r in rows)
    lines = [f"🤖 <b>AI sarfi — {day:%d.%m.%Y}</b> (kun yakuni)", ""]
    if talks:
        lines += [talks, ""]
    if not rows:
        lines.append("Bugun AI ishlatilmadi — <b>$0.00</b>")
    else:
        som = f" ≈ {_fmt(cost * usd_rate)} so'm" if usd_rate else ""
        lines += [
            f"💵 Jami: <b>${cost:.2f}</b>{som}",
            f"🔢 {requests} so'rov · {fmt_tokens(tokens_in)} kirish token "
            f"({fmt_tokens(cached)} keshdan, arzon) · {fmt_tokens(tokens_out)} chiqish token",
        ]
        if len(rows) > 1:
            for row in rows:
                lines.append(f"   <code>{html.escape(row['model'])}</code> — {int(row['requests'])} so'rov · "
                             f"${float(row['cost_usd']):.2f}")
        else:
            lines.append(f"🧠 Model: <code>{html.escape(rows[0]['model'])}</code>")
    if month and int(month.get("requests") or 0):
        lines.append(f"📅 Oy boshidan: {int(month['requests'])} so'rov · "
                     f"{fmt_tokens(int(month['input_tokens']) + int(month['output_tokens']))} token · "
                     f"<b>${float(month['cost_usd']):.2f}</b>")
    if questions:
        lines.append(f"❓ AI javob bera olmagan savollar: <b>{questions} ta</b> — /ai_bilim")
    if sales is not None:
        lines += ["", "🛒 <b>AI sotuvlari</b> (bekor qilinganlarsiz)"]
        if sales["orders"]:
            lines.append(f"   {sales['orders']} ta buyurtma · {sales['products']} ta mahsulot · "
                         f"<b>{_fmt(sales['goods'])} so'm</b> (yetkazishsiz)")
            if rows and usd_rate:
                spent = sum(float(r["cost_usd"]) for r in rows) * usd_rate
                if spent > 0:
                    lines.append(f"   Har 1 so'm AI sarfiga — {_fmt(sales['goods'] / spent)} so'm sotuv")
        else:
            lines.append("   Bugun AI orqali buyurtma bo'lmadi.")
    lines += ["", "<i>O'chirish: /ai_holat → Kunlik sarf hisoboti</i>"]
    return "\n".join(lines)


async def _usage_report_tick(bot: Bot, now_tk=None):
    """Navbatdagi hisobot vaqti kelgan bo'lsa yuboradi; yuborilgan kunni
    qaytaradi (yoki None). Kun bazada YUBORISHDAN OLDIN belgilanadi —
    qayta ishga tushish hech qachon ikki marta yubormaydi."""
    from datetime import timedelta
    now = now_tk or _now_tk()
    values = await _load_settings()
    if not await setting("report"):
        return None
    today = now.date()
    if (now.hour, now.minute) >= REPORT_AT:
        due = today
    elif now.hour >= REPORT_CATCHUP_FROM:
        due = today - timedelta(days=1)
    else:
        return None
    last = values.get(REPORT_DAY_SETTING)
    if last is None and due != today:
        # Birinchi ishga tushish — o'tgan kunlar uchun hisobot yubormaymiz.
        await set_setting(REPORT_DAY_SETTING, due.isoformat())
        return None
    if last and last >= due.isoformat():
        return None
    await set_setting(REPORT_DAY_SETTING, due.isoformat())

    rows, month, questions = await _usage_for_day(due)
    if not rows and not is_enabled():
        return None   # AI umuman ishlamaydi — "$0.00" ni har kuni yubormaymiz
    rate = None
    try:
        from targets import current_usd_rate
        rate, _ = await current_usd_rate()
    except Exception:
        logger.warning("USD rate for the AI usage report unavailable", exc_info=True)
    try:
        sales = await ai_sales_for_day(due)
    except Exception:
        logger.warning("AI sales for the daily report unavailable", exc_info=True)
        sales = None
    text = usage_report_text(due, rows, month, questions, rate, sales, await ai_stats.day_line(due))
    for admin_id in list(dict.fromkeys(ADMIN_IDS)):
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML", disable_notification=True)
        except Exception:
            logger.debug("AI usage report to %s failed", admin_id)
        await asyncio.sleep(0.05)
    # ...va mijozlar suhbatlari mavzusiga (egasi: "bu folderga ... hisoblab borsin har kuni").
    try:
        dest = await _log_destination()
        if dest:
            await bot.send_message(dest[0], text, message_thread_id=dest[1], parse_mode="HTML",
                                   disable_notification=True)
    except Exception:
        logger.warning("AI usage report to the conversation topic failed", exc_info=True)
    logger.info("AI usage report for %s sent", due)
    return due


# ─────────────────────────── AI sotuvlari ────────────────────────────
# Egasi, 2026-10-13: "AI nechta va necha pullik mahsulot sotganini hisoblab
# borsin har kuni, mijozni sotuvgacha olib borsa tantanali xabar yuborsin".
# AI tuzgan buyurtma alohida jadvalda belgilanadi — orders.source ga tegilmaydi
# (bloger, referal, tahrir qoidalari shunga tayanadi). Hisob orders dan har safar
# yangidan: bekor qilingani tushib qoladi, admin tahrirlasa yangi summa.

_ai_orders_ready = False


async def _ensure_ai_orders(conn) -> None:
    global _ai_orders_ready
    if _ai_orders_ready:
        return
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_orders (
            order_id INTEGER PRIMARY KEY,
            user_id BIGINT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
        )
    """)
    _ai_orders_ready = True


async def record_ai_order(order_id: int, user_id: int) -> None:
    async with database.pool.acquire() as conn:
        await _ensure_ai_orders(conn)
        await conn.execute(
            "INSERT INTO ai_orders (order_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            order_id, user_id)


def _paid_lines(items) -> list[dict]:
    import json
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except ValueError:
            items = []
    return [i for i in items or [] if isinstance(i, dict) and not (i.get("is_bonus") or i.get("is_gift"))]


def _goods_sum(lines: list[dict]) -> float:
    return sum(float(i.get("price") or 0) * float(i.get("quantity") or 0) for i in lines)


async def ai_sales_for_day(day) -> dict:
    """{orders, products, goods} — shu kun (Toshkent) AI tuzgan, bekor qilinmagan
    buyurtmalar: soni, mahsulot qatorlari soni, mahsulotlar summasi (yetkazishsiz)."""
    async with database.pool.acquire() as conn:
        await _ensure_ai_orders(conn)
        rows = await conn.fetch(
            """SELECT o.items FROM ai_orders a JOIN orders o ON o.id = a.order_id
                WHERE (a.created_at + INTERVAL '5 hours')::date = $1
                  AND COALESCE(o.status, '') <> 'cancelled'""", day)
    lines = [_paid_lines(r["items"]) for r in rows]
    return {"orders": len(rows), "products": sum(len(l) for l in lines),
            "goods": sum(_goods_sum(l) for l in lines)}


async def _celebrate(bot: Bot | None, user, order_id: int, items: list[dict], total: float,
                     payment: str) -> None:
    """AI mijozni sotuvgacha olib bordi: buyurtma belgilanadi, suhbat xabariga
    qo'shiladi va mavzuga (yo'q bo'lsa adminlarga) tantanali xabar ketadi."""
    try:
        await record_ai_order(order_id, user.id)
    except Exception:
        logger.exception("AI order %s could not be recorded", order_id)
    lines = _paid_lines(items)
    goods = _goods_sum(lines)
    await log_conversation(bot, user, f"✅ <b>Buyurtma #{order_id}</b> — {_fmt(total)} so'm")
    if bot is None:
        return
    try:
        today = await ai_sales_for_day(_now_tk().date())
    except Exception:
        logger.warning("AI daily sales could not be read", exc_info=True)
        today = None
    names = ", ".join(_esc(i.get("name")) for i in lines[:5])
    text = (f"🎉🎉 <b>AI sotuv!</b> Buyurtma <b>#{order_id}</b>\n"
            f"👤 {_who(user)} · <code>{user.id}</code>\n"
            f"📦 {len(lines)} ta mahsulot · <b>{_fmt(goods)} so'm</b>"
            + (" · 💳 karta (chek keldi)" if payment == "karta" else " · 💵 naqd")
            + (f"\n🛍 {names}" if names else ""))
    if today and today["orders"]:
        text += (f"\n\n🏆 <b>Bugun AI:</b> {today['orders']} ta buyurtma · "
                 f"{today['products']} ta mahsulot · <b>{_fmt(today['goods'])} so'm</b> 🚀")
    dest = None
    try:
        dest = await _log_destination()
    except Exception:
        pass
    if dest:
        try:
            await bot.send_message(dest[0], text, message_thread_id=dest[1], parse_mode="HTML")
            return
        except Exception:
            logger.warning("AI sale celebration to the topic failed", exc_info=True)
    for admin_id in list(dict.fromkeys(ADMIN_IDS)):
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception:
            logger.debug("AI sale celebration to %s failed", admin_id)


async def usage_report_loop(bot: Bot) -> None:
    await asyncio.sleep(30)   # bot to'liq ishga tushsin
    while True:
        try:
            await _usage_report_tick(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("AI usage report tick failed")
        await asyncio.sleep(REPORT_CHECK_EVERY)


def fmt_tokens(n) -> str:
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def usage_lines(today: list[dict], month: dict) -> list[str]:
    """Bugungi va oylik AI sarfi — /ai_holat ham, kunlik hisobot (targets.py)
    ham shu matnni ishlatadi, ikki joyda ikki xil raqam chiqmasin."""
    lines = ["🤖 <b>AI sarfi bugun</b>"]
    if not today:
        lines.append("   Bugun AI ishlatilmadi — $0.00")
    for row in today:
        known = ai_provider.price_for(row["model"]) is not None
        cost = f"${float(row['cost_usd']):.2f}" if known else "narx noma'lum"
        lines.append(
            f"   <code>{html.escape(row['model'])}</code> — {int(row['requests'])} so'rov · "
            f"{fmt_tokens(row['input_tokens'])} kirish "
            f"({fmt_tokens(row['cached_tokens'])} keshdan) · "
            f"{fmt_tokens(row['output_tokens'])} chiqish · <b>{cost}</b>"
        )
    if month and int(month.get("requests") or 0):
        lines.append(
            f"   Oy boshidan: {int(month['requests'])} so'rov · "
            f"{fmt_tokens(int(month['input_tokens']) + int(month['output_tokens']))} token · "
            f"<b>${float(month['cost_usd']):.2f}</b>"
        )
    return lines


@router.message(Command("ai_orgat"))
async def cmd_ai_teach(message: Message):
    """/ai_orgat Yetkazib berish Toshkent ichida 1 kunda, 25 000 so'm."""
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or len(parts[1].strip()) < 5:
        await message.answer(
            "🧠 <b>AI ga o'rgatish</b>\n\n"
            "Buyruqdan keyin AI bilishi kerak bo'lgan narsani yozing:\n"
            "<code>/ai_orgat Yetkazib berish Toshkent ichida 1 kunda, 25 000 so'm</code>\n"
            "<code>/ai_orgat Eritritol shakar o'rniga 1:1 ishlatiladi</code>\n\n"
            "Keyingi xabardan boshlab AI buni biladi. Ro'yxat: /ai_bilim",
            parse_mode="HTML",
        )
        return
    fact = parts[1].strip()[:1000]
    item_id = await database.add_ai_fact(fact, message.from_user.id)
    invalidate_knowledge()
    await message.answer(
        f"✅ O'rgatildi (#{item_id}). Keyingi suhbatdan boshlab AI buni biladi.\n"
        f"O'chirish: <code>/ai_unut {item_id}</code>",
        parse_mode="HTML",
    )


@router.message(Command("ai_bilim"))
async def cmd_ai_knowledge(message: Message):
    """O'rgatilganlar + AI javob bera olmagan savollar. Savol ostidagi raqam
    bilan /ai_orgat qilinsa ham, /ai_unut qilinsa ham ro'yxatdan chiqadi."""
    if message.from_user.id not in ADMIN_IDS:
        return
    facts = await database.list_ai_facts()
    questions = await database.list_ai_questions(limit=15)

    lines = ["🧠 <b>AI bilimlari</b>", ""]
    if facts:
        for f in facts[-30:]:
            lines.append(f"<code>#{f['id']}</code> {html.escape(f['text'][:200])}")
    else:
        lines.append("Hozircha hech narsa o'rgatilmagan.")
    lines += ["", "❓ <b>AI javob bera olmagan savollar</b>"]
    if questions:
        for q in questions:
            times = f" ×{q['times']}" if int(q["times"]) > 1 else ""
            lines.append(f"<code>#{q['id']}</code> {html.escape(q['text'][:200])}{times}")
        lines += ["", "<i>Javobini o'rgatish: /ai_orgat &lt;javob&gt;, keyin savolni "
                      "ro'yxatdan olib tashlash: /ai_unut &lt;raqam&gt;</i>"]
    else:
        lines.append("Yo'q — AI hamma savolga javob topgan.")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("ai_unut"))
async def cmd_ai_forget(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].lstrip("#").isdigit():
        await message.answer("Raqamini yozing: <code>/ai_unut 12</code> (ro'yxat: /ai_bilim)",
                             parse_mode="HTML")
        return
    item_id = int(parts[1].lstrip("#"))
    if await database.delete_ai_knowledge(item_id):
        invalidate_knowledge()
        await message.answer(f"🗑 #{item_id} o'chirildi.")
    else:
        await message.answer(f"#{item_id} topilmadi.")


def _user_id_arg(message: Message) -> int | None:
    parts = (message.text or "").split()
    if len(parts) < 2 or not parts[1].isdigit():
        return None
    return int(parts[1])


@router.message(Command("ai_hisobot"))
async def cmd_ai_report(message: Message):
    """/ai_hisobot — AI nechta mijoz bilan gaplashdi, nechta javob, mavzular,
    eng ko'p so'ralgan mahsulotlar, sotuvlar (ai_stats.py)."""
    if message.from_user.id not in ADMIN_IDS:
        return
    try:
        text = ai_stats.report_text(await ai_stats.fetch_stats())
    except Exception:
        logger.exception("AI report failed")
        text = "⚠️ Hisobotni o'qib bo'lmadi, birozdan keyin qayta urinib ko'ring."
    await message.answer(text, parse_mode="HTML")


@router.message(Command("ai_mijoz"))
async def cmd_ai_customer(message: Message):
    """/ai_mijoz 123456789 — AI shu mijoz haqida nimani eslab turibdi."""
    if message.from_user.id not in ADMIN_IDS:
        return
    user_id = _user_id_arg(message)
    if user_id is None:
        await message.answer("Mijoz ID sini yozing: <code>/ai_mijoz 123456789</code>\n"
                             "(ID AI suhbati nusxasida ko'rinadi)", parse_mode="HTML")
        return
    await message.answer(await _memory_card(user_id), parse_mode="HTML")


@router.message(Command("ai_mijoz_unut"))
async def cmd_ai_customer_forget(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    user_id = _user_id_arg(message)
    if user_id is None:
        await message.answer("Mijoz ID sini yozing: <code>/ai_mijoz_unut 123456789</code>",
                             parse_mode="HTML")
        return
    removed = await ai_memory.forget(user_id)
    _sessions.pop(user_id, None)
    await message.answer(f"🗑 {user_id} haqidagi {removed} ta eslatma o'chirildi "
                         "(buyurtmalar tarixi qoladi).")


async def _in_bot_form(state: FSMContext | None) -> bool:
    """Foydalanuvchi botning biror formasi ichida (FSM holati bor): masalan admin
    "↩️ Javob berish" ni bosib, mijozga javob yozyapti. Bunda yozgan matni o'sha
    formaniki — AI aralashmaydi (egasi, 2026-10-13: "mijozga o'zim javob
    bermoqchi edim, lekin AI menga javob beryapti"). support_relay routeri AI
    dan KEYIN turadi, shuning uchun bu tekshiruvsiz AI uning formasini yutib
    yuborardi; oldingi routerlardagi formalar baribir AI dan oldin ushlaydi.

    Istisno — AI o'zi ochgan buyurtma kartasi: u ochiq turganda mijoz yozsa
    ham suhbat AI da qoladi ('ha' — tasdiq, savol — javob)."""
    if state is None:
        return False
    try:
        current = await state.get_state()
    except Exception:
        return False
    if current is None:
        return False
    return not await ai_card_open(state)


async def _has_session(message: Message, state: FSMContext | None = None) -> bool:
    """FILTR sifatida ishlatiladi, handler ichidagi tekshiruv sifatida emas —
    va bu ataylab. aiogram'da mos kelgan handler `return` qilsa ham xabar
    "ishlangan" hisoblanadi va support_relay ga yetib bormaydi. Ya'ni AI
    javob bermaydigan odamning savoli jimgina yo'qolardi."""
    user = message.from_user
    if not user or message.chat.type != "private" or not await _ready():
        return False
    if await _in_bot_form(state):
        return False
    if _is_paused(user.id) or not await _allowed(user.id):
        return False
    if user.id in _sessions:
        return True
    # Adminlarga AI faqat sinov tugmasi yoqilganda o'zi javob beradi (egasi:
    # 2026-10-12 "adminlar yozganiga javob yozmasin", 2026-10-13 "hozircha
    # adminlarga ham javob bersin, testlash uchun"). O'chiq bo'lsa — /ai bilan.
    if user.id in ADMIN_IDS:
        return await setting("admins") and user.id not in _opted_out
    # Mijoz /ai siz ham: yozsa suhbat o'zi ochiladi (_reply ichida _session()
    # yaratadi). /ai_off bosgan odam operatorga qaytgan bo'ladi.
    return AUTOSTART and user.id not in _opted_out


CHEQUE_ORDER_DAYS = 3        # shu kundan eski buyurtmaga chek bog'lanmaydi


async def _open_order_for_cheque(user_id: int) -> int | None:
    """Chek qaysi buyurtmaniki: AI karta raqamini bergan buyurtma (sessiyada),
    bo'lmasa mijozning oxirgi CHEQUE_ORDER_DAYS kundagi ochiq buyurtmasi —
    to'lanmagan (online emas), cheki yo'q, yetkazilmagan va bekor qilinmagan.
    Bazadan o'qiladi, ya'ni bot qayta ishga tushsa ham, AI to'xtatilgan yoki
    suhbat unutilgan bo'lsa ham chek yo'qolmaydi. Faqat karta tanlangan
    ("To'lov: KARTA" izohli) buyurtma — naqd buyurtmachining rasmi chek emas
    (egasi, 2026-10-13: "kartaga
    to'lov qilinganda chekni qabul qilishi kerak, hozir qabul qilmadi")."""
    from datetime import datetime, timedelta, timezone
    session = _sessions.get(user_id)
    if session and session.get("awaiting_cheque"):
        return int(session["awaiting_cheque"])
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for order in await database.get_user_orders(user_id):
        created = order.get("created_at")
        if not isinstance(created, datetime) or now - created > timedelta(days=CHEQUE_ORDER_DAYS):
            continue
        if order.get("status") in ("delivered", "cancelled"):
            continue
        if order.get("payment_method") == "online" or order.get("cheque_file_id"):
            continue
        if "KARTA" not in (order.get("address_note") or ""):
            continue   # naqd buyurtma — mijozning rasmi chek emas
        return int(order["id"])
    return None


def _is_receipt(message: Message) -> bool:
    if message.photo:
        return True
    document = message.document
    mime = (getattr(document, "mime_type", None) or "") if document else ""
    return bool(document) and (mime.startswith("image/") or mime == "application/pdf")


async def _cheque_filter(message: Message, state: FSMContext | None = None):
    """FILTR: mijozning shaxsiy chatdagi rasmi/PDF i — to'lov cheki bo'lishi
    mumkinmi. Tugmali checkout ning chek holati (FSM) oldinroq turgan routerda
    ushlanadi; bu yerga faqat undan o'tganlari keladi. Topilgan buyurtma
    handlerga `cheque_order` bo'lib beriladi (None — buyurtmaga bog'lanmagan,
    lekin ochiq AI suhbatida)."""
    user = message.from_user
    if user is None or message.chat.type != "private" or not _is_receipt(message):
        return False
    if await _in_bot_form(state):
        return False   # botning biror formasi ichida — rasm o'sha formaniki
    if user.id in database.LEADERBOARD_EXCLUDED_USER_IDS or user.id in _settings["staff"]:
        return False
    in_session = user.id in _sessions and not _is_paused(user.id)
    if user.id in ADMIN_IDS and not in_session:
        return False   # admin rasm yuborsa — o'z ishi, chek emas (sinovda — sessiya bor)
    try:
        order_id = await _open_order_for_cheque(user.id)
    except Exception:
        logger.warning("Open order lookup for a cheque failed for %s", user.id, exc_info=True)
        order_id = None
    if order_id is None and not in_session:
        return False
    return {"cheque_order": order_id}


# Faqat minnatdorchilik — javob kutmaydi, model chaqirilmaydi. "ha", "ok",
# "xo'p", 👍 bu yerda YO'Q: ular buyurtmani tasdiqlash bo'lishi mumkin.
_THANKS_RE = re.compile(
    r"^\W*(?:katta\s+)?(?:rahmat|raxmat|rahmet|tashakkur|спасибо|спс|благодарю|рахмат|раҳмат|ташаккур)"
    r"(?:\s+(?:katta|sizga|сизга|катта|большое))?\W*$",
    re.IGNORECASE,
)


def is_thanks_only(text: str) -> bool:
    return bool(_THANKS_RE.match(text or ""))


# Mavzudan tashqari — do'konga aloqasi yo'q narsa YARATISHni so'rash (egasi,
# 2026-10-17: "mavzudan tashqari savollarga javob bermasliging kerak"). Jonli
# sinovda model she'r yozdi va uy vazifasini yechdi. Shu turdagi so'rov modelga
# bormaydi — qat'iy rad javobi, token ham ketmaydi. Qolgan mavzudan tashqari
# savollarni promptdagi MAVZU CHEGARASI qoidasi rad etadi.
_OFF_TOPIC = re.compile(
    r"\b(?:she['ʻ’`‘]r\w*|шеър\w*|стих\w*|insho\w*|иншо\w*|сочинени\w*|referat\w*|реферат\w*|"
    r"uy\s+vazifa\w*|уй\s+вазифа\w*|домашн\w+\s+задани\w*|tenglama\w*|тенглама\w*|уравнени\w*|"
    r"python\w*|javascript\w*|напиши\w*\s+код\b|написать\s+код\b)",
    re.IGNORECASE)


def off_topic_request(text: str) -> bool:
    return bool(_OFF_TOPIC.search(text or ""))


def off_topic_reply(lang: str) -> str:
    return _t("Kechirasiz, bu mavzuda yordam bera olmaymiz 😊\n\n"
              "Keto va PP mahsulotlari, retseptlar yoki buyurtma bo'yicha savolingiz bo'lsa — "
              "marhamat, yozing 🌿",
              "Извините, с этим помочь не сможем 😊\n\n"
              "Если есть вопрос о кето- и ПП-продуктах, рецептах или заказе — пишите 🌿", lang)


async def _decline_off_topic(bot: Bot | None, message: Message) -> None:
    user = message.from_user
    spoken = customer_language(message.text)
    lang = "ru" if spoken == "ru" else "uz_cyr" if spoken == "uz_cyr" else "uz" if spoken else await _lang(user.id)
    reply = off_topic_reply(lang)
    await message.answer(reply)
    await log_conversation(bot, user, f"👤 {_esc(_short(message.text, 300))}\n🤖 {_esc(reply)}\n"
                                      "<i>(mavzudan tashqari — modelsiz)</i>")
    if user.id not in ADMIN_IDS and user.id not in database.LEADERBOARD_EXCLUDED_USER_IDS:
        await ai_stats.record_turn(user.id, "bot", message.text)


def _keep_fsm(message: Message, state: FSMContext | None) -> None:
    """buyurtma_kartasi checkout holatini shu FSMContext orqali yozadi."""
    if state is not None:
        _session(message.from_user.id)["fsm"] = state


def _heard(message: Message) -> None:
    """Mijozning o'z so'zlari — kartaga faqat shulardan manzil va izoh tushadi
    (from_customer)."""
    session = _session(message.from_user.id)
    said = session.setdefault("said", [])
    said.append(message.text or "")
    del said[:-30]
    spoken = customer_language(message.text)
    if spoken:
        session["cust_lang"] = spoken   # "кв 5", kontakt, lokatsiya — oldingisi qoladi


@router.message(_has_session, F.text & ~F.text.startswith("/"))
async def on_text(message: Message, bot: Bot, state: FSMContext | None = None):
    """AI javob beradigan odamning oddiy matni. Router bot.py da support_relay
    dan OLDIN, qolgan hammasidan KEYIN turadi: menyu tugmalari va FSM oqimlari
    avvalgidek ishlayveradi, faqat hech kim ushlamagan matn AI ga tushadi."""
    _keep_fsm(message, state)
    _heard(message)
    if is_thanks_only(message.text):
        return   # "rahmat" ga javob shart emas — token ham ketmaydi
    if _card_fresh(message.from_user.id) and await ai_card_open(state):
        # Karta ochiq: "ha" — tasdiq, "karta bilan" / "naqd" — to'lov tugmasi.
        # Ikkalasi ham modelsiz, tugmali checkout ning o'z kodi bilan.
        if is_confirmation(message.text):
            await _confirm_typed(bot, message, state)
            return
        choice = payment_choice(message.text)
        if choice:
            await _switch_card_payment(bot, message, state, choice)
            return
    if off_topic_request(message.text):
        await _decline_off_topic(bot, message)
        return
    await _reply(bot, message, message.text)


@router.message(_has_session, F.location)
async def on_location(message: Message, bot: Bot, state: FSMContext | None = None):
    """Mijoz manzilni Telegram lokatsiyasi bilan yubordi. Tugmali checkout
    bilan bir xil ishlov: O'zbekiston chegarasi tekshiriladi va koordinata
    o'qiladigan manzilga aylantiriladi (handlers/cart.py::process_location) —
    kuryer 'Yunusobod, Mustaqillik 12' ni koordinatadan afzal ko'radi."""
    _keep_fsm(message, state)
    lat = message.location.latitude
    lng = message.location.longitude
    try:
        from handlers.cart import verify_uzbekistan, get_location_address_text
        if not await verify_uzbekistan(lat, lng):
            await message.answer(_t("📍 Bu manzil O'zbekistondan tashqarida ko'rinyapti. "
                                    "Yetkazib berish faqat O'zbekiston ichida.",
                                    "📍 Похоже, это место за пределами Узбекистана. "
                                    "Доставляем только по Узбекистану.",
                                    await _lang(message.from_user.id)))
            return
        readable = await get_location_address_text(lat, lng)
    except Exception:
        logger.warning("AI location lookup failed", exc_info=True)
        readable = None

    pin = f"📍 {lat:.6f}, {lng:.6f}"
    if readable:
        pin += f" — {readable}"
    _session(message.from_user.id)["location"] = (lat, lng, pin)
    _session(message.from_user.id)["keyboard"] = "menu"   # lokatsiya keldi — menyu qaytsin
    try:
        from handlers.cart import _is_tashkent
        where = "Toshkent ichida" if _is_tashkent(lat, lng) else "Toshkentdan TASHQARIDA (viloyat)"
    except Exception:
        where = "hududi noma'lum"
    # Koordinata modelga kerak emas (mijozga "41.311081, 69.240562" deb o'qib berardi) —
    # u kartada va kuryer xabarida bor.
    place = readable or "xaritadagi nuqta, ko'cha nomi aniqlanmadi"
    await _reply(bot, message, f"[Mijoz yetkazish lokatsiyasini yubordi: {place} — {where}]")


@router.message(_has_session, F.contact)
async def on_contact(message: Message, bot: Bot, state: FSMContext | None = None):
    """Kontakt tugmasi orqali kelgan telefon — qo'lda yozishdan ishonchliroq."""
    _keep_fsm(message, state)
    phone = (message.contact.phone_number or "").strip()
    if phone and not phone.startswith("+"):
        phone = "+" + phone
    _session(message.from_user.id)["phone"] = phone
    _session(message.from_user.id)["keyboard"] = "menu"
    await _reply(bot, message, f"[Mijoz telefon raqamini yubordi: {phone}]")


@router.message(_cheque_filter)
async def on_cheque(message: Message, bot: Bot, cheque_order: int | None = None):
    """To'lov cheki. AI uni KO'RMAYDI va tasdiqlamaydi. Buyurtma topilsa —
    tugmali checkout bilan bir xil: chek buyurtmaga biriktiriladi (kartochkada
    ko'rinadi) va adminlarga "🧾 Buyurtma #X uchun to'lov cheki" bo'lib boradi.
    Buyurtma 'cash' bo'lib qoladi — to'lov holatini admin o'zgartiradi."""
    user = message.from_user
    lang = await _lang(user.id)
    session = _sessions.get(user.id)
    if cheque_order:
        kind, file_id = (("photo", message.photo[-1].file_id) if message.photo
                         else ("document", message.document.file_id))
        try:
            await database.set_order_cheque(cheque_order, file_id, kind)
        except Exception:
            logger.exception("Cheque could not be attached to order %s", cheque_order)
        try:
            from handlers.cart import _forward_cheque_to_admins
            await _forward_cheque_to_admins(bot, cheque_order, user.full_name or "—", kind, file_id,
                                            reply_markup=_paid_kb(cheque_order))
        except Exception:
            logger.exception("Cheque for order %s could not be forwarded", cheque_order)
        if session:
            session["awaiting_cheque"] = None
        await log_conversation(bot, user, f"🧾 To'lov cheki yuborildi — buyurtma #{cheque_order}")
        await message.answer(_t(f"✅ Sizga rahmat! Buyurtma #{cheque_order} uchun chekingiz qabul qilindi — "
                                "operatorimiz to'lovni tekshirib tasdiqlaydi 🌿",
                                f"✅ Спасибо! Чек по заказу #{cheque_order} получен — оператор "
                                "проверит оплату и подтвердит 🌿", lang))
        return
    order_id = None
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
        await message.answer(_t("Sizga rahmat! Chekni oldik, operatorimiz tez orada bog'lanadi.",
                                "Спасибо! Чек получили, оператор скоро свяжется с вами.", lang))
        return
    await log_conversation(bot, user, "🧾 Rasm/chek yubordi (buyurtmaga bog'lanmagan)")
    await message.answer(_t("✅ Sizga rahmat! Chek qabul qilindi — operatorimiz to'lovni tekshirib tasdiqlaydi.",
                            "✅ Спасибо! Чек принят — оператор проверит оплату и подтвердит.", lang))


# ────────────────────────────── guruh rejimi ────────────────────────────────
# Guruhda SOTUV YO'Q (egasining talabi 2026-09-12): AI savollarga javob beradi
# va xarid qilmoqchi bo'lgan odamni botga yo'naltiradi — bu yerda vositalar
# umuman berilmaydi, ya'ni guruhdan turib hech narsa sotib bo'lmaydi. Ism,
# telefon va manzil ochiq guruhda so'ralmaydi.
#
# 2026-10-12 dan: kanalga ulangan guruhda mijozning savoliga @mention siz ham
# javob beradi (egasi: "vaqt ajrata olmayapmiz"). Lekin har xabarga emas:
#   * admin, guruh admini, ichki akkaunt, kanal posti, boshqa bot — hech
#     qachon, hatto botni chaqirsa ham;
#   * odamlar bir-biriga reply qilib gaplashsa — aralashmaydi;
#   * savolga o'xshamagan gap modelga bormaydi (looks_like_question); o'tib
#     ketganini model SKIP qiladi (rahmat, tabrik, o'zaro gap);
#   * guruhga soatiga GROUP_MAX_PER_HOUR dan ko'p chaqiruv yo'q.

LINKED_TTL = 3600
_group_calls: dict[int, list[float]] = {}   # chat_id -> oxirgi soatdagi chaqiruvlar
_linked: dict = {"at": float("-inf"), "id": None}


async def _channel_group(bot: Bot | None) -> int | None:
    """@ketoshop_uz kanaliga ulangan muhokama guruhi — kanal ma'lumotidan
    (linked_chat_id), soatiga bir marta so'raladi. Guruh almashtirilsa ham
    sozlama o'zgartirish shart emas."""
    now = time.monotonic()
    if bot is None or now - _linked["at"] < LINKED_TTL:
        return _linked["id"]
    _linked["at"] = now
    try:
        chat = await bot.get_chat(REQUIRED_CHANNEL_ID)
        _linked["id"] = getattr(chat, "linked_chat_id", None)
    except Exception:
        logger.warning("Linked discussion group of %s could not be read", REQUIRED_CHANNEL_ID,
                       exc_info=True)
    return _linked["id"]


async def _group_chats(bot: Bot | None) -> set[int]:
    chats = set(GROUP_CHATS)
    if CHANNEL_GROUP:
        linked = await _channel_group(bot)
        if linked:
            chats.add(linked)
    return chats


def _group_rules() -> str:
    rules = (
        "Sen Ketoshop (@" + BOT_USERNAME + ") do'konining kanaliga ulangan guruhdagi "
        "yordamchisisan. Ketoshop Toshkentda keto va PP mahsulotlari sotadi.\n\n"
        "QACHON JAVOB BERASAN\n"
        "- Har bir xabar senga keladi, lekin hammasiga javob shart emas. Javob ber: "
        "mahsulot, narx, bor-yo'qligi, yetkazish, to'lov, buyurtma, keto/PP haqidagi "
        "savollarga va do'konga qaratilgan murojaatlarga.\n"
        "- Javob KERAK EMAS bo'lsa (rahmat, tabrik, emoji, odamlarning o'zaro gapi, "
        "do'konga aloqasi yo'q gap, reklama yoki spam) — faqat bitta so'z yoz: SKIP\n"
        "- Kimdir botga to'g'ridan-to'g'ri murojaat qilsa (@" + BOT_USERNAME + " yoki "
        "botning xabariga reply) — doim javob ber.\n"
        "- '[Kanal postiga izoh...]' bo'lsa — savol o'sha postdagi mahsulot haqida.\n\n"
        "BU GURUH — SOTUV JOYI EMAS\n"
        "- Guruhda savat ham, buyurtma ham yo'q. Hech kimdan ism, telefon yoki "
        "manzil so'rama va buyurtma qabul qilma.\n"
        "- Kimdir sotib olmoqchi bo'lsa, javobni ber va botga yo'naltir: 'buyurtma uchun "
        "@" + BOT_USERNAME + " ga yozing — o'sha yerda rasmiylashtirib beramiz'.\n"
        "- Karta raqami, to'lov, chek — bular haqida guruhda gaplashma, botga yubor.\n"
        "- Retsept so'ralsa — guruhda retsept yozma, muloyim botga yo'naltir: 'Retseptni "
        "@" + BOT_USERNAME + " da mamnuniyat bilan ulashamiz 😊'.\n\n"
        "SALOMLASHISH\n"
        "- Kimdir salom bersa: 'Vaalaykum assalom! Assalomu alaykum, Keto shopga "
        "xush kelibsiz!' deb boshla, keyin savoliga javob ber.\n"
        "- Salom bermay savol bersa, salomni qisqa qil yoki umuman tashlab ket — "
        "guruhda har javobda salomlashish g'ashga tegadi.\n\n"
        "SEN KIMSAN\n"
        "- Sen Ketoshop jamoasining yordamchisisan. O'zingni robot, bot yoki "
        "sun'iy intellekt deb tanishtirma, 'katalog id', 'tizim' kabi ichki so'zlarni "
        "ishlatma. Robotmisan deb chin dildan so'rashsa, o'zingni odam deb atama: "
        "'Sizga Ketoshop yordamchisi javob beryapti' de va xodim bilan bog'lanish uchun "
        "raqamni ber: " + SUPPORT_PHONES + "\n\n"
        "NOQULAY HOLAT\n"
        "- Shikoyat, janjal, buyurtma yoki to'lov muammosi, javobini bilmagan savol "
        "bo'lsa, guruhda muhokama qilma: qisqa uzr so'rab "
        "'Batafsil ma\'lumot olish uchun: " + SUPPORT_PHONES + "' deb yoz va "
        "shaxsiy yozishga taklif qil.\n\n"
        "GAPIRISH USLUBI\n"
        "- Do'kon nomidan 'biz' deb gapir: beramiz, qilamiz, aytamiz — '-man' shakli yo'q.\n"
        "- Hech kimga ismi bilan murojaat qilma.\n"
        "- MAKSIMAL ODOB: odamdek, muloyim va samimiy yoz — 'siz' deb murojaat, "
        "'albatta', 'marhamat', 'rahmat'. Quruq bir so'zli javob ('Ha, bor.') yo'q.\n"
        "- Mijoz tomonidan o'yla: variantlar bo'lsa narxi va nimaga mosligini qisqa ayt, "
        "eng mosini tavsiya qil. Adabiy, grammatik to'g'ri o'zbek tilida yoz.\n"
        "- QISQA: 2-3 jumla. Guruhda uzun matn o'qilmaydi. HTML/markdown yo'q.\n"
        "- O'qish oson bo'lsin: variantlar alohida qatorda ('•' bilan), savol yoki botga "
        "yo'naltirish — alohida qatorda, hammasi bitta bo'lakka yopishmasin.\n"
        "- Kim qaysi til va yozuvda yozsa, o'shanda javob ber: o'zbekcha kirill — kirillda, "
        "lotin — lotinda, ruscha — ruscha, inglizcha — inglizcha.\n"
        "- Har javobda 1-2 ta muloyim emoji (😊 🌿 🤗 💚) — ko'p emas; shikoyatda yo'q.\n"
        "- Suhbatni davom ettir: oldingi xabarlarni hisobga ol, savol berilsa "
        "javob ber, hazilga hazil bilan javob berishing mumkin.\n\n"
        "AKSIYA\n"
        "- Pastda 'FAOL AKSIYA' yoki 'BOT CHEGIRMASI' bo'lsa va savol mavzuga tegsa, bir "
        "jumlada eslatib o't. Bosim yo'q, 'shoshiling' yo'q — faqat fakt va 'buyurtma uchun "
        "botga yozing'.\n\n"
        "NIMA HAQIDA GAPIRASAN\n"
        "- Mahsulotlar: faqat quyidagi katalogdan gapir. Narxni katalogdan ol, "
        "o'zingdan narx yoki chegirma o'ylab topma.\n"
        "- Bilmagan narsangni bilmayman de va operatorga/botga yo'naltir.\n\n"
        + _keto_knowledge() + "\n"
        + _shop_knowledge() + "\n"
        "QAT'IY CHEGARALAR\n"
        "- Tibbiy maslahat berma (dori, davolash, diagnoz, dozalar). Kasallik haqida "
        "so'rashsa: shifokor bilan maslahatlashishni ayt.\n"
        "- Siyosat, din va shaxsiy mavzulardan chetlan.\n"
        "- MAVZUDAN TASHQARI savol (umumiy bilim, uy vazifasi, kod, she'r, insho, sport, "
        "yangiliklar, ob-havo va h.k.) — mazmuniga JAVOB BERMA. Senga murojaat qilinmagan bo'lsa — "
        "SKIP. Murojaat qilingan bo'lsa (@ yoki reply) — bitta muloyim jumla: 'Bu mavzuda yordam "
        "bera olmaymiz 😊 Keto mahsulotlari yoki buyurtma bo'yicha savolingiz bo'lsa — marhamat!'\n"
    )
    return rules


def _is_channel_post(message) -> bool:
    """Kanaldan guruhga avtomatik tushgan post (izohlar shunga reply bo'ladi)."""
    if message is None:
        return False
    if getattr(message, "is_automatic_forward", False):
        return True
    sender = getattr(message, "sender_chat", None)
    return bool(sender and getattr(sender, "type", "") == "channel")


def _addressed_to_bot(message: Message) -> bool:
    text = message.text or message.caption or ""
    if ("@" + BOT_USERNAME).lower() in text.lower():
        return True
    reply = message.reply_to_message
    return bool(reply and reply.from_user and reply.from_user.is_bot
                and (reply.from_user.username or "").lower() == BOT_USERNAME.lower())


def _group_budget_ok(chat_id: int) -> bool:
    now = time.time()
    recent = [t for t in _group_calls.get(chat_id, []) if now - t < 3600]
    _group_calls[chat_id] = recent
    return len(recent) < GROUP_MAX_PER_HOUR


# Savolga o'xshaydimi — modelni chaqirishdan OLDIN, bepul tekshiruv (egasi:
# "faqat savol deb o'ylaganlariga javob yozsin", "maksimal token tejamkor").
# Guruhdagi gaplarning ko'pi savol emas: ular uchun model umuman chaqirilmaydi.
# O'tib ketgan gapni model baribir SKIP qila oladi — bu faqat birinchi elak.
_QUESTION_RE = re.compile(
    r"\?|"
    # o'zbekcha -mi/-mu yuklamasi: bormi, bo'ladimi, kelasizmi, борми
    r"\w{2,}(?:mi|mu|mikan|ми|му|микан)\b|"
    r"\b(?:qancha|qanch|necha|nechi|narx|narh|qayer|qanday|qachon|qaysi|nima|nega|"
    r"mumkin|kerak|olmoqchi|olsam|buyurtma|zakaz|dostavka|yetkaz|sotib|manzil|lokatsiya|adres|"
    r"сколько|почем|цена|цену|где|как|какой|какая|какие|когда|можно|нужн|хочу|"
    r"заказ|доставк|есть ли|купить|адрес|локац|манзил|рецепт|ретсепт|retsept|resept|"
    r"қанча|канча|нарх|қаер|каер|қандай|кандай|қачон|качон|қайси|кайси|нима|нега|"
    r"мумкин|керак|буюртма|етказ|сотиб)",
    re.IGNORECASE,
)


def looks_like_question(text: str) -> bool:
    return bool(_QUESTION_RE.search(text or ""))


async def _group_trigger(message: Message, bot: Bot) -> bool:
    """FILTR: bu guruh xabariga AI javob beradimi. Faqat begona odamning
    savoliga. Adminlar (bot adminlari, ichki akkauntlar, guruh adminlari)
    yozganiga HECH QACHON — reply qilib yozsa ham, botni chaqirsa ham (egasi,
    2026-10-13: "guruhda adminlar yozsa umuman javob berma"). Sinov tugmasi
    "Adminlarga ham javob" faqat botdagi shaxsiy chatga tegishli."""
    if message.chat.type not in ("group", "supergroup") or not await _ready():
        return False
    text = (message.text or message.caption or "").strip()
    if not text or text.startswith("/"):
        return False
    user = message.from_user
    if user is None or user.is_bot or message.sender_chat is not None:
        return False   # kanal posti, anonim admin, boshqa bot
    if message.chat.id not in await _group_chats(bot):
        return False
    if user.id in ADMIN_IDS or user.id in database.LEADERBOARD_EXCLUDED_USER_IDS:
        return False
    if not await setting("group") or not _group_budget_ok(message.chat.id):
        return False
    if not _addressed_to_bot(message):
        reply = message.reply_to_message
        if reply is not None and not _is_channel_post(reply):
            return False   # odamlar bir-biriga javob yozyapti
        if not looks_like_question(text):
            return False   # savol emas — model chaqirilmaydi
    import link_guard
    # Guruh admini (yoki ro'yxatni o'qib bo'lmadi) — o'zlari javob beradi.
    return await link_guard.is_privileged(bot, message) is False


async def _group_respond(chat_id: int, author: str, text: str) -> str:
    """Guruh savoliga javob. tools=None — ataylab: guruhda savat ham, buyurtma
    ham yo'q, ya'ni u yerdan hech narsa sotib bo'lmaydi. "" — javob kerak emas
    (model SKIP dedi).

    Zanjirsiz: har savol bo'sh holat bilan ketadi. Zanjir bo'lsa har chaqiruv
    butun guruh tarixini qayta to'laydi; kerakli kontekst (izoh qaysi postga,
    botning qaysi javobiga) savolning o'ziga qo'shib yuboriladi."""
    _group_calls.setdefault(chat_id, []).append(time.time())
    turn = await _step(
        {}, _group_rules(), await _dynamic_block(await _catalog_text()), None,
        user=f"{author}: {text}", max_tokens=400, history_limit=2,
    )
    if turn.refused:
        return ""
    reply = (turn.text or "").strip()
    if not reply or re.fullmatch(r"\W*SKIP\W*", reply, flags=re.IGNORECASE):
        return ""
    return reply


async def _group_answer(bot: Bot, message: Message, text: str) -> None:
    chat_id = message.chat.id
    replied = message.reply_to_message
    if _is_channel_post(replied):
        text = (f"[Kanal postiga izoh. Post matni: «{_short(replied.text or replied.caption or '', 700)}»]"
                f"\n{text}")
    elif replied is not None and _addressed_to_bot(message):
        text = f"[Sening oldingi javobingga reply: «{_short(replied.text or '', 400)}»]\n{text}"
    author = message.from_user.first_name or "Mijoz"
    try:
        reply = await _group_respond(chat_id, author, text)
    except Exception:
        logger.exception("AI group turn failed in chat %s", chat_id)
        return
    if not reply:
        return
    reply = thank_politely(strip_name_address(polish_reply(reply), customer_names(message.from_user, text)))
    await message.reply(reply)
    user_id = message.from_user.id
    await ai_stats.record_turn(user_id, "group", text)   # guruhda adminlarga javob yo'q
    _group_context[user_id] = (time.time(), text, reply)
    await _remember_quiet(user_id, "interest", f"guruhda so'radi: {_short(text, 200)}")


@router.message(_group_trigger, F.text | F.caption)
async def on_group_question(message: Message, bot: Bot):
    """Guruhdagi mijoz savoli. Javob reply bo'lib tushadi, ya'ni suhbat ipi
    ko'rinib turadi. Bitta odamning ketma-ket xabarlari bitta javob oladi."""
    text = (message.text or message.caption or "").replace("@" + BOT_USERNAME, "").strip()
    await _batch(("g", message.chat.id, message.from_user.id), message, text,
                 lambda msg, t: _group_answer(bot, msg, t))
