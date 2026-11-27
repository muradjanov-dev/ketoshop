"""
Mijoz portreti — murojaat ismi, yosh, jins (ismdan taxmin) va maqsadlar.

Egasi, 2026-11-15: "AI foydalanuvchi ma'lumotlarini yig'sin: murojaat uchun
ismini, yaxshiroq tavsiya uchun yoshini — hammasini bitta xabarda emas. Keyin
ismidan erkak yoki ayolligini aniqlasin. Har bir mijozning portretini tuzib
saqlasin. Har kuni kun oxirida adminlarga qaysi ma'lumot nechta mijozdan
yig'ilganini aytsin."

QOIDALAR (o'zgartirishdan oldin o'qing)
  * Sotuvchi so'raganidek, oddiy va suhbatga bog'lab, sababi rost: "Sizga
    qanday murojaat qilaylik?", "Yoshingizni bilsak, sizga mosrog'ini tavsiya
    qila olamiz 😊" (egasi, 2026-11-16), "Kim uchun olyapsiz — o'zingizgami
    yoki oilagami?". Model so'zma-so'z takrorlamaydi. Majburiy
    qilib ko'rsatilmaydi, buyurtma uchun kerak deyilmaydi. Egasi, 2026-11-16:
    "shubhali gaplar yozmasin, tabiiy yozsin" — izoh, ogohlantirish, maxfiylik
    haqidagi gap va so'rovnoma ohangi yo'q; model baribir qo'shsa, javobdan
    olinadi (plain_tone).
  * Bitta xabarda ko'pi bilan bitta savol; suhbatning birinchi javobida hech
    qachon (avval mijozning o'z savoliga javob). Ikki savol orasida kamida
    ASK_GAP_TURNS ta mijoz xabari.
  * Har bir maydon bir marta so'raladi: AI ga so'rash imkoni berilgan zahoti
    asked_*_at yoziladi — mijoz javob bermasa yoki istamasa, qayta so'ralmaydi.
    Qaysi xabarda so'rash mumkinligini KOD hal qiladi (claim_question), model
    o'zicha so'rasa — bu savol javobdan olib tashlanadi (drop_profile_questions).
  * Jins so'ralmaydi va mijozga aytilmaydi: ismdan jim taxmin qilinadi
    (name_gender.py), manbasi ('name' / 'stated') va ishonchi bilan saqlanadi.
    AI ga ham berilmaydi — faqat adminlar portreti va hisobot uchun.
  * Kasallik tashxisi, hujjat, karta raqami yozilmaydi: vositada faqat ism,
    yosh (butun son), ro'yxatdagi maqsad teglari va mijoz o'zi aytgan jins.
  * Rozilik (shaxsga doir ma'lumotlar qonuni): javob ixtiyoriy; /malumotlarim —
    mijoz nima saqlanganini ko'radi va bir tugma bilan o'chiradi. O'chirgan
    mijozdan boshqa so'ralmaydi va yangi ma'lumot yozilmaydi (opted_out_at),
    o'zi qayta yoqmaguncha. Buyurtmalar tarixi do'kon hisobi bo'lib qoladi.

KUNLIK HISOBOT — har kuni 23:30 (Toshkent) adminlarga, o'zbekcha: bugun
nechta mijozdan ism / yosh / jins / maqsad yig'ildi, jami portretlar va
har maydonning qamrovi, 3–5 ta ismsiz-familiyasiz misol. Adminlar va ichki
akkauntlar (LEADERBOARD_EXCLUDED_USER_IDS) hisobga kirmaydi. Bir kunda bir
marta (claim_release_notes); bot 23:30 dan keyin qayta ishga tushsa, o'sha
kecha yuboradi. PORTRAIT_REPORT=0 — o'chiq; AI_PORTRAIT_ASK=0 — AI so'ramaydi.

Jadval shu modulda yaratiladi (ai_memory.py dagidek) — faqat qo'shiladi,
mavjud jadvallarga tegilmaydi.
"""
import asyncio
import html
import logging
import os
import re
from datetime import date, datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

import database
import name_gender
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router()

ASK_ENABLED = os.getenv("AI_PORTRAIT_ASK", "1").strip() != "0"
REPORT_ENABLED = os.getenv("PORTRAIT_REPORT", "1").strip() != "0"

TZ_OFFSET = timedelta(hours=5)
REPORT_AT = (23, 30)
ASK_GAP_TURNS = 3            # ikki savol orasida kamida shuncha mijoz xabari
AGE_MIN, AGE_MAX = 10, 100
NAME_MAX = 40
EXAMPLES = 5
SEND_DELAY = 0.05

# Teg -> (o'zbekcha, ruscha). Tartib — ko'rsatish tartibi. Tashxis emas,
# xaridga tegishli maqsad: "qandsiz" — shakarsiz ovqat qidiradi.
GOALS = {
    "ozish": ("ozish", "похудение"),
    "keto": ("keto", "кето"),
    "pp": ("to'g'ri ovqatlanish (PP)", "правильное питание (ПП)"),
    "qandsiz": ("shakarsiz ovqat", "без сахара"),
    "glutensiz": ("glutensiz", "без глютена"),
    "sport": ("sport", "спорт"),
    "oila": ("oila uchun", "для семьи"),
    "bolalar": ("bolalar uchun", "для детей"),
    "pishiriq": ("pishiriq", "выпечка"),
}
_GOAL_ORDER = list(GOALS)

FIELDS = ("name", "age")


class Invalid(ValueError):
    """Model bergan qiymat yaroqsiz — vosita "Xato:" bilan qaytaradi."""


