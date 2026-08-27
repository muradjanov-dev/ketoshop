"""
Personalized recipe & product-benefit recommendations.

Every 2 days each buyer who has an order history gets a *personal* bonus
message built from what THEY actually bought: a keto/PP recipe featuring their
products plus a short "why this product is good for you" note. No external ML
service — the recommendation is a content library keyed to product profiles,
matched against the buyer's order history and rotated over time so each send
differs.

Public API:
  build_personal_message(lang, orders, cycle) -> str | None
  scheduler_loop(bot)                          -> runs forever
  send_personal_batch(bot, only_user=None)     -> (sent, failed)

Language: content is authored in Uzbek (Latin) + Russian; Cyrillic Uzbek is
auto-transliterated from the Latin source, same as the rest of the bot.
"""
import asyncio
import hashlib
import html
import json
import logging
import re
from datetime import datetime, timedelta

from aiogram import Bot
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramForbiddenError,
    TelegramBadRequest,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo

import database
from config import ADMIN_IDS, WEBAPP_URL
from locales import get_text, localize_product_text

logger = logging.getLogger(__name__)


# Rotating framing lines for the browse-only (most-viewed-product) spotlight
# — added 2026-07-27 so buyers who've never ordered still get reached every
# 4 days, via what they've actually looked at rather than order history.
# The underlying product/description doesn't change often, so instead of
# content variants (like the order-based recipes) we rotate the intro line;
# once all are exhausted the never-repeat guarantee below just skips them
# that round, same as the order-based path.
_VIEW_INTROS = [
    {"uz": "👀 Diqqatingizni tortgan mahsulot:", "ru": "👀 Товар, который вас заинтересовал:"},
    {"uz": "🛍 Yana bir bor eslatib o'tamiz:", "ru": "🛍 Напоминаем ещё раз:"},
    {"uz": "⭐ Sizni kutayotgan mahsulot:", "ru": "⭐ Товар, который вас ждёт:"},
    {"uz": "💡 Ehtimol, sizga qiziq bo'lar:", "ru": "💡 Возможно, вам будет интересно:"},
    {"uz": "🔎 Ko'rib chiqqan mahsulotingiz:", "ru": "🔎 Товар, который вы просматривали:"},
]


def build_viewed_product_message(lang: str, product: dict, cycle: int) -> str:
    intro = _VIEW_INTROS[cycle % len(_VIEW_INTROS)][lang if lang == "ru" else "uz"]
    name = localize_product_text(product.get("name"), product.get("name_ru"), lang)
    desc = (localize_product_text(product.get("description"), product.get("description_ru"), lang) or "").strip()
    if len(desc) > 300:
        desc = desc[:300].rsplit(" ", 1)[0] + "…"

    discount = database.active_discount(product.get("discount_percent"), product.get("discount_until"))
    price = database.effective_price(product["price"], discount, product.get("discount_until"))
    price_str = f"{int(price):,}".replace(",", " ")
    price_line = f"💰 Narxi: <b>{price_str} so'm</b>" if lang != "ru" else f"💰 Цена: <b>{price_str} сум</b>"

    lines = [intro, f"<b>{html.escape(name)}</b>"]
    if desc:
        lines.append(html.escape(desc))
    lines.append(price_line)
    return "\n\n".join(lines)


def _product_button(product: dict, lang: str) -> "InlineKeyboardMarkup":
    text = "🛒 Mahsulotni ko'rish" if lang != "ru" else "🛒 Смотреть товар"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=text, callback_data=f"product:{product['id']}")
    ]])


def _shop_button(lang: str) -> "InlineKeyboardMarkup | None":
    if not WEBAPP_URL:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=get_text("btn_store", lang), web_app=WebAppInfo(url=WEBAPP_URL))
    ]])

# Same cadence conventions as the tips broadcaster, but a different hour so the
# two 2-day messages don't land on top of each other.
TZ_OFFSET = timedelta(hours=5)   # Asia/Tashkent, fixed UTC+5
SEND_HOUR = 10                   # 10:00 Tashkent (tips go at 08:00)
# Owner request (2026-07-04): personal recos go every 4 days, and NEVER on a
# day the 2-day tips broadcast fired — if the days collide, we slip to the
# next day. (4 is a multiple of 2, so without the slip they'd always collide.)
INTERVAL_DAYS = 4
CHECK_EVERY = 900                # re-check every 15 min
MAX_VARIANT_TRIES = 24           # rotation offsets to try before skipping a buyer
SEND_DELAY = 0.05                # ~20 msgs/sec, under Telegram limits


