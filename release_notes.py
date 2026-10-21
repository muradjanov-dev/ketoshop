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

RELEASE_KEY = "2026-10-22-sayt-yangiliklari"
TZ_OFFSET = timedelta(hours=5)
SEND_WINDOW = (8, 22)          # never wake admins at night
# True bypasses the daytime window (used once, 2026-09-25). Normal releases
# keep it False so admins are never messaged at night.
SEND_NOW = False
CHECK_EVERY = 300

NOTES = (
    "🆕 <b>So'nggi 3 kunda (19–22 oktabr) nimalar o'zgardi</b>\n"
    '\n'
    '🛠 <b>Tuzatildi</b>\n'
    "• Saytda telefon raqami har qanday yozilishda qabul qilinadi (90 123 45 67, +998…, 8 90…). Avval ko'p raqam rad etilib, «Buyurtmani tasdiqlash» tugmasi ishlamayotgandek ko'rinardi.\n"
    "• Xaritadan lokatsiya: GPS ishlamasa, xarita Toshkent markazida qolib, o'sha nuqta buyurtmaga ketib qolardi. Endi xaritani surmaguncha yoki aniq GPS kelmaguncha tasdiqlab bo'lmaydi, joylashuv Telegram orqali olinadi, xaritada «Mening joylashuvim» tugmasi bor.\n"
    "⚠️ 22-oktabrgacha kelgan buyurtmada pin aynan Toshkent markazida tursa — mijozning izohiga qarang yoki qo'ng'iroq qiling.\n"
    "• Quvvat tejash rejimidagi telefonlarda saytdagi animatsiyalar (KETOSHOP muhri, yuklanish belgilari) to'xtab qolardi — endi ishlaydi. Til almashtirilgandan keyin qotib qoladigan mahsulotlar karuseli ham tuzatildi.\n"
    '\n'
    '🛍 <b>Saytda yangi</b>\n'
    "• Bosh sahifada «🔥 Ko'p olinadi»: oxirgi 30 kunda eng ko'p buyurtmalarda uchragan, omborda bor 10 ta mahsulot. Har kartada «+ Savatga» — mahsulotni ochmasdan savatga tushadi.\n"
    "• Retseptda pastda doim turadigan panel: «Retseptdagi Ketoshop mahsulotlari» va narxi, «🛒 Savatga», keyin «Savatni ochish →».\n"
    "• Ekranda vaqti-vaqti bilan monarx kapalagi uchib o'tadi. Hech narsani to'smaydi, buyurtma paytida va oyna ochiq bo'lsa chiqmaydi.\n"
    "• Fonda ora-orada qushlar sayraydi — kunduzi, mijoz saytda birinchi marta bosgandan keyin. Mijoz 🐦 tugmasi bilan o'chirib qo'yishi mumkin.\n"
    '\n'
    '📊 <b>Admin saytida</b>\n'
    "• «📈 Faollik»: saytning har bir ekrani, qancha vaqt o'tkazilgani, mahsulot qaysi bo'limdan ochilgani, buyurtma qayerda to'xtab qolgani; reliz belgilari bilan oldin/keyin taqqoslash.\n"
    "• «💬 Izohlar»: mahsulot sharhlari, sayt bahosi va NPS bir joyda.\n"
    '\n'
    'Mijozlardan fikr eshitsangiz — yozing 🤝'
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
