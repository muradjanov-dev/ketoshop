"""AI sotuvchi sinovi: bir oy oldingi va hozirgi versiya yonma-yon (egasi, 2026-11-27:
"test qilib ko'r ai model 1 oy avvalgiga qaraganda yaxshiroq va aqilliroqmi yoki yomonroq?").

* ESKI — 2026-10-26 dagi qoidalar (ai_eval_old_rules.py, git tarixidan, 96ccee2) va o'sha
  paytdagi model (gpt-5.4-mini).
* YANGI — hozirgi qoidalar (ai_sales._sales_rules) va hozirgi model (ai_sales.PROVIDER).
* Ikkalasiga bir xil katalog va do'kon ma'lumoti (ai_sales._dynamic_block), bir xil savollar.
  Vositalar (savat, buyurtma) yo'q — sof bilim va ohang sinovi.
* Hakam — kuchliroq model (JUDGE_MODEL), javoblar A/B tasodifiy almashtiriladi: qaysi biri
  eski, qaysi biri yangi ekanini bilmaydi.

/ai_sinov — faqat egasi. Mijozga hech narsa yuborilmaydi, bazaga yozilmaydi (faqat ai_usage).
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import random

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

import database

logger = logging.getLogger(__name__)
router = Router(name="ai_eval")

OLD_MODEL = "gpt-5.4-mini"
OLD_DATE = "26.10.2026"
JUDGE_MODEL = os.getenv("AI_EVAL_JUDGE", "gpt-5.4").strip()
USAGE_TAG = " · sinov"
PARALLEL = 4

QUESTIONS = [
    "Steviya bilan murabbo qilsa bo'ladimi?",
    "Yashil grechka donidan non retseptini bera olasizmi?",
    "Bodom uni 1 kg qancha turadi?",
    "Zangiota tumaniga yetkazib berasizlarmi, qancha bo'ladi?",
    "Hozir qanday aksiya yoki sovg'a bor?",
    "Assalomu alaykum",
    "Здравствуйте, есть ли у вас мука для кето хлеба?",
    "Ассалому алайкум, қандли диабет учун қайси ширинлаштирувчи яхши?",
    "Eritritol bilan alluloza farqi nima, qaysi biri yaxshi?",
    "Farzandimga shakarsiz shirinlik qilmoqchiman, nima tavsiya qilasiz?",
    "Keto dietada guruch yesa bo'ladimi?",
    "Psillium nima uchun kerak, qanday ishlatiladi?",
    "Kokos uni 500 gramligi bormi?",
    "Qimmat ekan, arzonroq qilib bera olasizmi?",
    "Kecha buyurtma bergandim, hali kelmadi",
]

JUDGE_RULES = """Sen tajribali sotuv murabbiyisan. Keto shop (keto, PP, glyutensiz, qandsiz mahsulotlar do'koni)
Telegram sotuvchisining ikki xil javobini (A va B) bitta mijoz savoliga solishtirasan. Ikkalasi bir xil
katalogni ko'rgan; savat va buyurtma vositalari yo'q edi.

Mezonlar: 1) to'g'rilik — faktlar, narx va mahsulot katalogga mos, to'qima yo'q; 2) savolning o'ziga aniq,
amaliy javob (avval javob, keyin maslahat); 3) odamdek, tabiiy, samimiy — qolip, takror, robot ohangi,
buyruq ohangi yo'q; 4) qisqa (Telegram chat); 5) muloyim sotuv — foydali taklif, majburlamay;
6) mijoz tilida va yozuvida.

