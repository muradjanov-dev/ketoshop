"""📞 Call Centre: operator zerikmasin (egasi, 2026-11-22).

Latifalar, kichik maqsad tabriklari, ruhlantiruvchi gaplar va «Tashakkurnoma»
matnlari. Sahifa (webapp/callcentre.html) ularni /cc/api/dashboard orqali
oladi, ertalabki bot xabari (call_centre_bot.py) — to'g'ridan-to'g'ri.

Qoidalar: hammasi o'zimizniki, hech kimni kamsitmaydi (qaynona, millat,
tana tuzilishi — yo'q), mahsulotni davo deb ko'rsatmaydi, «arzon» emas.
"""
import random

JOKES = [
    "— Nega har qo'ng'iroqdan keyin choy ichasiz?\n— Mijoz «o'ylab ko'raman» desa, men ham o'ylab ko'raman-da!",
    "Keto'chi do'stiga: «Kecha tushimda non ko'rdim».\n— Xo'sh, yedingmi?\n— Yo'q, uglevodini sanab o'tirib uyg'onib ketdim.",
    "Operator 80-qo'ng'iroqni yakunladi. Telefon pichirladi: «Endi meni ham zaryadga qo'ying, batareyam ham reja bajardi».",
    "— Dadajon, ishda nima qilasiz?\n— Odamlarga yaxshi maslahat beraman.\n— Unda menga ham qo'ng'iroq qiling, uy vazifasini qilishga ko'ndiring!",
    "Operator: «Assalomu alaykum, Keto Shopdan bezovta qilyapman».\nMijoz: «Bezovta qilmang, sotib olaman!»\nShunaqa qo'ng'iroq kuniga bitta bo'lsa ham kayfiyat yetarli 😄",
    "Keto'chi oshxonada: «Menga osh bering — guruchsiz, sabzisiz».\nOshpaz: «Unda sizga go'sht va katta hurmat beraman».",
    "— Nega kokos unini tanladingiz?\n— Bodom uni bilan biroz «tortishib» qoldik, endi kokos bilan do'stmiz.",
    "79-qo'ng'iroqdan keyin operator aytdi: «Eng qiziq qo'ng'iroq — 80-chisi. U reja bilan salyut o'rtasida turibdi!»",
    "Mijoz: «Uglevodsiz non bormi?»\nOperator: «Bor! Un bizdan, mahorat sizdan, maqtovni esa oilangiz aytadi».",
    "Ish kuni boshida — kofe, o'rtasida — choy, oxirida — mijozning «rahmat»i. Eng shirini oxirgisi, shakarsiz ham.",
    "— Telefon nega jiringlamayapti?\n— Chunki hamma sizning qo'ng'irog'ingizni kutyapti. Birinchi bo'lib siz qo'ng'iroq qiling!",
    "Keto'chining nonushtasi: pishloq, tuxum, salat. Kechki ovqati: salat, tuxum, pishloq. Tartibi o'zgaradi — kayfiyati o'zgarmaydi.",
    "Mijoz: «Ertaga qo'ng'iroq qiling».\nErtasi kuni: «Qanday eslab qoldingiz?»\nOperator: «Men emas, CRM eslab qoldi. U hech narsani unutmaydi — hatto tug'ilgan kuningizni ham».",
    "Do'sti so'radi: «Bugun 5 ta buyurtmani qanday olding?»\nOperator: «Gapirishdan ko'ra ko'proq tingladim».",
    "Mijoz: «Siz robotmisiz?»\nOperator: «Yo'q. Robot bo'lsam, tushlikni bunchalik kutmasdim».",
    "Bayramda hamma tort yeyapti, keto'chi esa sumkasidan bodom unli o'z tortini chiqardi. Yarim soatdan keyin hamma uning retseptini so'rayapti.",
    "Rahbar: «Nega bugun kayfiyatingiz zo'r?»\nOperator: «Mijoz maslahatimdan juda mamnun bo'ldi. Men esa 5 kilo stressni tashladim».",
    "— Bu shakarmi?\n— Yo'q, bu eritritol — shakarning odobli, tartibli ukasi.",
    "Operator stoliga yozib qo'ydi: «Tabassum telefonda ham eshitiladi». Shundan beri qo'shni stol ham kulib o'tiradi.",
    "Mijoz uch marta «o'ylab ko'raman» dedi. To'rtinchi qo'ng'iroqda o'zi so'radi: «Siz hali ham qo'ng'iroq qilasizmi? Unda yozing, qiziqib qoldim!»",
    "— Keto'da nima yesa bo'ladi?\n— Ko'p narsa.\n— Nima yesa bo'lmaydi?\n— Sevimli pishiriqlaringizning eski versiyasini. Yangisini bodom unidan qilamiz!",
    "Kun bo'yi telefonda gaplashgan operator uyda eshikni ochib: «Assalomu alaykum, Keto Shop…»\nOnasi: «Bolam, bu uy-ku!»",
    "Operator «qayta qo'ng'iroq qilaman» desa, albatta qiladi. Chunki u — so'zining va CRMning odami.",
    "Mijoz: «Stevia juda shirin ekan!»\nOperator: «Shuning uchun uni chimdim bilan solamiz — xuddi maqtovni ham me'yorida aytgandek».",
    "— Nima uchun operatorlar kam kasal bo'ladi?\n— Chunki kuniga 80 marta «salomatmisiz?» deb so'rashadi, kasallik ham uyalib qoladi.",
    "Yangi operator birinchi kuni: «Qancha qo'ng'iroq qilishim kerak?»\n— 80 ta.\n— Bir oydami?\n— Yo'q, bir kunda. Lekin har biridan keyin salyut bor!",
    "Mijoz: «Kokos uni kokosga o'xshaydimi?»\nOperator: «Ha, lekin palma ostida emas, oshxonangizda».",
    "Navbatchi kofe mashinasi operatorga: «Siz bugun 60 ta qo'ng'iroq qildingiz, men esa 6 ta kofe. Kim ko'proq ishladi — bahslashmaymiz».",
    "— CRMni nega har doim to'ldirasiz?\n— Kelajakdagi o'zimga hurmat. U ertaga 09:00 da menga rahmat aytadi.",
    "Operator tushlikda: «Bir soat gaplashmayman». 13:05 da: «Aytgancha, bilasizmi, alluloza nima?»",
]

