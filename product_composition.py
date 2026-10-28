"""
Mahsulot tarkibi — «🧾 Tarkibi» on every product card, in the bot and on the
site (owner, 2026-10-28: "xar bir mahsulot uchun botda ham saytda ham, tarkib
degan qism kirgaz va unlarni tarkibini o'zini mahsulotini yozib qo'y, va bot
orqali admin paneldan istalgan mahsulotga yana tarkib kiritish imkonini
qo'shgin ... tarkibni o'zgartirish imkoni ham bo'lsin").

Stored per product in products.composition (uz Latin; uz_cyr is derived as
everywhere else) and products.composition_ru. Admins write and change it in
the bot (product → ✏️ → «🧾 Tarkib») or on the admin website; a card reads
the row every time, so a change shows at once.

What is filled in here, and what is not
  This library fills ONLY products whose composition follows from what the
  product is: a flour of one grain, a seed, a nut, salt, eritritol, an extra
  virgin oil, honey… For those the name IS the ingredient list.
  Branded and mixed goods — chocolate, canned salmon, coconut cream, pasta,
  the Stevia 200/500/1000 g blends, nut pastes, the starter, frying oil — are
  left empty on purpose: their composition is on the label, and a guess on a
  food card can hide an allergen. Admins copy those from the pack.

  fill_missing() writes a suggestion into every product whose composition
  is still NULL — never touched. An admin clearing a composition stores ""
  (not NULL), so the library never writes it back.
"""
import asyncio
import logging
import re

logger = logging.getLogger(__name__)

CHECK_EVERY = 3600             # a new product gets its composition within the hour

# Never guessed — the label says what is inside (see the docstring).
_SKIP_RE = re.compile(
    r"makaron|vermishel|pasta|shokolad|шоколад|победа|tushonk|тушонк|slivka|сливк|chips|"
    r"\bset\b|to'plam|muzqaymoq|zakvaska|закваска|hamirturush|ҳамиртуруш|oq solod|"
    r"qovurish uchun", re.I)

