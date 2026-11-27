"""
Admin kayfiyati (2026-09-30) — owner's ask: every message the bot sends to
admins should carry an unusual, mood-lifting line that FITS the message
("adminlarga keladigan har qanday xabarda ... xabarga bog'liq bo'lsin").

How it reaches EVERY admin notification without touching 30 call sites:

* AdminCheerMiddleware sits on the bot's HTTP session (bot.session.middleware)
  and sees every SendMessage / SendPhoto / SendDocument / SendVideo. When the
  target chat is an admin it appends one line chosen for that message:
  classify() names the event (new order, cancel, delivered, cheque, stock,
  new user, lead, ...) and facts() pulls the order number, the amount and the
  product name out of the text, so the line can say "#512 yo'lga chiqdi"
  instead of a generic joke. A template is only used when its facts exist.
* It does NOT touch replies to the admin's own taps and commands — an admin
  paging through the panel doesn't want a joke under every menu. The update
  being handled is tracked in a contextvar (CurrentUserMiddleware); a message
  to the same person who triggered the update is a reply, anything else
  (background jobs, a buyer's order fanning out to admins, admin A's action
  notifying admin B) is a notification.
* quiet() switches it off for a block whose text is already written in this
  tone (stock_alerts) so nothing gets two jokes.
* ADMIN_CHEER=0 in the environment turns it all off.
"""
import contextlib
import contextvars
import os
import random
import re
import time

from aiogram import BaseMiddleware
from aiogram.client.session.middlewares.base import BaseRequestMiddleware

ENABLED = os.getenv("ADMIN_CHEER", "1") != "0"

_current_user: contextvars.ContextVar = contextvars.ContextVar("admin_mood_user", default=None)
_quiet: contextvars.ContextVar = contextvars.ContextVar("admin_mood_quiet", default=False)

TEXT_LIMIT = 4096
CAPTION_LIMIT = 1024