# ─────────────────────────────────────────────────────────────────────────────
# Content library
#
# Each "profile" describes a family of products the shop sells. `match` is a
# list of lowercase substrings looked up in the product NAME (works even if the
# product was later deleted, since we only need the stored order item name).
# `benefits` and `recipes` each carry uz + ru; the scheduler rotates through
# them by cycle so a returning buyer sees fresh content each time.
# ─────────────────────────────────────────────────────────────────────────────
PROFILES = [
    {
        "key": "almond_flour",
        "emoji": "🥜",
        "match": ["bodom", "mindal", "almond", "миндал", "бодом"],
        "name": {"uz": "Bodom uni", "ru": "Миндальная мука"},
        "benefits": [
            {"uz": "Bodom uni — past uglevodli, oqsil va sog'lom yog'larga boy. Un o'rnida ishlatsangiz, qonda shakar keskin ko'tarilmaydi va to'yimlilik uzoq saqlanadi.",
             "ru": "Миндальная мука — низкоуглеводная, богата белком и полезными жирами. Заменяя обычную муку, вы избегаете скачков сахара и дольше остаётесь сытыми."},
            {"uz": "E vitamini va magniyga boy — teri, soch va yurak salomatligi uchun foydali. Glutensiz, shuning uchun hazm qilish osonroq.",
             "ru": "Богата витамином E и магнием — полезна для кожи, волос и сердца. Без глютена, поэтому легче усваивается."},
        ],
        "recipes": [
            {"uz": "<b>Keto bodom keksi</b>\n• 200g bodom uni, 3 tuxum, 50g eritilgan sariyog', 60g eritritol, 1 ch.q. pishirish kukuni.\n• Aralashtiring, 180°C da 25 daqiqa yoping. Ustiga bir chimdim tuz — ta'mni ochadi.",
             "ru": "<b>Кето-кекс из миндаля</b>\n• 200г миндальной муки, 3 яйца, 50г топлёного масла, 60г эритрита, 1 ч.л. разрыхлителя.\n• Смешайте, выпекайте при 180°C 25 минут. Щепотка соли раскроет вкус."},
            {"uz": "<b>Bodom pancake (PP nonushta)</b>\n• 100g bodom uni, 2 tuxum, 3 osh q. suv/sut, bir chimdim tuz.\n• Xamirni quyuq qiling, kam yog'da ikkala tomonini qizarting. Ustiga chia yoki kokos qirindisi seping.",
             "ru": "<b>Миндальные панкейки (ПП-завтрак)</b>\n• 100г миндальной муки, 2 яйца, 3 ст.л. воды/молока, щепотка соли.\n• Сделайте густое тесто, обжарьте с двух сторон на малом масле. Посыпьте чиа или кокосом."},
            {"uz": "<b>Glutensiz bodom noni</b>\n• 250g bodom uni, 4 tuxum, 1 ch.q. soda, 1 osh q. olma sirkasi, tuz.\n• Qo'shib, non qolipida 180°C da 35 daqiqa yoping. Sendvich uchun ideal.",
             "ru": "<b>Безглютеновый миндальный хлеб</b>\n• 250г миндальной муки, 4 яйца, 1 ч.л. соды, 1 ст.л. яблочного уксуса, соль.\n• Смешайте, выпекайте в форме при 180°C 35 минут. Идеален для сэндвичей."},
        ],
    },
    {
        "key": "coconut",
        "emoji": "🥥",
        "match": ["kokos", "coconut", "кокос", "kakos"],
        "name": {"uz": "Kokos mahsulotlari", "ru": "Кокосовые продукты"},
        "benefits": [
            {"uz": "Kokos tarkibidagi MCT yog'lari tez energiyaga aylanadi va ketoz holatini qo'llab-quvvatlaydi. Ochlik hissi kamayadi.",
             "ru": "MCT-жиры кокоса быстро превращаются в энергию и поддерживают состояние кетоза. Снижают чувство голода."},
            {"uz": "Kokos qirindisi tolaga boy — hazmni yaxshilaydi va shirinliklarga uglevodsiz shirin ta'm beradi.",
             "ru": "Кокосовая стружка богата клетчаткой — улучшает пищеварение и придаёт десертам сладость без углеводов."},
        ],
        "recipes": [
            {"uz": "<b>Keto \"Bounty\" konfeti</b>\n• 100g kokos qirindisi, 40g eritilgan kokos yog'i, 30g eritritol, ozgina vanil.\n• Aralashtirib, kichik shariklar yasang, muzlatkichda 30 daqiqa saqlang. Xohlasangiz keto shokoladga bo'ktiring.",
             "ru": "<b>Кето-конфеты «Баунти»</b>\n• 100г кокосовой стружки, 40г топлёного кокосового масла, 30г эритрита, ваниль.\n• Скатайте шарики, охладите 30 минут. По желанию — в кето-шоколаде."},
            {"uz": "<b>Kokosli smuzi</b>\n• 200ml kokos suti, bir hovuch muzlatilgan mevalar, 1 osh q. chia, bir chimdim tuz.\n• Blenderda urib iching — to'yimli va yengil nonushta.",
             "ru": "<b>Кокосовое смузи</b>\n• 200мл кокосового молока, горсть замороженных ягод, 1 ст.л. чиа, щепотка соли.\n• Взбейте в блендере — сытный лёгкий завтрак."},
        ],
    },
    {
        "key": "bran_pp",
        "emoji": "🌾",
        "match": ["kepak", "otrub", "отруб", "bug'doy", "bugdoy", "pp un", "пп мук"],
        "name": {"uz": "Kepak va PP unlar", "ru": "Отруби и ПП-мука"},
        "benefits": [
            {"uz": "Kepak — tabiiy tola manbai. Ichak ishini yaxshilaydi, to'yimlilikni uzaytiradi va umumiy kaloriyani kamaytiradi.",
             "ru": "Отруби — источник натуральной клетчатки. Улучшают работу кишечника, продлевают сытость и снижают калорийность."},
            {"uz": "PP unlar oddiy oq unga nisbatan sekin hazm bo'ladi — energiya bir tekis taqsimlanadi, ortiqcha ishtaha bosiladi.",
             "ru": "ПП-мука усваивается медленнее белой — энергия распределяется ровно, аппетит под контролем."},
        ],
        "recipes": [
            {"uz": "<b>PP kepakli non</b>\n• 3 osh q. kepak, 2 tuxum, 2 osh q. tvorog, tuz, soda.\n• Aralashtirib, qolipda yoki tovada yoping. Yengil, tolaga boy nonushta noni.",
             "ru": "<b>ПП-хлеб с отрубями</b>\n• 3 ст.л. отрубей, 2 яйца, 2 ст.л. творога, соль, сода.\n• Смешайте и запеките. Лёгкий хлеб с клетчаткой на завтрак."},
            {"uz": "<b>Kepakli syrniki</b>\n• 200g tvorog, 1 tuxum, 2 osh q. kepak, shirinlashtirgich.\n• Kichik kulchalar yasab, kam yog'da qizarting. Ustiga tabiiy yogurt.",
             "ru": "<b>Сырники с отрубями</b>\n• 200г творога, 1 яйцо, 2 ст.л. отрубей, подсластитель.\n• Сформируйте, обжарьте на малом масле. Сверху — натуральный йогурт."},
        ],
    },
    {
        "key": "oils",
        "emoji": "🫒",
        "match": ["yog'", "yog ", "moy", "масло", "oil", "avokado", "zaytun", "olive"],
        "name": {"uz": "Sog'lom yog'lar", "ru": "Полезные масла"},
        "benefits": [
            {"uz": "Sifatli o'simlik yog'lari — keto ratsionining asosi. Ular yog'da eruvchi vitaminlarni (A, D, E, K) o'zlashtirishga yordam beradi.",
             "ru": "Качественные растительные масла — основа кето-рациона. Помогают усваивать жирорастворимые витамины (A, D, E, K)."},
            {"uz": "Sovuq bosim yog'lari salatlar uchun ideal; kokos yog'i esa yuqori haroratda qovurishga chidamli.",
             "ru": "Масла холодного отжима идеальны для салатов; кокосовое масло устойчиво к высоким температурам при жарке."},
        ],
        "recipes": [
            {"uz": "<b>Keto salat sousi</b>\n• 3 osh q. zaytun/avokado yog'i, 1 osh q. olma sirkasi, tuz, murch, xantal.\n• Chayqatib aralashtiring — har qanday yashil salatga jonli ta'm.",
             "ru": "<b>Кето-заправка для салата</b>\n• 3 ст.л. оливкового/авокадо масла, 1 ст.л. яблочного уксуса, соль, перец, горчица.\n• Взболтайте — оживит любой зелёный салат."},
            {"uz": "<b>Kokos yog'ida qovurilgan tuxum</b>\n• Kokos yog'ini qizdiring, tuxumni yoki avokado bilan qovuring, Himalay tuzi seping. To'yimli keto nonushta.",
             "ru": "<b>Яйца на кокосовом масле</b>\n• Разогрейте кокосовое масло, обжарьте яйца (можно с авокадо), посыпьте гималайской солью. Сытный кето-завтрак."},
        ],
    },
    {
        "key": "vinegar",
        "emoji": "🍎",
        "match": ["sirka", "uksus", "уксус", "vinegar"],
        "name": {"uz": "Olma sirkasi", "ru": "Яблочный уксус"},
        "benefits": [
            {"uz": "Ovqatdan oldin bir choy qoshiq olma sirkasi (bir stakan suvda) qondagi shakarning keskin ko'tarilishini yumshatishga yordam beradi.",
             "ru": "Чайная ложка яблочного уксуса в стакане воды перед едой помогает смягчить резкий подъём сахара в крови."},
            {"uz": "Ishtahani muvozanatlaydi va hazmni qo'llab-quvvatlaydi. Salat souslariga tabiiy nordonlik beradi.",
             "ru": "Балансирует аппетит и поддерживает пищеварение. Придаёт салатам натуральную кислинку."},
        ],
        "recipes": [
            {"uz": "<b>Tetiklashtiruvchi ichimlik</b>\n• 1 stakan suv, 1 ch.q. olma sirkasi, bir chimdim Himalay tuzi, xohlasangiz ozgina eritritol.\n• Ovqatdan 15 daqiqa oldin iching.",
             "ru": "<b>Бодрящий напиток</b>\n• Стакан воды, 1 ч.л. яблочного уксуса, щепотка гималайской соли, по желанию эритрит.\n• Пейте за 15 минут до еды."},
            {"uz": "<b>Tez marinad</b>\n• Bodring/karam/piyozni olma sirkasi, tuz va sув bilan 30 daqiqa marinadlang. Yog'li taomlarga yengil garnitura.",
             "ru": "<b>Быстрый маринад</b>\n• Огурцы/капусту/лук замаринуйте в яблочном уксусе с солью и водой на 30 минут. Лёгкий гарнир к жирным блюдам."},
        ],
    },
    {
        "key": "seeds",
        "emoji": "🌱",
        "match": ["chia", "чиа", "zig'ir", "zigir", "lyon", "лён", "len", "kunjut", "sesame", "кунжут", "urug'", "urug ", "semech", "семеч", "seed"],
        "name": {"uz": "Urug'lar (chia, zig'ir…)", "ru": "Семена (чиа, лён…)"},
        "benefits": [
            {"uz": "Chia va zig'ir urug'i omega-3 va eruvchi tolaga boy — yurak salomatligi va uzoq to'yimlilik uchun.",
             "ru": "Чиа и семена льна богаты омега-3 и растворимой клетчаткой — для здоровья сердца и долгой сытости."},
            {"uz": "Suvda bo'kkanda gelga aylanadi — ochlikni bosadi va ichak ishini yaxshilaydi.",
             "ru": "Разбухая в воде, превращаются в гель — утоляют голод и улучшают работу кишечника."},
        ],
        "recipes": [
            {"uz": "<b>Chia puding</b>\n• 3 osh q. chia, 200ml kokos/bodom suti, shirinlashtirgich, vanil.\n• Aralashtirib, tunda muzlatkichda qoldiring. Ertalab ustiga mevalar — tayyor keto nonushta.",
             "ru": "<b>Чиа-пудинг</b>\n• 3 ст.л. чиа, 200мл кокосового/миндального молока, подсластитель, ваниль.\n• Смешайте, оставьте на ночь в холодильнике. Утром — ягоды сверху."},
            {"uz": "<b>Zig'irli kraker</b>\n• 4 osh q. zig'ir urug'i + 4 osh q. suv 10 daqiqa turadi, tuz va ziravor qo'shing.\n• Yupqa yoyib, 150°C da 40 daqiqa quriting. Xrustaydigan keto gazak.",
             "ru": "<b>Льняные крекеры</b>\n• 4 ст.л. семян льна + 4 ст.л. воды на 10 минут, соль и специи.\n• Раскатайте тонко, сушите при 150°C 40 минут. Хрустящий кето-снек."},
        ],
    },
    {
        "key": "salt",
        "emoji": "🧂",
        "match": ["tuz", "соль", "sol ", "himalay", "гималай", "salt"],
        "name": {"uz": "Himalay tuzi", "ru": "Гималайская соль"},
        "benefits": [
            {"uz": "Keto davrida organizm ko'proq natriy yo'qotadi. Himalay tuzi elektrolit muvozanatini tiklaydi va \"keto grip\" (holsizlik, bosh og'rig'i) ni kamaytiradi.",
             "ru": "На кето организм теряет больше натрия. Гималайская соль восстанавливает баланс электролитов и снижает «кето-грипп» (слабость, головную боль)."},
            {"uz": "Tarkibida 80 dan ortiq mineral bor — oddiy tuzga qaraganda tabiiyroq va boy ta'mli.",
             "ru": "Содержит более 80 минералов — натуральнее и богаче по вкусу, чем обычная соль."},
        ],
        "recipes": [
            {"uz": "<b>Uy elektrolit ichimligi</b>\n• 500ml suv, 1/4 ch.q. Himalay tuzi, yarim limon sharbati, ozgina eritritol.\n• Kun davomida ho'plab iching — ayniqsa keto boshida foydali.",
             "ru": "<b>Домашний электролитный напиток</b>\n• 500мл воды, 1/4 ч.л. гималайской соли, сок половины лимона, немного эритрита.\n• Пейте в течение дня — особенно полезно в начале кето."},
        ],
    },
    {
        "key": "sweeteners",
        "emoji": "🍬",
        "match": ["eritritol", "эритрит", "stevia", "стеви", "shirin", "podslast", "подсласт", "shakar o'rn", "sweeten"],
        "name": {"uz": "Shirinlashtirgichlar", "ru": "Подсластители"},
        "benefits": [
            {"uz": "Eritritol va steviya deyarli 0 kaloriyali va qondagi shakarni ko'tarmaydi — shirinlikni yeb, ketozdan chiqmaysiz.",
             "ru": "Эритрит и стевия почти без калорий и не поднимают сахар — можно сладкое, не выходя из кетоза."},
            {"uz": "Tishlarga zararsiz va oddiy shakarga to'liq muqobil. Pishiriqlarda 1:1 nisbatda ishlatish mumkin.",
             "ru": "Безопасны для зубов и полностью заменяют сахар. В выпечке используются 1:1."},
        ],
        "recipes": [
            {"uz": "<b>Keto issiq shokolad</b>\n• 200ml kokos suti, 1 osh q. kakao, eritritol, bir chimdim tuz.\n• Isiting va aralashtiring — shakarsiz shirin kechki ichimlik.",
             "ru": "<b>Кето горячий шоколад</b>\n• 200мл кокосового молока, 1 ст.л. какао, эритрит, щепотка соли.\n• Подогрейте и размешайте — сладкий вечерний напиток без сахара."},
        ],
    },
    {
        "key": "honey",
        "emoji": "🍯",
        "match": ["asal", "мёд", "med ", "honey"],
        "name": {"uz": "Asal", "ru": "Мёд"},
        "benefits": [
            {"uz": "Tabiiy asal — antioksidant va mineralga boy. Keto rejimida oz miqdorda, oddiy shakar o'rnida ishlatilsa foydaliroq.",
             "ru": "Натуральный мёд богат антиоксидантами и минералами. На кето — в небольшом количестве, как замена обычному сахару."},
        ],
        "recipes": [
            {"uz": "<b>Tomoq uchun issiq ichimlik</b>\n• Iliq suv, 1 ch.q. asal, yarim limon, ozgina zanjabil. Sovuq kunlarda immunitet uchun.",
             "ru": "<b>Тёплый напиток для горла</b>\n• Тёплая вода, 1 ч.л. мёда, половина лимона, немного имбиря. Для иммунитета в холода."},
        ],
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# Complementary-ingredient suggestions (cross-recommendations).
#
# Keyed by the buyer's dominant profile: "you buy X — these ingredients pair
# with it". Each suggestion carries the profile key it belongs to, so we can
# skip suggesting things the buyer already purchases. All items are product
# families the shop actually stocks.
# ─────────────────────────────────────────────────────────────────────────────
PAIRINGS: dict[str, list[dict]] = {
    "almond_flour": [
        {"profile": "sweeteners", "emoji": "🍬",
         "name": {"uz": "Eritritol", "ru": "Эритрит"},
         "why": {"uz": "bodom unidan keto keks va pechene tayyorlashda shakar o'rnini bosadi — kaloriyasiz shirinlik",
                 "ru": "заменит сахар в кето-выпечке из миндальной муки — сладость без калорий"}},
        {"profile": "seeds", "emoji": "🌱",
         "name": {"uz": "Chia urug'i", "ru": "Семена чиа"},
         "why": {"uz": "pishiriqlarga qo'shsangiz tola va omega-3 qo'shiladi, xamir yaxshi bog'lanadi",
                 "ru": "добавит клетчатку и омега-3 в выпечку, хорошо связывает тесто"}},
        {"profile": "coconut", "emoji": "🥥",
         "name": {"uz": "Kokos qirindisi", "ru": "Кокосовая стружка"},
         "why": {"uz": "bodomli keks va pancake ustiga sepish uchun — tabiiy shirin ta'm",
                 "ru": "посыпка для кексов и панкейков — натуральная сладость"}},
    ],
    "coconut": [
        {"profile": "almond_flour", "emoji": "🥜",
         "name": {"uz": "Bodom uni", "ru": "Миндальная мука"},
         "why": {"uz": "kokos bilan juftlikda keto shirinliklarning asosiy poydevori",
                 "ru": "в паре с кокосом — основа кето-десертов"}},
        {"profile": "sweeteners", "emoji": "🍬",
         "name": {"uz": "Eritritol", "ru": "Эритрит"},
         "why": {"uz": "kokosli konfet va pudinglarga shakarsiz shirinlik beradi",
                 "ru": "придаст кокосовым конфетам сладость без сахара"}},
        {"profile": "seeds", "emoji": "🌱",
         "name": {"uz": "Chia urug'i", "ru": "Семена чиа"},
         "why": {"uz": "kokos suti bilan chia puding — eng oson keto nonushta",
                 "ru": "чиа-пудинг на кокосовом молоке — самый простой кето-завтрак"}},
    ],
    "bran_pp": [
        {"profile": "seeds", "emoji": "🌱",
         "name": {"uz": "Zig'ir urug'i", "ru": "Семена льна"},
         "why": {"uz": "kepakli nonga qo'shilsa tola va omega-3 yana ham oshadi",
                 "ru": "добавит хлебу с отрубями ещё больше клетчатки и омега-3"}},
        {"profile": "vinegar", "emoji": "🍎",
         "name": {"uz": "Olma sirkasi", "ru": "Яблочный уксус"},
         "why": {"uz": "PP xamirturushsiz nonda sodani faollashtiradi — non yumshoq chiqadi",
                 "ru": "активирует соду в ПП-выпечке — хлеб получается пышным"}},
        {"profile": "oils", "emoji": "🫒",
         "name": {"uz": "Zaytun yog'i", "ru": "Оливковое масло"},
         "why": {"uz": "PP taomlarga sog'lom yog' qo'shadi — vitaminlar yaxshi so'riladi",
                 "ru": "полезные жиры к ПП-блюдам — витамины усваиваются лучше"}},
    ],
    "oils": [
        {"profile": "vinegar", "emoji": "🍎",
         "name": {"uz": "Olma sirkasi", "ru": "Яблочный уксус"},
         "why": {"uz": "yog' bilan 3:1 nisbatda — mukammal salat sousi",
                 "ru": "с маслом в пропорции 3:1 — идеальная заправка для салата"}},
        {"profile": "salt", "emoji": "🧂",
         "name": {"uz": "Himalay tuzi", "ru": "Гималайская соль"},
         "why": {"uz": "sog'lom yog'lar bilan tayyorlangan taomlarga mineral qo'shadi",
                 "ru": "добавит минералы блюдам на полезных маслах"}},
        {"profile": "seeds", "emoji": "🌱",
         "name": {"uz": "Kunjut urug'i", "ru": "Кунжут"},
         "why": {"uz": "yog'li salatlarga xrust va kalsiy beradi",
                 "ru": "хруст и кальций для салатов с маслом"}},
    ],
    "vinegar": [
        {"profile": "oils", "emoji": "🫒",
         "name": {"uz": "Zaytun / avokado yog'i", "ru": "Оливковое масло / масло авокадо"},
         "why": {"uz": "sirka bilan birga klassik vinegret sousi bo'ladi",
                 "ru": "вместе с уксусом — классическая заправка винегрет"}},
        {"profile": "salt", "emoji": "🧂",
         "name": {"uz": "Himalay tuzi", "ru": "Гималайская соль"},
         "why": {"uz": "ertalabki sirka ichimligiga qo'shsangiz elektrolitlar tiklanadi",
                 "ru": "в утренний напиток с уксусом — для восстановления электролитов"}},
    ],
    "seeds": [
        {"profile": "coconut", "emoji": "🥥",
         "name": {"uz": "Kokos suti / qirindisi", "ru": "Кокосовое молоко / стружка"},
         "why": {"uz": "chia puding uchun eng mos asos",
                 "ru": "лучшая основа для чиа-пудинга"}},
        {"profile": "sweeteners", "emoji": "🍬",
         "name": {"uz": "Eritritol", "ru": "Эритрит"},
         "why": {"uz": "urug'li puding va smuzilarni shakarsiz shirin qiladi",
                 "ru": "подсластит пудинги и смузи без сахара"}},
        {"profile": "almond_flour", "emoji": "🥜",
         "name": {"uz": "Bodom uni", "ru": "Миндальная мука"},
         "why": {"uz": "urug'lar bilan birga keto non va krakerlar uchun asos",
                 "ru": "с семенами — основа кето-хлеба и крекеров"}},
    ],
    "salt": [
        {"profile": "vinegar", "emoji": "🍎",
         "name": {"uz": "Olma sirkasi", "ru": "Яблочный уксус"},
         "why": {"uz": "tuz bilan birga ertalabki elektrolit ichimligining asosi",
                 "ru": "с солью — основа утреннего электролитного напитка"}},
        {"profile": "oils", "emoji": "🫒",
         "name": {"uz": "Sog'lom yog'lar", "ru": "Полезные масла"},
         "why": {"uz": "keto ratsionda tuz va yog' — energiya va mineral juftligi",
                 "ru": "на кето соль и жиры — пара для энергии и минералов"}},
    ],
    "sweeteners": [
        {"profile": "almond_flour", "emoji": "🥜",
         "name": {"uz": "Bodom uni", "ru": "Миндальная мука"},
         "why": {"uz": "eritritol bilan birga to'liq keto pishiriq to'plami",
                 "ru": "с эритритом — полный набор для кето-выпечки"}},
        {"profile": "coconut", "emoji": "🥥",
         "name": {"uz": "Kokos qirindisi", "ru": "Кокосовая стружка"},
         "why": {"uz": "shirinlashtirgich bilan uy sharoitida 'Bounty' konfeti chiqadi",
                 "ru": "с подсластителем получаются домашние конфеты «Баунти»"}},
    ],
    "honey": [
        {"profile": "seeds", "emoji": "🌱",
         "name": {"uz": "Urug'lar aralashmasi", "ru": "Смесь семян"},
         "why": {"uz": "asal bilan birga tabiiy energiya batonchiklari tayyorlanadi",
                 "ru": "с мёдом — натуральные энергетические батончики"}},
        {"profile": "bran_pp", "emoji": "🌾",
         "name": {"uz": "Kepak", "ru": "Отруби"},
         "why": {"uz": "asalli granola va nonushta aralashmalari uchun tola manbai",
                 "ru": "источник клетчатки для медовой гранолы и завтраков"}},
    ],
    "healthy": [
        {"profile": "salt", "emoji": "🧂",
         "name": {"uz": "Himalay tuzi", "ru": "Гималайская соль"},
         "why": {"uz": "har qanday sog'lom oshxonaning asosi — 80+ mineral",
                 "ru": "основа любой здоровой кухни — 80+ минералов"}},
        {"profile": "oils", "emoji": "🫒",
         "name": {"uz": "Sovuq bosim yog'lari", "ru": "Масла холодного отжима"},
         "why": {"uz": "salat va tayyor taomlar uchun sog'lom yog' manbai",
                 "ru": "источник полезных жиров для салатов и готовых блюд"}},
    ],
}


# Fallback for products that don't match any profile above.
DEFAULT_PROFILE = {
    "key": "healthy",
    "emoji": "🥗",
    "name": {"uz": "Sog'lom mahsulotlar", "ru": "Здоровые продукты"},
    "benefits": [
        {"uz": "Tabiiy, kam qayta ishlangan mahsulotlar organizmni toza oziqlantiradi — energiya barqaror, ishtaha nazoratda bo'ladi.",
         "ru": "Натуральные, минимально обработанные продукты питают организм чисто — стабильная энергия и контроль аппетита."},
    ],
    "recipes": [
        {"uz": "<b>Sog'lom kosa (buddha bowl)</b>\n• Yashil barglar, qaynatilgan tuxum yoki tovuq, avokado, urug'lar, olma sirkasi + yog' sousi.\n• Tez, to'yimli va muvozanatli tushlik.",
         "ru": "<b>Здоровая тарелка (боул)</b>\n• Зелень, варёное яйцо или курица, авокадо, семена, заправка из масла и яблочного уксуса.\n• Быстрый, сытный и сбалансированный обед."},
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# Message building
# ─────────────────────────────────────────────────────────────────────────────
def _loc(entry: dict, lang: str) -> str:
    """Pick uz/ru text from a {uz, ru} entry; transliterate for uz_cyr."""
    if lang == "ru":
        return entry.get("ru") or entry.get("uz", "")
    text = entry.get("uz", "")
    if lang == "uz_cyr" and text:
        from translit import lat_to_cyr
        return lat_to_cyr(text)
    return text


def _aggregate_products(orders: list[dict]) -> list[tuple[str, float]]:
    """Sum ordered quantity per product name across the buyer's orders.
    Returns [(name, total_qty), …] sorted by qty desc."""
    totals: dict[str, float] = {}
    for o in orders:
        raw = o.get("items")
        if not raw:
            continue
        try:
            items = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError):
            continue
        for it in items or []:
            name = (it.get("name") or "").strip()
            if not name:
                continue
            try:
                qty = float(it.get("quantity") or 1)
            except (ValueError, TypeError):
                qty = 1.0
            totals[name] = totals.get(name, 0.0) + qty
    return sorted(totals.items(), key=lambda kv: kv[1], reverse=True)


def _profile_for(name: str) -> dict:
    """Match a product name to a content profile (keyword lookup), else default."""
    low = name.lower()
    for prof in PROFILES:
        if any(kw in low for kw in prof["match"]):
            return prof
    return DEFAULT_PROFILE


def _pick(seq: list, cycle: int):
    """Deterministic rotation so returning buyers get fresh content each send."""
    return seq[cycle % len(seq)] if seq else None


# Section labels, greeting, and the closing "bonus" note — the closing text is
# the one the shop owner asked to send verbatim.
LABELS = {
    "header": {
        "uz": "🎁 <b>Sizga maxsus — buyurtmalaringiz asosida</b>",
        "ru": "🎁 <b>Специально для вас — на основе ваших заказов</b>",
    },
    "intro": {
        "uz": "Assalomu alaykum! Siz tanlagan mahsulotlarni tahlil qildik va aynan Siz uchun retsept hamda foydali maslahatlar tayyorladik. 👇",
        "ru": "Здравствуйте! Мы проанализировали выбранные вами товары и подготовили рецепт и полезные советы именно для вас. 👇",
    },
    "your_picks": {
        "uz": "🛒 <b>Sizning tanlovingiz:</b>",
        "ru": "🛒 <b>Ваш выбор:</b>",
    },
    "recipe": {
        "uz": "👨‍🍳 <b>Siz uchun retsept</b>",
        "ru": "👨‍🍳 <b>Рецепт для вас</b>",
    },
    "benefit": {
        "uz": "💡 <b>Nega bu foydali?</b>",
        "ru": "💡 <b>Чем это полезно?</b>",
    },
    "pairs": {
        "uz": "🧺 <b>Bularni ham sinab ko'ring</b> — mahsulotlaringizga ajoyib hamroh:",
        "ru": "🧺 <b>Попробуйте также</b> — отлично дополнит ваши продукты:",
    },
    "pairs_footer": {
        "uz": "Bularning barchasini do'konimizdan topasiz 😊",
        "ru": "Всё это вы найдёте в нашем магазине 😊",
    },
    "closing": {
        "uz": ("🙏 <b>Ketoshopni tanlaganingiz uchun tashakkur!</b>\n"
               "Buyurtmalar tarixingiz asosida Sizga bonus tariqasida foydali "
               "ma'lumotlarni har 4 kunda berib boramiz. Yanada ko'proq foyda "
               "olsangiz — biz xursandmiz. Sizga sog'lom hayot va baxt tilaymiz!\n"
               "<i>Hurmat bilan, Ketoshop jamoasi.</i>"),
        "ru": ("🙏 <b>Спасибо, что выбрали Ketoshop!</b>\n"
               "На основе истории ваших заказов мы дарим вам полезные материалы "
               "каждые 4 дня. Будем рады, если это принесёт вам ещё больше пользы. "
               "Желаем вам здоровья и счастья!\n"
               "<i>С уважением, команда Ketoshop.</i>"),
    },
}


def build_personal_message(lang: str, orders: list[dict], cycle: int) -> str | None:
    """Compose one buyer's personalized message, or None if they have no
    recognizable order history."""
    products = _aggregate_products(orders)
    if not products:
        return None

    # The buyer's most-ordered product headlines this send; its profile drives
    # the recipe. A second, differently-profiled product (if any) adds a bonus
    # benefit so the note reflects the breadth of what they buy.
    star_name = products[0][0]
    star_profile = _profile_for(star_name)

    second_profile = None
    for name, _ in products[1:]:
        prof = _profile_for(name)
        if prof["key"] != star_profile["key"]:
            second_profile = prof
            break

    def esc(s: str) -> str:
        return html.escape(s, quote=False)

    lines: list[str] = []
    lines.append(_loc(LABELS["header"], lang))
    lines.append("")
    lines.append(_loc(LABELS["intro"], lang))
    lines.append("")

    # Buyer's top products (up to 3), each with its profile emoji.
    lines.append(_loc(LABELS["your_picks"], lang))
    for name, _qty in products[:3]:
        prof = _profile_for(name)
        lines.append(f"{prof['emoji']} {esc(name)}")
    lines.append("")

    # Content rotation uses a MIXED-RADIX decomposition of `cycle` — recipe is
    # the fastest "digit", then star benefit, then the rest. Rotating every
    # section with the same counter would sync them (period = LCM of lengths,
    # often just 2); decomposing walks the full Cartesian product of variants,
    # which the never-repeat dedupe in send_personal_batch depends on to find
    # fresh messages for as long as possible.
    r_len = max(1, len(star_profile["recipes"]))
    b_len = max(1, len(star_profile["benefits"]))
    recipe = _pick(star_profile["recipes"], cycle % r_len)
    if recipe:
        lines.append(_loc(LABELS["recipe"], lang))
        lines.append(_loc(recipe, lang))
        lines.append("")

    # Benefits — star product, plus one from a second profile when available.
    lines.append(_loc(LABELS["benefit"], lang))
    rest = cycle // r_len
    star_benefit = _pick(star_profile["benefits"], rest % b_len)
    rest //= b_len
    if star_benefit:
        lines.append(f"{star_profile['emoji']} {_loc(star_benefit, lang)}")
    if second_profile:
        sb_len = max(1, len(second_profile["benefits"]))
        sb = _pick(second_profile["benefits"], (rest + 1) % sb_len)
        rest //= sb_len
        if sb:
            lines.append(f"{second_profile['emoji']} {_loc(sb, lang)}")
    lines.append("")

    # Complementary ingredients the buyer does NOT already purchase — cross-
    # recommendations tied to their dominant product, with the reason each one
    # pairs well. Rotated by the remaining digits; capped at 2 per message.
    owned_keys = {_profile_for(name)["key"] for name, _ in products}
    candidates = [s for s in PAIRINGS.get(star_profile["key"], [])
                  if s["profile"] not in owned_keys]
    if candidates:
        start = rest % len(candidates)
        picked = [candidates[(start + i) % len(candidates)]
                  for i in range(min(2, len(candidates)))]
        lines.append(_loc(LABELS["pairs"], lang))
        for s in picked:
            lines.append(f"{s['emoji']} <b>{_loc(s['name'], lang)}</b> — {_loc(s['why'], lang)}")
        lines.append(_loc(LABELS["pairs_footer"], lang))
        lines.append("")

    lines.append(_loc(LABELS["closing"], lang))
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Sending
# ─────────────────────────────────────────────────────────────────────────────
def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


async def _notify_admins(bot: Bot, text: str):
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception:
            pass


async def send_personal_batch(bot: Bot, only_user: int | None = None) -> tuple[int, int]:
    """Build and send each eligible buyer's personalized message.

    `only_user` restricts the send to a single user id (used by /reco_test and
    /reco_now previews). Returns (sent, failed).

    Two populations: buyers with order history get the rich recipe/benefit
    message below; browse-only users (viewed products but never ordered —
    previously skipped entirely) get a lighter most-viewed-product spotlight,
    sent in the second loop further down (owner request 2026-07-27: reach
    "barcha foydalanuvchilar", not just past buyers)."""
    state = await database.get_reco_state()
    cycle = state.get("cycle", 0)

    if only_user is not None:
        user_ids = [only_user]
    else:
        user_ids = await database.get_user_ids_with_orders()

    # Never repeat: try successive rotation offsets until we find a message
    # this buyer hasn't received; if every variant was already sent, skip them
    # this round rather than send a duplicate. Test previews (only_user) skip
    # the bookkeeping so they don't burn variants.
    record = only_user is None

    sent = failed = skipped = 0
    for uid in user_ids:
        try:
            orders = await database.get_user_orders(uid)
            lang = await database.get_user_language(uid)

            seen = await database.get_reco_hashes(uid) if record else set()
            text = msg_hash = None
            for shift in range(MAX_VARIANT_TRIES):
                candidate = build_personal_message(lang, orders, cycle + shift)
                if not candidate:
                    break
                h = hashlib.sha256(candidate.encode()).hexdigest()
                if h not in seen:
                    text, msg_hash = candidate, h
                    break
            if not text:
                skipped += 1
                continue

            delivered = False
            markup = _shop_button(lang)
            try:
                await bot.send_message(uid, text, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                                        reply_markup=markup)
                delivered = True
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                await bot.send_message(uid, text, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                                        reply_markup=markup)
                delivered = True
            except (TelegramForbiddenError, TelegramBadRequest):
                failed += 1

            if delivered:
                sent += 1
                if record:
                    await database.mark_reco_sent(uid, msg_hash)
        except Exception:
            logger.exception("Personal reco send failed for user %s", uid)
            failed += 1
        await asyncio.sleep(SEND_DELAY)

    # Second population: browse-only users (no orders, but have viewed at
    # least one product) — most-viewed-product spotlight instead of a
    # recipe. Same never-repeat/skip bookkeeping, same reco_sent table.
    #
    # Rotates over BOTH their top-3 recently-viewed products AND the intro
    # line (owner request 2026-07-27: must adapt as interest shifts, not
    # freeze on one product forever) — get_user_top_viewed_products re-ranks
    # from the last 30 days fresh every send, so as a buyer's browsing moves
    # on, the spotlight follows. Their #1 current interest is tried first
    # (with all its intro variants) before falling back to #2/#3, so the
    # product only changes once genuinely-new content is needed.
    if only_user is None:
        view_only_ids = await database.get_user_ids_with_views_no_orders()
        for uid in view_only_ids:
            try:
                products = await database.get_user_top_viewed_products(uid, limit=3, recent_days=30)
                if not products:
                    skipped += 1
                    continue
                lang = await database.get_user_language(uid)
                seen = await database.get_reco_hashes(uid)

                text = msg_hash = product = None
                for p in products:
                    for shift in range(len(_VIEW_INTROS)):
                        candidate = build_viewed_product_message(lang, p, cycle + shift)
                        h = hashlib.sha256(candidate.encode()).hexdigest()
                        if h not in seen:
                            text, msg_hash, product = candidate, h, p
                            break
                    if text:
                        break
                if not text:
                    skipped += 1
                    continue

                delivered = False
                markup = _product_button(product, lang)
                try:
                    await bot.send_message(uid, text, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                                            reply_markup=markup)
                    delivered = True
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
                    await bot.send_message(uid, text, parse_mode=ParseMode.HTML, disable_web_page_preview=True,
                                            reply_markup=markup)
                    delivered = True
                except (TelegramForbiddenError, TelegramBadRequest):
                    failed += 1

                if delivered:
                    sent += 1
                    await database.mark_reco_sent(uid, msg_hash)
            except Exception:
                logger.exception("Viewed-product reco send failed for user %s", uid)
                failed += 1
            await asyncio.sleep(SEND_DELAY)

    if skipped:
        logger.info("Personal reco: %d buyer(s) skipped — all content variants already sent", skipped)
    return sent, failed


async def _tick(bot: Bot):
    state = await database.get_reco_state()
    if not state["enabled"]:
        return

    last = state["last_sent_at"]
    if last is None:
        due = True  # first send after arming — goes out on the next check
    else:
        now_tk = _now_tk()
        last_tk = last + TZ_OFFSET
        elapsed_days = (now_tk.date() - last_tk.date()).days
        due = elapsed_days >= INTERVAL_DAYS and now_tk.hour >= SEND_HOUR

    if not due:
        return

    # Never share a day with the keto-tips broadcast: if a tip already went out
    # today (Tashkent date), slip to tomorrow. `due` stays true, so the next
    # tick after midnight sends. Tips fire at 08:00 and we check at 10:00+, so
    # "sent today" is a reliable signal by the time we get here.
    try:
        tips = await database.get_broadcast_state()
        tips_last = tips.get("last_sent_at")
        if tips_last and (tips_last + TZ_OFFSET).date() == _now_tk().date():
            logger.info("Personal reco postponed: tips broadcast already sent today")
            return
    except Exception:
        logger.exception("Could not read tips state; sending reco anyway")

    sent, failed = await send_personal_batch(bot)
    await database.advance_reco()
    await _notify_admins(
        bot,
        f"🎁 Shaxsiy tavsiyalar yuborildi.\n"
        f"✅ {sent} ta yetkazildi, ⚠️ {failed} ta yetmadi.",
    )
    logger.info("Personal recommendations sent: %d ok, %d failed", sent, failed)


async def scheduler_loop(bot: Bot):
    """Background task: every CHECK_EVERY seconds, send personalized recos if due."""
    logger.info("Personal-recommendation scheduler started (%d profiles)", len(PROFILES))
    while True:
        try:
            await _tick(bot)
        except Exception:
            logger.exception("Personal reco tick failed")
        await asyncio.sleep(CHECK_EVERY)
