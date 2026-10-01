"""
Shaxsiy tavsiyalar — a line of advice on the product card, chosen from what
this buyer bought before (owner, 2026-10-01/02).

    🍚 Qizil guruch (Devzira) 1000gr
    💡 Devzirani GHEE yog'ida qovursangiz, palovning hidi butun uyga taraladi 😋
    (description …)

Owner's rules for the copy, all applied below:
  * advice, never an order — "…qilsangiz", "…bo'ladi"; no "oling/qo'shing";
  * never "olgan edingiz / tanlagan edingiz", and never assume the earlier
    purchase is still in the kitchen — it may well be used up;
  * natural, the way a shop assistant talks; no repeated template openings;
  * it must change: every pair has three variants with different openings,
    and the buyer sees the next one each time they open the card;
  * shown right after the product name, before the description.

The same texts feed retention's "tavsiya" message (a push with a button to
the product), so the card and the push never disagree.

Products are matched by NAME into fine-grained keys (tip_key) — the family
matcher in product_descriptions is too coarse here: it puts stevia, erythritol
and allulose in one "sweeteners" family, GHEE and olive oil in one "oils".
Free lines (aksiya bonus, the campaign gift) are not purchases: everybody got
an Eritritol pack in September, which must not make everyone "an Eritritol
buyer".
"""
import json
import re
import time
from datetime import datetime

# ─────────────────────────────── matching ───────────────────────────────────

# Order matters: the first match wins ("Alluloza +Steviya" is allulose,
# "Kokos uni" is the flour, not "kokos").
_KEYS: list[tuple[str, str]] = [
    ("cacao_nibs", r"nibs|нибс"),
    ("pistachio_paste", r"xandonpista\s*pasta|фисташк\w*\s*паст"),
    ("peanut_paste", r"yeryong'?oq|арахис"),
    ("chocolate", r"shokolad|шоколад|победа|pobeda"),
    ("coconut_flour", r"kokos\s*un|кокосов\w*\s*мук"),
    ("coconut_cream", r"kokos\s*slivk|кокосов\w*\s*сливк"),
    ("almond_flour", r"bodom\s*un|миндал\w*\s*мук"),
    ("allulose", r"allulo|аллюл"),
    ("erythritol", r"eritr|эритр"),
    ("stevia", r"stevi|стеви"),
    ("devzira", r"devzira|девзир"),
    ("basmati", r"basmati|басмати"),
    ("black_rice", r"qora\s*guruch|ч[её]рн\w*\s*рис"),
    ("ghee", r"\bghee\b|\bгхи\b"),
    ("olive_oil", r"zaytun|зайтун|оливк"),
    ("vinegar", r"sirka|уксус"),
    ("salt", r"himalay|гималай|\btuz\b|\bсоль\b"),
    ("psyllium", r"psill|псилл"),
    ("xanthan", r"ksantan|ксантан"),
    ("chia", r"\bchia\b|\bчиа\b"),
    ("flax", r"zig'?ir|зиғир|зигир|льн"),
    ("sesame", r"kunjut|кунжут"),
    ("buckwheat", r"grechka|гречк"),
    ("sourdough", r"zakvaska|закваск|hamirturush|ҳамиртуруш"),
    ("bran_flour", r"kepak|javdar|отруб|ржан"),
    ("cinnamon", r"koritsa|корица|dolchin"),
]
_KEY_RE = [(k, re.compile(p, re.I)) for k, p in _KEYS]


def _norm(name: str) -> str:
    return re.sub(r"[‘’ʻʼ`´]", "'", (name or "").lower())


def tip_key(name: str) -> str | None:
    n = _norm(name)
    for key, rx in _KEY_RE:
        if rx.search(n):
            return key
    return None


# ─────────────────────────────── the copy ───────────────────────────────────
# PAIRS[(viewed, earlier)] = ([uz × 3], [ru × 3]). Uzbek is written in Latin;
# Cyrillic is produced by translit. "GHEE" is always followed by a space,
# never an apostrophe — see _cyr().

_P: dict[tuple[str, str], tuple[list[str], list[str]]] = {}


def _pair(viewed: str, earlier: str | tuple, uz: list[str], ru: list[str]) -> None:
    assert len(uz) == 3 and len(ru) == 3, (viewed, earlier)
    for e in (earlier if isinstance(earlier, tuple) else (earlier,)):
        _P[(viewed, e)] = (uz, ru)


# — Bodom uni —
_pair("almond_flour", "erythritol",
      ["Bodom uni va eritritol — shakarsiz pechenye uchun boshqa hech narsa kerak emas 🍪",
       "Shakarsiz pechenye qilmoqchimisiz? Bodom uni bilan eritritol shuning uchun yaratilgandek 🍪",
       "Bilasizmi, bodom unli pishiriq eritritol bilan shakardagidek shirin chiqadi 🍪"],
      ["Миндальная мука и эритритол — для печенья без сахара больше ничего и не нужно 🍪",
       "Хотите печенье без сахара? Миндальная мука с эритритолом будто созданы для этого 🍪",
       "А вы знали? С эритритолом выпечка на миндальной муке сладкая, как с сахаром 🍪"])
_pair("almond_flour", "ghee",
      ["Bodom unli xamirga bir qoshiq GHEE qo'shilsa, pishiriq sariyog'dek mayin chiqadi 🧈",
       "Pishiriq quruq chiqyaptimi? Bodom unli xamirga ozgina GHEE yog'i yordam beradi 🧈",
       "GHEE bilan bodom unli pishiriq sariyog' ta'mini oladi, shakar esa kerak bo'lmaydi 🧈"],
      ["Если добавить в тесто ложку гхи, выпечка выйдет нежной, как на сливочном масле 🧈",
       "Выпечка получается суховатой? Немного гхи в тесте на миндальной муке это исправит 🧈",
       "С гхи выпечка на миндальной муке получает сливочный вкус 🧈"])
_pair("almond_flour", "coconut_flour",
      ["Bodom va kokos unini aralashtirsangiz, kekslar yengil va nam chiqadi 🥥",
       "Kekslar og'irroq chiqyaptimi? Bodom uniga ozgina kokos uni ularni yengillashtiradi 🥥",
       "Ko'pchilik kekslar uchun bodom va kokos unini aralash ishlatadi — natija yengil va mayin 🥥"],
      ["Смесь миндальной и кокосовой муки делает кексы лёгкими и влажными 🥥",
       "Кексы выходят тяжеловатыми? Немного кокосовой муки к миндальной сделает их легче 🥥",
       "Миндальная и кокосовая мука — лучшая смесь для кексов 🥥"])
_pair("almond_flour", "xanthan",
      ["Bodom unli xamir uvalanib ketsa, bir chimdim ksantan hammasini joyiga qo'yadi 😄",
       "Xamir tutmayaptimi? Ksantan bodom unli xamirni bir-biriga bog'lab turadi 😄",
       "Bir chimdim ksantan — va bodom unli xamir egiluvchan, pishiriq esa butun chiqadi ✨"],
      ["Если тесто на миндальной муке крошится, щепотка ксантана быстро всё исправит 😄",
       "Тесто из миндальной муки не держится? Ксантан его свяжет 😄",
       "Миндальная мука и щепотка ксантана — тесто эластичное, выпечка не разваливается ✨"])