_table_ready = False


async def _ensure(conn) -> None:
    global _table_ready
    if _table_ready:
        return
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS customer_portrait (
            user_id BIGINT PRIMARY KEY,
            display_name TEXT,
            name_collected_at TIMESTAMP,
            age SMALLINT,
            age_group TEXT,
            age_collected_at TIMESTAMP,
            gender TEXT NOT NULL DEFAULT 'unknown'
                CHECK (gender IN ('m', 'f', 'unknown')),
            gender_source TEXT CHECK (gender_source IS NULL OR gender_source IN ('name', 'stated')),
            gender_confidence REAL,
            gender_collected_at TIMESTAMP,
            goals TEXT[] NOT NULL DEFAULT '{}',
            goals_collected_at TIMESTAMP,
            asked_name_at TIMESTAMP,
            asked_age_at TIMESTAMP,
            opted_out_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
            updated_at TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC')
        )
    """)
    _table_ready = True


def _utcnow() -> datetime:
    # Bazadagi vaqtlar UTC, tz siz (NOW() AT TIME ZONE 'UTC') — shu bilan bir xil.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _now_tk() -> datetime:
    return _utcnow() + TZ_OFFSET


def _excluded_ids() -> list[int]:
    return sorted(set(ADMIN_IDS) | set(database.LEADERBOARD_EXCLUDED_USER_IDS))


# ───────────────────────────── qiymatlar ────────────────────────────────────

def clean_name(value) -> str:
    """Murojaat ismi: 1–3 so'z, harf bilan, raqam / havola / @ siz."""
    text = " ".join(str(value or "").replace("\n", " ").split()).strip(" \"'«»“”.,!?")
    if not text:
        raise Invalid("ism bo'sh")
    if (len(text) > NAME_MAX or len(text.split()) > 3 or re.search(r"\d|@|https?:|www\.|/", text)
            or not re.search(r"[^\W\d_]", text)):
        raise Invalid("ism emas — faqat mijoz qanday murojaat qilishni aytgan ismni yoz")
    return text


def clean_age(value) -> int:
    try:
        age = int(value)
    except (TypeError, ValueError):
        raise Invalid("yosh butun son bo'lishi kerak")
    if not AGE_MIN <= age <= AGE_MAX:
        raise Invalid(f"yosh {AGE_MIN}–{AGE_MAX} oralig'ida bo'lishi kerak")
    return age


def clean_goals(values) -> list[str]:
    if isinstance(values, str):
        values = [values]
    out = []
    for value in values or []:
        tag = str(value or "").strip().lower().replace("'", "").replace("ʻ", "")
        if tag in GOALS and tag not in out:
            out.append(tag)
    return out


def age_group(age: int | None) -> str | None:
    if age is None:
        return None
    if age < 18:
        return "18 gacha"
    for low, high in ((18, 24), (25, 34), (35, 44), (45, 54), (55, 64)):
        if low <= age <= high:
            return f"{low}–{high}"
    return "65+"


def plan_changes(current: dict | None, *, name: str | None = None, age: int | None = None,
                 goals: list[str] | None = None, stated_gender: str | None = None,
                 telegram_name: str | None = None, now: datetime | None = None) -> dict:
    """Portretga yoziladigan ustunlar (faqat o'zgargani). Har maydon o'zgarganda
    o'zining *_collected_at i yangilanadi — kunlik hisobot shundan sanaydi."""
    current = current or {}
    now = now or _utcnow()
    out: dict = {}
    if name and name != current.get("display_name"):
        out.update(display_name=name, name_collected_at=now)
    if age is not None and age != current.get("age"):
        out.update(age=age, age_group=age_group(age), age_collected_at=now)
    if goals:
        have = list(current.get("goals") or [])
        merged = sorted(set(have) | set(goals), key=lambda g: _GOAL_ORDER.index(g) if g in GOALS else 99)
        if set(merged) != set(have):
            out.update(goals=merged, goals_collected_at=now)

    if stated_gender in ("m", "f"):
        if current.get("gender") != stated_gender or current.get("gender_source") != "stated":
            out.update(gender=stated_gender, gender_source="stated", gender_confidence=1.0,
                       gender_collected_at=now)
    elif out and current.get("gender_source") != "stated":
        # Ism o'zgardi yoki jins hali noma'lum — o'zi aytgan ism, bo'lmasa Telegram ismi.
        if "display_name" in out or current.get("gender", "unknown") == "unknown":
            source = out.get("display_name") or current.get("display_name") or telegram_name
            gender, confidence = name_gender.infer(source)
            if gender != "unknown" and gender != current.get("gender"):
                out.update(gender=gender, gender_source="name", gender_confidence=confidence,
                           gender_collected_at=now)
    if out:
        out["updated_at"] = now
    return out


def pick_question(portrait: dict | None) -> str | None:
    """Hali so'ralmagan va noma'lum maydon: avval ism, keyin yosh."""
    portrait = portrait or {}
    if portrait.get("opted_out_at"):
        return None
    if not portrait.get("display_name") and not portrait.get("asked_name_at"):
        return "name"
    if portrait.get("age") is None and not portrait.get("asked_age_at"):
        return "age"
    return None


