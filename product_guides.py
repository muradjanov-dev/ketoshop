"""Mahsulot qo'llanmasi — «qayerda, nima uchun va qanday ishlatiladi» (2026-10-11).

Egasining talabi: kun mahsuloti mijozga borganda, u mahsulotni QAYERDA va
NIMA UCHUN ishlatishni bilsin — kamida 3 ta aniq usul (retsept bo'lsa ham
mayli), foydasi aniq sanab, zarari bo'lsa ogohlantirish va tavsiya bilan;
ustiga ketochi, parhezdagi va diabetli mijoz qaraydigan raqamlar (kkal,
glikemik indeks, uglevod).

Nega alohida xabar: kartochka Telegram'da rasm izohi — 1024 belgi, va u
narx, chegirma, sovg'a qatorlari bilan allaqachon to'la (product_card).
Qo'llanma kartochkadan keyin alohida matn bo'lib ketadi — u yerda 4096.
Kartochkaning o'ziga faqat bitta qisqa raqamlar qatori qo'shiladi
(card_line).

Nega oiladan maydaroq: product_descriptions oilalari tavsif uchun yetadi,
lekin aniq foyda va zarar uchun emas — eritritol, alluloza va toza steviya
bitta «shirinlashtirgich» oilasida, ksantan psillium bilan birga. Shuning
uchun bu yerda tur mahsulot nomidan o'zining qoidalari bilan aniqlanadi.

Matnlar product_guides_content.py da. Kirill o'zbekcha alohida yozilmaydi —
lotin matndan render paytida o'giriladi (translit.lat_to_cyr).
"""
import html
import re

from product_guides_content import GUIDES, NUTRITION, NUTRI_NOTE

# First match wins, so the order is the logic: a more specific kind must come
# before the broader one that would also match it — ice cream "(Shokolad,
# kakao)" before chocolate, "Kokos yog'i" before plain kokos, "Kepakli
# bug'doy uni" before kepak, "bulgur guruchi" before guruch, the stevia blends
# before plain stevia. Patterns run against the lower-cased name AND its
# Latin transliteration, so a name typed in Cyrillic ("Зайтун ёғи",
# "Шоколад Победа") still lands; Russian stems cover names typed in Russian.
_MATCH = [
    ("keto_icecream",    r"muzqaymoq|морожен"),
    ("cacao_nibs",       r"nibs|какао[- ]?крупк"),
    ("chocolate",        r"shokolad|pobeda|kakao|шоколад|побед|какао"),
    ("coconut_sugar",    r"kokos shakar|кокосов\w* сахар"),
    ("coconut_cream",    r"kokos (?:slivka|sut|qaymo)|кокосов\w* (?:сливк|молок)"),
    ("coconut_oil",      r"kokos yog'|кокосов\w* масл"),
    ("coconut_flour",    r"kokos uni|кокосов\w* мук"),
    ("coconut_flakes",   r"kokos|кокос"),
    ("ghee_butter",      r"ghee|\bgxi\b|saryog'|sariyog'|топлен|сливочн"),
    ("olive_oil",        r"zaytun|оливк"),
    ("nut_paste",        r"pasta|паста|urbech|урбеч"),
    ("xanthan",          r"ksantan|xantan|ксантан"),
    ("psyllium",         r"psill|псилл|sheluxa"),
    ("stevia_pure",      r"toza stevi|чист\w* стеви"),
    ("allulose_stevia",  r"allul\w*\s*\+\s*stevi|аллюл\w*\s*\+\s*стеви"),
    ("allulose",         r"allul|аллюл"),
    ("erythritol",       r"eritr|эритр"),
    ("stevia",           r"stevi|стеви"),
    ("honey",            r"\basal|\bмёд|\bмед\b"),
    ("vinegar",          r"sirka|уксус"),
    ("salt",             r"\btuz\b|\bсоль"),
    ("cinnamon",         r"koritsa|dolchin|корица"),
    ("fennel",           r"arpabodiyon|fenxel|фенхел"),
    ("nigella",          r"sedana|седан|чернушк|нигелл"),
    ("milk_thistle",     r"rastaropsha|расторопш"),
    ("sesame",           r"kunjut|кунжут"),
    ("pumpkin_seed",     r"qovoq|тыкв"),
    ("flax",             r"zig'ir|льн"),
    ("chia",             r"\bchia|\bчиа"),
    ("pistachio_flour",  r"fistashka uni|pista uni|фисташков\w* мук"),
    ("pistachio",        r"pista|fistashka|фисташк"),
    ("almond_flour",     r"bodom|миндал"),
    ("buckwheat_flour",  r"grechka uni|гречнев\w* мук"),
    ("buckwheat",        r"grechka|гречк"),
    ("chickpea_flour",   r"no'xat|\bнут"),
    ("rice_flour",       r"guruch uni|рисов\w* мук"),
    ("bulgur",           r"bulg'?ur|булгур"),
    ("rice",             r"guruch|\bрис"),
    ("starch",           r"kraxmal|крахмал"),
    ("corn_flour",       r"makkajo'xori|кукуруз"),
    ("oats",             r"ovsyanka|\bsuli\b|овсян|овёс|овес"),
    ("rye_flour",        r"javdar|ржан"),
    ("barley_flour",     r"arpa uni|ячмен"),
    ("spelt_flour",      r"polba|полб"),
    ("wholewheat_flour", r"kepakli|цельнозерн"),
    ("bran",             r"kepak|отруб"),
    ("wheat_2nd",        r"\b2-?\s*nav|ikkinchi nav|2-?го сорт|второго сорт"),
    ("soy_flour",        r"\bsoya|соев"),
    ("malt",             r"solod|солод"),
    ("sourdough",        r"zakvaska|закваск|hamirturush|xamirturush"),
    ("salmon",           r"losos|baliq|лосос|рыб"),
]
_COMPILED = [(key, re.compile(rx, re.I)) for key, rx in _MATCH]

