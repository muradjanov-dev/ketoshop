"""
⚖️ Yurist-agent — the shop's legal and tax assistant, living in one topic of
the «Ijodkorlar» group (owner, 2026-10-28: "bizga yurist agent kerak barcha
kp va hujjatlarni, franshiza, loyihani rasmiylashtirish va hokazo barcha
soliq dagi va boshqa bilimlarga ega agent bo'lsin uni ijodkorlar guruhidagi
alohida folderga integratsiya qilamiz, hozirgi gpt modeldan foydalanamiz").

The owner's choices (28.10): everyone writing in the topic gets an answer;
it checks the current rule on the internet (lex.uz, soliq.uz, gov.uz) before
it states a rate or an article; documents (tijorat taklifi, shartnoma,
franshiza, ariza …) also come as a Word file.

How it works
  * /yurist_mavzu — an admin types it INSIDE the topic; the group and topic
    ids are saved in ai_settings (the AI seller's settings table). Every
    other message there is a question for the agent.
  * The model is the AI seller's current OpenAI model and key (/ai_holat,
    /ai_kalit) — "hozirgi gpt model" — with YURIST_MODEL to override it.
    OpenAI Responses API with the built-in web_search tool and one function,
    make_document, which this module turns into a .docx (docx_writer.py)
    and posts to the topic.
  * One conversation per topic (previous_response_id), so a follow-up like
    "endi buni ruschaga o'gir" knows what "buni" is. /yurist_yangi starts
    over; it also restarts by itself after CHAIN_LIMIT turns.
  * A .docx / .txt / .pdf sent to the topic is read with its caption — "shu
    shartnomani tekshir".
  * YURIST_DAILY_USD (default 5) caps a day's model spend; /yurist_holat
    shows where it is bound, the model and today's spend.

It is an assistant, not a licensed lawyer, and says so where it matters:
registering a company, a court case, a large contract — it recommends a
lawyer or notary to confirm.
"""
import asyncio
import base64
import html
import json
import logging
import os
import re
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, Message

import ai_provider
import docx_writer
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router(name="yurist")

CHAT_SETTING = "yurist_chat"
THREAD_SETTING = "yurist_thread"
EFFORT = os.getenv("YURIST_EFFORT", "medium").strip() or "medium"
DAILY_USD = float(os.getenv("YURIST_DAILY_USD", "5") or 5)
CHAIN_LIMIT = 40
MAX_ROUNDS = 4                 # model ↔ make_document rounds per question
MAX_OUTPUT_TOKENS = 6000
TEXT_LIMIT = 3900              # Telegram's 4096, with room to spare
FILE_LIMIT = 15 * 1024 * 1024
TZ_OFFSET = timedelta(hours=5)

_chains: dict[tuple[int, int], dict] = {}
_locks: dict[tuple[int, int], asyncio.Lock] = {}
_spend = {"day": "", "usd": 0.0}

