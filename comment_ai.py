"""
Izohlarga AI javob loyihasi — Claude API (TZ «4-qism», 2026-11-09).

Instagram/Facebook izohi kelganda (meta_comments.py) shu modul:
  1. Claude Haiku 5.5 bilan izohni ajratadi va 1–3 gaplik javob yozadi;
  2. murakkab savolda (salomatlik, shikoyat, boshqa) javobni Claude
     Sonnet 5.5 qayta yozadi — baribir faqat admin tasdig'i bilan ketadi;
  3. `decide()` — javobni AI o'zi yuboradimi, admin tasdig'iga boradimi.
     Bu qaror modelda emas, shu yerda, kodda: model qaysi turga qo'ysa ham
     sog'liq yoki shikoyat izohi o'zi ketmaydi.

Bilim bazasi (manzil, yetkazish, buyurtma, optom, glyuten …) bazada turadi,
admin /izoh_bilim bilan o'zgartiradi; boshlang'ich matnlar — DEFAULT_KB
(do'kon manzili va yetkazish shartlari ai_sales/config bilan bir manbadan).
Narx va mavjudlik — jonli katalogdan (bazadagi narx, chegirma, qoldiq).

QAYSI AI (egasi, 2026-11-09: "antropic emas, gpt api bor")
  Asosiy — OpenAI (GPT): AI sotuvchining o'sha kaliti (/ai_kalit yoki env
  OPENAI_API_KEY) va o'sha modeli (gpt-5.4-mini); oddiy izoh — reasoning
  "low", murakkabi — "medium". Claude yo'li ham turibdi: faqat OpenAI kaliti
  yo'q va ANTHROPIC_API_KEY bor bo'lsa (yoki COMMENT_AI_PROVIDER=anthropic).
  Kalit bo'lmasa AI o'chiq: izohlar baribir botga tushadi, adminlar o'zi
  javob yozadi.
"""
import json
import logging
import os
import re
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# TZ: "Oddiy izohlarni ajratish va qisqa javoblar uchun claude-haiku-5-5 ...
# Murakkab savollar uchun claude-sonnet-5-5."
SIMPLE_MODEL = os.getenv("COMMENT_AI_MODEL", "claude-haiku-5-5").strip()
COMPLEX_MODEL = os.getenv("COMMENT_AI_COMPLEX_MODEL", "claude-sonnet-5-5").strip()
# Sonnet 5.5 rad etsa (refusal), Claude API o'zi mos modelga o'tkazadi.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 2000          # fikrlash + qisqa JSON — ortig'i bilan
CATALOG_TTL = 600

CATEGORIES = ("rahmat", "manzil", "yetkazish", "buyurtma", "narx", "mavjudlik",
              "salomatlik", "shikoyat", "spam", "boshqa")
CATEGORY_LABELS = {
    "rahmat": "🙏 Rahmat / maqtov", "manzil": "📍 Manzil", "yetkazish": "🚚 Yetkazish",
    "buyurtma": "🛍 Buyurtma qanday", "narx": "💰 Narx", "mavjudlik": "📦 Bor-yo'qligi",
    "salomatlik": "🩺 Salomatlik", "shikoyat": "⚠️ Tanqid / shikoyat", "spam": "🚫 Spam",
    "boshqa": "❓ Boshqa savol",
}
# TZ jadvali: kim yuboradi.
AUTO_ALWAYS = {"rahmat"}
AUTO_IF_KNOWN = {"manzil", "yetkazish", "buyurtma", "narx", "mavjudlik"}
COMPLEX = {"salomatlik", "shikoyat", "boshqa"}

AI_MODES = ("avto", "tasdiq", "off")

SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "reply": {"type": "string"},
        "confident": {"type": "boolean"},
    },
    "required": ["category", "reply", "confident"],
    "additionalProperties": False,
}

KB_KEYS = {
    "manzil": "Do'kon manzili",
    "yetkazish": "Yetkazib berish shartlari",
    "buyurtma": "Buyurtma berish yo'li",
    "optom": "Optom",
    "glyuten": "Glyuten haqida",
    "kepak": "Kepak haqida",
    "boshqa": "Qo'shimcha faktlar",
    "tpl_narx": "Shablon: 💰 Narx",
    "tpl_yetkazish": "Shablon: 🚚 Yetkazish",
    "tpl_bot": "Shablon: 🤖 Botga taklif",
}