# Plain text only — no < > & in the templates, so a line is safe under HTML
# parse mode and under none. Facts pulled from the message are HTML-escaped
# before they go in. Placeholders: {order} {amount} {product}.
PHRASES = {
    "new_order": {
        "uz": [
            "🎉 #{order} — kassa jiringladi! Yana bir mijoz keto-hayotni tanladi.",
            "💰 {amount} so'm — bu shunchaki summa emas, kimningdir sog'lom haftasi!",
            "🛍 #{order} uchun quti tayyorlaymiz — ichiga bir hovuch mehr ham solamiz 💚",
            "🚀 Buyurtmalar oqimi to'xtamayapti — #{order} navbatda turibdi!",
            "☕️ Choy damlab qo'ying — bugun ish qizg'in bo'ladiganga o'xshaydi!",
        ],
        "ru": [
            "🎉 #{order} — касса звенит! Ещё один клиент выбрал кето-жизнь.",
            "💰 {amount} сум — это не просто сумма, а чья-то здоровая неделя!",
            "🛍 Собираем коробку для #{order} — и положим туда щепотку заботы 💚",
            "🚀 Заказы идут потоком — #{order} уже в очереди!",
            "☕️ Заварите чай — похоже, сегодня будет жарко!",
        ],
    },
    "order": {
        "uz": [
            "✅ #{order} bo'yicha ish qaynayapti — mijoz allaqachon kutib o'tiribdi!",
            "💰 {amount} so'm — har bir so'm ortida mamnun mijoz turibdi!",
            "🧺 Buyurtmalar bilan ishlash — eng yoqimli tashvish!",
        ],
        "ru": [
            "✅ По #{order} работа кипит — клиент уже ждёт!",
            "💰 {amount} сум — за каждым сумом стоит довольный клиент!",
            "🧺 Возиться с заказами — самая приятная забота!",
        ],
    },
    "cancel": {
        "uz": [
            "🌤 #{order} bekor bo'ldi, lekin kayfiyat joyida — keyingisi albatta keladi!",
            "🍀 Bekor bo'lgan buyurtma keyingisiga joy bo'shatdi.",
            "💪 Kayfiyatni tushirmang — eng yaxshi buyurtmalar hali oldinda!",
        ],
        "ru": [
            "🌤 #{order} отменён, но настроение на месте — следующий обязательно будет!",
            "🍀 Отменённый заказ освободил место для следующего.",
            "💪 Не унываем — лучшие заказы ещё впереди!",
        ],
    },
    "delivered": {
        "uz": [
            "🏁 #{order} marraga yetdi — kuryerimizga qarsaklar! 👏",
            "📦 Yetkazildi! Bugun bir oila keto-dasturxon atrofida jam bo'ladi.",
            "🎯 Yana bir buyurtma nishonga tegdi — mijoz xursand, biz ham!",
        ],
        "ru": [
            "🏁 #{order} на финише — аплодисменты нашему курьеру! 👏",
            "📦 Доставлено! Сегодня одна семья соберётся за кето-столом.",
            "🎯 Ещё один заказ точно в цель — клиент доволен, и мы тоже!",
        ],
    },
    "shipped": {
        "uz": [
            "🚚 #{order} yo'lga chiqdi — kuryerimiz bugun keto-supermen! 🦸",
            "🛣 Yo'l ochiq, kayfiyat a'lo — #{order} mijoz eshigi tomon yo'lda!",
        ],
        "ru": [
            "🚚 #{order} в пути — наш курьер сегодня кето-супергерой! 🦸",
            "🛣 Дорога свободна, настроение отличное — #{order} едет к клиенту!",
        ],
    },
    "cheque": {
        "uz": [
            "💸 {amount} so'mlik chek keldi — pul ham, kayfiyat ham joyida!",
            "🧾 #{order} cheki keldi — mijoz ishonchining eng chiroyli ko'rinishi.",
            "🤑 Hisobimizda yana biroz quyosh chiqdi.",
        ],
        "ru": [
            "💸 Пришёл чек на {amount} сум — и деньги, и настроение на месте!",
            "🧾 Чек по #{order} — самое красивое проявление доверия клиента.",
            "🤑 На нашем счёте снова выглянуло солнце.",
        ],
    },
    "stock": {
        "uz": [
            "🐿 Olmaxon ham qishga g'amlaydi — «{product}» uchun ham g'amlab qo'yamiz!",
            "🔥 «{product}» shunchalik yoqibdiki, javonda to'xtab turolmayapti!",
            "📦 Ombor gapiryapti — uni tinglash vaqti keldi!",
            "🚚 Tez sotilayotgan mahsulot — yaxshi mahsulot. To'ldirib qo'yamiz!",
        ],
        "ru": [
            "🐿 Даже белка делает запасы — запасёмся и «{product}»!",
            "🔥 «{product}» так нравится покупателям, что на полке не задерживается!",
            "📦 Склад говорит — самое время его послушать!",
            "🚚 Быстро продаётся — значит, хороший товар. Пополним!",
        ],
    },
    "user": {
        "uz": [
            "👋 Oilamiz kattalashyapti!",
            "🌱 Yana bir odam keto-sayohatini boshladi.",
            "🎈 Yangi mehmon — yangi imkoniyat!",
            # Owner, 2026-10-01: "yanada quvnoq va kulguli" — 35 more, so the
            # same line rarely shows up twice in one day.
            "🥑 Yangi do'stimiz keldi — avokado ham xursand bo'lib ketdi!",
            "🎉 Diqqat, diqqat! Keto-klubimizga yangi a'zo kirib keldi!",
            "🚪 Taq-taq! Kim u? Yangi mijoz — choy qo'yamiz!",
            "🧈 Yangi a'zo — sariyog'dek yoqimli yangilik!",
            "🥚 Yana bir odam shakarga «xayr», bizga «salom» dedi!",
            "🕺 Yangi foydalanuvchi! Ofisda kichik raqs tushsak bo'ladi.",
            "🌰 Yong'oq ham sezgan edi — bugun yangi do'st keladi!",
            "🍫 Shakarsiz shokoladdek shirin xabar: yangi a'zo!",
            "📈 Grafik yuqoriga qarab ketyapti — yana bir odam qo'shildi!",
            "🏃 Yangi odam keldi — demak, kimdir bugun shakardan qochishni boshladi!",
            "🧲 Keto-magnitimiz yana bir odamni tortib oldi!",
            "🎁 Hali buyurtma bermagan bo'lsa ham, yangi mehmonning o'zi sovg'a!",
            "🦸 Yangi qahramon keto-jamoamizga qo'shildi!",
            "🌟 Osmonda yangi yulduz yo'q, lekin botimizda yangi a'zo bor!",
            "🍳 Yangi do'st keldi — tuxumni qovurib, kutib olamiz!",
            "🥗 Salat ham, biz ham xursandmiz — yangi a'zo!",
            "🐝 Asalarilardek g'ayratli jamoamizga yana bir odam qo'shildi!",
            "🎯 Reklamami, do'st maslahatimi, taqdirmi — har holda, yangi a'zo keldi!",
            "🧘 Yangi foydalanuvchi: tinchlik, sog'lik va keto bilan xush kelibsiz!",
            "🚀 Uchishga tayyor! Yana bir yo'lovchi keto-raketamizga chiqdi.",
            "🍵 Choynakka yana bir piyola qo'shamiz — yangi mehmon!",
            "🤗 Quchoqlarimiz ochiq — yangi a'zo kirib keldi!",
            "🥳 Bayram! Shakarsiz tort bilan nishonlaymiz — yangi foydalanuvchi!",
            "🐢 Sekin-sekin, lekin ishonch bilan — oilamiz yana bittaga ko'paydi!",
            "🧮 Hisobchimiz quvonch bilan +1 yozib qo'ydi!",
            "🌻 Kungaboqar quyoshga, odamlar Ketoshopga qarab keladi!",
            "📣 Ovozimiz tarqalyapti — yana bir odam yetib keldi!",
            "🛎 Qo'ng'iroq chalindi — yangi mehmon ostonada!",
            "🍋 Hayot limon bersa, biz keto-retsept beramiz. Xush kelibsiz, yangi do'st!",
            "🧀 Pishloqdek yetilgan xabar: oilamiz kattalashdi!",
            "🎶 Bugungi qo'shig'imiz: «Yana bir do'st, yana bir quvonch»!",
            "🐣 Yangi a'zo keto-dunyoda birinchi qadamini qo'ydi!",
            "🏆 Yangi foydalanuvchi — kichik g'alaba, katta quvonch!",
            "🙌 Kuting-kuting... ha, yana bir odam qo'shildi!",
            "💚 Har bir yangi a'zo — kimningdir sog'lom hayot sari birinchi qadami.",
        ],
        "ru": [
            "👋 Наша семья растёт!",
            "🌱 Ещё один человек начал кето-путешествие.",
            "🎈 Новый гость — новая возможность!",
            "🥑 К нам пришёл новый друг — даже авокадо обрадовалось!",
            "🎉 Внимание, внимание! В наш кето-клуб вступил новый участник!",
            "🚪 Тук-тук! Кто там? Новый клиент — ставим чай!",
            "🧈 Новый участник — новость приятная, как сливочное масло!",
            "🥚 Ещё один человек сказал сахару «пока», а нам — «привет»!",
            "🕺 Новый пользователь! Можно станцевать небольшой танец в офисе.",
            "🌰 Даже орех чувствовал — сегодня придёт новый друг!",
            "🍫 Сладкая, как шоколад без сахара, новость: новый участник!",
            "📈 График ползёт вверх — к нам присоединился ещё один человек!",
            "🏃 Пришёл новый человек — значит, кто-то сегодня начал убегать от сахара!",
            "🧲 Наш кето-магнит притянул ещё одного человека!",
            "🎁 Даже без заказа новый гость — уже подарок!",
            "🦸 В нашу кето-команду вступил новый герой!",
            "🌟 Новой звезды на небе нет, зато в боте новый участник!",
            "🍳 Пришёл новый друг — жарим яичницу и встречаем!",
            "🥗 И салат, и мы рады — новый участник!",
            "🐝 К нашей трудолюбивой, как пчёлы, команде присоединился ещё один!",
            "🎯 Реклама, совет друга или судьба — в любом случае, у нас новенький!",
            "🧘 Новый пользователь: добро пожаловать в мир покоя, здоровья и кето!",
            "🚀 Готовы к взлёту! Ещё один пассажир сел в нашу кето-ракету.",
            "🍵 Добавляем к чайнику ещё одну пиалу — новый гость!",
            "🤗 Объятия открыты — к нам пришёл новый участник!",
            "🥳 Праздник! Отмечаем тортом без сахара — новый пользователь!",
            "🐢 Медленно, но уверенно — нас стало на одного больше!",
            "🧮 Наш бухгалтер с радостью записал +1!",
            "🌻 Подсолнух тянется к солнцу, а люди — к Ketoshop!",
            "📣 О нас говорят — пришёл ещё один человек!",
            "🛎 Звонок прозвенел — новый гость на пороге!",
            "🍋 Если жизнь даёт лимон, мы даём кето-рецепт. Добро пожаловать, новый друг!",
            "🧀 Новость созрела, как сыр: наша семья выросла!",
            "🎶 Песня дня: «Ещё один друг — ещё одна радость»!",
            "🐣 Новый участник сделал первый шаг в кето-мире!",
            "🏆 Новый пользователь — маленькая победа, большая радость!",
            "🙌 Ждём-ждём... да, к нам присоединился ещё один!",
            "💚 Каждый новый участник — чей-то первый шаг к здоровой жизни.",
        ],
    },
    "lead": {
        "uz": [
            "📣 Reklama ishlayapti — yangi lid eshigimizni taqillatyapti!",
            "🎣 Qarmoqqa yana biri ilindi — endi uni iliq so'z bilan kutib olamiz!",
        ],
        "ru": [
            "📣 Реклама работает — новый лид стучится в дверь!",
            "🎣 Клюнул ещё один — встретим его тёплым словом!",
        ],
    },
    "review": {
        "uz": [
            "⭐️ Mijoz fikri — eng qimmatli bepul maslahat.",
            "📝 Har bir sharh bizni bir pog'ona yuqoriga ko'taradi.",
        ],
        "ru": [
            "⭐️ Мнение клиента — самый ценный бесплатный совет.",
            "📝 Каждый отзыв поднимает нас на ступеньку выше.",
        ],
    },
    "backup": {
        "uz": [
            "💾 Zaxira nusxa tayyor — ma'lumotlarimiz seyfdagidek xotirjam uxlayapti.",
            "🛡 Hamma narsa saqlab qo'yildi — tinchgina ishlashda davom etamiz!",
        ],
        "ru": [
            "💾 Резервная копия готова — данные спят спокойно, как в сейфе.",
            "🛡 Всё сохранено — работаем дальше спокойно!",
        ],
    },
    "broadcast": {
        "uz": [
            "📢 So'zimiz yuzlab ekranlarga yetib bordi!",
            "🕊 Xabar uchib ketdi — endi javoblarni kutamiz!",
        ],
        "ru": [
            "📢 Наше слово долетело до сотен экранов!",
            "🕊 Сообщение улетело — ждём откликов!",
        ],
    },
    "support": {
        "uz": [
            "💬 Mijoz sizni kutyapti — tabassum bilan javob beramiz!",
            "🤝 Tez javob — sodiq mijozning siri.",
        ],
        "ru": [
            "💬 Клиент ждёт — ответим с улыбкой!",
            "🤝 Быстрый ответ — секрет преданного клиента.",
        ],
    },
    "report": {
        "uz": [
            "📈 {amount} so'm — mehnatingiz raqamlarda ko'rinib turibdi!",
            "📊 Raqamlar ham ba'zan she'r yozadi.",
            "🏆 Bugungi mehnatingiz uchun katta rahmat!",
        ],
        "ru": [
            "📈 {amount} сум — ваш труд виден в цифрах!",
            "📊 Цифры тоже иногда пишут стихи.",
            "🏆 Огромное спасибо за сегодняшнюю работу!",
        ],
    },
    "error": {
        "uz": [
            "🛠 Xato — yechimini kutayotgan jumboq, xolos.",
            "🧘 Chuqur nafas oling — hammasini tuzatamiz.",
        ],
        "ru": [
            "🛠 Ошибка — это просто головоломка, ждущая решения.",
            "🧘 Глубокий вдох — всё исправим.",
        ],
    },
    "generic": {
        "uz": [
            "✨ Ajoyib kun tilaymiz!",
            "😊 Siz bilan ishlash — maza!",
            "🌟 Ketoshop jamoasi eng zo'ri!",
            "🍵 Bir piyola choy va oldinga!",
        ],
        "ru": [
            "✨ Желаем отличного дня!",
            "😊 Работать с вами — одно удовольствие!",
            "🌟 Команда Ketoshop — лучшая!",
            "🍵 Чашечку чая — и вперёд!",
        ],
    },
}

