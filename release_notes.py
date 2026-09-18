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

RELEASE_KEY = "2026-09-19-kuryer-tavsif-viloyat"
TZ_OFFSET = timedelta(hours=5)
SEND_WINDOW = (8, 22)          # never wake admins at night
# The owner asked for this release's notes to go out immediately (2026-09-19),
# so the daytime window is bypassed. Back to False for the next release.
SEND_NOW = True
CHECK_EVERY = 300

NOTES = (
    "🆕 <b>Bir kunda qo'shilganlar</b>\n\n"

    "🚚 <b>Kuryer paneli</b> — saytda yangi «Kuryer» bo'limi\n"
    "• Barcha buyurtma bir ekranda, ustunlar bo'ylab: Yangi → Qabul qilindi → "
    "Tayyor+Yo'lda → Yetkazildi → Bekor qilindi\n"
    "• Kartochkani ushlab surib yoki ◀ ▶ tugmalari bilan keyingi bosqichga o'tkaziladi\n"
    "• Kartochkada faqat keraklisi: kim, qayerga, qancha pul olish kerak, qancha kutmoqda. "
    "<b>Naqd</b> summa sariq fonda, oldindan to'langani xira — bir qarashda ko'rinadi\n"
    "• Mijoz lokatsiya yuborgan bo'lsa: xaritada ochish yoki pinni Telegramga yuborish "
    "(navigatorda ochiladi)\n"
    "• Har qadamda mijozga o'z tilida xabar ketadi; kartochkani orqaga surish jim\n"
    "• Ikki admin bir buyurtmani bir vaqtda surса, ikkinchisi ogohlantiriladi\n\n"

    "💸 <b>Kuryer haqi endi avtomatik chiqimga yoziladi</b>\n"
    "Toshkent ichida 25 000, viloyatga pochta orqali (BTS, EMU) 5 000 so'm — buyurtma "
    "yetkazilgan zahoti «Chiqimlar»ga tushadi. Bepul yetkazib berishda ham yoziladi: "
    "kuryerga baribir to'lanadi. Faqat bugundan keyingi buyurtmalardan.\n\n"

    "📝 <b>Barcha mahsulotga tavsif — uchala tilda</b>\n"
    "133 ta mahsulotning hammasiga o'zbekcha va ruscha tavsif yozildi, kirillcha "
    "avtomatik o'giriladi. Ruscha tanlagan mijozga endi ruscha chiqadi.\n"
    "Saytda: Mahsulotlar → «✍️ Tavsiflarni to'ldirish». Qo'lda tuzatish uchun JSON "
    "yuklab olish/yuklash ham bor, tahrirlash oynasida kirillchasi jonli ko'rinadi.\n\n"

    "🗺 <b>Dashboardda viloyatlar kesimi</b>\n"
    "Qaysi viloyat qancha buyurtma qilyapti, qancha pul olib kelyapti, nechta xaridori "
    "bor va o'rtacha cheki qancha. Qatorni ochsangiz — o'sha viloyat aynan nima "
    "olayotgani. Ombor rejasi uchun.\n\n"

    "🏆 <b>Do'kon bosh sahifasi endi yangilanib turadi</b>\n"
    "«Eng ko'p sotilganlar» butun tarix bo'yicha qotib qolgan edi — uchta mahsulot "
    "abadiy o'sha yerda turardi. Endi oxirgi 30 kunlik sotuvdan eng yaxshi 12 tasi "
    "olinadi va har kuni uchtasi ko'rsatiladi: to'rt kunda hammasi navbat bilan chiqadi.\n\n"

    "🌟 <b>Kun mahsuloti</b> — har kuni soat 13:00 da bitta mahsulot xaridorlarga va "
    "kanalga e'lon qilinadi. Navbat aylanma: hamma mahsulot o'z kunini oladi.\n"
    "Boshqarish: /kun_status · /kun_test · /kun_kanal · /kun_now · /kun_off\n\n"

    "🏢 <b>B2B savdolar ro'yxati</b>\n"
    "Optom tushum umumiy raqam ichida yashirin edi. Endi kim, qachon, nima olgani va "
    "foydasi ko'rinadi — botda «B2B Savdo → B2B savdolar», saytda esa Dashboardda.\n\n"

    "📈 <b>Foyda hisobidagi xato tuzatildi</b>\n"
    "Optom Eritritol sotuvi tannarxsiz («0 so'm») hisoblanardi — oylik foyda butun "
    "partiya miqdoricha oshib ko'rinardi. Endi to'g'ri hisoblanadi.\n\n"

    "📦 <b>Yetkazish</b>: Yandex Market tanlovdan olib tashlandi. Viloyatlarga "
    "faqat BTS va EMU qoldi.\n\n"

    "📞 <b>Aloqa raqami</b> yangilandi: +998993641343 — salom xabari, yordam matnlari, "
    "AI sotuvchi va keto maslahatlari, hammasida.\n\n"

    "🔤 <b>Kirillcha yozuvdagi xato tuzatildi</b>\n"
    "«чэк», «Чэхия», «печэне» kabi so'zlar noto'g'ri chiqardi — butun botning "
    "kirillcha matniga tegishli edi.\n\n"

    "🌐 Botdagi «Boshqaruv paneli» va «Mahsulot va Buyurtma» menyularidan endi "
    "to'g'ridan-to'g'ri saytga o'tish tugmasi bor.\n\n"

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
