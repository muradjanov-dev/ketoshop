"""
One-off announcement of new admin-panel sections, sent to every admin.

Run it by hand after a deploy that adds something admins have to go and find:
    railway run python broadcast_updates_script.py     (or locally with DATABASE_URL set)

Reads the roster from config.ADMIN_IDS *plus* the runtime admins in the DB —
the hardcoded list alone would miss everyone added through the bot's own
"Yangi admin qo'shish" flow, which is most of them by now. Admins who have
never opened the bot cannot be messaged at all; they are reported at the end
rather than silently counted as delivered.

Edit MESSAGE below before each run.
"""
import asyncio
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from aiogram import Bot

from config import BOT_TOKEN, ADMIN_IDS
import database

MESSAGE = (
    "🆕 <b>Admin panelga yangi bo'limlar qo'shildi</b>\n\n"

    "🎯 <b>Maqsadlar</b> — <i>Statistika va Hisobot → 🎯 Maqsadlar</i>\n"
    "Kunlik <b>10 ta sotuv</b> va oylik <b>$2 000 sof foyda</b> maqsadi. "
    "Har kuni soat <b>13:00</b> va <b>20:00</b> da holat va qancha qolgani haqida "
    "eslatma keladi. Ekranda oxirgi 14 kun tarixi bor. "
    "Kunlik son, oylik summa va dollar kursini ⚙️ tugmasidan o'zgartirasiz.\n\n"

    "👥 <b>Adminlar ro'yxati</b> — <i>Foydalanuvchilar → 👥 Adminlar ro'yxati</i>\n"
    "Kim admin ekani, kim qo'shgani va har biri nechta mijoz savoliga javob "
    "bergani ko'rinadi. Botni ochmagan adminlar alohida ogohlantiriladi — "
    "ularga bot hech narsa yubora olmaydi.\n\n"

    "🏢 <b>Optom (B2B) savdo</b> — <i>Mahsulot va Buyurtma → B2B Savdo</i>\n"
    "Endi optomga <b>kg</b> da sotiladi: 500 gr uchun <b>0.5</b> deb yoziladi. "
    "Har mahsulotning <b>alohida optom narxi</b> bor (chakana narxdan mustaqil) — "
    "uni <b>💰 Optom narxlar</b> bo'limidan belgilaysiz. "
    "Optom narxlar faqat adminlarga ko'rinadi.\n\n"

    "🔎 <b>Mahsulot qidirish va to'liq tahrirlash</b> — "
    "<i>Mahsulot va Buyurtma → Mening mahsulotlarim</i>\n"
    "120 ta mahsulotni varaqlamaysiz: <b>🔎 Mahsulot qidirish</b> tugmasiga bosib "
    "nomini yozasiz. Tahrirlashda yangi maydonlar: <b>ruscha nomi</b>, "
    "<b>ruscha tavsifi</b>, <b>o'lchov birligi</b> va <b>optom narx</b>.\n\n"

    "💬 <b>Mijoz savollari</b>\n"
    "Bitta savolga faqat <b>bitta admin</b> javob bera oladi. Kimdir javob "
    "berishni boshlasa, qolganlarning xabarida «javob yozmoqda…» deb turadi; "
    "javob yuborilgach hammaning xabarida <b>kim javob bergani va nima "
    "yozgani</b> ko'rinadi.\n\n"

    "🎁 <b>Aksiya eslatmasi</b>\n"
    "Kunlik «Bugungi sovg'alar» xabari endi <b>har kuni</b> soat 12:00 da "
    "chiqadi (avval kunora chiqardi). Mavlid aksiyasida <b>69 ta</b> bonus "
    "qoidasi bor.\n\n"

    "Hammasi serverga yuklandi va ishlayapti. ✅"
)


async def main() -> None:
    await database.init_db()
    try:
        recipients = set(ADMIN_IDS) | set(await database.get_extra_admin_ids())
        # full_name is NULL for anyone who never opened the bot — those cannot
        # be reached, so report them instead of pretending they were told.
        profiles = {p["user_id"]: p for p in await database.get_admin_profiles(sorted(recipients))}
    finally:
        await database.close_db()

    bot = Bot(token=BOT_TOKEN)
    sent, failed = [], []
    for admin_id in sorted(recipients):
        who = profiles.get(admin_id) or {}
        label = who.get("username") and f"@{who['username']}" or who.get("full_name") or str(admin_id)
        try:
            await bot.send_message(admin_id, MESSAGE, parse_mode="HTML")
            sent.append(label)
            print(f"OK    {admin_id}  {label}")
        except Exception as exc:
            failed.append(f"{label} ({exc.__class__.__name__})")
            print(f"FAIL  {admin_id}  {label}: {exc}")
        await asyncio.sleep(0.05)
    await bot.session.close()

    print(f"\nDelivered to {len(sent)}/{len(recipients)}")
    if failed:
        print("Not reached:", ", ".join(failed))


if __name__ == "__main__":
    asyncio.run(main())