_pair("almond_flour", "peanut_paste",
      ["Bodom uni, yeryong'oq pastasi — va 15 daqiqada uy pechenyesi tayyor 🥜",
       "Choyga tez pechenye kerakmi? Bodom uni bilan yeryong'oq pastasi 15 daqiqada yordam beradi 🥜",
       "Yeryong'oq pastasi bodom unli pechenyeni mayin va to'yimli qiladi 🥜"],
      ["Миндальная мука плюс арахисовая паста — и через 15 минут домашнее печенье готово 🥜",
       "Нужно быстрое печенье к чаю? Миндальная мука и арахисовая паста справятся за 15 минут 🥜",
       "Арахисовая паста делает печенье на миндальной муке нежным и сытным 🥜"])
_pair("almond_flour", ("stevia", "allulose"),
      ["Bodom uni bilan steviya yoki alluloza — shakarsiz tort shundan boshlanadi 🎂",
       "Shakarsiz tort haqida o'ylayapsizmi? Asosi — bodom uni, shirinligi — steviya yoki alluloza 🎂",
       "Bilasizmi, bodom unli biskvit shakarsiz ham shirin chiqadi — gap shirinlantiruvchida 🎂"],
      ["С миндальной мукой и стевией или аллюлозой начинается торт без сахара 🎂",
       "Думаете о торте без сахара? Основа — миндальная мука, сладость — стевия или аллюлоза 🎂",
       "Бисквит на миндальной муке бывает сладким и без сахара — главное, правильный подсластитель 🎂"])

# — Eritritol —
_pair("erythritol", "almond_flour",
      ["Bodom unli pishiriqqa eritritol qo'shilsa, shirin bo'ladi, lekin shakarsiz 🧁",
       "Pishiriq qilyapsizmi? Eritritol bodom unli xamirga shirinlik beradi, shakarning o'zi esa bo'lmaydi 🧁",
       "Eritritol pishganda ham ta'mini yo'qotmaydi — bodom unli kekslar uchun ayni muddao 🧁"],
      ["С эритритолом выпечка на миндальной муке сладкая, но без сахара 🧁",
       "Печёте на миндальной муке? Эритритол даст сладость без самого сахара 🧁",
       "Эритритол не теряет вкус при выпечке — то, что нужно для кексов на миндальной муке 🧁"])
_pair("erythritol", "chocolate",
      ["Qora shokolad va eritritoldan uyda shakarsiz shokolad kremi chiqadi 🍫",
       "Shokoladli krem xohlaysizmi? Qora shokoladga ozgina eritritol — va shakarsiz tayyor 🍫",
       "Bilasizmi, eritritol qora shokoladning achchiqligini yumshatadi, ta'mini esa saqlaydi 🍫"],
      ["Из тёмного шоколада и эритритола дома получается шоколадный крем без сахара 🍫",
       "Хочется шоколадного крема? Тёмный шоколад и немного эритритола — и без сахара 🍫",
       "А вы знали? Эритритол смягчает горечь тёмного шоколада, сохраняя вкус 🍫"])
_pair("erythritol", "coconut_flour",
      ["Eritritol kokosning ta'mini bosib ketmaydi — pishiriq kokos hidi bilan chiqadi 🥥",
       "Kokos pechenyesiga shirinlik kerakmi? Eritritol kokos ta'mini to'liq saqlaydi 🥥",
       "Bilasizmi, kokos uni o'zi biroz shirin — eritritol bilan pishiriq desertga aylanadi 🥥"],
      ["Эритритол не перебивает кокос — выпечка пахнет именно кокосом 🥥",
       "Нужна сладость для кокосового печенья? Эритритол полностью сохраняет вкус кокоса 🥥",
       "Кокосовая мука сама слегка сладкая, а с эритритолом выпечка становится десертом 🥥"])
_pair("erythritol", "chia",
      ["Chia pudingiga bir choy qoshiq eritritol — va oddiy nonushta desertga aylanadi 🍮",
       "Puding chuchmalroq tuyuladimi? Chiaga bir choy qoshiq eritritol yetarli 🍮",
       "Eritritol bilan chia pudingi shirin, lekin shakarsiz bo'ladi 🍮"],
      ["Чайная ложка эритритола в чиа-пудинг — и обычный завтрак становится десертом 🍮",
       "Чиа-пудинг кажется пресным? Чайной ложки эритритола достаточно 🍮",
       "С эритритолом чиа-пудинг сладкий, но без сахара 🍮"])
_pair("erythritol", "cacao_nibs",
      ["Kakao nibs va eritritoldan shakarsiz granola qilsa bo'ladi 🥣",
       "Uy granolasini xohlaysizmi? Kakao nibs va ozgina eritritol — shakarsiz variant 🥣",
       "Eritritol kakao nibsning achchiqligini yumshatadi — nonushta uchun zo'r juftlik 🥣"],
      ["Из какао-нибс и эритритола получается гранола без сахара 🥣",
       "Хотите домашнюю гранолу? Какао-нибс и немного эритритола — вариант без сахара 🥣",
       "Эритритол смягчает горечь какао-нибс — отличная пара для завтрака 🥣"])

# — Steviya —
_pair("stevia", "chocolate",
      ["Qora shokolad achchiqroq tuyulsa, bir chimdim steviya yetarli 🍫",
       "Steviya qora shokoladni shirinroq qiladi, kaloriyasini esa oshirmaydi 🍫",
       "Uyda issiq shokolad qilyapsizmi? Steviya uni shakarsiz shirin qiladi ☕️"],
      ["Если тёмный шоколад кажется горьковатым, хватит щепотки стевии 🍫",
       "Со стевией тёмный шоколад становится слаще, а калорий не прибавляется 🍫",
       "Готовите горячий шоколад? Стевия сделает его сладким без сахара ☕️"])
_pair("stevia", "chia",
      ["Chia pudingiga steviyaning bir-ikki tomchisi kifoya 🍮",
       "Steviya juda oz ketadi: chia pudingi uchun bir-ikki tomchi — shuning uchun uzoqqa yetadi 🍮",
       "Ertalabki chia pudingi steviya bilan shakarsiz desertga aylanadi 🍮"],
      ["Для чиа-пудинга достаточно пары капель стевии 🍮",
       "Чтобы подсластить чиа-пудинг, стевии нужно совсем чуть-чуть — хватает надолго 🍮",
       "Утренний чиа-пудинг со стевией превращается в десерт без сахара 🍮"])
_pair("stevia", "coconut_cream",
      ["Kokos slivkali qahvaga ozgina steviya — shakarsiz latte tayyor ☕️",
       "Qahvani kokos slivkasi bilan ichasizmi? Bir tomchi steviya uni latte'ga aylantiradi ☕️",
       "Kafedagidek qahva uyda ham bo'ladi: kokos slivkasi va bir tomchi steviya ☕️"],
      ["Кофе с кокосовыми сливками и капелькой стевии — вот и латте без сахара ☕️",
       "Пьёте кофе с кокосовыми сливками? Капля стевии превратит его в латте ☕️",
       "Кокосовые сливки и стевия — кофе как в кофейне, только без сахара ☕️"])
