"""
Bilim o'yinlari savollari — one question bank for the Mini App games and the
bot's question every two days (daily_quiz.py).

Owner, 2026-10-16: "o'yinlarga ko'proq turli savollarni qo'sh, keyin har
2 kunda 1 ta savolni bot orqali ber ... sayt ichiga qo'shganimiz yangi
o'yinlardan random olib". The site used to keep these lists in its own
JavaScript; they live here now so the bot asks exactly what the games ask.
webapp_server.index() puts the bank into the page ({{GAME_BANK}}).

Carb figures are net carbs (total minus fibre) per 100 g, rounded from USDA
FoodData Central; they vary by variety and cooking, which the games page
says. Nothing here is medical advice.

Shapes (the Mini App reads the same ones):
  FOODS  [uz name, ru name, net carbs, fits keto?, shop category | None, uz note, ru note]
  QUIZ   {"id", "q": [uz, ru], "a": [[uz, ru] x4, the right one first], "e": [uz, ru]}
  PAIRS  [[product uz, ru], [what it's good for uz, ru]]
"""
import json
import random

FOODS = [
    ['Avokado', 'Авокадо', 2, True, None, "Yog' va tolaga boy, sof uglevodi juda kam.", 'Богат жирами и клетчаткой, чистых углеводов очень мало.'],
    ['Tuxum', 'Яйцо', 1, True, None, "Deyarli uglevodsiz: oqsil va yog' manbai.", 'Почти без углеводов: источник белка и жира.'],
    ["Chedder pishlog'i", 'Сыр чеддер', 1, True, None, "Qattiq pishloqlarda uglevod deyarli yo'q.", 'В твёрдых сырах углеводов почти нет.'],
    ['Losos', 'Лосось', 0, True, None, "Baliqda uglevod yo'q, omega-3 esa ko'p.", 'В рыбе нет углеводов, зато много омега-3.'],
    ["Tovuq go'shti", 'Курица', 0, True, None, "Go'shtda uglevod yo'q.", 'В мясе нет углеводов.'],
    ['Brokkoli', 'Брокколи', 4, True, None, "Yashil sabzavotlar keto ratsionining asosi.", 'Зелёные овощи — основа кето-рациона.'],
    ['Ismaloq', 'Шпинат', 1, True, None, "Barg sabzavotlarida sof uglevod juda kam.", 'В листовых овощах очень мало чистых углеводов.'],
    ['Bodring', 'Огурец', 3, True, None, "Asosan suvdan iborat, uglevodi kam.", 'В основном вода, углеводов мало.'],
    ['Bodom uni', 'Миндальная мука', 10, True, 'keto_flour', "Bug'doy unidan taxminan 7 baravar kam sof uglevod.", 'Примерно в 7 раз меньше чистых углеводов, чем в пшеничной муке.'],
    ["Kokos yog'i", 'Кокосовое масло', 0, True, 'oils', "Toza yog': uglevod yo'q, MCT ga boy.", 'Чистый жир: углеводов нет, много MCT.'],
    ["Zaytun yog'i", 'Оливковое масло', 0, True, 'oils', "Salat va taomlar uchun uglevodsiz yog'.", 'Масло без углеводов для салатов и блюд.'],
    ["Chia urug'i", 'Семена чиа', 8, True, 'seeds', "100 g da ~34 g tola bor, shuning uchun sof uglevodi kam.", 'В 100 г ~34 г клетчатки, поэтому чистых углеводов мало.'],
    ["Zig'ir urug'i", 'Семена льна', 2, True, 'seeds', "Deyarli butunlay tola va yog'dan iborat.", 'Почти целиком состоит из клетчатки и жира.'],
    ["Qovoq urug'i", 'Тыквенные семечки', 5, True, 'seeds', "Magniy va ruxga boy, uglevodi kam.", 'Богаты магнием и цинком, углеводов мало.'],
    ['Eritritol', 'Эритритол', 0, True, 'sweeteners', "Qondagi shakarni deyarli oshirmaydi, shakar o'rnini bosadi.", 'Почти не повышает сахар в крови и заменяет сахар.'],
    ["Grek yong'og'i", 'Грецкий орех', 7, True, None, "Keto uchun eng mos yong'oqlardan biri.", 'Один из самых подходящих для кето орехов.'],
    ['Qulupnay', 'Клубника', 6, True, None, "Rezavorlar kam miqdorda keto ga sig'adi.", 'Ягоды в небольшом количестве вписываются в кето.'],
    ["Sariyog'", 'Сливочное масло', 0, True, None, "Deyarli toza yog'.", 'Почти чистый жир.'],
    ['Banan', 'Банан', 20, False, None, "Bitta banan kunlik keto chegarasining katta qismini egallaydi.", 'Один банан съедает большую часть дневной кето-нормы.'],
    ['Olma', 'Яблоко', 11, False, None, "Shirin mevalarda fruktoza ko'p.", 'В сладких фруктах много фруктозы.'],
    ['Guruch (pishgan)', 'Рис (варёный)', 28, False, None, "Kraxmalga boy, keto uchun mos emas.", 'Богат крахмалом, для кето не подходит.'],
    ['Kartoshka (qaynatilgan)', 'Картофель (варёный)', 18, False, None, "Kraxmal tezda shakarga aylanadi.", 'Крахмал быстро превращается в сахар.'],
    ['Oq non', 'Белый хлеб', 46, False, 'keto_flour', "O'rniga bodom yoki zig'ir unidan non yopish mumkin.", 'Вместо него можно испечь хлеб из миндальной или льняной муки.'],
    ["Bug'doy uni", 'Пшеничная мука', 73, False, 'keto_flour', "Keto pishiriqlarida uning o'rniga bodom uni ishlatiladi.", 'В кето-выпечке её заменяют миндальной мукой.'],
    ['Shakar', 'Сахар', 100, False, 'sweeteners', "Toza uglevod. O'rniga eritritol yoki steviya.", 'Чистые углеводы. Замена — эритритол или стевия.'],
    ['Xurmo', 'Финики', 67, False, None, "Quritilgan mevalarda shakar juda ko'p.", 'В сухофруктах очень много сахара.'],
    ['Makaron (pishgan)', 'Макароны (варёные)', 29, False, None, "Bug'doy xamiri, uglevodga boy.", 'Пшеничное тесто, много углеводов.'],
    ['Keshyu', 'Кешью', 27, False, None, "Yong'oqlar ichida uglevodi eng ko'plaridan biri.", 'Один из самых углеводных орехов.'],
    ['Uzum', 'Виноград', 17, False, None, "Keto uchun juda shirin rezavor.", 'Слишком сладкая для кето ягода.'],
    # Added 2026-10-16.
    ['Gulkaram', 'Цветная капуста', 3, True, None, "Guruch va pyure o'rnini bosadigan eng mashhur keto sabzavot.", 'Самый популярный кето-овощ: заменяет рис и пюре.'],
    ['Kabachok', 'Кабачок', 2, True, None, "Undan keto «spagetti» va quymoq tayyorlanadi.", 'Из него делают кето-«спагетти» и оладьи.'],
    ['Karam', 'Капуста', 3, True, None, "Arzon va tolaga boy sabzavot.", 'Недорогой овощ, богатый клетчаткой.'],
    ['Pomidor', 'Помидор', 3, True, None, "O'rtacha miqdorda keto ga bemalol sig'adi.", 'В умеренном количестве спокойно вписывается в кето.'],
    ["Qo'ziqorin", 'Грибы', 2, True, None, "Kam uglevodli va to'yimli.", 'Мало углеводов и сытно.'],
    ['Zaytun', 'Оливки', 3, True, None, "Foydali yog'larga boy gazak.", 'Закуска, богатая полезными жирами.'],
    ["Mol go'shti", 'Говядина', 0, True, None, "Go'shtda uglevod yo'q, oqsil va temir esa ko'p.", 'В мясе нет углеводов, зато много белка и железа.'],
    ['Krevetka', 'Креветки', 0, True, None, "Deyarli toza oqsil.", 'Почти чистый белок.'],
    ["Tvorog (yog'li)", 'Творог (жирный)', 3, True, None, "Shakarsiz va yog'li bo'lsa, keto ga mos.", 'Если жирный и без сахара — подходит для кето.'],
    ['Malina', 'Малина', 5, True, None, "Rezavorlar ichida eng kam uglevodlilaridan biri.", 'Одна из самых низкоуглеводных ягод.'],
    ["Pekan yong'og'i", 'Пекан', 4, True, None, "Yong'oqlar ichida sof uglevodi eng kami.", 'Среди орехов — один из самых низкоуглеводных.'],
    ['Makadamiya', 'Макадамия', 5, True, None, "Yog'ga juda boy, uglevodi kam.", 'Очень жирный орех, углеводов мало.'],
    ['Bodom', 'Миндаль', 9, True, None, "Bir hovuch bodom — keto uchun yaxshi gazak.", 'Горсть миндаля — хороший кето-перекус.'],
    ['Kokos qirindisi (shakarsiz)', 'Кокосовая стружка (без сахара)', 7, True, 'coconut', "Tolaga boy: pishiriq va gazaklar uchun.", 'Богата клетчаткой: для выпечки и перекусов.'],
    ['Asal', 'Мёд', 82, False, None, "Tabiiy, lekin deyarli toza shakar.", 'Натуральный, но почти чистый сахар.'],
    ['Suli yormasi (quruq)', 'Овсяные хлопья (сухие)', 56, False, None, "Sog'lom don, lekin keto uchun uglevodi juda ko'p.", 'Полезная крупа, но для кето слишком много углеводов.'],
    ['Grechka (pishgan)', 'Гречка (варёная)', 17, False, None, "Glyutensiz, ammo uglevodga boy.", 'Без глютена, но богата углеводами.'],
    ["Makkajo'xori (pishgan)", 'Кукуруза (варёная)', 19, False, None, "Kraxmalli don — keto uchun mos emas.", 'Крахмалистое зерно — не для кето.'],
    ['Mango', 'Манго', 13, False, None, "Juda shirin tropik meva.", 'Очень сладкий тропический фрукт.'],
    ['Ananas', 'Ананас', 12, False, None, "Shirin meva: keto da juda oz miqdorda ham ko'p.", 'Сладкий фрукт: для кето много даже понемногу.'],
    ['Mayiz', 'Изюм', 75, False, None, "Quritilgan uzum — shakar konsentrati.", 'Сушёный виноград — концентрат сахара.'],
    ["No'xat (pishgan)", 'Нут (варёный)', 20, False, None, "Foydali dukkakli, ammo kraxmalga boy.", 'Полезная бобовая, но много крахмала.'],
    ['Yasmiq (pishgan)', 'Чечевица (варёная)', 12, False, None, "Oqsilga boy, lekin uglevodi keto uchun ko'p.", 'Много белка, но для кето многовато углеводов.'],
    ['Shirin gazli ichimlik', 'Сладкая газировка', 11, False, None, "Bir stakanida bir necha qoshiq shakar bor.", 'В одном стакане — несколько ложек сахара.'],
    ['Apelsin sharbati', 'Апельсиновый сок', 10, False, None, "Sharbatda meva tolasi yo'q, asosan shakar qoladi.", 'В соке нет клетчатки фрукта — остаётся в основном сахар.'],
    ['Kartoshka chipsi', 'Картофельные чипсы', 48, False, None, "Kartoshka kraxmali — uglevodga juda boy.", 'Картофельный крахмал — очень много углеводов.'],
]


