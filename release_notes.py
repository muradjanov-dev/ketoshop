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

RELEASE_KEY = "2026-10-oktyabr-yangiliklari"
TZ_OFFSET = timedelta(hours=5)
SEND_WINDOW = (8, 22)          # never wake admins at night
# True bypasses the daytime window (used once, 2026-09-25). Normal releases
# keep it False so admins are never messaged at night.
SEND_NOW = False
CHECK_EVERY = 300

NOTES = "🆕 <b>Oktyabr — botga nimalar qo'shildi</b>\n\n📦 <b>Buyurtmalar</b>\n• Buyurtma holati o'zgarganda <b>barcha adminlarga</b> to'liq kartochka keladi: mijoz, mahsulotlar, summa, eski → yangi holat va kim o'zgartirgani.\n• Admin qo'lda (yoki B2B) buyurtma kiritsa — hamma adminlarga to'liq ma'lumot va kim kiritgani.\n• Holat o'zgargach bot menyuga emas, buyurtmalar sahifasiga qaytadi.\n\n🚚 <b>Kuryer</b>\n• Kuryer paneli botdan alohida oynada ochiladi (📦 Buyurtmalar → 🚚 Kuryer paneli), Dashboard'siz.\n• Telefonda kartochka endi faqat <b>bosib ushlab turilsa</b> ko'chadi — tasodifiy surish buyurtmani o'zgartirmaydi. «Yetkazildi», «Bekor» va sudrab tashlash tasdiq so'raydi.\n\n📊 <b>Sayt paneli</b>\n• Dashboard'da yalpi va sof marja — so'mda va foizda.\n• Mahsulotlarda B2B/chakana, aqlli qidiruv va «tannarxi yo'q» filtri.\n• Jadval sarlavhalari aylantirganda tepada qotib turadi.\n\n💚 <b>Mijozlar uchun</b>\n• Mahsulot kartochkasida <b>shaxsiy maslahat</b> — mijoz avval nima olganiga qarab (bot va do'kon ilovasida), har safar boshqa variant.\n• Yetkazilgandan 3 kun keyin bot mahsulotlar haqida <b>fikr so'raydi</b> (sifati, pishirib ko'rdingizmi).\n• Xaridlar orasida bitta <b>💡 shaxsiy tavsiya</b> xabari — 7 kunda bittadan ortiq shaxsiy xabar bormaydi.\n• Do'kon ilovasida <b>barcha mahsulotlar karuseli</b> endi eng tepada.\n• 3-oktyabr ertalab hammaga Eritritol sovg'asi eslatmasi (sovg'a olganlarga — «yana istaysizmi?»).\n\n😄 <b>Kayfiyat</b>\n• Har bir admin xabarida unga mos quvnoq gap, yangi a'zo xabarlarida esa 38 xil ibora.\n\nSavol yoki taklif bo'lsa — yozing 🤝"


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