_pair("stevia", "erythritol",
      ["Eritritol va steviyani aralashtirsangiz, shirinlik yumshoqroq chiqadi ✨",
       "Steviyaning o'ziga xos ta'mi bezovta qilsa, eritritol bilan aralashtirish yaxshi yechim ✨",
       "Bilasizmi, steviya va eritritol birga ishlatilsa, ikkalasi ham kamroq ketadi ✨"],
      ["Если смешать эритритол со стевией, сладость получается мягче ✨",
       "Если смущает особый вкус стевии, смесь с эритритолом — хорошее решение ✨",
       "А вы знали? Вместе стевии и эритритола уходит меньше, чем по отдельности ✨"])

# — Alluloza —
_pair("allulose", "almond_flour",
      ["Alluloza bilan bodom unli pishiriq xuddi shakardagidek qizarib pishadi 🥐",
       "Pishiriq oqarib qolyaptimi? Alluloza unga chiroyli tilla rang beradi 🥐",
       "Bilasizmi, alluloza shakarsiz pishiriqqa ham qarsildoq qobiq beradi 🥐"],
      ["С аллюлозой выпечка на миндальной муке румянится, как с обычным сахаром 🥐",
       "Выпечка остаётся бледной? Аллюлоза даст ей красивый золотистый цвет 🥐",
       "А вы знали? Аллюлоза даёт хрустящую корочку даже выпечке без сахара 🥐"])
_pair("allulose", "coconut_flour",
      ["Kokos uni va alluloza — eng oson shakarsiz kokos pechenyesi 🥥🍪",
       "Pechenye qilmoqchimisiz? Kokos uni va alluloza bilan u deyarli o'zi pishadi 🥥🍪",
       "Alluloza kokos pishiriqlarini shirin va tilla rangli qiladi 🥥"],
      ["Кокосовая мука и аллюлоза — самое простое кокосовое печенье без сахара 🥥🍪",
       "Собираетесь печь кокосовое печенье? С аллюлозой оно почти печётся само 🥥🍪",
       "Аллюлоза делает кокосовую выпечку сладкой и золотистой 🥥"])
_pair("allulose", "peanut_paste",
      ["Alluloza va yeryong'oq pastasidan cho'ziluvchan uy karameli chiqadi 🍯",
       "Shakarsiz karamel xohlaysizmi? Alluloza xuddi shakardek eriydi va cho'ziladi 🍯",
       "Yeryong'oq pastasi va alluloza — uy batonchigi uchun tayyor asos 🍯"],
      ["Из аллюлозы и арахисовой пасты выходит тягучая домашняя карамель 🍯",
       "Хочется карамели без сахара? Аллюлоза плавится и тянется, как сахар 🍯",
       "Арахисовая паста и аллюлоза — готовая основа для домашних батончиков 🍯"])
_pair("allulose", "stevia",
      ["Steviyaga ozgina alluloza qo'shilsa, achchiq ta'mi umuman sezilmaydi ✨",
       "Steviyaning ta'mi sizga og'irroqmi? Alluloza bilan shirinlik toza chiqadi ✨",
       "Alluloza va steviya — shakarga eng yaqin ta'mli juftlik ✨"],
      ["Если добавить к стевии немного аллюлозы, горчинка совсем пропадает ✨",
       "Вкус стевии кажется резким? С аллюлозой сладость становится чистой ✨",
       "Аллюлоза и стевия — пара, по вкусу ближе всего к сахару ✨"])

# — Devzira —
_pair("devzira", "ghee",
      ["Devzirani GHEE yog'ida qovursangiz, palovning hidi butun uyga taraladi 😋",
       "Palov qilmoqchimisiz? GHEE va Devzira bilan ta'mi to'yxonadagidek chiqadi 🍚",
       "Bilasizmi, Devzira yog'ni yaxshi shimadi — GHEE bilan har bir donasi yaltirab turadi ✨"],
      ["Если обжарить девзиру на гхи, аромат плова разойдётся по всему дому 😋",
       "Собираетесь готовить плов? С гхи и девзирой он получится как на свадьбе 🍚",
       "А вы знали? Девзира хорошо впитывает масло — с гхи каждое зёрнышко блестит ✨"])
_pair("devzira", "olive_oil",
      ["Zaytun yog'ida dimlangan Devzira yengilroq, lekin baribir xushbo'y bo'ladi 🌿",
       "Yengilroq palov xohlaysizmi? Devzira zaytun yog'ida ham ajoyib chiqadi 🌿",
       "Devzira va zaytun yog'i — yengil, lekin to'yimli kechki ovqat 🌿"],
      ["Девзира на оливковом масле получается полегче, но такой же ароматной 🌿",
       "Хочется плов полегче? Девзира отлично получается и на оливковом масле 🌿",
       "Девзира и оливковое масло — лёгкий, но сытный ужин 🌿"])
_pair("devzira", "black_rice",
      ["Devzira va qora guruch bir dasturxonda — ko'rinishi ham, ta'mi ham boshqacha 🍚",
       "Mehmon kutyapsizmi? Devzira va qora guruch dasturxonni bezatadi 🍚",
       "Qora guruchga Devzira qo'shilsa, garnir rang-barang va xushbo'y chiqadi 🍚"],
      ["Девзира и чёрный рис на одном столе — и красиво, и вкусно 🍚",
       "Ждёте гостей? Девзира и чёрный рис украсят стол 🍚",
       "Если смешать девзиру с чёрным рисом, гарнир выйдет ярким и ароматным 🍚"])
_pair("devzira", "salt",
      ["Devzirali palovga bir chimdim pushti tuz ta'mini tiniqroq qiladi 🧂",
       "Palov ta'mi to'liq ochilmayaptimi? Himalay tuzi yordam berishi mumkin 🧂",
       "Himalay tuzi Devziraning tabiiy ta'mini yanada yorqin qiladi 🧂"],
      ["Щепотка розовой соли делает вкус плова из девзиры ярче 🧂",
       "Вкус плова не раскрывается до конца? Гималайская соль может помочь 🧂",
       "Гималайская соль подчёркивает естественный вкус девзиры 🧂"])

# — GHEE —
_pair("ghee", "devzira",
      ["GHEE yog'ida qovurilgan Devzira — palov hidi qo'shnilargacha yetadi 😋",
       "Devzirali palov uchun eng yaxshi yog' qaysi? Ko'pchilik GHEE deydi 😋",
       "Bilasizmi, GHEE kuchli olovda ham kuymaydi — palov qovurish uchun ayni muddao 🍚"],
      ["Девзира на гхи — запах плова дойдёт и до соседей 😋",
       "Какое масло лучше для плова из девзиры? Многие скажут — гхи 😋",
       "Гхи не горит даже на сильном огне — то, что нужно для плова 🍚"])
