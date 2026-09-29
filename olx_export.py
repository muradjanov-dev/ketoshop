"""
OLX — hamma mahsulotni rasmi bilan OLX.uz ga chiqarish (2026-09-29).

Egasining so'rovi: "barcha mahsulotlarimni OLX ga rasmi bilan yuklab
beradigan tizim, eng sodda va samarali uslubda".

Ikki qavat, ikkalasi ham bitta manbadan — do'kondagi mahsulot kartochkasidan:

1. /olx — OLX PAKETI (kalit kerak emas, bugunoq ishlaydi).
   Bot har bir faol mahsulot uchun papka yig'adi: rasmlar (1.jpg, 2.jpg …)
   va elon.txt (sarlavha ≤70 belgi, narx, uz + ru tavsif). Hammasi ZIP bo'lib
   admin chatiga keladi, yoniga olx_elonlar.csv. Telefondan joylash uchun
   /olx <id> — bitta mahsulotning rasmlari albom bo'lib, ostidan nusxa
   olinadigan matn keladi: saqla → OLX ilovasiga qo'y, bir daqiqa.

2. /olx_joyla — AVTOPILOT (OLX Partner API, kalitlar env'da bo'lsa).
   Yangi mahsulot → e'lon yaratiladi, bor e'lon → narx/matn yangilanadi,
   tugagan yoki o'chirilgan mahsulot → e'lon to'xtatiladi. Takror bosish
   xavfsiz: qaysi mahsulot qaysi e'longa tegishli ekanini olx_adverts
   jadvali eslab turadi. Avval faqat reja ko'rsatiladi; OLX'ga haqiqatan
   yuborish uchun "/olx_joyla tasdiq" yoziladi — e'lon tashqi, ommaviy
   narsa, tasodifan chiqib ketmasin.

   Kerakli env:
     OLX_CLIENT_ID, OLX_CLIENT_SECRET, OLX_REFRESH_TOKEN — developer.olx.uz
       ilovasidan (refresh token har yangilanganda OLX yangisini beradi,
       shuning uchun oxirgisi bazada saqlanadi, env faqat birinchi marta).
     OLX_CATEGORY_ID — oziq-ovqat kategoriyasi raqami (OLX /categories).
     OLX_CITY_ID     — Toshkent shahri raqami (OLX /cities).
     OLX_CONTACT_NAME (ixtiyoriy, "Ketoshop"), OLX_ATTRIBUTES (ixtiyoriy
       JSON, kategoriya majburiy atributlari, masalan
       [{"code":"state","value":"new"}]).

Rasmlar OLX'ga URL bilan beriladi — bizning server ularni allaqachon ochiq
tarqatadi: Telegram rasmi /api/photo/{file_id}, saytdan yuklangani /img/{id}.
"""
import asyncio
import csv
import io
import json
import logging
import os
import re
import time
import zipfile
from datetime import datetime
from urllib.parse import urlsplit

import aiohttp
from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, InputMediaPhoto, Message

import database
from config import ADMIN_IDS, FREE_DELIVERY_FROM, SUPPORT_PHONES, WEBAPP_URL

logger = logging.getLogger(__name__)
router = Router()

TITLE_MIN, TITLE_MAX = 16, 70          # OLX sarlavha chegarasi
DESC_MIN, DESC_MAX = 80, 9000          # OLX tavsif chegarasi
MAX_PHOTOS = 8                         # OLX bitta e'longa 8 tagacha rasm oladi
ZIP_PART_LIMIT = 45 * 1024 * 1024      # Telegram bot hujjati ≤50 MB

OLX_BASE = "https://www.olx.uz"
OLX_API = f"{OLX_BASE}/api/partner"
OLX_TOKEN_URL = f"{OLX_BASE}/api/open/oauth/token"


# ─────────────────────────────── matn ───────────────────────────────────────

def _money(value: float) -> str:
    return f"{int(round(value)):,}".replace(",", " ")


def price_of(product: dict) -> int:
    """Xaridor hozir to'laydigan narx — amaldagi chegirma bilan."""
    return int(round(database.effective_price(
        float(product.get("price") or 0),
        product.get("discount_percent"),
        product.get("discount_until"),
    )))


def olx_title(product: dict) -> str:
    """16–70 belgi. Qisqa nom ("Eritritol 100gr") "keto" so'zi bilan to'ldiriladi —
    OLX qidiruvida odamlar aynan shuni yozadi."""
    name = re.sub(r"\s+", " ", (product.get("name") or "").strip())
    title = name
    if "keto" not in name.lower():
        title = f"{name} — keto mahsulot"
    if len(title) < TITLE_MIN:
        title = f"{title}, Toshkent"
    if len(title) > TITLE_MAX:
        title = (name if len(name) <= TITLE_MAX else name[:TITLE_MAX - 1].rstrip() + "…")
    return title


