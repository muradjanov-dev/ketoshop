"""
Bot configuration settings
"""
import os

# Bot token from @BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# Payment provider token (from @BotFather -> Payments)
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "YOUR_PAYMENT_TOKEN_HERE")

# Database — required. No fallback: a missing/typo'd DATABASE_URL used to
# silently fall back to a hardcoded string, masking env-wiring issues as
# opaque asyncpg TCP timeouts (lost ~half a day debugging once). Fail loud
# at import so the next time the wiring breaks, the log says exactly that.
# On Railway, set this as a reference: DATABASE_URL=${{Postgres.DATABASE_URL}}
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. On Railway, set the bot service's "
        "DATABASE_URL variable to the reference ${{Postgres.DATABASE_URL}} "
        "so it auto-tracks the Postgres add-on across recreations."
    )

# Admin user IDs (Telegram user IDs who can manage the bot)
_HARDCODED_ADMINS = {917456291, 1035429145}
_env_admins = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
ADMIN_IDS = list(_HARDCODED_ADMINS | _env_admins)

# Currency
CURRENCY = "UZS"  # Uzbek So'm

# Bot settings
ITEMS_PER_PAGE = 5
MAX_PRODUCT_PHOTOS = 5

# Support username shown in the help section (without @)
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "keto_market")

# Channel/group for order notifications (optional)
ORDER_NOTIFICATION_CHAT = os.getenv("ORDER_NOTIFICATION_CHAT", "")

# WebApp (Mini App) URL
WEBAPP_URL = os.getenv("WEBAPP_URL", "") or "https://worker-production-5412.up.railway.app"

# Online payment destination — shown to buyers in the cheque prompt.
# Override via env so rotating the card doesn't require a redeploy.
PAYMENT_CARD_NUMBER = os.getenv("PAYMENT_CARD_NUMBER", "9860 1701 0488 8293")
PAYMENT_RECIPIENT_NAME = os.getenv("PAYMENT_RECIPIENT_NAME", "Jamshid Raupov")

# Push admin alerts when a product's stock drops to or below this number
# after an order. Fires only on the *crossing* — not on every subsequent order.
LOW_STOCK_THRESHOLD = int(os.getenv("LOW_STOCK_THRESHOLD", "5"))

# Admin website (/admin) password. REQUIRED for the panel to work: when unset,
# /admin returns 503 instead of falling back to a guessable default.
ADMIN_WEB_PASSWORD = os.getenv("ADMIN_WEB_PASSWORD", "")

# Channel buyers must be subscribed to before using the bot (owner request
# 2026-07-27) — see subscription_gate.py. Override via env if the channel
# ever changes.
REQUIRED_CHANNEL_ID = int(os.getenv("REQUIRED_CHANNEL_ID", "-1002132040345"))
REQUIRED_CHANNEL_USERNAME = os.getenv("REQUIRED_CHANNEL_USERNAME", "ketoshop_uz")

# Bot's own @username (without @), used to build referral deep links
# (t.me/<username>?start=ref<id>) for the Keto musobaqasi contest.
BOT_USERNAME = os.getenv("BOT_USERNAME", "ketoshopbot")
