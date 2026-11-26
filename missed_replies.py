"""AI ishlamay qolgan paytdagi javobsiz savollarga kechikkan javob.

Egasi, 2026-11-26 (OpenAI krediti tugab, AI bir kun javob bermadi): "barcha
javob yozilmagan xabarlarga javob yozib chiqishi kerak, telegramda, botda,
guruhda (agar javob yozilmagan bo'lsa), instagram directda".

* Bot: AI xato bersa savol support_relay kartochkasi bo'lib adminlarga
  ketadi (support_messages, direction='in', answered_at NULL). Admin javob
  bermagan bo'lsa, AI qaytgach shu savollarga AI javob beradi — oldiga
  "kechikdik, uzr" — va adminlardagi kartochkalar "🤖 AI javob berdi" bilan
  yopiladi. Faqat LOOKBACK ichidagi, rasm emas, AI shu odamga javob
  berishi mumkin (mijozlarga yoqilgan, /ai_off emas, admin gapga kirmagan),
  admin «Javob berish» ni bosmagan bo'lsa.
* Guruh: AI xato bergan savol shu jadvalga (ai_missed) yoziladi; AI qaytgach
  o'sha xabarga reply bo'lib javob. Bu o'zgarishdan oldingi guruh savollari
  saqlanmagan — Telegram bot guruh tarixini o'qiy olmaydi.
* Instagram Direct — ig_direct.late_reply (24 soatlik oyna ichida).

Faqat Toshkent vaqti bilan HOURS oralig'ida, har EVERY soniyada; bitta
tekshiruvda PER_TICK tagacha, orasida tanaffus. AI hali ham xato bersa —
tekshiruv to'xtaydi, savollar navbatda qoladi.
"""
from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta
from types import SimpleNamespace as NS

from aiogram import Bot

import database

logger = logging.getLogger(__name__)

LOOKBACK_HOURS = 72
GROUP_LOOKBACK_HOURS = 24
EVERY = 300
HOURS = (8, 23)                   # Toshkent: 08:00–22:59 — tunda mijozni bezovta qilmaymiz
PER_TICK = 10
PAUSE = (2.0, 5.0)
MEDIA_PREFIX = "🖼"

SORRY = {
    "uz": "Javobimiz kechikdi, uzr so'raymiz 🙏",
    "uz_cyr": "Жавобимиз кечикди, узр сўраймиз 🙏",
    "ru": "Извините, что ответ задержался 🙏",
}
GROUP_SORRY = {"uz": "Kechikib javob berayotganimiz uchun uzr 🙏",
               "ru": "Извините за задержку с ответом 🙏"}
CARD_FOOTER = "🤖 <b>AI kechikib javob berdi</b>"

_table_ready = False


def _tashkent_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=5)


def in_hours(now: datetime | None = None) -> bool:
    now = now or _tashkent_now()
    return HOURS[0] <= now.hour < HOURS[1]


async def _ensure(conn) -> None:
    global _table_ready
    if _table_ready:
        return
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_missed (
            id SERIAL PRIMARY KEY,
            channel TEXT NOT NULL,
            chat_id BIGINT NOT NULL,
            message_id BIGINT,
            user_id BIGINT NOT NULL,
            author TEXT,
            text TEXT NOT NULL,
            background TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
            done_at TIMESTAMP,
            result TEXT
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_missed_open ON ai_missed(created_at) "
                       "WHERE done_at IS NULL")
    _table_ready = True


async def remember_group(chat_id: int, message_id: int, user_id: int, author: str,
                         text: str, background: str) -> None:
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        await conn.execute(
            "INSERT INTO ai_missed (channel, chat_id, message_id, user_id, author, text, background) "
            "VALUES ('group', $1, $2, $3, $4, $5, $6)",
            chat_id, message_id, user_id, author, text, background or "")


async def remember_bot(user_id: int, text: str) -> None:
    """Bot savoli AI xatosi sabab adminlarga ketdi — shu belgi bo'lmasa AI
    kechikib javob bermaydi (admin boshqa yo'l bilan javob bergan bo'lishi mumkin)."""
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        await conn.execute("INSERT INTO ai_missed (channel, chat_id, user_id, text) "
                           "VALUES ('bot', $1, $1, $2)", user_id, text or "")


async def close_bot_questions(user_id: int, result: str) -> None:
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        await conn.execute("UPDATE ai_missed SET done_at = NOW() AT TIME ZONE 'UTC', result = $2 "
                           "WHERE channel = 'bot' AND user_id = $1 AND done_at IS NULL", user_id, result)


