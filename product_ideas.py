"""«Bugun shundan nima tayyorlash mumkin» — kun mahsuloti uchun bir g'oya.

Kun mahsuloti e'loni mahsulot kartochkasini yuboradi (nomi, tavsifi, narxi).
Tavsif mahsulot nimaligini aytadi, lekin odamni harakatga undamaydi. Bitta
aniq g'oya — "bugun kechqurun shuni qiling" — undaydi, va u reklama kabi
o'qilmaydi, chunki mahsulotni emas, kechki ovqatni taklif qiladi.

Oilaga qarab yoziladi (product_descriptions bilan bir xil mantiq), shuning
uchun bitta g'oya o'sha oiladagi barcha o'lchovlarga yetadi va keyin
qo'shiladigan mahsulot ham o'z g'oyasini oladi.

Qisqa bo'lishi shart: kartochka Telegram'ga rasm izohi bo'lib ketadi, u
yerda jami 1024 belgi bor va asosiy qismi tavsif bilan narxga ketadi
(product_card.build_caption).

Shirinlashtirgich g'oyalari ataylab retsept ko'rinishida: eritritolni
"oling" deyish sotuvga o'xshaydi, "3 daqiqada shakarsiz kakao" esa
foydali maslahat bo'lib o'qiladi va o'zi bilan mahsulotni olib keladi.
"""

HEADING = {
    "uz": "💡 <b>Bugungi g'oya</b>",
    "ru": "💡 <b>Идея на сегодня</b>",
}

# family key -> {"uz": ..., "ru": ...}; keys match reco_content.PROFILES.
IDEAS = {
    "sweeteners": {
        "uz": "Issiq kakao: 1 stakan issiq sut + 1 osh qoshiq achchiq kakao "
              "+ 1 choy qoshiq shundan. Kakaoni avval quruq aralashtiring — "
              "quyuq bo'lib qolmaydi. Bir piyola ~2 gr uglevod.",
        "ru": "Горячее какао: стакан горячего молока + ложка горького какао "
              "+ чайная ложка этого. Какао сначала смешайте сухим — не будет "
              "комков. В чашке ~2 г углеводов.",
    },
    "almond_flour": {
        "uz": "Uch masalliqdan pechene: 200 gr shu un + 80 gr eritritol + "
              "1 tuxum. 180°C da 12 daqiqa. Bittasi ~2 gr uglevod.",
        "ru": "Печенье из трёх ингредиентов: 200 г этой муки + 80 г эритрита "
              "+ 1 яйцо. 180°C, 12 минут. В штуке ~2 г углеводов.",
    },
    "chia": {
        "uz": "Kechqurun 5 daqiqa — ertalab tayyor nonushta: 3 osh qoshiq shundan "
              "+ 200 ml sut + bir chimdim dolchin, muzlatgichga qo'ying.",
        "ru": "Вечером 5 минут — утром готовый завтрак: 3 ст. л. этого + 200 мл "
              "молока + щепотка корицы, оставьте в холодильнике.",
    },
    "coconut": {
        "uz": "5 daqiqalik quymoq: 2 tuxum + 2 osh qoshiq shu un + 2 osh qoshiq suv. "
              "Qizigan tovada ikki tomonini 2 daqiqadan pishiring.",
        "ru": "Панкейки за 5 минут: 2 яйца + 2 ст. л. этой муки + 2 ст. л. воды. "
              "По 2 минуты с каждой стороны.",
    },
    "cacao": {
        "uz": "Bir chimdim tuz qo'shib ko'ring — kakao ta'mi chuqurlashadi. "
              "Eritritol bilan birga issiq shokolad chiqadi, shakarsiz.",
        "ru": "Добавьте щепотку соли — вкус какао станет глубже. С эритритом "
              "получается горячий шоколад без сахара.",
    },
    "flax": {
        "uz": "Tuxum o'rniga: 1 osh qoshiq maydalangan shundan + 3 osh qoshiq suv, "
              "10 daqiqa turing. Pishiriqda bitta tuxumni almashtiradi.",
        "ru": "Вместо яйца: 1 ст. л. молотого + 3 ст. л. воды, настоять 10 минут. "
              "В выпечке заменяет одно яйцо.",
    },
    "oils": {
        "uz": "Ertalabki qahvaga 1 choy qoshiq qo'shib blenderda aylantiring — "
              "ko'pikli bo'ladi va tushgacha och qoldirmaydi.",
        "ru": "Добавьте чайную ложку в утренний кофе и взбейте блендером — "
              "получится пенка, и до обеда не проголодаетесь.",
    },
    "nuts": {
        "uz": "Bir hovuch — eng qulay gazak. Tuzsiz, qovurilmagan holda "
              "eng foydali; salat ustiga sepsangiz ham ta'm beradi.",
        "ru": "Горсть — самый удобный перекус. Полезнее несолёными и "
              "необжаренными; хороши и как посыпка для салата.",
    },
    "pastes": {
        "uz": "Olma bo'lagiga surtib bering — bolalar uchun shakarsiz shirinlik. "
              "Bo'tqaga qo'shsangiz, nonushta to'yimliroq bo'ladi.",
        "ru": "Намажьте на дольку яблока — десерт без сахара для детей. "
              "В каше делает завтрак сытнее.",
    },
    "fiber_supp": {
        "uz": "Glyutensiz non xamiriga 1-2 choy qoshiq qo'shing — xamir "
              "bog'lanadi va non to'kilmaydi.",
        "ru": "1–2 ч. л. в тесто для безглютенового хлеба — тесто свяжется "
              "и хлеб не будет крошиться.",
    },
    "salt": {
        "uz": "Keto boshlaganda bir chimdim ko'proq kerak bo'ladi: organizm "
              "suv bilan birga tuzni ham tez chiqaradi.",
        "ru": "В начале кето нужно чуть больше: организм быстро выводит соль "
              "вместе с водой.",
    },
    "sesame": {
        "uz": "Maydalab tahiniy qiling yoki salat ustiga seping — "
              "kalsiy bo'yicha sutdan qolishmaydi.",
        "ru": "Смелите в тахини или посыпьте салат — по кальцию не уступает "
              "молоку.",
    },
    "diet_rice": {
        "uz": "1 stakan yormaga 2 stakan suv. Losos tushonkasi bilan "
              "5 daqiqada to'liq tushlik bo'ladi.",
        "ru": "На 1 стакан крупы — 2 стакана воды. С тушёнкой из лосося "
              "получается полноценный обед за 5 минут.",
    },
    "honey": {
        "uz": "Issiq suvga solmang — foydasi kamayadi. Iliq choyga yoki "
              "bo'tqaga qo'shing.",
        "ru": "Не добавляйте в кипяток — польза теряется. Лучше в тёплый чай "
              "или кашу.",
    },
    "vinegar": {
        "uz": "Ovqatdan oldin 1 choy qoshiq bir stakan suvga — "
              "an'anaviy usul, hazmga yordam beradi.",
        "ru": "1 ч. л. на стакан воды перед едой — традиционный способ, "
              "помогает пищеварению.",
    },
    "keto_icecream": {
        "uz": "Muzlatgichdan olib 5 daqiqa turing — yumshab, ta'mi ochiladi. "
              "Ustidan yong'oq pastasi quysangiz, karamel o'rnini bosadi.",
        "ru": "Достаньте за 5 минут до подачи — станет мягче. Полейте ореховой "
              "пастой — заменит карамель.",
    },
    "pp_flour": {
        "uz": "Oq unning yarmini shu bilan almashtirib boshlang — "
              "ta'm deyarli o'zgarmaydi, tola esa ko'payadi.",
        "ru": "Начните с замены половины белой муки — вкус почти тот же, "
              "а клетчатки больше.",
    },
    "buckwheat": {
        "uz": "Bir kecha suvda ivitsangiz unib chiqadi — salatga qo'shsangiz "
              "foydasi eng yuqori bo'ladi.",
        "ru": "Замочите на ночь — прорастёт; в салате пользы больше всего.",
    },
    "sedana": {
        "uz": "Asal bilan aralashtirib kuniga yarim choy qoshiq — "
              "Sharqda asrlar davomida shunday ishlatilgan.",
        "ru": "Пол чайной ложки в день с мёдом — так его используют на Востоке "
              "веками.",
    },
}


