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
            {"uz": "<b>Keto bodom keksi</b>\n⏱ 35 daqiqa · 🍽 8 bo'lak\n<i>Kerak:</i> 200g bodom uni, 3 tuxum, 50g eritilgan sariyog', 60g eritritol, 1 ch.q. pishirish kukuni, bir chimdim tuz.\n<i>Tayyorlash:</i> Quruq va suyuq qismni alohida aralashtiring → qo'shing → qolipga soling → 180°C da 25 daqiqa. Tuzni tashlab ketmang: u shirinlik ta'mini ochadi.",
             "ru": "<b>Кето-кекс из миндаля</b>\n⏱ 35 минут · 🍽 8 кусочков\n<i>Нужно:</i> 200г миндальной муки, 3 яйца, 50г топлёного масла, 60г эритрита, 1 ч.л. разрыхлителя, щепотка соли.\n<i>Как:</i> Смешайте сухое и жидкое по отдельности → соедините → в форму → 180°C, 25 минут. Не пропускайте соль: она раскрывает сладость."},
            {"uz": "<b>Bodom pancake — 5 daqiqalik nonushta</b>\n⏱ 10 daqiqa · 🍽 2 kishiga\n<i>Kerak:</i> 100g bodom uni, 2 tuxum, 3 osh q. suv yoki sut, bir chimdim tuz.\n<i>Tayyorlash:</i> Xamir quyuq smetana holida bo'lsin → kam yog'da har tomonini 2 daqiqadan qizarting. Ustiga kokos qirindisi yoki chia seping.",
             "ru": "<b>Миндальные панкейки — завтрак за 5 минут</b>\n⏱ 10 минут · 🍽 2 порции\n<i>Нужно:</i> 100г миндальной муки, 2 яйца, 3 ст.л. воды или молока, щепотка соли.\n<i>Как:</i> Тесто как густая сметана → обжарьте по 2 минуты с каждой стороны. Сверху кокосовая стружка или чиа."},
            {"uz": "<b>Glutensiz bodom noni</b>\n⏱ 45 daqiqa · 🍽 1 non\n<i>Kerak:</i> 250g bodom uni, 4 tuxum, 1 ch.q. soda, 1 osh q. olma sirkasi, tuz.\n<i>Tayyorlash:</i> Sirkani sodaga qo'shing (ko'piklanadi) → qolganini aralashtiring → non qolipida 180°C da 35 daqiqa. Sovigach kesing, issiqligida to'kiladi.",
             "ru": "<b>Безглютеновый миндальный хлеб</b>\n⏱ 45 минут · 🍽 1 буханка\n<i>Нужно:</i> 250г миндальной муки, 4 яйца, 1 ч.л. соды, 1 ст.л. яблочного уксуса, соль.\n<i>Как:</i> Уксус к соде (запенится) → смешайте всё → в форме при 180°C 35 минут. Режьте остывшим, горячий крошится."},
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
            {"uz": "<b>Keto \"Bounty\" konfeti</b>\n⏱ 40 daqiqa · 🍽 12 dona\n<i>Kerak:</i> 100g kokos qirindisi, 40g eritilgan kokos yog'i, 30g maydalangan eritritol, vanil.\n<i>Tayyorlash:</i> Aralashtiring → shariklar yasang → muzlatkichda 30 daqiqa. Xohlasangiz erigan keto shokoladga bo'ktiring.",
             "ru": "<b>Кето-конфеты «Баунти»</b>\n⏱ 40 минут · 🍽 12 штук\n<i>Нужно:</i> 100г кокосовой стружки, 40г топлёного кокосового масла, 30г молотого эритрита, ваниль.\n<i>Как:</i> Смешайте → скатайте шарики → в холодильник на 30 минут. По желанию — в растопленном кето-шоколаде."},
            {"uz": "<b>Kokos unidan keksiklar</b>\n⏱ 30 daqiqa · 🍽 10 dona\n<i>Kerak:</i> 60g kokos uni, 4 tuxum, 80ml kokos yog'i, 50g shirinlashtirgich, 1 ch.q. pishirish kukuni.\n<i>Tayyorlash:</i> Aralashgan xamir 5 daqiqa tursin (kokos uni suvni tortadi) → qoshiqda qolipga soling → 180°C da 20 daqiqa.",
             "ru": "<b>Кексы из кокосовой муки</b>\n⏱ 30 минут · 🍽 10 штук\n<i>Нужно:</i> 60г кокосовой муки, 4 яйца, 80мл кокосового масла, 50г подсластителя, 1 ч.л. разрыхлителя.\n<i>Как:</i> Дайте тесту постоять 5 минут (мука впитает влагу) → разложите ложкой по формам → 180°C, 20 минут."},
            {"uz": "<b>Kokosli smuzi</b>\n⏱ 5 daqiqa · 🍽 1 stakan\n<i>Kerak:</i> 200ml kokos suti, bir hovuch muzlatilgan meva, 1 osh q. chia, bir chimdim tuz.\n<i>Tayyorlash:</i> Blenderda 30 soniya uring. Chia 5 daqiqada quyuqlashtiradi — shoshmang, to'yimliroq bo'ladi.",
             "ru": "<b>Кокосовое смузи</b>\n⏱ 5 минут · 🍽 1 стакан\n<i>Нужно:</i> 200мл кокосового молока, горсть замороженных ягод, 1 ст.л. чиа, щепотка соли.\n<i>Как:</i> Взбейте 30 секунд. Чиа загустит за 5 минут — не спешите, будет сытнее."},
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
            {"uz": "<b>Zig'irli kraker — xrustaydigan gazak</b>\n⏱ 50 daqiqa · 🍽 1 laganda\n<i>Kerak:</i> 4 osh q. zig'ir urug'i, 4 osh q. suv, tuz, ziravor (sedana, kunjut).\n<i>Tayyorlash:</i> Urug'ni suvda 10 daqiqa bo'ktiring → pergamentda juda yupqa yoying → 150°C da 40 daqiqa quriting → siniq-siniq qiling.",
             "ru": "<b>Льняные крекеры — хрустящий снек</b>\n⏱ 50 минут · 🍽 1 противень\n<i>Нужно:</i> 4 ст.л. семян льна, 4 ст.л. воды, соль, специи (чернушка, кунжут).\n<i>Как:</i> Замочите на 10 минут → раскатайте очень тонко на пергаменте → 150°C, 40 минут → разломайте."},
            {"uz": "<b>1 daqiqalik zig'ir noni (mikroto'lqinda)</b>\n⏱ 3 daqiqa · 🍽 1 kishiga\n<i>Kerak:</i> 3 osh q. zig'ir uni, 1 tuxum, 1 ch.q. yog', bir chimdim soda va tuz.\n<i>Tayyorlash:</i> Krujkada aralashtiring → mikroto'lqinda 90 soniya → ag'daring, kesing. Sendvich uchun tayyor.",
             "ru": "<b>Льняной хлеб за 1 минуту (в микроволновке)</b>\n⏱ 3 минуты · 🍽 1 порция\n<i>Нужно:</i> 3 ст.л. льняной муки, 1 яйцо, 1 ч.л. масла, щепотка соды и соли.\n<i>Как:</i> Смешайте в кружке → 90 секунд в микроволновке → переверните, нарежьте. Готово для сэндвича."},
            {"uz": "<b>Zig'ir kisel — ertalabki ichimlik</b>\n⏱ 5 daqiqa + tun\n<i>Kerak:</i> 1 osh q. butun zig'ir urug'i, 250ml issiq suv.\n<i>Tayyorlash:</i> Kechqurun ustiga issiq suv quying, tunda qoldiring → ertalab och qoringa iching. Oshqozon shilliq qavatini yumshoq o'raydi.",
             "ru": "<b>Льняной кисель — утренний напиток</b>\n⏱ 5 минут + ночь\n<i>Нужно:</i> 1 ст.л. цельных семян льна, 250мл горячей воды.\n<i>Как:</i> Залейте вечером, оставьте на ночь → выпейте утром натощак. Мягко обволакивает слизистую желудка."},
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
            {"uz": "<b>Chia puding — kechqurun tayyorlang, ertalab nonushta</b>\n⏱ 5 daqiqa + tun\n<i>Kerak:</i> 3 osh q. chia, 200ml kokos yoki bodom suti, shirinlashtirgich, vanil.\n<i>Tayyorlash:</i> Aralashtiring, 10 daqiqadan keyin YANA aralashtiring (aks holda pastda qotib qoladi) → muzlatkichda tunab qolsin.",
             "ru": "<b>Чиа-пудинг — готовьте вечером, завтрак утром</b>\n⏱ 5 минут + ночь\n<i>Нужно:</i> 3 ст.л. чиа, 200мл кокосового или миндального молока, подсластитель, ваниль.\n<i>Как:</i> Смешайте, через 10 минут перемешайте ЕЩЁ РАЗ (иначе слипнется на дне) → в холодильник на ночь."},
            {"uz": "<b>Chia \"tuxumi\" — pishiriqlar uchun</b>\n⏱ 10 daqiqa\n<i>Kerak:</i> 1 osh q. maydalangan chia + 3 osh q. suv = 1 tuxum o'rniga.\n<i>Tayyorlash:</i> 10 daqiqa turing, gel hosil bo'lsin. Keks, non va pancake xamirini ajoyib bog'laydi.",
             "ru": "<b>Чиа-«яйцо» для выпечки</b>\n⏱ 10 минут\n<i>Нужно:</i> 1 ст.л. молотой чиа + 3 ст.л. воды = замена 1 яйца.\n<i>Как:</i> Дайте постоять 10 минут до геля. Отлично связывает тесто для кексов, хлеба и панкейков."},
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
            {"uz": "<b>Undirilgan yashil grechka</b>\n⏱ 10 daqiqa + 1 kun\n<i>Kerak:</i> 1 stakan yashil grechka, suv.\n<i>Tayyorlash:</i> 2 soat bo'ktiring → yaxshilab yuving → nam doka ostida 12-24 soat qoldiring, kuniga 2 marta yuving → salatga qo'shing. Vitaminlar bir necha barobar oshadi.",
             "ru": "<b>Пророщенная зелёная гречка</b>\n⏱ 10 минут + сутки\n<i>Нужно:</i> 1 стакан зелёной гречки, вода.\n<i>Как:</i> Замочите на 2 часа → тщательно промойте → под влажной марлей 12-24 часа, промывая дважды в день → в салат. Витаминов в разы больше."},
            {"uz": "<b>Grechka unidan blin</b>\n⏱ 20 daqiqa · 🍽 6 dona\n<i>Kerak:</i> 100g grechka uni, 2 tuxum, 150ml suv yoki sut, tuz.\n<i>Tayyorlash:</i> Suyuq xamir qiling, 10 daqiqa tursin → qizigan tovada yupqa qilib yoping. Tvorog yoki avokado bilan o'rang.",
             "ru": "<b>Блины из гречневой муки</b>\n⏱ 20 минут · 🍽 6 штук\n<i>Нужно:</i> 100г гречневой муки, 2 яйца, 150мл воды или молока, соль.\n<i>Как:</i> Жидкое тесто, дайте постоять 10 минут → жарьте тонко на горячей сковороде. Заверните творог или авокадо."},
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
            {"uz": "<b>Rastaropsha shroti — eng oddiy usul</b>\n⏱ 2 daqiqa\n<i>Kerak:</i> 1 ch.q. maydalangan rastaropsha urug'i, 200ml iliq suv.\n<i>Tayyorlash:</i> Ovqatdan 20 daqiqa oldin suv bilan iching. Ta'mi bir oz achchiq — asal yoki limon yumshatadi.",
             "ru": "<b>Шрот расторопши — самый простой способ</b>\n⏱ 2 минуты\n<i>Нужно:</i> 1 ч.л. молотых семян расторопши, 200мл тёплой воды.\n<i>Как:</i> Выпейте за 20 минут до еды. Вкус горьковатый — мёд или лимон смягчат."},
            {"uz": "<b>Rastaropsha unini non xamiriga qo'shish</b>\n⏱ —\n<i>Kerak:</i> 1-2 osh q. rastaropsha uni.\n<i>Tayyorlash:</i> Har qanday keto non yoki keks xamiriga qo'shing — ta'mga deyarli ta'sir qilmaydi, foydasi qoladi. 1 osh qoshiqdan boshlang.",
             "ru": "<b>Мука расторопши в тесто</b>\n⏱ —\n<i>Нужно:</i> 1-2 ст.л. муки расторопши.\n<i>Как:</i> Добавьте в тесто любого кето-хлеба или кекса — на вкус почти не влияет, польза остаётся. Начните с 1 ст.л."},
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
            {"uz": "<b>Keto konfet — 3 ta masalliq</b>\n⏱ 20 daqiqa · 🍽 10 dona\n<i>Kerak:</i> 4 osh q. yong'oq pastasi, 2 osh q. kokos yog'i, shirinlashtirgich.\n<i>Tayyorlash:</i> Aralashtiring → qoshiqda pergamentga tomizing → muzlatgichda 15 daqiqa. Muzlatkichda saqlang.",
             "ru": "<b>Кето-конфеты из 3 ингредиентов</b>\n⏱ 20 минут · 🍽 10 штук\n<i>Нужно:</i> 4 ст.л. ореховой пасты, 2 ст.л. кокосового масла, подсластитель.\n<i>Как:</i> Смешайте → выложите ложкой на пергамент → в морозилку на 15 минут. Храните в холодильнике."},
            {"uz": "<b>Pastali smuzi-bowl</b>\n⏱ 5 daqiqa · 🍽 1 kishiga\n<i>Kerak:</i> 1 osh q. yong'oq pastasi, 150ml kokos suti, muzlatilgan meva, chia.\n<i>Tayyorlash:</i> Blenderda uring → kosaga soling → ustiga kokos qirindisi va kakao nibs seping.",
             "ru": "<b>Смузи-боул с пастой</b>\n⏱ 5 минут · 🍽 1 порция\n<i>Нужно:</i> 1 ст.л. ореховой пасты, 150мл кокосового молока, замороженные ягоды, чиа.\n<i>Как:</i> Взбейте → в миску → посыпьте кокосовой стружкой и какао-крупкой."},
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
            {"uz": "<b>Uy sharoitida yong'oq pastasi</b>\n⏱ 15 daqiqa\n<i>Kerak:</i> 200g mag'iz, bir chimdim tuz.\n<i>Tayyorlash:</i> Blenderda uzluksiz maydalang — avval un, keyin xamir, 8-10 daqiqadan keyin o'zi yog' chiqarib pastaga aylanadi. Sabr qiling, yog' qo'shmang.",
             "ru": "<b>Ореховая паста дома</b>\n⏱ 15 минут\n<i>Нужно:</i> 200г ядер, щепотка соли.\n<i>Как:</i> Измельчайте в блендере без остановки — сначала мука, потом комок, через 8-10 минут выделится масло и получится паста. Терпение, масло не добавляйте."},
            {"uz": "<b>Fistashka unli keto pechene</b>\n⏱ 25 daqiqa · 🍽 12 dona\n<i>Kerak:</i> 150g fistashka uni, 1 tuxum, 50g sariyog', 40g eritritol.\n<i>Tayyorlash:</i> Aralashtiring → sharchalar yasab, bosib yassilang → 170°C da 15 daqiqa. Sovigach qattiqlashadi.",
             "ru": "<b>Кето-печенье из фисташковой муки</b>\n⏱ 25 минут · 🍽 12 штук\n<i>Нужно:</i> 150г фисташковой муки, 1 яйцо, 50г масла, 40г эритрита.\n<i>Как:</i> Смешайте → скатайте шарики, приплюсните → 170°C, 15 минут. Затвердеет при остывании."},
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
            {"uz": "<b>Farinata — no'xat kulchasi</b>\n⏱ 30 daqiqa + 2 soat\n<i>Kerak:</i> 100g no'xat uni, 300ml suv, 2 osh q. zaytun yog'i, tuz, rozmarin.\n<i>Tayyorlash:</i> Aralashtirib 2 soat tindiring va ko'pigini oling → yog'langan qolipga quying → 200°C da 20 daqiqa.",
             "ru": "<b>Фарината — нутовая лепёшка</b>\n⏱ 30 минут + 2 часа\n<i>Нужно:</i> 100г нутовой муки, 300мл воды, 2 ст.л. оливкового масла, соль, розмарин.\n<i>Как:</i> Смешайте, дайте постоять 2 часа, снимите пену → в смазанную форму → 200°C, 20 минут."},
            {"uz": "<b>Tuxumsiz \"omlet\"</b>\n⏱ 10 daqiqa · 🍽 1 kishiga\n<i>Kerak:</i> 4 osh q. no'xat uni, 100ml suv, tuz, murch, kurkuma.\n<i>Tayyorlash:</i> Suyuq xamir → qizigan tovada qopqoq ostida 4 daqiqa → ag'daring. Ichiga sabzavot qo'shsangiz bo'ladi.",
             "ru": "<b>«Омлет» без яиц</b>\n⏱ 10 минут · 🍽 1 порция\n<i>Нужно:</i> 4 ст.л. нутовой муки, 100мл воды, соль, перец, куркума.\n<i>Как:</i> Жидкое тесто → на горячую сковороду под крышкой 4 минуты → переверните. Можно добавить овощи."},
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
            {"uz": "<b>Guruch unli yupqa nonlar</b>\n⏱ 20 daqiqa · 🍽 6 dona\n<i>Kerak:</i> 150g guruch uni, 120ml issiq suv, 1 osh q. yog', tuz.\n<i>Tayyorlash:</i> Issiq suv bilan xamir qoring → 10 daqiqa dam bersin → yupqa yoyib quruq tovada har tomonini 1 daqiqadan yoping.",
             "ru": "<b>Тонкие лепёшки из рисовой муки</b>\n⏱ 20 минут · 🍽 6 штук\n<i>Нужно:</i> 150г рисовой муки, 120мл горячей воды, 1 ст.л. масла, соль.\n<i>Как:</i> Замесите на горячей воде → дайте отдохнуть 10 минут → раскатайте тонко и обжарьте на сухой сковороде по 1 минуте."},
            {"uz": "<b>Xrustaydigan qobiq (panirovka o'rniga)</b>\n⏱ —\n<i>Kerak:</i> guruch uni, tuz, ziravor.\n<i>Tayyorlash:</i> Tovuq yoki baliqni guruch uniga talqonlab qovuring — bug'doy panirovkasidan yengilroq va xrustaydiganroq chiqadi.",
             "ru": "<b>Хрустящая панировка</b>\n⏱ —\n<i>Нужно:</i> рисовая мука, соль, специи.\n<i>Как:</i> Обваляйте курицу или рыбу в рисовой муке и обжарьте — легче и хрустящее, чем пшеничная панировка."},
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
            {"uz": "<b>Qora guruchli salat</b>\n⏱ 40 daqiqa · 🍽 4 kishiga\n<i>Kerak:</i> 200g qora guruch, bodring, pomidor, ko'katlar, zaytun yog'i, olma sirkasi, tuz.\n<i>Tayyorlash:</i> Guruchni pishirib sovuting → sabzavot bilan aralashtiring → yog' va sirka sousi bilan ziravorlang. Ertasi kuniga ham yaxshi turadi.",
             "ru": "<b>Салат с чёрным рисом</b>\n⏱ 40 минут · 🍽 4 порции\n<i>Нужно:</i> 200г чёрного риса, огурец, помидор, зелень, оливковое масло, яблочный уксус, соль.\n<i>Как:</i> Отварите рис и охладите → смешайте с овощами → заправьте маслом с уксусом. Хорошо стоит и на следующий день."},
            {"uz": "<b>Bulgurli tabbule</b>\n⏱ 25 daqiqa · 🍽 4 kishiga\n<i>Kerak:</i> 150g bulgur, bir bog' petrushka, na'matak yoki limon sharbati, zaytun yog'i, piyoz, pomidor.\n<i>Tayyorlash:</i> Bulgurni qaynoq suvda 20 daqiqa bo'ktiring (pishirmang) → suvini siqing → maydalangan ko'kat va sabzavot bilan aralashtiring.",
             "ru": "<b>Табуле с булгуром</b>\n⏱ 25 минут · 🍽 4 порции\n<i>Нужно:</i> 150г булгура, пучок петрушки, сок лимона, оливковое масло, лук, помидор.\n<i>Как:</i> Залейте булгур кипятком на 20 минут (не варить) → отожмите → смешайте с рубленой зеленью и овощами."},
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
            {"uz": "<b>PP blinchiklar</b>\n⏱ 20 daqiqa · 🍽 8 dona\n<i>Kerak:</i> 120g PP un (ovsyanka/polba), 2 tuxum, 250ml sut yoki suv, tuz, shirinlashtirgich.\n<i>Tayyorlash:</i> Suyuq xamir qiling, 15 daqiqa tindiring → qizigan tovada yupqa yoping. Tvorog yoki asal bilan.",
             "ru": "<b>ПП-блинчики</b>\n⏱ 20 минут · 🍽 8 штук\n<i>Нужно:</i> 120г ПП-муки (овсяная/полба), 2 яйца, 250мл молока или воды, соль, подсластитель.\n<i>Как:</i> Жидкое тесто, дайте постоять 15 минут → жарьте тонко. С творогом или мёдом."},
            {"uz": "<b>Javdar unli PP non</b>\n⏱ 60 daqiqa · 🍽 1 non\n<i>Kerak:</i> 300g javdar uni, 200ml iliq suv, 1 ch.q. tuz, hamirturush yoki zakvaska.\n<i>Tayyorlash:</i> Qorib, 1 soat issiq joyda turing → qolipga soling → 200°C da 35 daqiqa. Ustiga kunjut yoki zig'ir seping.",
             "ru": "<b>ПП-хлеб из ржаной муки</b>\n⏱ 60 минут · 🍽 1 буханка\n<i>Нужно:</i> 300г ржаной муки, 200мл тёплой воды, 1 ч.л. соли, дрожжи или закваска.\n<i>Как:</i> Замесите, дайте подойти час в тепле → в форму → 200°C, 35 минут. Сверху кунжут или лён."},
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
            {"uz": "<b>Kepakli syrniki</b>\n⏱ 20 daqiqa · 🍽 8 dona\n<i>Kerak:</i> 200g tvorog, 1 tuxum, 2 osh q. kepak, shirinlashtirgich.\n<i>Tayyorlash:</i> Aralashtirib 5 daqiqa qo'yib turing (kepak bo'ksin) → kulchalar yasab kam yog'da qizarting. Ustiga tabiiy yogurt.",
             "ru": "<b>Сырники с отрубями</b>\n⏱ 20 минут · 🍽 8 штук\n<i>Нужно:</i> 200г творога, 1 яйцо, 2 ст.л. отрубей, подсластитель.\n<i>Как:</i> Смешайте и дайте постоять 5 минут (отруби набухнут) → сформируйте и обжарьте на малом масле. Сверху натуральный йогурт."},
            {"uz": "<b>Kepakli non (tovada)</b>\n⏱ 15 daqiqa · 🍽 1 kishiga\n<i>Kerak:</i> 3 osh q. kepak, 2 tuxum, 2 osh q. tvorog, tuz, soda.\n<i>Tayyorlash:</i> Aralashtirib qopqoq ostida past olovda 6 daqiqa → ag'daring, yana 4 daqiqa. Yengil, tolaga boy nonushta noni.",
             "ru": "<b>Хлеб с отрубями на сковороде</b>\n⏱ 15 минут · 🍽 1 порция\n<i>Нужно:</i> 3 ст.л. отрубей, 2 яйца, 2 ст.л. творога, соль, сода.\n<i>Как:</i> Смешайте, жарьте под крышкой на малом огне 6 минут → переверните, ещё 4. Лёгкий хлеб с клетчаткой."},
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
            {"uz": "<b>Zakvaskani jonlantirish</b>\n⏱ 5 daqiqa/kun · 3 kun\n<i>Kerak:</i> zakvaska, un, iliq suv.\n<i>Tayyorlash:</i> Har kuni 1:1:1 nisbatda un va suv bilan \"boqing\", xona haroratida qoldiring. 3-kuni ko'pikli va nordon hidli bo'lsa — tayyor.",
             "ru": "<b>Как оживить закваску</b>\n⏱ 5 минут в день · 3 дня\n<i>Нужно:</i> закваска, мука, тёплая вода.\n<i>Как:</i> Каждый день «кормите» в пропорции 1:1:1 мукой и водой, оставляйте при комнатной температуре. На 3-й день пенится и пахнет кисло — готова."},
            {"uz": "<b>Solodli qora non</b>\n⏱ 3 soat · 🍽 1 non\n<i>Kerak:</i> 400g javdar uni, 2 osh q. fermentlangan solod, 300ml iliq suv, zakvaska, tuz, koriandr.\n<i>Tayyorlash:</i> Solodni qaynoq suvda damlang → qolganini qo'shib qoring → 2 soat ko'tarilsin → 200°C da 45 daqiqa.",
             "ru": "<b>Чёрный хлеб на солоде</b>\n⏱ 3 часа · 🍽 1 буханка\n<i>Нужно:</i> 400г ржаной муки, 2 ст.л. ферментированного солода, 300мл тёплой воды, закваска, соль, кориандр.\n<i>Как:</i> Заварите солод кипятком → замесите с остальным → 2 часа на подъём → 200°C, 45 минут."},
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
            {"uz": "<b>Uy tahinisi</b>\n⏱ 15 daqiqa\n<i>Kerak:</i> 200g oq kunjut, 2 osh q. zaytun yog'i, tuz.\n<i>Tayyorlash:</i> Kunjutni quruq tovada 3-4 daqiqa qovuring (kuydirmang) → blenderda yog' bilan silliq bo'lguncha uring. Sousga ham, shirinlikka ham asos.",
             "ru": "<b>Домашняя тахини</b>\n⏱ 15 минут\n<i>Нужно:</i> 200г белого кунжута, 2 ст.л. оливкового масла, соль.\n<i>Как:</i> Обжарьте кунжут на сухой сковороде 3-4 минуты (не сжигая) → взбейте с маслом до гладкости. Основа и для соуса, и для десерта."},
            {"uz": "<b>Kunjutli gomasio (tuz o'rniga)</b>\n⏱ 10 daqiqa\n<i>Kerak:</i> 5 osh q. kunjut, 1 ch.q. Himalay tuzi.\n<i>Tayyorlash:</i> Kunjutni qovuring → tuz bilan birga yengil ezing. Har qanday taomga seping — tuzni 2 barobar kam ishlatasiz.",
             "ru": "<b>Гомасио — кунжут вместо соли</b>\n⏱ 10 минут\n<i>Нужно:</i> 5 ст.л. кунжута, 1 ч.л. гималайской соли.\n<i>Как:</i> Обжарьте кунжут → слегка раздавите вместе с солью. Посыпайте любые блюда — соли уйдёт вдвое меньше."},
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
            {"uz": "<b>Ziravorli qovurilgan urug'</b>\n⏱ 15 daqiqa\n<i>Kerak:</i> 100g qovoq urug'i, 1 ch.q. zaytun yog'i, tuz, paprika, kurkuma.\n<i>Tayyorlash:</i> Aralashtirib pergamentga yoying → 160°C da 12 daqiqa, bir marta aralashtiring. Gazak sifatida bankada saqlang.",
             "ru": "<b>Пряные жареные семечки</b>\n⏱ 15 минут\n<i>Нужно:</i> 100г тыквенных семечек, 1 ч.л. оливкового масла, соль, паприка, куркума.\n<i>Как:</i> Смешайте, выложите на пергамент → 160°C, 12 минут, разок перемешайте. Храните в банке как снек."},
            {"uz": "<b>Yashil песто (qovoq urug'ida)</b>\n⏱ 10 daqiqa\n<i>Kerak:</i> 50g qovoq urug'i, bir bog' rayhon yoki petrushka, 80ml zaytun yog'i, sarimsoq, tuz.\n<i>Tayyorlash:</i> Blenderda uring. Go'sht, baliq va sabzavotga ajoyib sous.",
             "ru": "<b>Зелёное песто на тыквенных семечках</b>\n⏱ 10 минут\n<i>Нужно:</i> 50г семечек, пучок базилика или петрушки, 80мл оливкового масла, чеснок, соль.\n<i>Как:</i> Взбейте блендером. Отличный соус к мясу, рыбе и овощам."},
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
            {"uz": "<b>Sedana + asal aralashmasi</b>\n⏱ 5 daqiqa\n<i>Kerak:</i> 1 ch.q. maydalangan sedana, 2 osh q. asal.\n<i>Tayyorlash:</i> Aralashtiring, bankada saqlang. Ertalab och qoringa yarim choy qoshiq iliq suv bilan.",
             "ru": "<b>Смесь чёрного тмина с мёдом</b>\n⏱ 5 минут\n<i>Нужно:</i> 1 ч.л. молотого тмина, 2 ст.л. мёда.\n<i>Как:</i> Смешайте, храните в банке. Утром натощак половину чайной ложки с тёплой водой."},
            {"uz": "<b>Sedanali non ziravori</b>\n⏱ —\n<i>Kerak:</i> 1 ch.q. butun sedana.\n<i>Tayyorlash:</i> Non yoki kraker xamirining ustiga seping. Pishganda o'ziga xos achchiqroq, yong'oqsimon aromat beradi.",
             "ru": "<b>Чёрный тмин как посыпка для хлеба</b>\n⏱ —\n<i>Нужно:</i> 1 ч.л. цельных семян.\n<i>Как:</i> Посыпьте тесто хлеба или крекеров. При выпекании даёт характерный пряно-ореховый аромат."},
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
            {"uz": "<b>Psilliumli keto non</b>\n⏱ 60 daqiqa · 🍽 1 non\n<i>Kerak:</i> 150g bodom uni, 3 osh q. psillium, 4 tuxum oqi, 1 ch.q. soda, 1 osh q. olma sirkasi, 200ml issiq suv, tuz.\n<i>Tayyorlash:</i> Quruqni aralashtiring → oqsil va sirkani qo'shing → issiq suv quying, tez qoring → non shakliga soling → 180°C da 50 daqiqa.",
             "ru": "<b>Кето-хлеб с псиллиумом</b>\n⏱ 60 минут · 🍽 1 буханка\n<i>Нужно:</i> 150г миндальной муки, 3 ст.л. псиллиума, 4 белка, 1 ч.л. соды, 1 ст.л. яблочного уксуса, 200мл горячей воды, соль.\n<i>Как:</i> Смешайте сухое → добавьте белки и уксус → влейте горячую воду, быстро вымесите → сформуйте → 180°C, 50 минут."},
            {"uz": "<b>Ksantanli quyuq sous</b>\n⏱ 5 daqiqa\n<i>Kerak:</i> 250ml bulon yoki qaymoq, 1/4 ch.q. ksantan kamedi.\n<i>Tayyorlash:</i> Ksantanni suyuqlik ustiga SEKIN seping va darhol venchik bilan uring — birdaniga solsangiz to'p bo'lib qoladi. Un va kraxmalsiz quyuq sous tayyor.",
             "ru": "<b>Густой соус на ксантане</b>\n⏱ 5 минут\n<i>Нужно:</i> 250мл бульона или сливок, 1/4 ч.л. ксантановой камеди.\n<i>Как:</i> Всыпайте ксантан МЕДЛЕННО и сразу взбивайте венчиком — высыпете сразу, будут комки. Густой соус без муки и крахмала готов."},
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
            {"uz": "<b>Muzqaymoqli keto affogato</b>\n⏱ 3 daqiqa · 🍽 1 kishiga\n<i>Kerak:</i> 1 porsiya keto muzqaymoq, 1 shot issiq qahva (yoki kuchli kakao).\n<i>Tayyorlash:</i> Muzqaymoqni stakanga soling → ustidan issiq qahvani quying → darhol yeng. Italyancha desert, shakarsiz.",
             "ru": "<b>Кето-аффогато с мороженым</b>\n⏱ 3 минуты · 🍽 1 порция\n<i>Нужно:</i> 1 порция кето-мороженого, 1 шот горячего кофе (или крепкого какао).\n<i>Как:</i> Мороженое в стакан → залейте горячим кофе → сразу подавайте. Итальянский десерт без сахара."},
            {"uz": "<b>Keto muzqaymoq-bowl</b>\n⏱ 5 daqiqa · 🍽 1 kishiga\n<i>Kerak:</i> 1 porsiya keto muzqaymoq, 1 osh q. yong'oq pastasi, kokos chipsi yoki kakao nibs, bir hovuch rezavor.\n<i>Tayyorlash:</i> Kosaga muzqaymoqni soling → pastani ustidan quying → chips va rezavor seping. Dam olish kunining shirinligi.",
             "ru": "<b>Кето-боул с мороженым</b>\n⏱ 5 минут · 🍽 1 порция\n<i>Нужно:</i> 1 порция кето-мороженого, 1 ст.л. ореховой пасты, кокосовые чипсы или какао-крупка, горсть ягод.\n<i>Как:</i> Мороженое в миску → полейте пастой → посыпьте чипсами и ягодами. Десерт выходного дня."},
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
            {"uz": "<b>Shokoladli keto mug-keks (mikroto'lqinda)</b>\n⏱ 5 daqiqa · 🍽 1 kishiga\n<i>Kerak:</i> 3 osh q. bodom uni, 1 tuxum, 1 osh q. eritilgan sariyog', 1 osh q. shirinlashtirgich, 30g qora shokolad granula, bir chimdim pishirish kukuni.\n<i>Tayyorlash:</i> Krujkada aralashtiring, granulaning yarmini ichiga, yarmini ustiga soling → mikroto'lqinda 70 soniya. Ichi erigan shokoladli bo'ladi.",
             "ru": "<b>Шоколадный кето-кекс в кружке</b>\n⏱ 5 минут · 🍽 1 порция\n<i>Нужно:</i> 3 ст.л. миндальной муки, 1 яйцо, 1 ст.л. топлёного масла, 1 ст.л. подсластителя, 30г гранул тёмного шоколада, щепотка разрыхлителя.\n<i>Как:</i> Смешайте в кружке, половину гранул внутрь, половину сверху → 70 секунд в микроволновке. Внутри — расплавленный шоколад."},
            {"uz": "<b>Shokoladli kokos konfeti (3 masalliq)</b>\n⏱ 20 daqiqa · 🍽 12 dona\n<i>Kerak:</i> 100g qora shokolad (70%+ yoki shakarsiz), 60g kokos qirindisi, bir chimdim tuz.\n<i>Tayyorlash:</i> Shokoladni suv hammomida eriting → qirindi bilan aralashtiring → qoshiqda pergamentga tomizing → muzlatkichda 15 daqiqa.",
             "ru": "<b>Шоколадно-кокосовые конфеты из 3 ингредиентов</b>\n⏱ 20 минут · 🍽 12 штук\n<i>Нужно:</i> 100г тёмного шоколада (70%+ или без сахара), 60г кокосовой стружки, щепотка соли.\n<i>Как:</i> Растопите шоколад на водяной бане → смешайте со стружкой → выложите ложкой на пергамент → 15 минут в холодильник."},
            {"uz": "<b>Keto issiq shokolad</b>\n⏱ 10 daqiqa · 🍽 1 stakan\n<i>Kerak:</i> 200ml kokos suti, 1 osh q. kakao, eritritol, bir chimdim tuz, dolchin.\n<i>Tayyorlash:</i> Isiting va venchik bilan uring — ko'pik hosil bo'lsin. Kechqurungi shirinlik istagini bosadi.",
             "ru": "<b>Кето горячий шоколад</b>\n⏱ 10 минут · 🍽 1 стакан\n<i>Нужно:</i> 200мл кокосового молока, 1 ст.л. какао, эритрит, щепотка соли, корица.\n<i>Как:</i> Подогрейте и взбейте венчиком до пенки. Снимает вечернюю тягу к сладкому."},
            {"uz": "<b>Kakao nibsli keto plitka</b>\n⏱ 20 daqiqa · 🍽 8 bo'lak\n<i>Kerak:</i> 100g kokos yog'i, 3 osh q. kakao kukuni, 2 osh q. kakao nibs, shirinlashtirgich, tuz.\n<i>Tayyorlash:</i> Yog'ni eriting → kakao va shirinlashtirgichni aralashtiring → nibsni seping → qolipda muzlatkichda 15 daqiqa.",
             "ru": "<b>Кето-плитка с какао-крупкой</b>\n⏱ 20 минут · 🍽 8 кусочков\n<i>Нужно:</i> 100г кокосового масла, 3 ст.л. какао-порошка, 2 ст.л. какао-крупки, подсластитель, соль.\n<i>Как:</i> Растопите масло → вмешайте какао и подсластитель → всыпьте крупку → в форму, в холодильник на 15 минут."},
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
            {"uz": "<b>Losos salati (5 daqiqa)</b>\n⏱ 5 daqiqa · 🍽 2 kishiga\n<i>Kerak:</i> 1 banka losos, avokado, bodring, zaytun yog'i, limon, tuz.\n<i>Tayyorlash:</i> Baliqni vilka bilan ezing → sabzavotni to'g'rab qo'shing → yog' va limon bilan ziravorlang. Keto tushlik tayyor.",
             "ru": "<b>Салат с лососем за 5 минут</b>\n⏱ 5 минут · 🍽 2 порции\n<i>Нужно:</i> 1 банка лосося, авокадо, огурец, оливковое масло, лимон, соль.\n<i>Как:</i> Разомните рыбу вилкой → добавьте нарезанные овощи → заправьте маслом и лимоном. Кето-обед готов."},
            {"uz": "<b>Losos kotletlari (unsiz)</b>\n⏱ 20 daqiqa · 🍽 6 dona\n<i>Kerak:</i> 1 banka losos, 1 tuxum, 2 osh q. psillium yoki zig'ir uni, piyoz, ko'kat.\n<i>Tayyorlash:</i> Aralashtirib 10 daqiqa qo'ying (bog'lansin) → kotlet yasab kam yog'da har tomonini 3 daqiqadan qizarting.",
             "ru": "<b>Котлеты из лосося без муки</b>\n⏱ 20 минут · 🍽 6 штук\n<i>Нужно:</i> 1 банка лосося, 1 яйцо, 2 ст.л. псиллиума или льняной муки, лук, зелень.\n<i>Как:</i> Смешайте и дайте постоять 10 минут (свяжется) → сформуйте и обжарьте по 3 минуты с каждой стороны."},
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
            {"uz": "<b>Keto salat sousi</b>\n⏱ 3 daqiqa\n<i>Kerak:</i> 3 osh q. zaytun yog'i, 1 osh q. olma sirkasi, tuz, murch, 1 ch.q. xantal.\n<i>Tayyorlash:</i> Bankaga solib qattiq chayqating — emulsiya hosil bo'ladi va ajralmay turadi. Muzlatkichda 1 hafta turadi.",
             "ru": "<b>Кето-заправка для салата</b>\n⏱ 3 минуты\n<i>Нужно:</i> 3 ст.л. оливкового масла, 1 ст.л. яблочного уксуса, соль, перец, 1 ч.л. горчицы.\n<i>Как:</i> Взболтайте в банке до эмульсии — не расслоится. Хранится неделю в холодильнике."},
            {"uz": "<b>GHEE da qovurilgan tuxum va avokado</b>\n⏱ 8 daqiqa · 🍽 1 kishiga\n<i>Kerak:</i> 1 osh q. GHEE, 2 tuxum, yarim avokado, Himalay tuzi.\n<i>Tayyorlash:</i> GHEE ni qizdiring → tuxumni past olovda qovuring → avokado bilan tarelkaga, tuz seping. To'yimli keto nonushta.",
             "ru": "<b>Яйца на ГХИ с авокадо</b>\n⏱ 8 минут · 🍽 1 порция\n<i>Нужно:</i> 1 ст.л. ГХИ, 2 яйца, половина авокадо, гималайская соль.\n<i>Как:</i> Разогрейте ГХИ → жарьте яйца на малом огне → подайте с авокадо, посолите. Сытный кето-завтрак."},
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
            {"uz": "<b>Ertalabki tetiklashtiruvchi ichimlik</b>\n⏱ 2 daqiqa\n<i>Kerak:</i> 1 stakan suv, 1 ch.q. olma sirkasi, bir chimdim Himalay tuzi, xohlasangiz eritritol.\n<i>Tayyorlash:</i> Aralashtiring va ovqatdan 15 daqiqa oldin iching. Naycha bilan ichsangiz tishga yumshoqroq.",
             "ru": "<b>Утренний бодрящий напиток</b>\n⏱ 2 минуты\n<i>Нужно:</i> 1 стакан воды, 1 ч.л. яблочного уксуса, щепотка гималайской соли, по желанию эритрит.\n<i>Как:</i> Смешайте и выпейте за 15 минут до еды. Через трубочку — бережнее для зубов."},
            {"uz": "<b>Tez marinad</b>\n⏱ 30 daqiqa\n<i>Kerak:</i> bodring/karam/piyoz, 100ml suv, 3 osh q. olma sirkasi, tuz, murch.\n<i>Tayyorlash:</i> To'g'rab, marinadga soling, 30 daqiqa turing. Yog'li taomlarga yengil, nordon garnitura.",
             "ru": "<b>Быстрый маринад</b>\n⏱ 30 минут\n<i>Нужно:</i> огурцы/капуста/лук, 100мл воды, 3 ст.л. яблочного уксуса, соль, перец.\n<i>Как:</i> Нарежьте, залейте, дайте постоять 30 минут. Лёгкий кислый гарнир к жирным блюдам."},
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
            {"uz": "<b>Uy elektrolit ichimligi</b>\n⏱ 3 daqiqa · 🍽 500ml\n<i>Kerak:</i> 500ml suv, 1/4 ch.q. Himalay tuzi, yarim limon sharbati, ozgina eritritol.\n<i>Tayyorlash:</i> Aralashtirib kun davomida ho'plab iching. Ayniqsa keto boshida va issiq kunlarda foydali.",
             "ru": "<b>Домашний электролитный напиток</b>\n⏱ 3 минуты · 🍽 500мл\n<i>Нужно:</i> 500мл воды, 1/4 ч.л. гималайской соли, сок половины лимона, немного эритрита.\n<i>Как:</i> Смешайте и пейте глотками в течение дня. Особенно полезно в начале кето и в жару."},
            {"uz": "<b>Tuzli karamel ta'mi siri</b>\n⏱ —\n<i>Kerak:</i> bir chimdim Himalay tuzi.\n<i>Tayyorlash:</i> Har qanday keto shirinlikka (shokolad, keks, puding) bir chimdim tuz qo'shing — shirinlik ta'mi kuchayadi va chuqurlashadi.",
             "ru": "<b>Секрет вкуса солёной карамели</b>\n⏱ —\n<i>Нужно:</i> щепотка гималайской соли.\n<i>Как:</i> Добавьте щепотку в любой кето-десерт (шоколад, кекс, пудинг) — сладость станет ярче и глубже."},
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
            {"uz": "<b>Shakarsiz karamel sousi</b>\n⏱ 10 daqiqa\n<i>Kerak:</i> 80g alluloza, 40g sariyog', 60ml qaymoq, bir chimdim tuz.\n<i>Tayyorlash:</i> Allulozani past olovda eriting (jigarrang bo'lguncha) → sariyog', keyin qaymoqni qo'shing → tuz seping. Eritritol bu yerda ishlamaydi — u karamellashmaydi.",
             "ru": "<b>Карамельный соус без сахара</b>\n⏱ 10 минут\n<i>Нужно:</i> 80г аллюлозы, 40г масла, 60мл сливок, щепотка соли.\n<i>Как:</i> Растопите аллюлозу на малом огне до янтарного цвета → добавьте масло, затем сливки → посолите. Эритрит здесь не подойдёт — он не карамелизуется."},
            {"uz": "<b>Shirin qaymoq krem</b>\n⏱ 5 daqiqa\n<i>Kerak:</i> 200ml sovuq qaymoq, 2 osh q. maydalangan eritritol, vanil.\n<i>Tayyorlash:</i> Sovuq idishda qattiq ko'pik bo'lguncha uring. Eritritol albatta maydalangan bo'lsin, aks holda g'ijirlaydi.",
             "ru": "<b>Сладкий сливочный крем</b>\n⏱ 5 минут\n<i>Нужно:</i> 200мл холодных сливок, 2 ст.л. молотого эритрита, ваниль.\n<i>Как:</i> Взбейте в холодной миске до устойчивых пиков. Эритрит обязательно молотый, иначе будет хрустеть."},
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
            {"uz": "<b>Tomoq uchun issiq ichimlik</b>\n⏱ 5 daqiqa\n<i>Kerak:</i> iliq suv, 1 ch.q. asal, yarim limon, ozgina zanjabil.\n<i>Tayyorlash:</i> Suv ilimiq bo'lganda asalni qo'shing. Sovuq kunlarda immunitet uchun.",
             "ru": "<b>Тёплый напиток для горла</b>\n⏱ 5 минут\n<i>Нужно:</i> тёплая вода, 1 ч.л. мёда, половина лимона, немного имбиря.\n<i>Как:</i> Добавляйте мёд, когда вода станет тёплой, а не горячей. Для иммунитета в холода."},
            {"uz": "<b>Asalli yong'oq aralashmasi</b>\n⏱ 10 daqiqa\n<i>Kerak:</i> 200g turli mag'iz, 4 osh q. asal, 1 ch.q. dolchin.\n<i>Tayyorlash:</i> Mag'izni yirik to'g'rab asal bilan aralashtiring → bankada saqlang. Ertalab 1 osh qoshiq — energiya uchun.",
             "ru": "<b>Ореховая смесь с мёдом</b>\n⏱ 10 минут\n<i>Нужно:</i> 200г разных орехов, 4 ст.л. мёда, 1 ч.л. корицы.\n<i>Как:</i> Крупно порубите орехи и смешайте с мёдом → храните в банке. Утром 1 ст.л. для энергии."},
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
            {"uz": "<b>Fenxel choyi</b>\n⏱ 10 daqiqa\n<i>Kerak:</i> 1 ch.q. arpabodiyon urug'i, 250ml qaynoq suv.\n<i>Tayyorlash:</i> Urug'ni yengil ezib, qaynoq suvda 7 daqiqa damlang. Kechki ovqatdan keyin iching.",
             "ru": "<b>Фенхелевый чай</b>\n⏱ 10 минут\n<i>Нужно:</i> 1 ч.л. семян фенхеля, 250мл кипятка.\n<i>Как:</i> Слегка раздавите семена и заварите 7 минут. Пейте после ужина."},
            {"uz": "<b>Uy ziravor aralashmasi</b>\n⏱ 5 daqiqa\n<i>Kerak:</i> arpabodiyon, koriandr, zira, qora murch — teng miqdorda.\n<i>Tayyorlash:</i> Quruq tovada 2 daqiqa qovuring → maydalang. Go'sht, sabzavot va tuxumga seping.",
             "ru": "<b>Домашняя смесь специй</b>\n⏱ 5 минут\n<i>Нужно:</i> фенхель, кориандр, зира, чёрный перец — поровну.\n<i>Как:</i> Прогрейте на сухой сковороде 2 минуты → смелите. Посыпайте мясо, овощи и яйца."},
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
            {"uz": "<b>Universal keto pancake</b>\n⏱ 15 daqiqa · 🍽 6 dona\n<i>Kerak:</i> 100g keto un, 2 tuxum, 80ml sut yoki suv, 1 ch.q. pishirish kukuni, tuz, shirinlashtirgich.\n<i>Tayyorlash:</i> Aralashtiring, xamir quyuq smetana holida bo'lsin (kerak bo'lsa suv qo'shing) → kam yog'da har tomonini 2 daqiqadan qizarting.",
             "ru": "<b>Универсальные кето-панкейки</b>\n⏱ 15 минут · 🍽 6 штук\n<i>Нужно:</i> 100г кето-муки, 2 яйца, 80мл молока или воды, 1 ч.л. разрыхлителя, соль, подсластитель.\n<i>Как:</i> Смешайте до густоты сметаны (при необходимости добавьте воды) → обжарьте по 2 минуты с каждой стороны."},
            {"uz": "<b>Keto kraker (har qanday keto undan)</b>\n⏱ 30 daqiqa · 🍽 1 laganda\n<i>Kerak:</i> 150g keto un, 1 tuxum, 2 osh q. yog', tuz, kunjut yoki ziravor.\n<i>Tayyorlash:</i> Qattiq xamir qoring → ikki pergament orasida yupqa yoying → kvadratlarga kesing → 170°C da 15-18 daqiqa.",
             "ru": "<b>Кето-крекеры из любой кето-муки</b>\n⏱ 30 минут · 🍽 1 противень\n<i>Нужно:</i> 150г кето-муки, 1 яйцо, 2 ст.л. масла, соль, кунжут или специи.\n<i>Как:</i> Замесите плотное тесто → раскатайте тонко между двумя листами пергамента → нарежьте квадратами → 170°C, 15-18 минут."},
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
            {"uz": "<b>Urug'li salat sepkisi</b>\n⏱ 10 daqiqa\n<i>Kerak:</i> 3-4 xil urug', bir chimdim tuz, ziravor.\n<i>Tayyorlash:</i> Urug'larni quruq tovada yengil qovuring → tuz va ziravor bilan aralashtiring → bankada saqlang. Salat, sho'rva va tuxumga seping.",
             "ru": "<b>Посыпка из семян для салатов</b>\n⏱ 10 минут\n<i>Нужно:</i> 3-4 вида семян, щепотка соли, специи.\n<i>Как:</i> Слегка прогрейте семена на сухой сковороде → смешайте с солью и специями → храните в банке. Посыпайте салаты, супы и яйца."},
            {"uz": "<b>Urug'li energiya sharikalari</b>\n⏱ 15 daqiqa · 🍽 12 dona\n<i>Kerak:</i> 100g urug', 3 osh q. yong'oq pastasi, 1 osh q. kokos yog'i, shirinlashtirgich.\n<i>Tayyorlash:</i> Aralashtirib sharikalar yasang → muzlatkichda 20 daqiqa. Ish kunida sog'lom gazak.",
             "ru": "<b>Энергетические шарики из семян</b>\n⏱ 15 минут · 🍽 12 штук\n<i>Нужно:</i> 100г семян, 3 ст.л. ореховой пасты, 1 ст.л. кокосового масла, подсластитель.\n<i>Как:</i> Смешайте, скатайте шарики → 20 минут в холодильник. Здоровый перекус в рабочий день."},
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
            {"uz": "<b>Ertalabki tola kokteyli</b>\n⏱ 3 daqiqa\n<i>Kerak:</i> 250ml suv yoki kefir, 1 ch.q. tolali qo'shimcha, limon sharbati.\n<i>Tayyorlash:</i> Tez aralashtirib darhol iching (quyuqlashib qoladi), keyin yana bir stakan suv iching.",
             "ru": "<b>Утренний коктейль с клетчаткой</b>\n⏱ 3 минуты\n<i>Нужно:</i> 250мл воды или кефира, 1 ч.л. добавки с клетчаткой, лимонный сок.\n<i>Как:</i> Быстро размешайте и сразу выпейте (загустеет), затем выпейте ещё стакан воды."},
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
            {"uz": "<b>5 daqiqalik keto desert</b>\n⏱ 5 daqiqa · 🍽 1 kishiga\n<i>Kerak:</i> 150g grek yogurti yoki tvorog, 1 osh q. tayyor mahsulotingiz (shokolad granula, chips, nibs), shirinlashtirgich.\n<i>Tayyorlash:</i> Yogurtni shirinlashtirgich bilan uring → kosaga soling → ustiga seping. Kechki shirinlik istagi uchun.",
             "ru": "<b>Кето-десерт за 5 минут</b>\n⏱ 5 минут · 🍽 1 порция\n<i>Нужно:</i> 150г греческого йогурта или творога, 1 ст.л. вашего готового продукта (шоколадная гранула, чипсы, крупка), подсластитель.\n<i>Как:</i> Взбейте йогурт с подсластителем → в миску → посыпьте сверху. Против вечерней тяги к сладкому."},
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
        {"uz": "<b>Sog'lom kosa (buddha bowl)</b>\n⏱ 15 daqiqa · 🍽 1 kishiga\n<i>Kerak:</i> yashil barglar, qaynatilgan tuxum yoki tovuq, avokado, urug'lar, zaytun yog'i + olma sirkasi sousi.\n<i>Tayyorlash:</i> Hammasini kosaga joylashtiring → sous bilan ziravorlang. Tez, to'yimli va muvozanatli tushlik.",
         "ru": "<b>Здоровая тарелка (боул)</b>\n⏱ 15 минут · 🍽 1 порция\n<i>Нужно:</i> зелень, варёное яйцо или курица, авокадо, семена, заправка из масла и яблочного уксуса.\n<i>Как:</i> Разложите в миске → заправьте. Быстрый, сытный и сбалансированный обед."},
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
            "uz": "<b>Keto brauni</b>\n⏱ 35 daqiqa · 🍽 9 bo'lak\n<i>Kerak:</i> 100g bodom uni, 40g kakao, 80g eritritol, 3 tuxum, 100g eritilgan sariyog', bir chimdim tuz.\n<i>Tayyorlash:</i> Tuxum va shirinlashtirgichni ko'piklanguncha uring → yog'ni quying → un va kakaoni elab qo'shing → 175°C da 22 daqiqa. Markazi biroz nam qolsin, sovigach o'zi yetiladi.",
            "ru": "<b>Кето-брауни</b>\n⏱ 35 минут · 🍽 9 кусочков\n<i>Нужно:</i> 100г миндальной муки, 40г какао, 80г эритрита, 3 яйца, 100г топлёного масла, щепотка соли.\n<i>Как:</i> Взбейте яйца с подсластителем до пены → влейте масло → просейте муку с какао → 175°C, 22 минуты. Середина пусть остаётся слегка влажной, дойдёт при остывании."},
    },
    {
        "needs": {"almond_flour", "coconut", "sweeteners"},
        "recipe": {
            "uz": "<b>Bodom-kokos keksi</b>\n⏱ 40 daqiqa · 🍽 8 bo'lak\n<i>Kerak:</i> 150g bodom uni, 40g kokos uni, 50g kokos qirindisi, 70g eritritol, 4 tuxum, 80ml kokos yog'i, 1 ch.q. pishirish kukuni.\n<i>Tayyorlash:</i> Quruq qismni aralashtirib 5 daqiqa qo'ying (kokos uni namni tortsin) → tuxum va yog'ni qo'shing → 180°C da 30 daqiqa. Ustiga qirindi seping.",
            "ru": "<b>Миндально-кокосовый кекс</b>\n⏱ 40 минут · 🍽 8 кусочков\n<i>Нужно:</i> 150г миндальной муки, 40г кокосовой муки, 50г стружки, 70г эритрита, 4 яйца, 80мл кокосового масла, 1 ч.л. разрыхлителя.\n<i>Как:</i> Смешайте сухое и дайте постоять 5 минут (кокосовая мука впитает влагу) → добавьте яйца и масло → 180°C, 30 минут. Посыпьте стружкой."},
    },
    {
        "needs": {"flax", "fiber_supp"},
        "recipe": {
            "uz": "<b>Eng yaxshi keto non (zig'ir + psillium)</b>\n⏱ 70 daqiqa · 🍽 1 non\n<i>Kerak:</i> 120g zig'ir uni, 3 osh q. psillium, 4 tuxum oqi, 1 ch.q. soda, 1 osh q. olma sirkasi, 250ml issiq suv, tuz.\n<i>Tayyorlash:</i> Quruqni aralashtiring → oqsil va sirkani qo'shing → issiq suvni quyib TEZ qoring (psillium darhol ushlaydi) → non shaklini bering → 180°C da 55 daqiqa. Butunlay sovugach kesing.",
            "ru": "<b>Лучший кето-хлеб (лён + псиллиум)</b>\n⏱ 70 минут · 🍽 1 буханка\n<i>Нужно:</i> 120г льняной муки, 3 ст.л. псиллиума, 4 белка, 1 ч.л. соды, 1 ст.л. яблочного уксуса, 250мл горячей воды, соль.\n<i>Как:</i> Смешайте сухое → добавьте белки и уксус → влейте горячую воду и БЫСТРО вымесите (псиллиум схватывает сразу) → сформуйте → 180°C, 55 минут. Режьте полностью остывшим."},
    },
    {
        "needs": {"chia", "coconut", "sweeteners"},
        "recipe": {
            "uz": "<b>Kokosli chia puding (3 qatlamli)</b>\n⏱ 10 daqiqa + tun\n<i>Kerak:</i> 4 osh q. chia, 300ml kokos suti, 2 osh q. eritritol, kokos qirindisi, vanil.\n<i>Tayyorlash:</i> Chiani sut va shirinlashtirgich bilan aralashtiring, 10 daqiqadan keyin YANA aralashtiring → stakanlarga qatlab soling, orasiga qirindi seping → tunda muzlatkichda. Ertalab tayyor nonushta.",
            "ru": "<b>Кокосовый чиа-пудинг в 3 слоя</b>\n⏱ 10 минут + ночь\n<i>Нужно:</i> 4 ст.л. чиа, 300мл кокосового молока, 2 ст.л. эритрита, стружка, ваниль.\n<i>Как:</i> Смешайте чиа с молоком и подсластителем, через 10 минут перемешайте ЕЩЁ РАЗ → разложите в стаканы слоями со стружкой → на ночь в холодильник. Утром завтрак готов."},
    },
    {
        "needs": {"coconut", "cacao", "sweeteners"},
        "recipe": {
            "uz": "<b>Uy keto shokoladi</b>\n⏱ 20 daqiqa · 🍽 1 plitka\n<i>Kerak:</i> 100g kokos yog'i, 50g kakao kukuni, 40g maydalangan eritritol, bir chimdim tuz, vanil.\n<i>Tayyorlash:</i> Yog'ni suv hammomida eriting (qaynatmang) → kakao va shirinlashtirgichni elab aralashtiring → qolipga quying → muzlatkichda 20 daqiqa. Muzlatkichda saqlang: xona haroratida yumshaydi.",
            "ru": "<b>Домашний кето-шоколад</b>\n⏱ 20 минут · 🍽 1 плитка\n<i>Нужно:</i> 100г кокосового масла, 50г какао, 40г молотого эритрита, щепотка соли, ваниль.\n<i>Как:</i> Растопите масло на водяной бане (не кипятите) → вмешайте просеянное какао с подсластителем → в форму → 20 минут в холодильник. Хранить в холоде: при комнатной температуре мягчает."},
    },
    {
        "needs": {"pastes", "cacao", "sweeteners"},
        "recipe": {
            "uz": "<b>Keto \"Snickers\" konfeti</b>\n⏱ 30 daqiqa · 🍽 10 dona\n<i>Kerak:</i> 4 osh q. yeryong'oq pastasi, 2 osh q. kokos yog'i, shirinlashtirgich, qoplama uchun 50g kakao + 50g yog', tuz.\n<i>Tayyorlash:</i> Pasta, yog' va shirinlashtirgichni aralashtirib batonchalar yasang → 15 daqiqa muzlatgichda → erigan kakao qoplamasiga bo'ktiring → yana 10 daqiqa. Ustiga bir chimdim tuz.",
            "ru": "<b>Кето-«Сникерс»</b>\n⏱ 30 минут · 🍽 10 штук\n<i>Нужно:</i> 4 ст.л. арахисовой пасты, 2 ст.л. кокосового масла, подсластитель, на глазурь 50г какао + 50г масла, соль.\n<i>Как:</i> Смешайте пасту, масло и подсластитель, сформуйте батончики → 15 минут в морозилку → окуните в растопленную глазурь → ещё 10 минут. Сверху щепотка соли."},
    },
    {
        "needs": {"oils", "vinegar", "salt"},
        "recipe": {
            "uz": "<b>Mukammal salat sousi (bir haftaga)</b>\n⏱ 5 daqiqa · 🍽 250ml\n<i>Kerak:</i> 150ml zaytun yog'i, 50ml olma sirkasi, 1 ch.q. xantal, 1/2 ch.q. Himalay tuzi, murch, sarimsoq.\n<i>Tayyorlash:</i> Hammasini bankaga solib 30 soniya qattiq chayqating → muzlatkichda saqlang, ishlatishdan oldin yana chayqating. Har kuni yangi sous tayyorlash shart emas.",
            "ru": "<b>Идеальная заправка на неделю</b>\n⏱ 5 минут · 🍽 250мл\n<i>Нужно:</i> 150мл оливкового масла, 50мл яблочного уксуса, 1 ч.л. горчицы, 1/2 ч.л. гималайской соли, перец, чеснок.\n<i>Как:</i> Всё в банку, встряхивайте 30 секунд → храните в холодильнике, взбалтывайте перед подачей. Каждый день делать заново не нужно."},
    },
    {
        "needs": {"bran", "sesame", "flax"},
        "recipe": {
            "uz": "<b>Tolaga boy kraker</b>\n⏱ 45 daqiqa · 🍽 1 laganda\n<i>Kerak:</i> 3 osh q. kepak, 3 osh q. zig'ir urug'i, 2 osh q. kunjut, 120ml suv, tuz.\n<i>Tayyorlash:</i> Aralashtirib 15 daqiqa bo'ktiring (quyuq bo'tqa bo'lsin) → pergamentda 3mm yupqalikda yoying, kvadratlarga chizing → 150°C da 35 daqiqa. Bankada 2 hafta turadi.",
            "ru": "<b>Крекеры с высокой клетчаткой</b>\n⏱ 45 минут · 🍽 1 противень\n<i>Нужно:</i> 3 ст.л. отрубей, 3 ст.л. семян льна, 2 ст.л. кунжута, 120мл воды, соль.\n<i>Как:</i> Смешайте и дайте набухнуть 15 минут (густая каша) → раскатайте 3мм на пергаменте, наметьте квадраты → 150°C, 35 минут. В банке хранятся 2 недели."},
    },
    {
        "needs": {"diet_rice", "fish", "oils"},
        "recipe": {
            "uz": "<b>Losos bowl (qora guruch bilan)</b>\n⏱ 40 daqiqa · 🍽 2 kishiga\n<i>Kerak:</i> 150g qora guruch, 1 banka losos, avokado, bodring, kunjut, zaytun yog'i, limon, tuz.\n<i>Tayyorlash:</i> Guruchni pishirib sovuting → kosaga qatlab joylashtiring: guruch, losos, sabzavot → yog' va limon bilan ziravorlang, kunjut seping. Ishga olib borish uchun ideal.",
            "ru": "<b>Боул с лососем и чёрным рисом</b>\n⏱ 40 минут · 🍽 2 порции\n<i>Нужно:</i> 150г чёрного риса, 1 банка лосося, авокадо, огурец, кунжут, оливковое масло, лимон, соль.\n<i>Как:</i> Отварите рис и охладите → выложите слоями: рис, лосось, овощи → заправьте маслом с лимоном, посыпьте кунжутом. Идеально брать с собой."},
    },
    {
        "needs": {"nuts", "honey", "sesame"},
        "recipe": {
            "uz": "<b>Uy granolasi (shakarsiz)</b>\n⏱ 30 daqiqa · 🍽 1 banka\n<i>Kerak:</i> 200g turli mag'iz, 3 osh q. kunjut, 3 osh q. asal, 2 osh q. kokos yog'i, dolchin, tuz.\n<i>Tayyorlash:</i> Mag'izni yirik to'g'rang → eritilgan asal va yog' bilan aralashtiring → pergamentda 160°C da 20 daqiqa, 10-daqiqada aralashtiring → sovigach siniq-siniq qiling.",
            "ru": "<b>Домашняя гранола без сахара</b>\n⏱ 30 минут · 🍽 1 банка\n<i>Нужно:</i> 200г разных орехов, 3 ст.л. кунжута, 3 ст.л. мёда, 2 ст.л. кокосового масла, корица, соль.\n<i>Как:</i> Крупно порубите орехи → смешайте с растопленным мёдом и маслом → на пергаменте 160°C 20 минут, перемешав на 10-й → остудите и разломайте."},
    },
    {
        "needs": {"buckwheat", "oils", "salt"},
        "recipe": {
            "uz": "<b>Yashil grechka kashasi (kechqurundan tayyorlanadi)</b>\n⏱ 10 daqiqa + tun\n<i>Kerak:</i> 1 stakan yashil grechka, 2 stakan suv, 1 osh q. GHEE yoki kokos yog'i, Himalay tuzi.\n<i>Tayyorlash:</i> Grechkani kechqurun suvda bo'ktiring → ertalab suvini to'kib, yangi suvda 7 daqiqa qaynating → yog' va tuz qo'shing. Pishirish vaqti yarmiga qisqaradi, foydasi ortadi.",
            "ru": "<b>Каша из зелёной гречки (с вечера)</b>\n⏱ 10 минут + ночь\n<i>Нужно:</i> 1 стакан зелёной гречки, 2 стакана воды, 1 ст.л. ГХИ или кокосового масла, гималайская соль.\n<i>Как:</i> Замочите гречку на ночь → утром слейте, залейте свежей водой и варите 7 минут → добавьте масло и соль. Время варки вдвое меньше, пользы больше."},
    },
    {
        "needs": {"almond_flour", "sweeteners"},
        "recipe": {
            "uz": "<b>Keto bodom pechenesi</b>\n⏱ 25 daqiqa · 🍽 14 dona\n<i>Kerak:</i> 200g bodom uni, 70g eritritol, 80g yumshatilgan sariyog', 1 tuxum, vanil, bir chimdim tuz.\n<i>Tayyorlash:</i> Yog' va shirinlashtirgichni oqarguncha uring → tuxum, keyin unni qo'shing → sharchalar yasab bosing → 170°C da 13 daqiqa. Issiqligida yumshoq, sovigach xrustaydi.",
            "ru": "<b>Кето-печенье из миндальной муки</b>\n⏱ 25 минут · 🍽 14 штук\n<i>Нужно:</i> 200г миндальной муки, 70г эритрита, 80г мягкого масла, 1 яйцо, ваниль, щепотка соли.\n<i>Как:</i> Взбейте масло с подсластителем добела → яйцо, затем муку → скатайте шарики и приплюсните → 170°C, 13 минут. Горячее мягкое, остывшее хрустит."},
    },
    {
        "needs": {"chia", "flax"},
        "recipe": {
            "uz": "<b>Omega-3 aralashmasi (ertalabki qoshiq)</b>\n⏱ 5 daqiqa\n<i>Kerak:</i> teng miqdorda chia va maydalangan zig'ir urug'i, xohlasangiz kunjut.\n<i>Tayyorlash:</i> Aralashtirib muzlatkichda yopiq bankada saqlang (maydalangan zig'ir tez achiydi) → har kuni 1 osh qoshiq: yogurt, smuzi yoki bo'tqaga.",
            "ru": "<b>Омега-3 смесь (утренняя ложка)</b>\n⏱ 5 минут\n<i>Нужно:</i> чиа и молотое семя льна поровну, по желанию кунжут.\n<i>Как:</i> Смешайте и храните в закрытой банке в холодильнике (молотый лён быстро горкнет) → по 1 ст.л. в день: в йогурт, смузи или кашу."},
    },
    {
        "needs": {"fiber_supp", "sweeteners"},
        "recipe": {
            "uz": "<b>Psilliumli jele (shakarsiz)</b>\n⏱ 15 daqiqa\n<i>Kerak:</i> 300ml meva damlamasi yoki choy, 1 osh q. psillium, shirinlashtirgich, limon.\n<i>Tayyorlash:</i> Psilliumni suyuqlikka sekin sepib darhol uring → stakanlarga quying → 10 daqiqada o'zi quyuqlashadi. Jelatinsiz, o'simlik asosli shirinlik.",
            "ru": "<b>Желе на псиллиуме без сахара</b>\n⏱ 15 минут\n<i>Нужно:</i> 300мл ягодного настоя или чая, 1 ст.л. псиллиума, подсластитель, лимон.\n<i>Как:</i> Всыпайте псиллиум медленно и сразу взбивайте → разлейте по стаканам → загустеет само за 10 минут. Десерт без желатина, на растительной основе."},
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
    "almond_flour": [_SWEET, _CHIA, _COCO, _CACAO, _PSY],
    "coconut": [_ALMOND, _SWEET, _CACAO, _CHIA],
    "flax": [_PSY, _SESAME, _SALT, _CHIA],
    "chia": [_COCO, _SWEET, _FLAX, _CACAO],
    "buckwheat": [_OIL, _SALT, _SESAME, _PSY],
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
    "chickpea": [_OIL, _SALT, _SESAME],
    "rice_flour": [_ALMOND, _PSY, _SALT],
    "diet_rice": [
        _OIL, _SESAME,
        _s("fish", "🐟", "Losos tushonkasi", "Тушёнка из лосося",
           "guruch bilan 5 daqiqada to'liq tushlik bo'ladi",
           "с рисом получается полноценный обед за 5 минут"),
        _VIN,
    ],
    "pp_flour": [_FLAX, _SESAME, _PSY, _SALT],
    "bran": [_FLAX, _SESAME, _PSY],
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
    "cacao": [_SWEET, _COCO, _SALT, _ALMOND],
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
