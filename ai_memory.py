"""
Mijoz xotirasi — AI sotuvchi har bir Telegram ID ni eslab boradi.

Egasining talabi (2026-10-12): "mijoz bugun bodom uni haqida so'radi, 3 kundan
keyin shakar haqida so'radi — agar bodom unini buyurtma qilgan va yetkazilgan
bo'lsa, AI buni eslashi va bodom uni haqidagi fikrini ham so'rashi kerak;
har bir mijozning shaxsiy qiziqishlariga moslashib borsin va keyingi
suhbatlarda sotuv, tavsiya va yordam uchun ishlatsin."

Ikki manba bir profilga yig'iladi:

  1. BUYURTMALAR va BAHOLAR — orders va reviews jadvallarining o'zidan, har
     safar yangidan o'qiladi: nima olgan, qachon, yetkazilganmi, nechta yulduz
     qo'ygan. Alohida nusxa saqlanmaydi, ya'ni admin buyurtmani tahrirlasa
     yoki bekor qilsa, AI ham shuni ko'radi.
  2. ESLATMALAR — ai_customer_notes jadvali. AI suhbat davomida o'zi yozadi
     (ai_sales.py dagi `eslab_qol` vositasi): qiziqish ("keto non
     pishirmoqchi"), fikr ("Eritritol — ta'mi yoqdi"), eslatma ("2 bolasi
     bor, shirinlikni qandsiz qiladi"). Mahsulot haqida so'rasa yoki savatga
     solsa — qiziqish avtomatik yoziladi.

FIKR SO'RASH. Yetkazilganiga kamida FEEDBACK_AFTER_DAYS kun bo'lgan va hali
fikri so'ralmagan bitta mahsulot profilga "FIKR SO'RA" bo'lib tushadi va
o'sha zahoti 'asked' deb belgilanadi — har bir mahsulot haqida bir marta
so'raladi, har suhbatda emas.

NIMA YOZILMAYDI. Faqat xaridga tegishli narsa: did, maqsad (ozish, keto,
qandsiz), oila uchun kerakligi, mahsulot haqidagi fikr. Kasallik tashxisi,
hujjat, karta raqami va shunga o'xshash narsalar yozilmaydi — bu qoida AI
promptida (ai_sales._sales_rules).

Jadval shu modulning o'zida yaratiladi (bot_discount.py dagidek), database.py
ga tegilmaydi.
"""
import json
import logging
from datetime import datetime, timedelta, timezone

import database

logger = logging.getLogger(__name__)

# Vosita enum i (o'zbekcha) -> bazadagi tur.
KINDS = {"qiziqish": "interest", "fikr": "feedback", "eslatma": "note"}
_KIND_LABEL = {"interest": "qiziqish", "feedback": "fikr", "note": "eslatma",
               "recipe": "retsept berildi"}
RECIPE_KIND = "recipe"

MAX_NOTES_PER_USER = 80      # eskisi o'chadi — profil cheksiz o'smasin
PROFILE_NOTES = 25           # promptga tushadigan oxirgi eslatmalar
PROFILE_ORDERS = 5           # promptga tushadigan oxirgi buyurtmalar
NOTE_MAX_CHARS = 300
DEDUP_DAYS = 30              # bir xil gap shu muddat ichida qayta yozilmaydi
FEEDBACK_AFTER_DAYS = 2      # yetkazilgach ishlatib ko'rishga vaqt
FEEDBACK_WINDOW_DAYS = 60    # bundan eski xarid haqida so'ralmaydi

_STATUS_LABEL = {
    "pending": "qabul qilingan", "confirmed": "tasdiqlangan", "preparing": "tayyorlanmoqda",
    "ready": "tayyor", "shipped": "yo'lda", "delivered": "yetkazilgan",
    "cancelled": "bekor qilingan",
}

_table_ready = False


