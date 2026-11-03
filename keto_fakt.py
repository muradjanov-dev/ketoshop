"""
🔎 «Keto fakt» — kanalga har 2 kunda bitta qisqa post (egasi, 2026-11-03):
"maxsulotlarning ba'zi zararlari, ba'zilarini noto'g'ri ishlatayotganimiz,
ba'zilarining foydasi o'ylagandan ko'proqligi va shunga o'xshash fakt va
tarixiy isbotlangan ma'lumotlar rubrikasida har 2 kunda bir kanalga qisqagina
qiziqarli va savol bilan boshlanadigan postlar yubor".

Every post opens with a question (bold), gives one checked fact, a practical
tip, a link to the product in the text (no button — the comments stay open,
channel_link.py) and ends with a question for the comments.

Schedule: FACT_HOUR Tashkent on the days the recipe post (11:00) does NOT run
— START is a recipe-free day, so the channel gets one or the other daily.
The day is claimed in release_notes_sent first, so a restart never posts
twice; a failed post gives the claim back and is retried on the next tick.

Content rules: only facts with a clear source (a regulator, a peer-reviewed
paper, archaeology); health claims are hedged and never replace a doctor.
The channel reads Cyrillic (CHANNEL_LANG): the Latin source is transliterated
at send time, and ⟦…⟧ keeps names that must stay Latin (GHEE, FDA, EPA…).

Admins: /fakt_test — the next post, to you only; /fakt_off · /fakt_on.
"""
import asyncio
import html
import logging
import re
from datetime import date, datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import Message

import channel_link
import database
from config import ADMIN_IDS, REQUIRED_CHANNEL_ID

logger = logging.getLogger(__name__)
router = Router(name="keto_fakt")

START = date(2026, 11, 4)        # recipes run on even days from 2026-10-08 — this is an odd one
EVERY_DAYS = 2
FACT_HOUR = 16                   # 16:00 Tashkent — clear of 10:00 / 11:00 / 13:00 / 19:47
LAST_HOUR = 22
CHECK_EVERY = 600
TZ_OFFSET = timedelta(hours=5)
CHANNEL_LANG = "uz_cyr"
SETTING = "keto_fakt"            # app_settings: "0" = paused
PRODUCT_LABEL = "🛒 Ботда сотиб олиш"
HASHTAG = "#кетофакт"

