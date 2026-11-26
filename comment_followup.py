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
# Egasi, 2026-11-16: "30 kun avval yozilgan izohlarga nega yozmading, hammasiga yoz" —
# 25/kun, 20 daqiqada bitta edi (≈7 kun); endi 5 daqiqada bitta, kuniga 120 gacha (≈1,5 kun).
# Egasi, 2026-11-16: "har 10 daqiqada yozilmagan hammasiga yoz", keyin "instagram bloklash xavfiga
# yaqinlashmasin" — har EVERY soniyada navbatdagilarning hammasiga, lekin odamdek: orasida tasodifiy
# GAP..GAP_MAX soniya (soatiga ~30 ta), kuniga DAILY tadan oshmaydi, tunda emas.
# Egasi, 2026-11-26: "instagramga suspicious action deb keldi, juda ko'p bir vaqtda yozma, akauntni
# 100% xavfsiz holatda ulanib yozgin" — kuniga 20 ta, orasida 10–20 daqiqa, 10:00–21:00; ustiga
# ig_guard (hamma yozishlar uchun umumiy tezlik va ogohlantirishda 48 soat pauza).
# Egasi, 2026-11-26: "to'xtab qolma ... har 1 daqiqada"; "yangilarni hammasiga yozib bo'lgan
# bo'lsang — 1 oy+ avval yozganlarga qayta yoz, tavsiya va «Bilasizmi?» bilan". Yangi izohlarga
# javob (meta_comments) bir xil ig_guard navbatida birinchi turadi; qayta yozish — qolgan vaqtda.
DAILY = max(0, int(os.getenv("COMMENT_FOLLOWUP_DAILY", "200")))
EVERY = max(300, int(os.getenv("COMMENT_FOLLOWUP_EVERY", "600")))
GAP = max(30, int(os.getenv("COMMENT_FOLLOWUP_GAP", "60")))
GAP_MAX = max(GAP, int(os.getenv("COMMENT_FOLLOWUP_GAP_MAX", "100")))
HOURS = (9, 22)                  # Toshkent: 09:00–21:59
# Ikkinchi qayta yozish (egasi, 2026-11-24: "javob berilmagan izohlarga javob berib va qayta
# yozib chiq … telegramdan ketoshop_uz deb yozsalar chiqadi, yoki direct'dan yozishsa biz
# tashlab beramiz"): javob olgan har bir odamga yana bir marta, do'konga shu yo'l bilan.
# Izohi yoki birinchi qayta xabari ROUND2_MIN_DAYS kundan yangi bo'lsa — hali emas.
ROUND2_MIN_DAYS = max(1, int(os.getenv("COMMENT_FOLLOWUP2_MIN_DAYS", "3")))
# Uchinchi (egasi, 2026-11-26): «Bilasizmi?» + aksiyalar + kanal — ikkinchisini olganlarga
# ROUND3_MIN_DAYS kundan keyin, umuman javob olmaganlarga ham (database.*followup3*).
ROUND3_MIN_DAYS = max(1, int(os.getenv("COMMENT_FOLLOWUP3_MIN_DAYS", "5")))
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


def _age_days(row: dict) -> int:
    when = row.get("created_at") or row.get("received_at")
    if not isinstance(when, datetime):
        return ROUND2_MIN_DAYS
    return max(0, (datetime.utcnow() - when.replace(tzinfo=None)).days)


async def compose(row: dict, kb: dict | None = None, extra: tuple[str, str] | None = None,
                  second: bool = False) -> str | None:
    """Shu odamga qayta aloqa matni yoki None (yozmaymiz). second — ikkinchi
    bosqich: izoh yoshi haqiqiy, birinchi qayta xabarimiz (bo'lsa) AI'ga
    beriladi — takrorlamasin."""
    if kb is None:
        kb = comment_ai.kb_with_defaults((await database.get_meta_comments_state()).get("kb"))
    new, offers = extra if extra is not None else (await new_products_text(), await offers_text())
    caption, image = await mc.post_context(row)
    row = dict(row, post_caption=caption, post_image=image)
    return await comment_ai.followup(row, kb, _age_days(row) if second else _days_ago(row), new, offers)