def ask_allowed(session: dict) -> bool:
    """Shu xabarda portret savoli mumkinmi — faqat suhbat holatidan (bazasiz).
    Birinchi javobda yo'q; oldingi savoldan keyin ASK_GAP_TURNS ta xabar;
    buyurtma kartasi, lokatsiya yoki chek kutilayotganda yo'q."""
    if not ASK_ENABLED or session.get("portrait_done"):
        return False
    turns = int(session.get("turns") or 0)
    if turns < 2:
        return False
    last = session.get("portrait_asked_turn")
    if last is not None and turns - int(last) < ASK_GAP_TURNS:
        return False
    if session.get("card") or session.get("keyboard") == "location" or session.get("awaiting_cheque"):
        return False
    return True


_ASK_HINT = {
    "name": ("unga qanday murojaat qilishimizni so'ra (masalan: 'Sizga qanday murojaat qilaylik?'). "
             "Javob bersa — portret_yoz (ism)."),
    "age": ("yoshini mayin, sababini ichiga olgan jumla bilan so'ra, mijoz tanlayotgan narsaga bog'lab. "
            "Namuna: 'Yoshingizni bilsak, sizga mosrog'ini tavsiya qila olamiz 😊' (ruscha: 'Если "
            "подскажете ваш возраст, сможем посоветовать то, что подойдёт лучше 😊') — so'zma-so'z "
            "takrorlama, o'z so'zing bilan ayt. Javob bersa — portret_yoz (yosh)."),
}


def ask_hint(field: str) -> str:
    return ("[PORTRET — SO'RASH IMKONI, faqat shu xabarda: avval mijozning xabariga to'liq javob ber. "
            "Keyin, o'rni kelsa, javob oxirida alohida qatorda, mijoz tilida BITTA oddiy so'rov "
            "(savol yoki mayin jumla): "
            + _ASK_HINT[field]
            + " Sotuvchi suhbat orasida so'raganidek tabiiy yoz: izoh, ogohlantirish, maxfiylik haqida gap "
              "va so'rovnoma ohangi yo'q; bosim qilma, buyurtma uchun kerak dema. Mijoz norozi, shoshayotgan "
              "yoki buyurtma rasmiylashtirilayotgan bo'lsa — so'rama. Javob bermasa yoki aytgisi kelmasa — "
              "qayta so'rama. Javob bersa — keyingi xabarda shunga tayanib aniq tavsiya ber yoki "
              "suhbatni davom ettir; 'yoshingizga mos tavsiya qilamiz' deb yangi savol berma.]")


# Mijozning O'Z ismi / yoshi haqidagi savol (ikkinchi shaxs: "ismingiz",
# "yoshingiz"). "Bolangiz necha yoshda?" kabi savolga tegilmaydi.
_ASK_PATTERNS = {
    "name": re.compile(r"ismingiz|qanday murojaat|исмингиз|қандай мурожаат|как (?:к вам )?обращаться|"
                       r"как вас зовут|ваше имя|your name|call you", re.IGNORECASE),
    "age": re.compile(r"yoshingiz|necha yoshdasiz|nechchi yoshdasiz|ёшингиз|неча ёшдасиз|"
                      r"сколько вам лет|ваш возраст|how old are you", re.IGNORECASE),
}


# Savol belgisisiz, mayin so'rov: "Yoshingizni bilsak, ... tavsiya qila olamiz 😊".
_SOFT_ASK = re.compile(r"bilsak|aytsangiz|ayting|aytib\s+yuborsangiz|билсак|айтсангиз|айтинг|"
                       r"подскажете|скажете|подскажите|скажите|знать|let us know|tell us", re.IGNORECASE)


def _ask_kind(sentence: str) -> str | None:
    if "?" not in sentence and not _SOFT_ASK.search(sentence):
        return None
    for kind, pattern in _ASK_PATTERNS.items():
        if pattern.search(sentence):
            return kind
    return None


def drop_profile_questions(text: str, allowed: str | None) -> str:
    """Model ruxsatsiz so'ragan ism / yosh savolini olib tashlaydi: shu xabarda
    imkon berilmagan maydon yoki ikkinchi savol. Ruxsat berilgani — bitta,
    birinchisi qoladi. Hammasi o'chib ketsa — asl matn (javobsiz qolmasin)."""
    if not text:
        return text
    kept_lines, asked = [], False
    changed = False
    for line in text.split("\n"):
        parts = re.split(r"(?<=[.!?…])\s+", line)
        keep = []
        for part in parts:
            kind = _ask_kind(part)
            if kind is not None and (kind != allowed or asked):
                changed = True
                continue
            if kind is not None:
                asked = True
            keep.append(part)
        if keep or not line.strip():
            kept_lines.append(" ".join(keep))
        else:
            changed = True
    result = text
    if changed:
        result = re.sub(r"\n{3,}", "\n\n", "\n".join(kept_lines)).strip() or text
    return plain_tone(result, asking=asked)


# Egasi, 2026-11-16: "agar sir bo'lmasa -> bunday shubhali gaplar yozmasin,
# tabiiy yozsin". Promptda bu iboralar ataylab sanalmaydi (model ularni ko'rib
# ko'chirmasin) — kod javobdan oladi.
_APOS = "['’ʻ‘`ʼ]?"
_HEDGE = re.compile(
    r"\s*[,;]?\s*\b(?:agar\s+sir\s+bo" + _APOS + r"lmasa|agar\s+qarshi\s+bo" + _APOS + r"lmasangiz|"
    r"агар\s+сир\s+бўлмаса|агар\s+қарши\s+бўлмасангиз|если\s+не\s+секрет|если\s+вы\s+не\s+против|"
    r"если\s+не\s+возражаете)\b\s*,?", re.IGNORECASE)
