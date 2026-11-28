"""Saytdagi mahsulot rasmlari — yengil nusxa, oldindan tayyor.

Egasi, 2026-11-28: "nega sayt rasmlari sekin ochilyapti? juda sekin, bizni
interneti yaxshi ishlamaydigan mijozlarimiz qiynalishadiku? ... tayyor ochilgan
holatda bo'lishi kerak".

O'lchanganda (28.11):
  * admin paneldan yuklangan rasmlar (/img/N) asl holida berilardi — PNG
    2,4–2,7 MB, JPEG ~300 KB, kichkina katalog kartochkasi uchun;
  * Telegram rasmlari (/api/photo/<file_id>) har ko'rishda Telegram'dan
    qaytadan to'liq yuklab olinib uzatilardi — har biri 1–1,5 s, 70–270 KB,
    brauzer keshi 30 daqiqa.

Endi Mini App rasmni /p/<tg|img>/<ref> dan oladi:
  * MAX_SIDE px gacha kichraytirilgan JPEG (odatda 25–60 KB);
  * bir marta tayyorlanadi va bazada saqlanadi (photo_thumbs), xotirada ham
    turadi — keyingi so'rov darhol;
  * brauzerga "1 yil saqlab qo'y" deyiladi (rasm manzili o'zgarmas: Telegram
    file_id va /img/N almashmaydi — yangi rasm yangi manzil oladi);
  * warm_loop har 20 daqiqada sotuvdagi hamma mahsulot va to'plam rasmlarini
    oldindan tayyorlab qo'yadi — birinchi mijoz ham kutmaydi.

Nimadir o'xshamasa (Pillow yo'q, rasm buzuq, Telegram javob bermadi) — eski
manzilga yo'naltiriladi, rasm baribir chiqadi.
"""
from __future__ import annotations

import asyncio
import io
import logging
import re
from collections import OrderedDict

from aiohttp import web

import database

logger = logging.getLogger(__name__)

MAX_SIDE = 640           # 2 ustunli katalog va mahsulot oynasi uchun yetarli
QUALITY = 74
MEM_MAX = 400            # xotirada nechta rasm (~40 KB dan — ~16 MB)
CACHE_HEADER = "public, max-age=31536000, immutable"
WARM_EVERY = 20 * 60

_TG_REF = re.compile(r"^[A-Za-z0-9_-]{10,200}$")
_mem: "OrderedDict[str, tuple[bytes, str]]" = OrderedDict()
_locks: dict[str, asyncio.Lock] = {}
_gen = asyncio.Semaphore(2)          # rasm siqish CPU oladi — ko'pi bilan 2 ta parallel
_table_ready = False


def url_for(ref) -> str | None:
    """photo_url uchun: Telegram file_id → /p/tg/<id>, /img/N → /p/img/N,
    tashqi https havola — o'zi."""
    if not ref:
        return None
    ref = str(ref).strip()
    if ref.startswith("/img/"):
        num = ref[5:].split("?")[0]
        return f"/p/img/{num}" if num.isdigit() else ref
    if ref.startswith(("/", "http://", "https://")):
        return ref
    return f"/p/tg/{ref}" if _TG_REF.match(ref) else f"/api/photo/{ref}"


def _fallback(kind: str, ref: str) -> str:
    return f"/img/{ref}" if kind == "img" else f"/api/photo/{ref}"


async def _ensure(conn) -> None:
    global _table_ready
    if _table_ready:
        return
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS photo_thumbs (
            key TEXT PRIMARY KEY,
            data BYTEA NOT NULL,
            content_type TEXT NOT NULL DEFAULT 'image/jpeg',
            created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
        )
    """)
    _table_ready = True


def shrink(raw: bytes) -> bytes:
    """Asl rasm → MAX_SIDE px gacha JPEG. Shaffof PNG oq fonga qo'yiladi."""
    from PIL import Image, ImageOps
    im = Image.open(io.BytesIO(raw))
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[-1])
        im = bg
    else:
        im = im.convert("RGB")
    im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, "JPEG", quality=QUALITY, optimize=True, progressive=True)
    return out.getvalue()


async def _original(bot, kind: str, ref: str) -> bytes | None:
    if kind == "img":
        row = await database.get_web_image(int(ref))
        return bytes(row["data"]) if row else None
    if bot is None:
        return None
    buf = io.BytesIO()
    file = await bot.get_file(ref)
    await bot.download_file(file.file_path, destination=buf)
    return buf.getvalue()


