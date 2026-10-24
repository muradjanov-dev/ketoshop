"""
📮 UzPost «Bir Qadam» — a ready delivery price for regional buyers, and the
post office they collect the parcel from (owner, 2026-10-24: "Viloyatlarga
Uzpost narxlarini chamalab mijozga tayyor narx bera olamizmi umumiy
yetkazib berishga qo'shib" + "mijoz tashlagan manzilga eng yaqin pochta
indeksi va manzilini ham ayta olasanmi?").

Price. UzPost's own calculator (uz.post/Kalkulyator, checked 2026-10-24)
prices «Bir Qadam» from Tashkent by weight only, never by distance:
15 000 so'm for the first kilogram and 3 000 for each one after it — 7 000
to Karakalpakstan, Khorezm and Surkhandarya, which go by air. Weight is
rounded UP to whole kilograms, 20 kg at most per parcel. The buyer pays that
tariff plus SURCHARGE (owner's call: +3 000 so'm for taking the parcel to
the post office). There is no free threshold outside Tashkent — owner's call
too; the Tashkent courier's FREE_DELIVERY_FROM doesn't apply here.

Weight. Products carry no weight field, so it is read from what is there:
the pack size in the name ("Bodom uni 1000gr", "GHEE 1000ml", "5 l") times
the quantity, else the quantity itself for a product sold by the kilogram or
litre, else DEFAULT_ITEM_KG a piece; sets weigh SET_KG. Anything in a glass
jar, bottle or tin counts JAR_FACTOR times (is_jar — owner, 2026-10-24: the
jar weighs about as much as what is in it). A box adds PACKAGING_KG. It is
an estimate and every buyer-facing line says so (~); one kilogram off costs
3 000 so'm.

Post office. «Bir Qadam» runs only between the offices that offer it (220
of UzPost's ~1 600). The full office list (index, coordinates, which
services) comes from UzPost's public map API, cached for OFFICES_TTL; the
nearest «Bir Qadam» office to the buyer's pin is picked here and its address
and hours read by its index. If UzPost can't be reached the order still
goes through — just without an office line, and the admins pick one.
"""
import asyncio
import logging
import math
import re
import time

import aiohttp

logger = logging.getLogger(__name__)

METHOD = "uzpost"

FIRST_KG = 15_000
NEXT_KG = 3_000
NEXT_KG_FAR = 7_000
SURCHARGE = 3_000
MAX_KG = 20
PACKAGING_KG = 0.2
DEFAULT_ITEM_KG = 0.5
SET_KG = 1.5
JAR_FACTOR = 2

# Glass jars, bottles and tins (owner, 2026-10-24: "bonkali mahsulotlar bor
# masalan losos yoki extra virgin, bularni og'irligini pochta uchun 2x
# hisoblayver"). Everything sold by volume (ml / l) comes in one; these name
# words catch the rest. Matched lower-cased, with every apostrophe as "'".
_JAR_WORDS = ("tushonka", "тушонк", "losos", "lasos", "лосос", "virgin", "vergin",
              "zaytun", "зайтун", "yog'i", "ёғи", "масло", "ghee", "гхи", "asal", "асал",
              "мёд", "sirka", "сирка", "уксус", "pasta", "паста", "slivka", "сливк")
_LIQUID_UNITS = {"ml", "мл", "l", "л", "litr", "литр"}
_APOSTROPHES = str.maketrans({c: "'" for c in "ʻʼ‘’`´"})

# regions.py keys priced at NEXT_KG_FAR, and the same regions as UzPost's
# office records spell them (Cyrillic or Latin, lower-cased).
FAR_REGIONS = {"karakalpakstan", "khorezm", "surkhandarya"}
_FAR_WORDS = ("қорақалпоғ", "каракалпак", "qoraqalpog", "хоразм", "хорезм", "xorazm",
              "сурхон", "сурхан", "surxon")

OFFICES_URL = "https://new.pochta.uz/api/v1/maps/new/post/offices/"
DETAIL_URL = "https://new.pochta.uz/api/v1/maps/new/post/offices/detail/{index}/"
OFFICES_TTL = 24 * 3600
DETAIL_TTL = 7 * 24 * 3600
HTTP_TIMEOUT = 12
_HEADERS = {"User-Agent": "Mozilla/5.0 (Ketoshop bot)"}