def _descriptions(product: dict) -> tuple[str, str]:
    uz = (product.get("description") or "").strip()
    ru = (product.get("description_ru") or "").strip()
    if not uz or not ru:
        from product_descriptions import describe
        lib_uz, lib_ru, _ = describe(product.get("name") or "")
        uz, ru = uz or lib_uz, ru or lib_ru
    return uz, ru


def _phones() -> str:
    return ", ".join(p.strip() for p in SUPPORT_PHONES.split(",") if p.strip())


def olx_description(product: dict) -> str:
    uz, ru = _descriptions(product)
    unit = (product.get("unit") or "").strip()
    price_line = f"Narxi: {_money(price_of(product))} so'm" + (f" / {unit}" if unit and unit != "dona" else "")
    parts = [
        f"{product.get('name', '').strip()} — Ketoshop'dan, original qadoqda.",
        uz,
        price_line,
        "🚚 Toshkent bo'ylab kuryer, viloyatlarga pochta orqali yetkazamiz. "
        f"{_money(FREE_DELIVERY_FROM)} so'mdan yuqori buyurtmaga Toshkentda yetkazish bepul.",
        f"📞 {_phones()}",
        "— — —",
        ru,
        f"Цена: {_money(price_of(product))} сум. Доставка по Ташкенту курьером, по регионам — почтой.",
    ]
    text = "\n\n".join(p for p in parts if p)
    # OLX tavsifida HTML yo'q; bizning matnlarda <b> bo'lishi mumkin.
    text = re.sub(r"<[^>]+>", "", text)
    if len(text) < DESC_MIN:
        text += "\n\nKeto va past uglevodli ovqatlanish uchun sifatli mahsulot."
    return text[:DESC_MAX]


def ad_text(product: dict) -> str:
    """Qo'lda joylash uchun nusxa olinadigan to'liq e'lon."""
    return (f"SARLAVHA:\n{olx_title(product)}\n\n"
            f"NARX: {price_of(product)} so'm\n\n"
            f"TAVSIF:\n{olx_description(product)}")


# ─────────────────────────────── rasmlar ────────────────────────────────────

async def photo_refs(product: dict) -> list[str]:
    """Mahsulot rasmlari tartib bilan, takrorsiz: asosiy rasm, keyin galereya.
    Har biri Telegram file_id, "/img/N" yoki to'liq http URL."""
    refs: list[str] = []
    for ref in (product.get("image_url"), product.get("photo_id")):
        if ref and ref not in refs:
            refs.append(ref)
    try:
        for m in await database.get_product_media(product["id"]):
            if (m.get("media_type") or "photo") == "photo" and m.get("file_id") not in refs:
                refs.append(m["file_id"])
    except Exception:
        logger.exception("olx: galereyani o'qib bo'lmadi, product=%s", product.get("id"))
    return refs[:MAX_PHOTOS]


def _public_base() -> str:
    parts = urlsplit(WEBAPP_URL)
    return f"{parts.scheme}://{parts.netloc}" if parts.netloc else ""


def public_url(ref: str) -> str | None:
    """OLX o'zi yuklab oladigan ochiq URL."""
    if ref.startswith("http"):
        return ref
    base = _public_base()
    if not base:
        return None
    if ref.startswith("/"):
        return base + ref
    return f"{base}/api/photo/{ref}"


async def fetch_photo(bot: Bot, ref: str, session: aiohttp.ClientSession) -> bytes | None:
    try:
        m = re.fullmatch(r"/img/(\d+)", ref)
        if m:
            row = await database.get_web_image(int(m.group(1)))
            return bytes(row["data"]) if row else None
        if ref.startswith("http"):
            async with session.get(ref) as resp:
                return await resp.read() if resp.status == 200 else None
        buf = io.BytesIO()
        await bot.download(ref, destination=buf)
        return buf.getvalue()
    except Exception:
        logger.warning("olx: rasm olinmadi %s", ref[:40], exc_info=True)
        return None


