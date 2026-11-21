"""📞 Keto Shop Call Centre 1.0 — operator CRM (egasi, 2026-11-22).

«Keto_Shop_Call_Centre_1.0_Qollanma» hujjati asosida:
  * har bir qo'ng'iroq CRM yozuvi (sana, mijoz, telefon, kiruvchi/chiquvchi,
    davomiylik, 30+ soniya mazmunli, mahsulot, summa, holat, qayta aloqa
    sanasi, bog'langan buyurtma → yalpi foyda, operator);
  * kunlik reja 80 / 30 / 5 va kunlik hisobot;
  * oylik 100 ballik operatsion KPI va bonus pog'onalari;
  * Keto bilim bonusi (5 yo'nalish × 100 000);
  * yalpi foydadan komissiya (reja tasdiqlanmaguncha stavka yakuniy emas);
  * kichik maqsadlarga yetganda salyut + tabrik, kunlik reja to'lsa
    «Tashakkurnoma» (sahifa webapp/callcentre.html).

Kim ko'radi: config.OPERATOR_IDS (admins.role='operator') — faqat o'zini;
config.ADMIN_IDS — hamma operatorni, baholash va sozlamalarni.
Kirish: bot (/callcentre) → Telegram WebApp → initData. Android ilovasi
yasagan initData (ks_sid) bu yerda qabul qilinmaydi.

Yo'llar /api/ dan tashqarida (/cc/api/*): do'kon auth_middleware'i ilova
sessiyasini ham qabul qiladi, bu yerda esa faqat haqiqiy Telegram initData.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from aiohttp import web

import call_centre_content
import database
from config import ADMIN_IDS, BOT_TOKEN, OPERATOR_IDS
from phone_utils import normalize_uz_phone

logger = logging.getLogger(__name__)

TZ_OFFSET = timedelta(hours=5)          # Asia/Tashkent, UTC+5, DST yo'q

# ───────────────────────────── qoidalar (PDF) ────────────────────────────────

DEFAULT_SETTINGS = {
    "work_days": 22,            # oyiga ish kuni
    "daily_outbound": 80,       # chiquvchi qo'ng'iroq / kun
    "daily_meaningful": 30,     # 30+ soniyalik mazmunli suhbat / kun
    "daily_orders": 5,          # maqsadli buyurtma / kun
    "base_salary": 3_500_000,   # doimiy oylik maosh
}
SETTING_LIMITS = {
    "work_days": (1, 31),
    "daily_outbound": (1, 1000),
    "daily_meaningful": (1, 1000),
    "daily_orders": (1, 1000),
    "base_salary": (0, 100_000_000),
}

MEANINGFUL_SECONDS = 30

# KPI yo'nalishi → maksimal ball. Jami 100.
KPI_WEIGHTS = {"meaningful": 30, "orders": 50, "outbound": 10, "crm": 10}

# (minimal umumiy ball, oylik bonus) — yuqoridan pastga.
KPI_BONUS_TIERS = [(90, 1_000_000), (80, 750_000), (70, 500_000)]

# (yalpi foyda rejasi bajarilishi %, komissiya %) — yuqoridan pastga.
COMMISSION_TIERS = [(120, 2.5), (100, 2.0), (90, 1.5), (70, 1.0)]

KNOWLEDGE_AREAS = [
    ("asoslar", "Keto ovqatlanish asoslari"),
    ("gluten", "Keto va gluten-free farqi"),
    ("un", "Un mahsulotlari"),
    ("shirin", "Shirinlashtiruvchilar (eritritol, stevia, alluloza)"),
    ("amaliy", "Amaliy maslahat va mahsulot tanlash"),
]
KNOWLEDGE_KEYS = {k for k, _ in KNOWLEDGE_AREAS}
KNOWLEDGE_BONUS_EACH = 100_000

# CRM holatlari. «no_answer» — PDF jadvalida yo'q, lekin 11:00–11:30
# «javobsiz qo'ng'iroqlar» uchun kerak: terilgan, lekin ko'tarilmagan raqam.
STATUSES = {
    "sold": "✅ Sotildi",
    "thinking": "🤔 O'ylab ko'radi",
    "followup": "📅 Qayta aloqa",
    "declined": "🙅 Rad etdi",
    "no_answer": "📵 Javob bermadi",
}
CALL_TYPES = {"in", "out"}

# Ichki do'kon akkauntlari — qo'ng'iroq ro'yxatiga tushmaydi.
INTERNAL_USER_IDS = set(getattr(database, "LEADERBOARD_EXCLUDED_USER_IDS", set()))

# Kichik maqsadlar (kunlik). Oxirgisi — kunlik reja; u settingsdan olinadi.
MILESTONES = {
    "outbound": [10, 20, 40, 60],
    "meaningful": [5, 10, 20],
    "orders": [1, 3],
}


# ───────────────────────────── sof hisob-kitob ───────────────────────────────

def today_local(now: datetime | None = None) -> date:
    return ((now or datetime.utcnow()) + TZ_OFFSET).date()


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def month_range_utc(month: str) -> tuple[datetime, datetime]:
    """'2026-11' → [boshi, keyingi oy boshi) naive UTC, Toshkent kuni bo'yicha."""
    y, m = (int(x) for x in month.split("-"))
    start = datetime(y, m, 1)
    end = datetime(y + (m == 12), 1 if m == 12 else m + 1, 1)
    return start - TZ_OFFSET, end - TZ_OFFSET


def day_range_utc(d: date) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day) - TZ_OFFSET
    return start, start + timedelta(days=1)