def _q(qid, q, a, e):
    return {"id": qid, "q": q, "a": a, "e": e}


# Each answer list starts with the right one; options are shuffled on screen.
QUIZ = [
    _q("q01", ["Ketoz holatida organizm asosiy energiyani nimadan oladi?", 'Откуда организм берёт основную энергию в кетозе?'],
       [["Yog' va keton tanachalaridan", 'Из жиров и кетоновых тел'], ['Shakardan', 'Из сахара'], ['Faqat oqsildan', 'Только из белка'], ['Suvdan', 'Из воды']],
       ["Uglevod kam bo'lsa, jigar yog'dan keton tanachalari ishlab chiqaradi va ular asosiy yoqilg'iga aylanadi.",
        'Когда углеводов мало, печень делает из жира кетоновые тела — они и становятся основным топливом.']),
    _q("q02", ["Klassik keto dietada kuniga odatda qancha sof uglevod iste'mol qilinadi?", 'Сколько чистых углеводов в день обычно на классической кето-диете?'],
       [['20–50 g', '20–50 г'], ['100–150 g', '100–150 г'], ['200–300 g', '200–300 г'], ["Cheklov yo'q", 'Ограничений нет']],
       ["Ko'pchilik uchun ketozga kirish chegarasi kuniga taxminan 20–50 g sof uglevod.",
        'Для большинства порог входа в кетоз — примерно 20–50 г чистых углеводов в день.']),
    _q("q03", ['Sof uglevod qanday hisoblanadi?', 'Как считают чистые углеводы?'],
       [['Umumiy uglevod − tola', 'Все углеводы − клетчатка'], ['Umumiy uglevod + shakar', 'Все углеводы + сахар'], ["Yog' − oqsil", 'Жиры − белки'], ['Kaloriya ÷ 4', 'Калории ÷ 4']],
       ["Tola qondagi shakarni oshirmaydi, shuning uchun u umumiy uglevoddan ayiriladi.",
        'Клетчатка не повышает сахар в крови, поэтому её вычитают из общих углеводов.']),
    _q("q04", ["Eritritol qondagi shakarga qanday ta'sir qiladi?", 'Как эритритол влияет на сахар в крови?'],
       [["Deyarli ta'sir qilmaydi", 'Почти не влияет'], ['Shakar kabi oshiradi', 'Повышает, как сахар'], ['Ikki baravar oshiradi', 'Повышает вдвое сильнее'], ['Kuchli tushiradi', 'Сильно снижает']],
       ["Eritritolning glikemik indeksi nolga yaqin, shuning uchun u keto pishiriqlarida shakar o'rnini bosadi.",
        'Гликемический индекс эритритола близок к нулю, поэтому им заменяют сахар в кето-выпечке.']),
    _q("q05", ["100 g bodom unida bug'doy uniga nisbatan sof uglevod qancha?", 'Сколько чистых углеводов в 100 г миндальной муки по сравнению с пшеничной?'],
       [['Taxminan 7 baravar kam', 'Примерно в 7 раз меньше'], ['Bir xil', 'Столько же'], ["2 baravar ko'p", 'В 2 раза больше'], ["Umuman yo'q", 'Совсем нет']],
       ["Bodom unida ~10 g, bug'doy unida ~73 g sof uglevod bor (100 g da).",
        'В миндальной муке ~10 г, в пшеничной ~73 г чистых углеводов (на 100 г).']),
    _q("q06", ["Qaysi yog' MCT (o'rta zanjirli yog'lar)ga eng boy?", 'Какое масло богаче всего MCT (среднецепочечными триглицеридами)?'],
       [["Kokos yog'i", 'Кокосовое'], ["Kungaboqar yog'i", 'Подсолнечное'], ["Zaytun yog'i", 'Оливковое'], ["Makkajo'xori yog'i", 'Кукурузное']],
       ["Kokos yog'ining yarmidan ko'pi MCT: ular tez energiyaga aylanadi.",
        'Больше половины кокосового масла — MCT: они быстро превращаются в энергию.']),
    _q("q07", ["Keto pishiriqlariga psillium nima uchun qo'shiladi?", 'Зачем в кето-выпечку добавляют псиллиум?'],
       [["Xamirni bog'laydi va tola beradi", 'Связывает тесто и даёт клетчатку'], ['Shirinlik beradi', 'Даёт сладость'], ['Rang beradi', 'Даёт цвет'], ["Yog'ni almashtiradi", 'Заменяет жир']],
       ["Psillium suvni shimib, glyuten o'rnida xamirni elastik qiladi.",
        'Псиллиум впитывает воду и вместо глютена делает тесто эластичным.']),
    _q("q08", ["Keto boshidagi holsizlikni ('keto gripp') nima yengillatadi?", 'Что облегчает слабость в начале кето («кето-грипп»)?'],
       [['Suv va elektrolitlar: tuz, kaliy, magniy', 'Вода и электролиты: соль, калий, магний'], ["Ko'proq shakar", 'Больше сахара'], ["Ko'proq qahva", 'Больше кофе'], ["Ovqatni butunlay to'xtatish", 'Полный отказ от еды']],
       ["Keto boshida organizm suv va tuzni ko'proq chiqaradi; ularni to'ldirish holsizlikni kamaytiradi.",
        'В начале кето организм теряет больше воды и соли; их восполнение уменьшает слабость.']),
    _q("q09", ["100 g chia urug'ida taxminan qancha tola bor?", 'Сколько примерно клетчатки в 100 г семян чиа?'],
       [['~34 g', '~34 г'], ['~3 g', '~3 г'], ['~10 g', '~10 г'], ['~80 g', '~80 г']],
       ["Chia tolaga eng boy urug'lardan biri, shuning uchun uning sof uglevodi ~8 g.",
        'Чиа — одни из самых богатых клетчаткой семян, поэтому чистых углеводов в них ~8 г.']),
    _q("q10", ['Qaysi mahsulot keto uchun mos emas?', 'Какой продукт не подходит для кето?'],
       [['Guruch', 'Рис'], ['Avokado', 'Авокадо'], ['Tuxum', 'Яйцо'], ['Losos', 'Лосось']],
       ["100 g pishgan guruchda ~28 g sof uglevod bor: bu kunlik keto chegarasining deyarli hammasi.",
        'В 100 г варёного риса ~28 г чистых углеводов — почти вся дневная кето-норма.']),
    # Added 2026-10-16.
    _q("q11", ['Qaysi shirinlantiruvchi shakardan 200–300 baravar shirin?', 'Какой подсластитель в 200–300 раз слаще сахара?'],
       [['Steviya', 'Стевия'], ['Eritritol', 'Эритритол'], ['Alluloza', 'Аллюлоза'], ['Ksilit', 'Ксилит']],
       ["Steviya bargidagi moddalar juda shirin, shuning uchun u juda oz miqdorda ishlatiladi.",
        'Вещества из листьев стевии очень сладкие, поэтому её кладут совсем немного.']),
    _q("q12", ['Eritritol shakarga nisbatan qanchalik shirin?', 'Насколько эритритол сладок по сравнению с сахаром?'],
       [['Shakarning ~70% i qadar', 'Примерно на 70% от сахара'], ['2 baravar shirinroq', 'В 2 раза слаще'], ['10 baravar shirinroq', 'В 10 раз слаще'], ['Umuman shirin emas', 'Совсем не сладкий']],
       ["Shuning uchun retseptda shakar o'rniga eritritolni biroz ko'proq solish mumkin.",
        'Поэтому в рецепте эритритола можно положить чуть больше, чем сахара.']),
    _q("q13", ["Alluloza pishiriqda qaysi xususiyati bilan shakarga o'xshaydi?", 'Чем аллюлоза похожа на сахар в выпечке?'],
       [['Qizarib, karamellashadi', 'Румянится и карамелизуется'], ["Xamirni ko'pchitadi", 'Поднимает тесто'], ["Yog'ni almashtiradi", 'Заменяет жир'], ["Tuzli ta'm beradi", 'Даёт солёный вкус']],
       ["Alluloza qizdirilganda shakar kabi jigarrang tus oladi, lekin qondagi shakarni deyarli oshirmaydi.",
        'При нагреве аллюлоза румянится, как сахар, но почти не повышает сахар в крови.']),
    _q("q14", ["Pishiriqda kokos uni bug'doy uniga nisbatan qancha solinadi?", 'Сколько кокосовой муки кладут в выпечку вместо пшеничной?'],
       [['Ancha kam — taxminan 4 baravar', 'Гораздо меньше — примерно вчетверо'], ['Xuddi shuncha', 'Столько же'], ["2 baravar ko'p", 'В 2 раза больше'], ["4 baravar ko'p", 'В 4 раза больше']],
       ["Kokos uni suyuqlikni juda kuchli shimadi: uni oz solib, tuxum yoki suyuqlikni ko'paytirish kerak.",
        'Кокосовая мука сильно впитывает жидкость: её кладут мало, а яиц или жидкости — больше.']),
    _q("q15", ['Ksantan kamedi keto oshxonasida nima uchun ishlatiladi?', 'Зачем в кето-кухне ксантановая камедь?'],
       [['Sous va xamirni quyuqlashtiradi', 'Загущает соусы и тесто'], ['Shirinlik beradi', 'Даёт сладость'], ["Yog' o'rnini bosadi", 'Заменяет жир'], ['Rang beradi', 'Даёт цвет']],
       ["Juda oz miqdori — choy qoshiqning bir qismi — sous, krem va glyutensiz xamirni quyuq va bog'langan qiladi.",
        'Совсем немного — часть чайной ложки — делает соус, крем и безглютеновое тесто густым и связным.']),
    _q("q16", ["Zig'ir urug'idagi omega-3 yaxshiroq o'zlashishi uchun uni qanday iste'mol qilgan ma'qul?", 'Как лучше есть лён, чтобы омега-3 усваивалась лучше?'],
       [['Maydalab, un qilib', 'Молотым'], ['Butunligicha', 'Целыми семенами'], ['Kuydirib qovurib', 'Сильно прожаренным'], ['Muzlatib', 'Замороженным']],
       ["Butun zig'ir urug'i ko'pincha hazm bo'lmay o'tib ketadi; maydalanganidan omega-3 va tola yaxshiroq olinadi.",
        'Целые семена льна часто проходят непереваренными; из молотых омега-3 и клетчатка усваиваются лучше.']),
    _q("q17", ["Chia urug'i suyuqlikda nima bo'ladi?", 'Что происходит с семенами чиа в жидкости?'],
       [['Shishib, jelega aylanadi', 'Набухают и превращаются в гель'], ['Butunlay eriydi', 'Полностью растворяются'], ['Toshdek qotadi', 'Твердеют как камень'], ["O'zgarmaydi", 'Не меняются']],
       ["Chia o'z vaznidan taxminan 10 baravar ko'p suyuqlik shimib, puding uchun qulay jele hosil qiladi.",
        'Чиа впитывает жидкости примерно в 10 раз больше своего веса и даёт гель, удобный для пудинга.']),
    _q("q18", ["1 g yog'da taxminan qancha kaloriya bor?", 'Сколько калорий примерно в 1 г жира?'],
       [['~9 kkal', '~9 ккал'], ['~4 kkal', '~4 ккал'], ['~1 kkal', '~1 ккал'], ['~20 kkal', '~20 ккал']],
       ["Yog' eng to'yimli makronutriyent: oqsil va uglevodning grammida ~4 kkal bor.",
        'Жир — самый калорийный макронутриент: в грамме белка и углеводов ~4 ккал.']),
    _q("q19", ["Klassik keto dietada kaloriyaning qancha qismi yog'dan keladi?", 'Какая доля калорий на классической кето-диете приходится на жиры?'],
       [['Taxminan 70–75%', 'Примерно 70–75%'], ['10–15%', '10–15%'], ['Taxminan 30%', 'Около 30%'], ['100%', '100%']],
       ["Qolgani: ~20% oqsil va 5–10% uglevod.",
        'Остальное: ~20% белка и 5–10% углеводов.']),
    _q("q20", ['Keto boshida tez ketadigan dastlabki kilogrammlar ko\'pincha nima?', 'Что чаще всего уходит в первые дни кето, когда вес быстро падает?'],
       [['Suv', 'Вода'], ['Faqat mushak', 'Только мышцы'], ["Faqat yog'", 'Только жир'], ['Suyak', 'Кости']],
       ["Organizmdagi uglevod zaxirasi (glikogen) suv bilan birga saqlanadi; u kamayganda suv ham chiqib ketadi.",
        'Запас углеводов (гликоген) хранится вместе с водой; когда он уходит, уходит и вода.']),
    _q("q21", ['Qaysi biri keton tanachasi?', 'Что из этого — кетоновое тело?'],
       [['Beta-gidroksibutirat', 'Бета-гидроксибутират (BHB)'], ['Glyukoza', 'Глюкоза'], ['Insulin', 'Инсулин'], ['Laktoza', 'Лактоза']],
       ["Jigar yog'dan keton tanachalarini hosil qiladi; ularning eng asosiysi — beta-gidroksibutirat.",
        'Печень делает из жира кетоновые тела; главное из них — бета-гидроксибутират (BHB).']),
    _q("q22", ['Ketozni uyda qanday tekshirish mumkin?', 'Как проверить кетоз дома?'],
       [['Keton test-poloskalari yoki ketonometr bilan', 'Тест-полосками на кетоны или кетонометром'], ['Termometr bilan', 'Термометром'], ['Tarozida', 'На весах'], ["Qon bosimini o'lchab", 'Измерив давление']],
       ["Siydikdagi ketonni test-poloska, qondagisini maxsus ketonometr ko'rsatadi.",
        'Кетоны в моче показывает тест-полоска, в крови — специальный кетонометр.']),
    _q("q23", ["Yorliqda «shakarsiz» deb yozilgan bo'lsa, bu nimani anglatadi?", 'Что значит надпись «без сахара» на упаковке?'],
       [["Uglevod baribir bo'lishi mumkin — tarkibni o'qing", 'Углеводы всё равно могут быть — читайте состав'], ["Uglevod umuman yo'q", 'Углеводов нет совсем'], ["Kaloriya yo'q", 'Калорий нет'], ['Keto uchun albatta mos', 'Точно подходит для кето']],
       ["Shakar o'rniga un, kraxmal yoki maltit bo'lishi mumkin: sof uglevodni yorliqdan hisoblang.",
        'Вместо сахара там может быть мука, крахмал или мальтит: считайте чистые углеводы по этикетке.']),
    _q("q24", ['Qaysi biri yorliqlarda yashiringan shakar nomi?', 'Что из этого — скрытый сахар в составе?'],
       [['Maltodekstrin', 'Мальтодекстрин'], ['Ksantan', 'Ксантан'], ['Psillium', 'Псиллиум'], ['Kakao', 'Какао']],
       ["Maltodekstrinning glikemik indeksi oddiy shakarnikidan ham yuqori.",
        'Гликемический индекс мальтодекстрина даже выше, чем у обычного сахара.']),
    _q("q25", ['Qaysi shirinlantiruvchi qondagi shakarni sezilarli oshiradi?', 'Какой подсластитель заметно повышает сахар в крови?'],
       [['Maltit', 'Мальтит'], ['Eritritol', 'Эритритол'], ['Steviya', 'Стевия'], ['Alluloza', 'Аллюлоза']],
       ["«Shakarsiz» shokolad va konfetlarda ko'p uchraydigan maltitning glikemik indeksi ~35, eritritolniki esa nolga yaqin.",
        'У мальтита, частого в «шоколаде без сахара», гликемический индекс ~35, у эритритола — около нуля.']),
    _q("q26", ['Qaysi shirinlantiruvchi itlar uchun juda xavfli?', 'Какой подсластитель очень опасен для собак?'],
       [['Ksilit', 'Ксилит'], ['Eritritol', 'Эритритол'], ['Steviya', 'Стевия'], ['Alluloza', 'Аллюлоза']],
       ["Odam uchun xavfsiz ksilit itlarda qondagi shakarni keskin tushiradi — uy hayvonlaridan uzoqda saqlang.",
        'Безопасный для человека ксилит резко снижает сахар в крови у собак — храните подальше от питомцев.']),
    _q("q27", ["Qaysi yong'oqda sof uglevod eng kam?", 'В каком орехе меньше всего чистых углеводов?'],
       [['Pekan', 'Пекан'], ['Keshyu', 'Кешью'], ['Pista', 'Фисташки'], ["Yeryong'oq", 'Арахис']],
       ["100 g pekanda ~4 g, keshyuda esa ~27 g sof uglevod bor.",
        'В 100 г пекана ~4 г чистых углеводов, в кешью — ~27 г.']),
    _q("q28", ["Keto taomlarda guruch o'rniga nima ishlatiladi?", 'Что используют в кето-блюдах вместо риса?'],
       [['Maydalangan gulkaram', 'Измельчённую цветную капусту'], ['Makaron', 'Макароны'], ['Kartoshka', 'Картофель'], ['Grechka', 'Гречку']],
       ["100 g gulkaramda ~3 g, pishgan guruchda ~28 g sof uglevod bor.",
        'В 100 г цветной капусты ~3 г чистых углеводов, в варёном рисе — ~28 г.']),
    _q("q29", ["Makaron o'rniga qaysi keto variant mos?", 'Что подойдёт для кето вместо макарон?'],
       [['Kabachokdan «spagetti»', '«Спагетти» из кабачка'], ['Guruch lapshasi', 'Рисовая лапша'], ['Oq non', 'Белый хлеб'], ['Kartoshka pyuresi', 'Картофельное пюре']],
       ["Kabachokni ingichka tasmalab kesib, makaron kabi ishlatish mumkin: 100 g da ~2 g sof uglevod.",
        'Кабачок режут тонкими лентами и едят как пасту: ~2 г чистых углеводов на 100 г.']),
    _q("q30", ["Qaysi yog' kuchli olovda qovurishga eng chidamli?", 'Какой жир лучше всех выдерживает сильную жарку?'],
       [["Eritilgan sariyog' (gxi)", 'Гхи (топлёное масло)'], ["Zig'ir yog'i", 'Льняное масло'], ["Oddiy sariyog'", 'Обычное сливочное масло'], ["Baliq yog'i", 'Рыбий жир']],
       ["Eritilgan sariyog'da sut oqsili qolmagan, shuning uchun u ~250°C gacha kuymaydi; zig'ir yog'i esa faqat sovuq taomlar uchun.",
        'В гхи нет молочного белка, поэтому оно не горит примерно до 250°C; льняное масло — только для холодных блюд.']),
    _q("q31", ["Kokos yog'i qaysi haroratdan pastda qotadi?", 'При какой температуре застывает кокосовое масло?'],
       [['~24°C dan past', 'Ниже ~24°C'], ['Faqat 0°C da', 'Только при 0°C'], ['~60°C dan past', 'Ниже ~60°C'], ['Hech qachon qotmaydi', 'Никогда не застывает']],
       ["Xona salqin bo'lsa, kokos yog'i oq va qattiq bo'ladi — bu uning sifatiga ta'sir qilmaydi.",
        'В прохладной комнате кокосовое масло белое и твёрдое — на качество это не влияет.']),
    _q("q32", ["MCT yog'i nima bilan mashhur?", 'Чем известно масло MCT?'],
       [['Jigarda tez ketonga aylanadi', 'Быстро превращается в печени в кетоны'], ['Uglevodga boy', 'Богато углеводами'], ['Oqsilga boy', 'Богато белком'], ["Shirin ta'mi bor", 'Сладкое на вкус']],
       ["O'rta zanjirli yog' kislotalari tez so'riladi va tez energiya beradi.",
        'Среднецепочечные жирные кислоты быстро всасываются и быстро дают энергию.']),
    _q("q33", ['Keto qahva odatda nimadan tayyorlanadi?', 'Из чего обычно готовят кето-кофе?'],
       [["Qahva + sariyog' yoki MCT yog'i", 'Кофе + сливочное масло или MCT'], ['Qahva + shakar', 'Кофе + сахар'], ['Qahva + sut + asal', 'Кофе + молоко + мёд'], ['Qahva + sharbat', 'Кофе + сок']],
       ["Yog' uzoq to'qlik beradi, shakar esa qo'shilmaydi.",
        'Жир надолго даёт сытость, а сахар не добавляют.']),
    _q("q34", ['Olma sirkasidagi (5%) asosiy faol modda qaysi?', 'Какое главное активное вещество в яблочном уксусе (5%)?'],
       [['Sirka kislotasi', 'Уксусная кислота'], ['Limon kislotasi', 'Лимонная кислота'], ['Shakar', 'Сахар'], ['Spirt', 'Спирт']],
       ["Yorliqdagi «5%» — sirka kislotasining ulushi. Uni suvga qo'shib yoki salat sousida ishlatish mumkin.",
        '«5%» на этикетке — доля уксусной кислоты. Его добавляют в воду или в заправку для салата.']),
    _q("q35", ['Himalay tuzining pushti rangi nimadan?', 'Откуда розовый цвет у гималайской соли?'],
       [['Temir oksidi va boshqa minerallardan', 'От оксида железа и других минералов'], ["Bo'yoqdan", 'От красителя'], ['Shakardan', 'От сахара'], ['Qizil qalampirdan', 'От красного перца']],
       ["Tarkibining ~95–98% i oddiy osh tuzi (natriy xlorid); rangni oz miqdordagi minerallar beradi.",
        'На ~95–98% это обычная поваренная соль; цвет дают небольшие примеси минералов.']),
    _q("q36", ['Bitta tuxumda taxminan qancha oqsil bor?', 'Сколько примерно белка в одном яйце?'],
       [['~6 g', '~6 г'], ['~1 g', '~1 г'], ['~20 g', '~20 г'], ['~50 g', '~50 г']],
       ["Tuxum — arzon va to'liq oqsil manbai, uglevodi esa 1 g dan kam.",
        'Яйцо — недорогой полноценный белок, а углеводов в нём меньше 1 г.']),
    _q("q37", ['Qaysi mevada sof uglevod eng kam?', 'В каком фрукте меньше всего чистых углеводов?'],
       [['Malina', 'Малина'], ['Uzum', 'Виноград'], ['Banan', 'Банан'], ['Mango', 'Манго']],
       ["100 g malinada ~5 g sof uglevod bor — keto da oz miqdorda yeyish mumkin.",
        'В 100 г малины ~5 г чистых углеводов — на кето её можно понемногу.']),
    _q("q38", ['100 ml sutda taxminan qancha uglevod (laktoza) bor?', 'Сколько примерно углеводов (лактозы) в 100 мл молока?'],
       [['~5 g', '~5 г'], ['0 g', '0 г'], ['~20 g', '~20 г'], ['~50 g', '~50 г']],
       ["Shuning uchun keto da sut o'rniga ko'pincha qaymoq yoki kokos slivkasi ishlatiladi.",
        'Поэтому на кето вместо молока часто берут сливки или кокосовые сливки.']),
    _q("q39", ['Grechka glyutensiz. U keto uchun ham mosmi?', 'Гречка без глютена. Подходит ли она для кето?'],
       [["Yo'q — glyutensiz, lekin uglevodga boy", 'Нет — без глютена, но много углеводов'], ['Ha, mutlaqo mos', 'Да, полностью подходит'], ['Faqat kechqurun mos', 'Подходит только вечером'], ["Ha, uglevodi yo'q", 'Да, углеводов нет']],
       ["Glyutensiz degani keto degani emas: 100 g pishgan grechkada ~17 g sof uglevod bor.",
        'Без глютена — не значит кето: в 100 г варёной гречки ~17 г чистых углеводов.']),
    _q("q40", ['Qaysi unda glyuten bor?', 'В какой муке есть глютен?'],
       [['Javdar uni', 'Ржаная мука'], ['Bodom uni', 'Миндальная мука'], ['Kokos uni', 'Кокосовая мука'], ["Zig'ir uni", 'Льняная мука']],
       ["Bug'doy, javdar va arpada glyuten bor; bodom, kokos va zig'ir unida yo'q.",
        'Глютен есть в пшенице, ржи и ячмене; в миндальной, кокосовой и льняной муке его нет.']),
    _q("q41", ['Quyidagilardan qaysi biri magniyga eng boy?', 'Что из этого богаче всего магнием?'],
       [["Qovoq urug'i", 'Тыквенные семечки'], ['Olma', 'Яблоко'], ['Oq guruch', 'Белый рис'], ['Bodring', 'Огурец']],
       ["100 g qovoq urug'ida 500 mg dan ortiq magniy bor — bu kunlik ehtiyojdan ham ko'p.",
        'В 100 г тыквенных семечек больше 500 мг магния — это больше дневной нормы.']),
    _q("q42", ['Keto uchun qaysi qora shokolad ma\'qulroq?', 'Какой тёмный шоколад лучше для кето?'],
       [['Kakao 85% va undan yuqori', 'Какао 85% и выше'], ['Kakao 30%', 'Какао 30%'], ['Kakao 50%', 'Какао 50%'], ['Oq shokolad', 'Белый шоколад']],
       ["Kakao ulushi oshgani sari shakar kamayadi; eng yaxshisi — shakarsiz yoki eritritolli shokolad.",
        'Чем больше какао, тем меньше сахара; лучше всего — шоколад без сахара или на эритритоле.']),
    _q("q43", ['Ketchupning 100 g ida taxminan qancha shakar bor?', 'Сколько примерно сахара в 100 г кетчупа?'],
       [['~20 g dan ortiq', 'Больше ~20 г'], ['0 g', '0 г'], ['~2 g', '~2 г'], ['~80 g', '~80 г']],
       ["Soslardagi yashirin shakar ketozni buzishi mumkin — yorliqni tekshiring.",
        'Скрытый сахар в соусах может сбить кетоз — проверяйте этикетку.']),
    _q("q44", ['Asalning 100 g ida taxminan qancha shakar bor?', 'Сколько примерно сахара в 100 г мёда?'],
       [['~80 g', '~80 г'], ['~10 g', '~10 г'], ['~30 g', '~30 г'], ['0 g', '0 г']],
       ["Asal tabiiy, lekin deyarli toza shakar: keto da o'rniga eritritol yoki steviya ishlatiladi.",
        'Мёд натуральный, но это почти чистый сахар: на кето его заменяют эритритолом или стевией.']),
    _q("q45", ["Psillium qobig'i asosan nimadan iborat?", 'Из чего в основном состоит шелуха псиллиума?'],
       [['Eruvchan toladan', 'Из растворимой клетчатки'], ['Shakardan', 'Из сахара'], ["Yog'dan", 'Из жира'], ['Oqsildan', 'Из белка']],
       ["Eruvchan tola suvni shimib jele hosil qiladi: ichak uchun foydali va keto nonga elastiklik beradi.",
        'Растворимая клетчатка впитывает воду и образует гель: полезно для кишечника и делает кето-хлеб эластичным.']),
    _q("q46", ["Bodom unida bug'doy uniga qaraganda nima ancha ko'p?", 'Чего в миндальной муке гораздо больше, чем в пшеничной?'],
       [["Yog' va oqsil", 'Жиров и белка'], ['Shakar', 'Сахара'], ['Kraxmal', 'Крахмала'], ['Glyuten', 'Глютена']],
       ["100 g bodom unida ~50 g yog' va ~21 g oqsil bor, sof uglevodi esa ~10 g.",
        'В 100 г миндальной муки ~50 г жиров и ~21 г белка, а чистых углеводов ~10 г.']),
    _q("q47", ['100 g kokos unida taxminan qancha tola bor?', 'Сколько примерно клетчатки в 100 г кокосовой муки?'],
       [['~35–40 g', '~35–40 г'], ['~1 g', '~1 г'], ['~10 g', '~10 г'], ["Umuman yo'q", 'Совсем нет']],
       ["Shu tola tufayli kokos uni suyuqlikni ko'p shimadi va sof uglevodi kam.",
        'Из-за этой клетчатки кокосовая мука сильно впитывает жидкость, а чистых углеводов в ней мало.']),
    _q("q48", ['Qaysi sabzavotda sof uglevod eng kam?', 'В каком овоще меньше всего чистых углеводов?'],
       [['Ismaloq', 'Шпинат'], ['Kartoshka', 'Картофель'], ["Makkajo'xori", 'Кукуруза'], ["No'xat", 'Нут']],
       ["100 g ismaloqda ~1 g, qaynatilgan kartoshkada esa ~18 g sof uglevod bor.",
        'В 100 г шпината ~1 г чистых углеводов, в варёном картофеле — ~18 г.']),
    _q("q49", ['Qaysi pishloq mahsulotida uglevod eng kam?', 'В каком сырном продукте меньше всего углеводов?'],
       [['Qattiq pishloq (chedder, parmezan)', 'Твёрдый сыр (чеддер, пармезан)'], ['Shirin tvorog massasi', 'Сладкая творожная масса'], ['Shokoladli sirok', 'Глазированный сырок'], ['Mevali yogurt', 'Фруктовый йогурт']],
       ["Qattiq pishloqlarda uglevod deyarli yo'q; shirinlangan sut mahsulotlarida esa shakar ko'p.",
        'В твёрдых сырах углеводов почти нет, а в подслащённых молочных продуктах много сахара.']),
    _q("q50", ['Glyutensiz keto pishiriqda tuxum qanday vazifani bajaradi?', 'Зачем яйца в безглютеновой кето-выпечке?'],
       [["Xamirni bog'laydi va ko'pchitadi", 'Связывают и поднимают тесто'], ['Shirinlik beradi', 'Дают сладость'], ["Uglevod qo'shadi", 'Добавляют углеводы'], ['Faqat rang beradi', 'Только дают цвет']],
       ["Glyuten bo'lmagani uchun xamirni tuxum ushlab turadi; kokos uni bilan esa tuxum ko'proq kerak bo'ladi.",
        'Без глютена тесто держат яйца; с кокосовой мукой яиц нужно больше.']),
]

