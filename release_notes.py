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

RELEASE_KEY = "2026-10-13-oktyabr-2-yangiliklari"
TZ_OFFSET = timedelta(hours=5)
SEND_WINDOW = (8, 22)          # never wake admins at night
# True bypasses the daytime window (used once, 2026-09-25). Normal releases
# keep it False so admins are never messaged at night.
SEND_NOW = False
CHECK_EVERY = 300

NOTES = "🆕 <b>2-oktabrdan beri botga nimalar qo'shildi</b>\n\n🤖 <b>AI sotuvchi</b> — botda mijozlarga va kanal guruhida\n• Mijozga o'zi javob beradi: mahsulot tanlaydi, narxini aytadi, «Yana nima olamiz?» deb so'raydi, yetkazish usullarini narxi bilan taklif qiladi va buyurtmani rasmiylashtiradi. To'lovni siz tasdiqlaysiz.\n• Har bir mijoz suhbati «Mijoz va Ai suhbati» mavzusida bitta xabarda (mavzu ichida /ai_mavzu). AI sotsa — 🎉 tantanali xabar.\n• Har kuni 23:58 da — AI sarfi ($ va so'm) va AI sotuvlari.\n• Mijozni eslaydi: qiziqishi, fikri, buyurtmalari. Retsept — bitta mahsulotga 24 soatda bittadan.\n• Siz mijozga javob yozsangiz, AI unga 6 soat jim turadi. Guruhda adminlarga javob bermaydi.\n• Holat, yoqish/o'chirish va model: /ai_holat · kalit: /ai_kalit · AI bilmagan savollar: /ai_bilim\n\n🎁 <b>Chegirma va sovg'alar</b>\n• Bot orqali o'zi buyurtma berganga 10% chegirma — 14-oktabr 23:59 gacha. Tannarxdan arzonga tushmaydi, har kartochkada chegirmali narx (botda va saytda).\n• Har bir yangi foydalanuvchiga 100 Keto tangacha — tantanali, o'z tilida.\n• 🎁 «Bepul xarid qilish»: do'st taklif qilsa, uning birinchi xaridining 3% i Keto bo'lib tushadi.\n• Aksiyada bosqichli sovg'a: miqdorga qarab bitta sovg'a (masalan, Steviya: 1 kg+ → 200 g, 2 kg+ → 500 g, 4 kg+ → 2 kg).\n\n🛒 <b>Buyurtma va sayt</b>\n• Do'kondan olib ketish (bot va Mini App) — admin panelda yoqiladi.\n• Saytda retseptlar: har 2 kunda yangi, «Barcha masalliqlarni savatga».\n• Saytdan buyurtmada to'lov cheki endi har doim yetib boradi; setlar rasmi tuzatildi; mahsulot oynasida katta «← Orqaga».\n• «Qanday buyurtma beriladi» video qo'llanmasi — Marketing → 🎬 Video qo'llanma.\n\n📦 <b>Ombor</b>\n• Kam qolgan / tugagan mahsulotlar xodimlar guruhiga, har kuni 23:59 da to'liq holat.\n\n📣 <b>Reklama va kanal</b>\n• /reklama: sotuvga ta'siri, videolar va mahsulotlar. Meta tokeni — /reklama_token.\n• Kanalga eng ko'p sotilgan 70 ta mahsulot posti.\n\n👥 <b>Guruh va kuryer</b>\n• Guruhda bot menyusi, tugmalari va buyruqlari chiqmaydi; «qo'shildi» xabarlari o'chiriladi.\n• Kuryer doskasida ustunlar orasida surishsiz yurish.\n• Mijozlarga eslatmalar — ismsiz va bosimsiz.\n\nSavol yoki taklif bo'lsa — yozing 🤝"


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
