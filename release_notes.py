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

RELEASE_KEY = "2026-09-17-qayta-sotuv-keto-yetkazish"
TZ_OFFSET = timedelta(hours=5)
SEND_WINDOW = (8, 22)          # never wake admins at night
# This release was deployed at night, so it waits for 08:00 — set True only
# when the owner asks for notes to go out right away.
SEND_NOW = False
CHECK_EVERY = 300

NOTES = (
    "🆕 <b>Oxirgi yangiliklardan keyin qo'shilganlar</b>\n\n"

    "🚚 <b>Bepul yetkazib berish</b>\n"
    "Toshkent bo'ylab Ketoshop kuryeri <b>800 000 so'm va undan yuqori</b> "
    "buyurtmaga bepul (botda ham, Mini App'da ham). Savatda «yana X so'm — bepul» "
    "eslatmasi chiqadi.\n\n"

    "🔁 <b>Qayta sotuv xabarlari</b> — har kuni 09:30\n"
    "• «Kokos unini 26 kun oldin olgan edingiz — tugab qolmadimi?» + bir tugmada qayta buyurtma\n"
    "• 2-buyurtmaga sovg'a: 1-buyurtmadan 3 kun keyin, 14 kun amal qiladi\n"
    "• 30 / 60 / 90 kun kelmagan mijozga «sog'indik» (60 va 90 da sovg'a bilan)\n"
    "• Mijozga 7 kunda ko'pi bilan 1 ta; o'sha kuni boshqa tavsiya xabari bormaydi\n"
    "• Natija: /qaytarish · ko'rish: /qaytarish_test\n\n"

    "🎁 <b>Shaxsiy sovg'a</b> — Eritritol 100 gr, summa shart emas. "
    "Bitta buyurtmaga faqat bitta sovg'a (aksiya sovg'asi bilan qo'shilmaydi).\n\n"

    "🥑 <b>Keto tangachalar</b>\n"
    "• Keshbek darajaga qarab: Bronza 0.5% · Kumush 1% · Oltin 2% · Olmos 3%\n"
    "• Yangi darajaga chiqqanga 30 kunlik sovg'a\n"
    "• Mahsulot, savat va Mini App'da «🥑 +N Keto» belgisi\n"
    "• <b>18.09 soat 17:30</b> da hammaga sodda tushuntirish ketadi va "
    "tangachalarni sarflash yoqiladi (1 Keto = 1 so'm). Ko'rish: /keto_tushuntirish\n"
    "• Tuzatildi: yetkazilgan buyurtmadan keyin Keto tabrik xabari kelmay qolardi\n\n"

    "🧺 <b>«Siz olgan X bilan boshqalar Y ham olishyapti»</b> tavsiyasi — "
    "tugmalar bilan, yetkazilgan buyurtma xabarida. Buyurtmalarim'da «🔁 takrorlash» tugmasi.\n\n"

    "🌐 <b>Til</b>\n"
    "Keto maslahatlari endi kirillchilarga kirillda, ruslarga ruscha boradi; "
    "Keto va aksiya xabarlari ham har kimning o'z tilida.\n\n"

    "🛡 <b>Guruh</b>: havola o'chirilganda «Iltimos, guruhda havola tarqatmang…» "
    "deb muloyim yoziladi.\n\n"

    "📊 <b>Foyda va maqsadlar tuzatildi</b>\n"
    "• Dollar kursi har kuni Markaziy bankdan olinadi (bugun 11 797 so'm; oldin 12 800 turgan edi)\n"
    "• To'plam (set) mahsulotlar tannarxi 0 hisoblanib, foyda oshib ko'rinardi — tuzatildi "
    "(sayt Dashboard, Maqsadlar, Excel hisobot)\n"
    "• Tushum va foyda endi buyurtma <b>yetkazilgan kuni</b> bo'yicha — «bugungi foyda» "
    "endi to'g'ri chiqadi\n"
    "• Tannarxi kiritilmagan mahsulot sotilsa, maqsad xabarida ogohlantirish chiqadi\n\n"

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