# Har doim olinadigan gap — do'kon suhbatida bunga o'rin yo'q.
_PRIVACY_TALK = re.compile(
    r"shaxsiy\s+ma" + _APOS + r"lumot|ma" + _APOS + r"lumotlaringiz\s+xavfsiz|шахсий\s+маълумот|"
    r"маълумотларингиз\s+хавфсиз|персональн\w*\s+данн|личн\w*\s+данн|данные\s+в\s+безопасности",
    re.IGNORECASE)
# Savol bor javobda — "majburiy emas" kabi izoh.
_DISCLAIMER_WORDS = (r"majburiy\s+emas|ixtiyoriy|мажбурий\s+эмас|ихтиёрий|необязательно|"
                     r"не\s+обязательно")
_DISCLAIMER = re.compile(_DISCLAIMER_WORDS, re.IGNORECASE)
# Savolning o'zi ichida: "Yoshingiz nechada (majburiy emas)?" -> "Yoshingiz nechada?"
_DISCLAIMER_CLAUSE = re.compile(
    r"\s*[(,;—–-]*\s*(?:bu\s+|это\s+)?(?:" + _DISCLAIMER_WORDS + r")\s*\)?", re.IGNORECASE)


def plain_tone(text: str, asking: bool = False) -> str:
    """Savol yonidagi "agar sir bo'lmasa" kabi qo'shimcha va maxfiylik haqidagi
    gapni olib tashlaydi. `asking` — javobda portret savoli bor: shunda
    "majburiy emas" kabi izoh gapi ham olinadi."""
    if not text:
        return text
    out_lines, changed = [], False
    for line in text.split("\n"):
        keep = []
        for part in re.split(r"(?<=[.!?…])\s+", line):
            question = _ask_kind(part) is not None
            if _PRIVACY_TALK.search(part) or (asking and not question and _DISCLAIMER.search(part)):
                changed = True
                continue
            cleaned = _HEDGE.sub("", part)
            if asking and question:
                cleaned = _DISCLAIMER_CLAUSE.sub("", cleaned)
            if cleaned != part:
                changed = True
                cleaned = re.sub(r"\s+([?!.,])", r"\1", cleaned).strip(" ,")
                if cleaned[:1].islower() and part.lstrip()[:1].isupper():
                    cleaned = cleaned[0].upper() + cleaned[1:]
                if not cleaned or not re.search(r"\w", cleaned):
                    continue
            keep.append(cleaned)
        if keep or not line.strip():
            out_lines.append(" ".join(keep))
        else:
            changed = True
    if not changed:
        return text
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(out_lines)).strip()
    return result or text


# ───────────────────────────── baza ─────────────────────────────────────────

_COLUMNS = ("display_name", "name_collected_at", "age", "age_group", "age_collected_at", "gender",
            "gender_source", "gender_confidence", "gender_collected_at", "goals", "goals_collected_at",
            "asked_name_at", "asked_age_at", "opted_out_at", "updated_at")


def _upsert_sql(columns: list[str]) -> str:
    for column in columns:
        if column not in _COLUMNS:
            raise ValueError(column)
    names = ", ".join(columns)
    values = ", ".join(f"${i}" for i in range(2, len(columns) + 2))
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns)
    return (f"INSERT INTO customer_portrait (user_id, {names}) VALUES ($1, {values}) "
            f"ON CONFLICT (user_id) DO UPDATE SET {updates}")


async def get(user_id: int) -> dict | None:
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        row = await conn.fetchrow("SELECT * FROM customer_portrait WHERE user_id = $1", user_id)
    return dict(row) if row else None


async def is_opted_out(user_id: int, conn=None) -> bool:
    async def _check(c) -> bool:
        await _ensure(c)
        return bool(await c.fetchval(
            "SELECT 1 FROM customer_portrait WHERE user_id = $1 AND opted_out_at IS NOT NULL", user_id))
    if conn is not None:
        return await _check(conn)
    async with database.pool.acquire() as c:
        return await _check(c)


async def save(user_id: int, *, name=None, age=None, goals=None, stated_gender: str | None = None,
               telegram_name: str | None = None) -> dict:
    """AI vositasi (portret_yoz) chaqiradi. {"saved": [maydonlar], "opted_out": bool}.
    Yaroqsiz qiymat — Invalid."""
    name = clean_name(name) if name not in (None, "") else None
    age = clean_age(age) if age not in (None, "") else None
    goals = clean_goals(goals)
    if stated_gender not in (None, "m", "f"):
        raise Invalid("jins faqat mijoz o'zi aytgan bo'lsa: erkak yoki ayol")
    if not (name or age is not None or goals or stated_gender):
        raise Invalid("saqlanadigan narsa yo'q")
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM customer_portrait WHERE user_id = $1 FOR UPDATE", user_id)
            current = dict(row) if row else {}
            if current.get("opted_out_at"):
                return {"saved": [], "opted_out": True}
            changes = plan_changes(current, name=name, age=age, goals=goals,
                                   stated_gender=stated_gender, telegram_name=telegram_name)
            if changes:
                columns = list(changes)
                await conn.execute(_upsert_sql(columns), user_id, *[changes[c] for c in columns])
    saved = [field for field, column in (("name", "display_name"), ("age", "age"), ("goals", "goals"),
                                         ("gender", "gender")) if column in changes]
    return {"saved": saved, "opted_out": False}