Har biriga 1–10 baho ber (butun son). better: "A", "B" yoki "teng". reason — o'zbekcha, bitta qisqa gap:
nima uchun biri yaxshiroq (aniq farq)."""
JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"a": {"type": "integer"}, "b": {"type": "integer"},
                   "better": {"type": "string", "enum": ["A", "B", "teng"]},
                   "reason": {"type": "string"}},
    "required": ["a", "b", "better", "reason"],
    "additionalProperties": False,
}


def old_rules() -> str:
    from ai_eval_old_rules import OLD_RULES
    return OLD_RULES


async def _client():
    import comment_ai
    import openai
    key = await comment_ai._openai_key()
    if not key:
        return None
    return openai.AsyncOpenAI(api_key=key, timeout=120.0, max_retries=1)


async def _record(model: str, resp) -> None:
    try:
        import ai_provider
        u = ai_provider._openai_usage(getattr(resp, "usage", None))
        await database.record_ai_usage(model + USAGE_TAG, "openai", u.input, u.cached, u.output,
                                       ai_provider.estimate_cost(model, u.input, u.cached, u.output))
    except Exception:
        logger.debug("ai eval usage not recorded", exc_info=True)


async def answer(client, model: str, instructions: str, question: str) -> str:
    try:
        resp = await client.responses.create(
            model=model, instructions=instructions,
            input=[{"role": "user", "content": [{"type": "input_text", "text": question}]}],
            reasoning={"effort": "low"}, max_output_tokens=2000)
    except Exception as exc:
        logger.warning("ai eval answer (%s) failed: %s", model, exc)
        return f"[xato: {type(exc).__name__}]"
    await _record(model, resp)
    return (getattr(resp, "output_text", "") or "").strip() or "[bo'sh javob]"


async def judge(client, question: str, a: str, b: str) -> dict | None:
    user = f"MIJOZ SAVOLI:\n{question}\n\nJAVOB A:\n{a}\n\nJAVOB B:\n{b}"
    try:
        resp = await client.responses.create(
            model=JUDGE_MODEL, instructions=JUDGE_RULES,
            input=[{"role": "user", "content": [{"type": "input_text", "text": user}]}],
            reasoning={"effort": "medium"}, max_output_tokens=1500,
            text={"format": {"type": "json_schema", "name": "ai_sinov", "schema": JUDGE_SCHEMA, "strict": True}})
    except Exception as exc:
        logger.warning("ai eval judge failed: %s", exc)
        return None
    await _record(JUDGE_MODEL, resp)
    try:
        return json.loads(getattr(resp, "output_text", "") or "")
    except ValueError:
        return None


def unblind(verdict: dict, new_is_a: bool) -> dict:
    """Hakam bahosini A/B dan ESKI/YANGI ga qaytaradi."""
    new, old = (verdict["a"], verdict["b"]) if new_is_a else (verdict["b"], verdict["a"])
    better = verdict["better"]
    if better != "teng":
        better = "yangi" if (better == "A") == new_is_a else "eski"
    return {"new": int(new), "old": int(old), "better": better, "reason": verdict.get("reason") or ""}


async def run(questions=None, rng=None) -> dict:
    import ai_sales
    rng = rng or random.Random()
    client = await _client()
    if client is None:
        return {"error": "OpenAI kaliti yo'q"}
    dynamic = await ai_sales._dynamic_block(await ai_sales._catalog_text())
    old_instr = old_rules() + "\n\n" + dynamic
    new_instr = ai_sales._sales_rules() + "\n\n" + dynamic
    new_model = getattr(ai_sales.PROVIDER, "model", None) or OLD_MODEL
    sem = asyncio.Semaphore(PARALLEL)

    async def one(q: str) -> dict:
        async with sem:
            old_a, new_a = await asyncio.gather(answer(client, OLD_MODEL, old_instr, q),
                                                answer(client, new_model, new_instr, q))
            new_is_a = rng.random() < 0.5
            a, b = (new_a, old_a) if new_is_a else (old_a, new_a)
            verdict = await judge(client, q, a, b)
        row = {"q": q, "old_answer": old_a, "new_answer": new_a}
        row.update(unblind(verdict, new_is_a) if verdict else {"new": 0, "old": 0, "better": "?", "reason": "hakam javob bermadi"})
        return row

    rows = await asyncio.gather(*(one(q) for q in (questions or QUESTIONS)))
    scored = [r for r in rows if r["better"] != "?"]
    n = len(scored) or 1
    return {"rows": rows, "new_model": new_model,
            "avg_new": round(sum(r["new"] for r in scored) / n, 1),
            "avg_old": round(sum(r["old"] for r in scored) / n, 1),
            "wins_new": sum(r["better"] == "yangi" for r in scored),
            "wins_old": sum(r["better"] == "eski" for r in scored),
            "ties": sum(r["better"] == "teng" for r in scored)}


def verdict_line(res: dict) -> str:
    diff = res["avg_new"] - res["avg_old"]
    if diff >= 0.5:
        return "✅ Hozirgi AI yaxshiroq."
    if diff <= -0.5:
        return "⚠️ Hozirgi AI yomonroq — qoidalarni qayta ko'rish kerak."
    return "➖ Deyarli bir xil."


def report(res: dict) -> list[str]:
    head = [
        "🧪 <b>AI sinovi: 1 oy oldin va hozir</b>",
        f"Eski: {OLD_DATE} qoidalari · {OLD_MODEL}",
        f"Yangi: bugungi qoidalar · {html.escape(res['new_model'])}",
        f"Hakam: {JUDGE_MODEL} (qaysi javob qaysi versiyaniki ekanini bilmagan)", "",
        f"O'rtacha baho: yangi <b>{res['avg_new']}</b>/10 · eski <b>{res['avg_old']}</b>/10",
        f"Yutgan: yangi {res['wins_new']} · eski {res['wins_old']} · teng {res['ties']}",
        verdict_line(res), "",
    ]
    for i, r in enumerate(res["rows"], 1):
        mark = {"yangi": "🟢", "eski": "🔴", "teng": "⚪"}.get(r["better"], "❔")
        head.append(f"{mark} {i}. «{html.escape(r['q'])}» — yangi {r['new']}, eski {r['old']}. "
                    f"{html.escape(r['reason'])}")
    parts = ["\n".join(head)]
    gaps = sorted(res["rows"], key=lambda r: abs(r["new"] - r["old"]), reverse=True)[:3]
    for r in gaps:
        parts.append(f"🔍 <b>«{html.escape(r['q'])}»</b>\n\n<b>Eski ({r['old']}/10):</b>\n"
                     f"{html.escape(r['old_answer'][:1500])}\n\n<b>Yangi ({r['new']}/10):</b>\n"
                     f"{html.escape(r['new_answer'][:1500])}")
    return parts


@router.message(Command("ai_sinov"))
async def cmd_eval(message: Message, bot: Bot):
    import ai_sales
    if not ai_sales.is_owner(message.from_user.id):
        return
    await message.answer(f"🧪 {len(QUESTIONS)} ta savolni eski va yangi AI'ga beryapman, keyin hakam "
                         "baholaydi — 2–4 daqiqa…")
    try:
        res = await run()
    except Exception:
        logger.exception("ai eval failed")
        await message.answer("Sinov xato bilan to'xtadi, jurnalga yozildi.")
        return
    if res.get("error"):
        await message.answer(res["error"])
        return
    for part in report(res):
        for chunk in (part[i:i + 3900] for i in range(0, len(part), 3900)):
            await message.answer(chunk, parse_mode="HTML")