def default_kb() -> dict:
    """Boshlang'ich matnlar — izoh-javoblari-2026-11-09 (3-bo'lim) va do'konning
    o'z qoidalari. Manzil ai_sales'dagi bilan bir xil (egasi, 2026-11-04)."""
    from ai_sales import SHOP_LANDMARK, SHOP_STREET
    from config import FREE_DELIVERY_FROM
    from handlers.cart import SELF_DELIVERY_FEE

    def som(n):
        return f"{int(n):,}".replace(",", " ")

    delivery = (f"Toshkent ichida kuryer — {som(SELF_DELIVERY_FEE)} so'm, {som(FREE_DELIVERY_FROM)} "
                "so'mdan ortiq buyurtmaga bepul, 24 soat ichida; shoshilinch bo'lsa Yandex Taxi orqali; "
                "viloyatlarga pochta orqali yuboramiz; do'kondan o'zi olib ketish bepul.")
    return {
        "manzil": f"{SHOP_STREET}, mo'ljal: {SHOP_LANDMARK}. Aniq manzil profildagi aktual storisda ✅",
        "yetkazish": delivery,
        "buyurtma": "Telegram botimiz orqali: @ketoshopbot → «🛍 Do'konni ochish»",
        "optom": "Optom bo'yicha: 94 618 05 07",
        "glyuten": ("Glyuten — bug'doy, arpa va javdar unidagi oqsil; aynan u xamirni cho'ziluvchan qiladi. "
                    "Ba'zi odamlarda hazm bo'lmay, qorin dam bo'lishi, holsizlik kabi muammolar beradi. "
                    "Makkajo'xori va jo'xori uni tabiatan glyutensiz; ishlab chiqarishda bug'doy bilan "
                    "aralashmasligi uchun «gluten free» belgili mahsulotni tanlash tavsiya etiladi. "
                    "Batafsil — profilimizdagi «Glyuten nima? 2-qism» videosida."),
        "kepak": "",
        "boshqa": "",
        "tpl_narx": "Assalomu alaykum! Narxlar va to'liq ro'yxat Telegram botimizda: @ketoshopbot 🌿",
        "tpl_yetkazish": f"Assalomu alaykum! {delivery} 🚚",
        "tpl_bot": "Assalomu alaykum! Buyurtma Telegram botimiz orqali: @ketoshopbot → «🛍 Do'konni ochish» 🌿",
    }


def kb_with_defaults(stored: dict | None) -> dict:
    kb = default_kb()
    for key, value in (stored or {}).items():
        if key in KB_KEYS and isinstance(value, str):
            kb[key] = value
    return kb


# ─────────────────────────────── the policy ─────────────────────────────────

def decide(category: str | None, confident: bool, mode: str, fresh: bool = True) -> str:
    """'auto' (AI o'zi yuboradi), 'approve' (admin tasdig'i) yoki 'spam'.

    TZ jadvali: rahmat — darhol o'zi; manzil/yetkazish/buyurtma, narx/mavjudlik
    — bilim bazasida aniq javob bo'lsa o'zi, bo'lmasa admin; sog'liq, shikoyat
    va boshqa savollar — faqat admin; spam — xabar + 🙈. `mode`='tasdiq' —
    hammasi admin orqali; eski izoh (fresh=False) ham o'zi ketmaydi."""
    if category == "spam":
        return "spam"
    if mode != "avto" or not fresh or category not in CATEGORIES:
        return "approve"
    if category in AUTO_ALWAYS:
        return "auto"
    if category in AUTO_IF_KNOWN and confident:
        return "auto"
    return "approve"


# ─────────────────────────────── the prompt ─────────────────────────────────