def _remember(key: str, value: tuple[bytes, str]) -> None:
    _mem[key] = value
    _mem.move_to_end(key)
    while len(_mem) > MEM_MAX:
        _mem.popitem(last=False)


async def get(bot, kind: str, ref: str) -> tuple[bytes, str] | None:
    """Tayyor nusxa: xotira → baza → (bir marta) yasash. None — yasab bo'lmadi."""
    key = f"{kind}:{ref}"
    hit = _mem.get(key)
    if hit:
        _mem.move_to_end(key)
        return hit
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _mem.get(key)
        if hit:
            return hit
        if database.pool is None:
            return None
        async with database.pool.acquire() as conn:
            await _ensure(conn)
            row = await conn.fetchrow("SELECT data, content_type FROM photo_thumbs WHERE key = $1", key)
        if row:
            value = (bytes(row["data"]), row["content_type"])
            _remember(key, value)
            return value
        try:
            raw = await _original(bot, kind, ref)
            if not raw:
                return None
            async with _gen:
                small = await asyncio.get_running_loop().run_in_executor(None, shrink, raw)
        except Exception:
            logger.warning("Thumbnail for %s failed", key, exc_info=True)
            return None
        # Asl rasm allaqachon kichik bo'lsa — kattaroq nusxa saqlanmaydi.
        data = small if len(small) < len(raw) else raw
        ctype = "image/jpeg" if data is small else _sniff(raw)
        async with database.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO photo_thumbs (key, data, content_type) VALUES ($1, $2, $3) "
                "ON CONFLICT (key) DO NOTHING", key, data, ctype)
        value = (data, ctype)
        _remember(key, value)
        _locks.pop(key, None)
        return value


def _sniff(raw: bytes) -> str:
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


async def serve(request: web.Request) -> web.StreamResponse:
    """GET /p/{kind}/{ref} — public, like /img and /api/photo."""
    kind, ref = request.match_info["kind"], request.match_info["ref"]
    if kind not in ("tg", "img") or (kind == "img" and not ref.isdigit()) \
            or (kind == "tg" and not _TG_REF.match(ref)):
        raise web.HTTPNotFound
    found = await get(request.app.get("bot"), kind, ref)
    if not found:
        raise web.HTTPFound(_fallback(kind, ref))
    data, ctype = found
    return web.Response(body=data, content_type=ctype, headers={"Cache-Control": CACHE_HEADER})


def setup(app: web.Application) -> None:
    app.router.add_get("/p/{kind}/{ref}", serve)


# ───────────────────────── oldindan tayyorlash ─────────────────────────

def _split(ref) -> tuple[str, str] | None:
    url = url_for(ref)
    if not url or not url.startswith("/p/"):
        return None
    _, _, kind, rest = url.split("/", 3)
    return kind, rest


async def refs_to_warm() -> list[tuple[str, str]]:
    """Sotuvdagi mahsulotlar, to'plamlar va retseptlarning rasmlari."""
    queries = [
        "SELECT COALESCE(NULLIF(image_url, ''), photo_id) AS ref FROM products WHERE is_active = 1",
        "SELECT image_url AS ref FROM product_sets WHERE COALESCE(is_active, 1) = 1",
    ]
    refs: list[tuple[str, str]] = []
    async with database.pool.acquire() as conn:
        for sql in queries:
            try:
                rows = await conn.fetch(sql)
            except Exception:
                continue
            for r in rows:
                pair = _split(r["ref"])
                if pair and pair not in refs:
                    refs.append(pair)
    return refs


async def warm(bot) -> int:
    """Hali tayyor bo'lmaganlarini birma-bir tayyorlaydi. Nechtasi yangi bo'ldi."""
    made = 0
    for kind, ref in await refs_to_warm():
        key = f"{kind}:{ref}"
        if key in _mem:
            continue
        async with database.pool.acquire() as conn:
            await _ensure(conn)
            exists = await conn.fetchval("SELECT 1 FROM photo_thumbs WHERE key = $1", key)
        if exists:
            continue
        if await get(bot, kind, ref):
            made += 1
        await asyncio.sleep(0.3)          # Telegram va CPU ga yumshoq
    return made


async def warm_loop(bot) -> None:
    await asyncio.sleep(45)
    while True:
        try:
            made = await warm(bot)
            if made:
                logger.info("Photo thumbs: %d made ready", made)
        except Exception:
            logger.exception("photo thumbs warm failed")
        await asyncio.sleep(WARM_EVERY)
