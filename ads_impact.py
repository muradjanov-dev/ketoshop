"""
Reklama samarasi — Meta reklama sarfi bilan do'kon sotuvini yonma-yon qo'yadi.

meta_ads.py faqat Meta'ning o'z raqamlarini (sarf, ko'rsatish, klik) beradi.
Egasining savoli esa boshqa: "reklama sotuvni oshirdimi, qaysi video ishladi,
qaysi mahsulotga ta'sir qildi?" Shuning uchun bu modul Graph raqamlarini
bazadagi chakana sotuv bilan bir joyga yig'adi:

  • /reklama hisobotining pastida «💰 Sotuvga ta'siri» bloki — shu davrdagi
    buyurtma/tushum/yangi mijozlar, oldingi teng davr bilan taqqoslab;
  • 🎬 Videolar — har bir reklama: sarf, qamrov, ko'rishlar, bosish, xabar,
    bitta natija narxi va videoda ko'rsatilgan mahsulot sotuvi;
  • 📦 Mahsulotlar — davrda eng ko'p sotilgan va o'sgan/kamaygan mahsulotlar;
  • 📈 Bog'liqlik — kunma-kun sarf va sotuv, korrelyatsiya (umumiy va har
    bir video bo'yicha);
  • 🚀 Videodan keyin — har bir video boshlangan kundan oldingi va keyingi
    7 kun: buyurtma, o'rtacha chek, qaysi mahsulotlar ko'proq sotilgan.

Video qaysi mahsulot haqida ekanini bot reklama nomi va matnidan topadi
(mahsulot nomining birinchi ma'noli so'zi: "Eritritol", "Bodom", ...).
Bu — sabab-oqibat isboti emas, shuning uchun har ekranda taxminiy deb
yoziladi. Ulgurji (B2B) savdo va ichki akkauntlar hisobga olinmaydi —
database.get_sales_daily.

Hech narsa yubormaydi va yozmaydi — faqat o'qiydi. Token bo'lmasa (meta_ads
o'chiq) tugmalar ham ko'rinmaydi.
"""
import asyncio
import html
import logging
import math
import re
import time
from datetime import date, datetime, timedelta, timezone

import aiohttp
from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

import database
import meta_ads
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router()

TASHKENT_HOURS = 5.0
# Reklama hisobining vaqt zonasi Meta'da qotib qolgan (bizniki — America/
# Los_Angeles, UTC−7): Meta "kuni" Toshkentda 12:00 da boshlanadi. Sotuv
# oynalari va kunlari shu zonada olinadi, aks holda sarf va sotuv 12 soat
# siljib solishtiriladi.
TZ_TTL = 6 * 3600
CACHE_TTL = 120                 # tugmalar orasida yurganda Graph'ni qayta so'ramaslik
MIN_SPEND = 1.0                 # $1 dan kam sarflagan reklama solishtirilmaydi
MAX_ADS = 6

AD_FIELDS = ("ad_id,ad_name,spend,impressions,reach,inline_link_clicks,ctr,"
             "actions,video_thruplay_watched_actions")
DAILY_FIELDS = "ad_id,ad_name,spend,impressions,inline_link_clicks,actions"

MESSAGE_ACTIONS = {"onsite_conversion.messaging_conversation_started_7d"}
LEAD_ACTIONS = {"lead", "onsite_conversion.lead_grouped", "leadgen_grouped"}
VIEW_ACTIONS = {"video_view"}

# "Natija" — reklama nimaga optimallashtirilgan bo'lsa, o'shani sanaymiz.
RESULTS = (("messages", "xabar"), ("leads", "lead"), ("clicks", "bosish"),
           ("thruplays", "to'liq ko'rish"))

PREV_LABEL = {
    "today": "kecha shu vaqtgacha",
    "yesterday": "undan oldingi kun",
    "last_7d": "undan oldingi 7 kun",
    "last_30d": "undan oldingi 30 kun",
}
VIEWS = (("vid", "🎬 Videolar"), ("prd", "📦 Mahsulotlar"), ("cor", "📈 Bog'liqlik"),
         ("aft", "🚀 Videodan keyin"))
LAUNCH_WINDOW = 7               # video boshlanishidan oldingi va keyingi kunlar

# Mahsulot nomidagi bu so'zlar videoni mahsulotga bog'lashga yaramaydi.
STOP_WORDS = {
    "keto", "ketoshop", "shop", "set", "to'plam", "toplam", "mini", "maxi", "super",
    "organik", "organic", "natural", "tabiiy", "premium", "uchun", "bilan", "yangi",
    "new", "sale", "aksiya", "chegirma", "video", "reels", "post", "reklama",
    "кето", "набор", "новый", "для",
}
_UNIT_RE = re.compile(r"^(\d.*|gr|g|kg|ml|l|dona|sht|ta|gramm|г|гр|кг|мл|шт)$")
_APOS_RE = re.compile(r"[‘’`ʻʼ']")
_WORD_RE = re.compile(r"[\w']+")

_cache: dict[str, tuple[float, dict]] = {}
_tz_cache: tuple[float, float | None] = (0.0, None)


# ---------------------------------------------------------------- pure helpers

def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _action_sum(actions, wanted: set[str]) -> float:
    return sum(_f(a.get("value")) for a in actions or []
               if a.get("action_type") in wanted)


def ad_metrics(row: dict) -> dict:
    """Bitta Graph insight qatorini bot tushunadigan raqamlarga aylantiradi."""
    actions = row.get("actions") or []
    return {
        "id": row.get("ad_id"),
        "name": row.get("ad_name") or "—",
        "spend": _f(row.get("spend")),
        "impressions": _f(row.get("impressions")),
        "reach": _f(row.get("reach")),
        "clicks": _f(row.get("inline_link_clicks")),
        "ctr": _f(row.get("ctr")),
        "views": _action_sum(actions, VIEW_ACTIONS),
        "thruplays": sum(_f(a.get("value"))
                         for a in row.get("video_thruplay_watched_actions") or []),
        "messages": _action_sum(actions, MESSAGE_ACTIONS),
        "leads": _action_sum(actions, LEAD_ACTIONS),
    }