async def open_group_questions(limit: int) -> list[dict]:
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        rows = await conn.fetch(
            "SELECT * FROM ai_missed WHERE channel = 'group' AND done_at IS NULL "
            f"AND created_at > (NOW() AT TIME ZONE 'UTC') - INTERVAL '{GROUP_LOOKBACK_HOURS} hours' "
            "ORDER BY created_at LIMIT $1", limit)
    return [dict(r) for r in rows]


async def close_group_question(row_id: int, result: str) -> None:
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        await conn.execute("UPDATE ai_missed SET done_at = NOW() AT TIME ZONE 'UTC', result = $2 "
                           "WHERE id = $1", row_id, result)


# 2026-11-25/26 dagi uzilish (OpenAI krediti tugagan) — o'shanda savollar hali
# belgilanmagan edi; shu oraliqdagi javobsiz savollar ham AI xatosi sabab
# ketgan. Undan keyin faqat remember_bot belgisi bo'yicha.
OUTAGE = (datetime(2026, 11, 25, 12, 0), datetime(2026, 11, 26, 9, 0))    # UTC; kredit ~14:00 Toshkentda qaytdi


async def open_bot_questions(limit: int) -> list[dict]:
    """Admin javob bermagan, AI xatosi sabab adminlarga ketgan bot savollari,
    odam bo'yicha: user_id, texts. Savoldan keyin bizdan hech narsa
    ketmagan bo'lsin."""
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        rows = await conn.fetch(
            f"""SELECT s.user_id, array_agg(s.text ORDER BY s.created_at) AS texts,
                       MIN(s.created_at) AS first_at
                  FROM support_messages s
                 WHERE s.direction = 'in' AND s.answered_at IS NULL
                   AND s.created_at > NOW() - INTERVAL '{LOOKBACK_HOURS} hours'
                   -- created_at — server vaqt mintaqasida (CURRENT_TIMESTAMP); UTC ga o'tkazamiz
                   AND ((s.created_at AT TIME ZONE current_setting('TimeZone')) AT TIME ZONE 'UTC'
                            BETWEEN $2 AND $3
                        OR EXISTS (SELECT 1 FROM ai_missed m
                                    WHERE m.channel = 'bot' AND m.user_id = s.user_id
                                      AND m.text = s.text AND m.done_at IS NULL))
                   AND NOT EXISTS (SELECT 1 FROM support_messages o
                                    WHERE o.user_id = s.user_id AND o.direction = 'out'
                                      AND o.created_at >= s.created_at)
                 GROUP BY s.user_id
                 ORDER BY MIN(s.created_at)
                 LIMIT $1""", limit, *OUTAGE)
    return [dict(r) for r in rows]


def bot_question_text(texts: list[str]) -> str:
    """Rasm kartochkalari ("🖼 Rasm yubordi") tashlanadi — ularni AI ko'rmaydi."""
    return "\n".join(t.strip() for t in texts if t and t.strip() and not t.startswith(MEDIA_PREFIX))


class _LateChat:
    """ai_sales._answer kutgan Message'ning kerakli qismi. answer() — birinchi
    xabar oldiga "kechikdik, uzr"."""

    def __init__(self, bot: Bot, user: dict, text: str, sorry: str):
        uid = user["user_id"]
        first = (user.get("first_name") or "").strip()
        self.bot = bot
        self.text = text
        self.message_id = 0
        self.from_user = NS(id=uid, first_name=first or None, last_name=None,
                            full_name=first or "—", username=user.get("username"),
                            is_bot=False, language_code=None)
        self.chat = NS(id=uid, type="private")
        self.reply_to_message = None
        self.location = self.contact = self.photo = self.document = None
        self._sorry = sorry
        self.sent: list[str] = []

    async def answer(self, text: str, **kwargs):
        if not self.sent and self._sorry:
            text = f"{self._sorry}\n\n{text}"
        self.sent.append(text)
        return await self.bot.send_message(self.chat.id, text, **kwargs)


