"""
AI sotuvchi — mijoz bilan yozishib, buyurtmani o'zi rasmiylashtiradi.

Bot tugmalar bilan ishlaydi: katalog -> savat -> manzil -> tasdiq. Kim
tugmalarni bosmay, oddiy odamdek yozsa (meta_leads.py orqali kelgan reklama
mijozlari ko'pincha shunday qiladi), hozirgacha javob admin yozguncha kutardi.
Bu modul o'sha suhbatni modelga topshiradi: mahsulotni tanlaydi, savatga
soladi, ism/telefon/manzilni so'raydi va buyurtmani xuddi tugmali yo'l kabi
rasmiylashtiradi.

QAYERDA ISHLAYDI (egasi, 2026-10-12: "kanalga ulangan guruh va botga yozilgan
xabarlarga AI o'zi javob berishi kerak, biz vaqt ajrata olmayapmiz")
  * Botda — hamma mijozga. Mijoz oddiy matn yozsa, support_relay ga emas,
    shu yerga tushadi. Admin /ai_holat dagi tugma bilan bir zumda o'chiradi
    (bazada saqlanadi, server sozlamasi shart emas). Adminlar, kuryerlar va
    ichki akkauntlarga AI o'zi javob bermaydi — admin /ai bilan sinab ko'radi.
  * @ketoshop_uz kanaliga ulangan muhokama guruhida — guruh id si kanalning
    linked_chat_id sidan o'zi topiladi (+ AI_GROUP_CHATS dagi guruhlar).
    Faqat begona odamning SAVOLIGA (adminlarga hech qachon). Guruhda SOTUV
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
  * Har bir AI javobi mijoz xabari bilan birga adminlarga ovozsiz nusxa bo'lib
    boradi: "↩️ Javob berish" (support_relay oqimi), "⏸ AI to'xtasin" va
    "🧠 Xotira" tugmalari bilan.
  * Admin mijozga javob bersa (support_relay yoki buyurtma ekranidan), AI shu
    mijoz uchun HUMAN_PAUSE soat jim turadi — odam bilan AI ustma-ust
    gapirmaydi. Pauza xotirada; bot qayta ishga tushsa tozalanadi.
  * Mijozga ko'rinadigan matnlarda "AI", "bot", 🤖 yo'q. Lekin model mijoz
    chin dildan "robotmisan?" deb so'rasa o'zini odam deb aytmaydi — "Ketoshop
    yordamchisiman" deb, xodim raqamini beradi. Bu chegara ataylab qoldirilgan.

XOTIRA (ai_memory.py) — har bir Telegram ID ning buyurtmalari, qiziqishlari va
mahsulotlar haqidagi fikri suhbat boshida modelga beriladi. Yetkazilgan
mahsulot haqida bir marta fikr so'raladi.

TO'LOV. Mijoz karta orqali to'lamoqchi bo'lsa, AI do'konning karta raqamini
o'zi beradi (config.PAYMENT_CARD_NUMBER — tugmali checkout bilan bir xil karta)
va chek rasmini so'raydi. Lekin "to'lov o'tdi" degan qarorni AI hech qachon
qabul qilmaydi: chek rasmi to'g'ridan-to'g'ri adminlarga uzatiladi va bazada
buyurtma `payment_method="cash"` bo'lib qoladi — ya'ni "to'langan" deb
belgilanmaydi. Tugmali online oqim chek tekshirilgandan keyingina online deb
yoziladi (handlers/cart.py), AI uni yolg'on "to'landi" holatiga qo'ymasligi
uchun ataylab shunday. Egasining talabi: kartani AI tashlaydi, to'lovni admin
ko'radi (2026-09-12).

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
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
                           Message)
from aiogram.utils.chat_action import ChatActionSender

import ai_memory
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

# Mijoz tanlaydigan yetkazish -> bazadagi delivery_method. Tugmali checkout
# bilan bir xil to'plam (keyboards.delivery_method_keyboard).
DELIVERY = {"toshkent_kuryer": "self", "yandex_taxi": "yandex_taxi", "bts": "bts", "emu": "emu"}

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


def _strip_html(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text or "")).strip()


# ─────────────────────────────── sozlamalar ─────────────────────────────────
# Uchta kalit bazada (ai_settings) — admin /ai_holat dagi tugma bilan bir zumda
# o'zgartiradi, deploy ham, server sozlamasi ham kerak emas. Default — yoqilgan
# (egasi: "darhol test rejimida ishlatib ko'raylik").

_SETTING_DEFAULTS = {"customers": True, "group": True, "mirror": True, "report": True}
_SETTING_LABELS = {
    "customers": "Botda mijozlarga javob",
    "group": "Kanal guruhida javob",
    "mirror": "Suhbat nusxasi adminlarga",
    "report": "Kunlik sarf hisoboti (23:58)",
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
        by_category.setdefault(category, []).append(
            f"{p['id']} | {p['name']} | {_fmt(price)} so'm / {p.get('unit') or 'dona'}{badge}"
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
        "- Toshkentda Yandex Taxi bilan ham bo'ladi: yo'l haqini mijoz haydovchiga o'zi to'laydi, "
        "mahsulot puli faqat karta orqali oldindan.\n"
        "- Viloyatlarga BTS yoki EMU pochtasi orqali: pochta haqi pochtaga alohida to'lanadi, "
        "mahsulot puli faqat karta orqali oldindan. Muddatini pochta belgilaydi — aniq kun "
        "va'da qilma.\n"
        f"- Karta: {PAYMENT_CARD_NUMBER} — {PAYMENT_RECIPIENT_NAME}.\n"
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
        "bahslashma va o'zingni odam deb ham atama: 'Men Ketoshop yordamchisiman, "
        "xodimimiz bilan bevosita ham gaplashsangiz bo'ladi' de va raqamni ber:\n"
        "  " + SUPPORT_PHONES + "\n\n"
        "GAPIRISH USLUBI\n"
        "- JUDA QISQA yoz: odatda 1-2 jumla, ortiqcha muqaddimasiz va takrorsiz. Bu "
        "Telegram chat, maqola emas. Ro'yxat kerak bo'lsa — 3 qatordan oshmasin.\n"
        "- Mijoz qaysi tilda yozsa, o'sha tilda javob ber: o'zbekcha lotin, o'zbekcha "
        "kirill yoki ruscha. Kirillda yozsa — kirillda javob ber.\n"
        "- Iliq va sodda gapir, emoji ni oz ishlat (javobiga bittadan ko'p emas).\n"
        "- Bir vaqtda bitta narsa so'ra: hammasini birdan so'rab ro'yxat yozma.\n"
        "- Mijoz ketma-ket bir nechta xabar yozgan bo'lsa, ular birga keladi — hammasiga "
        "bitta javobda javob ber.\n"
        "- Matnda HTML yoki markdown (** yoki #) ishlatma — oddiy matn.\n\n"
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
        "PP, kim uchun), keyin aniq mahsulot va narx ayt, yoqsa 'savatga qo'shaymi?' de.\n"
        "- Tanlagan mahsulotiga mos bitta qo'shimcha narsani taklif qilsang bo'ladi "
        "(masalan bodom uni -> eritritol yoki psillium), bir marta, bosimsiz.\n"
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
        "- Avval buyurtma bergan mijozni ismi bilan, 'yana ko'rganimizdan xursandmiz' "
        "ohangida kutib ol.\n"
        "- Salomdan keyin darrov ishga o't: mijozning savoliga javob ber yoki "
        "bitta qisqa savol bilan mavzuga burib yubor ('nima qidiryapsiz?').\n"
        "- Salomni FAQAT suhbatning birinchi javobida ayt, keyingi har bir "
        "xabarda takrorlama.\n\n"
        "BUYURTMA\n"
        "- Mahsulot tanlangach savatga_qoshish (yoki set uchun set_qoshish) bilan savatga "
        "sol va qisqacha tasdiqla. Miqdorni o'zgartirsa — savatga_qoshish ni yangi miqdor "
        "bilan qayta chaqir (u miqdorni almashtiradi, ustiga qo'shmaydi).\n"
        "- Buyurtma uchun kerak: ISM, TELEFON, MANZIL, YETKAZISH TURI va TO'LOV. "
        "Ularni birma-bir so'ra. MIJOZ XOTIRASI da oxirgi manzil va telefon bo'lsa, "
        "qayta so'rama — 'shu manzilga yetkazaylikmi?' deb tasdiqlat.\n"
        "- Avval Toshkentdami yoki viloyatdami — shuni aniqla: Toshkentda kuryer (naqd yoki "
        "karta) yoki Yandex Taxi (faqat karta); viloyatda BTS yoki EMU (faqat karta).\n"
        "- MANZILNI so'raganda mijozdan Telegram lokatsiyasini yuborishni so'ra "
        "(skrepka 📎 -> Location), kuryerga eng aniq shu bo'ladi. Lokatsiya yubora "
        "olmasa, manzilni matn bilan yozsin — ikkalasi ham bo'ladi.\n"
        "- Telefonni ham kontakt tugmasi orqali yuborsa bo'ladi.\n"
        "- Tasdiqlatishdan oldin savatni_korish ni chaqir va jami summani FAQAT undan ol — "
        "o'zing hisoblama. Savat, yetkazish turi va jami summani qisqa takrorlab, mijozdan "
        "tasdiq so'ra. Mijoz 'ha' degandan keyingina buyurtma_rasmiylashtirish ni chaqir.\n"
        "- Buyurtma tushgach raqamini ayt. Toshkent kuryeri bo'lsa '24 soat ichida "
        "yetkaziladi', boshqasida 'operatorimiz bog'lanadi' de.\n\n"
        "TO'LOV\n"
        "- Toshkent kuryerida ikki yo'l bor: NAQD (kuryerga qo'lma-qo'l) yoki KARTA orqali "
        "oldindan. Boshqa yetkazishlarda faqat KARTA. Buyurtmani rasmiylashtirishdan oldin "
        "so'ra va buyurtma_rasmiylashtirish da tolov_turi ni to'g'ri ko'rsat.\n"
        "- Karta tanlansa, buyurtma tushgandan KEYIN karta raqamini o'zing ber "
        "(vosita qaytargan raqam va summa bilan) va to'lov chekining rasmini shu chatga "
        "yuborishni so'ra.\n"
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
                "yetkazish": {"type": "string", "enum": list(DELIVERY),
                              "description": "Toshkentda toshkent_kuryer yoki yandex_taxi, "
                                             "viloyatda bts yoki emu"},
                "tolov_turi": {"type": "string", "enum": ["naqd", "karta"],
                               "description": "Mijoz qanday to'laydi"},
                "izoh": {"type": "string", "description": "Qo'shimcha izoh (ixtiyoriy)"},
            },
            "required": ["ism", "telefon", "tolov_turi"],
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
    await database.add_to_cart(user_id, product_id=product_id, quantity=qty)
    await _remember_quiet(user_id, "interest", product["name"], product_id)
    return (f"OK: savatda {product['name']} — {qty:g} {product.get('unit') or 'dona'}."
            ) + await _promo_hint(user_id)


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
    await database.add_to_cart(user_id, set_id=set_id, quantity=count)
    await _remember_quiet(user_id, "interest", bundle["name"])
    return f"OK: savatda {bundle['name']} — {count} ta." + await _promo_hint(user_id)


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
    return "\n".join(lines) + await _promo_hint(user_id)


async def _tool_remove(user_id: int, args: dict) -> str:
    set_id = int(args.get("set_id") or 0)
    if set_id:
        removed = False
        for line in await database.get_cart(user_id):
            if line.get("set_id") == set_id:
                await database.remove_from_cart(line["cart_id"])
                removed = True
        return "OK: set savatdan o'chirildi." if removed else "Bu set savatda yo'q edi."
    product_id = int(args.get("mahsulot_id") or 0)
    cart_id, _ = await database.get_cart_line_for_product(user_id, product_id)
    if not cart_id:
        return "Bu mahsulot savatda yo'q edi."
    await database.remove_from_cart(cart_id)
    return "OK: savatdan o'chirildi."


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


async def _tool_order(bot: Bot, message: Message, args: dict) -> str:
    """Haqiqiy buyurtma. Tugmali checkout bilan bitta yo'ldan yuradi
    (handlers/cart.py::_build_order_summary -> database.create_order ->
    _notify_sellers), shuning uchun aksiya sovg'alari, chegirmalar va ombor
    hisobi o'z-o'zidan to'g'ri bo'ladi."""
    from handlers.cart import _build_order_summary, _is_tashkent, _notify_sellers

    user_id = message.from_user.id
    lang = await database.get_user_language(user_id) or "uz"
    session = _session(user_id)
    location = session.get("location")   # (lat, lon, o'qiladigan manzil) yoki None

    name = (args.get("ism") or message.from_user.full_name or "—").strip()
    phone = (args.get("telefon") or session.get("phone") or "").strip()
    address = (args.get("manzil") or "").strip()
    payment = (args.get("tolov_turi") or "naqd").strip().lower()
    note = (args.get("izoh") or "").strip() or None
    delivery = DELIVERY.get((args.get("yetkazish") or "toshkent_kuryer").strip().lower())

    if not delivery:
        return "Xato: yetkazish turi toshkent_kuryer, yandex_taxi, bts yoki emu bo'lishi kerak."
    if delivery != "self" and payment != "karta":
        return ("Xato: bu yetkazish turida to'lov faqat karta orqali oldindan. Mijozga ayt "
                "yoki Toshkentda bo'lsa kuryerni taklif qil.")
    if delivery == "self" and location and not _is_tashkent(location[0], location[1]):
        return ("Xato: lokatsiya Toshkentdan tashqarida — Ketoshop kuryeri faqat Toshkent "
                "bo'ylab. Viloyatga BTS yoki EMU (karta orqali) taklif qil.")

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

    # _build_order_summary telefon, manzil va to'lov turini ham o'qiydi
    # (data["phone"], data["payment_method"]) — busiz KeyError beradi.
    data = {"delivery_method": delivery, "payment_method": "cash", "phone": phone,
            "address": address, "address_note": note}
    _, total, items_data, keto_redeem = await _build_order_summary(user_id, data, lang)
    if not items_data:
        return "Xato: savat bo'sh — avval mahsulot qo'shish kerak."

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
            delivery_method=delivery,
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
            "delivery_method": delivery,
            "payment_method": "cash",
            "status": "pending",
        }, lang)
    except Exception:
        # Buyurtma allaqachon bazada — admin xabari ketmasa ham uni yo'qotmaymiz.
        logger.exception("AI order %s: admin notification failed", order_id)

    logger.info("AI sales created order %s for user %s (payment=%s, delivery=%s)",
                order_id, user_id, payment, delivery)
    session["location"] = None   # keyingi buyurtma o'z lokatsiyasini so'rasin

    result = f"OK: buyurtma #{order_id} qabul qilindi, jami {_fmt(total)} so'm."
    if delivery == "self":
        result += " Toshkent bo'ylab 24 soat ichida yetkaziladi."
    else:
        result += " Yetkazish bo'yicha operator bog'lanadi."
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
    if name == "mahsulot_haqida":
        return await _tool_info(user_id, args)
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
    if name == "buyurtma_rasmiylashtirish":
        return await _tool_order(bot, message, args)
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
    model savatga soladi/buyurtma beradi, natijani o'qiydi va yakuniy matnni
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
    rules, catalog = _sales_rules(), await _dynamic_block(await _catalog_text())
    lang = await _lang(user_id)

    turn = await _step(state, rules, catalog, TOOLS, user=user_text,
                       max_tokens=MAX_TOKENS, history_limit=HISTORY_LIMIT)
    reply_text = ""
    for attempt in range(MAX_TURNS):
        if turn.refused:
            logger.warning("AI sales refusal for user %s", user_id)
            return _t("Kechirasiz, bu savolga bu yerda javob bera olmayman.\n"
                      "Batafsil ma'lumot olish uchun: ",
                      "Извините, на этот вопрос здесь ответить не могу.\n"
                      "Подробнее по телефону: ", lang) + SUPPORT_PHONES
        reply_text = turn.text or reply_text
        if not turn.calls:
            return reply_text

        results = []
        for call in turn.calls:
            try:
                output = await _run_tool(bot, message, call.name, call.args)
                is_error = output.startswith("Xato:")
            except Exception:
                logger.exception("AI tool %s failed", call.name)
                output, is_error = "Xato: ichki nosozlik.", True
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
    if not reply:
        return
    if _is_paused(user_id):
        return   # javob tayyorlanguncha admin o'zi gapga kirdi — ustidan gapirmaymiz
    await message.answer(reply)
    await _mirror(bot, message, user_text, reply)


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