_pair("ghee", "basmati",
      ["Basmatini GHEE yog'ida dimlasangiz, guruch donalari bir-biriga yopishmaydi ✨",
       "Basmati yopishib qolyaptimi? Bir qoshiq GHEE har bir donani alohida qiladi ✨",
       "GHEE bilan basmati restoranlardagidek xushbo'y chiqadi ✨"],
      ["Если готовить басмати на гхи, рис получается рассыпчатым ✨",
       "Басмати слипается? Ложка гхи сделает каждое зёрнышко отдельным ✨",
       "С гхи басмати получается ароматным, как в ресторане ✨"])
_pair("ghee", "almond_flour",
      ["GHEE pishiriqqa sariyog' ta'mini beradi va oson kuyib qolmaydi 🧈",
       "Bodom unli pishiriq uchun yog' tanlayapsizmi? GHEE xamirni mayin qiladi 🧈",
       "Bilasizmi, GHEE sariyog'ning ta'mini beradi, lekin ancha uzoq saqlanadi 🧈"],
      ["Гхи даёт выпечке сливочный вкус и не так легко пригорает 🧈",
       "Выбираете масло для выпечки на миндальной муке? Гхи делает тесто нежным 🧈",
       "А вы знали? Гхи даёт вкус сливочного масла, но хранится гораздо дольше 🧈"])
_pair("ghee", "buckwheat",
      ["Grechka bo'tqasiga bir qoshiq GHEE — ta'mi butunlay boshqacha bo'ladi 🥣",
       "Bo'tqa quruqroq tuyuladimi? Grechkaga ozgina GHEE uni mayin va xushbo'y qiladi 🥣",
       "GHEE bilan grechka oddiy garnirdan alohida taomga aylanadi 🥣"],
      ["Ложка гхи в гречневую кашу — и вкус совсем другой 🥣",
       "Гречка кажется суховатой? Немного гхи сделает её нежной и ароматной 🥣",
       "С гхи гречка из простого гарнира превращается в отдельное блюдо 🥣"])

# — Zaytun yog'i —
_pair("olive_oil", "vinegar",
      ["Zaytun yog'i va olma sirkasi — salat sousi bir daqiqada tayyor 🥗",
       "Salatga sous kerakmi? Zaytun yog'iga bir qoshiq olma sirkasi kifoya 🥗",
       "Olma sirkasi zaytun yog'i bilan eng mazali va oddiy sousni beradi 🥗"],
      ["Оливковое масло и яблочный уксус — заправка для салата за минуту 🥗",
       "Нужна заправка? Достаточно ложки яблочного уксуса к оливковому маслу 🥗",
       "Яблочный уксус с оливковым маслом — самая простая и вкусная заправка 🥗"])
_pair("olive_oil", "salt",
      ["Zaytun yog'i va bir chimdim Himalay tuzi oddiy salatni ham mazali qiladi ✨",
       "Oddiy pomidor-bodringni bezatmoqchimisiz? Zaytun yog'i va pushti tuz yetadi ✨",
       "Himalay tuzi va zaytun yog'i — ortiqcha hech narsasiz eng toza ta'm ✨"],
      ["Оливковое масло и щепотка гималайской соли делают вкусным даже простой салат ✨",
       "Хотите украсить обычный салат? Достаточно оливкового масла и розовой соли ✨",
       "Гималайская соль и оливковое масло — чистый вкус без лишнего ✨"])
_pair("olive_oil", ("sesame", "flax"),
      ["Salatga zaytun yog'i quyib, ustidan kunjut sepilsa — bo'ldi, tayyor 🥗",
       "Salat zerikarli tuyulyaptimi? Zaytun yog'i va urug'lar uni qarsildoq qiladi 🥗",
       "Urug'lar zaytun yog'i bilan salatda ayniqsa mazali ochiladi 🥗"],
      ["Оливковое масло и немного кунжута сверху — и салат готов 🥗",
       "Салат кажется скучным? Оливковое масло и семена сделают его хрустящим 🥗",
       "С оливковым маслом семена в салате особенно хорошо раскрываются 🥗"])
_pair("olive_oil", "devzira",
      ["Devzirani zaytun yog'ida pishirsangiz ham juda xushbo'y chiqadi 🌿",
       "Yengilroq palov xohlasangiz, zaytun yog'i yaxshi tanlov 🌿",
       "Zaytun yog'idagi Devzira — kunduzgi yengil ovqat uchun 🌿"],
      ["Девзира на оливковом масле тоже получается очень ароматной 🌿",
       "Если хочется плов полегче, оливковое масло — хороший выбор 🌿",
       "Девзира на оливковом масле — лёгкий обед 🌿"])

# — Psillium —
_pair("psyllium", "flax",
      ["Keto-non qattiq chiqyaptimi? Bir qoshiq psillium uni yumshatadi 🍞",
       "Zig'ir unidan non yopsangiz, psillium uni ko'pchigan va yumshoq qiladi 🍞",
       "Bilasizmi, psillium keto-nonda gluten vazifasini bajaradi 🍞"],
      ["Кето-хлеб получается твёрдым? Ложка псиллиума сделает его мягче 🍞",
       "Если печь хлеб из льняной муки, псиллиум сделает его пышным и мягким 🍞",
       "А вы знали? В кето-хлебе псиллиум работает вместо глютена 🍞"])
_pair("psyllium", "almond_flour",
      ["Psillium bodom unli xamirni egiluvchan qiladi — non uvalanmaydi 🍞",
       "Bodom unidan non yopmoqchimisiz? Psillium xamirni yaxlit ushlab turadi 🍞",
       "Haqiqiy nonga o'xshash keto-non bodom uni va psilliumdan chiqadi 🍞"],
      ["Псиллиум делает тесто на миндальной муке эластичным — хлеб не крошится 🍞",
       "Хотите испечь хлеб из миндальной муки? Псиллиум удержит тесто 🍞",
       "Миндальная мука и псиллиум — кето-хлеб, похожий на настоящий 🍞"])
_pair("psyllium", "coconut_flour",
      ["Kokos unli xamir yopishmay qolsa, ozgina psillium uni birlashtiradi ✨",
       "Xamir tarqalib ketyaptimi? Psillium kokos unli xamirni bir joyda ushlaydi ✨",
       "Yumshoq va yaxlit pishiriq kerak bo'lsa, kokos uniga psillium yaxshi hamroh ✨"],
      ["Если тесто на кокосовой муке не держится, немного псиллиума его свяжет ✨",
       "Тесто из кокосовой муки рассыпается? Псиллиум его соберёт ✨",
       "Кокосовая мука и псиллиум — мягкая и цельная выпечка ✨"])

# — Ksantan —
_pair("xanthan", "almond_flour",
      ["Bodom unli xamir uvalansa, bir chimdim ksantan qo'shib ko'rish mumkin 😄",
       "Pishiriq uvalanib ketyaptimi? Bodom unli xamirga ksantan eng oddiy yechim ✨",
       "Ksantan juda oz ketadi: bir chimdimi butun xamirni ushlab turadi 😄"],
      ["Если тесто на миндальной муке крошится, можно попробовать щепотку ксантана 😄",
       "Выпечка на миндальной муке часто крошится — ксантан самое простое решение ✨",
       "Ксантана нужно совсем чуть-чуть: щепотка держит всё тесто 😄"])
