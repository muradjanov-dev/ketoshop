"""Ketoshop kuryeri narxi — Toshkent shahri chegarasiga qarab (egasi, 2026-11-26:
"faqat toshkent shahri ichida kuryer narxi 25000 so'm, ... shahar chegarasini bilib
ol va shahardan tashqariga chiqqach 25000 + har 1 km uchun 3000 so'mdan qo'shib bor,
masalan shahardan 5 km tashqarida — 25000 + 15000; buni mijozga avvaldan bildir har
yerda, ya'ni manzilini olgandan keyin hisob-kitob qilib").

* Shahar chegarasi — Toshkent shahrining ma'muriy chegarasi (OpenStreetMap,
  relation 2216724, ~100 m aniqlikda soddalashtirilgan; ikki bo'lak).
* Ichida: SELF_DELIVERY_FEE (25 000). Tashqarida: + har boshlangan km uchun
  PER_KM (3 000) — chegaraning eng yaqin nuqtasigacha to'g'ri chiziq bo'yicha.
* FREE_DELIVERY_FROM (800 000) dan — faqat asosiy 25 000 bepul; shahardan
  tashqaridagi km haqi baribir qo'shiladi (kuryer shuncha yo'l yuradi).
* Kuryer chegaradan MAX_KM_OUTSIDE km gacha boradi; undan uzoq — pochta/UzPost.
"""
from __future__ import annotations

import math

PER_KM = 3_000
MAX_KM_OUTSIDE = 40

CITY_POLYGONS: tuple[tuple[tuple[float, float], ...], ...] = (
    (
        (41.26626, 69.1218), (41.269, 69.13149), (41.27525, 69.13988), (41.27786, 69.14102),
        (41.28096, 69.14755), (41.27614, 69.14646), (41.26206, 69.14812), (41.25021, 69.16349),
        (41.24031, 69.16707), (41.23661, 69.16542), (41.23453, 69.16935), (41.22832, 69.17411),
        (41.22604, 69.17194), (41.22167, 69.17395), (41.22133, 69.1755), (41.21881, 69.17456),
        (41.21765, 69.17639), (41.21907, 69.1806), (41.21682, 69.18382), (41.21455, 69.18154),
        (41.21037, 69.18524), (41.2067, 69.18238), (41.20486, 69.18585), (41.20068, 69.18498),
        (41.1962, 69.18639), (41.17887, 69.20188), (41.17438, 69.20892), (41.16568, 69.23829),
        (41.16358, 69.27294), (41.16485, 69.27954), (41.16926, 69.28864), (41.16775, 69.32235),
        (41.16266, 69.33547), (41.1597, 69.42559), (41.15773, 69.42924), (41.16286, 69.44374),
        (41.16331, 69.45419), (41.16646, 69.45509), (41.16764, 69.46011), (41.16977, 69.46193),
        (41.16877, 69.46881), (41.17564, 69.47743), (41.18631, 69.48304), (41.21054, 69.50496),
        (41.22528, 69.50882), (41.24324, 69.50899), (41.27214, 69.52164), (41.2872, 69.52487),
        (41.29654, 69.52392), (41.30123, 69.52591), (41.3028, 69.52569), (41.30296, 69.52041),
        (41.30538, 69.51878), (41.30819, 69.49964), (41.31287, 69.49165), (41.31787, 69.45946),
        (41.32082, 69.44963), (41.33808, 69.47158), (41.3449, 69.47402), (41.34704, 69.47714),
        (41.34912, 69.47424), (41.34563, 69.46147), (41.34222, 69.40789), (41.34777, 69.41115),
        (41.35566, 69.4108), (41.36377, 69.4046), (41.36302, 69.4016), (41.36599, 69.39886),
        (41.36432, 69.39589), (41.36622, 69.39099), (41.36134, 69.37542), (41.36238, 69.36325),
        (41.35476, 69.35396), (41.35601, 69.34406), (41.37014, 69.32459), (41.38272, 69.31896),
        (41.38457, 69.31668), (41.3838, 69.28509), (41.39713, 69.26178), (41.39848, 69.23588),
        (41.38737, 69.21574), (41.38697, 69.21172), (41.384, 69.21046), (41.35684, 69.16888),
        (41.35109, 69.1657), (41.33333, 69.16271), (41.3282, 69.15986), (41.32723, 69.15486),
        (41.32519, 69.15354), (41.32159, 69.15429), (41.31377, 69.14826), (41.31366, 69.14663),
        (41.30816, 69.14909), (41.30511, 69.1485), (41.29493, 69.13845), (41.29241, 69.13826),
        (41.288, 69.13212), (41.28412, 69.13493), (41.27892, 69.13346), (41.27895, 69.13155),
        (41.27609, 69.12879), (41.27009, 69.1253), (41.26982, 69.12279), (41.26626, 69.1218),
    ),
    (
        (41.41303, 69.44084), (41.40683, 69.44355), (41.40026, 69.45015), (41.40138, 69.45803),
        (41.40662, 69.46954), (41.40935, 69.46439), (41.41261, 69.46994), (41.41343, 69.46932),
        (41.41429, 69.46838), (41.4119, 69.46453), (41.41816, 69.46295), (41.42223, 69.45541),
        (41.42086, 69.44589), (41.4173, 69.4419), (41.41303, 69.44084),
    ),
)

