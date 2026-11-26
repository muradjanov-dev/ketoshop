"""Fikr so'rash — 2 kunda bir AI xaridorlardan oldingi buyurtmasi haqida qisqa
so'raydi (egasi, 2026-11-16: "kunlik bot orqali eslatmalarda ham eski olgan
buyurtma va mahsulotlari haqida ham 2 kunda bir ai hamma mijozlardan fikr
so'rasin va tavsiyalar so'rasin, qisqa xabarda").

* Kimga: haqiqiy buyurtmasi bor xaridorlar (qo'lda kiritilgan emas), ichki
  akkauntlar va adminlarsiz.
* Nima haqida: yetkazilganiga 2–60 kun bo'lgan, fikri hali so'ralmagan va
  baholanmagan mahsulot (ai_memory.feedback_candidate — botdagi AI suhbat
  bilan bir xil qoida, bir mahsulot haqida bir marta). Bunday mahsulot
  bo'lmasa — oyiga ko'pi bilan bir marta umumiy taklif («do'konimizga nima
  qo'shaylik?»). Ikkalasi ham yo'q — xabar yo'q.
* Qanday: AI 1–2 gaplik iliq xabar yozadi, user tilida; havola, narx va
  shoshiltirish yo'q. AI javob bermasa yoki xabar shartga to'g'ri kelmasa —
  tayyor qisqa matn.
* Qachon: juft-toq kunlar bo'yicha 2 kunda bir, SEND_AT Toshkent vaqtida.
  Kuniga xabar chegarasidan o'tadi (push_cap, tur "fikr"); shu kuni userga
  umumiy maslahat (broadcast.py) ketmaydi — ikki xabar ketma-ket emas.
* Javob: user botga yozadi va AI sotuvchiga tushadi; mahsulot 'asked' deb
  belgilanadi va profilga «biz … haqida fikr so'radik» eslatmasi yoziladi —
  AI nima so'raganimizni biladi.

Boshqaruv: /fikr_sorash (holat) · /fikr_sorash on|off · /fikr_sorash test
(o'zingizga namuna — boshqalarga yuborilmaydi).
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import re
from datetime import datetime, timedelta

from aiogram import Bot, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.types import Message

import ai_memory
import database
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router(name="feedback_ask")

TZ = timedelta(hours=5)
SEND_AT = (7, 45)              # Toshkent: 08:00 dagi maslahatdan oldin
LAST_HOUR = 11                 # undan keyin boshlanmaydi (kechikkan deploy)
PARITY = 0                     # date.toordinal() % 2 == PARITY kunlari
SEND_DELAY = 0.06
SETTING = "feedback_ask"
TEXT_MAX = 170
GENERAL_NOTE = "Taklif so'raldi"   # ai_memory dedup — oyiga bir marta
USAGE_TAG = " · fikr so'rash"

# Egasi, 2026-11-26: "avval bizdan faloncha mahsulot olgan ekansiz, sifati Sizga ma'qul keldimi? ulardan
# qanday mahsulotlar tayyorladingiz, biz bilan ham bo'lisha olasizmi?" — "qisqaroq xabar bo'lishi kerak".
RULES = """Sen Keto shop jamoasi nomidan (keto, PP va glyutensiz mahsulotlar do'koni) mijozga Telegram botda
juda qisqa xabar yozasan: u bizdan olgan mahsulot ma'qul keldimi va undan nima tayyorlaganini so'raysan.

- BITTA yoki ikkita juda qisqa gap, jami 150 belgigacha. Iliq, oddiy, odamdek; «biz» nomidan. 1 ta emoji.
- MAHSULOT berilgan bo'lsa — mazmuni shu: "Avval bizdan {mahsulot} olgandingiz — ma'qul keldimi? Nima
  tayyorladingiz, bo'lishasizmi? 😊". O'z so'zing bilan, har safar biroz boshqacha.
- MAHSULOT yo'q bo'lsa — do'konimizga qanday mahsulot qo'shishimizni qisqa so'ra.
- Havola, narx, chegirma, sotuv taklifi yo'q (bu faqat savol). «Hurmatli mijoz», «iltimos» bilan boshlama.
- Til: TIL berilgan. uz — o'zbek lotin; ru — rus. Ismini bilmaymiz — ism yozma."""
SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}},
          "required": ["text"], "additionalProperties": False}

TEMPLATE = {
    "product": ("Avval bizdan {name} olgandingiz — ma'qul keldimi? Nima tayyorladingiz, bo'lishasizmi? 😊",
                "Вы брали у нас {name} — понравилось? Что приготовили, поделитесь? 😊"),
    "general": ("Do'konimizga yana qanday mahsulot qo'shsak, xursand bo'lardingiz? 😊 Taklifingizni shu yerga yozing.",
                "Какие товары нам стоит добавить в магазин? 😊 Напишите сюда — нам важно ваше мнение."),
}
_URL = re.compile(r"https?://|t\.me/|www\.", re.IGNORECASE)


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ


