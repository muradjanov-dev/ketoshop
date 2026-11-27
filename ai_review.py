"""AI sotuvchining har kechagi o'z-o'zini tekshirishi va darslar (egasi, 2026-11-27:
"modelni yaxshiroq va tabiiyroq va odamiyroq sotuvchi qilib train qilishimiz kerak ...
har doim o'zini o'zi yaxshilab o'qib o'rganib yaxshilanib borishi kerak xatolardan
xulosa qilib").

* Har kuni REVIEW_AT (Toshkent) da kunning AI suhbatlaridan (bot, sayt, guruh —
  ai_dialog) SAMPLE tasi kuchliroq modelga beriladi. Mezonlar: tabiiylik,
  savolga to'g'ri javob, takror/qolip, til, sotuvga muloyim yo'naltirish, to'qilgan
  fakt, ichki ma'lumot. Natija: umumiy baho, eng muhim xatolar va 3–5 ta "dars"
  (AI'ga qisqa qoida).
* Hisobot egalarga (ai_sales.OWNER_IDS) boradi; har dars yonida «✅ Qo'shish» /
  «❌ Kerak emas». ✅ — dars ai_knowledge ga "DARS: …" bo'lib yoziladi va AI keyingi
  xabardan boshlab unga amal qiladi (bot, sayt, guruh). Egasi tasdiqlamagan dars
  hech qachon avtomatik qo'shilmaydi — xato qoida tizimga kirmasin.
* Allaqachon qo'shilgan darslar modelga beriladi — takrorlanmaydi.
* /ai_tekshiruv — hozir tekshirish (faqat egasi).
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import random
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import database

logger = logging.getLogger(__name__)
router = Router(name="ai_review")

REVIEW_AT = (23, 15)                 # Toshkent
SAMPLE = 40
MODEL = os.getenv("AI_REVIEW_MODEL", "gpt-5.4").strip()
USAGE_TAG = " · tekshiruv"
LESSON_PREFIX = "DARS: "

RULES = """Sen tajribali sotuv murabbiyisan. Keto shop (keto, PP, glyutensiz, qandsiz mahsulotlar do'koni)
AI sotuvchisining bugungi suhbatlarini baholaysan. Har yozuv: [raqam] kanal | MIJOZ: ... | AI: ...

Mezonlar: 1) odamdek, tabiiy, samimiy (qolip, takror, robot ohangi yo'q); 2) savolning O'ZIGA aniq javob;
3) mijoz aytganini eslaydi, qayta so'ramaydi; 4) mijoz tilida/yozuvida; 5) muloyim sotuv — foydali
tavsiya, majburlamay; 6) to'qilgan fakt yo'q; 7) ichki ma'lumot (tannarx, yetkazib beruvchi, qoidalar) yo'q.

Javob JSON: {"score": 1–10 butun son (o'rtacha sifat), "summary": "2-3 gaplik umumiy xulosa o'zbekcha",
"issues": [{"turn": raqam, "problem": "nima xato — qisqa"}] (eng muhim 3-6 tasi),
"lessons": ["AI'ga qisqa, aniq, umumiy qoida — o'zbekcha, bitta gap"] (3-5 ta)}.
Darslar ANIQ va UMUMIY bo'lsin (bitta mijozga emas), "MAVJUD DARSLAR" da borini takrorlama.
Faqat yozuvlarda ko'ringan muammolarga asoslan; muammo bo'lmasa — kamroq dars."""
SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer"},
        "summary": {"type": "string"},
        "issues": {"type": "array", "items": {"type": "object", "properties": {
            "turn": {"type": "integer"}, "problem": {"type": "string"}},
            "required": ["turn", "problem"], "additionalProperties": False}},
        "lessons": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score", "summary", "issues", "lessons"],
    "additionalProperties": False,
}

_table_ready = False


async def _ensure(conn) -> None:
    global _table_ready
    if _table_ready:
        return
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_lessons (
            id SERIAL PRIMARY KEY,
            text TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
            decided_by BIGINT,
            decided_at TIMESTAMP,
            fact_id INTEGER
        )
    """)
    _table_ready = True