async def olx_products() -> list[dict]:
    """Faol, B2B'ga tegishli bo'lmagan mahsulotlar — OLX'ga chiqadiganlari."""
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT * FROM products
               WHERE is_active = 1 AND (b2b_only IS NOT TRUE) AND quantity > 0
               ORDER BY LOWER(name), id""")
    return [dict(r) for r in rows]


def _slug(text: str) -> str:
    return re.sub(r"[^\w\-]+", "_", text, flags=re.UNICODE).strip("_")[:40] or "mahsulot"


# ─────────────────────────────── /olx paket ─────────────────────────────────

async def build_pack(bot: Bot) -> tuple[list[bytes], bytes, int, int]:
    """(ZIP qismlari, CSV, mahsulotlar soni, rasmlar soni)."""
    products = await olx_products()
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    writer.writerow(["id", "papka", "sarlavha", "narx_som", "rasmlar", "tavsif"])

    parts: list[bytes] = []
    zbuf = io.BytesIO()
    zf = zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED)
    size = 0
    photos_total = 0

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        for n, p in enumerate(products, 1):
            folder = f"{n:03d}_{_slug(p['name'])}"
            files: list[tuple[str, bytes]] = [("elon.txt", ad_text(p).encode("utf-8"))]
            for i, ref in enumerate(await photo_refs(p), 1):
                data = await fetch_photo(bot, ref, session)
                if data:
                    files.append((f"{i}.jpg", data))
            photos = len(files) - 1
            photos_total += photos
            block = sum(len(d) for _, d in files)
            if size and size + block > ZIP_PART_LIMIT:
                zf.close()
                parts.append(zbuf.getvalue())
                zbuf = io.BytesIO()
                zf = zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED)
                size = 0
            for name, data in files:
                zf.writestr(f"{folder}/{name}", data)
            size += block
            writer.writerow([p["id"], folder, olx_title(p), price_of(p), photos, olx_description(p)])

    zf.close()
    parts.append(zbuf.getvalue())
    # Excel o'zbekcha/ruscha harflarni to'g'ri ochishi uchun BOM bilan.
    return parts, csv_buf.getvalue().encode("utf-8-sig"), len(products), photos_total


_pack_lock = asyncio.Lock()


@router.message(Command("olx"), F.from_user.id.in_(ADMIN_IDS), F.chat.type == "private")
async def cmd_olx(message: Message, command: CommandObject, bot: Bot):
    arg = (command.args or "").strip()
    if arg.isdigit():
        await _send_single(message, bot, int(arg))
        return
    if _pack_lock.locked():
        await message.answer("⏳ Paket allaqachon yig'ilyapti, biroz kuting.")
        return
    async with _pack_lock:
        status = await message.answer("📦 OLX paketi yig'ilyapti — rasmlar yuklanmoqda, 1–3 daqiqa…")
        parts, csv_bytes, n_products, n_photos = await build_pack(bot)
        stamp = datetime.now().strftime("%Y-%m-%d")
        for i, data in enumerate(parts, 1):
            suffix = f"_{i}-qism" if len(parts) > 1 else ""
            await message.answer_document(BufferedInputFile(data, f"ketoshop_olx_{stamp}{suffix}.zip"))
        await message.answer_document(
            BufferedInputFile(csv_bytes, f"olx_elonlar_{stamp}.csv"),
            caption=(f"✅ {n_products} ta mahsulot, {n_photos} ta rasm.\n\n"
                     "Har papkada: rasmlar + elon.txt (sarlavha, narx, tavsif).\n"
                     "Telefondan bittalab: /olx <id> — rasm albomi + tayyor matn.\n"
                     "Avtomatik joylash: /olx_joyla"))
        try:
            await status.delete()
        except Exception:
            pass


async def _send_single(message: Message, bot: Bot, product_id: int):
    p = await database.get_product(product_id)
    if not p:
        await message.answer("Bunday mahsulot yo'q.")
        return
    refs = await photo_refs(p)
    album, extra = [], []
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        for i, ref in enumerate(refs, 1):
            if ref.startswith("/") or ref.startswith("http"):
                data = await fetch_photo(bot, ref, session)
                if data:
                    album.append(InputMediaPhoto(media=BufferedInputFile(data, f"{i}.jpg")))
            else:
                album.append(InputMediaPhoto(media=ref))
    if album:
        await message.answer_media_group(album)
    else:
        extra.append("⚠️ Bu mahsulotda rasm yo'q.")
    # Oddiy matn (HTML emas) — nusxa olishda hech narsa buzilmaydi.
    await message.answer(ad_text(p) + ("\n\n" + "\n".join(extra) if extra else ""))


# ─────────────────────────────── OLX API ────────────────────────────────────

def api_configured() -> bool:
    return all(os.getenv(k) for k in ("OLX_CLIENT_ID", "OLX_CLIENT_SECRET", "OLX_CATEGORY_ID", "OLX_CITY_ID"))


async def ensure_schema() -> None:
    async with database.pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS olx_adverts (
                product_id INTEGER PRIMARY KEY,
                advert_id BIGINT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                last_price INTEGER,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS olx_state (
                id INTEGER PRIMARY KEY DEFAULT 1,
                refresh_token TEXT,
                CONSTRAINT olx_state_single CHECK (id = 1)
            )
        """)


