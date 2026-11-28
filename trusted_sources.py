"""Ishonchli manbalardan qisqa javob (egasi, 2026-11-28: "stevia, eritritol va shunga o'xshash
mahsulotlar haqida so'ralsa internetdagi ishonchli manbalardan olib ham javob beraver, manbani
keltirib, agar zarurat bo'lsa").

lookup(savol) — OpenAI veb-qidiruvi FAQAT ALLOWED_DOMAINS dagi saytlarda (sog'liqni saqlash
tashkilotlari, oziq-ovqat xavfsizligi idoralari, ilmiy maqolalar bazasi, yirik klinikalar).
Natija: 2–4 gapli o'zbekcha javob va 1–2 manba (nomi + havola). Bir xil savol CACHE_DAYS
davomida qayta qidirilmaydi. Xato yoki manba topilmasa — "" (AI o'z bilimi bilan, ehtiyotkor
javob beradi).
"""
from __future__ import annotations

import logging
import os
import re
import time

import database

logger = logging.getLogger(__name__)

MODEL = os.getenv("TRUSTED_SOURCES_MODEL", "gpt-5.4-mini").strip()
SEARCH_FEE_USD = 0.01                # bitta veb-qidiruv chaqiruvi (taxminiy)
CACHE_DAYS = 7
USAGE_TAG = " · manba"
ALLOWED_DOMAINS = [
    "who.int", "fda.gov", "efsa.europa.eu", "nih.gov", "ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov",
    "mayoclinic.org", "clevelandclinic.org", "health.harvard.edu", "hsph.harvard.edu",
    "hopkinsmedicine.org", "nhs.uk", "diabetes.org", "eatright.org", "cochranelibrary.com",
    "food.gov.uk", "canada.ca",
]
RULES = (
    "Sen Keto shop maslahatchisiga yordamchisan. Savolga FAQAT topilgan ishonchli manbalar asosida "
    "o'zbekcha 2–4 qisqa gapda javob ber: aniq fakt (xavfsiz miqdor, qon shakariga ta'siri, kimlarga "
    "ehtiyot bo'lish kerak). Tibbiy va'da berma; kasallik bo'lsa shifokor bilan maslahatlashishni ayt. "
    "Oxirida alohida qatorda 1–2 manba: 'Manba: <tashkilot nomi> — <havola>'. Manba topilmasa — "
    "faqat 'TOPILMADI' deb yoz.")

_cache: dict[str, tuple[float, str]] = {}


def _key(question: str) -> str:
    return re.sub(r"\W+", " ", (question or "").lower()).strip()[:300]


def _sources(resp) -> list[tuple[str, str]]:
    found = []
    for item in getattr(resp, "output", None) or []:
        for part in getattr(item, "content", None) or []:
            for ann in getattr(part, "annotations", None) or []:
                url = getattr(ann, "url", None)
                if url and all(url != u for _, u in found):
                    found.append((getattr(ann, "title", None) or url, url))
    return found[:2]


async def lookup(question: str) -> str:
    key = _key(question)
    if not key:
        return ""
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_DAYS * 86400:
        return hit[1]
    try:
        import comment_ai
        import openai
        api_key = await comment_ai._openai_key()
        if not api_key:
            return ""
        client = openai.AsyncOpenAI(api_key=api_key, timeout=60.0, max_retries=1)
        resp = await client.responses.create(
            model=MODEL, instructions=RULES,
            input=[{"role": "user", "content": [{"type": "input_text", "text": question[:600]}]}],
            tools=[{"type": "web_search", "search_context_size": "low",
                    "filters": {"allowed_domains": ALLOWED_DOMAINS}}],
            reasoning={"effort": "low"}, max_output_tokens=1500)
    except Exception as exc:
        logger.info("trusted sources lookup failed: %s", exc)
        return ""
    try:
        import ai_provider
        u = ai_provider._openai_usage(getattr(resp, "usage", None))
        await database.record_ai_usage(MODEL + USAGE_TAG, "openai", u.input, u.cached, u.output,
                                       ai_provider.estimate_cost(MODEL, u.input, u.cached, u.output) + SEARCH_FEE_USD)
    except Exception:
        logger.debug("trusted sources usage not recorded", exc_info=True)
    text = (getattr(resp, "output_text", "") or "").strip()
    if not text or "TOPILMADI" in text.upper():
        _cache[key] = (time.time(), "")
        return ""
    if "Manba:" not in text:
        refs = _sources(resp)
        if not refs:
            _cache[key] = (time.time(), "")
            return ""
        text += "\n" + "\n".join(f"Manba: {title} — {url}" for title, url in refs)
    _cache[key] = (time.time(), text[:1500])
    return text[:1500]
