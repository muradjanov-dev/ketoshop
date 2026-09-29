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

RELEASE_KEY = "2026-09-29-olx-bloger"
TZ_OFFSET = timedelta(hours=5)
SEND_WINDOW = (8, 22)          # never wake admins at night
# True bypasses the daytime window (used once, 2026-09-25). Normal releases
# keep it False so admins are never messaged at night.
SEND_NOW = False
CHECK_EVERY = 300

NOTES = "🆕 <b>OLX va blogerlar — yangiliklar</b>\n\n🟢 <b>Mahsulotlar OLX'ga chiqyapti</b>\nEndi mahsulotlarimiz OLX.uz'ga rasmi, narxi va o'zbekcha + ruscha tavsifi bilan avtomatik joylanadi. Qo'lda hech narsa yuklash shart emas — tizim o'zi saytdan oladi va to'ldiradi.\n\nHozir 5 ta e'lon OLX moderatsiyasida (tasdiqlangach havolalar ochiladi):\n1. <a href=\"https://www.olx.uz/d/66246838/\">Koritsa 70g</a>\n2. <a href=\"https://www.olx.uz/d/66246907/\">Qora shokolad granula 500g</a>\n3. <a href=\"https://www.olx.uz/d/66246925/\">Qora shokolad granula 300g</a>\n4. <a href=\"https://www.olx.uz/d/66246935/\">Kokos chipsi 100g</a>\n5. <a href=\"https://www.olx.uz/d/66246962/\">Kokos slivka 400ml</a>\n\n⚠️ <b>OLX limiti</b>\nOLX oziq-ovqat bo'limida 30 kunda faqat 5 ta bepul e'lon beradi. Qolgan 93 ta mahsulot uchun «Premium — 100 e'lon» paketi kerak: 442 000 so'm, 30 kunga (bitta e'lon ≈ 4 420 so'm). Paket olinishi bilan hammasi avtomatik joylanadi.\n\n🚫 E'lonlarga Telegram havolasi qo'yilmaydi — OLX buni taqiqlaydi, e'lon o'chiriladi. Telefon raqamimiz har bir e'londa bor.\n\n📢 <b>Blogerlar dasturi — eslatma</b>\nBloger ulushi <b>tushumdan emas, foydadan</b>: har bir olib kelgan mijozining dastlabki <b>10 ta yetkazilgan</b> buyurtmasi foydasining <b>10%</b>i. Pul Keto balansiga tushadi (1 Keto = 1 so'm). Blogerlar o'z kabinetini «👤 Kabinetim» → «📢 Bloger kabinetim» tugmasidan ochadi.\nBlogerlarga yuboriladigan tushuntirish matni (kirill, misollar bilan) tayyor — kerak bo'lsa so'rang."


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
