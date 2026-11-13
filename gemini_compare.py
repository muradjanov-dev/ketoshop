"""GPT va Gemini'ni izohlarda yonma-yon solishtirish (egasi, 2026-11-13:
"gemini o'zbek tilida ham budgetniy ham yaxshiroq deyishyapti shunga
o'zgartiramizmi?" — avval haqiqiy izohlarda solishtiramiz, keyin qaror).

* /gemini_kalit KEY [model] — Gemini API kaliti (aistudio.google.com) bot
  orqali, faqat egasi va shaxsiy chatda; xabar darhol o'chiriladi. Kalit
  Google'da bepul so'rov bilan tekshiriladi (models.get), ai_settings ga
  saqlanadi, hech qachon jurnalga yozilmaydi. Model topilmasa — ochiq
  "flash" modellar ro'yxati ko'rsatiladi.
* /izoh_solishtir [N] — oxirgi N ta (5–20) Instagram/Facebook izohi: bir xil
  qoidalar, katalog, post matni va rasm bilan GPT ham, Gemini ham javob
  yozadi; adminga yonma-yon chiqadi, tokenlar va vaqt bilan. HECH NARSA
  Instagram'ga yuborilmaydi va bazadagi izohlar o'zgarmaydi.

Ishlab turgan izohlar AI'si (comment_ai) o'zgarmaydi — o'tish qarori
solishtirishdan keyin, alohida.
"""
from __future__ import annotations

import base64
import html
import json
import logging
import os
import time

import aiohttp
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

import comment_ai
import database

logger = logging.getLogger(__name__)
router = Router(name="gemini_compare")

API = "https://generativelanguage.googleapis.com/v1beta"
KEY_SETTING = "gemini_key"
MODEL_SETTING = "gemini_model"
DEFAULT_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
IMAGE_MAX = 1_500_000
DEFAULT_N, MAX_N = 10, 20


class GeminiError(Exception):
    pass


# ─────────────────────────────── sozlamalar ─────────────────────────────────

async def _settings() -> dict:
    import ai_sales
    ai_sales._settings["at"] = float("-inf")
    return await ai_sales._load_settings()


async def gemini_key() -> tuple[str, str]:
    """(kalit, model) — bot orqali berilgani, bo'lmasa env."""
    values = {}
    try:
        values = await _settings()
    except Exception:
        logger.warning("gemini: settings unreadable", exc_info=True)
    key = (values.get(KEY_SETTING) or os.getenv("GEMINI_API_KEY", "")).strip()
    model = (values.get(MODEL_SETTING) or DEFAULT_MODEL).strip()
    return key, model


async def _get(session: aiohttp.ClientSession, path: str, key: str) -> tuple[int, dict]:
    async with session.get(f"{API}/{path}", headers={"x-goog-api-key": key},
                           timeout=aiohttp.ClientTimeout(total=20)) as resp:
        try:
            data = await resp.json(content_type=None)
        except Exception:
            data = {}
        return resp.status, data or {}


async def verify(key: str, model: str) -> tuple[str | None, list[str]]:
    """(xato yoki None, model topilmasa — ochiq flash modellar)."""
    async with aiohttp.ClientSession() as session:
        status, data = await _get(session, f"models/{model}", key)
        if status == 200:
            return None, []
        error = ((data.get("error") or {}).get("message") or f"HTTP {status}")[:200]
        if status == 404:
            status2, listing = await _get(session, "models?pageSize=200", key)
            if status2 == 200:
                names = [m.get("name", "").removeprefix("models/") for m in listing.get("models", [])
                         if "generateContent" in (m.get("supportedGenerationMethods") or [])]
                return error, [n for n in names if "flash" in n][:12]
        return error, []


# ───────────────────────────── Gemini chaqiruvi ─────────────────────────────

def gemini_schema(schema: dict) -> dict:
    """JSON sxema → Gemini responseSchema (OpenAPI to'plami): turlar katta
    harfda, additionalProperties yo'q."""
    out = {}
    for k, v in schema.items():
        if k == "additionalProperties":
            continue
        if k == "type":
            out[k] = str(v).upper()
        elif k == "properties":
            out[k] = {name: gemini_schema(sub) for name, sub in v.items()}
        elif isinstance(v, dict):
            out[k] = gemini_schema(v)
        else:
            out[k] = v
    return out


async def _image_part(session: aiohttp.ClientSession, url: str | None) -> dict | None:
    if not url:
        return None
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return None
            body = await resp.content.read(IMAGE_MAX + 1)
            if len(body) > IMAGE_MAX:
                return None
            mime = (resp.headers.get("Content-Type") or "image/jpeg").split(";")[0]
    except Exception:
        return None
    return {"inlineData": {"mimeType": mime, "data": base64.b64encode(body).decode()}}