async def claim_question(user_id: int) -> str | None:
    """Shu xabarda so'rash mumkin bo'lgan maydon ('name' / 'age') yoki None.
    Qaytarilgan maydon shu zahoti 'so'raldi' deb yoziladi — keyin hech qachon
    qayta berilmaydi, mijoz javob bermasa ham."""
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM customer_portrait WHERE user_id = $1 FOR UPDATE", user_id)
            field = pick_question(dict(row) if row else None)
            if field is None:
                return None
            column = f"asked_{field}_at"
            await conn.execute(
                f"INSERT INTO customer_portrait (user_id, {column}) VALUES ($1, $2) "
                f"ON CONFLICT (user_id) DO UPDATE SET {column} = "
                f"COALESCE(customer_portrait.{column}, EXCLUDED.{column})",
                user_id, _utcnow())
    return field


async def forget(user_id: int) -> dict:
    """/malumotlarim -> o'chirish: portret maydonlari bo'shatiladi, AI suhbat
    eslatmalari (ai_memory) o'chadi va mijoz yig'ishdan chiqariladi."""
    now = _utcnow()
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        await conn.execute(
            """INSERT INTO customer_portrait (user_id, opted_out_at, updated_at) VALUES ($1, $2, $2)
               ON CONFLICT (user_id) DO UPDATE SET
                   display_name = NULL, name_collected_at = NULL,
                   age = NULL, age_group = NULL, age_collected_at = NULL,
                   gender = 'unknown', gender_source = NULL, gender_confidence = NULL,
                   gender_collected_at = NULL, goals = '{}', goals_collected_at = NULL,
                   opted_out_at = EXCLUDED.opted_out_at, updated_at = EXCLUDED.updated_at""",
            user_id, now)
    import ai_memory
    notes = await ai_memory.forget(user_id)
    return {"notes": notes}


async def clear(user_id: int) -> None:
    """Admin /ai_mijoz_unut: portret butunlay o'chadi (so'raldi belgilari ham).
    Mijozning o'zi o'chirgani (opted_out_at) saqlanib qoladi — yig'ilmasin."""
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        await conn.execute(
            "DELETE FROM customer_portrait WHERE user_id = $1 AND opted_out_at IS NULL", user_id)


async def resume(user_id: int) -> None:
    """Mijoz o'zi yig'ishni qayta yoqdi (/malumotlarim)."""
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        await conn.execute(
            "UPDATE customer_portrait SET opted_out_at = NULL, updated_at = $2 WHERE user_id = $1",
            user_id, _utcnow())


# ─────────────────────── AI ga beriladigan qism ─────────────────────────────

_GENDER_UZ = {"m": "erkak", "f": "ayol"}
_SOURCE_UZ = {"name": "ismdan", "stated": "o'zi aytgan"}


def goal_labels(goals, lang: str = "uz") -> list[str]:
    index = 1 if lang == "ru" else 0
    return [GOALS[g][index] for g in goals or [] if g in GOALS]


def profile_lines(portrait: dict | None, admin: bool = False) -> list[str]:
    """[MIJOZ XOTIRASI] ga qo'shiladigan qatorlar. Jins AI ga berilmaydi
    (faqat admin ko'rinishida) — murojaat ism bilan, jinsga bog'liq so'zsiz."""
    if not portrait:
        return []
    if portrait.get("opted_out_at"):
        return ["PORTRET: mijoz o'z ma'lumotlarini o'chirgan — ism, yosh yoki maqsadini so'rama va "
                "portret_yoz ni chaqirma."]
    parts = []
    name = portrait.get("display_name")
    if name:
        parts.append(f"murojaat ismi «{name}» (o'zi aytgan)")
    if portrait.get("age") is not None:
        parts.append(f"yoshi {portrait['age']} ({portrait.get('age_group') or age_group(portrait['age'])})")
    if portrait.get("goals"):
        parts.append("maqsadi: " + ", ".join(goal_labels(portrait["goals"])))
    if admin and portrait.get("gender") in _GENDER_UZ:
        parts.append(f"jinsi: {_GENDER_UZ[portrait['gender']]} "
                     f"({_SOURCE_UZ.get(portrait.get('gender_source'), '?')}, "
                     f"ishonch {float(portrait.get('gender_confidence') or 0):.2f})")
    lines = []
    if parts:
        lines.append("PORTRET: " + " · ".join(parts) + ".")
    if name and not admin:
        lines.append(f"Mijozga «{name}» deb murojaat qilsang bo'ladi — ba'zan, tabiiy joyda, har xabarda "
                     "emas. Aka/opa kabi so'z qo'shma (o'zi shunday yozgan bo'lmasa).")
    if (portrait.get("age") is not None or portrait.get("goals")) and not admin:
        lines.append("Tavsiyani yoshi va maqsadiga moslashtir; buni har safar tilga olma.")
    return lines


# ───────────────────────────── /malumotlarim ────────────────────────────────

def _t(uz: str, ru: str, lang: str) -> str:
    if lang == "ru":
        return ru
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        return lat_to_cyr(uz)
    return uz


def _gender_label(gender: str | None, lang: str) -> str:
    return {"m": _t("erkak", "мужской", lang), "f": _t("ayol", "женский", lang)}.get(gender or "", "")


_SHOWN_NOTE_KINDS = ("interest", "note", "feedback")
NOTES_SHOWN = 8