SYSTEM = """Sen — Ketoshop jamoasining yurist va soliq maslahatchisisan («Yurist Agent»). \
Jamoa Telegram guruhining alohida mavzusida ishlaysan: savolni do'kon egasi, adminlar va \
hamkorlar beradi.

KETOSHOP HAQIDA (javoblarda shu kontekstdan foydalan)
- Toshkentdagi onlayn do'kon: keto va sog'lom ovqatlanish mahsulotlari (bodom uni, \
eritritol, steviya, kokos mahsulotlari, yog'lar, urug'lar va h.k.).
- Savdo Telegram bot va Mini App (sayt) orqali; Toshkent bo'ylab o'z kuryeri, viloyatlarga \
UzPost/BTS/EMU orqali yetkazadi; naqd va karta orqali to'lov qabul qiladi.
- Ulgurji (B2B) savdo ham bor; blogerlar bilan hamkorlik dasturi (foydadan ulush) ishlaydi.
- Franshiza rejasi: «Ketoshop hamkori» — viloyatlardagi hamkorlar (dilerlar) mahsulotni \
chakana narxdan −35% arzonga olib, bir xil narxda onlayn sotadi; bot bitta, hudud buyurtmasi \
hamkorga tushadi. Savdo belgisi hali ro'yxatdan o'tkazilmagan bo'lishi mumkin — bu haqda \
so'ra va maslahat ber.
- Yuridik shaxs nomi, STIR, bank rekvizitlari, rahbar F.I.Sh. senga ma'lum emas — hujjatda \
[STIR], [Bank rekvizitlari], [Rahbar F.I.Sh.] kabi to'ldiriladigan joy qoldir va kerak bo'lsa so'ra.

BILIM SOHASI — O'zbekiston Respublikasi qonunchiligi
- Soliq kodeksi (aylanmadan olinadigan soliq, QQS, foyda solig'i, JShDS, ijtimoiy soliq, \
mol-mulk solig'i, soliq hisoboti va muddatlari, e-faktura, onlayn NKM/virtual kassa).
- Fuqarolik kodeksi (shartnomalar, oldi-sotdi, yetkazib berish, xizmat ko'rsatish, \
kompleks tadbirkorlik litsenziyasi — franshiza, 50-bob), Mehnat kodeksi, \
«Iste'molchilarning huquqlarini himoya qilish to'g'risida»gi qonun, elektron tijorat, \
reklama, shaxsga doir ma'lumotlar, savdo belgilari (Intellektual mulk agentligi), \
oziq-ovqat xavfsizligi, sertifikatlash va sanitariya talablari, bojxona (import), \
tadbirkorlik subyektlarini ro'yxatdan o'tkazish (MChJ, YaTT, my.gov.uz, «yagona darcha»), \
litsenziya va ruxsatnomalar, bank va valyuta qoidalari.
- Hujjatlar: tijorat taklifi (KP), shartnomalar (oldi-sotdi, yetkazib berish, diler, \
franshiza, ijara, xizmat, NDA, mehnat), ishonchnoma, ariza, buyruq, dalolatnoma, \
pretenziya, hisob-faktura talablari.

QAT'IY QOIDALAR
1. Soliq stavkasi, jarima miqdori, muddat, modda raqami, BHM qiymati kabi o'zgaruvchan \
raqamni aytishdan OLDIN web_search bilan hozirgi qoidani tekshir — avvalo lex.uz, \
soliq.uz, gov.uz, my.gov.uz, cbu.uz, norma.uz. Topgan manbangni javob oxirida havola \
bilan yoz. Tekshirib bo'lmasa — buni ochiq ayt va «lex.uz da tekshiring» de.
2. Modda raqami yoki qonun nomini to'qib chiqarma. Ishonching komil bo'lmasa — shunday de.
3. Javobni amaliy qil: nima qilish kerak, qayerga murojaat, qaysi hujjat, qancha vaqt, \
qancha xarajat, qanday xatar.
4. Kompaniya ro'yxatdan o'tkazish, sud, katta summali shartnoma, soliq tekshiruvi kabi \
masalalarda oxirida bir qator bilan litsenziyali yurist, notarius yoki soliq maslahatchisi \
bilan tasdiqlashni tavsiya qil. Har javobga uzun ogohlantirish yozma.
5. Til: savol qaysi tilda bo'lsa, o'sha tilda javob ber (odatda o'zbek lotin; ruscha \
savolga ruscha). Hujjat — so'ralgan tilda, aytilmagan bo'lsa o'zbek lotin.
6. Format Telegram uchun: oddiy matn, qisqa xatboshilar, raqamlangan ro'yxatlar. Markdown \
(**, ##, jadval) ishlatma. Odatda 3000 belgidan oshirma; batafsil so'ralsa — ko'proq.
7. Hujjat (KP, shartnoma, ariza, nizom, buyruq va h.k.) so'ralsa yoki foydali bo'lsa — \
make_document vositasini chaqir: to'liq, rasmiy, O'zbekiston amaliyotiga mos tuzilma \
(raqam va sana, tuzilgan joy, tomonlar, predmet, narx va to'lov tartibi, tomonlarning \
huquq va majburiyatlari, javobgarlik, fors-major, nizolarni hal qilish, amal qilish \
muddati, rekvizitlar va imzolar). Chatda esa hujjat haqida 2–4 qatorlik izoh yoz, \
butun matnni takrorlama.
8. Guruhdagi suhbat ichki — maxfiy ma'lumotni (parol, kalit) hech qachon so'rama va yozma.
"""