_pair("xanthan", "coconut_cream",
      ["Kokos slivkali krem oqib ketmasligi uchun ozgina ksantan yetadi 🍰",
       "Krem shaklini ushlamayaptimi? Ksantan kokos kremini qalinlashtiradi 🍰",
       "Bir chimdim ksantan bilan kokos slivkasi tortga mos kremga aylanadi 🍰"],
      ["Чтобы крем на кокосовых сливках не растекался, хватит капельки ксантана 🍰",
       "Кокосовый крем не держит форму? Ксантан его загустит 🍰",
       "Со щепоткой ксантана кокосовые сливки становятся кремом для торта 🍰"])

# — Kokos uni —
_pair("coconut_flour", "almond_flour",
      ["Bodom uniga ozgina kokos uni qo'shilsa, pishiriq yumshoqroq chiqadi 🥥",
       "Yangi ta'm sinab ko'rmoqchimisiz? Bodom va kokos unining aralashmasi juda mayin 🥥",
       "Kokos uni bodom unli pishiriqqa yengil kokos hidini beradi 🥥"],
      ["Немного кокосовой муки к миндальной — и выпечка получается мягче 🥥",
       "Хотите попробовать новый вкус? Смесь миндальной и кокосовой муки очень нежная 🥥",
       "Кокосовая мука добавляет выпечке на миндальной муке лёгкий аромат кокоса 🥥"])
_pair("coconut_flour", ("erythritol", "allulose"),
      ["Kokos uni o'zi biroz shirin — shirinlantiruvchi kamroq ketadi 🍪",
       "Shirinlantiruvchini tejamoqchimisiz? Kokos unli pishiriqqa u kamroq ketadi 🍪",
       "Bilasizmi, kokos uni pishiriqqa tabiiy shirinlik beradi 🍪"],
      ["Кокосовая мука сама немного сладкая — подсластителя уйдёт меньше 🍪",
       "В выпечку на кокосовой муке нужно меньше сладкого — мука сама слаще 🍪",
       "А вы знали? Кокосовая мука даёт выпечке природную сладость 🍪"])
_pair("coconut_flour", "coconut_cream",
      ["Kokos uni va kokos slivkasi bo'lsa, butun boshli kokos deserti chiqadi 🥥",
       "Tort ham, krem ham bitta ta'mda — kokos uni va kokos slivkasidan 🥥",
       "Bilasizmi, kokos uni va slivkasidan butun boshli desert chiqadi 🥥"],
      ["Из кокосовой муки и кокосовых сливок выйдет целый кокосовый десерт 🥥",
       "Любите кокос? Из кокосовой муки и сливок получится и торт, и крем 🥥",
       "Кокосовая мука и сливки — целый десерт в одном вкусе 🥥"])

# — Kokos slivka —
_pair("coconut_cream", "chia",
      ["Chiani kechqurun kokos slivkasiga solib qo'ysangiz, ertalab puding tayyor 🍮",
       "Ertalab vaqt yo'qmi? Kokos slivkasida bir kecha turgan chia — tayyor nonushta 🍮",
       "Kokos slivkasi chia pudingini qaymoqdek mayin qiladi 🍮"],
      ["Если залить чиа кокосовыми сливками с вечера, утром будет готовый пудинг 🍮",
       "Утром нет времени? Чиа, постоявшая ночь в кокосовых сливках, — готовый завтрак 🍮",
       "Кокосовые сливки делают чиа-пудинг нежным, как крем 🍮"])
_pair("coconut_cream", "coconut_flour",
      ["Kokos pishiriqqa kokos slivkali krem — kokos ta'mi ikki baravar 🥥",
       "Keksga krem kerakmi? Kokos slivkasi kokos unli pishiriqqa eng mos keladi 🥥",
       "Bilasizmi, kokos slivkasi kokos unli pishiriqni haqiqiy desertga aylantiradi 🥥"],
      ["Крем на кокосовых сливках к кокосовой выпечке — вкус кокоса вдвойне 🥥",
       "Нужен крем для кокосового кекса? Кокосовые сливки подойдут лучше всего 🥥",
       "Кокосовые сливки превращают выпечку на кокосовой муке в настоящий десерт 🥥"])
_pair("coconut_cream", "chocolate",
      ["Kokos slivkasida issiq shokolad quyuq va mayin chiqadi ☕️",
       "Sovuq kechada issiq shokolad xohlaysizmi? Kokos slivkasi uni quyuq qiladi ☕️",
       "Qora shokolad va kokos slivkasi — bir krujkada kichik bayram ☕️"],
      ["На кокосовых сливках горячий шоколад получается густым и нежным ☕️",
       "Хочется горячего шоколада холодным вечером? Кокосовые сливки сделают его густым ☕️",
       "Тёмный шоколад и кокосовые сливки — маленький праздник в одной кружке ☕️"])

# — Qora shokolad —
_pair("chocolate", "stevia",
      ["Shokolad granula va bir chimdim steviya — shakarsiz issiq shokolad ☕️",
       "Shirinlikka ishtiyoq bormi? Qora shokolad va steviya shakarsiz yechim ☕️",
       "Steviya bilan qora shokolad granula sutli shokoladdek shirin bo'ladi 🍫"],
      ["Шоколадные гранулы и щепотка стевии — горячий шоколад без сахара ☕️",
       "Тянет на сладкое? Тёмный шоколад и стевия — решение без сахара ☕️",
       "Со стевией тёмный шоколад в гранулах сладкий, как молочный 🍫"])
_pair("chocolate", "almond_flour",
      ["Bodom unli keksga shokolad granula qo'shilsa, brauni chiqadi 🍫",
       "Brauni yoqadimi? Bodom uni va qora shokolad — shakarsiz varianti 🍫",
       "Shokolad granula bodom unli pishiriqni yanada mazali qiladi 🍫"],
      ["Если добавить шоколадные гранулы в кекс на миндальной муке, получится брауни 🍫",
       "Любите брауни? Миндальная мука и тёмный шоколад — вариант без сахара 🍫",
       "Шоколадные гранулы делают выпечку на миндальной муке ещё вкуснее 🍫"])
_pair("chocolate", "coconut_cream",
      ["Shokolad granula va kokos slivkasidan 5 daqiqada ganash tayyorlanadi ✨",
       "Tortga glazur kerakmi? Qora shokolad va kokos slivkasi 5 daqiqada yetadi ✨",
       "Kokos slivkasi bilan eritilgan shokolad — mayin va yaltiroq krem ✨"],
      ["Из шоколадных гранул и кокосовых сливок ганаш готовится за 5 минут ✨",
       "Нужна глазурь для торта? Тёмный шоколад и кокосовые сливки — 5 минут ✨",
       "Растопленный шоколад с кокосовыми сливками — нежный и блестящий крем ✨"])

