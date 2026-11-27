"""Avval yuborilgan, adminlarga yetmagan rasmlar — bir marta adminlarga (egasi,
2026-11-27: "avval yuborilgan rasmlari ham kelsin-da").

#278 gacha AI suhbatidagi har rasmga "Bu to'lov chekimi?" deb so'ralardi; mijoz
javob bermasa, rasm faqat FSM ma'lumotida (fsm_state.data.cheque_candidates,
cheque_confirm.py) qolardi va adminlar uni ko'rmasdi. Shu rasmlar bir marta
support_relay kartochkasi bo'lib adminlarga boradi («↩️ Javob berish» bilan).
Savoldagi tugma ishlashda davom etadi (ma'lumot o'chirilmaydi).

AI suhbati ochiq bo'lmagan paytda yuborilgan rasmlar esa hech qayerda saqlanmagan —
Telegram ularni botga qayta bermaydi, ularni tiklab bo'lmaydi.
"""
from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace as NS

import database

logger = logging.getLogger(__name__)

KEY = "recover_cheque_candidate_photos_2026_11_27"
PAUSE = 1.0


async def pending_photos() -> list[tuple[int, dict]]:
    """[(user_id, {kind, file_id, caption})] — javobsiz qolgan rasmlar, chatlar bo'yicha."""
    async with database.pool.acquire() as conn:
        exists = await conn.fetchval("SELECT to_regclass('fsm_state')")
        if not exists:
            return []
        rows = await conn.fetch("SELECT key, data FROM fsm_state WHERE data ? 'cheque_candidates'")
    out = []
    for r in rows:
        try:
            _bot, chat_id, user_id = str(r["key"]).split(":")[:3]
            if chat_id != user_id:
                continue                      # faqat shaxsiy chat
            data = r["data"] if isinstance(r["data"], dict) else json.loads(r["data"])
        except (ValueError, TypeError):
            continue
        for _msg, c in sorted((data.get("cheque_candidates") or {}).items(), key=lambda kv: int(kv[0])):
            if c.get("file_id"):
                out.append((int(user_id), c))
    return out


async def run_once(bot) -> int:
    if not await database.claim_release_notes(KEY):
        return 0
    from handlers.support_relay import relay_media
    sent = 0
    for user_id, c in await pending_photos():
        try:
            user = await database.get_user(user_id) or {}
            who = NS(id=user_id, full_name=user.get("full_name") or "—", username=user.get("username"))
            caption = "↩️ avval yuborilgan, javobsiz qolgan rasm" + (f": {c['caption']}" if c.get("caption") else "")
            await relay_media(bot, who, c.get("kind") or "photo", c["file_id"], caption)
            sent += 1
            await asyncio.sleep(PAUSE)
        except Exception:
            logger.warning("old photo of %s not relayed", user_id, exc_info=True)
    logger.info("recovered %d old customer photo(s) to the admins", sent)
    return sent


async def scheduler_loop(bot) -> None:
    await asyncio.sleep(90)
    try:
        await run_once(bot)
    except Exception:
        logger.exception("old photo recovery failed")