# (pattern on the normalised name, uz, ru) — first match wins, so the
# specific forms come before the general ones.
RULES: tuple[tuple[str, str, str], ...] = (
    # nuts, coconut
    (r"bodom.*po'st", "Maydalangan bodom mag'zi, po'sti bilan — 100%.",
     "Молотый миндаль с кожицей — 100%."),
    (r"bodom un", "Maydalangan bodom mag'zi — 100%.", "Молотый миндаль — 100%."),
    (r"kokos un", "Quritilgan va maydalangan, yog'i olingan kokos yong'og'i eti — 100%.",
     "Обезжиренная высушенная молотая мякоть кокоса — 100%."),
    (r"kokos qirind", "Quritilgan kokos yong'og'i eti — 100%.", "Высушенная мякоть кокоса — 100%."),
    (r"kokos shakar", "Kokos palmasi gullari shirasidan olingan shakar — 100%.",
     "Сахар из нектара цветков кокосовой пальмы — 100%."),
    (r"kokos yog'.*(virgin|vergin)", "Sovuq siqilgan, tozalanmagan kokos moyi (Extra Virgin) — 100%.",
     "Кокосовое масло холодного отжима, нерафинированное (Extra Virgin) — 100%."),
    (r"pista", "Pista mag'zi — 100%.", "Ядра фисташки — 100%."),
    # oils and dairy fat
    (r"zaytun.*(virgin|vergin|sovuq siq)", "Sovuq siqilgan zaytun moyi (Extra Virgin) — 100%.",
     "Оливковое масло холодного отжима (Extra Virgin) — 100%."),
    (r"ghee|гхи", "Sigir sutidan tayyorlangan tozalangan (eritilgan) sariyog' — 100%.",
     "Топлёное (очищенное) сливочное масло из коровьего молока — 100%."),
    (r"saryog'", "Sigir suti qaymog'idan pishib olingan sariyog' — 100%.",
     "Сливочное масло, сбитое из сливок коровьего молока — 100%."),
    # sweeteners
    (r"alluloz.*stev", "Alluloza, steviya ekstrakti (steviol glikozidlari, E960).",
     "Аллюлоза, экстракт стевии (стевиол-гликозиды, E960)."),
    (r"alluloz", "Alluloza (D-psikoza) — 100%.", "Аллюлоза (D-псикоза) — 100%."),
    (r"toza stevi", "Steviya barglari ekstrakti (steviol glikozidlari, E960) — 100%.",
     "Экстракт листьев стевии (стевиол-гликозиды, E960) — 100%."),
    (r"eritr", "Eritritol (E968) — 100%.", "Эритритол (E968) — 100%."),
    (r"asal", "Tabiiy asalari asali — 100%.", "Натуральный пчелиный мёд — 100%."),
    # seeds
    (r"chia", "Chia urug'i (Salvia hispanica) — 100%.", "Семена чиа (Salvia hispanica) — 100%."),
    (r"oq zig'ir un", "Oq (oltin) zig'ir urug'idan tortilgan un — 100%.",
     "Мука из семян белого (золотистого) льна — 100%."),
    (r"zig'ir un", "Zig'ir urug'idan tortilgan un — 100%.", "Мука из семян льна — 100%."),
    (r"zig'ir uru", "Zig'ir urug'i — 100%.", "Семена льна — 100%."),
    (r"oq kunjut", "Oq kunjut urug'i — 100%.", "Семена белого кунжута — 100%."),
    (r"qora kunjut", "Qora kunjut urug'i — 100%.", "Семена чёрного кунжута — 100%."),
    (r"qovoq uru", "Qovoq urug'i — 100%.", "Семена тыквы — 100%."),
    (r"sedana", "Qora sedana (Nigella sativa) urug'i — 100%.",
     "Семена чернушки (Nigella sativa) — 100%."),
    (r"rastaropsha un", "Rastaropsha (sut qushqo'nmasi) urug'idan tortilgan un — 100%.",
     "Мука из семян расторопши — 100%."),
    (r"rastaropsha", "Rastaropsha (sut qushqo'nmasi) urug'i — 100%.", "Семена расторопши — 100%."),
    (r"psill?ium (shel|qobiq)", "Psillium (Plantago ovata) urug'i qobig'i — 100%.",
     "Шелуха семян подорожника овального (псиллиум, Plantago ovata) — 100%."),
    (r"psill?ium", "Maydalangan psillium (Plantago ovata) urug'i qobig'i — 100%.",
     "Молотая шелуха семян псиллиума (Plantago ovata) — 100%."),
    # grains and flours
    (r"yashil grechka un", "Yashil (qovurilmagan) grechka donidan tortilgan un — 100%.",
     "Мука из зелёной (необжаренной) гречки — 100%."),
    (r"yashil grechka", "Yashil (qovurilmagan) grechka doni — 100%.",
     "Зелёная (необжаренная) гречневая крупа — 100%."),
    (r"grechka un", "Grechka donidan tortilgan un — 100%.", "Гречневая мука — 100%."),
    (r"no'xat un", "No'xat donidan tortilgan un — 100%.", "Нутовая мука — 100%."),
    (r"guruch un", "Guruch donidan tortilgan un — 100%.", "Рисовая мука — 100%."),
    (r"makkajo'xori un", "Makkajo'xori donidan tortilgan un — 100%.", "Кукурузная мука — 100%."),
    (r"ovsyanka un|suli un", "Suli donidan tortilgan un — 100%.", "Овсяная мука — 100%."),
    (r"suli yorma", "Suli yormasi — 100%.", "Овсяная крупа — 100%."),
    (r"javdar un", "Javdar donidan tortilgan un — 100%.", "Ржаная мука — 100%."),
    (r"arpa un", "Arpa donidan tortilgan un — 100%.", "Ячменная мука — 100%."),
    (r"polba", "Polba (spelta) bug'doyi donidan tortilgan un — 100%.",
     "Мука из полбы (спельты) — 100%."),
    (r"soya un", "Soya donidan tortilgan un — 100%.", "Соевая мука — 100%."),
    (r"kepakli bug'doy un", "Kepagi bilan tortilgan bug'doy uni (butun don uni) — 100%.",
     "Пшеничная мука с отрубями (цельнозерновая) — 100%."),
    (r"2-nav un|ikkinchi nav", "Ikkinchi navli bug'doy uni — 100%.", "Пшеничная мука второго сорта — 100%."),
    (r"kepak", "Bug'doy kepagi — 100%.", "Пшеничные отруби — 100%."),
    (r"basmati", "Basmati guruchi — 100%.", "Рис басмати — 100%."),
    (r"devzira", "Devzira guruchi (qizil, bo'yalmagan, yog'lanmagan) — 100%.",
     "Рис девзира (красный, неокрашенный, без масла) — 100%."),
    (r"bulgur", "Bulgur (bug'doy yormasi) — 100%.", "Булгур (пшеничная крупа) — 100%."),
    (r"fermentlangan solod", "Fermentlangan javdar solodi (undirilgan javdar donidan) — 100%.",
     "Ржаной ферментированный солод (из пророщенного зерна ржи) — 100%."),
    # the rest
    (r"himala|himolay", "Pushti himolay tuzi (tabiiy tosh tuz) — 100%.",
     "Розовая гималайская соль (натуральная каменная соль) — 100%."),
    (r"kakao nibs|kakao krupka", "Maydalangan kakao loviyasi (kakao nibs) — 100%.",
     "Дроблёные какао-бобы (какао-крупка) — 100%."),
    (r"koritsa|dolchin", "Dolchin (koritsa) — 100%.", "Корица — 100%."),
    (r"ksantan", "Ksantan kamedi (E415) — 100%.", "Ксантановая камедь (E415) — 100%."),
    (r"olma sirka", "Olma sharbatini tabiiy achitish yo'li bilan olingan sirka.",
     "Уксус, полученный естественным брожением яблочного сока."),
)
_RULES = tuple((re.compile(p, re.I), uz, ru) for p, uz, ru in RULES)
_APOSTROPHES = re.compile(r"[ʻʼ‘’`´]")


