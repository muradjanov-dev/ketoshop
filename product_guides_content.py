"""Mahsulot qo'llanmalari matni — product_guides.py uchun (2026-10-11).

Har bir tur: about (nima va nima uchun), benefits (aniq foydalari),
uses (kamida 3 ta usul yoki retsept: (sarlavha, matn)), cautions (zarar va
ogohlantirish — tavsiyasi bilan), advice (bitta amaliy maslahat).

Faqat uz (lotin) va ru yoziladi — kirill render paytida o'giriladi. Lotin
matnda o'zbek alifbosida yo'q harf (c, w) va lotin qisqartmalar ishlatilmaydi,
aks holda kirillda chala o'girilgan so'z chiqadi (test tekshiradi).

Sog'liq haqidagi gaplar ehtiyotkor: «yordam berishi mumkin», «manba».
Bu ovqat mahsuloti, dori emas.
"""

GUIDES = {
    # ───────────────────────── quyultirgich va tola ─────────────────────────
    "xanthan": {
        "uz": dict(
            about="Ksantan kamedi — tabiiy achitish yo'li bilan olinadigan quyultiruvchi va bog'lovchi kukun. "
                  "Glyutensiz va keto pishiriqda glyuten o'rnini bosadi: xamir uvalanmaydi, sous suyulib ketmaydi.",
            benefits=["Glyutensiz xamirni bog'laydi — non va pishiriq uvalanib ketmaydi",
                      "Unsiz va kraxmalsiz quyultiradi — sousga deyarli uglevod qo'shmaydi",
                      "Juda oz ketadi: 100 g uzoq vaqtga yetadi",
                      "Issiqda ham, sovuqda ham ishlaydi; muzlatib-eritganda ham buzilmaydi",
                      "Asosan eruvchan toladan iborat"],
            uses=[("Keto yoki glyutensiz non",
                   "200 g bodom yoki guruch uniga 1–1,5 choy qoshiq ksantan (keks va pechenega — 1/2 choy qoshiq). "
                   "Avval quruq masalliqlar bilan aralashtiring."),
                  ("Quyuq sous va sho'rva",
                   "250 ml bulon yoki qaymoqqa 1/4 choy qoshiq. Suyuqlikni venchik bilan aralashtirib turib, "
                   "kukunni SEKIN seping — 1 daqiqada quyuqlashadi."),
                  ("Salat zapravkasi",
                   "100 ml yog' va sirka aralashmasiga bir chimdim — zapravka ajralib ketmaydi va bargga yopishadi."),
                  ("Muzqaymoq, smuzi, kisel",
                   "500 ml asosga 1/4 choy qoshiq — muzqaymoq muz kristallarisiz mayin chiqadi, "
                   "smuzi suvlanmaydi, shakarsiz kisel quyuqlashadi.")],
            cautions=["Ko'p yeyilsa (kuniga 10–15 g dan ortiq) ich dam bo'lishi, gaz va ich ketishi mumkin — "
                      "retseptdagi me'yordan oshirmang.",
                      "Bir joyga to'kib yuborsangiz, to'p-to'p bo'lib qoladi — doim sekin sepib, darhol aralashtiring.",
                      "Chaqaloqlar (ayniqsa chala tug'ilganlar) ovqatiga qo'shmang. Ichak kasalligi bo'lsa — "
                      "shifokor bilan maslahatlashing."],
            advice="bir taomga 1/4–1 choy qoshiq yetarli. Ko'p solsangiz, taom shilimshiq bo'lib qoladi."),
        "ru": dict(
            about="Ксантановая камедь — загуститель и связующее, получаемое натуральной ферментацией. "
                  "В безглютеновой и кето-выпечке заменяет глютен: тесто не крошится, соус не расслаивается.",
            benefits=["Связывает безглютеновое тесто — хлеб и выпечка не крошатся",
                      "Загущает без муки и крахмала — почти не добавляет углеводов",
                      "Нужно очень мало: 100 г хватает надолго",
                      "Работает и в горячем, и в холодном; выдерживает заморозку",
                      "В основном состоит из растворимой клетчатки"],
            uses=[("Кето- или безглютеновый хлеб",
                   "на 200 г миндальной или рисовой муки — 1–1,5 ч. л. ксантана (для кексов и печенья — 1/2 ч. л.). "
                   "Сначала смешайте с сухими ингредиентами."),
                  ("Густой соус и суп",
                   "на 250 мл бульона или сливок — 1/4 ч. л. Помешивайте венчиком и МЕДЛЕННО всыпайте порошок — "
                   "загустеет за минуту."),
                  ("Заправка для салата",
                   "щепотка на 100 мл масла с уксусом — заправка не расслаивается и держится на листьях."),
                  ("Мороженое, смузи, кисель",
                   "1/4 ч. л. на 500 мл основы — мороженое без ледяных кристаллов, смузи не отслаивается, "
                   "кисель без сахара густеет.")],
            cautions=["В больших количествах (больше 10–15 г в день) — вздутие, газы, послабление стула. "
                      "Не превышайте дозировку рецепта.",
                      "Высыпанный разом — комкуется: всыпайте медленно и сразу размешивайте.",
                      "Не добавляйте в питание младенцев (особенно недоношенных). При болезнях кишечника — "
                      "посоветуйтесь с врачом."],
            advice="на одно блюдо хватает 1/4–1 ч. л. Если переборщить — блюдо станет слизистым."),
    },
    "psyllium": {
        "uz": dict(
            about="Psillium — zubturum turkumidagi o'simlik (Plantago ovata) urug'ining po'sti. Deyarli butunlay "
                  "eruvchan toladan iborat: suvda shishib, gelga aylanadi. Keto nonga «haqiqiy non» tuzilishini "
                  "beradi va ichak ishini yengillashtiradi.",
            benefits=["Eruvchan tolaga juda boy (70–80%) — ichak muntazam ishlashiga yordam beradi",
                      "Uzoq to'qlik hissi — ishtahani jilovlashga yordam beradi",
                      "Muntazam iste'molda ovqatdan keyingi qon shakari va «yomon» xolesterinni biroz "
                      "pasaytirishga yordam berishi mumkin",
                      "Keto nonni yumshoq va egiluvchan qiladi, glyuten o'rnini bosadi",
                      "Uglevodi deyarli yo'q"],
            uses=[("Keto bulochka (6 dona)",
                   "150 g bodom uni + 40 g psillium + 2 choy qoshiq qabartirgich + tuz. 3 ta tuxum oqi va 250 ml "
                   "qaynoq suv qo'shib tez aralashtiring, 6 ta bulochka yasab, 175°C da 50–55 daqiqa pishiring."),
                  ("Ertalabki tola ichimligi",
                   "1 choy qoshiq (taxminan 5 g) ni 250 ml suv yoki kefirga aralashtirib, darhol iching "
                   "(tez quyuqlashadi), ustidan yana 1 stakan suv iching."),
                  ("Bo'tqa, yogurt, smuzi",
                   "porsiyaga 1 choy qoshiq — taom quyuqroq va to'yimliroq bo'ladi."),
                  ("Tuxum o'rniga",
                   "1 choy qoshiq psillium + 3 osh qoshiq suv, 5 daqiqa tursin — pishiriqda 1 ta tuxumni "
                   "bog'lovchi sifatida almashtiradi.")],
            cautions=["Har doim ko'p suv bilan iching! Quruq yoki kam suv bilan ichilsa, tomoq va ichakda "
                      "tiqilib qolishi mumkin.",
                      "Birinchi kunlarda gaz va ich dam bo'lishi mumkin — kuniga 1 choy qoshiqdan boshlab, "
                      "asta oshiring.",
                      "Dorilarni psilliumdan kamida 2 soat oldin yoki keyin iching — tola dorining so'rilishini "
                      "kamaytiradi.",
                      "Yutish qiyin bo'lsa, ichak torayishi yoki tutilishi bo'lsa — iste'mol qilmang. Qand dori "
                      "ichayotganlar qon shakarini kuzatsin."],
            advice="kuniga 5–10 g (1–2 choy qoshiq), har 5 g ga kamida 1 stakan suv. Psillium uni mayinroq va "
                   "kuchliroq quyuqlashadi — retseptda gramm bilan o'lchang. Non binafsha tusga kirsa — zararsiz."),
        "ru": dict(
            about="Псиллиум — оболочка семян подорожника овального (Plantago ovata). Почти целиком состоит из "
                  "растворимой клетчатки: в воде набухает и превращается в гель. Даёт кето-хлебу структуру "
                  "«настоящего хлеба» и помогает работе кишечника.",
            benefits=["Очень много растворимой клетчатки (70–80%) — помогает регулярной работе кишечника",
                      "Долгое чувство сытости — помогает контролировать аппетит",
                      "При регулярном приёме может немного снижать сахар после еды и «плохой» холестерин",
                      "Делает кето-хлеб мягким и эластичным, заменяет глютен",
                      "Углеводов почти нет"],
            uses=[("Кето-булочки (6 шт.)",
                   "150 г миндальной муки + 40 г псиллиума + 2 ч. л. разрыхлителя + соль. Добавьте 3 белка и "
                   "250 мл кипятка, быстро перемешайте, сформуйте 6 булочек, выпекайте 50–55 минут при 175°C."),
                  ("Утренний напиток с клетчаткой",
                   "1 ч. л. (около 5 г) размешайте в 250 мл воды или кефира и сразу выпейте (быстро густеет), "
                   "затем выпейте ещё стакан воды."),
                  ("Каша, йогурт, смузи",
                   "1 ч. л. на порцию — блюдо гуще и сытнее."),
                  ("Вместо яйца",
                   "1 ч. л. псиллиума + 3 ст. л. воды, 5 минут — заменяет 1 яйцо как связующее в выпечке.")],
            cautions=["Всегда запивайте большим количеством воды! Сухой или с малым количеством воды может "
                      "застрять в горле или кишечнике.",
                      "В первые дни возможны газы и вздутие — начните с 1 ч. л. в день и увеличивайте постепенно.",
                      "Лекарства принимайте минимум за 2 часа до или через 2 часа после — клетчатка снижает их "
                      "всасывание.",
                      "При трудностях с глотанием, сужении или непроходимости кишечника — не употребляйте. "
                      "Принимающим сахароснижающие — следите за сахаром."],
            advice="5–10 г в день (1–2 ч. л.), на каждые 5 г — минимум стакан воды. Мука псиллиума мельче и "
                   "густеет сильнее — отмеряйте в граммах. Фиолетовый оттенок хлеба — безвреден."),
    },

    # ───────────────────────────── shirinlashtirgich ─────────────────────────────
    "stevia_pure": {
        "uz": dict(
            about="Toza steviya — steviya bargidan ajratib olingan shirin modda (steviol glikozidlari). Shakardan "
                  "200–300 barobar shirin va kaloriyasi yo'q, shuning uchun juda oz — pichoq uchida — ketadi.",
            benefits=["Kaloriyasi 0 — vazn nazoratida shakar o'rnini bosadi",
                      "Qondagi shakar va insulinni ko'tarmaydi — keto va qandli diabet ovqatlanishiga mos",
                      "Tishni buzmaydi",
                      "Issiqqa chidamli — choy, pishiriq va murabboda ishlaydi",
                      "Juda tejamli: 20 g uzoq vaqtga yetadi"],
            uses=[("Choy va qahva",
                   "1 stakanga pichoq uchida bir chimdim (1–2 choy qoshiq shakar o'rniga). Avval ozdan soling, "
                   "ta'mga qarab oshiring."),
                  ("Uy limonadi",
                   "1 litr suv + 1 ta limon sharbati + yalpiz + 2–3 chimdim steviya. 1 soat sovuting — shakarsiz, "
                   "kaloriyasiz ichimlik."),
                  ("Pishiriq",
                   "steviya hajm bermaydi, shuning uchun eritritol yoki alluloza bilan birga ishlating: "
                   "ularning shirinligini kuchaytiradi va kamroq solishga imkon beradi."),
                  ("Tvorog, yogurt, bo'tqa",
                   "porsiyaga bir chimdim — shirin, lekin shakarsiz nonushta.")],
            cautions=["Me'yordan oshsa, achchiq, qizilmiyaga o'xshash ta'm paydo bo'ladi — zararli emas, "
                      "faqat ko'p solingan.",
                      "Astradoshlarga (moychechak, ambroziya) allergiyasi borlarda kamdan-kam allergiya "
                      "berishi mumkin.",
                      "Qon bosimi yoki qand dori ichayotgan bo'lsangiz, ko'p miqdorda muntazam iste'mol qilishdan "
                      "oldin shifokor bilan maslahatlashing.",
                      "Bolalar ichimligiga kattalarnikidan kamroq soling."],
            advice="kuniga bir necha chimdim — choy, qahva va desert uchun yetarli va xavfsiz miqdor."),
        "ru": dict(
            about="Чистая стевия — сладкое вещество из листьев стевии (стевиол-гликозиды). В 200–300 раз слаще "
                  "сахара и без калорий, поэтому нужно совсем немного — на кончике ножа.",
            benefits=["0 калорий — заменяет сахар при контроле веса",
                      "Не поднимает сахар и инсулин — подходит для кето и диабета",
                      "Не разрушает зубы",
                      "Термостабильна — работает в чае, выпечке и варенье",
                      "Очень экономна: 20 г хватает надолго"],
            uses=[("Чай и кофе",
                   "щепотка на кончике ножа на чашку (вместо 1–2 ч. л. сахара). Начните с малого, добавляйте "
                   "по вкусу."),
                  ("Домашний лимонад",
                   "1 л воды + сок 1 лимона + мята + 2–3 щепотки стевии. Охладите час — без сахара и калорий."),
                  ("Выпечка",
                   "стевия не даёт объёма, поэтому используйте её вместе с эритритолом или аллюлозой: она "
                   "усиливает их сладость, и их нужно меньше."),
                  ("Творог, йогурт, каша",
                   "щепотка на порцию — сладкий завтрак без сахара.")],
            cautions=["При передозировке появляется горьковатый, «лакричный» привкус — не вредно, просто много.",
                      "У людей с аллергией на сложноцветные (ромашка, амброзия) изредка возможна аллергия.",
                      "Если принимаете препараты от давления или сахароснижающие — посоветуйтесь с врачом перед "
                      "регулярным употреблением в больших количествах.",
                      "В детские напитки кладите меньше, чем взрослым."],
            advice="несколько щепоток в день — достаточно и безопасно для чая, кофе и десерта."),
    },
    "stevia": {
        "uz": dict(
            about="Steviya asosidagi shirinlashtirgich kukuni — shakar o'rniga choy, qahva va pishiriqqa. "
                  "Shirinligi tarkibiga qarab har xil bo'ladi, shuning uchun nisbatni qadoqdan o'qing.",
            benefits=["Kaloriyasi yo'q yoki juda kam",
                      "Qondagi shakarni ko'tarmaydi — keto va qandli diabetga mos",
                      "Tishni buzmaydi",
                      "Issiqqa chidamli — pishiriqda ham ishlaydi"],
            uses=[("Choy va qahva",
                   "1 choy qoshiq shakar o'rniga avval chorak choy qoshiq soling, ta'mga qarab oshiring."),
                  ("Pishiriq va sirniki",
                   "shakar o'rniga qadoqdagi nisbatda. Pishiriq quruqroq chiqsa, 1 osh qoshiq qaymoq yoki "
                   "yogurt qo'shing."),
                  ("Kompot va limonad",
                   "1 litrga 1–2 choy qoshiqdan boshlang — sovuq ichimlikda ham eriydi."),
                  ("Shakarsiz krem",
                   "tvorog yoki qaymoqni steviya va vanil bilan ko'pirting — keks va quymoq uchun.")],
            cautions=["Ko'p solinsa, achchiqroq ta'm qoladi — ozdan boshlang.",
                      "Tarkibida eritritol bo'lsa (qadoqqa qarang), bir martada ko'p yeyilsa ich dam bo'lishi mumkin.",
                      "Astradoshlarga (moychechak, ambroziya) allergiyasi borlarda kamdan-kam allergiya "
                      "berishi mumkin."],
            advice="birinchi marta ozdan boshlang — keyin o'zingizga mos nisbatni topasiz."),
        "ru": dict(
            about="Сахарозаменитель на основе стевии — вместо сахара в чай, кофе и выпечку. Сладость зависит "
                  "от состава, поэтому пропорцию смотрите на упаковке.",
            benefits=["Без калорий или почти без них",
                      "Не поднимает сахар в крови — подходит для кето и диабета",
                      "Не разрушает зубы",
                      "Термостабилен — подходит для выпечки"],
            uses=[("Чай и кофе",
                   "вместо 1 ч. л. сахара начните с четверти чайной ложки и добавляйте по вкусу."),
                  ("Выпечка и сырники",
                   "вместо сахара по пропорции на упаковке. Если выпечка суховата — добавьте 1 ст. л. сливок "
                   "или йогурта."),
                  ("Компот и лимонад",
                   "начните с 1–2 ч. л. на литр — растворяется и в холодном."),
                  ("Крем без сахара",
                   "взбейте творог или сливки со стевией и ванилью — к кексам и панкейкам.")],
            cautions=["Если переборщить — остаётся горьковатый привкус; начинайте с малого.",
                      "Если в составе есть эритритол (смотрите упаковку), большое количество за раз может "
                      "вызвать вздутие.",
                      "У людей с аллергией на сложноцветные (ромашка, амброзия) изредка возможна аллергия."],
            advice="в первый раз начните с малого — так найдёте свою пропорцию."),
    },
    "erythritol": {
        "uz": dict(
            about="Eritritol — mevalarda tabiiy uchraydigan shakar spirti. Shakarning taxminan 70% shirinligiga "
                  "ega, lekin organizm uni deyarli o'zlashtirmaydi va o'zgarishsiz chiqarib yuboradi.",
            benefits=["Kaloriyasi deyarli yo'q (1 g da 0,2 kkal, shakarda 4 kkal)",
                      "Qondagi shakar va insulinni ko'tarmaydi (glikemik indeksi 0)",
                      "Tishni buzmaydi",
                      "Ta'mi shakarga eng yaqinlaridan, pishiriqda hajm beradi",
                      "Boshqa shakar spirtlariga qaraganda ichakka yengil"],
            uses=[("Pishiriq va keks",
                   "1 stakan shakar o'rniga taxminan 1⅓ stakan eritritol (u shakardan kamroq shirin). "
                   "Bodom yoki kokos uni bilan juda yaxshi ishlaydi."),
                  ("Krem va glazur",
                   "eritritolni qahva tegirmonida kukun qilib oling — kremda g'ijirlamaydi va kristallanmaydi."),
                  ("Choy, qahva, kompot",
                   "1 choy qoshiq shakar o'rniga 1–1,5 choy qoshiq."),
                  ("Shakarsiz murabbo",
                   "500 g rezavor + 150–200 g eritritol, 15 daqiqa qaynating; quyuqroq bo'lishi uchun "
                   "1 osh qoshiq chia qo'shing.")],
            cautions=["Bir martada 30–50 g dan ko'p yeyilsa, ich dam bo'lishi yoki ich ketishi mumkin — "
                      "ayniqsa boshlanishida.",
                      "2023 yilgi tadqiqotda qonida eritritol miqdori yuqori odamlarda yurak-qon tomir hodisalari "
                      "ko'proq qayd etilgan (bu bog'liqlik, isbotlangan sabab emas). Yurak kasalligi yoki insult "
                      "xavfi bo'lsa — me'yorida iste'mol qiling va shifokor bilan maslahatlashing.",
                      "Sovuq desertlarda kristallanib qolishi mumkin — kukun holida yoki alluloza bilan "
                      "aralashtirib ishlating.",
                      "Og'izda yengil «salqinlik» seziladi — bu tabiiy xususiyati."],
            advice="kuniga bir necha choy qoshiq — choy, qahva va bir bo'lak desert uchun yetarli."),
        "ru": dict(
            about="Эритритол — сахарный спирт, который естественно встречается во фруктах. Около 70% сладости "
                  "сахара, но организм его почти не усваивает и выводит в неизменном виде.",
            benefits=["Почти без калорий (0,2 ккал на 1 г, у сахара — 4 ккал)",
                      "Не поднимает сахар и инсулин (гликемический индекс 0)",
                      "Не разрушает зубы",
                      "По вкусу один из самых близких к сахару, даёт объём в выпечке",
                      "Мягче для кишечника, чем другие сахарные спирты"],
            uses=[("Выпечка и кексы",
                   "вместо 1 стакана сахара — примерно 1⅓ стакана эритритола (он менее сладкий). "
                   "Отлично работает с миндальной и кокосовой мукой."),
                  ("Крем и глазурь",
                   "смелите эритритол в кофемолке в пудру — крем не хрустит и не кристаллизуется."),
                  ("Чай, кофе, компот",
                   "вместо 1 ч. л. сахара — 1–1,5 ч. л."),
                  ("Варенье без сахара",
                   "500 г ягод + 150–200 г эритритола, варите 15 минут; для густоты добавьте 1 ст. л. чиа.")],
            cautions=["Больше 30–50 г за раз может вызвать вздутие или послабление стула — особенно поначалу.",
                      "В исследовании 2023 года у людей с высоким уровнем эритритола в крови чаще отмечались "
                      "сердечно-сосудистые события (это связь, а не доказанная причина). При болезнях сердца или "
                      "риске инсульта — употребляйте умеренно и посоветуйтесь с врачом.",
                      "В холодных десертах может кристаллизоваться — используйте пудру или смешивайте с аллюлозой.",
                      "Лёгкий «холодок» во рту — естественное свойство."],
            advice="несколько чайных ложек в день — хватит на чай, кофе и кусочек десерта."),
    },
    "allulose": {
        "uz": dict(
            about="Alluloza — anjir va mayizda tabiiy uchraydigan «noyob shakar». Ta'mi va o'zini tutishi oddiy "
                  "shakarga juda o'xshaydi, lekin organizm uni deyarli energiya sifatida ishlatmaydi.",
            benefits=["Kaloriyasi juda kam (1 g da taxminan 0,4 kkal)",
                      "Qondagi shakar va insulinni ko'tarmaydi",
                      "Shakar kabi karamellashadi va qizaradi — pishiriq chiroyli tusga kiradi",
                      "Kristallanmaydi — muzqaymoq, sous va karamel yumshoq qoladi",
                      "Achchiq yoki «salqin» ta'm qoldirmaydi"],
            uses=[("Keto karamel",
                   "100 g alluloza + 2 osh qoshiq suv, o'rta olovda oltin rangga kirguncha qaynating, "
                   "50 ml qaymoq va 20 g sariyog' qo'shing."),
                  ("Muzqaymoq va krem",
                   "500 ml qaymoq asosiga 70–80 g — muzlatgandan keyin ham tosh bo'lib qotmaydi."),
                  ("Pishiriq",
                   "1 stakan shakar o'rniga taxminan 1⅓ stakan. Tez qizaradi — pech haroratini 10–15°C "
                   "pasaytiring yoki ustini folga bilan yoping."),
                  ("Choy, qahva, limonad",
                   "1 choy qoshiq shakar o'rniga taxminan 1,5 choy qoshiq; sovuq ichimlikda ham tez eriydi.")],
            cautions=["Bir martada ko'p yeyilsa (60 kg odamga taxminan 25 g dan ortiq) ich dam bo'lishi, gaz "
                      "yoki ich ketishi mumkin.",
                      "Pishiriq tez kuyadi — pech yonidan uzoqlashmang.",
                      "Homiladorlik va bolalar uchun ma'lumot kam — me'yorida iste'mol qiling."],
            advice="kun davomida bir necha choy qoshiqdan boshlang."),
        "ru": dict(
            about="Аллюлоза — «редкий сахар», который естественно есть в инжире и изюме. По вкусу и поведению "
                  "очень похожа на обычный сахар, но организм почти не использует её как энергию.",
            benefits=["Очень мало калорий (около 0,4 ккал на 1 г)",
                      "Не поднимает сахар и инсулин",
                      "Карамелизуется и румянится как сахар — выпечка красиво подрумянивается",
                      "Не кристаллизуется — мороженое, соусы и карамель остаются мягкими",
                      "Без горечи и «холодка»"],
            uses=[("Кето-карамель",
                   "100 г аллюлозы + 2 ст. л. воды, варите на среднем огне до золотистого цвета, добавьте "
                   "50 мл сливок и 20 г сливочного масла."),
                  ("Мороженое и крем",
                   "70–80 г на 500 мл сливочной основы — после заморозки не каменеет."),
                  ("Выпечка",
                   "вместо 1 стакана сахара — около 1⅓ стакана. Быстро румянится — снизьте температуру на "
                   "10–15°C или накройте фольгой."),
                  ("Чай, кофе, лимонад",
                   "вместо 1 ч. л. сахара — около 1,5 ч. л.; быстро растворяется и в холодном.")],
            cautions=["Большое количество за раз (для человека 60 кг — больше примерно 25 г) может вызвать "
                      "вздутие, газы или послабление стула.",
                      "Выпечка быстро подгорает — не отходите от духовки.",
                      "Для беременных и детей данных мало — употребляйте умеренно."],
            advice="начните с нескольких чайных ложек в день."),
    },
    "allulose_stevia": {
        "uz": dict(
            about="Alluloza va steviya aralashmasi: alluloza hajm va shakarsimon ta'm beradi, steviya "
                  "shirinlikni kuchaytiradi. Shuning uchun oddiy allulozadan kamroq ketadi.",
            benefits=["Kaloriyasi juda kam",
                      "Qondagi shakarni ko'tarmaydi — keto va qandli diabetga mos",
                      "Achchiqlik va «salqinlik» deyarli sezilmaydi",
                      "Pishiriqda qizaradi va karamellashadi",
                      "Tejamli"],
            uses=[("Choy va qahva",
                   "1 choy qoshiq shakar o'rniga avval 1/2 choy qoshiq soling, ta'mga qarab oshiring."),
                  ("Sirniki va quymoq",
                   "xamirga shakar o'rniga qadoqdagi nisbatda — chiroyli qizaradi."),
                  ("Karamel va glazur",
                   "oz suv bilan o'rta olovda eriting — keks va pechene ustiga shakarsiz glazur."),
                  ("Shirin tvorog krem",
                   "tvorog + qaymoq + 1–2 choy qoshiq aralashma + vanil, ko'pirting.")],
            cautions=["Bir martada ko'p yeyilsa, ich dam bo'lishi mumkin.",
                      "Pishiriq oddiydan tezroq qizaradi — haroratni 10°C pasaytiring.",
                      "Astradoshlarga allergiyasi borlarda steviya kamdan-kam allergiya berishi mumkin."],
            advice="nisbat qadoqda yozilgan — birinchi marta ozroq soling."),
        "ru": dict(
            about="Смесь аллюлозы и стевии: аллюлоза даёт объём и вкус сахара, стевия усиливает сладость. "
                  "Поэтому её нужно меньше, чем чистой аллюлозы.",
            benefits=["Очень мало калорий",
                      "Не поднимает сахар в крови — подходит для кето и диабета",
                      "Горечи и «холодка» почти нет",
                      "В выпечке румянится и карамелизуется",
                      "Экономна"],
            uses=[("Чай и кофе",
                   "вместо 1 ч. л. сахара начните с 1/2 ч. л. и добавляйте по вкусу."),
                  ("Сырники и панкейки",
                   "в тесто вместо сахара по пропорции на упаковке — красиво румянятся."),
                  ("Карамель и глазурь",
                   "растопите с небольшим количеством воды на среднем огне — глазурь без сахара для кексов."),
                  ("Сладкий творожный крем",
                   "творог + сливки + 1–2 ч. л. смеси + ваниль, взбейте.")],
            cautions=["Много за раз — возможно вздутие.",
                      "Выпечка румянится быстрее обычного — снизьте температуру на 10°C.",
                      "При аллергии на сложноцветные стевия изредка может вызвать аллергию."],
            advice="пропорция указана на упаковке — в первый раз положите чуть меньше."),
    },
    "coconut_sugar": {
        "uz": dict(
            about="Kokos shakari — kokos palmasi gul shirasini bug'latib olinadi. Karamel ta'mli tabiiy shakar. "
                  "Muhim: bu shakar, shirinlashtirgich emas.",
            benefits=["Tozalanmagan — oz miqdorda kaliy, temir va rux saqlangan",
                      "Glikemik indeksi oq shakardan biroz past (manbalarga ko'ra 35–54)",
                      "Karamel-yong'oqsimon ta'm — pishiriqqa boy maza",
                      "Jigarrang shakar o'rniga 1:1"],
            uses=[("Pishiriq",
                   "oq yoki jigarrang shakar o'rniga 1:1 — pechene va keksga karamel ta'mi."),
                  ("Qahva va choy",
                   "1 choy qoshiq — karamelli shirinlik."),
                  ("Shirin-sho'r glazur",
                   "kokos shakari + soya sousi + sarimsoq — go'sht yoki sabzi uchun."),
                  ("Granola",
                   "yorma va yong'oqni kokos shakari va yog' bilan aralashtirib, 160°C da 20 daqiqa.")],
            cautions=["Keto uchun MOS EMAS: 1 choy qoshiqda taxminan 15 kkal va 4 g shakar — oq shakar bilan "
                      "deyarli bir xil.",
                      "Qandli diabetda oq shakar kabi hisoblang — qon shakarini ko'taradi.",
                      "«Foydali shakar» deb ko'p yemang: minerallari juda oz."],
            advice="shakarsiz kerak bo'lsa — eritritol, alluloza yoki steviya oling."),
        "ru": dict(
            about="Кокосовый сахар — выпаривают из нектара цветков кокосовой пальмы. Натуральный сахар с "
                  "карамельным вкусом. Важно: это сахар, а не сахарозаменитель.",
            benefits=["Нерафинированный — сохраняет немного калия, железа и цинка",
                      "Гликемический индекс немного ниже белого сахара (по разным данным 35–54)",
                      "Карамельно-ореховый вкус — богаче выпечка",
                      "Заменяет коричневый сахар 1:1"],
            uses=[("Выпечка",
                   "вместо белого или коричневого сахара 1:1 — карамельный вкус печенью и кексам."),
                  ("Кофе и чай",
                   "1 ч. л. — карамельная сладость."),
                  ("Сладко-солёная глазурь",
                   "кокосовый сахар + соевый соус + чеснок — для мяса или моркови."),
                  ("Гранола",
                   "смешайте хлопья и орехи с кокосовым сахаром и маслом, 20 минут при 160°C.")],
            cautions=["НЕ подходит для кето: в 1 ч. л. около 15 ккал и 4 г сахара — почти как белый сахар.",
                      "При диабете считайте как обычный сахар — поднимает сахар в крови.",
                      "Не налегайте как на «полезный сахар»: минералов в нём совсем мало."],
            advice="если нужно без сахара — берите эритритол, аллюлозу или стевию."),
    },
    "honey": {
        "uz": dict(
            about="Tabiiy, isitilmagan tog' asali. Yodda tuting: asal ham shakar (taxminan 80%), faqat tabiiy va "
                  "foydali moddalari bilan.",
            benefits=["Tabiiy antioksidantlar va fermentlar manbai (isitilmagan holda)",
                      "Yo'tal va tomoq og'rig'ida iliq ichimlik bilan yumshatishga yordam beradi",
                      "Oq shakardan xushbo'yroq — kamroq solsa ham shirin",
                      "Tez energiya beradi"],
            uses=[("Yo'tal uchun ichimlik",
                   "1 stakan iliq (40°C dan issiq emas) suv + 1 choy qoshiq asal + limon bo'lagi — uxlashdan oldin."),
                  ("Nonushta",
                   "tvorog yoki qatiq ustiga 1 choy qoshiq asal va bir hovuch yong'oq."),
                  ("Go'sht va sabzavot glazuri",
                   "2 osh qoshiq asal + 2 osh qoshiq soya sousi + sarimsoq — tovuq yoki sabziga pishishidan "
                   "10 daqiqa oldin surting."),
                  ("Choy",
                   "issiq choy biroz sovigach qo'shing — qaynoq suvda foydali fermentlari parchalanadi.")],
            cautions=["1 yoshgacha bo'lgan bolalarga MUTLAQO bermang — botulizm xavfi.",
                      "Keto va qandli diabetda asal shakar hisoblanadi — qon shakarini ko'taradi. Diabet bo'lsa, "
                      "shifokor bilan kelishing.",
                      "Gul changiga allergiyasi borlarda allergiya berishi mumkin.",
                      "Kaloriyasi yuqori: 1 osh qoshiqda taxminan 60 kkal."],
            advice="kuniga 1–2 choy qoshiqdan oshirmang. Qotib qolishi — tabiiylik belgisi; iliq suvli idishda "
                   "(40°C gacha) eritsa bo'ladi."),
        "ru": dict(
            about="Натуральный горный мёд без нагрева. Помните: мёд — это тоже сахар (около 80%), просто "
                  "натуральный и с полезными веществами.",
            benefits=["Источник натуральных антиоксидантов и ферментов (без нагрева)",
                      "Смягчает кашель и боль в горле с тёплым напитком",
                      "Ароматнее белого сахара — хватает меньшего количества",
                      "Быстрая энергия"],
            uses=[("Напиток от кашля",
                   "стакан тёплой (не выше 40°C) воды + 1 ч. л. мёда + долька лимона — перед сном."),
                  ("Завтрак",
                   "1 ч. л. мёда и горсть орехов на творог или йогурт."),
                  ("Глазурь для мяса и овощей",
                   "2 ст. л. мёда + 2 ст. л. соевого соуса + чеснок — смажьте курицу или морковь за 10 минут "
                   "до готовности."),
                  ("Чай",
                   "добавляйте в слегка остывший чай — в кипятке полезные ферменты разрушаются.")],
            cautions=["Детям до 1 года — СТРОГО нельзя: риск ботулизма.",
                      "На кето и при диабете мёд — это сахар, он поднимает сахар в крови. При диабете согласуйте "
                      "с врачом.",
                      "При аллергии на пыльцу возможна реакция.",
                      "Калорийно: около 60 ккал в 1 ст. л."],
            advice="не больше 1–2 ч. л. в день. Засахаривание — признак натуральности; можно растопить на "
                   "тёплой водяной бане (до 40°C)."),
    },
}