# First match wins, so the more specific kinds go first ("buyurtma bekor
# qilindi" is a cancel, not an order). A new-order card also has a "To'lov"
# line, which is why it is matched by its header before anything else.
# Matched against the lowercased text AND its Latin transliteration, so
# Cyrillic-Uzbek admins are covered too.
_RULES = [
    ("new_order", ("yangi buyurtma", "новый заказ")),
    ("error",     ("xato", "ошибк", "failed", "muvaffaqiyatsiz", "exception")),
    ("cancel",    ("bekor", "отмен")),
    ("delivered", ("yetkazildi", "доставлен")),
    ("shipped",   ("yo'lga chiqdi", "yo'lda", "отправлен", "в пути")),
    ("stock",     ("tugadi", "kam qoldi", "ombor", "закончил", "заканчива", "склад")),
    ("cheque",    ("chek", "чек")),
    ("backup",    ("backup", "zaxira nusxa", "резервн")),
    ("lead",      ("yangi lid", "lead", "reklama", "реклам", "лид")),
    ("user",      ("yangi foydalanuvchi", "qo'shildi", "taklif qil", "новый пользовател", "присоедин")),
    ("review",    ("sharh", "baho", "отзыв", "оценк", "nps")),
    ("report",    ("hisobot", "statistika", "отчёт", "отчет", "статистик", "natija")),
    ("order",     ("buyurtma", "заказ")),
    ("broadcast", ("tarqatma", "рассылк", "yuborildi")),
    ("support",   ("xabar", "savol", "сообщени", "вопрос")),
]

_TAG = re.compile(r"<[^>]+>")
_ORDER = re.compile(r"#\s?(\d{1,7})\b")
_MONEY = r"(\d{1,3}(?:[  ,.]\d{3})+|\d{4,})\s*(?:so'm|so‘m|сум|сўм)"
_TOTAL = re.compile(r"(?:jami|итого|жами)[^\d\n]{0,20}" + _MONEY, re.I)
_ANY_MONEY = re.compile(_MONEY, re.I)
_PRODUCT = re.compile(r"📦\s*([^\n]{2,60})")


def _search_text(text: str) -> str:
    low = (text or "").lower()
    try:
        from translit import cyr_to_lat
        low += "\n" + cyr_to_lat(text or "").lower()
    except Exception:
        pass
    return low


def classify(text: str) -> str:
    low = _search_text(_TAG.sub("", text or ""))
    for kind, needles in _RULES:
        if any(n in low for n in needles):
            return kind
    return "generic"


def facts(text: str) -> dict:
    """Order number, amount (the "Jami" line if there is one, else the last
    sum mentioned) and product name ("📦 ..." line), when present."""
    import html
    plain = html.unescape(_TAG.sub("", text or ""))
    out = {}
    m = _ORDER.search(plain)
    if m:
        out["order"] = m.group(1)
    m = _TOTAL.search(plain)
    amounts = [m.group(1)] if m else [a.group(1) for a in _ANY_MONEY.finditer(plain)]
    if amounts:
        out["amount"] = re.sub(r"[ ,.]", " ", amounts[-1])
    m = _PRODUCT.search(plain)
    if m:
        name = m.group(1).strip().strip("«»\"'").strip()
        # "📦 Yetkazildi: 12.09" style lines are timestamps, not products.
        if name and not re.search(r"\d{1,2}[.:]\d{2}", name):
            out["product"] = html.escape(name)
    return out