def normalise(name: str | None) -> str:
    """Lower-case Latin, one kind of apostrophe — "Зайтун ёғи" and
    "Zaytun yog‘i" read the same."""
    text = name or ""
    if re.search(r"[А-Яа-яЁёЎўҚқҒғҲҳ]", text):
        from translit import cyr_to_lat
        text = text + " " + cyr_to_lat(text)
    text = _APOSTROPHES.sub("'", text.lower())
    return re.sub(r"uru'g", "urug", text)          # "zig'ir uru'gi" — a typo in the catalogue


def suggest(name: str | None) -> tuple[str, str] | None:
    """(uz, ru) composition for a product name, or None when it has to come
    from the label."""
    text = normalise(name)
    if not text or _SKIP_RE.search(text):
        return None
    for rx, uz, ru in _RULES:
        if rx.search(text):
            return uz, ru
    return None


async def fill_missing() -> int:
    """Write a suggestion into every product nobody has given a composition
    yet (NULL). Returns how many were filled."""
    import database
    async with database.pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, name FROM products WHERE composition IS NULL")
        filled = 0
        for row in rows:
            found = suggest(row["name"])
            if not found:
                continue
            done = await conn.execute(
                "UPDATE products SET composition = $1, composition_ru = $2 "
                "WHERE id = $3 AND composition IS NULL", found[0], found[1], row["id"])
            filled += done.endswith(" 1")
    if filled:
        logger.info("Tarkib: %d ta mahsulotga kutubxonadan yozildi", filled)
    return filled


async def scheduler_loop() -> None:
    while True:
        try:
            await fill_missing()
        except Exception:
            logger.exception("Tarkib: avtomatik to'ldirish ishlamadi")
        await asyncio.sleep(CHECK_EVERY)