# ──────────────────────────────── keto unlar ────────────────────────────────
GUIDES.update({
    "almond_flour": {
        "uz": dict(
            about="Bodom uni — tozalangan bodomdan tortilgan mayin un. Bug'doy unining asosiy keto va glyutensiz "
                  "o'rnini bosuvchisi.",
            benefits=["Sof uglevodi taxminan 10 g/100 g (bug'doy unida taxminan 70 g)",
                      "Oqsil taxminan 21 g va tola 10 g (100 g da)",
                      "E vitamini va magniyga boy",
                      "Glyuten yo'q",
                      "Pishiriqqa yong'oq ta'mi va namlik beradi"],
            uses=[("Keto quymoq",
                   "100 g bodom uni + 2 tuxum + 100 ml sut + 1 choy qoshiq qabartirgich + shirinlashtirgich. "
                   "Yog'langan tovada o'rta olovda pishiring."),
                  ("Panirovka",
                   "non uvog'i o'rniga: tovuq yoki baliqni tuxumga, keyin bodom uni va ziravorga botiring."),
                  ("Keks va pechene",
                   "250 g bodom uni + 3 tuxum + 60 g sariyog' + 80 g eritritol + 1 choy qoshiq qabartirgich, "
                   "170°C da 25 daqiqa."),
                  ("Oddiy unga qo'shib",
                   "pishiriqda bug'doy unining 1/4 qismini almashtirishdan boshlang.")],
            cautions=["Yong'oqqa allergiya bo'lsa — mutlaqo yemang.",
                      "Kaloriyasi yuqori (taxminan 600 kkal/100 g) — porsiyani nazorat qiling.",
                      "Oksalatlarga boy: buyrakda tosh bo'lsa — me'yorida.",
                      "Tez qizaradi — pech haroratini 10–20°C past qiling. Glyuten yo'q, shuning uchun tuxum "
                      "yoki ksantan bilan bog'lang."],
            advice="og'zi yopiq idishda, yozda muzlatgichda saqlang."),
        "ru": dict(
            about="Миндальная мука — тонко смолотый очищенный миндаль. Главная кето- и безглютеновая замена "
                  "пшеничной муки.",
            benefits=["Чистых углеводов около 10 г/100 г (в пшеничной — около 70 г)",
                      "Белка около 21 г и клетчатки 10 г на 100 г",
                      "Богата витамином E и магнием",
                      "Без глютена",
                      "Даёт выпечке ореховый вкус и влажность"],
            uses=[("Кето-панкейки",
                   "100 г миндальной муки + 2 яйца + 100 мл молока + 1 ч. л. разрыхлителя + сахарозаменитель. "
                   "Жарьте на смазанной сковороде на среднем огне."),
                  ("Панировка",
                   "вместо сухарей: курицу или рыбу — в яйцо, затем в миндальную муку со специями."),
                  ("Кексы и печенье",
                   "250 г миндальной муки + 3 яйца + 60 г сливочного масла + 80 г эритритола + 1 ч. л. "
                   "разрыхлителя, 25 минут при 170°C."),
                  ("В смеси с обычной мукой",
                   "начните с замены 1/4 пшеничной муки в выпечке.")],
            cautions=["При аллергии на орехи — категорически нельзя.",
                      "Калорийна (около 600 ккал/100 г) — следите за порцией.",
                      "Богата оксалатами: при камнях в почках — умеренно.",
                      "Быстро румянится — ставьте духовку на 10–20°C ниже. Глютена нет — связывайте яйцом "
                      "или ксантаном."],
            advice="храните в закрытой таре, летом — в холодильнике."),
    },
    "coconut_flour": {
        "uz": dict(
            about="Kokos uni — yog'i olingan kokos mag'zidan. Tolaga juda boy va suyuqlikni juda ko'p shimadi, "
                  "shuning uchun oz ketadi.",
            benefits=["Tola taxminan 35–40 g/100 g — bug'doy unidan 10 barobar ko'p",
                      "Glyuten va yong'oqsiz — yong'oq allergiyasi borlar uchun bodom uni o'rniga",
                      "Uglevodi bug'doy unidan ancha kam",
                      "Yengil shirin, kokos ta'mi"],
            uses=[("Kokos quymoq",
                   "30 g kokos uni + 3 tuxum + 80 ml sut + bir chimdim qabartirgich. 5 daqiqa tursin, "
                   "kichik quymoq qilib pishiring."),
                  ("Bodom uni bilan",
                   "1 qism kokos uni + 3 qism bodom uni — keks va pechene uchun eng yaxshi nisbat."),
                  ("Quyultirish",
                   "sho'rva yoki sousga 1 choy qoshiq — un o'rniga."),
                  ("Panirovka",
                   "ziravor qo'shib, tovuq va baliq uchun.")],
            cautions=["Bug'doy unini 1:1 almashtirmang! 100 g bug'doy uni o'rniga 25–30 g kokos uni va "
                      "qo'shimcha tuxum (har 30 g ga taxminan 1 ta).",
                      "Tolasi ko'p: birdaniga ko'p yeyilsa ich dam bo'lishi mumkin — suvni ko'proq iching.",
                      "Kokosga allergiya kam uchraydi, lekin bo'lishi mumkin."],
            advice="xamir 5–10 daqiqa tursin — un suyuqlikni to'liq shimib oladi."),
        "ru": dict(
            about="Кокосовая мука — из обезжиренной мякоти кокоса. Очень богата клетчаткой и сильно впитывает "
                  "жидкость, поэтому её нужно немного.",
            benefits=["Клетчатки около 35–40 г/100 г — в 10 раз больше, чем в пшеничной",
                      "Без глютена и орехов — замена миндальной муке при аллергии на орехи",
                      "Углеводов намного меньше, чем в пшеничной",
                      "Лёгкая сладость и вкус кокоса"],
            uses=[("Кокосовые панкейки",
                   "30 г кокосовой муки + 3 яйца + 80 мл молока + щепотка разрыхлителя. Дайте постоять "
                   "5 минут, жарьте небольшие панкейки."),
                  ("С миндальной мукой",
                   "1 часть кокосовой + 3 части миндальной — лучшая пропорция для кексов и печенья."),
                  ("Загуститель",
                   "1 ч. л. в суп или соус вместо муки."),
                  ("Панировка",
                   "со специями — для курицы и рыбы.")],
            cautions=["Не заменяйте пшеничную муку 1:1! Вместо 100 г пшеничной — 25–30 г кокосовой и больше "
                      "яиц (примерно 1 яйцо на каждые 30 г).",
                      "Много клетчатки: большое количество сразу может вызвать вздутие — пейте больше воды.",
                      "Аллергия на кокос редка, но возможна."],
            advice="дайте тесту постоять 5–10 минут — мука полностью впитает жидкость."),
    },
    "pistachio_flour": {
        "uz": dict(
            about="Fistashka uni — maydalangan pista mag'zi. Chiroyli yashil rang va boy yong'oq ta'mi beradi; "
                  "bodom uni kabi keto pishiriqda ishlatiladi.",
            benefits=["Oqsil (taxminan 20 g/100 g) va tola manbai",
                      "Kaliy, B6 vitamini, lyutein va zeaksantin — ko'z uchun foydali antioksidantlar",
                      "Glyuten yo'q",
                      "Desertga bo'yoqsiz tabiiy yashil rang"],
            uses=[("Pista keks",
                   "150 g fistashka uni + 100 g bodom uni + 3 tuxum + 70 g eritritol + 60 g sariyog' + "
                   "1 choy qoshiq qabartirgich, 170°C da 25–30 daqiqa."),
                  ("Pista krem",
                   "200 g maskarpone yoki qaymoq + 3 osh qoshiq fistashka uni + shirinlashtirgich — tort va "
                   "keks ustiga."),
                  ("Baliq yoki tovuq qobig'i",
                   "fistashka uni + tuz + qalampir — filening ustiga bosib, pechda pishiring."),
                  ("Bo'tqa va yogurt",
                   "porsiyaga 1 osh qoshiq.")],
            cautions=["Yong'oqqa allergiya bo'lsa — yemang.",
                      "Kaloriyasi yuqori — porsiyani nazorat qiling.",
                      "Yog'i ko'p — salqin joyda yoki muzlatgichda saqlang, aks holda achib qoladi."],
            advice="pishiriqda bodom uni bilan aralashtirsangiz, tejamli va mazali chiqadi."),
        "ru": dict(
            about="Фисташковая мука — молотые ядра фисташки. Даёт красивый зелёный цвет и насыщенный ореховый "
                  "вкус; используется в кето-выпечке как миндальная.",
            benefits=["Источник белка (около 20 г/100 г) и клетчатки",
                      "Калий, витамин B6, лютеин и зеаксантин — антиоксиданты, полезные для глаз",
                      "Без глютена",
                      "Натуральный зелёный цвет десертам без красителей"],
            uses=[("Фисташковый кекс",
                   "150 г фисташковой муки + 100 г миндальной + 3 яйца + 70 г эритритола + 60 г сливочного "
                   "масла + 1 ч. л. разрыхлителя, 25–30 минут при 170°C."),
                  ("Фисташковый крем",
                   "200 г маскарпоне или сливок + 3 ст. л. фисташковой муки + сахарозаменитель — для торта "
                   "и кексов."),
                  ("Корочка для рыбы или курицы",
                   "фисташковая мука + соль + перец — прижмите к филе и запекайте."),
                  ("Каша и йогурт",
                   "1 ст. л. на порцию.")],
            cautions=["При аллергии на орехи — нельзя.",
                      "Калорийна — следите за порцией.",
                      "Много жира — храните в прохладе или в холодильнике, иначе прогоркнет."],
            advice="в выпечке смешивайте с миндальной мукой — экономно и вкусно."),
    },
    "flax": {
        "uz": dict(
            about="Zig'ir urug'i va uni — o'simlik omega-3 si va tolaning eng arzon manbalaridan biri. "
                  "Uglevodi juda kam, shuning uchun keto non va krekerlar asosi. Oq zig'ir — yumshoqroq ta'mli tur.",
            benefits=["O'simlik omega-3 si (alfa-linolen kislota): taxminan 22 g/100 g",
                      "Tolasi ko'p (taxminan 27 g/100 g) — ich qotishiga yordam beradi, to'qlik beradi",
                      "Lignanlar — antioksidant moddalar",
                      "Sof uglevodi deyarli yo'q — ketoga mos",
                      "Tuxum o'rnini bosa oladi"],
            uses=[("Tuxum o'rniga",
                   "1 osh qoshiq maydalangan zig'ir + 3 osh qoshiq suv, 10 daqiqa tursin = 1 ta tuxum."),
                  ("Keto kreker",
                   "100 g zig'ir uni + 50 g kunjut yoki qovoq urug'i + tuz + 120 ml suv. Pergamentga yupqa "
                   "yoyib, 160°C da 35–40 daqiqa quriting."),
                  ("Bo'tqa va smuzi",
                   "porsiyaga 1–2 osh qoshiq maydalangan zig'ir."),
                  ("Quymoq va non",
                   "unning 1/3 qismini zig'ir uni bilan almashtiring — oqsil va tola qo'shiladi.")],
            cautions=["Butun urug' hazm bo'lmay chiqib ketadi — foyda olish uchun maydalang.",
                      "Maydalangani tez achib qoladi: muzlatgichda saqlang, achchiq hid chiqsa — tashlang.",
                      "Xom zig'irni kuniga 2–3 osh qoshiqdan ko'p yemang va suv bilan iching.",
                      "Qon suyultiruvchi dori ichsangiz, homiladorlik yoki gormonga sezgir kasallik bo'lsa — "
                      "ko'p miqdordan oldin shifokor bilan maslahatlashing."],
            advice="kuniga 1–2 osh qoshiq maydalangan zig'ir yetarli."),
        "ru": dict(
            about="Семена и мука льна — один из самых доступных источников растительной омеги-3 и клетчатки. "
                  "Углеводов очень мало, поэтому это основа кето-хлеба и крекеров. Белый лён — с более мягким "
                  "вкусом.",
            benefits=["Растительная омега-3 (альфа-линоленовая кислота): около 22 г/100 г",
                      "Много клетчатки (около 27 г/100 г) — помогает при запорах, даёт сытость",
                      "Лигнаны — вещества-антиоксиданты",
                      "Чистых углеводов почти нет — подходит для кето",
                      "Может заменить яйцо"],
            uses=[("Вместо яйца",
                   "1 ст. л. молотого льна + 3 ст. л. воды, 10 минут = 1 яйцо."),
                  ("Кето-крекеры",
                   "100 г льняной муки + 50 г кунжута или тыквенных семечек + соль + 120 мл воды. Раскатайте "
                   "тонко на пергаменте, сушите 35–40 минут при 160°C."),
                  ("Каша и смузи",
                   "1–2 ст. л. молотого льна на порцию."),
                  ("Панкейки и хлеб",
                   "замените 1/3 муки льняной — добавится белок и клетчатка.")],
            cautions=["Целые семена выходят непереваренными — для пользы их нужно молоть.",
                      "Молотый лён быстро горкнет: храните в холодильнике, появился горький запах — выбросьте.",
                      "Сырого льна — не больше 2–3 ст. л. в день, запивайте водой.",
                      "Если принимаете антикоагулянты, беременны или есть гормонозависимые заболевания — "
                      "посоветуйтесь с врачом перед большими количествами."],
            advice="1–2 ст. л. молотого льна в день достаточно."),
    },
    "chia": {
        "uz": dict(
            about="Chia urug'i suvda o'z og'irligidan 10 barobar ko'p suyuqlik shimib, gelga aylanadi. "
                  "Tola, omega-3 va kalsiyga boy, uglevodi kam.",
            benefits=["Tola taxminan 34 g/100 g — to'qlik va ichak ishi uchun",
                      "O'simlik omega-3 si (taxminan 17 g/100 g)",
                      "Kalsiy (taxminan 630 mg/100 g) va magniy",
                      "Sof uglevodi kam — ketoga mos"],
            uses=[("Chia puding",
                   "3 osh qoshiq chia + 200 ml kokos suti yoki sut + bir chimdim eritritol — aralashtirib, "
                   "kechasi muzlatgichga qo'ying. Ertalab rezavor bilan."),
                  ("Shakarsiz murabbo",
                   "300 g ezilgan rezavor + 2 osh qoshiq chia + shirinlashtirgich — 20 daqiqada qotadi."),
                  ("Tuxum o'rniga",
                   "1 osh qoshiq chia + 3 osh qoshiq suv, 10 daqiqa = 1 ta tuxum."),
                  ("Smuzi, yogurt, salat",
                   "porsiyaga 1 osh qoshiq.")],
            cautions=["Quruq urug'ni ko'p yutib, ustidan suv ichmang — qizilo'ngachda shishib qolishi mumkin. "
                      "Doim ivitib yoki suyuqlik bilan yeng.",
                      "Birdaniga ko'p yeyilsa gaz va ich dam bo'lishi mumkin — kuniga 1 osh qoshiqdan boshlang.",
                      "Qon bosimi yoki qon suyultiruvchi dori ichayotganlar ko'p miqdordan oldin shifokor bilan "
                      "maslahatlashsin."],
            advice="kuniga 1–2 osh qoshiq, albatta suyuqlik bilan."),
        "ru": dict(
            about="Семена чиа впитывают в 10 раз больше жидкости, чем весят сами, и превращаются в гель. "
                  "Богаты клетчаткой, омегой-3 и кальцием, углеводов мало.",
            benefits=["Клетчатка около 34 г/100 г — для сытости и работы кишечника",
                      "Растительная омега-3 (около 17 г/100 г)",
                      "Кальций (около 630 мг/100 г) и магний",
                      "Чистых углеводов мало — подходит для кето"],
            uses=[("Чиа-пудинг",
                   "3 ст. л. чиа + 200 мл кокосового или обычного молока + щепотка эритритола — перемешайте "
                   "и уберите на ночь в холодильник. Утром — с ягодами."),
                  ("Джем без сахара",
                   "300 г размятых ягод + 2 ст. л. чиа + сахарозаменитель — загустеет за 20 минут."),
                  ("Вместо яйца",
                   "1 ст. л. чиа + 3 ст. л. воды, 10 минут = 1 яйцо."),
                  ("Смузи, йогурт, салат",
                   "1 ст. л. на порцию.")],
            cautions=["Не глотайте много сухих семян с последующим запиванием — могут набухнуть в пищеводе. "
                      "Всегда замачивайте или ешьте с жидкостью.",
                      "Много сразу — газы и вздутие; начните с 1 ст. л. в день.",
                      "Принимающим препараты от давления или антикоагулянты — посоветуйтесь с врачом перед "
                      "большими количествами."],
            advice="1–2 ст. л. в день, обязательно с жидкостью."),
    },
})