def my_data_text(portrait: dict | None, notes: list[dict] | None, lang: str) -> str:
    """Mijozga: biz nima saqlaganmiz. HTML."""
    portrait = portrait or {}
    esc = html.escape
    if portrait.get("opted_out_at"):
        return _t("🔐 <b>Ma'lumotlaringiz</b>\n\n"
                  "Siz ma'lumotlaringizni o'chirgansiz. Biz siz haqingizda yangi ma'lumot "
                  "yig'mayapmiz va so'ramaymiz.\n\n"
                  "Buyurtmalaringiz tarixi do'kon hisobida qoladi.",
                  "🔐 <b>Ваши данные</b>\n\n"
                  "Вы удалили свои данные. Мы не собираем и не спрашиваем о вас новых сведений.\n\n"
                  "История заказов остаётся в учёте магазина.", lang)
    lines = [_t("🔐 <b>Siz haqingizda saqlaganlarimiz</b>", "🔐 <b>Что мы о вас храним</b>", lang), ""]
    rows = 0
    if portrait.get("display_name"):
        lines.append(_t("👤 Murojaat: ", "👤 Обращение: ", lang) + esc(portrait["display_name"]))
        rows += 1
    if portrait.get("age") is not None:
        group = portrait.get("age_group") or age_group(portrait["age"])
        lines.append(_t("🎂 Yosh: ", "🎂 Возраст: ", lang) + f"{portrait['age']} ({esc(group or '')})")
        rows += 1
    if portrait.get("gender") in ("m", "f"):
        source = (_t("ismingizdan taxmin", "предположение по имени", lang)
                  if portrait.get("gender_source") == "name"
                  else _t("o'zingiz aytgansiz", "указали вы", lang))
        lines.append(_t("🚻 Jins: ", "🚻 Пол: ", lang)
                     + f"{_gender_label(portrait['gender'], lang)} ({source})")
        rows += 1
    if portrait.get("goals"):
        lines.append(_t("🎯 Maqsadlar: ", "🎯 Цели: ", lang)
                     + esc(", ".join(goal_labels(portrait["goals"], lang))))
        rows += 1
    shown = [n for n in (notes or []) if n.get("kind") in _SHOWN_NOTE_KINDS]
    if shown:
        lines.append("")
        lines.append(_t("💬 Suhbatlardan eslatmalar:", "💬 Заметки из переписки:", lang))
        for note in shown[-NOTES_SHOWN:]:
            lines.append("• " + esc(str(note.get("text") or ""))[:160])
        if len(shown) > NOTES_SHOWN:
            lines.append(_t(f"…va yana {len(shown) - NOTES_SHOWN} ta",
                            f"…и ещё {len(shown) - NOTES_SHOWN}", lang))
        rows += 1
    if not rows:
        lines.append(_t("Hozircha siz haqingizda hech narsa saqlanmagan (buyurtmalar tarixidan tashqari).",
                        "Пока мы ничего о вас не храним (кроме истории заказов).", lang))
        return "\n".join(lines)
    lines += ["", _t("Bularni sizga to'g'ri murojaat qilish va mos tavsiya berish uchun saqlaymiz. "
                     "Xohlasangiz, hammasini o'chiramiz. Buyurtmalar tarixi do'kon hisobida qoladi.",
                     "Храним это, чтобы правильно к вам обращаться и подбирать рекомендации. "
                     "Если хотите, всё удалим. История заказов остаётся в учёте магазина.", lang)]
    return "\n".join(lines)


def my_data_keyboard(portrait: dict | None, notes: list[dict] | None, lang: str) -> InlineKeyboardMarkup | None:
    portrait = portrait or {}
    if portrait.get("opted_out_at"):
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
            text=_t("↩️ Yig'ishni qayta yoqish", "↩️ Снова разрешить", lang), callback_data="mydata:on")]])
    has_data = (portrait.get("display_name") or portrait.get("age") is not None
                or portrait.get("gender") in ("m", "f") or portrait.get("goals")
                or any(n.get("kind") in _SHOWN_NOTE_KINDS for n in notes or []))
    if not has_data:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=_t("🗑 Ma'lumotlarimni o'chirish", "🗑 Удалить мои данные", lang), callback_data="mydata:del")]])


def _confirm_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=_t("✅ Ha, o'chirilsin", "✅ Да, удалить", lang), callback_data="mydata:del_ok"),
        InlineKeyboardButton(text=_t("Bekor qilish", "Отмена", lang), callback_data="mydata:show"),
    ]])


async def _lang(user_id: int) -> str:
    try:
        return await database.get_user_language(user_id)
    except Exception:
        return "uz"


async def my_data_view(user_id: int, lang: str) -> tuple[str, InlineKeyboardMarkup | None]:
    import ai_memory
    portrait = await get(user_id)
    try:
        notes = await ai_memory.notes(user_id)
    except Exception:
        logger.warning("AI notes could not be read for %s", user_id, exc_info=True)
        notes = []
    return my_data_text(portrait, notes, lang), my_data_keyboard(portrait, notes, lang)


@router.message(Command("malumotlarim"), F.chat.type == "private")
async def cmd_my_data(message: Message):
    user_id = message.from_user.id
    lang = await _lang(user_id)
    try:
        text, keyboard = await my_data_view(user_id, lang)
    except Exception:
        logger.exception("My-data view failed for %s", user_id)
        await message.answer(_t("Hozir ochib bo'lmadi, birozdan keyin qayta urinib ko'ring.",
                                "Сейчас не получилось открыть, попробуйте чуть позже.", lang))
        return
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


async def _edit(callback: CallbackQuery, text: str, keyboard) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    except Exception:
        await callback.message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@router.callback_query(F.data.startswith("mydata:"))