async def _mirror(bot: Bot | None, message: Message, user_text: str, reply: str) -> None:
    """Har bir AI javobi adminlarga ovozsiz nusxa: mijoz nima yozdi, AI nima
    dedi. Mijoz endi support_relay ga tushmaydi — adminlar uning savolini shu
    yerdan ko'radi va xohlasa o'zi javob beradi."""
    user = message.from_user
    if bot is None or user.id in ADMIN_IDS:
        return
    try:
        if not await setting("mirror"):
            return
    except Exception:
        return
    who = html.escape(user.full_name or "—") + (f" (@{html.escape(user.username)})" if user.username else "")
    body = (f"💬 <b>AI suhbati</b> · {who} · <code>{user.id}</code>\n\n"
            f"👤 {html.escape(_short(user_text, 900))}\n\n"
            f"🤖 {html.escape(_short(reply, MIRROR_TEXT_MAX))}")
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, body, parse_mode="HTML",
                                   reply_markup=_mirror_kb(user.id), disable_notification=True)
        except Exception:
            logger.debug("AI mirror to admin %s failed", admin_id)


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
                "lokatsiya/telefon so'raydi va buyurtmani rasmiylashtiradi.\n\n"
                "O'chirish: /ai_off · Holat: /ai_holat")
    else:
        # Mijoz ko'radigan matn — kim bilan yozishayotgani haqida ortiqcha gap yo'q.
        text = _t("Assalomu alaykum, Keto shopga xush kelibsiz! 🌿\n\n"
                  "Nima qidiryapsiz? Yozing — mahsulot tanlashga yordam beraman va "
                  "buyurtmangizni rasmiylashtiraman.",
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


async def _status_text() -> str:
    _prune_sessions()
    catalog = await _catalog_text() if await _ready() else ""
    linked = _linked["id"]
    groups = sorted(GROUP_CHATS | ({linked} if linked else set()))
    lines = [
        "🤖 <b>AI sotuvchi</b>", "",
        f"Holat: {'✅ yoqilgan' if is_enabled() else '⚠️ kalit yo`q (o`chiq)'}",
        f"Kalit: {_key_status()}",
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
    await message.answer(await _status_text(), parse_mode="HTML",
                         reply_markup=_settings_kb(_settings["values"]))


@router.callback_query(F.data.startswith("aiset:"))
async def cb_setting(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer()
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
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer()
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
                      usd_rate: float | None) -> str:
    requests = sum(int(r["requests"]) for r in rows)
    tokens_in = sum(int(r["input_tokens"]) for r in rows)
    cached = sum(int(r["cached_tokens"]) for r in rows)
    tokens_out = sum(int(r["output_tokens"]) for r in rows)
    cost = sum(float(r["cost_usd"]) for r in rows)
    lines = [f"🤖 <b>AI sarfi — {day:%d.%m.%Y}</b> (kun yakuni)", ""]
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
    text = usage_report_text(due, rows, month, questions, rate)
    for admin_id in list(dict.fromkeys(ADMIN_IDS)):
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML", disable_notification=True)
        except Exception:
            logger.debug("AI usage report to %s failed", admin_id)
        await asyncio.sleep(0.05)
    logger.info("AI usage report for %s sent", due)
    return due


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


async def _has_session(message: Message) -> bool:
    """FILTR sifatida ishlatiladi, handler ichidagi tekshiruv sifatida emas —
    va bu ataylab. aiogram'da mos kelgan handler `return` qilsa ham xabar
    "ishlangan" hisoblanadi va support_relay ga yetib bormaydi. Ya'ni AI
    javob bermaydigan odamning savoli jimgina yo'qolardi."""
    user = message.from_user
    if not user or message.chat.type != "private" or not await _ready():
        return False
    if _is_paused(user.id) or not await _allowed(user.id):
        return False
    if user.id in _sessions:
        return True
    # Adminlarga AI o'zi javob bermaydi (egasi, 2026-10-12: "adminlar yozgan
    # xabarga javob yozmasin") — sinash uchun /ai bilan ochiladi.
    if user.id in ADMIN_IDS:
        return False
    # Mijoz /ai siz ham: yozsa suhbat o'zi ochiladi (_reply ichida _session()
    # yaratadi). /ai_off bosgan odam operatorga qaytgan bo'ladi.
    return AUTOSTART and user.id not in _opted_out


async def _awaiting_cheque(message: Message) -> bool:
    """Rasm/hujjat faqat AI karta raqamini bergan suhbatda chek deb olinadi —
    boshqa paytda mijozning rasmi bu yerda ushlanmaydi."""
    if not await _has_session(message):
        return False
    session = _sessions.get(message.from_user.id)
    return bool(session and session.get("awaiting_cheque"))


# Faqat minnatdorchilik — javob kutmaydi, model chaqirilmaydi. "ha", "ok",
# "xo'p", 👍 bu yerda YO'Q: ular buyurtmani tasdiqlash bo'lishi mumkin.
_THANKS_RE = re.compile(
    r"^\W*(?:katta\s+)?(?:rahmat|raxmat|rahmet|tashakkur|спасибо|спс|благодарю|рахмат|раҳмат|ташаккур)"
    r"(?:\s+(?:katta|sizga|сизга|катта|большое))?\W*$",
    re.IGNORECASE,
)


def is_thanks_only(text: str) -> bool:
    return bool(_THANKS_RE.match(text or ""))


@router.message(_has_session, F.text & ~F.text.startswith("/"))
async def on_text(message: Message, bot: Bot):
    """AI javob beradigan odamning oddiy matni. Router bot.py da support_relay
    dan OLDIN, qolgan hammasidan KEYIN turadi: menyu tugmalari va FSM oqimlari
    avvalgidek ishlayveradi, faqat hech kim ushlamagan matn AI ga tushadi."""
    if is_thanks_only(message.text):
        return   # "rahmat" ga javob shart emas — token ham ketmaydi
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
    try:
        from handlers.cart import _is_tashkent
        where = "Toshkent ichida" if _is_tashkent(lat, lng) else "Toshkentdan TASHQARIDA (viloyat)"
    except Exception:
        where = "hududi noma'lum"
    await _reply(bot, message, f"[Mijoz yetkazish lokatsiyasini yubordi: {pin} — {where}]")


@router.message(_has_session, F.contact)
async def on_contact(message: Message, bot: Bot):
    """Kontakt tugmasi orqali kelgan telefon — qo'lda yozishdan ishonchliroq."""
    phone = (message.contact.phone_number or "").strip()
    if phone and not phone.startswith("+"):
        phone = "+" + phone
    _session(message.from_user.id)["phone"] = phone
    await _reply(bot, message, f"[Mijoz telefon raqamini yubordi: {phone}]")


@router.message(_awaiting_cheque, F.photo | F.document)
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

    lang = await _lang(user.id)
    if not sent:
        await message.answer(_t("Rahmat! Chekni oldim, operatorimiz tez orada bog'lanadi.",
                                "Спасибо! Чек получил, оператор скоро свяжется с вами.", lang))
        return
    session["awaiting_cheque"] = None
    await message.answer(_t("✅ Rahmat! Chek qabul qilindi — operatorimiz to'lovni tekshirib tasdiqlaydi.",
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
        "- Karta raqami, to'lov, chek — bular haqida guruhda gaplashma, botga yubor.\n\n"
        "SALOMLASHISH\n"
        "- Kimdir salom bersa: 'Vaalaykum assalom! Assalomu alaykum, Keto shopga "
        "xush kelibsiz!' deb boshla, keyin savoliga javob ber.\n"
        "- Salom bermay savol bersa, salomni qisqa qil yoki umuman tashlab ket — "
        "guruhda har javobda salomlashish g'ashga tegadi.\n\n"
        "SEN KIMSAN\n"
        "- Sen Ketoshop jamoasining yordamchisisan. O'zingni robot, bot yoki "
        "sun'iy intellekt deb tanishtirma, 'katalog id', 'tizim' kabi ichki so'zlarni "
        "ishlatma. Robotmisan deb chin dildan so'rashsa, o'zingni odam deb atama: "
        "'Men Ketoshop yordamchisiman' de va xodim bilan bog'lanish uchun "
        "raqamni ber: " + SUPPORT_PHONES + "\n\n"
        "NOQULAY HOLAT\n"
        "- Shikoyat, janjal, buyurtma yoki to'lov muammosi, javobini bilmagan savol "
        "bo'lsa, guruhda muhokama qilma: qisqa uzr so'rab "
        "'Batafsil ma\'lumot olish uchun: " + SUPPORT_PHONES + "' deb yoz va "
        "shaxsiy yozishga taklif qil.\n\n"
        "GAPIRISH USLUBI\n"
        "- Odamdek, muloyim va samimiy yoz. Quruq robot javobi emas.\n"
        "- JUDA QISQA: 1-2 jumla. Guruhda uzun matn o'qilmaydi. HTML/markdown yo'q.\n"
        "- Kim qaysi tilda yozsa, o'sha tilda javob ber (o'zbekcha lotin, kirill yoki ruscha).\n"
        "- Emoji ni oz ishlat — javobiga bittadan ko'p emas.\n"
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
    r"mumkin|kerak|olmoqchi|olsam|buyurtma|zakaz|dostavka|yetkaz|sotib|"
    r"сколько|почем|цена|цену|где|как|какой|какая|какие|когда|можно|нужн|хочу|"
    r"заказ|доставк|есть ли|купить|"
    r"қанча|канча|нарх|қаер|каер|қандай|кандай|қачон|качон|қайси|кайси|нима|нега|"
    r"мумкин|керак|буюртма|етказ|сотиб)",
    re.IGNORECASE,
)


def looks_like_question(text: str) -> bool:
    return bool(_QUESTION_RE.search(text or ""))


async def _group_trigger(message: Message, bot: Bot) -> bool:
    """FILTR: bu guruh xabariga AI javob beradimi. Faqat begona (admin
    bo'lmagan) odamning savoliga — adminlar yozganiga hech qachon, hatto
    botni chaqirsa ham (egasi, 2026-10-12)."""
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
    await message.reply(reply)
    user_id = message.from_user.id
    _group_context[user_id] = (time.time(), text, reply)
    await _remember_quiet(user_id, "interest", f"guruhda so'radi: {_short(text, 200)}")


@router.message(_group_trigger, F.text | F.caption)
async def on_group_question(message: Message, bot: Bot):
    """Guruhdagi mijoz savoli. Javob reply bo'lib tushadi, ya'ni suhbat ipi
    ko'rinib turadi. Bitta odamning ketma-ket xabarlari bitta javob oladi."""
    text = (message.text or message.caption or "").replace("@" + BOT_USERNAME, "").strip()
    await _batch(("g", message.chat.id, message.from_user.id), message, text,
                 lambda msg, t: _group_answer(bot, msg, t))