class _LateGroupMessage:
    def __init__(self, bot: Bot, row: dict, sorry: str):
        self.bot = bot
        self.text = row["text"]
        self.message_id = row.get("message_id") or 0
        name = row.get("author") or "Mijoz"
        self.from_user = NS(id=row["user_id"], first_name=name, last_name=None, full_name=name,
                            username=None, is_bot=False, language_code=None)
        self.chat = NS(id=row["chat_id"], type="supergroup")
        self.reply_to_message = None
        self._sorry = sorry
        self.sent: list[str] = []

    async def reply(self, text: str, **kwargs):
        if not self.sent and self._sorry:
            text = f"{self._sorry}\n\n{text}"
        self.sent.append(text)
        if self.message_id:
            kwargs.setdefault("reply_to_message_id", self.message_id)
        return await self.bot.send_message(self.chat.id, text, **kwargs)


async def _user_info(user_id: int) -> dict:
    info = {"user_id": user_id}
    try:
        u = await database.get_user(user_id)
        if u:
            info.update(first_name=u.get("first_name") or u.get("full_name"), username=u.get("username"))
    except Exception:
        logger.debug("missed: user %s not readable", user_id)
    return info


async def _eligible(user_id: int) -> bool:
    import ai_sales
    from database import support_claim_holder
    if user_id in ai_sales._opted_out or ai_sales._is_paused(user_id):
        return False
    if not await ai_sales._allowed(user_id):
        return False
    try:
        if await support_claim_holder(user_id):
            return False          # admin «Javob berish» ni bosgan — u yozyapti
    except Exception:
        return False
    return True


async def _close_bot_cards(bot: Bot, user_id: int, reply: str) -> None:
    from handlers.support_relay import _rewrite_cards
    import html
    preview = (reply or "").strip()
    if len(preview) > 300:
        preview = preview[:300].rstrip() + "…"
    try:
        await database.mark_support_answered(user_id)
        await database.log_support_message(user_id, "out", reply)
        await _rewrite_cards(bot, user_id, footer=f"{CARD_FOOTER}:\n<i>«{html.escape(preview)}»</i>",
                             keyboard=None)
        await database.close_support_relays(user_id)
    except Exception:
        logger.exception("missed: support cards of %s not closed", user_id)


async def answer_bot(bot: Bot, limit: int = PER_TICK) -> dict:
    import ai_sales
    stats = {"sent": 0, "skipped": 0}
    for row in await open_bot_questions(200):
        if stats["sent"] >= limit:
            break
        user_id = row["user_id"]
        text = bot_question_text(row["texts"])
        if not text or not await _eligible(user_id):
            stats["skipped"] += 1
            continue
        lang = await ai_sales._lang(user_id)
        chat = _LateChat(bot, await _user_info(user_id), text, SORRY.get(lang, SORRY["uz"]))
        await ai_sales._answer(bot, chat, text, late=True)      # xato — yuqoriga, tekshiruv to'xtaydi
        if chat.sent:
            stats["sent"] += 1
            await _close_bot_cards(bot, user_id, "\n\n".join(chat.sent))
            await close_bot_questions(user_id, "replied")
            await asyncio.sleep(random.uniform(*PAUSE))
        else:
            stats["skipped"] += 1
    return stats


async def answer_group(bot: Bot, limit: int = PER_TICK) -> dict:
    import ai_sales
    stats = {"sent": 0, "skipped": 0}
    for row in await open_group_questions(limit):
        sorry = GROUP_SORRY["ru"] if ai_sales._CYR_CHAR.search(row["text"] or "") else GROUP_SORRY["uz"]
        msg = _LateGroupMessage(bot, row, sorry)
        await ai_sales._group_answer(bot, msg, row["text"], late_background=row.get("background") or "")
        await close_group_question(row["id"], "replied" if msg.sent else "skip")
        stats["sent" if msg.sent else "skipped"] += 1
        if msg.sent:
            await asyncio.sleep(random.uniform(*PAUSE))
    return stats


async def tick(bot: Bot) -> dict:
    import ai_sales
    if not in_hours() or not await ai_sales._ready():
        return {"wait": 1}
    out = {}
    try:
        out["bot"] = await answer_bot(bot)
        if await ai_sales.setting("group"):
            out["group"] = await answer_group(bot)
    except Exception as exc:
        logger.warning("missed replies: AI still failing (%s) — later", type(exc).__name__)
        out["error"] = type(exc).__name__
    return out


async def loop(bot: Bot) -> None:
    await asyncio.sleep(90)
    while True:
        try:
            stats = await tick(bot)
            if any(isinstance(v, dict) and v.get("sent") for v in stats.values()):
                logger.info("missed replies: %s", stats)
        except Exception:
            logger.exception("missed replies tick failed")
        await asyncio.sleep(EVERY)
