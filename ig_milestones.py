"""Instagram: har 50 ta AI javobida adminlarga hisobot (egasi, 2026-11-28: "har 50 ta izohga javob
berganda instagramda botdan alohida statistikani yubor, va Direct'dan har 50 ta mijoz savoliga javob
berganda ham botdan yubor — kuzatib turishimiz kerak").

Ikki hisoblagich, alohida xabar:
  * izohlar — meta_comments da status='ai_answered' (AI yozgan javoblar);
  * Direct — ig_dm_messages da AI yuborgan javoblar (bitta javob = suhbat + replied_at).
Har STEP ga yetganda (50, 100, 150 ...) bitta hisobot: oxirgi 50 tasi qaysi vaqt oralig'ida,
toifalar yoki niyatlar, bugungi holat, navbat, adminga o'tganlar va bugungi AI sarfi.
Bir bosqich bir marta (release_notes_sent: kalit "ig50:<tur>:<son>"), restart ham takrorlamaydi.
Deploydan keyin faqat joriy bosqich yuboriladi — o'tganlari to'planib kelmaydi.
/ig_hisobot — hozirgi holat (adminlar).
"""
from __future__ import annotations

import asyncio
import html
import logging
from collections import Counter
from datetime import timedelta

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

import database
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router(name="ig_milestones")

STEP = 50
CHECK_EVERY = 300
TZ = timedelta(hours=5)


def _t(dt) -> str:
    return (dt + TZ).strftime("%d.%m %H:%M") if dt else "—"


async def comment_total() -> int:
    async with database.pool.acquire() as conn:
        return int(await conn.fetchval("SELECT COUNT(*) FROM meta_comments WHERE status = 'ai_answered'") or 0)


async def direct_total() -> int:
    try:
        async with database.pool.acquire() as conn:
            return int(await conn.fetchval(
                "SELECT COUNT(DISTINCT (conversation_id, replied_at)) FROM ig_dm_messages "
                "WHERE status = 'replied' AND replied_at IS NOT NULL") or 0)
    except Exception:            # jadval hali yo'q
        return 0


async def _usage_today(tag: str) -> float:
    try:
        rows = await database.get_ai_usage_today()
    except Exception:
        return 0.0
    return round(sum(float(r.get("cost_usd") or 0) for r in rows if tag in (r.get("model") or "")), 3)


async def comment_report(total: int) -> str:
    async with database.pool.acquire() as conn:
        last = await conn.fetch(
            "SELECT category, platform, replied_at FROM meta_comments WHERE status = 'ai_answered' "
            "AND replied_at IS NOT NULL ORDER BY replied_at DESC LIMIT $1", STEP)
        today = await conn.fetchrow(
            """SELECT COUNT(*) FILTER (WHERE status = 'ai_answered') AS ai,
                      COUNT(*) FILTER (WHERE status = 'answered') AS admin
                 FROM meta_comments
                WHERE COALESCE(replied_at, created_at) >= date_trunc('day', NOW() AT TIME ZONE 'Asia/Tashkent')
                                                          - INTERVAL '5 hours'""")
        waiting = await conn.fetchval(
            "SELECT COUNT(*) FROM meta_comments WHERE status IN ('new', 'pending') AND COALESCE(text, '') <> ''")
    cats = Counter((r["category"] or "boshqa") for r in last)
    span = f"{_t(last[-1]['replied_at'])} – {_t(last[0]['replied_at'])}" if last else "—"
    lines = [f"📸 <b>Instagram izohlari — yana {STEP} ta javob</b> (jami AI javoblari: {total})",
             f"🕒 Oxirgi {len(last)} tasi: {span}",
             "🏷 Toifalar: " + (", ".join(f"{html.escape(k)} {v}" for k, v in cats.most_common(6)) or "—"),
             f"📅 Bugun: AI {int(today['ai'] or 0)} ta, admin {int(today['admin'] or 0)} ta javob yozdi",
             f"⏳ Javob kutayotgan izohlar: {int(waiting or 0)}",
             f"💵 Bugungi AI sarfi (izohlar): ${await _usage_today('izoh')}"]
    return "\n".join(lines)


async def direct_report(total: int) -> str:
    async with database.pool.acquire() as conn:
        last = await conn.fetch(
            """SELECT DISTINCT ON (conversation_id, replied_at) conversation_id, replied_at, intent
                 FROM ig_dm_messages WHERE status = 'replied' AND replied_at IS NOT NULL
                ORDER BY conversation_id, replied_at, created_at DESC""")
    last = sorted((dict(r) for r in last), key=lambda r: r["replied_at"], reverse=True)[:STEP]
    intents = Counter((r["intent"] or "boshqa") for r in last)
    span = f"{_t(last[-1]['replied_at'])} – {_t(last[0]['replied_at'])}" if last else "—"
    try:
        import ig_direct
        day = await ig_direct.day_stats()
    except Exception:
        day = {}
    lines = [f"📩 <b>Instagram Direct — yana {STEP} ta javob</b> (jami AI javoblari: {total})",
             f"🕒 Oxirgi {len(last)} tasi: {span} · {len({r['conversation_id'] for r in last})} ta suhbat",
             "🏷 Mavzular: " + (", ".join(f"{html.escape(k)} {v}" for k, v in intents.most_common(6)) or "—"),
             f"📅 Bugun: {day.get('received', 0)} xabar keldi, {day.get('conversations', 0)} suhbatga "
             f"{day.get('replies', 0)} javob, adminga {day.get('to_human', 0)}, spam {day.get('spam', 0)}",
             f"⏳ Navbatda: {day.get('pending', 0)} · o'tkazib yuborilgan (24 soat o'tgan): {day.get('missed', 0)}",
             f"💵 Bugungi AI sarfi (Direct): ${await _usage_today('direct')}"]
    return "\n".join(lines)


async def _send_all(bot: Bot, text: str) -> None:
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as exc:
            logger.info("ig milestone → %s failed: %s", admin_id, exc)


async def check(bot: Bot) -> list[str]:
    """Bosqichga yetgan hisoblagich bo'yicha hisobot yuboradi. Yuborilgan turlar ro'yxati."""
    sent = []
    for kind, total_fn, report_fn in (("izoh", comment_total, comment_report),
                                      ("direct", direct_total, direct_report)):
        total = await total_fn()
        step = total // STEP * STEP
        if step <= 0 or not await database.claim_release_notes(f"ig50:{kind}:{step}"):
            continue
        try:
            await _send_all(bot, await report_fn(total))
            sent.append(kind)
        except Exception:
            logger.exception("ig milestone %s report failed", kind)
            await database.release_release_notes(f"ig50:{kind}:{step}")
    return sent


async def scheduler_loop(bot: Bot) -> None:
    await asyncio.sleep(120)
    while True:
        try:
            await check(bot)
        except Exception:
            logger.exception("ig milestone tick failed")
        await asyncio.sleep(CHECK_EVERY)


@router.message(Command("ig_hisobot"))
async def cmd_report(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        return
    for text in (await comment_report(await comment_total()), await direct_report(await direct_total())):
        await message.answer(text, parse_mode="HTML", disable_web_page_preview=True)