# ─────────────────── don, yorma va to'g'ri ovqatlanish unlari ───────────────────
GUIDES.update({
    "buckwheat": {
        "uz": dict(
            about="Yashil grechka — qovurilmagan grechka doni. Yengil ta'mli, unib chiqa oladi; glyutensiz.",
            benefits=["Glyuten yo'q",
                      "Oqsil (taxminan 13 g/100 g), magniy va tolaga boy",
                      "Rutin — qon tomirlarini qo'llab-quvvatlovchi antioksidant",
                      "Qovurilmagani uchun foydali moddalari ko'proq saqlangan"],
            uses=[("Bo'tqa",
                   "1 stakan donni yuvib, 2–3 soat iviting, keyin 1,5 stakan suvda 10–15 daqiqa pishiring."),
                  ("O'simtalar",
                   "donni 1 soat ivitib, suvini to'king va nam doka ostida 12–24 soat qoldiring. O'simtani "
                   "salat va smuziga qo'shing."),
                  ("Salat garniri",
                   "pishgan grechka + pomidor, bodring, ko'kat va zaytun yog'i."),
                  ("Uy granolasi",
                   "o'stirilgan donni quritib, yong'oq va urug'lar bilan aralashtiring.")],
            cautions=["Uglevodi ko'p (taxminan 70 g/100 g) — qat'iy keto uchun emas; to'g'ri va glyutensiz "
                      "ovqatlanish uchun.",
                      "Grechkaga allergiya kam uchraydi, lekin og'ir bo'lishi mumkin.",
                      "Ivitganda shilimshiq chiqadi — bu normal, yaxshilab yuving."],
            advice="bir porsiya — 40–60 g quruq don."),
        "ru": dict(
            about="Зелёная гречка — необжаренное зерно гречихи. Мягкий вкус, способна прорастать; без глютена.",
            benefits=["Без глютена",
                      "Богата белком (около 13 г/100 г), магнием и клетчаткой",
                      "Рутин — антиоксидант, поддерживающий сосуды",
                      "Без обжарки сохраняет больше полезных веществ"],
            uses=[("Каша",
                   "промойте стакан крупы, замочите на 2–3 часа, затем варите 10–15 минут в 1,5 стакана воды."),
                  ("Проростки",
                   "замочите на час, слейте воду и оставьте под влажной марлей на 12–24 часа. Добавляйте "
                   "проростки в салаты и смузи."),
                  ("Салат-гарнир",
                   "отварная гречка + помидоры, огурцы, зелень и оливковое масло."),
                  ("Домашняя гранола",
                   "высушите пророщенное зерно и смешайте с орехами и семечками.")],
            cautions=["Много углеводов (около 70 г/100 г) — не для строгого кето; для ПП и безглютенового питания.",
                      "Аллергия на гречку редка, но бывает тяжёлой.",
                      "При замачивании выделяется слизь — это нормально, хорошо промойте."],
            advice="порция — 40–60 г сухой крупы."),
    },
    "buckwheat_flour": {
        "uz": dict(
            about="Grechka uni — glyutensiz, to'q rangli, biroz yong'oqsimon ta'mli un. Blinchik va quymoq uchun "
                  "klassik tanlov.",
            benefits=["Glyuten yo'q",
                      "Oqsil, tola va magniy manbai",
                      "Glikemik indeksi oq undan past",
                      "Rutin — antioksidant"],
            uses=[("Grechka blinchik",
                   "150 g grechka uni + 2 tuxum + 350 ml sut + tuz + 1 osh qoshiq yog' — 20 daqiqa tursin, "
                   "yupqa qilib pishiring."),
                  ("Qatiqli quymoq",
                   "grechka uni + qatiq + tuxum + bir chimdim soda — yumshoq quymoq."),
                  ("Non va pishiriq",
                   "bug'doy unining 30% ini almashtiring yoki glyutensiz nonda guruch uni bilan aralashtiring."),
                  ("Quyultirish",
                   "sous va sho'rvaga 1 osh qoshiq.")],
            cautions=["Uglevodi ko'p — qat'iy keto uchun emas.",
                      "Glyuten yo'qligi uchun xamir uvalanadi — tuxum yoki ksantan bilan bog'lang.",
                      "Grechkaga allergiya bo'lishi mumkin."],
            advice="og'zi yopiq idishda, salqin joyda saqlang."),
        "ru": dict(
            about="Гречневая мука — без глютена, тёмная, со слегка ореховым вкусом. Классика для блинов и оладий.",
            benefits=["Без глютена",
                      "Источник белка, клетчатки и магния",
                      "Гликемический индекс ниже, чем у белой муки",
                      "Рутин — антиоксидант"],
            uses=[("Гречневые блины",
                   "150 г гречневой муки + 2 яйца + 350 мл молока + соль + 1 ст. л. масла — 20 минут "
                   "отдохнуть, жарьте тонкие блины."),
                  ("Оладьи на кефире",
                   "гречневая мука + кефир + яйцо + щепотка соды — пышные оладьи."),
                  ("Хлеб и выпечка",
                   "замените 30% пшеничной муки или смешивайте с рисовой в безглютеновом хлебе."),
                  ("Загуститель",
                   "1 ст. л. в соус или суп.")],
            cautions=["Много углеводов — не для строгого кето.",
                      "Без глютена тесто крошится — связывайте яйцом или ксантаном.",
                      "Возможна аллергия на гречку."],
            advice="храните в закрытой таре в прохладном месте."),
    },
    "chickpea_flour": {
        "uz": dict(
            about="No'xat uni — oqsilga boy, glyutensiz un. Pishgach yong'oqsimon ta'm beradi; tuxumsiz "
                  "«omlet» uchun asos.",
            benefits=["Oqsil taxminan 22 g va tola 10 g (100 g da)",
                      "Glyuten yo'q",
                      "Glikemik indeksi oq undan past",
                      "Folat va temir manbai"],
            uses=[("Tuxumsiz omlet",
                   "4 osh qoshiq no'xat uni + 6 osh qoshiq suv + tuz, zira, piyoz — tovada ikki tomonini "
                   "qizartiring."),
                  ("Kotlet va falafel",
                   "qiyma yoki sabzavotli kotletga bog'lovchi sifatida 2–3 osh qoshiq."),
                  ("Yupqa no'xat noni",
                   "1 stakan no'xat uni + 1 stakan suv + 2 osh qoshiq zaytun yog'i + tuz, 30 daqiqa tursin. "
                   "Qizdirilgan tovaga quyib, pechda 220°C da 10–12 daqiqa."),
                  ("Panirovka",
                   "sabzavot va baliq uchun.")],
            cautions=["Xom holda yemang — achchiq va yomon hazm bo'ladi; albatta pishiring.",
                      "Dukkaklilar gaz hosil qilishi mumkin — oz miqdordan boshlang.",
                      "Uglevodi taxminan 58 g/100 g — qat'iy keto uchun emas.",
                      "Dukkaklilarga allergiya bo'lsa — ehtiyot bo'ling."],
            advice="xamirni 20–30 daqiqa tindirsangiz, mazasi yaxshiroq bo'ladi."),
        "ru": dict(
            about="Нутовая мука — богатая белком мука без глютена. После приготовления даёт ореховый вкус; "
                  "основа для «омлета» без яиц.",
            benefits=["Белка около 22 г и клетчатки 10 г на 100 г",
                      "Без глютена",
                      "Гликемический индекс ниже, чем у белой муки",
                      "Источник фолатов и железа"],
            uses=[("Омлет без яиц",
                   "4 ст. л. нутовой муки + 6 ст. л. воды + соль, зира, лук — обжарьте с двух сторон."),
                  ("Котлеты и фалафель",
                   "2–3 ст. л. как связующее в мясные или овощные котлеты."),
                  ("Тонкая нутовая лепёшка",
                   "1 стакан нутовой муки + 1 стакан воды + 2 ст. л. оливкового масла + соль, 30 минут "
                   "отдохнуть. Влейте в разогретую сковороду и запекайте 10–12 минут при 220°C."),
                  ("Панировка",
                   "для овощей и рыбы.")],
            cautions=["Не ешьте сырой — горчит и плохо усваивается; обязательно готовьте.",
                      "Бобовые могут вызывать газы — начните с малого.",
                      "Углеводов около 58 г/100 г — не для строгого кето.",
                      "При аллергии на бобовые — осторожно."],
            advice="дайте тесту постоять 20–30 минут — вкус станет лучше."),
    },
    "rice_flour": {
        "uz": dict(
            about="Guruch uni — glyutensiz, ta'mi neytral un. Glyutensiz pishiriq, blinchik va qarsildoq "
                  "panirovka uchun.",
            benefits=["Glyuten yo'q — glyutenni ko'tara olmaydiganlar uchun",
                      "Ta'mi neytral, oson hazm bo'ladi",
                      "Panirovkani juda qarsildoq qiladi",
                      "Sousni silliq quyultiradi"],
            uses=[("Qarsildoq panirovka",
                   "tovuq yoki sabzavotni guruch uniga botirib qovuring — bug'doy unidan qarsildoqroq chiqadi."),
                  ("Glyutensiz blinchik",
                   "guruch uni + tuxum + sut + bir chimdim tuz — yupqa blinchik."),
                  ("Glyutensiz non",
                   "guruch uni + grechka yoki bodom uni + bog'lovchi (psillium yoki ksantan)."),
                  ("Sous",
                   "1 osh qoshiq unni sovuq suvda eritib, qaynayotgan sousga qo'shing.")],
            cautions=["Uglevodi ko'p (taxminan 80 g/100 g) va glikemik indeksi yuqori — keto va qandli "
                      "diabet uchun mos emas.",
                      "Glyuten yo'q — bog'lovchisiz pishiriq uvalanadi.",
                      "Guruch mahsulotlarini har kuni ko'p yemang — boshqa donlar bilan almashtirib turing."],
            advice="glyutensiz pishiriqda boshqa un bilan aralashtirib ishlating."),
        "ru": dict(
            about="Рисовая мука — без глютена, с нейтральным вкусом. Для безглютеновой выпечки, блинов и "
                  "хрустящей панировки.",
            benefits=["Без глютена — для тех, кто его не переносит",
                      "Нейтральный вкус, легко усваивается",
                      "Делает панировку очень хрустящей",
                      "Гладко загущает соусы"],
            uses=[("Хрустящая панировка",
                   "обваляйте курицу или овощи в рисовой муке и обжарьте — хрустит сильнее пшеничной."),
                  ("Безглютеновые блины",
                   "рисовая мука + яйцо + молоко + щепотка соли — тонкие блины."),
                  ("Безглютеновый хлеб",
                   "рисовая + гречневая или миндальная мука + связующее (псиллиум или ксантан)."),
                  ("Соус",
                   "1 ст. л. муки разведите в холодной воде и влейте в кипящий соус.")],
            cautions=["Много углеводов (около 80 г/100 г) и высокий гликемический индекс — не для кето и диабета.",
                      "Без глютена — без связующего выпечка крошится.",
                      "Не налегайте на рисовые продукты каждый день — чередуйте с другими крупами."],
            advice="в безглютеновой выпечке смешивайте с другой мукой."),
    },
    "rice": {
        "uz": dict(
            about="Guruchning foydali navlari: qora guruch (antotsianlarga boy), qizil devzira (palov uchun "
                  "klassik, yaltiratilmagan) va basmati (xushbo'y, oddiy oq guruchdan glikemik indeksi pastroq).",
            benefits=["Qora va qizil guruch — po'sti saqlangani uchun tola va antioksidantlarga boy",
                      "Basmatining glikemik indeksi oddiy oq guruchdan past",
                      "Glyuten yo'q",
                      "Devzira palovni ochiq-sochiq, yopishmaydigan qiladi"],
            uses=[("Palov",
                   "devzirani 1–2 soat ivitib, suvi tiniq bo'lguncha yuving — guruch ochilib, yopishmaydi."),
                  ("Qora guruch salati",
                   "1 qism guruchni 2,5 qism suvda 35–40 daqiqa pishiring; sovugach bodring, ko'kat, "
                   "avokado va zaytun yog'i bilan."),
                  ("Basmati garnir",
                   "1 qism guruchga 1,5 qism suv, 12 daqiqa pishirib, 10 daqiqa dam bering — baliq va go'shtga."),
                  ("Sovutilgan guruch",
                   "pishgan guruchni 12 soat muzlatgichda sovutib, keyin isitsangiz, «chidamli kraxmal» "
                   "ko'payadi va qon shakariga ta'siri kamayadi.")],
            cautions=["Uglevodi ko'p — keto uchun mos emas; qandli diabetda porsiyani cheklang "
                      "(pishgani 1/2 stakan).",
                      "Pishirishdan oldin yaxshilab yuving va mo'l suvda pishiring — guruchdagi og'ir metall "
                      "qoldiqlari kamayadi.",
                      "Pishgan guruchni xona haroratida uzoq qoldirmang — 1 soat ichida muzlatgichga."],
            advice="oq guruch o'rniga qora yoki qizil guruch — tolasi ko'proq, to'qlik uzoqroq."),
        "ru": dict(
            about="Полезные сорта риса: чёрный (богат антоцианами), красный девзира (классика для плова, "
                  "без шлифовки) и басмати (ароматный, с гликемическим индексом ниже обычного белого).",
            benefits=["Чёрный и красный рис — с оболочкой, поэтому больше клетчатки и антиоксидантов",
                      "У басмати гликемический индекс ниже, чем у обычного белого риса",
                      "Без глютена",
                      "Девзира делает плов рассыпчатым"],
            uses=[("Плов",
                   "замочите девзиру на 1–2 часа и промойте до прозрачной воды — рис раскроется и не слипнется."),
                  ("Салат с чёрным рисом",
                   "варите 1 часть риса в 2,5 частях воды 35–40 минут; остудите и смешайте с огурцом, "
                   "зеленью, авокадо и оливковым маслом."),
                  ("Гарнир из басмати",
                   "1 часть риса на 1,5 части воды, 12 минут варить и 10 минут дать постоять — к рыбе и мясу."),
                  ("Охлаждённый рис",
                   "если сваренный рис 12 часов охладить в холодильнике и затем разогреть, в нём становится "
                   "больше «резистентного крахмала» и он слабее влияет на сахар.")],
            cautions=["Много углеводов — не для кето; при диабете ограничьте порцию (1/2 стакана готового).",
                      "Перед варкой хорошо промывайте и варите в большом количестве воды — так снижается "
                      "содержание тяжёлых металлов.",
                      "Не оставляйте готовый рис надолго при комнатной температуре — в течение часа в "
                      "холодильник."],
            advice="вместо белого риса — чёрный или красный: больше клетчатки и дольше сытость."),
    },
    "bulgur": {
        "uz": dict(
            about="Bulg'ur — bug'da pishirilib, quritilib, maydalangan bug'doy yormasi. Tez pishadi va tolaga "
                  "boy; tarkibida glyuten bor.",
            benefits=["Tola ko'p (quruq holda taxminan 12 g/100 g)",
                      "Glikemik indeksi past (taxminan 46) — oq guruchdan sekin hazm bo'ladi",
                      "B guruh vitaminlari, magniy va temir",
                      "Tez pishadi: 10–15 daqiqa"],
            uses=[("Tabule salati",
                   "100 g mayda bulg'urga 150 ml qaynoq suv quyib, 15 daqiqa yopib qo'ying. Ko'p maydalangan "
                   "ko'kat, pomidor, limon sharbati va zaytun yog'i bilan aralashtiring."),
                  ("Bulg'ur palov",
                   "piyoz, sabzi va go'sht bilan; 1 qism bulg'urga 2 qism suv, 15 daqiqa pishirib, 10 daqiqa "
                   "dam bering."),
                  ("Kotlet",
                   "qiymaning 1/4 qismiga ivitilgan bulg'ur — kotlet suvli va to'yimli chiqadi."),
                  ("Sho'rva",
                   "guruch o'rniga bir hovuch bulg'ur.")],
            cautions=["Glyuten bor! Seliakiya yoki glyutenga sezgirlikda mutlaqo yemang.",
                      "Uglevodi ko'p — keto uchun mos emas.",
                      "Birdaniga ko'p yeyilsa, tolasi tufayli ich dam bo'lishi mumkin."],
            advice="bir porsiya — 50–70 g quruq bulg'ur."),
        "ru": dict(
            about="Булгур — пшеничная крупа, пропаренная, высушенная и дроблёная. Быстро готовится, богат "
                  "клетчаткой; содержит глютен.",
            benefits=["Много клетчатки (около 12 г/100 г сухого)",
                      "Низкий гликемический индекс (около 46) — усваивается медленнее белого риса",
                      "Витамины группы B, магний и железо",
                      "Готовится быстро: 10–15 минут"],
            uses=[("Салат табуле",
                   "залейте 100 г мелкого булгура 150 мл кипятка и накройте на 15 минут. Смешайте с большим "
                   "количеством зелени, помидорами, лимонным соком и оливковым маслом."),
                  ("Плов из булгура",
                   "с луком, морковью и мясом; 1 часть булгура на 2 части воды, 15 минут варить и 10 минут "
                   "дать постоять."),
                  ("Котлеты",
                   "1/4 часть фарша замените размоченным булгуром — котлеты сочные и сытные."),
                  ("Суп",
                   "горсть булгура вместо риса.")],
            cautions=["Содержит глютен! При целиакии или чувствительности к глютену — нельзя.",
                      "Много углеводов — не для кето.",
                      "Много сразу — из-за клетчатки возможно вздутие."],
            advice="порция — 50–70 г сухого булгура."),
    },
    "oats": {
        "uz": dict(
            about="Suli (oves) — yorma va un ko'rinishida. Beta-glyukan tolasi bilan mashhur: uzoq to'ydiradi "
                  "va xolesterin uchun foydali.",
            benefits=["Beta-glyukan — eruvchan tola; kuniga 3 g iste'mol qondagi xolesterinni pasaytirishga "
                      "yordam beradi",
                      "Uzoq to'qlik — energiya sekin ajraladi",
                      "Oqsil (taxminan 13 g/100 g), magniy va temir",
                      "Tabiatan glyutensiz (quyidagi ogohlantirishga qarang)"],
            uses=[("Bo'tqa",
                   "50 g yorma + 250 ml suv yoki sut, 5–7 daqiqa pishiring; ustiga rezavor va yong'oq."),
                  ("Suli quymog'i",
                   "1 stakan suli uni + 1 tuxum + 1 stakan qatiq + 1/2 choy qoshiq soda."),
                  ("Pechene",
                   "suli uni + maydalangan yong'oq + eritritol + tuxum — 180°C da 15 daqiqa."),
                  ("Smuzi va panirovka",
                   "smuziga 2 osh qoshiq yorma; tovuq panirovkasiga suli uni.")],
            cautions=["Uglevodi ko'p (taxminan 60 g/100 g) — qat'iy keto uchun emas.",
                      "Ko'pincha bug'doy bilan bir joyda qayta ishlanadi — seliakiyada faqat «glyutensiz» deb "
                      "belgilanganini oling.",
                      "Tolasi ko'p — birdaniga ko'p yeyilsa ich dam bo'lishi mumkin."],
            advice="kuniga 40–60 g — nonushta uchun yetarli."),
        "ru": dict(
            about="Овёс — в виде крупы и муки. Знаменит клетчаткой бета-глюканом: надолго насыщает и полезен "
                  "для холестерина.",
            benefits=["Бета-глюкан — растворимая клетчатка; 3 г в день помогают снижать холестерин в крови",
                      "Долгая сытость — энергия высвобождается медленно",
                      "Белок (около 13 г/100 г), магний и железо",
                      "От природы без глютена (см. предупреждение ниже)"],
            uses=[("Каша",
                   "50 г хлопьев + 250 мл воды или молока, 5–7 минут; сверху ягоды и орехи."),
                  ("Овсяные оладьи",
                   "1 стакан овсяной муки + 1 яйцо + 1 стакан кефира + 1/2 ч. л. соды."),
                  ("Печенье",
                   "овсяная мука + рубленые орехи + эритритол + яйцо — 15 минут при 180°C."),
                  ("Смузи и панировка",
                   "2 ст. л. хлопьев в смузи; овсяная мука — в панировку для курицы.")],
            cautions=["Много углеводов (около 60 г/100 г) — не для строгого кето.",
                      "Часто перерабатывается вместе с пшеницей — при целиакии берите только с пометкой "
                      "«без глютена».",
                      "Много клетчатки — большое количество сразу может вызвать вздутие."],
            advice="40–60 г в день — достаточно для завтрака."),
    },
    "rye_flour": {
        "uz": dict(
            about="Javdar uni — to'q rangli, tolaga boy un. Zakvaskali qora non va borodin noni uchun asos.",
            benefits=["Tolasi oq undan bir necha barobar ko'p",
                      "Javdar noni oq nondan sekin hazm bo'ladi va uzoqroq to'ydiradi",
                      "B guruh vitaminlari, magniy, temir",
                      "Boy, biroz nordon ta'm"],
            uses=[("Zakvaskali javdar noni",
                   "300 g javdar uni + 100 g faol zakvaska + 250 ml iliq suv + 1 choy qoshiq tuz + 1 osh qoshiq "
                   "qora solod. 4–6 soat oshirib, 200°C da 50 daqiqa pishiring."),
                  ("Bug'doy uni bilan",
                   "oddiy nonda bug'doy unining 30–50% ini javdar uni bilan almashtiring."),
                  ("Uy krekeri",
                   "javdar uni + suv + zig'ir + tuz — yupqa yoyib, 180°C da 15 daqiqa.")],
            cautions=["Glyuten bor — seliakiyada yemang.",
                      "Uglevodi ko'p — keto uchun emas.",
                      "Oshqozoni sezgir odamlarga og'irroq tuyulishi mumkin — oz-ozdan boshlang."],
            advice="xamir yopishqoq bo'ladi — ho'l qo'l bilan ishlang; xamirturushdan ko'ra zakvaska bilan "
                   "yaxshiroq oshadi."),
        "ru": dict(
            about="Ржаная мука — тёмная, богатая клетчаткой. Основа чёрного хлеба на закваске и бородинского.",
            benefits=["Клетчатки в несколько раз больше, чем в белой муке",
                      "Ржаной хлеб усваивается медленнее белого и дольше насыщает",
                      "Витамины группы B, магний, железо",
                      "Насыщенный, слегка кисловатый вкус"],
            uses=[("Ржаной хлеб на закваске",
                   "300 г ржаной муки + 100 г активной закваски + 250 мл тёплой воды + 1 ч. л. соли + "
                   "1 ст. л. чёрного солода. Расстойка 4–6 часов, выпекать 50 минут при 200°C."),
                  ("С пшеничной мукой",
                   "в обычном хлебе замените 30–50% пшеничной муки ржаной."),
                  ("Домашние крекеры",
                   "ржаная мука + вода + лён + соль — раскатать тонко, 15 минут при 180°C.")],
            cautions=["Содержит глютен — при целиакии нельзя.",
                      "Много углеводов — не для кето.",
                      "Людям с чувствительным желудком может казаться тяжёлым — начинайте понемногу."],
            advice="тесто липкое — работайте мокрыми руками; на закваске поднимается лучше, чем на дрожжах."),
    },
    "barley_flour": {
        "uz": dict(
            about="Arpa uni — yengil shirin ta'mli, beta-glyukan tolasiga boy un. Odatda bug'doy uniga qo'shib "
                  "ishlatiladi.",
            benefits=["Beta-glyukan — xolesterin va to'qlik uchun foydali eruvchan tola",
                      "Glikemik indeksi bug'doy unidan past",
                      "Selen, magniy va B vitaminlari",
                      "Yumshoq, yong'oqsimon ta'm"],
            uses=[("Non va lepyoshka",
                   "bug'doy unining 30% ini arpa uni bilan almashtiring."),
                  ("Quymoq",
                   "arpa uni + qatiq + tuxum + bir chimdim soda — to'yimli quymoq."),
                  ("Sho'rva va bo'tqa",
                   "sho'rvani quyultirish uchun yoki sut bilan talqonga o'xshash bo'tqa.")],
            cautions=["Glyuten bor — seliakiyada yemang.",
                      "Uglevodi ko'p — keto uchun emas.",
                      "Faqat arpa unidan non yaxshi oshmaydi — bug'doy uni bilan aralashtiring."],
            advice="salqin, quruq joyda saqlang."),
        "ru": dict(
            about="Ячменная мука — со сладковатым вкусом, богата клетчаткой бета-глюканом. Обычно используется "
                  "в смеси с пшеничной.",
            benefits=["Бета-глюкан — растворимая клетчатка, полезная для холестерина и сытости",
                      "Гликемический индекс ниже, чем у пшеничной",
                      "Селен, магний и витамины группы B",
                      "Мягкий ореховый вкус"],
            uses=[("Хлеб и лепёшки",
                   "замените 30% пшеничной муки ячменной."),
                  ("Оладьи",
                   "ячменная мука + кефир + яйцо + щепотка соды — сытные оладьи."),
                  ("Супы и каши",
                   "для загущения супа или как каша-толокно на молоке.")],
            cautions=["Содержит глютен — при целиакии нельзя.",
                      "Много углеводов — не для кето.",
                      "Хлеб только из ячменной муки плохо поднимается — смешивайте с пшеничной."],
            advice="храните в сухом прохладном месте."),
    },
    "spelt_flour": {
        "uz": dict(
            about="Polba (spelta) — qadimiy bug'doy turi. Yong'oqsimon ta'mli, oddiy bug'doydan oqsilga boyroq.",
            benefits=["Oqsil (taxminan 15 g/100 g) va tola",
                      "Temir, magniy, rux va B vitaminlari",
                      "Ba'zi odamlar oddiy bug'doydan yengilroq hazm qiladi",
                      "Non va pishiriqqa boy ta'm"],
            uses=[("Uy noni",
                   "oddiy bug'doy uni o'rniga 1:1, lekin xamirni kamroq qoring — glyuteni nozikroq."),
                  ("Blinchik va quymoq",
                   "polba uni + tuxum + sut."),
                  ("Pishiriq",
                   "pechene va keksda bug'doy unining yarmini almashtiring.")],
            cautions=["Bu ham bug'doy — glyuten bor! Seliakiyada mutlaqo yemang.",
                      "Uglevodi ko'p — keto uchun emas.",
                      "Suvni kamroq shimadi — retseptdagi suvni 10% kamaytiring."],
            advice="xamirni 5–7 daqiqa qorish yetarli — uzoq qorilsa yopishqoq bo'ladi."),
        "ru": dict(
            about="Полба (спельта) — древний вид пшеницы. С ореховым вкусом и большим содержанием белка, чем "
                  "у обычной пшеницы.",
            benefits=["Белок (около 15 г/100 г) и клетчатка",
                      "Железо, магний, цинк и витамины группы B",
                      "Некоторые люди переносят её легче обычной пшеницы",
                      "Насыщенный вкус хлеба и выпечки"],
            uses=[("Домашний хлеб",
                   "вместо пшеничной муки 1:1, но месите меньше — глютен у неё нежнее."),
                  ("Блины и оладьи",
                   "полбяная мука + яйцо + молоко."),
                  ("Выпечка",
                   "в печенье и кексах замените половину пшеничной муки.")],
            cautions=["Это тоже пшеница — содержит глютен! При целиакии нельзя.",
                      "Много углеводов — не для кето.",
                      "Впитывает меньше воды — уменьшите воду в рецепте на 10%."],
            advice="месите 5–7 минут — при долгом замесе тесто становится липким."),
    },
    "wholewheat_flour": {
        "uz": dict(
            about="Kepakli (to'liq donli) bug'doy uni — kepagi va murtagi olib tashlanmagan un. Oq unga "
                  "nisbatan tola va vitaminlari ko'p.",
            benefits=["Tola taxminan 10 g/100 g (oq unda taxminan 3 g)",
                      "B guruh vitaminlari, temir va magniy saqlangan",
                      "Oq undan sekin hazm bo'ladi, uzoqroq to'ydiradi",
                      "Kundalik non va pishiriqda oq unning foydali o'rni"],
            uses=[("Uy noni",
                   "oq unning yarmini yoki hammasini almashtiring; suvni 5–10% ko'proq qo'shing."),
                  ("Tez lepyoshka",
                   "un + suv + tuz + bir qoshiq yog' — yupqa yoyib, quruq tovada pishiring."),
                  ("Quymoq va pishiriq",
                   "pechene, keks va quymoqda oq un o'rniga.")],
            cautions=["Glyuten bor — seliakiyada yemang.",
                      "Uglevodi ko'p — keto uchun emas.",
                      "Murtagi tufayli tez achiydi — salqin joyda saqlab, 2–3 oy ichida ishlating."],
            advice="xamir 20–30 daqiqa tindirilsa, kepak yumshaydi va non mayinroq chiqadi."),
        "ru": dict(
            about="Цельнозерновая пшеничная мука — мука с отрубями и зародышем. Клетчатки и витаминов больше, "
                  "чем в белой.",
            benefits=["Клетчатки около 10 г/100 г (в белой — около 3 г)",
                      "Сохранены витамины группы B, железо и магний",
                      "Усваивается медленнее белой и дольше насыщает",
                      "Полезная замена белой муке в хлебе и выпечке"],
            uses=[("Домашний хлеб",
                   "замените половину или всю белую муку; воды добавьте на 5–10% больше."),
                  ("Быстрые лепёшки",
                   "мука + вода + соль + ложка масла — раскатать тонко и жарить на сухой сковороде."),
                  ("Оладьи и выпечка",
                   "вместо белой муки в печенье, кексах и оладьях.")],
            cautions=["Содержит глютен — при целиакии нельзя.",
                      "Много углеводов — не для кето.",
                      "Из-за зародыша быстро горкнет — храните в прохладе и используйте за 2–3 месяца."],
            advice="дайте тесту отдохнуть 20–30 минут — отруби размякнут, хлеб будет нежнее."),
    },
    "wheat_2nd": {
        "uz": dict(
            about="2-nav bug'doy uni — oliy navga nisbatan kepak zarralari ko'proq saqlangan un. Rangi biroz "
                  "to'qroq, ta'mi boyroq.",
            benefits=["Oliy nav undan tola va minerallar ko'proq",
                      "B guruh vitaminlari",
                      "Non, somsa va lepyoshka uchun yaxshi",
                      "Oq undan biroz sekinroq hazm bo'ladi"],
            uses=[("Uy noni",
                   "oddiy un kabi; suvni biroz ko'proq qo'shing."),
                  ("Lepyoshka va chuchvara xamiri",
                   "oliy nav un bilan yarmiga aralashtiring."),
                  ("Qatiqli quymoq",
                   "2-nav un + qatiq + tuxum + bir chimdim soda.")],
            cautions=["Glyuten bor — seliakiyada yemang.",
                      "Uglevodi ko'p — keto va qandli diabet uchun mos emas."],
            advice="salqin, quruq joyda saqlang."),
        "ru": dict(
            about="Пшеничная мука 2-го сорта — в ней больше частиц оболочки, чем в высшем сорте. Чуть темнее "
                  "и вкуснее.",
            benefits=["Больше клетчатки и минералов, чем в высшем сорте",
                      "Витамины группы B",
                      "Хороша для хлеба, самсы и лепёшек",
                      "Усваивается чуть медленнее белой муки"],
            uses=[("Домашний хлеб",
                   "как обычную муку; воды добавьте немного больше."),
                  ("Лепёшки и тесто для чучвары",
                   "пополам с мукой высшего сорта."),
                  ("Оладьи на кефире",
                   "мука 2-го сорта + кефир + яйцо + щепотка соды.")],
            cautions=["Содержит глютен — при целиакии нельзя.",
                      "Много углеводов — не для кето и диабета."],
            advice="храните в сухом прохладном месте."),
    },
    "corn_flour": {
        "uz": dict(
            about="Makkajo'xori uni — sariq rangli, shirinroq ta'mli glyutensiz un.",
            benefits=["Glyuten yo'q",
                      "Lyutein va zeaksantin — ko'z uchun antioksidantlar",
                      "Tola va magniy",
                      "Pishiriqqa chiroyli sariq rang"],
            uses=[("Makkajo'xori noni",
                   "200 g makkajo'xori uni + 100 g bug'doy yoki guruch uni + 2 tuxum + 250 ml qatiq + "
                   "1 choy qoshiq soda, 200°C da 25 daqiqa."),
                  ("Polenta (bo'tqa)",
                   "1 qism unga 4 qism suv, doim aralashtirib 20 daqiqa pishiring."),
                  ("Panirovka",
                   "baliq va tovuqni qarsildoq qiladi.")],
            cautions=["Uglevodi ko'p — keto va qandli diabet uchun mos emas.",
                      "Faqat makkajo'xori unidan non uvalanadi — boshqa un bilan aralashtiring."],
            advice="salqin, quruq joyda saqlang."),
        "ru": dict(
            about="Кукурузная мука — жёлтая, сладковатая, без глютена.",
            benefits=["Без глютена",
                      "Лютеин и зеаксантин — антиоксиданты для глаз",
                      "Клетчатка и магний",
                      "Красивый жёлтый цвет выпечки"],
            uses=[("Кукурузный хлеб",
                   "200 г кукурузной муки + 100 г пшеничной или рисовой + 2 яйца + 250 мл кефира + "
                   "1 ч. л. соды, 25 минут при 200°C."),
                  ("Полента (каша)",
                   "1 часть муки на 4 части воды, варите 20 минут, постоянно помешивая."),
                  ("Панировка",
                   "делает рыбу и курицу хрустящими.")],
            cautions=["Много углеводов — не для кето и диабета.",
                      "Хлеб только из кукурузной муки крошится — смешивайте с другой мукой."],
            advice="храните в сухом прохладном месте."),
    },
    "starch": {
        "uz": dict(
            about="Kraxmal — sof quyultiruvchi kukun. Sous, kisel va kremlarni tez va silliq quyultiradi, "
                  "pishiriqni mayin qiladi.",
            benefits=["Kuchli quyultiruvchi: oz miqdori yetarli",
                      "Ta'm va hid bermaydi",
                      "Glyuten yo'q",
                      "Panirovkani qarsildoq qiladi"],
            uses=[("Sous va sho'rva",
                   "1 osh qoshiq kraxmalni 3 osh qoshiq SOVUQ suvda eriting va qaynayotgan suyuqlikka "
                   "aralashtirib quying — 250–300 ml uchun."),
                  ("Kisel",
                   "1 litr kompotga 2–3 osh qoshiq kraxmal (sovuq suvda eritilgan)."),
                  ("Mayin biskvit",
                   "unning 1/4 qismini kraxmal bilan almashtiring — biskvit yumshoqroq chiqadi."),
                  ("Qarsildoq tovuq",
                   "go'shtni kraxmal, tuz va ziravor aralashmasiga botirib qovuring.")],
            cautions=["Deyarli sof uglevod (taxminan 85 g/100 g), glikemik indeksi yuqori — keto va qandli "
                      "diabet uchun mos emas.",
                      "Issiq suyuqlikka quruq holda solmang — to'p bo'lib qoladi.",
                      "Uzoq qaynatilsa quyuqligini yo'qotadi — oxirida qo'shing."],
            advice="keto taomni quyultirish uchun kraxmal o'rniga ksantan kamedini ishlating."),
        "ru": dict(
            about="Крахмал — чистый загуститель. Быстро и гладко загущает соусы, кисели и кремы, делает "
                  "выпечку нежнее.",
            benefits=["Сильный загуститель: нужно немного",
                      "Без вкуса и запаха",
                      "Без глютена",
                      "Делает панировку хрустящей"],
            uses=[("Соус и суп",
                   "1 ст. л. крахмала разведите в 3 ст. л. ХОЛОДНОЙ воды и влейте в кипящую жидкость, "
                   "помешивая, — на 250–300 мл."),
                  ("Кисель",
                   "2–3 ст. л. крахмала (разведённого в холодной воде) на 1 л компота."),
                  ("Нежный бисквит",
                   "замените 1/4 муки крахмалом — бисквит будет мягче."),
                  ("Хрустящая курица",
                   "обваляйте мясо в смеси крахмала, соли и специй и обжарьте.")],
            cautions=["Почти чистые углеводы (около 85 г/100 г), высокий гликемический индекс — не для кето "
                      "и диабета.",
                      "Не всыпайте сухим в горячую жидкость — будут комки.",
                      "При долгом кипячении теряет густоту — добавляйте в конце."],
            advice="для кето-блюд вместо крахмала используйте ксантановую камедь."),
    },
    "soy_flour": {
        "uz": dict(
            about="Soya uni — oqsilga juda boy, uglevodi oddiy undan kam un. Pishiriqqa oqsil qo'shish uchun.",
            benefits=["Oqsil taxminan 35–45 g/100 g — bug'doy unidan 3–4 barobar ko'p",
                      "Uglevodi bug'doy unidan ancha kam",
                      "Tola, temir va kaliy",
                      "Glyuten yo'q"],
            uses=[("Pishiriqqa oqsil",
                   "unning 1/4 qismini soya uni bilan almashtiring."),
                  ("Kam uglevodli quymoq",
                   "soya uni + bodom uni + tuxum + sut."),
                  ("Tuxum o'rniga",
                   "1 osh qoshiq soya uni + 1 osh qoshiq suv = 1 ta tuxum (bog'lovchi sifatida)."),
                  ("Kotlet va sous",
                   "bog'lash va quyultirish uchun 1–2 osh qoshiq.")],
            cautions=["Soya — kuchli allergenlardan biri. Allergiya bo'lsa, yemang.",
                      "Xom holda yemang — albatta pishiring.",
                      "Qalqonsimon bez kasalligi bo'lsa, ko'p miqdorda muntazam iste'mol qilishdan oldin "
                      "shifokor bilan maslahatlashing.",
                      "Tez qizaradi — pech haroratini 10–15°C pasaytiring."],
            advice="soya uni to'liq un o'rnini bosmaydi — boshqa un bilan aralashtiring."),
        "ru": dict(
            about="Соевая мука — очень богата белком, углеводов меньше, чем в обычной муке. Чтобы добавить "
                  "выпечке белка.",
            benefits=["Белка около 35–45 г/100 г — в 3–4 раза больше, чем в пшеничной",
                      "Углеводов намного меньше, чем в пшеничной",
                      "Клетчатка, железо и калий",
                      "Без глютена"],
            uses=[("Белок в выпечку",
                   "замените 1/4 муки соевой."),
                  ("Низкоуглеводные панкейки",
                   "соевая мука + миндальная + яйцо + молоко."),
                  ("Вместо яйца",
                   "1 ст. л. соевой муки + 1 ст. л. воды = 1 яйцо (как связующее)."),
                  ("Котлеты и соусы",
                   "1–2 ст. л. для связки и загущения.")],
            cautions=["Соя — один из сильных аллергенов. При аллергии — нельзя.",
                      "Не ешьте сырой — обязательно готовьте.",
                      "При заболеваниях щитовидной железы посоветуйтесь с врачом перед регулярным "
                      "употреблением в больших количествах.",
                      "Быстро румянится — снизьте температуру духовки на 10–15°C."],
            advice="соевая мука не заменяет муку полностью — смешивайте с другой."),
    },
})