async def ask_gemini(key: str, model: str, instructions: str, user: str, image: str | None) -> dict:
    """{'data': {...}, 'input': n, 'output': n, 'seconds': s} yoki GeminiError."""
    started = time.monotonic()
    async with aiohttp.ClientSession() as session:
        parts = [{"text": user}]
        img = await _image_part(session, image)
        if img:
            parts.append(img)
        body = {
            "systemInstruction": {"parts": [{"text": instructions}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseMimeType": "application/json",
                                 "responseSchema": gemini_schema(comment_ai.SCHEMA),
                                 "maxOutputTokens": 2048},
        }
        async with session.post(f"{API}/models/{model}:generateContent", json=body,
                                headers={"x-goog-api-key": key},
                                timeout=aiohttp.ClientTimeout(total=90)) as resp:
            data = await resp.json(content_type=None)
            if resp.status != 200:
                raise GeminiError(((data or {}).get("error") or {}).get("message", f"HTTP {resp.status}")[:200])
    cands = (data or {}).get("candidates") or []
    text = "".join(p.get("text", "") for p in ((cands[0].get("content") or {}).get("parts") or [])) if cands else ""
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        raise GeminiError(f"JSON emas: {text[:120]}")
    usage = data.get("usageMetadata") or {}
    return {"data": parsed, "input": int(usage.get("promptTokenCount") or 0),
            "output": int(usage.get("candidatesTokenCount") or 0) + int(usage.get("thoughtsTokenCount") or 0),
            "seconds": time.monotonic() - started}


async def ask_gpt(instructions: str, user: str, image: str | None) -> dict:
    key = await comment_ai._openai_key()
    if not key:
        raise GeminiError("GPT kaliti yo'q (/ai_kalit)")
    started = time.monotonic()
    data = await comment_ai._ask_openai(key, comment_ai.openai_model(), instructions, user,
                                        effort="low", image=image)
    if data is None:
        raise GeminiError("GPT javob bermadi")
    return {"data": data, "seconds": time.monotonic() - started}


# ─────────────────────────────── solishtirish ───────────────────────────────

async def compare(n: int) -> tuple[list[dict], dict]:
    """Oxirgi n ta izoh — har biriga GPT va Gemini javobi (yuborilmaydi)."""
    key, model = await gemini_key()
    if not key:
        raise GeminiError("Gemini kaliti yo'q — /gemini_kalit KEY")
    import meta_comments
    state = await database.get_meta_comments_state()
    kb = comment_ai.kb_with_defaults(state.get("kb"))
    instructions = comment_ai.RULES + "\n\n" + comment_ai.kb_block(kb, await comment_ai.catalog_text())
    rows = [r for r in await database.meta_comments_report("all", 200)
            if (r.get("text") or "").strip() and r.get("category") != "spam"][:n]
    out, totals = [], {"gpt_s": 0.0, "gem_s": 0.0, "gem_in": 0, "gem_out": 0, "gpt_err": 0, "gem_err": 0}
    for row in rows:
        caption, image = await meta_comments.post_context(row)
        user = comment_ai.comment_prompt(dict(row, post_caption=caption))
        item = {"row": row}
        try:
            g = await ask_gpt(instructions, user, image or None)
            item["gpt"] = comment_ai.finalize(row.get("text"), g["data"].get("reply"))
            item["gpt_meta"] = (g["data"].get("category"), g["data"].get("confident"))
            totals["gpt_s"] += g["seconds"]
        except Exception as exc:
            item["gpt"], totals["gpt_err"] = f"⚠️ {exc}", totals["gpt_err"] + 1
        try:
            m = await ask_gemini(key, model, instructions, user, image or None)
            item["gem"] = comment_ai.finalize(row.get("text"), m["data"].get("reply"))
            item["gem_meta"] = (m["data"].get("category"), m["data"].get("confident"))
            totals["gem_s"] += m["seconds"]
            totals["gem_in"] += m["input"]
            totals["gem_out"] += m["output"]
        except Exception as exc:
            item["gem"], totals["gem_err"] = f"⚠️ {exc}", totals["gem_err"] + 1
        out.append(item)
    totals["model"] = model
    return out, totals


def render(items: list[dict], totals: dict) -> list[str]:
    def esc(v):
        return html.escape(str(v or ""), quote=False)

    def meta(m):
        return f" <i>({esc(m[0])}{'' if m[1] else ', ishonmadi'})</i>" if m else ""

    blocks = []
    for i, it in enumerate(items, 1):
        r = it["row"]
        blocks.append(f"<b>{i}. «{esc((r.get('text') or '')[:120])}»</b>\n"
                      f"🟢 GPT{meta(it.get('gpt_meta'))}: {esc(it.get('gpt'))}\n"
                      f"🔵 Gemini{meta(it.get('gem_meta'))}: {esc(it.get('gem'))}")
    n = max(1, len(items))
    blocks.append(f"⏱ O'rtacha vaqt: GPT {totals['gpt_s'] / n:.1f} s · Gemini {totals['gem_s'] / n:.1f} s\n"
                  f"🔢 Gemini ({esc(totals['model'])}) tokenlari: {totals['gem_in']:,} kiruvchi, "
                  f"{totals['gem_out']:,} chiquvchi".replace(",", " ")
                  + (f"\n⚠️ Xatolar: GPT {totals['gpt_err']}, Gemini {totals['gem_err']}"
                     if totals["gpt_err"] or totals["gem_err"] else "")
                  + "\n\nHech narsa Instagram'ga yuborilmadi. GPT sarfi kunlik hisobotda ko'rinadi.")
    pages, page = [], "⚖️ <b>GPT va Gemini — bir xil izohlarga</b>"
    for b in blocks:
        if len(page) + len(b) + 2 > 3800:
            pages.append(page)
            page = b
        else:
            page += "\n\n" + b
    pages.append(page)
    return pages


# ──────────────────────────────── buyruqlar ─────────────────────────────────

@router.message(Command("gemini_kalit"))
async def cmd_key(message: Message):
    import ai_sales
    if message.from_user.id not in ai_sales.ADMIN_IDS:
        return
    parts = (message.text or "").split()
    if len(parts) < 2:
        key, model = await gemini_key()
        await message.answer(f"🔑 <b>Gemini kaliti:</b> {'bor (…' + html.escape(key[-4:]) + ')' if key else 'yo‘q'}\n"
                             f"Model: <code>{html.escape(model)}</code>\n\n"
                             "Berish: <code>/gemini_kalit KALIT</code> yoki <code>/gemini_kalit KALIT model</code>\n"
                             "Kalit: aistudio.google.com → Get API key.\n"
                             "Solishtirish: <code>/izoh_solishtir 10</code>", parse_mode="HTML")
        return
    try:
        await message.delete()
        deleted = True
    except Exception:
        deleted = False
    if message.chat.type != "private":
        await message.answer("⚠️ Kalitni faqat bot bilan shaxsiy chatda yuboring.")
        return
    if not ai_sales.is_owner(message.from_user.id):
        await message.answer(ai_sales.OWNER_DENIED)
        return
    key = parts[1].strip()
    model = parts[2].strip() if len(parts) > 2 else (await gemini_key())[1]
    error, models = await verify(key, model)
    if error:
        hint = ("\n\nOchiq modellar: " + ", ".join(f"<code>{html.escape(m)}</code>" for m in models)
                + "\n<code>/gemini_kalit KALIT model</code> bilan qayta yuboring." if models else "")
        await message.answer(f"❌ Saqlanmadi: <code>{html.escape(error)}</code>{hint}", parse_mode="HTML")
        return
    await ai_sales.set_setting(KEY_SETTING, key, message.from_user.id)
    await ai_sales.set_setting(MODEL_SETTING, model, message.from_user.id)
    text = (f"✅ Gemini kaliti saqlandi (…{html.escape(key[-4:])}), model <code>{html.escape(model)}</code>.\n"
            "Endi: <code>/izoh_solishtir 10</code> — oxirgi 10 ta izohga GPT va Gemini javoblari "
            "yonma-yon (hech narsa yuborilmaydi).")
    if not deleted:
        text += "\n\n⚠️ Kalitli xabaringizni o'chira olmadim — uni qo'lda o'chiring."
    await message.answer(text, parse_mode="HTML")


@router.message(Command("izoh_solishtir"))
async def cmd_compare(message: Message):
    import ai_sales
    if message.from_user.id not in ai_sales.ADMIN_IDS:
        return
    parts = (message.text or "").split()
    try:
        n = max(5, min(MAX_N, int(parts[1]))) if len(parts) > 1 else DEFAULT_N
    except ValueError:
        n = DEFAULT_N
    await message.answer(f"⏳ Oxirgi {n} ta izohga GPT va Gemini javob yozyapti (1–2 daqiqa)…")
    try:
        items, totals = await compare(n)
    except GeminiError as exc:
        await message.answer(f"❌ {html.escape(str(exc))}", parse_mode="HTML")
        return
    for page in render(items, totals):
        await message.answer(page, parse_mode="HTML", disable_web_page_preview=True)