DOCUMENT_TOOL = {
    "type": "function",
    "name": "make_document",
    "description": ("Rasmiy hujjatni Word (.docx) fayl qilib guruhga yuboradi: tijorat taklifi, "
                    "shartnoma, franshiza/diler shartnomasi, ariza, buyruq, dalolatnoma va h.k."),
    "strict": True,
    "parameters": {
        "type": "object",
        "additionalProperties": False,
        "required": ["title", "filename", "blocks"],
        "properties": {
            "title": {"type": "string", "description": "Hujjat sarlavhasi (bosh harflar bilan)."},
            "filename": {"type": "string",
                         "description": "Fayl nomi lotin harflarida, kengaytmasiz, masalan diler_shartnomasi"},
            "blocks": {
                "type": "array",
                "description": "Hujjat bo'laklari tartib bilan.",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["kind", "text", "items", "rows"],
                    "properties": {
                        "kind": {"type": "string",
                                 "enum": ["heading", "paragraph", "bullets", "table", "signature"]},
                        "text": {"type": "string", "description": "heading/paragraph matni, boshqasida bo'sh"},
                        "items": {"type": "array", "items": {"type": "string"},
                                  "description": "bullets bandlari yoki signature qatorlari, boshqasida []"},
                        "rows": {"type": "array", "items": {"type": "array", "items": {"type": "string"}},
                                 "description": "table qatorlari, birinchisi sarlavha; boshqasida []"},
                    },
                },
            },
        },
    },
}


# ─────────────────────────────── settings ───────────────────────────────────

async def _settings() -> dict:
    import ai_sales
    return await ai_sales._load_settings()


async def bound_place() -> tuple[int, int] | None:
    values = await _settings()
    try:
        return int(values[CHAT_SETTING]), int(values.get(THREAD_SETTING) or 0)
    except (KeyError, TypeError, ValueError):
        return None


def _place_of(message: Message) -> tuple[int, int]:
    thread = message.message_thread_id if getattr(message, "is_topic_message", False) else None
    return message.chat.id, int(thread or 0)


async def in_topic(message: Message) -> bool:
    """aiogram filter: a member's message in the bound topic (not a command,
    not a bot, not a service message)."""
    if message.chat.type not in ("group", "supergroup"):
        return False
    if message.from_user is None or message.from_user.is_bot:
        return False
    text = message.text or message.caption or ""
    if text.startswith("/"):
        return False
    if not (text or message.document):
        return False
    place = await bound_place()
    return place is not None and place == _place_of(message)


def _client_and_model():
    """The AI seller's OpenAI key and current model (/ai_kalit, /ai_holat),
    or the server's — "hozirgi gpt modeldan foydalanamiz"."""
    import ai_sales
    provider = ai_sales.PROVIDER
    key, model = "", ""
    if provider is not None and getattr(provider, "name", "") == "openai":
        key, model = provider.api_key, provider.model
    key = key or ai_provider.OPENAI_KEY
    model = os.getenv("YURIST_MODEL", "").strip() or model or ai_provider.DEFAULT_MODELS["openai"]
    if not key:
        return None, model
    from openai import AsyncOpenAI
    return AsyncOpenAI(api_key=key), model


# ─────────────────────────────── spend ──────────────────────────────────────

def _today() -> str:
    return (datetime.utcnow() + TZ_OFFSET).date().isoformat()


def _spent() -> float:
    if _spend["day"] != _today():
        _spend.update(day=_today(), usd=0.0)
    return _spend["usd"]


def _add_spend(model: str, usage) -> None:
    if usage is None:
        return
    details = getattr(usage, "input_tokens_details", None)
    cost = ai_provider.estimate_cost(
        model, int(getattr(usage, "input_tokens", 0) or 0),
        int(getattr(details, "cached_tokens", 0) or 0), int(getattr(usage, "output_tokens", 0) or 0))
    _spent()
    _spend["usd"] += cost


# ─────────────────────────────── the model ──────────────────────────────────

_WEB_TOOLS = ({"type": "web_search"}, {"type": "web_search_preview"})


async def _create(client, kwargs: dict):
    """responses.create with web search — the GA tool name first, the
    preview name if this account/SDK only knows that one."""
    last = None
    for web in _WEB_TOOLS:
        try:
            return await client.responses.create(**dict(kwargs, tools=[web, DOCUMENT_TOOL]))
        except Exception as exc:          # the model/tool combination was refused
            last = exc
            if "web_search" not in str(exc):
                raise
            logger.warning("Yurist: %s refused (%s) — trying the next name", web["type"], exc)
    raise last