# — Chia —
_pair("chia", "coconut_cream",
      ["Kechqurun chia bilan kokos slivkasini aralashtirib qo'ysangiz, ertalab nonushta tayyor 🌙🍮",
       "Tez va to'yimli nonushta qidiryapsizmi? Chia va kokos slivkasi aynan shunday 🍮",
       "Chia kokos slivkasida bo'kib, mayin pudingga aylanadi 🍮"],
      ["Если вечером смешать чиа с кокосовыми сливками, утром завтрак уже готов 🌙🍮",
       "Ищете быстрый и сытный завтрак? Чиа и кокосовые сливки — именно он 🍮",
       "Чиа набухает в кокосовых сливках и превращается в нежный пудинг 🍮"])
_pair("chia", ("stevia", "erythritol"),
      ["Chia pudingiga ozgina shirinlantiruvchi — nonushta desertga aylanadi 🍓",
       "Shakarsiz ham shirin: chia pudingiga ozgina shirinlantiruvchi yetadi 🍓",
       "Shirinlikni sevasizmi? Chia pudingi eng sog'lom desertlardan biri 🍓"],
      ["Немного подсластителя в чиа-пудинг — и завтрак превращается в десерт 🍓",
       "Чиа-пудинг бывает сладким и без сахара — хватит капли подсластителя 🍓",
       "Любите сладкое? Чиа-пудинг — один из самых полезных десертов 🍓"])

# — Zig'ir —
_pair("flax", "psyllium",
      ["Zig'ir uni va psillium — keto-non uchun eng yaxshi juftlik 🍞",
       "Uyda keto-non yopmoqchimisiz? Zig'ir uni va psillium — asosiy ikki ingredient 🍞",
       "Psillium bilan zig'ir unli non yumshoq va ko'pchigan chiqadi 🍞"],
      ["Льняная мука и псиллиум — лучшая пара для кето-хлеба 🍞",
       "Хотите испечь кето-хлеб дома? Льняная мука и псиллиум — два главных ингредиента 🍞",
       "С псиллиумом хлеб из льняной муки получается мягким и пышным 🍞"])
_pair("flax", "sesame",
      ["Zig'ir urug'i va kunjutni salat ustiga sepsangiz, qarsillab turadi 🥗",
       "Salatga qarsildoqlik yetishmayaptimi? Zig'ir va kunjut aralashmasi yordam beradi 🥗",
       "Bo'tqa, salat yoki qatiq — zig'ir urug'i va kunjut hammasiga mos 🥗"],
      ["Семена льна с кунжутом в салате приятно хрустят 🥗",
       "Салату не хватает хруста? Помогут лён и кунжут 🥗",
       "Семена льна и кунжут — отличная добавка к салату, каше и йогурту 🥗"])
_pair("flax", "sourdough",
      ["Zakvaskali nonga ozgina zig'ir uni qo'shilsa, yong'oqqa o'xshash ta'm beradi 🥖",
       "Uy noningizni boyitmoqchimisiz? Zig'ir uni zakvaskali nonga ajoyib ta'm qo'shadi 🥖",
       "Zig'ir uni zakvaskali nonni to'yimliroq qiladi 🥖"],
      ["Немного льняной муки в хлеб на закваске даёт ореховый привкус 🥖",
       "Хотите сделать домашний хлеб интереснее? Льняная мука добавит закваске вкуса 🥖",
       "Льняная мука делает хлеб на закваске сытнее 🥖"])

# — Grechka —
_pair("buckwheat", "peanut_paste",
      ["Grechka quymog'i ustiga yeryong'oq pastasi surtilsa — mazali nonushta 👑",
       "Dam olish kuni nonushtasiga g'oya kerakmi? Grechka quymog'i va yeryong'oq pastasi 👑",
       "Yeryong'oq pastasi grechka quymog'ini bolalar ham yaxshi ko'radigan taomga aylantiradi 👑"],
      ["Гречневые блинчики с арахисовой пастой — вкусный завтрак 👑",
       "Нужна идея для завтрака в выходной? Гречневые блинчики с арахисовой пастой 👑",
       "С арахисовой пастой гречневые блинчики полюбят даже дети 👑"])
_pair("buckwheat", "ghee",
      ["Yashil grechkani GHEE bilan dimlasangiz, yengil va to'yimli garnir chiqadi 🥣",
       "Kechki ovqatga yengil garnir kerakmi? Grechka va bir qoshiq GHEE yetadi 🥣",
       "GHEE grechkaga yong'oqsimon ta'm beradi 🥣"],
      ["Зелёная гречка на гхи — лёгкий и сытный гарнир 🥣",
       "Нужен лёгкий гарнир к ужину? Гречка и ложка гхи 🥣",
       "Гхи придаёт гречке ореховый вкус 🥣"])

# — Pastalar —
_pair("peanut_paste", "almond_flour",
      ["Bodom unli pechenyega bir qoshiq yeryong'oq pastasi — ta'mi ancha boyiydi 🥜",
       "Pechenye qurib qolyaptimi? Yeryong'oq pastasi uni mayin va namroq qiladi 🥜",
       "Yeryong'oq pastasi va bodom uni — 15 daqiqalik uy pechenyesi 🥜"],
      ["Ложка арахисовой пасты делает печенье на миндальной муке вкуснее 🥜",
       "Печенье получается сухим? Арахисовая паста сделает его нежнее 🥜",
       "Арахисовая паста и миндальная мука — домашнее печенье за 15 минут 🥜"])
_pair("pistachio_paste", "chocolate",
      ["Xandonpista pastasi va qora shokolad — uydagi \"Dubay shokoladi\" 🍫💚",
       "Mashhur Dubay shokoladini uyda qilmoqchimisiz? Xandonpista pastasi va qora shokolad yetadi 🍫💚",
       "Bilasizmi, xandonpista pastasi va qora shokolad — eng chiroyli juftliklardan biri 🍫💚"],
      ["Фисташковая паста и тёмный шоколад — «дубайский шоколад» в домашнем варианте 🍫💚",
       "Хотите повторить знаменитый дубайский шоколад дома? Хватит фисташковой пасты и тёмного шоколада 🍫💚",
       "Фисташковая паста — очень красивая пара для тёмного шоколада 🍫💚"])

# — Guruchlar —
_pair("basmati", "ghee",
      ["Basmatini GHEE yog'ida pishirsangiz, har bir donasi alohida va xushbo'y chiqadi ✨",
       "Basmati uchun yog' tanlayapsizmi? GHEE uni restorandagidek qiladi ✨",
       "GHEE va basmati — oddiy garnir, lekin mehmonlar albatta so'raydi ✨"],
      ["Басмати на гхи получается рассыпчатым и ароматным ✨",
       "Выбираете масло для басмати? Гхи сделает его как в ресторане ✨",
       "Гхи и басмати — простой гарнир, но гости обязательно спросят рецепт ✨"])
