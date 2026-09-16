"""
Admin commands to control the scheduled tips broadcast.

  /tips_status      — show state (enabled, next tip, remaining, last sent)
  /tips_on          — enable the scheduler
  /tips_off         — pause the scheduler
  /tips_now         — send the next tip to EVERYONE right now
  /tips_test        — preview the next tip (sent only to you)
  /tips_set <N>     — set the next tip to #N (1-based)
"""
import logging

from aiogram import Router, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message
from aiogram.enums import ParseMode

import database
from broadcast import send_next_tip, _format_tip, _SHOP_BUTTON
from broadcast_tips import TIPS
from config import ADMIN_IDS

logger = logging.getLogger(__name__)
router = Router()

# All commands here are admin-only.
router.message.filter(F.from_user.id.in_(ADMIN_IDS))


@router.message(Command("tips_status"))
async def tips_status(message: Message):
    state = await database.get_broadcast_state()
    idx = state["next_index"]
    remaining = len(TIPS) - idx
    last = state["last_sent_at"]
    last_str = last.strftime("%Y-%m-%d %H:%M UTC") if last else "— (hali yo'q)"
    next_no = (idx + 1) if idx < len(TIPS) else "—"
    holat = "🟢 yoqilgan" if state["enabled"] else "🔴 to'xtatilgan"
    await message.answer(
        f"📊 <b>Eslatmalar holati</b>\n\n"
        f"Holat: {holat}\n"
        f"Keyingi eslatma: <b>#{next_no}</b> / {len(TIPS)}\n"
        f"Qolgan: {remaining} ta (~{remaining * 2} kun)\n"
        f"Oxirgi yuborilgan: {last_str}",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("tips_on"))
async def tips_on(message: Message):
    await database.set_broadcast_enabled(True)
    await message.answer("🟢 Eslatmalar yuborish <b>yoqildi</b>.", parse_mode=ParseMode.HTML)


@router.message(Command("tips_off"))
async def tips_off(message: Message):
    await database.set_broadcast_enabled(False)
    await message.answer("🔴 Eslatmalar yuborish <b>to'xtatildi</b>.", parse_mode=ParseMode.HTML)


@router.message(Command("tips_test"))
async def tips_test(message: Message):
    state = await database.get_broadcast_state()
    idx = state["next_index"]
    if idx >= len(TIPS):
        await message.answer("Yuboriladigan eslatma qolmadi.")
        return
    await message.answer(
        f"👁 <b>Keyingi eslatma (#{idx + 1}) — faqat sizga ko'rsatildi:</b>",
        parse_mode=ParseMode.HTML,
    )
    # Every buyer gets it in their own language — show all three versions.
    from broadcast import localized_tip, shop_button
    for lang, label in (("uz", "O'zbekcha"), ("uz_cyr", "Кириллча"), ("ru", "Ruscha")):
        body = await localized_tip(TIPS[idx], lang)
        if body is None:
            await message.answer(f"⚠️ {label}: tarjima hozir olinmadi — bu tilda yuborilmaydi.")
            continue
        await message.answer(
            f"<i>{label}:</i>\n\n" + body, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
            reply_markup=shop_button(lang),
        )


@router.message(Command("tips_now"))
async def tips_now(message: Message):
    state = await database.get_broadcast_state()
    idx = state["next_index"]
    if idx >= len(TIPS):
        await message.answer("Yuboriladigan eslatma qolmadi. Yangi eslatma qo'shing.")
        return
    await message.answer(f"📤 Eslatma #{idx + 1} barchaga yuborilmoqda…")
    result = await send_next_tip(message.bot)
    if result is None:
        await message.answer("Yuboriladigan eslatma qolmadi.")


@router.message(Command("tips_set"))
async def tips_set(message: Message, command: CommandObject):
    arg = (command.args or "").strip()
    if not arg.isdigit():
        await message.answer("Foydalanish: <code>/tips_set 1</code> (1 dan boshlanadi)", parse_mode=ParseMode.HTML)
        return
    n = int(arg)
    if not (1 <= n <= len(TIPS)):
        await message.answer(f"1 dan {len(TIPS)} gacha son kiriting.")
        return
    await database.set_broadcast_index(n - 1)
    await message.answer(f"✅ Keyingi eslatma <b>#{n}</b> ga o'rnatildi.", parse_mode=ParseMode.HTML)


# ─────────────────────────────────────────────────────────────────────────────
# Personalized recommendations (order-history based, every 2 days)
#
#   /reco_status  — show state (enabled, last sent, eligible buyers)
#   /reco_on      — enable the personalized scheduler
#   /reco_off     — pause it
#   /reco_test    — preview YOUR own personalized message (only to you)
#   /reco_now     — send everyone their personalized message right now
# ─────────────────────────────────────────────────────────────────────────────
from personal_recommend import send_personal_batch, build_personal_message, reco_keyboard