def valid_month(raw: str | None) -> str | None:
    try:
        y, m = (raw or "").split("-")
        if len(y) == 4 and 1 <= int(m) <= 12 and 2020 <= int(y) <= 2100:
            return f"{int(y):04d}-{int(m):02d}"
    except ValueError:
        pass
    return None


def monthly_targets(settings: dict) -> dict:
    days = int(settings["work_days"])
    return {
        "outbound": int(settings["daily_outbound"]) * days,
        "meaningful": int(settings["daily_meaningful"]) * days,
        "orders": int(settings["daily_orders"]) * days,
    }


def kpi_points(actual: float, plan: float, weight: float) -> float:
    """(Amaldagi ÷ Rejadagi) × yo'nalish balli, maksimaldan oshmaydi.
    594/660×30 = 27; 99/110×50 = 45; 1584/1760×10 = 9."""
    if plan <= 0:
        return 0.0
    return round(min(float(weight), float(actual) / float(plan) * weight), 1)


def kpi_bonus(total: float) -> int:
    for floor, amount in KPI_BONUS_TIERS:
        if total >= floor:
            return amount
    return 0


def commission_rate(percent: float | None) -> float | None:
    """Reja bajarilishi % → komissiya %. Reja tasdiqlanmagan bo'lsa None."""
    if percent is None:
        return None
    for floor, rate in COMMISSION_TIERS:
        if percent >= floor:
            return rate
    return 0.0


def knowledge_bonus(passed) -> int:
    return KNOWLEDGE_BONUS_EACH * len(set(passed or []) & KNOWLEDGE_KEYS)


def kpi_summary(counts: dict, settings: dict, crm_score: float | None) -> dict:
    """counts: outbound / meaningful / orders (oy bo'yicha).
    crm_score: admin qo'ygan 0–10 (None — hali baholanmagan, 0 ball)."""
    targets = monthly_targets(settings)
    parts = {
        key: {"actual": int(counts.get(key, 0)), "plan": targets[key],
              "max": KPI_WEIGHTS[key],
              "points": kpi_points(counts.get(key, 0), targets[key], KPI_WEIGHTS[key])}
        for key in ("meaningful", "orders", "outbound")
    }
    crm = None if crm_score is None else max(0.0, min(10.0, float(crm_score)))
    parts["crm"] = {"actual": crm, "plan": 10, "max": KPI_WEIGHTS["crm"],
                    "points": round(crm or 0.0, 1)}
    total = round(sum(p["points"] for p in parts.values()), 1)
    return {"parts": parts, "total": total, "bonus": kpi_bonus(total),
            "crm_rated": crm is not None}


def earnings(settings: dict, kpi_total_bonus: int, passed, gross_profit: float,
             profit_plan: float | None) -> dict:
    percent = None
    if profit_plan and profit_plan > 0:
        percent = round(gross_profit / profit_plan * 100, 1)
    rate = commission_rate(percent)
    commission = round(gross_profit * rate / 100) if rate else 0
    base = int(settings["base_salary"])
    kb = knowledge_bonus(passed)
    return {
        "base": base,
        "kpi_bonus": kpi_total_bonus,
        "knowledge_bonus": kb,
        "gross_profit": round(gross_profit),
        "profit_plan": profit_plan,
        "plan_percent": percent,
        "commission_rate": rate,
        "commission": commission,
        "total": base + kpi_total_bonus + kb + commission,
    }


def is_meaningful(duration_sec: int, ticked: bool) -> bool:
    """30+ soniya VA operator «mazmunli» deb belgilagan (qisqa yoki bo'sh
    suhbat KPI emas — hujjatdagi qoida)."""
    return bool(ticked) and int(duration_sec or 0) >= MEANINGFUL_SECONDS


def crossed_milestones(before: dict, after: dict, settings: dict) -> list[dict]:
    """Saqlashdan oldingi va keyingi kunlik sonlar → bayram qilinadiganlar.
    Har biri: {kind: small|goal|record|certificate, metric, value}."""
    goals = {"outbound": int(settings["daily_outbound"]),
             "meaningful": int(settings["daily_meaningful"]),
             "orders": int(settings["daily_orders"])}
    out = []
    for metric, goal in goals.items():
        b, a = int(before.get(metric, 0)), int(after.get(metric, 0))
        if a <= b:
            continue
        for m in MILESTONES[metric]:
            if m < goal and b < m <= a:
                out.append({"kind": "small", "metric": metric, "value": m, "goal": goal})
        if b < goal <= a:
            out.append({"kind": "goal", "metric": metric, "value": goal, "goal": goal})
        elif metric == "orders" and b >= goal:
            # Rejadan keyingi har bir sotuv — rekord.
            out.append({"kind": "record", "metric": metric, "value": a, "goal": goal})

    def all_done(c):
        return all(int(c.get(k, 0)) >= g for k, g in goals.items())
    if all_done(after) and not all_done(before):
        out.append({"kind": "certificate", "metric": "day", "value": 1, "goal": 1})
    return out


def phone_tail(raw) -> str | None:
    """Oxirgi 9 raqam — har xil yozilgan raqamlarni solishtirish uchun."""
    p = normalize_uz_phone(raw) if isinstance(raw, str) else None
    return p[-9:] if p else None


def clean_text(value, limit: int = 300) -> str | None:
    if value is None:
        return None
    s = " ".join(str(value).split())[:limit]
    return s or None