async def _candidates() -> tuple[list[dict], bool]:
    """Avval birinchi bosqich navbati; u bo'sh bo'lsa — ikkinchi bosqich."""
    rows = await database.meta_comment_followup_candidates(DAYS, TRIES_PER_TICK)
    if rows:
        return rows, False
    rows = await database.meta_comment_followup2_candidates(ROUND2_MIN_DAYS, TRIES_PER_TICK)
    if rows:
        return rows, True
    rows = await database.meta_comment_followup3_candidates(ROUND3_MIN_DAYS, TRIES_PER_TICK)
    # Uchinchi bosqich: oldingi qayta xabar AI'ga beriladi — takrorlamasin.
    return [dict(r, followup_text=r.get("followup2_text") or r.get("followup_text"), round=3)
            for r in rows], True


async def _sent_today() -> int:
    return ((await database.meta_comment_followup_stats(DAYS))["today"]
            + (await database.meta_comment_followup2_stats(ROUND2_MIN_DAYS))["today"]
            + (await database.meta_comment_followup3_stats())["today"])


async def send_one(bot: Bot | None, now: datetime | None = None) -> str:
    """Bitta qadam: 'sent' | 'off' | 'quiet' | 'cap' | 'no_token' | 'none' | 'skipped'."""
    state = await database.get_meta_comments_state()
    if not state.get("followup_on", True) or DAILY == 0:
        return "off"
    if not in_hours(now):
        return "quiet"
    if await _sent_today() >= DAILY:
        return "cap"
    await mc.load_token()
    if not mc.token():
        return "no_token"
    candidates, second = await _candidates()
    if not candidates:
        return "none"
    mark = database.mark_meta_comment_followup2 if second else database.mark_meta_comment_followup
    if candidates and candidates[0].get("round") == 3:
        mark = database.mark_meta_comment_followup3
    kb = comment_ai.kb_with_defaults(state.get("kb"))
    extra = (await new_products_text(), await offers_text())
    for row in candidates:
        try:
            text = await compose(row, kb, extra, second)
        except Exception:
            logger.exception("follow-up: compose failed for %s", row.get("comment_id"))
            text = None
        if not text:
            # AI yozmaslikni tanladi (yoki xato) — bu odamni qayta tanlamaymiz.
            await mark(row["id"], "")
            continue
        try:
            async with aiohttp.ClientSession() as session:
                ident = await mc.identity(session)
                await mc.reply_public(session, ident, row, text)
        except mc.GraphError as e:
            if throttled(e):
                # Instagram cheklovi / «action blocked» — odamni belgilamaymiz, keyinroq.
                logger.warning("follow-up paused — Instagram limit: %s", e)
                return "throttled"
            # Izoh o'chirilgan yoki yopilgan — keyingi safar ham bo'lmaydi.
            logger.info("follow-up to %s failed: %s", row.get("comment_id"), e)
            await mark(row["id"], "")
            continue
        await mark(row["id"], text)
        logger.info("follow-up sent to %s (%s)", row.get("username"), row.get("comment_id"))
        return "sent"
    return "skipped"


THROTTLE_CODES = {4, 17, 32, 368, 613}


def throttled(e) -> bool:
    """Instagram/Meta «sekinroq» deyapti — rate limit yoki vaqtincha blok."""
    msg = str(getattr(e, "message", e)).lower()
    return getattr(e, "code", None) in THROTTLE_CODES or any(
        w in msg for w in ("rate limit", "too many", "action blocked", "temporarily blocked", "spam"))


async def send_all(bot: Bot | None, now: datetime | None = None) -> dict:
    """Navbatdagilarning hammasiga, orasida GAP soniya. Navbat tugasa, chegara
    to'lsa, o'chirilsa yoki Instagram cheklasa — to'xtaydi."""
    stats = {"sent": 0, "skipped": 0, "stop": ""}
    while True:
        result = await send_one(bot, now)
        if result == "sent":
            stats["sent"] += 1
        elif result == "skipped":
            stats["skipped"] += 1
        else:
            stats["stop"] = result
            break
        import random
        await asyncio.sleep(random.uniform(GAP, GAP_MAX))
    if stats["sent"] or stats["stop"] == "throttled":
        logger.info("comment follow-up round: %s", stats)
    return stats