# ───────────────────────── non uchun: kepak, solod, zakvaska ─────────────────────────
GUIDES.update({
    "bran": {
        "uz": dict(
            about="Kepak — donning tashqi qobig'i. Erimaydigan tolaning eng boy manbai: ichak ishini «yurgizadi».",
            benefits=["Tola taxminan 40 g/100 g — asosan erimaydigan tola",
                      "Ich qotishiga qarshi yordam beradi",
                      "Uzoq to'qlik, kam kaloriya",
                      "Magniy, temir va B vitaminlari"],
            uses=[("Kefir bilan",
                   "1 osh qoshiq kepakni 1 stakan kefir yoki qatiqqa solib, 10 daqiqa tursin — nonushta yoki "
                   "yengil kechki ovqat."),
                  ("Bo'tqa va non",
                   "bo'tqaga 1–2 osh qoshiq; non xamirida unning 10–15% ini kepak bilan almashtiring."),
                  ("Kotlet va panirovka",
                   "qiymaga 2–3 osh qoshiq; non uvog'i o'rniga panirovkaga.")],
            cautions=["Ko'p suv iching (kuniga 1,5–2 litr) — aks holda ich qotishi kuchayishi mumkin.",
                      "Kuniga 1 osh qoshiqdan boshlab, asta 2–3 osh qoshiqqa yetkazing — birdaniga ko'pi gaz va "
                      "og'riq beradi.",
                      "Ichak yallig'lanishi, yara yoki o'tkir gastritda — iste'mol qilmang.",
                      "Bug'doy kepagida glyuten qoldig'i bor. Dorilarni kepakdan 2 soat farq bilan iching."],
            advice="kuniga 20–30 g dan oshirmang."),
        "ru": dict(
            about="Отруби — внешняя оболочка зерна. Самый богатый источник нерастворимой клетчатки: «запускают» "
                  "работу кишечника.",
            benefits=["Клетчатка около 40 г/100 г — в основном нерастворимая",
                      "Помогают при запорах",
                      "Долгая сытость при малой калорийности",
                      "Магний, железо и витамины группы B"],
            uses=[("С кефиром",
                   "1 ст. л. отрубей в стакан кефира или йогурта, 10 минут — завтрак или лёгкий ужин."),
                  ("Каша и хлеб",
                   "1–2 ст. л. в кашу; в хлебном тесте замените отрубями 10–15% муки."),
                  ("Котлеты и панировка",
                   "2–3 ст. л. в фарш; вместо сухарей в панировку.")],
            cautions=["Пейте больше воды (1,5–2 л в день) — иначе запор может усилиться.",
                      "Начните с 1 ст. л. в день и постепенно доведите до 2–3 — резкое увеличение даёт газы и боль.",
                      "При воспалении кишечника, язве или остром гастрите — не употребляйте.",
                      "В пшеничных отрубях есть следы глютена. Лекарства принимайте с интервалом 2 часа."],
            advice="не больше 20–30 г в день."),
    },
    "malt": {
        "uz": dict(
            about="Solod — undirilib, quritilgan don (arpa yoki javdar). Qora fermentlangan solod borodin noni va "
                  "kvasga to'q rang va o'ziga xos xushbo'ylik beradi; oq (och) solod xamirga yengil shirinlik va "
                  "chiroyli qobiq beradi.",
            benefits=["Nonga tabiiy to'q rang va boy xushbo'ylik — bo'yoqsiz",
                      "B guruh vitaminlari va mikroelementlar manbai",
                      "Xamirga tabiiy shirinlik va chiroyli qobiq beradi",
                      "Uy kvasi uchun asos"],
            uses=[("Borodin noni",
                   "har 500 g javdar uniga 2–3 osh qoshiq qora solod (oz qaynoq suvda damlab qo'shing) va "
                   "bir chimdim kashnich urug'i."),
                  ("Uy kvasi",
                   "3 litr suvga 3–4 osh qoshiq qora solod, 100–150 g shakar (achish uchun kerak) va bir chimdim "
                   "xamirturush; 1–2 sutka iliq joyda."),
                  ("Pechene va pryanik",
                   "xamirga 1 osh qoshiq qora solod — shokoladsimon rang va ta'm."),
                  ("Oq solod bilan non",
                   "har 500 g unga 1 osh qoshiq oq solod — mag'zi yumshoq, qobig'i chiroyli bo'ladi.")],
            cautions=["Arpa va javdar solodida glyuten bor — seliakiyada yemang.",
                      "Uglevodi bor, kvasda esa shakar — keto va qandli diabet uchun mos emas.",
                      "Ko'p solinsa non achchiq va yopishqoq bo'lib qoladi — me'yorni saqlang."],
            advice="qora solodni xamirga solishdan oldin oz qaynoq suvda damlang — ta'mi to'liq ochiladi."),
        "ru": dict(
            about="Солод — пророщенное и высушенное зерно (ячмень или рожь). Чёрный ферментированный солод даёт "
                  "бородинскому хлебу и квасу тёмный цвет и характерный аромат; белый (светлый) солод — лёгкую "
                  "сладость и красивую корочку.",
            benefits=["Натуральный тёмный цвет и насыщенный аромат хлеба — без красителей",
                      "Источник витаминов группы B и микроэлементов",
                      "Даёт тесту естественную сладость и красивую корочку",
                      "Основа домашнего кваса"],
            uses=[("Бородинский хлеб",
                   "на каждые 500 г ржаной муки — 2–3 ст. л. чёрного солода (заварите небольшим количеством "
                   "кипятка) и щепотка семян кориандра."),
                  ("Домашний квас",
                   "на 3 л воды — 3–4 ст. л. чёрного солода, 100–150 г сахара (нужен для брожения) и щепотка "
                   "дрожжей; 1–2 суток в тепле."),
                  ("Печенье и пряники",
                   "1 ст. л. чёрного солода в тесто — шоколадный цвет и вкус."),
                  ("Хлеб с белым солодом",
                   "1 ст. л. белого солода на 500 г муки — мягкий мякиш и красивая корочка.")],
            cautions=["Ячменный и ржаной солод содержат глютен — при целиакии нельзя.",
                      "Есть углеводы, а в квасе — сахар: не для кето и диабета.",
                      "Если переборщить, хлеб станет горьким и липким — соблюдайте дозировку."],
            advice="перед добавлением в тесто заварите чёрный солод небольшим количеством кипятка — вкус "
                   "раскроется полностью."),
    },
    "sourdough": {
        "uz": dict(
            about="Zakvaska (tabiiy xamirturush) — un va suvdagi yovvoyi achitqi va sut kislotasi bakteriyalari. "
                  "Sanoat xamirturushisiz, haqiqiy non pishirish uchun jonli asos.",
            benefits=["Sekin achish — non oson hazm bo'ladi",
                      "Achish dondagi fitin kislotasini kamaytiradi — minerallar yaxshiroq so'riladi",
                      "Zakvaskali non oddiy oq nondan qon shakarini sekinroq ko'taradi",
                      "Non uzoq yumshoq turadi va kech mog'orlaydi"],
            uses=[("Zakvaskali non",
                   "500 g un + 150 g faol zakvaska + 330 ml suv + 10 g tuz. Qorib, 4–6 soat iliq joyda oshiring, "
                   "shakl berib, 230°C da 40 daqiqa pishiring."),
                  ("Nordon quymoq",
                   "zakvaskaning ortig'ini (boqishda to'kiladigan qismini) qatiq va tuxum bilan aralashtirib, "
                   "quymoq pishiring."),
                  ("Pitsa va lepyoshka",
                   "xamirturush o'rniga 100 g zakvaska — 8–12 soat oshsin, ta'mi boyroq bo'ladi."),
                  ("Zakvaskani boqish",
                   "1 qism zakvaska + 1 qism un + 1 qism suv; xona haroratida 4–8 soatda ikki barobar bo'ladi. "
                   "Muzlatgichda saqlansa, haftada 1 marta boqing.")],
            cautions=["Bug'doy yoki javdar unidagi glyuten zakvaska bilan yo'qolmaydi — seliakiyada yemang.",
                      "Pushti, to'q sariq yoki momiq mog'or paydo bo'lsa — tashlang. Ustidagi kulrang suyuqlik — "
                      "normal, aralashtirib yuboring.",
                      "Faollashtirishni qadoqdagi yo'riqnoma bo'yicha qiling — quruq zakvaska 1–3 kun boqishni "
                      "talab qiladi."],
            advice="tayyorligini tekshiring: bir choy qoshiq zakvaska suvda cho'kmasa — non qilsa bo'ladi."),
        "ru": dict(
            about="Закваска (натуральные дрожжи) — дикие дрожжи и молочнокислые бактерии в муке с водой. Живая "
                  "основа для настоящего хлеба без промышленных дрожжей.",
            benefits=["Медленное брожение — хлеб легче усваивается",
                      "Брожение снижает фитиновую кислоту — минералы усваиваются лучше",
                      "Хлеб на закваске поднимает сахар медленнее обычного белого",
                      "Хлеб дольше остаётся мягким и позже плесневеет"],
            uses=[("Хлеб на закваске",
                   "500 г муки + 150 г активной закваски + 330 мл воды + 10 г соли. Замесите, 4–6 часов "
                   "расстойки в тепле, сформуйте и выпекайте 40 минут при 230°C."),
                  ("Кислые оладьи",
                   "остаток закваски (то, что сливается при подкормке) смешайте с кефиром и яйцом и жарьте оладьи."),
                  ("Пицца и лепёшки",
                   "вместо дрожжей 100 г закваски — расстойка 8–12 часов, вкус богаче."),
                  ("Подкормка закваски",
                   "1 часть закваски + 1 часть муки + 1 часть воды; при комнатной температуре удваивается за "
                   "4–8 часов. В холодильнике подкармливайте раз в неделю.")],
            cautions=["Глютен пшеничной или ржаной муки закваска не убирает — при целиакии нельзя.",
                      "Появилась розовая, оранжевая или пушистая плесень — выбросьте. Серая жидкость сверху — "
                      "норма, просто перемешайте.",
                      "Активируйте по инструкции на упаковке — сухой закваске нужно 1–3 дня подкормок."],
            advice="проверка готовности: чайная ложка закваски не тонет в воде — можно печь."),
    },

    # ──────────────────────────── urug' va yong'oq ────────────────────────────
    "sesame": {
        "uz": dict(
            about="Kunjut — oq (tozalangan) va qora (po'stli) turlari bor. Qora kunjut po'sti bilan qolgani uchun "
                  "kalsiyga ancha boy va ta'mi to'qroq.",
            benefits=["Qora kunjut — kalsiy manbai (100 g da 900 mg gacha); oq kunjutda kamroq",
                      "Sog'lom yog'lar, oqsil (taxminan 18 g/100 g) va tola",
                      "Sezamin va sezamolin — antioksidantlar",
                      "Uglevodi kam — ketoga mos"],
            uses=[("Uy tahinisi (kunjut pastasi)",
                   "200 g kunjutni quruq tovada 3–4 daqiqa qizartiring, blenderda 2–3 osh qoshiq zaytun yog'i "
                   "bilan pasta bo'lguncha aylantiring."),
                  ("Keto kozinaki",
                   "60 g allulozani eriting, 150 g qizartirilgan kunjut qo'shing, pergamentga yoyib sovuting."),
                  ("Non, salat, go'sht",
                   "non ustiga, ko'kat salatga yoki tovuq panirovkasiga 1–2 osh qoshiq.")],
            cautions=["Kunjut — kuchli allergenlardan biri. Allergiya bo'lsa, oz miqdori ham xavfli.",
                      "Kaloriyasi yuqori: 1 osh qoshiqda taxminan 55 kkal.",
                      "Kuydirib yubormang — achchiq bo'lib qoladi; qovurilganini 1–2 oy ichida ishlating."],
            advice="kalsiy uchun maydalab yoki pasta qilib yeng — butun urug' yaxshi hazm bo'lmaydi."),
        "ru": dict(
            about="Кунжут бывает белый (очищенный) и чёрный (с оболочкой). Чёрный сохраняет оболочку, поэтому "
                  "намного богаче кальцием и насыщеннее по вкусу.",
            benefits=["Чёрный кунжут — источник кальция (до 900 мг на 100 г); в белом меньше",
                      "Полезные жиры, белок (около 18 г/100 г) и клетчатка",
                      "Сезамин и сезамолин — антиоксиданты",
                      "Мало углеводов — подходит для кето"],
            uses=[("Домашняя тахини (кунжутная паста)",
                   "обжарьте 200 г кунжута на сухой сковороде 3–4 минуты и перемелите в блендере с 2–3 ст. л. "
                   "оливкового масла до пасты."),
                  ("Кето-козинаки",
                   "растопите 60 г аллюлозы, добавьте 150 г обжаренного кунжута, распределите по пергаменту "
                   "и остудите."),
                  ("Хлеб, салат, мясо",
                   "1–2 ст. л. на хлеб, в зелёный салат или в панировку для курицы.")],
            cautions=["Кунжут — один из сильных аллергенов. При аллергии опасно даже немного.",
                      "Калорийно: около 55 ккал в 1 ст. л.",
                      "Не пережаривайте — будет горчить; обжаренный используйте за 1–2 месяца."],
            advice="ради кальция ешьте молотым или пастой — целые семена плохо усваиваются."),
    },
    "pumpkin_seed": {
        "uz": dict(
            about="Qovoq urug'i (tozalangan) — magniy va ruxning eng yaxshi tabiiy manbalaridan biri, uglevodi kam "
                  "to'yimli gazak.",
            benefits=["Magniy: 100 g da taxminan 550 mg (kunlik ehtiyojdan ko'p) — mushak va uyqu uchun muhim",
                      "Rux va temir manbai",
                      "Oqsil taxminan 30 g/100 g",
                      "Uglevodi kam — ketoga mos gazak"],
            uses=[("Gazak",
                   "bir hovuch (30 g) urug'ni quruq tovada 3 daqiqa qizartirib, bir chimdim tuz seping."),
                  ("Salat va bo'tqa",
                   "1–2 osh qoshiq ustiga seping."),
                  ("Ko'kat pestosi",
                   "1 bog' rayhon yoki ukrop + 40 g qovoq urug'i + 1 bo'lak sarimsoq + 80 ml zaytun yog'i + "
                   "tuz — blenderda."),
                  ("Keto granola",
                   "qovoq urug'i, kunjut, kokos qirindisi va bodomni tuxum oqi va eritritol bilan aralashtirib, "
                   "150°C da 15 daqiqa.")],
            cautions=["Kaloriyasi yuqori (taxminan 560 kkal/100 g) — kuniga bir hovuch yetarli.",
                      "Ko'p yeyilsa ich dam bo'lishi mumkin.",
                      "Allergiya kam uchraydi, lekin bo'lishi mumkin."],
            advice="kuniga 30 g (bir hovuch)."),
        "ru": dict(
            about="Тыквенные семечки (очищенные) — один из лучших природных источников магния и цинка, сытный "
                  "перекус с малым количеством углеводов.",
            benefits=["Магний: около 550 мг на 100 г (больше суточной нормы) — важен для мышц и сна",
                      "Источник цинка и железа",
                      "Белок около 30 г/100 г",
                      "Мало углеводов — кето-перекус"],
            uses=[("Перекус",
                   "горсть (30 г) обжарьте на сухой сковороде 3 минуты и посыпьте щепоткой соли."),
                  ("Салат и каша",
                   "посыпьте 1–2 ст. л."),
                  ("Песто из зелени",
                   "пучок базилика или укропа + 40 г тыквенных семечек + зубчик чеснока + 80 мл оливкового "
                   "масла + соль — в блендере."),
                  ("Кето-гранола",
                   "семечки, кунжут, кокосовая стружка и миндаль с белком и эритритолом, 15 минут при 150°C.")],
            cautions=["Калорийно (около 560 ккал/100 г) — горсти в день достаточно.",
                      "В большом количестве возможно вздутие.",
                      "Аллергия редка, но возможна."],
            advice="30 г (горсть) в день."),
    },
    "nigella": {
        "uz": dict(
            about="Qora sedana — non ustidagi tanish qora urug'. Biroz achchiq, yong'oqsimon ta'mi bor; "
                  "tarkibidagi timoxinon moddasi uchun xalq tabobatida qadrlanadi.",
            benefits=["Antioksidant timoxinon manbai",
                      "Sog'lom yog'lar va tola",
                      "Non, salat va qatiqqa o'ziga xos ta'm",
                      "Muntazam iste'molda qon shakari va xolesterinni biroz yaxshilashga yordam berishi mumkin "
                      "(tadqiqotlar hali cheklangan)"],
            uses=[("Uy noni",
                   "xamir ustiga 1–2 choy qoshiq seping yoki xamirga qo'shing."),
                  ("Salat va suzma",
                   "pomidor-bodring salati yoki suzmaga 1/2 choy qoshiq."),
                  ("Asal bilan (keto bo'lmaganlar uchun)",
                   "1 choy qoshiq ezilgan sedana + 1 choy qoshiq asal — ertalab."),
                  ("Go'sht va sabzavot",
                   "qovurishda yog'ga bir chimdim soling — xushbo'yligi ochiladi.")],
            cautions=["Homiladorlikda ko'p miqdorda (dori sifatida) iste'mol qilmang — taomdagi oz miqdor xavfsiz.",
                      "Qand yoki qon bosimini tushiruvchi dori ichayotgan bo'lsangiz, kuniga ko'p yemang — "
                      "ta'siri qo'shilishi mumkin.",
                      "Rejalashtirilgan jarrohlikdan 2 hafta oldin ko'p iste'molni to'xtating — qon ivishiga "
                      "ta'sir qilishi mumkin."],
            advice="kuniga 1–2 choy qoshiq — taom uchun yetarli."),
        "ru": dict(
            about="Чёрный тмин (седана, нигелла) — знакомые чёрные семена на лепёшке. Горьковато-ореховый вкус; "
                  "ценится в народной медицине за вещество тимохинон.",
            benefits=["Источник антиоксиданта тимохинона",
                      "Полезные жиры и клетчатка",
                      "Особый вкус хлебу, салатам и кисломолочным продуктам",
                      "При регулярном употреблении может немного улучшать сахар и холестерин "
                      "(исследований пока мало)"],
            uses=[("Домашний хлеб",
                   "посыпьте тесто 1–2 ч. л. или добавьте в замес."),
                  ("Салат и сюзьма",
                   "1/2 ч. л. в салат из помидоров и огурцов или в сюзьму."),
                  ("С мёдом (не для кето)",
                   "1 ч. л. молотой седаны + 1 ч. л. мёда — утром."),
                  ("Мясо и овощи",
                   "щепотку в масло при обжарке — раскроется аромат.")],
            cautions=["При беременности не употребляйте в больших (лечебных) количествах — немного в еде безопасно.",
                      "Если принимаете сахароснижающие или препараты от давления, не ешьте много — действие "
                      "может суммироваться.",
                      "За 2 недели до плановой операции прекратите употреблять в больших количествах — может "
                      "влиять на свёртываемость."],
            advice="1–2 ч. л. в день — достаточно для блюд."),
    },
    "milk_thistle": {
        "uz": dict(
            about="Rastaropsha (sut qushqo'nmasi) urug'i va uni. Tarkibidagi silimarin moddasi uchun jigarni "
                  "qo'llab-quvvatlash maqsadida an'anaviy ishlatiladi. Uni (shroti) — yog'i olingan, tolaga boy kukun.",
            benefits=["Silimarin manbai — jigar hujayralarini himoyalovchi antioksidant sifatida o'rganilgan",
                      "Tolaga boy — ichak ishiga yordam beradi",
                      "Uglevodi kam",
                      "Oqsil va mikroelementlar manbai"],
            uses=[("Kefir yoki qatiq bilan",
                   "1 choy qoshiq unni 1 stakan kefirga aralashtirib, ovqatdan 20 daqiqa oldin, kuniga 1–2 marta."),
                  ("Bo'tqa va smuzi",
                   "porsiyaga 1 choy qoshiq."),
                  ("Non va pishiriq",
                   "unning 10–15% ini rastaropsha uni bilan almashtiring."),
                  ("Urug' damlamasi",
                   "1 choy qoshiq urug'ni maydalab, 1 stakan qaynoq suvda 15 daqiqa damlang.")],
            cautions=["Astradoshlarga (ambroziya, moychechak, qoqio't) allergiya bo'lsa — ehtiyot bo'ling.",
                      "Qon shakarini pasaytirishi mumkin — qand dori ichayotganlar shifokor bilan kelishsin.",
                      "Ba'zi dorilar ta'siriga ta'sir qilishi mumkin; homiladorlik va emizishda shifokor "
                      "maslahatisiz ichmang.",
                      "Boshida ich yumshashi yoki ich dam bo'lishi mumkin."],
            advice="kuniga 1–2 choy qoshiq. Bu dori emas — jigar kasalligi bo'lsa, shifokor kuzatuvida bo'ling."),
        "ru": dict(
            about="Расторопша — семена и шрот. Традиционно используется для поддержки печени благодаря "
                  "силимарину. Шрот — обезжиренный порошок, богатый клетчаткой.",
            benefits=["Источник силимарина — изучается как антиоксидант, защищающий клетки печени",
                      "Богата клетчаткой — помогает работе кишечника",
                      "Мало углеводов",
                      "Источник белка и микроэлементов"],
            uses=[("С кефиром или йогуртом",
                   "1 ч. л. шрота на стакан кефира, за 20 минут до еды, 1–2 раза в день."),
                  ("Каша и смузи",
                   "1 ч. л. на порцию."),
                  ("Хлеб и выпечка",
                   "замените шротом 10–15% муки."),
                  ("Настой семян",
                   "1 ч. л. молотых семян залейте стаканом кипятка на 15 минут.")],
            cautions=["При аллергии на сложноцветные (амброзия, ромашка, одуванчик) — осторожно.",
                      "Может снижать сахар — принимающим сахароснижающие согласовать с врачом.",
                      "Может влиять на действие некоторых лекарств; при беременности и кормлении — только "
                      "по совету врача.",
                      "Поначалу возможны послабление стула или вздутие."],
            advice="1–2 ч. л. в день. Это не лекарство — при болезнях печени наблюдайтесь у врача."),
    },
    "pistachio": {
        "uz": dict(
            about="Pista mag'zi — tozalangan, gazak va desert uchun tayyor. Yong'oqlar orasida kaloriyasi "
                  "kamroq va oqsilga boylaridan.",
            benefits=["30 g (taxminan 49 dona) da — taxminan 6 g oqsil va 3 g tola",
                      "Kaliy, B6 vitamini, lyutein va zeaksantin",
                      "To'qlik beradi — sog'lom gazak",
                      "Sog'lom yog'lar"],
            uses=[("Gazak",
                   "bir hovuch (30 g) — ish yoki yo'l uchun."),
                  ("Salat",
                   "ko'kat yoki tvorog salatiga 1–2 osh qoshiq maydalangan pista."),
                  ("Pista pestosi",
                   "50 g pista + 1 bog' rayhon + sarimsoq + 80 ml zaytun yog'i + qattiq pishloq — go'sht yoki "
                   "kabachki «makaron»iga."),
                  ("Desert",
                   "keto muzqaymoq yoki shokoladli desert ustiga.")],
            cautions=["Yong'oqqa allergiya bo'lsa — yemang.",
                      "Kaloriyasi yuqori (taxminan 560 kkal/100 g) — kuniga bir hovuch yetarli.",
                      "Tuzlangan bo'lsa, qon bosimi yuqorilar ehtiyot bo'lsin."],
            advice="og'zi yopiq idishda, salqin joyda saqlang."),
        "ru": dict(
            about="Ядра фисташки — очищенные, готовы для перекуса и десертов. Среди орехов — одни из менее "
                  "калорийных и более белковых.",
            benefits=["В 30 г (около 49 штук) — около 6 г белка и 3 г клетчатки",
                      "Калий, витамин B6, лютеин и зеаксантин",
                      "Насыщают — полезный перекус",
                      "Полезные жиры"],
            uses=[("Перекус",
                   "горсть (30 г) — на работу или в дорогу."),
                  ("Салат",
                   "1–2 ст. л. рубленых фисташек в зелёный или творожный салат."),
                  ("Фисташковое песто",
                   "50 г фисташек + пучок базилика + чеснок + 80 мл оливкового масла + твёрдый сыр — к мясу "
                   "или «пасте» из кабачка."),
                  ("Десерт",
                   "на кето-мороженое или шоколадный десерт.")],
            cautions=["При аллергии на орехи — нельзя.",
                      "Калорийны (около 560 ккал/100 г) — горсти в день достаточно.",
                      "Если солёные — осторожно при повышенном давлении."],
            advice="храните в закрытой таре в прохладном месте."),
    },
    "nut_paste": {
        "uz": dict(
            about="Yong'oq pastasi — maydalangan pista yoki yeryong'oqdan tayyorlangan quyuq pasta. Sog'lom yog' "
                  "va oqsil manbai, tez to'ydiradi.",
            benefits=["Oqsil (yeryong'oqda taxminan 25 g/100 g) va sog'lom yog'lar",
                      "Uzoq to'qlik beradi",
                      "Magniy va E vitamini manbai",
                      "Shakarsiz bo'lsa uglevodi kam — ketoga mos"],
            uses=[("Nonushta",
                   "keto non yoki selderey poyasiga 1 osh qoshiq."),
                  ("Smuzi",
                   "1 osh qoshiq pasta + sut + kakao + muz — to'yimli ichimlik."),
                  ("Yong'oqli sous",
                   "2 osh qoshiq pasta + 1 osh qoshiq soya sousi + limon sharbati + iliq suv — tovuq yoki salat uchun."),
                  ("Desert krem",
                   "pasta + tvorog yoki maskarpone + shirinlashtirgich.")],
            cautions=["Yeryong'oq — eng xavfli allergenlardan biri: allergiyasi bor odamga oz miqdori ham xavfli.",
                      "Kaloriyasi yuqori: 1 osh qoshiqda taxminan 95 kkal.",
                      "Tarkibiga qarang: shakar qo'shilgan bo'lsa, keto uchun mos emas.",
                      "Ustiga yog' chiqishi — tabiiy; ishlatishdan oldin aralashtiring."],
            advice="kuniga 1–2 osh qoshiq."),
        "ru": dict(
            about="Ореховая паста — густая паста из фисташек или арахиса. Источник полезных жиров и белка, "
                  "быстро насыщает.",
            benefits=["Белок (в арахисе около 25 г/100 г) и полезные жиры",
                      "Долгая сытость",
                      "Источник магния и витамина E",
                      "Без сахара — мало углеводов, подходит для кето"],
            uses=[("Завтрак",
                   "1 ст. л. на кето-хлеб или стебель сельдерея."),
                  ("Смузи",
                   "1 ст. л. пасты + молоко + какао + лёд — сытный напиток."),
                  ("Ореховый соус",
                   "2 ст. л. пасты + 1 ст. л. соевого соуса + лимонный сок + тёплая вода — к курице или салату."),
                  ("Крем для десерта",
                   "паста + творог или маскарпоне + сахарозаменитель.")],
            cautions=["Арахис — один из самых опасных аллергенов: при аллергии опасно даже немного.",
                      "Калорийно: около 95 ккал в 1 ст. л.",
                      "Смотрите состав: если добавлен сахар — не для кето.",
                      "Масло сверху — это естественно; перемешайте перед использованием."],
            advice="1–2 ст. л. в день."),
    },

    # ──────────────────────────── shokolad va kakao ────────────────────────────
    "chocolate": {
        "uz": dict(
            about="Qora shokolad va shakarsiz kakao granulalari. Kakao foizi qancha yuqori bo'lsa, shakar shuncha "
                  "kam: 100% va «shakarsiz» — shakarsiz; 57–72% da shakar bor.",
            benefits=["Kakao flavanollari — qon tomirlari uchun foydali antioksidantlar",
                      "Magniy, temir va mis manbai",
                      "Kayfiyatni ko'taradi (teobromin)",
                      "100% va shakarsiz turlari — ketoga mos"],
            uses=[("Ganash (glazur)",
                   "100 g shokolad + 100 ml issiq qaymoq yoki kokos qaymog'i — aralashtirib, keks ustiga quying."),
                  ("Keto pechene",
                   "bodom unli pechene xamiriga 50 g shokolad granulasi."),
                  ("Issiq shokolad",
                   "250 ml sut + 20 g shokolad + bir chimdim dolchin — eriguncha qizdiring."),
                  ("Rezavor va yong'oq",
                   "eritilgan shokoladga qulupnay yoki yong'oqni botirib, muzlatgichda qoting.")],
            cautions=["57–72% shokoladda shakar bor — keto va qandli diabetda 2–3 bo'lakdan oshirmang. Keto uchun "
                      "100% yoki shakarsiz turini oling.",
                      "Kofein va teobromin bor — kechqurun, homiladorlikda va yurak tez urganda ko'p yemang.",
                      "Itlar va mushuklar uchun zaharli — ularga bermang!",
                      "Migren va zarda qaynashini qo'zg'atishi mumkin; yong'oqli turida yong'oq allergiyasi "
                      "borlar ehtiyot bo'lsin."],
            advice="kuniga 20–30 g — foydasi uchun yetarli."),
        "ru": dict(
            about="Тёмный шоколад и гранулы какао без сахара. Чем выше процент какао, тем меньше сахара: 100% и "
                  "«без сахара» — без сахара; в 57–72% сахар есть.",
            benefits=["Флаванолы какао — антиоксиданты, полезные для сосудов",
                      "Источник магния, железа и меди",
                      "Поднимает настроение (теобромин)",
                      "100% и варианты без сахара подходят для кето"],
            uses=[("Ганаш (глазурь)",
                   "100 г шоколада + 100 мл горячих сливок или кокосовых сливок — перемешайте и полейте кекс."),
                  ("Кето-печенье",
                   "50 г шоколадных гранул в тесто на миндальной муке."),
                  ("Горячий шоколад",
                   "250 мл молока + 20 г шоколада + щепотка корицы — нагрейте до растворения."),
                  ("Ягоды и орехи",
                   "обмакните клубнику или орехи в растопленный шоколад и уберите в холодильник.")],
            cautions=["В шоколаде 57–72% есть сахар — на кето и при диабете не больше 2–3 долек. Для кето "
                      "берите 100% или без сахара.",
                      "Есть кофеин и теобромин — не налегайте вечером, при беременности и учащённом сердцебиении.",
                      "Ядовит для собак и кошек — не давайте им!",
                      "Может провоцировать мигрень и изжогу; в варианте с орехами — осторожно при аллергии на орехи."],
            advice="20–30 г в день — достаточно для пользы."),
    },
    "cacao_nibs": {
        "uz": dict(
            about="Kakao nibs — qovurilgan va maydalangan kakao loviyasi bo'laklari. Shakarsiz, biroz achchiq, "
                  "qarsildoq — shokoladning eng tabiiy shakli.",
            benefits=["Shakar qo'shilmagan — ketoga mos",
                      "Tolaga boy (taxminan 30 g/100 g)",
                      "Magniy, temir va kakao antioksidantlari",
                      "Qarsildoq — yong'oq o'rnida ishlatsa bo'ladi"],
            uses=[("Yogurt va bo'tqa",
                   "porsiyaga 1 osh qoshiq — shokoladsimon qarsildoqlik."),
                  ("Smuzi",
                   "1 osh qoshiq nibs + rezavor + sut."),
                  ("Keto pechene",
                   "shokolad bo'lakchalari o'rniga xamirga 2–3 osh qoshiq."),
                  ("Keto granola",
                   "yong'oq, urug'lar va kokos qirindisi bilan aralashtiring.")],
            cautions=["Kofein va teobromin bor — kechqurun ko'p yemang.",
                      "Achchiq ta'mga o'rganish kerak — shirinlashtirgich bilan birga ishlating.",
                      "Oksalatlarga boy — buyrakda tosh bo'lsa, me'yorida.",
                      "Itlar uchun zaharli."],
            advice="kuniga 1–2 osh qoshiq."),
        "ru": dict(
            about="Какао-крупка (нибс) — дроблёные обжаренные какао-бобы. Без сахара, слегка горькая, хрустящая — "
                  "самая натуральная форма шоколада.",
            benefits=["Без добавленного сахара — подходит для кето",
                      "Много клетчатки (около 30 г/100 г)",
                      "Магний, железо и антиоксиданты какао",
                      "Хрустит — можно использовать вместо орехов"],
            uses=[("Йогурт и каша",
                   "1 ст. л. на порцию — шоколадный хруст."),
                  ("Смузи",
                   "1 ст. л. крупки + ягоды + молоко."),
                  ("Кето-печенье",
                   "2–3 ст. л. в тесто вместо шоколадных капель."),
                  ("Кето-гранола",
                   "смешайте с орехами, семечками и кокосовой стружкой.")],
            cautions=["Есть кофеин и теобромин — не ешьте много вечером.",
                      "К горечи нужно привыкнуть — сочетайте с сахарозаменителем.",
                      "Богата оксалатами — при камнях в почках умеренно.",
                      "Ядовита для собак."],
            advice="1–2 ст. л. в день."),
    },
    "keto_icecream": {
        "uz": dict(
            about="Keto muzqaymoq — qo'shilgan shakarsiz, shirinlashtirgich bilan tayyorlangan muzqaymoq. Ta'mi "
                  "odatdagidek, uglevodi esa minimal.",
            benefits=["Qo'shilgan shakar yo'q",
                      "Uglevodi kam — ketoda ham shirinlik",
                      "Qon shakarini oddiy muzqaymoqdek keskin ko'tarmaydi",
                      "Oz miqdori — katta qoniqish"],
            uses=[("Klassik desert",
                   "yong'oq, kakao nibs yoki rezavor bilan."),
                  ("Affogato",
                   "1 shar muzqaymoq ustiga 1 porsiya issiq espresso."),
                  ("Milkshake",
                   "2 shar muzqaymoq + 200 ml sut yoki kokos suti — blenderda."),
                  ("Keto keks bilan",
                   "issiq keks yoki pechene yonida.")],
            cautions=["Shirinlashtirgichlar ko'p yeyilsa ich dam bo'lishi mumkin — 1–2 shar yetarli.",
                      "«Shakarsiz» — «kaloriyasiz» degani emas.",
                      "Tarkibiga qarang: sut, yong'oq yoki tuxumga allergiya bo'lsa.",
                      "Erigach qayta muzlatmang."],
            advice="muzlatgichdan olib, 3–5 daqiqa tursin — yumshoq va mazali bo'ladi."),
        "ru": dict(
            about="Кето-мороженое — без добавленного сахара, на сахарозаменителе. Вкус привычный, углеводов — "
                  "минимум.",
            benefits=["Без добавленного сахара",
                      "Мало углеводов — сладкое и на кето",
                      "Не поднимает сахар так резко, как обычное мороженое",
                      "Немного — а удовольствия много"],
            uses=[("Классический десерт",
                   "с орехами, какао-крупкой или ягодами."),
                  ("Аффогато",
                   "шарик мороженого и порция горячего эспрессо сверху."),
                  ("Милкшейк",
                   "2 шарика мороженого + 200 мл молока или кокосового молока — в блендере."),
                  ("С кето-кексом",
                   "рядом с тёплым кексом или печеньем.")],
            cautions=["Сахарозаменители в большом количестве могут вызвать вздутие — 1–2 шариков достаточно.",
                      "«Без сахара» не значит «без калорий».",
                      "Смотрите состав при аллергии на молоко, орехи или яйца.",
                      "Не замораживайте повторно после таяния."],
            advice="достаньте из морозилки за 3–5 минут — станет мягким и вкуснее."),
    },

    # ──────────────────────────────── kokos ────────────────────────────────
    "coconut_cream": {
        "uz": dict(
            about="Kokos qaymog'i (slivka) — kokos mag'zidan olinadigan quyuq, yog'li sut. Sut mahsulotisiz "
                  "qaymoq o'rnini bosadi.",
            benefits=["Sut va laktozasiz — sutni ko'tara olmaydiganlar uchun",
                      "Yog'li va kam uglevodli — ketoga mos",
                      "Kokos yog'lari — tez energiya",
                      "Taomga mayin, kremsimon tekstura"],
            uses=[("Krem-sho'rva va kari",
                   "tovuq yoki sabzavotli sho'rvaga 100–200 ml — qaymoqdek mayin."),
                  ("Ko'pirtirilgan krem",
                   "bankani kechasi muzlatgichda saqlang, ustki quyuq qismini shirinlashtirgich bilan 3–4 daqiqa "
                   "ko'pirting."),
                  ("Qahva va smuzi",
                   "sut o'rniga 2–3 osh qoshiq."),
                  ("Chia puding",
                   "3 osh qoshiq chia + 200 ml kokos qaymog'i — kechasi muzlatgichda.")],
            cautions=["Kaloriyasi va to'yingan yog'i yuqori — porsiyani nazorat qiling.",
                      "Ochilgach shisha idishga o'tkazib, muzlatgichda 3–4 kun saqlang.",
                      "Yog'i ustiga ajralib chiqishi tabiiy — aralashtiring yoki iliting."],
            advice="ishlatishdan oldin bankani yaxshilab chayqating."),
        "ru": dict(
            about="Кокосовые сливки — густое жирное молоко из мякоти кокоса. Заменяют сливки без молочных продуктов.",
            benefits=["Без молока и лактозы — для тех, кто не переносит молоко",
                      "Жирные и низкоуглеводные — подходят для кето",
                      "Кокосовые жиры — быстрая энергия",
                      "Нежная сливочная текстура блюд"],
            uses=[("Крем-суп и карри",
                   "100–200 мл в суп с курицей или овощами — нежно, как со сливками."),
                  ("Взбитые сливки",
                   "уберите банку на ночь в холодильник, верхний густой слой взбейте с сахарозаменителем 3–4 минуты."),
                  ("Кофе и смузи",
                   "2–3 ст. л. вместо молока."),
                  ("Чиа-пудинг",
                   "3 ст. л. чиа + 200 мл кокосовых сливок — на ночь в холодильник.")],
            cautions=["Калорийны и богаты насыщенными жирами — следите за порцией.",
                      "После вскрытия переложите в стекло и храните в холодильнике 3–4 дня.",
                      "Отделение жира сверху — естественно; перемешайте или подогрейте."],
            advice="перед использованием хорошо встряхните банку."),
    },
    "coconut_flakes": {
        "uz": dict(
            about="Kokos chipslari va qirindisi — quritilgan kokos mag'zi. Tabiiy shirin, tolaga boy; keto "
                  "gazak va desertlar uchun.",
            benefits=["Tola taxminan 16 g/100 g",
                      "Kokos yog'lari — tez energiya",
                      "Glyuten va sutsiz",
                      "Shakarsiz bo'lsa sof uglevodi kam"],
            uses=[("Gazak",
                   "chipsni quruq tovada 2 daqiqa qizartiring — qarsildoq gazak."),
                  ("Keto granola",
                   "kokos + yong'oq + urug'lar + 1 osh qoshiq kokos yog'i + eritritol, 150°C da 15 daqiqa."),
                  ("Kokos panirovka",
                   "tovuq yoki krevetkani tuxumga, keyin kokos qirindisiga botirib pishiring."),
                  ("Keto konfet",
                   "kokos qirindisi + kokos qaymog'i + shirinlashtirgich — sharcha qilib, muzlatgichda qoting.")],
            cautions=["Kaloriyasi yuqori (taxminan 650 kkal/100 g) — bir hovuch yetarli.",
                      "To'yingan yog'i ko'p — xolesterin yuqori bo'lsa me'yorida.",
                      "Tarkibiga qarang: shakarli bo'lsa, keto uchun mos emas."],
            advice="og'zi yopiq idishda saqlang — namni tortib yumshab qoladi."),
        "ru": dict(
            about="Кокосовые чипсы и стружка — сушёная мякоть кокоса. Естественно сладкие, богаты клетчаткой; "
                  "для кето-перекусов и десертов.",
            benefits=["Клетчатки около 16 г/100 г",
                      "Кокосовые жиры — быстрая энергия",
                      "Без глютена и молока",
                      "Без сахара — мало чистых углеводов"],
            uses=[("Перекус",
                   "обжарьте чипсы 2 минуты на сухой сковороде — хрустящий перекус."),
                  ("Кето-гранола",
                   "кокос + орехи + семечки + 1 ст. л. кокосового масла + эритритол, 15 минут при 150°C."),
                  ("Кокосовая панировка",
                   "курицу или креветки — в яйцо, затем в стружку, и запекайте."),
                  ("Кето-конфеты",
                   "стружка + кокосовые сливки + сахарозаменитель — скатайте шарики и охладите.")],
            cautions=["Калорийно (около 650 ккал/100 г) — горсти достаточно.",
                      "Много насыщенных жиров — при высоком холестерине умеренно.",
                      "Смотрите состав: с сахаром — не для кето."],
            advice="храните закрытыми — впитывают влагу и теряют хруст."),
    },

    # ──────────────────────────────── yog'lar ────────────────────────────────
    "olive_oil": {
        "uz": dict(
            about="Zaytun yog'i ikki xil: sovuq siqim (birinchi siqim) — salat va tayyor taom uchun, polifenollarga "
                  "boy; «qovurish uchun» — yuqori haroratga chidamli, qovurish va dimlashga.",
            benefits=["Olein kislotasi (taxminan 70%) — yurak uchun foydali to'yinmagan yog'",
                      "Sovuq siqimda polifenollar va E vitamini — antioksidantlar",
                      "O'rta yer dengizi parhezining asosi",
                      "Ketoda sog'lom yog' manbai"],
            uses=[("Salat zapravkasi (sovuq siqim)",
                   "3 osh qoshiq yog' + 1 osh qoshiq limon sharbati yoki sirka + tuz + sarimsoq."),
                  ("Qovurish va dimlash",
                   "«qovurish uchun» yog'ida go'sht, sabzavot, palov — yuqori olovda ham tutamaydi."),
                  ("Tayyor taom ustiga",
                   "sho'rva, grechka yoki baliq ustiga 1 choy qoshiq sovuq siqim yog'i."),
                  ("Marinad",
                   "yog' + limon + rozmarin + sarimsoq — tovuq va baliq uchun.")],
            cautions=["Kaloriyasi yuqori: 1 osh qoshiqda taxminan 120 kkal — o'lchab soling.",
                      "Sovuq siqim yog'ini tutun chiqqunicha qizdirmang — foydasi yo'qoladi; qovurishga «qovurish "
                      "uchun» yog'ini oling.",
                      "Yorug'lik va issiqda achiydi — qorong'i, salqin joyda saqlang; taxir hid chiqsa ishlatmang."],
            advice="kuniga 2–3 osh qoshiq — sog'lom me'yor."),
        "ru": dict(
            about="Оливковое масло бывает двух видов: холодного отжима (Extra Virgin) — для салатов и готовых "
                  "блюд, богато полифенолами; «для жарки» — выдерживает высокую температуру.",
            benefits=["Олеиновая кислота (около 70%) — полезный для сердца ненасыщенный жир",
                      "В маслах холодного отжима — полифенолы и витамин E, антиоксиданты",
                      "Основа средиземноморской диеты",
                      "Источник полезного жира на кето"],
            uses=[("Заправка для салата (холодный отжим)",
                   "3 ст. л. масла + 1 ст. л. лимонного сока или уксуса + соль + чеснок."),
                  ("Жарка и тушение",
                   "на масле «для жарки» — мясо, овощи, плов; не дымит даже на сильном огне."),
                  ("Поверх готового блюда",
                   "1 ч. л. масла холодного отжима на суп, гречку или рыбу."),
                  ("Маринад",
                   "масло + лимон + розмарин + чеснок — для курицы и рыбы.")],
            cautions=["Калорийно: около 120 ккал в 1 ст. л. — отмеряйте.",
                      "Масло холодного отжима не нагревайте до дыма — теряет пользу; для жарки берите масло "
                      "«для жарки».",
                      "На свету и в тепле горкнет — храните в тёмном прохладном месте; появилась горечь в "
                      "запахе — не используйте."],
            advice="2–3 ст. л. в день — здоровая норма."),
    },
    "coconut_oil": {
        "uz": dict(
            about="Kokos yog'i (sovuq siqim) — xona haroratida qotib turadigan, kokos ta'mli yog'. Qovurish, "
                  "pishiriq va keto qahva uchun.",
            benefits=["O'rta zanjirli yog' kislotalari — tez energiyaga aylanadi, keto uchun qulay",
                      "Laurin kislotasi (taxminan 50%)",
                      "Issiqqa chidamli — o'rta olovda qovurishga mos",
                      "Sariyog' o'rnini bosadi — sut mahsulotisiz"],
            uses=[("Keto qahva",
                   "1 stakan qahva + 1 choy qoshiq kokos yog'i + 1 choy qoshiq sariyog' — blenderda ko'pirting."),
                  ("Qovurish",
                   "tuxum, sabzavot, tovuq — o'rta olovda."),
                  ("Pishiriq",
                   "sariyog' o'rniga 1:1 (eritilgan holda) — keks, pechene, granola."),
                  ("Uy shokoladi",
                   "50 g kokos yog'i + 3 osh qoshiq kakao + shirinlashtirgich — qolipga quyib, muzlatgichga.")],
            cautions=["Taxminan 90% to'yingan yog' — ba'zi odamlarda «yomon» xolesterinni oshirishi mumkin. "
                      "Kuniga 1–2 osh qoshiqdan oshirmang.",
                      "Yurak-qon tomir kasalligi yoki xolesterin yuqori bo'lsa — shifokor bilan maslahatlashing.",
                      "Keto qahvada boshida ich ketishi mumkin — 1 choy qoshiqdan boshlang."],
            advice="24°C dan pastda qotadi — bu normal; iliq suvda eriting."),
        "ru": dict(
            about="Кокосовое масло (холодного отжима) — твёрдое при комнатной температуре, со вкусом кокоса. "
                  "Для жарки, выпечки и кето-кофе.",
            benefits=["Среднецепочечные жирные кислоты — быстро превращаются в энергию, удобно на кето",
                      "Лауриновая кислота (около 50%)",
                      "Термостойкое — подходит для жарки на среднем огне",
                      "Заменяет сливочное масло без молочных продуктов"],
            uses=[("Кето-кофе",
                   "стакан кофе + 1 ч. л. кокосового масла + 1 ч. л. сливочного — взбейте в блендере."),
                  ("Жарка",
                   "яйца, овощи, курица — на среднем огне."),
                  ("Выпечка",
                   "вместо сливочного масла 1:1 (в растопленном виде) — кексы, печенье, гранола."),
                  ("Домашний шоколад",
                   "50 г кокосового масла + 3 ст. л. какао + сахарозаменитель — разлейте в формочки и в "
                   "холодильник.")],
            cautions=["Около 90% насыщенных жиров — у некоторых людей повышает «плохой» холестерин. Не больше "
                      "1–2 ст. л. в день.",
                      "При сердечно-сосудистых заболеваниях или высоком холестерине — посоветуйтесь с врачом.",
                      "В кето-кофе поначалу возможно послабление стула — начните с 1 ч. л."],
            advice="ниже 24°C застывает — это нормально; растопите на тёплой воде."),
    },
    "ghee_butter": {
        "uz": dict(
            about="Uy sariyog'i va eritilgan sariyog' (gi). Gi — suvi va sut oqsillari olib tashlangan sof "
                  "sariyog': juda yuqori haroratga chidaydi va laktozasi deyarli yo'q.",
            benefits=["A, D, E va K vitaminlari manbai",
                      "Eritilgan sariyog' 250°C gacha qizdirilsa ham tutamaydi — qovurish va palov uchun",
                      "Eritilgan sariyog'da laktoza deyarli yo'q — sutni ko'tara olmaydiganlar ko'pincha yaxshi "
                      "o'zlashtiradi",
                      "Uglevodsiz — ketoga mos"],
            uses=[("Palov va qovurish",
                   "o'simlik yog'i o'rniga eritilgan sariyog' — taom xushbo'y, kuyish hidi yo'q."),
                  ("Keto qahva",
                   "1 stakan qahva + 1 choy qoshiq sariyog' — blenderda ko'pirting."),
                  ("Bo'tqa va sabzavot",
                   "tayyor taom ustiga 1 choy qoshiq."),
                  ("Pishiriq",
                   "keks va pechenega — ta'mi boy chiqadi.")],
            cautions=["To'yingan yog' va kaloriyasi yuqori (1 osh qoshiqda taxminan 110–120 kkal) — xolesterin "
                      "yuqori yoki yurak kasalligida me'yorida.",
                      "Sut oqsiliga allergiya bo'lsa sariyog' yemang; eritilganida ham iz miqdorda oqsil qolishi mumkin.",
                      "Sariyog'ni muzlatgichda saqlang; eritilgan sariyog' yopiq idishda xona haroratida ham turadi."],
            advice="kuniga 1–2 osh qoshiq yog' — sog'lom me'yor."),
        "ru": dict(
            about="Домашнее сливочное масло и топлёное (гхи). Гхи — чистый молочный жир без воды и молочных "
                  "белков: выдерживает очень высокую температуру и почти не содержит лактозы.",
            benefits=["Источник витаминов A, D, E и K",
                      "Топлёное масло не дымит до 250°C — для жарки и плова",
                      "В топлёном масле почти нет лактозы — люди с непереносимостью молока часто его хорошо переносят",
                      "Без углеводов — подходит для кето"],
            uses=[("Плов и жарка",
                   "топлёное масло вместо растительного — блюдо ароматное, без запаха гари."),
                  ("Кето-кофе",
                   "стакан кофе + 1 ч. л. масла — взбейте в блендере."),
                  ("Каши и овощи",
                   "1 ч. л. в готовое блюдо."),
                  ("Выпечка",
                   "в кексы и печенье — вкус богаче.")],
            cautions=["Много насыщенных жиров и калорий (около 110–120 ккал в 1 ст. л.) — при высоком холестерине "
                      "или болезнях сердца умеренно.",
                      "При аллергии на белок молока — сливочное масло нельзя; в топлёном тоже могут остаться следы белка.",
                      "Сливочное масло храните в холодильнике; топлёное в закрытой банке может стоять при комнатной "
                      "температуре."],
            advice="1–2 ст. л. масла в день — здоровая норма."),
    },

    # ───────────────────────────── baliq ─────────────────────────────
    "salmon": {
        "uz": dict(
            about="Losos tushonkasi — tayyor baliq, pishirish shart emas. Sifatli oqsil va omega-3 ning eng qulay "
                  "manbalaridan biri.",
            benefits=["Oqsil taxminan 20 g/100 g",
                      "Omega-3 yog' kislotalari — yurak va miya uchun foydali",
                      "D va B12 vitaminlari",
                      "Uglevod yo'q — ketoga mos"],
            uses=[("Salat",
                   "1 stakan losos + 2 ta qaynatilgan tuxum + bodring + ko'k piyoz + 1 osh qoshiq qatiq yoki mayonez."),
                  ("Baliq sho'rva",
                   "gulkaram, sabzi va piyoz qaynagach, losos va ko'kat qo'shib, yana 5 daqiqa."),
                  ("Keto non bilan",
                   "keto bulochka ustiga tvorog pishlog'i va losos."),
                  ("Omlet",
                   "3 tuxum + 100 g losos + ko'kat — tovada yoki pechda.")],
            cautions=["Qopqog'i shishgan, ochilganda «pishillagan» yoki hidi g'alati bo'lsa — mutlaqo yemang "
                      "(botulizm xavfi).",
                      "Ochilgandan keyin muzlatgichda 1–2 kun saqlang.",
                      "Tuzi bor — qon bosimi yuqori bo'lsa, qo'shimcha tuz solmang.",
                      "Baliqqa allergiya bo'lsa — yemang."],
            advice="haftasiga 2 marta baliq — omega-3 uchun yaxshi me'yor."),
        "ru": dict(
            about="Рагу из лосося — готовая рыба, варить не нужно. Один из самых удобных источников качественного "
                  "белка и омеги-3.",
            benefits=["Белок около 20 г/100 г",
                      "Омега-3 жирные кислоты — полезны для сердца и мозга",
                      "Витамины D и B12",
                      "Без углеводов — подходит для кето"],
            uses=[("Салат",
                   "стакан лосося + 2 варёных яйца + огурец + зелёный лук + 1 ст. л. йогурта или майонеза."),
                  ("Рыбный суп",
                   "когда цветная капуста, морковь и лук сварятся, добавьте лосось и зелень — ещё 5 минут."),
                  ("С кето-хлебом",
                   "творожный сыр и лосось на кето-булочке."),
                  ("Омлет",
                   "3 яйца + 100 г лосося + зелень — на сковороде или в духовке.")],
            cautions=["Вздутая крышка, «шипение» при вскрытии или странный запах — не ешьте ни в коем случае "
                      "(риск ботулизма).",
                      "После вскрытия храните в холодильнике 1–2 дня.",
                      "Есть соль — при высоком давлении не досаливайте.",
                      "При аллергии на рыбу — нельзя."],
            advice="рыба 2 раза в неделю — хорошая норма для омеги-3."),
    },

    # ─────────────────────── sirka, tuz va ziravorlar ───────────────────────
    "vinegar": {
        "uz": dict(
            about="Olma sirkasi (5%) — olma sharbatini tabiiy achitib olinadi. Taomga nordonlik beradi va "
                  "ovqatdan keyingi qon shakarini biroz tekislashga yordam berishi mumkin.",
            benefits=["Salat va marinadga tabiiy nordonlik — yog' va tuzni kamroq ishlatish imkoni",
                      "Ovqat oldidan suyultirib ichilsa, ovqatdan keyingi qon shakari keskin ko'tarilishini biroz "
                      "kamaytirishi mumkin",
                      "To'qlik hissini uzaytirishi mumkin",
                      "Kaloriyasi deyarli yo'q"],
            uses=[("Salat zapravkasi",
                   "3 osh qoshiq zaytun yog'i + 1 osh qoshiq olma sirkasi + 1/2 choy qoshiq xantal + tuz, qalampir."),
                  ("Go'sht marinadi",
                   "1 kg go'shtga 3–4 osh qoshiq sirka + piyoz + ziravor, 2–4 soat — go'sht yumshoq bo'ladi."),
                  ("Ovqat oldidan ichimlik",
                   "1 osh qoshiq sirkani 1 stakan (250 ml) suvga solib, ovqatdan 10–15 daqiqa oldin trubochka "
                   "orqali iching."),
                  ("Tez tuzlama",
                   "bodring yoki karam: 1 stakan suv + 1/2 stakan sirka + 1 choy qoshiq tuz + ziravor, 1 sutka "
                   "muzlatgichda.")],
            cautions=["Hech qachon suyultirmasdan ichmang — tish emali, og'iz va qizilo'ngachni kuydiradi. "
                      "Ichgach og'izni suv bilan chayqang.",
                      "Gastrit, oshqozon yarasi yoki zarda qaynashi bo'lsa — ichimlik sifatida iste'mol qilmang.",
                      "Insulin, siydik haydovchi yoki yurak dorilari ichayotgan bo'lsangiz, har kuni ichishdan "
                      "oldin shifokor bilan maslahatlashing (kaliyni kamaytirishi mumkin)."],
            advice="kuniga 1–2 osh qoshiq, faqat suyultirilgan holda."),
        "ru": dict(
            about="Яблочный уксус (5%) — получают натуральным брожением яблочного сока. Даёт блюдам кислинку и "
                  "может немного сглаживать подъём сахара после еды.",
            benefits=["Натуральная кислинка для салатов и маринадов — можно меньше масла и соли",
                      "Разбавленный перед едой может немного уменьшать резкий подъём сахара после еды",
                      "Может продлевать чувство сытости",
                      "Почти без калорий"],
            uses=[("Заправка для салата",
                   "3 ст. л. оливкового масла + 1 ст. л. яблочного уксуса + 1/2 ч. л. горчицы + соль, перец."),
                  ("Маринад для мяса",
                   "на 1 кг мяса 3–4 ст. л. уксуса + лук + специи, 2–4 часа — мясо станет мягче."),
                  ("Напиток перед едой",
                   "1 ст. л. уксуса на стакан (250 мл) воды, через трубочку, за 10–15 минут до еды."),
                  ("Быстрые соленья",
                   "огурцы или капуста: стакан воды + полстакана уксуса + 1 ч. л. соли + специи, сутки в "
                   "холодильнике.")],
            cautions=["Никогда не пейте неразбавленным — обжигает эмаль, рот и пищевод. После питья "
                      "прополощите рот водой.",
                      "При гастрите, язве или изжоге — не употребляйте как напиток.",
                      "Если принимаете инсулин, мочегонные или сердечные препараты — посоветуйтесь с врачом перед "
                      "ежедневным приёмом (может снижать калий)."],
            advice="1–2 ст. л. в день, только в разбавленном виде."),
    },
    "salt": {
        "uz": dict(
            about="Himoloy tuzi — qayta ishlanmagan, oqartirilmagan tosh tuz. Pushti rangi temir va boshqa "
                  "minerallardan. Taomga xuddi oddiy tuzdek ta'm beradi.",
            benefits=["Qo'shimchasiz: oqartiruvchi va qotishga qarshi moddalar yo'q",
                      "Keto boshida yo'qotiladigan natriyni to'ldirishga yordam beradi — «keto grippi»dagi bosh "
                      "og'rig'i va holsizlikni yengillatadi",
                      "Yirik kristallari tuz tegirmoni uchun qulay",
                      "Mikroelementlar bor, lekin juda oz — asosiy afzalligi «toza tuz»"],
            uses=[("Kundalik taom",
                   "oddiy tuz o'rniga xuddi shu miqdorda — sho'rva, salat, go'sht."),
                  ("Keto boshlanishida",
                   "1 stakan suvga 1/4 choy qoshiq tuz va limon sharbati — holsizlik va bosh og'rig'ida kuniga 1–2 marta."),
                  ("Go'sht va baliq",
                   "pishirishdan 30–40 daqiqa oldin yirik tuz bilan surting — sharbati ichida qoladi.")],
            cautions=["Bu ham natriy: yuqori qon bosimi, buyrak yoki yurak kasalligida tuzni cheklang.",
                      "Yodlanmagan! O'zbekiston yod tanqis hudud — faqat shu tuzni ishlatsangiz, yodni yodlangan "
                      "tuz, baliq yoki dengiz mahsulotlaridan oling.",
                      "Jahon sog'liqni saqlash tashkiloti tavsiyasi: kuniga 5 g dan (1 choy qoshiq) oshirmang."],
            advice="pushti tuz oddiy tuzdan «foydaliroq» emas, tabiiyroq. Me'yorni saqlang."),
        "ru": dict(
            about="Гималайская соль — необработанная, неотбеленная каменная соль. Розовый цвет — от железа и "
                  "других минералов. На вкус — как обычная соль.",
            benefits=["Без добавок: нет отбеливателей и антислёживателей",
                      "Помогает восполнить натрий, теряемый в начале кето, — облегчает головную боль и слабость "
                      "«кето-гриппа»",
                      "Крупные кристаллы удобны для мельницы",
                      "Микроэлементы есть, но их очень мало — главное преимущество в «чистой соли»"],
            uses=[("Повседневные блюда",
                   "вместо обычной соли в том же количестве — супы, салаты, мясо."),
                  ("В начале кето",
                   "1/4 ч. л. соли и лимонный сок на стакан воды — при слабости и головной боли 1–2 раза в день."),
                  ("Мясо и рыба",
                   "натрите крупной солью за 30–40 минут до готовки — сок останется внутри.")],
            cautions=["Это тоже натрий: при высоком давлении, болезнях почек или сердца ограничивайте соль.",
                      "Не йодирована! Узбекистан — йододефицитный регион: если пользуетесь только этой солью, "
                      "получайте йод из йодированной соли, рыбы или морепродуктов.",
                      "Рекомендация ВОЗ: не больше 5 г соли в день (1 ч. л.)."],
            advice="розовая соль не «полезнее» обычной, а натуральнее. Соблюдайте норму."),
    },
    "cinnamon": {
        "uz": dict(
            about="Dolchin (koritsa) — shirinlik hissini kuchaytiradigan xushbo'y ziravor: shakarsiz taom ham "
                  "shirinroq tuyuladi.",
            benefits=["Shakarsiz shirinlik hissi — shakarni kamroq solishga yordam beradi",
                      "Antioksidantlarga boy",
                      "Ovqatdan keyingi qon shakarini biroz tekislashga yordam berishi mumkin",
                      "Kaloriyasi deyarli yo'q"],
            uses=[("Qahva va choy",
                   "chashkaga bir chimdim yoki dolchin tayoqchasi — shakarsiz ham shirin ta'm."),
                  ("Bo'tqa, tvorog, olma",
                   "porsiyaga 1/4 choy qoshiq; pechda pishirilgan olmaga dolchin va eritritol."),
                  ("Keto pishiriq",
                   "bodom unli keks yoki pechenega 1 choy qoshiq — eritritol bilan juda mos."),
                  ("Go'shtli taom",
                   "palov, lag'mon yoki qo'y go'shtiga bir chimdim — sharqona xushbo'ylik.")],
            cautions=["Do'konlardagi dolchinning ko'pi — kassiya turi. Unda kumarin bor: ko'p miqdorda muntazam "
                      "iste'mol jigarga zarar qilishi mumkin.",
                      "Jigar kasalligi bo'lsa yoki qon suyultiruvchi dori ichayotgan bo'lsangiz — ko'p ishlatmang.",
                      "Homiladorlikda — faqat taomdagi oddiy miqdorda."],
            advice="kattalar uchun kuniga 1/2 choy qoshiqdan, bolalar uchun bir chimdimdan oshirmang."),
        "ru": dict(
            about="Корица — ароматная специя, которая усиливает ощущение сладости: даже блюдо без сахара кажется "
                  "слаще.",
            benefits=["Ощущение сладости без сахара — помогает класть меньше сахара",
                      "Богата антиоксидантами",
                      "Может немного сглаживать подъём сахара после еды",
                      "Почти без калорий"],
            uses=[("Кофе и чай",
                   "щепотка на чашку или палочка корицы — сладкий вкус без сахара."),
                  ("Каша, творог, яблоко",
                   "1/4 ч. л. на порцию; к печёному яблоку — корица и эритритол."),
                  ("Кето-выпечка",
                   "1 ч. л. в кекс или печенье на миндальной муке — отлично сочетается с эритритолом."),
                  ("Мясные блюда",
                   "щепотка в плов, лагман или баранину — восточный аромат.")],
            cautions=["Большая часть корицы в магазинах — кассия. В ней есть кумарин: регулярное употребление "
                      "в больших количествах может вредить печени.",
                      "При болезнях печени или приёме антикоагулянтов — не налегайте.",
                      "При беременности — только в обычных кулинарных количествах."],
            advice="взрослым — не больше 1/2 ч. л. в день, детям — не больше щепотки."),
    },
    "fennel": {
        "uz": dict(
            about="Arpabodiyon (fenxel) urug'i — shirinroq, anisni eslatuvchi xushbo'y ziravor. An'anaviy "
                  "ravishda ovqat hazmi va gaz uchun ishlatiladi.",
            benefits=["Ovqatdan keyingi ich dam bo'lishi va gazni yengillatishga yordam berishi mumkin",
                      "Og'iz hidini yangilaydi",
                      "Tola, kaliy va antioksidantlar manbai",
                      "Taomga shirinroq xushbo'ylik beradi"],
            uses=[("Arpabodiyon choyi",
                   "1 choy qoshiq urug'ni biroz ezib, 1 stakan qaynoq suvga soling, 10 daqiqa damlang — ovqatdan keyin."),
                  ("Non va pishiriq",
                   "xamirga yoki non ustiga 1 choy qoshiq — sedana bilan birga juda yaxshi."),
                  ("Baliq, karam, sabzavot",
                   "baliq, karam dimlama yoki tuzlamaga 1/2 choy qoshiq."),
                  ("Ovqatdan keyin",
                   "bir chimdim urug'ni chaynang — og'iz hidi yangilanadi.")],
            cautions=["Homiladorlik va emizish davrida arpabodiyon choyini muntazam ichmang (tarkibidagi "
                      "estragol tufayli).",
                      "4 yoshgacha bolalarga choy ko'rinishida muntazam bermang — shifokor bilan maslahatlashing.",
                      "Selderey, sabzi yoki ukropga allergiyasi borlarda allergiya berishi mumkin.",
                      "Gormonga sezgir kasalliklarda ko'p miqdorda iste'mol qilmang."],
            advice="taomdagi oddiy miqdor xavfsiz; choyni kuniga 1–2 stakan, 1–2 haftadan uzoq ichmang."),
        "ru": dict(
            about="Семена фенхеля — сладковатая специя с анисовым ароматом. Традиционно используется для "
                  "пищеварения и от газов.",
            benefits=["Может облегчать вздутие и газы после еды",
                      "Освежает дыхание",
                      "Источник клетчатки, калия и антиоксидантов",
                      "Сладковатый аромат блюдам"],
            uses=[("Чай с фенхелем",
                   "1 ч. л. слегка размятых семян залейте стаканом кипятка, настаивайте 10 минут — после еды."),
                  ("Хлеб и выпечка",
                   "1 ч. л. в тесто или сверху на хлеб — отлично с седаной."),
                  ("Рыба, капуста, овощи",
                   "1/2 ч. л. в рыбу, тушёную капусту или соленья."),
                  ("После еды",
                   "пожуйте щепотку семян — освежает дыхание.")],
            cautions=["При беременности и кормлении не пейте чай с фенхелем регулярно (из-за эстрагола).",
                      "Детям до 4 лет регулярно в виде чая не давайте — посоветуйтесь с врачом.",
                      "Возможна аллергия у людей с аллергией на сельдерей, морковь или укроп.",
                      "При гормонозависимых заболеваниях — не в больших количествах."],
            advice="обычные кулинарные количества безопасны; чай — 1–2 стакана в день, не дольше 1–2 недель."),
    },
})