async def cb_my_data(callback: CallbackQuery):
    user_id = callback.from_user.id
    lang = await _lang(user_id)
    action = callback.data.split(":", 1)[1]
    try:
        if action == "del":
            await _edit(callback, _t("Rostdan o'chiraylikmi? Murojaat ismi, yosh, maqsadlar va suhbatlardan "
                                     "eslatmalar o'chadi, keyin biz ularni boshqa yig'maymiz.",
                                     "Точно удалить? Удалятся обращение, возраст, цели и заметки из "
                                     "переписки, и мы больше не будем их собирать.", lang),
                        _confirm_keyboard(lang))
        elif action == "del_ok":
            await forget(user_id)
            _forget_session(user_id)
            await _edit(callback, _t("✅ O'chirildi. Endi bu ma'lumotlarni so'ramaymiz va yig'maymiz.",
                                     "✅ Удалено. Больше не будем спрашивать и собирать эти данные.", lang),
                        None)
        elif action == "on":
            await resume(user_id)
            text, keyboard = await my_data_view(user_id, lang)
            await _edit(callback, text, keyboard)
        else:
            text, keyboard = await my_data_view(user_id, lang)
            await _edit(callback, text, keyboard)
    except Exception:
        logger.exception("My-data action %s failed for %s", action, user_id)
        await callback.answer(_t("Xatolik — birozdan keyin qayta urinib ko'ring.",
                                 "Ошибка — попробуйте чуть позже.", lang), show_alert=True)
        return
    await callback.answer()


FORGOT_NOTE = ("[TIZIM: mijoz /malumotlarim orqali o'z ma'lumotlarini o'chirdi. Endi uni ismi bilan "
               "atama, ism, yosh yoki maqsadini so'rama, portret_yoz ni chaqirma va oldingi suhbatlardagi "
               "eslatmalarga tayanma.]")


def _forget_session(user_id: int) -> None:
    """Ochiq AI suhbati ham bilsin: ism bilan atamasin, qayta so'ramasin."""
    try:
        import ai_sales
        session = ai_sales._sessions.get(user_id)
        if session is not None:
            session.pop("address_name", None)
            session["portrait_done"] = True
            session["note"] = "\n".join(n for n in (session.get("note"), FORGOT_NOTE) if n)
    except Exception:
        logger.debug("AI session could not be updated for %s", user_id, exc_info=True)


# ───────────────────────────── kunlik hisobot ───────────────────────────────

_STATS_SQL = """
    SELECT
        COUNT(*) FILTER (WHERE (name_collected_at + INTERVAL '5 hours')::date = $1) AS name_today,
        COUNT(*) FILTER (WHERE (age_collected_at + INTERVAL '5 hours')::date = $1) AS age_today,
        COUNT(*) FILTER (WHERE gender_source = 'name'
                           AND (gender_collected_at + INTERVAL '5 hours')::date = $1) AS gender_name_today,
        COUNT(*) FILTER (WHERE gender_source = 'stated'
                           AND (gender_collected_at + INTERVAL '5 hours')::date = $1) AS gender_stated_today,
        COUNT(*) FILTER (WHERE (goals_collected_at + INTERVAL '5 hours')::date = $1) AS goals_today,
        COUNT(*) FILTER (WHERE (GREATEST(name_collected_at, age_collected_at, gender_collected_at,
                                         goals_collected_at) + INTERVAL '5 hours')::date = $1) AS people_today,
        COUNT(*) FILTER (WHERE (asked_name_at + INTERVAL '5 hours')::date = $1) AS asked_name_today,
        COUNT(*) FILTER (WHERE (asked_age_at + INTERVAL '5 hours')::date = $1) AS asked_age_today,
        COUNT(*) FILTER (WHERE display_name IS NOT NULL OR age IS NOT NULL
                           OR gender <> 'unknown' OR cardinality(goals) > 0) AS portraits,
        COUNT(*) FILTER (WHERE display_name IS NOT NULL) AS with_name,
        COUNT(*) FILTER (WHERE age IS NOT NULL) AS with_age,
        COUNT(*) FILTER (WHERE gender = 'f') AS female,
        COUNT(*) FILTER (WHERE gender = 'm') AS male,
        COUNT(*) FILTER (WHERE cardinality(goals) > 0) AS with_goals,
        COUNT(*) FILTER (WHERE opted_out_at IS NOT NULL) AS opted_out
    FROM customer_portrait
    WHERE user_id <> ALL($2::bigint[])
"""

_GOALS_SQL = """
    SELECT g AS goal, COUNT(*) AS n
    FROM customer_portrait, unnest(goals) AS g
    WHERE user_id <> ALL($1::bigint[]) AND opted_out_at IS NULL
    GROUP BY g ORDER BY n DESC, g
"""

_EXAMPLES_SQL = """
    SELECT display_name, age, gender, gender_source, goals
    FROM customer_portrait
    WHERE user_id <> ALL($2::bigint[]) AND opted_out_at IS NULL
      AND (GREATEST(name_collected_at, age_collected_at, gender_collected_at, goals_collected_at)
           + INTERVAL '5 hours')::date = $1
      AND (display_name IS NOT NULL OR age IS NOT NULL OR cardinality(goals) > 0)
    ORDER BY (display_name IS NOT NULL)::int + (age IS NOT NULL)::int
             + (cardinality(goals) > 0)::int + (gender <> 'unknown')::int DESC,
             updated_at DESC
    LIMIT $3
"""


async def collect(day: date) -> tuple[dict, list[dict], list[dict]]:
    excluded = _excluded_ids()
    async with database.pool.acquire() as conn:
        await _ensure(conn)
        stats = dict(await conn.fetchrow(_STATS_SQL, day, excluded))
        goals = [dict(r) for r in await conn.fetch(_GOALS_SQL, excluded)]
        examples = [dict(r) for r in await conn.fetch(_EXAMPLES_SQL, day, excluded, EXAMPLES)]
    return stats, goals, examples