def parse_call(body: dict) -> tuple[dict | None, str | None]:
    """Formadan kelgan qo'ng'iroq → (maydonlar, xato matni)."""
    call_type = body.get("call_type")
    if call_type not in CALL_TYPES:
        return None, "Qo'ng'iroq turini tanlang"
    status = body.get("status")
    if status not in STATUSES:
        return None, "Natijani tanlang"
    try:
        duration = int(float(body.get("duration_sec") or 0))
    except (TypeError, ValueError):
        return None, "Davomiylik — soniyalarda son"
    if not 0 <= duration <= 4 * 3600:
        return None, "Davomiylik 0–4 soat oralig'ida bo'lsin"
    raw_phone = clean_text(body.get("phone"), 40)
    phone = normalize_uz_phone(raw_phone) if raw_phone else None
    if raw_phone and not phone:
        return None, "Telefon raqami noto'g'ri (masalan: 90 123 45 67)"
    amount = body.get("order_amount")
    if amount in (None, ""):
        amount = None
    else:
        try:
            amount = float(str(amount).replace(" ", "").replace(",", ""))
        except ValueError:
            return None, "Summa — son"
        if amount < 0 or amount > 1_000_000_000:
            return None, "Summa noto'g'ri"
    order_id = body.get("order_id")
    if order_id in (None, ""):
        order_id = None
    else:
        try:
            order_id = int(str(order_id).lstrip("#"))
        except ValueError:
            return None, "Buyurtma raqami — son"
        if order_id <= 0:
            return None, "Buyurtma raqami noto'g'ri"
    follow = body.get("follow_up_on") or None
    if follow:
        try:
            follow = date.fromisoformat(str(follow)[:10])
        except ValueError:
            return None, "Qayta aloqa sanasi noto'g'ri"
    if status == "followup" and not follow:
        return None, "Qayta aloqa uchun sanani belgilang"
    if status == "sold" and not (amount or order_id):
        return None, "Sotuv uchun summa yoki buyurtma raqamini yozing"
    return {
        "call_type": call_type,
        "status": status,
        "duration_sec": duration,
        "meaningful": is_meaningful(duration, body.get("meaningful", True)),
        "customer_name": clean_text(body.get("customer_name"), 120),
        "phone": phone,
        "product": clean_text(body.get("product"), 200),
        "order_amount": amount,
        "order_id": order_id,
        "follow_up_on": follow,
        "note": clean_text(body.get("note"), 1000),
    }, None


def crm_fill_percent(calls: list[dict]) -> int:
    """CRM to'ldirilishi: javob berilgan qo'ng'iroqlarda ism, telefon va
    (sotuv/qayta aloqada) summa/sana bor ulushi. Admin bahosiga yordam."""
    relevant = [c for c in calls if c.get("status") != "no_answer"]
    if not relevant:
        return 100
    ok = 0
    for c in relevant:
        good = bool(c.get("customer_name")) and bool(c.get("phone"))
        if c.get("status") == "sold":
            good = good and bool(c.get("order_amount") or c.get("order_id"))
        if c.get("status") in ("followup", "thinking"):
            good = good and bool(c.get("follow_up_on"))
        ok += good
    return round(ok * 100 / len(relevant))


# ───────────────────────────── baza ──────────────────────────────────────────

