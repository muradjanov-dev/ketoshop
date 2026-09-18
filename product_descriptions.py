"""Mahsulot tavsiflari kutubxonasi — har bir oila uchun uz + ru matn.

Nega kutubxona, nega qo'lda emas: do'konda 100 dan ortiq mahsulot bor va
ularning ko'pi bir oilaning turli o'lchovi ("Bodom uni 200gr", "Bodom uni
500gr", "Bodom uni 1000gr"). Bitta oilaga bitta yaxshi matn yozilsa, u
o'nlab mahsulotga yetadi va keyin qo'shiladigan yangisiga ham o'zi tushadi.

Oilani mahsulot NOMI bo'yicha aniqlaymiz — buning uchun tayyor mantiq bor
(personal_recommend.name_profile, reco_content.PROFILES), shuning uchun bu
yerda u qayta yozilmaydi, faqat chaqiriladi. Kirill bilan kiritilgan nom ham
lotinga o'girilib solishtiriladi — u yog'i o'sha funksiyaning ishi.

Matn shakli (egasining tanlovi, 2026-09-18):

    <bir-ikki jumla tanishtirish>

    💚 Foydasi:
    • ...
    • ...

    🍽 Ishlatilishi: ...
    📦 Saqlash: ...

Uzunlik 650 belgidan oshmasligi kerak: mahsulot kartochkasi Telegram'ga rasm
izohi bo'lib ketadi, u yerda jami 1024 belgi bor va qolgani narx, qoldiq,
chegirma va Keto qatorlariga ketadi (handlers/catalog.DESC_IN_CARD_MAX).

Kirill o'zbekcha alohida yozilmaydi — bot lotin matnni render paytida o'zi
o'giradi (locales.localize_product_text), xuddi qolgan hamma joydagidek.

Sog'liq haqidagi gaplar ataylab ehtiyotkor: "manba", "yordam beradi" —
"davolaydi" emas. Bu ovqat mahsuloti, dori emas.
"""
import logging
import re

logger = logging.getLogger(__name__)

# Form beats ingredient. The family matcher is built for the recommendation
# broadcast, where "Bodom yog'i" landing on the almond family is fine — the
# message talks about almonds either way. A description is not fine: the
# almond entry describes FLOUR, so an oil would have been sold with "mix a
# quarter of your wheat flour with it". These rules run first and route by
# what the product IS, not what it is made from.
#
# The apostrophe is followed by "i", whitespace or end-of-name on purpose:
# "yog'lanmagan" (unoiled, as in the Devzira rice) must NOT read as an oil.
_FORM_RULES = (
    ("oils", re.compile(r"yog['ʻ‘’](?:i\b|\s|$)|\bmoy\b|\bmaslo\b|масл|\boil\b", re.I)),
    ("pastes", re.compile(r"\bpasta|паста|urbech|урбеч", re.I)),
)


def _form_key(name: str) -> str | None:
    """The family a product's FORM puts it in, ignoring its ingredient."""
    for key, rx in _FORM_RULES:
        if rx.search(name or ""):
            return key
    return None

# Bo'lim sarlavhalari — barcha matnlar uchun bitta joyda.
_H = {
    "uz": {"benefits": "💚 Foydasi:", "use": "🍽 Ishlatilishi:", "keep": "📦 Saqlash:"},
    "ru": {"benefits": "💚 Польза:", "use": "🍽 Применение:", "keep": "📦 Хранение:"},
}


def _build(lang: str, intro: str, benefits: list[str], use: str, keep: str) -> str:
    h = _H[lang]
    lines = [intro, "", h["benefits"]]
    lines += [f"• {b}" for b in benefits]
    lines += ["", f"{h['use']} {use}", f"{h['keep']} {keep}"]
    return "\n".join(lines)