# Every apostrophe Uzbek Latin gets typed with, folded to the plain one the
# patterns use ("yog‘i", "urugʻi", "yog’i").
_APOS = str.maketrans({"‘": "'", "’": "'", "ʻ": "'", "ʼ": "'", "`": "'"})

_HEAD = {
    "uz": {"title": "📖 <b>{name}: qayerda va qanday ishlatiladi?</b>",
           "nutri": "📊 <b>100 g da (taxminan)</b>",
           "benefits": "💚 <b>Foydasi</b>",
           "uses": "🍽 <b>Qayerda va qanday ishlatiladi</b>",
           "cautions": "⚠️ <b>Ehtiyot bo'ling</b>",
           "advice": "✅ <b>Maslahat:</b>"},
    "ru": {"title": "📖 <b>{name}: где и как использовать?</b>",
           "nutri": "📊 <b>На 100 г (примерно)</b>",
           "benefits": "💚 <b>Польза</b>",
           "uses": "🍽 <b>Где и как использовать</b>",
           "cautions": "⚠️ <b>Осторожно</b>",
           "advice": "✅ <b>Совет:</b>"},
}
_NUM = ("1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣")

_UNITS = {
    "uz": {"kcal": "kkal", "g": "g", "p": "Oqsil", "f": "Yog'", "c": "Uglevod", "fiber": "Tola",
           "gi": "Glikemik indeks", "gi_short": "GI", "carbs_short": "uglevod"},
    "ru": {"kcal": "ккал", "g": "г", "p": "Белки", "f": "Жиры", "c": "Углеводы", "fiber": "Клетчатка",
           "gi": "Гликемический индекс", "gi_short": "ГИ", "carbs_short": "углеводы"},
}
_GI_WORD = {
    "uz": {0: "qon shakarini ko'tarmaydi", "low": "past — qon shakarini sekin ko'taradi",
           "mid": "o'rta", "high": "yuqori — qon shakarini tez ko'taradi"},
    "ru": {0: "не поднимает сахар в крови", "low": "низкий — сахар растёт медленно",
           "mid": "средний", "high": "высокий — сахар растёт быстро"},
}
_KETO = {
    "uz": {"yes": "✅ Ketoga mos", "limited": "⚠️ Ketoda — oz miqdorda", "no": "❌ Keto uchun mos emas"},
    "ru": {"yes": "✅ Подходит для кето", "limited": "⚠️ На кето — понемногу", "no": "❌ Не для кето"},
}
_KETO_MARK = {"yes": "✅", "limited": "⚠️", "no": "❌"}


def _haystack(name: str) -> str:
    low = (name or "").translate(_APOS).lower()
    try:
        from translit import cyr_to_lat
        lat = cyr_to_lat(name or "").translate(_APOS).lower()
    except Exception:
        lat = ""
    return f"{low} | {lat}"


def guide_key(product_name: str) -> str | None:
    """Which guide this product name gets, or None when nothing fits — an
    unknown product gets no guide rather than a generic one."""
    hay = _haystack(product_name)
    for key, rx in _COMPILED:
        if rx.search(hay):
            return key
    return None


def _num(x: float, lang: str) -> str:
    """12 → "12", 0.5 → "0,5" — the decimal comma both audiences read."""
    if float(x).is_integer():
        return str(int(x))
    return f"{x:g}".replace(".", ",")


def _kcal(n: dict) -> int | None:
    if n.get("kcal") is not None:
        return int(n["kcal"])
    if any(n.get(k) is None for k in ("p", "f", "c", "fiber")):
        return None
    raw = 4 * n["p"] + 9 * n["f"] + 4 * n["c"] + 2 * n["fiber"]
    return int(round(raw / 10.0) * 10)