RULES = """Sen Ketoshop do'konining Instagram va Facebook sahifasidagi izohlarga javob yozasan.
Ketoshop Toshkentda keto, glyutensiz va PP mahsulotlari sotadi (@ketoshop.uz, Telegram: @ketoshopbot).

VAZIFA: izohni bitta turga ajrat (category) va unga ochiq javob yoz (reply).

TURLAR
- rahmat — rahmat, maqtov, emoji, "zo'r", duo.
- manzil — do'kon qayerda, manzil, lokatsiya.
- yetkazish — yetkazib berish, viloyatga, kuryer, muddat.
- buyurtma — qanday buyurtma beraman, qayerdan olaman.
- narx — narxi qancha.
- mavjudlik — bormi, sotuvdami, qaysi mahsulotlar bor.
- salomatlik — kasallik, bolalar, dori, homiladorlik, diabet, tashxis, "zararimi/foydasimi".
- shikoyat — tanqid, norozilik, xato topgani (masalan videodagi xato), aldov deyish.
- spam — reklama, havola tarqatish, haqorat, mavzuga aloqasiz.
- boshqa — yuqoridagilarga kirmaydigan savol yoki fikr.

JAVOB QOIDALARI
- Izoh qaysi yozuvda bo'lsa, o'shanda javob ber: o'zbek lotin, o'zbek kirill yoki rus. Izoh kirillda bo'lsa — javob ham kirillda.
- Qisqa: 1–3 gap. Xushmuomala, iliq, "Assalomu alaykum" bilan boshla (rahmat/emoji izohiga salomsiz qisqa rahmat ham bo'ladi). 1–2 ta emoji.
- Faqat quyidagi BILIM BAZASI va KATALOGdagi faktlarni yoz. Narx, mahsulot, muddat, manzil yoki telefonni o'zing o'ylab topma.
- Narx so'ralsa: mahsulot katalogda aniq topilsa — narxini ayt; topilmasa yoki qaysi mahsulot ekani noaniq bo'lsa — confident=false.
- Tibbiy va'da berma ("davolaydi", "kasallikka yordam beradi", "qandni tushiradi" kabi). Sog'liq savollarida "shifokor bilan maslahatlashing" deb qo'sh.
- Instagram izohida havola bosilmaydi: havola yozma, "@ketoshopbot" deb yoz yoki "profildagi havola orqali" de.
- O'zingni bot, AI yoki dastur deb tanishtirma. Ichki so'zlarni (bilim bazasi, katalog, kategoriya) ishlatma.
- Spam va haqoratga javob yozma: reply bo'sh qator bo'lsin.

confident = true faqat javobdagi har bir fakt bilim bazasi yoki katalogda aniq yozilgan bo'lsa. Ikkilansang — false."""


def comment_prompt(c: dict) -> str:
    platform = "Instagram" if c.get("platform") == "ig" else "Facebook"
    where = f"reklama «{c['ad_name']}»" if c.get("ad_name") else ("reklama" if c.get("ad_id") else "post")
    who = c.get("username") or "mijoz"
    return (f"{platform} · {where}\nIzoh muallifi: {who}\n"
            f"IZOH:\n{(c.get('text') or '').strip()[:1500]}")


def kb_block(kb: dict, catalog: str) -> str:
    lines = ["BILIM BAZASI"]
    for key in ("manzil", "yetkazish", "buyurtma", "optom", "glyuten", "kepak", "boshqa"):
        if (kb.get(key) or "").strip():
            lines.append(f"- {KB_KEYS[key]}: {kb[key].strip()}")
    lines += ["", "KATALOG (nomi — narxi; «tugagan» — hozir sotuvda yo'q)", catalog or "—"]
    return "\n".join(lines)


_catalog_cache: tuple[float, str] = (0.0, "")


async def catalog_text() -> str:
    """Jonli katalog: faol, chakana mahsulotlar va bugungi narxi (chegirma bilan)."""
    global _catalog_cache
    if _catalog_cache[1] and time.monotonic() - _catalog_cache[0] < CATALOG_TTL:
        return _catalog_cache[1]
    import database
    import manual_order
    products = await database.admin_list_products(include_inactive=False)
    rows = []
    for p in sorted(products, key=lambda p: (p.get("category") or "", p.get("name") or "")):
        if p.get("b2b_only"):
            continue
        price = int(round(manual_order.shelf_price(p)))
        stock = "" if float(p.get("quantity") or 0) > 0 else " (tugagan)"
        rows.append(f"- {p.get('name')} — {price:,} so'm{stock}".replace(",", " "))
    text = "\n".join(rows)
    _catalog_cache = (time.monotonic(), text)
    return text


# ─────────────────────────────── calling Claude ─────────────────────────────

@dataclass
class Draft:
    category: str
    reply: str
    confident: bool
    model: str


_client = None
_openai_client: tuple[str, object] | None = None


async def _openai_key() -> str:
    """AI sotuvchi ishlatayotgan OpenAI kaliti: /ai_kalit bilan botga
    berilgani ustun, bo'lmasa env."""
    try:
        import ai_sales
        await ai_sales._load_settings()
        prov = ai_sales.PROVIDER
        if prov is not None and getattr(prov, "name", "") == "openai" and getattr(prov, "api_key", ""):
            return prov.api_key
    except Exception:
        logger.warning("comment AI: AI seller settings unreadable", exc_info=True)
    return os.getenv("OPENAI_API_KEY", "").strip()