PAIRS = [
    [["Chia", 'Чиа'], ['Tolaga boy', 'Много клетчатки']],
    [['Eritritol', 'Эритритол'], ['Shakarsiz shirinlik', 'Сладость без сахара']],
    [['Bodom uni', 'Миндальная мука'], ['Glyutensiz un', 'Мука без глютена']],
    [["Kokos yog'i", 'Кокосовое масло'], ['MCT manbai', 'Источник MCT']],
    [['Psillium', 'Псиллиум'], ["Xamirni bog'laydi", 'Связывает тесто']],
    [["Zig'ir urug'i", 'Семена льна'], ['Omega-3 manbai', 'Источник омега-3']],
    # Added 2026-10-16.
    [['Ksantan', 'Ксантан'], ['Sousni quyuqlashtiradi', 'Загущает соус']],
    [['Kokos uni', 'Кокосовая мука'], ["Suyuqlikni ko'p shimadi", 'Сильно впитывает жидкость']],
    [['Steviya', 'Стевия'], ['200–300 baravar shirin', 'В 200–300 раз слаще']],
    [['Alluloza', 'Аллюлоза'], ['Karamellashadi', 'Карамелизуется']],
    [["Eritilgan sariyog'", 'Топлёное масло'], ['Kuchli olovga chidaydi', 'Выдерживает сильный жар']],
    [["MCT yog'i", 'Масло MCT'], ['Tez energiya', 'Быстрая энергия']],
    [["Qovoq urug'i", 'Тыквенные семечки'], ['Magniyga boy', 'Богаты магнием']],
    [['Gulkaram', 'Цветная капуста'], ["Guruch o'rnini bosadi", 'Заменяет рис']],
    [['Kabachok', 'Кабачок'], ["Makaron o'rnini bosadi", 'Заменяет макароны']],
    [['Olma sirkasi', 'Яблочный уксус'], ['Salat sousi uchun', 'Для заправки салата']],
]