def idea_for(family_key: str | None, lang: str = "uz") -> str | None:
    """The day's idea for this product family, or None when we have nothing
    worth saying — an empty heading is worse than no heading."""
    if not family_key:
        return None
    entry = IDEAS.get(family_key)
    if not entry:
        return None
    return entry.get("ru" if lang == "ru" else "uz")


ORDER_HEADING = {
    "uz": "🍳 <b>Bugun shundan nima tayyorlash mumkin</b>",
    "ru": "🍳 <b>Что можно приготовить из этого</b>",
}


def order_idea_block(items, lang: str = "uz") -> str | None:
    """An idea for the delivered order, chosen from what is actually in it.

    Rides inside the "yetkazildi" message rather than arriving as a message
    of its own: the buyer has the product in their hands right now, which is
    the one moment a recipe is worth more than a reminder — and the shop's
    one-personal-message-a-week budget (retention.py) stays free for the
    messages that bring people back.

    The priciest non-gift line wins, on the assumption that it is what the
    buyer was actually shopping for.
    """
    import product_descriptions

    best, best_value = None, -1.0
    for it in (items or []):
        if not isinstance(it, dict) or it.get("is_gift") or it.get("is_bonus"):
            continue
        name = (it.get("name") or "").strip()
        if not name:
            continue
        try:
            value = float(it.get("price") or 0) * float(it.get("quantity") or 0)
        except (TypeError, ValueError):
            continue
        if value > best_value and idea_for(product_descriptions.family_key(name), "uz"):
            best, best_value = name, value
    if not best:
        return None

    text = idea_for(product_descriptions.family_key(best), lang)
    if not text:
        return None
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        return lat_to_cyr(f"{ORDER_HEADING['uz']}\n{text}")
    return f"{ORDER_HEADING['ru' if lang == 'ru' else 'uz']}\n{text}"


def idea_block(product_name: str, lang: str = "uz") -> str | None:
    """Ready-to-append block for a product card, or None.

    Cyrillic Uzbek is transliterated from the Latin source at render time,
    same as everywhere else, so only uz + ru are written here.
    """
    import product_descriptions

    text = idea_for(product_descriptions.family_key(product_name), lang)
    if not text:
        return None
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        return lat_to_cyr(f"{HEADING['uz']}\n{text}")
    return f"{HEADING['ru' if lang == 'ru' else 'uz']}\n{text}"