_pair("black_rice", "devzira",
      ["Qora guruch dasturxonda ko'zga tashlanadi — to'yimli va chiroyli 🍚",
       "Yangi guruch sinab ko'rmoqchimisiz? Qora guruch rangi va ta'mi bilan ajralib turadi 🍚",
       "Salat va garnirlarda qora guruch ayniqsa chiroyli ko'rinadi 🍚"],
      ["Чёрный рис сразу привлекает внимание на столе — сытный и красивый 🍚",
       "Хотите попробовать новый рис? Чёрный выделяется и цветом, и вкусом 🍚",
       "Чёрный рис особенно красиво смотрится в салатах и гарнирах 🍚"])

# — Boshqalar —
_pair("vinegar", "olive_oil",
      ["Zaytun yog'iga bir qoshiq olma sirkasi — salat sousi tayyor 🥗",
       "Salat sousi uchun murakkab narsa shart emas: zaytun yog'i va olma sirkasi yetadi 🥗",
       "Olma sirkasi salatga yengil nordonlik beradi 🥗"],
      ["Ложка яблочного уксуса к оливковому маслу — и заправка готова 🥗",
       "Для заправки ничего сложного не нужно: оливковое масло и яблочный уксус 🥗",
       "Яблочный уксус добавляет салату лёгкую кислинку 🥗"])
_pair("cacao_nibs", "coconut_cream",
      ["Kokos slivkali desert ustiga bir hovuch kakao nibs — restorandagidek 🍨",
       "Desertga qarsildoqlik kerakmi? Kakao nibs kokos kremi bilan ajoyib 🍨",
       "Kakao nibs shokolad ta'mini shakarsiz beradi 🍨"],
      ["Горсть какао-нибс сверху — и десерт на кокосовых сливках как из ресторана 🍨",
       "Десерту не хватает хруста? Какао-нибс отлично сочетаются с кокосовым кремом 🍨",
       "Какао-нибс дают шоколадный вкус без сахара 🍨"])
_pair("sourdough", "bran_flour",
      ["Kepakli undan nonni tabiiy zakvaska bilan yopsangiz, ta'mi ancha boshqacha bo'ladi 🥖",
       "Uy noni xamirturushsiz ham bo'ladi — tabiiy zakvaska bilan ✨",
       "Zakvaskali non uzoqroq yumshoq turadi 🥖"],
      ["Хлеб из отрубной муки на натуральной закваске — совсем другой вкус 🥖",
       "Домашний хлеб можно печь и без дрожжей — на натуральной закваске ✨",
       "Хлеб на закваске дольше остаётся мягким 🥖"])
_pair("cinnamon", ("erythritol", "almond_flour"),
      ["Bir chimdim koritsa shakarsiz pishiriqni shirinroq his qildiradi 🍂",
       "Shakarsiz pishiriq chuchmal tuyuladimi? Koritsa ta'mini ochib beradi 🍂",
       "Koritsa va bodom uni — kuzgi uy pishiriqlarining hidi 🍂"],
      ["Щепотка корицы делает выпечку без сахара будто слаще 🍂",
       "Выпечка без сахара кажется пресной? Корица раскроет вкус 🍂",
       "Корица и миндальная мука — запах осенней домашней выпечки 🍂"])

PAIRS = _P

# Another size of something the buyer already knows.
SIZE: tuple[list[str], list[str]] = (
    ["Doim ishlatsangiz, katta qadoq qulayroq va hamyonboproq 😊",
     "Katta qadoq bilan \"tugab qoldi\" degan kun ancha kech keladi 🙂",
     "Kichik qadog'i yangi retseptni sinab ko'rish uchun juda qulay ✨",
     "Kichik hajmi sovg'a uchun ham chiroyli variant 🎁",
     "Shu mahsulotning boshqa hajmi ham bor — ehtiyojga qarab tanlash oson 😊"],
    ["Если пользуетесь постоянно, большая упаковка удобнее и выгоднее 😊",
     "С большой упаковкой «закончилось» случается гораздо реже 🙂",
     "Маленькая упаковка удобна, чтобы попробовать новый рецепт ✨",
     "Маленький объём — ещё и хороший вариант для подарка 🎁",
     "Этот продукт есть и в другом объёме — легко выбрать под себя 😊"],
)

# No matching pair (or no history at all): one warm general line per product.
GENERAL: dict[str, tuple[str, str]] = {
    "almond_flour": ("Pechenye, keks, tort — keto-pishiriqning ko'pi bodom unidan boshlanadi 🥜",
                     "Печенье, кексы, торты — кето-выпечка чаще всего начинается с миндальной муки 🥜"),
    "erythritol": ("Choy, qahva va pishiriqqa — shakar o'rniga eng oson variant 🍬",
                   "Для чая, кофе и выпечки — самая простая замена сахару 🍬"),
    "stevia": ("Juda oz ishlatiladi, shuning uchun uzoqqa yetadi 🌿",
               "Нужно совсем немного, поэтому хватает надолго 🌿"),
    "allulose": ("Pishiriq u bilan xuddi shakardagidek qizarib pishadi 🍯",
                 "С ней выпечка румянится, как с обычным сахаром 🍯"),
    "devzira": ("Bo'yalmagan, tabiiy Devzira — haqiqiy palov uchun 🍚",
                "Неокрашенная натуральная девзира — для настоящего плова 🍚"),
    "ghee": ("Qovurishga ham, pishiriqqa ham — kuchli olovda ham kuymaydi 🧈",
             "И для жарки, и для выпечки — не горит даже на сильном огне 🧈"),
    "olive_oil": ("Salatga ham, issiq ovqatga ham — oshxonada doim kerak bo'ladi 🫒",
                  "И для салатов, и для горячего — на кухне всегда пригодится 🫒"),
    "psyllium": ("Keto-nonni yumshoq va ko'pchigan qiladi 🍞",
                 "Делает кето-хлеб мягким и пышным 🍞"),
    "coconut_flour": ("O'zi biroz shirin — kokos pishiriqlari uchun ayni muddao 🥥",
                      "Сама слегка сладкая — то, что нужно для кокосовой выпечки 🥥"),
    "coconut_cream": ("Qahvaga, kremga, desertga — hammasini mayin qiladi 🥛",
                      "В кофе, крем, десерт — всё делает нежнее 🥛"),
    "chocolate": ("Shakarsiz shokolad — shirinlikdan voz kechish shart emas 🍫",
                  "Шоколад без сахара — от сладкого отказываться не обязательно 🍫"),
    "chia": ("Kechqurun 2 daqiqa — ertalab tayyor puding 🌙",
             "2 минуты вечером — и утром готов пудинг 🌙"),
    "flax": ("Keto-nonga yong'oqqa o'xshash ta'm beradi 🌾",
             "Даёт кето-хлебу приятный ореховый вкус 🌾"),
    "buckwheat": ("Yengil va to'yimli — nonushtaga ham, kechki ovqatga ham 🥣",
                  "Лёгкая и сытная — и на завтрак, и на ужин 🥣"),
    "peanut_paste": ("Bir qoshiq — va oddiy nonushta mazaliroq bo'ladi 🥜",
                     "Одна ложка — и обычный завтрак становится вкуснее 🥜"),
    "pistachio_paste": ("Bir qoshiq — va oddiy nonushta mazaliroq bo'ladi 🥜",
                        "Одна ложка — и обычный завтрак становится вкуснее 🥜"),
}