def is_ask_day(day) -> bool:
    return day.toordinal() % 2 == PARITY


async def enabled() -> bool:
    try:
        import ai_sales
        values = await ai_sales._load_settings()
        return str(values.get(SETTING, "1")) != "0"
    except Exception:
        return True


def _localize(text: str, lang: str) -> str:
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        return lat_to_cyr(text)
    return text


def template(topic: dict | None, lang: str) -> str:
    kind = "product" if topic else "general"
    uz, ru = TEMPLATE[kind]
    text = (ru if lang == "ru" else uz).format(name=(topic or {}).get("name") or "")
    return _localize(text, lang)


def acceptable(text: str | None, topic: dict | None, lang: str) -> bool:
    """AI matni yaraydimi: qisqa, havolasiz, mahsulot nomi bor, to'g'ri yozuvda."""
    if not text or len(text) > TEXT_MAX or _URL.search(text) or "<" in text:
        return False
    if topic:
        first = (topic.get("name") or "").split()[0].lower() if topic.get("name") else ""
        if first and first[:4] not in text.lower():
            return False
    from comment_ai import is_cyrillic
    return is_cyrillic(text) == (lang == "ru")


async def compose(topic: dict | None, lang: str) -> str:
    """Bitta userga xabar — AI yozgani yoki tayyor matn."""
    ai_lang = "ru" if lang == "ru" else "uz"
    try:
        import comment_ai
        key = await comment_ai._openai_key()
        if key:
            import ai_provider
            import openai
            model = comment_ai.openai_model()
            client = openai.AsyncOpenAI(api_key=key, timeout=40.0, max_retries=1)
            user = f"TIL: {ai_lang}\nMAHSULOT: {(topic or {}).get('name') or '—'}"
            resp = await client.responses.create(
                model=model, instructions=RULES,
                input=[{"role": "user", "content": [{"type": "input_text", "text": user}]}],
                reasoning={"effort": "low"}, max_output_tokens=400,
                text={"format": {"type": "json_schema", "name": "fikr", "schema": SCHEMA, "strict": True}})
            try:
                usage = ai_provider._openai_usage(getattr(resp, "usage", None))
                await database.record_ai_usage(model + USAGE_TAG, "openai", usage.input, usage.cached, usage.output,
                                               ai_provider.estimate_cost(model, usage.input, usage.cached,
                                                                         usage.output))
            except Exception:
                pass
            text = (json.loads(getattr(resp, "output_text", "") or "{}").get("text") or "").strip()
            if acceptable(text, topic, ai_lang):
                return _localize(text, lang)
    except Exception:
        logger.info("feedback ask: AI unavailable — template used", exc_info=True)
    return template(topic, lang)


async def topic_for(user_id: int) -> dict | None | bool:
    """Mahsulot (dict), umumiy taklif (None) yoki hech narsa (False)."""
    orders = await database.get_user_orders(user_id)
    notes = await ai_memory.notes(user_id)
    try:
        reviewed = {r["product_id"] for r in await ai_memory._reviews(user_id)}
    except Exception:
        reviewed = set()
    product = ai_memory.feedback_candidate(orders, notes, reviewed=reviewed)
    if product:
        return product
    recent = datetime.utcnow() - timedelta(days=ai_memory.DEDUP_DAYS)
    for n in notes:
        if n.get("kind") == "asked" and n.get("text") == GENERAL_NOTE and (n.get("created_at") or recent) > recent:
            return False
    return None if any(o.get("status") == "delivered" for o in orders) else False


async def _send(bot: Bot, uid: int, text: str) -> bool:
    for attempt in range(2):
        try:
            await bot.send_message(uid, html.escape(text, quote=False), parse_mode=ParseMode.HTML)
            return True
        except TelegramRetryAfter as exc:
            if attempt:
                return False
            await asyncio.sleep(exc.retry_after + 1)
        except (TelegramForbiddenError, TelegramBadRequest):
            return False
        except Exception:
            logger.exception("feedback ask to %s failed", uid)
            return False
    return False


async def _mark(uid: int, topic: dict | None) -> None:
    try:
        if topic:
            await ai_memory.remember(uid, "asked", topic["name"] or str(topic["product_id"]),
                                     product_id=topic["product_id"])
            # Egasi, 2026-11-26: javob yozgach — yangi narsa pishirib ko'rishga, foydasini aytib
            # sotuvga; ora-orada chegirmadan foydalanib qolishga.
            await ai_memory.remember(uid, "eslatma", f"Biz botda «{topic['name']}» ma'qul kelganini va nima "
                                                     "tayyorlaganini so'radik. Javob yozsa: samimiy rahmat; "
                                                     "shu mahsulot bilan yangi bir taom g'oyasi va foydasi "
                                                     "(bir gap); mos 1 mahsulotni muloyim taklif qil; "
                                                     "chegirmadagisi mos bo'lsa — eslat; bitta savol bilan "
                                                     "suhbatni davom ettir.")
        else:
            await ai_memory.remember(uid, "asked", GENERAL_NOTE)
            await ai_memory.remember(uid, "eslatma", "Biz botda do'konga qanday mahsulot qo'shishimiz haqida "
                                                     "taklif so'radik — javob yozsa, minnatdorchilik bildir.")
    except Exception:
        logger.warning("feedback ask: memory not updated for %s", uid, exc_info=True)


