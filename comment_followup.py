"""Qayta aloqa: bir oy oldin Instagram/Facebook'da izoh qoldirganlarga o'sha
izohi ostida samimiy qayta yozish (egasi, 2026-11-13: "1 oy avval javob
berilganlarga ham qayta yozib xabar ol ... manipulyatsiyasiz ... biror
mahsulotni so'raganlarga Keto shopda bor ekanini va retsept uchun botga
o'tishlari kerakligini ayt").

* Kim: DAYS kundan oldin izoh qoldirib, o'shanda javob olgan odamlar — har
  biriga bir marta (database.meta_comment_followup_candidates). Oxirgi DAYS
  kunda o'zi yozgan bo'lsa (yangi javob olgan) — tegmaymiz. Spam — yo'q.
* Nima: AI (comment_ai.followup) eski izoh, o'sha postning matni va rasmi,
  katalog, yangi mahsulotlar va aksiyadan shaxsiy 1–3 gap yozadi; noo'rin
  bo'lsa (boshqalar suhbati, qattiq norozilik) — yozmaydi.
* Qayerga: o'sha izohning o'zi ostiga, ochiq javob (Instagram odamga xabar
  beradi). Direct emas — Meta faqat 7 kun ichida ruxsat beradi.
* Qancha: Toshkent vaqti bilan HOURS oralig'ida har EVERY soniyada bittadan,
  kuniga DAILY tadan oshmaydi — Instagram buni spam deb bilmasin.
* Boshqaruv: /izoh_qayta (holat), /izoh_qayta on|off, /izoh_qayta namuna
  (3 ta namuna — hech narsa yuborilmaydi).
"""
from __future__ import annotations

import asyncio
import html
import logging
import os
from datetime import datetime, timedelta

import aiohttp
from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

import comment_ai
import database
import meta_comments as mc

logger = logging.getLogger(__name__)
router = Router(name="comment_followup")

DAYS = max(7, int(os.getenv("COMMENT_FOLLOWUP_DAYS", "30")))
DAILY = max(0, int(os.getenv("COMMENT_FOLLOWUP_DAILY", "25")))
EVERY = max(300, int(os.getenv("COMMENT_FOLLOWUP_EVERY", "1200")))
HOURS = (10, 20)                 # Toshkent: 10:00–19:59
NEW_PRODUCT_DAYS = 45
TRIES_PER_TICK = 3               # AI "yozmaymiz" desa — keyingi odam


def _tashkent_now() -> datetime:
    return datetime.utcnow() + timedelta(hours=5)


def in_hours(now: datetime | None = None) -> bool:
    now = now or _tashkent_now()
    return HOURS[0] <= now.hour < HOURS[1]


async def new_products_text() -> str:
    """Oxirgi NEW_PRODUCT_DAYS kunda qo'shilgan, sotuvdagi chakana mahsulotlar."""
    import manual_order
    since = datetime.utcnow() - timedelta(days=NEW_PRODUCT_DAYS)
    rows = []
    for p in await database.admin_list_products(include_inactive=False):
        created = p.get("created_at")
        if p.get("b2b_only") or float(p.get("quantity") or 0) <= 0:
            continue
        if not isinstance(created, datetime) or created.replace(tzinfo=None) < since:
            continue
        price = int(round(manual_order.shelf_price(p)))
        rows.append((created, f"- {p.get('name')} — {price:,} so'm".replace(",", " ")))
    rows.sort(key=lambda r: r[0], reverse=True)
    return "\n".join(line for _, line in rows[:15])


async def offers_text() -> str:
    """Hozirgi aksiya (bo'lsa) — AI boshqa chegirma o'ylab topmasin."""
    import promotions
    try:
        promo = await promotions.get_active()
    except Exception:
        logger.warning("follow-up: promotion unavailable", exc_info=True)
        return ""
    if not promo:
        return ""
    lines = [promotions.promo_name(promo, "uz")]
    if promo.get("conditions"):
        lines.append(promotions.promo_conditions(promo, "uz"))
    for rule in promo.get("bonuses") or []:
        try:
            lines.append(promotions.rule_line(rule, "uz"))
        except Exception:
            continue
    return "\n".join(f"- {line}" for line in lines if line)


def _days_ago(row: dict) -> int:
    when = row.get("created_at") or row.get("received_at")
    if not isinstance(when, datetime):
        return DAYS
    return max(DAYS, (datetime.utcnow() - when.replace(tzinfo=None)).days)


async def compose(row: dict, kb: dict | None = None, extra: tuple[str, str] | None = None) -> str | None:
    """Shu odamga qayta aloqa matni yoki None (yozmaymiz)."""
    if kb is None:
        kb = comment_ai.kb_with_defaults((await database.get_meta_comments_state()).get("kb"))
    new, offers = extra if extra is not None else (await new_products_text(), await offers_text())
    caption, image = await mc.post_context(row)
    row = dict(row, post_caption=caption, post_image=image)
    return await comment_ai.followup(row, kb, _days_ago(row), new, offers)