def _gi_text(gi: int, lang: str) -> str:
    words = _GI_WORD[lang]
    if gi == 0:
        word = words[0]
    elif gi <= 55:
        word = words["low"]
    elif gi < 70:
        word = words["mid"]
    else:
        word = words["high"]
    return f"~{gi} — {word}"


def _nutrition_block(key: str, lang: str) -> str | None:
    n = NUTRITION.get(key)
    if not n:
        return None
    u = _UNITS[lang]
    lines = [_HEAD[lang]["nutri"]]
    kcal = _kcal(n)
    if kcal is not None:
        lines.append(f"🔥 ~{kcal} {u['kcal']}")
    if n.get("p") is not None and n.get("f") is not None:
        lines.append(f"🥩 {u['p']} {_num(n['p'], lang)} {u['g']} · 🧈 {u['f']} {_num(n['f'], lang)} {u['g']}")
    if n.get("c") is not None and n.get("fiber") is not None:
        lines.append(f"🍞 {u['c']} {_num(n['c'], lang)} {u['g']} · 🌾 {u['fiber']} "
                     f"{_num(n['fiber'], lang)} {u['g']}")
    if n.get("gi") is not None:
        lines.append(f"📈 {u['gi']}: {_gi_text(n['gi'], lang)}")
    if n.get("keto"):
        lines.append(_KETO[lang][n["keto"]])
    note = (NUTRI_NOTE.get(key) or {}).get(lang)
    if note:
        lines.append(f"<i>{note}</i>")
    return "\n".join(lines)


def _render(key: str, lang: str) -> str:
    """The guide body in "uz" or "ru", with a {name} placeholder for the
    product's display name (filled in after transliteration, so the name is
    never run through it twice)."""
    g = GUIDES[key][lang]
    h = _HEAD[lang]
    parts = [h["title"], g["about"]]
    nutri = _nutrition_block(key, lang)
    if nutri:
        parts.append(nutri)
    parts.append("\n".join([h["benefits"]] + [f"• {b}" for b in g["benefits"]]))
    uses = [h["uses"]]
    for i, (title, text) in enumerate(g["uses"]):
        uses.append(f"{_NUM[i]} <b>{title}.</b> {text}")
    parts.append("\n".join(uses))
    parts.append("\n".join([h["cautions"]] + [f"• {c}" for c in g["cautions"]]))
    parts.append(f"{h['advice']} {g['advice']}")
    return "\n\n".join(parts)


def guide_text(product: dict, lang: str) -> str | None:
    """The full guide message for this product in the reader's language
    (uz / uz_cyr / ru), or None when the product has no guide."""
    key = guide_key(product.get("name") or "")
    if key is None:
        return None
    from locales import localize_product_text
    name = html.escape(localize_product_text(product.get("name"), product.get("name_ru"), lang) or "",
                       quote=False)
    if lang == "ru":
        body = _render(key, "ru")
    elif lang == "uz_cyr":
        from translit import lat_to_cyr
        body = lat_to_cyr(_render(key, "uz"))
    else:
        body = _render(key, "uz")
    return body.replace("{name}", name)


def guide_parts(product_name: str, lang: str) -> dict | None:
    """The guide's pieces (about, benefits, uses, cautions, advice) in the
    reader's language, for messages that quote one piece at a time — the
    daily interest nudge rotates through them. None when there's no guide."""
    key = guide_key(product_name)
    if key is None:
        return None
    g = GUIDES[key]["ru" if lang == "ru" else "uz"]
    if lang != "uz_cyr":
        return dict(g)
    from translit import lat_to_cyr
    return dict(about=lat_to_cyr(g["about"]),
                benefits=[lat_to_cyr(b) for b in g["benefits"]],
                uses=[(lat_to_cyr(t), lat_to_cyr(x)) for t, x in g["uses"]],
                cautions=[lat_to_cyr(c) for c in g["cautions"]],
                advice=lat_to_cyr(g["advice"]))


def card_line(product_name: str, lang: str) -> str | None:
    """One short line of numbers for the product card itself, e.g.
    «📊 100 g: ~590 kkal · uglevod 10 g · GI ~20 · ✅ keto». None when the
    product has no figures (no guide, or a kind where per-100 g numbers would
    be guesswork)."""
    key = guide_key(product_name)
    n = NUTRITION.get(key) if key else None
    if not n:
        return None
    kcal = _kcal(n)
    if kcal is None or n.get("c") is None:
        return None
    base = "ru" if lang == "ru" else "uz"
    u = _UNITS[base]
    bits = [f"~{kcal} {u['kcal']}", f"{u['carbs_short']} {_num(n['c'], base)} {u['g']}"]
    if n.get("gi") is not None:
        bits.append(f"{u['gi_short']} ~{n['gi']}")
    bits.append(f"{_KETO_MARK[n['keto']]} keto" if base == "uz" else f"{_KETO_MARK[n['keto']]} кето")
    line = f"📊 100 {u['g']}: " + " · ".join(bits)
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        line = lat_to_cyr(line)
    return line
