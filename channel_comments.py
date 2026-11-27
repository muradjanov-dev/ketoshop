"""Kanal postlaridagi hamma izohlar — to'liq saqlanadi.

Egasi, 2026-11-27: "endi kanal postlaridagi hamma izohlarni saqlaydigan qil".
Kanalda "eng ko'p ishlatadigan 10 ta mahsulotingiz" deb so'ralgan edi. Javoblarni
ko'rib chiqqanda bazada faqat AI javob bergan izohlar topildi (ai_dialog), qolgani
hech qayerda yo'q edi: Bot API guruh tarixini qaytarmaydi.

Endi @ketoshop_uz ga ulangan muhokama guruhidagi har bir xabar yoziladi:
  * kanaldan guruhga avtomatik tushgan post — channel_comment_posts (qaysi post
    ekanini bilish uchun: kanaldagi message_id va matni);
  * har bir izoh — channel_comments: kim yozgani, to'liq matni (yoki rasm/video
    izohi), qaysi postga (message_thread_id), qaysi xabarga javob, vaqti. Keyin
    tahrir qilinsa matn yangilanadi (edited_at).

link_guard havolali izohni o'chiradi. U ham shu yerda saqlanib qoladi, chunki
middleware har qanday handlerdan oldin ishlaydi.

Hammasi MUDDATSIZ saqlanadi (egasi, 2026-11-17: "biz hammasini cheksiz saqlashimiz
kerak"). /malumotlarim da ma'lumotini o'chirgan mijoz yozilmaydi (ai_dialog
dagidek). Hech bir funksiya xato ko'tarmaydi va xabarni to'xtatmaydi: yozuv
ishlamasa ham guruh va AI odatdagidek ishlaydi.

Ko'rish: botda /kanal_izohlar (oxirgi postlar va izohlar soni), /kanal_izohlar N
(N-postning hamma izohlari fayl qilib); saytda GET /admin/api/channel-comments.
"""
from __future__ import annotations

import asyncio
import html
import logging
from datetime import timedelta

from aiogram import BaseMiddleware, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, Message

import database

logger = logging.getLogger(__name__)

router = Router(name="channel_comments")

_table_ready = False
_tasks: set[asyncio.Task] = set()


