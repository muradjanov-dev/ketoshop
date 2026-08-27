import asyncio
import os
import sys

# Ensure this is run from the project root
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from aiogram import Bot
from config import BOT_TOKEN, ADMIN_IDS
import database

async def broadcast_updates():
    bot = Bot(token=BOT_TOKEN)
    message_text = (
        "🚀 <b>Tizimdagi So'nggi Yangilanishlar (24 soat ichida):</b>\n\n"
        "<b>1. Admin Panel 4 bo'limga ajratildi:</b> Juda ko'p bo'lib ketgan tugmalar endi 4 ta guruhga bo'lindi va ixchamlashdi.\n"
        "<b>2. Yangi To'plam qo'shish imkoniyati:</b> Admin panel orqali to'g'ridan-to'g'ri yangi to'plam (Set) va ularga alohida narx kiritish yo'lga qo'yildi.\n"
        "<b>3. Kuryer tizimi super-qulaylashtirildi:</b> Kuryerlar har bir buyurtmaga alohida kirmasdan, bitta xabarning o'zidayoq buyurtmalarni varaqlab ('⬅️' '➡️') qabul qilishlari va yetkazishlari mumkin.\n"
        "<b>4. Mijozlarga javob qaytarish xatosi tuzatildi:</b> Botga yozgan mijozlarga adminlar 'Javob berish' tugmasi orqali yozganda, xabar o'ziga qaytib qolish xatosi to'liq bartaraf etildi.\n"
        "<b>5. B2B Savdo menyusi:</b> Barcha ulgurji (B2B va Eritritol) savdolar bitta bo'lim ichiga yig'ildi.\n"
        "<b>6. Dashboard (Web panel):</b> Narxlarda yuzaga kelayotgan 'so'm so'm' degan takrorlanish (bug) bartaraf etildi.\n\n"
        "Barcha yangilanishlar muvaffaqiyatli serverga yuklandi (Deploy qilindi) va ishga tushdi! 🎉"
    )
    
    all_admins = set(ADMIN_IDS)
    
    for admin_id in all_admins:
        try:
            await bot.send_message(
                admin_id, 
                message_text, 
                parse_mode="HTML"
            )
            print(f"Sent update to {admin_id}")
        except Exception as e:
            print(f"Failed to send to {admin_id}: {e}")
            
    await bot.session.close()

if __name__ == "__main__":
    asyncio.run(broadcast_updates())
