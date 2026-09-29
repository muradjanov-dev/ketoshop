"""
Kanal postlari — har kuni bitta tayyor post @ketoshop_uz kanaliga.

Nega alohida modul: "Kun mahsuloti" (product_of_day.py) mahsulot sotadi,
bu esa kontent beradi — mif, retsept, yorliq o'qish, latifa. Ikkalasi bir
kunda, boshqa-boshqa soatda chiqadi va bir-biriga xalaqit bermaydi.

Tartib tasodifiy emas. channel_posts_content.WEEKS da 15 ta hafta bor, har
haftada bitta mavzu: "Shakar masalasi", "Un va non", "Kechki ovqat"... Hafta
ichida 6 kun mavzuni bosqichma-bosqich ochadi (mif → raqam → alternativa →
mahsulot → retsept), 7-kuni esa o'sha mavzuga mos latifa bilan yakunlanadi.
Shuning uchun kanalni ketma-ket o'qigan odam uzilgan gaplar emas, bog'langan
kurs ko'radi.

Holat bazada: `position` — ORDER ro'yxatidagi navbatdagi post, `cycle` —
nechanchi aylanma. Kun bazaga yozilgani uchun qayta ishga tushish yoki
redeploy bir kunda ikkinchi postni yubormaydi. 105 kun tugagach, aylanma
qaytadan boshlanadi.

Boshqaruv: /kanal_status · /kanal_on · /kanal_off · /kanal_test ·
/kanal_now · /kanal_otkaz
"""
import asyncio
import html
import logging
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

import database
import channel_posts_content as content
from config import ADMIN_IDS, BOT_USERNAME, REQUIRED_CHANNEL_ID

logger = logging.getLogger(__name__)

# Asia/Tashkent — doimiy UTC+5, yoz/qish siljishi yo'q.
TZ_OFFSET = timedelta(hours=5)
SEND_HOUR = 19          # 19:47 Toshkent — egasining tanlovi
SEND_MINUTE = 47
CHECK_EVERY = 60        # daqiqa aniqligi uchun har daqiqada tekshiramiz

SHOP_URL = f"https://t.me/{BOT_USERNAME}/shop"
BUTTON_LABEL = "🛒 Дўконни очиш"


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


def _due(now: datetime) -> bool:
    """Bugungi post vaqti keldimi?"""
    return (now.hour, now.minute) >= (SEND_HOUR, SEND_MINUTE)


def slug_at(position: int) -> str:
    return content.ORDER[position % len(content.ORDER)]


def build_text(slug: str) -> str:
    """Postni HTML ga o'raymiz: sarlavha qalin, qolgani o'zgarishsiz.

    Manbadagi «N-qism — » prefiksi hujjat ichidagi raqamlash edi; kanalda u
    keraksiz, shuning uchun sarlavha o'sha prefikssiz qalin qilib qo'yiladi.
    Matnda `<`, `>`, `&` yo'q (tekshirilgan), lekin kelajakda paydo bo'lsa
    Telegram xato bermasligi uchun escape qilinadi."""
    title, text = content.POSTS[slug]
    text = text.strip()
    # Latifalarda alohida sarlavha yo'q — matnning o'zi zarba gapi bilan boshlanadi.
    if slug.startswith("lat-"):
        return html.escape(text, quote=False)
    body = "\n".join(text.split("\n")[1:]).strip()
    title_html = html.escape(title, quote=False)
    body_html = html.escape(body, quote=False)
    return f"<b>{title_html}</b>\n\n{body_html}"


def keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=BUTTON_LABEL, url=SHOP_URL)
    ]])


async def _notify_admins(bot: Bot, text: str):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception:
            pass


async def post_to_channel(bot: Bot, slug: str) -> int | None:
    """Kanalga yuboradi. Qaytaradi: message_id yoki None (xato bo'lsa)."""
    if not REQUIRED_CHANNEL_ID:
        logger.warning("REQUIRED_CHANNEL_ID yo'q — kanal posti o'tkazib yuborildi")
        return None
    try:
        msg = await bot.send_message(
            REQUIRED_CHANNEL_ID,
            build_text(slug),
            parse_mode=ParseMode.HTML,
            reply_markup=keyboard(),
            disable_web_page_preview=True,
        )
        return msg.message_id
    except Exception:
        logger.exception("Kanal posti yuborilmadi (%s)", slug)
        return None


