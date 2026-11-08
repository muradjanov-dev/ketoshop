"""AI sotuvchi javobidagi qoliplar ketma-ket takrorlanmasin.

Egasi, 2026-11-08, steviya haqidagi suhbatdan ("necha pul" / "kompot uchun ham
mumkinmi" / "uzoq saqlanadimi"): "robotga o'xshab faqat tasdiqlayvermasin,
sezilib qolyapti va noqulay bo'lyapti". Model har javobni "Ha, ..." bilan
boshlagan va oxirida har safar "Savatga qo'shamizmi? 🛒" degan.

Bu promptda taqiqlangan (ai_sales._sales_rules), lekin kichik model ba'zan
baribir shunday yozadi. Bitta "Ha," yoki bitta taklif odamdek eshitiladi, robotni
TAKROR fosh qiladi. Shuning uchun kod faqat takrorni oladi: oldingi javobda
ham bo'lgan qolip shu javobdan olib tashlanadi:
- javob boshidagi tasdiq ("Ha, ...", "Ha, albatta ...", "Да, ...", "Конечно, ...");
- "Savatga qo'shamizmi? 🛒" savoli (va uning ruscha/kirillcha shakli);
- "Agar xohlasangiz, ... aytib beramiz" va'dasi.
Javobning mazmuni o'zgarmaydi. Olib tashlangandan keyin hech narsa qolmasa,
asl javob qaytadi.
"""
import re

_APOS = "'‘’ʻʼ`"

# Javob boshidagi tasdiq so'zi: "Hamma", "Xamir", "Давайте" kabi so'zlar
# ushlanmasin, shuning uchun so'zdan keyin \b qo'yilgan.
_YES_WORD = r"(?:ha|xa|ҳа|ха|да|yes|albatta|албатта|конечно|sure|of\s+course)\b"
_YES_OPENER = re.compile(rf"^\s*{_YES_WORD}(?:[\s,!.:—–-]+{_YES_WORD})*[^\w«\"'(]*",
                         re.IGNORECASE)

_CART_ASK = re.compile(
    rf"(?:savatga\s+(?:\w+\s+)?(?:qo[{_APOS}]?sh|sol)\w*(?:\s+qo[{_APOS}]?y\w*)?"
    r"|саватга\s+(?:\w+\s+)?(?:қўш|қуш|сол)\w*(?:\s+қўй\w*)?"
    r"|(?:добав|полож)\w*\s+(?:\w+\s+)?в\s+корзин\w*"
    r"|в\s+корзину\s+(?:добав|полож)\w*"
    r"|add\s+(?:it\s+|them\s+|this\s+)?to\s+(?:your|the)\s+cart)"
    r"\s*\?",
    re.IGNORECASE)

_OFFER = re.compile(
    r"(?:agar\s+)?xohlasangiz\b[^.!?\n]*?\b(?:aytib|tushuntirib|taxmin\s+qilib)\s+beramiz"
    r"|(?:агар\s+)?хоҳласангиз\b[^.!?\n]*?\b(?:айтиб|тушунтириб|тахмин\s+қилиб)\s+берамиз"
    r"|если\s+хотите\b[^.!?\n]*?\b(?:подскаж|расскаж|объясн)\w*",
    re.IGNORECASE)

_SENTENCE_END = re.compile(r"[.!?…](?=\s)")
_END_MARK = re.compile(r"[.!?…]")


def starts_with_yes(text: str | None) -> bool:
    return bool(_YES_OPENER.match(text or ""))


def _drop_yes(text: str) -> str:
    rest = text[_YES_OPENER.match(text).end():]
    first_line = rest.split("\n", 1)[0]
    if len(re.findall(r"\w+", first_line)) < 2:
        return text            # "Ha 😊" — tasdiqdan boshqa gap yo'q
    return rest[:1].upper() + rest[1:]


def _cut(text: str, pattern: re.Pattern) -> str:
    """Pattern turgan gapni (jumlani) qatordan oladi. Qatorda boshqa gap
    bo'lsa, o'shalar qoladi. Qator bo'shab qolsa, qator ham olib tashlanadi."""
    lines = []
    for line in text.split("\n"):
        match = pattern.search(line)
        if not match:
            lines.append(line)
            continue
        while match:
            ends = [m.end() for m in _SENTENCE_END.finditer(line, 0, match.start())]
            start = ends[-1] if ends else 0
            end = match.end()
            if line[end - 1:end] not in "?.!…":
                mark = _END_MARK.search(line, end)
                end = mark.end() if mark else len(line)
            while end < len(line) and not line[end].isalnum() and line[end] not in "«\"'(":
                end += 1           # gap oxiridagi emoji (🛒) va bo'shliq
            line = (line[:start].rstrip() + " " + line[end:]).strip()
            match = pattern.search(line)
        if line:
            lines.append(line)
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def vary(reply: str, previous: str | None) -> str:
    """Oldingi javobda ham bo'lgan qolipni shu javobdan oladi."""
    if not reply or not previous:
        return reply
    out = reply
    if starts_with_yes(previous) and starts_with_yes(out):
        out = _drop_yes(out)
    for pattern in (_CART_ASK, _OFFER):
        if pattern.search(previous) and pattern.search(out):
            out = _cut(out, pattern)
    return out if re.search(r"\w", out) else reply