def bank_json() -> str:
    """The bank for the Mini App, safe to put inside a <script> element."""
    data = {
        "foods": FOODS,
        "quiz": [{"q": x["q"], "a": x["a"], "e": x["e"]} for x in QUIZ],
        "pairs": PAIRS,
    }
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


# ───────────────────── the bot's question every 2 days ──────────────────────
# Owner: "sayt ichiga qo'shganimiz yangi o'yinlardan random olib jo'nat
# bittasini". Three of the four games can be asked in a chat: the quiz, "Keto
# mi, emas mi?" and "Qaysi birida uglevod kam?". (The memory game can't.)
# Every question has a stable key, stored with each send, so the same one is
# not asked again until every key of its game has been used.

GAME_OF_KIND = {"quiz": "quiz", "keto": "keto", "duel": "duel"}
DUEL_MIN_GAP = 5            # g; closer pairs aren't fair with rounded figures

_FOOD_BY_NAME = {f[0]: f for f in FOODS}
_QUIZ_BY_ID = {x["id"]: x for x in QUIZ}


def _duel_keys() -> list[str]:
    keys = []
    for i, a in enumerate(FOODS):
        for b in FOODS[i + 1:]:
            if abs(a[2] - b[2]) >= DUEL_MIN_GAP:
                keys.append(f"duel:{a[0]}|{b[0]}")
    return keys