@router.message(Command("reco_status"))
async def reco_status(message: Message):
    state = await database.get_reco_state()
    buyers = await database.get_user_ids_with_orders()
    last = state["last_sent_at"]
    last_str = last.strftime("%Y-%m-%d %H:%M UTC") if last else "— (hali yo'q)"
    holat = "🟢 yoqilgan" if state["enabled"] else "🔴 to'xtatilgan"
    await message.answer(
        f"🎁 <b>Shaxsiy tavsiyalar holati</b>\n\n"
        f"Holat: {holat}\n"
        f"Mos oluvchilar (buyurtma qilganlar): <b>{len(buyers)}</b> ta\n"
        f"Sikl (rotatsiya): {state['cycle']}\n"
        f"Oxirgi yuborilgan: {last_str}\n"
        f"Jadval: har 2 kunda, 10:00 (Toshkent) — maslahatlar kuni bilan to'g'ri kelsa, ertasiga suriladi",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("reco_on"))
async def reco_on(message: Message):
    await database.set_reco_enabled(True)
    await message.answer("🟢 Shaxsiy tavsiyalar <b>yoqildi</b> (har 2 kunda).", parse_mode=ParseMode.HTML)


@router.message(Command("reco_off"))
async def reco_off(message: Message):
    await database.set_reco_enabled(False)
    await message.answer("🔴 Shaxsiy tavsiyalar <b>to'xtatildi</b>.", parse_mode=ParseMode.HTML)


@router.message(Command("reco_test"))
async def reco_test(message: Message):
    state = await database.get_reco_state()
    orders = await database.get_user_orders(message.from_user.id)
    lang = await database.get_user_language(message.from_user.id)
    text = build_personal_message(lang, orders, state["cycle"])
    if not text:
        await message.answer(
            "Sizda buyurtma tarixi yo'q, shuning uchun namuna tuzilmadi. "
            "Namunani ko'rish uchun avval biror buyurtma bering."
        )
        return
    await message.answer("👁 <b>Sizning shaxsiy xabaringiz (faqat sizga):</b>", parse_mode=ParseMode.HTML)
    await message.answer(text, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                          reply_markup=reco_keyboard(lang, orders))


@router.message(Command("reco_now"))
async def reco_now(message: Message):
    buyers = await database.get_user_ids_with_orders()
    await message.answer(f"📤 {len(buyers)} ta xaridorga shaxsiy tavsiya yuborilmoqda…")
    sent, failed = await send_personal_batch(message.bot)
    await database.advance_reco()
    await message.answer(
        f"✅ {sent} ta yetkazildi, ⚠️ {failed} ta yetmadi.",
        parse_mode=ParseMode.HTML,
    )


# ─────────────────────────────────────────────────────────────────────────────
# One-time NPS (1-10) satisfaction survey
#
#   /nps_test  — preview the survey (sent only to you)
#   /nps_now   — send the survey to every buyer with at least one real order
# ─────────────────────────────────────────────────────────────────────────────
from nps_survey import send_nps_batch


@router.message(Command("nps_test"))
async def nps_test(message: Message):
    await message.answer("👁 <b>NPS so'rovnomasi (faqat sizga ko'rsatildi):</b>", parse_mode=ParseMode.HTML)
    sent, failed = await send_nps_batch(message.bot, only_user=message.from_user.id)
    if not sent:
        await message.answer("⚠️ Yuborib bo'lmadi.")


@router.message(Command("nps_now"))
async def nps_now(message: Message):
    buyers = await database.get_user_ids_with_orders()
    buyers = [uid for uid in buyers if uid not in database.LEADERBOARD_EXCLUDED_USER_IDS]
    await message.answer(f"📤 {len(buyers)} ta mijozga NPS so'rovnomasi yuborilmoqda…")
    sent, failed = await send_nps_batch(message.bot)
    await message.answer(
        f"✅ {sent} ta yetkazildi, ⚠️ {failed} ta yetmadi.",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("backup_now"))