# ─────────────────────── ozuqaviy qiymat, 100 g uchun ───────────────────────
# Owner's ask (2026-10-11): the numbers keto, diet and diabetic buyers look
# for — kcal, glycemic index, carbs. Typical reference values per 100 g, not
# lab results for our exact batch, so every render says "taxminan" and points
# at the label.
#
#   p, f    — protein, fat (g)
#   c       — AVAILABLE carbs (g), i.e. without fibre — the number keto
#             counts. Sugar alcohols and allulose are 0 here: they do not
#             become blood sugar.
#   fiber   — dietary fibre (g)
#   gi      — glycemic index, or None where no trustworthy figure exists
#             (better no line than an invented one)
#   keto    — "yes" | "limited" | "no"
#   kcal    — only where the formula below is wrong (sweeteners, vinegar)
#
# kcal is otherwise 4·p + 9·f + 4·c + 2·fiber, rounded to 10 — the EU / EAEU
# label convention (fibre at 2 kcal/g), so high-fibre flours read the way
# their packs do.
NUTRITION = {
    "xanthan":          dict(p=0, f=0, c=0, fiber=78, gi=0, keto="yes"),
    "psyllium":         dict(p=2, f=1, c=5, fiber=80, gi=0, keto="yes"),
    "stevia_pure":      dict(p=0, f=0, c=0, fiber=0, gi=0, keto="yes", kcal=0),
    "stevia":           dict(gi=0, keto="yes"),
    "erythritol":       dict(p=0, f=0, c=0, fiber=0, gi=0, keto="yes", kcal=20),
    "allulose":         dict(p=0, f=0, c=0, fiber=0, gi=0, keto="yes", kcal=40),
    "allulose_stevia":  dict(p=0, f=0, c=0, fiber=0, gi=0, keto="yes", kcal=40),
    "coconut_sugar":    dict(p=1, f=0.5, c=92, fiber=0, gi=54, keto="no"),
    "honey":            dict(p=0.3, f=0, c=82, fiber=0, gi=58, keto="no"),
    "almond_flour":     dict(p=21, f=50, c=10, fiber=10, gi=20, keto="yes"),
    "coconut_flour":    dict(p=18, f=14, c=20, fiber=38, gi=45, keto="yes"),
    "pistachio_flour":  dict(p=20, f=45, c=18, fiber=10, gi=15, keto="limited"),
    "flax":             dict(p=18, f=42, c=2, fiber=27, gi=35, keto="yes"),
    "chia":             dict(p=17, f=31, c=8, fiber=34, gi=30, keto="yes"),
    "buckwheat":        dict(p=13, f=3.4, c=62, fiber=10, gi=40, keto="no"),
    "buckwheat_flour":  dict(p=13, f=3, c=60, fiber=10, gi=50, keto="no"),
    "chickpea_flour":   dict(p=22, f=6.7, c=47, fiber=11, gi=35, keto="no"),
    "rice_flour":       dict(p=6, f=1.4, c=78, fiber=2.4, gi=95, keto="no"),
    "rice":             dict(p=7, f=1, c=74, fiber=3, gi=50, keto="no"),
    "bulgur":           dict(p=12, f=1.3, c=63, fiber=12, gi=46, keto="no"),
    "oats":             dict(p=13, f=6.5, c=57, fiber=10, gi=55, keto="no"),
    "rye_flour":        dict(p=10, f=2, c=53, fiber=22, gi=45, keto="no"),
    "barley_flour":     dict(p=10, f=1.6, c=64, fiber=10, gi=None, keto="no"),
    "spelt_flour":      dict(p=15, f=2.4, c=60, fiber=10, gi=45, keto="no"),
    "wholewheat_flour": dict(p=13, f=2.5, c=62, fiber=10, gi=45, keto="no"),
    "wheat_2nd":        dict(p=12, f=1.8, c=67, fiber=6.7, gi=70, keto="no"),
    "corn_flour":       dict(p=7, f=1.5, c=72, fiber=7, gi=70, keto="no"),
    "starch":           dict(p=0.3, f=0.1, c=86, fiber=1, gi=95, keto="no"),
    "soy_flour":        dict(p=35, f=20, c=20, fiber=10, gi=25, keto="limited"),
    "bran":             dict(p=15, f=4, c=21, fiber=42, gi=15, keto="limited"),
    "malt":             dict(p=10, f=2, c=60, fiber=10, gi=None, keto="no"),
    "sesame":           dict(p=18, f=50, c=12, fiber=12, gi=35, keto="yes"),
    "pumpkin_seed":     dict(p=30, f=49, c=5, fiber=6, gi=25, keto="yes"),
    "nigella":          dict(p=18, f=33, c=27, fiber=7, gi=None, keto="yes"),
    "milk_thistle":     dict(p=17, f=7, c=20, fiber=30, gi=None, keto="limited"),
    "pistachio":        dict(p=20, f=45, c=18, fiber=10, gi=15, keto="limited"),
    "nut_paste":        dict(p=25, f=50, c=12, fiber=8, gi=15, keto="yes"),
    "chocolate":        dict(gi=25, keto="limited"),
    "cacao_nibs":       dict(p=14, f=43, c=4, fiber=32, gi=20, keto="yes"),
    "keto_icecream":    dict(gi=None, keto="yes"),
    "coconut_cream":    dict(p=2, f=20, c=3, fiber=0, gi=40, keto="yes"),
    "coconut_flakes":   dict(p=7, f=65, c=7, fiber=16, gi=45, keto="yes"),
    "olive_oil":        dict(p=0, f=100, c=0, fiber=0, gi=0, keto="yes"),
    "coconut_oil":      dict(p=0, f=100, c=0, fiber=0, gi=0, keto="yes"),
    "ghee_butter":      dict(p=0, f=99.5, c=0, fiber=0, gi=0, keto="yes"),
    "salmon":           dict(p=20, f=10, c=0, fiber=0, gi=0, keto="yes"),
    "vinegar":          dict(p=0, f=0, c=1, fiber=0, gi=None, keto="yes", kcal=20),
    "salt":             dict(p=0, f=0, c=0, fiber=0, gi=None, keto="yes", kcal=0),
    "cinnamon":         dict(p=4, f=1.2, c=27, fiber=53, gi=5, keto="yes"),
    "fennel":           dict(p=16, f=15, c=12, fiber=40, gi=None, keto="yes"),
    # sourdough: a live starter — flour and water in whatever ratio it was
    # fed, so no per-100 g figure would be honest. No block at all.
}

