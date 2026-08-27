"""
Daily full-database backup, sent to every admin as a Telegram document.

Added 2026-07-13 after the `products` table (and every FK-dependent child
table) was found wiped with no recent backup anywhere — the only one on
hand was three weeks stale. This guarantees admins always have a same-day
copy of the whole DB sitting in their own Telegram chat with the bot,
independent of Railway's own backup settings (which may or may not be
enabled/configured).

Runs once a day at ~03:00 Asia/Tashkent (quiet hours). State (last backup
date) lives in the db_backup_state DB row, so a redeploy mid-day doesn't
re-send it, same pattern as broadcast.py / personal_recommend.py.
"""
import asyncio
import gzip
import json
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.types import BufferedInputFile

import database
from config import ADMIN_IDS

logger = logging.getLogger(__name__)

TZ_OFFSET = timedelta(hours=5)  # Asia/Tashkent, fixed UTC+5, no DST
BACKUP_HOUR = 3                 # 03:00 Tashkent
CHECK_EVERY = 900               # re-check every 15 minutes


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


def _json_default(obj):
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


async def run_backup_now(bot: Bot) -> dict:
    """Dump every table, gzip it, send to each admin. Returns a summary dict.
    Also callable on-demand (e.g. from an admin command) outside the daily schedule."""
    data = await database.dump_all_tables()
    counts = {t: len(rows) for t, rows in data.items()}

    payload = json.dumps(data, default=_json_default, ensure_ascii=False).encode("utf-8")
    compressed = gzip.compress(payload)

    date_str = _now_tk().strftime("%Y-%m-%d")
    filename = f"ketoshop_backup_{date_str}.json.gz"

    summary_lines = "\n".join(f"  {t}: {n}" for t, n in sorted(counts.items()) if n)
    caption = (
        f"🗄 Kunlik zaxira nusxa — {date_str}\n\n"
        f"{summary_lines}\n\n"
        f"Hajmi: {len(compressed) / 1024:.0f} KB"
    )
    if len(caption) > 1024:  # Telegram document caption limit
        caption = caption[:1000] + "\n…"

    sent, failed = 0, 0
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_document(
                chat_id=admin_id,
                document=BufferedInputFile(compressed, filename=filename),
                caption=caption,
            )
            sent += 1
        except Exception:
            logger.warning("Daily backup send to admin %s failed", admin_id, exc_info=True)
            failed += 1

    return {"counts": counts, "sent": sent, "failed": failed, "size_bytes": len(compressed)}


async def scheduler_loop(bot: Bot):
    """Background task: checks every CHECK_EVERY seconds, fires once per
    Tashkent calendar day once BACKUP_HOUR has passed."""
    logger.info("Daily DB backup scheduler started (runs ~%02d:00 Asia/Tashkent)", BACKUP_HOUR)
    while True:
        try:
            state = await database.get_backup_state()
            now = _now_tk()
            today = now.date()
            already_done = state.get("last_backup_date") == today
            if not already_done and now.hour >= BACKUP_HOUR:
                result = await run_backup_now(bot)
                await database.set_backup_date(today)
                logger.info(
                    "Daily DB backup sent: %d admin(s) OK, %d failed, %d bytes",
                    result["sent"], result["failed"], result["size_bytes"],
                )
        except Exception:
            logger.exception("Daily DB backup run failed")

        await asyncio.sleep(CHECK_EVERY)