async def ensure_schema() -> None:
    async with database.pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS cc_calls (
                id BIGSERIAL PRIMARY KEY,
                operator_id BIGINT NOT NULL,
                called_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                call_type TEXT NOT NULL,
                customer_name TEXT,
                phone TEXT,
                duration_sec INTEGER NOT NULL DEFAULT 0,
                meaningful BOOLEAN NOT NULL DEFAULT FALSE,
                product TEXT,
                order_amount DOUBLE PRECISION,
                status TEXT NOT NULL,
                follow_up_on DATE,
                follow_up_done BOOLEAN NOT NULL DEFAULT FALSE,
                order_id INTEGER,
                note TEXT,
                updated_at TIMESTAMP
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS cc_calls_op_time ON cc_calls (operator_id, called_at)")
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS cc_calls_followup ON cc_calls (operator_id, follow_up_on) "
            "WHERE follow_up_on IS NOT NULL AND NOT follow_up_done")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS cc_daily_reports (
                operator_id BIGINT NOT NULL,
                day DATE NOT NULL,
                learned TEXT,
                problems TEXT,
                submitted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (operator_id, day)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS cc_monthly (
                operator_id BIGINT NOT NULL,
                month TEXT NOT NULL,
                crm_score DOUBLE PRECISION,
                knowledge JSONB NOT NULL DEFAULT '[]'::jsonb,
                profit_plan DOUBLE PRECISION,
                note TEXT,
                updated_by BIGINT,
                updated_at TIMESTAMP,
                PRIMARY KEY (operator_id, month)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS cc_settings (
                id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                data JSONB NOT NULL DEFAULT '{}'::jsonb
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS cc_morning_sent (
                operator_id BIGINT NOT NULL,
                day DATE NOT NULL,
                PRIMARY KEY (operator_id, day)
            )
        """)


async def load_operators() -> None:
    ids = await database.get_operator_ids()
    OPERATOR_IDS.clear()
    OPERATOR_IDS.extend(i for i in ids if i not in ADMIN_IDS)
    if OPERATOR_IDS:
        logger.info("Loaded %d call-centre operator(s)", len(OPERATOR_IDS))


async def get_settings() -> dict:
    async with database.pool.acquire() as conn:
        raw = await conn.fetchval("SELECT data FROM cc_settings WHERE id = 1")
    data = json.loads(raw) if isinstance(raw, str) else (raw or {})
    out = dict(DEFAULT_SETTINGS)
    for k in DEFAULT_SETTINGS:
        if isinstance(data.get(k), (int, float)):
            out[k] = int(data[k])
    return out


async def save_settings(values: dict) -> dict:
    current = await get_settings()
    for k, (lo, hi) in SETTING_LIMITS.items():
        if k in values:
            v = int(float(values[k]))
            if not lo <= v <= hi:
                raise ValueError(k)
            current[k] = v
    async with database.pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO cc_settings (id, data) VALUES (1, $1::jsonb)
               ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data""",
            json.dumps(current))
    return current


_CALL_COLS = ("id, operator_id, called_at, call_type, customer_name, phone, duration_sec, "
              "meaningful, product, order_amount, status, follow_up_on, follow_up_done, "
              "order_id, note")


def _call_json(r) -> dict:
    d = dict(r)
    if isinstance(d.get("called_at"), datetime):
        d["called_at_local"] = (d["called_at"] + TZ_OFFSET).isoformat(timespec="minutes")
        d["called_at"] = d["called_at"].isoformat()
    if isinstance(d.get("follow_up_on"), date):
        d["follow_up_on"] = d["follow_up_on"].isoformat()
    return d


async def day_counts(operator_id: int, day: date) -> dict:
    start, end = day_range_utc(day)
    async with database.pool.acquire() as conn:
        r = await conn.fetchrow(
            """SELECT COUNT(*) FILTER (WHERE call_type = 'out') AS outbound,
                      COUNT(*) FILTER (WHERE call_type = 'in') AS inbound,
                      COUNT(*) FILTER (WHERE meaningful) AS meaningful,
                      COUNT(*) FILTER (WHERE status = 'sold') AS orders,
                      COUNT(*) FILTER (WHERE status = 'followup') AS followups,
                      COALESCE(SUM(order_amount) FILTER (WHERE status = 'sold'), 0) AS sales
                 FROM cc_calls
                WHERE operator_id = $1 AND called_at >= $2 AND called_at < $3""",
            operator_id, start, end)
    return {k: (float(v) if k == "sales" else int(v)) for k, v in dict(r).items()}


async def list_calls(operator_id: int, start: datetime, end: datetime, limit: int = 300) -> list[dict]:
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT {_CALL_COLS} FROM cc_calls
                 WHERE operator_id = $1 AND called_at >= $2 AND called_at < $3
                 ORDER BY called_at DESC LIMIT $4""",
            operator_id, start, end, limit)
    return [_call_json(r) for r in rows]


async def due_followups(operator_id: int, day: date) -> list[dict]:
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT {_CALL_COLS} FROM cc_calls
                 WHERE operator_id = $1 AND follow_up_on IS NOT NULL
                   AND NOT follow_up_done AND follow_up_on <= $2
                 ORDER BY follow_up_on, called_at""",
            operator_id, day)
    return [_call_json(r) for r in rows]


async def upcoming_followups(operator_id: int, day: date, limit: int = 30) -> list[dict]:
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            f"""SELECT {_CALL_COLS} FROM cc_calls
                 WHERE operator_id = $1 AND follow_up_on > $2 AND NOT follow_up_done
                 ORDER BY follow_up_on, called_at LIMIT $3""",
            operator_id, day, limit)
    return [_call_json(r) for r in rows]


async def order_owner(order_id: int) -> int | None:
    """Buyurtmani CRMda birinchi bo'lib biriktirgan operator."""
    async with database.pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT operator_id FROM cc_calls WHERE order_id = $1 ORDER BY called_at LIMIT 1",
            order_id)


async def order_brief(order_id: int) -> dict | None:
    async with database.pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT id, customer_name, phone, total, status, created_at FROM orders WHERE id = $1",
            order_id)
    if not r:
        return None
    d = dict(r)
    d["created_at"] = (d["created_at"] + TZ_OFFSET).isoformat(timespec="minutes") if d["created_at"] else None
    return d


async def insert_call(operator_id: int, fields: dict) -> dict:
    async with database.pool.acquire() as conn:
        r = await conn.fetchrow(
            f"""INSERT INTO cc_calls (operator_id, call_type, customer_name, phone, duration_sec,
                       meaningful, product, order_amount, status, follow_up_on, order_id, note)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                RETURNING {_CALL_COLS}""",
            operator_id, fields["call_type"], fields["customer_name"], fields["phone"],
            fields["duration_sec"], fields["meaningful"], fields["product"],
            fields["order_amount"], fields["status"], fields["follow_up_on"],
            fields["order_id"], fields["note"])
    return _call_json(r)


async def update_call(call_id: int, fields: dict) -> dict | None:
    async with database.pool.acquire() as conn:
        r = await conn.fetchrow(
            f"""UPDATE cc_calls SET call_type=$2, customer_name=$3, phone=$4, duration_sec=$5,
                       meaningful=$6, product=$7, order_amount=$8, status=$9, follow_up_on=$10,
                       order_id=$11, note=$12, updated_at=CURRENT_TIMESTAMP,
                       follow_up_done = CASE WHEN $10::date IS DISTINCT FROM follow_up_on
                                             THEN FALSE ELSE follow_up_done END
                 WHERE id = $1 RETURNING {_CALL_COLS}""",
            call_id, fields["call_type"], fields["customer_name"], fields["phone"],
            fields["duration_sec"], fields["meaningful"], fields["product"],
            fields["order_amount"], fields["status"], fields["follow_up_on"],
            fields["order_id"], fields["note"])
    return _call_json(r) if r else None


