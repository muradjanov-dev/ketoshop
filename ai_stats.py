"""
AI hisobot — AI nechta mijoz bilan gaplashdi, nechta xabarga javob berdi va
qaysi mavzularda (egasi, 2026-10-14: "shu paytgacha nechta odamni savoliga
javob berding? va qanday mavzularda?").

Har bir AI javobi (botda va kanal guruhida) ai_conversations ga yoziladi:
bitta mijoz + 1 soatgacha jimlik = bitta suhbat (guruh mavzusidagi suhbat
xabari bilan bir xil qoida). Mavzu mijoz matnidagi kalit so'zlardan topiladi —
model chaqirilmaydi, token ketmaydi. Adminlar va ichki akkauntlarning sinov
yozishmalari hisobga kirmaydi.

Jadval paydo bo'lgunga qadar (deploydan oldin) suhbatlar soni yo'q; o'sha davr
uchun hisobotda mijoz xotirasidagi qiziqishlar (ai_customer_notes) ko'rsatiladi.
"""
import html
import logging
import re
import time

import database

logger = logging.getLogger(__name__)

NEW_CONVERSATION_AFTER = 3600

# (kalit, nomi, kalit so'zlar) — tartib hisobotdagi tartib.
TOPICS = [
    ("narx", "💰 Narx / mahsulot bormi",
     r"narx|narh|qancha|bormi|\bbor\b|сколько|цена|почем|есть ли|нарх|қанча|борми|price|how much|do you have"),
    ("buyurtma", "🛒 Buyurtma berish",
     r"buyurtma|olaman|olmoqchi|savat|zakaz|заказ|купить|буюртма|оламан|order|\bbuy\b"),
    ("yetkazish", "🚚 Yetkazish",
     r"yetkaz|dostavka|qachon|kuryer|pochta|\bbts\b|\bemu\b|доставк|курьер|етказ|қачон|deliver"),
    ("retsept", "🍰 Retsept / pishirish", r"retsept|resept|рецепт|ретсепт|pishir|пишир|recipe|bake"),
    ("keto", "🥗 Keto / PP maslahat",
     r"keto|кето|\bpp\b|\bпп\b|ozish|озиш|shakar|шакар|сахар|diabet|диабет|kaloriya|калор|uglevod|углевод|sugar"),
    ("tolov", "💳 To'lov / chek", r"karta|карта|\bchek\b|\bчек\b|to'?lov|тўлов|оплат|naqd|нақд|наличн|payme|click|\bpay"),
    ("manzil", "📍 Do'kon manzili / olib ketish",
     r"manzil|qayerda|адрес|где вы|манзил|қаерда|olib ket|самовывоз|address|where are you"),
    ("shikoyat", "⚠️ Shikoyat / muammo",
     r"kelmadi|kechik|shikoyat|jahl|buzil|qaytar|almashtir|проблем|не пришл|жалоб|келмади|шикоят|complain|refund"),
]
_TOPIC_RES = [(key, title, re.compile(words, re.IGNORECASE)) for key, title, words in TOPICS]
TOPIC_TITLES = {key: title for key, title, _ in TOPICS}
OTHER = "boshqa"
TOPIC_TITLES[OTHER] = "💬 Boshqa (salom, umumiy savol)"

_open: dict[tuple[str, int], tuple[int, float]] = {}
_table_ready = False


def classify(text: str | None) -> list[str]:
    """Mijoz matnidagi mavzular. "[Mijoz lokatsiyasini yubordi ...]" kabi tizim
    belgilari hisobga olinmaydi."""
    clean = re.sub(r"\[[^\]]*\]", " ", text or "")
    return [key for key, _, pattern in _TOPIC_RES if pattern.search(clean)]