async def send_today(bot: Bot, day=None) -> dict | None:
    """Navbatdagi postni kanalga chiqaradi va navbatni surib qo'yadi.

    Kun avval yoziladi: yuborish paytida redeploy bo'lsa ham bir kunda
    ikkinchi post chiqmaydi."""
    state = await database.get_channel_post_state()
    position = state["position"]
    cycle = state["cycle"]
    slug = slug_at(position)

    message_id = await post_to_channel(bot, slug)
    if message_id is None:
        return None

    new_position = position + 1
    new_cycle = cycle + 1 if new_position % len(content.ORDER) == 0 else cycle
    await database.advance_channel_post(
        slug, position, cycle, message_id,
        new_position % len(content.ORDER), new_cycle,
        day or _now_tk().date())

    week, theme = content.week_of(position)
    logger.info("Kanal posti %s (%d-kun, %d-hafta '%s')", slug, position + 1, week, theme)
    return {"slug": slug, "position": position, "cycle": cycle,
            "week": week, "theme": theme, "message_id": message_id}


async def skip_next() -> str:
    """Navbatdagi postni hech kimga yubormasdan o'tkazib yuboradi."""
    state = await database.get_channel_post_state()
    position = state["position"]
    slug = slug_at(position)
    new_position = (position + 1) % len(content.ORDER)
    new_cycle = state["cycle"] + 1 if position + 1 == len(content.ORDER) else state["cycle"]
    await database.set_channel_post_position(new_position, new_cycle)
    return slug


async def _tick(bot: Bot):
    state = await database.get_channel_post_state()
    if not state["enabled"]:
        return

    now_tk = _now_tk()
    if not _due(now_tk):
        return
    if state["last_sent_date"] == now_tk.date():
        return  # bugun allaqachon chiqqan

    result = await send_today(bot, now_tk.date())
    if result is None:
        await _notify_admins(
            bot,
            "⚠️ <b>Kanal posti yuborilmadi</b>\n"
            "Telegram xato qaytardi — loglarni ko'ring. Ertaga qayta uriniladi.",
        )
        return

    title = content.POSTS[result["slug"]][0]
    await _notify_admins(
        bot,
        f"📣 <b>Kanalga chiqdi:</b> {html.escape(title)}\n"
        f"📅 {result['position'] + 1}-kun · {result['week']}-hafta "
        f"«{html.escape(result['theme'])}»\n"
        f"Keyingisi ertaga {SEND_HOUR:02d}:{SEND_MINUTE:02d} da · /kanal_status",
    )


async def scheduler_loop(bot: Bot):
    """Fon vazifasi: har daqiqada — bugungi post vaqti keldimi?"""
    logger.info("Kanal postlari scheduler ishga tushdi (%02d:%02d Toshkent)",
                SEND_HOUR, SEND_MINUTE)
    try:
        if await database.arm_channel_posts():
            logger.info("Kanal postlari birinchi bor yoqildi")
            await _notify_admins(
                bot,
                "📣 <b>Kanal postlari yoqildi</b>\n"
                f"Har kuni soat <b>{SEND_HOUR:02d}:{SEND_MINUTE:02d}</b> da "
                f"kanalga bitta post chiqadi.\n"
                f"Jami {len(content.ORDER)} ta post — {len(content.WEEKS)} hafta, "
                "har haftada bitta mavzu.\n"
                "Holat: /kanal_status · To'xtatish: /kanal_off",
            )
    except Exception:
        logger.exception("Kanal postlarini yoqish muvaffaqiyatsiz")
    while True:
        try:
            await _tick(bot)
        except Exception:
            logger.exception("Kanal posti tick xatosi")
        await asyncio.sleep(CHECK_EVERY)
