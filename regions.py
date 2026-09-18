"""Buyurtma manzilidan O'zbekiston hududini aniqlash.

Buyurtmada viloyat alohida saqlanmaydi — xaridor yo manzilni yozadi, yo
Telegram'dan lokatsiya yuboradi. Shuning uchun hudud ikki yo'l bilan
topiladi:

  1. Manzil matnidan — shahar/tuman nomlari bo'yicha. Eng ishonchli yo'l,
     chunki xaridorning o'zi yozgan. Lotin, kirill va ruscha yozuvlar ham
     qamrab olingan, chunki uchalasi ham bazada uchraydi.
  2. Koordinatadan — matn hech narsa bermasa, eng yaqin viloyat markazi.
     Taxminiy, lekin xaridorlarning deyarli hammasi shahar ichida turadi,
     shuning uchun amalda to'g'ri chiqadi. 250 km dan uzoq nuqta hech
     qaysi markazga bog'lanmaydi — noto'g'ri javobdan ko'ra "aniqlanmagan"
     yaxshiroq.

Tartib muhim: "Toshkent viloyati" "Toshkent"dan OLDIN tekshiriladi, aks
holda har bir viloyat buyurtmasi poytaxt hisobiga yozilardi. Shu sababli
hududlar ro'yxat (dict emas) va har birining kalit so'zlari o'z ichida
uzunidan qisqasiga tekshiriladi.
"""
import math
import re
import unicodedata

# (key, uz nomi, ru nomi, markaz (lat, lng), kalit so'zlar)
# Kalit so'zlar kichik harfda va apostrofsiz yoziladi — _norm() ham shunday
# qiladi, shuning uchun "Farg'ona", "Fargona" va "Фаргона" bir xil topiladi.
REGIONS = [
    ("tashkent_region", "Toshkent viloyati", "Ташкентская область", (41.10, 69.60), [
        "toshkent viloyat", "toshkent vil", "тошкент вилоят", "ташкентская область",
        "ташкентской области", "ташкентская обл",
        "chirchiq", "чирчик", "olmaliq", "алмалык", "angren", "ангрен",
        "ohangaron", "ахангаран", "bekobod", "бекабад", "yangiyol", "янгиюль",
        "parkent", "паркент", "piskent", "пскент", "qibray", "кибрай",
        "zangiota", "зангиата", "chinoz", "чиназ", "buka", "бука",
        "gazalkent", "газалкент", "keles", "келес",
        "nurafshon", "нурафшон", "tuytepa", "туйтепа",
    ]),
    ("tashkent", "Toshkent shahri", "город Ташкент", (41.31, 69.28), [
        "toshkent", "тошкент", "ташкент", "tashkent",
        "chilonzor", "чиланзар", "yunusobod", "юнусабад", "mirzo ulugbek",
        "мирзо улугбек", "yakkasaroy", "яккасарай", "shayxontohur",
        "шайхантахур", "olmazor", "алмазар", "sergeli", "сергели",
        "bektemir", "бектемир", "mirobod", "мирабад", "uchtepa", "учтепа",
        "yashnobod", "яшнабад", "yangihayot", "янгихаёт",
    ]),
    ("samarkand", "Samarqand", "Самарканд", (39.65, 66.96), [
        "samarqand", "самарканд", "самарқанд", "urgut", "ургут",
        "kattaqorgon", "каттакурган", "bulungur", "булунгур",
        "ishtixon", "иштыхан", "jomboy", "джамбай", "pastdargom", "пастдаргом",
    ]),
    ("bukhara", "Buxoro", "Бухара", (39.77, 64.42), [
        "buxoro", "бухара", "бухоро", "kogon", "каган", "gijduvon", "гиждуван",
        "vobkent", "вабкент", "romitan", "ромитан", "olot", "алат",
    ]),
    ("namangan", "Namangan", "Наманган", (41.00, 71.67), [
        "namangan", "наманган", "chust", "чуст", "pop", "поп",
        "chortoq", "чартак", "kosonsoy", "касансай", "uchqorgon", "учкурган",
        "torakorgon", "туракурган", "mingbuloq", "мингбулак",
    ]),
    ("andijan", "Andijon", "Андижан", (40.78, 72.34), [
        "andijon", "андижан", "андижон", "asaka", "асака", "shahrixon",
        "шахрихан", "xonobod", "ханабад", "qorgontepa", "кургантепа",
        "marhamat", "мархамат", "paxtaobod", "пахтаабад", "baliqchi", "балыкчи",
    ]),
    ("fergana", "Farg'ona", "Фергана", (40.39, 71.78), [
        "fargona", "фергана", "фаргона", "qoqon", "kokand", "коканд", "қўқон",
        "margilon", "маргилан", "quvasoy", "кувасай", "rishton", "риштан",
        "oltiariq", "алтыарык", "beshariq", "бешарык", "buvayda", "бувайда",
        "dangara", "дангара", "yozyovon", "язъяван",
    ]),
    ("navoi", "Navoiy", "Навои", (40.10, 65.37), [
        "navoiy", "навои", "навоий", "zarafshon", "зарафшан", "uchquduq",
        "учкудук", "karmana", "кармана", "nurota", "нурата", "konimex", "канимех",
    ]),
    ("kashkadarya", "Qashqadaryo", "Кашкадарья", (38.86, 65.79), [
        "qashqadaryo", "кашкадар", "қашқадарё", "qarshi", "карши", "қарши",
        "shahrisabz", "шахрисабз", "kitob", "китаб", "gozon", "газган",
        "koson", "касан", "muborak", "мубарек", "dehqonobod", "дехканабад",
    ]),
    ("surkhandarya", "Surxondaryo", "Сурхандарья", (37.23, 67.28), [
        "surxondaryo", "сурхандар", "сурхондарё", "termiz", "термез", "термиз",
        "denov", "денау", "sherobod", "шерабад", "boysun", "байсун",
        "qumqorgon", "кумкурган", "jarqorgon", "джаркурган",
    ]),
    ("jizzakh", "Jizzax", "Джизак", (40.12, 67.84), [
        "jizzax", "джизак", "жиззах", "gallaorol", "галляарал",
        "zomin", "зомин", "зааминь", "dostlik", "дустлик", "pahtakor", "пахтакор",
    ]),
    ("syrdarya", "Sirdaryo", "Сырдарья", (40.49, 68.78), [
        "sirdaryo", "сырдар", "сирдарё", "guliston", "гулистан", "гулистон",
        "yangiyer", "янгиер", "shirin", "ширин", "boyovut", "баяут",
        "sardoba", "сардоба", "oqoltin", "акалтын", "gulistan",
    ]),
    ("khorezm", "Xorazm", "Хорезм", (41.55, 60.63), [
        "xorazm", "хорезм", "хоразм", "urganch", "ургенч", "урганч",
        "xiva", "хива", "khiva", "shovot", "шават", "gurlan", "гурлен",
        "xonqa", "ханка", "yangiariq", "янгиарык", "bogot", "багат",
    ]),
    ("karakalpakstan", "Qoraqalpog'iston", "Каракалпакстан", (42.46, 59.61), [
        "qoraqalpog", "qoraqalpoq", "каракалпак", "қорақалпоғ",
        "nukus", "нукус", "мойнак", "moynoq", "xojayli", "ходжейли",
        "beruniy", "беруни", "chimboy", "чимбай", "taxiatosh", "тахиаташ",
        "qongirot", "кунград", "shumanay", "шуманай", "tortkol", "турткуль",
    ]),
]

