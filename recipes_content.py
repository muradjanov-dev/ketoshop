"""
Saytdagi retseptlar — egasi so'rovi 2026-10-08: "har 2 kunda 1 ta retsept
beramiz", rasm, qadamma-qadam va mahsulot tafsilotlari bilan, har retsept
ostida "🛒 Barcha masalliqlarni savatga".

Har bir retsept:
  slug         — rasm nomi ham shu: webapp/recipes/<slug>.jpg (/static/recipes/...)
  title/intro  — uz + ru (kirillcha o'zbekcha uz dan transliteratsiya qilinadi)
  minutes      — umumiy vaqt; `rest` — kutish (tun bo'yi va h.k.), bo'lsa
  servings     — "10 bo'lak", "2 kishilik"
  per_serving  — taxminiy: sof uglevod (g) va kkal, bir porsiya/bo'lakka
  ingredients  — amount + name; `match` bo'lsa — bu Ketoshop mahsuloti:
                 sayt uni katalogdan topib (recipes.resolve), rasm, joriy narx
                 va "savatga" tugmasini qo'shadi; `why` — nega aynan shu
                 mahsulot. `match` yo'q — uydan (tuxum, tovuq, suv).
  steps, tip

`match` — mahsulot NOMIDA qidiriladigan so'zlar guruhlari: guruhdagi hamma
so'z bo'lsa — mos. Lotin va kirill yozuvi ikkalasi beriladi, chunki katalogda
ikkalasi ham uchraydi. Birinchi topilgan guruh ishlatiladi; bir nechta qadoq
bo'lsa (200 g / 500 g / 1 kg) — omborda bor eng hamyonbopi savatga tushadi.

Rasm promptlari (Higgsfield, gpt_image_2_5) retsept matniga mos yozilgan:
rasmda ko'rinadigan narsa (kunjut, kokos, sous...) retseptda ham bor.
"""

_ALMOND = [["bodom", "uni"], ["бодом", "уни"]]
_PSYLLIUM_FLOUR = [["psillium", "uni"], ["псиллиум", "уни"]]
_PSYLLIUM_ANY = [["psillium"], ["псиллиум"]]
_SALT = [["himalay"], ["ҳималай"], ["гималай"]]
_VINEGAR = [["olma", "sirka"], ["олма", "сирка"]]
_SESAME_WHITE = [["oq", "kunjut"], ["оқ", "кунжут"]]
_SESAME_BLACK = [["qora", "kunjut"], ["қора", "кунжут"]]
_CHIA = [["chia"], ["чиа"]]
_COCONUT_FLAKES = [["kokos", "qirindi"], ["кокос", "қиринди"], ["kokos", "chips"], ["кокос", "чипс"]]
_NIBS = [["kakao", "nibs"], ["какао", "нибс"]]
_ERYTHRITOL = [["eritritol"], ["эритритол"]]
_GHEE = [["ghee"], ["гхи"]]
_FLAX_SEEDS = [["zig'ir", "urug'"], ["зиғир", "уруғ"]]
_PUMPKIN = [["qovoq", "urug'"], ["қовоқ", "уруғ"]]
_OLIVE = [["zaytun", "virgin"], ["зайтун", "virgin"], ["zaytun", "sovuq"], ["зайтун", "совуқ"]]


def _i(amount_uz, amount_ru, name_uz, name_ru, match=None, why_uz=None, why_ru=None):
    item = {"amount": {"uz": amount_uz, "ru": amount_ru}, "name": {"uz": name_uz, "ru": name_ru}}
    if match:
        item["match"] = match
    if why_uz:
        item["why"] = {"uz": why_uz, "ru": why_ru}
    return item


def _s(uz, ru):
    return {"uz": uz, "ru": ru}