# (slug, product search word or None, question, fact, tip, closing question)
FACTS: list[tuple[str, str | None, str, str, str, str]] = [
    ("eritritol-tabiiy", "eritritol",
     "Eritritol — kimyomi yoki tabiiy?",
     "Eritritol tabiatda bor: uzum, nok, tarvuz va fermentlangan mahsulotlarda oz miqdorda "
     "uchraydi. Sanoatda uni qatiq yoki non kabi — achitqi yordamida fermentatsiya qilib olishadi. "
     "Organizm uning qariyb 90% ini o'zgartirmasdan chiqarib yuboradi, shuning uchun qonda qandni "
     "deyarli ko'tarmaydi.",
     "Me'yor muhim: bir martada juda ko'p yeyilsa, qorin damlashi mumkin.",
     "Eritritolni qayerga qo'shasiz — choyga yoki pishiriqqa?"),
    ("stevia-guarani", "stevia",
     "Steviyani birinchi bo'lib kim ishlatgan?",
     "Paragvaydagi guarani xalqi bu o'tni asrlar davomida ⟦ka'a he'ê⟧ — «shirin o't» deb atab, "
     "choyiga solgan. Steviya bargidagi steviol glikozidlari shakardan 200–300 marta shirin, "
     "kaloriyasi esa deyarli nol.",
     "Ko'p solsangiz achchiq ta'm beradi — chimdimdan boshlang, juda oz miqdor yetadi.",
     "Sizga steviya yoqadimi yoki eritritolni afzal ko'rasizmi?"),
    ("psillium-suv", "psillium",
     "Psilliumni suvsiz ichsa nima bo'ladi?",
     "Psillium qobig'i suvni shimib, hajmi bir necha barobar kattalashadi va gelga aylanadi. "
     "Yetarli suvsiz ichilsa — tomoqda yoki ichakda tiqilib qolishi mumkin. To'g'ri ichilsa esa "
     "eruvchan tolasi «yomon» xolesterinni (⟦LDL⟧) pasaytirishi isbotlangan: AQSh ⟦FDA⟧ buni "
     "1998-yildan rasman tan oladi.",
     "Har choy qoshiq psilliumga kamida bir stakan suv iching.",
     "Psilliumni nonga qo'shib ko'rganmisiz?"),
    ("zigir-butun", "zig'ir uni",
     "Zig'ir urug'ini butunligicha yeyish foydalimi?",
     "Ko'pincha — yo'q. Butun urug'ning qattiq po'sti hazm bo'lmay, omega-3 va lignanlar "
     "o'zlashtirilmasdan chiqib ketadi. Foydasini olish uchun zig'irni maydalab yoki zig'ir uni "
     "sifatida ishlatish kerak.",
     "Maydalangan zig'ir tez oksidlanadi — yopiq idishda, muzlatgichda saqlang.",
     "Zig'irni nimaga qo'shasiz?"),
    ("bodom-achchiq", "bodom uni",
     "Nega achchiq bodomni xom yeyish mumkin emas?",
     "Achchiq bodomda amigdalin bor — u hazm bo'lganda sianid hosil qiladi. Biz yeydigan shirin "
     "bodomda bu modda juda kam, u xavfsiz. Bodom uni aynan shirin bodomdan tayyorlanadi va "
     "E vitamini hamda magniyga boy.",
     "Bodom unidan pishiriq tez qizaradi — pechni odatdagidan 10–20°C past qo'ying.",
     "Bodom unidan nima pishirgansiz?"),
    ("kokos-uni-1-1", "kokos uni",
     "Kokos unini bodom uni o'rniga 1:1 solsa bo'ladimi?",
     "Yo'q — bu eng ko'p uchraydigan xato. Kokos uni tolaga juda boy va suyuqlikni bir necha "
     "barobar ko'p shimadi. 1:1 solinsa, xamir quruq va uvalanadigan bo'lib qoladi.",
     "Taxminiy qoida: 1 stakan bodom uni o'rniga ¼–⅓ stakan kokos uni va qo'shimcha tuxum yoki suyuqlik.",
     "Kokos uni bilan tajriba qilganmisiz — natija qanday bo'ldi?"),
    ("ghee-tutun", "ghee",
     "Nega ⟦GHEE⟧ da qovurish sariyog'dan yaxshiroq?",
     "⟦GHEE⟧ — suvi va sut qoldiqlari ajratib olingan sariyog'. Yuqori haroratda aynan sut "
     "qoldiqlari kuyadi: oddiy sariyog' ~175°C da tutay boshlasa, ⟦GHEE⟧ taxminan 230–250°C gacha "
     "chidaydi. Laktoza va kazein ham juda oz qoladi.",
     "⟦GHEE⟧ kaloriyali — bir ovqatga 1–2 choy qoshiq yetadi.",
     "Siz nimada qovurasiz?"),
    ("zaytun-extra-virgin", "zaytun",
     "«⟦Extra Virgin⟧» yozuvi aslida nimani anglatadi?",
     "Bu reklama so'zi emas: Xalqaro zaytun kengashi standarti bo'yicha ⟦Extra Virgin⟧ moy faqat "
     "mexanik usulda, kimyoviy ishlovsiz olinadi va kislotaligi 0,8% dan oshmaydi. Shuning uchun "
     "unda polifenollar — tabiiy antioksidantlar — ko'p saqlanadi.",
     "Salatga va o'rtacha olovda pishirishga ishlating; qorong'i, salqin joyda saqlang.",
     "Zaytun moyini salatga qo'shasizmi yoki qovurishga ishlatasizmi?"),
    ("himolay-tuz", "himalay tuz",
     "Himolay tuzi rostdan Himolay tog'laridanmi?",
     "Aslida u Pokistondagi Xevra tuz konidan — Tuz tizmasidan qazib olinadi. Pushti rangni temir "
     "oksidi beradi. Tarkibining qariyb 98% i oddiy natriy xlorid, boshqa minerallar juda oz.",
     "Ketoning birinchi kunlarida organizm suv va natriyni tez yo'qotadi — ovqatga biroz tuz "
     "«keto grippi»ni yengillatadi. Lekin JSST kuniga 5 g dan oshirmaslikni tavsiya qiladi.",
     "Siz qaysi tuzni ishlatasiz?"),
    ("chia-quruq", "chia",
     "Chia urug'ini quruq holda yutish nega xavfli?",
     "Chia o'z og'irligidan 10 barobardan ko'p suv shimib, gelga aylanadi. Shifokorlar quruq chia "
     "yutib, ustidan suv ichgan odamning qizilo'ngachi tiqilib qolgan holatini tasvirlashgan (2014). "
     "Asteklar va mayyalar esa chiani asosiy oziq sifatida ishlatgan.",
     "Chiani kamida 10–15 daqiqa suv yoki sutda ivitib iste'mol qiling.",
     "Chia pudingi tayyorlaganmisiz?"),
    ("grechka-psevdodon", "grechka",
     "Grechka aslida donmi?",
     "Yo'q — grechka bug'doyga qarindosh emas, u otquloq va ravochning qarindoshi, botanikada "
     "«psevdodon» hisoblanadi. Shuning uchun tabiatan glyutensiz. Yashil grechka — qovurilmagan, "
     "xom grechka.",
     "Lekin uglevodi ko'p (100 g quruq grechkada ~70 g) — qat'iy ketoda oz miqdorda iste'mol qiling.",
     "Yashil grechkadan nima tayyorlaysiz?"),
    ("alluloza-qand-emas", "alluloza",
     "Qaysi «shakar» yorliqda qand deb hisoblanmaydi?",
     "Alluloza — anjir va mayizda oz miqdorda uchraydigan «noyob shakar». Shirinligi shakarning "
     "~70% i, kaloriyasi esa juda kam. AQSh ⟦FDA⟧ 2019-yildan allulozani yorliqdagi «qand» qatoriga "
     "kiritmaslikka ruxsat bergan — u qonda qandni deyarli oshirmaydi.",
     "Alluloza shakar kabi karamellashadi va qizaradi — pishiriqqa qulay.",
     "Allulozani sinab ko'rganmisiz?"),
    ("mct-doza", "mct",
     "⟦MCT⟧ moyini birdaniga ko'p ichsa nima bo'ladi?",
     "⟦MCT⟧ — o'rta zanjirli yog'lar: ular to'g'ri jigarga borib, tez keton tanalariga aylanadi. "
     "Lekin birinchi kunlardanoq katta doza ichilsa, oshqozon og'rig'i va ich ketishi bo'lishi mumkin.",
     "1 choy qoshiqdan boshlang va bir necha kun ichida asta oshiring.",
     "⟦MCT⟧ ni qahvaga qo'shasizmi?"),
    ("kokos-moyi-mct", "kokos",
     "Kokos moyi va ⟦MCT⟧ moyi — bir narsami?",
     "To'liq emas. Kokos moyidagi yog'larning yarmidan ko'pi lauril kislotasi (⟦C12⟧) — u "
     "organizmda ko'proq uzun zanjirli yog'dek ishlaydi. Tez energiya beradigan ⟦C8⟧ va ⟦C10⟧ "
     "kokos moyida oz, ⟦MCT⟧ moyida esa asosiy qism.",
     "Pishirishga — kokos moyi, tez energiya uchun — ⟦MCT⟧ moyi.",
     "Qaysi biri sizga ko'proq yoqadi?"),
    ("asal-ming-yil", "asal",
     "Qaysi mahsulot ming yillar davomida buzilmaydi?",
     "Asal! Arxeologlar Misr maqbaralarida uch ming yildan ortiq yotgan asal topishgan. Sababi — "
     "suvi kam, muhiti kislotali va unda tabiiy antibakterial moddalar bor.",
     "Lekin asal ~80% qand: ketoda — juda oz. Bir yoshgacha bolalarga asal berilmaydi (botulizm xavfi).",
     "Asalni qanday saqlaysiz?"),
    ("yeryongoq-dukkak", "yeryong'oq",
     "Yeryong'oq aslida yong'oqmi?",
     "Yo'q — yeryong'oq dukkakli o'simlik, no'xat va loviyaning qarindoshi, mevasi yer ostida "
     "pishadi. Shunga qaramay oqsil va yog'ga boy, ketoda me'yorida yeyish mumkin.",
     "Yeryong'oq pastasi tanlaganda tarkibiga qarang: qo'shilgan shakar va palma moyi bo'lmasin.",
     "Yeryong'oq pastasini nima bilan yeysiz?"),
    ("losos-suyak", "losos",
     "Losos konservasining suyagini tashlab yuboryapsizmi?",
     "Shoshilmang: konservadagi yumshoq suyaklar bemalol yeyiladi va kalsiyga juda boy. Losos — "
     "omega-3 (⟦EPA⟧ va ⟦DHA⟧) ning eng yaxshi manbalaridan biri.",
     "Suyaklarni vilka bilan ezib, salat yoki pashtetga qo'shing.",
     "Losos konservasidan nima tayyorlaysiz?"),
    ("keto-1921", None,
     "Keto parhezi qachon va nima uchun o'ylab topilgan?",
     "1921-yilda AQShdagi Meyo klinikasi shifokori Rassel Uaylder epilepsiyani davolash uchun "
     "ketogen parhezni taklif qilgan. Ochlik tutqanoqlarni kamaytirishi qadimdan ma'lum edi — keto "
     "organizmni to'yg'izgan holda shunga o'xshash holatga olib keladi.",
     "Bugun ham epilepsiyaning ayrim turlarida shifokor nazoratida qo'llaniladi.",
     "Siz ketoni nima uchun boshlagansiz?"),
    ("shakar-1960", None,
     "Shakar zarari haqidagi haqiqat yarim asr yashirilganmi?",
     "2016-yilda ⟦JAMA Internal Medicine⟧ jurnalida chop etilgan tahlil ko'rsatdi: 1960-yillarda "
     "shakar sanoati pul to'lagan Garvard sharhi yurak kasalliklarida aybni asosan yog'ga yuklab, "
     "shakarning rolini kamaytirib ko'rsatgan.",
     "Yorliqni o'qing: «yog'siz» deb yozilgan ko'p mahsulotlarda shakar ko'p bo'ladi.",
     "Siz mahsulot tarkibini o'qiysizmi?"),
    ("maltit-shokolad", None,
     "«Shakarsiz» shokolad ketodan chiqarib yuborishi mumkinmi?",
     "Ha — agar tarkibida maltit bo'lsa. Maltitning glikemik indeksi ~35 atrofida, u qonda qandni "
     "sezilarli ko'taradi. Eritritol va steviyaning glikemik indeksi esa amalda nol.",
     "«Shakarsiz» yozuviga emas, tarkibga qarang: maltit, sorbit — ehtiyot bo'ling.",
     "Shakarsiz shokolad tanlaganda nimaga qaraysiz?"),
    ("tuxum-xolesterin", None,
     "Tuxumdagi xolesterindan qo'rqish kerakmi?",
     "AQSh ovqatlanish yo'riqnomasi 2015-yilda kuniga 300 mg xolesterin chegarasini olib tashladi: "
     "ko'pchilik sog'lom odamda ovqatdagi xolesterin qondagisiga o'ylanganchalik ta'sir qilmaydi. "
     "Tuxum — oqsil, xolin va vitaminlarga boy, ketoning asosiy mahsuloti.",
     "Yurak-qon tomir kasalligingiz bo'lsa, me'yorni shifokor bilan aniqlang.",
     "Kuniga nechta tuxum yeysiz?"),
    ("psillium-binafsha", "psillium",
     "Psillium qo'shilgan non nega binafsha rangga kiradi?",
     "Bu buzilish emas! Ayrim psillium navlari pishiriq kukuni yoki sodaning ishqoriy muhiti bilan "
     "reaksiyaga kirib, nonni binafsha-ko'kish rangga bo'yaydi. Zararsiz — ta'm o'zgarmaydi.",
     "Rang yoqmasa, xamirga biroz olma sirkasi yoki limon sharbati qo'shing.",
     "Sizning psillium noningiz qanday rangda chiqdi?"),
    ("kakao-pul", "shokolad",
     "Kakao loviyasi qachon pul bo'lgan?",
     "Mayya va asteklarda kakao loviyasi haqiqiy pul vazifasini o'tagan: bozorda u bilan tovar "
     "sotib olishgan. Achchiq kakao ichimligi esa zodagonlar va jangchilar ichimligi bo'lgan.",
     "Ketoda kakao miqdori yuqori (70% va undan ko'p) yoki shakarsiz shokoladni tanlang.",
     "Siz qaysi shokoladni yaxshi ko'rasiz?"),
    ("bodom-uglevod", "bodom uni",
     "Bodom unida bug'doy unidan necha marta kam uglevod bor?",
     "100 g bug'doy unida ~75 g uglevod bo'lsa, bodom unida ~20 g, uning yarmiga yaqini — tola. "
     "Ya'ni sof uglevod qariyb 7 marta kam.",
     "Bodom uni pishiriqni namroq qiladi — tayyor pishiriqni to'liq sovigach kesing.",
     "Bug'doy unidan butunlay voz kechganmisiz?"),
    ("zaytun-olimpiya", "zaytun",
     "Qadimgi Olimpiya g'oliblariga nima sovg'a qilingan?",
     "Olimpiya o'yinlarida g'oliblar zaytun shoxidan gulchambar bilan taqdirlangan, Afinadagi "
     "Panafiney o'yinlarida esa — zaytun moyi to'ldirilgan amforalar bilan. Zaytun O'rta yer "
     "dengizi atrofida 6 ming yildan ortiq vaqtdan beri ekiladi.",
     "⟦Extra Virgin⟧ moyni taomga oxirida qo'shing — ta'mi va foydasi saqlanadi.",
     "Uyingizda zaytun moyi doim bormi?"),
]