# A gentle "it may be used up" note, added when the earlier purchase is old
# enough to plausibly be gone. Never an order, never "you bought".
RESTOCK_AFTER_DAYS = 21
_RESTOCK = ("Uydagi {name} tugab qolgan bo'lsa, u ham shu yerda 😊",)
# Short everyday names for that note — "Tabiiy GHEE 1000ml" reads like a receipt.
LABELS: dict[str, tuple[str, str]] = {
    "almond_flour": ("bodom uni", "миндальная мука"), "erythritol": ("eritritol", "эритритол"),
    "stevia": ("steviya", "стевия"), "allulose": ("alluloza", "аллюлоза"),
    "devzira": ("Devzira", "девзира"), "basmati": ("basmati", "басмати"),
    "black_rice": ("qora guruch", "чёрный рис"), "ghee": ("GHEE", "гхи"),
    "olive_oil": ("zaytun yog'i", "оливковое масло"), "vinegar": ("olma sirkasi", "яблочный уксус"),
    "salt": ("Himalay tuzi", "гималайская соль"), "psyllium": ("psillium", "псиллиум"),
    "xanthan": ("ksantan", "ксантан"), "coconut_flour": ("kokos uni", "кокосовая мука"),
    "coconut_cream": ("kokos slivkasi", "кокосовые сливки"), "chocolate": ("shokolad", "шоколад"),
    "cacao_nibs": ("kakao nibs", "какао-нибс"), "chia": ("chia", "чиа"),
    "flax": ("zig'ir", "лён"), "sesame": ("kunjut", "кунжут"), "buckwheat": ("grechka", "гречка"),
    "peanut_paste": ("yeryong'oq pastasi", "арахисовая паста"),
    "pistachio_paste": ("xandonpista pastasi", "фисташковая паста"),
    "sourdough": ("zakvaska", "закваска"), "bran_flour": ("kepakli un", "отрубная мука"),
    "cinnamon": ("koritsa", "корица"),
}


# ─────────────────────────────── rendering ──────────────────────────────────

_KEEP = re.compile(r"\bGHEE\b")


def _cyr(text: str) -> str:
    """Uzbek Latin → Cyrillic, leaving brand words alone ("GHEE" must not
    become "ГҲЕЕ")."""
    from translit import lat_to_cyr
    kept: list[str] = []

    def stash(m):
        kept.append(m.group(0))
        return f"\x00{len(kept) - 1}\x00"

    out = lat_to_cyr(_KEEP.sub(stash, text))
    return re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], out)


def _lang_pick(uz: str, ru: str, lang: str) -> str:
    if lang == "ru":
        return ru
    return _cyr(uz) if lang == "uz_cyr" else uz


def is_purchase_line(item: dict) -> bool:
    """A line the buyer chose and paid for — not a gift/bonus."""
    return bool(item.get("product_id")) and not (item.get("is_bonus") or item.get("is_gift"))


def history_from_orders(orders: list[dict]) -> list[dict]:
    """[{product_id, name, key, at}] newest first, one entry per product."""
    seen: set[int] = set()
    out: list[dict] = []
    for o in sorted(orders, key=lambda o: o.get("created_at") or datetime.min, reverse=True):
        if o.get("status") == "cancelled":
            continue
        raw = o.get("items")
        try:
            items = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except (TypeError, ValueError):
            items = []
        for it in items:
            if not isinstance(it, dict) or not is_purchase_line(it):
                continue
            pid = int(it["product_id"])
            if pid in seen:
                continue
            seen.add(pid)
            out.append({"product_id": pid, "name": it.get("name") or "",
                        "key": tip_key(it.get("name") or ""), "at": o.get("created_at")})
    return out


def choose(history: list[dict], product: dict, lang: str, turn: int = 0,
           now: datetime | None = None) -> str | None:
    """The advice line for `product`, or None. `turn` rotates the variants so
    the same card reads differently on the next visit."""
    vkey = tip_key(product.get("name") or "")
    if not vkey:
        return None
    ru = lang == "ru"
    for h in history:                       # most recent purchase first
        if h["key"] and h["key"] != vkey and (vkey, h["key"]) in PAIRS:
            uz_list, ru_list = PAIRS[(vkey, h["key"])]
            i = turn % 3
            line = _lang_pick(uz_list[i], ru_list[i], lang)
            # The "may be used up" note rides along every third time only, so
            # the line doesn't end the same way on every visit.
            if (turn % 3 == 0 and h.get("at") and now
                    and (now - h["at"]).days >= RESTOCK_AFTER_DAYS and h["key"] in LABELS):
                label = LABELS[h["key"]][1 if ru else 0]
                if ru:
                    note = f"Запас ({label}) закончился? У нас всё есть 😊"
                else:
                    note = _RESTOCK[0].format(name=label)
                line += " " + (_cyr(note) if lang == "uz_cyr" else note)
            return line
    pid = product.get("id")
    if any(h["key"] == vkey and h["product_id"] != pid for h in history):
        uz_list, ru_list = SIZE
        i = turn % len(uz_list)
        return _lang_pick(uz_list[i], ru_list[i], lang)
    general = GENERAL.get(vkey)
    if general:
        return _lang_pick(general[0], general[1], lang)
    return None


# ─────────────────────────────── per-buyer state ────────────────────────────

_HISTORY_TTL = 300
_history_cache: dict[int, tuple[float, list[dict]]] = {}
_turns: dict[tuple[int, int], int] = {}


async def buyer_history(user_id: int) -> list[dict]:
    hit = _history_cache.get(user_id)
    if hit and time.monotonic() - hit[0] < _HISTORY_TTL:
        return hit[1]
    import database
    async with database.pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT items, created_at, status FROM orders
                WHERE user_id = $1 AND status <> 'cancelled'
                ORDER BY created_at DESC LIMIT 40""", user_id)
    hist = history_from_orders([dict(r) for r in rows])
    if len(_history_cache) > 20000:
        _history_cache.clear()
    _history_cache[user_id] = (time.monotonic(), hist)
    return hist


def next_turn(user_id: int, product_id: int, advance: bool) -> int:
    """Rotation index for this buyer and card; advances on a fresh open only,
    so the +/- buttons repaint the same line instead of a new one."""
    key = (user_id, product_id)
    if len(_turns) > 50000:
        _turns.clear()
    turn = _turns.get(key, -1)
    if advance or turn < 0:
        turn += 1
        _turns[key] = turn
    return turn


async def tip_for(user_id: int, product: dict, lang: str, *, advance: bool = True) -> str | None:
    """Card entry point. Never raises — a card without advice is fine."""
    try:
        hist = await buyer_history(user_id)
        from datetime import datetime as _dt
        return choose(hist, product, lang, next_turn(user_id, product["id"], advance),
                      now=_dt.utcnow())
    except Exception:
        import logging
        logging.getLogger(__name__).warning("product tip failed for %s/%s", user_id,
                                            product.get("id"), exc_info=True)
        return None
