"""
"Nima yangi" — one message to every admin after a deploy (2026-09-17).

broadcast_updates_script.py does the same job by hand, but it has to be run on
the server with production credentials. This sends the notes from the running
bot itself, so a deploy through GitHub is enough.

Each release has a KEY. The first time a bot with that key runs, the notes go
to every admin — hardcoded and the ones added through the bot (bot.py merges
those into ADMIN_IDS at startup) — once, during daytime. The key is claimed in
the database before sending, so restarts and redeploys never repeat it.

For the next release: change RELEASE_KEY and rewrite NOTES.
"""
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.enums import ParseMode

import database
from config import ADMIN_IDS

logger = logging.getLogger(__name__)

RELEASE_KEY = "2026-09-17-oson-buyurtma-sovga-ombor"
TZ_OFFSET = timedelta(hours=5)
SEND_WINDOW = (8, 22)          # never wake admins at night
# Owner asked for this release's notes to go out right away (2026-09-17,
# "hoziroq yubor"), so the daytime window is skipped for it. Set back to
# False for the next release.
SEND_NOW = True
CHECK_EVERY = 300

NOTES = (
    "🆕 <b>Botga yangi imkoniyatlar qo'shildi</b>\n\n"

    "🛒 <b>Buyurtma berish osonlashdi</b>\n"
    "• Mahsulot savatga qo'shilganda «✅ … savatingizga qo'shildi» xabari keladi — "
    "savatdagi soni, summasi va [Buyurtma berish] [Savat] tugmalari bilan "
    "(botda ham, Mini App'da ham)\n"
    "• Telefon raqami bir tugma bilan yuboriladi — yozish shart emas\n"
    "• Ixtiyoriy qadamlarda «⏭ O'tkazib yuborish» tugmasi\n"
    "• «⚡ Tezkor buyurtma» — avval buyurtma bergan mijoz saqlangan manzil va "
    "to'lov usuli bilan 2 bosishda buyurtma beradi\n"
    "• Har qadamda «Qadam 2/6», savat tugmasida mahsulot soni va summasi\n\n"

    "🎁 <b>Eritritol 100gr sovg'asi — 30 kun</b>\n"
    "• Botda <b>111 000 so'm va undan yuqori</b> har bir buyurtmaga avtomatik "
    "qo'shiladi (bir kunda necha marta bo'lsa ham)\n"
    "• Bugun <b>09:00</b> da barcha mijozlarga e'lon qilinadi va shundan boshlanadi\n"
    "• Adminlar va do'kon akkauntlari buyurtmasiga qo'shilmaydi\n"
    "• Yetkazilgan har bir sovg'a <b>Chiqimlar</b>ga avtomatik yoziladi "
    "(«🎁 Sovg'a: Eritritol 100gr — buyurtma #…»)\n"
    "• Buyurtma xabarida «🎁 BONUS» qatori chiqadi — qadoqlashda qo'shishni unutmang\n"
    "• Holati: /sovga\n\n"

    "🔔 <b>Tashlab ketilgan savat eslatmasi</b>\n"
    "Savatga mahsulot solib buyurtma bermagan mijozga 3 va 24 soatdan keyin "
    "eslatma boradi (faqat 09:00–21:00). Natijasi: /savat_eslatma\n\n"

    "📦 <b>Ombor ogohlantirishlari</b>\n"
    "Mahsulot <b>tugasa yoki 5 tadan kam qolsa</b> — barcha adminlarga xabar "
    "keladi, har safar shu chegaraga tushganda. Bugun kunduzi hozirgi holat "
    "bo'yicha bitta umumiy ro'yxat ham keladi. Istalgan payt: /ombor\n\n"

    "🍳 <b>Shaxsiy tavsiyalar yangilandi</b>\n"
    "• Endi <b>har 2 kunda</b>, kunduzi\n"
    "• Katalogdagi barcha 116 mahsulot uchun retseptlar, mijoz olgan "
    "mahsulotlaridan kelib chiqib\n"
    "• Profili yo'q yangi mahsulot bo'lsa, yuborishdan keyin adminlarga ro'yxat keladi\n\n"

    "🛡 <b>Guruhda havola qo'riqchisi</b>\n"
    "Bot guruhga «Xabarlarni o'chirish» huquqi bilan admin qilinsa, "
    "adminlardan boshqa hech kim havola tashlay olmaydi — havolali xabar o'chiriladi.\n\n"

    "📊 <b>Foyda hisobi tuzatildi</b>\n"
    "Aksiya bonuslari tannarxi noto'g'ri (gramm soni bo'yicha) hisoblanardi — "
    "tuzatildi. O'tgan aksiya davrlaridagi foyda raqamlari to'g'rilanib, ko'payishi mumkin.\n\n"

    "Hammasi serverga yuklandi va ishlayapti ✅"
)


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


async def send_if_due(bot: Bot) -> bool:
    if not SEND_NOW and not (SEND_WINDOW[0] <= _now_tk().hour < SEND_WINDOW[1]):
        return False
    if not await database.claim_release_notes(RELEASE_KEY):
        return False                    # already sent for this release
    sent = failed = 0
    for admin_id in list(dict.fromkeys(ADMIN_IDS)):
        try:
            await bot.send_message(admin_id, NOTES, parse_mode=ParseMode.HTML)
            sent += 1
        except Exception as exc:
            failed += 1
            logger.warning("Release notes to admin %s failed: %s", admin_id, exc)
        await asyncio.sleep(0.05)
    logger.info("Release notes %s: %d sent, %d failed", RELEASE_KEY, sent, failed)
    return True


async def scheduler_loop(bot: Bot) -> None:
    while True:
        try:
            if await send_if_due(bot):
                return
        except Exception:
            logger.exception("Release notes check failed")
        await asyncio.sleep(CHECK_EVERY)