def pick_result(ads: list[dict]) -> tuple[str, str]:
    """Hamma reklama uchun bitta "natija" turi — har reklamaga boshqa o'lchov
    tanlansa, ularni bir-biri bilan solishtirib bo'lmaydi. Natija turi
    reklamalarning kamida 60% ida bo'lsa olinadi: bitta natijasiz reklama
    o'lchovni o'zgartirmaydi (u shunchaki yomon), lekin lead formali reklama
    va saytga o'tkazadigan Instagram boost aralash bo'lsa — umumiy o'lchov
    "bosish"."""
    spending = [a for a in ads if a.get("spend", 0) >= MIN_SPEND] or ads
    for key, label in RESULTS:
        if spending and sum(1 for a in spending if a.get(key, 0) > 0) / len(spending) >= 0.6:
            return key, label
    for key, label in RESULTS:
        if sum(a.get(key, 0) for a in ads) > 0:
            return key, label
    return "reach", "kishi"


def cost_per(ad: dict, key: str) -> float | None:
    n = ad.get(key) or 0
    return ad["spend"] / n if n and ad.get("spend") else None


def rank_ads(ads: list[dict], key: str) -> list[dict]:
    """Arzon natija beruvchi birinchi; natijasiz sarf eng oxirida."""
    def sort_key(a):
        c = cost_per(a, key)
        return (c is None, c if c is not None else -a["spend"])
    return sorted(ads, key=sort_key)


def pearson(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < 5 or n != len(ys):
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sxx * syy)


def best_lag(spend: list[float], metric: list[float]) -> tuple[float | None, int]:
    """Bir kunlik yoki ertasi kungi ta'sir — qaysi biri kuchliroq bo'lsa.
    Instagram'da odam videoni kechqurun ko'rib, ertasiga yozishi odatiy."""
    r0 = pearson(spend, metric)
    r1 = pearson(spend[:-1], metric[1:]) if len(spend) > 1 else None
    if r1 is not None and (r0 is None or r1 > r0 + 0.05):
        return r1, 1
    return r0, 0


def strength(r: float | None) -> str:
    if r is None:
        return "ma'lumot yetarli emas"
    if r >= 0.6:
        return "kuchli"
    if r >= 0.3:
        return "o'rtacha"
    if r > -0.3:
        return "sezilmadi"
    return "teskari"


def _norm(text: str) -> str:
    return _APOS_RE.sub("'", (text or "").lower())


def product_key(name: str) -> str | None:
    """Mahsulot nomining videoni tanib olishga yaraydigan birinchi so'zi:
    "Eritritol 500gr" → "eritritol", "Bodom uni 1kg" → "bodom"."""
    for word in _WORD_RE.findall(_norm(name)):
        word = word.strip("'")
        if len(word) >= 4 and word not in STOP_WORDS and not _UNIT_RE.match(word):
            return word
    return None


def build_families(catalog: dict) -> dict:
    """{product_id: family} va {family: [kalit so'zlar]} — bitta mahsulotning
    100gr, 500gr, 1kg qadoqlari bitta oila, chunki video ularni ajratmaydi."""
    of_product, keys = {}, {}
    for pid, p in catalog.items():
        fam = product_key(p.get("name") or "") or product_key(p.get("name_ru") or "")
        if not fam:
            continue
        of_product[pid] = fam
        bucket = keys.setdefault(fam, {fam})
        ru = product_key(p.get("name_ru") or "")
        if ru:
            bucket.add(ru)
    return {"of_product": of_product, "keys": keys}


def families_in_text(text: str, families: dict) -> list[str]:
    try:
        from translit import cyr_to_lat
        latin = cyr_to_lat(text or "")
    except Exception:
        latin = ""
    hay = _norm(text) + " " + _norm(latin)
    found = []
    for fam, keys in families["keys"].items():
        for key in keys:
            # Uzun so'z — o'zak (eritritolni, eritritoldan); qisqasi — butun so'z.
            tail = "" if len(key) >= 5 else r"(?![\w'])"
            if re.search(r"(?<![\w'])" + re.escape(key) + tail, hay):
                found.append(fam)
                break
    return found


def family_title(fam: str, catalog: dict, families: dict) -> str:
    """Oilaning odam o'qiydigan nomi — katalogdagi so'zning asl yozilishi."""
    for pid, f in families["of_product"].items():
        if f == fam:
            for word in _WORD_RE.findall(catalog[pid].get("name") or ""):
                if _norm(word).strip("'") == fam:
                    return word
    return fam.capitalize()


def totals(days: dict) -> dict:
    out = {"orders": 0, "revenue": 0.0, "new_users": 0, "ad_users": 0, "products": {}}
    for d in days.values():
        for k in ("orders", "revenue", "new_users", "ad_users"):
            out[k] += d.get(k, 0)
        for key, line in d.get("products", {}).items():
            t = out["products"].setdefault(key, {"name": line["name"], "qty": 0.0, "revenue": 0.0})
            t["qty"] += line["qty"]
            t["revenue"] += line["revenue"]
    return out


def family_qty(products: dict, fam: str, families: dict) -> float:
    return sum(p["qty"] for key, p in products.items()
               if families["of_product"].get(key) == fam)


def avg_check(t: dict) -> float:
    return t["revenue"] / t["orders"] if t.get("orders") else 0.0


def pct(cur: float, prev: float) -> float | None:
    if not prev:
        return None
    return (cur - prev) / prev * 100


def delta(cur: float, prev: float) -> str:
    p = pct(cur, prev)
    if p is None:
        return "yangi" if cur else "—"
    if abs(p) < 1:
        return "o'zgarmadi"
    return f"{'▲' if p > 0 else '▼'} {abs(p):.0f}%"


def som(x: float) -> str:
    x = x or 0
    if abs(x) >= 1_000_000:
        return f"{x / 1_000_000:.1f} mln".replace(".0 mln", " mln")
    return f"{x:,.0f}".replace(",", " ")


def num(x: float) -> str:
    return f"{x or 0:,.0f}".replace(",", " ")


def qty(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else f"{x:.1f}"


def usd(x: float) -> str:
    return f"${x:,.2f}".replace(",", " ")


def short(name: str, width: int = 40) -> str:
    name = (name or "—").strip()
    return html.escape(name if len(name) <= width else name[: width - 1] + "…")


# ---------------------------------------------------------------- windows

def today_in(tz_hours: float) -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=tz_hours)).date()


def tz_note(tz_hours: float) -> str:
    """Meta kuni Toshkent kuni bilan bir xil bo'lmasa — o'quvchiga aytamiz."""
    if tz_hours == TASHKENT_HOURS:
        return ""
    h = int((TASHKENT_HOURS - tz_hours) % 24)
    return f"Kunlar reklama hisobi vaqtida: Toshkent bo'yicha {h:02d}:00 dan {h:02d}:00 gacha."