async def get_call(call_id: int) -> dict | None:
    async with database.pool.acquire() as conn:
        r = await conn.fetchrow(f"SELECT {_CALL_COLS} FROM cc_calls WHERE id = $1", call_id)
    return _call_json(r) if r else None


async def month_counts(operator_id: int, month: str) -> dict:
    """KPI uchun oy sonlari. Sotuv — CRMda «Sotildi»; bog'langan buyurtma
    bekor qilingan bo'lsa hisobga kirmaydi."""
    start, end = month_range_utc(month)
    async with database.pool.acquire() as conn:
        r = await conn.fetchrow(
            """SELECT COUNT(*) FILTER (WHERE c.call_type = 'out') AS outbound,
                      COUNT(*) FILTER (WHERE c.call_type = 'in') AS inbound,
                      COUNT(*) FILTER (WHERE c.meaningful) AS meaningful,
                      COUNT(*) FILTER (WHERE c.status = 'sold'
                                       AND COALESCE(o.status, '') <> 'cancelled') AS orders,
                      COALESCE(SUM(c.order_amount) FILTER (
                          WHERE c.status = 'sold' AND COALESCE(o.status, '') <> 'cancelled'), 0) AS sales
                 FROM cc_calls c
                 LEFT JOIN orders o ON o.id = c.order_id
                WHERE c.operator_id = $1 AND c.called_at >= $2 AND c.called_at < $3""",
            operator_id, start, end)
        calls = await conn.fetch(
            """SELECT customer_name, phone, status, order_amount, order_id, follow_up_on
                 FROM cc_calls WHERE operator_id = $1 AND called_at >= $2 AND called_at < $3""",
            operator_id, start, end)
    out = {k: (float(v) if k == "sales" else int(v)) for k, v in dict(r).items()}
    out["crm_fill"] = crm_fill_percent([dict(c) for c in calls])
    return out


async def gross_profit(operator_id: int, month: str) -> dict:
    """Operatorga biriktirilgan (birinchi biriktirgan — egasi), shu oyda
    tuzilgan va YETKAZILGAN buyurtmalar: tushum − mahsulot tannarxi (line_cost,
    hamma hisobotlardagi bitta qoida). Bekor/qaytarilgan kirmaydi."""
    start, end = month_range_utc(month)
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            """WITH owners AS (
                   SELECT DISTINCT ON (order_id) order_id, operator_id
                     FROM cc_calls WHERE order_id IS NOT NULL
                    ORDER BY order_id, called_at)
               SELECT o.id, o.total, o.items
                 FROM orders o JOIN owners w ON w.order_id = o.id
                WHERE w.operator_id = $1 AND o.status = 'delivered'
                  AND o.created_at >= $2 AND o.created_at < $3""",
            operator_id, start, end)
        cost_map = {r["id"]: r["cost_price"] or 0
                    for r in await conn.fetch("SELECT id, cost_price FROM products")}
    set_costs = await database.get_set_costs()
    revenue = cost = 0.0
    known = True
    for r in rows:
        try:
            items = json.loads(r["items"] or "[]")
        except Exception:
            items = []
        revenue += float(r["total"] or 0)
        for it in items:
            c, k = database.line_cost(it, cost_map, set_costs)
            cost += c
            known = known and k
    return {"orders": len(rows), "revenue": round(revenue), "cost": round(cost),
            "profit": round(revenue - cost), "cost_known": known}


async def get_monthly(operator_id: int, month: str) -> dict:
    async with database.pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT crm_score, knowledge, profit_plan, note FROM cc_monthly "
            "WHERE operator_id = $1 AND month = $2", operator_id, month)
    if not r:
        return {"crm_score": None, "knowledge": [], "profit_plan": None, "note": None}
    k = r["knowledge"]
    k = json.loads(k) if isinstance(k, str) else (k or [])
    return {"crm_score": r["crm_score"], "knowledge": [x for x in k if x in KNOWLEDGE_KEYS],
            "profit_plan": r["profit_plan"], "note": r["note"]}


