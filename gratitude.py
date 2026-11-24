"""Mijoz minnatdorchilik bildirsa — samimiy tashakkur.

Egasi, 2026-11-24: "botdan kelgan minnatdorchilik izohlariga samimiy tashakkur
va bu bizni va jamoamizni ko'proq insonlarga sog'lom va 100% tabiiy
mahsulotlarni yetkazib berishga va insonlarni sog'lomroq bo'lishlariga
qo'limizdan kelgancha harakat qilamiz degandek javob ber", "samimiy chiqsin",
"Assalomu alaykum dan boshla, agar salom berilgan bo'lsa avval alik ol".

Qayerda: AI chatda faqat "rahmat" (avval javobsiz qolardi), 4-5 yulduzli
sharh izohi va 8-10 balli NPS izohi. Uchta har xil to'liq javob — qolip
bo'lmasin. Bir kunda ikkinchi "rahmat" ga — qisqa iliq javob, nutq emas.
"""
import random
import re
import time

from translit import lat_to_cyr

FULL = [
    ("Iliq so'zlaringiz uchun chin dildan rahmat! 💚\n\n"
     "Bunday fikrlar bizni va butun jamoamizni ko'proq insonlarga sog'lom va 100% tabiiy "
     "mahsulotlar yetkazib berishga ilhomlantiradi. Insonlar sog'lomroq bo'lishi uchun "
     "qo'limizdan kelgancha harakat qilamiz 🌿",
     "От всей души спасибо за тёплые слова! 💚\n\n"
     "Такие отзывы вдохновляют нас и всю нашу команду доставлять ещё большему числу людей "
     "полезные и на 100% натуральные продукты. Мы делаем всё, что в наших силах, чтобы люди "
     "становились здоровее 🌿"),
    ("Samimiy minnatdorchiligingiz uchun katta rahmat! 🤗\n\n"
     "Siz kabi mijozlarimizning fikri bizga kuch beradi: jamoamiz har kuni ko'proq odamlarga "
     "sog'lom va 100% tabiiy mahsulotlarni yetkazish uchun ishlaydi. Har bir mijozimiz "
     "sog'lomroq bo'lishi uchun qo'limizdan kelganini qilamiz 💚",
     "Огромное спасибо за ваши искренние слова! 🤗\n\n"
     "Они придают сил всей нашей команде: каждый день мы работаем, чтобы полезные и на 100% "
     "натуральные продукты доходили до всё большего числа людей. И делаем всё возможное, "
     "чтобы наши клиенты становились здоровее 💚"),
    ("Sizga chin dildan rahmat, bu so'zlar biz uchun juda qadrli 💚\n\n"
     "Aynan shunday fikrlar bizni va jamoamizni yanada ko'proq insonlarga sog'lom, 100% tabiiy "
     "mahsulotlar yetkazishga undaydi. Insonlarning sog'lig'i yo'lida qo'limizdan kelgancha "
     "harakat qilaveramiz. Sog'lig'ingiz mustahkam bo'lsin! 🌿",
     "Сердечно благодарим вас, такие слова для нас очень ценны 💚\n\n"
     "Именно они вдохновляют нас и нашу команду доставлять ещё больше полезных и на 100% "
     "натуральных продуктов. Мы и дальше будем делать всё, что в наших силах, ради здоровья "
     "людей. Крепкого вам здоровья! 🌿"),
]
SHORT = [
    ("Sizga ham katta rahmat! 😊 Sog'lig'ingiz mustahkam bo'lsin 💚",
     "И вам большое спасибо! 😊 Крепкого здоровья 💚"),
    ("Arzimaydi, doim xizmatingizdamiz 🌿",
     "Всегда рады помочь 🌿"),
    ("Sizga rahmat! Biror savol bo'lsa, bemalol yozib yuborsangiz bo'ladi 😊",
     "Спасибо вам! Если появятся вопросы, пишите, пожалуйста 😊"),
]
FULL_EVERY = 24 * 3600          # to'liq javob bir odamga kuniga bir marta

_GREETING = re.compile(
    r"^\W*(?:as+alomu?\s*alaykum|as+alom|salom|ассалому?\s*алайкум|ассалом|салом|"
    r"здравствуй\w*|привет\w*|добр(?:ый|ое|ого)\s+(?:день|утро|вечер))\b",
    re.IGNORECASE)
_THANKS = re.compile(
    r"^\W*(?:(?:as+alomu?\s*alaykum|as+alom|salom|ассалому?\s*алайкум|ассалом|салом|"
    r"здравствуй\w*|добр(?:ый|ое|ого)\s+(?:день|утро|вечер))\W*)?"
    r"(?:(?:katta|kattakon|juda|chin\s+dildan|катта|жуда|большое|огромное)\s+)?"
    r"(?:rahmat|raxmat|rahmet|tashakkur|minnatdorman|спасибо|спс|благодарю|рахмат|раҳмат|ташаккур)"
    r"(?:\s+(?:katta|kattakon|sizga|sizlarga|сизга|катта|большое|вам|juda\s+ham))*\W*$",
    re.IGNORECASE)
_RUSSIAN = re.compile(r"спасибо|спс|благодар|здравствуй|привет|добр", re.IGNORECASE)
_CYRILLIC = re.compile(r"[а-яёўқғҳ]", re.IGNORECASE)

_last_full: dict[int, float] = {}


def is_thanks(text: str | None) -> bool:
    """Faqat minnatdorchilik (salom bilan bo'lishi mumkin): "rahmat",
    "Assalomu alaykum, katta rahmat", "спасибо большое"."""
    return bool(_THANKS.match(text or ""))


def language(text: str | None, fallback: str) -> str:
    """Mijoz qaysi tilda yozgan bo'lsa — o'sha tilda javob."""
    text = text or ""
    if _RUSSIAN.search(text):
        return "ru"
    if _CYRILLIC.search(text):
        return "uz_cyr"
    if re.search(r"[a-z]", text, re.IGNORECASE):
        return "uz"
    return fallback


def _say(pair: tuple[str, str], lang: str) -> str:
    uz, ru = pair
    if lang == "ru":
        return ru
    return lat_to_cyr(uz) if lang == "uz_cyr" else uz


def greeting(customer_text: str | None, lang: str) -> str:
    """'Assalomu alaykum!' — mijoz salom bergan bo'lsa, avval alik: 'Va alaykum assalom!'."""
    greeted = bool(_GREETING.match(customer_text or ""))
    if lang == "ru":
        return "Здравствуйте!"
    return _say(("Va alaykum assalom!" if greeted else "Assalomu alaykum!", ""), lang)


def reply(lang: str, customer_text: str | None = None, user_id: int | None = None) -> str:
    """Salom (yoki alik) + samimiy tashakkur. Shu odamga bugun to'liq javob
    berilgan bo'lsa — qisqa iliq javob, salomsiz."""
    now = time.time()
    if user_id is not None and now - _last_full.get(user_id, 0) < FULL_EVERY:
        return _say(random.choice(SHORT), lang)
    if user_id is not None:
        _last_full[user_id] = now
    return f"{greeting(customer_text, lang)} {_say(random.choice(FULL), lang)}"
