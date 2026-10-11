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
from config import ADMIN_IDS, WEBAPP_URL

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
        f"🎁 <b>Keto gemifikatsiya holati</b>\n\n"
        f"Holat: {holat}\n"
        f"Keto olgan foydalanuvchilar: <b>{stats['users_with_keto']}</b>\n"
        f"Jami berilgan Keto: <b>{stats['total_awarded']:,}</b>".replace(",", " ") + "\n"
        f"Ochilgan yutuqlar: <b>{stats['achievements_unlocked']}</b>",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("sayt"))
async def sayt(message: Message):
    """The admin site's address as plain, copyable text.

    The inline buttons open it, but a button cannot be copied — and the
    address lives only in WEBAPP_URL on the server, so there is nowhere else
    to read it from.
    """
    if not WEBAPP_URL:
        await message.answer(
            "⚠️ Sayt manzili sozlanmagan (WEBAPP_URL bo'sh). "
            "Serverdagi sozlamaga qo'shilishi kerak.")
        return
    base = WEBAPP_URL.rstrip("/")
    await message.answer(
        "🌐 <b>Boshqaruv paneli</b>\n"
        f"<code>{base}/admin</code>\n\n"
        "🛒 <b>Do'kon (Mini App)</b>\n"
        f"<code>{base}</code>\n\n"
        "Manzilni bosib nusxalab olsangiz bo'ladi. Panelga kirish uchun parol so'raladi.",
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


@router.message(Command("keto_berish"))
async def keto_berish(message: Message):
    """Qo'lda Keto qo'shish — sinov uchun va nosozlikni tuzatish uchun.

        /keto_berish 100              -> o'zingizga
        /keto_berish 123456789 100    -> o'sha foydalanuvchiga

    Faqat qo'shadi. Yechish uchun alohida yo'l kerak: credit_keto balans
    bilan birga keto_lifetime'ni ham o'zgartiradi, u esa darajani belgilaydi
    — manfiy son odamni darajasidan tushirib yuborardi.

    Har bir harakat keto_ledger'ga kim bergani bilan yoziladi, shunda balans
    o'z-o'zidan o'zgarganday ko'rinmaydi.
    """
    parts = (message.text or "").split()
    target = message.from_user.id
    raw_amount = None
    if len(parts) == 2:
        raw_amount = parts[1]
    elif len(parts) >= 3:
        target, raw_amount = parts[1], parts[2]
    try:
        amount = int(raw_amount)
        target = int(target)
    except (TypeError, ValueError):
        await message.answer(
            "Format:\n"
            "<code>/keto_berish 100</code> — o'zingizga\n"
            "<code>/keto_berish 123456789 100</code> — boshqa foydalanuvchiga\n"
            "Faqat musbat son.",
            parse_mode=ParseMode.HTML,
        )
        return
    if amount <= 0:
        await message.answer(
            "Faqat musbat son qo'shiladi. Yechish darajani ham tushirib "
            "yuboradi, shuning uchun bu buyruqda yo'q.")
        return

    user = await database.get_user(target)
    if not user:
        await message.answer(f"❌ <code>{target}</code> foydalanuvchi topilmadi.",
                             parse_mode=ParseMode.HTML)
        return

    await database.credit_keto(
        target, None, amount, kind="manual",
        note=f"admin {message.from_user.id}",
    )
    fresh = await database.get_user(target)
    balance = int(fresh.get("keto_balance") or 0)
    who = "Sizga" if target == message.from_user.id else f"<code>{target}</code> ga"
    await message.answer(
        f"🎁 {who} <b>+{amount}</b> Keto yozildi.\n"
        f"Yangi balans: <b>{balance:,}</b> Keto".replace(",", " "),
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


# ─────────────────────────────────────────────────────────────────────────────
# Kun mahsuloti — one product a day to every buyer and to the channel
#
#   /kun_status   — holat: yoqilganmi, bugun ketdimi, oxirgi 7 kun
#   /kun_on       — kunlik yuborishni yoqish
#   /kun_off      — to'xtatish
#   /kun_test     — bugungi mahsulot kartochkasini FAQAT o'zingizga yuboradi
#   /kun_kanal    — FAQAT kanalga sinov posti (mijozlarga yuborilmaydi)
#   /kun_otkaz    — navbatdagi mahsulotni o'tkazib yuborish (hech kimga ketmaydi)
#   /kun_now      — hoziroq barchaga va kanalga yuboradi
# ─────────────────────────────────────────────────────────────────────────────
import product_of_day


@router.message(Command("kun_status"))
async def kun_status(message: Message):
    state = await database.get_product_of_day_state()
    holat = "🟢 yoqilgan" if state["enabled"] else "🔴 to'xtatilgan"
    last = state["last_sent_date"]
    last_str = last.strftime("%d.%m.%Y") if last else "— (hali yo'q)"
    product, cycle = await product_of_day.pick_product()
    keyingi = f"{product.get('name')} (#{product['id']})" if product else "— (zaxirada mahsulot yo'q)"

    history = await database.get_product_of_day_history(7)
    tarix = "\n".join(
        f"• {h['sent_at'].strftime('%d.%m')} — {h['name'] or '#' + str(h['product_id'])}"
        f" · ✅{h['sent']} ⚠️{h['failed']}{' · 📣' if h['channel_ok'] else ''}"
        for h in history
    ) or "—"

    await message.answer(
        f"📦 <b>Kun mahsuloti</b>\n\n"
        f"Holat: {holat}\n"
        f"Vaqt: har kuni <b>{product_of_day.SEND_HOUR:02d}:00</b> (Toshkent)\n"
        f"Oxirgi yuborilgan kun: {last_str}\n"
        f"Navbatdagi mahsulot: <b>{keyingi}</b>\n"
        f"Aylanma: {cycle + 1}-doira\n\n"
        f"<b>Oxirgi kunlar:</b>\n{tarix}",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("kun_on"))
async def kun_on(message: Message):
    await database.set_product_of_day_enabled(True)
    await message.answer(
        f"🟢 Kun mahsuloti yoqildi — har kuni soat "
        f"{product_of_day.SEND_HOUR:02d}:00 da barchaga va kanalga ketadi."
    )


@router.message(Command("kun_off"))
async def kun_off(message: Message):
    await database.set_product_of_day_enabled(False)
    await message.answer("🔴 Kun mahsuloti to'xtatildi.")


@router.message(Command("kun_test"))
async def kun_test(message: Message):
    """Preview: the exact card, sent only to the admin who asked."""
    product, _cycle = await product_of_day.pick_product()
    if product is None:
        await message.answer("Zaxirada bor mahsulot topilmadi.")
        return
    lang = await database.get_user_language(message.from_user.id)
    await message.answer(
        f"👀 Navbatdagi kun mahsuloti: <b>{product.get('name')}</b>\n"
        f"Quyida — mijoz ko'radigan kartochka:",
        parse_mode=ParseMode.HTML,
    )
    import product_card
    await product_card.send_card(message.bot, message.from_user.id, product, lang)


@router.message(Command("kun_kanal"))
async def kun_kanal(message: Message):
    """Channel-only dry run: post the card to the channel and tell the admin
    how it went. No customer ever sees this one — it exists so the channel
    layout can be checked before a day's real send goes out."""
    product, _cycle = await product_of_day.pick_product()
    if product is None:
        await message.answer("Zaxirada bor mahsulot topilmadi.")
        return
    ok = await product_of_day.post_to_channel(message.bot, product)
    if ok:
        # The channel has now seen it, so the product is spent for this cycle:
        # without this, the next real send would post the very same card again.
        # The day itself stays open — today's 13:00 send takes the next one.
        await database.record_product_of_day(product["id"], _cycle, 0, 0, True)
        nxt, _c = await product_of_day.pick_product()
        await message.answer(
            f"📣 Kanalga sinov posti ketdi: <b>{product.get('name')}</b>\n"
            f"Mijozlarga yuborilmadi. Yoqmasa — kanaldan o'chirib tashlang.\n\n"
            f"Bu mahsulot shu aylanishda qayta chiqmaydi.\n"
            f"Navbatdagi: <b>{nxt.get('name') if nxt else '—'}</b>",
            parse_mode=ParseMode.HTML,
        )
    else:
        await message.answer(
            "⚠️ Kanalga yuborib bo'lmadi. Bot kanalda admin ekanini va "
            "post qo'yish huquqi borligini tekshiring."
        )


@router.message(Command("kun_otkaz"))
async def kun_otkaz(message: Message):
    """Retire the queued product without sending it anywhere — for a card that
    was already posted by hand, or one that simply shouldn't go out now."""
    product, cycle = await product_of_day.pick_product()
    if product is None:
        await message.answer("Navbatda mahsulot yo'q.")
        return
    await database.record_product_of_day(product["id"], cycle, 0, 0, False)
    nxt, _c = await product_of_day.pick_product()
    await message.answer(
        f"⏭ <b>{product.get('name')}</b> o'tkazib yuborildi — shu aylanishda qayta chiqmaydi.\n"
        f"Navbatdagi: <b>{nxt.get('name') if nxt else '—'}</b>",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("kun_now"))
async def kun_now(message: Message):
    await message.answer("📤 Kun mahsuloti barchaga va kanalga yuborilmoqda…")
    result = await product_of_day.send_today(message.bot)
    if result is None:
        await message.answer("Zaxirada bor mahsulot topilmadi — hech narsa yuborilmadi.")
        return
    await message.answer(
        f"✅ <b>{result['product'].get('name')}</b> yuborildi.\n"
        f"Mijozlar: ✅ {result['sent']} · ⚠️ {result['failed']}\n"
        f"Kanal: {'📣 yuborildi' if result['channel_ok'] else '⚠️ yuborilmadi'}",
        parse_mode=ParseMode.HTML,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Yangiliklar e'loni — what changed FOR THE BUYER, in their own words
#
#   /yangilik_test    — uchala tilda, faqat o'zingizga
#   /yangilik_kanal   — faqat kanalga (kirillcha)
#   /yangilik_hammaga — barcha mijozlarga, har biriga o'z tilida
# ─────────────────────────────────────────────────────────────────────────────
import news_announce


@router.message(Command("yangilik_test"))
async def yangilik_test(message: Message):
    """All three languages, to the admin who asked — nobody else sees it."""
    for lang in ("uz", "uz_cyr", "ru"):
        await message.answer(news_announce.text_for(lang),
                             parse_mode=ParseMode.HTML,
                             reply_markup=news_announce.buyer_keyboard(lang),
                             disable_web_page_preview=True)
    await message.answer(
        "👆 Yuqoridagi uchtasi — mijoz o'z tilida oladigan xabar.\n"
        "Kanalga: /yangilik_kanal · Hammaga: /yangilik_hammaga"
    )


@router.message(Command("yangilik_kanal"))
async def yangilik_kanal(message: Message):
    ok = await news_announce.post_to_channel(message.bot)
    await message.answer(
        "📣 Kanalga e'lon qo'yildi. Yoqmasa — kanaldan o'chirib tashlang."
        if ok else
        "⚠️ Kanalga yuborib bo'lmadi. Bot kanalda admin ekanini tekshiring."
    )


@router.message(Command("yangilik_hammaga"))
async def yangilik_hammaga(message: Message):
    await message.answer("📤 E'lon barcha mijozlarga yuborilmoqda — biroz vaqt oladi…")
    sent, failed = await news_announce.broadcast(message.bot)
    await message.answer(
        f"✅ {sent} ta mijozga yetkazildi, ⚠️ {failed} ta yetmadi.",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Oylik hisobot — kanalga bir martalik e'lon (monthly_report.py).
#   /hisobot_test  — faqat o'zingizga, kanal tugmasi bilan
#   /hisobot_kanal — kanalga
# ─────────────────────────────────────────────────────────────────────────────
import monthly_report


@router.message(Command("hisobot_test"))
async def hisobot_test(message: Message):
    await monthly_report.send_preview(message.bot, message.chat.id)
    await message.answer("👆 Kanalga aynan shu ko'rinishda chiqadi.\nKanalga: /hisobot_kanal")


@router.message(Command("hisobot_kanal"))
async def hisobot_kanal(message: Message):
    ok = await monthly_report.post_to_channel(message.bot)
    await message.answer(
        "📣 Hisobot kanalga qo'yildi. Yoqmasa — kanaldan o'chirib tashlang."
        if ok else
        "⚠️ Kanalga yuborib bo'lmadi. Bot kanalda admin ekanini tekshiring."
    )


# Kanal postlari — one content post a day to the channel, in course order
#
#   /kanal_status  — holat: qaysi kun, qaysi hafta, navbatdagi post
#   /kanal_on      — kunlik postni yoqish
#   /kanal_off     — to'xtatish
#   /kanal_test    — navbatdagi postni FAQAT o'zingizga ko'rsatadi
#   /kanal_now     — navbatdagini hoziroq kanalga chiqaradi
#   /kanal_otkaz   — navbatdagini o'tkazib yuboradi (hech qayerga ketmaydi)
#   /kanal_set N   — navbatni N-kunga qo'yish (1 dan 105 gacha)
# ─────────────────────────────────────────────────────────────────────────────
import channel_posts
import channel_posts_content as _cpc


@router.message(Command("kanal_status"))
async def kanal_status(message: Message):
    state = await database.get_channel_post_state()
    holat = "🟢 yoqilgan" if state["enabled"] else "🔴 to'xtatilgan"
    pos = state["position"]
    slug = channel_posts.slug_at(pos)
    title = _cpc.POSTS[slug][0]
    week, theme = _cpc.week_of(pos)
    day_in_week = pos % 7 + 1
    last = state["last_sent_date"]
    last_str = last.strftime("%d.%m.%Y") if last else "— (hali yo'q)"

    history = await database.get_channel_post_history(7)
    tarix = "\n".join(
        f"• {h['sent_at'].strftime('%d.%m')} — {_cpc.POSTS.get(h['slug'], ('?',))[0]}"
        for h in history
    ) or "—"

    await message.answer(
        f"📣 <b>Kanal postlari</b>\n\n"
        f"Holat: {holat}\n"
        f"Vaqt: har kuni <b>{channel_posts.SEND_HOUR:02d}:"
        f"{channel_posts.SEND_MINUTE:02d}</b> (Toshkent)\n"
        f"Oxirgi chiqqan kun: {last_str}\n\n"
        f"Navbatdagi: <b>{title}</b>\n"
        f"📅 {pos + 1}-kun / {len(_cpc.ORDER)} · {week}-hafta «{theme}» "
        f"({day_in_week}-kuni)\n"
        f"🔄 Aylanma: {state['cycle'] + 1}-doira\n\n"
        f"<b>Oxirgi kunlar:</b>\n{tarix}",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("kanal_on"))
async def kanal_on(message: Message):
    await database.set_channel_posts_enabled(True)
    await message.answer(
        f"🟢 Kanal postlari yoqildi — har kuni soat "
        f"{channel_posts.SEND_HOUR:02d}:{channel_posts.SEND_MINUTE:02d} da chiqadi."
    )


@router.message(Command("kanal_off"))
async def kanal_off(message: Message):
    await database.set_channel_posts_enabled(False)
    await message.answer("🔴 Kanal postlari to'xtatildi. Yoqish: /kanal_on")


@router.message(Command("kanal_test"))
async def kanal_test(message: Message):
    """Preview: the exact post, sent only to the admin who asked."""
    state = await database.get_channel_post_state()
    slug = channel_posts.slug_at(state["position"])
    week, theme = _cpc.week_of(state["position"])
    await message.answer(
        f"👀 Navbatdagi kanal posti — {state['position'] + 1}-kun, "
        f"{week}-hafta «{theme}»:",
        parse_mode=ParseMode.HTML,
    )
    await message.answer(
        channel_posts.build_text(slug),
        parse_mode=ParseMode.HTML,
        reply_markup=channel_posts.keyboard(),
        disable_web_page_preview=True,
    )


@router.message(Command("kanal_now"))
async def kanal_now(message: Message):
    """Send the queued post to the channel right now. The calendar day is
    closed too, so the scheduler doesn't post a second one this evening."""
    result = await channel_posts.send_today(message.bot)
    if result is None:
        await message.answer(
            "⚠️ Kanalga yuborib bo'lmadi. Bot kanalda admin ekanini va "
            "post qo'yish huquqi borligini tekshiring."
        )
        return
    title = _cpc.POSTS[result["slug"]][0]
    await message.answer(
        f"📣 Kanalga chiqdi: <b>{title}</b>\n"
        f"📅 {result['position'] + 1}-kun · {result['week']}-hafta "
        f"«{result['theme']}»\n"
        f"Bugungi post shu — ertaga navbatdagisi chiqadi.",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("kanal_otkaz"))
async def kanal_otkaz(message: Message):
    """Skip the queued post — it goes nowhere and the cursor moves on."""
    skipped = await channel_posts.skip_next()
    state = await database.get_channel_post_state()
    nxt = channel_posts.slug_at(state["position"])
    await message.answer(
        f"⏭ <b>{_cpc.POSTS[skipped][0]}</b> o'tkazib yuborildi.\n"
        f"Navbatdagi: <b>{_cpc.POSTS[nxt][0]}</b> ({state['position'] + 1}-kun)",
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("kanal_set"))
async def kanal_set(message: Message, command: CommandObject):
    """Jump the queue to a given day, 1-based — for restarting the course or
    re-running a post that deserves a second outing."""
    arg = (command.args or "").strip()
    if not arg.isdigit() or not (1 <= int(arg) <= len(_cpc.ORDER)):
        await message.answer(
            f"Foydalanish: <code>/kanal_set N</code> — N 1 dan "
            f"{len(_cpc.ORDER)} gacha.",
            parse_mode=ParseMode.HTML,
        )
        return
    pos = int(arg) - 1
    state = await database.get_channel_post_state()
    await database.set_channel_post_position(pos, state["cycle"])
    week, theme = _cpc.week_of(pos)
    await message.answer(
        f"✅ Navbat {pos + 1}-kunga qo'yildi: "
        f"<b>{_cpc.POSTS[channel_posts.slug_at(pos)][0]}</b>\n"
        f"{week}-hafta «{theme}»",
        parse_mode=ParseMode.HTML,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Sovg'a eslatmasi (gift_campaign.send_reminder) — 2026-10-03 09:00 da o'zi
# ketadi. Bu buyruq faqat ko'rinishini so'ragan adminga ko'rsatadi.
# ─────────────────────────────────────────────────────────────────────────────

@router.message(Command("sovga_eslatma_test"))
async def sovga_eslatma_test(message: Message):
    import gift_campaign
    from datetime import timedelta
    row = await gift_campaign._state(force=True)
    if not row or not row.get("ends_at"):
        await message.answer("Sovg'a kampaniyasi faol emas — eslatma ketmaydi.")
        return
    until = row["ends_at"] + gift_campaign.TZ_OFFSET
    lang = await database.get_user_language(message.from_user.id)
    photo = await gift_campaign._product_photo(await gift_campaign.gift_product(force=True))
    for segment, label in (("new", "🆕 Hali sovg'a olmaganlarga"), ("again", "🔁 Sovg'a olganlarga")):
        await message.answer(f"👁 <b>{label}</b> (faqat sizga):", parse_mode=ParseMode.HTML)
        await gift_campaign._send_photo(message.bot, message.from_user.id, photo,
                                        gift_campaign.reminder_text(segment, lang, until),
                                        gift_campaign.reminder_keyboard(lang))
    since = row.get("announced_at")
    got = len(await gift_campaign.gift_receivers(since)) if since else 0
    total = len(await database.get_all_user_ids())
    await message.answer(
        f"📅 Avtomatik: {gift_campaign.REMINDER_FROM:%d.%m.%Y} soat "
        f"{gift_campaign.REMINDER_WINDOW[0]:02d}:00 dan, bir marta.\n"
        f"👥 Jami {total} ta foydalanuvchi: {got} tasiga «yana sovg'a», qolganiga «xabaringiz bormi».")


# ─────────────────────────────────────────────────────────────────────────────
# Shaxsiy tavsiyalar tekshiruvi (product_tips.py) — prod bazasidagi haqiqiy
# xaridorlar uchun kartochkada qaysi juftlik gapi chiqishini ko'rsatadi.
#   /tavsiya_test           — oxirgi xarid qilgan 3 ta mijoz
#   /tavsiya_test <user_id> — aniq bitta mijoz
# Hech kimga hech narsa yuborilmaydi.
# ─────────────────────────────────────────────────────────────────────────────

@router.message(Command("tavsiya_test"))
async def tavsiya_test(message: Message, command: CommandObject):
    import html as _html
    import product_tips
    import retention
    arg = (command.args or "").strip()
    only = int(arg) if arg.lstrip("-").isdigit() else None
    orders_by_user = await retention._load_orders(only)     # real orders only, admins excluded
    available = await retention._load_available()
    lang = await database.get_user_language(message.from_user.id)
    products = [p for key, p in available.items() if key[0] == "p"]

    def recent(uid):
        return max(o["created_at"] for o in orders_by_user[uid])

    blocks = []
    for uid in sorted(orders_by_user, key=recent, reverse=True):
        hist = product_tips.history_from_orders(orders_by_user[uid])
        owned = {h["key"] for h in hist if h["key"]}
        lines = []
        for prod in products:
            vkey = product_tips.tip_key(prod.get("name") or "")
            earlier = next((h for h in hist if h["key"] and h["key"] != vkey
                            and (vkey, h["key"]) in product_tips.PAIRS), None)
            if not vkey or vkey in owned or not earlier:
                continue
            tip = product_tips.choose(hist, prod, lang, turn=0)
            lines.append(f"• <b>{_html.escape(prod['name'])}</b> ← {_html.escape(earlier['name'])}\n"
                         f"  💡 <i>{_html.escape(tip or '')}</i>")
            if len(lines) == 3:
                break
        if lines:
            bought = ", ".join(_html.escape(h["name"]) for h in hist[:4])
            blocks.append(f"👤 Mijoz <code>{uid}</code> — avval olgan: {bought}\n" + "\n".join(lines))
        if len(blocks) == (1 if only else 3):
            break

    if not blocks:
        await message.answer("Mos juftligi bor mijoz topilmadi."
                             + (" Bu mijozning bekor qilinmagan o'z buyurtmasi yo'q." if only else ""))
        return
    await message.answer("🧪 <b>Shaxsiy tavsiyalar — haqiqiy mijozlar</b>\n"
                         "Kartochkada (birinchi variant) shunday chiqadi:\n\n" + "\n\n".join(blocks),
                         parse_mode=ParseMode.HTML)
