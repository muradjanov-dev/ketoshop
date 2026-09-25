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

RELEASE_KEY = "2026-09-25-savdo-hisobi"
TZ_OFFSET = timedelta(hours=5)
SEND_WINDOW = (8, 22)          # never wake admins at night
# The owner asked for this release's notes to go out immediately (2026-09-25),
# so the daytime window is bypassed. Back to False for the next release.
SEND_NOW = True
CHECK_EVERY = 300

NOTES = "🆕 <b>Statistikadagi xato tuzatildi</b>\n\n📉 <b>Muammo nima edi</b>\nKun yakuni hisoboti savdoni kam ko'rsatardi. Masalan 24-sentabr uchun «5 ta sotuv · 561 000 so'm» deb yozdi, aslida o'sha kuni 1 000 000 dan ortiq savdo bo'lgan edi.\n\nSababi: bitta qatordagi ikki raqam ikki xil joydan olinardi. <b>Sotuv soni</b> — o'sha kuni tushgan buyurtmalardan. <b>Pul</b> esa — faqat o'sha kuni kuryer «yetkazildi» deb belgilagan buyurtmalardan. Kechqurun ko'p buyurtma hali yo'lda bo'ladi, shuning uchun ular sotuv bo'lib ko'rinardi, lekin puli hisobga kirmasdi.\n\n✅ <b>Endi qanday</b>\nBuyurtma tushgan zahoti puli ham, soni ham darhol hisobga kiradi — kuryerni kutmaydi. Ikki raqam doim bitta buyurtmalar to'plamidan olinadi.\nBuyurtma bekor qilinsa, u o'sha zahoti savdodan ham, foydadan ham chiqib ketadi — kunlik va oylik raqamlardan ham.\n\n♻️ <b>Bekor qilingan buyurtmaning chiqimlari qaytariladi</b>\nIlgari buyurtma yetkazilib, keyin bekor qilinsa, uning sovg'asi, aksiya bonusi va kuryer haqi «Chiqimlar»da qolib ketardi — ya'ni berilmagan mol foydani yeb turardi. Endi bekor qilingan zahoti o'sha chiqimlar o'zi o'chadi. Eskilari ham tozalanadi.\n\n🎁 <b>Keto bilan to'langan pul alohida ko'rinadi</b>\nMijoz Keto tangacha bilan to'lagan summa endi hisobotda va saytdagi panelda alohida qator bo'lib turadi. U «Chiqimlar»ga yozilmaydi — chunki mijoz o'sha pulni allaqachon kam to'lagan, ya'ni tushumdan bir marta ayrilgan. Ikkinchi marta ayirsak, foyda haqiqiydan kam chiqardi.\n\n📅 <b>«Oxirgi kunlar» ro'yxati o'zini tuzatadi</b>\nOxirgi 7 kunning raqamlari har yarim soatda qaytadan hisoblanadi. Kechagi buyurtma bugun bekor qilinsa yoki tannarx to'ldirilsa, o'sha kunning qatori o'zi to'g'rilanadi.\n\n⚠️ <b>Bittasi hali qo'lda</b>\n17-sentabrdan 25-sentabrgacha bo'lgan kunlarning yozib qo'yilgan raqamlari eski holida turibdi. Ular bir martalik tozalashni kutyapti — ayting, ishga tushiraman.\n\n🏷 <b>Eslatma:</b> Eritritol (B2B) va Zig'ir urug'i 1000g tannarxi hali kiritilmagan. Shu sababli foyda haqiqiydan yuqori ko'rinyapti — panelda «Asl narx»ni to'ldirsangiz, raqam aniq bo'ladi.\n\nHammasi serverga yuklandi va ishlayapti ✅"


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