# Umumiy o'zbekona hazil qatorlari (egasi, 2026-11-27: "yanada kulgili va kayfiyatni ko'taruvchi
# iboralar qo'sh, yana 100 xil, o'zbeklarga va jargon va faqat o'zbeklar tushunadigan gap va
# hazillar ham bo'lsin"). Har qanday xabar turiga (xatolardan tashqari) o'zbekcha xabarlarda
# shu turning o'z qatorlari bilan aralash tushadi.
FUN_UZ = [
    "😎 Ishlar besh — beshdan ham zo'r, olti!",
    '🫖 Choy sovib qolmasin, ish esa qizib turaversin!',
    "🍚 Kechqurun osh bo'lsa, bugun ishlar ham joyida bo'ladi!",
    "💪 Gap yo'q — siz bilan bu do'kon tog'ni ham ko'taradi!",
    "😂 Qo'shni xola so'radi: «Ketoshop yana kengaydimi?» — Ha, xola, kengayapmiz!",
    '🚐 Damasdek ixcham, lekin Kobaltdek ishonchli jamoa!',
    '🥇 Bugun ham chempionlar jamoasi navbatchilikda!',
    "🧿 Ko'z tegmasin, ishlarimiz yurishib ketdi!",
    "🎶 Ish qo'shiq bilan — kayfiyat esa to'ydagidek!",
    '🍞 Non issiq, ish shirin — yana nima kerak?',
    '😄 Boshliq kulsa — demak, bugun hammasi joyida!',
    "🫡 Qoyil qildingiz — shapka olib ta'zim!",
    "🍉 Yozda tarvuz, qishda kepak — bizda har fasl zo'r!",
    "🚀 Ketvordik! Endi to'xtatib bo'lmaydi!",
    '🍯 Bu jamoa asaldek shirin, lekin qandsiz — keto-shirin!',
    '😅 Telefon jiringlayapti — yangi baraka kelyapti!',
    "🧠 Bosh joyida, qo'l ishda, ko'ngil xotirjam!",
    '🌞 Erta turgan ishni bitirar, Ketoshop jamoasi esa ikki barobar!',
    "🤝 Bitta qo'l bilan qars chiqmaydi — shuning uchun biz jamoamiz!",
    '🏃 Chopqir otdek ishlaymiz, lekin dam olishni ham unutmang!',
    "🥟 Somsadek qizg'in kun — ichi to'la baraka!",
    '😂 Kalkulyator ham hayron: buncha buyurtma qayerdan?',
    '🧃 Bir qultum suv iching — ish yana kutib turadi!',
    "🎯 Nishonga aniq tegdi — xuddi bazmda qo'ylangan osh kabi!",
    "🪴 Sabr qilsang, g'o'radan holva bitar — biz esa keto-holva qilamiz!",
    "📦 Qutilar to'lyapti, ko'ngillar ham!",
    "😁 Kim aytdi «ish zerikarli» deb? Bizda har kuni to'y!",
    '🦁 Sherlar ishlayapti — mushuklar dam olsin!',
    "🍵 Ko'k choy, issiq non, yaxshi xabar — o'zbekona baxt!",
    '🎉 Bugungi ish — ertangi maqtov!',
    "😎 Shoshilmang, lekin to'xtamang — bizning shiorimiz!",
    "🌙 Kechasi ham uyg'oq — Ketoshop hech qachon uxlamaydi!",
    "🧂 Himalay tuzidek — ozgina, lekin ta'm beradi!",
    "😂 Navbat Chorsu bozoridagidek uzun bo'lsin — buyurtmaga!",
    "🚕 Kuryer yo'lda, xursandchilik ham!",
    '🏆 Bu hafta MVP — siz!',
    '🥳 Har bir buyurtma — kichik bayram, katta baraka!',
    "😌 Ko'ngil tinch bo'lsa, ish ham o'z-o'zidan yuradi.",
    '🔥 Qozon qaynayapti — ishlar ham!',
    "🍏 Olma pishsa o'zi tushadi, mijoz esa o'zi qaytib keladi!",
    "😄 Mehmon otangdan ulug' — mijoz esa undan ham!",
    "🛠 Usta bo'lsang, ish o'zi topiladi — bizda esa ish ko'p!",
    "💚 Sog'lom ovqat — sog'lom el, sog'lom el — gullagan yurt!",
    "🧳 Qopni to'ldiramiz, ko'ngilni ham!",
    '😂 Hatto tandir ham hayron: bizning nonlar glyutensiz!',
    "🌟 Yulduzlar bizni ko'rib, o'zlarini sozlayapti!",
    "🤗 Bitta tabassum — o'nta buyurtmaga teng!",
    "🎈 Kayfiyat — havo shari: siz uni ko'tarib turibsiz!",
    "😜 «Keyinroq» degan so'z bizda yo'q — «hozir» bor!",
    '🍬 Shakarsiz, lekin shirin — bizning ishimiz kabi!',
    "🏡 Uyga ham baraka, do'konga ham!",
    '😂 Qayin ona ham maqtaydigan xizmat — mana bu daraja!',
    "🧮 Hisob-kitob aniq, ko'ngil to'q!",
    "🥗 Salatdek yangi, oshdek to'yimli kun!",
    '🫶 Mijoz xursand — biz ham xursand, hamma xursand!',
    '🚦 Yashil chiroq yondi — oldinga!',
    "😎 Bugun omad bizning tomonda — buyurtmalarni ko'ring!",
    "🐎 Ot aylanib qozig'ini topar — mijoz ham Ketoshopni!",
    "🍲 Mastava issiq, ish tez, ko'ngil to'q!",
    "😂 Ishimiz shunchalik ko'pki, soat ham charchab qoldi!",
    "📈 Grafik yuqoriga — xuddi kelinning sepidek to'lib boryapti!",
    '🧘 Chuqur nafas — keyin yana zarb bilan!',
    '🌻 Kungaboqar quyoshga, biz esa mijozga qaraymiz!',
    "😁 «Zo'r-ku!» deydigan kun bugun!",
    '🧁 Keto-tort kabi: shakarsiz, lekin bayramona!',
    "🥜 Yong'oqdek mustahkam jamoa!",
    '🤣 Kuryerimiz shunday tez-ki, GPS ortda qolyapti!',
    "🏔 Tog'ni ham ko'chiramiz — faqat avval choy ichib olamiz!",
    "🎁 Har kuni sovg'a — mijozga ham, jamoaga ham!",
    '😇 Duo olgan ish yurishadi — mijozlarimiz duo qilyapti!',
    "🚴 Sekin yursang ham, to'xtamasang yetasan!",
    "😂 Qo'shni do'kon hayron: «Bular nima sotyapti o'zi?»",
    "🍳 Ertalabki tuxumdek — kun ham to'liq, ham foydali!",
    "💼 Biznes — bu biznes, lekin kayfiyat birinchi o'rinda!",
    "🌈 Yomg'irdan keyin kamalak — qiyin kundan keyin zo'r savdo!",
    "😄 Bir kun ko'rmasak, mijozlar sog'inib qoladi!",
    "🪙 Tiyin-tiyin yig'ilib, so'm bo'ladi — so'm-so'm yig'ilib, Ketoshop!",
    '🎬 Bu kino emas — bu Ketoshopning real hayoti!',
    "😂 Ombordagi qoplar ham bizni ko'rib tik turibdi!",
    '🍇 Uzumdek shirin, keto kabi foydali kun!',
    '🫵 Ha, aynan siz — bugungi qahramon!',
    '😎 Ish qilsang — qoyilmaqom qil, deydi ustoz!',
    "🧺 Savat to'la, ko'ngil to'la!",
    "🤭 Tushlikka keto-somsa bo'lsa, ish yanada yurishadi!",
    '🏅 Har bir yetkazilgan quti — kichik medal!',
    "🕊 Tinchlik, xotirjamlik va ko'p buyurtma!",
    "😂 Bugun shunchalik ish ko'pki, hatto mushuk ham yordam bermoqchi!",
    "🌄 Har tong — yangi imkoniyat, har buyurtma — yangi do'st!",
    "🥤 Ayronday sovuqqon, oshdek qizg'in — ideal jamoa!",
    "😃 Ko'ngil xush bo'lsa, ko'cha ham gulzor!",
    "🛒 Savat aravachasi g'ildiragi aylanyapti — biz ham!",
    "😆 Hazil-hazil bilan bugungi rejani bajarib qo'ydik!",
    '🌰 Bodom unidan ham mayin, tosh devordan ham mustahkam jamoa!',
    "🎺 Karnay-surnay chalinsin — yana bir zo'r kun!",
    '😌 Ishdan keyin oila, choy va xotirjamlik — siz bunga loyiqsiz!',
    "🔑 Muvaffaqiyat kaliti — sizning cho'ntagingizda!",
    "😂 Bizning tezlikni ko'rib, Yandex ham o'ylanib qoldi!",
    '🫓 Patir non kabi — qatlam-qatlam baraka!',
    "🌳 Ekkaning ko'karadi — bugungi mehnat ertaga meva beradi!",
    "🥰 Siz bo'lmasangiz, bu do'kon shunchaki do'kon bo'lardi — siz bilan oila!",
]
# Jahon kompaniyalari misolida kulgili va ruhlantiruvchi qatorlar (egasi, 2026-11-27: "yana 100 xil
# ... dunyo miqyosida katta kompaniyalardan misol keltirib, endi o'zbekona bo'lmasin"; keyin:
# "hammasi ham kompaniyalar haqida emas ... o'chirma va ustiga qo'sh 50 tani"). Faqat keng ma'lum
# faktlar, to'qima iqtiboslar yo'q.
FUN_WORLD = [
    '📦 Amazon garajda kitob sotishdan boshlagan — bizda esa allaqachon ombor bor, demak biz oldindamiz!',
    "🍏 Apple ham garajda tug'ilgan — garaj emas, g'oya muhim!",
    '🔍 Google ham bir garajda ish boshlagan — biz esa hozir dunyoni qidiruvsiz topyapmiz!',
    "☕ Starbucks bitta do'kondan boshlagan — bizning ham har bir buyurtma kelajakdagi filialning g'ishti!",
    "👟 Nike asoschisi poyabzalni mashina yukxonasidan sotgan — bizning kuryer ham shu yo'ldan!",
    "🥣 Airbnb asoschilari kompaniyani saqlab qolish uchun yorma qutilari sotgan — kepak sotish undan ham zo'r!",
    "🎬 Netflix pochta orqali DVD jo'natishdan boshlagan — biz ham qutilar bilan boshladik, keyingisi strimingmi?",
    "🚗 Toyota to'quv dastgohlari yasashdan boshlagan — boshlanish emas, davom ettirish muhim!",
    '🖊 IKEA ruchka sotishdan boshlagan — biz Eritritol 100 grammdan boshladik, qayerga yetamiz?',
    '🐟 Samsung quritilgan baliq va oziq-ovqat savdosidan boshlagan — oziq-ovqat yaxshi boshlanish ekan!',
    "📄 Nokia qog'oz fabrikasidan boshlagan — o'zgarishdan qo'rqmang!",
    "🧱 LEGO yog'och o'yinchoqlardan boshlagan — g'isht-g'isht bilan imperiya qurilar!",
    '🏠 Alibaba bir kvartirada boshlangan — bizda esa ombor ham, jamoa ham bor!',
    '🥤 Coca-Cola birinchi yili kuniga bir necha stakan sotgan — sabr qilganlar yutadi!',
    "🍔 McDonald's bitta oshxonadan boshlangan — bugun esa dunyoni ovqatlantiradi. Navbat bizda!",
    "🚀 SpaceX ning dastlabki uchta raketasi uchmagan — to'rtinchisi uchdi. Taslim bo'lmang!",
    "🛍 Zara bitta kichik do'kondan boshlangan — kichik do'kon katta orzuga xalaqit bermaydi!",
    "💬 WhatsApp asoschisini Facebook ishga olmagan — keyin Facebook WhatsApp'ni milliardlarga sotib oldi. Rad javob — boshlanish!",
    "📸 Instagram aslida boshqa ilova bo'lgan — rasmga e'tibor qaratdi va yutdi. Asosiysiga e'tibor!",
    '🌀 Dyson changyutgich uchun minglab prototip yasagan — bizda esa har kuni yangi tajriba!',
    "🍗 KFC asoschisi retseptini ko'p marta rad etishgan — keyin butun dunyo tovuq yedi!",
    '🐭 Disney ham kichik studiyadan boshlagan — sehr har doim kichikdan boshlanadi!',
    "🏪 Walmart bitta do'kondan boshlangan — bugun eng katta chakana savdogar. Bitta do'kon kam emas!",
    "🎧 Spotify musiqani hammaga ochdi — biz esa sog'lom ovqatni hammaga ochyapmiz!",
    '💻 Microsoft ham kichik ofisdan boshlagan — bugun har uyda. Kim biladi, ertaga keto har uyda!',
    "🟢 NVIDIA o'yinlar uchun chip qilgan — keyin sun'iy intellektga yo'l ochdi. Kutilmagan imkoniyatni ko'ring!",
    "🚙 Tesla birinchi mashinasini juda kam sotgan — bugun dunyo elektromobilga o'tyapti. Boshlanishi kichik bo'lsa ham bo'ladi!",
    "📱 Xiaomi internetda muxlislar bilan gaplashib o'sgan — biz ham mijozlarimizni eshitib o'samiz!",
    "🛒 Costco a'zolarini xursand qilib o'sdi — mamnun mijoz eng yaxshi reklama!",
    "🍕 Domino's yetkazib berishni tezlashtirib g'olib bo'ldi — bizning kuryer ham shu ligada!",
    '🔵 Facebook yotoqxona xonasida boshlangan — bizda esa haqiqiy ofis va haqiqiy mijozlar!',
    "🎮 Nintendo o'yin kartalari bilan boshlagan, 100 yildan ortiq yashadi — uzoq yashash sirlari: o'zgarish!",
    '✈️ Southwest Airlines oddiy va arzon xizmat bilan yutdi — oddiylik ham kuch!',
    "🧸 Build-A-Bear har mijozga o'z ayiqchasini yasatadi — bizda har mijozga o'z savati!",
    "📦 Amazon'ning shiori — mijozdan boshlash. Bizniki ham aynan shunday!",
    "🍎 Steve Jobs aytgan: «Och bo'l, tentak bo'l» — biz esa to'q bo'lamiz, lekin keto bo'lamiz!",
    "🚀 Elon Musk Marsni o'ylaydi — biz esa ertangi yetkazishni. Ikkalasi ham muhim!",
    "🧠 Google xodimlariga o'ylash uchun vaqt beradi — sizga ham bir piyola choy vaqti!",
    '🏎 Ferrari bir paytlar faqat poyga uchun mashina qilgan — fokus har doim yutadi!',
    '🥫 Heinz ketchupni sifat bilan mashhur qilgan — biz ham sifat bilan!',
    "📷 Kodak yangilikni o'tkazib yuborgan — biz esa har kuni yangilanib turamiz!",
    "📼 Blockbuster Netflix'ni sotib olmaganiga afsuslangan — biz imkoniyatni qo'ldan chiqarmaymiz!",
    '🛫 Wright aka-uchalar velosiped ustaxonasida samolyot yasagan — kichik ustaxona katta osmonga olib chiqadi!',
    "🍫 Ferrero Nutellani tanqislik paytida o'ylab topgan — qiyinchilik ixtiroga aylandi!",
    "📚 J.K. Rowlingning kitobini ko'p nashriyot rad etgan — keyin Garri Potter dunyoni egalladi!",
    "🎵 Beatles'ni bir yozuv kompaniyasi rad etgan — keyin tarix yaratildi. Rad javob — yo'lning boshi!",
    '🏀 Maykl Jordan bir paytlar maktab terma jamoasiga olinmagan — keyin afsonaga aylandi!',
    "🍵 Lipton choyni har bir uyga yetkazdi — biz ham sog'lom ovqatni har bir uyga!",
    '💡 Edison minglab urinishdan keyin lampani yoqdi — har bir urinish oldinga qadam!',
    '🚲 Uber bir tugma bilan taksini chaqirdi — bizda bir tugma bilan keto-savat!',
    '🧃 Red Bull bitta ichimlikdan global brend qildi — bitta yaxshi mahsulot yetadi!',
    "🌍 Patagonia mijozga 'kerakmas bo'lsa olmang' dedi — halollik ham brend!",
    "🖥 IBM yuz yildan ortiq yashadi, chunki o'zgardi — biz ham o'zgarishga tayyormiz!",
    "📞 Zappos qo'ng'iroqlarni soatlab gaplashib mijozni xursand qildi — samimiylik g'alaba qiladi!",
    "🧁 Bitta keks do'koni ham brendga aylanishi mumkin — bizning keto-keks navbatda!",
    "🍫 Hershey bir necha marta bankrot bo'lib, yana turdi — yiqilgan turadi!",
    "🏗 Burj Xalifa ham birinchi g'ishtdan boshlangan — bugungi buyurtma — g'isht!",
    "🔋 Duracell 'uzoq yashaydi' deydi — bizning g'ayrat undan ham uzoq!",
    "🎁 Amazon Prime bepul yetkazish bilan mijozni bog'ladi — bizda 800 mingdan bepul, ham bog'laymiz!",
    "🍦 Ben and Jerry's muzqaymog'i eski yoqilg'i shoxobchasida boshlangan — joy emas, ta'm muhim!",
    "🧑\u200d🚀 NASA Oyga borishdan oldin ko'p sinov qilgan — biz ham har kuni sinab, yaxshilaymiz!",
    "🛰 Starlink butun dunyoni ulayapti — biz esa butun Toshkentni sog'lom ovqatga ulaymiz!",
    "🎨 Canva'ni investorlar 100 dan ortiq marta rad etgan — keyin milliardlik kompaniya bo'ldi. Davom eting!",
    '📈 Warren Buffett sabr bilan boylik orttirgan — biz ham sabr bilan, buyurtma-buyurtma!',
    "🛋 IKEA mijozga o'zi yig'dirib, arzon qildi — aqlli yechim har doim yutadi!",
    "🍟 McDonald's jarayonni soatdek aniq qildi — bizning qadoqlash ham shu yo'lda!",
    "🧭 Toyota 'kaizen' — har kuni ozgina yaxshilanish. Bugun ham ozgina yaxshiroq!",
    "🥇 Apple 'boshqacha o'yla' degan — biz esa 'sog'lomroq o'yla' deymiz!",
    '🏁 Formula 1 jamoalari pit-stopni 2 soniyaga tushirgan — bizning tezlik ham mashq bilan!',
    "📦 FedEx asoschisining g'oyasiga universitetda past baho qo'yilgan — keyin butun dunyoga yetkazdi!",
    "🌐 Yandex qidiruvdan taksi va yetkazib berishgacha o'sdi — o'sish chegarasi yo'q!",
    '🤖 OpenAI ham kichik laboratoriyadan boshlagan — bugungi AI yordamchimiz ham shundan!',
    "🧩 Slack aslida o'yin kompaniyasining ichki vositasi edi — kutilmagan yo'l ham yutuq olib keladi!",
    "📺 YouTube boshida boshqa g'oya bilan boshlangan — moslashganlar yutadi!",
    "🦆 Duolingo hazil bilan million odamni o'qitdi — biz ham kulib-kulib sotamiz!",
    "🍿 Netflix o'z biznesini ikki marta qaytadan qurdi — o'zgarishdan qo'rqmaganlar g'olib!",
    "🛵 Glovo va Bolt shaharni tezlikka o'rgatdi — bizning kuryer ham ulardan qolishmaydi!",
    "🏋️ Peloton uyga sport olib keldi — biz uyga sog'lom ovqat olib kelyapmiz!",
    '🧪 Pfizer laboratoriyada yillab ishlaydi — sifatli ish vaqt talab qiladi, lekin arziydi!',
    '🌱 Beyond Meat ovqatga yangicha qarashni olib keldi — keto ham shunday inqilob!',
    '🍞 Warburtons non bilan oilaviy biznesni 140 yildan ortiq yuritmoqda — non va sabr — abadiy!',
    "🗽 Kichik startaplar Nyu-Yorkda ham, Toshkentda ham bir xil boshlanadi — g'oya va g'ayrat bilan!",
    '📮 Pochta ham bir paytlar otlarda yurgan — bugun bizning kuryer tezroq!',
    '🎯 Amazon bir paytlar faqat kitob sotardi — fokusdan boshlab kengayish kerak!',
    "💎 Tiffany ko'k qutisi bilan tanildi — bizning qutimiz ham bir kun shunday mashhur bo'ladi!",
    "🧴 L'Oréal 'Siz bunga loyiqsiz' deydi — biz ham aytamiz: siz bugungi muvaffaqiyatga loyiqsiz!",
    "🚀 Jeff Bezos 'Bugun ham birinchi kun' deydi — bizda ham har kun birinchi kundek g'ayrat!",
    "🛠 Bosch ustaxonadan dunyo brendigacha o'sdi — ustalik vaqt bilan keladi!",
    "🌟 Har bir yirik kompaniya ham bir paytlar sizdek kichik jamoa bo'lgan — davom etamiz!",
    "📊 Excel'ni bilganlar dunyoni boshqaradi — bizning hisobotlar ham shunday aniq!",
    "🧲 Apple do'konlarida mijoz tajribasi birinchi — bizda ham mijoz birinchi!",
    "🏆 Real Madrid ham har o'yinga birinchi o'yindek chiqadi — biz ham har buyurtmaga!",
    "🌍 Coca-Cola hamma joyda — Ketoshop ham bir kun shunday bo'ladi, faqat qandsiz!",
    "🧠 Einstein patent idorasida kotib bo'lib ishlagan — kim qayerdan boshlashi muhim emas!",
    "🛒 Alibaba'ning 'Bo'ydoqlar kuni' bitta g'oyadan dunyoning eng katta savdo kuniga aylandi — bizning aksiyalar ham!",
    "📦 Har bir global brend ham birinchi qutini qo'lda qadoqlagan — biz ham shu yo'ldamiz!",
    "🥇 Toyota sifatni har bir xodimga ishonib topshirgan — sifat bu yerda ham sizning qo'lingizda!",
    '🚀 Bugun Amazon, ertaga Ketoshop — kim biladi, kulgili emas, rejali!',
    "☁️ Salesforce 'bulutda' ishlashni ommalashtirdi — bizning kayfiyat ham bulutlardan baland!",
    "🏨 Marriott oilaviy kichik ichimlik do'konidan mehmonxona imperiyasigacha o'sdi — kichikdan boshlash uyat emas!",
]
# Kompaniyalarsiz umumiy kulgili va ruhlantiruvchi qatorlar.
FUN_GENERAL = [
    "😂 Dushanba ham bizdan qo'rqadi — biz har kuni juma kayfiyatida ishlaymiz!",
    "☕ Kofe tugasa ham, g'ayrat tugamaydi!",
    "🦸 Supermen plashsiz ham bo'ladi — siz bunga isbot!",
    '🐢 Toshbaqa ham marraga yetgan — biz esa undan tezroqmiz!',
    "🧗 Cho'qqiga hamma bir qadamdan boshlab chiqadi!",
    '😴 Uxlash ham ishning bir qismi — lekin hozir emas!',
    '🎢 Biznes — attraksion: baland-past, lekin juda qiziqarli!',
    "🌈 Bulutli kun ham o'tadi, savdo esa qoladi!",
    "🤓 Bugun o'rgangan bitta narsa — ertangi katta g'alaba!",
    '😆 Rejalar A dan Z gacha — agar A ishlamasa, alifboda yana 25 ta harf bor!',
    "🧩 Har bir bo'lak o'z joyiga tushyapti — rasm ham chiroyli chiqadi!",
    "🐝 Asalari ham to'xtamaydi — shuning uchun asal shirin!",
    "🎯 Maqsad aniq bo'lsa, yo'l o'zi topiladi!",
    '😂 Muammo keldi? U bizni hali tanimaydi!',
    '🔋 Quvvat 100% — agar kamaysa, bir piyola choy zaryadlaydi!',
    '🏃\u200d♂️ Marafon — sprint emas, lekin bugun biroz sprint qildik!',
    "🌱 Har bir katta daraxt ham bir urug'dan boshlangan!",
    '😎 Sovuqqonlik — eng kuchli superqahramonlik qobiliyati!',
    "📚 Xato — eng yaxshi o'qituvchi, lekin darsni takrorlamaymiz!",
    "🎉 Kichik g'alabalarni ham nishonlang — ular katta g'alabaning g'ishtlari!",
    "🧘 Shoshilmang — eng yaxshi ishlar xotirjam qo'lda bitadi!",
    '😂 Wi-Fi uzilsa ham, jamoa ruhi uzilmaydi!',
    "🦾 Bugun ham qo'limizdan keladi — kecha ham keldi-ku!",
    '🌅 Har tong — qayta yuklash tugmasi!',
    "🎵 Ish ham musiqa kabi — ritmni topsangiz, raqs o'zi boshlanadi!",
    '🍀 Omad — tayyorgarlik imkoniyat bilan uchrashgan joy!',
    "😜 Agar hammasi oson bo'lganda, hamma qilardi — biz esa qilyapmiz!",
    "🧠 Aqlli ishlash qattiq ishlashdan ham kuchli — ikkalasi bo'lsa, umuman zo'r!",
    "🏔 Tog' baland, lekin biz ham past emasmiz!",
    "🚦 Qizil chiroq ham o'tadi — keyin yashil yonadi!",
    "😂 Kalendarimiz to'lib ketdi — yaxshi belgi!",
    "🌊 To'lqin kelsa, suzishni o'rganamiz!",
    '🛡 Qiyinchilik — bizni chiniqtiradigan sport zali!',
    "🎈 Yengil bo'ling — og'ir yukni jamoa bilan ko'taramiz!",
    "🤝 Yolg'iz tez boriladi, birga uzoqqa boriladi!",
    "😄 Tabassum — eng arzon, lekin eng qimmat sovg'a!",
    "⏰ Vaqt — eng qimmat resurs, siz esa uni zo'r ishlatyapsiz!",
    "🔭 Uzoqni ko'ring, lekin oyoq ostini ham unutmang!",
    "😂 Bugungi ish rejasi: zo'r bo'lish. Bajarildi ✅",
    "🌟 Yorug' yulduzlar qorong'ida yaxshi ko'rinadi — qiyin kunda ham porlaymiz!",
    "🧭 Yo'ldan adashsak ham, kompas — maqsadimiz!",
    "🏅 G'olib — bu yiqilib, yana turganlar!",
    "😎 Stress? U kim bo'ldi? Tanishmaymiz!",
    "🍃 Shamol qarshi bo'lsa — samolyot shunday ko'tariladi!",
    "🎬 Har bir kun — yangi seriya, bugungisi zo'r chiqdi!",
    '😂 Ishimiz shunchalik yaxshiki, hatto printer ham hasad qilyapti!',
    "💡 Eng yaxshi g'oyalar choy ustida keladi — choy damlang!",
    '🪜 Zinapoyani bir sakrashda emas, qadamma-qadam chiqamiz!',
    "🌍 Dunyoni o'zgartirish — bitta mamnun mijozdan boshlanadi!",
    "😄 Bugun ham shunday zo'r ishladingiz-ki, ertaga o'zingizga havas qilasiz!",
]
FUN_ALL = FUN_UZ + FUN_WORLD + FUN_GENERAL
FUN_SHARE = 0.5          # aniq xabarga bog'langan qator (#raqam, summa) bilan teng ehtimol


