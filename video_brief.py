"""Reels/video mazmuni — AI videoga oid izohlarga aniq javob bersin (egasi, 2026-11-28:
"bazilar postdagi video bo'yicha savol berishgan bo'lsa ularga qanday javob bersak bo'ladi"
→ "Video tahlilini boshlaymi? — Ha").

Bir video — bir marta (video_brief jadvali, media_id bo'yicha; egasi: hech narsani o'chirma):
  1. video yuklanadi (MAX_BYTES gacha);
  2. ffmpeg: ovozi (mono 16 kHz) va FRAMES ta kadr (videoning 10–85 % joylaridan);
  3. ovoz matnga (TRANSCRIBE_MODEL, zaxira — whisper-1);
  4. kadrlar + ovoz matni + post matnidan qisqa o'zbekcha mazmun (SUMMARY_MODEL).
Natija izoh AI'ga "VIDEO MAZMUNI" bo'lib beriladi (meta_comments.post_context). ffmpeg yo'q,
video ochilmadi yoki AI xato bersa — bo'sh: AI avvalgidek post matni va muqova bilan ishlaydi.
Muvaffaqiyatsiz urinish FAIL_RETRY_HOURS dan keyin qayta sinaladi.
"""
from __future__ import annotations

import asyncio
import base64
import logging
import os
import shutil
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import database

logger = logging.getLogger(__name__)

MAX_BYTES = 80 * 1024 * 1024
FRAMES = 4
TRANSCRIBE_MODEL = os.getenv("VIDEO_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe").strip()
SUMMARY_MODEL = os.getenv("VIDEO_SUMMARY_MODEL", "gpt-5.4-mini").strip()
TRANSCRIBE_PER_MIN = 0.003          # $ / daqiqa (taxminiy, sarf hisobi uchun)
FAIL_RETRY_HOURS = 24
USAGE_TAG = " · video"

SUMMARY_RULES = (
    "Bu Keto shop (keto, PP, glyutensiz, qandsiz mahsulotlar do'koni) Instagram reels videosi: bir nechta "
    "kadr, ovozning matni va post matni berilgan. O'zbekcha 3–6 gapda mazmunini yoz: videoda nima "
    "ko'rsatiladi va nima deyiladi, qaysi mahsulotlar (nomi, og'irligi), retsept bo'lsa — masalliq va "
    "asosiy qadamlar, aytilgan narx, va'da yoki maslahat. Faqat videoda bor narsani yoz, to'qima. "
    "Odamlarning shaxsi haqida yozma.")

_table_ready = False
_locks: dict[str, asyncio.Lock] = {}