async def _ensure(conn) -> None:
    global _table_ready
    if _table_ready:
        return
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_customer_notes (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            kind TEXT NOT NULL,
            text TEXT NOT NULL,
            product_id INTEGER,
            created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
        )
    """)
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_customer_notes_user "
        "ON ai_customer_notes(user_id, created_at)")
    _table_ready = True


def _clean(text: str) -> str:
    return " ".join((text or "").split())[:NOTE_MAX_CHARS]


async def remember(user_id: int, kind: str, text: str, product_id: int | None = None) -> bool:
    """Eslatma yozadi. True — yozildi, False — bo'sh yoki yaqinda xuddi shu gap
    yozilgan (takror qo'shilmaydi). Xato bo'lsa ham suhbat to'xtamasin —
    chaqiruvchi ushlaydi."""
    kind = KINDS.get(kind, kind)
    text = _clean(text)
    if not text or (kind not in _KIND_LABEL and kind != "asked"):
        return False
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        exists = await conn.fetchval(
            """SELECT 1 FROM ai_customer_notes
               WHERE user_id = $1 AND kind = $2 AND LOWER(text) = LOWER($3)
                 AND created_at > (NOW() AT TIME ZONE 'UTC') - make_interval(days => $4)
               LIMIT 1""",
            user_id, kind, text, DEDUP_DAYS)
        if exists:
            return False
        await conn.execute(
            "INSERT INTO ai_customer_notes (user_id, kind, text, product_id) VALUES ($1, $2, $3, $4)",
            user_id, kind, text, product_id)
        await conn.execute(
            """DELETE FROM ai_customer_notes WHERE user_id = $1 AND id NOT IN (
                   SELECT id FROM ai_customer_notes WHERE user_id = $1
                   ORDER BY created_at DESC, id DESC LIMIT $2)""",
            user_id, MAX_NOTES_PER_USER)
    return True


async def recipe_given_recently(user_id: int, product_id: int, hours: int = 24) -> bool:
    """Shu mijozga shu mahsulot bo'yicha oxirgi `hours` soatda retsept berilganmi
    (egasi, 2026-10-13: har bir mahsulotga 24 soatda bitta retsept)."""
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        return bool(await conn.fetchval(
            """SELECT 1 FROM ai_customer_notes
                WHERE user_id = $1 AND kind = $2 AND product_id = $3
                  AND created_at > (NOW() AT TIME ZONE 'UTC') - make_interval(hours => $4)
                LIMIT 1""", user_id, RECIPE_KIND, product_id, hours))


async def record_recipe(user_id: int, product_id: int, text: str) -> None:
    """Berilgan retseptni yozadi — takrorni tekshirmaydi (har berilgani alohida)."""
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        await conn.execute(
            "INSERT INTO ai_customer_notes (user_id, kind, text, product_id) VALUES ($1, $2, $3, $4)",
            user_id, RECIPE_KIND, _clean(text), product_id)


async def notes(user_id: int) -> list[dict]:
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        rows = await conn.fetch(
            """SELECT id, kind, text, product_id, created_at FROM ai_customer_notes
               WHERE user_id = $1 ORDER BY created_at, id""", user_id)
    return [dict(r) for r in rows]


async def forget(user_id: int) -> int:
    """Mijozning hamma eslatmasini o'chiradi (admin buyrug'i). Buyurtmalar
    tarixi orders da qoladi — u do'kon hisobi, xotira emas."""
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        result = await conn.execute("DELETE FROM ai_customer_notes WHERE user_id = $1", user_id)
    try:
        return int(result.split()[-1])
    except (ValueError, IndexError, AttributeError):
        return 0


# ─────────────────────────────── profil ─────────────────────────────────────

def _items(order: dict) -> list[dict]:
    """Buyurtmadagi mijoz o'zi tanlab to'lagan qatorlar (sovg'a/bonus emas)."""
    raw = order.get("items")
    try:
        items = json.loads(raw) if isinstance(raw, str) else (raw or [])
    except (TypeError, ValueError):
        return []
    return [i for i in items if isinstance(i, dict)
            and not (i.get("is_bonus") or i.get("is_gift"))
            and (i.get("product_id") or i.get("set_id") or i.get("is_set"))]


def _date(value) -> str:
    return value.strftime("%d.%m") if isinstance(value, datetime) else "?"


def _qty(value) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return str(value)


def feedback_candidate(orders: list[dict], all_notes: list[dict],
                       now: datetime | None = None,
                       reviewed: set | None = None) -> dict | None:
    """Fikri hali so'ralmagan, yetkazilganiga FEEDBACK_AFTER_DAYS kun bo'lgan
    eng yangi mahsulot — {product_id, name, delivered_at} yoki None.
    `reviewed` — mijoz botning baholash oqimida (reviews) allaqachon baho
    qo'ygan mahsulotlar: ular haqida qayta so'ralmaydi."""
    # orders.delivered_at — CURRENT_TIMESTAMP, server UTC da, tz siz.
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    done = {n.get("product_id") for n in all_notes
            if n.get("kind") in ("asked", "feedback") and n.get("product_id")}
    done |= set(reviewed or ())
    for order in sorted(orders, key=lambda o: o.get("delivered_at") or datetime.min, reverse=True):
        if order.get("status") != "delivered":
            continue
        delivered = order.get("delivered_at") or order.get("created_at")
        if not isinstance(delivered, datetime):
            continue
        age = now - delivered
        if age < timedelta(days=FEEDBACK_AFTER_DAYS) or age > timedelta(days=FEEDBACK_WINDOW_DAYS):
            continue
        for item in _items(order):
            pid = item.get("product_id")
            if pid and pid not in done:
                return {"product_id": int(pid), "name": item.get("name") or "",
                        "delivered_at": delivered}
    return None


