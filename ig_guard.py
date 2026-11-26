"""Instagram akkaunti xavfsizligi — hamma avtomatik yozish bitta darvozadan
(egasi, 2026-11-26: "instagramga suspicious action deb keldi, juda ko'p bir
vaqtda yozma, akauntni 100% xavfsiz holatda ulanib yozgin").

meta_comments._graph har bir POST (izohga javob, yashirish, Direct, qayta
yozish) oldidan before_write() ni chaqiradi:
* PAUZA: Meta "shubhali harakat" / "action blocked" / tezlik chegarasi
  qaytarsa — hamma yozish PAUSE_HOURS soatga to'xtaydi (bazada saqlanadi,
  qayta ishga tushsa ham), adminlarga bir marta xabar.
* ODAMDEK TEZLIK: ikki yozish orasida kamida MIN_GAP..MAX_GAP soniya
  (tasodifiy), soatiga HOURLY tadan, kuniga DAILY tadan ko'p emas. Chegara
  to'lsa — GraphError(4) (hamma chaqiruvchi buni "keyinroq" deb tushunadi).
* Faqat kunduzi (Toshkent HOURS) — tunda bot yozmaydi.
Instagram'dan o'qish (GET) cheklanmaydi.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import deque
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

PAUSE_HOURS = 48
# Egasi, 2026-11-26 ("o'zing xavfsizlik va ... har necha daqiqada yozish kerakligini aniqla"):
# Meta ogohlantirishidan keyingi kunlar uchun ehtiyotkor, odamdek ritm — 3–7 daqiqada bitta,
# soatiga 10, kuniga 60, faqat 09–21. Hamma yozish (yangi izohga javob, qayta yozish, Direct)
# shu bitta navbatda.
MIN_GAP, MAX_GAP = 180.0, 420.0      # ikki yozish orasida, soniya
HOURLY = 10
DAILY = 60
HOURS = (9, 21)                      # Toshkent
SETTING = "ig_pause_until"
WARNING_CODES = {4, 17, 32, 368, 613}
WARNING_WORDS = ("suspicious", "unusual", "checkpoint", "action blocked", "temporarily blocked", "spam",
                 "rate limit", "too many", "restricted", "limit how often", "try again later")

_lock = asyncio.Lock()
_sent: deque[float] = deque()
_last = {"at": 0.0}
_paused = {"until": None, "loaded": False}


class Blocked(Exception):
    pass


def _now_tk() -> datetime:
    return datetime.utcnow() + timedelta(hours=5)


def is_warning(code, message: str | None) -> bool:
    msg = (message or "").lower()
    return code in WARNING_CODES or any(w in msg for w in WARNING_WORDS)


async def _load() -> None:
    if _paused["loaded"]:
        return
    _paused["loaded"] = True
    try:
        import ai_sales
        values = await ai_sales._load_settings()
        raw = values.get(SETTING)
        if raw:
            _paused["until"] = datetime.fromisoformat(raw)
    except Exception:
        logger.warning("ig guard: pause state unreadable", exc_info=True)


async def paused_until() -> datetime | None:
    await _load()
    until = _paused["until"]
    return until if until and until > datetime.utcnow() else None


async def pause(reason: str, hours: float = PAUSE_HOURS, bot=None) -> None:
    """Hamma avtomatik yozishni to'xtatadi va adminlarga bir marta aytadi."""
    until = datetime.utcnow() + timedelta(hours=hours)
    already = await paused_until()
    _paused["until"] = max(until, already) if already else until
    try:
        import ai_sales
        await ai_sales.set_setting(SETTING, _paused["until"].isoformat())
    except Exception:
        logger.warning("ig guard: pause not saved", exc_info=True)
    logger.warning("Instagram writes paused until %s: %s", _paused["until"], reason)
    if already:
        return
    try:
        from config import ADMIN_IDS
        if bot is None:
            from aiogram import Bot
            from config import BOT_TOKEN
            bot = Bot(BOT_TOKEN)
        text = (f"🛡 <b>Instagram — avtomatik yozish {int(hours)} soatga to'xtatildi</b>\n"
                f"Meta ogohlantirdi: «{reason[:200]}».\n"
                f"Izohlarga javob, qayta yozish va Direct {(_paused['until'] + timedelta(hours=5)):%d.%m %H:%M} "
                "gacha jim. Akkaunt xavfsizligi uchun. Ertaroq kerak bo'lsa: /ig_pauza off")
        for admin_id in ADMIN_IDS:
            try:
                await bot.send_message(admin_id, text, parse_mode="HTML")
            except Exception:
                pass
    except Exception:
        logger.warning("ig guard: admins not told", exc_info=True)