def cheer_line(text: str, lang: str = "uz", rng: random.Random | None = None) -> str:
    kind = classify(text)
    found = facts(text)
    pool = PHRASES[kind]["ru" if lang == "ru" else "uz"]

    def usable(tpl: str) -> bool:
        return all(k in found for k in re.findall(r"{(\w+)}", tpl))

    fitting = [p for p in pool if usable(p)]
    # Prefer a line that talks about THIS message; fall back to the rest.
    specific = [p for p in fitting if "{" in p]
    general = [p for p in fitting if "{" not in p] or fitting
    if lang != "ru" and kind != "error":
        general = general + FUN_ALL         # hazil va ruhlantiruvchi qatorlar — xato xabarlarida emas
    rnd = rng or random
    tpl = rnd.choice(specific) if specific and rnd.random() < FUN_SHARE else rnd.choice(general)
    if lang == "uz_cyr":
        from translit import lat_to_cyr
        tpl = lat_to_cyr(tpl)
    return tpl.format(**found)


@contextlib.contextmanager
def quiet():
    token = _quiet.set(True)
    try:
        yield
    finally:
        _quiet.reset(token)


_lang_cache: dict[int, tuple[float, str]] = {}


async def _admin_lang(chat_id: int) -> str:
    hit = _lang_cache.get(chat_id)
    if hit and time.monotonic() - hit[0] < 600:
        return hit[1]
    try:
        import database
        lang = await database.get_user_language(chat_id)
    except Exception:
        lang = "uz"
    _lang_cache[chat_id] = (time.monotonic(), lang)
    return lang