async def backup_now(message: Message):
    """Manually trigger the full-DB backup right now (normally runs ~03:00
    Tashkent automatically) — sends a gzipped JSON snapshot of every table
    to every admin, right here in Telegram."""
    from db_backup import run_backup_now

    await message.answer("🗄 Zaxira nusxa tayyorlanmoqda…")
    result = await run_backup_now(message.bot)
    await message.answer(
        f"✅ Yuborildi: {result['sent']} ta admin, ⚠️ {result['failed']} ta yetmadi. "
        f"Hajmi: {result['size_bytes'] / 1024:.0f} KB",
        parse_mode=ParseMode.HTML,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Keto gamification (test rollout, 2026-07-26) — earn-only, instant kill switch:
#   /keto_status  — enabled? how many users/Keto so far?
#   /keto_on      — enable awarding (default ON at deploy)
#   /keto_off     — pause awarding immediately, no redeploy needed
# ─────────────────────────────────────────────────────────────────────────────

@router.message(Command("keto_status"))
async def keto_status(message: Message):
    state = await database.get_gamification_state()
    holat = "🟢 yoqilgan (test rejimi)" if state["enabled"] else "🔴 to'xtatilgan"
    stats = await database.get_keto_program_stats()
    await message.answer(
        f"🥑 <b>Keto gemifikatsiya holati</b>\n\n"
        f"Holat: {holat}\n"
        f"Keto olgan foydalanuvchilar: <b>{stats['users_with_keto']}</b>\n"
        f"Jami berilgan Keto: <b>{stats['total_awarded']:,}</b>".replace(",", " ") + "\n"
        f"Ochilgan yutuqlar: <b>{stats['achievements_unlocked']}</b>",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("keto_on"))
async def keto_on(message: Message):
    await database.set_gamification_enabled(True)
    await message.answer("🟢 Keto berish <b>yoqildi</b>.", parse_mode=ParseMode.HTML)


@router.message(Command("keto_off"))
async def keto_off(message: Message):
    await database.set_gamification_enabled(False)
    await message.answer(
        "🔴 Keto berish <b>to'xtatildi</b>. Hech kimga endi Keto berilmaydi "
        "(oldin berilganlar saqlanib qoladi).",
        parse_mode=ParseMode.HTML,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Kunlik qiziqish eslatmasi (daily_interest.py)
#   /qiziqish_status — holat, oluvchilar soni, jadval
#   /qiziqish_on     — yoqish
#   /qiziqish_off    — to'xtatish
#   /qiziqish_test   — namunani faqat o'zingizga yuborish
#   /qiziqish_now    — hoziroq hammaga yuborish
# ─────────────────────────────────────────────────────────────────────────────
import daily_interest


@router.message(Command("qiziqish_status"))
async def interest_status(message: Message):
    state = await database.get_interest_state()
    people = await database.get_user_ids_with_views(daily_interest.RECENT_DAYS)
    last = state.get("last_sent_date")
    holat = "🟢 yoqilgan" if state.get("enabled") else "🔴 to'xtatilgan"
    await message.answer(
        f"👀 <b>Kunlik qiziqish eslatmasi</b>\n\n"
        f"Holat: {holat}\n"
        f"Oluvchilar (so'nggi {daily_interest.RECENT_DAYS} kunda mahsulot ko'rganlar): "
        f"<b>{len(people)}</b> ta\n"
        f"Sikl (matn rotatsiyasi): {state.get('cycle', 0)}\n"
        f"Oxirgi yuborilgan sana: {last or '— (hali yo‘q)'}\n\n"
        f"Jadval: har kuni <b>{daily_interest.SEND_HOUR}:00</b> (Toshkent).\n"
        f"O'sha kuni maslahat / shaxsiy tavsiya / aksiya e'loni allaqachon "
        f"yuborilgan bo'lsa, bu xabar o'tkazib yuboriladi — kuniga ikkitadan "
        f"ortiq xabar bormasligi uchun.",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("qiziqish_on"))
async def interest_on(message: Message):
    await database.set_interest_enabled(True)
    await message.answer("🟢 Kunlik qiziqish eslatmasi <b>yoqildi</b>.", parse_mode=ParseMode.HTML)


@router.message(Command("qiziqish_off"))
async def interest_off(message: Message):
    await database.set_interest_enabled(False)
    await message.answer("🔴 Kunlik qiziqish eslatmasi <b>to'xtatildi</b>.", parse_mode=ParseMode.HTML)


@router.message(Command("qiziqish_test"))
async def interest_test(message: Message):
    """Preview against YOUR own most-viewed product — nothing is recorded and
    nobody else receives anything."""
    sent, failed, skipped = await daily_interest.send_batch(message.bot, only_user=message.from_user.id)
    if skipped:
        await message.answer(
            "Sizda ko'rilgan mahsulot yo'q, shuning uchun namuna tuzilmadi. "
            "Katalogdan biror mahsulotni ochib, qayta urinib ko'ring."
        )
    elif failed:
        await message.answer("⚠️ Yuborib bo'lmadi.")


@router.message(Command("qiziqish_now"))
async def interest_now(message: Message):
    people = await database.get_user_ids_with_views(daily_interest.RECENT_DAYS)
    await message.answer(f"📤 {len(people)} ta foydalanuvchiga qiziqish eslatmasi yuborilmoqda…")
    sent, failed, skipped = await daily_interest.send_batch(message.bot)
    state = await database.get_interest_state()
    await database.advance_interest(daily_interest._now_tk().date(), int(state.get("cycle") or 0) + 1)
    await message.answer(
        f"✅ {sent} ta yetkazildi · ⚠️ {failed} ta yetmadi · ⏭ {skipped} ta o'tkazildi.",
        parse_mode=ParseMode.HTML,
    )