def _safe_filename(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", (name or "").strip())[:60].strip("_")
    return (name or "hujjat") + ".docx"


async def _send_document(bot: Bot, place: tuple[int, int], args: dict) -> str:
    data = docx_writer.build(args.get("title") or "Hujjat", args.get("blocks") or [])
    await bot.send_document(
        place[0], BufferedInputFile(data, filename=_safe_filename(args.get("filename"))),
        caption=f"📄 {html.escape(args.get('title') or 'Hujjat', quote=False)}",
        message_thread_id=place[1] or None, parse_mode="HTML")
    return "Hujjat guruhga Word fayl bo'lib yuborildi."


async def ask(bot: Bot, place: tuple[int, int], content: list[dict]) -> str:
    """One question → the agent's final text; documents are posted on the way."""
    client, model = _client_and_model()
    if client is None:
        return "⚠️ OpenAI kaliti yo'q — /ai_kalit bilan bering, keyin qayta yozing."
    chain = _chains.setdefault(place, {})
    if chain.get("turns", 0) >= CHAIN_LIMIT:
        chain.clear()
    items: list = [{"role": "user", "content": content}]
    for _ in range(MAX_ROUNDS):
        kwargs = {"model": model, "instructions": SYSTEM + f"\nBugungi sana: {_today()}.",
                  "input": items, "reasoning": {"effort": EFFORT},
                  "max_output_tokens": MAX_OUTPUT_TOKENS}
        if chain.get("prev_id"):
            kwargs["previous_response_id"] = chain["prev_id"]
        try:
            response = await _create(client, kwargs)
        except Exception:
            chain.clear()                 # a broken chain would fail every next question
            raise
        chain["prev_id"] = response.id
        chain["turns"] = chain.get("turns", 0) + 1
        _add_spend(model, getattr(response, "usage", None))
        calls = [o for o in (response.output or []) if getattr(o, "type", "") == "function_call"]
        if not calls:
            return (response.output_text or "").strip()
        items = []
        for call in calls:
            try:
                args = json.loads(call.arguments or "{}")
                output = (await _send_document(bot, place, args) if call.name == "make_document"
                          else f"Noma'lum vosita: {call.name}")
            except Exception as exc:
                logger.exception("Yurist: tool %s failed", call.name)
                output = f"Xato: {exc}"
            items.append({"type": "function_call_output", "call_id": call.call_id, "output": output})
    return "Hujjat tayyorlandi." if items else ""


# ─────────────────────────────── Telegram ───────────────────────────────────

def split_text(text: str, limit: int = TEXT_LIMIT) -> list[str]:
    """Long answers in pieces, cut at a paragraph or line where possible."""
    text = (text or "").strip()
    out = []
    while len(text) > limit:
        cut = text.rfind("\n\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        out.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        out.append(text)
    return out


async def _typing(bot: Bot, place: tuple[int, int], stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await bot.send_chat_action(place[0], "typing", message_thread_id=place[1] or None)
        except Exception:
            pass
        try:
            await asyncio.wait_for(stop.wait(), timeout=4.5)
        except asyncio.TimeoutError:
            pass


async def _attachment(bot: Bot, message: Message) -> list[dict]:
    """A document someone sent, as model input: .docx/.txt as text, .pdf as a file."""
    doc = message.document
    if doc is None:
        return []
    name = doc.file_name or "fayl"
    if (doc.file_size or 0) > FILE_LIMIT:
        return [{"type": "input_text", "text": f"[{name} juda katta — o'qilmadi]"}]
    buf = await bot.download(doc)
    data = buf.read() if buf else b""
    low = name.lower()
    if low.endswith(".docx"):
        return [{"type": "input_text", "text": f"[Ilova: {name}]\n{docx_writer.extract_text(data)}"}]
    if low.endswith(".txt"):
        return [{"type": "input_text", "text": f"[Ilova: {name}]\n{data.decode('utf-8', 'replace')[:40000]}"}]
    if low.endswith(".pdf"):
        b64 = base64.b64encode(data).decode()
        return [{"type": "input_file", "filename": name, "file_data": f"data:application/pdf;base64,{b64}"}]
    return [{"type": "input_text", "text": f"[{name} — bu turdagi faylni o'qiy olmayman: .docx, .pdf yoki .txt yuboring]"}]


@router.message(in_topic)
async def on_question(message: Message, bot: Bot):
    place = _place_of(message)
    if _spent() >= DAILY_USD:
        await message.reply("⏸ Bugungi limit tugadi (YURIST_DAILY_USD). Ertaga davom etamiz yoki "
                            "admin /yurist_holat orqali tekshirsin.", parse_mode=None)
        return
    lock = _locks.setdefault(place, asyncio.Lock())
    async with lock:
        stop = asyncio.Event()
        typing = asyncio.create_task(_typing(bot, place, stop))
        try:
            who = message.from_user.full_name or "Foydalanuvchi"
            text = message.text or message.caption or ""
            content = [{"type": "input_text", "text": f"{who}: {text}".strip()}]
            content += await _attachment(bot, message)
            answer = await ask(bot, place, content)
        except Exception:
            logger.exception("Yurist agent failed")
            answer = "⚠️ Hozir javob bera olmadim (AI xizmatida xato). Birozdan keyin qayta yozing."
        finally:
            stop.set()
            await typing
        for i, part in enumerate(split_text(answer or "…")):
            for _ in range(2):
                try:
                    await bot.send_message(place[0], part, message_thread_id=place[1] or None,
                                           reply_to_message_id=message.message_id if i == 0 else None,
                                           parse_mode=None, disable_web_page_preview=True)
                    break
                except TelegramRetryAfter as exc:
                    await asyncio.sleep(exc.retry_after)


@router.message(Command("yurist_mavzu"))
async def cmd_bind(message: Message, bot: Bot):
    """Typed by an admin INSIDE the group topic the agent should live in."""
    user = message.from_user
    if user is None or user.id not in ADMIN_IDS or message.sender_chat is not None:
        return
    if message.chat.type not in ("group", "supergroup"):
        await message.answer("Bu buyruqni yurist ishlashi kerak bo'lgan guruh mavzusining "
                             "(topic) ichida yozing.")
        return
    import ai_sales
    chat_id, thread = _place_of(message)
    await ai_sales.set_setting(CHAT_SETTING, str(chat_id), user.id)
    await ai_sales.set_setting(THREAD_SETTING, str(thread), user.id)
    _chains.pop((chat_id, thread), None)
    try:
        await message.delete()
    except Exception:
        pass
    await bot.send_message(
        chat_id,
        "⚖️ Yurist-agent shu mavzuga ulandi.\n\n"
        "Savolingizni oddiy yozing: soliq, shartnoma, franshiza, kompaniya ochish, litsenziya, "
        "mehnat masalalari… Hujjat kerak bo'lsa — «KP tayyorla», «diler shartnomasi yoz» deng, "
        "Word fayl bo'lib keladi. Shartnomani tekshirish uchun .docx yoki .pdf ni shu yerga "
        "tashlang.\n\n"
        "Stavka va moddalarni lex.uz, soliq.uz dan tekshirib, manbasini yozadi. Muhim "
        "qarorlarni baribir yurist yoki notarius bilan tasdiqlang.",
        message_thread_id=thread or None, parse_mode=None)


@router.message(Command("yurist_yangi"))
async def cmd_reset(message: Message):
    if message.from_user is None or message.from_user.id not in ADMIN_IDS:
        return
    _chains.pop(_place_of(message), None)
    await message.answer("🆕 Yurist bilan yangi suhbat — oldingi kontekst unutildi.", parse_mode=None)


@router.message(Command("yurist_holat"))
async def cmd_status(message: Message):
    if message.from_user is None or message.from_user.id not in ADMIN_IDS:
        return
    place = await bound_place()
    _, model = _client_and_model()
    where = (f"guruh {place[0]}, mavzu {place[1] or '— (umumiy chat)'}" if place
             else "ulanmagan — mavzu ichida /yurist_mavzu yozing")
    await message.answer(
        "⚖️ Yurist-agent\n"
        f"• Joyi: {where}\n"
        f"• Model: {model} (fikrlash: {EFFORT}), internet qidiruv bilan\n"
        f"• Bugun sarflandi: ${_spent():.2f} / ${DAILY_USD:.2f}\n"
        f"• Faol suhbatlar: {len(_chains)}",
        parse_mode=None)
