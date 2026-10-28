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

RELEASE_KEY = "2026-10-28-mahsulot-tarkibi"
TZ_OFFSET = timedelta(hours=5)
SEND_WINDOW = (8, 22)          # never wake admins at night
# True bypasses the daytime window (used 2026-09-25, and 2026-10-22 at 03:00
# when the owner said "hozir yubor"). Tied to this release's key, so the next
# release is back to daytime without anyone remembering to switch it off.
SEND_NOW = RELEASE_KEY == "2026-10-22-sayt-yangiliklari"
CHECK_EVERY = 300

NOTES = (
    '🆕 <b>Yangi: har bir mahsulotda «🧾 Tarkibi»</b>\n'
    '\n'
    "1. Botdagi mahsulot kartochkasida va saytdagi mahsulot oynasida tavsif ostida endi <b>«🧾 Tarkibi»</b> chiqadi — mijozning o'z tilida (lotin, kirill, rus).\n"
    '\n'
    "2. <b>111 ta mahsulotning tarkibi avtomatik yozildi</b> — bitta xomashyodan iborat mahsulotlar: unlar, urug'lar, eritritol, alluloza, toza steviya, himolay tuzi, Extra Virgin yog'lar, GHEE, asal va h.k. (masalan, «Maydalangan bodom mag'zi — 100%»). Shunday yangi mahsulot qo'shilsa, unga ham bir soat ichida o'zi yoziladi.\n"
    '\n'
    "3. ✍️ <b>Sizdan iltimos — quyidagilarning tarkibini qadoqdagi yorliqdan ko'chirib kiriting.</b> Ular ataylab bo'sh qoldirilgan: tarkibni taxmin qilsak, allergen yashirinib qolishi mumkin.\n"
    '• Победа shokoladlari, qora shokolad granula\n'
    '• Losos tushonkasi, kokos slivka, kokos chipsi\n'
    '• Stevia 200g, 500g va 1000g\n'
    '• Makaronlar: Barilla, kepakli, grechkali, ismaloqli\n'
    "• Xandonpista va yeryong'oq pastalari\n"
    "• Zakvaska, oq solod, qovurish uchun zaytun yog'i, Keto set\n"
    '\n'
    "4. <b>Qanday kiritiladi:</b> botda mahsulot → ✏️ Tahrirlash → «🧾 Tarkib» → tarkibni yozing. Ruschasi avtomatik tarjima bo'ladi, kerak bo'lsa «🇷🇺 Tarkib (rus)» bilan tuzatasiz. «-» yuborsangiz, tarkib o'chadi. Admin saytida — mahsulot formasidagi «Tarkibi (UZ/RU)» maydonlari.\n"
    '\n'
    "5. Saqlangan zahoti do'kon va katalogda ko'rinadi. Avtomatik yozilganlardan qadoqdagidan farq qiladiganini ko'rsangiz (masalan, tuzlangan pista) — o'sha tugma bilan tuzating.\n"
    '\n'
    '6. AI sotuvchi ham endi tarkibni biladi; tarkibi kiritilmagan mahsulot haqida taxmin qilmaydi.\n'
    '\n'
    'Rahmat 🤝'
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