MOTIVATION = [
    "Har bir «yo'q» sizni keyingi «ha»ga bir qadam yaqinlashtiradi.",
    "Siz shunchaki qo'ng'iroq qilmayapsiz — kimgadir sog'lom tanlov qilishga yordam beryapsiz.",
    "Tabassum bilan gapiring — u simdan ham o'tadi.",
    "Ko'p tinglang, kam gapiring: mijoz o'zi nima kerakligini aytib beradi.",
    "Kichik qadamlar katta natija beradi. Bitta qo'ng'iroq — bitta qadam.",
    "Bugungi mehnatingiz — ertangi takroriy mijoz.",
    "Bilim — eng yaxshi sotuvchi. Bugun ham 20 daqiqa o'rganing.",
    "Har bir mijoz — yangi hikoya. Uni qiziqib tinglang.",
    "Charchasangiz — chuqur nafas oling, suv iching va yana olg'a!",
    "Siz jamoaning ovozisiz. Ovozingiz iliq bo'lsin.",
    "Reja — yo'l xaritasi. Siz esa haydovchisiz.",
    "Bugun kimningdir kunini yaxshi maslahat bilan yorug' qiling.",
]

# Kichik maqsad tabriklari: metric → matnlar. {n} — erishilgan son.
SMALL_CHEERS = {
    "outbound": [
        "{n} ta qo'ng'iroq! Barmoqlaringiz isindi 🔥",
        "{n} ta! Telefon sizdan faxrlanyapti 📞",
        "Zo'r tezlik — {n} ta qo'ng'iroq ortda!",
        "{n} ta qo'ng'iroq — siz to'xtovsiz poyezdsiz 🚄",
    ],
    "meaningful": [
        "{n} ta mazmunli suhbat — odamlar sizni tinglashni yoqtiryapti 💬",
        "{n} ta chin suhbat! Siz haqiqiy maslahatchisiz 🌿",
        "{n} ta mazmunli suhbat — so'zlaringiz o'z o'rnini topyapti ✨",
    ],
    "orders": [
        "Bugungi {n}-buyurtma! Yo'l ochildi 🛒",
        "{n} ta buyurtma! Mijozlar sizga ishonyapti 💚",
        "{n}-buyurtma — omad sizni yaxshi ko'radi 🍀",
    ],
}

GOAL_CHEERS = {
    "outbound": "🎯 Kunlik qo'ng'iroq rejasi bajarildi! {n} ta — bu chinakam marafon!",
    "meaningful": "🎯 {n} ta mazmunli suhbat — bugungi suhbatlar rejasi to'ldi!",
    "orders": "🎯 {n} ta buyurtma — kunlik sotuv rejasi bajarildi! Siz zo'rsiz!",
}

RECORD_CHEERS = [
    "🚀 Rejadan tashqari {n}-buyurtma! Bu endi rekord hududi!",
    "🏆 {n} ta buyurtma! Reja ortda qoldi, siz esa olg'a ketyapsiz!",
    "🌟 {n}-buyurtma — bugun sizning kuningiz!",
]

THANKS = [
    "Bugungi mehnatingiz, sabringiz va mijozlarga ko'rsatgan e'tiboringiz uchun "
    "Keto Shop jamoasi nomidan chin dildan tashakkur bildiramiz.",
    "Siz bugun kunlik rejani to'liq bajardingiz. Har bir qo'ng'iroqdagi iliq so'zingiz "
    "va to'g'ri maslahatingiz uchun rahmat!",
    "Bugun ko'plab odamlarga sog'lom tanlovda yordam berdingiz. Mehnatingiz qadrlanadi — rahmat!",
]

METRIC_LABEL = {
    "outbound": "chiquvchi qo'ng'iroq",
    "meaningful": "mazmunli suhbat",
    "orders": "buyurtma",
}


def random_joke(rng: random.Random | None = None) -> str:
    return (rng or random).choice(JOKES)


def joke_of_day(day_ordinal: int) -> str:
    """Bir kun ichida bir xil latifa (ertalabki xabar va sahifa birinchi kartasi)."""
    return JOKES[day_ordinal % len(JOKES)]


def as_payload() -> dict:
    return {
        "jokes": JOKES,
        "motivation": MOTIVATION,
        "small": SMALL_CHEERS,
        "goal": GOAL_CHEERS,
        "record": RECORD_CHEERS,
        "thanks": THANKS,
        "labels": METRIC_LABEL,
    }