def _is_markdown(parse_mode) -> bool:
    return isinstance(parse_mode, str) and parse_mode.lower().startswith("markdown")


class CurrentUserMiddleware(BaseMiddleware):
    """dp.update.outer_middleware — remembers who triggered this update."""

    async def __call__(self, handler, event, data):
        user = data.get("event_from_user")
        token = _current_user.set(user.id if user else None)
        try:
            return await handler(event, data)
        finally:
            _current_user.reset(token)


class AdminCheerMiddleware(BaseRequestMiddleware):
    """bot.session.middleware — appends the cheer line to admin notifications."""

    def __init__(self, admin_ids):
        self.admin_ids = admin_ids   # the live set — admins added at runtime count

    async def __call__(self, make_request, bot, method):
        try:
            method = await self._decorate(method)
        except Exception:
            pass   # never let a joke break a delivery
        return await make_request(bot, method)

    async def _decorate(self, method):
        if not ENABLED or _quiet.get():
            return method
        from aiogram.methods import SendDocument, SendMessage, SendPhoto, SendVideo
        if isinstance(method, SendMessage):
            field, limit = "text", TEXT_LIMIT
        elif isinstance(method, (SendPhoto, SendDocument, SendVideo)):
            field, limit = "caption", CAPTION_LIMIT
        else:
            return method
        chat_id = method.chat_id
        if not isinstance(chat_id, int) or chat_id not in self.admin_ids:
            return method
        if chat_id == _current_user.get():
            return method   # a reply to this admin's own tap/command
        if _is_markdown(getattr(method, "parse_mode", None)):
            return method
        body = getattr(method, field, None)
        if not body:
            return method
        line = cheer_line(body, await _admin_lang(chat_id))
        new_body = f"{body}\n\n{line}"
        if len(new_body) > limit:
            return method
        return method.model_copy(update={field: new_body})


