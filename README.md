# 🛒 Ketoshop

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

**For production**, consider:
- Use **webhooks** instead of polling (faster, more reliable)
- Switch to **PostgreSQL** with `asyncpg` for larger scale
- Add **Redis** for FSM storage (`aiogram.fsm.storage.redis`)
- Deploy on a VPS (e.g., Timeweb, Aeza) or use **Railway** / **Render**
- Set up **systemd** or **Docker** for auto-restart

### Docker Example
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python", "bot.py"]
```

## 📝 License

MIT — use freely for your marketplace!