async def _ensure(conn) -> None:
    global _table_ready
    if _table_ready:
        return
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS video_brief (
            media_id TEXT PRIMARY KEY,
            summary TEXT NOT NULL DEFAULT '',
            transcript TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'ok',
            created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
        )
    """)
    _table_ready = True


async def _stored(media_id: str) -> dict | None:
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        row = await conn.fetchrow("SELECT summary, status, created_at FROM video_brief WHERE media_id = $1",
                                  media_id)
    return dict(row) if row else None


async def _save(media_id: str, summary: str, transcript: str, status: str) -> None:
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        await conn.execute(
            "INSERT INTO video_brief (media_id, summary, transcript, status) VALUES ($1, $2, $3, $4) "
            "ON CONFLICT (media_id) DO UPDATE SET summary = $2, transcript = $3, status = $4, "
            "created_at = NOW() AT TIME ZONE 'UTC'", media_id, summary, transcript, status)


async def _run(*args: str, timeout: float = 120) -> tuple[int, bytes]:
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE)
    try:
        out, _err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return -1, b""
    return proc.returncode, out


async def _download(url: str, path: Path) -> bool:
    import aiohttp
    size = 0
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=180)) as s:
        async with s.get(url) as r:
            if r.status != 200:
                return False
            with open(path, "wb") as f:
                async for chunk in r.content.iter_chunked(1 << 16):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        return False
                    f.write(chunk)
    return size > 0


async def _duration(path: Path) -> float:
    code, out = await _run("ffprobe", "-v", "error", "-show_entries", "format=duration",
                           "-of", "default=nw=1:nk=1", str(path), timeout=30)
    try:
        return float(out.decode().strip()) if code == 0 else 0.0
    except ValueError:
        return 0.0


async def extract(video: Path, workdir: Path) -> tuple[Path | None, list[Path], float]:
    """(ovoz fayli yoki None, kadrlar, davomiylik soniyada)."""
    seconds = await _duration(video)
    audio = workdir / "audio.mp3"
    code, _ = await _run("ffmpeg", "-y", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
                         "-b:a", "32k", str(audio))
    frames = []
    points = [0.10, 0.35, 0.60, 0.85][:FRAMES] if seconds > 0 else [0.0]
    for i, share in enumerate(points):
        out = workdir / f"f{i}.jpg"
        rc, _ = await _run("ffmpeg", "-y", "-v", "error", "-ss", f"{seconds * share:.2f}", "-i", str(video),
                           "-frames:v", "1", "-vf", "scale=512:-2", str(out), timeout=60)
        if rc == 0 and out.exists() and out.stat().st_size:
            frames.append(out)
    return (audio if code == 0 and audio.exists() and audio.stat().st_size else None), frames, seconds


async def _transcribe(client, audio: Path, seconds: float) -> str:
    for model in (TRANSCRIBE_MODEL, "whisper-1"):
        try:
            with open(audio, "rb") as f:
                resp = await client.audio.transcriptions.create(model=model, file=f)
        except Exception as exc:
            logger.info("video transcribe (%s) failed: %s", model, exc)
            continue
        try:
            await database.record_ai_usage(model + USAGE_TAG, "openai", 0, 0, 0,
                                           round(seconds / 60 * TRANSCRIBE_PER_MIN, 6))
        except Exception:
            logger.debug("transcribe usage not recorded", exc_info=True)
        return (getattr(resp, "text", "") or "").strip()
    return ""


async def _summarise(client, frames: list[Path], transcript: str, caption: str) -> str:
    content = [{"type": "input_text", "text": f"POST MATNI:\n{caption[:1500] or '—'}\n\n"
                                              f"OVOZ MATNI:\n{transcript[:6000] or '— (ovoz yo‘q yoki tushunarsiz)'}"}]
    for p in frames:
        content.append({"type": "input_image", "detail": "low",
                        "image_url": "data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode()})
    try:
        resp = await client.responses.create(model=SUMMARY_MODEL, instructions=SUMMARY_RULES,
                                             input=[{"role": "user", "content": content}],
                                             reasoning={"effort": "low"}, max_output_tokens=1200)
    except Exception as exc:
        logger.info("video summary failed: %s", exc)
        return ""
    try:
        import ai_provider
        u = ai_provider._openai_usage(getattr(resp, "usage", None))
        await database.record_ai_usage(SUMMARY_MODEL + USAGE_TAG, "openai", u.input, u.cached, u.output,
                                       ai_provider.estimate_cost(SUMMARY_MODEL, u.input, u.cached, u.output))
    except Exception:
        logger.debug("video summary usage not recorded", exc_info=True)
    return (getattr(resp, "output_text", "") or "").strip()[:1500]


async def brief(media_id: str, video_url: str, caption: str = "") -> str:
    """Videoning qisqa mazmuni (bazada bo'lsa — o'sha) yoki ''. Hech qachon xato ko'tarmaydi."""
    if not media_id or not video_url:
        return ""
    lock = _locks.setdefault(media_id, asyncio.Lock())
    async with lock:
        try:
            got = await _stored(media_id)
        except Exception:
            logger.warning("video_brief read failed", exc_info=True)
            return ""
        if got and got["status"] == "ok":
            return got["summary"]
        if got and datetime.utcnow() - got["created_at"] < timedelta(hours=FAIL_RETRY_HOURS):
            return ""
        if not shutil.which("ffmpeg"):
            return ""
        summary, transcript = "", ""
        try:
            import comment_ai
            import openai
            key = await comment_ai._openai_key()
            if not key:
                return ""
            client = openai.AsyncOpenAI(api_key=key, timeout=180.0, max_retries=1)
            with tempfile.TemporaryDirectory(prefix="vb_") as tmp:
                work = Path(tmp)
                video = work / "v.mp4"
                if await _download(video_url, video):
                    audio, frames, seconds = await extract(video, work)
                    if audio is not None:
                        transcript = await _transcribe(client, audio, seconds)
                    if frames or transcript:
                        summary = await _summarise(client, frames, transcript, caption)
        except Exception:
            logger.warning("video brief failed for %s", media_id, exc_info=True)
        try:
            await _save(media_id, summary, transcript, "ok" if summary else "failed")
        except Exception:
            logger.warning("video_brief write failed", exc_info=True)
        return summary
