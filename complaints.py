"""Mijoz shikoyati AI suhbatida ko'zdan qochmasin (egasi, 2026-11-26 — saytdagi
«Yordamchi»ga "o'tgan safar javdar uni zakaz qilganimda kelmagan edi, olib kelib
beramiz deb hech kim olib kelmadi" deb yozilgan; AI faqat telefon berdi, adminlarga
hech narsa bormadi, shikoyat hal bo'lmadi).

AI (bot, sayt yordamchisi, guruh) javob bergach, mijoz matnida shikoyat belgisi
bo'lsa — support_relay kartochkasi («↩️ Javob berish» tugmasi bilan) hamma
adminlarga: qaysi kanal, mijoz yozgani, AI nima degani va so'nggi buyurtmalari.
Bir mijozga DEDUP_HOURS da bir marta (ketma-ket xabarlar — bitta kartochka).
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import timedelta

import database

logger = logging.getLogger(__name__)

DEDUP_HOURS = 6
CHANNELS = {"bot": "🤖 Bot", "site": "🌐 Sayt yordamchisi", "group": "👥 Kanal guruhi"}

COMPLAINT = re.compile(
    r"kelmad|kelmag|kemag|kemad|yetib kelmad|yetkazilmad|olib kelmad|ob kemad|ob kelmad|kam keld|"
    r"buzil|buzuq|sinib keld|muddati o'?tgan|eskirgan|noto'?g'?ri keld|almashib keld|aralashib keld|"
    r"pulimni|qaytarib bering|aldad|shikoyat|hech kim (olib|ob|qo'ng'iroq|javob)|javob bermay|"
    r"келмад|келмаг|кемаг|кемад|етиб келмад|етказилмад|олиб келмад|об кемад|кам келд|бузил|бузуқ|"
    r"муддати ўтган|нотўғри келд|пулимни|қайтариб беринг|алдад|шикоят|ҳеч ким (олиб|об)|хеч ким (олиб|об)|"
    r"не пришл|не доставил|не привез|не довез|не хватает|недолож|верните|обманул|жалоб|испорч|просроч|"
    r"разбит|не тот товар",
    re.IGNORECASE)

_recent: dict[int, float] = {}


def is_complaint(text: str | None) -> bool:
    return bool(COMPLAINT.search((text or "").replace("ʻ", "'").replace("’", "'")))


def _items(order: dict) -> list[dict]:
    items = order.get("items")
    if isinstance(items, str):
        try:
            items = json.loads(items)
        except ValueError:
            items = []
    return items if isinstance(items, list) else []


async def _orders_line(user_id: int) -> str:
    try:
        orders = (await database.get_user_orders(user_id))[:3]
    except Exception:
        return ""
    lines = []
    for o in orders:
        when = (o["created_at"] + timedelta(hours=5)).strftime("%d.%m") if o.get("created_at") else "—"
        goods = ", ".join(f"{i.get('name')} ×{i.get('quantity')}" for i in _items(o)[:5])
        lines.append(f"• #{o['id']} {when} · {o.get('status')} · {goods}")
    return ("\n🧾 So'nggi buyurtmalari:\n" + "\n".join(lines)) if lines else "\n🧾 Buyurtmasi yo'q"


async def escalate(bot, user, channel: str, text: str, ai_reply: str | None = None) -> bool:
    """Shikoyat bo'lsa — adminlarga kartochka. True — yuborildi."""
    if bot is None or user is None or not is_complaint(text):
        return False
    now = time.time()
    if now - _recent.get(user.id, 0) < DEDUP_HOURS * 3600:
        return False
    _recent[user.id] = now
    body = (f"⚠️ SHIKOYAT — AI sezdi ({CHANNELS.get(channel, channel)})\n"
            f"«{text.strip()[:900]}»"
            + (f"\n🤖 AI javobi: «{ai_reply.strip()[:300]}»" if ai_reply else "")
            + await _orders_line(user.id)
            + "\n👉 Odam hal qilishi kerak — mijozga javob bering.")
    try:
        from handlers.support_relay import _to_admins
        await _to_admins(bot, user, body)
        return True
    except Exception:
        logger.exception("complaint card for %s not sent", user.id)
        return False