async def save_monthly(operator_id: int, month: str, by: int, values: dict) -> dict:
    cur = await get_monthly(operator_id, month)
    if "crm_score" in values:
        v = values["crm_score"]
        cur["crm_score"] = None if v in (None, "") else max(0.0, min(10.0, float(v)))
    if "knowledge" in values:
        cur["knowledge"] = sorted(set(values["knowledge"] or []) & KNOWLEDGE_KEYS)
    if "profit_plan" in values:
        v = values["profit_plan"]
        cur["profit_plan"] = None if v in (None, "", 0) else max(0.0, float(v))
    if "note" in values:
        cur["note"] = clean_text(values["note"], 1000)
    async with database.pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO cc_monthly (operator_id, month, crm_score, knowledge, profit_plan,
                                       note, updated_by, updated_at)
               VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7,CURRENT_TIMESTAMP)
               ON CONFLICT (operator_id, month) DO UPDATE SET
                 crm_score=EXCLUDED.crm_score, knowledge=EXCLUDED.knowledge,
                 profit_plan=EXCLUDED.profit_plan, note=EXCLUDED.note,
                 updated_by=EXCLUDED.updated_by, updated_at=EXCLUDED.updated_at""",
            operator_id, month, cur["crm_score"], json.dumps(cur["knowledge"]),
            cur["profit_plan"], cur["note"], by)
    return cur


async def month_view(operator_id: int, month: str) -> dict:
    settings = await get_settings()
    counts = await month_counts(operator_id, month)
    monthly = await get_monthly(operator_id, month)
    kpi = kpi_summary(counts, settings, monthly["crm_score"])
    gp = await gross_profit(operator_id, month)
    money = earnings(settings, kpi["bonus"], monthly["knowledge"], gp["profit"],
                     monthly["profit_plan"])
    return {"month": month, "counts": counts, "kpi": kpi, "gross": gp, "money": money,
            "monthly": monthly, "targets": monthly_targets(settings)}


async def lookup_phone(raw: str) -> dict:
    tail = phone_tail(raw)
    if not tail:
        return {"phone": None}
    async with database.pool.acquire() as conn:
        orders = await conn.fetch(
            """SELECT id, customer_name, total, status, created_at, items
                 FROM orders
                WHERE right(regexp_replace(COALESCE(phone, ''), '[^0-9]', '', 'g'), 9) = $1
                ORDER BY created_at DESC LIMIT 20""", tail)
        calls = await conn.fetch(
            """SELECT called_at, status, note, product, operator_id FROM cc_calls
                WHERE right(COALESCE(phone, ''), 9) = $1 ORDER BY called_at DESC LIMIT 5""", tail)
    products: dict[str, int] = {}
    for o in orders:
        try:
            for it in json.loads(o["items"] or "[]"):
                name = it.get("name") or it.get("product_name")
                if name:
                    products[name] = products.get(name, 0) + 1
        except Exception:
            pass
    delivered = [o for o in orders if o["status"] == "delivered"]
    return {
        "phone": "+998" + tail,
        "name": next((o["customer_name"] for o in orders if o["customer_name"]), None),
        "orders": len(delivered),
        "spent": round(sum(float(o["total"] or 0) for o in delivered)),
        "last_order": (orders[0]["created_at"] + TZ_OFFSET).date().isoformat() if orders else None,
        "top_products": [n for n, _ in sorted(products.items(), key=lambda x: -x[1])[:4]],
        "calls": [{"at": (c["called_at"] + TZ_OFFSET).isoformat(timespec="minutes"),
                   "status": c["status"], "note": c["note"], "product": c["product"]}
                  for c in calls],
    }


async def call_leads(limit: int = 40) -> list[dict]:
    """«Kimga qo'ng'iroq qilay?» — 30+ kun xarid qilmagan, yetkazilgan
    buyurtmasi bor mijozlar; oxirgi 14 kunda CRMda qo'ng'iroq qilinganlar,
    ichki akkauntlar, xodimlar va B2B chiqariladi."""
    exclude = sorted(INTERNAL_USER_IDS | set(ADMIN_IDS) | set(OPERATOR_IDS))
    now = datetime.utcnow()
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT o.user_id,
                      (array_agg(o.customer_name ORDER BY o.created_at DESC))[1] AS name,
                      (array_agg(o.phone ORDER BY o.created_at DESC))[1] AS phone,
                      COUNT(*) AS orders, MAX(o.created_at) AS last_at,
                      SUM(o.total) AS spent
                 FROM orders o
                WHERE o.status = 'delivered' AND COALESCE(o.phone, '') <> ''
                  AND COALESCE(o.source, '') <> 'b2b'
                  AND NOT (o.user_id = ANY($1::bigint[]))
                GROUP BY o.user_id
               HAVING MAX(o.created_at) < $2
                ORDER BY COUNT(*) DESC, MAX(o.created_at) DESC
                LIMIT 400""",
            exclude, now - timedelta(days=30))
        recent = {r["t"] for r in await conn.fetch(
            "SELECT DISTINCT right(phone, 9) AS t FROM cc_calls "
            "WHERE phone IS NOT NULL AND called_at > $1", now - timedelta(days=14))}
    out = []
    for r in rows:
        tail = phone_tail(r["phone"])
        if not tail or tail in recent:
            continue
        out.append({"name": r["name"], "phone": "+998" + tail, "orders": int(r["orders"]),
                    "spent": round(float(r["spent"] or 0)),
                    "days": (now - r["last_at"]).days})
        if len(out) >= limit:
            break
    return out


# ───────────────────────────── HTTP ──────────────────────────────────────────

def _json(data, status: int = 200) -> web.Response:
    return web.json_response(data, status=status,
                             dumps=lambda o: json.dumps(o, default=str, ensure_ascii=False))


def role_of(user_id: int) -> str | None:
    if user_id in ADMIN_IDS:
        return "admin"
    if user_id in OPERATOR_IDS:
        return "operator"
    return None


def _auth(request: web.Request) -> tuple[int, str, dict] | web.Response:
    from webapp_server import _validate_init_data
    header = request.headers.get("Authorization", "")
    if not header.startswith("tma "):
        return _json({"error": "auth"}, 401)
    parsed = _validate_init_data(header[4:], BOT_TOKEN, allow_app=False)
    user = (parsed or {}).get("user")
    uid = user.get("id") if isinstance(user, dict) else None
    if not isinstance(uid, int) or isinstance(uid, bool):
        return _json({"error": "auth"}, 401)
    role = role_of(uid)
    if role is None:
        return _json({"error": "forbidden"}, 403)
    return uid, role, user


def _target(request: web.Request, uid: int, role: str) -> int | web.Response:
    """Kimning ma'lumoti: operator — faqat o'zi; admin — ?operator=."""
    raw = request.query.get("operator")
    if role != "admin" or not raw:
        return uid
    try:
        target = int(raw)
    except ValueError:
        return _json({"error": "operator"}, 400)
    if target != uid and target not in OPERATOR_IDS and target not in ADMIN_IDS:
        return _json({"error": "operator"}, 404)
    return target