async def send_one(bot: Bot | None, now: datetime | None = None) -> str:
    """Bitta qadam: 'sent' | 'off' | 'quiet' | 'cap' | 'no_token' | 'none' | 'skipped'."""
    state = await database.get_meta_comments_state()
    if not state.get("followup_on", True) or DAILY == 0:
        return "off"
    if not in_hours(now):
        return "quiet"
    if (await database.meta_comment_followup_stats(DAYS))["today"] >= DAILY:
        return "cap"
    await mc.load_token()
    if not mc.token():
        return "no_token"
    candidates = await database.meta_comment_followup_candidates(DAYS, TRIES_PER_TICK)
    if not candidates:
        return "none"
    kb = comment_ai.kb_with_defaults(state.get("kb"))
    extra = (await new_products_text(), await offers_text())
    for row in candidates:
        try:
            text = await compose(row, kb, extra)
        except Exception:
            logger.exception("follow-up: compose failed for %s", row.get("comment_id"))
            text = None
        if not text:
            # AI yozmaslikni tanladi (yoki xato) — bu odamni qayta tanlamaymiz.
            await database.mark_meta_comment_followup(row["id"], "")
            continue
        try:
            async with aiohttp.ClientSession() as session:
                ident = await mc.identity(session)
                await mc.reply_public(session, ident, row, text)
        except mc.GraphError as e:
            # Izoh o'chirilgan yoki yopilgan — keyingi safar ham bo'lmaydi.
            logger.info("follow-up to %s failed: %s", row.get("comment_id"), e)
            await database.mark_meta_comment_followup(row["id"], "")
            continue
        await database.mark_meta_comment_followup(row["id"], text)
        logger.info("follow-up sent to %s (%s)", row.get("username"), row.get("comment_id"))
        return "sent"
    return "skipped"


async def loop(bot: Bot) -> None:
    await asyncio.sleep(120)
    logger.info("Comment follow-up loop started (every %ds, %d/day)", EVERY, DAILY)
    while True:
        try:
            await send_one(bot)
        except Exception:
            logger.exception("comment follow-up tick failed")
        await asyncio.sleep(EVERY)


# ─────────────────────────────── /izoh_qayta ───────────────────────────────

async def status_text() -> str:
    state = await database.get_meta_comments_state()
    st = await database.meta_comment_followup_stats(DAYS)
    on = state.get("followup_on", True)
    lines = [
        "🔁 <b>Qayta aloqa</b> — bir oy oldin izoh qoldirganlarga samimiy qayta yozish",
        "",
        f"Holat: <b>{'yoqilgan ✅' if on else 'o‘chiq ⏸'}</b>",
        f"Bugun: <b>{st['today']}</b> / {DAILY} ta · jami: {st['total']} ta · AI yozmagan: {st['skipped']} ta",
        f"Navbatda: {st['queue']} kishi ({DAYS} kundan eski izohlar, har biriga bir marta)",
        f"Vaqti: Toshkent {HOURS[0]:02d}:00–{HOURS[1]:02d}:00, har {EVERY // 60} daqiqada bittadan",
    ]
    if st["last"]:
        lines += ["", "<b>Oxirgilari:</b>"]
        for r in st["last"]:
            link = f" <a href=\"{html.escape(r['post_link'])}\">🔗</a>" if r.get("post_link") else ""
            lines.append(f"• {html.escape(r.get('username') or '—')}: «{html.escape((r.get('text') or '')[:50])}» → "
                         f"«{html.escape((r.get('followup_text') or '')[:160])}»{link}")
    lines += ["", "<code>/izoh_qayta off</code> — to'xtatish · <code>/izoh_qayta on</code> — yoqish",
              "<code>/izoh_qayta namuna</code> — 3 ta namuna (hech narsa yuborilmaydi)"]
    return "\n".join(lines)


async def samples(limit: int = 3) -> list[tuple[dict, str | None]]:
    """Navbatdagi odamlarga nima yozilishi — yuborilmaydi va belgilanmaydi."""
    rows = await database.meta_comment_followup_candidates(DAYS, limit)
    state = await database.get_meta_comments_state()
    kb = comment_ai.kb_with_defaults(state.get("kb"))
    extra = (await new_products_text(), await offers_text())
    return [(row, await compose(row, kb, extra)) for row in rows]


@router.message(Command("izoh_qayta"))
async def cmd_followup(message: Message):
    if not mc.is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    arg = parts[1].lower() if len(parts) > 1 else ""
    if arg in ("on", "off"):
        await database.set_meta_comments_followup(arg == "on")
    if arg == "namuna":
        await message.answer("⏳ Namunalar tayyorlanyapti (hech narsa yuborilmaydi)…")
        out = []
        for row, text in await samples():
            out.append(f"• {html.escape(row.get('username') or '—')}: «{html.escape((row.get('text') or '')[:80])}»\n"
                       f"   → {html.escape(text) if text else '<i>AI yozmaslikni tanladi</i>'}")
        await message.answer("🔁 <b>Namunalar</b>\n\n" + ("\n\n".join(out) or "Navbat bo'sh."),
                             parse_mode="HTML", disable_web_page_preview=True)
        return
    await message.answer(await status_text(), parse_mode="HTML", disable_web_page_preview=True)
