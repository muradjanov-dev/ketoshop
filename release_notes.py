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

RELEASE_KEY = "2026-10-24-uzpost-fikr-dashboard"
TZ_OFFSET = timedelta(hours=5)
SEND_WINDOW = (8, 22)          # never wake admins at night
# True bypasses the daytime window (used 2026-09-25, and 2026-10-22 at 03:00
# when the owner said "hozir yubor"). Tied to this release's key, so the next
# release is back to daytime without anyone remembering to switch it off.
SEND_NOW = RELEASE_KEY == "2026-10-22-sayt-yangiliklari"
CHECK_EVERY = 300

NOTES = (
    "🆕 <b>Bugun (24 oktabr) nimalar qo'shildi</b>\n"
    '\n'
    "1. <b>📮 Viloyatlarga UzPost «Bir Qadam»</b> — viloyatdagi mijoz botda va saytda birinchi bo'lib «📮 UzPost — 1 kunda, ~21 000 so'm» ni ko'radi. Narx og'irlik bo'yicha o'zi hisoblanadi va jami summaga qo'shiladi: birinchi kg 18 000 so'm, har keyingi kg +3 000 (Qoraqalpog'iston, Xorazm, Surxondaryo: +7 000). BTS va EMU ham avvalgidek qoladi.\n"
    '\n'
    "2. <b>📮 Eng yaqin pochta bo'limi</b> — UzPost tanlanganda bot mijozning lokatsiyasiga eng yaqin «Bir Qadam» bo'limini topadi va mijozga indeks, manzil, ish vaqti, xaritani ko'rsatadi. Buyurtma kartochkasida «📮 UzPost «Bir Qadam» → indeks — bo'lim, manzil» va taxminiy og'irlik turadi — posilkaga shu indeksni yozing. «bo'limni admin aniqlaydi» deb chiqsa, mijozga yozib aniqlang.\n"
    '\n'
    "3. <b>💬 Fikr so'rovi</b> — buyurtmasi yetkazilgan har bir xaridorga «Mahsulotlarimiz sizga ma'qul keldimi?» xabari ketdi. Yozilgan har bir sharh sizga shu yerga keladi. Umumiy fikrlar «Xabarlar»ga «💬 Fikr so'roviga javob» belgisi bilan tushadi — iltimos, javob bering. Bu xaridorlar uchun AI sotuvchi 48 soat jim turadi.\n"
    '\n'
    "4. <b>📦 Dashboard: Mahsulot savdosi</b> — admin saytida har bir mahsulot bo'yicha soni, tushum, foyda, marja, qoldiq va «necha kunga yetadi» (qizil — 7 kundan kam). «⬇️ Excel» tugmasi tanlangan davr ro'yxatini yuklab beradi.\n"
    '\n'
    "5. <b>📈 Dashboard: o'tgan davrga solishtirish</b> — har bir asosiy ko'rsatkich yonida ▲/▼ foiz (oldingi shuncha kunga nisbatan) va kunlar bo'yicha buyurtmalar grafigi.\n"
    '\n'
    "6. <b>📋 Uzun ro'yxatlar qisqa</b> — ABC, mahsulot savdosi, viloyatlar va B2B ro'yxatlari qisqa ko'rinadi, «▼ Yana N ta ko'rsatish» bilan ochiladi.\n"
    '\n'
    "7. <b>🎶 Saytda klassik musiqa</b> — qushlar ostida mashhur klassik asarlar (Bax, Paxelbel, Betxoven) yengil chalinadi. 🎶 tugmasi o'chiradi, qayta yoqilganda keyingi asar boshlanadi. Buyurtma rasmiylashtirilayotganda musiqa to'xtaydi.\n"
    '\n'
    "8. <b>🙂 «Saytimiz sizga qulaymi?» endi qayta-qayta so'ramaydi</b> — javob bergan mijozdan boshqa so'ralmaydi, ko'pi bilan 2 marta va 30 kun oralig'ida; adminlardan umuman so'ralmaydi.\n"
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