async def resume() -> None:
    _paused["until"] = None
    try:
        import ai_sales
        await ai_sales.set_setting(SETTING, "")
    except Exception:
        logger.warning("ig guard: resume not saved", exc_info=True)


def _trim(now: float) -> None:
    while _sent and now - _sent[0] > 24 * 3600:
        _sent.popleft()


async def before_write() -> None:
    """POST oldidan: pauza, tun, chegaralar — Blocked; aks holda navbat kutadi."""
    if await paused_until():
        raise Blocked("Instagram pauzada (xavfsizlik)")
    if not HOURS[0] <= _now_tk().hour < HOURS[1]:
        raise Blocked("tunda Instagram'ga yozilmaydi")
    async with _lock:
        now = time.time()
        _trim(now)
        if sum(1 for t in _sent if now - t < 3600) >= HOURLY:
            raise Blocked(f"soatiga {HOURLY} ta chegarasi")
        if len(_sent) >= DAILY:
            raise Blocked(f"kuniga {DAILY} ta chegarasi")
        wait = _last["at"] + random.uniform(MIN_GAP, MAX_GAP) - now
        if wait > 0:
            await asyncio.sleep(wait)
        _last["at"] = time.time()
        _sent.append(_last["at"])


def status_line() -> str:
    now = time.time()
    _trim(now)
    hour = sum(1 for t in _sent if now - t < 3600)
    until = _paused["until"]
    state = (f"⏸ pauza {(until + timedelta(hours=5)):%d.%m %H:%M} gacha"
             if until and until > datetime.utcnow() else "✅ ishlayapti")
    return (f"🛡 Instagram himoyasi: {state} · oxirgi soatda {hour}/{HOURLY}, sutkada {len(_sent)}/{DAILY} · "
            f"orasida {int(MIN_GAP)}–{int(MAX_GAP)} s · {HOURS[0]:02d}–{HOURS[1]:02d}")


# ─────────────────────────────── /ig_pauza ──────────────────────────────────
from aiogram import Router                    # noqa: E402
from aiogram.filters import Command           # noqa: E402
from aiogram.types import Message             # noqa: E402

router = Router(name="ig_guard")


@router.message(Command("ig_pauza"))
async def cmd_pause(message: Message):
    """/ig_pauza — holat; /ig_pauza on [soat] — to'xtatish; /ig_pauza off — davom ettirish."""
    from config import ADMIN_IDS
    if message.from_user.id not in ADMIN_IDS:
        return
    parts = (message.text or "").split()
    arg = parts[1].lower() if len(parts) > 1 else ""
    if arg == "off":
        await resume()
        await message.answer("✅ Instagram'ga avtomatik yozish qayta yoqildi (odamdek tezlikda).")
        return
    if arg == "on":
        hours = float(parts[2]) if len(parts) > 2 and parts[2].replace(".", "").isdigit() else PAUSE_HOURS
        await pause(f"admin {message.from_user.id} qo'lda to'xtatdi", hours, bot=message.bot)
        await message.answer(f"⏸ Instagram'ga avtomatik yozish {hours:g} soatga to'xtatildi.")
        return
    await paused_until()
    await message.answer(status_line() + "\n\n/ig_pauza on [soat] — to'xtatish · /ig_pauza off — davom ettirish")