class OlxClient:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.token: str | None = None
        self.expires = 0.0

    async def _refresh(self) -> None:
        async with database.pool.acquire() as conn:
            saved = await conn.fetchval("SELECT refresh_token FROM olx_state WHERE id = 1")
        refresh = saved or os.getenv("OLX_REFRESH_TOKEN", "")
        body = {
            "grant_type": "refresh_token",
            "client_id": os.getenv("OLX_CLIENT_ID"),
            "client_secret": os.getenv("OLX_CLIENT_SECRET"),
            "refresh_token": refresh,
        }
        async with self.session.post(OLX_TOKEN_URL, json=body) as resp:
            data = await resp.json(content_type=None)
            if resp.status != 200 or "access_token" not in data:
                raise RuntimeError(f"OLX token: {resp.status} {str(data)[:300]}")
        self.token = data["access_token"]
        self.expires = time.time() + int(data.get("expires_in", 3600)) - 60
        if data.get("refresh_token"):
            async with database.pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO olx_state (id, refresh_token) VALUES (1, $1)
                       ON CONFLICT (id) DO UPDATE SET refresh_token = EXCLUDED.refresh_token""",
                    data["refresh_token"])

    async def call(self, method: str, path: str, body: dict | None = None) -> dict:
        if not self.token or time.time() > self.expires:
            await self._refresh()
        headers = {"Authorization": f"Bearer {self.token}", "Version": "2.0"}
        async with self.session.request(method, OLX_API + path, json=body, headers=headers) as resp:
            data = await resp.json(content_type=None) if resp.content_length != 0 else {}
            if resp.status >= 400:
                raise RuntimeError(f"{resp.status} {str(data)[:400]}")
            return data or {}


async def advert_payload(product: dict) -> dict:
    images = [u for u in (public_url(r) for r in await photo_refs(product)) if u]
    return {
        "title": olx_title(product),
        "description": olx_description(product),
        "category_id": int(os.getenv("OLX_CATEGORY_ID", "0")),
        "advertiser_type": "business",
        "contact": {"name": os.getenv("OLX_CONTACT_NAME", "Ketoshop"),
                    "phone": _phones().split(",")[0].strip()},
        "location": {"city_id": int(os.getenv("OLX_CITY_ID", "0"))},
        "images": [{"url": u} for u in images],
        "price": {"value": price_of(product), "currency": "UZS", "negotiable": False},
        "attributes": json.loads(os.getenv("OLX_ATTRIBUTES", "[]") or "[]"),
    }


async def plan() -> dict:
    """Nima qilinadi: create / update / deactivate ro'yxatlari."""
    live = {p["id"]: p for p in await olx_products()}
    async with database.pool.acquire() as conn:
        mapped = {r["product_id"]: dict(r) for r in await conn.fetch("SELECT * FROM olx_adverts")}
    create = [p for pid, p in live.items() if pid not in mapped or mapped[pid]["status"] != "active"]
    update = [p for pid, p in live.items()
              if pid in mapped and mapped[pid]["status"] == "active"]
    stop = [m for pid, m in mapped.items() if pid not in live and m["status"] == "active"]
    return {"create": create, "update": update, "stop": stop, "mapped": mapped}


