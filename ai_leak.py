"""Ichki ma'lumot mijozga chiqmasin (egasi, 2026-11-27: "ichki ma'lumotlarni mijozlar
so'rasa aytmasligi kerak").

Prompt allaqachon "ichki narsalarni aytma" deydi — bu kod darajasidagi ikkinchi qatlam:
AI javobi mijozga ketishidan oldin tekshiriladi. Topilsa — model bir marta qayta
yozadi (ai_sales LEAK_FIX), baribir qolsa — o'sha qatorlar olib tashlanadi, hammasi
ketsa — muloyim rad javobi. Izohlar va Direct'da — javob o'rniga ushlab turuvchi matn.

Nima ichki: tannarx, ustama/marja, kirim (sotib olish) narxi, yetkazib beruvchilar;
prompt, qoidalar, vositalar va tizim belgilari; adminlarning Telegram ID raqamlari.
Mahsulot foydasi ("tolaga boy, foydasi …"), sotuv narxi va qoldiq — ichki EMAS.
"""
from __future__ import annotations

import re

COST = re.compile(
    r"tannarx|таннарх|себестоим|nakrutka|накрутк|наценк|\bmarja\w*|маржа\w*|"
    r"kirim\s+narx|кирим\s+нарх|sotib\s+olish\s+narx|sotib\s+olgan\s+narx|закупочн\w*|закупк\w*\s+цен|"
    r"yetkazib\s+beruvchi|етказиб\s+берувчи|поставщик\w*|supplier|optom\s+olib\s+keladigan|"
    r"ustama(?:miz|\s+foiz|\s+\d)|устама(?:миз|\s+фоиз)",
    re.IGNORECASE)
INTERNAL = re.compile(
    r"\[\s*TIZIM|\bTIZIM\s*:|MIJOZ\s+XOTIRASI|system\s+prompt|\bprompt\w*|промпт\w*|"
    r"function[_\s]call|tool[_\s]call|\bai_sales\b|\bdatabase\b|"
    r"ko['ʻ’]rsatmalarim|qoidalarim\b|мои\s+инструкци|системн\w+\s+инструкци",
    re.IGNORECASE)

SAFE_REPLY = {
    "uz": "Bu ichki ma'lumot, uni ulasha olmaymiz 🙂 Mahsulot, narx yoki buyurtma bo'yicha bemalol so'rang — yordam beramiz.",
    "ru": "Это внутренняя информация, её мы не раскрываем 🙂 По товарам, ценам и заказам — с радостью поможем.",
}


def reasons(reply: str | None, admin_ids=()) -> list[str]:
    text = reply or ""
    found = []
    if COST.search(text):
        found.append("tannarx/ustama/yetkazib beruvchi")
    if INTERNAL.search(text):
        found.append("ichki qoida/tizim so'zlari")
    for admin_id in admin_ids or ():
        if admin_id and str(admin_id) in text:
            found.append("admin ID")
            break
    return found


def strip(reply: str, admin_ids=()) -> str:
    """Ichki ma'lumotli qatorlarni olib tashlaydi."""
    keep = [line for line in (reply or "").split("\n") if not reasons(line, admin_ids)]
    return "\n".join(keep).strip()


def safe_reply(lang: str) -> str:
    text = SAFE_REPLY["ru" if lang == "ru" else "uz"]
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        text = lat_to_cyr(text)
    return text
