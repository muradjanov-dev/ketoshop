"""Mijoz qaysi post yoki xabarga reply qilib yozganini AI biladi (egasi, 2026-11-27: "mijozlar
biror postni reply qilib yoki izoh qilib yozishsa AI buni bilmayapti va umumiy savol deb
o'ylayapti ... rasmni ham, videoni ham o'qiy oladigan qila olamizmi?").

reply_block(bot, message) — model uchun bitta qator kontekst yoki "":
  * kimning xabari: kanal posti, botning o'z xabari (kun mahsuloti, retsept...), boshqa odam;
  * matni yoki izohi (caption), mijoz belgilagan iqtibos (quote);
  * RASM — kichik vision model tavsifi: qaysi mahsulot, yozuvlar, narx, taom;
  * VIDEO / GIF / dumaloq video — Telegram bergan muqova kadri tavsifi + davomiyligi (serverda
    ffmpeg yo'q, to'liq video o'qilmaydi; matn va muqova odatda yetadi).
Boshqa chatdagi postga reply (external_reply) ham shu yo'l bilan.

Tavsif bir rasmga bir marta qilinadi: media_desc jadvalida file_unique_id bo'yicha saqlanadi
(egasi: hech narsani o'chirma). Xato bo'lsa — rasmsiz, faqat matn bilan; javob to'xtamaydi.
"""
from __future__ import annotations

import base64
import io
import logging
import os

import database

logger = logging.getLogger(__name__)

VISION_MODEL = os.getenv("AI_VISION_MODEL", "gpt-5.4-mini").strip()
USAGE_TAG = " · rasm"
TEXT_MAX = 700
MAX_SIDE = 1280
DESCRIBE_RULES = (
    "Bu Keto shop (keto, PP, glyutensiz, qandsiz mahsulotlar do'koni) Telegram postidagi rasm yoki "
    "video muqovasi. O'zbekcha, 1-3 gapda qisqa tasvirla: qaysi mahsulot(lar) — qadoqdagi nomi va "
    "og'irligi, rasmda yozilgan narx yoki matn, qanday taom yoki pishiriq. Ko'rinmagan narsani "
    "to'qima. Odamlarning yuzi yoki shaxsi haqida yozma.")

_cache: dict[str, str] = {}
_table_ready = False


