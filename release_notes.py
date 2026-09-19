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

RELEASE_KEY = "2026-09-19-sirli-sovga-bonus-chiqim"
TZ_OFFSET = timedelta(hours=5)
SEND_WINDOW = (8, 22)          # never wake admins at night
# The owner asked for this release's notes to go out immediately (2026-09-19),
# so the daytime window is bypassed. Back to False for the next release.
SEND_NOW = True
CHECK_EVERY = 300

NOTES = (
    "🆕 <b>Oxirgi 12 soatda qo'shilganlar</b>\n\n"
    "🎁 <b>Sirli sovg'a — 400 000 so'mdan yuqori buyurtmalarga</b>\n"
    "Ketoshop jamoasi nomidan, nima ekani aytilmaydi — sir bo'lgani uchun ham qiziq.\n"
    "• Yozuv mijoz pul sanaydigan har bir joyda: mahsulot kartochkasi, savatga qo'shildi xabari, savat, tasdiqlash ekrani va tasdiqdan keyingi xabar\n"
    "• Chegaraga yaqin qolganda o'zi hisoblab turadi: «yana 50 000 so'm va sovg'a sizniki» — o'rtacha chekni ko'taradigan aynan shu qator\n"
    "• Sovg'aning buyurtmada alohida qatori yo'q — uni qo'lda solasiz. Shuning uchun adminning buyurtma xabarida va Kuryer panelida «🎁 Sirli sovg'a — qutiga soling» belgisi chiqadi\n\n"
    "🚚 <b>Bepul yetkazib berish endi ko'rinadi</b>\n"
    "800 000 so'mdan Toshkent bo'ylab bepul — ilgari buni faqat savatga yetib kelgan mijoz bilardi. Endi har bir mahsulot kartochkasida, kanaldagi e'londa, Mini App'ning bosh sahifasida, katalogda va savatda yozib qo'yilgan.\n\n"
    "💸 <b>Aksiya bonuslari avtomatik Chiqimlarga yoziladi</b>\n"
    "Masalan 2 kg Steviyaga 0,5 kg bonus — buyurtma yetkazilgan zahoti bonusning tannarxi «Chiqimlar»ga tushadi, sovg'alar kabi. Bir buyurtma bir marta yoziladi va foydadan ikki marta yechilmaydi; eski buyurtmalar tegilmagan.\n"
    "Aksiyaning o'zini saytdagi «Aksiya» bo'limida tuzasiz: 2 kg Steviya → 0,5 kg Steviya bonus.\n\n"
    "🎁 <b>Keto tangachalar tushunarli yozildi</b>\n"
    "Mini App'da «+525 Keto» hech narsa demas edi. Endi ochiq: «Pulingiz qaytadi: 525 Keto».\n\n"
    "🍬 <b>Eritritol sovg'asi har bir kartochkada</b>\n"
    "«Har bir buyurtmaga 100 gr Eritritol sovg'a» yozuvi endi mijoz mahsulotni tanlayotganda ko'rinadi, savatni to'ldirgandan keyin emas. Kampaniya tugasa yoki Eritritol omborda qolmasa — yozuv o'zi yo'qoladi.\n\n"
    "🌟 <b>Kun mahsuloti ishga tushdi</b>\n"
    "Har kuni soat 13:00 da bitta mahsulot barcha mijozlarga o'z tilida, kanalga esa kirillchada chiqadi; kanaldagi «Botda sotib olish» tugmasi aynan o'sha mahsulotni ochadi. Yuborilgan kartochka mijozning chatidan o'chmaydi.\n"
    "• /kun_status — navbatdagi mahsulot\n"
    "• /kun_test — faqat o'zingizga\n"
    "• /kun_kanal — faqat kanalga sinov\n"
    "• /kun_otkaz — navbatdagini o'tkazib yuborish\n"
    "• /kun_off — to'xtatish\n\n"
    "📊 <b>Sovg'a hisoboti aniqlashdi</b>\n"
    "/sovga endi nechta buyurtma emas, nechta MIJOZ sovg'a olganini ham ko'rsatadi.\n\n"
    "💰 <b>Panelda tannarx ustuni</b>\n"
    "Mahsulotlar ro'yxatida tannarx narx yonida turadi — har birini ochib ko'rishning hojati yo'q.\n\n"
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