MAX_BACKOFF = 2 * 3600


def next_wait(throttles: int) -> int:
    """Navbatdagi tekshiruvgacha: odatda EVERY; Instagram ketma-ket cheklasa —
    2, 4, 8 … baravar uzoqroq (ko'pi bilan MAX_BACKOFF), blok cho'zilmasin.
    Ochilishi bilan (birinchi yuborilgan xabar) yana EVERY (egasi, 2026-11-16:
    "to'xtab qolsa avtomatik davom etishi kerak ochilgandan keyin")."""
    return EVERY if throttles <= 0 else min(MAX_BACKOFF, EVERY * 2 ** throttles)


RESUME_KEY = "ig_resume_safe_2026_11_26"


async def resume_safely_once() -> bool:
    """Egasi, 2026-11-26: "... shuni ishga tushir, izohlarga javob yozishni boshla" — yangi
    ehtiyotkor tezlik (ig_guard) bilan bir marta: qayta yozish va Direct yoqiladi, pauza olinadi."""
    if not await database.claim_release_notes(RESUME_KEY):
        return False
    import ig_direct
    import ig_guard
    await database.set_meta_comments_followup(True)
    await ig_direct.set_enabled(True)
    await ig_guard.resume()
    logger.info("Instagram writes resumed at the safe pace (%s)", RESUME_KEY)
    return True


async def loop(bot: Bot) -> None:
    await asyncio.sleep(120)
    try:
        await resume_safely_once()
    except Exception:
        logger.exception("Instagram resume failed")
    logger.info("Comment follow-up loop started (every %ds, everyone waiting, %ds apart)", EVERY, GAP)
    throttles = 0
    while True:
        try:
            stats = await send_all(bot)
            throttles = throttles + 1 if stats.get("stop") == "throttled" and not stats.get("sent") else 0
        except Exception:
            logger.exception("comment follow-up tick failed")
        await asyncio.sleep(next_wait(throttles))


# ─────────────────────────────── /izoh_qayta ───────────────────────────────

async def status_text() -> str:
    state = await database.get_meta_comments_state()
    st = await database.meta_comment_followup_stats(DAYS)
    st2 = await database.meta_comment_followup2_stats(ROUND2_MIN_DAYS)
    on = state.get("followup_on", True)
    lines = [
        "🔁 <b>Qayta aloqa</b> — bir oy oldin izoh qoldirganlarga samimiy qayta yozish",
        "",
        f"Holat: <b>{'yoqilgan ✅' if on else 'o‘chiq ⏸'}</b>",
        f"Bugun (1-bosqich): <b>{st['today']}</b> / {DAILY} ta · jami: {st['total']} ta · AI yozmagan: {st['skipped']} ta",
        f"Navbatda: {st['queue']} kishi ({DAYS} kundan eski izohlar, har biriga bir marta)",
        f"2-bosqich (do'konga yangi yo'l, javob olgan har kimga bir marta): bugun {st2['today']} · "
        f"jami {st2['total']} · navbatda {st2['queue']} kishi",
        f"3-bosqich («Bilasizmi?», aksiyalar, kanal; javob olmaganlarga ham): bugun "
        f"{(await database.meta_comment_followup3_stats())['today']} · "
        f"jami {(await database.meta_comment_followup3_stats())['total']}",
        f"Har {EVERY // 60} daqiqada navbatdagilarning hammasiga, orasida {GAP}–{GAP_MAX} soniya, "
        f"Toshkent {HOURS[0]:02d}:00–{HOURS[1]:02d}:00; Instagram cheklasa — to'xtab, o'zi davom etadi",
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
    second = not rows
    if second:
        rows = await database.meta_comment_followup2_candidates(ROUND2_MIN_DAYS, limit)
    if not rows:
        rows = [dict(r, followup_text=r.get("followup2_text") or r.get("followup_text"), round=3)
                for r in await database.meta_comment_followup3_candidates(ROUND3_MIN_DAYS, limit)]
    state = await database.get_meta_comments_state()
    kb = comment_ai.kb_with_defaults(state.get("kb"))
    extra = (await new_products_text(), await offers_text())
    return [(row, await compose(row, kb, extra, second)) for row in rows]


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
