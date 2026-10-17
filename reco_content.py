"""
Content library for the personal recommendation broadcast (personal_recommend.py).

Rebuilt 2026-09-17 on the owner's request: cover EVERYTHING the shop sells (the
previous nine profiles left rice, psyllium, xanthan, milk thistle, buckwheat,
nut pastes, cacao, sourdough, fish and half the flours falling through to a
generic "healthy products" note), warm the voice up, and give every message
something to act on.

Three layers:

  PROFILES  — one per product family the shop stocks. `match` is a list of
              lowercase substrings looked up in the product NAME, so it keeps
              working even after a product is deleted (we only ever have the
              order item's stored name). ORDER MATTERS: _profile_for returns
              the FIRST profile that hits, so specific families come before the
              generic ones that would otherwise swallow them — "Guruch uni"
              must land on rice_flour and not diet_rice, "Xandonpista pastasi"
              on pastes and not nuts, "Zig'ir uni" on flax and not pp_flour.

  COMBOS    — recipes that need SEVERAL of the buyer's families at once. A
              buyer who orders almond flour, erythritol and cocoa gets a recipe
              built from all three rather than from whichever single product
              they happened to buy most of. Tried before the single-profile
              recipes; skipped when the buyer doesn't own the whole set.

  PAIRINGS  — "you buy X, these go with it" cross-recommendations, keyed by the
              buyer's dominant family and filtered against what they already
              order.

`shop` on a profile is the search term behind the "🛒 Mahsulotlarni ko'rish"
button, so the call to action lands on real products instead of the catalogue
root.

Every entry carries uz + ru. Cyrillic Uzbek is transliterated from the Latin
source at render time, same as the rest of the bot.
"""

