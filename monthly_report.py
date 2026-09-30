"""
Oylik hisobot — kanalga bir martalik e'lon (2026-09-30, sentyabr).

Egasi matnni o'zi tasdiqladi. Raqamlar /admin statistikasidan olingan
(1–30 sentyabr): 165 ta sotuv (171 buyurtmadan 6 tasi bekor), top 7 —
tushum bo'yicha. Dona bo'yicha emas: aksiya sovg'asi (Oq kunjut) va
ulgurji kg bilan sanalgan unlar ro'yxatni buzardi.

Matn kanal tilida (kirill) qat'iy yozilgan — keyingi oy uchun TEXT ni
yangilash kifoya.

  /hisobot_test  — faqat so'ragan adminga
  /hisobot_kanal — kanalga
"""
import logging

from aiogram import Bot
from aiogram.enums import ParseMode

import news_announce
from config import REQUIRED_CHANNEL_ID

logger = logging.getLogger(__name__)

TEXT = (
    "📊 <b>Сентябрь ойи ҳисоботи</b>\n\n"
    "Ҳурматли <b>Кетошоп оиласи</b>! 💚\n\n"
    "Сентябрь ойида сизлар билан бирга <b>165 марта харид</b> амалга оширилди "
    "ва биз уларни сизларга етказиб бера олдик. Умид қиламизки, бу маҳсулотлар "
    "билан оилангиз ва яқинларингизни хурсанд қилдингиз, ўзингиз эса янада "
    "қувватга тўлдингиз. Ишончингиз ва бизни танлаганингиз учун катта раҳмат!\n\n"
    "🏆 <b>Ойнинг энг кўп сотилган 7 та маҳсулоти:</b>\n"
    "1. Бодом уни 1000 гр\n"
    "2. Эритритол 1000 гр\n"
    "3. Стевия 1000 гр\n"
    "4. Аллюлоза 1000 гр\n"
    "5. Тоза стевия 1000 гр\n"
    "6. Қизил гуруч (Девзира) 1000 гр\n"
    "7. Зайтун ёғи, Испания (5 л)\n\n"
    "🍂 <b>Октябрь ойида ҳам</b> Кетошоп сизлар учун энг хавфсиз ва соғлом "
    "маҳсулотларни етказиб беришга тайёр!\n\n"
    "Биз билан бўлганингиз учун раҳмат 🤝"
)


async def send_preview(bot: Bot, chat_id: int) -> None:
    await bot.send_message(chat_id, TEXT, parse_mode=ParseMode.HTML,
                           reply_markup=news_announce.channel_keyboard(),
                           disable_web_page_preview=True)


async def post_to_channel(bot: Bot) -> bool:
    if not REQUIRED_CHANNEL_ID:
        return False
    try:
        await bot.send_message(REQUIRED_CHANNEL_ID, TEXT, parse_mode=ParseMode.HTML,
                               reply_markup=news_announce.channel_keyboard(),
                               disable_web_page_preview=True)
        return True
    except Exception:
        logger.exception("Oylik hisobotni kanalga yuborib bo'lmadi")
        return False
