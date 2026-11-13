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
# Shu turlarga ikkinchi, chuqurroq o'tish (reasoning "medium").
COMPLEX = {"salomatlik", "shikoyat", "boshqa"}

AI_MODES = ("avto", "tasdiq", "off")

# Direct'dagi rahmat oxiriga kod o'zi qo'shadigan havola (egasi, 2026-11-11:
# "barcha sog'lom Keto va PP mahsulotlarini … shu yerdan ko'rib chiqishingiz
# mumkin, deb: https://t.me/ketoshopbot/shop shu linkni bergin").
SHOP_LINK = os.getenv("META_COMMENTS_SHOP_LINK", "https://t.me/ketoshopbot/shop").strip()
DEFAULT_DM = ("Izohingiz uchun katta rahmat! 🌿 Barcha sog'lom keto va PP mahsulotlarimizni "
              "shu yerdan bemalol ko'rib chiqishingiz mumkin:")
# ai_usage da izohlar sarfi AI sotuvchinikidan alohida qatorda turadi.
USAGE_TAG = " · izohlar"

SCHEMA = {
    "type": "object",
    "properties": {
        "category": {"type": "string", "enum": list(CATEGORIES)},
        "reply": {"type": "string"},
        "confident": {"type": "boolean"},
        "dm": {"type": "string"},
    },
    "required": ["category", "reply", "confident", "dm"],
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
    from ai_sales import SHOP_HOURS, SHOP_LANDMARK, SHOP_STREET
    from config import FREE_DELIVERY_FROM
    from handlers.cart import SELF_DELIVERY_FEE

    def som(n):
        return f"{int(n):,}".replace(",", " ")

    delivery = (f"Toshkent ichida kuryer — {som(SELF_DELIVERY_FEE)} so'm, {som(FREE_DELIVERY_FROM)} "
                "so'mdan ortiq buyurtmaga bepul, 24 soat ichida; shoshilinch bo'lsa Yandex Taxi orqali; "
                "viloyatlarga pochta orqali yuboramiz; do'kondan o'zi olib ketish bepul.")
    return {
        "manzil": (f"{SHOP_STREET}, mo'ljal: {SHOP_LANDMARK}. Ish vaqti (kelib olib ketish uchun): "
                   f"{SHOP_HOURS}. Aniq manzil profildagi aktual storisda ✅"),
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


# Oddiy savollar: AI aniq javob topmasa ham — bilim bazasidagi tayyor javob.
_TEMPLATE_FOR = {"narx": "tpl_narx", "mavjudlik": "tpl_narx", "buyurtma": "tpl_bot",
                 "yetkazish": "tpl_yetkazish"}


def template_reply(category: str | None, kb: dict) -> str | None:
    """Narx / bor-yo'qligi / buyurtma / yetkazish / manzil savoliga tayyor
    javob (2026-11-12: «Narxi qancha», «Нархи» kabi izohlar kutib qolgan edi).
    Sog'liq, shikoyat va boshqa savollar uchun — None (admin javob beradi)."""
    if category == "manzil":
        text = (kb.get("manzil") or "").strip()
        return f"Assalomu alaykum! Manzilimiz: {text} Viloyatlarga pochta orqali ham yuboramiz 🌿" if text else None
    key = _TEMPLATE_FOR.get(category or "")
    text = (kb.get(key) or "").strip() if key else ""
    return text or None


# ─────────────────────────────── the policy ─────────────────────────────────

def decide(category: str | None, confident: bool, mode: str) -> str:
    """'auto' (AI o'zi yuboradi), 'approve' (adminga) yoki 'spam' (javobsiz).

    Egasi, 2026-11-11: "ai o'zi javoblarni yuborishni boshlasin hammasini …
    botga faqat ai javob topa olmagan izohlar kelsin". 'avto' rejimda AI
    javob topgan har qanday izohga — rahmat, savol, sog'liq, shikoyat, eski
    izoh ham — o'zi yozadi; topa olmaganini (confident=false) adminga beradi.
    Spamga yozmaydi va adminni ham bezovta qilmaydi. 'tasdiq' — hammasi admin
    orqali."""
    if category == "spam":
        return "spam"
    if mode != "avto" or category not in CATEGORIES:
        return "approve"
    return "auto" if confident else "approve"


# ─────────────────────────────── the prompt ─────────────────────────────────

RULES = """Sen Keto shop jamoasi nomidan Instagram va Facebook sahifamizdagi izohlarga javob yozasan.
Keto shop Toshkentda keto, glyutensiz va PP mahsulotlari sotadi (@ketoshop.uz, Telegram: @ketoshopbot).

VAZIFA: izohni bitta turga ajrat (category), unga ochiq javob yoz (reply) va javobing izohga
to'liq javob bo'la oladimi — ayt (confident). Javobing izoh ostida hammaga ko'rinadi.

KIM NOMIDAN: har doim "biz" — Keto shop jamoasi nomidan (egasi, 2026-11-11: "aytaman emas, aytamiz
desin"). "Aytamiz", "yuboramiz", "xursandmiz", "bizda bor"; hech qachon "men", "aytaman", "yuboraman".

IZOH QAYSI POST OSTIDA: izoh o'sha post yoki reels haqida. "POST MATNI" va post rasmi (berilgan bo'lsa)
— postda ko'rsatilgan mahsulot; savoldagi "bu", "narxi qancha" shu mahsulotga tegishli. Rasmdagi
mahsulotni KATALOG bilan solishtirib aniqla.
- HECH QACHON "qaysi mahsulot?", "nomini yoki suratini yuboring" kabi qayta so'rama: mahsulot o'zimizning
  postimizda turibdi (egasi, 2026-11-11: "postda yoki videoda mahsulot bo'ladi … bu javob mantiqsiz").
- Mahsulotni aniq aniqlay olmasang ham — "videodagi mahsulot va barcha narxlar @ketoshopbot da, Direct'ga
  ham havolasini yubordik" mazmunida javob ber (bu to'liq javob, confident=true).

ODOB: biror narsa so'raganda yoki taklif qilganda "iltimos" yoki "imkoningiz bo'lsa" ishlat (masalan,
"iltimos, Direct'ga yozing", "imkoningiz bo'lsa, @ketoshopbot ga kiring").

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

QANDAY YOZISH — muloyim, jonli odamdek, biroz hamdardlik bilan
- Iliq, samimiy va sodda yoz — do'konimiz jamoasi yozgandek. Har javob o'ziga xos bo'lsin:
  shablon gaplar va har safar bir xil boshlanish bo'lmasin, "Ha," bilan boshlama.
- Odamni eshitganingni qisqa va tabiiy ko'rsat: savoliga qiziqish, tashvishiga tushunish ("Tushunaman,
  bu muhim"), maqtoviga samimiy minnatdorchilik. Ortiqcha shirinsuxanlik va mubolag'a yo'q.
- Savolga aniq, foydali javob ber; kerak bo'lsa keyingi qadamni ayt (masalan, buyurtma — @ketoshopbot orqali).
- Qisqa: 1–3 gap. O'rinli bo'lsa 1–2 ta emoji.
- Savol yoki muammoga "Assalomu alaykum" bilan boshlasang bo'ladi, lekin har doim shart emas;
  rahmat, maqtov va emojiga — qisqa, samimiy rahmat.
- Izoh qaysi yozuvda bo'lsa, o'shanda javob ber: o'zbek lotin, o'zbek kirill yoki rus. Izoh kirillda bo'lsa — javob ham kirillda.
- Shikoyat yoki norozilikka: avval kechirim so'ra yoki tushunishingni bildir, oqlanma va bahslashma;
  hal qilish uchun Direct'ga yoki @ketoshopbot ga yozishni taklif qil.
- Xatomizni ko'rsatishsa (masalan, videoda): samimiy rahmat ayt va to'g'ri ma'lumotni ber.

FAKTLAR
- Faqat quyidagi BILIM BAZASI va KATALOGdagi faktlarni yoz. Narx, mahsulot, muddat, manzil yoki telefonni o'zing o'ylab topma.
- Mahsulot nomini faqat KATALOGdagidek yoz (masalan "Tabiiy GHEE 1000ml"). POST MATNI va rasm faqat qaysi
  katalog mahsuloti ekanini topish uchun: post sarlavhasidagi chiroyli nomni, kelib chiqish joyini yoki
  sifat ta'rifini (masalan "Bahmal tog' GHEEsi") mahsulot nomi yoki fakt sifatida takrorlama (egasi,
  2026-11-13: "bahmal tog' ghee si deb yozipsan nega? aniqmi?").
- Narx so'ralsa: mahsulot (izohdan, POST MATNIdan yoki rasmdan) katalogda aniq topilsa — nomi va narxini
  ayt. Aniqlab bo'lmasa — narxlar @ketoshopbot da ekanini va Direct'ga havola yuborganimizni ayt
  (confident=true). Narxni taxmin qilma.
- Bitta odam bir xil matnni boshqalarni belgilab (@...) ko'p marta yozgan bo'lsa — mazmuniga bir marta
  javob ber; reklama yoki tarqatma bo'lsa — spam.
- Tibbiy va'da berma ("davolaydi", "kasallikka yordam beradi", "qandni tushiradi" kabi). Sog'liq savoliga —
  bilim bazasidagi umumiy ma'lumot va "shifokor bilan maslahatlashing".
- Instagram izohida havola bosilmaydi: havola yozma, "@ketoshopbot" deb yoz yoki "profildagi havola orqali" de.
- O'zingni bot, AI yoki dastur deb tanishtirma. Ichki so'zlarni (bilim bazasi, katalog, kategoriya) ishlatma.
- Spam va haqoratga javob yozma: reply bo'sh qator bo'lsin.

confident — javobing izohga to'liq va to'g'ri javobmi:
- true: rahmat, maqtov, emoji; javobi bilim bazasi yoki katalogda bor savol; sog'liq savoliga umumiy javob
  va shifokor tavsiyasi; shikoyatga kechirim va Direct'ga yoki botga taklif.
- false: javob uchun bilim bazasi yoki katalogda yo'q fakt kerak bo'lsa; odam nima so'rayotgani tushunarsiz
  bo'lsa; aniq buyurtma muammosi (kelmadi, noto'g'ri keldi, pul qaytarish) yoki optom narx kelishuvi kabi
  odam qarori kerak bo'lsa; aniq dori, doza yoki davolash so'ralsa. Ikkilansang — false.

dm — shu odamga Direct'ga boradigan 1–2 gaplik samimiy xabar: izoh qoldirgani uchun rahmat va barcha
sog'lom keto va PP mahsulotlarimizni ko'rib chiqishga iliq taklif. Har safar o'zingcha, ijodiy yoz,
izoh yozuvida. Havola YOZMA — uni o'zimiz oxiriga qo'shamiz. Spam va haqoratga — bo'sh qator."""


def comment_prompt(c: dict) -> str:
    platform = "Instagram" if c.get("platform") == "ig" else "Facebook"
    where = f"reklama «{c['ad_name']}»" if c.get("ad_name") else ("reklama" if c.get("ad_id") else "post")
    who = c.get("username") or "mijoz"
    caption = (c.get("post_caption") or "").strip()
    post = f"POST MATNI:\n{caption[:700]}\n\n" if caption else ""
    return (f"{platform} · {where}\nIzoh muallifi: {who}\n\n{post}"
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
    dm: str = ""


_URL = re.compile(r"(https?://\S+|t\.me/\S+)", re.IGNORECASE)


def dm_text(comment_text: str | None, dm: str | None) -> str:
    """Direct'dagi rahmat: AI yozgani (yoki DEFAULT_DM) + do'kon havolasi.
    Havolani har doim kod qo'yadi — model o'zgartirib yozmasin."""
    body = _URL.sub("", (dm or "").strip()).strip() or DEFAULT_DM
    body = in_script_of(comment_text, body)
    return f"{body}\n\n👉 {SHOP_LINK}"


def _build(first: dict, better: dict | None, model: str, better_model: str) -> Draft:
    """Birinchi o'tish turini qoldiramiz; murakkab savolda chuqurroq o'tish
    bo'lsa — uning javobi va o'z bahosi (confident) olinadi."""
    result = Draft(first["category"], first["reply"].strip(), bool(first["confident"]), model,
                   (first.get("dm") or "").strip())
    if better and (better.get("reply") or "").strip():
        result = Draft(result.category, better["reply"].strip(), bool(better.get("confident")), better_model,
                       (better.get("dm") or result.dm or "").strip())
    if result.category == "spam":
        result.reply, result.dm = "", ""
    return result


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
        await database.record_ai_usage(model + USAGE_TAG, "anthropic", fresh + cached + written, cached, out, cost)
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


async def _ask(model: str, system: list, user: str, effort: str, fallback: bool,
               image: str | None = None) -> dict | None:
    import anthropic
    client = _get_client()
    content = ([{"type": "image", "source": {"type": "url", "url": image}}] if image else []) + \
              [{"type": "text", "text": user}]
    kwargs = dict(
        model=model, max_tokens=MAX_TOKENS, system=system,
        messages=[{"role": "user", "content": content}],
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
    except anthropic.BadRequestError as e:
        if image:   # post rasmi ochilmadi (muddati o'tgan havola) — rasmsiz
            logger.info("comment AI: image refused (%s), retrying without it", e.message)
            return await _ask(model, system, user, effort, fallback)
        logger.warning("comment AI error 400 (%s): %s", model, e.message)
        return None
    except anthropic.APIStatusError as e:
        logger.warning("comment AI error %s (%s): %s", e.status_code, model, e.message)
        return None
    except anthropic.APIConnectionError:
        logger.warning("comment AI connection failed (%s)", model)
        return None
    await _record_usage(model, getattr(resp, "usage", None))
    return _parse(resp)


async def _ask_openai(key: str, model: str, instructions: str, user: str, effort: str,
                      image: str | None = None) -> dict | None:
    """OpenAI Responses API, qat'iy JSON sxemasi bilan (AI sotuvchidagi kabi
    Responses — GPT-5.x da reasoning shu yerda ishlaydi). `image` — post
    rasmi yoki reels muqovasi (detail "low" — arzon)."""
    global _openai_client
    import ai_provider
    import openai
    if _openai_client is None or _openai_client[0] != key:
        _openai_client = (key, openai.AsyncOpenAI(api_key=key, timeout=60.0, max_retries=2))
    client = _openai_client[1]
    content = [{"type": "input_text", "text": user}]
    if image:
        content.append({"type": "input_image", "image_url": image, "detail": "low"})
    try:
        resp = await client.responses.create(
            model=model, instructions=instructions,
            input=[{"role": "user", "content": content}],
            reasoning={"effort": effort}, max_output_tokens=MAX_TOKENS,
            text={"format": {"type": "json_schema", "name": "izoh_javob", "schema": SCHEMA, "strict": True}},
        )
    except openai.RateLimitError:
        logger.warning("comment AI rate-limited (%s)", model)
        return None
    except openai.BadRequestError as e:
        if image:   # post rasmi ochilmadi (muddati o'tgan havola) — rasmsiz
            logger.info("comment AI: image refused (%s), retrying without it", e.message)
            return await _ask_openai(key, model, instructions, user, effort)
        logger.warning("comment AI error 400 (%s): %s", model, e.message)
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
        await database.record_ai_usage(model + USAGE_TAG, "openai", usage.input, usage.cached, usage.output,
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
    image = comment.get("post_image") or None
    first = await _ask_openai(key, model, instructions, user, effort="low", image=image)
    if first is None:
        return None
    better = None
    if first["category"] in COMPLEX:
        try:
            better = await _ask_openai(key, model, instructions, user, effort="medium", image=image)
        except Exception:
            logger.exception("comment AI: complex redraft failed — keeping the first draft")
    return _build(first, better, model, model)


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
    image = comment.get("post_image") or None
    first = await _ask(SIMPLE_MODEL, system, user, effort="low", fallback=False, image=image)
    if first is None:
        return None
    better = None
    if first["category"] in COMPLEX:
        try:
            better = await _ask(COMPLEX_MODEL, system, user, effort="medium", fallback=True, image=image)
        except Exception:
            logger.exception("comment AI: complex redraft failed — keeping the first draft")
    return _build(first, better, SIMPLE_MODEL, COMPLEX_MODEL)


# ─────────────────────────────── helpers ────────────────────────────────────

_CYR = re.compile(r"[а-яёўқғҳ]", re.IGNORECASE)


def is_cyrillic(text: str | None) -> bool:
    letters = re.findall(r"[^\W\d_]", text or "")
    return bool(letters) and sum(1 for ch in letters if _CYR.match(ch)) * 2 > len(letters)


_APOS = str.maketrans({"‘": "'", "’": "'", "`": "'", "´": "'", "ʼ": "'"})
_CYR_APOS = {"о'": "ў", "О'": "Ў", "г'": "ғ", "Г'": "Ғ"}


def _fix_cyr_apos(text: str) -> str:
    """Kirill matndagi «со‘м», «бо‘лса» → «сўм», «бўлса» (translit ‘ ’ ni
    apostrof deb tanimaydi, model ham ba'zan shunday yozadi)."""
    return re.sub(r"[оОгГ]'", lambda m: _CYR_APOS[m.group(0)], text)


def in_script_of(comment_text: str | None, reply: str) -> str:
    """Izoh kirillda bo'lsa — javob ham butunlay kirillda: lotincha qolgan
    so'zlar (mahsulot nomlari: «Stevia 200гр») ham o'giriladi; @handle va
    havolalarga translit tegmaydi."""
    if is_cyrillic(comment_text):
        from translit import lat_to_cyr
        # Avval kirilldagi «о'» → «ў» (aks holda translit «'» ni «ъ» qiladi).
        return _fix_cyr_apos(lat_to_cyr(_fix_cyr_apos(reply.translate(_APOS))))
    return reply


# 1-shaxs birlik → "biz" (egasi, 2026-11-11: "aytaman demasin aytamiz desin").
_SINGULAR_WORDS = {"xursandman": "xursandmiz", "minnatdorman": "minnatdormiz", "tayyorman": "tayyormiz",
                   "хурсандман": "хурсандмиз", "миннатдорман": "миннатдормиз", "тайёрман": "тайёрмиз"}
_SINGULAR_VERB = re.compile(r"\b(\w{3,}?)(a|а|ya|я)(y|й)?(man|ман)\b", re.IGNORECASE)
# "Qaysi … kerakligini yozing", "номини ёзинг" — o'z postimizdagi mahsulotni qayta so'rash.
_ASK = re.compile(r"(nomini|номини|qaysi|қайси|kerakligini|кераклигини).{0,80}"
                  r"(yozing|ёзинг|ayting|айтинг|yuboring|юборинг|yozsangiz|ёзсангиз|aytsangiz|айтсангиз)",
                  re.IGNORECASE)
_ASK_FALLBACK = "Barcha narxlar va mahsulotlarimiz @ketoshopbot da 🌿"


def _plural(text: str) -> str:
    for one, many in _SINGULAR_WORDS.items():
        text = re.sub(rf"\b{one}\b", many, text, flags=re.IGNORECASE)

    def verb(m):
        stem, vowel, y, man = m.groups()
        if len(stem) + len(vowel) < 4:          # «yaman», «осман» — fe'l emas
            return m.group(0)
        mi = "miz" if man.lower() == "man" else "миз"
        return f"{stem}{vowel}{y or ''}{mi}"
    return _SINGULAR_VERB.sub(verb, text)


_CLAUSE_START = re.compile(r"\b(agar|агар|xohlasangiz|хоҳласангиз|iltimos|илтимос)\b", re.IGNORECASE)
_BOUNDARY = re.compile("[.!?…]|[\U0001F300-\U0001FAFF☀-➿]")


def _drop_asks(text: str) -> str:
    """Faqat so'rash bo'lagini kesadi: «Кепак — 10 000 сўм 😊 Агар … номини
    ёзинг — айтаман.» → «Кепак — 10 000 сўм 😊» + narxlar botda."""
    m = _ASK.search(text)
    if not m:
        return text
    head = text[:m.start()]
    cut = 0
    for b in _BOUNDARY.finditer(head):
        cut = b.end()
    starts = [s.start() for s in _CLAUSE_START.finditer(head) if s.start() >= cut]
    if starts:
        cut = starts[0]
    kept = head[:cut].rstrip(" ,—-") if cut else ""
    end = _BOUNDARY.search(text, m.end())
    tail = text[end.end():].strip() if end else ""
    return " ".join(p for p in (kept, tail, _ASK_FALLBACK) if p).strip()


def finalize(comment_text: str | None, reply: str | None) -> str:
    """Izohga ketishdan oldin har javob: markdown yo'q (Instagram ko'rsatmaydi),
    "biz" nomidan, o'z postimizdagi mahsulotni qayta so'ramaydi, izoh
    yozuvida (kirillda — to'liq kirill, «сўм» to'g'ri)."""
    text = (reply or "").replace("**", "").replace("__", "")
    text = text.translate(_APOS)
    text = _drop_asks(text)
    text = _plural(text)
    return in_script_of(comment_text, text).strip()
