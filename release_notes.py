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

RELEASE_KEY = "2026-11-03-navigator-sovga-ai-narx"
TZ_OFFSET = timedelta(hours=5)
SEND_WINDOW = (8, 22)          # never wake admins at night
# True bypasses the daytime window (used 2026-09-25, and 2026-10-22 at 03:00
# when the owner said "hozir yubor"). Tied to this release's key, so the next
# release is back to daytime without anyone remembering to switch it off.
SEND_NOW = RELEASE_KEY == "2026-10-22-sayt-yangiliklari"
CHECK_EVERY = 300

NOTES = (
    "🆕 <b>Yangi: Yandex Navigator, sirli sovg'a eslatmasi va AI narxlari</b>\n"
    '\n'
    '🚚 <b>Kuryer paneli</b>\n'
    "1. Telefonda «🧭 Yo'l» yoki xaritani bossangiz, endi <b>sayt emas — Yandex ilovasi</b> ochiladi: avval <b>Yandex Navigator</b>, u bo'lmasa Yandex Maps; ikkalasi ham yo'q bo'lsa — «o'rnatish» tugmasi chiqadi. Yandex Go tashqaridan marshrut qabul qilmaydi.\n"
    '\n'
    "2. «🗺 Xarita» bo'limidagi marshrut tugmasi <b>barcha faol manzillarni bitta marshrut</b> qilib Navigatorda ochadi — sizga eng yaqinidan boshlab (joylashuvga ruxsat bering). Bitta buyurtmaning xaritasi — faqat o'sha manzilni.\n"
    '\n'
    "3. ⚠️ Yandex qoidasi: Navigator bitta telefonda kuniga taxminan <b>5 marta</b> tashqi havoladan marshrut ochadi. Ochilmay qolsa — «🗺 Yandex Maps'da ochish» tugmasini bosing.\n"
    '\n'
    "4. 🧪 <b>Test buyurtma</b>: admin saytida «Kuryer» → «🧪 Test buyurtma» (yoki botda /test_buyurtma) — «Yo'lda» turgan sinov kartasi: Amir Temur xiyoboni, 0 so'm, <b>tushumga kirmaydi</b>, «Yetkazildi» qilinmaydi. Sinab bo'lgach kartaning «⋯» → «🗑» bilan o'chiring.\n"
    '\n'
    '📦 <b>Buyurtmalar</b>\n'
    "5. 🎁 400 000 so'mdan yuqori buyurtmada «<b>SIRLI SOVG'A — qutiga soling</b>» eslatmasi endi <b>ochilgan buyurtma kartasida va holat kartalarida</b> ham turadi (avval faqat birinchi xabarda edi).\n"
    '\n'
    "6. Savat va buyurtma matnida miqdor «2.0 dona» emas, <b>«2 dona»</b>; sovg'a narxi «<s>15 000 so'm</s> → bepul» (avval «15 000 0» bo'lib, 150 000 deb o'qilardi).\n"
    '\n'
    "7. ✏️ Qo'lda kiritilgan (oflayn) buyurtmaning tarkibini ham «Tarkibni o'zgartirish» bilan tahrirlash mumkin — ombor o'zgarmaydi.\n"
    '\n'
    '🤖 <b>AI sotuvchi</b>\n'
    "8. AI endi narx va «Jami»ni <b>o'zi hisoblamaydi</b> — kod hisoblaydi va javobdagi har bir summa katalog bilan tekshiriladi. «Yashil grechka uni»ni 29 000 deb (bu — grechka <b>doni</b> narxi) yozib, jamini o'zi qo'shgan xato endi takrorlanmaydi: noto'g'ri summa mijozga ketmaydi.\n"
    '\n'
    "AI yoki Navigator bilan g'alati narsa ko'rsangiz — skrinshot yuboring.\n"
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
