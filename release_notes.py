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

RELEASE_KEY = "2026-10-17-oktyabr-3-yangiliklari"
TZ_OFFSET = timedelta(hours=5)
SEND_WINDOW = (8, 22)          # never wake admins at night
# True bypasses the daytime window (used once, 2026-09-25). Normal releases
# keep it False so admins are never messaged at night.
SEND_NOW = False
CHECK_EVERY = 300

NOTES = (
    "🆕 <b>13-oktabrdan beri botda nimalar o'zgardi</b>\n"
    '\n'
    '🤖 <b>AI sotuvchi</b>\n'
    "• Buyurtmani endi tugmali checkout kartasi tuzadi: jami, chegirma, Keto va yetkazish narxini kod hisoblaydi. AI summani o'zi yozmaydi, manzil va raqamni to'qimaydi. Mijoz «✅ Tasdiqlash» ni bosadi yoki «ha» deb yozadi.\n"
    '• Qadamlar qisqardi: qanday olasiz → raqam va lokatsiya → uy/xonadon → karta (avval ~10 ta savol edi).\n'
    "• Karta bilan to'lovda buyurtma chek kelgach tuziladi — sizga to'lanmagan buyurtma kelmaydi.\n"
    '• Ruscha yozganga ruscha, kirillda yozganga kirillda javob beradi; ism bilan murojaat qilmaydi, «Sizga rahmat» deydi.\n'
    "• Mavzudan tashqari savollarga (she'r, uy vazifasi, kod, siyosat, sport, ob-havo) javob bermaydi — muloyim rad etib, mahsulotga qaytaradi.\n"
    '• Siz «↩️ Javob berish» bilan yozayotganingizda AI aralashmaydi. Chek har doim qabul qilinadi. /ai_hisobot — AI kim bilan va qaysi mavzularda gaplashgani.\n'
    '\n'
    '🛒 <b>Savat va buyurtma</b>\n'
    '• Savat broni: savatga solingan mahsulot 6 soat shu mijozniki — oxirgi donani ikki kishi talashmaydi. 3 soatda «HH:MM gacha band» ogohlantirishi, 6 soatda mahsulot sotuvga qaytadi.\n'
    '• /bron — kimning savatida nima band; «⏱ Hozirgi bronlarni 1 soatga qisqartirish» tugmasi.\n'
    "• Band yoki tugagan mahsulotni so'ragan mijozga u qaytishi bilan «Siz so'ragan mahsulot qaytdi» xabari boradi — mahsulotni siz qo'shsangiz ham.\n"
    "• Har bir buyurtma holati xabarida va kuryer panelida to'liq mijoz bloki va Yandex havolasi.\n"
    '• Kuryer tabida «🗺 Xarita» — barcha faol buyurtmalar bitta xaritada.\n'
    '\n'
    "🏪 <b>Sayt va do'kon</b>\n"
    '• Sayt faqat botda START bosganlarga ochiladi — buyurtma holati va chek javoblari mijozga yetib boradi.\n'
    "• Tugagan mahsulot do'konda qoladi: «Yo'lda 🚚», «⏳ Tez orada qaytadi» va «🔔 Kelganda xabar bering».\n"
    "• Tillar aralashmaydi (aksiya, birlik, set nomlari kirill va ruscha). Mahsulot rasmi va to'liq tavsifi botda ham chiqadi.\n"
    '• Saytda 1 daqiqadan keyin «Saytimiz sizga qulaymi?» — 5 yulduz va izoh sizga keladi.\n'
    '• Admin saytida mahsulotning sotuv turi (oddiy / faqat B2B) tanlanadi va tahrirlanadi.\n'
    '\n'
    '🍳 <b>Retsept va kontent</b>\n'
    "• Kun mahsuloti kartochkasi ichida to'liq «🍳 Bugungi retsept».\n"
    "• Saytga 10 ta yangi retsept (05.11 gacha), har biri kanalda havola bilan e'lon qilinadi. 80 ta retsept va 50 ta postda miqdorlar va qadamlar to'ldirildi.\n"
    "• Yangi mijozga video qo'llanmadan keyin bugungi retsept rasmi bilan boradi.\n"
    "• Har 2 kunda 20:00 da «🧠 Keto savol» — sayt o'yinlaridan; o'yinlarda 50 ta savol.\n"
    '\n'
    '⭐ <b>Sharhlar</b>\n'
    "• 1–2★ qo'yib izoh yozmagan mijozdan sababi muloyim so'raladi, javobi sizga keladi.\n"
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