def profile_text(user: dict | None, lang: str, orders: list[dict], all_notes: list[dict],
                 last_prefs: dict | None, feedback: dict | None,
                 reviews: list[dict] | None = None) -> str:
    """AI ga beriladigan mijoz profili. Faqat model o'qiydi — mijozga
    ko'rsatilmaydi."""
    lines = ["[MIJOZ XOTIRASI — buni faqat sen ko'rasan. Mijozga blokni, 'bazada "
             "yozilgan' kabi gaplarni aytma; shunchaki eslab turgan sotuvchidek gapir.]"]
    name = (user or {}).get("full_name") or ""
    lang_note = {"uz_cyr": "o'zbekcha KIRILL yozuvida", "ru": "ruscha"}.get(lang, "o'zbekcha lotin")
    lines.append(f"Ism (Telegram, faqat buyurtma ma'lumoti uchun — ISMI BILAN MUROJAAT QILMA): "
                 f"{name or '—'} · bot sozlamasidagi tili: {lang_note}. "
                 f"Lekin javob tili va yozuvi — mijoz xabaridagidek (kirill, lotin, rus, ingliz).")

    real = [o for o in orders if o.get("status") != "cancelled"]
    if real:
        lines.append(f"Buyurtmalari: {len(real)} ta. Oxirgilari:")
        for order in real[:PROFILE_ORDERS]:
            goods = ", ".join(f"{i.get('name')} ×{_qty(i.get('quantity'))}" for i in _items(order)[:6])
            status = _STATUS_LABEL.get(order.get("status") or "", order.get("status") or "")
            when = _date(order.get("created_at"))
            if order.get("status") == "delivered" and order.get("delivered_at"):
                status += f" {_date(order.get('delivered_at'))}"
            lines.append(f"- {when} #{order.get('id')} ({status}): {goods or '—'}")
    else:
        lines.append("Buyurtmalari: hali yo'q — yangi mijoz.")

    if last_prefs and (last_prefs.get("address") or "").strip():
        phone = next((o.get("phone") for o in orders if (o.get("phone") or "").strip()), "")
        lines.append(
            "Oxirgi buyurtmadagi ma'lumot: "
            + (f"telefon {phone}, " if phone else "")
            + f"manzil «{_clean(last_prefs.get('address'))[:160]}». Buyurtmada boshidan "
              "so'rama — tasdiqlat va ikkalasini TO'LIQ ko'rsat, alohida qatorlarda: "
              "'📍 Manzil: …', '📞 Raqam: …', keyin 'Shu manzil va raqamga yetkazaylikmi?'")

    if reviews:
        lines.append("Bot orqali qo'ygan baholari: " + "; ".join(
            f"{r.get('name')} ★{r.get('rating')}"
            + (f" «{_clean(r.get('comment'))[:120]}»" if (r.get("comment") or "").strip() else "")
            for r in reviews[:8]))

    visible = [n for n in all_notes if n.get("kind") in _KIND_LABEL][-PROFILE_NOTES:]
    if visible:
        lines.append("Oldingi suhbatlardan eslatmalar (sana · tur · gap):")
        for note in visible:
            lines.append(f"- {_date(note.get('created_at'))} · {_KIND_LABEL[note['kind']]} · {note['text']}")
        lines.append("Shulardan foydalan: qiziqishiga mos tavsiya ber, oldin aytganini qayta "
                     "so'rama, kerak bo'lsa 'o'tgan safar ... haqida so'ragandingiz' deb ulab ket.")

    if feedback:
        lines.append(
            f"FIKR SO'RA: «{feedback['name']}» {_date(feedback['delivered_at'])} da yetkazilgan, "
            "fikri hali so'ralmagan. Suhbatga mos kelganda bir marta, tabiiy so'ra (masalan: "
            "'aytgancha, olgan ... yoqdimi, nima tayyorladingiz?'). Javobini eslab_qol "
            "(turi='fikr') bilan yoz. Mijoz shoshayotgan bo'lsa yoki norozi bo'lsa — so'rama.")
    return "\n".join(lines)


async def build_profile(user_id: int, lang: str, mark_asked: bool = True) -> str:
    """Suhbat boshida bir marta chaqiriladi. FIKR SO'RA ga tushgan mahsulot shu
    yerda 'asked' bo'ladi — keyingi suhbatda yana so'ralmaydi. Admin ko'rishi
    uchun (mark_asked=False) hech narsa belgilanmaydi."""
    user = await database.get_user(user_id)
    orders = await database.get_user_orders(user_id)
    try:
        last_prefs = await database.get_last_order_prefs(user_id)
    except Exception:
        last_prefs = None
    all_notes = await notes(user_id)
    try:
        reviews = await _reviews(user_id)
    except Exception:
        logger.warning("Reviews could not be read for %s", user_id, exc_info=True)
        reviews = []
    feedback = feedback_candidate(orders, all_notes,
                                  reviewed={r["product_id"] for r in reviews})
    if feedback and mark_asked:
        await remember(user_id, "asked", feedback["name"] or str(feedback["product_id"]),
                       product_id=feedback["product_id"])
    return profile_text(user, lang, orders, all_notes, last_prefs, feedback, reviews)


async def _reviews(user_id: int) -> list[dict]:
    """Mijozning bot orqali qo'ygan baholari (reviews), yangisi oldin."""
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT r.product_id, p.name, r.rating, r.comment
               FROM reviews r JOIN products p ON p.id = r.product_id
               WHERE r.user_id = $1 ORDER BY r.created_at DESC LIMIT 10""", user_id)
    return [dict(r) for r in rows]