def preset_dates(preset: str, account_row: dict | None, today: date) -> tuple[date, date]:
    """Davrning mahalliy kunlari (ikkala chet ham kiradi). Graph qatori
    date_start/date_stop bersa — o'sha, chunki sarf aynan shu kunlarga tegishli."""
    if account_row and account_row.get("date_start") and account_row.get("date_stop"):
        try:
            return (date.fromisoformat(account_row["date_start"]),
                    date.fromisoformat(account_row["date_stop"]))
        except ValueError:
            pass
    return {
        "today": (today, today),
        "yesterday": (today - timedelta(days=1), today - timedelta(days=1)),
        "last_7d": (today - timedelta(days=7), today - timedelta(days=1)),
        "last_30d": (today - timedelta(days=30), today - timedelta(days=1)),
    }.get(preset, (today - timedelta(days=30), today))


def utc_window(first: date, last: date, now_utc: datetime,
               tz_hours: float = TASHKENT_HOURS) -> tuple[datetime, datetime]:
    """`tz_hours` zonasidagi kunlar → bazadagi naive-UTC [start, end). Bugungi
    kun hozirgi soatda tugaydi — oldingi davr ham xuddi shuncha uzun bo'lishi uchun."""
    shift = timedelta(hours=tz_hours)
    start = datetime.combine(first, datetime.min.time()) - shift
    end = datetime.combine(last + timedelta(days=1), datetime.min.time()) - shift
    return start, min(end, now_utc)