# key -> {"uz": {...}, "ru": {...}}; keys are reco_content.PROFILES keys.
FAMILY = {
    "almond_flour": {
        "uz": dict(
            intro="Bodomdan tortilgan mayin un — bug'doy unining keto va glyutensiz o'rnini bosadi.",
            benefits=["Uglevodi kam, oqsil va tolasi ko'p",
                      "Glyuten yo'q",
                      "E vitamini va magniy manbai",
                      "Pishiriqqa yong'oq ta'mi va yumshoqlik beradi"],
            use="non, keks, quymoq va pechene — bug'doy unining 1/4 qismini almashtiring, keyin ko'paytiring.",
            keep="og'zi yopiq idishda, salqin va qorong'i joyda; yozda muzlatgichda uzoqroq turadi."),
        "ru": dict(
            intro="Тонкая мука из миндаля — кето- и безглютеновая замена пшеничной.",
            benefits=["Мало углеводов, много белка и клетчатки",
                      "Без глютена",
                      "Источник витамина E и магния",
                      "Даёт выпечке ореховый вкус и мягкость"],
            use="хлеб, кексы, панкейки и печенье — начните с замены 1/4 пшеничной муки.",
            keep="в закрытой таре, в прохладном тёмном месте; летом дольше хранится в холодильнике."),
    },
    "coconut": {
        "uz": dict(
            intro="Kokosdan tayyorlangan mahsulot — shirin, tabiiy va keto dasturxonining doimiy a'zosi.",
            benefits=["Tolaga boy, tez to'ydiradi",
                      "Glyuten va sut yo'q",
                      "Tabiiy yog'lari energiya beradi",
                      "Pishiriq va shirinlikka kokos ta'mi qo'shadi"],
            use="pishiriq, smuzi, bo'tqa va uy shirinliklariga.",
            keep="quruq, salqin joyda; ochilgandan keyin og'zini mahkam yoping."),
        "ru": dict(
            intro="Кокосовый продукт — сладковатый, натуральный, постоянный гость кето-стола.",
            benefits=["Богат клетчаткой, быстро насыщает",
                      "Без глютена и молока",
                      "Натуральные жиры дают энергию",
                      "Добавляет выпечке и десертам кокосовый вкус"],
            use="выпечка, смузи, каши и домашние десерты.",
            keep="в сухом прохладном месте; после вскрытия плотно закрывайте."),
    },
    "flax": {
        "uz": dict(
            intro="Zig'ir — omega-3 va tolaning eng arzon manbalaridan biri.",
            benefits=["O'simlik omega-3 (ALA) manbai",
                      "Tolasi ko'p — hazmga yordam beradi",
                      "Uglevodi juda kam",
                      "Tuxum o'rniga bog'lovchi bo'la oladi"],
            use="1 osh qoshiq maydalangan zig'ir + 3 osh qoshiq suv = 1 dona tuxum o'rni; bo'tqa va pishiriqqa ham.",
            keep="maydalangani tez achiydi — muzlatgichda, og'zi yopiq idishda saqlang."),
        "ru": dict(
            intro="Лён — один из самых доступных источников омега-3 и клетчатки.",
            benefits=["Источник растительной омега-3 (ALA)",
                      "Много клетчатки — помогает пищеварению",
                      "Очень мало углеводов",
                      "Заменяет яйцо как связующее"],
            use="1 ст. л. молотого льна + 3 ст. л. воды = 1 яйцо; также в каши и выпечку.",
            keep="молотый быстро горкнет — храните в холодильнике в закрытой таре."),
    },
    "chia": {
        "uz": dict(
            intro="Mayda urug', suvda bo'kib jelega aylanadi — to'yimli va bir necha soat och qoldirmaydi.",
            benefits=["Omega-3 va tolaga boy",
                      "Kalsiy va magniy manbai",
                      "O'z vaznidan 10 barobar suv ushlaydi",
                      "Ta'msiz — har qanday taomga qo'shiladi"],
            use="2 osh qoshiq chia + 150 ml sut yoki suv, 20 daqiqa turing — tayyor chia-puding.",
            keep="quruq, salqin joyda, og'zi yopiq idishda."),
        "ru": dict(
            intro="Мелкие семена, которые в жидкости превращаются в гель — сытно и надолго.",
            benefits=["Богаты омега-3 и клетчаткой",
                      "Источник кальция и магния",
                      "Удерживают в 10 раз больше своего веса воды",
                      "Нейтральный вкус — подходят к любому блюду"],
            use="2 ст. л. чиа + 150 мл молока или воды, настоять 20 минут — готов чиа-пудинг.",
            keep="в сухом прохладном месте, в закрытой таре."),
    },
    "buckwheat": {
        "uz": dict(
            intro="Qovurilmagan yashil grechka — oddiy grechkadan farqli o'laroq unib chiqadi va foydasi to'liq saqlanadi.",
            benefits=["To'liq o'simlik oqsili",
                      "Glyuten yo'q",
                      "Temir va magniyga boy",
                      "Glikemik indeksi past"],
            use="bo'tqa, unib chiqargan holda salatga; uni esa non va quymoq uchun.",
            keep="quruq, salqin va qorong'i joyda."),
        "ru": dict(
            intro="Необжаренная зелёная гречка — в отличие от обычной, прорастает и сохраняет всю пользу.",
            benefits=["Полноценный растительный белок",
                      "Без глютена",
                      "Богата железом и магнием",
                      "Низкий гликемический индекс"],
            use="каша, пророщенная — в салат; мука — для хлеба и панкейков.",
            keep="в сухом, прохладном и тёмном месте."),
    },
    "rastaropsha": {
        "uz": dict(
            intro="Sutgul (rastaropsha) — jigarni qo'llab-quvvatlovchi silimarin bilan mashhur o'simlik.",
            benefits=["Silimarin manbai",
                      "Antioksidantlarga boy",
                      "Tolasi ko'p",
                      "Ta'mi yengil — taomga bilinmaydi"],
            use="bo'tqa, smuzi va pishiriqqa kuniga 1-2 osh qoshiq qo'shing.",
            keep="quruq, salqin joyda; og'zi yopiq idishda."),
        "ru": dict(
            intro="Расторопша — растение, известное силимарином, который поддерживает печень.",
            benefits=["Источник силимарина",
                      "Богата антиоксидантами",
                      "Много клетчатки",
                      "Мягкий вкус — не меняет блюдо"],
            use="1–2 ст. л. в день в каши, смузи и выпечку.",
            keep="в сухом прохладном месте, в закрытой таре."),
    },
    "pastes": {
        "uz": dict(
            intro="Faqat maydalangan mag'izdan tayyorlangan pasta — shakar ham, palma yog'i ham qo'shilmagan.",
            benefits=["Tarkibi bitta: mag'izning o'zi",
                      "Sog'lom yog' va oqsil manbai",
                      "Qo'shilgan shakar yo'q",
                      "Bir qoshiq uzoq to'ydiradi"],
            use="non va olma bilan, bo'tqaga, smuzi va uy shirinliklariga.",
            keep="salqin joyda; yog'i ajralsa, aralashtirib yuboring — bu tabiiy holat."),
        "ru": dict(
            intro="Паста только из перемолотых ядер — без сахара и пальмового масла.",
            benefits=["Состав из одного ингредиента",
                      "Источник полезных жиров и белка",
                      "Без добавленного сахара",
                      "Одна ложка насыщает надолго"],
            use="к хлебу и яблоку, в кашу, смузи и домашние десерты.",
            keep="в прохладном месте; если масло отслоилось — просто перемешайте."),
    },
    "nuts": {
        "uz": dict(
            intro="Tabiiy mag'iz — shakarsiz, tuzsiz, hech narsa qo'shilmagan.",
            benefits=["Sog'lom yog' va oqsil manbai",
                      "Magniy va E vitamini",
                      "Uglevodi kam — ketoga mos",
                      "Qulay gazak: bir hovuch yetarli"],
            use="gazak sifatida, salat va bo'tqaga, pishiriqqa maydalab.",
            keep="salqin, qorong'i joyda; ochilgach og'zi yopiq idishda."),
        "ru": dict(
            intro="Натуральные ядра — без сахара, соли и добавок.",
            benefits=["Источник полезных жиров и белка",
                      "Магний и витамин E",
                      "Мало углеводов — подходит для кето",
                      "Удобный перекус: хватает горсти"],
            use="как перекус, в салаты и каши, молотые — в выпечку.",
            keep="в прохладном тёмном месте; после вскрытия — в закрытой таре."),
    },
    "chickpea": {
        "uz": dict(
            intro="No'xatdan tortilgan un — oqsili ko'p, glyuteni yo'q, ta'mi yengil yong'oqsimon.",
            benefits=["Oqsil va tolaga boy",
                      "Glyuten yo'q",
                      "Glikemik indeksi past",
                      "Xamirni yaxshi bog'laydi"],
            use="falafel, kotlet, quymoq va non; qalinlashtirgich sifatida sousga.",
            keep="quruq, salqin joyda, og'zi yopiq idishda."),
        "ru": dict(
            intro="Мука из нута — много белка, без глютена, с лёгким ореховым вкусом.",
            benefits=["Богата белком и клетчаткой",
                      "Без глютена",
                      "Низкий гликемический индекс",
                      "Хорошо связывает тесто"],
            use="фалафель, котлеты, панкейки и хлеб; как загуститель для соусов.",
            keep="в сухом прохладном месте, в закрытой таре."),
    },
    "rice_flour": {
        "uz": dict(
            intro="Guruch uni — glyutensiz pishiriqning yengil va neytral asosi.",
            benefits=["Glyuten yo'q",
                      "Ta'mi neytral — taom ta'mini o'zgartirmaydi",
                      "Oson hazm bo'ladi",
                      "Sousga yaxshi qalinlik beradi"],
            use="quymoq, keks va non; sous va qaymoqli taomlarni qalinlashtirishga.",
            keep="quruq, salqin joyda, og'zi yopiq idishda."),
        "ru": dict(
            intro="Рисовая мука — лёгкая нейтральная основа безглютеновой выпечки.",
            benefits=["Без глютена",
                      "Нейтральный вкус — не меняет блюдо",
                      "Легко усваивается",
                      "Хорошо загущает соусы"],
            use="панкейки, кексы и хлеб; для загущения соусов и сливочных блюд.",
            keep="в сухом прохладном месте, в закрытой таре."),
    },
    "diet_rice": {
        "uz": dict(
            intro="Dietik yorma — oq guruchdan farqli o'laroq qobig'i va foydasi saqlangan.",
            benefits=["Tolasi ko'p, uzoq to'ydiradi",
                      "Glikemik indeksi pastroq",
                      "Guruh B vitaminlari va magniy",
                      "Garnir sifatida universal"],
            use="garnir, plov va salat uchun; 1 stakan yormaga 2 stakan suv.",
            keep="quruq, salqin joyda; og'zi yopiq idishda."),
        "ru": dict(
            intro="Диетическая крупа — в отличие от белого риса, сохраняет оболочку и пользу.",
            benefits=["Много клетчатки, насыщает надолго",
                      "Более низкий гликемический индекс",
                      "Витамины группы B и магний",
                      "Универсальный гарнир"],
            use="гарнир, плов и салаты; на 1 стакан крупы — 2 стакана воды.",
            keep="в сухом прохладном месте, в закрытой таре."),
    },
    "pp_flour": {
        "uz": dict(
            intro="To'g'ri ovqatlanish uchun un — oq unning oqartirilmagan, foydasi saqlangan o'rnidoshi.",
            benefits=["Tolasi oq undan ko'p",
                      "Vitamin va minerallari saqlangan",
                      "Uzoqroq to'ydiradi",
                      "Kundalik pishiriqqa mos"],
            use="non, quymoq, keks; oq unning yarmini almashtirib boshlang.",
            keep="quruq, salqin joyda; og'zi yopiq idishda."),
        "ru": dict(
            intro="Мука для правильного питания — неотбеленная замена белой, с сохранённой пользой.",
            benefits=["Клетчатки больше, чем в белой",
                      "Сохранены витамины и минералы",
                      "Насыщает дольше",
                      "Подходит для ежедневной выпечки"],
            use="хлеб, панкейки, кексы; начните с замены половины белой муки.",
            keep="в сухом прохладном месте, в закрытой таре."),
    },
    "bran": {
        "uz": dict(
            intro="Don qobig'i — kaloriyasi kam, tolasi esa juda ko'p.",
            benefits=["Tolaning eng zich manbalaridan",
                      "Hazmga yordam beradi",
                      "Kaloriyasi kam",
                      "Kam miqdorda ham to'yimli"],
            use="kuniga 1-2 osh qoshiq: kefir, bo'tqa yoki xamirga; ko'p suv iching.",
            keep="quruq, salqin joyda, og'zi yopiq idishda."),
        "ru": dict(
            intro="Оболочка зерна — мало калорий и очень много клетчатки.",
            benefits=["Один из самых концентрированных источников клетчатки",
                      "Помогает пищеварению",
                      "Низкая калорийность",
                      "Сытно даже в малом количестве"],
            use="1–2 ст. л. в день: в кефир, кашу или тесто; пейте больше воды.",
            keep="в сухом прохладном месте, в закрытой таре."),
    },
    "sourdough": {
        "uz": dict(
            intro="Uy noni uchun tabiiy asos — sanoat xamirturushisiz, haqiqiy tandir ta'mi bilan.",
            benefits=["Tabiiy achish",
                      "Non uzoqroq yumshoq turadi",
                      "Ta'mi boy va chuqur",
                      "Oshqozonga yengilroq"],
            use="non xamiriga qadoqdagi nisbat bo'yicha; xamirni 4-12 soat tindiring.",
            keep="salqin va quruq joyda; ochilgach og'zini mahkam yoping."),
        "ru": dict(
            intro="Натуральная основа для домашнего хлеба — без промышленных дрожжей.",
            benefits=["Натуральное брожение",
                      "Хлеб дольше остаётся мягким",
                      "Богатый глубокий вкус",
                      "Легче для желудка"],
            use="в тесто по пропорции на упаковке; расстойка 4–12 часов.",
            keep="в прохладном сухом месте; после вскрытия плотно закрывайте."),
    },
    "sesame": {
        "uz": dict(
            intro="Kunjut — kalsiyning eng zich o'simlik manbalaridan biri.",
            benefits=["Kalsiyga juda boy",
                      "Sog'lom yog' va oqsil",
                      "Temir va magniy manbai",
                      "Taomga yong'oq ta'mi beradi"],
            use="salat, non va taomlarga sepib; maydalab tahiniy tayyorlash mumkin.",
            keep="salqin, qorong'i joyda; og'zi yopiq idishda."),
        "ru": dict(
            intro="Кунжут — один из самых богатых растительных источников кальция.",
            benefits=["Очень много кальция",
                      "Полезные жиры и белок",
                      "Источник железа и магния",
                      "Придаёт блюдам ореховый вкус"],
            use="посыпать салаты, хлеб и блюда; из молотого получается тахини.",
            keep="в прохладном тёмном месте, в закрытой таре."),
    },
    "pumpkin_seed": {
        "uz": dict(
            intro="Qovoq urug'i — magniy va rux manbai, shirinsiz gazak uchun ideal.",
            benefits=["Magniyga boy",
                      "Rux manbai",
                      "Oqsili ko'p, uglevodi kam",
                      "Qovurilmagan — foydasi to'liq"],
            use="gazak sifatida bir hovuch; salat, bo'tqa va non ustiga.",
            keep="salqin, qorong'i joyda; og'zi yopiq idishda."),
        "ru": dict(
            intro="Тыквенные семечки — источник магния и цинка, отличный несладкий перекус.",
            benefits=["Богаты магнием",
                      "Источник цинка",
                      "Много белка, мало углеводов",
                      "Необжаренные — польза сохранена"],
            use="горсть как перекус; в салаты, каши и на хлеб.",
            keep="в прохладном тёмном месте, в закрытой таре."),
    },
    "sedana": {
        "uz": dict(
            intro="Qora sedana (qora zira) — Sharqda asrlar davomida qadrlangan urug'.",
            benefits=["Timoxinon manbai",
                      "Antioksidantlarga boy",
                      "Immunitetni qo'llab-quvvatlaydi",
                      "Yog'i ham, urug'i ham ishlatiladi"],
            use="kuniga 1/2-1 choy qoshiq: asal bilan, non va salatga.",
            keep="quruq, salqin va qorong'i joyda."),
        "ru": dict(
            intro="Чёрный тмин — семена, которые на Востоке ценят веками.",
            benefits=["Источник тимохинона",
                      "Богат антиоксидантами",
                      "Поддерживает иммунитет",
                      "Используются и семена, и масло"],
            use="1/2–1 ч. л. в день: с мёдом, в хлеб и салаты.",
            keep="в сухом, прохладном и тёмном месте."),
    },
    "fiber_supp": {
        "uz": dict(
            intro="Tola va tabiiy qalinlashtirgich — glyutensiz xamirni bir-biriga bog'laydi.",
            benefits=["Eruvchan tolaga juda boy",
                      "Hazm va to'qlik hissiga yordam beradi",
                      "Glyutensiz xamirni bog'laydi",
                      "Kam miqdori ham yetarli"],
            use="non xamiriga 1-2 choy qoshiq; ichimlikka qo'shsangiz darhol iching va ko'p suv iching.",
            keep="quruq joyda; namdan saqlang."),
        "ru": dict(
            intro="Клетчатка и натуральный загуститель — связывает безглютеновое тесто.",
            benefits=["Очень много растворимой клетчатки",
                      "Помогает пищеварению и насыщению",
                      "Связывает тесто без глютена",
                      "Достаточно малого количества"],
            use="1–2 ч. л. в тесто; в напиток — выпивайте сразу и пейте больше воды.",
            keep="в сухом месте, беречь от влаги."),
    },
    "keto_icecream": {
        "uz": dict(
            intro="Shakarsiz muzqaymoq — ta'mi odatdagidek, lekin uglevodi minimal.",
            benefits=["Qo'shilgan shakar yo'q",
                      "Uglevodi kam — ketoga mos",
                      "Tabiiy shirinlashtirgich bilan",
                      "Qondagi shakarni keskin ko'tarmaydi"],
            use="muzlatgichdan olib 5 daqiqa turing — yumshab, ta'mi ochiladi.",
            keep="muzlatkichda −18°C; erigach qayta muzlatmang."),
        "ru": dict(
            intro="Мороженое без сахара — вкус привычный, углеводов минимум.",
            benefits=["Без добавленного сахара",
                      "Мало углеводов — подходит для кето",
                      "На натуральном подсластителе",
                      "Не даёт резкого скачка сахара"],
            use="достаньте за 5 минут до подачи — станет мягче и вкуснее.",
            keep="в морозилке при −18°C; не замораживайте повторно."),
    },
    "cacao": {
        "uz": dict(
            intro="Qo'shilgan shakarsiz kakao — achchiq, chuqur ta'm va antioksidantlar.",
            benefits=["Antioksidantlarga boy",
                      "Magniy manbai",
                      "Qo'shilgan shakar yo'q",
                      "Kayfiyatga yaxshi ta'sir qiladi"],
            use="issiq shokolad, pishiriq va keto shirinliklarga; bir bo'lak kunlik gazak sifatida.",
            keep="quruq, salqin joyda; yorug'likdan saqlang."),
        "ru": dict(
            intro="Какао без добавленного сахара — горький глубокий вкус и антиоксиданты.",
            benefits=["Богат антиоксидантами",
                      "Источник магния",
                      "Без добавленного сахара",
                      "Хорошо влияет на настроение"],
            use="горячий шоколад, выпечка и кето-десерты; кусочек — как перекус.",
            keep="в сухом прохладном месте, беречь от света."),
    },
    "fish": {
        "uz": dict(
            intro="Baliq mahsuloti — tayyor oqsil va omega-3 manbai, pishirish shart emas.",
            benefits=["Sifatli oqsil",
                      "Omega-3 yog' kislotalari",
                      "Uglevodi yo'q — ketoga mos",
                      "Tayyor: ochdingiz va yedingiz"],
            use="salat, sendvich va garnir bilan; issiq taomga ham qo'shsa bo'ladi.",
            keep="ochilmagan holda salqin joyda; ochilgach muzlatgichda 1-2 kun."),
        "ru": dict(
            intro="Рыбный продукт — готовый белок и омега-3, готовить не нужно.",
            benefits=["Качественный белок",
                      "Омега-3 жирные кислоты",
                      "Без углеводов — подходит для кето",
                      "Готов к употреблению"],
            use="в салаты, сэндвичи и к гарниру; можно добавить в горячее.",
            keep="закрытым — в прохладном месте; после вскрытия 1–2 дня в холодильнике."),
    },
    "oils": {
        "uz": dict(
            intro="Sog'lom yog' — keto va to'g'ri ovqatlanishning asosiy energiya manbai.",
            benefits=["Sifatli yog' kislotalari",
                      "Uglevodi yo'q",
                      "Yog'da eriydigan vitaminlarni o'zlashtirishga yordam beradi",
                      "Taomga to'liq ta'm beradi"],
            use="salatga sovuq holda, pishirishga — qadoqdagi harorat ko'rsatmasi bo'yicha.",
            keep="qorong'i, salqin joyda; og'zi yopiq shishada."),
        "ru": dict(
            intro="Полезный жир — основной источник энергии на кето и ПП.",
            benefits=["Качественные жирные кислоты",
                      "Без углеводов",
                      "Помогает усваивать жирорастворимые витамины",
                      "Раскрывает вкус блюда"],
            use="в салат холодным, для готовки — по температуре, указанной на упаковке.",
            keep="в тёмном прохладном месте, в закрытой бутылке."),
    },
    "vinegar": {
        "uz": dict(
            intro="Tabiiy achitilgan olma sirkasi — filtrlanmagan, «onasi» bilan.",
            benefits=["Tabiiy achish mahsuloti",
                      "Ovqat hazmiga yordam beradi",
                      "Salatga yengil nordonlik beradi",
                      "Qo'shimcha kimyo yo'q"],
            use="1 choy qoshiq bir stakan suvga, ovqatdan oldin; salat souslariga ham.",
            keep="salqin, qorong'i joyda; cho'kma bo'lsa — bu tabiiy holat."),
        "ru": dict(
            intro="Натурально сброженный яблочный уксус — нефильтрованный, с «маткой».",
            benefits=["Продукт натурального брожения",
                      "Помогает пищеварению",
                      "Даёт салату мягкую кислинку",
                      "Без лишней химии"],
            use="1 ч. л. на стакан воды перед едой; и в заправки для салатов.",
            keep="в прохладном тёмном месте; осадок — это нормально."),
    },
    "salt": {
        "uz": dict(
            intro="Tozalanmagan tabiiy tuz — minerallari olib tashlanmagan.",
            benefits=["80 dan ortiq mikroelement",
                      "Oqartirilmagan va qo'shimchasiz",
                      "Keto paytida elektrolit muvozanatiga yordam beradi",
                      "Ta'mi yumshoqroq"],
            use="oddiy tuz o'rniga har qanday taomga; keto boshida bir chimdim ko'proq.",
            keep="quruq joyda; namdan saqlang."),
        "ru": dict(
            intro="Нерафинированная природная соль — минералы не удалены.",
            benefits=["Более 80 микроэлементов",
                      "Без отбеливания и добавок",
                      "Помогает держать электролиты на кето",
                      "Мягче на вкус"],
            use="вместо обычной соли в любые блюда; в начале кето — чуть больше.",
            keep="в сухом месте, беречь от влаги."),
    },
    "sweeteners": {
        "uz": dict(
            intro="Shakarning tabiiy o'rnini bosadi — ta'mi xuddi shakardek, lekin organizm uni singdirmaydi.",
            benefits=["Kaloriyasi yo'q yoki juda kam",
                      "Qondagi shakarni ko'tarmaydi",
                      "Tishni buzmaydi",
                      "Keto va diabetga mos"],
            use="choy, qahva va pishiriqqa — shakar o'rniga qadoqdagi nisbat bo'yicha.",
            keep="quruq, salqin joyda; og'zi yopiq idishda."),
        "ru": dict(
            intro="Натуральная замена сахару — вкус тот же, но организм его не усваивает.",
            benefits=["Без калорий или почти без них",
                      "Не поднимает сахар в крови",
                      "Не разрушает зубы",
                      "Подходит для кето и диабета"],
            use="в чай, кофе и выпечку — вместо сахара, по пропорции на упаковке.",
            keep="в сухом прохладном месте, в закрытой таре."),
    },
    "honey": {
        "uz": dict(
            intro="Tabiiy asal — isitilmagan, suyultirilmagan, tog' o'tloqlaridan.",
            benefits=["Tabiiy antioksidantlar",
                      "Qo'shimcha shakar yo'q",
                      "Tomoq va immunitetga yordam beradi",
                      "Yorqin, tabiiy ta'm"],
            use="choy va bo'tqaga, non bilan; issiq suvga solmang — foydasi kamayadi.",
            keep="xona haroratida, qorong'i joyda; qotib qolsa — bu tabiiylik belgisi."),
        "ru": dict(
            intro="Натуральный мёд — без нагрева и разбавления, с горных лугов.",
            benefits=["Натуральные антиоксиданты",
                      "Без добавленного сахара",
                      "Поддерживает горло и иммунитет",
                      "Яркий природный вкус"],
            use="в чай и кашу, с хлебом; не добавляйте в кипяток — польза теряется.",
            keep="при комнатной температуре, в тёмном месте; засахаривание — признак натуральности."),
    },
    "spices": {
        "uz": dict(
            intro="Tabiiy ziravor — taomga ta'm beradi, tuz va shakarga ehtiyojni kamaytiradi.",
            benefits=["Antioksidantlarga boy",
                      "Kaloriyasi yo'q",
                      "Hazmga yordam beradi",
                      "Oddiy taomni qayta ochadi"],
            use="issiq taom, choy va pishiriqqa bir chimdim; oxirida qo'shsangiz hidi kuchliroq.",
            keep="og'zi yopiq idishda, quruq va qorong'i joyda."),
        "ru": dict(
            intro="Натуральная специя — раскрывает вкус и снижает потребность в соли и сахаре.",
            benefits=["Богата антиоксидантами",
                      "Без калорий",
                      "Помогает пищеварению",
                      "Преображает простое блюдо"],
            use="щепотку в горячее, чай и выпечку; добавленная в конце — ароматнее.",
            keep="в закрытой таре, в сухом тёмном месте."),
    },
}