async def _names(ids) -> dict[int, str]:
    ids = list({int(i) for i in ids})
    if not ids:
        return {}
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT user_id, full_name, username FROM users WHERE user_id = ANY($1::bigint[])", ids)
    names = {r["user_id"]: (r["full_name"] or (r["username"] and "@" + r["username"]) or str(r["user_id"]))
             for r in rows}
    return {i: names.get(i, str(i)) for i in ids}


async def page(request: web.Request):
    return web.FileResponse(Path(__file__).parent / "webapp" / "callcentre.html",
                            headers={"Cache-Control": "no-cache"})


async def api_dashboard(request: web.Request):
    auth = _auth(request)
    if isinstance(auth, web.Response):
        return auth
    uid, role, user = auth
    target = _target(request, uid, role)
    if isinstance(target, web.Response):
        return target
    today = today_local()
    month = valid_month(request.query.get("month")) or month_key(today)
    settings = await get_settings()
    start, end = day_range_utc(today)
    async with database.pool.acquire() as conn:
        report = await conn.fetchrow(
            "SELECT learned, problems, submitted_at FROM cc_daily_reports "
            "WHERE operator_id = $1 AND day = $2", target, today)
    body = {
        "me": {"id": uid, "role": role, "first_name": user.get("first_name") or ""},
        "operator": target,
        "today": today.isoformat(),
        "settings": settings,
        "statuses": STATUSES,
        "knowledge_areas": KNOWLEDGE_AREAS,
        "day": await day_counts(target, today),
        "calls": await list_calls(target, start, end),
        "due": await due_followups(target, today),
        "upcoming": await upcoming_followups(target, today),
        "report": dict(report) if report else None,
        "month": await month_view(target, month),
        "tiers": {"kpi": KPI_BONUS_TIERS, "commission": COMMISSION_TIERS},
        "fun": call_centre_content.as_payload(),
        "joke_of_day": call_centre_content.joke_of_day(today.toordinal()),
    }
    if role == "admin":
        staff = list(OPERATOR_IDS)
        names = await _names(staff + [uid, target])
        body["operators"] = [{"id": i, "name": names[i]} for i in staff]
        body["target_name"] = names.get(target)
    return _json(body)


async def _write_call(request: web.Request, call_id: int | None):
    auth = _auth(request)
    if isinstance(auth, web.Response):
        return auth
    uid, role, _ = auth
    try:
        body = await request.json()
    except Exception:
        return _json({"error": "Noto'g'ri so'rov"}, 400)
    fields, err = parse_call(body if isinstance(body, dict) else {})
    if err:
        return _json({"error": err}, 400)

    existing = None
    owner = uid
    if call_id is not None:
        existing = await get_call(call_id)
        if not existing or (existing["operator_id"] != uid and role != "admin"):
            return _json({"error": "Topilmadi"}, 404)
        owner = existing["operator_id"]

    if fields["order_id"]:
        order = await order_brief(fields["order_id"])
        if not order:
            return _json({"error": f"#{fields['order_id']} buyurtma topilmadi"}, 400)
        holder = await order_owner(fields["order_id"])
        if holder is not None and holder != owner:
            return _json({"error": "Bu buyurtma boshqa operatorga biriktirilgan"}, 409)
        if not fields["order_amount"]:
            fields["order_amount"] = float(order["total"] or 0)

    today = today_local()
    before = await day_counts(owner, today)
    call = await (update_call(call_id, fields) if call_id else insert_call(owner, fields))
    after = await day_counts(owner, today)
    settings = await get_settings()
    # Bayram faqat operatorning o'zi yozganda — admin tuzatishi salyut emas.
    party = crossed_milestones(before, after, settings) if owner == uid else []
    return _json({"call": call, "day": after, "celebrate": party})


async def api_call_create(request: web.Request):
    return await _write_call(request, None)


async def api_call_update(request: web.Request):
    try:
        call_id = int(request.match_info["id"])
    except ValueError:
        return _json({"error": "id"}, 400)
    return await _write_call(request, call_id)


async def api_call_delete(request: web.Request):
    auth = _auth(request)
    if isinstance(auth, web.Response):
        return auth
    uid, role, _ = auth
    try:
        call_id = int(request.match_info["id"])
    except ValueError:
        return _json({"error": "id"}, 400)
    call = await get_call(call_id)
    if not call:
        return _json({"error": "Topilmadi"}, 404)
    # Operator faqat o'zining BUGUNGI yozuvini o'chiradi — o'tgan kunlar KPI.
    if role != "admin":
        local_day = call.get("called_at_local", "")[:10]
        if call["operator_id"] != uid or local_day != today_local().isoformat():
            return _json({"error": "Faqat bugungi o'z yozuvingizni o'chira olasiz"}, 403)
    async with database.pool.acquire() as conn:
        await conn.execute("DELETE FROM cc_calls WHERE id = $1", call_id)
    return _json({"ok": True})


async def api_followup_done(request: web.Request):
    auth = _auth(request)
    if isinstance(auth, web.Response):
        return auth
    uid, role, _ = auth
    try:
        call_id = int(request.match_info["id"])
    except ValueError:
        return _json({"error": "id"}, 400)
    call = await get_call(call_id)
    if not call or (call["operator_id"] != uid and role != "admin"):
        return _json({"error": "Topilmadi"}, 404)
    async with database.pool.acquire() as conn:
        await conn.execute("UPDATE cc_calls SET follow_up_done = TRUE WHERE id = $1", call_id)
    return _json({"ok": True})