def keys_by_kind() -> dict[str, list[str]]:
    return {
        "quiz": [f"quiz:{x['id']}" for x in QUIZ],
        "keto": [f"keto:{f[0]}" for f in FOODS],
        "duel": _duel_keys(),
    }


def pick_key(sent: set[str], rng: random.Random | None = None) -> str:
    """A random game, then a random question of it that hasn't been asked
    yet. A game whose questions are all used starts over."""
    rng = rng or random.Random()
    pools = keys_by_kind()
    kind = rng.choice(list(pools))
    fresh = [k for k in pools[kind] if k not in sent]
    return rng.choice(fresh or pools[kind])


def build_item(key: str) -> dict | None:
    """{kind, key, q, options, correct, e} in [uz, ru] pairs, or None for a
    key that no longer exists (a question removed from the bank)."""
    kind, _, rest = key.partition(":")
    if kind == "quiz":
        x = _QUIZ_BY_ID.get(rest)
        if not x:
            return None
        return {"kind": kind, "key": key, "q": x["q"], "options": x["a"], "correct": 0, "e": x["e"]}
    if kind == "keto":
        f = _FOOD_BY_NAME.get(rest)
        if not f:
            return None
        return {
            "kind": kind, "key": key,
            "q": [f"«{f[0]}» keto uchun mos keladimi?", f"«{f[1]}» подходит для кето?"],
            # 👍/👎, not ✅/❌ — those mark the right/wrong answer afterwards.
            "options": [["👍 Ha, mos", "👍 Да, подходит"], ["👎 Yo'q, mos emas", "👎 Нет, не подходит"]],
            "correct": 0 if f[3] else 1,
            "e": [f"100 g da ~{f[2]} g sof uglevod. {f[5]}", f"~{f[2]} г чистых углеводов на 100 г. {f[6]}"],
        }
    if kind == "duel":
        a_name, _, b_name = rest.partition("|")
        a, b = _FOOD_BY_NAME.get(a_name), _FOOD_BY_NAME.get(b_name)
        if not a or not b:
            return None
        low = a if a[2] < b[2] else b
        return {
            "kind": kind, "key": key,
            "q": ["Qaysi birida sof uglevod kamroq (100 g da)?", "Где меньше чистых углеводов (на 100 г)?"],
            "options": [[a[0], a[1]], [b[0], b[1]]],
            "correct": 0 if low is a else 1,
            "e": [f"{a[0]}: ~{a[2]} g, {b[0]}: ~{b[2]} g. {low[5]}",
                  f"{a[1]}: ~{a[2]} г, {b[1]}: ~{b[2]} г. {low[6]}"],
        }
    return None


def option_order(item: dict, send_id: int) -> list[int]:
    """Shown position → option index. Quiz and duel options are shuffled
    (the bank lists the right quiz answer first, and duel keys follow FOODS
    order); a send always shows the same order, so an answer tapped days
    later still means the same option."""
    n = len(item["options"])
    if item["kind"] == "keto":            # "Ha" / "Yo'q" keep their order
        return list(range(n))
    order = list(range(n))
    random.Random(f"{send_id}:{item['key']}").shuffle(order)
    return order