def _pct(part: int, whole: int) -> str:
    return f"{round(100 * part / whole)}%" if whole else "0%"


def example_line(row: dict) -> str:
    """«Dilnoza, 28 yosh, ayol (ismdan), maqsad: ozish» — faqat birinchi so'z
    (ism), familiya va ID siz."""
    parts = [html.escape(name_gender.first_word(row.get("display_name"))) or "ismi aytilmagan"]
    if row.get("age") is not None:
        parts.append(f"{int(row['age'])} yosh")
    if row.get("gender") in _GENDER_UZ:
        parts.append(f"{_GENDER_UZ[row['gender']]} ({_SOURCE_UZ.get(row.get('gender_source'), '?')})")
    if row.get("goals"):
        parts.append("maqsad: " + html.escape(", ".join(goal_labels(row["goals"]))))
    return ", ".join(parts)


def report_text(day: date, stats: dict, goals: list[dict], examples: list[dict]) -> str:
    s = {k: int(v or 0) for k, v in stats.items()}
    total = s["portraits"]
    gender_today = f"{s['gender_name_today']}"
    if s["gender_stated_today"]:
        gender_today += f" (+{s['gender_stated_today']} o'zi aytgan)"
    lines = [
        f"🧑‍🤝‍🧑 <b>Mijoz portreti — {day:%d.%m.%Y}</b>",
        "",
        "<b>Bugun yig'ildi:</b>",
        f"👤 Ism — {s['name_today']}",
        f"🎂 Yosh — {s['age_today']}",
        f"🚻 Jins (ismdan) — {gender_today}",
        f"🎯 Maqsad — {s['goals_today']}",
        f"Bugun portreti to'ldirilgan mijozlar: <b>{s['people_today']}</b>",
        f"AI bugun so'radi: ism — {s['asked_name_today']}, yosh — {s['asked_age_today']}",
        "",
        f"<b>Jami:</b> {total} ta mijozning portreti bor",
    ]
    if total:
        with_gender = s["female"] + s["male"]
        top_goals = " · ".join(f"{html.escape(GOALS[g['goal']][0] if g['goal'] in GOALS else g['goal'])} "
                               f"{int(g['n'])}" for g in goals[:6])
        lines += [
            f"👤 Ism — {s['with_name']} ({_pct(s['with_name'], total)})",
            f"🎂 Yosh — {s['with_age']} ({_pct(s['with_age'], total)})",
            f"🚻 Jins — {with_gender} ({_pct(with_gender, total)}): ayol {s['female']} · erkak {s['male']}",
            f"🎯 Maqsad — {s['with_goals']} ({_pct(s['with_goals'], total)})"
            + (f": {top_goals}" if top_goals else ""),
        ]
    if s["opted_out"]:
        lines.append(f"🗑 Ma'lumotini o'chirganlar — {s['opted_out']}")
    lines.append("")
    if examples:
        lines.append("<b>Bugungi misollar:</b>")
        lines += [f"• {example_line(row)}" for row in examples[:EXAMPLES]]
    else:
        lines.append("Bugun yangi ma'lumot yig'ilmadi.")
    lines += ["", "<i>Adminlar va ichki akkauntlar hisobga olinmagan. Mijozlar ko'rishi va o'chirishi "
                  "mumkin: /malumotlarim</i>"]
    return "\n".join(lines)


def report_key(day: date) -> str:
    return f"portrait-report-{day.isoformat()}"


async def send_daily_report(bot: Bot, day: date | None = None) -> bool:
    """Bugungi hisobot hamma adminga, kuniga bir marta."""
    day = day or _now_tk().date()
    key = report_key(day)
    if not await database.claim_release_notes(key):
        return False
    try:
        text = report_text(day, *await collect(day))
    except Exception:
        logger.exception("Portrait report could not be built")
        await database.release_release_notes(key)
        return False
    import admin_mood
    sent = 0
    for admin_id in list(dict.fromkeys(ADMIN_IDS)):
        try:
            with admin_mood.quiet():
                await bot.send_message(admin_id, text, parse_mode="HTML")
            sent += 1
        except Exception as exc:
            logger.warning("Portrait report to admin %s failed: %s", admin_id, exc)
        await asyncio.sleep(SEND_DELAY)
    logger.info("Portrait report %s sent to %d admin(s)", day, sent)
    return True


def seconds_until_report(now: datetime) -> float:
    """Toshkent vaqti bo'yicha bugungi 23:30 gacha. 23:30–23:59 — darhol
    (bot shu oraliqda qayta ishga tushsa ham o'sha kechaning hisoboti ketadi;
    takrorini claim kaliti to'xtatadi)."""
    hour, minute = REPORT_AT
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if now >= target:
        return 0.0
    return (target - now).total_seconds()


async def report_loop(bot: Bot) -> None:
    if not REPORT_ENABLED:
        logger.info("Portrait report is off (PORTRAIT_REPORT=0)")
        return
    await asyncio.sleep(60)
    logger.info("Portrait report scheduled daily at %02d:%02d Asia/Tashkent", *REPORT_AT)
    while True:
        await asyncio.sleep(seconds_until_report(_now_tk()))
        try:
            await send_daily_report(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Portrait report failed")
        now = _now_tk()
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=5, microsecond=0)
        await asyncio.sleep(max(60.0, (tomorrow - now).total_seconds()))