async def api_lookup(request: web.Request):
    auth = _auth(request)
    if isinstance(auth, web.Response):
        return auth
    return _json(await lookup_phone(request.query.get("phone", "")))


async def api_order(request: web.Request):
    auth = _auth(request)
    if isinstance(auth, web.Response):
        return auth
    try:
        order_id = int(request.match_info["id"])
    except ValueError:
        return _json({"error": "id"}, 400)
    order = await order_brief(order_id)
    if not order:
        return _json({"error": "Topilmadi"}, 404)
    holder = await order_owner(order_id)
    order["operator"] = holder
    return _json(order)


async def api_leads(request: web.Request):
    auth = _auth(request)
    if isinstance(auth, web.Response):
        return auth
    return _json({"leads": await call_leads()})


async def api_report(request: web.Request):
    auth = _auth(request)
    if isinstance(auth, web.Response):
        return auth
    uid, role, user = auth
    try:
        body = await request.json()
    except Exception:
        return _json({"error": "Noto'g'ri so'rov"}, 400)
    learned = clean_text(body.get("learned"), 500)
    problems = clean_text(body.get("problems"), 1500)
    if not learned:
        return _json({"error": "Bugun o'rganilgan mavzuni yozing"}, 400)
    today = today_local()
    async with database.pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO cc_daily_reports (operator_id, day, learned, problems)
               VALUES ($1, $2, $3, $4)
               ON CONFLICT (operator_id, day) DO UPDATE SET
                 learned = EXCLUDED.learned, problems = EXCLUDED.problems,
                 submitted_at = CURRENT_TIMESTAMP""",
            uid, today, learned, problems)
    counts = await day_counts(uid, today)
    settings = await get_settings()
    start, end = day_range_utc(today)
    calls = await list_calls(uid, start, end)
    text = report_text(user.get("first_name") or str(uid), today, counts, settings,
                       crm_fill_percent(calls), learned, problems)
    bot = request.app.get("bot")
    if bot is not None and role == "operator":
        for admin_id in list(ADMIN_IDS):
            try:
                await bot.send_message(admin_id, text, parse_mode="HTML")
            except Exception:
                pass
    return _json({"ok": True, "text": text})


def report_text(name: str, day: date, c: dict, s: dict, fill: int,
                learned: str | None, problems: str | None) -> str:
    import html
    sales = f"{int(c.get('sales', 0)):,}".replace(",", " ")
    lines = [
        f"📞 <b>Call Centre — kunlik hisobot</b> · {day.strftime('%d.%m.%Y')}",
        f"👤 {html.escape(name)}",
        "",
        f"📤 Chiquvchi qo'ng'iroqlar: <b>{c.get('outbound', 0)}</b> / {s['daily_outbound']}",
        f"💬 30+ soniyalik mazmunli: <b>{c.get('meaningful', 0)}</b> / {s['daily_meaningful']}",
        f"🛒 Buyurtmalar: <b>{c.get('orders', 0)}</b> / {s['daily_orders']}",
        f"📥 Kiruvchi: {c.get('inbound', 0)}",
        f"📅 Qayta qo'ng'iroqqa qo'yilgan: {c.get('followups', 0)}",
        f"💰 Sotuv summasi: {sales} so'm",
        f"🗂 CRM to'ldirilishi: {fill}%",
        "",
        f"📚 O'rganilgan mavzu: {html.escape(learned or '—')}",
        f"⚠️ Muammolar va izohlar: {html.escape(problems or '—')}",
    ]
    return "\n".join(lines)


async def api_monthly(request: web.Request):
    auth = _auth(request)
    if isinstance(auth, web.Response):
        return auth
    uid, role, _ = auth
    if role != "admin":
        return _json({"error": "Faqat admin baholaydi"}, 403)
    try:
        body = await request.json()
        operator = int(body["operator"])
        month = valid_month(body.get("month"))
        if not month:
            raise ValueError
        values = {k: body[k] for k in ("crm_score", "knowledge", "profit_plan", "note") if k in body}
        if "knowledge" in values and not isinstance(values["knowledge"], list):
            raise ValueError
        await save_monthly(operator, month, uid, values)
    except (KeyError, TypeError, ValueError):
        return _json({"error": "Noto'g'ri qiymat"}, 400)
    return _json(await month_view(operator, month))


async def api_settings(request: web.Request):
    auth = _auth(request)
    if isinstance(auth, web.Response):
        return auth
    _, role, _ = auth
    if role != "admin":
        return _json({"error": "Faqat admin"}, 403)
    try:
        body = await request.json()
        settings = await save_settings(body if isinstance(body, dict) else {})
    except (TypeError, ValueError):
        return _json({"error": "Qiymat chegaradan tashqarida"}, 400)
    return _json({"settings": settings})


def add_routes(app: web.Application) -> None:
    app.router.add_get("/callcentre", page)
    app.router.add_get("/cc/api/dashboard", api_dashboard)
    app.router.add_post("/cc/api/calls", api_call_create)
    app.router.add_post("/cc/api/calls/{id}", api_call_update)
    app.router.add_post("/cc/api/calls/{id}/delete", api_call_delete)
    app.router.add_post("/cc/api/followups/{id}/done", api_followup_done)
    app.router.add_get("/cc/api/lookup", api_lookup)
    app.router.add_get("/cc/api/order/{id}", api_order)
    app.router.add_get("/cc/api/leads", api_leads)
    app.router.add_post("/cc/api/report", api_report)
    app.router.add_post("/cc/api/monthly", api_monthly)
    app.router.add_post("/cc/api/settings", api_settings)