# ===== /kayfiyat_test — preview for the admin who types it, nobody else =====

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from config import ADMIN_IDS

router = Router()

SAMPLES = [
    "🔔 <b>Yangi buyurtma #512</b>\n\n👤 Namuna mijoz\n🛒 Zig'ir uni 300gr × 2\n💰 <b>Jami: 184 000 so'm</b>",
    "🚚 Buyurtma #512 yo'lga chiqdi.",
    "📦 Buyurtma #512 mijozga yetkazildi.",
    "❌ Mijoz buyurtma #513 ni bekor qildi.",
    "🧾 #514 buyurtma to'lov cheki — 245 000 so'm",
    "👤 Yangi foydalanuvchi qo'shildi: Namuna (taklif qilgan: Ali)",
    "📣 Reklamadan yangi lid: +998 90 000 00 00",
    "📊 Kunlik hisobot: 12 ta buyurtma, jami 2 450 000 so'm",
    "⚠️ Kanal posti yuborilmadi: xato 400",
]


@router.message(Command("kayfiyat_test"), F.from_user.id.in_(ADMIN_IDS))
async def cmd_mood_test(message: Message):
    """Every kind of admin notification with its mood line, sent only to the
    admin who asked — the safe way to see the tone before it reaches all."""
    import database
    import stock_alerts
    lang = await database.get_user_language(message.from_user.id)
    await message.answer("🧪 <b>Kayfiyat sinovi</b> — namunalar faqat sizga yuboriladi.")
    product = {"name": "Zig'ir uni 300gr", "quantity": 0, "unit": "piece", "low_stock_threshold": None}
    await message.answer(stock_alerts._alert_text(product, "out", lang))
    await message.answer(stock_alerts._alert_text(dict(product, quantity=3), "low", lang))
    for sample in SAMPLES:
        await message.answer(f"{sample}\n\n{cheer_line(sample, lang)}")