_WEIGHT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(kg|кг|kilogramm?|килограмм?|gr|g|гр|г|gramm?|грамм?|ml|мл|l|л|litr|литр)(?![a-zа-яё])",
    re.IGNORECASE)
_KG_UNITS = {"kg", "кг", "l", "liter", "litr", "литр", "л"}
_NUM = re.compile(r"-?\d+(?:\.\d+)?")

_offices: dict = {"at": 0.0, "list": []}
_details: dict[str, tuple[float, dict]] = {}
_lock = asyncio.Lock()


# ─────────────────────────────── weight & price ─────────────────────────────

def pack_kg(name: str | None) -> float | None:
    """The pack size written in a product name, in kg (ml counted as g), or
    None. The last size wins: "Kokos uni 1000gr (2 x 500g)" is rare, a
    trailing size is the norm."""
    found = _WEIGHT_RE.findall(name or "")
    if not found:
        return None
    value, unit = found[-1]
    try:
        amount = float(value.replace(",", "."))
    except ValueError:
        return None
    if amount <= 0:
        return None
    unit = unit.lower()
    small = unit in ("gr", "g", "гр", "г", "gram", "gramm", "грам", "грамм", "ml", "мл")
    return amount / 1000 if small else amount


def is_jar(name: str | None) -> bool:
    """Whether a product ships in a glass jar, bottle or tin."""
    low = (name or "").lower().translate(_APOSTROPHES)
    found = _WEIGHT_RE.findall(low)
    if found and found[-1][1] in _LIQUID_UNITS:
        return True
    return any(word in low for word in _JAR_WORDS)


def item_kg(item: dict) -> float:
    """Shipping weight of one order line, in kg."""
    try:
        qty = float(item.get("stock_quantity") or 1) if item.get("is_bonus") \
            else float(item.get("quantity") or 0)
    except (TypeError, ValueError):
        qty = 0.0
    if qty <= 0:
        return 0.0
    if item.get("is_set"):
        return SET_KG * qty
    name = item.get("name")
    per = pack_kg(name)
    if per is None:
        per = 1.0 if str(item.get("unit") or "").lower() in _KG_UNITS else DEFAULT_ITEM_KG
    return per * qty * (JAR_FACTOR if is_jar(name) else 1)


def parcel_kg(items: list[dict]) -> float:
    """The whole box: every line that ships (gifts and bonuses too) + box."""
    return round(sum(item_kg(it) for it in items or [] if isinstance(it, dict)) + PACKAGING_KG, 2)


def is_far(region: str | None) -> bool:
    """Karakalpakstan / Khorezm / Surkhandarya — a regions.py key or an
    office's own region text."""
    if not region:
        return False
    low = str(region).lower()
    return low in FAR_REGIONS or any(w in low for w in _FAR_WORDS)


def tariff(kg: float, far: bool = False) -> int:
    """What UzPost charges for «Bir Qadam» from Tashkent."""
    whole = max(1, math.ceil(round(kg, 3)))
    return FIRST_KG + (whole - 1) * (NEXT_KG_FAR if far else NEXT_KG)


def buyer_fee(items: list[dict], far: bool = False) -> int:
    """What the buyer pays: the tariff + SURCHARGE."""
    return tariff(parcel_kg(items), far) + SURCHARGE


def fmt_kg(kg: float) -> str:
    return f"{kg:.1f}".rstrip("0").rstrip(".").replace(".", ",")


# ─────────────────────────────── post offices ───────────────────────────────

def _num(value) -> float | None:
    m = _NUM.match(str(value or "").strip())
    return float(m.group()) if m else None


def _km(a: tuple[float, float], b: tuple[float, float]) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def parse_offices(payload: dict) -> list[dict]:
    """The «Bir Qadam» offices out of UzPost's office list. Some coordinates
    come with junk after the number ("67.284027,1810"); points outside
    Uzbekistan are dropped rather than trusted."""
    out = []
    for o in (payload or {}).get("result") or []:
        if not isinstance(o, dict) or o.get("one_step") != "Bor" or not o.get("index"):
            continue
        lat, lng = _num(o.get("lat")), _num(o.get("lng"))
        if lat is None or lng is None or not (37 < lat < 46 and 55 < lng < 74):
            continue
        out.append({"index": str(o["index"]), "lat": lat, "lng": lng})
    return out


def nearest(offices: list[dict], lat: float, lng: float) -> tuple[dict, float] | None:
    best = None
    for o in offices:
        km = _km((lat, lng), (o["lat"], o["lng"]))
        if best is None or km < best[1]:
            best = (o, km)
    return best


