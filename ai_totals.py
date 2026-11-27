"""AI hamma joyda nechta javob yozgani — jami, boshidan beri (egasi, 2026-11-27:
"shu kungacha ai nechta insonga javob yozgan hamma yerda ... necha soat tejaganmiz?").

Faqat o'qiydi. Manbalar:
  * ai_conversations (ai_stats.py) — bot/sayt/guruh, eng eski hisob (messages = AI javoblari);
  * ai_dialog — 2026-11-17 dan beri har savol-javob matni bilan (solishtirish uchun);
  * ig_dm_messages — Instagram Direct: bitta javob = (suhbat, replied_at) jufti;
  * meta_comments — AI yozgan izoh javoblari va 1–3-qayta xabarlar.
Xodimlar (adminlar, do'kon hisoblari) Telegram sonlariga kirmaydi.
"""
from __future__ import annotations

import logging

import database

logger = logging.getLogger(__name__)


def _iso(value):
    return value.isoformat() if value is not None else None


async def _one(conn, sql: str, *args) -> dict:
    try:
        row = await conn.fetchrow(sql, *args)
    except Exception as exc:          # jadval hali yo'q — shu manba 0
        logger.info("ai totals: %s", exc)
        return {"replies": 0, "people": 0, "since": None}
    return {"replies": int(row["replies"] or 0), "people": int(row["people"] or 0), "since": _iso(row["since"])}


async def totals(staff: list[int]) -> dict:
    staff = [int(x) for x in staff]
    out: dict = {"telegram": {}, "telegram_text": {}}
    async with database.pool.acquire() as conn:
        for channel in ("bot", "site", "group"):
            out["telegram"][channel] = await _one(
                conn, """SELECT SUM(messages) AS replies, COUNT(DISTINCT user_id) AS people,
                                MIN(started_at) AS since
                           FROM ai_conversations WHERE channel = $1 AND NOT (user_id = ANY($2::bigint[]))""",
                channel, staff)
            out["telegram_text"][channel] = await _one(
                conn, """SELECT COUNT(*) AS replies, COUNT(DISTINCT user_id) AS people, MIN(created_at) AS since
                           FROM ai_dialog WHERE channel = $1 AND answer <> ''
                            AND NOT (user_id = ANY($2::bigint[]))""",
                channel, staff)
        out["telegram_people"] = (await _one(
            conn, """SELECT 0 AS replies, COUNT(DISTINCT user_id) AS people, MIN(started_at) AS since
                       FROM ai_conversations WHERE NOT (user_id = ANY($1::bigint[]))""", staff))["people"]
        out["direct"] = await _one(
            conn, """SELECT COUNT(DISTINCT (conversation_id, replied_at)) AS replies,
                            COUNT(DISTINCT conversation_id) AS people, MIN(replied_at) AS since
                       FROM ig_dm_messages WHERE status = 'replied' AND replied_at IS NOT NULL""")
        out["direct_holding"] = (await _one(
            conn, """SELECT COUNT(DISTINCT (conversation_id, replied_at)) AS replies,
                            COUNT(DISTINCT conversation_id) AS people, MIN(replied_at) AS since
                       FROM ig_dm_messages WHERE status = 'held' AND replied_at IS NOT NULL"""))
        out["comments"] = await _one(
            conn, """SELECT COUNT(*) AS replies, COUNT(DISTINCT lower(username)) AS people,
                            MIN(COALESCE(replied_at, created_at)) AS since
                       FROM meta_comments WHERE status = 'ai_answered'""")
        out["followups"] = await _one(
            conn, """SELECT COUNT(*) FILTER (WHERE COALESCE(followup_text, '') <> '')
                          + COUNT(*) FILTER (WHERE COALESCE(followup2_text, '') <> '')
                          + COUNT(*) FILTER (WHERE COALESCE(followup3_text, '') <> '') AS replies,
                            COUNT(DISTINCT lower(username)) FILTER (WHERE COALESCE(followup_text, '') <> '')
                                AS people,
                            MIN(followup_at) AS since
                       FROM meta_comments""")
    tg = sum(v["replies"] for v in out["telegram"].values())
    out["total_replies"] = (tg + out["direct"]["replies"] + out["direct_holding"]["replies"]
                            + out["comments"]["replies"] + out["followups"]["replies"])
    return out
