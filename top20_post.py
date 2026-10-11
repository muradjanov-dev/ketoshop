"""
Kanalga bir martalik post — Ketoshopning eng ko'p sotilgan 70 ta mahsuloti
(owner, 2026-10-04: "shu kungacha sotilgan top 20 ta mahsulotni soni bilan
kanalga yubor bot orqali, inline buttonsiz" → text approved, then "top 70 ta" →
"ha yubor").

Numbers, all time up to 2026-10-04, from /admin statistics: every
non-cancelled order (retail, admin-entered and B2B — owner: "b2b dagi
savdoni ham qo'shaver"), minus free lines (aksiya bonus, campaign gift).
The archived "Jo'xori uni" is left out — it can't be bought any more.

Sent once, right after the deploy that ships it: the key is claimed in
release_notes_sent before sending, so a restart never posts it twice, and a
failed send gives the key back and retries a few times.
"""
import asyncio
import logging

from aiogram import Bot
from aiogram.enums import ParseMode

import database
from config import ADMIN_IDS, REQUIRED_CHANNEL_ID

logger = logging.getLogger(__name__)

KEY = "channel-top70-2026-10-04"
RETRIES = 6
RETRY_EVERY = 300

TEXT = (
    "🏆 <b>Кетошопнинг энг кўп сотилган 70 та маҳсулоти</b>\n\n"
    "Бугунгача сизлар энг кўп танлаган маҳсулотлар:\n"
    "1. Кепакли буғдой уни — 414 та\n"
    "2. Кепак (ўртача катталикда) — 343 та\n"
    "3. Арпа уни — 235 та\n"
    "4. Жавдар уни — 179 та\n"
    "5. Қизил гуруч (Девзира) 1000 гр — 178 та\n"
    "6. Бодом уни 1000 гр — 176 та\n"
    "7. Ҳималай тузи 1000 гр — 105 та\n"
    "8. Эритритол 1000 гр — 104 та\n"
    "9. Псиллиум уни 300 гр — 66 та\n"
    "10. Овсянка уни — 64 та\n"
    "11. Басмати гуруч (майда, оқ) 1000 гр — 53 та\n"
    "12. Кокос уни 1000 гр — 47 та\n"
    "13. Булгур гуручи 1000 гр — 47 та\n"
    "14. Зайтун ёғи (совуқ сиқим, Extra virgin) — 46 та\n"
    "15. Қора ферментланган солод 1 кг — 45 та\n"
    "16. Писта мағзи 500 гр — 45 та\n"
    "17. Бодом уни 500 гр — 44 та\n"
    "18. 2-нав ун — 43 та\n"
    "19. Ксантан камеди 100 гр — 42 та\n"
    "20. Ксантан камеди 500 гр — 38 та\n"
    "21. Стевия 200 гр — 37 та\n"
    "22. Псиллиум шелуха 150 гр — 33 та\n"
    "23. Стевия 1000 гр — 33 та\n"
    "24. Ксантан камеди 200 гр — 33 та\n"
    "25. Зайтун ёғи (қовуриш учун) 1000 мл — 30 та\n"
    "26. Кокос уни 500 гр — 30 та\n"
    "27. Гуруч уни — 30 та\n"
    "28. Аллюлоза 1000 гр — 29 та\n"
    "29. Табиий GHEE 1000 мл — 29 та\n"
    "30. Басмати гуруч Premium Besta 900 гр — 29 та\n"
    "31. Олма сиркаси (Тошкент) 250 гр — 29 та\n"
    "32. Эритритол 100 гр — 28 та\n"
    "33. Эритритол 500 гр — 26 та\n"
    "34. Аллюлоза 200 гр — 25 та\n"
    "35. Маккажўхори уни — 25 та\n"
    "36. Какао нибс 200 гр — 21 та\n"
    "37. Табиий ҳамиртуруш (закваска) — 21 та\n"
    "38. Ҳималай тузи 500 гр — 20 та\n"
    "39. Ерёнғоқ пастаси 200 гр — 19 та\n"
    "40. Нўхат уни — 19 та\n"
    "41. Тоза стевия 20 гр — 18 та\n"
    "42. Кокос шакари 250 гр — 18 та\n"
    "43. Кокос қириндиси 200 гр — 18 та\n"
    "44. Қора кунжут 300 гр — 17 та\n"
    "45. Зиғир уруғлари 600 гр — 16 та\n"
    "46. Бодом уни 200 гр — 16 та\n"
    "47. Зиғир уни 1000 гр — 16 та\n"
    "48. Кокос уни 200 гр — 16 та\n"
    "49. Оқ зиғир уни 1000 гр — 15 та\n"
    "50. Полба уни — 15 та\n"
    "51. Оқ кунжут 600 гр — 14 та\n"
    "52. Хандонписта пастаси 200 гр — 13 та\n"
    "53. Қовоқ уруғи 200 гр — 13 та\n"
    "54. Яшил гречка дони 1000 гр — 13 та\n"
    "55. Қизил гуруч (Девзира) 500 гр — 13 та\n"
    "56. Гречка уни — 13 та\n"
    "57. Оқ кунжут 300 гр — 13 та\n"
    "58. Зайтун ёғи Испания (5 л, қовуриш учун) — 12 та\n"
    "59. Зомин тоғ асали 700 гр — 12 та\n"
    "60. Аллюлоза + Стевия 200 гр — 12 та\n"
    "61. Чиа уруғи 600 гр — 10 та\n"
    "62. Кето музқаймоқ (Авокадо + Банан) — 10 та\n"
    "63. Қора седана 200 гр — 10 та\n"
    "64. Уй куви сарёғи 800 гр — 9 та\n"
    "65. Яшил гречка уни 1000 гр — 9 та\n"
    "66. Чиа уруғи 300 гр — 9 та\n"
    "67. Тоза стевия 50 гр — 8 та\n"
    "68. Кето музқаймоқ (Шоколад, какао) — 8 та\n"
    "69. Қора кунжут 600 гр — 8 та\n"
    "70. Лосос балиқ тушонкаси 1 л — 7 та\n\n"
    "Соғлом овқатланиш йўлида одамларга соғлом маҳсулотларни етказишда давом этамиз 🌿\n\n"
    "@ketoshop_uz — Сизнинг кето дўконингиз 💚"
)