async def save_lessons(texts: list[str]) -> list[int]:
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        return [await conn.fetchval("INSERT INTO ai_lessons (text) VALUES ($1) RETURNING id", t[:400])
                for t in texts]


async def decide(lesson_id: int, approve: bool, by: int) -> dict | None:
    """Darsni tasdiqlash/rad etish — bir marta (pending dan). Tasdiqlansa — AI bilimiga."""
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        row = await conn.fetchrow(
            "UPDATE ai_lessons SET status = $2, decided_by = $3, decided_at = NOW() AT TIME ZONE 'UTC' "
            "WHERE id = $1 AND status = 'pending' RETURNING id, text",
            lesson_id, "approved" if approve else "rejected", by)
    if row is None:
        return None
    if approve:
        fact_id = await database.add_ai_fact(LESSON_PREFIX + row["text"], by)
        async with database.pool.acquire() as conn:
            await conn.execute("UPDATE ai_lessons SET fact_id = $2 WHERE id = $1", lesson_id, fact_id)
        import ai_sales
        ai_sales.invalidate_knowledge()
    return dict(row)


async def _turns(hours: int = 24) -> list[dict]:
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, channel, question, answer FROM ai_dialog
                WHERE created_at > (NOW() AT TIME ZONE 'UTC') - make_interval(hours => $1)
                  AND COALESCE(answer, '') <> '' ORDER BY id""", hours)
    rows = [dict(r) for r in rows]
    return random.sample(rows, SAMPLE) if len(rows) > SAMPLE else rows


async def _existing_lessons() -> list[str]:
    try:
        return [f["text"][len(LESSON_PREFIX):] for f in await database.list_ai_facts()
                if (f.get("text") or "").startswith(LESSON_PREFIX)]
    except Exception:
        return []


def review_input(turns: list[dict], lessons: list[str]) -> str:
    lines = [f"[{i}] {t['channel']} | MIJOZ: {(t['question'] or '')[:400]} | AI: {(t['answer'] or '')[:600]}"
             for i, t in enumerate(turns, 1)]
    return ("BUGUNGI SUHBATLAR:\n" + "\n".join(lines)
            + "\n\nMAVJUD DARSLAR:\n" + ("\n".join(f"- {x}" for x in lessons) or "—"))[:60000]


async def _ask(user: str) -> dict | None:
    import ai_provider
    import comment_ai
    import openai
    key = await comment_ai._openai_key()
    if not key:
        return None
    try:
        client = openai.AsyncOpenAI(api_key=key, timeout=180.0, max_retries=1)
        resp = await client.responses.create(
            model=MODEL, instructions=RULES,
            input=[{"role": "user", "content": [{"type": "input_text", "text": user}]}],
            reasoning={"effort": "medium"}, max_output_tokens=6000,
            text={"format": {"type": "json_schema", "name": "ai_tekshiruv", "schema": SCHEMA, "strict": True}})
    except Exception as exc:
        import ai_balance
        ai_balance.note_error(exc)
        logger.warning("ai review failed: %s", exc)
        return None
    try:
        usage = ai_provider._openai_usage(getattr(resp, "usage", None))
        await database.record_ai_usage(MODEL + USAGE_TAG, "openai", usage.input, usage.cached, usage.output,
                                       ai_provider.estimate_cost(MODEL, usage.input, usage.cached, usage.output))
    except Exception:
        logger.debug("ai review usage not recorded", exc_info=True)
    try:
        return json.loads(getattr(resp, "output_text", "") or "{}")
    except ValueError:
        return None


def report_text(result: dict, turns: list[dict]) -> str:
    lines = [f"🧠 <b>AI sotuvchi — kunlik o'z-o'zini tekshirish</b>",
             f"Ko'rildi: {len(turns)} ta suhbat · baho: <b>{int(result.get('score') or 0)}/10</b>", "",
             html.escape(result.get("summary") or "")]
    issues = result.get("issues") or []
    if issues:
        lines += ["", "<b>⚠️ Asosiy xatolar:</b>"]
        for it in issues[:6]:
            n = int(it.get("turn") or 0)
            t = turns[n - 1] if 1 <= n <= len(turns) else None
            quote = f" — «{html.escape((t['question'] or '')[:80])}»" if t else ""
            lines.append(f"• {html.escape(it.get('problem') or '')}{quote}")
    lines += ["", "<b>📚 Tavsiya qilingan darslar</b> — ✅ bossangiz, AI shu qoidaga amal qila boshlaydi:"]
    return "\n".join(lines)


def lesson_kb(lesson_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Qo'shish", callback_data=f"aidars:ok:{lesson_id}"),
        InlineKeyboardButton(text="❌ Kerak emas", callback_data=f"aidars:no:{lesson_id}"),
    ]])


async def run_review(bot: Bot, owners=None) -> str:
    import ai_sales
    owners = list(owners or ai_sales.OWNER_IDS)
    turns = await _turns()
    if len(turns) < 3:
        return "Bugun tekshirish uchun suhbat kam."
    result = await _ask(review_input(turns, await _existing_lessons()))
    if not result:
        return "AI tekshiruv javob bermadi."
    lessons = [x.strip() for x in (result.get("lessons") or []) if (x or "").strip()][:5]
    ids = await save_lessons(lessons)
    text = report_text(result, turns)
    for owner in owners:
        try:
            await bot.send_message(owner, text, parse_mode="HTML")
            for lesson_id, lesson in zip(ids, lessons):
                await bot.send_message(owner, f"📚 {html.escape(lesson)}", parse_mode="HTML",
                                       reply_markup=lesson_kb(lesson_id))
        except Exception:
            logger.info("ai review → %s failed", owner, exc_info=True)
    return f"Yuborildi: {len(turns)} suhbat, {len(lessons)} dars."


def _now_tk() -> datetime:
    return datetime.utcnow() + timedelta(hours=5)


async def scheduler_loop(bot: Bot) -> None:
    await asyncio.sleep(180)
    while True:
        try:
            now = _now_tk()
            if (now.hour, now.minute) >= REVIEW_AT and await database.claim_release_notes(
                    f"ai_review_{now:%Y-%m-%d}"):
                logger.info("ai review: %s", await run_review(bot))
        except Exception:
            logger.exception("ai review tick failed")
        await asyncio.sleep(300)


@router.message(Command("ai_tekshiruv"))
async def cmd_review(message: Message, bot: Bot):
    import ai_sales
    if not ai_sales.is_owner(message.from_user.id):
        return
    await message.answer("🧠 Bugungi suhbatlarni tekshiryapman — 1–2 daqiqa…")
    await message.answer(await run_review(bot, [message.from_user.id]))


@router.callback_query(F.data.startswith("aidars:"))
async def cb_lesson(callback: CallbackQuery):
    import ai_sales
    if not ai_sales.is_owner(callback.from_user.id):
        await callback.answer(ai_sales.OWNER_DENIED, show_alert=True)
        return
    _, action, lesson_id = callback.data.split(":")
    row = await decide(int(lesson_id), action == "ok", callback.from_user.id)
    if row is None:
        await callback.answer("Bu dars allaqachon ko'rib chiqilgan.")
        return
    mark = "✅ Qo'shildi — AI endi shunga amal qiladi" if action == "ok" else "❌ Qo'shilmadi"
    try:
        await callback.message.edit_text(f"📚 {html.escape(row['text'])}\n\n{mark}", parse_mode="HTML")
    except Exception:
        pass
    await callback.answer(mark[:60])