_KM_LAT = 111.32
_KM_LNG = 111.32 * math.cos(math.radians(41.3))


def _inside_ring(lat: float, lng: float, ring) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        y1, x1 = ring[i]
        y2, x2 = ring[(i + 1) % n]
        if (y1 > lat) != (y2 > lat):
            x_cross = x1 + (lat - y1) * (x2 - x1) / (y2 - y1)
            if lng < x_cross:
                inside = not inside
    return inside


def inside_city(lat, lng) -> bool:
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return False
    return any(_inside_ring(lat, lng, ring) for ring in CITY_POLYGONS)


def _segment_km(lat, lng, a, b) -> float:
    """Nuqtadan kesmagacha masofa, km (kichik masofada tekis proyeksiya yetarli)."""
    px, py = lng * _KM_LNG, lat * _KM_LAT
    ax, ay = a[1] * _KM_LNG, a[0] * _KM_LAT
    bx, by = b[1] * _KM_LNG, b[0] * _KM_LAT
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def km_outside(lat, lng) -> float | None:
    """Shahar chegarasidan qancha km tashqarida (ichida — 0); lokatsiya yo'q — None."""
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    if inside_city(lat, lng):
        return 0.0
    return min(_segment_km(lat, lng, ring[i], ring[(i + 1) % len(ring)])
               for ring in CITY_POLYGONS for i in range(len(ring)))


def billable_km(lat, lng) -> int:
    """Haq olinadigan butun km: boshlangan har km (4,2 km → 5). Ichida yoki noma'lum — 0."""
    km = km_outside(lat, lng)
    return int(math.ceil(km - 1e-9)) if km else 0


def courier_ok(lat, lng) -> bool:
    """Ketoshop kuryeri boradimi: shahar ichida yoki chegaradan MAX_KM_OUTSIDE km gacha."""
    km = km_outside(lat, lng)
    return km is not None and km <= MAX_KM_OUTSIDE


def extra_fee(lat, lng) -> int:
    return billable_km(lat, lng) * PER_KM


def breakdown_text(base: int, lat, lng, lang: str) -> str:
    """"📍 Shahardan 5 km tashqarida: 25 000 + 5 × 3 000 = 40 000 so'm" yoki ""."""
    km = billable_km(lat, lng)
    if not km:
        return ""
    som = lambda v: f"{int(v):,}".replace(",", " ")
    total = base + km * PER_KM
    if lang == "ru":
        return (f"📍 {km} км за городом: {som(base)} + {km} × {som(PER_KM)} = {som(total)} сум")
    text = f"📍 Shahardan {km} km tashqarida: {som(base)} + {km} × {som(PER_KM)} = {som(total)} so'm"
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        text = lat_to_cyr(text)
    return text
