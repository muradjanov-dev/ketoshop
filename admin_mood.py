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


def cheer_line(text: str, lang: str = "uz", rng: random.Random | None = None) -> str:
    kind = classify(text)
    found = facts(text)
    pool = PHRASES[kind]["ru" if lang == "ru" else "uz"]

    def usable(tpl: str) -> bool:
        return all(k in found for k in re.findall(r"{(\w+)}", tpl))

    fitting = [p for p in pool if usable(p)]
    # Prefer a line that talks about THIS message; fall back to the rest.
    specific = [p for p in fitting if "{" in p]
    rnd = rng or random
    tpl = rnd.choice(specific) if specific and rnd.random() < 0.75 else rnd.choice(
        [p for p in fitting if "{" not in p] or fitting)
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