async def _ensure(conn) -> None:
    global _table_ready
    if _table_ready:
        return
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_conversations (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            channel TEXT NOT NULL,
            started_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
            last_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
            messages INTEGER NOT NULL DEFAULT 1,
            topics TEXT[] NOT NULL DEFAULT '{}'
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_conversations_started "
                       "ON ai_conversations(started_at)")
    _table_ready = True


async def record_turn(user_id: int, channel: str, text: str | None) -> None:
    """AI bir mijozga javob berdi — suhbatni hisobga oladi. Xato bo'lsa jim:
    statistika javobdan muhim emas."""
    topics = classify(text)
    key = (channel, user_id)
    now = time.time()
    current = _open.get(key)
    try:
        async with database.pool.acquire() as conn:
            await _ensure(conn)
            if current and now - current[1] < NEW_CONVERSATION_AFTER:
                await conn.execute(
                    """UPDATE ai_conversations
                          SET messages = messages + 1, last_at = NOW() AT TIME ZONE 'UTC',
                              topics = ARRAY(SELECT DISTINCT unnest(topics || $2::text[]))
                        WHERE id = $1""", current[0], topics)
                _open[key] = (current[0], now)
            else:
                conv_id = await conn.fetchval(
                    "INSERT INTO ai_conversations (user_id, channel, topics) VALUES ($1, $2, $3) "
                    "RETURNING id", user_id, channel, topics)
                _open[key] = (conv_id, now)
    except Exception:
        logger.warning("AI conversation could not be recorded for %s", user_id, exc_info=True)


_DAY = "(c.started_at + INTERVAL '5 hours')::date"
_TODAY = "(NOW() AT TIME ZONE 'UTC' + INTERVAL '5 hours')::date"
PERIODS = (("bugun", f"{_DAY} = {_TODAY}"), ("7 kun", f"{_DAY} > {_TODAY} - 7"), ("jami", "TRUE"))


async def fetch_stats() -> dict:
    """Hisobot uchun hamma raqamlar — bitta ulanishda."""
    stats: dict = {"periods": [], "topics": [], "interests": [], "people_with_notes": 0,
                   "orders": [], "questions": 0, "since": None}
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        for label, where in PERIODS:
            row = await conn.fetchrow(
                f"""SELECT COUNT(DISTINCT c.user_id) AS people, COUNT(*) AS conversations,
                           COALESCE(SUM(c.messages), 0) AS messages,
                           COUNT(*) FILTER (WHERE c.channel = 'group') AS group_conversations
                      FROM ai_conversations c WHERE {where}""")
            stats["periods"].append((label, dict(row)))
        stats["since"] = await conn.fetchval("SELECT MIN(started_at) FROM ai_conversations")
        rows = await conn.fetch(
            f"""SELECT topic, COUNT(*) AS n FROM (
                    SELECT CASE WHEN cardinality(c.topics) = 0 THEN ARRAY['{OTHER}'] ELSE c.topics END AS ts
                      FROM ai_conversations c WHERE {PERIODS[1][1]}) x, unnest(x.ts) AS topic
                 GROUP BY topic ORDER BY n DESC""")
        stats["topics"] = [(r["topic"], int(r["n"])) for r in rows]
        try:
            rows = await conn.fetch(
                """SELECT text, COUNT(DISTINCT user_id) AS n FROM ai_customer_notes
                    WHERE kind = 'interest' AND text NOT LIKE 'guruhda so''radi:%'
                    GROUP BY text ORDER BY n DESC, text LIMIT 8""")
            stats["interests"] = [(r["text"], int(r["n"])) for r in rows]
            stats["people_with_notes"] = int(await conn.fetchval(
                "SELECT COUNT(DISTINCT user_id) FROM ai_customer_notes") or 0)
        except Exception:
            logger.debug("ai_customer_notes not available yet", exc_info=True)
        try:
            for label, where in (("bugun", f"(a.created_at + INTERVAL '5 hours')::date = {_TODAY}"),
                                 ("7 kun", f"(a.created_at + INTERVAL '5 hours')::date > {_TODAY} - 7"),
                                 ("jami", "TRUE")):
                row = await conn.fetchrow(
                    f"""SELECT COUNT(*) AS orders, COALESCE(SUM(o.total), 0) AS total
                          FROM ai_orders a JOIN orders o ON o.id = a.order_id
                         WHERE {where} AND COALESCE(o.status, '') <> 'cancelled'""")
                stats["orders"].append((label, int(row["orders"]), float(row["total"])))
        except Exception:
            logger.debug("ai_orders not available yet", exc_info=True)
        try:
            stats["questions"] = int(await conn.fetchval(
                "SELECT COUNT(*) FROM ai_knowledge WHERE kind = 'question' AND NOT handled") or 0)
        except Exception:
            pass
    return stats