async def _ensure(conn) -> None:
    global _table_ready
    if _table_ready:
        return
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS media_desc (
            file_unique_id TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
        )
    """)
    _table_ready = True


def _short(text, limit: int = TEXT_MAX) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _best_photo(sizes):
    if not sizes:
        return None
    fitting = [p for p in sizes if max(p.width or 0, p.height or 0) <= MAX_SIDE]
    return (fitting or list(sizes))[-1]


def media_of(msg) -> tuple[str, object | None, int | None]:
    """(turi, rasm sifatida o'qiladigan fayl, davomiylik soniyada)."""
    if msg is None:
        return "", None, None
    if getattr(msg, "photo", None):
        return "rasm", _best_photo(msg.photo), None
    for attr, label in (("video", "video"), ("animation", "GIF/animatsiya"), ("video_note", "dumaloq video")):
        media = getattr(msg, attr, None)
        if media:
            return label, getattr(media, "thumbnail", None), getattr(media, "duration", None)
    doc = getattr(msg, "document", None)
    if doc and (getattr(doc, "mime_type", "") or "").startswith("image/"):
        return "rasm", getattr(doc, "thumbnail", None) or doc, None
    return "", None, None


async def _stored(unique_id: str) -> str | None:
    if unique_id in _cache:
        return _cache[unique_id]
    try:
        async with database.pool.acquire() as conn:
            await _ensure(conn)
            got = await conn.fetchval("SELECT description FROM media_desc WHERE file_unique_id = $1", unique_id)
    except Exception:
        logger.debug("media_desc read failed", exc_info=True)
        return None
    if got:
        _cache[unique_id] = got
    return got


async def _save(unique_id: str, text: str) -> None:
    _cache[unique_id] = text
    try:
        async with database.pool.acquire() as conn:
            await _ensure(conn)
            await conn.execute("INSERT INTO media_desc (file_unique_id, description) VALUES ($1, $2) "
                               "ON CONFLICT (file_unique_id) DO NOTHING", unique_id, text)
    except Exception:
        logger.debug("media_desc write failed", exc_info=True)


async def _vision(image: bytes, hint: str) -> str | None:
    import comment_ai
    import openai
    key = await comment_ai._openai_key()
    if not key:
        return None
    data_url = "data:image/jpeg;base64," + base64.b64encode(image).decode()
    content = [{"type": "input_image", "image_url": data_url}]
    if hint:
        content.insert(0, {"type": "input_text", "text": f"Post matni (yordam uchun): {hint}"})
    try:
        client = openai.AsyncOpenAI(api_key=key, timeout=40.0, max_retries=1)
        resp = await client.responses.create(model=VISION_MODEL, instructions=DESCRIBE_RULES,
                                             input=[{"role": "user", "content": content}],
                                             reasoning={"effort": "low"}, max_output_tokens=600)
    except Exception as exc:
        logger.info("post image describe failed: %s", exc)
        return None
    try:
        import ai_provider
        u = ai_provider._openai_usage(getattr(resp, "usage", None))
        await database.record_ai_usage(VISION_MODEL + USAGE_TAG, "openai", u.input, u.cached, u.output,
                                       ai_provider.estimate_cost(VISION_MODEL, u.input, u.cached, u.output))
    except Exception:
        logger.debug("vision usage not recorded", exc_info=True)
    return _short(getattr(resp, "output_text", "") or "", 500) or None


async def describe(bot, file, hint: str = "") -> str | None:
    """Rasm yoki video muqovasi tavsifi (bazada saqlangani bo'lsa — o'sha)."""
    unique_id = getattr(file, "file_unique_id", None)
    if not unique_id:
        return None
    got = await _stored(unique_id)
    if got:
        return got
    try:
        buf = io.BytesIO()
        await bot.download(file.file_id, destination=buf)
        image = buf.getvalue()
    except Exception:
        logger.info("post image download failed", exc_info=True)
        return None
    if not image:
        return None
    text = await _vision(image, hint)
    if text:
        await _save(unique_id, text)
    return text


def _who(msg, bot_id) -> str:
    chat = getattr(msg, "sender_chat", None)
    if getattr(msg, "is_automatic_forward", False) or (chat and getattr(chat, "type", "") == "channel"):
        title = getattr(chat, "title", None)
        return f"kanal posti ({title})" if title else "kanal posti"
    user = getattr(msg, "from_user", None)
    if user and getattr(user, "is_bot", False) and (bot_id is None or user.id == bot_id):
        return "bizning (do'kon botining) xabarimiz"
    return "boshqa odamning xabari" if user else "xabar"


def _duration(seconds) -> str:
    if not seconds:
        return ""
    return f" ({int(seconds) // 60}:{int(seconds) % 60:02d})"


async def reply_block(bot, message, lead: str | None = None) -> str:
    """Mijoz reply qilgan post yoki xabar haqida model uchun bitta blok, yoki ""."""
    src = getattr(message, "reply_to_message", None)
    ext = getattr(message, "external_reply", None)
    quote = getattr(message, "quote", None)
    if src is None and ext is None:
        return ""
    bot_id = getattr(bot, "id", None)
    if src is not None:
        who = _who(src, bot_id)
        text = getattr(src, "text", None) or getattr(src, "caption", None) or ""
        kind, file, seconds = media_of(src)
    else:
        origin = getattr(ext, "origin", None)
        chat = getattr(origin, "chat", None)
        title = getattr(chat, "title", None)
        who = f"boshqa chatdagi post ({title})" if title else "boshqa chatdagi post"
        text = ""
        kind, file, seconds = media_of(ext)
    parts = [lead or f"MIJOZ SHU XABARGA REPLY QILIB YOZDI — savol shu haqida, umumiy emas: {who}"]
    if kind:
        parts.append(f"{kind}{_duration(seconds)}")
    if quote is not None and getattr(quote, "text", None):
        parts.append(f"mijoz belgilagan joy: «{_short(quote.text, 300)}»")
    if text:
        parts.append(f"matni: «{_short(text)}»")
    if file is not None:
        seen = await describe(bot, file, _short(text, 300))
        if seen:
            parts.append(("videoning muqovasida: " if kind != "rasm" else "rasmda: ") + seen)
    if len(parts) == 1:
        return ""
    return "[" + " · ".join(parts) + "]"