# One line under the numbers where the bare table would mislead.
NUTRI_NOTE = {
    "xanthan": {"uz": "Bir taomga 1–3 g ketadi — kaloriyasi sezilmaydi.",
                "ru": "На блюдо уходит 1–3 г — калорийность незаметна."},
    "stevia_pure": {"uz": "Bir chimdim — taxminan 0,05 g.",
                    "ru": "Щепотка — около 0,05 г."},
    "stevia": {"uz": "Kaloriya va uglevod tarkibiga bog'liq — qadoq yorlig'iga qarang.",
               "ru": "Калорийность и углеводы зависят от состава — смотрите этикетку."},
    "erythritol": {"uz": "Shakar spirti qon shakariga aylanmaydi, shuning uchun sof uglevod — 0.",
                   "ru": "Сахарный спирт не превращается в сахар крови, поэтому чистые углеводы — 0."},
    "allulose": {"uz": "Alluloza qon shakariga aylanmaydi, shuning uchun sof uglevod — 0.",
                 "ru": "Аллюлоза не превращается в сахар крови, поэтому чистые углеводы — 0."},
    "allulose_stevia": {"uz": "Alluloza qon shakariga aylanmaydi, shuning uchun sof uglevod — 0.",
                        "ru": "Аллюлоза не превращается в сахар крови, поэтому чистые углеводы — 0."},
    "flax": {"uz": "Yog'sizlantirilgan zig'ir unida: oqsil taxminan 35 g, yog' 10 g, taxminan 300 kkal.",
             "ru": "В обезжиренной льняной муке: белка около 35 г, жира 10 г, около 300 ккал."},
    "rice": {"uz": "Quruq guruch uchun. Glikemik indeks: qora guruch taxminan 42, devzira 50–55, basmati 50–58.",
             "ru": "Для сухого риса. Гликемический индекс: чёрный около 42, девзира 50–55, басмати 50–58."},
    "soy_flour": {"uz": "Yog'sizlantirilgan soya unida oqsil taxminan 50 g, yog' 1–2 g.",
                  "ru": "В обезжиренной соевой муке белка около 50 г, жира 1–2 г."},
    "milk_thistle": {"uz": "Uni (shrot) uchun; urug'ida yog' ko'proq (taxminan 25 g).",
                     "ru": "Для шрота; в семенах жира больше (около 25 г)."},
    "nigella": {"uz": "Taomga oz miqdorda (1–2 choy qoshiq) ishlatiladi.",
                "ru": "В блюда идёт понемногу (1–2 ч. л.)."},
    "nut_paste": {"uz": "Yeryong'oq pastasi uchun; pista pastasida raqamlar yaqin.",
                  "ru": "Для арахисовой пасты; у фисташковой цифры близкие."},
    "chocolate": {"uz": "72% li: taxminan 550 kkal, uglevod 30–35 g. 100% va shakarsiz: 550–600 kkal, "
                        "uglevod 10–15 g. 57% li: uglevod taxminan 50 g. Glikemik indeks — 70% va undan "
                        "yuqori shokolad uchun.",
                  "ru": "72%: около 550 ккал, углеводов 30–35 г. 100% и без сахара: 550–600 ккал, углеводов "
                        "10–15 г. 57%: углеводов около 50 г. Гликемический индекс — для шоколада от 70%."},
    "keto_icecream": {"uz": "Kaloriya va tarkib ta'miga qarab farq qiladi — qadoq yorlig'iga qarang.",
                      "ru": "Калорийность и состав зависят от вкуса — смотрите этикетку."},
    "coconut_cream": {"uz": "Yog'liligi turiga qarab 15–25%.",
                      "ru": "Жирность — 15–25% в зависимости от вида."},
    "olive_oil": {"uz": "1 osh qoshiq (14 g) — taxminan 120 kkal.",
                  "ru": "1 ст. л. (14 г) — около 120 ккал."},
    "coconut_oil": {"uz": "1 osh qoshiq (14 g) — taxminan 120 kkal.",
                    "ru": "1 ст. л. (14 г) — около 120 ккал."},
    "ghee_butter": {"uz": "Eritilgan sariyog' uchun; oddiy sariyog' — taxminan 740 kkal (yog' 82 g).",
                    "ru": "Для топлёного масла; сливочное — около 740 ккал (жир 82 г)."},
    "salmon": {"uz": "Yog'liligi tayyorlanishiga qarab farq qiladi.",
               "ru": "Жирность зависит от способа приготовления."},
    "vinegar": {"uz": "1 osh qoshiqda taxminan 3 kkal.",
                "ru": "В 1 ст. л. около 3 ккал."},
    "salt": {"uz": "100 g tuzda taxminan 38 g natriy; 1 choy qoshiq (6 g) — 2,3 g natriy, kunlik me'yorning "
                   "deyarli hammasi.",
             "ru": "В 100 г соли около 38 г натрия; 1 ч. л. (6 г) — 2,3 г натрия, почти вся суточная норма."},
    "cinnamon": {"uz": "Taomga bir chimdim ketadi — kaloriyasi sezilmaydi.",
                 "ru": "В блюдо идёт щепотка — калорийность незаметна."},
    "fennel": {"uz": "Taomga oz miqdorda ketadi — kaloriyasi sezilmaydi.",
               "ru": "В блюдо идёт немного — калорийность незаметна."},
}