RECIPES = [
    {
        "slug": "bodom-noni",
        "title": _s("Glyutensiz bodom noni", "Безглютеновый миндальный хлеб"),
        "intro": _s(
            "Yumshoq, g'ovak va to'yimli — oddiy nonni sog'inmaysiz. Bodom uni va psillium "
            "xamirni ushlab turadi, kunjut esa qobig'iga mazali qarsillash beradi.",
            "Мягкий, пористый и сытный — по обычному хлебу скучать не придётся. Миндальная "
            "мука и псиллиум держат тесто, а кунжут даёт хрустящую корочку."),
        "minutes": 70,
        "servings": _s("10 bo'lak", "10 ломтиков"),
        "per_serving": {"carbs": 2.5, "kcal": 170},
        "ingredients": [
            _i("200 g", "200 г", "Bodom uni", "Миндальная мука", _ALMOND,
               "Asosiy un — past uglevodli, oqsil va sog'lom yog'larga boy.",
               "Основная мука — мало углеводов, много белка и полезных жиров."),
            _i("40 g", "40 г", "Psillium uni", "Псиллиум (мука)", _PSYLLIUM_FLOUR,
               "Glyuten o'rnini bosadi: non ko'tariladi va ushalmaydi.",
               "Заменяет глютен: хлеб поднимается и не крошится."),
            _i("2 osh q.", "2 ст.л.", "Olma sirkasi", "Яблочный уксус", _VINEGAR,
               "Soda bilan birga xamirni ko'pchitadi.",
               "Вместе с содой делает тесто пышным."),
            _i("2 osh q.", "2 ст.л.", "Oq kunjut (ustiga)", "Белый кунжут (сверху)", _SESAME_WHITE,
               "Qobiqqa qarsillash va yong'oqsimon ta'm beradi.",
               "Хрустящая корочка и ореховый вкус."),
            _i("1 ch.q.", "1 ч.л.", "Himalay tuzi", "Гималайская соль", _SALT,
               "Ta'mni ochadi, foydali minerallarga boy.",
               "Раскрывает вкус, богата минералами."),
            _i("3 ta", "3 шт", "Tuxum", "Яйца"),
            _i("250 ml", "250 мл", "Qaynoq suv", "Кипяток"),
            _i("1 ch.q.", "1 ч.л.", "Soda", "Сода"),
        ],
        "steps": [
            _s("Pechni 180°C ga qizdiring, qolipga pergament to'shang.",
               "Разогрейте духовку до 180°C, застелите форму пергаментом."),
            _s("Bodom uni, psillium uni, soda va tuzni idishda yaxshilab aralashtiring.",
               "Хорошо смешайте миндальную муку, псиллиум, соду и соль."),
            _s("Tuxum va olma sirkasini qo'shib, qoshiq bilan aralashtiring — xamir quyuq bo'ladi.",
               "Добавьте яйца и уксус, перемешайте ложкой — тесто будет густым."),
            _s("Qaynoq suvni quyib, darhol 30 soniya aralashtiring: psillium suvni shimib, "
               "xamir yumshoq loydek bo'ladi.",
               "Влейте кипяток и сразу мешайте 30 секунд: псиллиум впитает воду, тесто станет "
               "мягким, как пластилин."),
            _s("Ho'l qo'l bilan non shaklini bering, qolipga soling va ustiga kunjut seping.",
               "Мокрыми руками сформируйте буханку, выложите в форму и посыпьте кунжутом."),
            _s("50–55 daqiqa pishiring. Tayyor nonning tagiga chertilsa, bo'g'iq ovoz chiqadi.",
               "Выпекайте 50–55 минут. Готовый хлеб глухо звучит, если постучать по донышку."),
            _s("Kesishdan oldin to'liq soviting (kamida 1 soat) — issiqligida ichi yopishqoq bo'ladi.",
               "Перед нарезкой полностью остудите (минимум час) — горячий мякиш липкий."),
        ],
        "tip": _s("Xamirga zig'ir yoki qovoq urug'i qo'shsangiz, yanada to'yimli bo'ladi. "
                  "Muzlatgichda 1 oygacha saqlanadi.",
                  "Добавьте в тесто семена льна или тыквы — станет ещё сытнее. "
                  "В морозилке хранится до месяца."),
        "image_prompt": "gluten-free almond flour and psyllium bread loaf, sesame on top, slices, "
                        "pink salt, apple cider vinegar, light oak board",
    },
    {
        "slug": "chia-puding",
        "title": _s("Kokosli chia pudingi kakao nibs bilan", "Кокосовый пудинг чиа с какао-крупкой"),
        "intro": _s(
            "Kechqurun 5 daqiqada tayyorlab qo'yasiz — ertalab nonushta tayyor turadi. "
            "Shakarsiz, lekin shirin, ustida esa qarsildoq kakao nibs.",
            "Готовится вечером за 5 минут — утром завтрак уже ждёт. Без сахара, но сладкий, "
            "а сверху хрустящая какао-крупка."),
        "minutes": 10,
        "rest": _s("+ muzlatkichda 4 soat yoki tun bo'yi", "+ 4 часа или ночь в холодильнике"),
        "servings": _s("2 kishilik", "2 порции"),
        "per_serving": {"carbs": 6, "kcal": 390},
        "ingredients": [
            _i("50 g", "50 г", "Chia urug'i", "Семена чиа", _CHIA,
               "Tolaga boy: suyuqlikni shimib puding bo'ladi va uzoq to'q tutadi.",
               "Много клетчатки: впитывает жидкость, превращаясь в пудинг, и надолго насыщает."),
            _i("20 g", "20 г", "Kokos qirindisi", "Кокосовая стружка", _COCONUT_FLAKES,
               "Qovurilgach xushbo'y va qarsildoq bo'ladi.",
               "После обжарки — ароматная и хрустящая."),
            _i("15 g", "15 г", "Kakao nibs", "Какао-крупка", _NIBS,
               "Shakarsiz shokolad ta'mi va antioksidantlar.",
               "Шоколадный вкус без сахара и антиоксиданты."),
            _i("1–2 osh q.", "1–2 ст.л.", "Eritritol", "Эритрит", _ERYTHRITOL,
               "Shakar o'rnida — qonda shakarni ko'tarmaydi.",
               "Вместо сахара — не повышает сахар в крови."),
            _i("200 ml", "200 мл", "Kokos suti", "Кокосовое молоко"),
            _i("100 ml", "100 мл", "Suv yoki sut", "Вода или молоко"),
            _i("bir chimdim", "щепотка", "Tuz", "Соль"),
            _i("2–3 barg", "2–3 листика", "Yalpiz (bezash uchun)", "Мята (для подачи)"),
        ],
        "steps": [
            _s("Idishda kokos suti, suv, eritritol va bir chimdim tuzni aralashtiring.",
               "Смешайте кокосовое молоко, воду, эритрит и щепотку соли."),
            _s("Chia urug'ini qo'shib, 1 daqiqa yaxshilab aralashtiring.",
               "Добавьте чиа и хорошо мешайте 1 минуту."),
            _s("10 daqiqadan keyin yana bir bor aralashtiring — chia bir joyga yopishib qolmaydi.",
               "Через 10 минут перемешайте ещё раз — так чиа не слипнется комками."),
            _s("Ikki bankaga bo'lib, muzlatkichda kamida 4 soat yoki tun bo'yi saqlang.",
               "Разлейте по двум баночкам и уберите в холодильник минимум на 4 часа или на ночь."),
            _s("Kokos qirindisini quruq tovada 1–2 daqiqa, och-oltin rangga kelguncha qovuring.",
               "Обжарьте кокосовую стружку на сухой сковороде 1–2 минуты до светло-золотистого цвета."),
            _s("Tortishdan oldin ustiga kokos qirindisi va kakao nibs seping, yalpiz bilan bezang.",
               "Перед подачей посыпьте стружкой и какао-крупкой, украсьте мятой."),
        ],
        "tip": _s("Muzlatkichda 3 kungacha saqlanadi — bir yo'la 3 kunlik nonushta tayyorlab qo'ying.",
                  "Хранится в холодильнике до 3 дней — приготовьте завтраки сразу на три утра."),
        "image_prompt": "two glass jars of coconut chia pudding, toasted coconut flakes, cacao nibs, mint",
    },
    {
        "slug": "kakao-nibs-pechenye",
        "title": _s("Kakao nibsli bodom pechenyesi", "Миндальное печенье с какао-крупкой"),
        "intro": _s(
            "Choyga yumshoq, xushbo'y pechenye — qandsiz va glyutensiz. Bor-yo'g'i 25 daqiqada tayyor.",
            "Мягкое ароматное печенье к чаю — без сахара и глютена. Готово всего за 25 минут."),
        "minutes": 25,
        "servings": _s("12 dona", "12 штук"),
        "per_serving": {"carbs": 1.5, "kcal": 140},
        "ingredients": [
            _i("150 g", "150 г", "Bodom uni", "Миндальная мука", _ALMOND,
               "Pechenyega yumshoqlik va yong'oq ta'mini beradi.",
               "Даёт печенью нежность и ореховый вкус."),
            _i("50 g", "50 г", "Eritritol", "Эритрит", _ERYTHRITOL,
               "Shakarsiz shirinlik — kaloriyasi deyarli nol.",
               "Сладость без сахара и почти без калорий."),
            _i("50 g", "50 г", "Ghee (eritilgan sariyog')", "Гхи (топлёное масло)", _GHEE,
               "Qaymoqli ta'm beradi va pishganda yonmaydi.",
               "Сливочный вкус, не горит при выпечке."),
            _i("30 g", "30 г", "Kakao nibs", "Какао-крупка", _NIBS,
               "Shokolad bo'lakchalari o'rnida — shakarsiz.",
               "Вместо шоколадной крошки — без сахара."),
            _i("1 ta", "1 шт", "Tuxum", "Яйцо"),
            _i("½ ch.q.", "½ ч.л.", "Soda", "Сода"),
            _i("bir chimdim", "щепотка", "Tuz", "Соль"),
        ],
        "steps": [
            _s("Pechni 175°C ga qizdiring, patnisga pergament to'shang.",
               "Разогрейте духовку до 175°C, застелите противень пергаментом."),
            _s("Eritilgan ghee, eritritol va tuxumni silliq bo'lguncha ko'pchiting.",
               "Взбейте растопленное гхи, эритрит и яйцо до однородности."),
            _s("Bodom uni, soda va tuzni qo'shib, yumshoq xamir qoring.",
               "Добавьте миндальную муку, соду и соль, замесите мягкое тесто."),
            _s("Kakao nibsni qo'shib, qoshiq bilan aralashtiring.",
               "Вмешайте ложкой какао-крупку."),
            _s("Xamirdan 12 ta yong'oqdek sharcha yasab, patnisga qo'ying va kaft bilan biroz bosing.",
               "Скатайте 12 шариков размером с грецкий орех, выложите на противень и слегка прижмите."),
            _s("12–14 daqiqa, chetlari oltin rangga kirguncha pishiring.",
               "Выпекайте 12–14 минут, пока края не станут золотистыми."),
            _s("Patnisda 10 daqiqa soviting — issiqligida yumshoq, sovigach shakli o'rnashadi.",
               "Остудите на противне 10 минут — горячее печенье мягкое, остыв, держит форму."),
        ],
        "tip": _s("Eritritol o'rniga allyuloza ishlatsangiz, pechenye yanada yumshoq va karamelli bo'ladi.",
                  "С аллюлозой вместо эритрита печенье получится ещё мягче, с карамельной ноткой."),
        "image_prompt": "golden almond flour cookies with cacao nibs on parchment, one broken, glass of milk",
    },
    {
        "slug": "urugli-kreker",
        "title": _s("Urug'li qarsildoq kreker", "Хрустящие крекеры из семян"),
        "intro": _s(
            "Chipsga sog'lom muqobil: faqat urug'lar, zaytun yog'i va tuz. Bir patnis — "
            "butun hafta uchun gazak.",
            "Полезная замена чипсам: только семена, оливковое масло и соль. Один противень — "
            "перекус на всю неделю."),
        "minutes": 75,
        "servings": _s("~24 dona", "~24 штуки"),
        "per_serving": {"carbs": 0.8, "kcal": 45},
        "ingredients": [
            _i("60 g", "60 г", "Zig'ir urug'i", "Семена льна", _FLAX_SEEDS,
               "Omega-3 va tolaga boy — krekerning asosi.",
               "Богаты омега-3 и клетчаткой — основа крекера."),
            _i("40 g", "40 г", "Chia urug'i", "Семена чиа", _CHIA,
               "Suvni shimib, urug'larni bir-biriga yopishtiradi.",
               "Впитывает воду и склеивает семена между собой."),
            _i("40 g", "40 г", "Oq kunjut", "Белый кунжут", _SESAME_WHITE,
               "Kalsiyga boy, qovurilganda xushbo'y.",
               "Богат кальцием, ароматный после запекания."),
            _i("20 g", "20 г", "Qora kunjut", "Чёрный кунжут", _SESAME_BLACK,
               "Chiroyli ko'rinish va boyroq ta'm.",
               "Красивый вид и более насыщенный вкус."),
            _i("50 g", "50 г", "Qovoq urug'i", "Тыквенные семечки", _PUMPKIN,
               "Magniy va rux manbai, yirik qarsillash beradi.",
               "Источник магния и цинка, крупный хруст."),
            _i("1 osh q.", "1 ст.л.", "Psillium", "Псиллиум", _PSYLLIUM_ANY,
               "Massani bog'laydi — kreker yoyilganda yirtilmaydi.",
               "Связывает массу — пласт не рвётся при раскатке."),
            _i("1 osh q.", "1 ст.л.", "Zaytun yog'i (sovuq siqim)", "Оливковое масло (холодного отжима)", _OLIVE,
               "Sog'lom yog' va yengil ta'm.",
               "Полезный жир и мягкий вкус."),
            _i("½ ch.q.", "½ ч.л.", "Himalay tuzi", "Гималайская соль", _SALT,
               "Krekerga kerakli sho'rlikni beradi.",
               "Нужная солоноватость для крекера."),
            _i("250 ml", "250 мл", "Iliq suv", "Тёплая вода"),
            _i("ixtiyoriy", "по желанию", "Quritilgan rayhon, sarimsoq kukuni", "Сушёный базилик, чесночный порошок"),
        ],
        "steps": [
            _s("Barcha urug'lar, psillium va tuzni idishda aralashtiring.",
               "Смешайте все семена, псиллиум и соль."),
            _s("Iliq suv va zaytun yog'ini quyib aralashtiring, 15 daqiqa qoldiring — massa yopishqoq bo'ladi.",
               "Влейте тёплую воду и масло, перемешайте и оставьте на 15 минут — масса станет вязкой."),
            _s("Pechni 160°C ga qizdiring.", "Разогрейте духовку до 160°C."),
            _s("Massani pergamentga solib, ustidan ikkinchi pergament yopib, 3–4 mm qalinlikda yoying.",
               "Выложите массу на пергамент, накройте вторым листом и раскатайте пласт толщиной 3–4 мм."),
            _s("Ustki pergamentni olib, pichoq bilan kvadratlarga chizib chiqing.",
               "Снимите верхний лист и надрежьте пласт ножом на квадраты."),
            _s("40–45 daqiqa pishiring, keyin pechni o'chirib, eshigini qiya ochib yana 15 daqiqa quriting.",
               "Выпекайте 40–45 минут, затем выключите духовку и подсушите ещё 15 минут с приоткрытой дверцей."),
            _s("Sovigach chiziqlar bo'ylab sindiring. O'tli qaymoqli pishloq sousi bilan torting.",
               "Остывший пласт разломайте по надрезам. Подавайте со сливочным сыром с зеленью."),
        ],
        "tip": _s("Germetik bankada 2 haftagacha qarsildoqligicha saqlanadi.",
                  "В герметичной банке остаются хрустящими до 2 недель."),
        "image_prompt": "seed crackers of flax, chia, sesame, pumpkin seeds, herbed cream cheese dip",
    },
    {
        "slug": "tovuq-nuggets",
        "title": _s("Bodom va kunjut qobig'idagi tovuq", "Курица в миндально-кунжутной панировке"),
        "intro": _s(
            "Bolalar ham, kattalar ham sevadigan qarsildoq nuggets — un va non ushog'isiz. "
            "Salat va sarimsoqli sous bilan to'liq kechki ovqat.",
            "Хрустящие наггетсы, которые любят и дети, и взрослые — без муки и сухарей. "
            "С салатом и чесночным соусом — полноценный ужин."),
        "minutes": 30,
        "servings": _s("3 kishilik", "3 порции"),
        "per_serving": {"carbs": 4, "kcal": 420},
        "ingredients": [
            _i("80 g", "80 г", "Bodom uni", "Миндальная мука", _ALMOND,
               "Non ushog'i o'rnida — qarsildoq va past uglevodli.",
               "Вместо сухарей — хрустит и почти без углеводов."),
            _i("30 g", "30 г", "Oq kunjut", "Белый кунжут", _SESAME_WHITE,
               "Qobiqqa qo'shimcha qarsillash beradi.",
               "Дополнительный хруст панировки."),
            _i("3 osh q.", "3 ст.л.", "Ghee (qovurish uchun)", "Гхи (для жарки)", _GHEE,
               "Yuqori haroratga chidamli — tutun chiqarmaydi.",
               "Выдерживает высокую температуру — не дымит."),
            _i("1 ch.q.", "1 ч.л.", "Himalay tuzi", "Гималайская соль", _SALT,
               "Go'sht ta'mini ochadi.", "Раскрывает вкус мяса."),
            _i("500 g", "500 г", "Tovuq filesi", "Куриное филе"),
            _i("2 ta", "2 шт", "Tuxum", "Яйца"),
            _i("bir chimdim", "по щепотке", "Qora qalampir, paprika", "Чёрный перец, паприка"),
            _i("3 osh q.", "3 ст.л.", "Qaymoq yoki grek yogurti (sous)", "Сметана или греческий йогурт (соус)"),
            _i("1 bo'lak", "1 зубчик", "Sarimsoq, limon sharbati (sous)", "Чеснок, лимонный сок (соус)"),
            _i("1 likop", "1 тарелка", "Bodring, pomidor, ko'katlar (salat)", "Огурец, помидоры, зелень (салат)"),
        ],
        "steps": [
            _s("Tovuq filesini 3–4 sm bo'laklarga kesing, tuz va qalampir seping.",
               "Нарежьте филе кусочками 3–4 см, посолите и поперчите."),
            _s("Bir idishda tuxumni chayqating, ikkinchisida bodom uni, kunjut va paprikani aralashtiring.",
               "В одной миске взбейте яйца, в другой смешайте миндальную муку, кунжут и паприку."),
            _s("Har bir bo'lakni avval tuxumga, keyin bodom-kunjut aralashmasiga botiring.",
               "Обмакните каждый кусочек сначала в яйцо, затем в миндально-кунжутную смесь."),
            _s("Tovada ghee'ni qizdiring va o'rtacha olovda har tomonini 3–4 daqiqadan oltin rangga "
               "kelguncha qovuring.",
               "Разогрейте гхи и обжарьте на среднем огне по 3–4 минуты с каждой стороны до золотистого цвета."),
            _s("Sous uchun qaymoq, maydalangan sarimsoq va limon sharbatini aralashtiring.",
               "Для соуса смешайте сметану, измельчённый чеснок и лимонный сок."),
            _s("Nuggetsni yangi salat, limon bo'lagi va sarimsoqli sous bilan torting.",
               "Подавайте наггетсы со свежим салатом, долькой лимона и чесночным соусом."),
        ],
        "tip": _s("Pechda ham bo'ladi: 200°C da 18–20 daqiqa, o'rtasida bir marta ag'darib.",
                  "Можно в духовке: 200°C, 18–20 минут, один раз перевернув."),
        "image_prompt": "almond flour and sesame crusted chicken nuggets, green salad, garlic sauce, lemon",
    },
]