async def send_round(bot: Bot) -> dict:
    """Bir aylanma: har xaridorga (chegara ruxsat bersa) bitta qisqa savol."""
    import push_cap
    skip = set(ADMIN_IDS) | set(database.LEADERBOARD_EXCLUDED_USER_IDS)
    users = [u for u in await database.get_user_ids_with_orders() if u not in skip]
    langs = await database.get_user_languages(users)
    stats = {"sent": 0, "capped": 0, "nothing": 0, "failed": 0, "ai": 0}
    for uid in users:
        try:
            topic = await topic_for(uid)
        except Exception:
            logger.exception("feedback ask: topic failed for %s", uid)
            continue
        if topic is False:
            stats["nothing"] += 1
            continue
        if not await push_cap.claim(uid, "fikr"):
            stats["capped"] += 1
            continue
        lang = langs.get(uid, "uz")
        text = await compose(topic, lang)
        stats["ai"] += text != template(topic, lang)
        if await _send(bot, uid, text):
            stats["sent"] += 1
            await _mark(uid, topic)
        else:
            stats["failed"] += 1
        await asyncio.sleep(SEND_DELAY)
    return stats


async def _tick(bot: Bot) -> None:
    now = _now_tk()
    if not is_ask_day(now.date()) or (now.hour, now.minute) < SEND_AT or now.hour >= LAST_HOUR:
        return
    import gift_campaign
    if gift_campaign.comeback_day(now.date()):
        return          # the gift's comeback announcement takes this morning's slot
    if not await enabled():
        return
    if not await database.claim_release_notes(f"feedback-ask-{now.date().isoformat()}"):
        return
    stats = await send_round(bot)
    logger.info("feedback ask round: %s", stats)
    text = (f"🗣 <b>Fikr so'rash (AI)</b>: {stats['sent']} ta xaridorga yuborildi"
            f" · AI yozgani {stats['ai']} · chegarada qoldi {stats['capped']}"
            f" · so'raladigan narsa yo'q {stats['nothing']} · yetmadi {stats['failed']}\n"
            "Javoblar botdagi AI suhbatga tushadi. Boshqaruv: /fikr_sorash")
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML, disable_notification=True)
        except Exception:
            pass


async def scheduler_loop(bot: Bot) -> None:
    await asyncio.sleep(90)
    while True:
        try:
            await _tick(bot)
        except Exception:
            logger.exception("feedback ask tick failed")
        await asyncio.sleep(300)


@router.message(Command("fikr_sorash"))
async def cmd_feedback_ask(message: Message):
    import ai_sales
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = (message.text or "").split()
    arg = parts[1].lower() if len(parts) > 1 else ""
    if arg in ("on", "off"):
        await ai_sales.set_setting(SETTING, "1" if arg == "on" else "0", message.from_user.id)
        ai_sales._settings["at"] = float("-inf")
    if arg == "test":
        lang = await database.get_user_language(message.from_user.id) or "uz"
        sample = {"product_id": 0, "name": "Bodom uni 500gr"}
        for topic in (sample, None):
            await message.answer(await compose(topic, lang))
        await message.answer("☝️ Namuna — faqat sizga. Haqiqiy xabar har xaridorning o'z mahsuloti bilan.")
        return
    on = await enabled()
    nxt = _now_tk().date()
    while not is_ask_day(nxt) or (nxt == _now_tk().date() and _now_tk().hour >= LAST_HOUR):
        nxt += timedelta(days=1)
    await message.answer(
        f"🗣 <b>Fikr so'rash (AI)</b>: {'yoqilgan ✅' if on else 'o‘chiq ⏸'}\n\n"
        "2 kunda bir xaridorga oldingi buyurtmasidagi mahsulot qanday chiqqanini va taklifini qisqa so'raydi "
        "(mahsulot bo'lmasa — oyiga bir marta umumiy taklif). Kuniga xabar chegarasiga kiradi.\n"
        f"Keyingisi: {nxt:%d.%m} soat {SEND_AT[0]:02d}:{SEND_AT[1]:02d}\n\n"
        "<code>/fikr_sorash test</code> — namuna · <code>/fikr_sorash off</code> — o'chirish", parse_mode="HTML")