async def post(bot: Bot) -> bool:
    if not REQUIRED_CHANNEL_ID:
        return False
    try:
        # No reply_markup — the owner asked for no inline buttons.
        import bot_discount
        text = TEXT + await bot_discount.channel_footer()
        await bot.send_message(REQUIRED_CHANNEL_ID, text if len(text) <= 4096 else TEXT,
                               parse_mode=ParseMode.HTML, disable_web_page_preview=True)
        return True
    except Exception:
        logger.exception("Top-70 kanal posti yuborilmadi")
        return False


async def _tell_admins(bot: Bot, text: str) -> None:
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception:
            pass


async def scheduler_loop(bot: Bot) -> None:
    await asyncio.sleep(20)          # let startup (DB, commands) settle first
    for _ in range(RETRIES):
        try:
            if not await database.claim_release_notes(KEY):
                return               # already posted
            if await post(bot):
                await _tell_admins(bot, "📣 <b>Kanalga yuborildi:</b> «Кетошопнинг энг кўп сотилган "
                                        "70 та маҳсулоти» (tugmasiz).")
                return
            await database.release_release_notes(KEY)
        except Exception:
            logger.exception("Top-70 post loop failed")
        await asyncio.sleep(RETRY_EVERY)
    await _tell_admins(bot, "⚠️ Top-70 postini kanalga yuborib bo'lmadi — bot kanalda admin ekanini tekshiring.")
