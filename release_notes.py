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

RELEASE_KEY = "2026-11-01-navigatsiya-marshrut"
TZ_OFFSET = timedelta(hours=5)
SEND_WINDOW = (8, 22)          # never wake admins at night
# True bypasses the daytime window (used 2026-09-25, and 2026-10-22 at 03:00
# when the owner said "hozir yubor"). Tied to this release's key, so the next
# release is back to daytime without anyone remembering to switch it off.
SEND_NOW = RELEASE_KEY == "2026-10-22-sayt-yangiliklari"
CHECK_EVERY = 300

NOTES = (
    "🆕 <b>Yangi: buyurtmalarda oson navigatsiya va kuryer uchun marshrut</b>\n"
    '\n'
    '📦 <b>Botda — «Buyurtmalar»</b>\n'
    "1. Filtrdan (masalan «Yo'lda») buyurtmani ochsangiz, «◀️ Orqaga» endi <b>o'sha ro'yxatning o'sha sahifasiga</b> qaytaradi — «Buyurtmalar»ga boshidan kirish shart emas.\n"
    '\n'
    "2. Qabul qilish, Yo'lga chiqarish, Yetkazildi, Rad etish yoki o'chirishdan keyin ham o'sha ro'yxat ochiladi, natija qisqa xabar bo'lib chiqadi — keyingi buyurtmaga darhol o'tasiz.\n"
    '\n'
    "3. ✏️ <b>Tarkibni o'zgartirish</b>da ekranda doim bitta oyna qoladi: mahsulot qo'shsangiz yoki son yozsangiz, eski oyna va yordamchi xabarlar o'chadi. 💾 Saqlash yoki Bekor qilish — to'g'ri <b>buyurtmaning o'ziga</b> qaytaradi; saqlangandan keyin birinchi tugma «📨 Mijozga xabar berish».\n"
    '\n'
    "4. Mijozga xabar yuborgach «📦 Buyurtmaga qaytish» tugmasi chiqadi. Buyurtma ostidagi 📍 lokatsiya va chek siz undan chiqqanda o'chadi — chat toza qoladi.\n"
    '\n'
    '🚚 <b>Kuryer paneli</b>\n'
    "5. Buyurtmadagi «🧭 Yo'l», buyurtma oynasidagi kichik xarita va xaritadagi pin endi Yandex'ni <b>yo'l ko'rsatish rejimida</b> ochadi — sizning joyingizdan o'sha manzilgacha.\n"
    '\n'
    "6. «🗺 Xarita» bo'limida yangi <b>«🧭 Marshrut»</b>: tayyor va yo'ldagi hamma buyurtmalar raqamlanib, xaritada chiziq bilan ko'rinadi (olib ketish, Yandex Taxi/Market, BTS, EMU va UzPost kirmaydi).\n"
    '\n'
    "7. <b>Birinchi qayerga borishni o'zingiz tanlaysiz:</b> ▲ ▼ — tartibni o'zgartiradi, ✕ — bu safar bormaysiz (pastdagi «＋» bilan qaytarasiz), ↺ — avtomatik tartib: eng uzoq kutgandan boshlab, keyin har doim eng yaqini. Tartib telefoningizda saqlanadi.\n"
    '\n'
    "8. «🧭 Yandex'da yo'lga chiqish» — hamma manzilni shu tartibda bitta marshrut qilib Yandex'da ochadi (10 tadan ko'p bo'lsa — «1–10», «11–…» bo'laklarga).\n"
    '\n'
    "Kuryerlardan iltimos: birinchi marshrutni ochib ko'ring — Yandex to'g'ri ochilmasa yoki tartib noto'g'ri chiqsa, xabar bering.\n"
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
