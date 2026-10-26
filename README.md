# 🛒 Ketoshop

> Current production uses PostgreSQL (`asyncpg` in `database.py`), a polling
> Telegram bot, and GitHub Actions → GHCR → netcup from `master`. The setup
> example below is an old standalone guide; follow the current code,
> `.github/workflows/` and `AGENTS.md` for development and deployment.

Telegram Marketplace Bot for organic & natural products in Uzbekistan.

**Features:**
- 🇺🇿/🇷🇺 Bilingual UI (Uzbek & Russian — user chooses at start)
- 🛒 Product catalog with 8 categories (fruits, vegetables, herbs, honey, dried fruits, grains, dairy, other)
- 🛍 Shopping cart with quantity selection
- 📦 Full checkout flow (name → phone → address → payment)
- 💳 Telegram Payments support + cash on delivery
- 📊 Seller panel: add/manage products, view orders, statistics
- 🔔 Real-time order notifications to sellers
- 📱 Uzbek phone number validation (+998XXXXXXXXX)

## ⚡ Quick Setup

### 1. Create your bot
- Open [@BotFather](https://t.me/BotFather) on Telegram
- Send `/newbot`, follow the prompts
- Copy the **API token**

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure
Edit `config.py` or set environment variables:

```bash
export BOT_TOKEN="7123456789:AAH..."
export PAYMENT_PROVIDER_TOKEN="..."  # Optional: from @BotFather → Payments
export ADMIN_IDS="123456789"         # Your Telegram user ID
```

### 4. Run
```bash
python bot.py
```

## 💳 Setting up Payments (Optional)

1. Open [@BotFather](https://t.me/BotFather)
2. Send `/mybots` → Select your bot → **Payments**
3. Choose a payment provider (Click, Payme, Stripe, etc.)
4. Copy the provider token to `PAYMENT_PROVIDER_TOKEN`

> For **Uzbekistan**, recommended providers: **Click**, **Payme**, or **Stripe**

## 📁 Project Structure

```
marketplace_bot/
├── bot.py                  # Main entry point
├── config.py               # Configuration
├── database.py             # SQLite database layer
├── locales.py              # UZ/RU translations
├── keyboards.py            # Inline keyboard builders
├── requirements.txt
├── handlers/
│   ├── start.py            # /start, language, main menu
│   ├── catalog.py          # Browse categories & products
│   ├── cart.py             # Cart, checkout, orders, payments
│   └── seller.py           # Seller panel, product management
```

## 🗂 Product Categories

| Emoji | O'zbek | Русский |
|-------|--------|---------|
| 🍎 | Mevalar | Фрукты |
| 🥕 | Sabzavotlar | Овощи |
| 🌿 | Dorivor o'simliklar | Лечебные растения |
| 🍯 | Asal mahsulotlari | Мёд и продукты пчеловодства |
| 🥜 | Quritilgan mevalar | Сухофрукты и орехи |
| 🌾 | Don mahsulotlari | Зерновые и крупы |
| 🥛 | Sut mahsulotlari | Молочные продукты |
| 📦 | Boshqalar | Другое |

## 🔧 Deployment Tips

Admin panelining **Chiqimlar** bo'limida qo'lda kiritilgan chiqimlarni qo'shish,
ko'rish, **Tahrirlash** va tasdiqlab **O'chirish** mumkin. Summani kiritganda
formatlangan qiymat ko'rinadi (masalan, `125 000 so'm`). Tahrirlash chiqimning
asl sanasini saqlaydi. Buyurtmadan avtomatik yozilgan sovg'a, aksiya va kuryer
chiqimlari buyurtma raqami bilan belgilanadi va shu ro'yxatdan o'zgartirilmaydi.

Admin botida `/mahsulot_savdosi` yoki `/admin` → **Statistika va Hisobot** →
**Mahsulot savdosi — 15/30 kun** orqali barcha sotilgan mahsulotlar va
to'plamlarning oxirgi 15 va 30 kunlik hisoboti olinadi. Eski `/banka`
buyrug'i ham shu to'liq hisobotni ochadi. Davr Toshkent sanasi bo'yicha,
bugungi kun bilan birga hisoblanadi. Miqdor, o'rtacha narx, summa va B2B
ulushi admin Dashboard'dagi «Mahsulot savdosi» bilan bir xil asosda olinadi;
bekor qilingan buyurtmalar va sovg'alar sotuvga kirmaydi. Mahsulotlar yonida
taxminiy pochta narxi chiqmaydi. Buyurtmada pochta haqi hisoblangan bo'lsa,
saqlangan summa buyurtma raqami va sanasi bilan alohida ko'rsatiladi;
u mahsulotlar jamiga qo'shilmaydi va bugungi tarif bilan qayta hisoblanmaydi.
Pochta summasi qayd etilmagan bo'lsa, bu bo'lim chiqmaydi. Uzun ro'yxat
mahsulotlarni tashlab ketmasdan bir nechta xabarga bo'linadi. Yangilanishdan
keyin shu hisobot har bir adminga bir marta, 09:00–21:00 oralig'ida yuboriladi.

Amaldagi production deploy yo‘li: GitHub Actions → GHCR → netcup.

1. `master` ga push qilinganda [CI](.github/workflows/ci.yml) ishga tushadi.
   U Python 3.12 muhitida bog‘liqliklarni o‘rnatib, sintaksis tekshiruvi,
   modullarni import qilish sinovi va `unittest` testlarini bajaradi. CI pull
   requestlarda ham ishlaydi.
2. [Deploy](.github/workflows/deploy.yml) ish oqimi `master` ga push qilinganda
   (yoki qo‘lda `workflow_dispatch` orqali) CI ni chaqiradi. CI muvaffaqiyatli
   tugagach, Docker tasviri GHCR ga commit SHA va `latest` teglari bilan
   yuboriladi: `ghcr.io/<repository_owner>/ketoshop:<commit_sha>`.
3. Build tugagach, `production` muhiti uchun SSH bosqichi netcup serverida
   `/srv/stack/scripts/deploy.sh ketoshop <commit_sha>` ni ishga tushiradi.
   Deploy uchun zarur maxfiy qiymatlar GitHub Actions secrets orqali beriladi.
4. Yakunda netcup da ishlayotgan tasvirning SHA qiymati aynan yuborilgan commit
   SHA ga mosligini va xizmat sog‘lom ishlayotganini tekshiring. SSH bosqichi
   o‘tkazib yuborilgan bo‘lsa, yashil workflow natijasi deploy tasdig‘i emas.

## 📝 License

MIT — use freely for your marketplace!

## Kanal bestsellerlari

2026-10-23 dan boshlab har 3 kunda Toshkent vaqti bilan 10:00 da kanalga
oxirgi 30 kunning TOP-10 mahsuloti chiqadi. Post kirillchada, faqat nomlar
va do'konni ochish tugmasi bilan: sotilgan va ombordagi sonlar ko'rsatilmaydi.
Bekor qilingan va ichki test buyurtmalari, bepul bonus/sovg'alar hisoblanmaydi;
haqiqiy qo'lda kiritilgan va B2B savdolar hisobga olinadi. Faqat faol,
zaxirada bor, chakana sotuvga ochiq mahsulotlar chiqariladi. Oylik savdo
bo'lmasa eski davr bilan to'ldirilmaydi va bo'sh post yuborilmaydi.

Davr kalendarga bog'langan: 23, 26, 29-oktabr, 1-noyabr va hokazo. Bot
o'sha kuni kechroq ishga tushsa, 22:00 gacha yuboradi; o'tgan kunlar
to'planib yuborilmaydi. Mavjud bazadagi kunlik kalit restart/redeployda
takrorni to'sadi. Telegram aniq rad etsa qayta uriniladi; javobi noma'lum
bo'lgan tarmoq xatosida takror xavfi sabab avtomatik qayta yuborilmaydi.

## Olib ketish (pickup)

Pickup is disabled on a fresh database. An authenticated admin can configure it
in **Admin → Olib ketish** by entering the shop's real address and an HTTPS map
link, then enabling it. Leave it disabled until both values are correct.
Settings are kept in one database row; changing them does not rewrite
instructions already attached to existing orders.

When enabled, bot and Mini App customers can choose delivery or pickup. Pickup
uses the customer's primary phone, skips their home location and courier-only
fields, and supports cash at collection or the existing online cheque flow.
The shop address and instructions come from server settings, and pickup adds no
customer delivery fee or courier expense.

When a pickup order is ready, the customer receives the saved collection
address and map link. After the customer has collected it, an admin can
mark it **Olib ketildi** from the ready card in the Admin courier board. That
moves the order to delivered and triggers the existing delivery rewards.