async def _get_json(url: str) -> dict | None:
    try:
        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT)
        async with aiohttp.ClientSession(timeout=timeout, headers=_HEADERS) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                return await resp.json(content_type=None)
    except Exception:
        logger.warning("UzPost request failed: %s", url, exc_info=True)
        return None


async def _office_list() -> list[dict]:
    async with _lock:
        if _offices["list"] and time.time() - _offices["at"] < OFFICES_TTL:
            return _offices["list"]
        parsed = parse_offices(await _get_json(OFFICES_URL) or {})
        if parsed:
            _offices.update(at=time.time(), list=parsed)
        return _offices["list"]          # stale beats nothing


async def _detail(index: str) -> dict:
    cached = _details.get(index)
    if cached and time.time() - cached[0] < DETAIL_TTL:
        return cached[1]
    payload = await _get_json(DETAIL_URL.format(index=index)) or {}
    office = ((payload.get("result") or {}).get("postal_office")) or {}
    if office:
        _details[index] = (time.time(), office)
    return office


def _clean(value) -> str:
    text = " ".join(str(value or "").split())
    return text[:-2] if text.endswith(".0") else text


def describe(index: str, detail: dict, lat: float, lng: float, km: float) -> dict:
    """The office as the bot shows and stores it."""
    name = _clean(detail.get("name_uz")) or f"UzPost {index}"
    name = re.sub(r"^UzPost\s*-\s*", "", name).strip() or name
    street = " ".join(p for p in (_clean(detail.get("street")), _clean(detail.get("house"))) if p)
    place = [_clean(detail.get(k)) for k in ("region", "city", "district")]
    seen, parts = set(), []
    for p in place + [street]:
        if p and p.lower() not in seen:
            seen.add(p.lower())
            parts.append(p)
    hours = " ".join(p for p in (_clean(detail.get("working_days")), _clean(detail.get("working_hours"))) if p)
    return {
        "index": index, "name": name, "address": ", ".join(parts), "hours": hours,
        "region": _clean(detail.get("region")), "lat": lat, "lng": lng, "km": round(km, 1),
    }


async def nearest_office(lat, lng) -> dict | None:
    """The closest «Bir Qadam» office to a pin, or None (no pin / UzPost down)."""
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    offices = await _office_list()
    found = nearest(offices, lat, lng) if offices else None
    if not found:
        return None
    office, km = found
    detail = await _detail(office["index"])
    return describe(office["index"], detail, office["lat"], office["lng"], km)


_DAYS = {"пн": ("Du", "Ду"), "вт": ("Se", "Се"), "ср": ("Chor", "Чор"), "чт": ("Pay", "Пай"),
         "пт": ("Ju", "Жу"), "сб": ("Sha", "Ша"), "вс": ("Yak", "Як")}
_DAY_RE = re.compile(r"(?<![а-яё])(пн|вт|ср|чт|пт|сб|вс)(?![а-яё])", re.IGNORECASE)


def localize(office: dict | None, lang: str) -> dict | None:
    """UzPost writes addresses in Cyrillic Uzbek and hours as "Пн-Сб" — the
    buyer reads them in their own language (Latin for uz, Uzbek day names
    for both Uzbek scripts; Russian stays as UzPost wrote it)."""
    if not office or lang not in ("uz", "uz_cyr"):
        return office
    cyr = lang == "uz_cyr"
    hours = _DAY_RE.sub(lambda m: _DAYS[m.group(1).lower()][1 if cyr else 0], office.get("hours") or "")
    out = dict(office, hours=hours)
    if not cyr:
        from translit import cyr_to_lat
        out.update(address=cyr_to_lat(office.get("address") or ""),
                   hours=cyr_to_lat(hours), name=cyr_to_lat(office.get("name") or ""))
    return out


def map_url(office: dict) -> str:
    return f"https://yandex.uz/maps/?pt={office['lng']:.6f},{office['lat']:.6f}&z=17&l=map"


def office_line(office: dict | None) -> str:
    """One line for the order record and the admin card:
    "141600 — Urgut Pochtamt, Самарқанд, Ургут, А.Навоий шох кучаси 17"."""
    if not office:
        return ""
    line = f"{office['index']} — {office['name']}"
    return line + (f", {office['address']}" if office.get("address") else "")