async def sync(progress=None) -> dict:
    """OLX'ni do'kon bilan tenglashtiradi. Har mahsulot alohida: bittasi xato
    bersa, qolganlari davom etadi, xatolar hisobotda ko'rinadi."""
    work = await plan()
    done = {"created": 0, "updated": 0, "stopped": 0, "errors": []}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        client = OlxClient(session)

        async def save(pid: int, advert_id: int, status: str, price: int | None):
            async with database.pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO olx_adverts (product_id, advert_id, status, last_price, updated_at)
                       VALUES ($1, $2, $3, $4, CURRENT_TIMESTAMP)
                       ON CONFLICT (product_id) DO UPDATE SET advert_id = EXCLUDED.advert_id,
                         status = EXCLUDED.status, last_price = EXCLUDED.last_price,
                         updated_at = CURRENT_TIMESTAMP""",
                    pid, advert_id, status, price)

        for p in work["create"]:
            try:
                old = work["mapped"].get(p["id"])
                if old:   # avval to'xtatilgan e'lonni qayta yoqamiz, yangisini ochmaymiz
                    await client.call("PUT", f"/adverts/{old['advert_id']}", await advert_payload(p))
                    await client.call("POST", f"/adverts/{old['advert_id']}/commands", {"command": "activate"})
                    advert_id = old["advert_id"]
                else:
                    data = await client.call("POST", "/adverts", await advert_payload(p))
                    advert_id = int((data.get("data") or data)["id"])
                await save(p["id"], advert_id, "active", price_of(p))
                done["created"] += 1
            except Exception as e:
                done["errors"].append(f"#{p['id']} {p['name']}: {e}")
            await asyncio.sleep(1)   # OLX limitiga urilmaslik uchun

        for p in work["update"]:
            m = work["mapped"][p["id"]]
            if m.get("last_price") == price_of(p):
                continue           # o'zgarmagan — OLX'ni bezovta qilmaymiz
            try:
                await client.call("PUT", f"/adverts/{m['advert_id']}", await advert_payload(p))
                await save(p["id"], m["advert_id"], "active", price_of(p))
                done["updated"] += 1
            except Exception as e:
                done["errors"].append(f"#{p['id']} {p['name']}: {e}")
            await asyncio.sleep(1)

        for m in work["stop"]:
            try:
                await client.call("POST", f"/adverts/{m['advert_id']}/commands",
                                  {"command": "deactivate", "is_success": True})
                await save(m["product_id"], m["advert_id"], "stopped", m.get("last_price"))
                done["stopped"] += 1
            except Exception as e:
                done["errors"].append(f"#{m['product_id']} to'xtatish: {e}")
    return done


_sync_lock = asyncio.Lock()

SETUP_HELP = (
    "🔑 OLX avtopiloti hali ulanmagan.\n\n"
    "1) developer.olx.uz da ilova oching (yoki OLX biznes menejeridan Partner API so'rang).\n"
    "2) Serverga env qo'ying: OLX_CLIENT_ID, OLX_CLIENT_SECRET, OLX_REFRESH_TOKEN, "
    "OLX_CATEGORY_ID (oziq-ovqat), OLX_CITY_ID (Toshkent).\n"
    "3) /olx_joyla — reja, /olx_joyla tasdiq — joylash.\n\n"
    "Shu orada /olx paketi bilan qo'lda joylash mumkin."
)


@router.message(Command("olx_joyla"), F.from_user.id.in_(ADMIN_IDS), F.chat.type == "private")
async def cmd_olx_sync(message: Message, command: CommandObject):
    if not api_configured():
        await message.answer(SETUP_HELP)
        return
    await ensure_schema()
    if (command.args or "").strip().lower() != "tasdiq":
        w = await plan()
        changed = sum(1 for p in w["update"] if w["mapped"][p["id"]].get("last_price") != price_of(p))
        no_photo = [p for p in w["create"] if not (p.get("photo_id") or p.get("image_url"))]
        lines = [
            "🧭 OLX reja (hali hech narsa yuborilmadi):",
            f"➕ Yangi e'lon: {len(w['create'])}",
            f"✏️ Narxi o'zgargan: {changed}",
            f"⏸ To'xtatiladi (tugagan/o'chirilgan): {len(w['stop'])}",
        ]
        if no_photo:
            lines.append(f"⚠️ Rasmsiz: {len(no_photo)} ta — " + ", ".join(p["name"] for p in no_photo[:5]))
        lines.append("\nYuborish uchun: /olx_joyla tasdiq")
        await message.answer("\n".join(lines))
        return
    if _sync_lock.locked():
        await message.answer("⏳ Joylash allaqachon ketyapti.")
        return
    async with _sync_lock:
        await message.answer("🚀 OLX'ga yuborilyapti…")
        try:
            r = await sync()
        except Exception as e:
            logger.exception("olx sync")
            await message.answer(f"❌ OLX bilan bog'lanib bo'lmadi: {e}")
            return
        text = (f"✅ OLX: +{r['created']} yangi, ✏️ {r['updated']} yangilandi, "
                f"⏸ {r['stopped']} to'xtatildi.")
        if r["errors"]:
            text += f"\n\n❗ Xatolar ({len(r['errors'])}):\n" + "\n".join(r["errors"][:15])
        await message.answer(text[:4000])