def openai_model() -> str:
    import ai_provider
    return os.getenv("COMMENT_AI_OPENAI_MODEL", "").strip() or ai_provider.DEFAULT_MODELS["openai"]


async def provider() -> str:
    """'openai', 'anthropic' yoki '' (kalit yo'q). GPT birinchi."""
    wanted = os.getenv("COMMENT_AI_PROVIDER", "").strip().lower()
    oa = await _openai_key()
    an = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if wanted == "anthropic" and an:
        return "anthropic"
    if oa:
        return "openai"
    return "anthropic" if an else ""


async def provider_label() -> str:
    """/izohlar va /izoh_ai uchun: qaysi AI ishlayapti, bo'sh — hech biri."""
    prov = await provider()
    if prov == "openai":
        return f"GPT ({openai_model()})"
    if prov == "anthropic":
        return f"Claude ({SIMPLE_MODEL} / {COMPLEX_MODEL})"
    return ""


def _get_client():
    global _client
    if _client is None:
        from anthropic import AsyncAnthropic
        _client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY", "").strip(),
                                 timeout=60.0, max_retries=2)
    return _client


_PRICES = {  # $ / 1M token: kirish, kesh o'qish, chiqish (2026-10 jadvali)
    "claude-haiku-5-5": (0.10, 0.01, 0.50),
    "claude-sonnet-5-5": (2.00, 0.20, 10.00),
}


async def _record_usage(model: str, usage) -> None:
    try:
        fresh = int(getattr(usage, "input_tokens", 0) or 0)
        cached = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        written = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        out = int(getattr(usage, "output_tokens", 0) or 0)
        p_in, p_cache, p_out = _PRICES.get(model, (0, 0, 0))
        cost = ((fresh + written * 1.25) * p_in + cached * p_cache + out * p_out) / 1_000_000
        import database
        await database.record_ai_usage(model, "anthropic", fresh + cached + written, cached, out, cost)
    except Exception:
        logger.warning("comment AI usage not recorded", exc_info=True)


def _parse(resp) -> dict | None:
    if getattr(resp, "stop_reason", None) in ("refusal", "max_tokens"):
        logger.info("comment AI stopped: %s", resp.stop_reason)
        return None
    text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        logger.warning("comment AI returned non-JSON: %.200s", text)
        return None
    if data.get("category") not in CATEGORIES or not isinstance(data.get("reply"), str):
        return None
    return data