# Used when a product's name matches no family — deliberately honest rather
# than inventing properties for something we can't identify.
DEFAULT = {
    "uz": dict(
        intro="Ketoshop tanlovidagi tabiiy mahsulot — sog'lom ovqatlanish uchun.",
        benefits=["Tabiiy tarkib",
                  "Keto va to'g'ri ovqatlanishga mos",
                  "Sinovdan o'tgan yetkazib beruvchidan"],
        use="kundalik taomlaringizga qo'shing.",
        keep="quruq, salqin joyda; og'zi yopiq idishda."),
    "ru": dict(
        intro="Натуральный продукт из подборки Ketoshop — для здорового питания.",
        benefits=["Натуральный состав",
                  "Подходит для кето и ПП",
                  "От проверенного поставщика"],
        use="добавляйте в привычные блюда.",
        keep="в сухом прохладном месте, в закрытой таре."),
}


def family_key(product_name: str) -> str | None:
    """Which family this product name belongs to, or None.

    Reuses personal_recommend.name_profile — the same matcher the
    recommendation broadcast has used since 2026-09-17, including its
    Cyrillic-to-Latin fallback. Imported lazily: that module pulls in the
    whole reco content library, which the admin panel has no reason to load
    until someone actually asks for descriptions.
    """
    form = _form_key(product_name)
    if form:
        return form
    try:
        from personal_recommend import name_profile
    except Exception:
        logger.exception("tavsif: oila aniqlagichni yuklab bo'lmadi")
        return None
    profile = name_profile(product_name or "")
    return profile["key"] if profile else None


def describe(product_name: str) -> tuple[str, str, str | None]:
    """(uz, ru, family_key) for this product name.

    `family_key` is None when nothing matched and the generic text was used —
    the caller can surface that, so a product nobody recognised is visible
    rather than silently given a vague description.
    """
    key = family_key(product_name)
    entry = FAMILY.get(key) if key else None
    if entry is None:
        entry = DEFAULT
        key = None
    return _build("uz", **entry["uz"]), _build("ru", **entry["ru"]), key