def prev_window(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """Xuddi shuncha uzun, butun kunlarga surilgan oldingi davr: bugun 14:00
    gacha → kecha 14:00 gacha (kechaning oxirgi 14 soati emas — kechqurungi
    buyurtmalar ertalabkiga teng kelmaydi)."""
    shift = timedelta(days=math.ceil((end - start) / timedelta(days=1)))
    return start - shift, end - shift


def _fmt_day(d: date) -> str:
    return d.strftime("%d.%m")


# ---------------------------------------------------------------- Graph + DB

async def _get_all(session, path: str, max_pages: int = 10, **params) -> list[dict]:
    data = await meta_ads._get(session, path, **params)
    rows = list(data.get("data", []))
    nxt, pages = (data.get("paging") or {}).get("next"), 1
    while nxt and pages < max_pages:
        async with session.get(nxt, timeout=aiohttp.ClientTimeout(total=45)) as resp:
            data = await resp.json(content_type=None)
        if isinstance(data, dict) and "error" in data:
            err = data["error"]
            raise meta_ads.GraphError(err.get("code"), err.get("message", "unknown"))
        rows += data.get("data", [])
        nxt, pages = (data.get("paging") or {}).get("next"), pages + 1
    return rows


async def _insights_all(session, max_pages: int = 10, **params) -> list[dict]:
    """act_*/insights hamma reklama hisoblari bo'yicha (meta_ads.account_ids):
    Ads Manager hisobi ham, Instagram ilovasidan boost qilinganlar turgan
    hisob ham. Bittasi o'qilmasa — qolganlari bilan; hammasi yiqilsa — xato."""
    ids = await meta_ads.account_ids(session)
    results = await asyncio.gather(
        *[_get_all(session, f"act_{a}/insights", max_pages=max_pages, **params) for a in ids],
        return_exceptions=True)
    rows, errors = [], []
    for acc, res in zip(ids, results):
        if isinstance(res, BaseException):
            logger.warning("Insights for act_%s failed: %s", acc, res)
            errors.append(res)
            continue
        rows += res
    if errors and len(errors) == len(ids):
        raise errors[0]
    return rows


async def _ad_texts(session) -> dict[str, str]:
    """{ad_id: nom + sarlavha + matn}. Ruxsat yetmasa — faqat nomlar bilan ishlaymiz."""
    rows = []
    for acc in await meta_ads.account_ids(session):
        try:
            rows += await _get_all(session, f"act_{acc}/ads", max_pages=3,
                                   fields="id,name,creative{title,body}", limit=100)
        except Exception:
            logger.warning("Ad creative texts unavailable for act_%s", acc, exc_info=True)
    out = {}
    for r in rows:
        c = r.get("creative") or {}
        out[str(r.get("id"))] = " ".join(x for x in (r.get("name"), c.get("title"), c.get("body")) if x)
    return out


async def account_tz_hours(session=None) -> float:
    """Reklama hisobining UTC siljishi (soat). Topilmasa — Toshkent."""
    global _tz_cache
    if not meta_ads.is_enabled():
        return TASHKENT_HOURS
    ts, hours = _tz_cache
    if hours is not None and time.monotonic() - ts < TZ_TTL:
        return hours
    try:
        if session is None:
            async with aiohttp.ClientSession() as own:
                data = await meta_ads._get(own, f"act_{meta_ads.AD_ACCOUNT_ID}",
                                           fields="timezone_offset_hours_utc")
        else:
            data = await meta_ads._get(session, f"act_{meta_ads.AD_ACCOUNT_ID}",
                                       fields="timezone_offset_hours_utc")
        hours = float(data["timezone_offset_hours_utc"])
    except Exception:
        logger.warning("Ad account timezone unavailable — using Tashkent", exc_info=True)
        return TASHKENT_HOURS
    _tz_cache = (time.monotonic(), hours)
    return hours


async def _usd_rate() -> float:
    try:
        import targets
        rate, _ = await targets.current_usd_rate()
        if rate:
            return rate
        state = await database.get_targets_state()
        return float(state.get("usd_rate") or 12800)
    except Exception:
        return 12800.0


def _cached(key: str):
    hit = _cache.get(key)
    return hit[1] if hit and time.monotonic() - hit[0] < CACHE_TTL else None


async def collect(preset: str) -> dict:
    """Videolar va mahsulotlar ekranlari uchun hamma narsa bitta joyda."""
    key = "period:" + preset
    if (hit := _cached(key)) is not None:
        return hit
    async with aiohttp.ClientSession() as session:
        account_rows, ad_rows, texts, tz = await asyncio.gather(
            _insights_all(session, fields="spend,impressions,reach,inline_link_clicks,actions",
                          date_preset=preset, level="account"),
            _insights_all(session, fields=AD_FIELDS, date_preset=preset, level="ad", limit=100),
            _ad_texts(session),
            account_tz_hours(session),
        )
    account = meta_ads.merge_account_rows(account_rows)
    first, last = preset_dates(preset, account, today_in(tz))
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    start, end = utc_window(first, last, now_utc, tz)
    p_start, p_end = prev_window(start, end)
    cur, prev = await asyncio.gather(database.get_sales_daily(start, end, tz),
                                     database.get_sales_daily(p_start, p_end, tz))
    families = build_families(cur["catalog"])
    ads = []
    for row in ad_rows:
        a = ad_metrics(row)
        a["families"] = families_in_text(texts.get(str(a["id"])) or a["name"], families)
        ads.append(a)
    data = {
        "preset": preset, "first": first, "last": last,
        "spend": _f(account.get("spend")) if account else 0.0,
        "ads": ads, "cur": totals(cur["days"]), "prev": totals(prev["days"]),
        "catalog": cur["catalog"], "families": families,
        "rate": await _usd_rate(), "prev_days": (p_end - p_start).days,
    }
    _cache[key] = (time.monotonic(), data)
    return data


def daily_range(preset: str, first: date | None, today: date) -> tuple[date, date]:
    """Kunlik bog'liqlik uchun kamida 30 kun kerak — 1 yoki 7 nuqtadan
    korrelyatsiya chiqmaydi. Bugun hisobga olinmaydi: yarim kun pastga tortadi."""
    last = today - timedelta(days=1)
    if preset == "maximum" and first:
        return max(first, today - timedelta(days=90)), last
    return today - timedelta(days=30), last


async def collect_daily(preset: str) -> dict:
    key = "daily:" + preset
    if (hit := _cached(key)) is not None:
        return hit
    first_seen = None
    async with aiohttp.ClientSession() as session:
        tz = await account_tz_hours(session)
        today = today_in(tz)
        if preset == "maximum":
            rows = await _insights_all(session, fields="spend", date_preset="maximum",
                                       level="account")
            starts = [r["date_start"] for r in rows if r.get("date_start")]
            if starts:
                first_seen = date.fromisoformat(min(starts))
        first, last = daily_range(preset, first_seen, today)
        import json
        time_range = json.dumps({"since": first.isoformat(), "until": last.isoformat()})
        ad_rows, texts = await asyncio.gather(
            _insights_all(session, max_pages=20, fields=DAILY_FIELDS, level="ad",
                          time_increment=1, time_range=time_range, limit=500),
            _ad_texts(session),
        )
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    # Sotuv LAUNCH_WINDOW kun oldinroqdan — oraliqdagi birinchi videoning ham
    # "oldingi haftasi" bo'lsin (🚀 Videodan keyin).
    start, end = utc_window(first - timedelta(days=LAUNCH_WINDOW), last, now_utc, tz)
    sales = await database.get_sales_daily(start, end, tz)
    families = build_families(sales["catalog"])
    dates = [first + timedelta(days=i) for i in range((last - first).days + 1)]
    per_ad: dict[str, dict] = {}
    for row in ad_rows:
        a = per_ad.setdefault(str(row.get("ad_id")), {
            "name": row.get("ad_name") or "—", "spend": {}, "total": 0.0})
        s = _f(row.get("spend"))
        a["spend"][row.get("date_start")] = a["spend"].get(row.get("date_start"), 0.0) + s
        a["total"] += s
    for ad_id, a in per_ad.items():
        a["families"] = families_in_text(texts.get(ad_id) or a["name"], families)
    data = {"preset": preset, "dates": dates, "ads": per_ad, "days": sales["days"],
            "catalog": sales["catalog"], "families": families, "rate": await _usd_rate(),
            # Oraliq 90 kunga qirqilgan bo'lsa, birinchi kuni "ko'ringan" video aslida
            # ancha oldin boshlangan bo'lishi mumkin — uning boshlanishi noma'lum.
            "capped": bool(first_seen and first > first_seen), "tz_hours": tz}
    _cache[key] = (time.monotonic(), data)
    return data


# ---------------------------------------------------------------- screens

async def sales_block(preset: str, account_row: dict | None) -> str:
    """/reklama hisobotining davomi: shu davrda do'kon nima sotdi."""
    tz = await account_tz_hours()
    first, last = preset_dates(preset, account_row, today_in(tz))
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    start, end = utc_window(first, last, now_utc, tz)
    p_start, p_end = prev_window(start, end)
    cur_raw, prev_raw = await asyncio.gather(database.get_sales_daily(start, end, tz),
                                             database.get_sales_daily(p_start, p_end, tz))
    cur, prev = totals(cur_raw["days"]), totals(prev_raw["days"])
    spend = _f(account_row.get("spend")) if account_row else 0.0
    rate = await _usd_rate() if spend else 0.0
    return format_sales_block(preset, first, last, cur, prev, spend, rate,
                              (p_end - p_start).days, tz)


def _prev_label(preset: str, prev_days: int) -> str:
    if preset == "maximum":
        return f"reklamadan oldingi {prev_days} kun"
    return PREV_LABEL.get(preset, "oldingi davr")


def sales_verdict(cur: dict, prev: dict, spend: float) -> str:
    p = pct(cur["orders"], prev["orders"])
    if not spend:
        return "ℹ️ Bu davrda reklamaga pul sarflanmagan."
    if p is None:
        return ("✅ Oldingi davrda buyurtma bo'lmagan, bu davrda — "
                f"{cur['orders']} ta." if cur["orders"] else
                "⚠️ Reklama ishlayapti, lekin hali buyurtma yo'q.")
    if p >= 10:
        return f"✅ Reklama davrida buyurtmalar oldingi davrdan <b>{p:.0f}% ko'p</b>."
    if p > -10:
        return "➖ Buyurtmalar deyarli o'zgarmadi — reklama hozircha sezilarli qo'shimcha sotuv bermayapti."
    return f"⚠️ Reklama ishlayapti, lekin buyurtmalar oldingi davrdan <b>{abs(p):.0f}% kam</b>."


def format_sales_block(preset, first, last, cur, prev, spend, rate, prev_days,
                       tz_hours: float = TASHKENT_HOURS) -> str:
    period = _fmt_day(first) if first == last else f"{_fmt_day(first)}–{_fmt_day(last)}"
    lines = ["", "━━━━━━━━━━━━", f"💰 <b>Sotuvga ta'siri</b> · {period}",
             sales_verdict(cur, prev, spend), ""]
    lines.append(f"🛒 Buyurtmalar: <b>{cur['orders']}</b> · oldin {prev['orders']} "
                 f"({delta(cur['orders'], prev['orders'])})")
    lines.append(f"💵 Tushum: <b>{som(cur['revenue'])}</b> so'm · oldin {som(prev['revenue'])} "
                 f"({delta(cur['revenue'], prev['revenue'])})")
    if cur["orders"] or prev["orders"]:
        lines.append(f"🧾 O'rtacha chek: <b>{som(avg_check(cur))}</b> so'm · oldin "
                     f"{som(avg_check(prev))} ({delta(avg_check(cur), avg_check(prev))})")
    lines.append(f"🙋 Botga yangi kelganlar: <b>{cur['new_users']}</b> · oldin {prev['new_users']} "
                 f"({delta(cur['new_users'], prev['new_users'])})")
    if cur["ad_users"] or prev["ad_users"]:
        lines.append(f"🔗 Reklama havolasidan: <b>{cur['ad_users']}</b> · oldin {prev['ad_users']}")
    if spend:
        lines.append(f"📣 Reklamaga: {usd(spend)} ≈ {som(spend * rate)} so'm")
        # Faqat O'SISH reklamaga yoziladi — reklamasiz ham bo'ladigan sotuv emas.
        extra = cur["orders"] - prev["orders"]
        if extra > 0:
            lines.append(f"🧮 Qo'shimcha {extra} ta buyurtma → biriga ≈ <b>{usd(spend / extra)}</b>")
        extra_rev = cur["revenue"] - prev["revenue"]
        if extra_rev > 0 and rate:
            lines.append(f"🧮 Qo'shimcha tushum {som(extra_rev)} so'm → reklamaga 1 so'm ≈ "
                         f"<b>{extra_rev / (spend * rate):.1f} so'm</b> qaytdi")
    note = tz_note(tz_hours)
    lines.append(f"<i>Taqqoslash: {_prev_label(preset, prev_days)}. "
                 "Ulgurji (B2B) va ichki akkauntlar hisobga olinmagan."
                 f"{' ' + note if note else ''}</i>")
    return "\n".join(lines)


def format_videos(data: dict) -> str:
    label = meta_ads.PRESETS[data["preset"]][0]
    ads = [a for a in data["ads"] if a["spend"] >= MIN_SPEND] or data["ads"]
    head = [f"🎬 <b>Videolar samarasi — {label}</b>", ""]
    if not ads:
        return "\n".join(head + ["Bu davrda reklama ko'rsatilmagan."])

    key, unit = pick_result(ads)
    ranked = rank_ads(ads, key)
    priced = [a for a in ranked if cost_per(a, key) is not None]
    best, worst = (priced[0], priced[-1]) if priced else (None, None)
    families, catalog = data["families"], data["catalog"]
    cur, prev = data["cur"]["products"], data["prev"]["products"]

    if best and len(priced) > 1:
        head.append(f"Eng arzon natija — «{short(best['name'])}»: 1 ta {unit} "
                    f"<b>{usd(cost_per(best, key))}</b>. Eng qimmati — «{short(worst['name'])}»: "
                    f"{usd(cost_per(worst, key))}.")
    elif best:
        head.append(f"1 ta {unit} narxi: <b>{usd(cost_per(best, key))}</b>.")
    else:
        head.append(f"⚠️ Reklamalar hali birorta ham {unit} bermagan.")
    head.append("")

    medals = ["🥇", "🥈", "🥉"]
    body = []
    for i, a in enumerate(ranked[:MAX_ADS]):
        mark = medals[i] if i < 3 and cost_per(a, key) is not None else "•"
        body.append(f"{mark} <b>{short(a['name'])}</b> · {meta_ads.source_tag(a['name'])}")
        body.append(f"💵 {usd(a['spend'])} · 👥 {num(a['reach'])} kishi ko'rdi")
        if a["views"]:
            tp = f" · {num(a['thruplays'])} tasi oxirigacha" if a["thruplays"] else ""
            body.append(f"▶️ {num(a['views'])} marta ko'rildi{tp}")
        extra = f" · 💬 {num(a['messages'])} xabar" if a["messages"] else ""
        if a["leads"]:
            extra += f" · 🎯 {num(a['leads'])} lead"
        body.append(f"🖱 {num(a['clicks'])} bosish (CTR {a['ctr']:.1f}%){extra}")
        c = cost_per(a, key)
        body.append(f"🏷 1 ta {unit}: <b>{usd(c)}</b>" if c else f"🏷 {unit.capitalize()} yo'q")
        for fam in a["families"][:2]:
            now_q, was_q = family_qty(cur, fam, families), family_qty(prev, fam, families)
            body.append(f"📦 Videoda: {html.escape(family_title(fam, catalog, families))} — "
                        f"{qty(now_q)} dona sotildi (oldin {qty(was_q)}, {delta(now_q, was_q)})")
        body.append("")

    todo = []
    if best and len(priced) > 1:
        todo.append(f"«{short(best['name'])}» byudjetini oshiring — natija eng arzon.")
        if cost_per(worst, key) >= 2 * cost_per(best, key):
            ratio = cost_per(worst, key) / cost_per(best, key)
            todo.append(f"«{short(worst['name'])}» ni to'xtating yoki yangi video bilan "
                        f"almashtiring — natija {ratio:.0f} marta qimmat.")
    for a in ranked:
        if cost_per(a, key) is None and a["spend"] >= 3:
            todo.append(f"«{short(a['name'])}» {usd(a['spend'])} sarfladi, lekin {unit} yo'q — to'xtating.")
            break
    if len(ads) == 1:
        todo.append("Bitta video ishlayapti — solishtirish uchun 2-3 xil video qo'ying (har biri boshqa mahsulot haqida).")
    low = _low_stock_advertised(ads, data)
    if low:
        todo.append(low)
    if any(not a["families"] for a in ads):
        todo.append("Reklama nomiga mahsulot nomini yozing (masalan «Eritritol video 1») — "
                    "bot shu orqali videoni mahsulot sotuvi bilan bog'laydi.")
    return fit("\n".join(head + body + _todo(todo)))


def _low_stock_advertised(ads: list[dict], data: dict) -> str | None:
    fams = {f for a in ads for f in a["families"]}
    for pid, fam in data["families"]["of_product"].items():
        p = data["catalog"].get(pid) or {}
        if fam in fams and (p.get("quantity") or 0) < 10 and pid in data["cur"]["products"]:
            return (f"«{html.escape(p.get('name') or '—')}» omborda {p.get('quantity') or 0} ta qoldi — "
                    "reklama ishlayotganda tugab qolmasin.")
    return None


def fit(text: str, limit: int = 4000) -> str:
    """Telegram 4096 belgidan uzun xabarni rad etadi — oxirgi qatorlarni qirqamiz."""
    if len(text) <= limit:
        return text
    return text[:limit].rsplit("\n", 1)[0] + "\n…"


def _todo(items: list[str]) -> list[str]:
    if not items:
        return []
    return ["<b>NIMA QILISH KERAK</b>"] + [f"{i}. {t}" for i, t in enumerate(items, 1)]


def product_changes(cur: dict, prev: dict, of_product: dict, advertised: set) -> list[dict]:
    rows = []
    for key in set(cur) | set(prev):
        now_q = cur.get(key, {}).get("qty", 0.0)
        was_q = prev.get(key, {}).get("qty", 0.0)
        rows.append({"key": key, "name": (cur.get(key) or prev.get(key))["name"],
                     "now": now_q, "was": was_q,
                     "revenue": cur.get(key, {}).get("revenue", 0.0),
                     "ad": of_product.get(key) in advertised})
    return rows


def grew(rows: list[dict], limit: int = 5) -> list[dict]:
    """Kamida +2 dona va +30% — bitta tasodifiy buyurtma "o'sish" bo'lmasin."""
    return sorted([r for r in rows if r["now"] - r["was"] >= 2 and
                   (not r["was"] or r["now"] / r["was"] >= 1.3)],
                  key=lambda r: r["now"] - r["was"], reverse=True)[:limit]


def format_products(data: dict) -> str:
    label = meta_ads.PRESETS[data["preset"]][0]
    cur, prev = data["cur"]["products"], data["prev"]["products"]
    families = data["families"]
    advertised = {f for a in data["ads"] if a["spend"] >= MIN_SPEND for f in a["families"]}
    lines = [f"📦 <b>Mahsulotlar — {label}</b>", ""]
    if not cur:
        return "\n".join(lines + ["Bu davrda chakana sotuv bo'lmagan."])

    rows = product_changes(cur, prev, families["of_product"], advertised)
    growing = grew(rows)
    falling = sorted([r for r in rows if r["was"] - r["now"] >= 2 and r["now"] <= 0.7 * r["was"]],
                     key=lambda r: r["was"] - r["now"], reverse=True)[:3]

    if growing:
        lines.append("Eng ko'p o'sgan: " + ", ".join(
            f"{html.escape(r['name'])} ({delta(r['now'], r['was'])})" for r in growing[:3]) + ".")
    else:
        lines.append("Hech bir mahsulot sotuvi oldingi davrga nisbatan sezilarli o'smadi.")
    lines += ["", "🔝 <b>Eng ko'p sotilgan</b>"]
    top = sorted([r for r in rows if r["now"]], key=lambda r: r["revenue"], reverse=True)[:10]
    for i, r in enumerate(top, 1):
        lines.append(f"{i}. {html.escape(r['name'])} — {qty(r['now'])} dona · {som(r['revenue'])} "
                     f"(oldin {qty(r['was'])}, {delta(r['now'], r['was'])}){' 🎬' if r['ad'] else ''}")
    if growing:
        lines += ["", "📈 <b>Ko'proq sotila boshlagan</b>"]
        lines += [f"• {html.escape(r['name'])}: {qty(r['was'])} → {qty(r['now'])} dona"
                  f"{' 🎬' if r['ad'] else ''}" for r in growing]
    if falling:
        lines += ["", "📉 <b>Kamaygan</b>"]
        lines += [f"• {html.escape(r['name'])}: {qty(r['was'])} → {qty(r['now'])} dona" for r in falling]
    if advertised:
        lines += ["", "🎬 — reklama videosida ko'rsatilgan mahsulot"]
    lines.append("")

    todo = []
    for r in growing:
        stock = (data["catalog"].get(r["key"]) or {}).get("quantity")
        if stock is not None and stock < r["now"]:
            todo.append(f"«{html.escape(r['name'])}» tez sotilyapti, omborda {stock} ta — "
                        "buyurtma bering.")
            break
    not_ad = [r for r in growing if not r["ad"]]
    if not_ad and advertised:
        todo.append(f"«{html.escape(not_ad[0]['name'])}» reklamasiz ham o'smoqda — "
                    "keyingi video uchun yaxshi nomzod.")
    flat = [f for f in advertised
            if family_qty(cur, f, families) <= family_qty(prev, f, families)]
    if flat:
        title = family_title(flat[0], data["catalog"], families)
        todo.append(f"«{html.escape(title)}» videoda bor, lekin sotuvi o'smadi — "
                    "videoni yoki taklifni (narx, sovg'a) o'zgartirib ko'ring.")
    lines += _todo(todo)
    lines.append("<i>Ulgurji (B2B), sovg'a va aksiya bonuslari hisobga olinmagan.</i>")
    return fit("\n".join(lines))


def _series(data: dict, getter) -> list[float]:
    return [float(getter(data["days"].get(d.isoformat(), {}))) for d in data["dates"]]


def _family_series(data: dict, fam: str) -> list[float]:
    of = data["families"]["of_product"]
    return _series(data, lambda d: sum(p["qty"] for k, p in d.get("products", {}).items()
                                       if of.get(k) == fam))


def format_correlation(data: dict) -> str:
    dates = data["dates"]
    spend = [sum(a["spend"].get(d.isoformat(), 0.0) for a in data["ads"].values()) for d in dates]
    orders = _series(data, lambda d: d.get("orders", 0))
    users = _series(data, lambda d: d.get("new_users", 0))
    revenue = _series(data, lambda d: d.get("revenue", 0))
    head = [f"📈 <b>Reklama va sotuv — kunma-kun</b> · {_fmt_day(dates[0])}–{_fmt_day(dates[-1])} "
            f"({len(dates)} kun)", ""]

    active = [s for s in spend if s > 0]
    if len(active) < 5:
        return "\n".join(head + ["Ma'lumot yetarli emas: reklama kamida 5-7 kun ishlagan "
                                 "bo'lishi kerak. «Butun davr»ni tanlab ko'ring."])

    r_users, lag_u = best_lag(spend, users)
    r_orders, lag_o = best_lag(spend, orders)
    r_rev, lag_r = best_lag(spend, revenue)
    mean = sum(active) / len(active)
    steady = (math.sqrt(sum((s - mean) ** 2 for s in active) / len(active)) / mean < 0.15
              and len(active) == len(spend))
    best_r = max(r for r in (r_orders, r_users, 0.0) if r is not None)
    if steady:
        head.append("ℹ️ Reklama har kuni bir xil byudjet bilan ishlagan — kunlik bog'liqlikni "
                    "o'lchab bo'lmaydi. «Butun davr» bo'yicha reklamadan oldin/keyin solishtiring.")
    elif best_r >= 0.6:
        head.append("✅ Reklama ishlayapti: sarf oshgan kunlari sotuv ham oshgan.")
    elif best_r >= 0.3:
        head.append("🟡 Reklama sotuvga qisman ta'sir qilyapti.")
    else:
        head.append("⚠️ Reklama sarfi va sotuv o'rtasida bog'liqlik sezilmadi.")
    head.append("")

    table = [f"{'Kun':<5} {'Sarf':>5} {'Yangi':>5} {'Buyurt':>6} {'Tushum':>8}"]
    for i in range(len(dates) - 1, max(-1, len(dates) - 15), -1):
        table.append(f"{_fmt_day(dates[i])} {spend[i]:>4.0f}$ {users[i]:>5.0f} {orders[i]:>6.0f} "
                     f"{som(revenue[i]):>8}")
    body = ["<pre>" + html.escape("\n".join(table)) + "</pre>", "",
            "<b>Bog'liqlik</b> (1 — to'liq, 0 — yo'q)"]
    for title, r, lag in (("yangi mijozlar", r_users, lag_u), ("buyurtmalar", r_orders, lag_o),
                          ("tushum", r_rev, lag_r)):
        tail = ", ta'siri ertasi kuni" if lag and r is not None and r >= 0.3 else ""
        body.append(f"• Sarf ↔ {title}: {strength(r)}"
                    f"{f' ({r:.2f})' if r is not None else ''}{tail}")

    ad_lines, todo = [], []
    top_products = sorted(
        {fam for fam in data["families"]["keys"]},
        key=lambda f: -sum(_family_series(data, f)))[:15]
    for ad_id, a in sorted(data["ads"].items(), key=lambda kv: -kv[1]["total"])[:MAX_ADS]:
        if a["total"] < MIN_SPEND:
            continue
        ad_spend = [a["spend"].get(d.isoformat(), 0.0) for d in dates]
        if sum(1 for s in ad_spend if s > 0) < 3:
            continue
        r_o, _ = best_lag(ad_spend, orders)
        if r_o is None:             # har kuni bir xil sarf — solishtiradigan narsa yo'q
            ad_lines.append(f"• «{short(a['name'], 32)}» — har kuni bir xil sarf, o'lchab bo'lmaydi")
            continue
        parts = [f"buyurtmalar: {strength(r_o)} ({r_o:.2f})"]
        named = a["families"]
        candidates = named or [f for f in top_products
                               if sum(1 for x in _family_series(data, f) if x) >= 3]
        best_fam, best_fr = None, None
        for fam in candidates:
            fr, _ = best_lag(ad_spend, _family_series(data, fam))
            if fr is not None and (best_fr is None or fr > best_fr):
                best_fam, best_fr = fam, fr
        if best_fam and best_fr is not None and (named or best_fr >= 0.6):
            title = html.escape(family_title(best_fam, data["catalog"], data["families"]))
            guess = "" if named else ", taxminiy"
            parts.append(f"{title}: {strength(best_fr)} ({best_fr:.2f}{guess})")
            if best_fr >= 0.6:
                todo.append(f"«{short(a['name'])}» {title} sotuvini ko'taryapti — shu mahsulot "
                            "bilan yana video qiling.")
        ig = "📱 " if meta_ads.is_ig_boost(a["name"]) else ""
        ad_lines.append(f"• {ig}«{short(a['name'], 32)}» — " + "; ".join(parts))
    if ad_lines:
        body += ["", "🎬 <b>Videolar bo'yicha</b>"] + ad_lines
    note = tz_note(data.get("tz_hours", TASHKENT_HOURS))
    body += ["", "<i>Bog'liqlik — sarf ko'paygan kunlari sotuv ham ko'payganini ko'rsatadi. "
                 "Bu taxmin: bayram, kanal posti, aksiya ham ta'sir qiladi."
                 f"{' ' + note if note else ''}</i>", ""]

    if not steady and best_r < 0.3:
        todo.append("Reklama sotuvni ko'tarmayapti — auditoriya yoki videoni almashtiring, "
                    "yoki 3-4 kun to'xtatib, sotuv tushadimi tekshiring.")
    if steady:
        todo.append("Ta'sirni bilish uchun byudjetni 2-3 kun oshirib, keyin kamaytirib ko'ring — "
                    "bot farqni shu yerda ko'rsatadi.")
    return "\n".join(head + body + _todo(todo[:4]))


def launch_effects(data: dict, window: int = LAUNCH_WINDOW) -> list[dict]:
    """Har bir video boshlangan kundan oldingi `window` kun va keyingi `window`
    kun: buyurtma, o'rtacha chek va qaysi mahsulot ko'proq sotilgan.

    Video hali `window` kun ishlamagan bo'lsa, ikki tomon ham shuncha qisqa
    olinadi (kamida 3 kun) — 4 kunni 7 kun bilan solishtirish o'sishni
    yashirib qo'yadi."""
    dates = data["dates"]
    last = dates[-1]
    of_product = data["families"]["of_product"]
    launches = {}
    for ad_id, a in data["ads"].items():
        spent = sorted(d for d, v in a["spend"].items() if v > 0)
        if spent and a["total"] >= MIN_SPEND:
            launches[ad_id] = date.fromisoformat(spent[0])

    def window_totals(days_list):
        return totals({d.isoformat(): data["days"][d.isoformat()]
                       for d in days_list if d.isoformat() in data["days"]})

    out = []
    for ad_id, launch in launches.items():
        a = data["ads"][ad_id]
        if data.get("capped") and launch <= dates[0]:
            continue
        n = min(window, (last - launch).days + 1)
        entry = {"id": ad_id, "ad": a, "launch": launch, "days": n}
        if n < 3:
            out.append({**entry, "too_new": True})
            continue
        before = window_totals([launch - timedelta(days=i) for i in range(n, 0, -1)])
        after_days = [launch + timedelta(days=i) for i in range(n)]
        after = window_totals(after_days)
        rows = product_changes(after["products"], before["products"], of_product,
                               set(a["families"]))
        rivals = [other for other, l2 in launches.items()
                  if other != ad_id and abs((l2 - launch).days) < n]
        growth = grew(rows, 4)
        for r in growth:
            # Shu kunlarda boshlangan BOSHQA videoda ko'rsatilgan mahsulotning
            # o'sishi o'sha videoniki — bu videoga yozilmaydi.
            r["rival"] = None if r["ad"] else next(
                (data["ads"][o]["name"] for o in rivals
                 if of_product.get(r["key"]) in data["ads"][o]["families"]), None)
        out.append({**entry, "before": before, "after": after, "growth": growth,
                    "own": [r for r in growth if not r["rival"]],
                    "spend": sum(a["spend"].get(d.isoformat(), 0.0) for d in after_days),
                    "rivals": [data["ads"][o]["name"] for o in rivals]})
    return sorted(out, key=lambda e: e["launch"], reverse=True)


def format_after(data: dict) -> str:
    effects = launch_effects(data)
    head = ["🚀 <b>Videodan keyin nima o'zgardi</b>",
            f"<i>Har bir video boshlangan kundan oldingi va keyingi {LAUNCH_WINDOW} kun "
            "solishtirildi.</i>", ""]
    measured = [e for e in effects if not e.get("too_new")]
    if not effects:
        return "\n".join(head + ["So'nggi 90 kunda yangi boshlangan video topilmadi."])

    best = max(measured, key=lambda e: (e["own"][0]["now"] - e["own"][0]["was"])
               if e["own"] else 0, default=None)
    if best and best["own"]:
        g = best["own"][0]
        head.append(f"Eng katta o'sish — «{short(best['ad']['name'])}» dan keyin: "
                    f"<b>{html.escape(g['name'])}</b> {qty(g['was'])} → {qty(g['now'])} dona.")
    elif measured:
        head.append("⚠️ Hech bir videodan keyin mahsulot sotuvi sezilarli o'smadi.")
    head.append("")

    body, todo = [], []
    for e in effects[:MAX_ADS]:
        a = e["ad"]
        ig = " 📱" if meta_ads.is_ig_boost(a["name"]) else ""
        body.append(f"🎬 <b>{short(a['name'])}</b>{ig} · {_fmt_day(e['launch'])} dan")
        if e.get("too_new"):
            body += ["⏳ Hali 3 kun ishlamagan — xulosa erta.", ""]
            continue
        b, af = e["before"], e["after"]
        body.append(f"💵 {e['days']} kunda {usd(e['spend'])}")
        body.append(f"🛒 Buyurtma: {b['orders']} → <b>{af['orders']}</b> "
                    f"({delta(af['orders'], b['orders'])})")
        if b["orders"] or af["orders"]:
            body.append(f"🧾 O'rtacha chek: {som(avg_check(b))} → <b>{som(avg_check(af))}</b> "
                        f"({delta(avg_check(af), avg_check(b))})")
        if e["growth"]:
            body.append("📈 Ko'proq sotilgan:")
            for r in e["growth"]:
                mark = (" 🎬" if r["ad"] else
                        f" (🎬 «{short(r['rival'], 28)}» da)" if r["rival"] else "")
                body.append(f"   • {html.escape(r['name'])}: {qty(r['was'])} → {qty(r['now'])} dona{mark}")
        else:
            body.append("➖ Hech bir mahsulot sezilarli o'smadi.")
        own = e["own"]
        if own and own[0]["ad"]:
            todo.append(f"«{short(a['name'])}» dan keyin {html.escape(own[0]['name'])} ko'proq "
                        "sotildi — shu mahsulot bilan yana video qiling.")
        elif own and not e["rivals"]:
            todo.append(f"«{short(a['name'])}» dan keyin umumiy sotuv o'sdi, ayniqsa "
                        f"{html.escape(own[0]['name'])} — u haqida alohida video qiling.")
        elif not own and not e["rivals"] and a["total"] >= 5:
            todo.append(f"«{short(a['name'])}» dan keyin sotuv o'smadi — videoni almashtiring.")
        if e["rivals"]:
            names = ", ".join(f"«{short(n, 28)}»" for n in e["rivals"][:2])
            body.append(f"⚠️ Shu kunlarda {names} ham boshlangan — ta'sir aralash.")
        body.append("")
    body.append("<i>🎬 — shu videoda ko'rsatilgan mahsulot. «Keyin» — «sabab» degani emas: "
                "bayram, aksiya, kanal posti ham ta'sir qiladi. Ulgurji (B2B), sovg'a va "
                "bonuslar hisobga olinmagan."
                f"{' ' + tz_note(data.get('tz_hours', TASHKENT_HOURS)) if tz_note(data.get('tz_hours', TASHKENT_HOURS)) else ''}</i>")
    body.append("")
    return fit("\n".join(head + body + _todo(todo[:4])))


# ---------------------------------------------------------------- keyboards

def view_rows(preset: str, active: str | None = None) -> list[list[InlineKeyboardButton]]:
    buttons = [InlineKeyboardButton(text=("• " if v == active else "") + title,
                                    callback_data=f"adsv:{v}:{preset}") for v, title in VIEWS]
    if active:
        buttons.insert(0, InlineKeyboardButton(text="📊 Umumiy", callback_data=f"ads:{preset}"))
    return [buttons[i:i + 2] for i in range(0, len(buttons), 2)]


def view_keyboard(view: str, preset: str) -> InlineKeyboardMarkup:
    row1 = [InlineKeyboardButton(text=("• " if k == preset else "") + meta_ads.PRESETS[k][0],
                                 callback_data=f"adsv:{view}:{k}") for k in ("today", "yesterday")]
    row2 = [InlineKeyboardButton(text=("• " if k == preset else "") + meta_ads.PRESETS[k][0],
                                 callback_data=f"adsv:{view}:{k}")
            for k in ("last_7d", "last_30d", "maximum")]
    # 🚀 har doim so'nggi 90 kundagi videolarni ko'rsatadi — davr tugmalari unga ta'sir qilmaydi.
    periods = [] if view == "aft" else [row1, row2]
    return InlineKeyboardMarkup(inline_keyboard=periods + view_rows(preset, view))


async def build_view(view: str, preset: str) -> str:
    if view == "cor":
        return format_correlation(await collect_daily(preset))
    if view == "aft":
        return format_after(await collect_daily("maximum"))
    data = await collect(preset)
    return format_products(data) if view == "prd" else format_videos(data)


@router.callback_query(F.data.startswith("adsv:"))
async def cb_view(callback: CallbackQuery):
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Faqat adminlar uchun", show_alert=True)
        return
    _, view, preset = (callback.data.split(":", 2) + ["", ""])[:3]
    if view not in dict(VIEWS) or preset not in meta_ads.PRESETS:
        await callback.answer()
        return
    if not meta_ads.is_enabled():
        await callback.answer("Reklama tokeni o'rnatilmagan — /reklama_token", show_alert=True)
        return
    await callback.answer("Yuklanmoqda…")
    try:
        text = await build_view(view, preset)
    except meta_ads.GraphError as e:
        text = f"❌ <code>{html.escape(str(e))}</code>"
    except Exception:
        logger.exception("Ads impact view %s/%s failed", view, preset)
        text = "❌ Hisobotni tuzib bo'lmadi — birozdan keyin qayta urinib ko'ring."
    kb = view_keyboard(view, preset)
    try:
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=kb,
                                         disable_web_page_preview=True)
    except Exception:
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb,
                                      disable_web_page_preview=True)