async def _ensure(conn) -> None:
    global _table_ready
    if _table_ready:
        return
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS channel_comment_posts (
            chat_id BIGINT NOT NULL,
            thread_id BIGINT NOT NULL,
            channel_message_id BIGINT,
            text TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
            PRIMARY KEY (chat_id, thread_id)
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS channel_comments (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT NOT NULL,
            message_id BIGINT NOT NULL,
            thread_id BIGINT,
            reply_to_message_id BIGINT,
            user_id BIGINT,
            username TEXT,
            full_name TEXT,
            kind TEXT NOT NULL DEFAULT 'text',
            file_id TEXT,
            text TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
            edited_at TIMESTAMP,
            UNIQUE (chat_id, message_id)
        )
    """)
    await conn.execute("CREATE INDEX IF NOT EXISTS idx_channel_comments_thread "
                       "ON channel_comments(chat_id, thread_id, id)")
    _table_ready = True


# ───────────────────────── qaysi guruh ─────────────────────────

async def _is_channel_group(message: Message) -> bool:
    chat = message.chat
    if chat is None or chat.type not in ("group", "supergroup"):
        return False
    import ai_sales
    try:
        linked = await ai_sales._channel_group(message.bot)
    except Exception:
        return False
    return bool(linked) and chat.id == linked


def _is_post(message: Message) -> bool:
    import ai_sales
    return ai_sales._is_channel_post(message)


def _channel_message_id(message: Message) -> int | None:
    origin = getattr(message, "forward_origin", None)
    mid = getattr(origin, "message_id", None) if origin is not None else None
    return mid or getattr(message, "forward_from_message_id", None)


def _kind_and_file(message: Message) -> tuple[str, str | None]:
    if message.photo:
        return "photo", message.photo[-1].file_id
    for kind in ("video", "voice", "video_note", "audio", "document", "animation", "sticker"):
        obj = getattr(message, kind, None)
        if obj is not None and not isinstance(obj, (str, bool, int)):
            return kind, getattr(obj, "file_id", None)
    return "text", None


def _text(message: Message) -> str:
    text = message.text or message.caption or ""
    if not text and message.sticker is not None:
        text = getattr(message.sticker, "emoji", "") or ""
    return str(text) if isinstance(text, str) else ""


# ───────────────────────── yozish ─────────────────────────

async def record(message: Message) -> None:
    """Bitta guruh xabarini yozadi: post yoki izoh. Xato ko'tarmaydi."""
    if database.pool is None:
        return
    try:
        if not await _is_channel_group(message):
            return
        async with database.pool.acquire() as conn:
            await _ensure(conn)
            if _is_post(message):
                await conn.execute(
                    """INSERT INTO channel_comment_posts (chat_id, thread_id, channel_message_id, text)
                       VALUES ($1, $2, $3, $4)
                       ON CONFLICT (chat_id, thread_id) DO NOTHING""",
                    message.chat.id, message.message_id, _channel_message_id(message), _text(message))
                return
            user = message.from_user
            user_id = user.id if user else None
            if user_id is not None:
                import customer_portrait
                if await customer_portrait.is_opted_out(user_id, conn):
                    return
            kind, file_id = _kind_and_file(message)
            reply = message.reply_to_message
            await conn.execute(
                """INSERT INTO channel_comments
                       (chat_id, message_id, thread_id, reply_to_message_id, user_id, username,
                        full_name, kind, file_id, text)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                   ON CONFLICT (chat_id, message_id) DO NOTHING""",
                message.chat.id, message.message_id, message.message_thread_id,
                reply.message_id if reply else None, user_id,
                user.username if user else None, user.full_name if user else None,
                kind, file_id, _text(message))
    except Exception:
        logger.warning("Channel comment %s could not be recorded",
                       getattr(message, "message_id", None), exc_info=True)


async def record_edit(message: Message) -> None:
    if database.pool is None:
        return
    try:
        if not await _is_channel_group(message):
            return
        async with database.pool.acquire() as conn:
            await _ensure(conn)
            await conn.execute(
                """UPDATE channel_comments SET text = $3, edited_at = NOW() AT TIME ZONE 'UTC'
                   WHERE chat_id = $1 AND message_id = $2""",
                message.chat.id, message.message_id, _text(message))
    except Exception:
        logger.warning("Channel comment edit %s could not be recorded",
                       getattr(message, "message_id", None), exc_info=True)


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


class ChannelCommentsMiddleware(BaseMiddleware):
    """dp.message outer — first, so a comment link_guard deletes is kept too.
    Writes in the background: the handlers never wait for it."""

    async def __call__(self, handler, event, data):
        if isinstance(event, Message) and event.chat is not None \
                and event.chat.type in ("group", "supergroup"):
            _spawn(record(event))
        return await handler(event, data)


@router.edited_message(F.chat.type.in_({"group", "supergroup"}))
async def on_edit(message: Message):
    await record_edit(message)


# ───────────────────────── o'qish ─────────────────────────

async def posts(limit: int = 20) -> list[dict]:
    """Oxirgi postlar va har biridagi izohlar soni, yangisi birinchi."""
    if database.pool is None:
        return []
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        rows = await conn.fetch(
            """SELECT p.chat_id, p.thread_id, p.channel_message_id, p.text, p.created_at,
                      COUNT(c.id) AS comments, COUNT(DISTINCT c.user_id) AS people
               FROM channel_comment_posts p
               LEFT JOIN channel_comments c ON c.chat_id = p.chat_id AND c.thread_id = p.thread_id
               GROUP BY p.chat_id, p.thread_id
               ORDER BY p.created_at DESC
               LIMIT $1""", limit)
    return [dict(r) for r in rows]


async def comments(thread_id: int | None = None, days: int | None = None,
                   limit: int = 2000) -> list[dict]:
    """Izohlar, eskisi birinchi: bitta post (thread_id) yoki oxirgi `days` kun."""
    if database.pool is None:
        return []
    where, args = [], []
    if thread_id is not None:
        args.append(thread_id)
        where.append(f"thread_id = ${len(args)}")
    if days:
        args.append(timedelta(days=days))
        where.append(f"created_at >= (NOW() AT TIME ZONE 'UTC') - ${len(args)}::interval")
    args.append(limit)
    sql = ("SELECT id, chat_id, message_id, thread_id, reply_to_message_id, user_id, username, "
           "full_name, kind, text, created_at, edited_at FROM channel_comments"
           + (" WHERE " + " AND ".join(where) if where else "")
           + f" ORDER BY id LIMIT ${len(args)}")
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        rows = await conn.fetch(sql, *args)
    return [dict(r) for r in rows]


def _when(ts) -> str:
    return (ts + timedelta(hours=5)).strftime("%d.%m %H:%M") if ts else "—"


def _short(text: str, n: int = 70) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[:n - 1] + "…"


def comments_file(post: dict | None, rows: list[dict]) -> str:
    """Bitta postning izohlari — oddiy matn fayl (Toshkent vaqti)."""
    head = []
    if post:
        head = [f"Post ({_when(post.get('created_at'))}): {' '.join((post.get('text') or '').split())}", ""]
    lines = head + [f"Izohlar: {len(rows)} ta, {len({r['user_id'] for r in rows})} kishi", ""]
    for r in rows:
        who = r.get("full_name") or "—"
        if r.get("username"):
            who += f" (@{r['username']})"
        kind = "" if r.get("kind") == "text" else f"[{r['kind']}] "
        lines.append(f"— {_when(r.get('created_at'))} · {who} · id {r.get('user_id')}")
        lines.append(kind + (r.get("text") or ""))
        lines.append("")
    return "\n".join(lines)


@router.message(Command("kanal_izohlar"))
async def cmd_channel_comments(message: Message, command: CommandObject):
    """/kanal_izohlar — oxirgi postlar; /kanal_izohlar N — N-postning hamma izohlari fayl qilib."""
    from config import ADMIN_IDS
    if message.chat.type != "private" or message.from_user.id not in ADMIN_IDS:
        return
    items = await posts(15)
    if not items:
        await message.answer("💬 Hali saqlangan kanal izohi yo'q — yangi izohlar shu paytdan yozila boshlaydi.")
        return
    arg = (command.args or "").strip()
    if arg.isdigit() and 1 <= int(arg) <= len(items):
        post = items[int(arg) - 1]
        rows = await comments(thread_id=post["thread_id"])
        data = comments_file(post, rows).encode("utf-8")
        await message.answer_document(
            BufferedInputFile(data, f"kanal_izohlar_{post['thread_id']}.txt"),
            caption=f"💬 {html.escape(_short(post.get('text') or '', 60))} — {len(rows)} ta izoh")
        return
    lines = ["💬 <b>Kanal postlari va izohlar</b> (yangisi tepada)", ""]
    for i, p in enumerate(items, 1):
        lines.append(f"{i}. {_when(p['created_at'])} — <b>{p['comments']}</b> izoh, {p['people']} kishi\n"
                     f"    {html.escape(_short(p.get('text') or '(matnsiz post)'))}")
    lines += ["", "Hammasini fayl qilib olish: /kanal_izohlar 1 (raqam — ro'yxatdagi post)"]
    await message.answer("\n".join(lines), parse_mode="HTML")