PROFILES = [
    {
        "key": "almond_flour",
        "emoji": "🥜",
        "match": ["bodom", "mindal", "almond", "миндал", "бодом"],
        "name": {"uz": "Bodom uni", "ru": "Миндальная мука"},
        "shop": "bodom",
        "benefits": [
            {"uz": "Bodom uni — past uglevodli, oqsil va sog'lom yog'larga boy. Un o'rnida ishlatsangiz, qonda shakar keskin ko'tarilmaydi va to'yimlilik uzoq saqlanadi.",
             "ru": "Миндальная мука — низкоуглеводная, богата белком и полезными жирами. Заменяя обычную муку, вы избегаете скачков сахара и дольше остаётесь сытыми."},
            {"uz": "E vitamini va magniyga boy — teri, soch va yurak salomatligi uchun. Glutensiz, shuning uchun hazm qilish osonroq.",
             "ru": "Богата витамином E и магнием — для кожи, волос и сердца. Без глютена, поэтому легче усваивается."},
            {"uz": "100g bodom unida ~10g tola bor, oddiy oq unda esa deyarli yo'q. Shuning uchun undan pishgan non ertalabki ochlikni ancha uzoq ushlaydi.",
             "ru": "В 100г миндальной муки ~10г клетчатки, в белой её почти нет. Поэтому хлеб из неё дольше удерживает сытость."},
        ],
        "recipes": [
            {"uz": "<b>Keto bodom keksi</b>\n⏱ 35 daqiqa · 🍽 8 bo'lak\n\n🧾 <b>Masalliqlar:</b>\n• 200 g bodom uni\n• 3 ta tuxum\n• 50 g sariyog' (eritilgan)\n• 60 g eritritol\n• 1 choy qoshiq pishirish kukuni (razrixlitel)\n• 1 chimdim tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Pechni 180°C ga qizdiring. Kichik keks qolipini (20×10 sm) yog'lang yoki pergament qog'oz to'shang.\n2. Bir idishda bodom uni, eritritol, pishirish kukuni va tuzni aralashtiring.\n3. Boshqa idishda tuxumni vilka bilan 1 daqiqa ko'pirtiring va iliq eritilgan sariyog'ni qo'shing.\n4. Suyuq qismni quruq qismga quyib, bir xil xamir bo'lguncha aralashtiring.\n5. Xamirni qolipga soling, ustini qoshiq bilan tekislang.\n6. 180°C da 25 daqiqa pishiring. Tish kavlagich tiqib ko'ring: quruq chiqsa — tayyor.\n7. Qolipda 10 daqiqa sovusin, keyin olib 8 bo'lakka kesing.\n\n💡 Tuzni tashlab ketmang — u shirinlik ta'mini ochadi.",
             "ru": "<b>Кето-кекс из миндаля</b>\n⏱ 35 минут · 🍽 8 кусочков\n\n🧾 <b>Ингредиенты:</b>\n• 200 г миндальной муки\n• 3 яйца\n• 50 г сливочного масла (растопленного)\n• 60 г эритрита\n• 1 ч. ложка разрыхлителя\n• 1 щепотка соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Разогрейте духовку до 180°C. Небольшую форму (20×10 см) смажьте маслом или застелите пергаментом.\n2. В миске смешайте миндальную муку, эритрит, разрыхлитель и соль.\n3. В другой миске взбейте яйца вилкой 1 минуту и добавьте тёплое растопленное масло.\n4. Влейте жидкую часть в сухую и перемешайте до однородного теста.\n5. Выложите тесто в форму и разровняйте ложкой.\n6. Выпекайте 25 минут при 180°C. Проверьте зубочисткой: выходит сухой — готово.\n7. Остудите в форме 10 минут, достаньте и нарежьте на 8 кусочков.\n\n💡 Не пропускайте соль — она раскрывает сладость."},
            {"uz": "<b>Bodom unidan quymoq — 10 daqiqalik nonushta</b>\n⏱ 10 daqiqa · 🍽 2 kishilik (6–8 dona)\n\n🧾 <b>Masalliqlar:</b>\n• 100 g bodom uni\n• 2 ta tuxum\n• 3 osh qoshiq suv yoki sut\n• 1 chimdim tuz\n• 1 choy qoshiq yog' (tova uchun)\n• Ustiga: 1 osh qoshiq kokos qirindisi yoki chia (ixtiyoriy)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Idishda tuxumni vilka bilan ko'pirtiring.\n2. Bodom uni, suv (yoki sut) va tuzni qo'shib aralashtiring. Xamir quyuq qaymoqdek bo'lishi kerak; juda quyuq bo'lsa, yana 1 osh qoshiq suv qo'shing.\n3. Tovani o'rtacha olovda qizdiring va ozgina yog' surting.\n4. Har bir quymoq uchun 1 osh qoshiq xamir quying.\n5. Har tomonini 2 daqiqadan, qizarguncha pishiring.\n6. Tarelkaga olib, ustiga kokos qirindisi yoki chia seping.\n\n💡 Olov baland bo'lsa, ichi pishmay usti kuyadi — o'rtacha olovda pishiring.",
             "ru": "<b>Миндальные панкейки — завтрак за 10 минут</b>\n⏱ 10 минут · 🍽 2 порции (6–8 штук)\n\n🧾 <b>Ингредиенты:</b>\n• 100 г миндальной муки\n• 2 яйца\n• 3 ст. ложки воды или молока\n• 1 щепотка соли\n• 1 ч. ложка масла (для сковороды)\n• Сверху: 1 ст. ложка кокосовой стружки или чиа (по желанию)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Взбейте яйца вилкой в миске.\n2. Добавьте миндальную муку, воду (или молоко) и соль, перемешайте. Тесто должно быть как густая сметана; если слишком густое — добавьте ещё 1 ст. ложку воды.\n3. Разогрейте сковороду на среднем огне и слегка смажьте маслом.\n4. На каждый панкейк выкладывайте 1 ст. ложку теста.\n5. Жарьте по 2 минуты с каждой стороны до румяности.\n6. Подавайте, посыпав кокосовой стружкой или чиа.\n\n💡 На сильном огне снаружи подгорит, а внутри не пропечётся — держите средний огонь."},
            {"uz": "<b>Glyutensiz bodom noni</b>\n⏱ 45 daqiqa · 🍽 1 non (10 bo'lak)\n\n🧾 <b>Masalliqlar:</b>\n• 250 g bodom uni\n• 4 ta tuxum\n• 1 choy qoshiq soda\n• 1 osh qoshiq olma sirkasi\n• 1/2 choy qoshiq tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Pechni 180°C ga qizdiring. Non qolipiga (taxminan 20×10 sm) pergament qog'oz to'shang.\n2. Idishda bodom uni, soda va tuzni aralashtiring.\n3. Tuxumni alohida idishda vilka bilan ko'pirtiring va quruq qismga qo'shing.\n4. Olma sirkasini oxirida qo'shing — xamir biroz ko'piklanadi, shunday bo'lishi kerak. Tez aralashtiring.\n5. Xamirni darhol qolipga soling va ustini tekislang.\n6. 180°C da 35 daqiqa pishiring. Usti qizarib, tish kavlagich quruq chiqsa — tayyor.\n7. Nonni to'liq sovuting (kamida 30 daqiqa), keyin kesing — issiqligida uvalanadi.\n\n💡 Muzlatkichda 5 kungacha saqlanadi; bo'laklab muzlatib ham qo'yish mumkin.",
             "ru": "<b>Безглютеновый миндальный хлеб</b>\n⏱ 45 минут · 🍽 1 буханка (10 ломтиков)\n\n🧾 <b>Ингредиенты:</b>\n• 250 г миндальной муки\n• 4 яйца\n• 1 ч. ложка соды\n• 1 ст. ложка яблочного уксуса\n• 1/2 ч. ложки соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Разогрейте духовку до 180°C. Застелите форму для хлеба (примерно 20×10 см) пергаментом.\n2. В миске смешайте миндальную муку, соду и соль.\n3. Взбейте яйца вилкой в отдельной миске и добавьте к сухой части.\n4. В конце влейте яблочный уксус — тесто слегка вспенится, так и должно быть. Быстро перемешайте.\n5. Сразу выложите тесто в форму и разровняйте.\n6. Выпекайте 35 минут при 180°C. Верх румяный, зубочистка сухая — готово.\n7. Полностью остудите хлеб (минимум 30 минут) и только потом режьте — горячий крошится.\n\n💡 В холодильнике хранится до 5 дней; можно заморозить ломтиками."},
        ],
    },
    {
        "key": "coconut",
        "emoji": "🥥",
        "match": ["kokos", "coconut", "кокос", "kakos"],
        "name": {"uz": "Kokos mahsulotlari", "ru": "Кокосовые продукты"},
        "shop": "kokos",
        "benefits": [
            {"uz": "Kokosdagi MCT yog'lari jigarda tez energiyaga aylanadi va ketoz holatini qo'llab-quvvatlaydi — ochlik hissi sezilarli kamayadi.",
             "ru": "MCT-жиры кокоса быстро становятся энергией в печени и поддерживают кетоз — чувство голода заметно снижается."},
            {"uz": "Kokos uni tolaga juda boy: bodom uniga qaraganda uch barobar ko'p suyuqlik tortadi, shuning uchun retseptda undan 3-4 barobar kam ishlatiladi.",
             "ru": "Кокосовая мука очень богата клетчаткой: впитывает втрое больше жидкости, чем миндальная, поэтому её берут в 3-4 раза меньше."},
            {"uz": "Kokos shakarining glikemik indeksi oddiy shakarnikidan past va tarkibida inulin bor — qonda shakar sekinroq ko'tariladi.",
             "ru": "У кокосового сахара ниже гликемический индекс и есть инулин — сахар в крови поднимается медленнее."},
        ],
        "recipes": [
            {"uz": "<b>Keto «Baunti» konfeti</b>\n⏱ 40 daqiqa (shundan 30 daqiqasi muzlatkichda) · 🍽 12 dona\n\n🧾 <b>Masalliqlar:</b>\n• 100 g kokos qirindisi\n• 40 g kokos yog'i (eritilgan)\n• 30 g eritritol (kofe maydalagichda unga aylantirilgan)\n• 1 chimdim vanilin\n• Qoplama uchun (ixtiyoriy): 50 g shakarsiz qora shokolad\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Kokos yog'ini suv hammomida yoki mikroto'lqinli pechda 20–30 soniya eriting.\n2. Idishda kokos qirindisi, maydalangan eritritol va vanilinni aralashtiring.\n3. Erigan kokos yog'ini qo'shib, qo'l bilan siqib aralashtiring — massa siqilganda yopishib turishi kerak.\n4. Ho'l qo'l bilan yong'oqdek (taxminan 15 g) 12 ta sharcha yoki kichik batoncha yasang.\n5. Pergament qog'ozga terib, muzlatkichda 30 daqiqa qoldiring.\n6. Xohlasangiz, shokoladni suv hammomida eritib, har bir konfetni botirib oling va yana 10 daqiqa muzlatkichga qo'ying.\n\n💡 Muzlatkichda yopiq idishda 1 haftagacha saqlang — xona haroratida yumshab qoladi.",
             "ru": "<b>Кето-конфеты «Баунти»</b>\n⏱ 40 минут (из них 30 в холодильнике) · 🍽 12 штук\n\n🧾 <b>Ингредиенты:</b>\n• 100 г кокосовой стружки\n• 40 г кокосового масла (растопленного)\n• 30 г эритрита (смолотого в кофемолке в пудру)\n• 1 щепотка ванилина\n• Для глазури (по желанию): 50 г тёмного шоколада без сахара\n\n👩‍🍳 <b>Приготовление:</b>\n1. Растопите кокосовое масло на водяной бане или 20–30 секунд в микроволновке.\n2. В миске смешайте кокосовую стружку, молотый эритрит и ванилин.\n3. Добавьте растопленное масло и перемешайте руками — при сжатии масса должна держать форму.\n4. Влажными руками скатайте 12 шариков или батончиков размером с грецкий орех (около 15 г).\n5. Выложите на пергамент и уберите в холодильник на 30 минут.\n6. По желанию растопите шоколад на водяной бане, окуните каждую конфету и уберите в холодильник ещё на 10 минут.\n\n💡 Храните в закрытом контейнере в холодильнике до 1 недели — при комнатной температуре они мягчеют."},
            {"uz": "<b>Kokos unidan keksiklar</b>\n⏱ 30 daqiqa · 🍽 10 dona\n\n🧾 <b>Masalliqlar:</b>\n• 60 g kokos uni\n• 4 ta tuxum\n• 80 ml kokos yog'i (eritilgan)\n• 50 g eritritol\n• 1 choy qoshiq pishirish kukuni\n• 1 chimdim tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Pechni 180°C ga qizdiring. Keks qoliplariga qog'oz stakanchalar qo'ying yoki yog'lang.\n2. Idishda tuxum va eritritolni vilka yoki mikser bilan 2 daqiqa ko'pirtiring.\n3. Eritilgan (iliq, issiq emas) kokos yog'ini qo'shib aralashtiring.\n4. Kokos uni, pishirish kukuni va tuzni qo'shing va bir xil bo'lguncha aralashtiring.\n5. Xamirni 5 daqiqa qo'yib qo'ying — kokos uni suyuqlikni shimib, xamir quyuqlashadi.\n6. Qoliplarni 3/4 qismigacha to'ldiring (har biriga taxminan 2 osh qoshiq).\n7. 180°C da 20 daqiqa pishiring. Usti qizarib, tish kavlagich quruq chiqsa — tayyor.\n\n💡 Kokos unini ko'z bilan ko'paytirmang: bir qoshiq ortiqcha ham keksni quruq qiladi.",
             "ru": "<b>Кексы из кокосовой муки</b>\n⏱ 30 минут · 🍽 10 штук\n\n🧾 <b>Ингредиенты:</b>\n• 60 г кокосовой муки\n• 4 яйца\n• 80 мл кокосового масла (растопленного)\n• 50 г эритрита\n• 1 ч. ложка разрыхлителя\n• 1 щепотка соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Разогрейте духовку до 180°C. Вставьте бумажные капсулы в формы для кексов или смажьте их.\n2. Взбейте яйца с эритритом вилкой или миксером 2 минуты.\n3. Добавьте растопленное (тёплое, не горячее) кокосовое масло и перемешайте.\n4. Всыпьте кокосовую муку, разрыхлитель и соль, перемешайте до однородности.\n5. Оставьте тесто на 5 минут — мука впитает жидкость, и тесто загустеет.\n6. Заполните формы на 3/4 (около 2 ст. ложек в каждую).\n7. Выпекайте 20 минут при 180°C. Верх румяный, зубочистка сухая — готово.\n\n💡 Не добавляйте кокосовую муку «на глаз»: даже лишняя ложка делает кексы сухими."},
            {"uz": "<b>Kokosli smuzi</b>\n⏱ 5 daqiqa · 🍽 1 stakan (250 ml)\n\n🧾 <b>Masalliqlar:</b>\n• 200 ml kokos suti\n• 1 hovuch (taxminan 70 g) muzlatilgan rezavor (qulupnay, malina yoki qorag'at)\n• 1 osh qoshiq chia urug'i\n• 1 chimdim tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Barcha masalliqlarni blender idishiga soling.\n2. Yuqori tezlikda 30 soniya, silliq bo'lguncha aylantiring.\n3. Stakanga quyib, 5 daqiqa qo'yib qo'ying — chia ichimlikni biroz quyuqlashtiradi.\n4. Qoshiq bilan bir aralashtirib iching.\n\n💡 Juda quyuq bo'lsa, 2–3 osh qoshiq suv qo'shib yana aylantiring.",
             "ru": "<b>Кокосовое смузи</b>\n⏱ 5 минут · 🍽 1 стакан (250 мл)\n\n🧾 <b>Ингредиенты:</b>\n• 200 мл кокосового молока\n• 1 горсть (около 70 г) замороженных ягод (клубника, малина или смородина)\n• 1 ст. ложка семян чиа\n• 1 щепотка соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Сложите все ингредиенты в чашу блендера.\n2. Взбивайте 30 секунд на высокой скорости до гладкости.\n3. Перелейте в стакан и оставьте на 5 минут — чиа слегка загустит напиток.\n4. Перемешайте ложкой и пейте.\n\n💡 Если слишком густо — добавьте 2–3 ст. ложки воды и взбейте ещё раз."},
        ],
    },
    {
        "key": "flax",
        "emoji": "🌾",
        "match": ["zig'ir", "zigir", "zig ir", "лён", "льн", "lyon", "flax"],
        "name": {"uz": "Zig'ir (uni va urug'i)", "ru": "Лён (мука и семена)"},
        "shop": "zig'ir",
        "benefits": [
            {"uz": "Zig'ir urug'i o'simlik dunyosidagi eng boy omega-3 manbalaridan biri. Kuniga 1-2 osh qoshiq yurak va qon tomirlarni qo'llab-quvvatlaydi.",
             "ru": "Семена льна — один из богатейших растительных источников омега-3. 1-2 ст.л. в день поддерживают сердце и сосуды."},
            {"uz": "Zig'ir unida lignanlar ko'p — bu tabiiy antioksidantlar gormonal muvozanatni qo'llab-quvvatlaydi, ayniqsa ayollar uchun foydali.",
             "ru": "В льняной муке много лигнанов — природных антиоксидантов, поддерживающих гормональный баланс, особенно у женщин."},
            {"uz": "Maydalangan zig'ir suvda gel hosil qiladi — keto pishiriqlarida tuxum o'rnini bosadi va ichak ishini yumshoq yo'lga soladi.",
             "ru": "Молотый лён образует гель в воде — заменяет яйцо в кето-выпечке и мягко налаживает работу кишечника."},
        ],
        "recipes": [
            {"uz": "<b>Zig'irli kraker — qarsillaydigan gazak</b>\n⏱ 50 daqiqa · 🍽 1 laganda (taxminan 20 dona)\n\n🧾 <b>Masalliqlar:</b>\n• 4 osh qoshiq butun zig'ir urug'i (taxminan 40 g)\n• 4 osh qoshiq suv\n• 1/4 choy qoshiq tuz\n• 1 choy qoshiq sedana yoki kunjut\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Zig'ir urug'i, suv, tuz va sedanani idishda aralashtiring.\n2. 10 daqiqa qo'yib qo'ying — urug'lar shilimshiq bo'lib, bir-biriga yopishadi.\n3. Pechni 150°C ga qizdiring. Laganga pergament qog'oz to'shang.\n4. Massani pergamentga solib, qoshiqning orqasi bilan 2–3 mm qalinlikda, iloji boricha yupqa yoying.\n5. 150°C da 40 daqiqa quriting. Chetlari jigarrang bo'lib, o'rtasi qattiq bo'lsa — tayyor.\n6. To'liq sovuting va qo'l bilan bo'laklarga sindiring.\n\n💡 Yopiq bankada 2 haftagacha qarsillab turadi.",
             "ru": "<b>Льняные крекеры — хрустящий снек</b>\n⏱ 50 минут · 🍽 1 противень (около 20 штук)\n\n🧾 <b>Ингредиенты:</b>\n• 4 ст. ложки цельных семян льна (около 40 г)\n• 4 ст. ложки воды\n• 1/4 ч. ложки соли\n• 1 ч. ложка чернушки или кунжута\n\n👩‍🍳 <b>Приготовление:</b>\n1. Смешайте в миске семена льна, воду, соль и чернушку.\n2. Оставьте на 10 минут — семена станут клейкими и слипнутся.\n3. Разогрейте духовку до 150°C. Застелите противень пергаментом.\n4. Выложите массу на пергамент и тыльной стороной ложки распределите слоем 2–3 мм, как можно тоньше.\n5. Подсушивайте 40 минут при 150°C. Края потемнели, середина твёрдая — готово.\n6. Полностью остудите и разломайте руками на кусочки.\n\n💡 В закрытой банке остаются хрустящими до 2 недель."},
            {"uz": "<b>1 daqiqalik zig'ir noni (mikroto'lqinli pechda)</b>\n⏱ 3 daqiqa · 🍽 1 kishilik\n\n🧾 <b>Masalliqlar:</b>\n• 3 osh qoshiq zig'ir uni\n• 1 ta tuxum\n• 1 choy qoshiq yog' (sariyog' yoki zaytun yog'i)\n• 1 chimdim soda\n• 1 chimdim tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Keng krujkaga (kamida 300 ml) barcha masalliqlarni soling.\n2. Vilka bilan 30 soniya, bir xil bo'lguncha yaxshilab aralashtiring.\n3. Mikroto'lqinli pechda to'liq quvvatda 90 soniya pishiring.\n4. Krujkani ag'darib nonni chiqaring, 2 daqiqa sovusin.\n5. O'rtasidan kesib, sendvich uchun ishlating.\n\n💡 Ustini tovada 1 daqiqa qizartirsangiz, qarsillaydigan bo'ladi.",
             "ru": "<b>Льняной хлеб за 1 минуту (в микроволновке)</b>\n⏱ 3 минуты · 🍽 1 порция\n\n🧾 <b>Ингредиенты:</b>\n• 3 ст. ложки льняной муки\n• 1 яйцо\n• 1 ч. ложка масла (сливочного или оливкового)\n• 1 щепотка соды\n• 1 щепотка соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Сложите все ингредиенты в широкую кружку (не меньше 300 мл).\n2. Тщательно перемешайте вилкой 30 секунд до однородности.\n3. Готовьте в микроволновке на полной мощности 90 секунд.\n4. Переверните кружку, достаньте хлеб и дайте остыть 2 минуты.\n5. Разрежьте пополам — готово для сэндвича.\n\n💡 Если подрумянить срез на сковороде 1 минуту, будет хрустящим."},
            {"uz": "<b>Zig'ir kiseli — ertalabki ichimlik</b>\n⏱ 5 daqiqa + 1 kecha · 🍽 1 stakan\n\n🧾 <b>Masalliqlar:</b>\n• 1 osh qoshiq butun zig'ir urug'i\n• 250 ml issiq suv (qaynoq emas, taxminan 80°C)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Kechqurun zig'ir urug'ini stakanga soling.\n2. Ustiga 250 ml issiq suv quying va qoshiq bilan aralashtiring.\n3. Stakanni likopcha bilan yoping va xona haroratida tunab qoldiring (8–10 soat).\n4. Ertalab aralashtiring — ichimlik shilimshiq kiselga aylangan bo'ladi.\n5. Nonushtadan 20–30 daqiqa oldin, och qoringa urug'i bilan birga iching.\n\n💡 Ta'mi yoqmasa, 1 choy qoshiq limon sharbati qo'shing.",
             "ru": "<b>Льняной кисель — утренний напиток</b>\n⏱ 5 минут + ночь · 🍽 1 стакан\n\n🧾 <b>Ингредиенты:</b>\n• 1 ст. ложка цельных семян льна\n• 250 мл горячей воды (не кипятка, около 80°C)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Вечером насыпьте семена льна в стакан.\n2. Залейте 250 мл горячей воды и перемешайте ложкой.\n3. Накройте блюдцем и оставьте на ночь при комнатной температуре (8–10 часов).\n4. Утром перемешайте — напиток станет густым, как кисель.\n5. Выпейте вместе с семенами натощак, за 20–30 минут до завтрака.\n\n💡 Если вкус непривычный, добавьте 1 ч. ложку лимонного сока."},
        ],
    },
    {
        "key": "chia",
        "emoji": "🌱",
        "match": ["chia", "чиа"],
        "name": {"uz": "Chia urug'i", "ru": "Семена чиа"},
        "shop": "chia",
        "benefits": [
            {"uz": "Chia o'z og'irligidan 10 barobar ko'p suv tortadi — oshqozonda hajm hosil qilib, ochlikni tabiiy yo'l bilan bosadi.",
             "ru": "Чиа впитывает в 10 раз больше воды своего веса — создаёт объём в желудке и естественно притупляет голод."},
            {"uz": "2 osh qoshiq chiada ~10g tola va kunlik kalsiy me'yorining ~18% i bor. Sut mahsulotlarini kam iste'mol qilsangiz — ajoyib manba.",
             "ru": "В 2 ст.л. чиа ~10г клетчатки и ~18% суточной нормы кальция. Отличный источник, если вы мало едите молочного."},
        ],
        "recipes": [
            {"uz": "<b>Chia puding — kechqurun tayyorlang, ertalab nonushta</b>\n⏱ 5 daqiqa + 1 kecha · 🍽 1 kishilik\n\n🧾 <b>Masalliqlar:</b>\n• 3 osh qoshiq chia urug'i (30 g)\n• 200 ml kokos yoki bodom suti (oddiy sut ham bo'ladi)\n• 1–2 choy qoshiq eritritol (ta'mga qarab)\n• 1 chimdim vanilin\n• Ustiga: 1 hovuch rezavor yoki 1 osh qoshiq kokos qirindisi (ixtiyoriy)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Stakan yoki bankaga sut, eritritol va vanilinni soling va aralashtiring.\n2. Chia urug'ini qo'shib, 30 soniya yaxshilab aralashtiring.\n3. 10 daqiqa kuting va YANA aralashtiring — aks holda chia pastga cho'kib, bir bo'lak bo'lib qotadi.\n4. Usti yopiq holda muzlatkichda kamida 4 soat, yaxshisi tun bo'yi qoldiring.\n5. Ertalab aralashtirib, ustiga rezavor yoki kokos qirindisi qo'yib yeng.\n\n💡 Muzlatkichda 3 kungacha turadi — bir yo'la 3 ta banka tayyorlab qo'yish mumkin.",
             "ru": "<b>Чиа-пудинг — готовьте вечером, завтрак утром</b>\n⏱ 5 минут + ночь · 🍽 1 порция\n\n🧾 <b>Ингредиенты:</b>\n• 3 ст. ложки семян чиа (30 г)\n• 200 мл кокосового или миндального молока (можно обычное)\n• 1–2 ч. ложки эритрита (по вкусу)\n• 1 щепотка ванилина\n• Сверху: горсть ягод или 1 ст. ложка кокосовой стружки (по желанию)\n\n👩‍🍳 <b>Приготовление:</b>\n1. В стакан или баночку налейте молоко, добавьте эритрит и ванилин, перемешайте.\n2. Всыпьте чиа и тщательно перемешайте 30 секунд.\n3. Подождите 10 минут и перемешайте ЕЩЁ РАЗ — иначе чиа осядет и слипнется комком на дне.\n4. Накройте и уберите в холодильник минимум на 4 часа, лучше на ночь.\n5. Утром перемешайте, добавьте ягоды или стружку и ешьте.\n\n💡 В холодильнике хранится до 3 дней — можно сразу сделать 3 баночки."},
            {"uz": "<b>Chia «tuxumi» — pishiriqlar uchun</b>\n⏱ 10 daqiqa · 🍽 1 tuxum o'rniga\n\n🧾 <b>Masalliqlar:</b>\n• 1 osh qoshiq maydalangan chia urug'i (kofe maydalagichda)\n• 3 osh qoshiq suv\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Chia urug'ini kofe maydalagichda unga aylantiring.\n2. Kichik idishda 1 osh qoshiq chia uniga 3 osh qoshiq suv quyib aralashtiring.\n3. 10 daqiqa qo'yib qo'ying — massa tuxum oqiga o'xshash quyuq jelega aylanadi.\n4. Retseptdagi har bir tuxum o'rniga shu miqdorni xamirga qo'shing.\n\n💡 Keks, non va quymoqda yaxshi ishlaydi; bezeda (tuxum oqidan ko'pik) ishlamaydi.",
             "ru": "<b>Чиа-«яйцо» для выпечки</b>\n⏱ 10 минут · 🍽 замена 1 яйца\n\n🧾 <b>Ингредиенты:</b>\n• 1 ст. ложка молотых семян чиа (в кофемолке)\n• 3 ст. ложки воды\n\n👩‍🍳 <b>Приготовление:</b>\n1. Смелите семена чиа в кофемолке в муку.\n2. В маленькой миске залейте 1 ст. ложку чиа 3 ст. ложками воды и перемешайте.\n3. Оставьте на 10 минут — получится густой гель, похожий на белок.\n4. Добавляйте эту порцию в тесто вместо каждого яйца по рецепту.\n\n💡 Хорошо работает в кексах, хлебе и панкейках; для безе (взбитых белков) не подходит."},
        ],
    },
    {
        "key": "buckwheat",
        "emoji": "🍀",
        "match": ["grechka", "гречк", "grechixa", "grechnev"],
        "name": {"uz": "Yashil grechka", "ru": "Зелёная гречка"},
        "shop": "grechka",
        "benefits": [
            {"uz": "Yashil grechka — qovurilmagan, tirik don. Uni undirib ham, oddiy pishirib ham yeyish mumkin; tarkibidagi rutin qon tomirlarni mustahkamlaydi.",
             "ru": "Зелёная гречка — необжаренная, живая крупа. Её можно проращивать или просто варить; рутин в составе укрепляет сосуды."},
            {"uz": "Glutensiz va to'liq qiymatli oqsil manbai — tarkibida organizm o'zi ishlab chiqarmaydigan barcha aminokislotalar bor. Go'shtni kam yesangiz muhim.",
             "ru": "Без глютена и с полноценным белком — содержит все незаменимые аминокислоты. Важно, если вы едите мало мяса."},
        ],
        "recipes": [
            {"uz": "<b>Undirilgan yashil grechka</b>\n⏱ 10 daqiqa ish + 1 kun kutish · 🍽 2 stakan\n\n🧾 <b>Masalliqlar:</b>\n• 1 stakan (200 g) yashil grechka\n• 2 stakan (400 ml) bo'ktirish uchun suv\n• Yuvish uchun: har safar 1 litr toza suv\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Grechkani elakda sovuq suvda 2–3 marta yuving.\n2. Idishga solib, 2 stakan suv quying va 2 soat bo'ktiring.\n3. Suvini to'kib, grechkani elakda yana yaxshilab yuving — shilimshiq yuvilib ketsin.\n4. Grechkani tekis idishga yupqa qatlam qilib yoying va ustini ho'l doka yoki sochiq bilan yoping.\n5. Xona haroratida 12–24 soat qoldiring; har 8–12 soatda yuvib, dokani namlab turing.\n6. Kichik oq maysachalar (1–2 mm) chiqqanda — tayyor. Salat, smuzi yoki bo'tqaga qo'shing.\n\n💡 Tayyor grechkani muzlatkichda yopiq idishda 2 kungacha saqlang.",
             "ru": "<b>Пророщенная зелёная гречка</b>\n⏱ 10 минут работы + сутки · 🍽 2 стакана\n\n🧾 <b>Ингредиенты:</b>\n• 1 стакан (200 г) зелёной гречки\n• 2 стакана (400 мл) воды для замачивания\n• Для промывания: каждый раз 1 л чистой воды\n\n👩‍🍳 <b>Приготовление:</b>\n1. Промойте гречку в сите холодной водой 2–3 раза.\n2. Переложите в миску, залейте 2 стаканами воды и замочите на 2 часа.\n3. Слейте воду и снова хорошо промойте гречку в сите — смойте слизь.\n4. Разложите гречку тонким слоем в плоской посуде и накройте влажной марлей или полотенцем.\n5. Оставьте при комнатной температуре на 12–24 часа; каждые 8–12 часов промывайте и смачивайте марлю.\n6. Появились белые ростки (1–2 мм) — готово. Добавляйте в салаты, смузи или кашу.\n\n💡 Готовую гречку храните в холодильнике в закрытой посуде до 2 дней."},
            {"uz": "<b>Grechka unidan blinchik</b>\n⏱ 20 daqiqa · 🍽 6 dona\n\n🧾 <b>Masalliqlar:</b>\n• 100 g grechka uni\n• 2 ta tuxum\n• 150 ml suv yoki sut\n• 1/4 choy qoshiq tuz\n• 1 choy qoshiq yog' (tova uchun)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Idishda tuxum va tuzni vilka bilan ko'pirtiring.\n2. Sut (yoki suv)ni qo'shib aralashtiring.\n3. Grechka unini asta-sekin qo'shib, quyuqlashmaguncha aralashtiring — xamir suyuq qaymoqdek bo'lsin.\n4. Xamirni 10 daqiqa qo'yib qo'ying.\n5. Tovani o'rtacha olovda qizdirib, yog' surting. 1 cho'mich (taxminan 50 ml) xamir quyib, tovani aylantirib yupqa yoying.\n6. Har tomonini 1–1,5 daqiqadan pishiring.\n7. Ichiga tvorog yoki avokado solib o'rab torting.",
             "ru": "<b>Блинчики из гречневой муки</b>\n⏱ 20 минут · 🍽 6 штук\n\n🧾 <b>Ингредиенты:</b>\n• 100 г гречневой муки\n• 2 яйца\n• 150 мл воды или молока\n• 1/4 ч. ложки соли\n• 1 ч. ложка масла (для сковороды)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Взбейте яйца с солью вилкой.\n2. Добавьте молоко (или воду) и перемешайте.\n3. Постепенно всыпьте гречневую муку, мешая без комков, — тесто должно быть как жидкие сливки.\n4. Оставьте тесто на 10 минут.\n5. Разогрейте сковороду на среднем огне и смажьте маслом. Налейте половник (около 50 мл) теста и, вращая сковороду, распределите тонко.\n6. Жарьте по 1–1,5 минуты с каждой стороны.\n7. Заверните творог или авокадо и подавайте."},
        ],
    },
    {
        "key": "rastaropsha",
        "emoji": "🌿",
        "match": ["rastaropsha", "rasteropsha", "расторопш", "sutgul"],
        "name": {"uz": "Rastaropsha (sutgul)", "ru": "Расторопша"},
        "shop": "rastaropsha",
        "benefits": [
            {"uz": "Rastaropsha tarkibidagi silimarin jigar hujayralarini himoya qiladi va tiklanishiga yordam beradi — yog'li ratsionda jigarga qo'shimcha qo'llab-quvvatlash.",
             "ru": "Силимарин расторопши защищает клетки печени и помогает им восстанавливаться — дополнительная поддержка печени при жирном рационе."},
            {"uz": "Kuniga 1 choy qoshiq maydalangan urug' — an'anaviy me'yor. Odatda 3-4 hafta kurs qilinadi, so'ng tanaffus beriladi.",
             "ru": "1 ч.л. молотых семян в день — традиционная норма. Обычно курс 3-4 недели, затем перерыв."},
        ],
        "recipes": [
            {"uz": "<b>Rastoropsha shroti — eng oddiy usul</b>\n⏱ 2 daqiqa · 🍽 1 stakan\n\n🧾 <b>Masalliqlar:</b>\n• 1 choy qoshiq maydalangan rastoropsha urug'i (shrot)\n• 200 ml iliq suv\n• Ixtiyoriy: 1/2 choy qoshiq asal yoki 1 choy qoshiq limon sharbati\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Stakanga rastoropsha shrotini soling.\n2. Ustiga 200 ml iliq suv quyib, yaxshilab aralashtiring.\n3. Ta'mi achchiqroq bo'lsa, asal yoki limon sharbati qo'shing.\n4. Ovqatdan 20 daqiqa oldin, kuniga 1 marta iching.\n\n💡 Dori ichayotgan bo'lsangiz yoki homilador bo'lsangiz, avval shifokor bilan maslahatlashing.",
             "ru": "<b>Шрот расторопши — самый простой способ</b>\n⏱ 2 минуты · 🍽 1 стакан\n\n🧾 <b>Ингредиенты:</b>\n• 1 ч. ложка молотых семян расторопши (шрота)\n• 200 мл тёплой воды\n• По желанию: 1/2 ч. ложки мёда или 1 ч. ложка лимонного сока\n\n👩‍🍳 <b>Приготовление:</b>\n1. Насыпьте шрот расторопши в стакан.\n2. Залейте 200 мл тёплой воды и хорошо перемешайте.\n3. Если горчит — добавьте мёд или лимонный сок.\n4. Пейте за 20 минут до еды, 1 раз в день.\n\n💡 Если принимаете лекарства или беременны, сначала посоветуйтесь с врачом."},
            {"uz": "<b>Rastoropsha unini non xamiriga qo'shish</b>\n⏱ 1 daqiqa · 🍽 1 non uchun\n\n🧾 <b>Masalliqlar:</b>\n• 1–2 osh qoshiq rastoropsha uni (1 non yoki 1 keks xamiriga)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Istalgan keto non yoki keks retseptini oling.\n2. Quruq masalliqlarni (un, pishirish kukuni) aralashtirayotganda 1 osh qoshiq rastoropsha uni qo'shing.\n3. Qolgan bosqichlarni retseptdagidek bajaring — pishirish vaqti o'zgarmaydi.\n4. Ta'mi yoqsa, keyingi safar 2 osh qoshiqqacha oshiring.\n\n💡 Ta'mga deyarli ta'sir qilmaydi, xamir rangi biroz to'qroq bo'ladi.",
             "ru": "<b>Мука расторопши в тесто</b>\n⏱ 1 минута · 🍽 на 1 буханку\n\n🧾 <b>Ингредиенты:</b>\n• 1–2 ст. ложки муки расторопши (на 1 хлеб или 1 кекс)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Возьмите любой рецепт кето-хлеба или кекса.\n2. Когда смешиваете сухие ингредиенты (муку, разрыхлитель), добавьте 1 ст. ложку муки расторопши.\n3. Дальше готовьте по рецепту — время выпечки не меняется.\n4. Если понравится, в следующий раз увеличьте до 2 ст. ложек.\n\n💡 На вкус почти не влияет, тесто становится чуть темнее."},
        ],
    },
    {
        "key": "pastes",
        "emoji": "🥄",
        "match": ["pasta", "паста", "urbech", "урбеч"],
        "name": {"uz": "Yong'oq pastalari", "ru": "Ореховые пасты"},
        "shop": "pasta",
        "benefits": [
            {"uz": "Tarkibida faqat yong'oqning o'zi — shakar ham, palma yog'i ham yo'q. Bir osh qoshiq to'yimli yog' va oqsil beradi, tushlikkacha ochlikni ushlaydi.",
             "ru": "В составе только сам орех — ни сахара, ни пальмового масла. Ложка даёт сытные жиры и белок, удерживая голод до обеда."},
            {"uz": "Yeryong'oq pastasi magniy va B3 vitaminiga boy; xandonpista pastasi esa mis va lyuteinga — ko'z salomatligi uchun.",
             "ru": "Арахисовая паста богата магнием и витамином B3; фисташковая — медью и лютеином для здоровья глаз."},
        ],
        "recipes": [
            {"uz": "<b>Keto konfet — 3 ta masalliqdan</b>\n⏱ 20 daqiqa (shundan 15 daqiqasi muzlatgichda) · 🍽 10 dona\n\n🧾 <b>Masalliqlar:</b>\n• 4 osh qoshiq yong'oq pastasi (bodom, yeryong'oq yoki funduk)\n• 2 osh qoshiq kokos yog'i (eritilgan)\n• 1 osh qoshiq maydalangan eritritol\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Kokos yog'ini suv hammomida yoki mikroto'lqinli pechda 20 soniya eriting.\n2. Idishda yong'oq pastasi, erigan kokos yog'i va eritritolni silliq bo'lguncha aralashtiring.\n3. Pergament qog'ozga choy qoshiq bilan 10 ta kichik doira qilib tomizing (yoki konfet qolipiga quying).\n4. Muzlatgichda (morozilkada) 15 daqiqa qotiring.\n5. Qotgach, yopiq idishga olib, muzlatkichda saqlang.\n\n💡 Ustiga bir chimdim dag'al tuz sepsangiz, «tuzli karamel» ta'mi chiqadi.",
             "ru": "<b>Кето-конфеты из 3 ингредиентов</b>\n⏱ 20 минут (из них 15 в морозилке) · 🍽 10 штук\n\n🧾 <b>Ингредиенты:</b>\n• 4 ст. ложки ореховой пасты (миндальной, арахисовой или фундучной)\n• 2 ст. ложки кокосового масла (растопленного)\n• 1 ст. ложка молотого эритрита\n\n👩‍🍳 <b>Приготовление:</b>\n1. Растопите кокосовое масло на водяной бане или 20 секунд в микроволновке.\n2. Смешайте в миске ореховую пасту, растопленное масло и эритрит до гладкости.\n3. Выложите чайной ложкой на пергамент 10 маленьких кружков (или разлейте по формочкам для конфет).\n4. Заморозьте в морозилке 15 минут.\n5. Переложите застывшие конфеты в контейнер и храните в холодильнике.\n\n💡 Щепотка крупной соли сверху даёт вкус «солёной карамели»."},
            {"uz": "<b>Yong'oq pastali smuzi-kosa</b>\n⏱ 5 daqiqa · 🍽 1 kishilik\n\n🧾 <b>Masalliqlar:</b>\n• 1 osh qoshiq yong'oq pastasi\n• 150 ml kokos suti\n• 100 g muzlatilgan rezavor (qulupnay, malina yoki qorag'at)\n• 1 choy qoshiq chia urug'i\n• Ustiga: 1 osh qoshiq kokos qirindisi va 1 choy qoshiq kakao nibs\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Blender idishiga kokos suti, muzlatilgan rezavor, yong'oq pastasi va chiani soling.\n2. Quyuq va silliq bo'lguncha 40–60 soniya aylantiring (quyuq qatiqdek bo'lishi kerak).\n3. Kosaga soling.\n4. Ustiga kokos qirindisi va kakao nibs sepib, darhol qoshiq bilan yeng.\n\n💡 Rezavor muzlatilgan bo'lishi shart — shunda smuzi muzqaymoqdek quyuq chiqadi.",
             "ru": "<b>Смузи-боул с ореховой пастой</b>\n⏱ 5 минут · 🍽 1 порция\n\n🧾 <b>Ингредиенты:</b>\n• 1 ст. ложка ореховой пасты\n• 150 мл кокосового молока\n• 100 г замороженных ягод (клубника, малина или смородина)\n• 1 ч. ложка семян чиа\n• Сверху: 1 ст. ложка кокосовой стружки и 1 ч. ложка какао-крупки\n\n👩‍🍳 <b>Приготовление:</b>\n1. Сложите в блендер кокосовое молоко, замороженные ягоды, ореховую пасту и чиа.\n2. Взбивайте 40–60 секунд до густоты и гладкости (как густой йогурт).\n3. Выложите в миску.\n4. Посыпьте кокосовой стружкой и какао-крупкой и сразу ешьте ложкой.\n\n💡 Ягоды должны быть замороженными — тогда смузи получится густым, как мороженое."},
        ],
    },
    {
        "key": "nuts",
        "emoji": "🌰",
        "match": ["fistashka", "фисташ", "pista", "писта", "mag'z", "magz", "yeryong'oq", "yeryongoq", "арахис"],
        "name": {"uz": "Yong'oq va mag'izlar", "ru": "Орехи и ядра"},
        "shop": "pista",
        "benefits": [
            {"uz": "Bir hovuch (~30g) yong'oq — ideal gazak: qonda shakarni ko'tarmaydi, lekin 2-3 soatga to'q qiladi.",
             "ru": "Горсть (~30г) орехов — идеальный перекус: не поднимает сахар, но насыщает на 2-3 часа."},
            {"uz": "Xandonpista boshqa yong'oqlarga qaraganda kamroq kaloriyali va oqsilga boyroq. Kechqurun ochlik tutsa — eng xavfsiz tanlov.",
             "ru": "Фисташки менее калорийны и богаче белком, чем другие орехи. Самый безопасный выбор при вечернем голоде."},
        ],
        "recipes": [
            {"uz": "<b>Uyda yong'oq pastasi</b>\n⏱ 15 daqiqa · 🍽 1 banka (200 g)\n\n🧾 <b>Masalliqlar:</b>\n• 200 g yong'oq mag'zi (bodom, yeryong'oq yoki funduk)\n• 1 chimdim tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Mag'izni quruq tovada o'rtacha olovda 5–7 daqiqa, aralashtirib, aromat chiqquncha qizdiring (kuydirmang).\n2. 5 daqiqa sovuting — iliq mag'iz tezroq pastaga aylanadi.\n3. Kuchli blender yoki kombaynga mag'iz va tuzni soling.\n4. To'xtovsiz aylantiring: avval un bo'ladi, keyin bir bo'lak xamirga aylanadi, 8–10 daqiqadan keyin mag'iz yog' chiqarib suyuq pastaga aylanadi.\n5. Har 2 daqiqada to'xtatib, idish devoridagi massani spatula bilan pastga tushiring.\n6. Toza bankaga solib, muzlatkichda saqlang.\n\n💡 Sabr qiling va yog' qo'shmang — mag'iz o'zi yog' chiqaradi. Muzlatkichda 1 oy turadi.",
             "ru": "<b>Ореховая паста дома</b>\n⏱ 15 минут · 🍽 1 банка (200 г)\n\n🧾 <b>Ингредиенты:</b>\n• 200 г ядер орехов (миндаль, арахис или фундук)\n• 1 щепотка соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Прогрейте орехи на сухой сковороде на среднем огне 5–7 минут, помешивая, до аромата (не сжигайте).\n2. Остудите 5 минут — тёплые орехи быстрее превращаются в пасту.\n3. Сложите орехи и соль в мощный блендер или комбайн.\n4. Измельчайте без остановки: сначала будет мука, потом комок, через 8–10 минут орехи выделят масло и станут жидкой пастой.\n5. Каждые 2 минуты останавливайтесь и счищайте массу со стенок лопаткой.\n6. Переложите в чистую банку и храните в холодильнике.\n\n💡 Наберитесь терпения и не добавляйте масло — орехи отдадут его сами. В холодильнике хранится 1 месяц."},
            {"uz": "<b>Fistashka unli keto pechene</b>\n⏱ 25 daqiqa · 🍽 12 dona\n\n🧾 <b>Masalliqlar:</b>\n• 150 g fistashka uni\n• 1 ta tuxum\n• 50 g sariyog' (yumshatilgan, xona haroratida)\n• 40 g eritritol\n• 1 chimdim tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Pechni 170°C ga qizdiring. Laganga pergament qog'oz to'shang.\n2. Yumshoq sariyog' va eritritolni vilka bilan 1 daqiqa ezib aralashtiring.\n3. Tuxumni qo'shib aralashtiring.\n4. Fistashka uni va tuzni qo'shib, yumshoq xamir qoring.\n5. Xamirdan yong'oqdek (taxminan 20 g) 12 ta sharcha yasang, laganga 3 sm oraliqda tering va kaft bilan 1 sm qalinlikkacha bosing.\n6. 170°C da 15 daqiqa, chetlari qizarguncha pishiring.\n7. Laganda 10 daqiqa sovuting — issiqligida yumshoq, sovigach qattiqlashadi.",
             "ru": "<b>Кето-печенье из фисташковой муки</b>\n⏱ 25 минут · 🍽 12 штук\n\n🧾 <b>Ингредиенты:</b>\n• 150 г фисташковой муки\n• 1 яйцо\n• 50 г сливочного масла (мягкого, комнатной температуры)\n• 40 г эритрита\n• 1 щепотка соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Разогрейте духовку до 170°C. Застелите противень пергаментом.\n2. Разомните вилкой мягкое масло с эритритом 1 минуту.\n3. Добавьте яйцо и перемешайте.\n4. Всыпьте фисташковую муку и соль, замесите мягкое тесто.\n5. Скатайте 12 шариков размером с грецкий орех (около 20 г), выложите на противень на расстоянии 3 см и приплюсните ладонью до толщины 1 см.\n6. Выпекайте 15 минут при 170°C, до румяных краёв.\n7. Остудите на противне 10 минут — горячее печенье мягкое, остывшее твердеет."},
        ],
    },
    {
        "key": "chickpea",
        "emoji": "🫘",
        "match": ["no'xat", "noxat", "нухат", "нут ", "chickpea"],
        "name": {"uz": "No'xat uni", "ru": "Нутовая мука"},
        "shop": "no'xat",
        "benefits": [
            {"uz": "No'xat uni oqsilga boy (100g da ~20g) va glutensiz. Tuxum yemaydiganlar uchun omlet o'rnini bosuvchi asos.",
             "ru": "Нутовая мука богата белком (~20г на 100г) и без глютена. Основа для замены омлета тем, кто не ест яйца."},
            {"uz": "Glikemik indeksi bug'doy unidan ancha past — energiya sekin va bir tekis ajraladi.",
             "ru": "Гликемический индекс заметно ниже пшеничной муки — энергия высвобождается медленно и ровно."},
        ],
        "recipes": [
            {"uz": "<b>Farinata — no'xat unidan kulcha</b>\n⏱ 30 daqiqa + 2 soat tindirish · 🍽 4 bo'lak\n\n🧾 <b>Masalliqlar:</b>\n• 100 g no'xat uni\n• 300 ml iliq suv\n• 2 osh qoshiq zaytun yog'i (1 tasi xamirga, 1 tasi qolipga)\n• 1/2 choy qoshiq tuz\n• 1/2 choy qoshiq quritilgan rozmarin (yoki 1 shoxcha yangisi)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Idishda no'xat uni va tuzni aralashtiring.\n2. Iliq suvni asta-sekin quyib, venchik bilan uring — xamir suyuq, quyruqsiz bo'lsin.\n3. 1 osh qoshiq zaytun yog'ini qo'shib aralashtiring, usti yopiq holda 2 soat qoldiring.\n4. Ustidagi ko'pikni qoshiq bilan olib tashlang.\n5. Pechni 220°C ga qizdiring. 24 sm li qolipga 1 osh qoshiq yog' quyib, qolipni pechda 5 daqiqa qizdiring.\n6. Issiq qolipga xamirni quying, ustiga rozmarin seping.\n7. 200°C da 20 daqiqa, chetlari qizarib, o'rtasi qotguncha pishiring. 4 bo'lakka kesib, issiq holda torting.",
             "ru": "<b>Фарината — лепёшка из нутовой муки</b>\n⏱ 30 минут + 2 часа отстаивания · 🍽 4 куска\n\n🧾 <b>Ингредиенты:</b>\n• 100 г нутовой муки\n• 300 мл тёплой воды\n• 2 ст. ложки оливкового масла (1 в тесто, 1 в форму)\n• 1/2 ч. ложки соли\n• 1/2 ч. ложки сушёного розмарина (или 1 веточка свежего)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Смешайте в миске нутовую муку и соль.\n2. Постепенно вливайте тёплую воду, взбивая венчиком, — тесто должно быть жидким и без комков.\n3. Добавьте 1 ст. ложку масла, перемешайте, накройте и оставьте на 2 часа.\n4. Снимите ложкой пену с поверхности.\n5. Разогрейте духовку до 220°C. Налейте 1 ст. ложку масла в форму 24 см и прогрейте её в духовке 5 минут.\n6. Вылейте тесто в горячую форму, посыпьте розмарином.\n7. Выпекайте 20 минут при 200°C, пока края не подрумянятся, а центр не схватится. Нарежьте на 4 части и подавайте горячей."},
            {"uz": "<b>Tuxumsiz «omlet» (no'xat unidan)</b>\n⏱ 10 daqiqa · 🍽 1 kishilik\n\n🧾 <b>Masalliqlar:</b>\n• 4 osh qoshiq no'xat uni (40 g)\n• 100 ml suv\n• 1 chimdim tuz\n• 1 chimdim qora murch\n• 1/4 choy qoshiq kurkuma (rang uchun)\n• 1 choy qoshiq yog' (tova uchun)\n• Ixtiyoriy: 2 osh qoshiq mayda to'g'ralgan sabzavot (bulg'or qalampiri, ko'kat)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Idishda no'xat uni, tuz, murch va kurkumani aralashtiring.\n2. Suvni asta-sekin quyib, venchik bilan quyruqsiz suyuq xamir qiling (suyuq qaymoqdek).\n3. Xohlasangiz, to'g'ralgan sabzavotni qo'shing.\n4. Tovani o'rtacha olovda qizdirib, yog' surting va xamirni quying.\n5. Qopqoq ostida 4 daqiqa, usti qotguncha pishiring.\n6. Kurakcha bilan ag'darib, yana 1–2 daqiqa pishiring va issiq holda torting.",
             "ru": "<b>«Омлет» без яиц (из нутовой муки)</b>\n⏱ 10 минут · 🍽 1 порция\n\n🧾 <b>Ингредиенты:</b>\n• 4 ст. ложки нутовой муки (40 г)\n• 100 мл воды\n• 1 щепотка соли\n• 1 щепотка чёрного перца\n• 1/4 ч. ложки куркумы (для цвета)\n• 1 ч. ложка масла (для сковороды)\n• По желанию: 2 ст. ложки мелко нарезанных овощей (болгарский перец, зелень)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Смешайте в миске нутовую муку, соль, перец и куркуму.\n2. Постепенно влейте воду и взбейте венчиком без комков (как жидкие сливки).\n3. По желанию добавьте нарезанные овощи.\n4. Разогрейте сковороду на среднем огне, смажьте маслом и вылейте тесто.\n5. Готовьте под крышкой 4 минуты, пока верх не схватится.\n6. Переверните лопаткой, жарьте ещё 1–2 минуты и подавайте горячим."},
        ],
    },
    {
        "key": "rice_flour",
        "emoji": "🍙",
        "match": ["guruch uni", "гуруч уни", "рисовая мука", "rice flour"],
        "name": {"uz": "Guruch uni", "ru": "Рисовая мука"},
        "shop": "guruch uni",
        "benefits": [
            {"uz": "Guruch uni glutensiz va neytral ta'mli — sezgir hazm uchun eng yumshoq un. Qovurishda xrustaydigan qobiq beradi.",
             "ru": "Рисовая мука без глютена и с нейтральным вкусом — самая мягкая мука для чувствительного пищеварения. При жарке даёт хрустящую корочку."},
            {"uz": "Boshqa glutensiz unlar bilan aralashtirilganda xamirni yengil qiladi — bodom yoki kokos uniga 20-30% qo'shsangiz natija yaxshilanadi.",
             "ru": "В смеси с другими безглютеновыми мукой делает тесто легче — добавьте 20-30% к миндальной или кокосовой, и результат улучшится."},
        ],
        "recipes": [
            {"uz": "<b>Guruch unidan yupqa nonlar</b>\n⏱ 20 daqiqa · 🍽 6 dona\n\n🧾 <b>Masalliqlar:</b>\n• 150 g guruch uni\n• 120 ml issiq suv (qaynoq, taxminan 90°C)\n• 1 osh qoshiq yog' (zaytun yoki kungaboqar)\n• 1/2 choy qoshiq tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Idishda guruch uni va tuzni aralashtiring.\n2. Issiq suv va yog'ni qo'shib, avval qoshiq bilan, biroz sovigach qo'l bilan yumshoq xamir qoring.\n3. Xamirni yopib, 10 daqiqa dam bering.\n4. 6 ta teng bo'lakka bo'ling. Har birini ikki pergament orasida 2 mm qalinlikda yoying.\n5. Quruq (yog'siz) tovani o'rtacha olovda qizdiring.\n6. Har bir nonni har tomoniga 1 daqiqadan, dog'lar paydo bo'lguncha pishiring.\n7. Tayyor nonlarni sochiq ostida ushlang — yumshoq qoladi.\n\n💡 Xamir yoyishda yorilsa, 1 osh qoshiq issiq suv qo'shib qayta qoring.",
             "ru": "<b>Тонкие лепёшки из рисовой муки</b>\n⏱ 20 минут · 🍽 6 штук\n\n🧾 <b>Ингредиенты:</b>\n• 150 г рисовой муки\n• 120 мл горячей воды (почти кипяток, около 90°C)\n• 1 ст. ложка масла (оливкового или подсолнечного)\n• 1/2 ч. ложки соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Смешайте в миске рисовую муку и соль.\n2. Добавьте горячую воду и масло, перемешайте ложкой, а когда немного остынет — замесите руками мягкое тесто.\n3. Накройте и дайте тесту отдохнуть 10 минут.\n4. Разделите на 6 частей. Каждую раскатайте между двумя листами пергамента толщиной 2 мм.\n5. Разогрейте сухую (без масла) сковороду на среднем огне.\n6. Жарьте каждую лепёшку по 1 минуте с каждой стороны, до появления пятнышек.\n7. Готовые лепёшки держите под полотенцем — останутся мягкими.\n\n💡 Если тесто трескается при раскатке, добавьте 1 ст. ложку горячей воды и перемесите."},
            {"uz": "<b>Qarsillaydigan qobiq (panirovka o'rniga)</b>\n⏱ 15 daqiqa · 🍽 2 kishilik (400 g go'sht yoki baliq uchun)\n\n🧾 <b>Masalliqlar:</b>\n• 4 osh qoshiq guruch uni (40 g)\n• 1/2 choy qoshiq tuz\n• 1/2 choy qoshiq paprika\n• 1/4 choy qoshiq qora murch\n• 400 g tovuq filesi yoki baliq\n• 2 osh qoshiq yog' (qovurish uchun)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Tovuq yoki baliqni 2 sm qalinlikdagi bo'laklarga kesing va qog'oz sochiq bilan quriting.\n2. Tekis idishda guruch uni, tuz, paprika va murchni aralashtiring.\n3. Har bir bo'lakni un aralashmasiga har tomonidan botirib oling.\n4. Tovada yog'ni o'rtacha-baland olovda qizdiring.\n5. Bo'laklarni har tomonidan 3–4 daqiqadan, oltinrang qobiq hosil bo'lguncha qovuring.\n6. Tovuq ichi oq bo'lsa (pushti rang qolmasa) — tayyor.\n\n💡 Bug'doy panirovkasidan yengilroq va qarsillaydiganroq chiqadi.",
             "ru": "<b>Хрустящая панировка из рисовой муки</b>\n⏱ 15 минут · 🍽 2 порции (на 400 г мяса или рыбы)\n\n🧾 <b>Ингредиенты:</b>\n• 4 ст. ложки рисовой муки (40 г)\n• 1/2 ч. ложки соли\n• 1/2 ч. ложки паприки\n• 1/4 ч. ложки чёрного перца\n• 400 г куриного филе или рыбы\n• 2 ст. ложки масла (для жарки)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Нарежьте курицу или рыбу кусочками толщиной 2 см и обсушите бумажным полотенцем.\n2. Смешайте в плоской тарелке рисовую муку, соль, паприку и перец.\n3. Обваляйте каждый кусочек в смеси со всех сторон.\n4. Разогрейте масло на сковороде на среднем-сильном огне.\n5. Жарьте по 3–4 минуты с каждой стороны до золотистой корочки.\n6. Курица готова, когда внутри белая (без розового цвета).\n\n💡 Легче и хрустящее, чем пшеничная панировка."},
        ],
    },
    {
        "key": "diet_rice",
        "emoji": "🍚",
        "match": ["guruch", "гуруч", "bulgur", "булгур", "basmati", "басмати", "devzira", "девзира", "рис "],
        "name": {"uz": "Dietik guruch va bulgur", "ru": "Диетический рис и булгур"},
        "shop": "guruch",
        "benefits": [
            {"uz": "Qora va qizil guruch qobig'i saqlangan — oq guruchga qaraganda tola va antotsianinlarga ancha boy, qonda shakarni sekinroq ko'taradi.",
             "ru": "Чёрный и красный рис сохраняют оболочку — заметно больше клетчатки и антоцианов, чем в белом, и сахар поднимается медленнее."},
            {"uz": "Bulgur — oldindan bug'langan bug'doy yormasi. Tez pishadi va glikemik indeksi oddiy guruchdan past.",
             "ru": "Булгур — предварительно пропаренная пшеничная крупа. Готовится быстро, а гликемический индекс ниже обычного риса."},
            {"uz": "Pishgan guruchni sovutib yesangiz, tarkibida rezistent kraxmal hosil bo'ladi — u ichak mikroflorasini oziqlantiradi va kamroq so'riladi.",
             "ru": "Если сварить рис и охладить, образуется резистентный крахмал — он питает микрофлору кишечника и меньше усваивается."},
        ],
        "recipes": [
            {"uz": "<b>Qora guruchli salat</b>\n⏱ 40 daqiqa · 🍽 4 kishilik\n\n🧾 <b>Masalliqlar:</b>\n• 200 g qora guruch\n• 500 ml suv (pishirish uchun)\n• 1 ta bodring\n• 2 ta pomidor\n• 1 bog' ko'kat (shivit yoki petrushka)\n• 3 osh qoshiq zaytun yog'i\n• 1 osh qoshiq olma sirkasi\n• 1/2 choy qoshiq tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Guruchni sovuq suvda 2–3 marta yuving.\n2. 500 ml suvni qaynatib, guruch va chimdim tuz soling. Qopqoqni yopib, past olovda 30–35 daqiqa pishiring.\n3. Suvi qolsa to'kib tashlang, guruchni tekis idishga yoyib to'liq sovuting.\n4. Bodring va pomidorni 1 sm kubik qilib to'g'rang, ko'katni mayda to'g'rang.\n5. Kichik idishda zaytun yog'i, olma sirkasi va qolgan tuzni aralashtirib sous qiling.\n6. Guruch, sabzavot va ko'katni aralashtirib, sousni quying va torting.\n\n💡 Ertasi kuni ham mazali turadi — tushlikka olib borishga qulay.",
             "ru": "<b>Салат с чёрным рисом</b>\n⏱ 40 минут · 🍽 4 порции\n\n🧾 <b>Ингредиенты:</b>\n• 200 г чёрного риса\n• 500 мл воды (для варки)\n• 1 огурец\n• 2 помидора\n• 1 пучок зелени (укроп или петрушка)\n• 3 ст. ложки оливкового масла\n• 1 ст. ложка яблочного уксуса\n• 1/2 ч. ложки соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Промойте рис холодной водой 2–3 раза.\n2. Доведите 500 мл воды до кипения, добавьте рис и щепотку соли. Варите под крышкой на слабом огне 30–35 минут.\n3. Слейте остаток воды, разложите рис на блюде и полностью остудите.\n4. Нарежьте огурец и помидоры кубиком 1 см, зелень — мелко.\n5. В маленькой миске смешайте масло, уксус и оставшуюся соль — это заправка.\n6. Смешайте рис, овощи и зелень, полейте заправкой и подавайте.\n\n💡 Хорошо стоит и на следующий день — удобно брать с собой."},
            {"uz": "<b>Bulgurli tabbule</b>\n⏱ 25 daqiqa · 🍽 4 kishilik\n\n🧾 <b>Masalliqlar:</b>\n• 150 g bulgur\n• 300 ml qaynoq suv\n• 2 bog' petrushka\n• 1/2 bog' yalpiz (ixtiyoriy)\n• 2 ta pomidor\n• 1/2 ta kichik piyoz\n• Yarim limon sharbati (2 osh qoshiq)\n• 3 osh qoshiq zaytun yog'i\n• 1/2 choy qoshiq tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Bulgurni idishga solib, 300 ml qaynoq suv quying, yopib 20 daqiqa qo'ying — pishirmang.\n2. Shu vaqtda petrushka va yalpizni juda mayda to'g'rang.\n3. Pomidorni 1 sm kubik, piyozni mayda qilib to'g'rang.\n4. Bulgur yumshagach, ortiqcha suvini elakda siqib to'king.\n5. Bulgur, ko'kat, pomidor va piyozni aralashtiring.\n6. Limon sharbati, zaytun yog'i va tuzni qo'shib aralashtiring va torting.\n\n💡 Tabbuleda ko'kat asosiy — bulgurdan ko'p bo'lishi kerak.",
             "ru": "<b>Табуле с булгуром</b>\n⏱ 25 минут · 🍽 4 порции\n\n🧾 <b>Ингредиенты:</b>\n• 150 г булгура\n• 300 мл кипятка\n• 2 пучка петрушки\n• 1/2 пучка мяты (по желанию)\n• 2 помидора\n• 1/2 небольшой луковицы\n• Сок половины лимона (2 ст. ложки)\n• 3 ст. ложки оливкового масла\n• 1/2 ч. ложки соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Залейте булгур 300 мл кипятка, накройте и оставьте на 20 минут — не варите.\n2. Тем временем очень мелко порубите петрушку и мяту.\n3. Нарежьте помидоры кубиком 1 см, лук — мелко.\n4. Когда булгур размягчится, откиньте на сито и отожмите лишнюю воду.\n5. Смешайте булгур, зелень, помидоры и лук.\n6. Добавьте лимонный сок, масло и соль, перемешайте и подавайте.\n\n💡 В табуле главное — зелень: её должно быть больше, чем булгура."},
        ],
    },
    {
        "key": "pp_flour",
        "emoji": "🌾",
        "match": ["bug'doy uni", "bugdoy uni", "arpa uni", "javdar", "ржан", "polba", "полб", "makkajo'xori", "makkajoxori", "кукуруз", "kraxmal", "крахмал", "jo'xori", "joxori", "ovsyanka", "овсян", "2-nav", "pp un", "пп мук"],
        "name": {"uz": "PP unlar", "ru": "ПП-мука"},
        "shop": "uni",
        "benefits": [
            {"uz": "To'liq donli PP unlar oddiy oq unga nisbatan sekin hazm bo'ladi — energiya bir tekis taqsimlanadi, ortiqcha ishtaha bosiladi.",
             "ru": "Цельнозерновая ПП-мука усваивается медленнее белой — энергия распределяется ровно, аппетит под контролем."},
            {"uz": "Polba va javdar unida gluten bor, lekin oddiy bug'doyga qaraganda kamroq va yengilroq. Ovsyanka uni esa beta-glyukanga boy — xolesterinni tushirishga yordam beradi.",
             "ru": "В полбе и ржи глютен есть, но его меньше и он мягче, чем в обычной пшенице. Овсяная мука богата бета-глюканом — помогает снижать холестерин."},
        ],
        "recipes": [
            {"uz": "<b>PP blinchiklar</b>\n⏱ 20 daqiqa · 🍽 8 dona\n\n🧾 <b>Masalliqlar:</b>\n• 120 g PP un (suli yoki polba uni)\n• 2 ta tuxum\n• 250 ml sut yoki suv\n• 1/4 choy qoshiq tuz\n• 1 osh qoshiq eritritol (shirin blinchik uchun)\n• 1 choy qoshiq yog' (tova uchun)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Idishda tuxum, tuz va eritritolni vilka bilan ko'pirtiring.\n2. Sutni quyib aralashtiring.\n3. Unni asta-sekin qo'shib, venchik bilan quyruqsiz suyuq xamir qiling.\n4. Xamirni 15 daqiqa qo'yib qo'ying — un shishib, blinchik yirtilmaydi.\n5. Tovani o'rtacha olovda qizdirib, yog' surting. 1 cho'mich (50 ml) xamir quyib, tovani aylantirib yoying.\n6. Har tomonini 1 daqiqadan pishiring.\n7. Tvorog yoki 1 choy qoshiq asal bilan torting.",
             "ru": "<b>ПП-блинчики</b>\n⏱ 20 минут · 🍽 8 штук\n\n🧾 <b>Ингредиенты:</b>\n• 120 г ПП-муки (овсяной или полбяной)\n• 2 яйца\n• 250 мл молока или воды\n• 1/4 ч. ложки соли\n• 1 ст. ложка эритрита (для сладких блинчиков)\n• 1 ч. ложка масла (для сковороды)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Взбейте вилкой яйца с солью и эритритом.\n2. Влейте молоко и перемешайте.\n3. Постепенно всыпьте муку и взбейте венчиком в жидкое тесто без комков.\n4. Оставьте тесто на 15 минут — мука набухнет, и блинчики не будут рваться.\n5. Разогрейте сковороду на среднем огне, смажьте маслом. Налейте половник (50 мл) теста и распределите, вращая сковороду.\n6. Жарьте по 1 минуте с каждой стороны.\n7. Подавайте с творогом или 1 ч. ложкой мёда."},
            {"uz": "<b>Javdar unidan PP non</b>\n⏱ 2 soat (shundan 1 soati ko'tarilish) · 🍽 1 non\n\n🧾 <b>Masalliqlar:</b>\n• 300 g javdar uni\n• 200 ml iliq suv (37–40°C, qo'lga iliq)\n• 1 choy qoshiq tuz\n• 7 g (1 paket) quruq xamirturush YOKI 100 g faol zakvaska\n• 1 choy qoshiq asal (xamirturush uchun)\n• 1 osh qoshiq kunjut yoki zig'ir urug'i (ustiga)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Iliq suvda asal va xamirturushni eritib, 10 daqiqa ko'pik chiqquncha qo'ying (zakvaska bo'lsa, shunchaki suvga qo'shing).\n2. Idishda javdar uni va tuzni aralashtiring.\n3. Xamirturushli suvni quyib, qoshiq bilan yopishqoq xamir qoring — javdar xamiri bug'doynikidek elastik bo'lmaydi, bu normal.\n4. Ho'l qo'l bilan non shaklini berib, pergament to'shalgan qolipga soling, ustiga kunjut seping.\n5. Ustini sochiq bilan yopib, iliq joyda 1 soat (zakvaska bilan 3–4 soat) ko'tarilishga qo'ying.\n6. Pechni 200°C ga qizdiring va nonni 35 daqiqa pishiring.\n7. Panjarada to'liq sovuting, keyin kesing.\n\n💡 Non tagini chertib ko'ring: bo'g'iq «bo'sh» ovoz chiqsa — pishgan.",
             "ru": "<b>ПП-хлеб из ржаной муки</b>\n⏱ 2 часа (из них 1 час на подъём) · 🍽 1 буханка\n\n🧾 <b>Ингредиенты:</b>\n• 300 г ржаной муки\n• 200 мл тёплой воды (37–40°C, тёплая для руки)\n• 1 ч. ложка соли\n• 7 г (1 пакетик) сухих дрожжей ИЛИ 100 г активной закваски\n• 1 ч. ложка мёда (для дрожжей)\n• 1 ст. ложка кунжута или льна (сверху)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Растворите в тёплой воде мёд и дрожжи и оставьте на 10 минут до пены (закваску просто добавьте в воду).\n2. Смешайте в миске ржаную муку и соль.\n3. Влейте воду с дрожжами и замесите ложкой липкое тесто — ржаное тесто не бывает эластичным, как пшеничное, это нормально.\n4. Влажными руками сформуйте буханку, выложите в форму с пергаментом, посыпьте кунжутом.\n5. Накройте полотенцем и оставьте в тепле на 1 час (с закваской — 3–4 часа).\n6. Разогрейте духовку до 200°C и выпекайте 35 минут.\n7. Полностью остудите на решётке и только потом режьте.\n\n💡 Постучите по дну: глухой «пустой» звук — хлеб пропёкся."},
        ],
    },
    {
        "key": "bran",
        "emoji": "🥖",
        "match": ["kepak", "otrub", "отруб"],
        "name": {"uz": "Kepak", "ru": "Отруби"},
        "shop": "kepak",
        "benefits": [
            {"uz": "Kepak — tabiiy tolaning eng arzon va eng kuchli manbai. Ichak ishini yo'lga soladi, to'yimlilikni uzaytiradi va umumiy kaloriyani kamaytiradi.",
             "ru": "Отруби — самый доступный и мощный источник клетчатки. Налаживают кишечник, продлевают сытость и снижают общую калорийность."},
            {"uz": "Kuniga 1-2 osh qoshiqdan boshlang va suvni ko'p iching — tola suv bilan birga ishlaydi, quruq holda aksincha ta'sir qilishi mumkin.",
             "ru": "Начинайте с 1-2 ст.л. в день и пейте больше воды — клетчатка работает вместе с водой, всухую может дать обратный эффект."},
        ],
        "recipes": [
            {"uz": "<b>Kepakli sirniki</b>\n⏱ 20 daqiqa · 🍽 8 dona\n\n🧾 <b>Masalliqlar:</b>\n• 200 g tvorog (5–9%)\n• 1 ta tuxum\n• 2 osh qoshiq kepak (bug'doy yoki suli)\n• 1 osh qoshiq eritritol\n• 1 chimdim tuz\n• 1 osh qoshiq yog' (qovurish uchun)\n• Torting uchun: 2 osh qoshiq tabiiy yogurt\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Idishda tvorogni vilka bilan yaxshilab ezing.\n2. Tuxum, kepak, eritritol va tuzni qo'shib aralashtiring.\n3. 5 daqiqa qo'yib qo'ying — kepak shishadi va massa quyuqlashadi.\n4. Ho'l qo'l bilan 8 ta kichik kulcha yasang (1,5 sm qalinlikda).\n5. Tovada yog'ni o'rtacha olovda qizdiring.\n6. Kulchalarni har tomonini 3 daqiqadan, qizarguncha qovuring.\n7. Ustiga tabiiy yogurt qo'yib torting.\n\n💡 Massa juda suyuq bo'lsa, yana 1 osh qoshiq kepak qo'shing.",
             "ru": "<b>Сырники с отрубями</b>\n⏱ 20 минут · 🍽 8 штук\n\n🧾 <b>Ингредиенты:</b>\n• 200 г творога (5–9%)\n• 1 яйцо\n• 2 ст. ложки отрубей (пшеничных или овсяных)\n• 1 ст. ложка эритрита\n• 1 щепотка соли\n• 1 ст. ложка масла (для жарки)\n• Для подачи: 2 ст. ложки натурального йогурта\n\n👩‍🍳 <b>Приготовление:</b>\n1. Хорошо разомните творог вилкой.\n2. Добавьте яйцо, отруби, эритрит и соль, перемешайте.\n3. Оставьте на 5 минут — отруби набухнут, масса загустеет.\n4. Влажными руками сформуйте 8 небольших сырников толщиной 1,5 см.\n5. Разогрейте масло на сковороде на среднем огне.\n6. Обжарьте по 3 минуты с каждой стороны до румяности.\n7. Подавайте с натуральным йогуртом.\n\n💡 Если масса слишком жидкая, добавьте ещё 1 ст. ложку отрубей."},
            {"uz": "<b>Kepakli non (tovada)</b>\n⏱ 15 daqiqa · 🍽 1 kishilik\n\n🧾 <b>Masalliqlar:</b>\n• 3 osh qoshiq kepak\n• 2 ta tuxum\n• 2 osh qoshiq tvorog\n• 1 chimdim tuz\n• 1 chimdim soda\n• 1/2 choy qoshiq yog' (tova uchun)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Idishda barcha masalliqlarni vilka bilan bir xil bo'lguncha aralashtiring.\n2. 3 daqiqa qo'yib qo'ying — kepak shishsin.\n3. Kichik tovani (18–20 sm) yog'lab, past olovda qizdiring.\n4. Massani tovaga quyib tekislang va qopqoq ostida 6 daqiqa pishiring.\n5. Kurakcha bilan ag'darib, qopqoqsiz yana 4 daqiqa pishiring.\n6. Biroz sovutib, ikkiga bo'ling — sendvich yoki nonushta noni tayyor.",
             "ru": "<b>Хлеб с отрубями на сковороде</b>\n⏱ 15 минут · 🍽 1 порция\n\n🧾 <b>Ингредиенты:</b>\n• 3 ст. ложки отрубей\n• 2 яйца\n• 2 ст. ложки творога\n• 1 щепотка соли\n• 1 щепотка соды\n• 1/2 ч. ложки масла (для сковороды)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Перемешайте вилкой все ингредиенты до однородности.\n2. Оставьте на 3 минуты — отруби набухнут.\n3. Смажьте небольшую сковороду (18–20 см) маслом и разогрейте на слабом огне.\n4. Вылейте массу, разровняйте и жарьте под крышкой 6 минут.\n5. Переверните лопаткой и жарьте без крышки ещё 4 минуты.\n6. Слегка остудите и разрежьте пополам — хлеб для сэндвича или завтрака готов."},
        ],
    },
    {
        "key": "sourdough",
        "emoji": "🫓",
        "match": ["solod", "солод", "zakvaska", "закваск", "hamirturush", "ҳамиртуруш", "hamirtrush"],
        "name": {"uz": "Zakvaska va solod", "ru": "Закваска и солод"},
        "shop": "zakvaska",
        "benefits": [
            {"uz": "Zakvaskali non oddiy hamirturushlikdan farqli: uzoq bijg'ish davomida fitin kislotasi parchalanadi va minerallar yaxshiroq so'riladi.",
             "ru": "Хлеб на закваске отличается от дрожжевого: при долгом брожении разрушается фитиновая кислота и минералы усваиваются лучше."},
            {"uz": "Fermentlangan solod nonga to'q rang, quyuq aromat va tabiiy shirinlik beradi — shakar qo'shmasdan.",
             "ru": "Ферментированный солод даёт хлебу тёмный цвет, густой аромат и природную сладость — без добавления сахара."},
        ],
        "recipes": [
            {"uz": "<b>Zakvaskani jonlantirish (3 kun)</b>\n⏱ kuniga 5 daqiqa · 3 kun\n\n🧾 <b>Masalliqlar:</b>\n• 50 g zakvaska (bizdagi tayyor zakvaska)\n• Har kuni: 50 g un (javdar yoki bug'doy)\n• Har kuni: 50 ml iliq suv (30°C)\n• 1 litrlik toza shisha banka\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. 1-kun: bankaga 50 g zakvaska, 50 g un va 50 ml iliq suvni solib, quyuq qaymoqdek aralashtiring.\n2. Bankani doka yoki teshikli qopqoq bilan yoping va xona haroratida (22–26°C) qoldiring.\n3. 2-kun: massaning yarmini olib tashlang, qolganiga yana 50 g un va 50 ml iliq suv qo'shib aralashtiring («boqing»).\n4. 3-kun: yana shunday boqing.\n5. Zakvaska 4–6 soatda ikki baravar ko'tarilsa, ko'pikli va yoqimli nordon hidli bo'lsa — tayyor, non yopishingiz mumkin.\n\n💡 Ishlatmasangiz, muzlatkichda saqlang va haftada bir marta boqing.",
             "ru": "<b>Как оживить закваску (3 дня)</b>\n⏱ 5 минут в день · 3 дня\n\n🧾 <b>Ингредиенты:</b>\n• 50 г закваски (наша готовая закваска)\n• Каждый день: 50 г муки (ржаной или пшеничной)\n• Каждый день: 50 мл тёплой воды (30°C)\n• Чистая стеклянная банка на 1 литр\n\n👩‍🍳 <b>Приготовление:</b>\n1. День 1: положите в банку 50 г закваски, 50 г муки и 50 мл тёплой воды, перемешайте до густоты сметаны.\n2. Накройте марлей или крышкой с дырочками и оставьте при комнатной температуре (22–26°C).\n3. День 2: уберите половину массы, к оставшейся добавьте 50 г муки и 50 мл тёплой воды, перемешайте («подкормите»).\n4. День 3: подкормите так же.\n5. Если закваска за 4–6 часов поднимается вдвое, пузырится и приятно пахнет кислым — готова, можно печь хлеб.\n\n💡 Если не используете — храните в холодильнике и подкармливайте раз в неделю."},
            {"uz": "<b>Solodli qora non</b>\n⏱ 3 soat (shundan 2 soati ko'tarilish) · 🍽 1 non\n\n🧾 <b>Masalliqlar:</b>\n• 400 g javdar uni\n• 2 osh qoshiq qora fermentlangan solod\n• 100 ml qaynoq suv (solod uchun)\n• 200 ml iliq suv (xamir uchun)\n• 150 g faol zakvaska\n• 1 choy qoshiq tuz\n• 1 choy qoshiq maydalangan koriandr (+ ustiga sepish uchun yarim choy qoshiq)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Solodni stakanga solib, 100 ml qaynoq suv quying, aralashtiring va 15 daqiqa iliq bo'lguncha soviting.\n2. Katta idishda javdar uni, tuz va koriandrni aralashtiring.\n3. Solod damlamasi, 200 ml iliq suv va zakvaskani qo'shing, qoshiq bilan yopishqoq xamir qoring.\n4. Ho'l qo'l bilan non shaklini berib, pergament to'shalgan qolipga soling, ustiga koriandr seping.\n5. Sochiq bilan yopib, iliq joyda 2 soat, xamir 1,5 baravar ko'tarilguncha qoldiring.\n6. Pechni 200°C ga qizdiring va nonni 45 daqiqa pishiring.\n7. Panjarada kamida 2 soat sovuting — javdar noni sovib bo'lgach «yetiladi».",
             "ru": "<b>Чёрный хлеб на солоде</b>\n⏱ 3 часа (из них 2 часа на подъём) · 🍽 1 буханка\n\n🧾 <b>Ингредиенты:</b>\n• 400 г ржаной муки\n• 2 ст. ложки ферментированного солода\n• 100 мл кипятка (для солода)\n• 200 мл тёплой воды (для теста)\n• 150 г активной закваски\n• 1 ч. ложка соли\n• 1 ч. ложка молотого кориандра (+ 1/2 ч. ложки для посыпки)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Залейте солод 100 мл кипятка, перемешайте и остудите 15 минут до тёплого.\n2. В большой миске смешайте ржаную муку, соль и кориандр.\n3. Добавьте заварку солода, 200 мл тёплой воды и закваску, замесите ложкой липкое тесто.\n4. Влажными руками сформуйте буханку, выложите в форму с пергаментом, посыпьте кориандром.\n5. Накройте полотенцем и оставьте в тепле на 2 часа, пока тесто не поднимется в 1,5 раза.\n6. Разогрейте духовку до 200°C и выпекайте 45 минут.\n7. Остудите на решётке минимум 2 часа — ржаной хлеб «доходит» после остывания."},
        ],
    },
    {
        "key": "sesame",
        "emoji": "⚪",
        "match": ["kunjut", "кунжут", "sesame", "tahini", "тахин"],
        "name": {"uz": "Kunjut", "ru": "Кунжут"},
        "shop": "kunjut",
        "benefits": [
            {"uz": "Kunjut kalsiy bo'yicha rekordchi: 100g da sutdagidan bir necha barobar ko'p. Suyak va tish salomatligi uchun.",
             "ru": "Кунжут — рекордсмен по кальцию: в 100г в разы больше, чем в молоке. Для здоровья костей и зубов."},
            {"uz": "Qora kunjutda antioksidantlar oq kunjutdagidan ko'proq. Yengil qovurilsa aromati ochiladi va yaxshiroq so'riladi.",
             "ru": "В чёрном кунжуте больше антиоксидантов, чем в белом. При лёгкой обжарке раскрывается аромат и лучше усваивается."},
        ],
        "recipes": [
            {"uz": "<b>Uy tahinisi (kunjut pastasi)</b>\n⏱ 15 daqiqa · 🍽 1 banka (200 g)\n\n🧾 <b>Masalliqlar:</b>\n• 200 g oq kunjut\n• 2–3 osh qoshiq zaytun yog'i\n• 1 chimdim tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Kunjutni quruq tovada o'rtacha olovda 3–4 daqiqa, to'xtovsiz aralashtirib qizdiring — och oltinrang bo'lsin, kuydirmang.\n2. Tekis idishga olib, 5 daqiqa sovuting.\n3. Kunjutni blender yoki kombaynga solib, 1–2 daqiqa unga aylantiring.\n4. 2 osh qoshiq yog' va tuzni qo'shib, yana 3–5 daqiqa silliq pasta bo'lguncha aylantiring; har daqiqada devorlardan tushirib turing.\n5. Juda quyuq bo'lsa, yana 1 osh qoshiq yog' qo'shing.\n6. Toza bankaga solib, muzlatkichda saqlang (1 oygacha).\n\n💡 Limon sharbati va sarimsoq qo'shsangiz — go'sht va sabzavotlar uchun tayyor sous.",
             "ru": "<b>Домашняя тахини (кунжутная паста)</b>\n⏱ 15 минут · 🍽 1 банка (200 г)\n\n🧾 <b>Ингредиенты:</b>\n• 200 г белого кунжута\n• 2–3 ст. ложки оливкового масла\n• 1 щепотка соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Прогрейте кунжут на сухой сковороде на среднем огне 3–4 минуты, постоянно помешивая, до светло-золотистого цвета — не сожгите.\n2. Переложите на тарелку и остудите 5 минут.\n3. Смелите кунжут в блендере или комбайне в муку 1–2 минуты.\n4. Добавьте 2 ст. ложки масла и соль и измельчайте ещё 3–5 минут до гладкой пасты, каждую минуту счищая со стенок.\n5. Если слишком густо — добавьте ещё 1 ст. ложку масла.\n6. Переложите в чистую банку и храните в холодильнике (до 1 месяца).\n\n💡 С лимонным соком и чесноком получится готовый соус к мясу и овощам."},
            {"uz": "<b>Kunjutli gomasio (tuz o'rniga)</b>\n⏱ 10 daqiqa · 🍽 1 kichik banka\n\n🧾 <b>Masalliqlar:</b>\n• 5 osh qoshiq kunjut (50 g)\n• 1 choy qoshiq Himalay tuzi\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Kunjutni quruq tovada o'rtacha olovda 3 daqiqa, oltinrang bo'lguncha aralashtirib qizdiring.\n2. Ohak (yoki kofe maydalagich)ga kunjut va tuzni soling.\n3. Yengil ezing (maydalagichda 2–3 marta qisqa bosing) — kunjutning yarmi butun qolsin.\n4. Sovigach, yopiq bankaga soling.\n5. Salat, guruch, tuxum va sabzavotlarga oddiy tuz o'rniga seping.\n\n💡 Tuzni 2 baravar kam ishlatasiz, ta'm esa boyroq bo'ladi.",
             "ru": "<b>Гомасио — кунжут вместо соли</b>\n⏱ 10 минут · 🍽 1 маленькая баночка\n\n🧾 <b>Ингредиенты:</b>\n• 5 ст. ложек кунжута (50 г)\n• 1 ч. ложка гималайской соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Прогрейте кунжут на сухой сковороде на среднем огне 3 минуты до золотистого цвета, помешивая.\n2. Сложите кунжут и соль в ступку (или кофемолку).\n3. Слегка разотрите (в кофемолке — 2–3 коротких нажатия) — половина зёрен должна остаться целой.\n4. Остудите и пересыпьте в закрытую баночку.\n5. Посыпайте салаты, рис, яйца и овощи вместо обычной соли.\n\n💡 Соли уходит вдвое меньше, а вкус богаче."},
        ],
    },
    {
        "key": "pumpkin_seed",
        "emoji": "🎃",
        "match": ["qovoq urug", "qovoq urugʻ", "тыквен", "pumpkin"],
        "name": {"uz": "Qovoq urug'i", "ru": "Тыквенные семечки"},
        "shop": "qovoq",
        "benefits": [
            {"uz": "Qovoq urug'i rux (sink) bo'yicha eng boy mahsulotlardan biri — immunitet va teri salomatligi uchun muhim mineral.",
             "ru": "Тыквенные семечки — один из богатейших источников цинка, важного минерала для иммунитета и кожи."},
            {"uz": "Tarkibidagi magniy va triptofan kechqurun asabni tinchlantiradi — uyqudan oldin bir hovuch yaxshi tanlov.",
             "ru": "Магний и триптофан в составе успокаивают вечером — горсть перед сном хороший выбор."},
        ],
        "recipes": [
            {"uz": "<b>Ziravorli qovurilgan qovoq urug'i</b>\n⏱ 15 daqiqa · 🍽 100 g gazak\n\n🧾 <b>Masalliqlar:</b>\n• 100 g tozalangan qovoq urug'i\n• 1 choy qoshiq zaytun yog'i\n• 1/4 choy qoshiq tuz\n• 1/2 choy qoshiq paprika\n• 1/4 choy qoshiq kurkuma\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Pechni 160°C ga qizdiring. Laganga pergament qog'oz to'shang.\n2. Idishda urug', yog', tuz, paprika va kurkumani aralashtiring — har bir urug' ziravorga bulansin.\n3. Laganga bir qatlam qilib yoying.\n4. 160°C da 12 daqiqa qovuring; 6-daqiqada bir marta aralashtiring.\n5. Urug'lar «chirsillay» boshlab, biroz shishsa — tayyor. To'liq sovuting.\n6. Yopiq bankada saqlang (2 haftagacha).",
             "ru": "<b>Пряные жареные тыквенные семечки</b>\n⏱ 15 минут · 🍽 100 г снека\n\n🧾 <b>Ингредиенты:</b>\n• 100 г очищенных тыквенных семечек\n• 1 ч. ложка оливкового масла\n• 1/4 ч. ложки соли\n• 1/2 ч. ложки паприки\n• 1/4 ч. ложки куркумы\n\n👩‍🍳 <b>Приготовление:</b>\n1. Разогрейте духовку до 160°C. Застелите противень пергаментом.\n2. Смешайте в миске семечки, масло, соль, паприку и куркуму — каждая семечка должна быть в специях.\n3. Распределите одним слоем на противне.\n4. Жарьте 12 минут при 160°C, перемешав один раз на 6-й минуте.\n5. Семечки начали потрескивать и слегка вздулись — готово. Полностью остудите.\n6. Храните в закрытой банке (до 2 недель)."},
            {"uz": "<b>Yashil pesto (qovoq urug'idan)</b>\n⏱ 10 daqiqa · 🍽 1 kichik banka (150 g)\n\n🧾 <b>Masalliqlar:</b>\n• 50 g qovoq urug'i\n• 1 katta bog' rayhon yoki petrushka (taxminan 40 g, faqat barglari)\n• 80 ml zaytun yog'i\n• 1 tishcha sarimsoq\n• 1/4 choy qoshiq tuz\n• 1 osh qoshiq limon sharbati\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Qovoq urug'ini quruq tovada 2–3 daqiqa qizdiring va sovuting.\n2. Ko'katni yuvib, sochiq bilan yaxshilab quriting va barglarini uzing.\n3. Blenderga urug', ko'kat, tozalangan sarimsoq, tuz va limon sharbatini soling.\n4. Aylantira turib, zaytun yog'ini asta-sekin quying.\n5. Kichik bo'lakchalar qolgan quyuq sous bo'lguncha 30–40 soniya aylantiring.\n6. Bankaga solib, ustiga yupqa qatlam zaytun yog'i quying — rangi qoraymaydi.\n\n💡 Go'sht, baliq, tuxum va sabzavotlarga mos. Muzlatkichda 5 kun turadi.",
             "ru": "<b>Зелёное песто на тыквенных семечках</b>\n⏱ 10 минут · 🍽 1 баночка (150 г)\n\n🧾 <b>Ингредиенты:</b>\n• 50 г тыквенных семечек\n• 1 большой пучок базилика или петрушки (около 40 г, только листья)\n• 80 мл оливкового масла\n• 1 зубчик чеснока\n• 1/4 ч. ложки соли\n• 1 ст. ложка лимонного сока\n\n👩‍🍳 <b>Приготовление:</b>\n1. Прогрейте семечки на сухой сковороде 2–3 минуты и остудите.\n2. Вымойте зелень, хорошо обсушите полотенцем и оборвите листья.\n3. Сложите в блендер семечки, зелень, очищенный чеснок, соль и лимонный сок.\n4. Взбивая, тонкой струйкой влейте масло.\n5. Взбивайте 30–40 секунд до густого соуса с мелкими кусочками.\n6. Переложите в баночку и залейте сверху тонким слоем масла — цвет не потемнеет.\n\n💡 Подходит к мясу, рыбе, яйцам и овощам. В холодильнике хранится 5 дней."},
        ],
    },
    {
        "key": "sedana",
        "emoji": "⚫",
        "match": ["sedana", "седана", "chernushka", "чернушк", "nigella", "kalonji", "qora zira"],
        "name": {"uz": "Qora sedana", "ru": "Чёрный тмин"},
        "shop": "sedana",
        "benefits": [
            {"uz": "Qora sedana — an'anaviy tabobatda eng hurmatli urug'lardan biri. Tarkibidagi timoxinon antioksidant sifatida o'rganilgan.",
             "ru": "Чёрный тмин — одно из самых почитаемых семян в традиционной медицине. Тимохинон в составе изучается как антиоксидант."},
            {"uz": "Kuniga yarim choy qoshiq — an'anaviy me'yor. Asal bilan aralashtirilsa ta'mi yumshaydi va yaxshiroq qabul qilinadi.",
             "ru": "Половина чайной ложки в день — традиционная норма. С мёдом вкус мягче и переносится легче."},
        ],
        "recipes": [
            {"uz": "<b>Sedana va asal aralashmasi</b>\n⏱ 5 daqiqa · 🍽 1 haftaga\n\n🧾 <b>Masalliqlar:</b>\n• 1 choy qoshiq maydalangan sedana (qora sedana urug'i)\n• 2 osh qoshiq asal (suyuq)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Sedanani kofe maydalagichda maydalang (yoki tayyor maydalanganini oling).\n2. Kichik bankada sedana va asalni bir xil bo'lguncha aralashtiring.\n3. Qopqog'ini yopib, xona haroratida saqlang.\n4. Ertalab och qoringa yarim choy qoshiqni bir stakan iliq suv bilan iching.\n\n💡 Asalni issiq suvga solmang — iliq suv yetarli. 12 yoshgacha bolalarga va homiladorlarga shifokor bilan kelishib bering.",
             "ru": "<b>Смесь чёрного тмина с мёдом</b>\n⏱ 5 минут · 🍽 на неделю\n\n🧾 <b>Ингредиенты:</b>\n• 1 ч. ложка молотого чёрного тмина\n• 2 ст. ложки мёда (жидкого)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Смелите семена тмина в кофемолке (или возьмите уже молотые).\n2. В маленькой баночке смешайте тмин и мёд до однородности.\n3. Закройте крышкой и храните при комнатной температуре.\n4. Утром натощак съешьте 1/2 ч. ложки, запивая стаканом тёплой воды.\n\n💡 Не растворяйте мёд в горячей воде — достаточно тёплой. Детям до 12 лет и беременным — по согласованию с врачом."},
            {"uz": "<b>Sedana — non ustiga ziravor</b>\n⏱ 1 daqiqa · 🍽 1 non uchun\n\n🧾 <b>Masalliqlar:</b>\n• 1 choy qoshiq butun sedana urug'i\n• 1 osh qoshiq suv yoki 1 ta tuxum sarig'i (ustiga surtish uchun)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Non yoki kraker xamirini qolipga solib, pishirishga tayyorlang.\n2. Ustini suv yoki tuxum sarig'i bilan yupqa surting — urug' yopishib turadi.\n3. Sedanani tekis sepib, kaft bilan yengil bosing.\n4. Retseptdagidek pishiring.\n\n💡 Pishganda achchiqroq, yong'oqsimon aromat beradi.",
             "ru": "<b>Чёрный тмин как посыпка для хлеба</b>\n⏱ 1 минута · 🍽 на 1 буханку\n\n🧾 <b>Ингредиенты:</b>\n• 1 ч. ложка цельных семян чёрного тмина\n• 1 ст. ложка воды или 1 желток (смазать верх)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Подготовьте тесто хлеба или крекеров к выпечке.\n2. Смажьте верх тонким слоем воды или желтка — так семена приклеятся.\n3. Равномерно посыпьте тмином и слегка прижмите ладонью.\n4. Выпекайте по рецепту.\n\n💡 При выпекании даёт пряно-ореховый аромат."},
        ],
    },
    {
        "key": "fiber_supp",
        "emoji": "💊",
        "match": ["psillium", "псилл", "sheluxa", "шелух", "ksantan", "xantan", "ксантан", "kamedi", "камед"],
        "name": {"uz": "Psillium va ksantan", "ru": "Псиллиум и ксантан"},
        "shop": "psillium",
        "benefits": [
            {"uz": "Psillium — glutensiz pishiriqning siri. U xamirni bog'laydi va nonga \"cho'ziluvchan\" tuzilma beradi, bo'lmasa u to'kilib ketadi.",
             "ru": "Псиллиум — секрет безглютеновой выпечки. Он связывает тесто и даёт хлебу «тянущуюся» структуру, без него он крошится."},
            {"uz": "Ksantan kamedi juda kam miqdorda ishlaydi: 1 kg xamirga 5-8g yetarli. Ko'p solsangiz taom sirpanchiq bo'lib qoladi.",
             "ru": "Ксантановая камедь работает в крошечных дозах: 5-8г на 1кг теста достаточно. Переборщите — блюдо станет склизким."},
            {"uz": "Psillium eruvchi tola sifatida ham ishlaydi — suv bilan ichilsa to'yimlilikni uzaytiradi va ichakni yumshoq tozalaydi.",
             "ru": "Псиллиум работает и как растворимая клетчатка — с водой продлевает сытость и мягко очищает кишечник."},
        ],
        "recipes": [
            {"uz": "<b>Psilliumli keto non</b>\n⏱ 60 daqiqa · 🍽 1 non (8 bo'lak)\n\n🧾 <b>Masalliqlar:</b>\n• 150 g bodom uni\n• 3 osh qoshiq psillium (qobig'i kukuni)\n• 4 ta tuxum oqi\n• 1 choy qoshiq soda\n• 1 osh qoshiq olma sirkasi\n• 200 ml qaynoq suv\n• 1/2 choy qoshiq tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Pechni 180°C ga qizdiring. Laganga pergament qog'oz to'shang.\n2. Idishda bodom uni, psillium, soda va tuzni aralashtiring.\n3. Tuxum oqi va olma sirkasini qo'shib, qoshiq bilan aralashtiring.\n4. Qaynoq suvni quyib, darhol 30 soniya tez aralashtiring — psillium tezda xamirni bog'laydi.\n5. Ho'l qo'l bilan 1 ta non (yoki 6 ta bulochka) shaklini bering va laganga qo'ying.\n6. 180°C da 50 daqiqa pishiring.\n7. Panjarada to'liq sovuting, keyin kesing — issiqligida ichi nam ko'rinadi.\n\n💡 Tuxum sarig'i qolsa, ertasi kuni omlet yoki krem uchun ishlating.",
             "ru": "<b>Кето-хлеб с псиллиумом</b>\n⏱ 60 минут · 🍽 1 буханка (8 ломтиков)\n\n🧾 <b>Ингредиенты:</b>\n• 150 г миндальной муки\n• 3 ст. ложки псиллиума (порошка шелухи)\n• 4 яичных белка\n• 1 ч. ложка соды\n• 1 ст. ложка яблочного уксуса\n• 200 мл кипятка\n• 1/2 ч. ложки соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Разогрейте духовку до 180°C. Застелите противень пергаментом.\n2. Смешайте в миске миндальную муку, псиллиум, соду и соль.\n3. Добавьте белки и уксус, перемешайте ложкой.\n4. Влейте кипяток и сразу быстро перемешайте 30 секунд — псиллиум мгновенно связывает тесто.\n5. Влажными руками сформуйте 1 буханку (или 6 булочек) и выложите на противень.\n6. Выпекайте 50 минут при 180°C.\n7. Полностью остудите на решётке, затем режьте — горячий хлеб внутри кажется сырым.\n\n💡 Оставшиеся желтки используйте на следующий день для омлета или крема."},
            {"uz": "<b>Ksantan bilan quyuq sous</b>\n⏱ 5 daqiqa · 🍽 250 ml sous\n\n🧾 <b>Masalliqlar:</b>\n• 250 ml bulon yoki qaymoq (issiq)\n• 1/4 choy qoshiq ksantan kamedi\n• 1 chimdim tuz\n• 1 chimdim qora murch\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Bulon yoki qaymoqni kichik qozonda qaynash arafasigacha isiting va olovni pasaytiring.\n2. Venchik bilan to'xtovsiz aralashtirib turib, ksantanni yuzaga juda SEKIN, chimdimlab seping — birdaniga solsangiz, bo'laklar bo'lib qoladi.\n3. 30 soniya qattiq urib turing.\n4. 1 daqiqa past olovda qoldiring — sous o'zi quyuqlashadi.\n5. Tuz va murch qo'shing. Go'sht, baliq yoki sabzavot bilan torting.\n\n💡 Quyuqroq kerak bo'lsa, yana bir chimdim qo'shing — lekin 1/2 choy qoshiqdan oshirmang, aks holda shilimshiq bo'ladi.",
             "ru": "<b>Густой соус на ксантане</b>\n⏱ 5 минут · 🍽 250 мл соуса\n\n🧾 <b>Ингредиенты:</b>\n• 250 мл бульона или сливок (горячих)\n• 1/4 ч. ложки ксантановой камеди\n• 1 щепотка соли\n• 1 щепотка чёрного перца\n\n👩‍🍳 <b>Приготовление:</b>\n1. Нагрейте бульон или сливки в сотейнике почти до кипения и убавьте огонь.\n2. Непрерывно взбивая венчиком, ОЧЕНЬ медленно, по щепотке, всыпайте ксантан на поверхность — если высыпать сразу, будут комки.\n3. Энергично взбивайте 30 секунд.\n4. Подержите 1 минуту на слабом огне — соус загустеет сам.\n5. Посолите, поперчите. Подавайте к мясу, рыбе или овощам.\n\n💡 Нужно гуще — добавьте ещё щепотку, но не больше 1/2 ч. ложки, иначе станет слизистым."},
        ],
    },
    {
        # Before cacao and oils: "Keto muzqaymoqlari (Shokolad kakao)" would
        # otherwise land on cacao, and "(Avokado + Banan)" on oils.
        "key": "keto_icecream",
        "emoji": "🍨",
        "match": ["muzqaymoq", "мороженое", "морожен", "ice cream", "plombir", "пломбир"],
        "name": {"uz": "Keto muzqaymoq", "ru": "Кето-мороженое"},
        "shop": "muzqaymoq",
        "benefits": [
            {"uz": "Keto muzqaymoq shakar o'rniga shirinlashtirgich bilan tayyorlanadi — shirinlik istagini qondiradi, lekin qondagi shakarni keskin ko'tarmaydi.",
             "ru": "Кето-мороженое готовится на подсластителе вместо сахара — утоляет тягу к сладкому, не вызывая резкого скачка сахара в крови."},
            {"uz": "Yog'li asos (qaymoq, kokos) muzqaymoqni to'yimli qiladi: bir porsiya yetadi, oddiy muzqaymoqdagidek \"yana bittasi\" istagi bo'lmaydi.",
             "ru": "Жирная основа (сливки, кокос) делает мороженое сытным: одной порции хватает, без привычного «ещё одно»."},
        ],
        "recipes": [
            {"uz": "<b>Muzqaymoqli keto affogato</b>\n⏱ 3 daqiqa · 🍽 1 kishilik\n\n🧾 <b>Masalliqlar:</b>\n• 1 porsiya (2 ta shar, taxminan 100 g) keto muzqaymoq\n• 50 ml issiq kuchli qahva (yoki 50 ml kuchli shakarsiz kakao)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Qahvani tayyorlang: 50 ml qaynoq suvga 1 choy qoshiq eruvchan qahva yoki 1 ta espresso.\n2. Muzqaymoqni stakan yoki kosaga soling.\n3. Ustidan issiq qahvani quying.\n4. Darhol, muzqaymoq erib ulgurmasdan qoshiq bilan yeng.\n\n💡 Kakao varianti: 1 osh qoshiq kakao + 50 ml qaynoq suv + 1 choy qoshiq eritritol.",
             "ru": "<b>Кето-аффогато с мороженым</b>\n⏱ 3 минуты · 🍽 1 порция\n\n🧾 <b>Ингредиенты:</b>\n• 1 порция (2 шарика, около 100 г) кето-мороженого\n• 50 мл горячего крепкого кофе (или 50 мл крепкого какао без сахара)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Приготовьте кофе: 1 ч. ложка растворимого на 50 мл кипятка или 1 эспрессо.\n2. Положите мороженое в стакан или пиалу.\n3. Залейте горячим кофе.\n4. Сразу ешьте ложкой, пока мороженое не растаяло.\n\n💡 Вариант с какао: 1 ст. ложка какао + 50 мл кипятка + 1 ч. ложка эритрита."},
            {"uz": "<b>Keto muzqaymoq-kosa</b>\n⏱ 5 daqiqa · 🍽 1 kishilik\n\n🧾 <b>Masalliqlar:</b>\n• 1 porsiya (100 g) keto muzqaymoq\n• 1 osh qoshiq yong'oq pastasi\n• 1 osh qoshiq kokos chipsi yoki 1 choy qoshiq kakao nibs\n• 1 hovuch (50 g) rezavor (malina, qulupnay)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Muzqaymoqni muzlatkichdan olib, 3–5 daqiqa xonada qoldiring — yumshaydi.\n2. Kosaga muzqaymoqni soling.\n3. Yong'oq pastasini mikroto'lqinli pechda 10 soniya isitib suyultiring va muzqaymoq ustidan quying.\n4. Kokos chipsi (yoki kakao nibs) va rezavorlarni sepib, darhol torting.",
             "ru": "<b>Кето-боул с мороженым</b>\n⏱ 5 минут · 🍽 1 порция\n\n🧾 <b>Ингредиенты:</b>\n• 1 порция (100 г) кето-мороженого\n• 1 ст. ложка ореховой пасты\n• 1 ст. ложка кокосовых чипсов или 1 ч. ложка какао-крупки\n• 1 горсть (50 г) ягод (малина, клубника)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Достаньте мороженое из морозилки за 3–5 минут — оно станет мягче.\n2. Выложите мороженое в пиалу.\n3. Подогрейте ореховую пасту 10 секунд в микроволновке, чтобы стала жидкой, и полейте мороженое.\n4. Посыпьте кокосовыми чипсами (или какао-крупкой) и ягодами, сразу подавайте."},
        ],
    },
    {
        "key": "cacao",
        "emoji": "🍫",
        # Pobeda bars are named without "shokolad" ("«Pobeda» 72% Dark gorkiy").
        "match": ["kakao", "cacao", "какао", "nibs", "shokolad", "шокола", "pobeda", "победа",
                  "gorkiy", "горьк", "dark"],
        "name": {"uz": "Shokolad va kakao", "ru": "Шоколад и какао"},
        "shop": "shokolad",
        "benefits": [
            {"uz": "Kakaosi 70% va undan yuqori qora shokolad — flavonoidlar, magniy va temirga boy. Shakarsiz turi keto ratsionda ham shirinlik istagini bemalol qondiradi.",
             "ru": "Тёмный шоколад от 70% какао богат флавоноидами, магнием и железом. Вариант без сахара спокойно закрывает тягу к сладкому и на кето."},
            {"uz": "Kakao foizi qancha yuqori bo'lsa, shakar shuncha kam. 100% shokoladda shakar umuman yo'q — achchiq ta'mga o'rgangan sari shirinlikka ehtiyoj kamayadi.",
             "ru": "Чем выше процент какао, тем меньше сахара. В 100% шоколаде сахара нет вовсе — чем больше привыкаете к горечи, тем меньше тянет на сладкое."},
            {"uz": "Kakao nibs — maydalangan kakao doni, shakarsiz. Flavonoidlarga boy va magniy bo'yicha eng kuchli mahsulotlardan biri.",
             "ru": "Какао-крупка — дроблёные какао-бобы без сахара. Богата флавоноидами и одна из сильнейших по магнию."},
            {"uz": "Xrustaydigan tuzilmasi shokolad krupkasini almashtiradi — puding, smuzi va pishiriqqa uglevodsiz \"shokolad\" beradi.",
             "ru": "Хрустящая текстура заменяет шоколадную крошку — даёт «шоколад» без углеводов в пудингах, смузи и выпечке."},
        ],
        "recipes": [
            {"uz": "<b>Shokoladli keto keks krujkada (mikroto'lqinli pechda)</b>\n⏱ 5 daqiqa · 🍽 1 kishilik\n\n🧾 <b>Masalliqlar:</b>\n• 3 osh qoshiq bodom uni (30 g)\n• 1 ta tuxum\n• 1 osh qoshiq sariyog' (eritilgan)\n• 1 osh qoshiq eritritol\n• 30 g shakarsiz qora shokolad granulasi\n• 1 chimdim pishirish kukuni\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. 300 ml li krujkaga bodom uni, eritritol va pishirish kukunini solib aralashtiring.\n2. Tuxum va eritilgan sariyog'ni qo'shib, vilka bilan bir xil bo'lguncha aralashtiring.\n3. Shokolad granulasining yarmini xamirga aralashtiring, qolgan yarmini ustiga seping.\n4. Mikroto'lqinli pechda to'liq quvvatda 70 soniya pishiring (keks krujka chetigacha ko'tariladi).\n5. 1 daqiqa sovusin va qoshiq bilan yeng — ichi erigan shokoladli bo'ladi.\n\n💡 Pech kuchsiz bo'lsa (700 W dan past), yana 10–15 soniya qo'shing.",
             "ru": "<b>Шоколадный кето-кекс в кружке (в микроволновке)</b>\n⏱ 5 минут · 🍽 1 порция\n\n🧾 <b>Ингредиенты:</b>\n• 3 ст. ложки миндальной муки (30 г)\n• 1 яйцо\n• 1 ст. ложка сливочного масла (растопленного)\n• 1 ст. ложка эритрита\n• 30 г гранул тёмного шоколада без сахара\n• 1 щепотка разрыхлителя\n\n👩‍🍳 <b>Приготовление:</b>\n1. В кружке на 300 мл смешайте миндальную муку, эритрит и разрыхлитель.\n2. Добавьте яйцо и растопленное масло, перемешайте вилкой до однородности.\n3. Половину шоколадных гранул вмешайте в тесто, вторую половину посыпьте сверху.\n4. Готовьте в микроволновке на полной мощности 70 секунд (кекс поднимется до края кружки).\n5. Дайте остыть 1 минуту и ешьте ложкой — внутри расплавленный шоколад.\n\n💡 Если микроволновка слабая (меньше 700 Вт), добавьте 10–15 секунд."},
            {"uz": "<b>Shokoladli kokos konfeti (3 masalliqdan)</b>\n⏱ 20 daqiqa (shundan 15 daqiqasi muzlatkichda) · 🍽 12 dona\n\n🧾 <b>Masalliqlar:</b>\n• 100 g qora shokolad (kakao 70% dan yuqori yoki shakarsiz)\n• 60 g kokos qirindisi\n• 1 chimdim tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Shokoladni bo'laklarga sindirib, kichik idishga soling.\n2. Idishni qaynab turgan suvli qozon ustiga qo'yib (suv hammomi), aralashtirib eriting — suv shokoladga tegmasin.\n3. Erigan shokoladga kokos qirindisi va tuzni qo'shib aralashtiring.\n4. Pergament qog'ozga choy qoshiq bilan 12 ta kichik uyum qilib tomizing.\n5. Muzlatkichda 15 daqiqa qotiring.\n6. Yopiq idishda muzlatkichda saqlang (1 haftagacha).",
             "ru": "<b>Шоколадно-кокосовые конфеты из 3 ингредиентов</b>\n⏱ 20 минут (из них 15 в холодильнике) · 🍽 12 штук\n\n🧾 <b>Ингредиенты:</b>\n• 100 г тёмного шоколада (какао от 70% или без сахара)\n• 60 г кокосовой стружки\n• 1 щепотка соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Разломайте шоколад на кусочки и сложите в небольшую миску.\n2. Поставьте миску на кастрюлю с кипящей водой (водяная баня) и растопите, помешивая, — вода не должна касаться шоколада.\n3. Вмешайте в шоколад кокосовую стружку и соль.\n4. Выложите чайной ложкой на пергамент 12 небольших горок.\n5. Уберите в холодильник на 15 минут.\n6. Храните в закрытом контейнере в холодильнике (до 1 недели)."},
            {"uz": "<b>Keto issiq shokolad</b>\n⏱ 10 daqiqa · 🍽 1 stakan (200 ml)\n\n🧾 <b>Masalliqlar:</b>\n• 200 ml kokos suti\n• 1 osh qoshiq kakao kukuni (shakarsiz)\n• 1–2 choy qoshiq eritritol (ta'mga qarab)\n• 1 chimdim tuz\n• 1/4 choy qoshiq dolchin\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Kichik qozonda kakao, eritritol, tuz va dolchinni aralashtiring.\n2. 3 osh qoshiq kokos sutini qo'shib, quyruqsiz pasta bo'lguncha aralashtiring.\n3. Qolgan sutni quyib, o'rtacha olovda aralashtirib turib isiting — qaynatmang.\n4. Issiq bo'lgach (2–3 daqiqa), venchik bilan 30 soniya urib ko'pik hosil qiling.\n5. Krujkaga quyib, issiq holda iching.\n\n💡 Kechqurun shirinlik ishtahasini bosadi.",
             "ru": "<b>Кето горячий шоколад</b>\n⏱ 10 минут · 🍽 1 чашка (200 мл)\n\n🧾 <b>Ингредиенты:</b>\n• 200 мл кокосового молока\n• 1 ст. ложка какао-порошка (без сахара)\n• 1–2 ч. ложки эритрита (по вкусу)\n• 1 щепотка соли\n• 1/4 ч. ложки корицы\n\n👩‍🍳 <b>Приготовление:</b>\n1. В сотейнике смешайте какао, эритрит, соль и корицу.\n2. Добавьте 3 ст. ложки кокосового молока и разотрите в пасту без комков.\n3. Влейте остальное молоко и нагревайте на среднем огне, помешивая, — не кипятите.\n4. Когда станет горячим (2–3 минуты), взбейте венчиком 30 секунд до пенки.\n5. Перелейте в кружку и пейте горячим.\n\n💡 Снимает вечернюю тягу к сладкому."},
            {"uz": "<b>Kakao nibsli keto shokolad plitkasi</b>\n⏱ 20 daqiqa (shundan 15 daqiqasi muzlatkichda) · 🍽 8 bo'lak\n\n🧾 <b>Masalliqlar:</b>\n• 100 g kokos yog'i\n• 3 osh qoshiq kakao kukuni (30 g)\n• 2 osh qoshiq kakao nibs\n• 2 osh qoshiq maydalangan eritritol\n• 1 chimdim tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Kokos yog'ini suv hammomida yoki mikroto'lqinli pechda 30 soniya eriting (qaynatmang).\n2. Kakao kukuni va eritritolni elab qo'shing, quyruqsiz bo'lguncha aralashtiring.\n3. Tuzni qo'shing va aralashtiring.\n4. Massani pergament to'shalgan kichik qolipga (taxminan 15×10 sm) 1 sm qalinlikda quying.\n5. Ustiga kakao nibsni tekis sepib, biroz bosing.\n6. Muzlatkichda 15 daqiqa qotiring va 8 bo'lakka sindiring.\n7. Faqat muzlatkichda saqlang — xona haroratida eriydi.",
             "ru": "<b>Кето-плитка с какао-крупкой</b>\n⏱ 20 минут (из них 15 в холодильнике) · 🍽 8 кусочков\n\n🧾 <b>Ингредиенты:</b>\n• 100 г кокосового масла\n• 3 ст. ложки какао-порошка (30 г)\n• 2 ст. ложки какао-крупки\n• 2 ст. ложки молотого эритрита\n• 1 щепотка соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Растопите кокосовое масло на водяной бане или 30 секунд в микроволновке (не кипятите).\n2. Просейте туда какао и эритрит, перемешайте без комков.\n3. Добавьте соль и перемешайте.\n4. Вылейте массу в небольшую форму с пергаментом (примерно 15×10 см) слоем 1 см.\n5. Равномерно посыпьте какао-крупкой и слегка прижмите.\n6. Уберите в холодильник на 15 минут и разломайте на 8 кусочков.\n7. Храните только в холодильнике — при комнатной температуре тает."},
        ],
    },
    {
        "key": "fish",
        "emoji": "🐟",
        "match": ["losos", "лосос", "baliq", "рыб", "tushonka", "тушёнк", "tushyonka"],
        "name": {"uz": "Baliq mahsulotlari", "ru": "Рыбные продукты"},
        "shop": "losos",
        "benefits": [
            {"uz": "Losos — omega-3 (EPA va DHA) ning eng yaxshi manbai. Bu shakllar o'simlik omega-3 sidan farqli, organizm tomonidan to'g'ridan-to'g'ri ishlatiladi.",
             "ru": "Лосось — лучший источник омега-3 (EPA и DHA). В отличие от растительных, эти формы используются организмом напрямую."},
            {"uz": "Tushonka shaklida D vitamini va oqsil saqlanadi — sovuq oylarda tayyor, uzoq saqlanadigan oqsil manbai.",
             "ru": "В виде тушёнки сохраняются витамин D и белок — готовый источник белка с долгим сроком хранения на холодные месяцы."},
        ],
        "recipes": [
            {"uz": "<b>Losos salati (5 daqiqada)</b>\n⏱ 5 daqiqa · 🍽 2 kishilik\n\n🧾 <b>Masalliqlar:</b>\n• 1 banka (taxminan 240 g) losos tushonkasi\n• 1 ta avokado\n• 1 ta bodring\n• 1 osh qoshiq zaytun yog'i\n• 1 osh qoshiq limon sharbati (yarim limon)\n• 1 chimdim tuz\n• 1 chimdim qora murch\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Bankani ochib, suyuqligini to'king va baliqni idishga solib vilka bilan yirik bo'laklarga ajrating.\n2. Avokadoni ikkiga bo'lib, danagini olib tashlang, qoshiq bilan chiqarib 1 sm kubik qiling.\n3. Bodringni 1 sm kubik qilib to'g'rang.\n4. Baliq, avokado va bodringni aralashtiring.\n5. Zaytun yog'i, limon sharbati, tuz va murchni qo'shib, ehtiyotkorlik bilan aralashtiring va darhol torting.\n\n💡 Avokado qorayib qolmasligi uchun limon sharbatini birinchi unga quying.",
             "ru": "<b>Салат с лососем за 5 минут</b>\n⏱ 5 минут · 🍽 2 порции\n\n🧾 <b>Ингредиенты:</b>\n• 1 банка (около 240 г) консервированного лосося\n• 1 авокадо\n• 1 огурец\n• 1 ст. ложка оливкового масла\n• 1 ст. ложка лимонного сока (половина лимона)\n• 1 щепотка соли\n• 1 щепотка чёрного перца\n\n👩‍🍳 <b>Приготовление:</b>\n1. Откройте банку, слейте жидкость, переложите рыбу в миску и разберите вилкой на крупные кусочки.\n2. Разрежьте авокадо пополам, удалите косточку, достаньте мякоть ложкой и нарежьте кубиком 1 см.\n3. Нарежьте огурец кубиком 1 см.\n4. Смешайте рыбу, авокадо и огурец.\n5. Добавьте масло, лимонный сок, соль и перец, аккуратно перемешайте и сразу подавайте.\n\n💡 Чтобы авокадо не потемнело, сначала полейте его лимонным соком."},
            {"uz": "<b>Losos kotletlari (unsiz)</b>\n⏱ 20 daqiqa · 🍽 6 dona\n\n🧾 <b>Masalliqlar:</b>\n• 1 banka (taxminan 240 g) losos tushonkasi\n• 1 ta tuxum\n• 2 osh qoshiq psillium yoki zig'ir uni\n• 1/2 ta kichik piyoz\n• 2 osh qoshiq mayda to'g'ralgan ko'kat (shivit yoki petrushka)\n• 1 chimdim tuz\n• 2 osh qoshiq yog' (qovurish uchun)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Baliq suyuqligini to'kib, idishda vilka bilan ezing.\n2. Piyozni juda mayda to'g'rang.\n3. Baliqqa tuxum, psillium (yoki zig'ir uni), piyoz, ko'kat va tuzni qo'shib aralashtiring.\n4. 10 daqiqa qo'yib qo'ying — psillium massani bog'laydi.\n5. Ho'l qo'l bilan 6 ta kotlet yasang (2 sm qalinlikda).\n6. Tovada yog'ni o'rtacha olovda qizdirib, kotletlarni har tomonini 3 daqiqadan, qizarguncha qovuring.\n\n💡 Yashil salat yoki yogurt-sarimsoq sousi bilan mazali.",
             "ru": "<b>Котлеты из лосося без муки</b>\n⏱ 20 минут · 🍽 6 штук\n\n🧾 <b>Ингредиенты:</b>\n• 1 банка (около 240 г) консервированного лосося\n• 1 яйцо\n• 2 ст. ложки псиллиума или льняной муки\n• 1/2 небольшой луковицы\n• 2 ст. ложки мелко рубленной зелени (укроп или петрушка)\n• 1 щепотка соли\n• 2 ст. ложки масла (для жарки)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Слейте жидкость и разомните рыбу вилкой в миске.\n2. Очень мелко нарежьте лук.\n3. Добавьте к рыбе яйцо, псиллиум (или льняную муку), лук, зелень и соль, перемешайте.\n4. Оставьте на 10 минут — псиллиум свяжет массу.\n5. Влажными руками сформуйте 6 котлет толщиной 2 см.\n6. Разогрейте масло на среднем огне и обжарьте котлеты по 3 минуты с каждой стороны до румяности.\n\n💡 Вкусно с зелёным салатом или соусом из йогурта с чесноком."},
        ],
    },
    {
        "key": "oils",
        "emoji": "🫒",
        # "saryog"/"sariyog" spelled out because plain "yog" would swallow
        # "yogurt"; the apostrophe-less spellings are common in the catalog.
        "match": ["yog'", "yog ", "saryog", "sariyog", "moy", "масло", "oil",
                  "avokado", "zaytun", "olive", "ghee", "гхи"],
        "name": {"uz": "Sog'lom yog'lar", "ru": "Полезные масла"},
        "shop": "yog'",
        "benefits": [
            {"uz": "Sifatli yog'lar — keto ratsionining asosi. Ular yog'da eruvchi vitaminlarni (A, D, E, K) o'zlashtirishga yordam beradi; ularsiz sabzavotdan foyda yarmiga tushadi.",
             "ru": "Качественные жиры — основа кето-рациона. Они помогают усваивать жирорастворимые витамины (A, D, E, K); без них польза овощей вдвое меньше."},
            {"uz": "Sovuq bosim zaytun yog'i salatlar uchun; kokos yog'i va GHEE esa yuqori haroratga chidamli — qovurish uchun aynan shularni tanlang.",
             "ru": "Оливковое холодного отжима — для салатов; кокосовое масло и ГХИ выдерживают высокую температуру — именно их берите для жарки."},
            {"uz": "GHEE — sutdan tozalangan sariyog': laktoza va kazein deyarli yo'q, shuning uchun sutni ko'tarmaydiganlar ham iste'mol qila oladi.",
             "ru": "ГХИ — топлёное масло без молочных белков: лактозы и казеина почти нет, поэтому подходит и при непереносимости молока."},
        ],
        "recipes": [
            {"uz": "<b>Keto salat sousi</b>\n⏱ 3 daqiqa · 🍽 4 kishilik salatga (80 ml)\n\n🧾 <b>Masalliqlar:</b>\n• 3 osh qoshiq zaytun yog'i\n• 1 osh qoshiq olma sirkasi\n• 1 choy qoshiq xantal (gorchitsa)\n• 1/4 choy qoshiq tuz\n• 1 chimdim qora murch\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Barcha masalliqlarni qopqoqli kichik bankaga soling.\n2. Qopqoqni yopib, 20–30 soniya qattiq chayqating — sous oqarib, quyuqlashadi (emulsiya).\n3. Salatga torting oldidan quying va aralashtiring.\n\n💡 Muzlatkichda 1 haftagacha turadi; ishlatishdan oldin yana chayqating.",
             "ru": "<b>Кето-заправка для салата</b>\n⏱ 3 минуты · 🍽 на салат для 4 человек (80 мл)\n\n🧾 <b>Ингредиенты:</b>\n• 3 ст. ложки оливкового масла\n• 1 ст. ложка яблочного уксуса\n• 1 ч. ложка горчицы\n• 1/4 ч. ложки соли\n• 1 щепотка чёрного перца\n\n👩‍🍳 <b>Приготовление:</b>\n1. Сложите все ингредиенты в небольшую банку с крышкой.\n2. Закройте и энергично встряхивайте 20–30 секунд — заправка посветлеет и загустеет (эмульсия).\n3. Полейте салат перед подачей и перемешайте.\n\n💡 В холодильнике хранится до 1 недели; перед использованием снова встряхните."},
            {"uz": "<b>Eritilgan sariyog'da (gxi) tuxum va avokado</b>\n⏱ 8 daqiqa · 🍽 1 kishilik\n\n🧾 <b>Masalliqlar:</b>\n• 1 osh qoshiq eritilgan sariyog' (gxi)\n• 2 ta tuxum\n• 1/2 ta avokado\n• 1 chimdim Himalay tuzi\n• 1 chimdim qora murch (ixtiyoriy)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Tovada eritilgan sariyog'ni o'rtacha olovda 1 daqiqa qizdiring.\n2. Tuxumni chaqib, tovaga ehtiyotkorlik bilan soling va olovni pasaytiring.\n3. Tuxum oqi butunlay oqarib, sarig'i suyuq qolguncha 3–4 daqiqa pishiring (qattiq sevsangiz — qopqoq ostida yana 2 daqiqa).\n4. Shu vaqtda avokadoni po'stidan tozalab, yupqa bo'laklarga kesing.\n5. Tuxum va avokadoni tarelkaga solib, tuz va murch seping.\n\n💡 To'yimli keto nonushta — tushgacha ochiqmaysiz.",
             "ru": "<b>Яйца на топлёном масле (гхи) с авокадо</b>\n⏱ 8 минут · 🍽 1 порция\n\n🧾 <b>Ингредиенты:</b>\n• 1 ст. ложка топлёного масла (гхи)\n• 2 яйца\n• 1/2 авокадо\n• 1 щепотка гималайской соли\n• 1 щепотка чёрного перца (по желанию)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Разогрейте топлёное масло на сковороде на среднем огне 1 минуту.\n2. Аккуратно разбейте яйца на сковороду и убавьте огонь.\n3. Жарьте 3–4 минуты, пока белок полностью не побелеет, а желток останется жидким (любите твёрдый — ещё 2 минуты под крышкой).\n4. Тем временем очистите авокадо и нарежьте тонкими ломтиками.\n5. Выложите яйца и авокадо на тарелку, посолите и поперчите.\n\n💡 Сытный кето-завтрак — до обеда не проголодаетесь."},
        ],
    },
    {
        "key": "vinegar",
        "emoji": "🍎",
        "match": ["sirka", "uksus", "уксус", "vinegar"],
        "name": {"uz": "Olma sirkasi", "ru": "Яблочный уксус"},
        "shop": "sirka",
        "benefits": [
            {"uz": "Ovqatdan oldin bir choy qoshiq olma sirkasi (bir stakan suvda) qondagi shakarning keskin ko'tarilishini yumshatishga yordam beradi.",
             "ru": "Чайная ложка яблочного уксуса в стакане воды перед едой помогает смягчить резкий подъём сахара в крови."},
            {"uz": "Ishtahani muvozanatlaydi va hazmni qo'llab-quvvatlaydi. Doim suv bilan suyultiring — sof holda tish emalini shikastlaydi.",
             "ru": "Балансирует аппетит и поддерживает пищеварение. Всегда разбавляйте водой — в чистом виде вредит эмали зубов."},
        ],
        "recipes": [
            {"uz": "<b>Ertalabki tetiklashtiruvchi ichimlik</b>\n⏱ 2 daqiqa · 🍽 1 stakan\n\n🧾 <b>Masalliqlar:</b>\n• 250 ml iliq suv\n• 1 choy qoshiq olma sirkasi (5%)\n• 1 chimdim Himalay tuzi\n• 1/2 choy qoshiq eritritol (ixtiyoriy, nordonlikni yumshatadi)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Stakanga iliq suv quying.\n2. Olma sirkasi, tuz va (xohlasangiz) eritritolni qo'shib aralashtiring.\n3. Nonushtadan 15 daqiqa oldin, naycha orqali iching — tish emaliga yumshoqroq.\n4. Ichgandan keyin og'izni oddiy suv bilan chaying.\n\n💡 Oshqozon yarasi yoki gastrit bo'lsa, sirkali ichimlikni ichmang.",
             "ru": "<b>Утренний бодрящий напиток</b>\n⏱ 2 минуты · 🍽 1 стакан\n\n🧾 <b>Ингредиенты:</b>\n• 250 мл тёплой воды\n• 1 ч. ложка яблочного уксуса (5%)\n• 1 щепотка гималайской соли\n• 1/2 ч. ложки эритрита (по желанию, смягчает кислоту)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Налейте в стакан тёплую воду.\n2. Добавьте уксус, соль и (по желанию) эритрит, перемешайте.\n3. Выпейте за 15 минут до завтрака через трубочку — бережнее для эмали зубов.\n4. После этого прополощите рот простой водой.\n\n💡 При язве или гастрите напиток с уксусом пить не стоит."},
            {"uz": "<b>Tezkor marinadlangan sabzavot</b>\n⏱ 10 daqiqa + 30 daqiqa kutish · 🍽 1 banka (500 ml)\n\n🧾 <b>Masalliqlar:</b>\n• 300 g sabzavot: bodring, karam yoki piyoz (bittasi yoki aralash)\n• 100 ml suv\n• 3 osh qoshiq olma sirkasi\n• 1 choy qoshiq tuz\n• 1 choy qoshiq eritritol\n• 5–6 dona qora murch (no'xatcha)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Sabzavotni yupqa qilib to'g'rang: bodringni doira, karamni somoncha, piyozni yarim halqa.\n2. Kichik qozonda suv, sirka, tuz, eritritol va murchni qaynating va olovdan oling.\n3. Sabzavotni bankaga zich joylab, ustidan issiq marinadni quying.\n4. Qopqoqni yopib, 30 daqiqa qo'yib qo'ying (yoki muzlatkichda 2 soat).\n5. Yog'li go'sht va palov bilan garnir sifatida torting.\n\n💡 Muzlatkichda 5 kungacha saqlanadi.",
             "ru": "<b>Быстрые маринованные овощи</b>\n⏱ 10 минут + 30 минут ожидания · 🍽 1 банка (500 мл)\n\n🧾 <b>Ингредиенты:</b>\n• 300 г овощей: огурцы, капуста или лук (один вид или ассорти)\n• 100 мл воды\n• 3 ст. ложки яблочного уксуса\n• 1 ч. ложка соли\n• 1 ч. ложка эритрита\n• 5–6 горошин чёрного перца\n\n👩‍🍳 <b>Приготовление:</b>\n1. Тонко нарежьте овощи: огурцы кружками, капусту соломкой, лук полукольцами.\n2. В сотейнике доведите до кипения воду, уксус, соль, эритрит и перец, снимите с огня.\n3. Плотно уложите овощи в банку и залейте горячим маринадом.\n4. Закройте и оставьте на 30 минут (или на 2 часа в холодильнике).\n5. Подавайте как гарнир к жирному мясу и плову.\n\n💡 В холодильнике хранится до 5 дней."},
        ],
    },
    {
        "key": "salt",
        "emoji": "🧂",
        "match": ["tuz", "соль", "sol ", "himalay", "гималай", "salt"],
        "name": {"uz": "Himalay tuzi", "ru": "Гималайская соль"},
        "shop": "tuz",
        "benefits": [
            {"uz": "Keto davrida organizm ko'proq natriy yo'qotadi. Himalay tuzi elektrolit muvozanatini tiklaydi va \"keto grip\" (holsizlik, bosh og'rig'i) ni kamaytiradi.",
             "ru": "На кето организм теряет больше натрия. Гималайская соль восстанавливает баланс электролитов и снижает «кето-грипп» (слабость, головную боль)."},
            {"uz": "Tarkibida 80 dan ortiq mineral bor — oddiy tuzga qaraganda tabiiyroq va boy ta'mli, shuning uchun kamroq miqdor yetadi.",
             "ru": "Содержит более 80 минералов — натуральнее и богаче по вкусу обычной, поэтому её нужно меньше."},
        ],
        "recipes": [
            {"uz": "<b>Uy elektrolit ichimligi</b>\n⏱ 3 daqiqa · 🍽 500 ml\n\n🧾 <b>Masalliqlar:</b>\n• 500 ml suv (xona haroratida)\n• 1/4 choy qoshiq Himalay tuzi\n• Yarim limon sharbati (taxminan 2 osh qoshiq)\n• 1 choy qoshiq eritritol (ixtiyoriy)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Butilka yoki bankaga suv quying.\n2. Tuz, limon sharbati va eritritolni qo'shing.\n3. Qopqoqni yopib, tuz erib ketguncha 20 soniya chayqating.\n4. Kun davomida ho'plab-ho'plab iching (birdaniga emas).\n\n💡 Ayniqsa keto boshida, sport va issiq kunlarda foydali. Yuqori qon bosimi bo'lsa, tuz miqdorini shifokor bilan kelishing.",
             "ru": "<b>Домашний электролитный напиток</b>\n⏱ 3 минуты · 🍽 500 мл\n\n🧾 <b>Ингредиенты:</b>\n• 500 мл воды (комнатной температуры)\n• 1/4 ч. ложки гималайской соли\n• Сок половины лимона (около 2 ст. ложек)\n• 1 ч. ложка эритрита (по желанию)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Налейте воду в бутылку или банку.\n2. Добавьте соль, лимонный сок и эритрит.\n3. Закройте и встряхивайте 20 секунд, пока соль не растворится.\n4. Пейте небольшими глотками в течение дня (не залпом).\n\n💡 Особенно полезно в начале кето, при спорте и в жару. При повышенном давлении количество соли согласуйте с врачом."},
            {"uz": "<b>Tuzli karamel ta'mi siri</b>\n⏱ 10 soniya · 🍽 har qanday shirinlikka\n\n🧾 <b>Masalliqlar:</b>\n• 1 chimdim (taxminan 1/8 choy qoshiq) Himalay tuzi — 1 ta shokolad plitka, keks yoki 2 porsiya puding uchun\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Keto shirinligingizni (shokolad, keks, puding, krem) retsept bo'yicha tayyorlang.\n2. Shokolad va konfetlar uchun: qotishidan oldin ustiga bir chimdim dag'al tuz seping.\n3. Keks va pudinglar uchun: tuzni xamirga yoki massaga boshqa masalliqlar bilan birga qo'shing.\n4. Tatib ko'ring — shirinlik ta'mi kuchliroq va chuqurroq bo'ladi, sho'rlik sezilmaydi.\n\n💡 Bir chimdimdan oshirmang — maqsad sho'r qilish emas, shirinlikni ochish.",
             "ru": "<b>Секрет вкуса солёной карамели</b>\n⏱ 10 секунд · 🍽 к любому десерту\n\n🧾 <b>Ингредиенты:</b>\n• 1 щепотка (около 1/8 ч. ложки) гималайской соли — на 1 плитку шоколада, кекс или 2 порции пудинга\n\n👩‍🍳 <b>Приготовление:</b>\n1. Приготовьте кето-десерт по рецепту (шоколад, кекс, пудинг, крем).\n2. Для шоколада и конфет: перед застыванием посыпьте сверху щепоткой крупной соли.\n3. Для кексов и пудингов: добавьте соль в тесто или массу вместе с остальными ингредиентами.\n4. Попробуйте — сладость станет ярче и глубже, а солёности не будет чувствоваться.\n\n💡 Не больше щепотки — цель не посолить, а раскрыть сладость."},
        ],
    },
    {
        "key": "sweeteners",
        "emoji": "🍬",
        "match": ["eritritol", "eritrtitol", "эритрит", "stevia", "steviya", "стеви", "alluloz", "аллюлоз",
                  "shirin", "podslast", "подсласт", "sweeten"],
        "name": {"uz": "Shirinlashtirgichlar", "ru": "Подсластители"},
        "shop": "eritritol",
        "benefits": [
            {"uz": "Eritritol va steviya deyarli 0 kaloriyali va qondagi shakarni ko'tarmaydi — shirinlikni yeb, ketozdan chiqmaysiz.",
             "ru": "Эритрит и стевия почти без калорий и не поднимают сахар — можно сладкое, не выходя из кетоза."},
            {"uz": "Alluloza pishiriqda shakarga eng yaqin: karamellashadi va eritritolga xos \"sovuq\" ta'm bermaydi. Shirinligi shakarning ~70% i.",
             "ru": "Аллюлоза ближе всех к сахару в выпечке: карамелизуется и не даёт «холодящего» привкуса эритрита. Сладость ~70% от сахара."},
            {"uz": "Steviya juda konsentrlangan — 1g steviya ~10 osh qoshiq shakarga teng. Ozdan boshlang, ko'p solsangiz achchiq ta'm beradi.",
             "ru": "Стевия очень концентрирована — 1г ≈ 10 ст.л. сахара. Начинайте с малого, переборщите — появится горечь."},
        ],
        "recipes": [
            {"uz": "<b>Shakarsiz karamel sousi</b>\n⏱ 10 daqiqa · 🍽 1 kichik banka (150 ml)\n\n🧾 <b>Masalliqlar:</b>\n• 80 g alluloza\n• 40 g sariyog'\n• 60 ml qaymoq (20–33%, xona haroratida)\n• 1 chimdim tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Qalin tubli kichik qozonga allulozani soling va past olovda qo'ying.\n2. Aralashtirmasdan, qozonni ohista aylantirib, alluloza erib och jigarrang (asal rangi) bo'lguncha 4–5 daqiqa kuting.\n3. Olovdan olib, sariyog'ni qo'shing va venchik bilan aralashtiring (ko'piklanadi — ehtiyot bo'ling).\n4. Qaymoqni asta-sekin quyib, silliq bo'lguncha aralashtiring.\n5. Tuz qo'shing. Sovigach quyuqlashadi — bankaga solib muzlatkichda saqlang (1 haftagacha).\n\n💡 Eritritol bu yerda ishlamaydi — u karamellashmaydi, faqat alluloza.",
             "ru": "<b>Карамельный соус без сахара</b>\n⏱ 10 минут · 🍽 1 баночка (150 мл)\n\n🧾 <b>Ингредиенты:</b>\n• 80 г аллюлозы\n• 40 г сливочного масла\n• 60 мл сливок (20–33%, комнатной температуры)\n• 1 щепотка соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Насыпьте аллюлозу в небольшой сотейник с толстым дном и поставьте на слабый огонь.\n2. Не перемешивая, а лишь покачивая сотейник, дождитесь, пока аллюлоза растает и станет светло-янтарной (цвета мёда), 4–5 минут.\n3. Снимите с огня, добавьте масло и перемешайте венчиком (вспенится — осторожно).\n4. Постепенно влейте сливки и мешайте до гладкости.\n5. Посолите. Остывая, соус загустеет — переложите в баночку и храните в холодильнике (до 1 недели).\n\n💡 Эритрит здесь не подойдёт — он не карамелизуется, только аллюлоза."},
            {"uz": "<b>Shirin qaymoq krem</b>\n⏱ 5 daqiqa · 🍽 4 kishilik (400 ml krem)\n\n🧾 <b>Masalliqlar:</b>\n• 200 ml qaymoq (33–35%, muzlatkichdan yangi chiqqan)\n• 2 osh qoshiq eritritol (kofe maydalagichda unga aylantirilgan)\n• 1 chimdim vanilin\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Mikser idishi va venchiklarni muzlatkichda 10 daqiqa sovuting.\n2. Sovuq qaymoqni idishga quying.\n3. Mikser bilan o'rta tezlikda 1 daqiqa, keyin maydalangan eritritol va vanilinni qo'shib yuqori tezlikda uring.\n4. 3–4 daqiqada qaymoq qalin, qattiq «cho'qqi» hosil qiladi — shu yerda to'xtating, aks holda sariyog'ga aylanadi.\n5. Keks, rezavor yoki kakao bilan torting.\n\n💡 Eritritol albatta maydalangan bo'lsin, aks holda tishda g'ijirlaydi.",
             "ru": "<b>Сладкий сливочный крем</b>\n⏱ 5 минут · 🍽 4 порции (400 мл крема)\n\n🧾 <b>Ингредиенты:</b>\n• 200 мл сливок (33–35%, только из холодильника)\n• 2 ст. ложки эритрита (смолотого в кофемолке в пудру)\n• 1 щепотка ванилина\n\n👩‍🍳 <b>Приготовление:</b>\n1. Охладите чашу и венчики миксера в холодильнике 10 минут.\n2. Налейте в чашу холодные сливки.\n3. Взбивайте миксером на средней скорости 1 минуту, затем добавьте молотый эритрит и ванилин и взбивайте на высокой.\n4. Через 3–4 минуты сливки дадут плотные устойчивые пики — остановитесь, иначе получится масло.\n5. Подавайте с кексом, ягодами или какао.\n\n💡 Эритрит обязательно молотый, иначе будет хрустеть на зубах."},
        ],
    },
    {
        "key": "honey",
        "emoji": "🍯",
        "match": ["asal", "мёд", "мед ", "med ", "honey"],
        "name": {"uz": "Tabiiy asal", "ru": "Натуральный мёд"},
        "shop": "asal",
        "benefits": [
            {"uz": "Tog' asali antioksidant va mineralga boy. Keto rejimida oz miqdorda, oddiy shakar o'rnida ishlatilsa — ancha foydaliroq tanlov.",
             "ru": "Горный мёд богат антиоксидантами и минералами. На кето — в небольшом количестве как замена обычному сахару, выбор намного лучше."},
            {"uz": "Asalni 40°C dan yuqori qizdirmang — foydali fermentlari parchalanadi. Choyni bir oz sovutib, keyin qo'shing.",
             "ru": "Не нагревайте мёд выше 40°C — полезные ферменты разрушаются. Дайте чаю чуть остыть, потом добавляйте."},
        ],
        "recipes": [
            {"uz": "<b>Tomoq uchun iliq ichimlik</b>\n⏱ 5 daqiqa · 🍽 1 krujka (250 ml)\n\n🧾 <b>Masalliqlar:</b>\n• 250 ml suv\n• 1 choy qoshiq asal\n• Yarim limon (sharbati, taxminan 2 osh qoshiq)\n• 1 sm bo'lak yangi zanjabil (yoki 1/4 choy qoshiq quruq zanjabil)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Zanjabilni yupqa doira qilib kesing.\n2. Suvni qaynatib, zanjabilni soling va 3 daqiqa damlang.\n3. Krujkaga quyib, 3–5 daqiqa iliq holatgacha (taxminan 50°C) soviting.\n4. Limon sharbati va asalni qo'shib aralashtiring.\n5. Kichik ho'plab, iliq holda iching.\n\n💡 Asalni qaynoq suvga solmang — foydali xususiyati yo'qoladi.",
             "ru": "<b>Тёплый напиток для горла</b>\n⏱ 5 минут · 🍽 1 кружка (250 мл)\n\n🧾 <b>Ингредиенты:</b>\n• 250 мл воды\n• 1 ч. ложка мёда\n• Половина лимона (сок, около 2 ст. ложек)\n• Кусочек свежего имбиря 1 см (или 1/4 ч. ложки сушёного)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Нарежьте имбирь тонкими кружочками.\n2. Вскипятите воду, добавьте имбирь и настаивайте 3 минуты.\n3. Перелейте в кружку и остудите 3–5 минут до тёплого (около 50°C).\n4. Добавьте лимонный сок и мёд, перемешайте.\n5. Пейте тёплым, небольшими глотками.\n\n💡 Не кладите мёд в кипяток — полезные свойства теряются."},
            {"uz": "<b>Asalli yong'oq aralashmasi</b>\n⏱ 10 daqiqa · 🍽 1 banka (250 g)\n\n🧾 <b>Masalliqlar:</b>\n• 200 g turli mag'iz (yong'oq, bodom, funduk)\n• 4 osh qoshiq asal (suyuq)\n• 1 choy qoshiq dolchin\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Mag'izni quruq tovada 4–5 daqiqa, aralashtirib qizdiring va sovuting.\n2. Pichoq bilan yirik bo'laklarga to'g'rang.\n3. Idishda mag'iz, asal va dolchinni aralashtiring.\n4. Toza, quruq bankaga zich solib, qopqog'ini yoping.\n5. Ertalab 1 osh qoshiqdan yeng — bo'tqa yoki yogurtga ham qo'shsa bo'ladi.\n\n💡 Xona haroratida 1 oygacha saqlanadi.",
             "ru": "<b>Ореховая смесь с мёдом</b>\n⏱ 10 минут · 🍽 1 банка (250 г)\n\n🧾 <b>Ингредиенты:</b>\n• 200 г разных орехов (грецкие, миндаль, фундук)\n• 4 ст. ложки мёда (жидкого)\n• 1 ч. ложка корицы\n\n👩‍🍳 <b>Приготовление:</b>\n1. Прогрейте орехи на сухой сковороде 4–5 минут, помешивая, и остудите.\n2. Крупно порубите ножом.\n3. Смешайте в миске орехи, мёд и корицу.\n4. Плотно переложите в чистую сухую банку и закройте крышкой.\n5. Ешьте по 1 ст. ложке утром — можно добавлять в кашу или йогурт.\n\n💡 При комнатной температуре хранится до 1 месяца."},
        ],
    },
    {
        "key": "spices",
        "emoji": "🌾",
        "match": ["arpabodiyon", "fenxel", "фенхел", "ziravor", "специ", "koriandr", "кориандр", "zanjabil", "имбир",
                  "koritsa", "корица", "dolchin", "долчин", "cinnamon", "darchin"],
        "name": {"uz": "Ziravorlar", "ru": "Специи"},
        "shop": "arpabodiyon",
        "benefits": [
            {"uz": "Arpabodiyon (fenxel) urug'i ovqatdan keyin shishishni kamaytiradi va hazmni yengillashtiradi — shuning uchun ko'p oshxonalarda ovqatdan keyin chaynaladi.",
             "ru": "Семена фенхеля уменьшают вздутие после еды и облегчают пищеварение — во многих кухнях их жуют после обеда."},
            {"uz": "Ziravorlar taomga tuzsiz ham ta'm beradi — tuzni kamaytirmoqchi bo'lsangiz eng oson yo'l.",
             "ru": "Специи придают вкус и без соли — самый простой способ сократить её количество."},
        ],
        "recipes": [
            {"uz": "<b>Arpabodiyon (fenxel) choyi</b>\n⏱ 10 daqiqa · 🍽 1 krujka\n\n🧾 <b>Masalliqlar:</b>\n• 1 choy qoshiq arpabodiyon (fenxel) urug'i\n• 250 ml qaynoq suv\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Urug'ni ohakda yoki qoshiqning orqasi bilan yengil ezing — aromati ochiladi.\n2. Krujkaga solib, ustiga qaynoq suv quying.\n3. Likopcha bilan yopib, 7 daqiqa damlang.\n4. Suzib, iliq holda kechki ovqatdan keyin iching.\n\n💡 Ovqat hazmiga yordam beradi va qorindagi og'irlikni kamaytiradi.",
             "ru": "<b>Фенхелевый чай</b>\n⏱ 10 минут · 🍽 1 кружка\n\n🧾 <b>Ингредиенты:</b>\n• 1 ч. ложка семян фенхеля\n• 250 мл кипятка\n\n👩‍🍳 <b>Приготовление:</b>\n1. Слегка раздавите семена в ступке или тыльной стороной ложки — раскроется аромат.\n2. Положите в кружку и залейте кипятком.\n3. Накройте блюдцем и настаивайте 7 минут.\n4. Процедите и пейте тёплым после ужина.\n\n💡 Помогает пищеварению и уменьшает тяжесть в животе."},
            {"uz": "<b>Uy ziravor aralashmasi</b>\n⏱ 5 daqiqa · 🍽 1 kichik banka (4 osh qoshiq)\n\n🧾 <b>Masalliqlar:</b>\n• 1 osh qoshiq arpabodiyon (fenxel) urug'i\n• 1 osh qoshiq koriandr urug'i\n• 1 osh qoshiq zira\n• 1 osh qoshiq qora murch (no'xatcha)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Barcha urug'larni quruq tovaga soling.\n2. O'rtacha olovda 2 daqiqa, to'xtovsiz aralashtirib, xushbo'y hid chiqquncha qizdiring (kuydirmang).\n3. Tekis idishga olib, 5 daqiqa soviting.\n4. Kofe maydalagich yoki ohakda maydalang.\n5. Yopiq bankada saqlang; go'sht, sabzavot va tuxumga 1/2 choy qoshiqdan seping.\n\n💡 3 oygacha aromatini yo'qotmaydi.",
             "ru": "<b>Домашняя смесь специй</b>\n⏱ 5 минут · 🍽 1 баночка (4 ст. ложки)\n\n🧾 <b>Ингредиенты:</b>\n• 1 ст. ложка семян фенхеля\n• 1 ст. ложка семян кориандра\n• 1 ст. ложка зиры\n• 1 ст. ложка чёрного перца горошком\n\n👩‍🍳 <b>Приготовление:</b>\n1. Насыпьте все семена на сухую сковороду.\n2. Прогревайте на среднем огне 2 минуты, постоянно помешивая, до аромата (не сожгите).\n3. Переложите на тарелку и остудите 5 минут.\n4. Смелите в кофемолке или ступке.\n5. Храните в закрытой баночке; посыпайте мясо, овощи и яйца по 1/2 ч. ложки.\n\n💡 Аромат сохраняется до 3 месяцев."},
        ],
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# CATEGORY fallbacks (2026-09-17).
#
# The catalogue grows through the admin panel, so a product can appear whose
# name no profile above recognises ("Makadamiya uni", "Koritsa 70g"). Rather
# than drop it to the generic "healthy products" note, personal_recommend
# looks up the product's shop category and uses the profile below. Every one of
# the 15 categories in locales.CATEGORIES resolves to something specific; the
# name match above still wins whenever it hits, since it's more precise.
#
# These generic profiles are NOT in PROFILES on purpose — they have no name
# keywords and must never out-rank a real name match.
# ─────────────────────────────────────────────────────────────────────────────
CATEGORY_GENERIC_PROFILES = {
    "keto_flour": {
        "key": "keto_flour_generic",
        "emoji": "🌰",
        "match": [],
        "name": {"uz": "Keto unlar", "ru": "Кето-мука"},
        "shop": "uni",
        "benefits": [
            {"uz": "Keto unlar yong'oq, urug' va dukkaklilardan tayyorlanadi — oddiy bug'doy uniga qaraganda bir necha barobar kam uglevod va ko'p oqsil hamda tola beradi.",
             "ru": "Кето-мука делается из орехов, семян и бобовых — в разы меньше углеводов и больше белка и клетчатки, чем в пшеничной."},
            {"uz": "Glutensiz unlar suyuqlikni har xil tortadi: yangi unni sinayotganda suyuqlikni asta-sekin qo'shing va xamirga 5 daqiqa dam bering.",
             "ru": "Безглютеновая мука по-разному впитывает жидкость: пробуя новую, добавляйте жидкость постепенно и дайте тесту отдохнуть 5 минут."},
        ],
        "recipes": [
            {"uz": "<b>Universal keto quymoq (istalgan keto undan)</b>\n⏱ 15 daqiqa · 🍽 6 dona\n\n🧾 <b>Masalliqlar:</b>\n• 100 g keto un (bodom, kokos-bodom aralashmasi yoki boshqa)\n• 2 ta tuxum\n• 80 ml sut yoki suv\n• 1 choy qoshiq pishirish kukuni\n• 1 chimdim tuz\n• 1 osh qoshiq eritritol\n• 1 choy qoshiq yog' (tova uchun)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Idishda tuxum, sut va eritritolni vilka bilan aralashtiring.\n2. Un, pishirish kukuni va tuzni qo'shib, quyruqsiz aralashtiring.\n3. Xamir quyuq qaymoqdek bo'lishi kerak: juda quyuq bo'lsa — 1–2 osh qoshiq suv, suyuq bo'lsa — 1 osh qoshiq un qo'shing.\n4. Tovani o'rtacha olovda qizdirib, yog' surting.\n5. Har biriga 2 osh qoshiq xamir quyib, sirtida pufakchalar paydo bo'lguncha 2 daqiqa pishiring.\n6. Ag'darib, yana 1–2 daqiqa pishiring. Rezavor yoki shirin qaymoq krem bilan torting.\n\n💡 Kokos uni bo'lsa, faqat 40 g oling va 1 ta tuxum qo'shing — u suyuqlikni ko'p shimadi.",
             "ru": "<b>Универсальные кето-панкейки (из любой кето-муки)</b>\n⏱ 15 минут · 🍽 6 штук\n\n🧾 <b>Ингредиенты:</b>\n• 100 г кето-муки (миндальной, кокосово-миндальной смеси или другой)\n• 2 яйца\n• 80 мл молока или воды\n• 1 ч. ложка разрыхлителя\n• 1 щепотка соли\n• 1 ст. ложка эритрита\n• 1 ч. ложка масла (для сковороды)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Смешайте вилкой яйца, молоко и эритрит.\n2. Добавьте муку, разрыхлитель и соль, перемешайте без комков.\n3. Тесто должно быть как густая сметана: слишком густое — добавьте 1–2 ст. ложки воды, жидкое — 1 ст. ложку муки.\n4. Разогрейте сковороду на среднем огне и смажьте маслом.\n5. Выкладывайте по 2 ст. ложки теста и жарьте 2 минуты, пока на поверхности не появятся пузырьки.\n6. Переверните и жарьте ещё 1–2 минуты. Подавайте с ягодами или сливочным кремом.\n\n💡 С кокосовой мукой берите только 40 г и добавьте ещё 1 яйцо — она сильно впитывает жидкость."},
            {"uz": "<b>Keto kraker (istalgan keto undan)</b>\n⏱ 30 daqiqa · 🍽 1 laganda (taxminan 24 dona)\n\n🧾 <b>Masalliqlar:</b>\n• 150 g keto un (bodom, zig'ir yoki aralash)\n• 1 ta tuxum\n• 2 osh qoshiq zaytun yog'i yoki eritilgan sariyog'\n• 1/2 choy qoshiq tuz\n• 1 osh qoshiq kunjut yoki 1 choy qoshiq quritilgan ziravor (rayhon, oregano)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Pechni 170°C ga qizdiring.\n2. Idishda un, tuz va kunjutni (yoki ziravorni) aralashtiring.\n3. Tuxum va yog'ni qo'shib, zich xamir qoring; juda quruq bo'lsa — 1 osh qoshiq suv qo'shing.\n4. Xamirni ikki pergament qog'oz orasiga qo'yib, 2–3 mm qalinlikda yoying.\n5. Ustki qog'ozni oling va pichoq bilan 4×4 sm kvadratlarga chizing (oxirigacha kesmasdan).\n6. Pergament bilan birga laganga o'tkazib, 170°C da 15–18 daqiqa, chetlari qizarguncha pishiring.\n7. To'liq sovugach chiziqlar bo'ylab sindiring — sovigach qarsillaydi.\n\n💡 Yopiq bankada 1 haftagacha saqlanadi.",
             "ru": "<b>Кето-крекеры из любой кето-муки</b>\n⏱ 30 минут · 🍽 1 противень (около 24 штук)\n\n🧾 <b>Ингредиенты:</b>\n• 150 г кето-муки (миндальной, льняной или смеси)\n• 1 яйцо\n• 2 ст. ложки оливкового или растопленного сливочного масла\n• 1/2 ч. ложки соли\n• 1 ст. ложка кунжута или 1 ч. ложка сушёных трав (базилик, орегано)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Разогрейте духовку до 170°C.\n2. Смешайте в миске муку, соль и кунжут (или травы).\n3. Добавьте яйцо и масло, замесите плотное тесто; если сухое — добавьте 1 ст. ложку воды.\n4. Положите тесто между двумя листами пергамента и раскатайте толщиной 2–3 мм.\n5. Снимите верхний лист и наметьте ножом квадраты 4×4 см (не прорезая до конца).\n6. Переложите вместе с пергаментом на противень и выпекайте 15–18 минут при 170°C, до румяных краёв.\n7. Полностью остудите и разломайте по линиям — остывшие крекеры хрустят.\n\n💡 В закрытой банке хранятся до 1 недели."},
        ],
    },
    "seeds": {
        "key": "seeds_generic",
        "emoji": "🌱",
        "match": [],
        "name": {"uz": "Urug'lar va donlar", "ru": "Семена и зёрна"},
        "shop": "urug'",
        "benefits": [
            {"uz": "Urug'lar — kichik, lekin to'yimli: sog'lom yog'lar, o'simlik oqsili, tola va minerallar bir hovuchda. Salat va bo'tqaga qo'shish eng oson yo'l.",
             "ru": "Семена — маленькие, но питательные: полезные жиры, растительный белок, клетчатка и минералы в одной горсти. Проще всего добавлять в салаты и каши."},
            {"uz": "Quruq tovada 2-3 daqiqa yengil qovursangiz, urug'ning aromati ochiladi — faqat kuydirmang, foydali yog'lari achiydi.",
             "ru": "Если слегка прогреть семена 2-3 минуты на сухой сковороде, раскроется аромат — только не пережаривайте, полезные жиры горкнут."},
        ],
        "recipes": [
            {"uz": "<b>Urug'li salat sepkisi</b>\n⏱ 10 daqiqa · 🍽 1 banka (150 g)\n\n🧾 <b>Masalliqlar:</b>\n• 2 osh qoshiq qovoq urug'i\n• 2 osh qoshiq kungaboqar urug'i\n• 2 osh qoshiq kunjut\n• 2 osh qoshiq zig'ir urug'i\n• 1 chimdim tuz\n• 1/2 choy qoshiq paprika yoki quritilgan ko'kat\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Quruq tovani o'rtacha olovda qizdiring.\n2. Qovoq va kungaboqar urug'ini 3 daqiqa aralashtirib qizdiring.\n3. Kunjut va zig'irni qo'shib, yana 1–2 daqiqa, kunjut och oltinrang bo'lguncha qizdiring.\n4. Olovdan olib, tuz va paprikani qo'shib aralashtiring.\n5. Sovigach, yopiq bankaga soling.\n6. Salat, sho'rva, omlet va bo'tqaga 1 osh qoshiqdan seping.\n\n💡 2 haftagacha saqlanadi.",
             "ru": "<b>Посыпка из семян для салатов</b>\n⏱ 10 минут · 🍽 1 банка (150 г)\n\n🧾 <b>Ингредиенты:</b>\n• 2 ст. ложки тыквенных семечек\n• 2 ст. ложки подсолнечных семечек\n• 2 ст. ложки кунжута\n• 2 ст. ложки семян льна\n• 1 щепотка соли\n• 1/2 ч. ложки паприки или сушёной зелени\n\n👩‍🍳 <b>Приготовление:</b>\n1. Разогрейте сухую сковороду на среднем огне.\n2. Прогрейте тыквенные и подсолнечные семечки 3 минуты, помешивая.\n3. Добавьте кунжут и лён и прогревайте ещё 1–2 минуты, пока кунжут не станет светло-золотистым.\n4. Снимите с огня, добавьте соль и паприку, перемешайте.\n5. Остудите и пересыпьте в закрытую банку.\n6. Посыпайте салаты, супы, омлеты и каши по 1 ст. ложке.\n\n💡 Хранится до 2 недель."},
            {"uz": "<b>Urug'li energiya sharchalari</b>\n⏱ 15 daqiqa + 20 daqiqa muzlatkichda · 🍽 12 dona\n\n🧾 <b>Masalliqlar:</b>\n• 100 g urug'lar aralashmasi (qovoq, kungaboqar, kunjut)\n• 3 osh qoshiq yong'oq pastasi\n• 1 osh qoshiq kokos yog'i (eritilgan)\n• 1 osh qoshiq maydalangan eritritol\n• 1 chimdim tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Urug'larni blenderda 10–15 soniya yirik maydalang (un bo'lib ketmasin).\n2. Idishda maydalangan urug', yong'oq pastasi, erigan kokos yog'i, eritritol va tuzni aralashtiring.\n3. Massa qo'lda siqilganda yopishib turishi kerak; quruq bo'lsa — yana 1 osh qoshiq pasta qo'shing.\n4. Ho'l qo'l bilan yong'oqdek 12 ta sharcha yasang.\n5. Pergamentga terib, muzlatkichda 20 daqiqa qotiring.\n6. Yopiq idishda muzlatkichda saqlang (1 haftagacha).\n\n💡 Ishga yoki maktabga gazak sifatida qulay.",
             "ru": "<b>Энергетические шарики из семян</b>\n⏱ 15 минут + 20 минут в холодильнике · 🍽 12 штук\n\n🧾 <b>Ингредиенты:</b>\n• 100 г смеси семян (тыквенные, подсолнечные, кунжут)\n• 3 ст. ложки ореховой пасты\n• 1 ст. ложка кокосового масла (растопленного)\n• 1 ст. ложка молотого эритрита\n• 1 щепотка соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Измельчите семена в блендере 10–15 секунд крупно (не в муку).\n2. Смешайте в миске семена, ореховую пасту, растопленное масло, эритрит и соль.\n3. При сжатии масса должна держаться; если сухая — добавьте ещё 1 ст. ложку пасты.\n4. Влажными руками скатайте 12 шариков размером с грецкий орех.\n5. Выложите на пергамент и уберите в холодильник на 20 минут.\n6. Храните в закрытом контейнере в холодильнике (до 1 недели).\n\n💡 Удобный перекус на работу или в школу."},
        ],
    },
    "supplements": {
        "key": "supplements_generic",
        "emoji": "💊",
        "match": [],
        "name": {"uz": "Foydali qo'shimchalar", "ru": "Полезные добавки"},
        "shop": "psillium",
        "benefits": [
            {"uz": "To'g'ri tanlangan qo'shimchalar keto va PP ratsionidagi bo'shliqlarni to'ldiradi: tola, minerallar va pishiriqda bog'lovchi vazifasi.",
             "ru": "Правильно подобранные добавки закрывают пробелы кето- и ПП-рациона: клетчатка, минералы и роль связующего в выпечке."},
            {"uz": "Har qanday yangi qo'shimchani kichik miqdordan boshlang va organizmingiz qanday qabul qilishini kuzating — ko'proq har doim yaxshiroq degani emas.",
             "ru": "Любую новую добавку начинайте с малой дозы и следите за реакцией организма — больше не всегда значит лучше."},
        ],
        "recipes": [
            {"uz": "<b>Ertalabki tola kokteyli</b>\n⏱ 3 daqiqa · 🍽 1 stakan\n\n🧾 <b>Masalliqlar:</b>\n• 250 ml suv yoki kefir\n• 1 choy qoshiq tolali qo'shimcha (psillium yoki kepak)\n• 1 osh qoshiq limon sharbati\n• Keyin ichish uchun: yana 1 stakan (250 ml) suv\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Stakanga suv yoki kefir quying.\n2. Limon sharbatini qo'shing.\n3. Tolali qo'shimchani sepib, qoshiq bilan 15 soniya tez aralashtiring.\n4. Darhol, 1 daqiqa ichida iching — keyin quyuqlashib jelega aylanadi.\n5. Ketidan yana 1 stakan oddiy suv iching — tola suv bilan yaxshi ishlaydi.\n\n💡 1/2 choy qoshiqdan boshlab, 1 haftada 1 choy qoshiqqa yetkazing. Dori ichsangiz, oraliq kamida 2 soat bo'lsin.",
             "ru": "<b>Утренний коктейль с клетчаткой</b>\n⏱ 3 минуты · 🍽 1 стакан\n\n🧾 <b>Ингредиенты:</b>\n• 250 мл воды или кефира\n• 1 ч. ложка добавки с клетчаткой (псиллиум или отруби)\n• 1 ст. ложка лимонного сока\n• Чтобы запить: ещё 1 стакан (250 мл) воды\n\n👩‍🍳 <b>Приготовление:</b>\n1. Налейте в стакан воду или кефир.\n2. Добавьте лимонный сок.\n3. Всыпьте клетчатку и быстро перемешайте ложкой 15 секунд.\n4. Выпейте сразу, в течение 1 минуты, — потом напиток загустеет в желе.\n5. Запейте ещё стаканом простой воды — клетчатке нужна вода.\n\n💡 Начните с 1/2 ч. ложки и за неделю дойдите до 1 ч. ложки. Если принимаете лекарства, интервал не меньше 2 часов."},
        ],
    },
    "ready_made": {
        "key": "ready_made",
        "emoji": "🍫",
        "match": [],
        "name": {"uz": "Tayyor sog'lom mahsulotlar", "ru": "Готовые полезные продукты"},
        "shop": "shokolad",
        "benefits": [
            {"uz": "Tayyor sog'lom mahsulotlar — vaqt yo'q kunlar uchun qutqaruvchi: shakarli gazakka qo'l cho'zish o'rniga, ratsiondan chiqmasdan shirinlik.",
             "ru": "Готовые полезные продукты выручают, когда нет времени: сладкое без выхода из рациона вместо сахарного перекуса."},
            {"uz": "Etiketkaga qarang: tarkibi qisqa va shakar ro'yxat oxirida (yoki umuman yo'q) bo'lsa — to'g'ri tanlov.",
             "ru": "Смотрите на этикетку: короткий состав и сахар в конце списка (или его нет вовсе) — правильный выбор."},
        ],
        "recipes": [
            {"uz": "<b>5 daqiqalik keto desert</b>\n⏱ 5 daqiqa · 🍽 1 kishilik\n\n🧾 <b>Masalliqlar:</b>\n• 150 g grek yogurti yoki yumshoq tvorog (5% va undan yog'li)\n• 1 choy qoshiq maydalangan eritritol\n• 1 osh qoshiq tayyor mahsulot: shakarsiz shokolad granulasi, kokos chipsi yoki kakao nibs\n• Ixtiyoriy: 1 hovuch rezavor\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Yogurt (yoki tvorog) va eritritolni vilka bilan 1 daqiqa, silliq va havodor bo'lguncha uring.\n2. Kosaga soling.\n3. Ustiga shokolad granulasi, kokos chipsi yoki kakao nibs seping.\n4. Xohlasangiz, rezavor qo'shib darhol yeng.\n\n💡 Kechki shirinlik ishtahasini bosish uchun eng tez yo'l.",
             "ru": "<b>Кето-десерт за 5 минут</b>\n⏱ 5 минут · 🍽 1 порция\n\n🧾 <b>Ингредиенты:</b>\n• 150 г греческого йогурта или мягкого творога (от 5% жирности)\n• 1 ч. ложка молотого эритрита\n• 1 ст. ложка готового продукта: шоколадные гранулы без сахара, кокосовые чипсы или какао-крупка\n• По желанию: горсть ягод\n\n👩‍🍳 <b>Приготовление:</b>\n1. Взбейте вилкой йогурт (или творог) с эритритом 1 минуту до гладкости и воздушности.\n2. Выложите в пиалу.\n3. Посыпьте шоколадными гранулами, кокосовыми чипсами или какао-крупкой.\n4. По желанию добавьте ягоды и сразу ешьте.\n\n💡 Самый быстрый способ справиться с вечерней тягой к сладкому."},
        ],
    },
}

# Category → profile. Homogeneous categories reuse their specific profile;
# mixed ones use a generic profile above.
CATEGORY_PROFILE_KEYS = {
    "keto_flour": "keto_flour_generic",
    "coconut": "coconut",
    "pp_flour": "pp_flour",
    "supplements": "supplements_generic",
    "oils": "oils",
    "vinegar": "vinegar",
    "seeds": "seeds_generic",
    "sweeteners": "sweeteners",
    "salt": "salt",
    "fish": "fish",
    "pastes": "pastes",
    "sourdough": "sourdough",
    "ready_made": "ready_made",
    "diet_rice": "diet_rice",
    "honey": "honey",
}


# Fallback for products that don't match any profile above. With the catalogue
# now covered family by family this should be rare — if it starts showing up in
# real sends, that's the signal a new profile is missing above.
DEFAULT_PROFILE = {
    "key": "healthy",
    "emoji": "🥗",
    "name": {"uz": "Sog'lom mahsulotlar", "ru": "Здоровые продукты"},
    "shop": "keto",
    "benefits": [
        {"uz": "Tabiiy, kam qayta ishlangan mahsulotlar organizmni toza oziqlantiradi — energiya barqaror, ishtaha nazoratda bo'ladi.",
         "ru": "Натуральные, минимально обработанные продукты питают организм чисто — стабильная энергия и контроль аппетита."},
        {"uz": "Tarkibi qisqa mahsulot deyarli har doim yaxshiroq: 3-4 ta tanish nomdan iborat etiketka — sog'lom tanlovning eng oddiy mezoni.",
         "ru": "Продукт с коротким составом почти всегда лучше: этикетка из 3-4 знакомых слов — простейший критерий здорового выбора."},
    ],
    "recipes": [
        {"uz": "<b>Sog'lom kosa — to'yimli tushlik</b>\n⏱ 15 daqiqa · 🍽 1 kishilik\n\n🧾 <b>Masalliqlar:</b>\n• 2 hovuch (50 g) yashil barglar (salat bargi, ismaloq)\n• 2 ta qaynatilgan tuxum YOKI 120 g qaynatilgan tovuq filesi\n• 1/2 ta avokado\n• 1 osh qoshiq urug'lar (qovoq, kunjut)\n• Sous: 1 osh qoshiq zaytun yog'i + 1 choy qoshiq olma sirkasi + 1 chimdim tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Tuxumni qaynab turgan suvga solib, 9 daqiqa pishiring va sovuq suvga oling (yoki tovuqni bo'laklab qo'ying).\n2. Barglarni yuvib, quriting va kosa tubiga yoying.\n3. Avokadoni bo'laklarga, tuxumni ikkiga kesing.\n4. Kosaga avokado va tuxum (yoki tovuq)ni chiroyli terib qo'ying.\n5. Kichik idishda yog', sirka va tuzni aralashtirib, ustidan quying.\n6. Urug'larni sepib torting.\n\n💡 Tez, to'yimli va muvozanatli: oqsil, foydali yog' va tola bir kosada.",
         "ru": "<b>Здоровая тарелка (боул) — сытный обед</b>\n⏱ 15 минут · 🍽 1 порция\n\n🧾 <b>Ингредиенты:</b>\n• 2 горсти (50 г) листовой зелени (салат, шпинат)\n• 2 варёных яйца ИЛИ 120 г варёного куриного филе\n• 1/2 авокадо\n• 1 ст. ложка семян (тыквенные, кунжут)\n• Заправка: 1 ст. ложка оливкового масла + 1 ч. ложка яблочного уксуса + 1 щепотка соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Опустите яйца в кипящую воду, варите 9 минут и переложите в холодную воду (или нарежьте курицу).\n2. Вымойте и обсушите зелень, выложите на дно миски.\n3. Нарежьте авокадо дольками, яйца — пополам.\n4. Красиво разложите в миске авокадо и яйца (или курицу).\n5. В маленькой миске смешайте масло, уксус и соль и полейте сверху.\n6. Посыпьте семенами и подавайте.\n\n💡 Быстро, сытно и сбалансированно: белок, полезные жиры и клетчатка в одной миске."},
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# COMBO recipes — built from SEVERAL of the buyer's families at once.
#
# The old message picked the buyer's single most-ordered product and showed a
# recipe for that one thing, which read the same whether someone bought one
# product or nine. A combo fires only when the buyer actually orders every
# family in `needs`, so "we looked at what you buy" is literally true.
#
# Tried before the single-profile recipes; longer `needs` sets are checked
# first, so the most specific match wins.
# ─────────────────────────────────────────────────────────────────────────────
COMBOS = [
    {
        "needs": {"almond_flour", "cacao", "sweeteners"},
        "recipe": {
            "uz": "<b>Keto brauni</b>\n⏱ 35 daqiqa · 🍽 9 bo'lak\n\n🧾 <b>Masalliqlar:</b>\n• 100 g bodom uni\n• 40 g kakao kukuni (shakarsiz)\n• 80 g eritritol\n• 3 ta tuxum\n• 100 g sariyog' (eritilgan)\n• 1 chimdim tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Pechni 175°C ga qizdiring. 20×20 sm qolipga pergament qog'oz to'shang.\n2. Sariyog'ni eritib, 5 daqiqa iliq holatgacha soviting.\n3. Tuxum va eritritolni mikser bilan 3 daqiqa, oqarib ko'piklanguncha uring.\n4. Iliq sariyog'ni ingichka oqim bilan quyib, aralashtiring.\n5. Bodom uni, kakao va tuzni elab qo'shing va spatula bilan pastdan yuqoriga ehtiyotkorlik bilan aralashtiring.\n6. Qolipga solib tekislang va 175°C da 22 daqiqa pishiring — markazi biroz nam qolishi kerak.\n7. Qolipda to'liq soviting (1 soat), so'ng 9 bo'lakka kesing — sovigach o'zi «yetiladi».",
            "ru": "<b>Кето-брауни</b>\n⏱ 35 минут · 🍽 9 кусочков\n\n🧾 <b>Ингредиенты:</b>\n• 100 г миндальной муки\n• 40 г какао-порошка (без сахара)\n• 80 г эритрита\n• 3 яйца\n• 100 г сливочного масла (растопленного)\n• 1 щепотка соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Разогрейте духовку до 175°C. Застелите форму 20×20 см пергаментом.\n2. Растопите масло и остудите 5 минут до тёплого.\n3. Взбейте яйца с эритритом миксером 3 минуты, до посветления и пены.\n4. Тонкой струйкой влейте тёплое масло и перемешайте.\n5. Просейте миндальную муку, какао и соль и аккуратно вмешайте лопаткой снизу вверх.\n6. Выложите в форму, разровняйте и выпекайте 22 минуты при 175°C — центр должен остаться слегка влажным.\n7. Полностью остудите в форме (1 час), затем нарежьте на 9 кусочков — при остывании брауни «доходит»."},
    },
    {
        "needs": {"almond_flour", "coconut", "sweeteners"},
        "recipe": {
            "uz": "<b>Bodom-kokos keksi</b>\n⏱ 40 daqiqa · 🍽 8 bo'lak\n\n🧾 <b>Masalliqlar:</b>\n• 150 g bodom uni\n• 40 g kokos uni\n• 50 g kokos qirindisi (+1 osh qoshiq ustiga)\n• 70 g eritritol\n• 4 ta tuxum\n• 80 ml kokos yog'i (eritilgan)\n• 1 choy qoshiq pishirish kukuni\n• 1 chimdim tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Pechni 180°C ga qizdiring. 20×10 sm qolipga pergament qog'oz to'shang.\n2. Idishda bodom uni, kokos uni, kokos qirindisi, eritritol, pishirish kukuni va tuzni aralashtiring.\n3. Boshqa idishda tuxumni vilka bilan ko'pirtirib, iliq kokos yog'ini qo'shing.\n4. Suyuq qismni quruq qismga qo'shib aralashtiring va 5 daqiqa qo'yib qo'ying — kokos uni namni shimadi.\n5. Xamirni qolipga solib, ustiga 1 osh qoshiq qirindi seping.\n6. 180°C da 30 daqiqa pishiring; tish kavlagich quruq chiqsa — tayyor.\n7. Qolipda 15 daqiqa sovutib, keyin 8 bo'lakka kesing.",
            "ru": "<b>Миндально-кокосовый кекс</b>\n⏱ 40 минут · 🍽 8 кусочков\n\n🧾 <b>Ингредиенты:</b>\n• 150 г миндальной муки\n• 40 г кокосовой муки\n• 50 г кокосовой стружки (+1 ст. ложка сверху)\n• 70 г эритрита\n• 4 яйца\n• 80 мл кокосового масла (растопленного)\n• 1 ч. ложка разрыхлителя\n• 1 щепотка соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Разогрейте духовку до 180°C. Застелите форму 20×10 см пергаментом.\n2. Смешайте в миске миндальную и кокосовую муку, стружку, эритрит, разрыхлитель и соль.\n3. В другой миске взбейте вилкой яйца и добавьте тёплое кокосовое масло.\n4. Соедините жидкую и сухую части, перемешайте и оставьте на 5 минут — кокосовая мука впитает влагу.\n5. Выложите тесто в форму и посыпьте сверху 1 ст. ложкой стружки.\n6. Выпекайте 30 минут при 180°C; зубочистка выходит сухой — готово.\n7. Остудите в форме 15 минут и нарежьте на 8 кусочков."},
    },
    {
        "needs": {"flax", "fiber_supp"},
        "recipe": {
            "uz": "<b>Eng yaxshi keto non (zig'ir + psillium)</b>\n⏱ 70 daqiqa · 🍽 1 non (10 bo'lak)\n\n🧾 <b>Masalliqlar:</b>\n• 120 g zig'ir uni\n• 3 osh qoshiq psillium (qobig'i kukuni)\n• 4 ta tuxum oqi\n• 1 choy qoshiq soda\n• 1 osh qoshiq olma sirkasi\n• 250 ml qaynoq suv\n• 1/2 choy qoshiq tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Pechni 180°C ga qizdiring. Laganga pergament qog'oz to'shang.\n2. Idishda zig'ir uni, psillium, soda va tuzni aralashtiring.\n3. Tuxum oqi va olma sirkasini qo'shib, qoshiq bilan aralashtiring.\n4. Qaynoq suvni quyib, darhol 30 soniya TEZ aralashtiring — psillium bir zumda xamirni ushlaydi.\n5. Ho'l qo'l bilan cho'zinchoq non shaklini berib, laganga qo'ying; ustini pichoq bilan 2–3 marta kesib qo'ying.\n6. 180°C da 55 daqiqa pishiring.\n7. Panjarada butunlay sovuting (kamida 1 soat) va shundan keyin kesing.\n\n💡 Muzlatkichda 5 kun turadi; bo'laklab muzlatib, tosterda qizdirish mumkin.",
            "ru": "<b>Лучший кето-хлеб (лён + псиллиум)</b>\n⏱ 70 минут · 🍽 1 буханка (10 ломтиков)\n\n🧾 <b>Ингредиенты:</b>\n• 120 г льняной муки\n• 3 ст. ложки псиллиума (порошка шелухи)\n• 4 яичных белка\n• 1 ч. ложка соды\n• 1 ст. ложка яблочного уксуса\n• 250 мл кипятка\n• 1/2 ч. ложки соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Разогрейте духовку до 180°C. Застелите противень пергаментом.\n2. Смешайте в миске льняную муку, псиллиум, соду и соль.\n3. Добавьте белки и уксус, перемешайте ложкой.\n4. Влейте кипяток и сразу БЫСТРО перемешайте 30 секунд — псиллиум схватывает тесто моментально.\n5. Влажными руками сформуйте продолговатую буханку, выложите на противень и сделайте 2–3 надреза ножом.\n6. Выпекайте 55 минут при 180°C.\n7. Полностью остудите на решётке (минимум 1 час) и только потом режьте.\n\n💡 В холодильнике хранится 5 дней; можно заморозить ломтиками и подогревать в тостере."},
    },
    {
        "needs": {"chia", "coconut", "sweeteners"},
        "recipe": {
            "uz": "<b>Kokosli chia puding (3 qatlamli)</b>\n⏱ 10 daqiqa + 1 kecha · 🍽 2 stakan\n\n🧾 <b>Masalliqlar:</b>\n• 4 osh qoshiq chia urug'i (40 g)\n• 300 ml kokos suti\n• 2 osh qoshiq eritritol\n• 3 osh qoshiq kokos qirindisi\n• 1 chimdim vanilin\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Idishda kokos suti, eritritol va vanilinni aralashtiring.\n2. Chia urug'ini qo'shib, 30 soniya yaxshilab aralashtiring.\n3. 10 daqiqa kuting va YANA aralashtiring — chia pastga cho'kib qotmasin.\n4. 2 ta stakanga qatlam-qatlam soling: 2 osh qoshiq puding → 1 osh qoshiq kokos qirindisi → yana puding (3 qatlam).\n5. Ustini yopib, muzlatkichda kamida 4 soat, yaxshisi tun bo'yi qoldiring.\n6. Ertalab ustiga qolgan qirindini sepib torting.",
            "ru": "<b>Кокосовый чиа-пудинг в 3 слоя</b>\n⏱ 10 минут + ночь · 🍽 2 стакана\n\n🧾 <b>Ингредиенты:</b>\n• 4 ст. ложки семян чиа (40 г)\n• 300 мл кокосового молока\n• 2 ст. ложки эритрита\n• 3 ст. ложки кокосовой стружки\n• 1 щепотка ванилина\n\n👩‍🍳 <b>Приготовление:</b>\n1. Смешайте в миске кокосовое молоко, эритрит и ванилин.\n2. Всыпьте чиа и хорошо перемешайте 30 секунд.\n3. Подождите 10 минут и перемешайте ЕЩЁ РАЗ — чтобы чиа не осела и не слиплась.\n4. Разложите в 2 стакана слоями: 2 ст. ложки пудинга → 1 ст. ложка стружки → снова пудинг (3 слоя).\n5. Накройте и уберите в холодильник минимум на 4 часа, лучше на ночь.\n6. Утром посыпьте оставшейся стружкой и подавайте."},
    },
    {
        "needs": {"coconut", "cacao", "sweeteners"},
        "recipe": {
            "uz": "<b>Uy keto shokoladi</b>\n⏱ 20 daqiqa (shundan 20 daqiqasi muzlatkichda) · 🍽 1 plitka (8 bo'lak)\n\n🧾 <b>Masalliqlar:</b>\n• 100 g kokos yog'i\n• 50 g kakao kukuni (shakarsiz)\n• 40 g eritritol (kofe maydalagichda unga aylantirilgan)\n• 1 chimdim tuz\n• 1 chimdim vanilin\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Kokos yog'ini suv hammomida eriting — qaynatmang.\n2. Kakao va maydalangan eritritolni elab qo'shing, quyruqsiz silliq bo'lguncha aralashtiring.\n3. Tuz va vanilinni qo'shing.\n4. Massani shokolad qolipiga yoki pergament to'shalgan kichik idishga (15×10 sm) quying.\n5. Muzlatkichda 20 daqiqa qotiring va bo'laklarga sindiring.\n6. Faqat muzlatkichda saqlang — xona haroratida yumshaydi.\n\n💡 Ichiga 2 osh qoshiq yong'oq yoki kokos qirindisi qo'shsangiz, yanada mazali.",
            "ru": "<b>Домашний кето-шоколад</b>\n⏱ 20 минут (все 20 — в холодильнике) · 🍽 1 плитка (8 кусочков)\n\n🧾 <b>Ингредиенты:</b>\n• 100 г кокосового масла\n• 50 г какао-порошка (без сахара)\n• 40 г эритрита (смолотого в кофемолке в пудру)\n• 1 щепотка соли\n• 1 щепотка ванилина\n\n👩‍🍳 <b>Приготовление:</b>\n1. Растопите кокосовое масло на водяной бане — не кипятите.\n2. Просейте какао и молотый эритрит и перемешайте до гладкости без комков.\n3. Добавьте соль и ванилин.\n4. Вылейте массу в форму для шоколада или небольшую ёмкость с пергаментом (15×10 см).\n5. Уберите в холодильник на 20 минут и разломайте на кусочки.\n6. Храните только в холодильнике — при комнатной температуре мягчеет.\n\n💡 Добавьте 2 ст. ложки орехов или кокосовой стружки — будет ещё вкуснее."},
    },
    {
        "needs": {"pastes", "cacao", "sweeteners"},
        "recipe": {
            "uz": "<b>Keto «Snikers» konfeti</b>\n⏱ 30 daqiqa (shundan 25 daqiqasi muzlatgichda) · 🍽 10 dona\n\n🧾 <b>Masalliqlar:</b>\n• 4 osh qoshiq yeryong'oq pastasi\n• 2 osh qoshiq kokos yog'i (eritilgan)\n• 1 osh qoshiq maydalangan eritritol\n• 2 osh qoshiq qovurilgan yeryong'oq (yirik to'g'ralgan, ixtiyoriy)\n• Qoplama: 50 g kakao kukuni + 50 g kokos yog'i + 1 osh qoshiq eritritol\n• 1 chimdim dag'al tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Yeryong'oq pastasi, 2 osh qoshiq kokos yog'i, eritritol va to'g'ralgan yeryong'oqni aralashtiring.\n2. Pergamentga qo'yib, 10 ta kichik batoncha (3×5 sm) shaklida yasang.\n3. Muzlatgichda (morozilkada) 15 daqiqa qotiring.\n4. Qoplama uchun: 50 g kokos yog'ini eritib, kakao va eritritolni qo'shib silliq aralashtiring.\n5. Har bir batonchani vilka bilan qoplamaga botirib oling va pergamentga qayta qo'ying.\n6. Ustiga bir chimdim tuz sepib, yana 10 daqiqa muzlatgichda qotiring.\n7. Muzlatkichda saqlang.",
            "ru": "<b>Кето-«Сникерс»</b>\n⏱ 30 минут (из них 25 в морозилке) · 🍽 10 штук\n\n🧾 <b>Ингредиенты:</b>\n• 4 ст. ложки арахисовой пасты\n• 2 ст. ложки кокосового масла (растопленного)\n• 1 ст. ложка молотого эритрита\n• 2 ст. ложки жареного арахиса (крупно рубленного, по желанию)\n• Глазурь: 50 г какао + 50 г кокосового масла + 1 ст. ложка эритрита\n• 1 щепотка крупной соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Смешайте арахисовую пасту, 2 ст. ложки кокосового масла, эритрит и рубленый арахис.\n2. На пергаменте сформуйте 10 маленьких батончиков (3×5 см).\n3. Заморозьте в морозилке 15 минут.\n4. Для глазури растопите 50 г кокосового масла, вмешайте какао и эритрит до гладкости.\n5. Окуните каждый батончик в глазурь с помощью вилки и снова выложите на пергамент.\n6. Посыпьте щепоткой соли и уберите в морозилку ещё на 10 минут.\n7. Храните в холодильнике."},
    },
    {
        "needs": {"oils", "vinegar", "salt"},
        "recipe": {
            "uz": "<b>Mukammal salat sousi (bir haftaga)</b>\n⏱ 5 daqiqa · 🍽 250 ml (taxminan 12 ta salatga)\n\n🧾 <b>Masalliqlar:</b>\n• 150 ml zaytun yog'i\n• 50 ml olma sirkasi\n• 1 choy qoshiq xantal (gorchitsa)\n• 1/2 choy qoshiq Himalay tuzi\n• 1/4 choy qoshiq qora murch\n• 1 tishcha sarimsoq (maydalangan)\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Sarimsoqni tozalab, pichoq yoki sarimsoq ezgichda maydalang.\n2. Barcha masalliqlarni 300 ml li qopqoqli bankaga soling.\n3. Qopqoqni mahkam yopib, 30 soniya qattiq chayqating.\n4. Muzlatkichda saqlang.\n5. Har ishlatishdan oldin 10 soniya chayqating va salatga 1–2 osh qoshiqdan quying.\n\n💡 Muzlatkichda zaytun yog'i biroz qotadi — 5 daqiqa xonada tursa, yana suyuladi.",
            "ru": "<b>Идеальная заправка на неделю</b>\n⏱ 5 минут · 🍽 250 мл (примерно на 12 салатов)\n\n🧾 <b>Ингредиенты:</b>\n• 150 мл оливкового масла\n• 50 мл яблочного уксуса\n• 1 ч. ложка горчицы\n• 1/2 ч. ложки гималайской соли\n• 1/4 ч. ложки чёрного перца\n• 1 зубчик чеснока (измельчённого)\n\n👩‍🍳 <b>Приготовление:</b>\n1. Очистите чеснок и измельчите ножом или прессом.\n2. Сложите все ингредиенты в банку на 300 мл с крышкой.\n3. Плотно закройте и энергично встряхивайте 30 секунд.\n4. Храните в холодильнике.\n5. Перед каждым использованием встряхните 10 секунд и поливайте салат по 1–2 ст. ложки.\n\n💡 В холодильнике оливковое масло слегка густеет — постоит 5 минут в комнате и снова станет жидким."},
    },
    {
        "needs": {"bran", "sesame", "flax"},
        "recipe": {
            "uz": "<b>Tolaga boy kraker</b>\n⏱ 45 daqiqa · 🍽 1 laganda (taxminan 20 dona)\n\n🧾 <b>Masalliqlar:</b>\n• 3 osh qoshiq kepak\n• 3 osh qoshiq zig'ir urug'i\n• 2 osh qoshiq kunjut\n• 120 ml suv\n• 1/4 choy qoshiq tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Idishda kepak, zig'ir, kunjut va tuzni aralashtiring.\n2. Suvni quyib aralashtiring va 15 daqiqa qo'yib qo'ying — quyuq bo'tqaga aylanadi.\n3. Pechni 150°C ga qizdiring. Laganga pergament qog'oz to'shang.\n4. Massani pergamentga solib, qoshiq bilan 3 mm qalinlikda tekis yoying.\n5. Pichoq bilan 5×5 sm kvadratlarga chizing.\n6. 150°C da 35 daqiqa, qattiq va quruq bo'lguncha quriting.\n7. Sovigach chiziqlar bo'ylab sindiring.\n\n💡 Yopiq bankada 2 haftagacha qarsillab turadi.",
            "ru": "<b>Крекеры с высокой клетчаткой</b>\n⏱ 45 минут · 🍽 1 противень (около 20 штук)\n\n🧾 <b>Ингредиенты:</b>\n• 3 ст. ложки отрубей\n• 3 ст. ложки семян льна\n• 2 ст. ложки кунжута\n• 120 мл воды\n• 1/4 ч. ложки соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Смешайте в миске отруби, лён, кунжут и соль.\n2. Влейте воду, перемешайте и оставьте на 15 минут — получится густая каша.\n3. Разогрейте духовку до 150°C. Застелите противень пергаментом.\n4. Выложите массу на пергамент и распределите ложкой ровным слоем 3 мм.\n5. Наметьте ножом квадраты 5×5 см.\n6. Подсушивайте 35 минут при 150°C, до твёрдости и сухости.\n7. Остудите и разломайте по линиям.\n\n💡 В закрытой банке остаются хрустящими до 2 недель."},
    },
    {
        "needs": {"diet_rice", "fish", "oils"},
        "recipe": {
            "uz": "<b>Losos va qora guruchli kosa</b>\n⏱ 40 daqiqa · 🍽 2 kishilik\n\n🧾 <b>Masalliqlar:</b>\n• 150 g qora guruch\n• 400 ml suv (pishirish uchun)\n• 1 banka (taxminan 240 g) losos tushonkasi\n• 1 ta avokado\n• 1 ta bodring\n• 1 osh qoshiq kunjut\n• 2 osh qoshiq zaytun yog'i\n• 1 osh qoshiq limon sharbati\n• 1/2 choy qoshiq tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Guruchni yuvib, 400 ml qaynab turgan suvga soling, bir chimdim tuz qo'shing.\n2. Qopqoq ostida past olovda 30–35 daqiqa pishiring, ortiqcha suvini to'kib sovuting.\n3. Avokado va bodringni 1 sm kubik qilib to'g'rang; losos suyuqligini to'kib, bo'laklarga ajrating.\n4. Zaytun yog'i, limon sharbati va qolgan tuzni aralashtirib sous qiling.\n5. 2 ta kosaga qatlab joylang: guruch, ustiga losos, avokado va bodring.\n6. Sousni quyib, kunjut sepib torting.\n\n💡 Guruchni kechqurun pishirib qo'ysangiz, ertalab 5 daqiqada ishga tushlik tayyor.",
            "ru": "<b>Боул с лососем и чёрным рисом</b>\n⏱ 40 минут · 🍽 2 порции\n\n🧾 <b>Ингредиенты:</b>\n• 150 г чёрного риса\n• 400 мл воды (для варки)\n• 1 банка (около 240 г) консервированного лосося\n• 1 авокадо\n• 1 огурец\n• 1 ст. ложка кунжута\n• 2 ст. ложки оливкового масла\n• 1 ст. ложка лимонного сока\n• 1/2 ч. ложки соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Промойте рис, всыпьте в 400 мл кипящей воды, добавьте щепотку соли.\n2. Варите под крышкой на слабом огне 30–35 минут, слейте лишнюю воду и остудите.\n3. Нарежьте авокадо и огурец кубиком 1 см; слейте жидкость с лосося и разберите на кусочки.\n4. Смешайте масло, лимонный сок и оставшуюся соль — это заправка.\n5. Разложите по 2 мискам слоями: рис, сверху лосось, авокадо и огурец.\n6. Полейте заправкой, посыпьте кунжутом и подавайте.\n\n💡 Если отварить рис с вечера, утром обед на работу готов за 5 минут."},
    },
    {
        "needs": {"nuts", "honey", "sesame"},
        "recipe": {
            "uz": "<b>Uy granolasi (oq shakarsiz)</b>\n⏱ 30 daqiqa · 🍽 1 banka (300 g)\n\n🧾 <b>Masalliqlar:</b>\n• 200 g turli mag'iz (bodom, yong'oq, funduk)\n• 3 osh qoshiq kunjut\n• 3 osh qoshiq asal\n• 2 osh qoshiq kokos yog'i\n• 1 choy qoshiq dolchin\n• 1 chimdim tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Pechni 160°C ga qizdiring. Laganga pergament qog'oz to'shang.\n2. Mag'izni pichoq bilan yirik (no'xatdek) to'g'rang.\n3. Kichik qozonda asal va kokos yog'ini past olovda 1 daqiqa, suyulguncha isiting.\n4. Idishda mag'iz, kunjut, dolchin va tuzni aralashtirib, asalli yog'ni quying va yaxshilab aralashtiring.\n5. Laganga bir qatlam qilib yoying.\n6. 160°C da 20 daqiqa pishiring; 10-daqiqada aralashtiring. Oltinrang bo'lsa — tayyor.\n7. To'liq soviting (qotadi), keyin bo'laklarga sindirib bankaga soling.\n\n💡 Asal ham shakar ekanini unutmang: 1 porsiya — 2 osh qoshiq, yogurt bilan.",
            "ru": "<b>Домашняя гранола (без белого сахара)</b>\n⏱ 30 минут · 🍽 1 банка (300 г)\n\n🧾 <b>Ингредиенты:</b>\n• 200 г разных орехов (миндаль, грецкие, фундук)\n• 3 ст. ложки кунжута\n• 3 ст. ложки мёда\n• 2 ст. ложки кокосового масла\n• 1 ч. ложка корицы\n• 1 щепотка соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Разогрейте духовку до 160°C. Застелите противень пергаментом.\n2. Крупно (размером с горошину) порубите орехи ножом.\n3. В сотейнике на слабом огне 1 минуту нагрейте мёд с кокосовым маслом до жидкого состояния.\n4. Смешайте в миске орехи, кунжут, корицу и соль, влейте медовое масло и хорошо перемешайте.\n5. Распределите одним слоем на противне.\n6. Выпекайте 20 минут при 160°C, перемешав на 10-й минуте. Стала золотистой — готово.\n7. Полностью остудите (застынет), разломайте и пересыпьте в банку.\n\n💡 Помните, что мёд — тоже сахар: 1 порция — 2 ст. ложки, с йогуртом."},
    },
    {
        "needs": {"buckwheat", "oils", "salt"},
        "recipe": {
            "uz": "<b>Yashil grechka bo'tqasi (kechqurundan tayyorlanadi)</b>\n⏱ 10 daqiqa + 1 kecha · 🍽 2 kishilik\n\n🧾 <b>Masalliqlar:</b>\n• 1 stakan (200 g) yashil grechka\n• 2 stakan (400 ml) bo'ktirish uchun suv\n• 1,5 stakan (300 ml) pishirish uchun suv\n• 1 osh qoshiq eritilgan sariyog' (gxi) yoki kokos yog'i\n• 1/2 choy qoshiq Himalay tuzi\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Kechqurun grechkani 2–3 marta yuvib, 2 stakan suvga solib tunab qoldiring.\n2. Ertalab suvini to'kib, elakda yaxshilab yuving.\n3. Qozonga grechka va 1,5 stakan yangi suv soling, qaynating.\n4. Qaynagach, olovni pasaytirib, qopqoq ostida 7 daqiqa pishiring.\n5. Olovdan olib, yog' va tuz qo'shing, aralashtiring va 3 daqiqa dam bering.\n\n💡 Bo'ktirilgani uchun pishirish vaqti 2 baravar qisqaradi.",
            "ru": "<b>Каша из зелёной гречки (с вечера)</b>\n⏱ 10 минут + ночь · 🍽 2 порции\n\n🧾 <b>Ингредиенты:</b>\n• 1 стакан (200 г) зелёной гречки\n• 2 стакана (400 мл) воды для замачивания\n• 1,5 стакана (300 мл) воды для варки\n• 1 ст. ложка топлёного масла (гхи) или кокосового масла\n• 1/2 ч. ложки гималайской соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Вечером промойте гречку 2–3 раза и замочите в 2 стаканах воды на ночь.\n2. Утром слейте воду и хорошо промойте гречку в сите.\n3. Положите гречку в кастрюлю, залейте 1,5 стакана свежей воды и доведите до кипения.\n4. Убавьте огонь и варите под крышкой 7 минут.\n5. Снимите с огня, добавьте масло и соль, перемешайте и дайте постоять 3 минуты.\n\n💡 Благодаря замачиванию время варки сокращается вдвое."},
    },
    {
        "needs": {"almond_flour", "sweeteners"},
        "recipe": {
            "uz": "<b>Keto bodom pechenesi</b>\n⏱ 25 daqiqa · 🍽 14 dona\n\n🧾 <b>Masalliqlar:</b>\n• 200 g bodom uni\n• 70 g eritritol\n• 80 g sariyog' (yumshatilgan, xona haroratida)\n• 1 ta tuxum\n• 1 chimdim vanilin\n• 1 chimdim tuz\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Pechni 170°C ga qizdiring. Laganga pergament qog'oz to'shang.\n2. Yumshoq sariyog' va eritritolni mikser yoki vilka bilan 2 daqiqa, oqarguncha uring.\n3. Tuxum va vanilinni qo'shib aralashtiring.\n4. Bodom uni va tuzni qo'shib, yumshoq xamir qoring.\n5. 14 ta yong'oqdek (taxminan 25 g) sharcha yasang, laganga 3 sm oraliqda tering va kaft bilan 1 sm gacha bosing.\n6. 170°C da 13 daqiqa, chetlari oltinrang bo'lguncha pishiring.\n7. Laganda 10 daqiqa sovuting: issiqligida yumshoq, sovigach qarsillaydi.",
            "ru": "<b>Кето-печенье из миндальной муки</b>\n⏱ 25 минут · 🍽 14 штук\n\n🧾 <b>Ингредиенты:</b>\n• 200 г миндальной муки\n• 70 г эритрита\n• 80 г сливочного масла (мягкого, комнатной температуры)\n• 1 яйцо\n• 1 щепотка ванилина\n• 1 щепотка соли\n\n👩‍🍳 <b>Приготовление:</b>\n1. Разогрейте духовку до 170°C. Застелите противень пергаментом.\n2. Взбейте мягкое масло с эритритом миксером или вилкой 2 минуты, до посветления.\n3. Добавьте яйцо и ванилин, перемешайте.\n4. Всыпьте миндальную муку и соль, замесите мягкое тесто.\n5. Скатайте 14 шариков размером с грецкий орех (около 25 г), выложите на противень на расстоянии 3 см и приплюсните ладонью до 1 см.\n6. Выпекайте 13 минут при 170°C, до золотистых краёв.\n7. Остудите на противне 10 минут: горячее печенье мягкое, остывшее хрустит."},
    },
    {
        "needs": {"chia", "flax"},
        "recipe": {
            "uz": "<b>Omega-3 aralashmasi (ertalabki qoshiq)</b>\n⏱ 5 daqiqa · 🍽 1 banka (2 haftaga)\n\n🧾 <b>Masalliqlar:</b>\n• 7 osh qoshiq chia urug'i\n• 7 osh qoshiq maydalangan zig'ir urug'i\n• Ixtiyoriy: 3 osh qoshiq kunjut\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Zig'ir urug'ini kofe maydalagichda maydalang (yoki tayyor maydalanganini oling).\n2. Quruq bankada chia, maydalangan zig'ir va kunjutni aralashtiring.\n3. Qopqoqni mahkam yopib, muzlatkichda saqlang — maydalangan zig'ir xonada tez achiydi.\n4. Har kuni 1 osh qoshiqdan yogurt, smuzi yoki bo'tqaga qo'shing.\n\n💡 Ketidan bir stakan suv iching — urug'lar suv bilan yaxshi ishlaydi.",
            "ru": "<b>Омега-3 смесь (утренняя ложка)</b>\n⏱ 5 минут · 🍽 1 банка (на 2 недели)\n\n🧾 <b>Ингредиенты:</b>\n• 7 ст. ложек семян чиа\n• 7 ст. ложек молотых семян льна\n• По желанию: 3 ст. ложки кунжута\n\n👩‍🍳 <b>Приготовление:</b>\n1. Смелите лён в кофемолке (или возьмите уже молотый).\n2. В сухой банке смешайте чиа, молотый лён и кунжут.\n3. Плотно закройте и храните в холодильнике — молотый лён быстро горкнет в тепле.\n4. Добавляйте по 1 ст. ложке в день в йогурт, смузи или кашу.\n\n💡 Запивайте стаканом воды — семенам нужна вода."},
    },
    {
        "needs": {"fiber_supp", "sweeteners"},
        "recipe": {
            "uz": "<b>Psilliumli jele (shakarsiz)</b>\n⏱ 15 daqiqa · 🍽 2 stakan\n\n🧾 <b>Masalliqlar:</b>\n• 300 ml rezavor damlamasi yoki choy (sovuq yoki iliq)\n• 1 osh qoshiq psillium (qobig'i kukuni)\n• 1–2 choy qoshiq eritritol (ta'mga qarab)\n• 1 osh qoshiq limon sharbati\n\n👩‍🍳 <b>Tayyorlash:</b>\n1. Damlamani tayyorlang: 2 osh qoshiq quritilgan rezavor yoki 1 choy paketiga 300 ml qaynoq suv quyib, 10 daqiqa damlang va suzing.\n2. Iliq damlamaga eritritol va limon sharbatini qo'shib aralashtiring.\n3. Venchik bilan to'xtovsiz aralashtirib turib, psilliumni sekin seping.\n4. 30 soniya urib, darhol 2 ta stakanga quying.\n5. 10 daqiqada o'zi quyuqlashadi; sovuq holda yeyish uchun muzlatkichda 30 daqiqa saqlang.\n\n💡 Jelatinsiz, o'simlik asosli shirinlik.",
            "ru": "<b>Желе на псиллиуме без сахара</b>\n⏱ 15 минут · 🍽 2 стакана\n\n🧾 <b>Ингредиенты:</b>\n• 300 мл ягодного настоя или чая (тёплого или холодного)\n• 1 ст. ложка псиллиума (порошка шелухи)\n• 1–2 ч. ложки эритрита (по вкусу)\n• 1 ст. ложка лимонного сока\n\n👩‍🍳 <b>Приготовление:</b>\n1. Приготовьте настой: 2 ст. ложки сушёных ягод или 1 чайный пакетик залейте 300 мл кипятка, настаивайте 10 минут и процедите.\n2. В тёплый настой добавьте эритрит и лимонный сок, перемешайте.\n3. Непрерывно взбивая венчиком, медленно всыпьте псиллиум.\n4. Взбивайте 30 секунд и сразу разлейте по 2 стаканам.\n5. Через 10 минут загустеет само; чтобы есть холодным, уберите в холодильник на 30 минут.\n\n💡 Десерт без желатина, на растительной основе."},
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Complementary-ingredient suggestions.
#
# Keyed by the buyer's dominant profile: "you buy X — these go with it". Each
# suggestion carries the profile key it belongs to, so we never suggest
# something the buyer already orders. PAIRINGS_DEFAULT catches the families
# that have no list of their own, so every message can still close with a
# concrete next product rather than trailing off.
# ─────────────────────────────────────────────────────────────────────────────
def _s(profile, emoji, uz_name, ru_name, uz_why, ru_why):
    """Terser than spelling the dict out 60 times."""
    return {"profile": profile, "emoji": emoji,
            "name": {"uz": uz_name, "ru": ru_name},
            "why": {"uz": uz_why, "ru": ru_why}}


_SWEET = _s("sweeteners", "🍬", "Eritritol", "Эритрит",
            "pishiriqlaringizda shakar o'rnini bosadi, kaloriyasiz shirinlik beradi",
            "заменит сахар в выпечке, даёт сладость без калорий")
# Baking families get their own wording: the reason to keep a sweetener in
# the cupboard is concrete (the dough is ready, the sugar is the missing
# piece), which persuades where a generic "goes well together" does not.
_SWEET_BAKE = _s("sweeteners", "🍬", "Eritritol", "Эритрит",
                 "xamir tayyor — shirinlik yetishmaydi; shakar o'rniga 1:1 qo'shiladi",
                 "тесто готово — не хватает сладости; кладётся вместо сахара 1:1")
_SWEET_DRINK = _s("sweeteners", "🍬", "Eritritol", "Эритрит",
                  "choy va qahvaga: ta'mi o'sha, qondagi shakar ko'tarilmaydi",
                  "в чай и кофе: вкус тот же, сахар в крови не поднимается")

_CHIA = _s("chia", "🌱", "Chia urug'i", "Семена чиа",
           "xamirni bog'laydi, tola va omega-3 qo'shadi",
           "связывает тесто, добавляет клетчатку и омега-3")
_PSY = _s("fiber_supp", "💊", "Psillium", "Псиллиум",
          "glutensiz nonni to'kilmaydigan va cho'ziluvchan qiladi",
          "делает безглютеновый хлеб тянущимся, а не крошащимся")
_SALT = _s("salt", "🧂", "Himalay tuzi", "Гималайская соль",
           "bir chimdim tuz shirinlik ta'mini ochadi, sho'r qilmaydi",
           "щепотка соли раскрывает сладость, не делая солёным")
_OIL = _s("oils", "🫒", "Sovuq bosim zaytun yog'i", "Оливковое масло холодного отжима",
          "salat va tayyor taomlar uchun sog'lom yog' manbai",
          "источник полезных жиров для салатов и готовых блюд")
_CACAO = _s("cacao", "🍫", "Kakao nibs", "Какао-крупка",
            "puding va pishiriqqa shakarsiz, xrustaydigan \"shokolad\" qatlami",
            "хрустящий слой «шоколада» без сахара для пудингов и выпечки")
_COCO = _s("coconut", "🥥", "Kokos qirindisi", "Кокосовая стружка",
           "ustiga sepish uchun tabiiy shirin ta'm va tola beradi",
           "даёт натуральную сладость и клетчатку в посыпке")
_VIN = _s("vinegar", "🍎", "Olma sirkasi", "Яблочный уксус",
          "sodani ishga tushiradi, xamir yumshoq ko'tariladi",
          "активирует соду, тесто поднимается мягче")
_ALMOND = _s("almond_flour", "🥜", "Bodom uni", "Миндальная мука",
             "har qanday keto pishiriqning past uglevodli, to'yimli asosi",
             "низкоуглеводная и сытная основа любой кето-выпечки")
_SESAME = _s("sesame", "⚪", "Kunjut", "Кунжут",
             "kalsiy manbai va har qanday taomga yong'oqsimon aromat",
             "источник кальция и ореховый аромат к любому блюду")
_FLAX = _s("flax", "🌾", "Zig'ir urug'i", "Семена льна",
           "omega-3 va tola manbai, kuniga bir osh qoshiq yetarli",
           "источник омега-3 и клетчатки, достаточно ложки в день")

PAIRINGS = {
    "almond_flour": [_SWEET_BAKE, _CHIA, _COCO, _CACAO, _PSY],
    "coconut": [_ALMOND, _SWEET_BAKE, _CACAO, _CHIA],
    "flax": [_PSY, _SESAME, _SALT, _CHIA],
    "chia": [_COCO, _SWEET, _FLAX, _CACAO],
    "buckwheat": [_SWEET_BAKE, _OIL, _SALT, _SESAME],
    "rastaropsha": [
        _s("honey", "🍯", "Tabiiy asal", "Натуральный мёд",
           "rastaropsha ta'mining achchig'ini yumshatadi",
           "смягчает горечь расторопши"),
        _ALMOND, _FLAX,
    ],
    "pastes": [_CACAO, _SWEET, _COCO, _SALT],
    "nuts": [
        _s("honey", "🍯", "Tabiiy asal", "Натуральный мёд",
           "uy granolasi va yong'oq aralashmasi uchun",
           "для домашней гранолы и ореховой смеси"),
        _SESAME, _CACAO, _SALT,
    ],
    "chickpea": [_OIL, _SALT, _SESAME, _SWEET_BAKE],
    "rice_flour": [_SWEET_BAKE, _ALMOND, _PSY, _SALT],
    "diet_rice": [
        _OIL, _SESAME,
        _s("fish", "🐟", "Losos tushonkasi", "Тушёнка из лосося",
           "guruch bilan 5 daqiqada to'liq tushlik bo'ladi",
           "с рисом получается полноценный обед за 5 минут"),
        _VIN,
    ],
    "pp_flour": [_SWEET_BAKE, _FLAX, _SESAME, _PSY],
    "bran": [_FLAX, _SESAME, _PSY, _SWEET_DRINK],
    "sourdough": [
        _s("pp_flour", "🌾", "Javdar uni", "Ржаная мука",
           "zakvaska uchun eng mos un, non chin ma'noda nordon chiqadi",
           "лучшая мука для закваски, хлеб выходит по-настоящему кислым"),
        _SESAME, _SALT,
    ],
    "sesame": [_FLAX, _SALT, _OIL, _CHIA],
    "pumpkin_seed": [_SESAME, _SALT, _OIL],
    "sedana": [
        _s("honey", "🍯", "Tabiiy asal", "Натуральный мёд",
           "sedana bilan aralashtirilganda ta'mi yumshaydi, an'anaviy usul",
           "в смеси с тмином вкус мягче, это традиционный способ"),
        _SESAME, _FLAX,
    ],
    "fiber_supp": [_ALMOND, _FLAX, _SWEET, _SALT],
    "cacao": [_SWEET_BAKE, _COCO, _SALT, _ALMOND],
    "keto_icecream": [_CACAO, _COCO,
        _s("pastes", "🥄", "Yong'oq pastasi", "Ореховая паста",
           "muzqaymoq ustidan quyilsa — shakarsiz karamel o'rnini bosadi",
           "полейте мороженое — заменит карамель без сахара")],
    "fish": [
        _OIL, _SESAME,
        _s("diet_rice", "🍚", "Qora guruch", "Чёрный рис",
           "losos bilan bowl qilsangiz, ishga olib boradigan tayyor tushlik bo'ladi",
           "боул с лососем станет готовым обедом, который берут с собой"),
    ],
    "oils": [_VIN, _SALT, _SESAME],
    "vinegar": [_OIL, _SALT],
    "salt": [_OIL, _VIN, _SESAME],
    "sweeteners": [_ALMOND, _CACAO, _COCO, _SALT],
    "honey": [
        _s("nuts", "🌰", "Pista mag'zi", "Фисташковые ядра",
           "asal bilan aralashtirib ertalabki energiya aralashmasi qilinadi",
           "с мёдом получается утренняя энергетическая смесь"),
        _SESAME, _CACAO,
    ],
    "spices": [_SALT, _OIL, _SESAME],
}

PAIRINGS_DEFAULT = [_OIL, _SALT, _CHIA, _ALMOND]


# ─────────────────────────────────────────────────────────────────────────────
# Message copy.
#
# Rewritten 2026-09-17. Three things the old version didn't do:
#   1. say out loud that this was put together BY KETOSHOP, FOR THIS BUYER —
#      people were reading it as another mass broadcast;
#   2. thank them warmly and specifically for choosing a healthy life, naming
#      how many times they've ordered rather than a generic "dear customer";
#   3. end on a call to action instead of trailing off.
#
# Every uz string is rendered through _loc(), which transliterates to Cyrillic
# Uzbek for buyers on uz_cyr — so the Latin source here is the only copy that
# ever needs editing.
# ─────────────────────────────────────────────────────────────────────────────
LABELS = {
    # Opening line — states who it's from and who it's for, in that order.
    "header": {
        "uz": "🎁 <b>Ketoshopdan — faqat Siz uchun tayyorlandi</b>",
        "ru": "🎁 <b>От Ketoshop — подготовлено лично для вас</b>",
    },
    # Greeting. The named variant is used whenever the buyer's order carries a
    # customer_name — being addressed by name is most of what makes a message
    # feel written for one person rather than blasted at a list.
    "greet_named": {
        "uz": "Assalomu alaykum, <b>{name}</b>!",
        "ru": "Здравствуйте, <b>{name}</b>!",
    },
    "greet": {
        "uz": "Assalomu alaykum!",
        "ru": "Здравствуйте!",
    },
    # Praise, in three flavours by how long they've been with us. {n} = orders.
    "praise_first": {
        "uz": ("Sog'lom hayotni tanlaganingiz uchun chin dildan rahmat! 🤍\n"
               "Siz Ketoshopdan birinchi buyurtmangizni berdingiz — bu yo'lning eng "
               "muhim qadami. Aynan Siz olgan mahsulotlarni ko'rib chiqib, quyidagi "
               "retsept va maslahatlarni Siz uchun tayyorladik."),
        "ru": ("От души благодарим за то, что вы выбрали здоровую жизнь! 🤍\n"
               "Вы сделали свой первый заказ в Ketoshop — самый важный шаг на этом пути. "
               "Мы посмотрели именно на то, что вы взяли, и подготовили для вас рецепт "
               "и советы ниже."),
    },
    "praise_regular": {
        "uz": ("Sog'lom hayotni tanlaganingiz uchun chin dildan rahmat! 🤍\n"
               "Siz Ketoshopdan allaqachon <b>{n} marta</b> buyurtma berdingiz — bu "
               "shunchaki xarid emas, bu o'zingizga va oilangizga g'amxo'rlik. "
               "Shu sababli aynan Siz olgan mahsulotlar asosida quyidagilarni "
               "tayyorladik."),
        "ru": ("От души благодарим за то, что вы выбрали здоровую жизнь! 🤍\n"
               "Вы заказывали в Ketoshop уже <b>{n} {word}</b> — это не просто покупки, "
               "это забота о себе и о своей семье. Поэтому мы собрали всё ниже именно "
               "на основе ваших товаров."),
    },
    "praise_loyal": {
        "uz": ("Sog'lom hayotni tanlaganingiz uchun chin dildan rahmat! 🤍\n"
               "Siz Ketoshopning eng sodiq mijozlaridan birisiz — <b>{n} ta buyurtma</b>. "
               "Bu izchillik va iroda demakdir, biz Sizdan faxrlanamiz. Quyidagilarni "
               "aynan Sizning tanlovingizga qarab tayyorladik."),
        "ru": ("От души благодарим за то, что вы выбрали здоровую жизнь! 🤍\n"
               "Вы один из самых верных покупателей Ketoshop — <b>{n} {word}</b>. "
               "Это последовательность и сила воли, и мы вами гордимся. Всё ниже "
               "составлено именно по вашему выбору."),
    },
    "your_picks": {
        "uz": "🛒 <b>Siz tanlagan mahsulotlar:</b>",
        "ru": "🛒 <b>Товары, которые вы выбрали:</b>",
    },
    # Two recipe headings: the combo one can honestly say "from these together".
    "recipe_combo": {
        "uz": "👨‍🍳 <b>Siz uchun retsept — shu mahsulotlaringizni birgalikda ishlatadi</b>",
        "ru": "👨‍🍳 <b>Рецепт для вас — использует эти ваши товары вместе</b>",
    },
    "recipe_single": {
        "uz": "👨‍🍳 <b>Siz uchun retsept</b>",
        "ru": "👨‍🍳 <b>Рецепт для вас</b>",
    },
    "benefit": {
        "uz": "💡 <b>Nega bu Sizga foydali?</b>",
        "ru": "💡 <b>Чем это полезно именно вам?</b>",
    },
    "pairs": {
        "uz": "🧺 <b>Shularni ham sinab ko'ring</b> — mahsulotlaringizga ajoyib hamroh:",
        "ru": "🧺 <b>Попробуйте также</b> — отлично дополнит ваши продукты:",
    },
    # Call to action — the line right above the buttons.
    "cta": {
        "uz": "👇 Retseptdagi mahsulotlar do'konimizda tayyor — bir bosishda ko'ring:",
        "ru": "👇 Продукты из рецепта уже ждут в магазине — посмотрите в один клик:",
    },
    "closing": {
        "uz": ("🤍 <b>Ketoshopni tanlaganingiz uchun rahmat!</b>\n"
               "Bu maslahatlarni Sizga bonus sifatida, buyurtmalaringiz asosida har "
               "2 kunda tayyorlab boramiz. Sizga sog'lom hayot va baxt tilaymiz!\n"
               "<i>Hurmat bilan, Ketoshop jamoasi.</i>"),
        "ru": ("🤍 <b>Спасибо, что выбираете Ketoshop!</b>\n"
               "Эти материалы мы готовим для вас как бонус, на основе ваших заказов, "
               "каждые 2 дня. Желаем вам здоровья и счастья!\n"
               "<i>С уважением, команда Ketoshop.</i>"),
    },
    "btn_shop_profile": {
        "uz": "🛒 {name} — do'konda ko'rish",
        "ru": "🛒 {name} — смотреть в магазине",
    },
}