def _fmt(n) -> str:
    return f"{int(round(float(n or 0))):,}".replace(",", " ")


def report_text(stats: dict) -> str:
    lines = ["🤖 <b>AI hisobot</b> — mijozlar bilan suhbatlar", ""]
    for label, row in stats["periods"]:
        group = f" (guruhda {row['group_conversations']})" if row["group_conversations"] else ""
        lines.append(f"<b>{label.capitalize()}:</b> {row['people']} ta mijoz · "
                     f"{row['conversations']} ta suhbat{group} · {row['messages']} ta javob")
    if stats.get("orders"):
        lines.append("")
        lines.append("🛒 <b>AI sotuvlari</b> (bekor qilinganlarsiz): " + " · ".join(
            f"{label} — {n} ta, {_fmt(total)} so'm" for label, n, total in stats["orders"]))
    if stats["topics"]:
        lines += ["", "📊 <b>Mavzular (7 kun, suhbatlar soni)</b>"]
        lines += [f"   {TOPIC_TITLES.get(key, key)} — {n}" for key, n in stats["topics"]]
    if stats["interests"]:
        lines += ["", "🔎 <b>Eng ko'p so'ralgan mahsulotlar</b> (nechta mijoz)"]
        lines += [f"   {html.escape(text)} — {n}" for text, n in stats["interests"]]
    if stats.get("people_with_notes"):
        lines.append(f"   <i>AI xotirasida jami {stats['people_with_notes']} ta mijoz bor.</i>")
    if stats.get("questions"):
        lines += ["", f"❓ AI javob bera olmagan savollar: <b>{stats['questions']} ta</b> — /ai_bilim"]
    since = stats.get("since")
    lines += ["", "<i>Suhbatlar hisobi " + (f"{since:%d.%m.%Y} dan" if since else "shu yangilanishdan")
              + " boshlab yuritiladi; adminlarning sinovi kirmaydi.</i>"]
    return "\n".join(lines)


async def day_line(day) -> str:
    """23:58 hisoboti uchun bir qator: shu kun nechta mijoz va asosiy mavzular."""
    try:
        async with database.pool.acquire() as conn:
            await _ensure(conn)
            row = await conn.fetchrow(
                """SELECT COUNT(DISTINCT user_id) AS people, COALESCE(SUM(messages), 0) AS messages
                     FROM ai_conversations WHERE (started_at + INTERVAL '5 hours')::date = $1""", day)
            rows = await conn.fetch(
                """SELECT topic, COUNT(*) AS n FROM ai_conversations c, unnest(c.topics) AS topic
                    WHERE (c.started_at + INTERVAL '5 hours')::date = $1
                    GROUP BY topic ORDER BY n DESC LIMIT 3""", day)
    except Exception:
        logger.warning("AI day line unavailable", exc_info=True)
        return ""
    if not row or not int(row["people"] or 0):
        return ""
    top = ", ".join(TOPIC_TITLES.get(r["topic"], r["topic"]) for r in rows)
    return (f"👥 Suhbatlar: <b>{row['people']} ta mijoz</b>, {row['messages']} ta javob"
            + (f" · ko'pi: {top}" if top else ""))