_PROTECT = re.compile(r"⟦(.*?)⟧")


def _now_tk() -> datetime:
    return datetime.utcnow() + TZ_OFFSET


def is_fact_day(day: date) -> bool:
    return day >= START and (day - START).days % EVERY_DAYS == 0


def fact_for(day: date) -> tuple:
    """The fact for a posting day — in order, then round again."""
    return FACTS[((day - START).days // EVERY_DAYS) % len(FACTS)]


def next_fact_day(day: date) -> date:
    nxt = max(day, START)
    while not is_fact_day(nxt):
        nxt += timedelta(days=1)
    return nxt


def to_channel_script(text: str, lang: str = CHANNEL_LANG) -> str:
    """Latin source → the channel's script; ⟦…⟧ stays Latin as written."""
    if lang != "uz_cyr":
        return _PROTECT.sub(r"\1", text)
    from translit import lat_to_cyr
    out, pos = [], 0
    for m in _PROTECT.finditer(text):
        out.append(lat_to_cyr(text[pos:m.start()]))
        out.append(m.group(1))
        pos = m.end()
    out.append(lat_to_cyr(text[pos:]))
    return "".join(out)


def post_text(fact: tuple, link: str, lang: str = CHANNEL_LANG) -> str:
    """❓ question (bold) · fact · 💡 tip · link · 💬 question · #кетофакт."""
    _, _, question, body, tip, closing = fact

    def t(s: str) -> str:
        return html.escape(to_channel_script(s, lang), quote=False)
    return (f"<b>❓ {t(question)}</b>\n\n{t(body)}\n\n💡 {t(tip)}\n\n{link}\n\n"
            f"💬 {t(closing)}\n\n{HASHTAG}")


async def _product_link(word: str | None) -> str:
    """The shop product the fact is about, as a link in the text — else the shop."""
    if word:
        try:
            for p in await database.admin_search_products(word, limit=10):
                if p.get("is_active") == 1:
                    import product_card
                    return channel_link.link_line(product_card.product_link(p["id"]), PRODUCT_LABEL)
        except Exception:
            logger.warning("keto fakt: product lookup failed for %r", word, exc_info=True)
    return channel_link.link_line(channel_link.SHOP_URL, channel_link.SHOP_LABEL)


async def build_post(day: date) -> str:
    fact = fact_for(day)
    return post_text(fact, await _product_link(fact[1]))


async def is_enabled() -> bool:
    try:
        async with database.pool.acquire() as conn:
            value = await conn.fetchval("SELECT value FROM app_settings WHERE key = $1", SETTING)
        return value != "0"
    except Exception:
        return True          # the table is made at startup (alphabet.py); default: on


async def set_enabled(on: bool) -> None:
    async with database.pool.acquire() as conn:
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        await conn.execute(
            "INSERT INTO app_settings (key, value) VALUES ($1, $2) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", SETTING, "1" if on else "0")


async def _notify_admins(bot: Bot, text: str) -> None:
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text, parse_mode=ParseMode.HTML)
        except Exception:
            pass


async def _tick(bot: Bot) -> None:
    now = _now_tk()
    day = now.date()
    if not REQUIRED_CHANNEL_ID or not is_fact_day(day) or not FACT_HOUR <= now.hour < LAST_HOUR:
        return
    if not await is_enabled():
        return
    key = f"keto-fakt-{day.isoformat()}"
    if not await database.claim_release_notes(key):
        return
    try:
        await bot.send_message(REQUIRED_CHANNEL_ID, await build_post(day),
                               parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception:
        await database.release_release_notes(key)          # retried on the next tick
        logger.exception("Keto fakt channel post failed (%s)", key)
        return
    question = html.escape(fact_for(day)[2].replace("⟦", "").replace("⟧", ""), quote=False)
    await _notify_admins(bot, f"📣 <b>Kanalga «Keto fakt» chiqdi:</b> {question}\n"
                              "Havola matn ichida, tugma yo'q — izohlar ochiq. Keyingisi: /fakt_test")


async def scheduler_loop(bot: Bot) -> None:
    logger.info("Keto fakt scheduler started (%02d:00 every %d days from %s)",
                FACT_HOUR, EVERY_DAYS, START.isoformat())
    while True:
        try:
            await _tick(bot)
        except Exception:
            logger.exception("Keto fakt tick failed")
        await asyncio.sleep(CHECK_EVERY)


@router.message(Command("fakt_test"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_preview(message: Message):
    """The next channel post, to the admin who asked only."""
    day = next_fact_day(_now_tk().date())
    state = "✅ yoqilgan" if await is_enabled() else "⏸ to'xtatilgan (/fakt_on)"
    await message.answer(
        f"🔎 <b>Keto fakt</b> — {state}. Navbatdagisi: {day.strftime('%d.%m')} soat "
        f"{FACT_HOUR}:00 da ({len(FACTS)} ta fakt aylanib turadi):", parse_mode=ParseMode.HTML)
    await message.answer(await build_post(day), parse_mode=ParseMode.HTML,
                         disable_web_page_preview=True)


@router.message(Command("fakt_off"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_off(message: Message):
    await set_enabled(False)
    await message.answer("⏸ «Keto fakt» to'xtatildi. Yoqish: /fakt_on")


@router.message(Command("fakt_on"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_on(message: Message):
    await set_enabled(True)
    await message.answer("✅ «Keto fakt» yoqildi — har 2 kunda soat 16:00 da. Ko'rish: /fakt_test")