UNKNOWN_KEY = "unknown"
UNKNOWN_UZ = "Aniqlanmagan"
UNKNOWN_RU = "Не определён"

# A pin further than this from every regional centre is not assigned to one:
# a wrong province is worse than an honest "unknown".
MAX_PIN_KM = 250

NAMES = {key: {"uz": uz, "ru": ru} for key, uz, ru, _, _ in REGIONS}
NAMES[UNKNOWN_KEY] = {"uz": UNKNOWN_UZ, "ru": UNKNOWN_RU}

_APOSTROPHES = "'‘’ʻʼ`´"
_TRANS = str.maketrans({ch: "" for ch in _APOSTROPHES})


def _norm(text: str) -> str:
    """Lowercase, apostrophes dropped, punctuation flattened to spaces.

    "Farg'ona", "Fargʻona" and "FARGONA" all become "fargona", so a keyword
    list doesn't have to carry every apostrophe variant the shop's buyers
    type. Cyrillic is left as-is and matched by its own keywords — a
    transliteration pass here would only add a second way to be wrong.
    """
    text = unicodedata.normalize("NFKC", text or "").lower().translate(_TRANS)
    return re.sub(r"[^\wЀ-ӿ]+", " ", text, flags=re.UNICODE).strip()


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1 = math.radians(a[0]), math.radians(a[1])
    lat2, lng2 = math.radians(b[0]), math.radians(b[1])
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2)
    return 2 * 6371.0 * math.asin(min(1.0, math.sqrt(h)))


def region_from_text(address: str | None) -> str | None:
    """Region key from a written address, or None if nothing matched."""
    hay = _norm(address)
    if not hay:
        return None
    for key, _uz, _ru, _centre, keywords in REGIONS:
        for kw in keywords:
            if _norm(kw) in hay:
                return key
    return None


def region_from_pin(lat, lng) -> str | None:
    """Region key from a map pin — the nearest regional centre, or None when
    the pin is too far from all of them to guess honestly."""
    try:
        point = (float(lat), float(lng))
    except (TypeError, ValueError):
        return None
    if not point[0] or not point[1]:
        return None
    best_key, best_km = None, None
    for key, _uz, _ru, centre, _kw in REGIONS:
        km = _haversine_km(point, centre)
        if best_km is None or km < best_km:
            best_key, best_km = key, km
    return best_key if best_km is not None and best_km <= MAX_PIN_KM else None


def region_of(order: dict) -> str:
    """The region an order belongs to. Text first, then the pin, then
    'unknown' — never a guess dressed up as a fact."""
    return (region_from_text(order.get("address"))
            or region_from_pin(order.get("latitude"), order.get("longitude"))
            or UNKNOWN_KEY)


def region_name(key: str, lang: str = "uz") -> str:
    entry = NAMES.get(key) or NAMES[UNKNOWN_KEY]
    return entry.get("ru" if lang == "ru" else "uz", key)
