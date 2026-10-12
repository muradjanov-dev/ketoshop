"""
«📍 Keto shop manzili» — kanal va botdagi har bir post tagidagi havola.

Egasi, 2026-10-12: "kanalga va botga yuboriladigan har bir post tagida
tartibli bo'lib «Keto shop manzili» deb, uni ichiga link qilib qo'y".
Havola kanaldagi do'kon manzili postiga olib boradi.

Tartib hamma postda bir xil: post matni → (yoqilgan bo'lsa) chegirma
eslatmasi → bo'sh qator → 📍 manzil. Manzil doim eng oxirgi qator.
Matn va havola faqat shu yerda — o'zgartirish bir joyda.
"""
from translit import lat_to_cyr

ADDRESS_URL = "https://t.me/ketoshop_uz/1071"

_LABEL = {
    "uz": "Keto shop manzili",
    "ru": "Адрес Keto shop",
}


def line(lang: str) -> str:
    """Bitta qator: 📍 + havola, o'quvchi tilida (uz / uz_cyr / ru)."""
    if lang == "ru":
        label = _LABEL["ru"]
    elif lang == "uz_cyr":
        label = lat_to_cyr(_LABEL["uz"])
    else:
        label = _LABEL["uz"]
    return f'📍 <a href="{ADDRESS_URL}">{label}</a>'


def footer(lang: str) -> str:
    """Post oxiriga qo'shiladigan blok: "\\n\\n📍 ..."."""
    return "\n\n" + line(lang)


def add(text: str, lang: str, limit: int = 4096) -> str:
    """`text` + manzil. Telegram chegarasidan (matn 4096, rasm izohi 1024)
    oshib ketsa — o'zgarishsiz: post manzilsiz chiqqani yo'qolganidan yaxshi."""
    tail = footer(lang)
    return text + tail if len(text) + len(tail) <= limit else text
