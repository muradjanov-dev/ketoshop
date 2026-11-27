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
Bitta istisno takrorni kutmaydi: "... farqini HAM aytib beramiz" kabi
qo'shimcha va'da birinchi martadan olinadi (egasi, 2026-11-16, kanal guruhi).
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

# "... farqini HAM aytib beramiz" — javobga qo'shimcha va'da. Bu doim bo'sh: aytsa
# bo'ladigan narsa shu javobda aytilishi kerak edi (egasi, 2026-11-16 — guruhda
# "farqini ham aytib beramiz" deyilgan, keyin "farqini ayting" javobsiz qolgan).
# Shuning uchun birinchi martadan olinadi. "Narxini aytib beramiz" (ham siz) —
# mijozdan nimadir so'rashi mumkin, u faqat takrorlansa olinadi (_OFFER).
_EXTRA_OFFER = re.compile(
    r"(?:agar|xohlasangiz|istasangiz|qiziqsangiz)\b[^.!?\n]*?\bham\b[^.!?\n]*?"
    r"\b(?:(?:aytib|tushuntirib|taxmin\s+qilib|solishtirib)\s+beramiz|aytamiz|tushuntiramiz)\b"
    r"|(?:агар|хоҳласангиз|истасангиз|қизиқсангиз)\b[^.!?\n]*?\bҳам\b[^.!?\n]*?"
    r"\b(?:(?:айтиб|тушунтириб|солиштириб)\s+берамиз|айтамиз|тушунтирамиз)"
    r"|(?:если|хотите)\b[^.!?\n]*?\b(?:также|ещё|еще|тоже|и)\s+(?:\w+\s+)?(?:подскаж|расскаж|объясн|сравн)\w*"
    r"|(?:если|хотите)\b[^.!?\n]*?\b(?:подскаж|расскаж|объясн|сравн)\w*[^.!?\n]*?\b(?:также|ещё|еще|тоже)\b",
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
            if re.search(r"\w", line[start:match.start()]):
                # Gap o'rtasida ("Pishiriqqa alluloza mos, agar xohlasangiz ...") —
                # gapning boshi qoladi, faqat qolip bo'lagi olinadi.
                head = line[:match.start()].rstrip(" ,;:-—–")
                if head and head[-1] not in ".!?…":
                    head += "."
                line = (head + " " + line[end:]).strip()
            else:
                line = (line[:start].rstrip() + " " + line[end:]).strip()
            match = pattern.search(line)
        if line:
            lines.append(line)
    text = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def vary(reply: str, previous: str | None) -> str:
    """"... ham aytib beramiz" va'dasini doim, oldingi javobda ham bo'lgan
    qolipni esa takror bo'lganda shu javobdan oladi."""
    if not reply:
        return reply
    out = reply
    if _EXTRA_OFFER.search(out):
        out = _cut(out, _EXTRA_OFFER)
    if previous:
        if starts_with_yes(previous) and starts_with_yes(out):
            out = _drop_yes(out)
        for pattern in (_CART_ASK, _OFFER):
            if pattern.search(previous) and pattern.search(out):
                out = _cut(out, pattern)
    return out if re.search(r"\w", out) else reply


# Mijoz salom bersa — javobda salom albatta bo'lsin (egasi, 2026-11-22: "20% ga
# odobliroq qil"; jonli sinovda ruscha "Здравствуйте, где мой заказ?" ga javob
# salomsiz boshlangan). Prompt so'raydi, kod kafolatlaydi.
_CUSTOMER_GREETING = re.compile(
    r"^\W*(?:(?P<ru>здравствуй\w*|привет\w*|добр(?:ый|ое|ого)\s+(?:день|утро|вечер)|доброго\s+времени)"
    r"|(?P<cyr>ассалому?\s*алайкум|ассалом|салом)"
    r"|(?P<lat>as+alomu?\s*alaykum|as+alom|salom|assalamu\s*alaykum)"
    r"|(?P<en>hello|hi|good\s+(?:morning|afternoon|evening)))\b",
    re.IGNORECASE)
_REPLY_GREETING = re.compile(
    r"^\W*(?:va\s*alaykum|vaalaykum|as+alomu?|salom|ва\s*алайкум|ваалайкум|ассалом|салом|"
    r"здравствуй|добр(?:ый|ое|ого)|привет|hello|hi\b|good\s+(?:morning|afternoon|evening))",
    re.IGNORECASE)
_GREETING_BACK = {"ru": "Здравствуйте!", "cyr": "Ва алайкум ассалом!", "lat": "Va alaykum assalom!",
                  "en": "Hello!"}


def greet_back(reply: str, customer_text: str | None) -> str:
    """Mijoz salom bilan boshlagan, javob esa salomsiz bo'lsa — salomni qo'shadi."""
    match = _CUSTOMER_GREETING.match(customer_text or "")
    if not reply or not match or _REPLY_GREETING.match(reply):
        return reply
    kind = next(k for k, v in match.groupdict().items() if v)
    return f"{_GREETING_BACK[kind]}\n\n{reply}"


# Suhbat o'rtasida yangidan salomlashish (egasi, 2026-11-26: "gaplashayotgan mijozi bilan
# suhbat o'rtasida assalomu alaykum demagin, axir mijoz portreti bor-ku").
_OPENING = re.compile(
    r"^\s*(?:as+alomu?\s*alaykum|assalamu\s*alaykum|ассалому?\s*алайкум|здравствуйте|здравствуй|"
    r"добр(?:ый|ое)\s+(?:день|утро|вечер)|salom|салом|hello)\b[^\n.!?]*[!.]?[ \t]*"
    r"(?:[^\n]*?(?:xush kelibsiz|хуш келибсиз|добро пожаловать)[^\n]*)?\s*",
    re.IGNORECASE)


def drop_midchat_greeting(reply: str, customer_text: str | None, mid_conversation: bool) -> str:
    """Suhbat davom etayotgan bo'lsa (yaqinda gaplashgan) va mijoz o'zi salom bermagan
    bo'lsa — javob boshidagi "Assalomu alaykum! … xush kelibsiz" olib tashlanadi."""
    if not reply or not mid_conversation or _CUSTOMER_GREETING.match(customer_text or ""):
        return reply
    rest = _OPENING.sub("", reply, count=1).lstrip()
    if not rest or rest == reply.lstrip():
        return reply
    return rest[0].upper() + rest[1:]
