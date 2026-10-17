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
# 2026-10-17 recipes
_OLIVE_FRY = [["zaytun", "qovurish"], ["зайтун", "қовуриш"]]
_COCONUT_FLOUR = [["kokos", "uni"], ["кокос", "уни"]]
_FLAX_FLOUR = [["zig'ir", "uni"], ["зиғир", "уни"]]
_GREEN_BUCKWHEAT = [["yashil", "grechka", "don"], ["яшил", "гречка", "дон"]]
_BLACK_RICE = [["qora", "guruch"], ["қора", "гуруч"]]
_PISTACHIO = [["pista", "mag'z"], ["писта", "мағз"]]


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
    },    # ─── 2026-10-17: 10 more (owner: "saytga yana 10 xil dolzarb va bizdagi
    # masalliqlardan tayyorlash mumkin bo'lgan ketochilar va dietadagilar va
    # ozishni istaganlar va diabetlar orasida dolzarb bo'lgan retseptlar").
    {
        "slug": "keto-pitsa",
        "title": _s("Bodom unidan keto pitsa", "Кето-пицца на миндальной муке"),
        "intro": _s(
            "Pitsani sog'inib yurganlar uchun: asosi bodom uni va pishloqdan, bug'doy unisiz. "
            "Bir bo'lagida atigi ~6 g uglevod, oddiy pitsada esa ~35 g.",
            "Для тех, кто скучает по пицце: основа из миндальной муки и сыра, без пшеничной муки. "
            "В куске всего ~6 г углеводов, в обычной пицце — ~35 г."),
        "minutes": 40,
        "servings": _s("1 ta pitsa (26 sm), 4 bo'lak", "1 пицца (26 см), 4 куска"),
        "per_serving": {"carbs": 6, "kcal": 400},
        "ingredients": [
            _i("100 g", "100 г", "Bodom uni", "Миндальная мука", _ALMOND,
               "Asosning asosi: bug'doy unidan 7 baravar kam uglevod.",
               "Основа теста: в 7 раз меньше углеводов, чем в пшеничной муке."),
            _i("1/2 ch.q.", "1/2 ч.л.", "Himalay tuzi", "Гималайская соль", _SALT,
               "Xamir va sous ta'mini ochadi.", "Раскрывает вкус теста и соуса."),
            _i("1 osh q.", "1 ст.л.", "Zaytun yog'i", "Оливковое масло", _OLIVE,
               "Qolipni yog'lash va pitsa ustiga.", "Смазать форму и полить пиццу."),
            _i("150 g", "150 г", "Mozzarella (xamirga)", "Моцарелла (в тесто)"),
            _i("100 g", "100 г", "Mozzarella (ustiga)", "Моцарелла (сверху)"),
            _i("1 ta", "1 шт", "Tuxum", "Яйцо"),
            _i("3 osh q.", "3 ст.л.", "Shakarsiz tomat sousi yoki pastasi", "Томатный соус или паста без сахара"),
            _i("100 g", "100 г", "Qaynatilgan tovuq yoki qo'ziqorin", "Варёная курица или грибы"),
            _i("1/2 ch.q.", "1/2 ч.л.", "Quritilgan oregano yoki rayhon", "Сушёный орегано или базилик"),
        ],
        "steps": [
            _s("Pechni 200°C ga qizdiring. Laganga pergament qog'oz to'shab, zaytun yog'i surting.",
               "Разогрейте духовку до 200°C. Застелите противень пергаментом и смажьте оливковым маслом."),
            _s("150 g mozzarellani mayda to'g'rab, mikroto'lqinli pechda 1 daqiqa (yoki suv hammomida) "
               "to'liq eriting va aralashtiring.",
               "Натрите 150 г моцареллы, растопите в микроволновке 1 минуту (или на водяной бане) и перемешайте."),
            _s("Erigan pishloqqa bodom uni, tuxum va tuzni qo'shing va qoshiq bilan, keyin qo'l bilan "
               "bir xil xamir bo'lguncha qoring. Xamir yopishsa, qo'lni ho'llang.",
               "Добавьте к сыру миндальную муку, яйцо и соль и замесите сначала ложкой, затем руками до "
               "однородного теста. Если липнет — смочите руки."),
            _s("Xamirni pergamentga qo'yib, ikkinchi pergament ostidan 26 sm doira qilib, 4–5 mm qalinlikda yoying. "
               "Vilka bilan 8–10 joyini teshib chiqing.",
               "Раскатайте тесто между двумя листами пергамента в круг 26 см толщиной 4–5 мм. "
               "Наколите вилкой в 8–10 местах."),
            _s("Asosni o'zini 200°C da 10 daqiqa, chetlari qizarguncha pishiring.",
               "Выпекайте одну основу 10 минут при 200°C, до румяных краёв."),
            _s("Asos ustiga tomat sousini surting, tovuq (yoki qo'ziqorin) va 100 g mozzarellani tering, "
               "oregano seping.",
               "Смажьте основу томатным соусом, выложите курицу (или грибы) и 100 г моцареллы, посыпьте орегано."),
            _s("Yana 8–10 daqiqa, pishloq erib, qizarguncha pishiring. 3 daqiqa sovutib, 4 bo'lakka kesing.",
               "Выпекайте ещё 8–10 минут, пока сыр не расплавится и не зарумянится. Остудите 3 минуты и "
               "нарежьте на 4 куска."),
        ],
        "tip": _s("Asosni oldindan pishirib muzlatib qo'ysangiz, kechki ovqatga pitsa 10 daqiqada tayyor.",
                  "Испеките основы заранее и заморозьте — пицца к ужину будет готова за 10 минут."),
        "image_prompt": "keto pizza on almond flour crust, melted mozzarella, chicken and mushrooms, basil leaves, "
                        "one slice pulled out, tomato sauce, round wooden board",
    },
    {
        "slug": "kokos-quymoq",
        "title": _s("Kokos unidan keto quymoq", "Кето-панкейки из кокосовой муки"),
        "intro": _s(
            "Yumshoq, momiqdek quymoqlar — shakarsiz va glyutensiz. Dam olish kunining nonushtasi: "
            "15 daqiqada tayyor, bir porsiyada ~6 g uglevod.",
            "Мягкие, пышные панкейки — без сахара и глютена. Завтрак выходного дня: готов за 15 минут, "
            "в порции ~6 г углеводов."),
        "minutes": 20,
        "servings": _s("2 kishilik (8 dona)", "2 порции (8 штук)"),
        "per_serving": {"carbs": 6, "kcal": 305},
        "ingredients": [
            _i("40 g (4 osh q.)", "40 г (4 ст.л.)", "Kokos uni", "Кокосовая мука", _COCONUT_FLOUR,
               "Tolaga juda boy: oz miqdori ham quymoqni to'yimli qiladi.",
               "Очень много клетчатки: даже немного муки делает панкейки сытными."),
            _i("1 osh q.", "1 ст.л.", "Eritritol", "Эритрит", _ERYTHRITOL,
               "Shirinlik beradi, qondagi shakarni oshirmaydi.", "Даёт сладость, не повышая сахар в крови."),
            _i("2 osh q.", "2 ст.л.", "Kokos chipsi (ustiga)", "Кокосовые чипсы (сверху)", _COCONUT_FLAKES,
               "Qarsildoq va xushbo'y bezak.", "Хрустящее ароматное украшение."),
            _i("4 ta", "4 шт", "Tuxum", "Яйца"),
            _i("80 ml", "80 мл", "Sut yoki kokos suti", "Молоко или кокосовое молоко"),
            _i("1/2 ch.q.", "1/2 ч.л.", "Pishirish kukuni (razrixlitel)", "Разрыхлитель"),
            _i("1 chimdim", "щепотка", "Tuz", "Соль"),
            _i("1 osh q.", "1 ст.л.", "Sariyog' yoki kokos yog'i (tova uchun)", "Сливочное или кокосовое масло (для сковороды)"),
        ],
        "steps": [
            _s("Idishda tuxum, sut va eritritolni vilka yoki venchik bilan 1 daqiqa ko'pirtiring.",
               "Взбейте вилкой или венчиком яйца, молоко и эритрит 1 минуту."),
            _s("Kokos uni, pishirish kukuni va tuzni qo'shib, quyruqsiz aralashtiring.",
               "Добавьте кокосовую муку, разрыхлитель и соль и перемешайте без комков."),
            _s("Xamirni 5 daqiqa qo'yib qo'ying — kokos uni suyuqlikni shimib, xamir quyuq qaymoqdek bo'ladi.",
               "Оставьте тесто на 5 минут — кокосовая мука впитает жидкость, и тесто станет как густая сметана."),
            _s("Tovani past-o'rtacha olovda qizdirib, ozgina yog' surting (olov baland bo'lsa, quymoq ichi pishmay kuyadi).",
               "Разогрейте сковороду на слабом-среднем огне и слегка смажьте маслом (на сильном огне подгорит "
               "снаружи и останется сырым внутри)."),
            _s("Har bir quymoq uchun 2 osh qoshiq xamir quying va qoshiq bilan 8 sm doira qilib tekislang.",
               "Выкладывайте по 2 ст. ложки теста на панкейк и разровняйте ложкой в круг 8 см."),
            _s("Sirtida pufakchalar paydo bo'lguncha 2–3 daqiqa pishiring, ehtiyotkorlik bilan ag'darib, yana 2 daqiqa pishiring.",
               "Жарьте 2–3 минуты до появления пузырьков, аккуратно переверните и жарьте ещё 2 минуты."),
            _s("Ustiga kokos chipsi sepib, rezavor yoki shakarsiz qaymoq bilan torting.",
               "Посыпьте кокосовыми чипсами и подавайте с ягодами или несладкой сметаной."),
        ],
        "tip": _s("Kokos unini ko'z bilan ko'paytirmang: bir qoshiq ortiqcha ham quymoqni quruq qiladi.",
                  "Не добавляйте кокосовую муку «на глаз»: даже лишняя ложка делает панкейки сухими."),
        "image_prompt": "stack of fluffy coconut flour pancakes, toasted coconut chips on top, fresh raspberries, "
                        "small jug of cream, breakfast table",
    },
    {
        "slug": "yashil-grechka-palov",
        "title": _s("Yashil grechkadan PP palov", "ПП-плов из зелёной гречки"),
        "intro": _s(
            "Palovni yaxshi ko'rasiz, lekin guruch qondagi shakarni tez ko'taradimi? Yashil grechka "
            "bilan palov ta'mi saqlanadi, glikemik indeksi esa oq guruchdagidan ancha past.",
            "Любите плов, но рис быстро поднимает сахар? С зелёной гречкой вкус плова сохраняется, "
            "а гликемический индекс заметно ниже, чем у белого риса."),
        "minutes": 50,
        "servings": _s("4 kishilik", "4 порции"),
        "per_serving": {"carbs": 36, "kcal": 380},
        "ingredients": [
            _i("200 g", "200 г", "Yashil grechka", "Зелёная гречка", _GREEN_BUCKWHEAT,
               "Qovurilmagan grechka: tola va oqsilga boy, glyutensiz.",
               "Необжаренная гречка: много клетчатки и белка, без глютена."),
            _i("2 osh q.", "2 ст.л.", "Zaytun yog'i (qovurish uchun)", "Оливковое масло (для жарки)", _OLIVE_FRY,
               "Qovurishga chidamli, palov uchun yetarli miqdor.",
               "Подходит для жарки, для плова этого достаточно."),
            _i("1 ch.q.", "1 ч.л.", "Himalay tuzi", "Гималайская соль", _SALT,
               "Ta'mni ochadi.", "Раскрывает вкус."),
            _i("400 g", "400 г", "Tovuq filesi (yoki yog'siz mol go'shti)", "Куриное филе (или постная говядина)"),
            _i("2 ta (200 g)", "2 шт (200 г)", "Sabzi", "Морковь"),
            _i("1 ta", "1 шт", "Piyoz", "Лук"),
            _i("1 ch.q.", "1 ч.л.", "Zira", "Зира"),
            _i("1 bosh", "1 головка", "Sarimsoq", "Чеснок"),
            _i("450 ml", "450 мл", "Issiq suv", "Горячая вода"),
        ],
        "steps": [
            _s("Grechkani 3 marta, suvi tiniq bo'lguncha yuving va elakda suvini to'kib qo'ying.",
               "Промойте гречку 3 раза до прозрачной воды и откиньте на сито."),
            _s("Tovuqni 3 sm bo'laklarga, piyozni yarim halqa, sabzini somoncha qilib to'g'rang.",
               "Нарежьте курицу кусочками 3 см, лук — полукольцами, морковь — соломкой."),
            _s("Qozonda zaytun yog'ini o'rtacha olovda qizdirib, tovuqni 5–6 daqiqa, oqarguncha qovuring.",
               "Разогрейте масло в казане на среднем огне и обжарьте курицу 5–6 минут, пока не побелеет."),
            _s("Piyozni qo'shib 3 daqiqa, keyin sabzini qo'shib yana 5 daqiqa, yumshaguncha qovuring.",
               "Добавьте лук и жарьте 3 минуты, затем морковь — ещё 5 минут, до мягкости."),
            _s("Tuz va zirani seping, 450 ml issiq suv quying va qaynatib oling.",
               "Посолите, добавьте зиру, влейте 450 мл горячей воды и доведите до кипения."),
            _s("Grechkani tekis yoying (aralashtirmang), o'rtasiga butun sarimsoqni tiqing.",
               "Ровно распределите гречку сверху (не перемешивайте), в центр вдавите целую головку чеснока."),
            _s("Qopqoqni yopib, past olovda 20 daqiqa dimlang — suv to'liq shimilsin.",
               "Накройте крышкой и томите на слабом огне 20 минут, пока вода полностью не впитается."),
            _s("Olovni o'chirib, yana 10 daqiqa dam bering, so'ng aralashtirib torting.",
               "Выключите огонь, дайте постоять ещё 10 минут, затем перемешайте и подавайте."),
        ],
        "tip": _s("Diabet bo'lsa, porsiyani yangi sabzavot salati bilan birga yeng — tola qondagi "
                  "shakarning ko'tarilishini yanada sekinlashtiradi.",
                  "При диабете ешьте порцию вместе с салатом из свежих овощей — клетчатка ещё больше "
                  "замедляет подъём сахара."),
        "image_prompt": "uzbek style pilaf made with green buckwheat instead of rice, chicken pieces, julienned "
                        "carrots, whole garlic head on top, served in a cast iron kazan, fresh tomato salad aside",
    },
    {
        "slug": "shakarsiz-chizkeyk",
        "title": _s("Shakarsiz chizkeyk (bodom uni asosli)", "Чизкейк без сахара на миндальной основе"),
        "intro": _s(
            "Bayram stoliga ham, diabeti borlarga ham: kremdek yumshoq chizkeyk, shakar va bug'doy unisiz. "
            "Bir bo'lakda ~4,5 g uglevod — oddiy chizkeykda ~30 g.",
            "И на праздничный стол, и для тех, у кого диабет: нежный, как крем, чизкейк без сахара и "
            "пшеничной муки. В куске ~4,5 г углеводов — в обычном ~30 г."),
        "minutes": 80,
        "rest": _s("+ muzlatkichda kamida 6 soat", "+ минимум 6 часов в холодильнике"),
        "servings": _s("8 bo'lak (20 sm qolip)", "8 кусков (форма 20 см)"),
        "per_serving": {"carbs": 4.5, "kcal": 395},
        "ingredients": [
            _i("120 g", "120 г", "Bodom uni (asos uchun)", "Миндальная мука (для основы)", _ALMOND,
               "Pechene o'rnidagi asos — qarsildoq va past uglevodli.",
               "Основа вместо печенья — хрустящая и низкоуглеводная."),
            _i("1 osh q. + 80 g", "1 ст.л. + 80 г", "Eritritol (asosga va kremga)", "Эритрит (в основу и крем)", _ERYTHRITOL,
               "Shakar o'rnida: qondagi shakarni ko'tarmaydi.", "Вместо сахара: не повышает сахар в крови."),
            _i("40 g", "40 г", "Sariyog' (eritilgan)", "Сливочное масло (растопленное)"),
            _i("500 g", "500 г", "Krem-pishloq yoki yumshoq yog'li tvorog (9%)", "Сливочный сыр или мягкий жирный творог (9%)"),
            _i("2 ta", "2 шт", "Tuxum (xona haroratida)", "Яйца (комнатной температуры)"),
            _i("100 ml", "100 мл", "Qaymoq (20–33%)", "Сливки (20–33%)"),
            _i("1 osh q.", "1 ст.л.", "Limon sharbati", "Лимонный сок"),
            _i("1 chimdim", "щепотка", "Vanilin", "Ванилин"),
        ],
        "steps": [
            _s("Pechni 160°C ga qizdiring. 20 sm li ajraladigan qolip tubiga pergament to'shang.",
               "Разогрейте духовку до 160°C. Застелите дно разъёмной формы 20 см пергаментом."),
            _s("Asos: bodom uni, 1 osh qoshiq eritritol va eritilgan sariyog'ni aralashtirib, qolip tubiga "
               "qoshiq bilan zich bosib yoying. 10 daqiqa pishirib, sovuting.",
               "Основа: смешайте миндальную муку, 1 ст. ложку эритрита и растопленное масло, плотно утрамбуйте "
               "ложкой по дну формы. Выпекайте 10 минут и остудите."),
            _s("Krem: krem-pishloq (yoki tvorog)ni 80 g eritritol bilan mikserda past tezlikda 1 daqiqa silliq bo'lguncha uring.",
               "Крем: взбейте сливочный сыр (или творог) с 80 г эритрита на низкой скорости 1 минуту до гладкости."),
            _s("Tuxumni birma-bir qo'shing, keyin qaymoq, limon sharbati va vanilinni qo'shib, faqat aralashguncha "
               "uring (ko'p ursangiz, chizkeyk yoriladi).",
               "Добавьте яйца по одному, затем сливки, лимонный сок и ванилин — взбивайте только до "
               "соединения (если перебить, чизкейк треснет)."),
            _s("Kremni asos ustiga quying va tekislang.",
               "Вылейте крем на основу и разровняйте."),
            _s("Pechning pastki qavatiga suvli lagan qo'ying (bug' yorilishdan saqlaydi) va chizkeykni "
               "160°C da 50–55 daqiqa pishiring — o'rtasi biroz titrab turishi kerak.",
               "Поставьте на нижний уровень противень с водой (пар защитит от трещин) и выпекайте "
               "50–55 минут при 160°C — центр должен слегка дрожать."),
            _s("Pechni o'chirib, eshigini qiya ochib, chizkeykni ichida 1 soat sovuting.",
               "Выключите духовку, приоткройте дверцу и оставьте чизкейк внутри на 1 час."),
            _s("Muzlatkichda kamida 6 soat (yaxshisi tun bo'yi) qotiring, keyin 8 bo'lakka kesing.",
               "Уберите в холодильник минимум на 6 часов (лучше на ночь), затем нарежьте на 8 кусков."),
        ],
        "tip": _s("Kesishda pichoqni issiq suvga botirib, har kesgandan keyin artib turing — bo'laklar tekis chiqadi.",
                  "Режьте ножом, окунутым в горячую воду, вытирая после каждого разреза, — куски будут ровными."),
        "image_prompt": "creamy sugar-free cheesecake on almond flour crust, one slice cut out showing smooth "
                        "texture, fresh raspberries and mint on top, light ceramic cake stand",
    },
    {
        "slug": "keto-lavash",
        "title": _s("Psilliumli keto lavash (shaurma uchun)", "Кето-лаваш с псиллиумом (для шаурмы)"),
        "intro": _s(
            "Shaurma, rulet yoki o'rama — endi bug'doy lavashisiz. Yumshoq, egiluvchan va yirtilmaydi; "
            "bitta lavashda atigi ~2 g uglevod.",
            "Шаурма, ролл или врап — теперь без пшеничного лаваша. Мягкий, гибкий и не рвётся; "
            "в одном лаваше всего ~2 г углеводов."),
        "minutes": 30,
        "servings": _s("6 ta lavash (20 sm)", "6 лавашей (20 см)"),
        "per_serving": {"carbs": 2, "kcal": 125},
        "ingredients": [
            _i("100 g", "100 г", "Bodom uni", "Миндальная мука", _ALMOND,
               "Lavashga yumshoqlik va to'yimlilik beradi.", "Даёт лавашу мягкость и сытность."),
            _i("30 g (3 osh q.)", "30 г (3 ст.л.)", "Psillium uni", "Псиллиум (мука)", _PSYLLIUM_FLOUR,
               "Glyuten o'rnini bosadi: xamir egiluvchan bo'ladi va yirtilmaydi.",
               "Заменяет глютен: тесто становится эластичным и не рвётся."),
            _i("1/2 ch.q.", "1/2 ч.л.", "Himalay tuzi", "Гималайская соль", _SALT,
               "Ta'mni ochadi.", "Раскрывает вкус."),
            _i("1 osh q.", "1 ст.л.", "Zaytun yog'i", "Оливковое масло", _OLIVE,
               "Xamirni yumshoq qiladi.", "Делает тесто мягким."),
            _i("150 ml", "150 мл", "Qaynoq suv", "Кипяток"),
        ],
        "steps": [
            _s("Idishda bodom uni, psillium uni va tuzni aralashtiring.",
               "Смешайте в миске миндальную муку, псиллиум и соль."),
            _s("Zaytun yog'i va qaynoq suvni quyib, qoshiq bilan tez aralashtiring — psillium suvni shimib, "
               "xamir quyuqlashadi.",
               "Влейте масло и кипяток и быстро перемешайте ложкой — псиллиум впитает воду, тесто загустеет."),
            _s("Biroz sovigach, qo'l bilan 1 daqiqa yumshoq xamir qoring va 10 daqiqa dam bering.",
               "Когда немного остынет, вымесите руками 1 минуту до мягкого теста и дайте отдохнуть 10 минут."),
            _s("Xamirni 6 ta teng bo'lakka bo'ling. Har birini ikki pergament orasida 20 sm doira qilib, "
               "1–2 mm qalinlikda yoying.",
               "Разделите тесто на 6 равных частей. Каждую раскатайте между двумя листами пергамента "
               "в круг 20 см толщиной 1–2 мм."),
            _s("Quruq (yog'siz) tovani o'rtacha olovda qizdiring.",
               "Разогрейте сухую (без масла) сковороду на среднем огне."),
            _s("Lavashni ustki pergamentdan ajratib, tovaga ag'daring va har tomonini 1–1,5 daqiqadan, "
               "dog'lar paydo bo'lguncha pishiring.",
               "Снимите верхний пергамент, переверните лаваш на сковороду и жарьте по 1–1,5 минуты "
               "с каждой стороны, до появления пятнышек."),
            _s("Tayyor lavashlarni ustma-ust qo'yib, sochiq bilan yoping — bug'da yumshoq va egiluvchan qoladi.",
               "Складывайте готовые лаваши стопкой и накрывайте полотенцем — в пару они останутся мягкими и гибкими."),
        ],
        "tip": _s("Ichiga: qovurilgan tovuq, bodring, pomidor, karam va qatiq-sarimsoq sousi — uy shaurmasi tayyor.",
                  "Начинка: жареная курица, огурец, помидор, капуста и соус из йогурта с чесноком — домашняя шаурма готова."),
        "image_prompt": "thin keto flatbread wraps made with almond flour and psyllium, one rolled shawarma style "
                        "with grilled chicken, cucumber, tomato and garlic yogurt sauce, stack of wraps aside",
    },
    {
        "slug": "urugli-granola",
        "title": _s("Shakarsiz urug'li granola", "Гранола из семян без сахара"),
        "intro": _s(
            "Do'kon granolasining yarmi shakar. Bu granola urug' va yong'oqdan: qarsildoq, shirin, "
            "lekin qondagi shakarni ko'tarmaydi. Yogurt yoki sut bilan — 3 daqiqalik nonushta.",
            "Половина магазинной гранолы — сахар. Эта — из семян и орехов: хрустящая, сладкая, "
            "но не повышает сахар. С йогуртом или молоком — завтрак за 3 минуты."),
        "minutes": 35,
        "servings": _s("9 porsiya (30 g dan)", "9 порций (по 30 г)"),
        "per_serving": {"carbs": 2, "kcal": 165},
        "ingredients": [
            _i("100 g", "100 г", "Qovoq urug'i", "Тыквенные семечки", _PUMPKIN,
               "Magniy va ruxga boy, granolaning asosi.", "Богаты магнием и цинком — основа гранолы."),
            _i("50 g", "50 г", "Kokos chipsi", "Кокосовые чипсы", _COCONUT_FLAKES,
               "Qarsildoq va tabiiy shirin ta'm.", "Хруст и естественная сладость."),
            _i("50 g", "50 г", "Pista mag'zi", "Фисташки", _PISTACHIO,
               "Oqsil va qarsillash qo'shadi.", "Добавляют белок и хруст."),
            _i("2 osh q.", "2 ст.л.", "Qora kunjut", "Чёрный кунжут", _SESAME_BLACK,
               "Kalsiy va chiroyli rang.", "Кальций и красивый цвет."),
            _i("2 osh q.", "2 ст.л.", "Zig'ir urug'i", "Семена льна", _FLAX_SEEDS,
               "Omega-3 va tola.", "Омега-3 и клетчатка."),
            _i("2 osh q.", "2 ст.л.", "Eritritol", "Эритрит", _ERYTHRITOL,
               "Shakarsiz shirinlik.", "Сладость без сахара."),
            _i("1 ta", "1 шт", "Tuxum oqi", "Яичный белок"),
            _i("1 osh q.", "1 ст.л.", "Kokos yog'i yoki sariyog' (eritilgan)", "Кокосовое или сливочное масло (растопленное)"),
            _i("1 ch.q.", "1 ч.л.", "Dolchin", "Корица"),
            _i("1 chimdim", "щепотка", "Tuz", "Соль"),
        ],
        "steps": [
            _s("Pechni 150°C ga qizdiring. Laganga pergament qog'oz to'shang.",
               "Разогрейте духовку до 150°C. Застелите противень пергаментом."),
            _s("Pista mag'zini pichoq bilan yirik (no'xatdek) to'g'rang.",
               "Крупно (размером с горошину) порубите фисташки ножом."),
            _s("Katta idishda tuxum oqini vilka bilan 30 soniya ko'pirtiring, eritritol, erigan yog', dolchin "
               "va tuzni qo'shib aralashtiring.",
               "В большой миске взбейте белок вилкой 30 секунд, добавьте эритрит, растопленное масло, корицу "
               "и соль, перемешайте."),
            _s("Barcha urug'lar, kokos chipsi va pistani qo'shib, har biri aralashmaga bulanguncha aralashtiring.",
               "Добавьте все семена, кокосовые чипсы и фисташки и перемешайте, чтобы всё покрылось смесью."),
            _s("Laganga 1 sm qalinlikda zich yoying.",
               "Распределите по противню плотным слоем 1 см."),
            _s("150°C da 25 daqiqa pishiring; 12-daqiqada kurakcha bilan ehtiyotkorlik bilan ag'darib chiqing. "
               "Oltinrang bo'lsa — tayyor.",
               "Выпекайте 25 минут при 150°C; на 12-й минуте аккуратно переверните лопаткой. "
               "Стала золотистой — готово."),
            _s("Laganda to'liq soviting (sovigach qotadi), keyin bo'laklarga sindirib, yopiq bankaga soling.",
               "Полностью остудите на противне (застынет при остывании), разломайте и пересыпьте в закрытую банку."),
        ],
        "tip": _s("Bir porsiya — 3 osh qoshiq (30 g) tabiiy yogurt yoki sut bilan. Yopiq bankada 2 hafta saqlanadi.",
                  "Порция — 3 ст. ложки (30 г) с натуральным йогуртом или молоком. В закрытой банке хранится 2 недели."),
        "image_prompt": "homemade sugar-free granola clusters with pumpkin seeds, coconut chips, pistachios and black "
                        "sesame in a glass jar and a bowl of greek yogurt topped with granola",
    },
    {
        "slug": "qora-guruch-salat",
        "title": _s("Qora guruch va tovuqli salat", "Салат с чёрным рисом и курицей"),
        "intro": _s(
            "To'yimli, lekin og'ir emas: ozishni istaganlar uchun ideal tushlik. Qora guruch oddiy "
            "guruchdan tolaga boy va sekin hazm bo'ladi — uzoq to'q tutadi.",
            "Сытно, но не тяжело: идеальный обед для тех, кто худеет. Чёрный рис богаче клетчаткой, "
            "чем обычный, и переваривается медленно — надолго насыщает."),
        "minutes": 45,
        "servings": _s("2 kishilik", "2 порции"),
        "per_serving": {"carbs": 40, "kcal": 480},
        "ingredients": [
            _i("100 g", "100 г", "Qora guruch", "Чёрный рис", _BLACK_RICE,
               "Antotsianlarga boy, tola ko'p — uzoq to'q tutadi.",
               "Богат антоцианами и клетчаткой — надолго насыщает."),
            _i("1 osh q.", "1 ст.л.", "Qora kunjut", "Чёрный кунжут", _SESAME_BLACK,
               "Yong'oqsimon ta'm va kalsiy.", "Ореховый вкус и кальций."),
            _i("2 osh q.", "2 ст.л.", "Zaytun yog'i (sous)", "Оливковое масло (заправка)", _OLIVE,
               "Foydali yog' — sousning asosi.", "Полезный жир — основа заправки."),
            _i("1 osh q.", "1 ст.л.", "Olma sirkasi (sous)", "Яблочный уксус (заправка)", _VINEGAR,
               "Sousga yengil nordonlik beradi.", "Даёт заправке лёгкую кислинку."),
            _i("1/2 ch.q.", "1/2 ч.л.", "Himalay tuzi", "Гималайская соль", _SALT,
               "Ta'mni ochadi.", "Раскрывает вкус."),
            _i("250 g", "250 г", "Tovuq filesi", "Куриное филе"),
            _i("1 ta", "1 шт", "Bodring", "Огурец"),
            _i("1 ta", "1 шт", "Pomidor", "Помидор"),
            _i("1 bog'", "1 пучок", "Ko'kat (shivit yoki petrushka)", "Зелень (укроп или петрушка)"),
            _i("300 ml", "300 мл", "Suv (guruch uchun)", "Вода (для риса)"),
        ],
        "steps": [
            _s("Guruchni 3 marta yuving. 300 ml suvni qaynatib, guruch va bir chimdim tuz soling.",
               "Промойте рис 3 раза. Вскипятите 300 мл воды, всыпьте рис и щепотку соли."),
            _s("Qopqoq ostida past olovda 35 daqiqa pishiring, ortiqcha suvini to'kib, tekis idishda sovuting.",
               "Варите под крышкой на слабом огне 35 минут, слейте лишнюю воду и остудите на тарелке."),
            _s("Shu vaqtda tovuqni qaynab turgan tuzli suvga solib, 15 daqiqa pishiring va sovutib, tolalarga ajrating.",
               "Тем временем опустите курицу в кипящую подсоленную воду, варите 15 минут, остудите и разберите на волокна."),
            _s("Bodring va pomidorni 1 sm kubik, ko'katni mayda to'g'rang.",
               "Нарежьте огурец и помидор кубиком 1 см, зелень — мелко."),
            _s("Sous: zaytun yog'i, olma sirkasi va qolgan tuzni kichik idishda aralashtiring.",
               "Заправка: смешайте в маленькой миске масло, уксус и оставшуюся соль."),
            _s("Katta idishda guruch, tovuq, sabzavot va ko'katni aralashtiring, sousni quyib, yana aralashtiring.",
               "В большой миске смешайте рис, курицу, овощи и зелень, полейте заправкой и снова перемешайте."),
            _s("Ustiga qora kunjut sepib torting.",
               "Посыпьте чёрным кунжутом и подавайте."),
        ],
        "tip": _s("Guruch va tovuqni kechqurun pishirib qo'ysangiz, ertalab 5 daqiqada ishga tushlik tayyor.",
                  "Если отварить рис и курицу с вечера, утром обед на работу готов за 5 минут."),
        "image_prompt": "black rice salad bowl with shredded chicken, cucumber, tomato, fresh dill, black sesame "
                        "seeds, olive oil dressing, served in a wide ceramic bowl",
    },
    {
        "slug": "pistali-pechene",
        "title": _s("Pistali keto pechene", "Кето-печенье с фисташками"),
        "intro": _s(
            "Choy uchun qarsildoq pechene — shakarsiz va bug'doy unisiz. Pista va bodom uni: "
            "bitta pechenyeda ~2 g uglevod.",
            "Хрустящее печенье к чаю — без сахара и пшеничной муки. Фисташки и миндальная мука: "
            "в одной штуке ~2 г углеводов."),
        "minutes": 30,
        "servings": _s("14 dona", "14 штук"),
        "per_serving": {"carbs": 2, "kcal": 120},
        "ingredients": [
            _i("100 g", "100 г", "Pista mag'zi", "Фисташки", _PISTACHIO,
               "Rang, ta'm va qarsillash — pechenening yulduzi.",
               "Цвет, вкус и хруст — звезда этого печенья."),
            _i("100 g", "100 г", "Bodom uni", "Миндальная мука", _ALMOND,
               "Un o'rnida — past uglevodli asos.", "Вместо муки — низкоуглеводная основа."),
            _i("60 g", "60 г", "Eritritol", "Эритрит", _ERYTHRITOL,
               "Shakarsiz shirinlik.", "Сладость без сахара."),
            _i("60 g", "60 г", "Sariyog' (yumshatilgan)", "Сливочное масло (мягкое)"),
            _i("1 ta", "1 шт", "Tuxum", "Яйцо"),
            _i("1 chimdim", "щепотка", "Tuz", "Соль"),
        ],
        "steps": [
            _s("Pechni 170°C ga qizdiring. Laganga pergament qog'oz to'shang.",
               "Разогрейте духовку до 170°C. Застелите противень пергаментом."),
            _s("Pistaning 70 g ini blender yoki kofe maydalagichda maydalang (un bo'lib ketmasin), 30 g ini "
               "pichoq bilan yirik to'g'rang.",
               "70 г фисташек измельчите в блендере или кофемолке (не в пыль), 30 г крупно порубите ножом."),
            _s("Yumshoq sariyog' va eritritolni mikser yoki vilka bilan 2 daqiqa, oqarguncha uring.",
               "Взбейте мягкое масло с эритритом миксером или вилкой 2 минуты до посветления."),
            _s("Tuxumni qo'shib aralashtiring, keyin bodom uni, maydalangan pista va tuzni qo'shib, yumshoq xamir qoring.",
               "Добавьте яйцо, перемешайте, затем всыпьте миндальную муку, молотые фисташки и соль и замесите мягкое тесто."),
            _s("Xamirdan 14 ta yong'oqdek (25 g) sharcha yasang, laganga 3 sm oraliqda tering va kaft bilan 1 sm gacha bosing.",
               "Скатайте 14 шариков размером с грецкий орех (25 г), выложите на противень на расстоянии 3 см и "
               "приплюсните ладонью до 1 см."),
            _s("Har birining ustiga to'g'ralgan pistani sepib, biroz bosing.",
               "Посыпьте каждое рубленными фисташками и слегка прижмите."),
            _s("170°C da 13–15 daqiqa, chetlari oltinrang bo'lguncha pishiring va laganda 10 daqiqa sovuting.",
               "Выпекайте 13–15 минут при 170°C до золотистых краёв и остудите на противне 10 минут."),
        ],
        "tip": _s("Issiqligida yumshoq bo'ladi — bu normal, sovigach qarsillaydi. Yopiq idishda 1 hafta turadi.",
                  "Горячее печенье мягкое — это нормально, остывая, оно станет хрустящим. В закрытой банке — неделя."),
        "image_prompt": "keto pistachio cookies with chopped pistachios on top, cup of black tea, pistachio kernels "
                        "scattered, cooling rack on light oak table",
    },
    {
        "slug": "kokosli-sirniki",
        "title": _s("Kokos unli sirniki", "Сырники на кокосовой муке"),
        "intro": _s(
            "Oddiy sirnikidek mazali, lekin bug'doy uni va shakarsiz. Oqsilga boy nonushta — "
            "tushgacha ochiqmaysiz, bitta sirnikida ~2 g uglevod.",
            "Вкусные, как обычные сырники, но без пшеничной муки и сахара. Белковый завтрак — до обеда "
            "не проголодаетесь, в одном сырнике ~2 г углеводов."),
        "minutes": 25,
        "servings": _s("8 dona", "8 штук"),
        "per_serving": {"carbs": 2, "kcal": 125},
        "ingredients": [
            _i("2 osh q. (20 g)", "2 ст.л. (20 г)", "Kokos uni", "Кокосовая мука", _COCONUT_FLOUR,
               "Bug'doy uni o'rnida: oz miqdori ham massani ushlab turadi.",
               "Вместо пшеничной муки: даже немного хорошо держит массу."),
            _i("2 osh q.", "2 ст.л.", "Eritritol", "Эритрит", _ERYTHRITOL,
               "Shakarsiz shirinlik.", "Сладость без сахара."),
            _i("400 g", "400 г", "Tvorog (5–9%, quruqroq)", "Творог (5–9%, суховатый)"),
            _i("2 ta", "2 шт", "Tuxum", "Яйца"),
            _i("1 chimdim", "щепотка", "Vanilin", "Ванилин"),
            _i("1 chimdim", "щепотка", "Tuz", "Соль"),
            _i("1 osh q.", "1 ст.л.", "Yog' (qovurish uchun)", "Масло (для жарки)"),
            _i("2 osh q.", "2 ст.л.", "Qaymoq yoki tabiiy yogurt (torting uchun)", "Сметана или натуральный йогурт (для подачи)"),
        ],
        "steps": [
            _s("Tvorogni vilka bilan yaxshilab ezing (donador bo'lsa, elakdan o'tkazing).",
               "Хорошо разомните творог вилкой (если зернистый — протрите через сито)."),
            _s("Tuxum, eritritol, vanilin va tuzni qo'shib aralashtiring.",
               "Добавьте яйца, эритрит, ванилин и соль, перемешайте."),
            _s("Kokos unini qo'shib aralashtiring va 10 daqiqa qo'yib qo'ying — kokos uni namni shimib, massa quyuqlashadi.",
               "Всыпьте кокосовую муку, перемешайте и оставьте на 10 минут — мука впитает влагу, масса загустеет."),
            _s("Ho'l qo'l bilan 8 ta kulcha (1,5 sm qalinlikda, 6 sm diametrda) yasang.",
               "Влажными руками сформуйте 8 сырников толщиной 1,5 см и диаметром 6 см."),
            _s("Tovada yog'ni past-o'rtacha olovda qizdiring.",
               "Разогрейте масло на сковороде на слабом-среднем огне."),
            _s("Sirnikini har tomonini 3–4 daqiqadan, qizarguncha qovuring; oxirida qopqoq ostida 2 daqiqa ushlang.",
               "Обжарьте сырники по 3–4 минуты с каждой стороны до румяности; в конце подержите 2 минуты под крышкой."),
            _s("Qaymoq yoki tabiiy yogurt bilan issiq holda torting.",
               "Подавайте горячими со сметаной или натуральным йогуртом."),
        ],
        "tip": _s("Massa qo'lga yopishsa, yana 1 choy qoshiq kokos uni qo'shing — ko'p emas, aks holda quruq bo'ladi.",
                  "Если масса липнет к рукам, добавьте ещё 1 ч. ложку кокосовой муки — не больше, иначе будут сухими."),
        "image_prompt": "golden pan-fried cottage cheese pancakes syrniki made with coconut flour, sour cream, "
                        "fresh berries, sprinkle of coconut, breakfast plate",
    },
    {
        "slug": "keto-bulochka",
        "title": _s("Zig'ir unidan keto bulochka (burger uchun)", "Кето-булочки из льняной муки (для бургеров)"),
        "intro": _s(
            "Burger, sendvich yoki shunchaki choyga — yumshoq, g'ovak bulochkalar. Zig'ir uni va psillium: "
            "bitta bulochkada ~1,5 g uglevod, oddiy bulochkada ~25 g.",
            "Для бургера, сэндвича или просто к чаю — мягкие пористые булочки. Льняная мука и псиллиум: "
            "в одной ~1,5 г углеводов, в обычной ~25 г."),
        "minutes": 55,
        "servings": _s("4 dona", "4 штуки"),
        "per_serving": {"carbs": 1.5, "kcal": 115},
        "ingredients": [
            _i("100 g", "100 г", "Zig'ir uni", "Льняная мука", _FLAX_FLOUR,
               "Omega-3 va tolaga boy, uglevodi juda kam.", "Много омега-3 и клетчатки, очень мало углеводов."),
            _i("3 osh q. (30 g)", "3 ст.л. (30 г)", "Psillium uni", "Псиллиум (мука)", _PSYLLIUM_FLOUR,
               "Bulochkani ko'taradi va yumshoq qiladi.", "Поднимает булочку и делает её мягкой."),
            _i("1 osh q.", "1 ст.л.", "Olma sirkasi", "Яблочный уксус", _VINEGAR,
               "Soda bilan birga bulochkani g'ovak qiladi.", "Вместе с содой делает булочку пористой."),
            _i("1 osh q.", "1 ст.л.", "Oq kunjut (ustiga)", "Белый кунжут (сверху)", _SESAME_WHITE,
               "Klassik burger ko'rinishi va qarsillash.", "Классический вид бургерной булочки и хруст."),
            _i("1/2 ch.q.", "1/2 ч.л.", "Himalay tuzi", "Гималайская соль", _SALT,
               "Ta'mni ochadi.", "Раскрывает вкус."),
            _i("3 ta", "3 шт", "Tuxum oqi", "Яичный белок"),
            _i("1 ch.q.", "1 ч.л.", "Soda", "Сода"),
            _i("150 ml", "150 мл", "Qaynoq suv", "Кипяток"),
        ],
        "steps": [
            _s("Pechni 180°C ga qizdiring. Laganga pergament qog'oz to'shang.",
               "Разогрейте духовку до 180°C. Застелите противень пергаментом."),
            _s("Idishda zig'ir uni, psillium uni, soda va tuzni aralashtiring.",
               "Смешайте в миске льняную муку, псиллиум, соду и соль."),
            _s("Tuxum oqi va olma sirkasini qo'shib, qoshiq bilan aralashtiring.",
               "Добавьте белки и уксус, перемешайте ложкой."),
            _s("Qaynoq suvni quyib, darhol 30 soniya tez aralashtiring — psillium bir zumda xamirni bog'laydi.",
               "Влейте кипяток и сразу быстро перемешайте 30 секунд — псиллиум мгновенно свяжет тесто."),
            _s("Ho'l qo'l bilan 4 ta yumaloq bulochka yasang, laganga 5 sm oraliqda tering va ustiga kunjut sepib, biroz bosing.",
               "Влажными руками сформуйте 4 круглые булочки, выложите на противень на расстоянии 5 см, "
               "посыпьте кунжутом и слегка прижмите."),
            _s("180°C da 40–45 daqiqa pishiring. Tagini chertganda bo'g'iq ovoz chiqsa — tayyor.",
               "Выпекайте 40–45 минут при 180°C. Глухой звук при постукивании по дну — готово."),
            _s("Panjarada to'liq sovuting (30 daqiqa), so'ng ikkiga kesing.",
               "Полностью остудите на решётке (30 минут), затем разрежьте пополам."),
        ],
        "tip": _s("Burger uchun: kotlet, pishloq, salat bargi, pomidor va bodring tuzlamasi — hammasi keto.",
                  "Для бургера: котлета, сыр, лист салата, помидор и маринованный огурец — всё кето."),
        "image_prompt": "keto burger buns made from flaxseed flour and psyllium with white sesame on top, one bun "
                        "made into a burger with beef patty, cheese, lettuce and tomato",
    },
]