async def _ask(model: str, system: list, user: str, effort: str, fallback: bool) -> dict | None:
    import anthropic
    client = _get_client()
    kwargs = dict(
        model=model, max_tokens=MAX_TOKENS, system=system,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    try:
        if fallback:
            # `fallbacks` body orqali: o'rnatilgan SDK versiyasida bu parametr
            # nomi bo'lmasligi mumkin (0.105 da yo'q), API esa qabul qiladi.
            resp = await client.beta.messages.create(betas=[FALLBACK_BETA],
                                                     extra_body={"fallbacks": "default"}, **kwargs)
        else:
            resp = await client.messages.create(**kwargs)
    except anthropic.RateLimitError:
        logger.warning("comment AI rate-limited (%s)", model)
        return None
    except anthropic.APIStatusError as e:
        logger.warning("comment AI error %s (%s): %s", e.status_code, model, e.message)
        return None
    except anthropic.APIConnectionError:
        logger.warning("comment AI connection failed (%s)", model)
        return None
    await _record_usage(model, getattr(resp, "usage", None))
    return _parse(resp)


async def _ask_openai(key: str, model: str, instructions: str, user: str, effort: str) -> dict | None:
    """OpenAI Responses API, qat'iy JSON sxemasi bilan (AI sotuvchidagi kabi
    Responses — GPT-5.x da reasoning shu yerda ishlaydi)."""
    global _openai_client
    import ai_provider
    import openai
    if _openai_client is None or _openai_client[0] != key:
        _openai_client = (key, openai.AsyncOpenAI(api_key=key, timeout=60.0, max_retries=2))
    client = _openai_client[1]
    try:
        resp = await client.responses.create(
            model=model, instructions=instructions,
            input=[{"role": "user", "content": user}],
            reasoning={"effort": effort}, max_output_tokens=MAX_TOKENS,
            text={"format": {"type": "json_schema", "name": "izoh_javob", "schema": SCHEMA, "strict": True}},
        )
    except openai.RateLimitError:
        logger.warning("comment AI rate-limited (%s)", model)
        return None
    except openai.APIStatusError as e:
        logger.warning("comment AI error %s (%s): %s", e.status_code, model, e.message)
        return None
    except openai.APIConnectionError:
        logger.warning("comment AI connection failed (%s)", model)
        return None
    usage = ai_provider._openai_usage(getattr(resp, "usage", None))
    try:
        import database
        await database.record_ai_usage(model, "openai", usage.input, usage.cached, usage.output,
                                       ai_provider.estimate_cost(model, usage.input, usage.cached, usage.output))
    except Exception:
        logger.warning("comment AI usage not recorded", exc_info=True)
    for item in getattr(resp, "output", None) or []:
        if getattr(item, "type", "") == "message" and any(
                getattr(part, "type", "") == "refusal" for part in (getattr(item, "content", None) or [])):
            logger.info("comment AI refused (%s)", model)
            return None
    if getattr(resp, "status", "completed") == "incomplete":
        logger.info("comment AI incomplete (%s)", model)
        return None
    text = getattr(resp, "output_text", "") or ""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        logger.warning("comment AI returned non-JSON: %.200s", text)
        return None
    if data.get("category") not in CATEGORIES or not isinstance(data.get("reply"), str):
        return None
    return data


async def _draft_openai(comment: dict, kb: dict) -> Draft | None:
    key = await _openai_key()
    model = openai_model()
    # Barqaror qism oldinda — OpenAI uzun prefiksni o'zi keshlaydi.
    instructions = RULES + "\n\n" + kb_block(kb, await catalog_text())
    user = comment_prompt(comment)
    first = await _ask_openai(key, model, instructions, user, effort="low")
    if first is None:
        return None
    result = Draft(first["category"], first["reply"].strip(), bool(first["confident"]), model)
    if result.category in COMPLEX:
        try:
            better = await _ask_openai(key, model, instructions, user, effort="medium")
        except Exception:
            logger.exception("comment AI: complex redraft failed — keeping the first draft")
            better = None
        if better and better.get("reply", "").strip():
            result = Draft(result.category, better["reply"].strip(), False, model)
    if result.category == "spam":
        result.reply = ""
    return result


async def draft(comment: dict, kb: dict) -> Draft | None:
    """Javob loyihasi yoki None (kalit yo'q, xato, rad etildi — admin o'zi yozadi)."""
    prov = await provider()
    if prov == "openai":
        return await _draft_openai(comment, kb)
    if prov != "anthropic":
        return None
    system = [
        {"type": "text", "text": RULES},
        # Bilim bazasi + katalog — tizim promptining keshlanadigan qismi.
        {"type": "text", "text": kb_block(kb, await catalog_text()), "cache_control": {"type": "ephemeral"}},
    ]
    user = comment_prompt(comment)
    first = await _ask(SIMPLE_MODEL, system, user, effort="low", fallback=False)
    if first is None:
        return None
    result = Draft(first["category"], first["reply"].strip(), bool(first["confident"]), SIMPLE_MODEL)
    if result.category in COMPLEX:
        try:
            better = await _ask(COMPLEX_MODEL, system, user, effort="medium", fallback=True)
        except Exception:
            logger.exception("comment AI: complex redraft failed — keeping the first draft")
            better = None
        if better and better.get("reply", "").strip():
            # Ehtiyot tomonga: turini Haiku qo'ygandek qoldiramiz (murakkab).
            result = Draft(result.category, better["reply"].strip(), False, COMPLEX_MODEL)
    if result.category == "spam":
        result.reply = ""
    return result


# ─────────────────────────────── helpers ────────────────────────────────────

_CYR = re.compile(r"[а-яёўқғҳ]", re.IGNORECASE)


def is_cyrillic(text: str | None) -> bool:
    letters = re.findall(r"[^\W\d_]", text or "")
    return bool(letters) and sum(1 for ch in letters if _CYR.match(ch)) * 2 > len(letters)


def in_script_of(comment_text: str | None, reply: str) -> str:
    """Shablon (lotinda) izoh kirillda bo'lsa — kirillga."""
    if is_cyrillic(comment_text) and not is_cyrillic(reply):
        from translit import lat_to_cyr
        return lat_to_cyr(reply)
    return reply
