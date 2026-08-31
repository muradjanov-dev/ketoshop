"""
Database layer using asyncpg (PostgreSQL)
"""
import asyncpg
import json
import os
from config import DATABASE_URL, ADMIN_IDS

pool: asyncpg.Pool | None = None


async def init_db():
    """Initialize connection pool and database tables"""
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)

    async with pool.acquire() as conn:
        # Typo-tolerant product search. pg_trgm is a trusted extension the
        # non-superuser Railway role can create. If it's unavailable, search
        # falls back to plain ILIKE (see search_products).
        try:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        except Exception:
            pass
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS couriers (
                user_id BIGINT PRIMARY KEY,
                added_by BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                phone TEXT,
                address TEXT,
                language TEXT DEFAULT 'uz',
                is_seller INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id SERIAL PRIMARY KEY,
                seller_id BIGINT NOT NULL REFERENCES users(user_id),
                name TEXT NOT NULL,
                description TEXT,
                price DOUBLE PRECISION NOT NULL,
                unit TEXT DEFAULT 'kg',
                quantity DOUBLE PRECISION DEFAULT 0,
                category TEXT NOT NULL,
                photo_id TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS cart (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(user_id),
                product_id INTEGER REFERENCES products(id),
                set_id INTEGER REFERENCES product_sets(id),
                quantity DOUBLE PRECISION NOT NULL DEFAULT 1,
                CHECK ((product_id IS NOT NULL AND set_id IS NULL) OR (product_id IS NULL AND set_id IS NOT NULL))
            )
        """)
        try:
            await conn.execute("ALTER TABLE cart ALTER COLUMN product_id DROP NOT NULL")
            await conn.execute("ALTER TABLE cart ADD COLUMN IF NOT EXISTS set_id INTEGER REFERENCES product_sets(id)")
        except Exception:
            pass
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(user_id),
                seller_id BIGINT,
                customer_name TEXT,
                phone TEXT,
                address TEXT,
                items TEXT,
                total DOUBLE PRECISION NOT NULL,
                status TEXT DEFAULT 'pending',
                payment_method TEXT DEFAULT 'cash',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            await conn.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS courier_id BIGINT")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_courier_id ON orders(courier_id)")
        except Exception:
            pass
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(user_id),
                product_id INTEGER NOT NULL REFERENCES products(id),
                order_id INTEGER,
                rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, product_id)
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS delivery_zones (
                id SERIAL PRIMARY KEY,
                city_name_uz TEXT NOT NULL,
                city_name_ru TEXT NOT NULL,
                price DOUBLE PRECISION NOT NULL DEFAULT 0,
                min_free_delivery DOUBLE PRECISION DEFAULT 0,
                estimated_days TEXT DEFAULT '1-2',
                is_active INTEGER DEFAULT 1
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id BIGINT PRIMARY KEY,
                reason TEXT,
                banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Admins added at runtime via the bot's "Add admin" flow, on top of
        # the always-present hardcoded/env set in config.ADMIN_IDS.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id BIGINT PRIMARY KEY,
                added_by BIGINT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS product_media (
                id SERIAL PRIMARY KEY,
                product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                file_id TEXT NOT NULL,
                media_type TEXT DEFAULT 'photo',
                sort_order INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS product_views (
                id SERIAL PRIMARY KEY,
                product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
                user_id BIGINT,
                viewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # One-time NPS (1-10) satisfaction survey. `comment` is filled in
        # separately, after the score, once the buyer replies with a reason
        # (or /skip) — see nps_survey.py / handlers/nps.py.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS nps_responses (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(user_id),
                score INTEGER NOT NULL CHECK (score >= 1 AND score <= 10),
                comment TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # General interaction log for the admin activity dashboard — how many
        # distinct users touched the bot in a period, and which buttons/
        # sections get used the most. 'kind' separates real button taps
        # ('callback') from free-text messages ('message'), so the "top
        # buttons" ranking doesn't get diluted by typed text/phone numbers.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS bot_activity (
                id SERIAL PRIMARY KEY,
                user_id BIGINT,
                kind TEXT NOT NULL,
                action TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Scheduled tips broadcast — single-row state table tracking which tip
        # goes out next and when the last one was sent. Survives restarts so the
        # 2-day cadence isn't reset every deploy.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS broadcast_state (
                id INTEGER PRIMARY KEY DEFAULT 1,
                next_index INTEGER NOT NULL DEFAULT 0,
                last_sent_at TIMESTAMP,
                enabled BOOLEAN NOT NULL DEFAULT FALSE,
                last_warn_date DATE,
                CONSTRAINT broadcast_state_single CHECK (id = 1)
            )
        """)
        await conn.execute(
            "INSERT INTO broadcast_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING"
        )

        # Personalized recommendation broadcaster — its own single-row state,
        # independent from the generic tips above. `cycle` advances each send so
        # returning buyers get rotated recipe/benefit content.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS personal_reco_state (
                id INTEGER PRIMARY KEY DEFAULT 1,
                cycle INTEGER NOT NULL DEFAULT 0,
                last_sent_at TIMESTAMP,
                enabled BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT personal_reco_state_single CHECK (id = 1)
            )
        """)
        await conn.execute(
            "INSERT INTO personal_reco_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING"
        )

        # Fingerprints of every personalized message actually delivered, so a
        # buyer is never sent a byte-identical message twice: if all content
        # variants for their profile are exhausted, we skip them that round
        # instead of repeating.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS personal_reco_sent (
                user_id BIGINT NOT NULL,
                msg_hash TEXT NOT NULL,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, msg_hash)
            )
        """)

        # Daily full-DB backup scheduler — single-row state tracking the last
        # successful backup date, so a redeploy mid-day doesn't re-send it.
        # Added 2026-07-13 after the products table was found wiped with no
        # recent backup anywhere; this guarantees admins always have a copy
        # of the full DB from Telegram itself, independent of Railway.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS db_backup_state (
                id INTEGER PRIMARY KEY DEFAULT 1,
                last_backup_date DATE,
                CONSTRAINT db_backup_state_single CHECK (id = 1)
            )
        """)
        await conn.execute(
            "INSERT INTO db_backup_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING"
        )

        # Meta (Facebook/Instagram) Lead Ads inbox. Every lead pulled from the
        # Graph API is stored here before it's pushed to Telegram: the row is
        # what makes the poll idempotent (a restart mid-sweep can't re-notify),
        # and it outlives Meta's own 90-day retention, so the contact history
        # survives even after Meta deletes it upstream. handled_by/handled_at
        # record which admin tapped "Bog'landim" so two people don't call the
        # same buyer.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS meta_leads (
                lead_id TEXT PRIMARY KEY,
                form_id TEXT,
                form_name TEXT,
                full_name TEXT,
                phone TEXT,
                email TEXT,
                campaign_name TEXT,
                ad_name TEXT,
                raw JSONB,
                created_time TIMESTAMPTZ,
                received_at TIMESTAMPTZ DEFAULT NOW(),
                handled_by BIGINT,
                handled_at TIMESTAMPTZ
            )
        """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS meta_leads_created_idx ON meta_leads (created_time DESC)"
        )

        # Product "sets" (bundles) managed from the admin website. The bundle is
        # sold at set_price; the individual combined price is computed on the fly
        # from the member products so the UI can show it struck-through.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS product_sets (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                name_ru TEXT,
                description TEXT,
                description_ru TEXT,
                set_price DOUBLE PRECISION NOT NULL DEFAULT 0,
                image_url TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS product_set_items (
                id SERIAL PRIMARY KEY,
                set_id INTEGER NOT NULL REFERENCES product_sets(id) ON DELETE CASCADE,
                product_id INTEGER NOT NULL REFERENCES products(id),
                quantity DOUBLE PRECISION NOT NULL DEFAULT 1
            )
        """)

        # Images uploaded through the admin website. Stored in Postgres (not on
        # disk) because Railway's filesystem is ephemeral — a redeploy would
        # otherwise wipe every product photo. Served via GET /img/{id}.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS web_images (
                id SERIAL PRIMARY KEY,
                data BYTEA NOT NULL,
                content_type TEXT NOT NULL DEFAULT 'image/jpeg',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Add translation columns if they don't exist
        for col in ("name_ru", "description_ru"):
            try:
                await conn.execute(f"ALTER TABLE products ADD COLUMN {col} TEXT")
            except Exception:
                pass  # Column already exists

        # Per-product discount (percent off, 0-100) and optional expiry
        try:
            await conn.execute("ALTER TABLE products ADD COLUMN discount_percent INTEGER DEFAULT 0")
        except Exception:
            pass
        try:
            await conn.execute("ALTER TABLE products ADD COLUMN discount_until TIMESTAMP")
        except Exception:
            pass

        # Per-product low-stock threshold (NULL = use global LOW_STOCK_THRESHOLD)
        try:
            await conn.execute("ALTER TABLE products ADD COLUMN low_stock_threshold INTEGER")
        except Exception:
            pass

        # Cost price (what we paid to acquire one unit). Admin-only — never
        # exposed to buyers. Used for accounting / profit reports.
        try:
            await conn.execute("ALTER TABLE products ADD COLUMN cost_price DOUBLE PRECISION DEFAULT 0")
        except Exception:
            pass

        # Website-hosted product image (URL/path served by our own server).
        # Separate from photo_id (a Telegram file_id) so images uploaded via the
        # admin website work on a plain browser page, not only inside Telegram.
        try:
            await conn.execute("ALTER TABLE products ADD COLUMN image_url TEXT")
        except Exception:
            pass

        # Add payment_method column to users
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN payment_method TEXT DEFAULT 'cash'")
        except Exception:
            pass

        # Add location columns to orders
        for col, col_type in [("latitude", "DOUBLE PRECISION"), ("longitude", "DOUBLE PRECISION")]:
            try:
                await conn.execute(f"ALTER TABLE orders ADD COLUMN {col} {col_type}")
            except Exception:
                pass

        # Delivery method chosen by buyer (self / yandex_taxi / yandex_market / bts / emu)
        try:
            await conn.execute("ALTER TABLE orders ADD COLUMN delivery_method TEXT")
        except Exception:
            pass

        # Free-form note for the courier (apartment number, floor, landmark, etc.)
        try:
            await conn.execute("ALTER TABLE orders ADD COLUMN address_note TEXT")
        except Exception:
            pass

        # Optional backup contact — courier dials this if primary is unreachable.
        try:
            await conn.execute("ALTER TABLE orders ADD COLUMN secondary_phone TEXT")
        except Exception:
            pass

        # Where the order came from. NULL/'bot'/'webapp' = buyer self-service;
        # 'manual' = admin entered an offline (phone/in-person) order so all
        # orders live in one table for stats/accounting.
        try:
            await conn.execute("ALTER TABLE orders ADD COLUMN source TEXT")
        except Exception:
            pass

        # Lifecycle timestamps — set the first time the order enters each state
        for col in ("confirmed_at", "shipped_at", "delivered_at"):
            try:
                await conn.execute(f"ALTER TABLE orders ADD COLUMN {col} TIMESTAMP")
            except Exception:
                pass

        # Payment cheque (online orders) — file_id + kind ('photo'/'document')
        # so the admin can re-view the proof later from the order card.
        for col in ("cheque_file_id", "cheque_type"):
            try:
                await conn.execute(f"ALTER TABLE orders ADD COLUMN {col} TEXT")
            except Exception:
                pass

        # Keto-as-discount redemption (2026-07-30, built dormant — see
        # gamification_state.redemption_enabled below). How much of this
        # order's total was covered by spending Keto balance (1 Keto = 1 so'm),
        # recorded for the buyer's order history / admin accounting even
        # though the feature isn't live for real users yet.
        try:
            await conn.execute("ALTER TABLE orders ADD COLUMN keto_redeemed INTEGER NOT NULL DEFAULT 0")
        except Exception:
            pass

        # Keto gamification (added 2026-07-26, test rollout — earning only,
        # no spending yet). keto_balance == keto_lifetime for now since
        # nothing is ever deducted; kept as two columns so a future "spend"
        # feature can drain balance without retroactively lowering levels/
        # achievements, which key off keto_lifetime. keto_pin_message_id
        # tracks the per-user pinned "Keto card" so it gets edited in place
        # instead of re-pinned (and re-notified) every refresh.
        for col, col_type in [
            ("keto_balance", "INTEGER NOT NULL DEFAULT 0"),
            ("keto_lifetime", "INTEGER NOT NULL DEFAULT 0"),
            ("keto_pin_message_id", "BIGINT"),
        ]:
            try:
                await conn.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
            except Exception:
                pass

        # One-time Kabinetim onboarding — a short explainer shown the very
        # first time a user opens the section (owner request 2026-07-27),
        # never again after.
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN kabinetim_intro_seen BOOLEAN NOT NULL DEFAULT FALSE")
        except Exception:
            pass

        # The persistent 🏠/🛒 reply keyboard is sent once per chat and then
        # stays put on Telegram's side (2026-08-31) — this records that it has
        # been, so /start doesn't re-send the explainer message every time.
        try:
            await conn.execute("ALTER TABLE users ADD COLUMN menu_keyboard_sent BOOLEAN NOT NULL DEFAULT FALSE")
        except Exception:
            pass

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS keto_ledger (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(user_id),
                order_id INTEGER,
                amount INTEGER NOT NULL,
                kind TEXT NOT NULL,
                note TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # One order can only ever pay out Keto once, no matter how many times
        # its status gets bounced around (partial index only applies to
        # kind='order' rows, so achievement-kind rows with order_id NULL
        # aren't constrained by this).
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_keto_ledger_order_once "
            "ON keto_ledger(order_id) WHERE kind = 'order'"
        )
        # Mirrors the above for the opposite direction: an order's Keto
        # redemption (spend) can also only ever be debited once.
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_keto_ledger_redeem_once "
            "ON keto_ledger(order_id) WHERE kind = 'redeem'"
        )

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS user_achievements (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(user_id),
                code TEXT NOT NULL,
                unlocked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, code)
            )
        """)

        # Single-row on/off switch (owner: "fikrimdan qaytsam olib tashlaymiz"
        # — needs an instant kill switch without a redeploy) + the daily
        # pin-card refresh watermark, same single-row pattern as
        # broadcast_state/db_backup_state.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS gamification_state (
                id INTEGER PRIMARY KEY DEFAULT 1,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                last_pin_refresh_date DATE,
                CONSTRAINT gamification_state_single CHECK (id = 1)
            )
        """)
        await conn.execute(
            "INSERT INTO gamification_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING"
        )

        # Keto-as-discount at checkout (2026-07-30): opt-in, buyer picks how
        # much of their own balance to apply (1 Keto = 1 so'm off the total).
        # Built dormant on purpose — owner wants it ready but NOT available to
        # real users yet, separate from the earn-side kill switch above so
        # earning and spending can be toggled independently.
        try:
            await conn.execute(
                "ALTER TABLE gamification_state ADD COLUMN redemption_enabled BOOLEAN NOT NULL DEFAULT FALSE"
            )
        except Exception:
            pass

        # Referral tracking (2026-07-30, "Keto musobaqasi" contest). One row per
        # successful invite — UNIQUE on referred_user_id means the first link a
        # new user clicks is the only one that ever counts (no re-crediting a
        # later inviter for the same person).
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                id SERIAL PRIMARY KEY,
                referred_user_id BIGINT NOT NULL UNIQUE REFERENCES users(user_id),
                referrer_user_id BIGINT NOT NULL REFERENCES users(user_id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_user_id)")

        # Single-row contest state, same pattern as gamification_state/
        # broadcast_state. image_url points at a web_images row uploaded
        # through the admin panel. prize_1/2/3 are free-form text (can list
        # more than one gift per place) set by the admin at launch.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS referral_contest_state (
                id INTEGER PRIMARY KEY DEFAULT 1,
                active BOOLEAN NOT NULL DEFAULT FALSE,
                started_at TIMESTAMP,
                ends_at TIMESTAMP,
                image_url TEXT,
                prize_1 TEXT,
                prize_2 TEXT,
                prize_3 TEXT,
                last_reminder_date DATE,
                winners_announced BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT referral_contest_state_single CHECK (id = 1)
            )
        """)
        await conn.execute(
            "INSERT INTO referral_contest_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING"
        )
        # Optional contest video — stores a Telegram file_id, NOT our own
        # hosted URL: the admin's upload gets relayed through the bot once
        # (see admin_web.py's api_contest_upload_video) purely to obtain a
        # file_id, and the bytes are never persisted in Postgres. Telegram's
        # own CDN hosts the video from then on; the bot prefers video over
        # photo when both are set (see referral_contest.py).
        try:
            await conn.execute("ALTER TABLE referral_contest_state ADD COLUMN video_file_id TEXT")
        except Exception:
            pass

        # Same idea for a photo, but uploaded from the bot's own in-chat
        # admin panel (owner request 2026-07-30) — there the bot already has
        # the file_id directly from the sent photo, no relay-upload trick
        # needed (that trick exists only for the website, which has no bot
        # connection of its own). Kept separate from image_url (a webapp-
        # hosted URL string from the website's upload) since the two aren't
        # interchangeable inputs to send_photo.
        try:
            await conn.execute("ALTER TABLE referral_contest_state ADD COLUMN image_file_id TEXT")
        except Exception:
            pass

        # A separate, ADDITIONAL "how to participate" video (owner request
        # 2026-07-31) — coexists with the main promo photo/video above rather
        # than replacing it. Sent as its own extra message after the main
        # contest post, when set.
        try:
            await conn.execute("ALTER TABLE referral_contest_state ADD COLUMN guide_video_file_id TEXT")
        except Exception:
            pass

        # Indexes
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_product_media_product ON product_media(product_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_product_views_product ON product_views(product_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_product_views_time ON product_views(viewed_at)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_bot_activity_time ON bot_activity(created_at)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_bot_activity_kind_time ON bot_activity(kind, created_at)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_nps_responses_user ON nps_responses(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_products_category ON products(category)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_products_seller ON products(seller_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_cart_user ON cart(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_orders_seller ON orders(seller_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_reviews_product ON reviews(product_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_products_name ON products(LOWER(name))")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_set_items_set ON product_set_items(set_id)")
        # Trigram index speeds up fuzzy (word_similarity) search.
        try:
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_products_name_trgm ON products USING gin (name gin_trgm_ops)")
        except Exception:
            pass

        # Product categories (2026-07-30) — used to be a hardcoded list in
        # locales.py; now admin-extensible from either admin panel (website
        # or the bot's own). `key` is the same slug products.category stores
        # (plain TEXT, no FK — matches how products already reference it).
        # Seeded once from the original hardcoded set so existing products
        # keep working; new ones the admin adds go straight in here.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id SERIAL PRIMARY KEY,
                key TEXT UNIQUE NOT NULL,
                name_uz TEXT NOT NULL,
                name_ru TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        count = await conn.fetchval("SELECT COUNT(*) FROM categories")
        if count == 0:
            await _seed_categories(conn)

        # Seed delivery zones if empty
        count = await conn.fetchval("SELECT COUNT(*) FROM delivery_zones")
        if count == 0:
            await _seed_delivery_zones(conn)

        # Expenses (Chiqimlar) table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS expenses (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                amount DOUBLE PRECISION NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ===== Aksiya / Bonus (2026-08-31) =====
        # An "aksiya" is a named, time-boxed campaign the owner writes up in
        # the admin panel and then explicitly starts. Only ONE can run at a
        # time — starting one deactivates the rest (see start_promotion) —
        # because the bot and Mini App both surface "the current aksiya" in a
        # single banner slot rather than a list.
        #
        # Nothing here changes anything for buyers until an admin presses
        # "Boshlash": rows are created inactive, so this table is safe to
        # deploy ahead of the first campaign.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS promotions (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                name_ru TEXT,
                conditions TEXT,
                conditions_ru TEXT,
                days INTEGER NOT NULL DEFAULT 7,
                image_url TEXT,
                active BOOLEAN NOT NULL DEFAULT FALSE,
                started_at TIMESTAMP,
                ends_at TIMESTAMP,
                announced_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # One row per bonus rule: "buy `trigger_quantity` of trigger_product
        # -> get `bonus_amount bonus_unit` of bonus_product free".
        #
        # Two quantity columns on purpose, because the display unit and the
        # stock unit are usually different: the owner writes "100 gr" but
        # Eritritol is stocked in kg, so bonus_amount/bonus_unit are what the
        # buyer reads ("100 gr") while bonus_stock_qty (0.1) is what actually
        # comes off products.quantity. See promotions.py::to_stock_qty for
        # the conversion — it's computed once at save time so a later unit
        # change on the product can't silently rewrite past orders.
        #
        # max_bonus_amount caps the multiplier ("3 kg -> 300 gr, but never
        # more than 500 gr"); NULL means uncapped.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS promotion_bonuses (
                id SERIAL PRIMARY KEY,
                promo_id INTEGER NOT NULL REFERENCES promotions(id) ON DELETE CASCADE,
                trigger_product_id INTEGER NOT NULL REFERENCES products(id),
                trigger_quantity DOUBLE PRECISION NOT NULL DEFAULT 1,
                bonus_product_id INTEGER NOT NULL REFERENCES products(id),
                bonus_amount DOUBLE PRECISION NOT NULL DEFAULT 1,
                bonus_unit TEXT NOT NULL DEFAULT 'gr',
                bonus_stock_qty DOUBLE PRECISION NOT NULL DEFAULT 0,
                max_bonus_amount DOUBLE PRECISION,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Daily "bugungi sovg'alar" showcase (owner request 2026-08-31): 3 bonus
        # rules a day, announced with a link straight to each product. The
        # cursor walks the rule list so every rule gets its turn instead of the
        # first three being announced forever; last_showcase_date is the
        # once-a-day guard (Tashkent date, so a restart can't double-send).
        for ddl in (
            "ALTER TABLE promotions ADD COLUMN showcase_enabled BOOLEAN NOT NULL DEFAULT TRUE",
            "ALTER TABLE promotions ADD COLUMN showcase_cursor INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE promotions ADD COLUMN last_showcase_date DATE",
        ):
            try:
                await conn.execute(ddl)
            except Exception:
                pass

        await conn.execute("CREATE INDEX IF NOT EXISTS idx_promo_bonuses_promo ON promotion_bonuses(promo_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_promo_bonuses_trigger ON promotion_bonuses(trigger_product_id)")
        # Partial unique index — the "only one active aksiya" rule enforced by
        # the database itself, not just by start_promotion's UPDATE order.
        await conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_promotions_single_active ON promotions((active)) WHERE active"
        )


async def close_db():
    """Close the connection pool"""
    global pool
    if pool:
        await pool.close()
        pool = None


# ===== USER OPERATIONS =====

async def get_user(user_id: int) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
        return dict(row) if row else None


async def create_user(user_id: int, username: str = None, full_name: str = None, language: str = "uz"):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (user_id, username, full_name, language) VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
            user_id, username, full_name, language
        )


async def update_user_language(user_id: int, language: str):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET language = $1 WHERE user_id = $2", language, user_id)


async def update_user_info(user_id: int, **kwargs):
    allowed_columns = {"username", "full_name", "phone", "address", "language", "is_seller", "payment_method"}
    async with pool.acquire() as conn:
        for key, value in kwargs.items():
            if key not in allowed_columns:
                raise ValueError(f"Invalid column for users: {key}")
            await conn.execute(f"UPDATE users SET {key} = $1 WHERE user_id = $2", value, user_id)


async def get_user_language(user_id: int) -> str:
    user = await get_user(user_id)
    return user["language"] if user else "uz"


async def set_user_as_seller(user_id: int):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET is_seller = 1 WHERE user_id = $1", user_id)


# ===== PRODUCT OPERATIONS =====

async def add_product(seller_id: int, name: str, description: str, price: float,
                      unit: str, quantity: float, category: str, photo_id: str = None,
                      name_ru: str = None, description_ru: str = None,
                      cost_price: float = 0) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO products (seller_id, name, description, price, unit, quantity, category, photo_id, name_ru, description_ru, cost_price)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) RETURNING id""",
            seller_id, name, description, price, unit, quantity, category, photo_id, name_ru, description_ru, cost_price
        )


async def get_products_by_category(category: str, page: int = 0, per_page: int = 5) -> tuple[list[dict], int]:
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM products WHERE category = $1 AND is_active = 1",
            category
        )
        rows = await conn.fetch(
            """SELECT p.*, u.full_name as seller_name, u.username as seller_username
               FROM products p
               JOIN users u ON p.seller_id = u.user_id
               WHERE p.category = $1 AND p.is_active = 1
               ORDER BY LOWER(p.name) ASC, p.id ASC
               LIMIT $2 OFFSET $3""",
            category, per_page, page * per_page
        )
        return [dict(r) for r in rows], total


async def get_discounted_products(page: int = 0, per_page: int = 5) -> tuple[list[dict], int]:
    """Active-discount products across all categories, for the bot's Discounts
    section. 'Active' mirrors active_discount(): percent > 0 and not expired
    (NULL discount_until = no expiry). Compared against naive UTC, same as the
    Python helper, so a parameter is passed rather than relying on NOW()."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    where = ("WHERE p.is_active = 1 AND COALESCE(p.discount_percent, 0) > 0 "
             "AND (p.discount_until IS NULL OR p.discount_until > $1)")
    async with pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT COUNT(*) FROM products p {where}", now)
        rows = await conn.fetch(
            f"""SELECT p.*, u.full_name as seller_name, u.username as seller_username
                FROM products p
                JOIN users u ON p.seller_id = u.user_id
                {where}
                ORDER BY LOWER(p.name) ASC, p.id ASC
                LIMIT $2 OFFSET $3""",
            now, per_page, page * per_page
        )
        return [dict(r) for r in rows], total


async def get_all_products_paginated(page: int = 0, per_page: int = 20) -> tuple[list[dict], int]:
    """Active products across every category, genuinely paginated (used by
    the catalog's "Hammasi/All" tab) — unlike get_top_ordered_products or
    the old ad-hoc per-category slice, this actually walks the whole table."""
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM products WHERE is_active = 1")
        rows = await conn.fetch(
            """SELECT p.*, u.full_name as seller_name, u.username as seller_username
               FROM products p
               JOIN users u ON p.seller_id = u.user_id
               WHERE p.is_active = 1
               ORDER BY LOWER(p.name) ASC, p.id ASC
               LIMIT $1 OFFSET $2""",
            per_page, page * per_page
        )
        return [dict(r) for r in rows], total


async def get_all_active_products() -> list[dict]:
    """All active products (lightweight) for the admin list-to-quote matcher.
    Not paginated — the catalog is small enough to match against in memory."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, name, name_ru, price, unit, quantity,
                      discount_percent, discount_until, seller_id
               FROM products WHERE is_active = 1"""
        )
        return [dict(r) for r in rows]


async def get_product(product_id: int) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT p.*, u.full_name as seller_name, u.username as seller_username
               FROM products p
               JOIN users u ON p.seller_id = u.user_id
               WHERE p.id = $1""",
            product_id
        )
        return dict(row) if row else None


async def get_seller_products(seller_id: int, all_products: bool = False) -> list[dict]:
    async with pool.acquire() as conn:
        if all_products:
            rows = await conn.fetch(
                "SELECT * FROM products WHERE is_active = 1 ORDER BY created_at DESC"
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM products WHERE seller_id = $1 AND is_active = 1 ORDER BY created_at DESC",
                seller_id
            )
        return [dict(r) for r in rows]


def active_discount(discount_percent: int | None, discount_until=None) -> int:
    """Return the discount percent if still in effect, else 0.
    discount_until is a naive UTC datetime or None (None = no expiry)."""
    if not discount_percent:
        return 0
    if discount_until is not None:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if discount_until < now:
            return 0
    return discount_percent


def effective_price(price: float, discount_percent: int | None, discount_until=None) -> float:
    """Apply percentage discount to a price (respecting expiry). Returns price the buyer pays."""
    d = active_discount(discount_percent, discount_until)
    if not d:
        return price
    return price * (100 - d) / 100


async def count_active_products_in_category(category: str) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM products WHERE category = $1 AND is_active = 1",
            category,
        )


async def bulk_set_category_discount(category: str, discount_percent: int,
                                     discount_until=None) -> int:
    """Apply (or clear) a discount to every active product in a category.
    Single SQL UPDATE — atomic and fast. Returns the number of rows updated.
    Pass discount_percent=0 to clear (also clears discount_until)."""
    if discount_percent < 0 or discount_percent > 100:
        raise ValueError("discount_percent must be between 0 and 100")
    async with pool.acquire() as conn:
        if discount_percent == 0:
            result = await conn.execute(
                """UPDATE products
                   SET discount_percent = 0, discount_until = NULL
                   WHERE category = $1 AND is_active = 1""",
                category,
            )
        else:
            result = await conn.execute(
                """UPDATE products
                   SET discount_percent = $1, discount_until = $2
                   WHERE category = $3 AND is_active = 1""",
                discount_percent, discount_until, category,
            )
        # asyncpg returns "UPDATE <n>"
        try:
            return int(result.split()[-1])
        except (ValueError, IndexError):
            return 0


async def update_product(product_id: int, **kwargs):
    allowed_columns = {"name", "description", "price", "unit", "quantity", "category", "photo_id", "is_active", "name_ru", "description_ru", "discount_percent", "discount_until", "low_stock_threshold", "cost_price", "image_url"}
    async with pool.acquire() as conn:
        for key, value in kwargs.items():
            if key not in allowed_columns:
                raise ValueError(f"Invalid column for products: {key}")
            await conn.execute(f"UPDATE products SET {key} = $1 WHERE id = $2", value, product_id)


async def add_product_media(product_id: int, file_id: str, media_type: str = "photo") -> int:
    async with pool.acquire() as conn:
        sort_order = await conn.fetchval(
            "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM product_media WHERE product_id = $1",
            product_id
        )
        return await conn.fetchval(
            "INSERT INTO product_media (product_id, file_id, media_type, sort_order) VALUES ($1, $2, $3, $4) RETURNING id",
            product_id, file_id, media_type, sort_order
        )


async def get_product_media(product_id: int) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM product_media WHERE product_id = $1 ORDER BY sort_order",
            product_id
        )
        return [dict(r) for r in rows]


async def delete_product_media(media_id: int):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM product_media WHERE id = $1", media_id)


async def delete_product(product_id: int):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE products SET is_active = 0 WHERE id = $1", product_id)


async def reduce_product_quantity(product_id: int, amount: float):
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE products SET quantity = GREATEST(0, quantity - $1) WHERE id = $2",
            amount, product_id
        )



# ===== CART OPERATIONS =====

async def add_to_cart(user_id: int, product_id: int = None, quantity: float = 1, set_id: int = None):
    async with pool.acquire() as conn:
        if set_id is not None:
            existing = await conn.fetchrow(
                "SELECT id, quantity FROM cart WHERE user_id = $1 AND set_id = $2",
                user_id, set_id
            )
            if existing:
                await conn.execute("UPDATE cart SET quantity = quantity + $1 WHERE id = $2", quantity, existing["id"])
            else:
                await conn.execute("INSERT INTO cart (user_id, set_id, quantity) VALUES ($1, $2, $3)", user_id, set_id, quantity)
        else:
            existing = await conn.fetchrow(
                "SELECT id, quantity FROM cart WHERE user_id = $1 AND product_id = $2",
                user_id, product_id
            )
            if existing:
                await conn.execute("UPDATE cart SET quantity = quantity + $1 WHERE id = $2", quantity, existing["id"])
            else:
                await conn.execute("INSERT INTO cart (user_id, product_id, quantity) VALUES ($1, $2, $3)", user_id, product_id, quantity)


async def get_cart_line_for_product(user_id: int, product_id: int) -> tuple[int | None, float]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, quantity FROM cart WHERE user_id = $1 AND product_id = $2", user_id, product_id)
        return (row["id"], row["quantity"]) if row else (None, 0.0)

async def get_cart_line_for_set(user_id: int, set_id: int) -> tuple[int | None, float]:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, quantity FROM cart WHERE user_id = $1 AND set_id = $2", user_id, set_id)
        return (row["id"], row["quantity"]) if row else (None, 0.0)

async def set_cart_product_quantity(user_id: int, product_id: int = None, quantity: float = 1, set_id: int = None):
    async with pool.acquire() as conn:
        if set_id is not None:
            existing = await conn.fetchrow("SELECT id FROM cart WHERE user_id = $1 AND set_id = $2", user_id, set_id)
            if existing:
                await conn.execute("UPDATE cart SET quantity = $1 WHERE id = $2", quantity, existing["id"])
            else:
                await conn.execute("INSERT INTO cart (user_id, set_id, quantity) VALUES ($1, $2, $3)", user_id, set_id, quantity)
        else:
            existing = await conn.fetchrow("SELECT id FROM cart WHERE user_id = $1 AND product_id = $2", user_id, product_id)
            if existing:
                await conn.execute("UPDATE cart SET quantity = $1 WHERE id = $2", quantity, existing["id"])
            else:
                await conn.execute("INSERT INTO cart (user_id, product_id, quantity) VALUES ($1, $2, $3)", user_id, product_id, quantity)

async def get_cart(user_id: int) -> list[dict]:
    async with pool.acquire() as conn:
        # fetch products
        prod_rows = await conn.fetch(
            """SELECT c.id as cart_id, c.quantity as cart_quantity, c.set_id,
                      p.id as product_id, p.name, p.name_ru, p.price, p.unit, p.seller_id, p.photo_id,
                      COALESCE(p.quantity, 0) as stock,
                      COALESCE(p.discount_percent, 0) as discount_percent,
                      p.discount_until as discount_until
               FROM cart c
               JOIN products p ON c.product_id = p.id
               WHERE c.user_id = $1 AND p.is_active = 1""", user_id)
        
        # fetch sets
        set_rows = await conn.fetch(
            """SELECT c.id as cart_id, c.quantity as cart_quantity, c.set_id,
                      s.name, s.name_ru, s.set_price as price, s.image_url as photo_id
               FROM cart c
               JOIN product_sets s ON c.set_id = s.id
               WHERE c.user_id = $1 AND s.is_active = 1""", user_id)
               
        result = [dict(r) for r in prod_rows]
        for r in set_rows:
            d = dict(r)
            d["is_set"] = True
            d["unit"] = "piece" # sets are treated as piece
            d["stock"] = 999 # Sets are assumed available as long as items are, actual check is on order
            d["discount_percent"] = 0
            d["discount_until"] = None
            d["seller_id"] = None
            result.append(d)
        
        return sorted(result, key=lambda x: x["cart_id"])

async def clear_cart(user_id: int):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM cart WHERE user_id = $1", user_id)

async def remove_from_cart(cart_id: int):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM cart WHERE id = $1", cart_id)

async def set_cart_quantity(cart_id: int, quantity: float) -> None:
    async with pool.acquire() as conn:
        await conn.execute("UPDATE cart SET quantity = $1 WHERE id = $2", quantity, cart_id)

async def get_cart_item(cart_id: int) -> dict | None:
    async with pool.acquire() as conn:
        prod = await conn.fetchrow(
            """SELECT c.id as cart_id, c.user_id, c.quantity as cart_quantity,
                      p.id as product_id, p.unit, COALESCE(p.quantity, 0) as stock
               FROM cart c JOIN products p ON c.product_id = p.id WHERE c.id = $1""", cart_id)
        if prod: return dict(prod)
        
        st = await conn.fetchrow(
            """SELECT c.id as cart_id, c.user_id, c.quantity as cart_quantity, c.set_id,
                      'piece' as unit, 999 as stock
               FROM cart c JOIN product_sets s ON c.set_id = s.id WHERE c.id = $1""", cart_id)
        if st:
            d = dict(st)
            d["is_set"] = True
            return d
        return None

async def get_user_delivered_order_count(user_id: int) -> int:
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            """SELECT COUNT(*) FROM orders
               WHERE user_id = $1 AND status = 'delivered'
                 AND COALESCE(source, 'bot') <> 'manual'""", user_id)
        return count or 0

async def get_cart_count(user_id: int) -> int:
    async with pool.acquire() as conn:
        # count products + sets
        pc = await conn.fetchval("SELECT COUNT(*) FROM cart c JOIN products p ON c.product_id = p.id WHERE c.user_id = $1 AND p.is_active = 1", user_id)
        sc = await conn.fetchval("SELECT COUNT(*) FROM cart c JOIN product_sets s ON c.set_id = s.id WHERE c.user_id = $1 AND s.is_active = 1", user_id)
        return (pc or 0) + (sc or 0)

async def get_cart_total(user_id: int) -> float:
    cart = await get_cart(user_id)
    def price(item):
        if item.get("is_set"): return float(item["price"])
        from database import effective_price
        return effective_price(item["price"], item.get("discount_percent"), item.get("discount_until"))
    return sum(price(item) * item["cart_quantity"] for item in cart)


# ===== ORDER OPERATIONS =====

class InsufficientStockError(Exception):
    """Raised when an order can't be placed because a product's stock dropped
    below the requested quantity between cart view and checkout."""
    def __init__(self, product_id: int, requested: float, available: float):
        self.product_id = product_id
        self.requested = requested
        self.available = available
        super().__init__(
            f"Insufficient stock for product {product_id}: "
            f"requested {requested}, available {available}"
        )


class InsufficientKetoError(Exception):
    """Raised when a checkout requests more Keto-as-discount than the buyer's
    current balance actually covers (balance can shift between the buyer
    opening the confirm screen and tapping "place order")."""
    def __init__(self, requested: int, available: int):
        self.requested = requested
        self.available = available
        super().__init__(f"Insufficient Keto balance: requested {requested}, available {available}")



async def create_order(user_id: int, customer_name: str, phone: str, address: str,
                       items: list[dict], total: float, payment_method: str = "cash",
                       latitude: float = None, longitude: float = None,
                       delivery_method: str | None = None,
                       address_note: str | None = None,
                       secondary_phone: str | None = None,
                       keto_redeem: int = 0) -> tuple[int, list[dict]]:
    if not items:
        raise ValueError("Cannot create order with empty items")
    seller_id = items[0].get("seller_id")
    keto_redeem = int(keto_redeem or 0)
    if keto_redeem < 0:
        raise ValueError("keto_redeem cannot be negative")

    from config import LOW_STOCK_THRESHOLD
    global_threshold = LOW_STOCK_THRESHOLD
    low_stock: list[dict] = []

    async with pool.acquire() as conn:
        async with conn.transaction():
            for item in items:
                qty = item["quantity"]
                if item.get("is_bonus"):
                    # Free aksiya bonus (see promotions.py) — decrement stock
                    # best-effort and NEVER block the order on it. A paid
                    # order must not fail because the giveaway item ran out;
                    # the admin sees the bonus line in the order notification
                    # either way and can substitute or drop it while packing.
                    await conn.execute(
                        "UPDATE products SET quantity = GREATEST(quantity - $1, 0) WHERE id = $2",
                        float(item.get("stock_quantity") or 0), item.get("product_id"),
                    )
                    continue
                if item.get("is_set"):
                    set_id = item.get("set_id") or item.get("product_id") or item.get("id")
                    set_items = await conn.fetch("SELECT product_id, quantity FROM product_set_items WHERE set_id = $1", set_id)
                    for si in set_items:
                        spid = si["product_id"]
                        sqty = float(si["quantity"]) * float(qty)
                        row = await conn.fetchrow(
                            """UPDATE products SET quantity = quantity - $1
                               WHERE id = $2 AND quantity >= $1
                               RETURNING quantity, name, low_stock_threshold""",
                            sqty, spid,
                        )
                        if row is None:
                            available = await conn.fetchval("SELECT quantity FROM products WHERE id = $1", spid)
                            raise InsufficientStockError(spid, sqty, available or 0)

                        new_qty = float(row["quantity"])
                        old_qty = new_qty + float(sqty)
                        threshold = row["low_stock_threshold"] if row["low_stock_threshold"] is not None else global_threshold
                        if old_qty > threshold >= new_qty:
                            low_stock.append({"product_id": spid, "name": row["name"], "quantity": new_qty})
                else:
                    pid = item.get("product_id") or item.get("id")
                    row = await conn.fetchrow(
                        """UPDATE products SET quantity = quantity - $1
                           WHERE id = $2 AND quantity >= $1
                           RETURNING quantity, name, low_stock_threshold""",
                        qty, pid,
                    )
                    if row is None:
                        available = await conn.fetchval("SELECT quantity FROM products WHERE id = $1", pid)
                        raise InsufficientStockError(pid, qty, available or 0)

                    new_qty = float(row["quantity"])
                    old_qty = new_qty + float(qty)
                    threshold = row["low_stock_threshold"] if row["low_stock_threshold"] is not None else global_threshold
                    if old_qty > threshold >= new_qty:
                        low_stock.append({"product_id": pid, "name": row["name"], "quantity": new_qty})

            if keto_redeem > 0:
                balance = await conn.fetchval("SELECT keto_balance FROM users WHERE user_id = $1 FOR UPDATE", user_id)
                if balance is None or balance < keto_redeem:
                    raise InsufficientKetoError(keto_redeem, int(balance or 0))

            import json
            order_id = await conn.fetchval(
                """INSERT INTO orders (user_id, seller_id, customer_name, phone, address, items, total, payment_method, latitude, longitude, delivery_method, address_note, secondary_phone, keto_redeemed)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14) RETURNING id""",
                user_id, seller_id, customer_name, phone, address, json.dumps(items, ensure_ascii=False), total, payment_method,
                latitude, longitude, delivery_method, address_note, secondary_phone, keto_redeem
            )

            if keto_redeem > 0:
                await conn.execute("INSERT INTO keto_ledger (user_id, order_id, amount, kind, note) VALUES ($1, $2, $3, 'redeem', $4)", user_id, order_id, -keto_redeem, f"Buyurtma #{order_id} uchun chegirma")
                await conn.execute("UPDATE users SET keto_balance = keto_balance - $1 WHERE user_id = $2", keto_redeem, user_id)

            await conn.execute("DELETE FROM cart WHERE user_id = $1", user_id)

    return order_id, low_stock


async def get_user_orders(user_id: int) -> list[dict]:
    """Buyer's own order history. Excludes manual entries — those are rows
    that the admin keyed in for offline orders, attached to the admin's
    user_id but representing someone else's purchase."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT * FROM orders
               WHERE user_id = $1 AND COALESCE(source, 'bot') <> 'manual'
               ORDER BY created_at DESC LIMIT 20""",
            user_id
        )
        return [dict(r) for r in rows]


async def add_manual_order(admin_user_id: int, customer_name: str, phone: str,
                            address: str, items_data: list[dict], total: float,
                            payment_method: str, delivery_method: str | None,
                            status: str, address_note: str | None = None) -> int:
    """Insert an admin-entered offline order.

    items_data is a list of {product_id, name, quantity, price, unit} dicts —
    same shape as bot/Mini App orders, so per-product analytics (top
    products, items-per-buyer, etc.) include manual sales too.

    Stock is *not* decremented: the admin already fulfilled it physically and
    presumably reflected that in their inventory. If they want stock to drop,
    they can edit the product quantity manually.
    """
    async with pool.acquire() as conn:
        order_id = await conn.fetchval(
            """INSERT INTO orders (user_id, customer_name, phone, address, items, total,
                                    payment_method, delivery_method, address_note, status,
                                    source, confirmed_at, shipped_at, delivered_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'manual',
                       CASE WHEN $10 IN ('confirmed','shipped','delivered') THEN CURRENT_TIMESTAMP END,
                       CASE WHEN $10 IN ('shipped','delivered')             THEN CURRENT_TIMESTAMP END,
                       CASE WHEN $10 = 'delivered'                          THEN CURRENT_TIMESTAMP END)
               RETURNING id""",
            admin_user_id, customer_name, phone, address,
            json.dumps(items_data, ensure_ascii=False), total,
            payment_method, delivery_method, address_note, status,
        )
        return order_id


async def add_b2b_order(admin_user_id: int, company_name: str,
                         items_data: list[dict], total: float) -> int:
    """Insert an admin-entered B2B (wholesale/company) sale.

    Lives in the same orders table as manual orders (source='b2b') so it
    feeds the same items-based analytics, but has no phone/address/delivery —
    a B2B sale is a company-to-company transaction the admin is just logging
    for the books, not something Ketoshop couriers deliver. Always recorded
    as already 'delivered' for the same reason. Excluded from top-products /
    top-active-customer analytics the same way manual test orders are, since
    `user_id` here is the admin who logged it, not the buyer (see
    LEADERBOARD_EXCLUDED_USER_IDS) — but counted in get_admin_stats' revenue
    and broken out separately as b2b_revenue/b2b_orders.
    """
    async with pool.acquire() as conn:
        order_id = await conn.fetchval(
            """INSERT INTO orders (user_id, customer_name, items, total, status,
                                    source, confirmed_at, shipped_at, delivered_at)
               VALUES ($1, $2, $3, $4, 'delivered', 'b2b',
                       CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
               RETURNING id""",
            admin_user_id, company_name,
            json.dumps(items_data, ensure_ascii=False), total,
        )
        return order_id

async def add_b2b_eritritol_order(admin_user_id: int, address: str, phone: str, 
                                 quantity: float, total: float) -> int:
    """Insert an admin-entered B2B Eritritol wholesale sale."""
    async with pool.acquire() as conn:
        items_data = [{
            "id": -1, # Using a dummy ID or Eritritol product ID if possible, but let's just save the name
            "name": "Eritritol (B2B)",
            "quantity": quantity,
            "price": round(total / quantity, 2) if quantity else 0,
            "unit": "kg"
        }]
        
        order_id = await conn.fetchval(
            """INSERT INTO orders (user_id, customer_name, address, phone, items, total, status,
                                    source, confirmed_at, shipped_at, delivered_at)
               VALUES ($1, 'B2B Eritritol', $2, $3, $4, $5, 'delivered', 'b2b',
                       CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
               RETURNING id""",
            admin_user_id, address, phone,
            json.dumps(items_data, ensure_ascii=False), total,
        )
        return order_id


async def get_seller_orders(seller_id: int, all_orders: bool = False) -> list[dict]:
    async with pool.acquire() as conn:
        if all_orders:
            rows = await conn.fetch(
                "SELECT * FROM orders ORDER BY created_at DESC LIMIT 20"
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM orders WHERE seller_id = $1 ORDER BY created_at DESC LIMIT 20",
                seller_id
            )
        return [dict(r) for r in rows]


async def get_order(order_id: int) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM orders WHERE id = $1", order_id)
        return dict(row) if row else None


async def update_order_status(order_id: int, status: str):
    """Update order status and stamp the matching lifecycle timestamp the first
    time the order reaches that state (idempotent — won't overwrite an existing
    stamp, so e.g. confirmed → cancelled → confirmed keeps the original time)."""
    async with pool.acquire() as conn:
        if status == "confirmed":
            await conn.execute(
                "UPDATE orders SET status = $1, confirmed_at = COALESCE(confirmed_at, CURRENT_TIMESTAMP) WHERE id = $2",
                status, order_id,
            )
        elif status == "shipped":
            await conn.execute(
                "UPDATE orders SET status = $1, shipped_at = COALESCE(shipped_at, CURRENT_TIMESTAMP) WHERE id = $2",
                status, order_id,
            )
        elif status == "delivered":
            await conn.execute(
                "UPDATE orders SET status = $1, delivered_at = COALESCE(delivered_at, CURRENT_TIMESTAMP) WHERE id = $2",
                status, order_id,
            )
        else:
            await conn.execute("UPDATE orders SET status = $1 WHERE id = $2", status, order_id)


async def transition_order_status(order_id: int, expected_from: str, new_status: str) -> bool:
    """Atomic state transition guarded by the current status. Returns True if
    the row was at `expected_from` and got updated, False otherwise. Used to
    stop two admins from each running the full confirm/ship/deliver flow when
    they tap at the same time — only one transition wins; the loser sees a
    'already done' toast."""
    async with pool.acquire() as conn:
        if new_status == "confirmed":
            row = await conn.fetchrow(
                "UPDATE orders SET status=$1, confirmed_at=COALESCE(confirmed_at, CURRENT_TIMESTAMP) "
                "WHERE id=$2 AND status=$3 RETURNING id",
                new_status, order_id, expected_from,
            )
        elif new_status == "shipped":
            row = await conn.fetchrow(
                "UPDATE orders SET status=$1, shipped_at=COALESCE(shipped_at, CURRENT_TIMESTAMP) "
                "WHERE id=$2 AND status=$3 RETURNING id",
                new_status, order_id, expected_from,
            )
        elif new_status == "delivered":
            row = await conn.fetchrow(
                "UPDATE orders SET status=$1, delivered_at=COALESCE(delivered_at, CURRENT_TIMESTAMP) "
                "WHERE id=$2 AND status=$3 RETURNING id",
                new_status, order_id, expected_from,
            )
        else:
            row = await conn.fetchrow(
                "UPDATE orders SET status=$1 WHERE id=$2 AND status=$3 RETURNING id",
                new_status, order_id, expected_from,
            )
        return row is not None


async def set_order_cheque(order_id: int, file_id: str, cheque_type: str = "photo"):
    """Persist the payment cheque file_id so the order card can show it later."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE orders SET cheque_file_id = $1, cheque_type = $2 WHERE id = $3",
            file_id, cheque_type, order_id,
        )


async def _seed_delivery_zones(conn):
    """Seed delivery zones with major Uzbekistan cities"""
    cities = [
        ("Toshkent", "Ташкент", 15000, 500000, "1"),
        ("Toshkent viloyati", "Ташкентская область", 25000, 500000, "1-2"),
        ("Samarqand", "Самарканд", 35000, 700000, "2-3"),
        ("Buxoro", "Бухара", 40000, 700000, "2-3"),
        ("Namangan", "Наманган", 35000, 700000, "2-3"),
        ("Andijon", "Андижан", 35000, 700000, "2-3"),
        ("Farg'ona", "Фергана", 35000, 700000, "2-3"),
        ("Navoiy", "Навои", 40000, 800000, "2-3"),
        ("Qarshi", "Карши", 40000, 800000, "2-3"),
        ("Nukus", "Нукус", 50000, 1000000, "3-4"),
        ("Urganch", "Ургенч", 45000, 900000, "3-4"),
        ("Xiva", "Хива", 45000, 900000, "3-4"),
        ("Termiz", "Термез", 45000, 900000, "3-4"),
        ("Jizzax", "Джизак", 30000, 600000, "2"),
        ("Guliston", "Гулистан", 30000, 600000, "2"),
        ("Chirchiq", "Чирчик", 20000, 500000, "1"),
        ("Olmaliq", "Алмалык", 25000, 500000, "1-2"),
        ("Angren", "Ангрен", 25000, 500000, "1-2"),
        ("Kokand", "Коканд", 35000, 700000, "2-3"),
        ("Marg'ilon", "Маргилан", 35000, 700000, "2-3"),
    ]
    for city in cities:
        await conn.execute(
            """INSERT INTO delivery_zones (city_name_uz, city_name_ru, price, min_free_delivery, estimated_days)
               VALUES ($1, $2, $3, $4, $5)""",
            *city
        )


async def _seed_categories(conn):
    """One-time copy of the original hardcoded category list (locales.py) into
    the new admin-manageable table, so existing products' category values
    keep resolving to the same labels they always have."""
    import locales
    for i, key in enumerate(locales.CATEGORIES):
        entry = locales.TEXTS.get(f"cat_{key}", {})
        name_uz = entry.get("uz", key)
        name_ru = entry.get("ru", name_uz)
        await conn.execute(
            "INSERT INTO categories (key, name_uz, name_ru, sort_order) VALUES ($1, $2, $3, $4) "
            "ON CONFLICT (key) DO NOTHING",
            key, name_uz, name_ru, i,
        )


# ===== CATEGORIES =====

async def get_categories(active_only: bool = True) -> list[dict]:
    async with pool.acquire() as conn:
        where = "WHERE is_active = 1" if active_only else ""
        rows = await conn.fetch(f"SELECT * FROM categories {where} ORDER BY sort_order, id")
        return [dict(r) for r in rows]


def _slugify_category_key(text: str) -> str:
    """'🥩 Go'sht mahsulotlari' -> 'gosht_mahsulotlari' — strips emoji/
    punctuation, lowercases, spaces to underscores. Falls back to a generic
    stem if the name is emoji-only or otherwise has no ASCII letters."""
    import re
    ascii_only = re.sub(r"[^a-zA-Z0-9\s]", "", text).strip().lower()
    slug = re.sub(r"\s+", "_", ascii_only)
    return slug or "category"


async def create_category(name_uz: str, name_ru: str | None = None, key: str | None = None) -> dict:
    """Auto-slugs `key` from name_uz when not given, retrying with a numeric
    suffix on collision — callers never need to think about uniqueness."""
    async with pool.acquire() as conn:
        base_key = key or _slugify_category_key(name_uz)
        candidate = base_key
        suffix = 2
        while await conn.fetchval("SELECT 1 FROM categories WHERE key = $1", candidate):
            candidate = f"{base_key}_{suffix}"
            suffix += 1

        max_sort = await conn.fetchval("SELECT COALESCE(MAX(sort_order), -1) FROM categories")
        row = await conn.fetchrow(
            "INSERT INTO categories (key, name_uz, name_ru, sort_order) VALUES ($1, $2, $3, $4) RETURNING *",
            candidate, name_uz, name_ru or name_uz, max_sort + 1,
        )
    import locales
    locales.register_category(row["key"], row["name_uz"], row["name_ru"])
    return dict(row)


async def sync_categories_to_locales() -> None:
    """Called at startup (after init_db) so locales.CATEGORIES/TEXTS — which
    every category_name/keyboard call site reads synchronously — reflect
    the DB: names (including ones an admin added in a previous run) AND
    ordering (sort_order), every time this runs. create_category() keeps
    names in sync live after that; move_category_to_top() re-runs this
    fully so a reorder also takes effect without a restart."""
    import locales
    cats = await get_categories(active_only=True)
    for cat in cats:
        locales.register_category(cat["key"], cat["name_uz"], cat["name_ru"])
    locales.reorder_categories([c["key"] for c in cats])


async def move_category_to_top(key: str) -> None:
    """Bumps `key` above every other category (owner request 2026-07-30 —
    a newly-added category showed up at the bottom of the homepage tabs)."""
    async with pool.acquire() as conn:
        min_sort = await conn.fetchval("SELECT COALESCE(MIN(sort_order), 0) FROM categories")
        await conn.execute("UPDATE categories SET sort_order = $1 WHERE key = $2", min_sort - 1, key)
    await sync_categories_to_locales()


# ===== SEARCH =====

# Trigram word-similarity cutoff. 0.3 catches typos like "aluloza"→"Alluloza"
# and "eritrol"→"Eritritol" without dragging in unrelated products.
SEARCH_SIMILARITY = 0.3


async def search_products(query: str, page: int = 0, per_page: int = 5) -> tuple[list[dict], int]:
    """Typo-tolerant product search.

    Matches by substring (ILIKE) first, then by pg_trgm word-similarity so a
    misspelled query still returns the nearest-named products. Results are
    ordered exact-substring-first, then by closeness. Falls back to plain
    substring search if pg_trgm is unavailable.
    """
    async with pool.acquire() as conn:
        search_term = f"%{query}%"
        try:
            where = """p.is_active = 1
                   AND (p.name ILIKE $1 OR p.description ILIKE $1
                        OR word_similarity($2, p.name) > $3)"""
            total = await conn.fetchval(
                f"SELECT COUNT(*) FROM products p WHERE {where}",
                search_term, query, SEARCH_SIMILARITY,
            )
            rows = await conn.fetch(
                f"""SELECT p.*, u.full_name as seller_name, u.username as seller_username
                   FROM products p
                   JOIN users u ON p.seller_id = u.user_id
                   WHERE {where}
                   ORDER BY (p.name ILIKE $1) DESC,
                            word_similarity($2, p.name) DESC,
                            LOWER(p.name) ASC, p.id ASC
                   LIMIT $4 OFFSET $5""",
                search_term, query, SEARCH_SIMILARITY, per_page, page * per_page,
            )
            return [dict(r) for r in rows], total
        except Exception:
            # pg_trgm not available — fall back to plain substring search.
            total = await conn.fetchval(
                """SELECT COUNT(*) FROM products
                   WHERE is_active = 1 AND (name ILIKE $1 OR description ILIKE $1)""",
                search_term,
            )
            rows = await conn.fetch(
                """SELECT p.*, u.full_name as seller_name, u.username as seller_username
                   FROM products p
                   JOIN users u ON p.seller_id = u.user_id
                   WHERE p.is_active = 1 AND (p.name ILIKE $1 OR p.description ILIKE $1)
                   ORDER BY LOWER(p.name) ASC, p.id ASC
                   LIMIT $2 OFFSET $3""",
                search_term, per_page, page * per_page,
            )
            return [dict(r) for r in rows], total


# ===== REVIEWS =====

async def add_review(user_id: int, product_id: int, rating: int, comment: str = None, order_id: int = None):
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO reviews (user_id, product_id, order_id, rating, comment)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT (user_id, product_id) DO UPDATE SET rating = $4, comment = $5, order_id = $3""",
            user_id, product_id, order_id, rating, comment
        )


async def get_product_reviews(product_id: int) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT r.*, u.full_name, u.username
               FROM reviews r
               JOIN users u ON r.user_id = u.user_id
               WHERE r.product_id = $1
               ORDER BY r.created_at DESC LIMIT 20""",
            product_id
        )
        return [dict(r) for r in rows]


async def get_product_rating(product_id: int) -> tuple[float, int]:
    """Returns (average_rating, review_count). Cast to float — asyncpg
    returns Decimal for NUMERIC, which json.dumps can't serialize, and
    the Mini App's /api/product/{id} response goes through json.dumps."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT COALESCE(AVG(rating), 0) as avg_r, COUNT(*) as cnt FROM reviews WHERE product_id = $1",
            product_id
        )
        return round(float(row["avg_r"]), 1), int(row["cnt"])


async def delete_review(review_id: int) -> bool:
    """Admin moderation (owner request 2026-07-30, website reviews). Returns
    False if the review was already gone."""
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM reviews WHERE id = $1", review_id)
        return result != "DELETE 0"


async def get_user_review(user_id: int, product_id: int) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM reviews WHERE user_id = $1 AND product_id = $2", user_id, product_id
        )
        return dict(row) if row else None


async def has_user_reviewed(user_id: int, product_id: int) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM reviews WHERE user_id = $1 AND product_id = $2",
            user_id, product_id
        )
        return row is not None


async def has_user_purchased(user_id: int, product_id: int) -> bool:
    """Check if user has a delivered order containing this product"""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT items FROM orders WHERE user_id = $1 AND status = 'delivered'",
            user_id
        )
        for row in rows:
            items = json.loads(row["items"]) if isinstance(row["items"], str) else row["items"]
            for item in items:
                if item.get("product_id") == product_id:
                    return True
        return False


# ===== DELIVERY ZONES =====

async def get_delivery_zones(active_only: bool = True) -> list[dict]:
    async with pool.acquire() as conn:
        query = "SELECT * FROM delivery_zones"
        if active_only:
            query += " WHERE is_active = 1"
        query += " ORDER BY price ASC"
        rows = await conn.fetch(query)
        return [dict(r) for r in rows]


async def get_delivery_zone(zone_id: int) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM delivery_zones WHERE id = $1", zone_id)
        return dict(row) if row else None


async def update_delivery_zone(zone_id: int, **kwargs):
    allowed_columns = {"city_name_uz", "city_name_ru", "price", "min_free_delivery", "estimated_days", "is_active"}
    async with pool.acquire() as conn:
        for key, value in kwargs.items():
            if key not in allowed_columns:
                raise ValueError(f"Invalid column for delivery_zones: {key}")
            await conn.execute(f"UPDATE delivery_zones SET {key} = $1 WHERE id = $2", value, zone_id)


async def add_delivery_zone(city_uz: str, city_ru: str, price: float, min_free: float = 0, days: str = "2-3") -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO delivery_zones (city_name_uz, city_name_ru, price, min_free_delivery, estimated_days)
               VALUES ($1, $2, $3, $4, $5) RETURNING id""",
            city_uz, city_ru, price, min_free, days
        )


# ===== ADMIN =====

async def get_all_users(page: int = 0, per_page: int = 20) -> tuple[list[dict], int]:
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM users")
        rows = await conn.fetch(
            "SELECT * FROM users ORDER BY created_at DESC LIMIT $1 OFFSET $2",
            per_page, page * per_page
        )
        return [dict(r) for r in rows], total


async def get_order_counts_by_status() -> dict[str, int]:
    """Return a {status: count} map for all orders. Used to badge the
    admin filter menu so the operator can see workload at a glance
    without having to open each filter."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT status, COUNT(*) AS n FROM orders GROUP BY status"
        )
        counts = {r["status"]: int(r["n"]) for r in rows}
        counts["all"] = sum(counts.values())
        return counts


async def get_all_orders(page: int = 0, per_page: int = 20, status: str = None) -> tuple[list[dict], int]:
    async with pool.acquire() as conn:
        if status:
            total = await conn.fetchval("SELECT COUNT(*) FROM orders WHERE status = $1", status)
            rows = await conn.fetch(
                "SELECT * FROM orders WHERE status = $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3",
                status, per_page, page * per_page
            )
        else:
            total = await conn.fetchval("SELECT COUNT(*) FROM orders")
            rows = await conn.fetch(
                "SELECT * FROM orders ORDER BY created_at DESC LIMIT $1 OFFSET $2",
                per_page, page * per_page
            )
        return [dict(r) for r in rows], total


async def get_all_products(page: int = 0, per_page: int = 20) -> tuple[list[dict], int]:
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM products WHERE is_active = 1")
        rows = await conn.fetch(
            """SELECT p.*, u.full_name as seller_name
               FROM products p JOIN users u ON p.seller_id = u.user_id
               WHERE p.is_active = 1
               ORDER BY p.created_at DESC LIMIT $1 OFFSET $2""",
            per_page, page * per_page
        )
        return [dict(r) for r in rows], total


def _period_start(period: str):
    """Translate a period label into a UTC-naive cutoff datetime, or None for all-time.

    created_at columns are naive UTC, but "today" must mean the local
    (Asia/Tashkent, DISPLAY_TZ_OFFSET_HOURS) calendar day — not the UTC one.
    Flooring in UTC directly would, for the first DISPLAY_TZ_OFFSET_HOURS
    hours of each local day, count almost all of the previous local day too.
    """
    from datetime import datetime, timedelta, timezone
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    if period == "today":
        now_local = now_utc + timedelta(hours=DISPLAY_TZ_OFFSET_HOURS)
        local_midnight = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        return local_midnight - timedelta(hours=DISPLAY_TZ_OFFSET_HOURS)
    if period == "7d":
        return now_utc - timedelta(days=7)
    if period == "30d":
        return now_utc - timedelta(days=30)
    return None  # all-time



def _period_range(period: str | dict):
    from datetime import datetime, timedelta, timezone
    if isinstance(period, dict):
        try:
            start = datetime.fromisoformat(period["start"])
            end = datetime.fromisoformat(period["end"]) + timedelta(days=1) - timedelta(microseconds=1)
            # user provides local time, convert to naive UTC for DB
            start = start - timedelta(hours=DISPLAY_TZ_OFFSET_HOURS)
            end = end - timedelta(hours=DISPLAY_TZ_OFFSET_HOURS)
            return start, end
        except Exception:
            pass
    return _period_start(period), None

async def get_admin_stats(period: str | dict = "all") -> dict:
    start_time, end_time = _period_range(period)
    
    async with pool.acquire() as conn:
        users_total = await conn.fetchval("SELECT COUNT(*) FROM users")
        reviews_total = await conn.fetchval("SELECT COUNT(*) FROM reviews")
        
        where_time = ""
        args = []
        if start_time and end_time:
            where_time = " WHERE created_at >= $1 AND created_at <= $2"
            args = [start_time, end_time]
        elif start_time:
            where_time = " WHERE created_at >= $1"
            args = [start_time]
            
        if not where_time:
            users_new = users_total
            reviews_new = reviews_total
        else:
            users_new = await conn.fetchval(f"SELECT COUNT(*) FROM users{where_time}", *args)
            reviews_new = await conn.fetchval(f"SELECT COUNT(*) FROM reviews{where_time}", *args)
            
        products_active = await conn.fetchval("SELECT COUNT(*) FROM products WHERE is_active = 1")
        products_in_stock = await conn.fetchval("SELECT COUNT(*) FROM products WHERE is_active = 1 AND quantity > 0")

        async def count_status(status: str | None) -> int:
            q = "SELECT COUNT(*) FROM orders"
            w = []
            a = []
            if status:
                w.append("status = $1")
                a.append(status)
            if start_time:
                w.append(f"created_at >= ${len(a)+1}")
                a.append(start_time)
            if end_time:
                w.append(f"created_at <= ${len(a)+1}")
                a.append(end_time)
            
            if w:
                q += " WHERE " + " AND ".join(w)
            return await conn.fetchval(q, *a)

        orders_total = await count_status(None)
        orders_pending = await count_status("pending")
        orders_confirmed = await count_status("confirmed")
        orders_delivered = await count_status("delivered")
        orders_cancelled = await count_status("cancelled")

        q_rev = "SELECT COALESCE(SUM(total), 0) FROM orders WHERE status = 'delivered'"
        q_b2b = "SELECT COALESCE(SUM(total), 0) AS rev, COUNT(*) AS cnt FROM orders WHERE status = 'delivered' AND source = 'b2b'"
        w_time = ""
        a_time = []
        if start_time:
            w_time += f" AND created_at >= ${len(a_time)+1}"
            a_time.append(start_time)
        if end_time:
            w_time += f" AND created_at <= ${len(a_time)+1}"
            a_time.append(end_time)
            
        revenue = await conn.fetchval(q_rev + w_time, *a_time)
        b2b_row = await conn.fetchrow(q_b2b + w_time, *a_time)
        
    revenue = int(revenue or 0)
    aov = int(revenue / orders_delivered) if orders_delivered else 0
    b2b_revenue = int(b2b_row["rev"] or 0)
    b2b_orders = int(b2b_row["cnt"] or 0)

    async with pool.acquire() as conn:
        q_exp = "SELECT COALESCE(SUM(amount), 0) FROM expenses"
        w_exp = ""
        a_exp = []
        if start_time:
            w_exp += f" WHERE created_at >= ${len(a_exp)+1}"
            a_exp.append(start_time)
        if end_time:
            prefix = " AND" if w_exp else " WHERE"
            w_exp += f"{prefix} created_at <= ${len(a_exp)+1}"
            a_exp.append(end_time)
            
        expenses_total = await conn.fetchval(q_exp + w_exp, *a_exp)
        
        q_items = "SELECT items FROM orders WHERE status = 'delivered'"
        orders_rows = await conn.fetch(q_items + w_time, *a_time)
            
        product_cost_total = 0
        products_costs_rows = await conn.fetch("SELECT id, cost_price FROM products")
        cost_map = {row["id"]: row["cost_price"] or 0 for row in products_costs_rows}
        
        for r in orders_rows:
            try:
                import json
                items = json.loads(r["items"] or "[]")
                for item in items:
                    pid = item.get("id") or item.get("product_id")
                    qty = item.get("quantity", 0)
                    if pid in cost_map:
                        product_cost_total += cost_map[pid] * qty
            except Exception:
                pass
                
    expenses_total = int(expenses_total or 0)
    product_cost_total = int(product_cost_total)
    profit = revenue - expenses_total - product_cost_total

    return {
        "period": period if isinstance(period, str) else "custom",
        "users_total": users_total,
        "users_new": users_new,
        "products_active": products_active,
        "products_in_stock": products_in_stock,
        "reviews_total": reviews_total,
        "reviews_new": reviews_new,
        "orders_total": orders_total,
        "orders_pending": orders_pending,
        "orders_confirmed": orders_confirmed,
        "orders_delivered": orders_delivered,
        "orders_cancelled": orders_cancelled,
        "revenue": revenue,
        "aov": aov,
        "b2b_revenue": b2b_revenue,
        "b2b_orders": b2b_orders,
        "expenses": expenses_total,
        "product_cost": product_cost_total,
        "profit": profit,
    }

async def add_expense(name: str, amount: float) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO expenses (name, amount) VALUES ($1, $2) RETURNING id",
            name, amount
        )

async def get_expenses(limit: int = 50) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, name, amount, created_at FROM expenses ORDER BY created_at DESC LIMIT $1", limit)
        return [dict(r) for r in rows]


def _month_window_utc(year: int, month: int, cap_at_now: bool = False):
    """(start_utc, end_utc) for one Asia/Tashkent calendar month, shifted to
    UTC-naive for querying against created_at. If cap_at_now, the end is
    "now" instead of the month's close (for the current, still-open month) —
    same reasoning as _period_start's "today" fix: flooring in UTC directly
    would misalign the first few hours of each local month."""
    from datetime import datetime, timedelta, timezone
    start_local = datetime(year, month, 1)
    end_local = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    if cap_at_now:
        now_local = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=DISPLAY_TZ_OFFSET_HOURS)
        end_local = min(end_local, now_local)
    offset = timedelta(hours=DISPLAY_TZ_OFFSET_HOURS)
    return start_local - offset, end_local - offset


async def _query_month(conn, start_utc, end_utc) -> dict:
    row = await conn.fetchrow(
        """SELECT COALESCE(SUM(total), 0) AS revenue, COUNT(*) AS orders
           FROM orders WHERE status = 'delivered' AND created_at >= $1 AND created_at < $2""",
        start_utc, end_utc,
    )
    b2b_revenue = await conn.fetchval(
        """SELECT COALESCE(SUM(total), 0) FROM orders
           WHERE status = 'delivered' AND source = 'b2b' AND created_at >= $1 AND created_at < $2""",
        start_utc, end_utc,
    )
    return {
        "revenue": int(row["revenue"] or 0),
        "orders": row["orders"],
        "b2b_revenue": int(b2b_revenue or 0),
    }


async def get_monthly_breakdown(months_back: int = 6) -> list[dict]:
    """Calendar-month revenue/orders, Asia/Tashkent local calendar (not a
    rolling 30-day window) — current month-to-date first, then `months_back`
    prior complete months, newest first."""
    from datetime import datetime, timedelta, timezone
    now_local = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=DISPLAY_TZ_OFFSET_HOURS)

    y, m = now_local.year, now_local.month
    results = []
    async with pool.acquire() as conn:
        for i in range(months_back + 1):
            is_current = (i == 0)
            start_utc, end_utc = _month_window_utc(y, m, cap_at_now=is_current)
            stats = await _query_month(conn, start_utc, end_utc)
            results.append({"year": y, "month": m, "is_current": is_current, **stats})
            y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    return results


async def get_month_stats(year: int, month: int) -> dict:
    """A single arbitrary past calendar month's revenue/orders/B2B — for the
    monthly-report drill-down (owner request 2026-07-27)."""
    from datetime import datetime, timezone, timedelta
    now_local = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=DISPLAY_TZ_OFFSET_HOURS)
    is_current = (year, month) == (now_local.year, now_local.month)
    start_utc, end_utc = _month_window_utc(year, month, cap_at_now=is_current)
    async with pool.acquire() as conn:
        stats = await _query_month(conn, start_utc, end_utc)
    return {"year": year, "month": month, "is_current": is_current, **stats}


async def log_activity(user_id: int, kind: str, action: str) -> None:
    """Record one interaction (button tap or message) for the admin activity
    dashboard. Best-effort — callers fire this without letting failures
    affect the actual user-facing action."""
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO bot_activity (user_id, kind, action) VALUES ($1, $2, $3)",
            user_id, kind, action,
        )


def _activity_excluded_ids() -> list[int]:
    """user_ids whose bot_activity shouldn't count as customer engagement:
    admins doing admin-panel work (ADMIN_IDS, live-updated as admins are
    added) plus the internal/shop test accounts. Owner request (2026-07-26):
    admin actions were dominating "most active users" / "top clicked
    sections" — e.g. an admin's own manual-order entry clicks ("Admin
    bo'limi", "Qo'lda buyurtma: kategoriya tanlash") swamped real customer
    signal."""
    return list(set(ADMIN_IDS) | LEADERBOARD_EXCLUDED_USER_IDS)


async def get_daily_active_users(period: str = "today") -> int:
    """Distinct real (non-admin) users who interacted with the bot at all
    (button or message) in the given period — the "how many people
    opened/used the bot" metric."""
    cutoff = _period_start(period)
    excluded = _activity_excluded_ids()
    async with pool.acquire() as conn:
        if cutoff is None:
            return await conn.fetchval(
                "SELECT COUNT(DISTINCT user_id) FROM bot_activity WHERE user_id <> ALL($1::bigint[])",
                excluded,
            )
        return await conn.fetchval(
            "SELECT COUNT(DISTINCT user_id) FROM bot_activity WHERE created_at >= $1 AND user_id <> ALL($2::bigint[])",
            cutoff, excluded,
        )


async def get_top_actions(period: str = "today", limit: int = 8) -> list[dict]:
    """Most-used buttons/sections in the period, grouped by their human
    label (see activity.py) — button taps only, messages excluded, admin/
    internal accounts excluded (see _activity_excluded_ids)."""
    cutoff = _period_start(period)
    excluded = _activity_excluded_ids()
    async with pool.acquire() as conn:
        if cutoff is None:
            rows = await conn.fetch(
                """SELECT action, COUNT(*) AS clicks FROM bot_activity
                   WHERE kind = 'callback' AND user_id <> ALL($1::bigint[])
                   GROUP BY action ORDER BY clicks DESC LIMIT $2""",
                excluded, limit,
            )
        else:
            rows = await conn.fetch(
                """SELECT action, COUNT(*) AS clicks FROM bot_activity
                   WHERE kind = 'callback' AND created_at >= $1 AND user_id <> ALL($2::bigint[])
                   GROUP BY action ORDER BY clicks DESC LIMIT $3""",
                cutoff, excluded, limit,
            )
        return [dict(r) for r in rows]


async def get_top_products(period: str | dict = "all", limit: int = 5) -> list[dict]:
    start_time, end_time = _period_range(period)
    
    async with pool.acquire() as conn:
        q = "SELECT items FROM orders WHERE status = 'delivered'"
        a = []
        if start_time:
            q += f" AND created_at >= ${len(a)+1}"
            a.append(start_time)
        if end_time:
            q += f" AND created_at <= ${len(a)+1}"
            a.append(end_time)
            
        rows = await conn.fetch(q, *a)

    agg: dict[int, dict] = {}
    for r in rows:
        raw = r["items"]
        items = json.loads(raw) if isinstance(raw, str) else raw
        for it in items or []:
            pid = it.get("product_id")
            if pid is None:
                continue
            entry = agg.setdefault(pid, {
                "product_id": pid,
                "name": it.get("name", "—"),
                "qty": 0.0,
                "revenue": 0.0,
            })
            q = float(it.get("quantity", 0))
            p = float(it.get("price", 0))
            entry["qty"] += q
            entry["revenue"] += q * p

    top = sorted(agg.values(), key=lambda x: x["qty"], reverse=True)[:limit]
    for t in top:
        t["qty"] = int(t["qty"]) if float(t["qty"]).is_integer() else round(t["qty"], 1)
        t["revenue"] = int(t["revenue"])
    return top


async def get_abc_analysis(period: str | dict = "all") -> list[dict]:
    start_time, end_time = _period_range(period)
    
    async with pool.acquire() as conn:
        q = "SELECT items FROM orders WHERE status = 'delivered'"
        a = []
        if start_time:
            q += f" AND created_at >= ${len(a)+1}"
            a.append(start_time)
        if end_time:
            q += f" AND created_at <= ${len(a)+1}"
            a.append(end_time)
            
        rows = await conn.fetch(q, *a)

    agg: dict[int, dict] = {}
    total_revenue = 0.0
    import json
    for r in rows:
        raw = r["items"]
        items = json.loads(raw) if isinstance(raw, str) else raw
        for it in items or []:
            pid = it.get("product_id")
            if pid is None:
                continue
            entry = agg.setdefault(pid, {
                "product_id": pid,
                "name": it.get("name", "—"),
                "qty": 0.0,
                "revenue": 0.0,
            })
            q = float(it.get("quantity", 0))
            p = float(it.get("price", 0))
            rev = q * p
            entry["qty"] += q
            entry["revenue"] += rev
            total_revenue += rev

    # Sort descending by revenue
    sorted_items = sorted(agg.values(), key=lambda x: x["revenue"], reverse=True)
    
    cumulative = 0.0
    for item in sorted_items:
        cumulative += item["revenue"]
        pct = (cumulative / total_revenue * 100) if total_revenue > 0 else 0
        
        if pct <= 80:
            item["category"] = "A"
        elif pct <= 95:
            item["category"] = "B"
        else:
            item["category"] = "C"
            
        item["contribution"] = (item["revenue"] / total_revenue * 100) if total_revenue > 0 else 0

    return sorted_items


async def get_top_ordered_products(limit: int = 3) -> list[dict]:
    """Most-ordered ACTIVE products for the storefront podium.

    Ranks by total quantity across all non-cancelled orders, then returns the
    current product rows (active only) in popularity order. Returns full rows
    so the webapp can serialize them like any other product card.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT items FROM orders WHERE status <> 'cancelled'")

        qty_by_id: dict[int, float] = {}
        for r in rows:
            raw = r["items"]
            items = json.loads(raw) if isinstance(raw, str) else raw
            for it in (items or []):
                pid = it.get("product_id")
                if pid is None:
                    continue
                try:
                    qty_by_id[pid] = qty_by_id.get(pid, 0.0) + float(it.get("quantity", 0) or 0)
                except (TypeError, ValueError):
                    continue

        if not qty_by_id:
            return []

        ranked_ids = [pid for pid, _ in sorted(qty_by_id.items(), key=lambda kv: kv[1], reverse=True)]
        fetched = await conn.fetch(
            """SELECT p.*, u.full_name as seller_name, u.username as seller_username
               FROM products p JOIN users u ON p.seller_id = u.user_id
               WHERE p.is_active = 1 AND p.id = ANY($1::int[])""",
            ranked_ids,
        )
        by_id = {p["id"]: dict(p) for p in fetched}

        result: list[dict] = []
        for pid in ranked_ids:
            if pid in by_id:
                result.append(by_id[pid])
                if len(result) >= limit:
                    break
        return result


# Internal/shop-owned Telegram accounts that place orders for testing or
# demo purposes — not real customers, so they're excluded from the public
# leaderboard (confirmed with the owner 2026-07-15).
LEADERBOARD_EXCLUDED_USER_IDS = {425609051, 6950127923}


async def get_top_active_customers(days: int = 30, limit: int = 5) -> list[dict]:
    """Most-active real customers (by order count) in the last `days` days,
    for the storefront leaderboard. Excludes cancelled orders and internal
    shop/admin accounts (see LEADERBOARD_EXCLUDED_USER_IDS).

    Grouped by phone number rather than user_id: admin-entered manual orders
    (offline sales taken by phone, see add_manual_order) carry the *admin's*
    user_id, not the customer's, so a user_id-based count would either merge
    every manual sale into "the admin" or miss the repeat customer entirely.
    Phone numbers are normalized (digits only, last 9 kept) since the same
    person's number may be typed as "+998 90 123 45 67" via checkout vs
    "998901234567" by an admin. The exclusion list only applies to non-manual
    orders — a manual order's user_id is just whichever admin logged it, so
    it must never disqualify the underlying customer.
    """
    excluded = list(LEADERBOARD_EXCLUDED_USER_IDS)
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            r"""
            SELECT MAX(COALESCE(u.full_name, o.customer_name)) AS full_name,
                   COUNT(*) AS order_count
            FROM orders o
            LEFT JOIN users u
                ON u.user_id = o.user_id AND COALESCE(o.source, 'bot') <> 'manual'
            WHERE o.created_at >= NOW() - ($1 || ' days')::interval
              AND o.status <> 'cancelled'
              AND o.phone IS NOT NULL AND o.phone <> ''
              AND NOT (COALESCE(o.source, 'bot') <> 'manual' AND o.user_id = ANY($2::bigint[]))
            GROUP BY RIGHT(REGEXP_REPLACE(o.phone, '\D', '', 'g'), 9)
            ORDER BY order_count DESC, MAX(o.created_at) DESC
            LIMIT $3
            """,
            str(days), excluded, limit,
        )
        return [dict(r) for r in rows]


async def get_top_active_users(period: str = "today", limit: int = 10) -> list[dict]:
    """Most-active real users (by bot_activity interaction count) in the
    given period, for the admin stats dashboard — each entry paired with
    the product they viewed the most in that same window. Excludes
    admin/internal accounts (see _activity_excluded_ids)."""
    cutoff = _period_start(period)
    excluded = _activity_excluded_ids()
    async with pool.acquire() as conn:
        if cutoff is None:
            rows = await conn.fetch(
                """SELECT a.user_id, COALESCE(u.full_name, '—') AS name, COUNT(*) AS clicks
                   FROM bot_activity a
                   LEFT JOIN users u ON u.user_id = a.user_id
                   WHERE a.user_id IS NOT NULL AND a.user_id <> ALL($1::bigint[])
                   GROUP BY a.user_id, u.full_name
                   ORDER BY clicks DESC
                   LIMIT $2""",
                excluded, limit,
            )
        else:
            rows = await conn.fetch(
                """SELECT a.user_id, COALESCE(u.full_name, '—') AS name, COUNT(*) AS clicks
                   FROM bot_activity a
                   LEFT JOIN users u ON u.user_id = a.user_id
                   WHERE a.created_at >= $1 AND a.user_id IS NOT NULL
                     AND a.user_id <> ALL($2::bigint[])
                   GROUP BY a.user_id, u.full_name
                   ORDER BY clicks DESC
                   LIMIT $3""",
                cutoff, excluded, limit,
            )
        users = [dict(r) for r in rows]

        # One extra query per user (max `limit`, so ≤10) to find their
        # favorite product in the same window — fine for an admin-only,
        # manually-triggered dashboard, not worth a fancier join.
        for u in users:
            if cutoff is None:
                fav = await conn.fetchrow(
                    """SELECT p.name, COUNT(*) AS views
                       FROM product_views v JOIN products p ON p.id = v.product_id
                       WHERE v.user_id = $1
                       GROUP BY p.name ORDER BY views DESC LIMIT 1""",
                    u["user_id"],
                )
            else:
                fav = await conn.fetchrow(
                    """SELECT p.name, COUNT(*) AS views
                       FROM product_views v JOIN products p ON p.id = v.product_id
                       WHERE v.user_id = $1 AND v.viewed_at >= $2
                       GROUP BY p.name ORDER BY views DESC LIMIT 1""",
                    u["user_id"], cutoff,
                )
            u["fav_product"] = fav["name"] if fav else None
        return users


async def restore_product_quantity(product_id: int, amount: float):
    """Return stock that was reserved for a cancelled order."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE products SET quantity = quantity + $1 WHERE id = $2",
            amount, product_id,
        )


async def delete_order_permanently(order_id: int) -> dict | None:
    """Hard-delete an order from the DB — restoring stock if it wasn't already
    cancelled — atomically. Returns the deleted row, or None if the order
    didn't exist.

    Use this only for cleanup of mistakenly-created orders. Cancellation is
    the normal flow (cancel_order); this leaves no trace, so analytics will
    no longer count the order.

    Stock is restored once: if the order was already cancelled, cancel_order
    already restored it, so we just delete the row. Otherwise we add the
    quantities back before deleting.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM orders WHERE id = $1 FOR UPDATE", order_id
            )
            if row is None:
                return None
            order = dict(row)

            if order["status"] != "cancelled":
                items = order["items"]
                items = json.loads(items) if isinstance(items, str) else items
                for it in items or []:
                    pid = it.get("product_id")
                    qty = it.get("quantity")
                    if pid is None or qty is None:
                        continue
                    await conn.execute(
                        "UPDATE products SET quantity = quantity + $1 WHERE id = $2",
                        float(qty), pid,
                    )

            await conn.execute("DELETE FROM orders WHERE id = $1", order_id)
            return order


async def cancel_order(order_id: int) -> dict | None:
    """Mark an order cancelled and restore stock — atomically, idempotently.

    Returns the order row (post-cancellation) or None if the order doesn't exist.
    If the order is already cancelled, this is a no-op (no double-restore).
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM orders WHERE id = $1 FOR UPDATE", order_id
            )
            if row is None:
                return None
            order = dict(row)
            if order["status"] == "cancelled":
                return order  # already cancelled — don't restore stock twice

            items = order["items"]
            items = json.loads(items) if isinstance(items, str) else items
            for it in items or []:
                pid = it.get("product_id")
                qty = it.get("quantity")
                if pid is None or qty is None:
                    continue
                await conn.execute(
                    "UPDATE products SET quantity = quantity + $1 WHERE id = $2",
                    float(qty), pid,
                )
            await conn.execute(
                "UPDATE orders SET status = 'cancelled' WHERE id = $1", order_id
            )
            order["status"] = "cancelled"
            return order


async def add_product_view(product_id: int, user_id: int | None = None):
    """Record one view of a product for analytics."""
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO product_views (product_id, user_id) VALUES ($1, $2)",
            product_id, user_id,
        )


# Display timezone — order timestamps are stored as naive UTC, but the bot
# is for the Uzbek market and admins/buyers think in local time. Override
# via env if you ever deploy elsewhere.
DISPLAY_TZ_OFFSET_HOURS = int(os.getenv("DISPLAY_TZ_OFFSET_HOURS", "5"))


def format_local_dt(dt, fmt: str = "%d.%m.%Y %H:%M") -> str:
    """Format a naive UTC datetime in the configured display timezone
    (Asia/Tashkent / UTC+5 by default). Empty string for None."""
    if dt is None:
        return ""
    from datetime import datetime, timedelta
    if isinstance(dt, datetime):
        return (dt + timedelta(hours=DISPLAY_TZ_OFFSET_HOURS)).strftime(fmt)
    return str(dt)[:16]


def now_local_for_display() -> "datetime":
    """Return a naive datetime that, when fed to format_local_dt, prints as
    *current* local time. Used when we need a fresh stamp for the buyer's
    cancellation notice (no DB column for it)."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def get_all_cost_prices() -> dict[int, float]:
    """Return {product_id: cost_price} for every product.

    Used by the Excel report to compute per-line-item profit. Cost price is
    admin-only (never exposed to buyers), and a single query is far cheaper
    than fetching each product separately while iterating order items.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, COALESCE(cost_price, 0) AS cost_price FROM products"
        )
        return {int(r["id"]): float(r["cost_price"]) for r in rows}


async def get_orders_for_export(period: str = "all") -> list[dict]:
    """Return all orders in the given period with items already JSON-decoded.
    Used by reports.py to build Excel exports — sourced from the same time
    windows as get_admin_stats so the numbers match the dashboard."""
    cutoff = _period_start(period)
    async with pool.acquire() as conn:
        if cutoff is None:
            rows = await conn.fetch(
                "SELECT * FROM orders ORDER BY created_at DESC"
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM orders WHERE created_at >= $1 ORDER BY created_at DESC",
                cutoff,
            )
    out = []
    for r in rows:
        d = dict(r)
        raw = d.get("items")
        try:
            d["items_data"] = json.loads(raw) if isinstance(raw, str) else (raw or [])
        except Exception:
            d["items_data"] = []
        out.append(d)
    return out


async def get_top_viewed_products(period: str = "all", limit: int = 5) -> list[dict]:
    """Top products by view count in the given period."""
    cutoff = _period_start(period)
    async with pool.acquire() as conn:
        if cutoff is None:
            rows = await conn.fetch(
                """SELECT v.product_id, p.name, COUNT(*) AS views
                   FROM product_views v
                   JOIN products p ON v.product_id = p.id
                   GROUP BY v.product_id, p.name
                   ORDER BY views DESC
                   LIMIT $1""",
                limit,
            )
        else:
            rows = await conn.fetch(
                """SELECT v.product_id, p.name, COUNT(*) AS views
                   FROM product_views v
                   JOIN products p ON v.product_id = p.id
                   WHERE v.viewed_at >= $1
                   GROUP BY v.product_id, p.name
                   ORDER BY views DESC
                   LIMIT $2""",
                cutoff, limit,
            )
    return [dict(r) for r in rows]


async def ban_user(user_id: int, reason: str = ""):
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO banned_users (user_id, reason) VALUES ($1, $2)
               ON CONFLICT (user_id) DO UPDATE SET reason = $2, banned_at = CURRENT_TIMESTAMP""",
            user_id, reason
        )


async def unban_user(user_id: int):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM banned_users WHERE user_id = $1", user_id)


async def is_user_banned(user_id: int) -> bool:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT user_id FROM banned_users WHERE user_id = $1", user_id)
        return row is not None


async def get_extra_admin_ids() -> list[int]:
    """Admins added at runtime (on top of config.ADMIN_IDS' hardcoded/env
    set) — loaded once at bot startup and merged into that same list."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM admins")
        return [r["user_id"] for r in rows]


async def add_admin_db(user_id: int, added_by: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO admins (user_id, added_by) VALUES ($1, $2)
               ON CONFLICT (user_id) DO NOTHING""",
            user_id, added_by
        )


async def get_courier_ids() -> list[int]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM couriers")
        return [r["user_id"] for r in rows]


async def add_courier_db(user_id: int, added_by: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO couriers (user_id, added_by) VALUES ($1, $2)
               ON CONFLICT (user_id) DO NOTHING""",
            user_id, added_by
        )


async def remove_courier_db(user_id: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM couriers WHERE user_id = $1", user_id)


async def admin_delete_product(product_id: int):
    await delete_product(product_id)


async def get_seller_stats(seller_id: int, all_stats: bool = False) -> dict:
    async with pool.acquire() as conn:
        if all_stats:
            products = await conn.fetchval(
                "SELECT COUNT(*) FROM products WHERE is_active = 1"
            )
            orders = await conn.fetchval(
                "SELECT COUNT(*) FROM orders"
            )
            completed = await conn.fetchval(
                "SELECT COUNT(*) FROM orders WHERE status = 'delivered'"
            )
            revenue = await conn.fetchval(
                "SELECT COALESCE(SUM(total), 0) FROM orders WHERE status = 'delivered'"
            )
        else:
            products = await conn.fetchval(
                "SELECT COUNT(*) FROM products WHERE seller_id = $1 AND is_active = 1",
                seller_id
            )
            orders = await conn.fetchval(
                "SELECT COUNT(*) FROM orders WHERE seller_id = $1",
                seller_id
            )
            completed = await conn.fetchval(
                "SELECT COUNT(*) FROM orders WHERE seller_id = $1 AND status = 'delivered'",
                seller_id
            )
            revenue = await conn.fetchval(
                "SELECT COALESCE(SUM(total), 0) FROM orders WHERE seller_id = $1 AND status = 'delivered'",
                seller_id
            )
        return {
            "products": products,
            "orders": orders,
            "completed": completed,
            "revenue": int(revenue),
        }


# ===== BROADCAST (scheduled tips) =====

async def get_all_user_ids() -> list[int]:
    """All user IDs eligible for a broadcast (banned users excluded)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT user_id FROM users
            WHERE user_id NOT IN (SELECT user_id FROM banned_users)
        """)
        return [r["user_id"] for r in rows]


async def get_broadcast_state() -> dict:
    """Return the single broadcast-state row, creating it if missing."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM broadcast_state WHERE id = 1")
        if row is None:
            await conn.execute("INSERT INTO broadcast_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
            row = await conn.fetchrow("SELECT * FROM broadcast_state WHERE id = 1")
        return dict(row)


async def advance_broadcast(new_index: int):
    """Record that a tip was just sent: move the pointer and stamp the time."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE broadcast_state SET next_index = $1, last_sent_at = (now() AT TIME ZONE 'utc') WHERE id = 1",
            new_index,
        )


async def set_broadcast_enabled(enabled: bool):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE broadcast_state SET enabled = $1 WHERE id = 1", enabled)


async def set_broadcast_index(index: int):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE broadcast_state SET next_index = $1 WHERE id = 1", index)


async def set_broadcast_warn_date(d):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE broadcast_state SET last_warn_date = $1 WHERE id = 1", d)


# ===== PERSONALIZED RECOMMENDATION STATE =====

async def get_reco_state() -> dict:
    """Return the single personal-recommendation state row, creating if missing."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM personal_reco_state WHERE id = 1")
        if row is None:
            await conn.execute("INSERT INTO personal_reco_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
            row = await conn.fetchrow("SELECT * FROM personal_reco_state WHERE id = 1")
        return dict(row)


async def advance_reco():
    """Record a personal-reco send: bump the rotation cycle and stamp the time."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE personal_reco_state SET cycle = cycle + 1, "
            "last_sent_at = (now() AT TIME ZONE 'utc') WHERE id = 1"
        )


async def set_reco_enabled(enabled: bool):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE personal_reco_state SET enabled = $1 WHERE id = 1", enabled)


async def get_reco_hashes(user_id: int) -> set[str]:
    """Fingerprints of every personalized message this buyer already received."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT msg_hash FROM personal_reco_sent WHERE user_id = $1", user_id
        )
        return {r["msg_hash"] for r in rows}


async def mark_reco_sent(user_id: int, msg_hash: str):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO personal_reco_sent (user_id, msg_hash) VALUES ($1, $2) "
            "ON CONFLICT DO NOTHING",
            user_id, msg_hash,
        )


async def add_nps_response(user_id: int, score: int) -> int:
    """Record a new NPS score; the reason (if the buyer gives one) is added
    afterwards via set_nps_comment. Returns the new row's id."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO nps_responses (user_id, score) VALUES ($1, $2) RETURNING id",
            user_id, score,
        )


async def set_nps_comment(response_id: int, comment: str | None) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE nps_responses SET comment = $1 WHERE id = $2",
            comment, response_id,
        )


async def get_user_ids_with_orders() -> list[int]:
    """Buyers eligible for a personalized recommendation: users who have at
    least one real (non-manual) order and aren't banned.

    Manual orders are excluded because they're keyed under the admin's user_id
    but represent someone else's offline purchase — see get_user_orders."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT o.user_id
            FROM orders o
            WHERE COALESCE(o.source, 'bot') <> 'manual'
              AND o.user_id NOT IN (SELECT user_id FROM banned_users)
        """)
        return [r["user_id"] for r in rows]


async def get_user_ids_with_views_no_orders() -> list[int]:
    """Browse-only buyers: they've viewed at least one product but never
    ordered (so get_user_ids_with_orders skips them entirely). Used by the
    4-day personal reco to reach them too, via their most-viewed product
    instead of order history (owner request 2026-07-27: "barcha
    foydalanuvchilar" — everyone, not just past buyers)."""
    excluded = list(set(ADMIN_IDS) | LEADERBOARD_EXCLUDED_USER_IDS)
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT DISTINCT v.user_id
            FROM product_views v
            WHERE v.user_id IS NOT NULL
              AND v.user_id NOT IN (SELECT user_id FROM banned_users)
              AND v.user_id <> ALL($1::bigint[])
              AND NOT EXISTS (
                  SELECT 1 FROM orders o
                  WHERE o.user_id = v.user_id AND COALESCE(o.source, 'bot') <> 'manual'
              )
        """, excluded)
        return [r["user_id"] for r in rows]


async def get_user_top_viewed_products(user_id: int, limit: int = 3, recent_days: int = 30) -> list[dict]:
    """This user's most-viewed products (full rows + view_count), ranked by
    views within the last `recent_days` — so the spotlight tracks what
    they're *currently* interested in rather than freezing on whatever they
    looked at once, months ago (owner request 2026-07-27: "yangilanib
    qiziqishlarini kuzatib borishi kerak" — must adapt as interest shifts).
    Falls back to all-time views if they have none in the recent window
    (e.g. a one-time visitor who hasn't been back) — still worth reaching
    with *something* rather than nothing."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.*, COUNT(*) AS view_count
            FROM product_views v
            JOIN products p ON p.id = v.product_id
            WHERE v.user_id = $1 AND p.is_active = 1
              AND v.viewed_at >= NOW() - ($2 || ' days')::interval
            GROUP BY p.id
            ORDER BY view_count DESC, MAX(v.viewed_at) DESC
            LIMIT $3
        """, user_id, str(recent_days), limit)
        if not rows:
            rows = await conn.fetch("""
                SELECT p.*, COUNT(*) AS view_count
                FROM product_views v
                JOIN products p ON p.id = v.product_id
                WHERE v.user_id = $1 AND p.is_active = 1
                GROUP BY p.id
                ORDER BY view_count DESC
                LIMIT $2
            """, user_id, limit)
        return [dict(r) for r in rows]


# ===== ADMIN WEBSITE: PRODUCTS =====

async def admin_list_products(include_inactive: bool = True) -> list[dict]:
    """Every product (active and, optionally, archived) for the admin website,
    newest first. Includes image_url so the panel can show thumbnails."""
    where = "" if include_inactive else "WHERE is_active = 1"
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM products {where} ORDER BY created_at DESC, id DESC"
        )
        return [dict(r) for r in rows]


async def admin_create_product(seller_id: int, name: str, price: float, category: str,
                               unit: str = "kg", quantity: float = 0,
                               description: str = None, name_ru: str = None,
                               description_ru: str = None, cost_price: float = 0,
                               discount_percent: int = 0, image_url: str = None) -> int:
    """Insert a product from the admin website. seller_id must reference an
    existing users row (the caller ensures the admin user exists first)."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO products
                 (seller_id, name, description, price, unit, quantity, category,
                  name_ru, description_ru, cost_price, discount_percent, image_url)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12) RETURNING id""",
            seller_id, name, description, price, unit, quantity, category,
            name_ru, description_ru, cost_price, discount_percent, image_url,
        )


async def ensure_user_exists(user_id: int, full_name: str = "Admin"):
    """Make sure a users row exists so a product's seller_id FK is satisfied."""
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (user_id, full_name) VALUES ($1, $2) ON CONFLICT (user_id) DO NOTHING",
            user_id, full_name,
        )


# ===== ADMIN WEBSITE: PRODUCT SETS (BUNDLES) =====

async def _set_with_items(conn, row) -> dict:
    """Hydrate a product_sets row with its member items and the computed
    combined ('separate') price so the UI can show set vs. original."""
    s = dict(row)
    items = await conn.fetch(
        """SELECT si.id AS item_id, si.product_id, si.quantity,
                  p.name, p.name_ru, p.price, p.unit, p.image_url, p.is_active
           FROM product_set_items si
           JOIN products p ON p.id = si.product_id
           WHERE si.set_id = $1
           ORDER BY si.id""",
        s["id"],
    )
    items = [dict(i) for i in items]
    original_total = sum(float(i["price"]) * float(i["quantity"]) for i in items)
    s["items"] = items
    s["original_total"] = original_total
    s["savings"] = max(0.0, original_total - float(s["set_price"]))
    return s


async def get_sets(active_only: bool = False) -> list[dict]:
    where = "WHERE is_active = 1" if active_only else ""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM product_sets {where} ORDER BY created_at DESC, id DESC"
        )
        return [await _set_with_items(conn, r) for r in rows]

async def get_active_sets_for_catalog() -> list[dict]:
    # Returns all active sets, skipping any set whose individual items are inactive or out of stock
    sets = await get_sets(active_only=True)
    valid_sets = []
    for s in sets:
        valid = True
        for item in s["items"]:
            if item.get("is_active", 0) == 0:
                valid = False
                break
        if valid:
            valid_sets.append(s)
    return valid_sets


async def get_set(set_id: int) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM product_sets WHERE id = $1", set_id)
        return await _set_with_items(conn, row) if row else None


async def create_set(name: str, set_price: float, items: list[dict],
                     name_ru: str = None, description: str = None,
                     description_ru: str = None, image_url: str = None) -> int:
    """Create a bundle. `items` is a list of {product_id, quantity}."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            set_id = await conn.fetchval(
                """INSERT INTO product_sets
                     (name, name_ru, description, description_ru, set_price, image_url)
                   VALUES ($1,$2,$3,$4,$5,$6) RETURNING id""",
                name, name_ru, description, description_ru, set_price, image_url,
            )
            for it in items:
                await conn.execute(
                    "INSERT INTO product_set_items (set_id, product_id, quantity) VALUES ($1,$2,$3)",
                    set_id, int(it["product_id"]), float(it.get("quantity", 1)),
                )
        return set_id


async def update_set(set_id: int, *, items: list[dict] | None = None, **fields):
    """Update a set's scalar fields and, if `items` is provided, replace its
    membership wholesale."""
    allowed = {"name", "name_ru", "description", "description_ru", "set_price", "image_url", "is_active"}
    async with pool.acquire() as conn:
        async with conn.transaction():
            for key, value in fields.items():
                if key not in allowed:
                    raise ValueError(f"Invalid column for product_sets: {key}")
                await conn.execute(f"UPDATE product_sets SET {key} = $1 WHERE id = $2", value, set_id)
            if items is not None:
                await conn.execute("DELETE FROM product_set_items WHERE set_id = $1", set_id)
                for it in items:
                    await conn.execute(
                        "INSERT INTO product_set_items (set_id, product_id, quantity) VALUES ($1,$2,$3)",
                        set_id, int(it["product_id"]), float(it.get("quantity", 1)),
                    )


async def delete_set(set_id: int):
    """Hard-delete a set (its items cascade)."""
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM product_sets WHERE id = $1", set_id)


# ===== ADMIN WEBSITE: UPLOADED IMAGES =====

async def save_web_image(data: bytes, content_type: str) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO web_images (data, content_type) VALUES ($1, $2) RETURNING id",
            data, content_type,
        )


async def get_web_image(image_id: int) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT data, content_type FROM web_images WHERE id = $1", image_id
        )
        return dict(row) if row else None


# ===== DAILY DB BACKUP =====

async def get_backup_state() -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM db_backup_state WHERE id = 1")
        if row is None:
            await conn.execute("INSERT INTO db_backup_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
            row = await conn.fetchrow("SELECT * FROM db_backup_state WHERE id = 1")
        return dict(row)


async def set_backup_date(d):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE db_backup_state SET last_backup_date = $1 WHERE id = 1", d)


# Tables excluded from the daily backup: FSM/session state that's meaningless
# outside a live process, and web_images (raw image bytes — would make the
# backup huge; product_media/photo_id Telegram file_ids already cover product
# photos for restore purposes).
_BACKUP_EXCLUDE_TABLES = {"fsm_state", "web_images"}


async def dump_all_tables() -> dict:
    """Snapshot every table (except the ones excluded above) as plain
    JSON-able rows. Used by the daily backup job — deliberately a plain
    SELECT * per table rather than pg_dump, since pg_dump isn't installed
    in the bot's own container."""
    async with pool.acquire() as conn:
        table_rows = await conn.fetch(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        tables = sorted(r["table_name"] for r in table_rows if r["table_name"] not in _BACKUP_EXCLUDE_TABLES)

        out = {}
        for t in tables:
            rows = await conn.fetch(f"SELECT * FROM {t}")
            out[t] = [dict(r) for r in rows]
        return out


# ===== KETO GAMIFICATION (2026-07-26, test rollout — earn only) =====

async def credit_keto(user_id: int, order_id: int | None, amount: int, kind: str,
                       note: str | None = None) -> bool:
    """Add `amount` Keto to a user's balance+lifetime, logged in keto_ledger.
    Returns False (no-op) if this exact (order_id, kind='order') pair was
    already credited — the partial unique index on keto_ledger makes this
    safe to call more than once for the same order without double-paying."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                await conn.execute(
                    "INSERT INTO keto_ledger (user_id, order_id, amount, kind, note) "
                    "VALUES ($1, $2, $3, $4, $5)",
                    user_id, order_id, amount, kind, note,
                )
            except asyncpg.UniqueViolationError:
                return False
            await conn.execute(
                "UPDATE users SET keto_balance = keto_balance + $1, keto_lifetime = keto_lifetime + $1 "
                "WHERE user_id = $2",
                amount, user_id,
            )
    return True


async def count_user_delivered_orders(user_id: int) -> int:
    """Delivered orders placed BY this user through the bot/webapp themselves
    — excludes admin-entered manual/B2B orders, which carry the admin's
    user_id rather than the real buyer's."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM orders WHERE user_id = $1 AND status = 'delivered' "
            "AND COALESCE(source, 'bot') NOT IN ('manual', 'b2b')",
            user_id,
        )


async def get_user_achievement_codes(user_id: int) -> set[str]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT code FROM user_achievements WHERE user_id = $1", user_id)
        return {r["code"] for r in rows}


async def unlock_achievement(user_id: int, code: str) -> bool:
    """Returns False if already unlocked (UNIQUE(user_id, code))."""
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO user_achievements (user_id, code) VALUES ($1, $2)",
                user_id, code,
            )
            return True
        except asyncpg.UniqueViolationError:
            return False


async def get_user_achievements(user_id: int) -> list[dict]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT code, unlocked_at FROM user_achievements WHERE user_id = $1 ORDER BY unlocked_at",
            user_id,
        )
        return [dict(r) for r in rows]


async def set_keto_pin_message_id(user_id: int, message_id: int | None) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET keto_pin_message_id = $1 WHERE user_id = $2",
            message_id, user_id,
        )


async def mark_kabinetim_intro_seen(user_id: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET kabinetim_intro_seen = TRUE WHERE user_id = $1",
            user_id,
        )


async def was_menu_keyboard_sent(user_id: int) -> bool:
    """Has this chat already been given the persistent 🏠/🛒 reply keyboard?
    Defaults to False for a user row that doesn't exist yet, so a brand-new
    user gets it on their very first /start."""
    async with pool.acquire() as conn:
        return bool(await conn.fetchval(
            "SELECT menu_keyboard_sent FROM users WHERE user_id = $1", user_id
        ))


async def mark_menu_keyboard_sent(user_id: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE users SET menu_keyboard_sent = TRUE WHERE user_id = $1", user_id
        )


async def get_users_with_keto_pin() -> list[int]:
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users WHERE keto_pin_message_id IS NOT NULL")
        return [r["user_id"] for r in rows]


async def get_gamification_state() -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM gamification_state WHERE id = 1")
        if row is None:
            await conn.execute("INSERT INTO gamification_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
            row = await conn.fetchrow("SELECT * FROM gamification_state WHERE id = 1")
        return dict(row)


async def set_gamification_enabled(enabled: bool) -> None:
    async with pool.acquire() as conn:
        await conn.execute("UPDATE gamification_state SET enabled = $1 WHERE id = 1", enabled)


async def set_redemption_enabled(enabled: bool) -> None:
    async with pool.acquire() as conn:
        await conn.execute("UPDATE gamification_state SET redemption_enabled = $1 WHERE id = 1", enabled)


async def get_keto_balances_list() -> list[dict]:
    """Every user with any Keto (balance or lifetime), highest first — admin
    panel's Keto tab, so the owner can check who has how much without asking."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT user_id, username, full_name, keto_balance, keto_lifetime
               FROM users WHERE keto_balance > 0 OR keto_lifetime > 0
               ORDER BY keto_lifetime DESC, keto_balance DESC"""
        )
        return [dict(r) for r in rows]


async def set_gamification_pin_refresh_date(d) -> None:
    async with pool.acquire() as conn:
        await conn.execute("UPDATE gamification_state SET last_pin_refresh_date = $1 WHERE id = 1", d)


async def get_keto_program_stats() -> dict:
    """Quick program-wide snapshot for /keto_status."""
    async with pool.acquire() as conn:
        users_with_keto = await conn.fetchval("SELECT COUNT(*) FROM users WHERE keto_lifetime > 0")
        total_awarded = await conn.fetchval("SELECT COALESCE(SUM(amount), 0) FROM keto_ledger")
        achievements_unlocked = await conn.fetchval("SELECT COUNT(*) FROM user_achievements")
    return {
        "users_with_keto": users_with_keto,
        "total_awarded": int(total_awarded or 0),
        "achievements_unlocked": achievements_unlocked,
    }


# ===== REFERRAL CONTEST ("Keto musobaqasi", 2026-07-30) =====

async def record_referral(referred_user_id: int, referrer_user_id: int) -> bool:
    """Log that `referrer_user_id` invited `referred_user_id`. Returns False
    (no-op) if this person was already credited to someone else — the UNIQUE
    constraint on referred_user_id makes this safe to call at most once per
    new user, no matter how many times /start ref... gets re-processed."""
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO referrals (referred_user_id, referrer_user_id) VALUES ($1, $2)",
                referred_user_id, referrer_user_id,
            )
            return True
        except asyncpg.UniqueViolationError:
            return False


async def get_referral_contest_state() -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM referral_contest_state WHERE id = 1")
        if row is None:
            await conn.execute("INSERT INTO referral_contest_state (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
            row = await conn.fetchrow("SELECT * FROM referral_contest_state WHERE id = 1")
        return dict(row)


async def start_referral_contest(days: int, image_url: str | None,
                                  prize_1: str | None, prize_2: str | None, prize_3: str | None,
                                  video_file_id: str | None = None, image_file_id: str | None = None) -> dict:
    """(Re)launch the contest for `days` days from now. Re-arming after a
    previous run clears winners_announced/last_reminder_date so the new run
    gets its own fresh reminder cadence and end announcement.

    image_url/video_file_id/image_file_id are three independent media slots
    (website-hosted image URL, bot-uploaded video, bot-uploaded photo — see
    _contest_media() in referral_contest.py for send priority). Whichever
    admin surface calls this only manages its own slot(s); the caller is
    responsible for passing through the other slots' *current* values
    unchanged (both admin_web.py and handlers/admin.py do this) so starting
    from one interface doesn't wipe media set via the other."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE referral_contest_state SET
                active = TRUE,
                started_at = CURRENT_TIMESTAMP,
                ends_at = CURRENT_TIMESTAMP + ($1 || ' days')::INTERVAL,
                image_url = $2, prize_1 = $3, prize_2 = $4, prize_3 = $5, video_file_id = $6,
                image_file_id = $7,
                last_reminder_date = NULL, winners_announced = FALSE
            WHERE id = 1
            RETURNING *
            """,
            str(int(days)), image_url, prize_1, prize_2, prize_3, video_file_id, image_file_id,
        )
        return dict(row)


async def update_contest_media(video_file_id: str | None, image_file_id: str | None) -> None:
    """Swap the contest's bot-uploaded media without touching the timer,
    prizes, or active state — for a quick "just change the photo/video" edit
    from the bot's admin panel (owner request 2026-07-31), as opposed to
    start_referral_contest which re-arms the whole contest."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE referral_contest_state SET video_file_id = $1, image_file_id = $2 WHERE id = 1",
            video_file_id, image_file_id,
        )


async def update_contest_guide_video(guide_video_file_id: str | None) -> None:
    """Set/clear the ADDITIONAL 'how to participate' video — independent of
    the main promo photo/video slot (owner request 2026-07-31: add one, not
    replace the existing photo)."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE referral_contest_state SET guide_video_file_id = $1 WHERE id = 1",
            guide_video_file_id,
        )


async def stop_referral_contest() -> None:
    """Admin manual stop — e.g. to correct a mistaken launch. Does not clear
    the recorded referrals, just deactivates the contest and closes it out."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE referral_contest_state SET active = FALSE WHERE id = 1"
        )


async def set_contest_reminder_date(d) -> None:
    async with pool.acquire() as conn:
        await conn.execute("UPDATE referral_contest_state SET last_reminder_date = $1 WHERE id = 1", d)


async def mark_contest_finished() -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE referral_contest_state SET active = FALSE, winners_announced = TRUE WHERE id = 1"
        )


async def get_contest_leaderboard(since, until, exclude: set[int], limit: int = 50) -> list[dict]:
    """Referral counts within [since, until], ranked highest first. Excludes
    admin/internal accounts as both referrer and referred (mirrors
    gamification._is_eligible / LEADERBOARD_EXCLUDED_USER_IDS)."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT r.referrer_user_id AS user_id, COUNT(*) AS invites,
                   u.username, u.full_name
            FROM referrals r
            JOIN users u ON u.user_id = r.referrer_user_id
            WHERE r.created_at >= $1 AND r.created_at <= $2
              AND r.referrer_user_id != ALL($3::BIGINT[])
              AND r.referred_user_id != ALL($3::BIGINT[])
            GROUP BY r.referrer_user_id, u.username, u.full_name
            ORDER BY invites DESC, MIN(r.created_at) ASC
            LIMIT $4
            """,
            since, until, list(exclude), limit,
        )
        return [dict(r) for r in rows]


async def get_user_referral_count(user_id: int, since, until) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT COUNT(*) FROM referrals WHERE referrer_user_id = $1 AND created_at >= $2 AND created_at <= $3",
            user_id, since, until,
        )


# ===== META LEAD ADS (2026-08-22) =====
# Backing store for meta_leads.py — see that module's docstring for why the
# integration polls the Graph API instead of taking a webhook.

async def meta_lead_seen(lead_id: str) -> bool:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM meta_leads WHERE lead_id = $1)", lead_id
        )


async def save_meta_lead(*, lead_id, form_id=None, form_name=None, full_name=None,
                         phone=None, email=None, campaign_name=None, ad_name=None,
                         created_time=None, raw=None):
    """Insert one lead. ON CONFLICT DO NOTHING because two overlapping polls
    (a slow sweep still running when the next tick fires) must not double-write
    — the insert, not the read, is what guarantees each lead notifies once."""
    import json as _json
    from datetime import datetime as _dt

    if isinstance(created_time, str) and created_time:
        try:
            created_time = _dt.fromisoformat(created_time.replace("Z", "+00:00"))
        except ValueError:
            created_time = None

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO meta_leads (lead_id, form_id, form_name, full_name, phone,
                                    email, campaign_name, ad_name, raw, created_time)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
            ON CONFLICT (lead_id) DO NOTHING
            """,
            lead_id, form_id, form_name, full_name, phone, email,
            campaign_name, ad_name,
            _json.dumps(raw, ensure_ascii=False, default=str) if raw is not None else None,
            created_time,
        )


async def mark_meta_lead_handled(lead_id: str, admin_id: int) -> bool:
    """Claim a lead. Returns False when another admin already claimed it —
    the WHERE handled_by IS NULL makes that race a database-level decision
    rather than a read-then-write both callers can win."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE meta_leads SET handled_by = $2, handled_at = NOW()
            WHERE lead_id = $1 AND handled_by IS NULL
            RETURNING lead_id
            """,
            lead_id, admin_id,
        )
        return row is not None


async def get_meta_lead(lead_id: str) -> dict | None:
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM meta_leads WHERE lead_id = $1", lead_id)
        return dict(row) if row else None


async def get_recent_meta_leads(limit: int = 10) -> list:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM meta_leads ORDER BY created_time DESC NULLS LAST, received_at DESC LIMIT $1",
            limit,
        )
        return [dict(r) for r in rows]


async def count_meta_leads() -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM meta_leads")


async def get_meta_leads_summary() -> dict:
    """Lead counters for the admin panel's Reklama tab. One aggregate query
    instead of counting a fetched list — the table only grows, and the panel
    asks for this on every period switch. "Today" is the Tashkent day, not the
    UTC one, so the number matches what the shop actually worked through."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT COUNT(*) AS total,
                   COUNT(*) FILTER (
                       WHERE COALESCE(created_time, received_at)
                             >= date_trunc('day', NOW() AT TIME ZONE 'Asia/Tashkent')
                                AT TIME ZONE 'Asia/Tashkent'
                   ) AS today,
                   COUNT(*) FILTER (WHERE handled_by IS NULL) AS unhandled
            FROM meta_leads
        """)
        return {"total": row["total"], "today": row["today"], "unhandled": row["unhandled"]}


# ===== AKSIYA / BONUS (2026-08-31) =====
# Backing store for promotions.py. A promotion is created inactive and only
# becomes visible to buyers once an admin presses "Boshlash" (start_promotion),
# which is also what stamps started_at/ends_at — the `days` column is just the
# saved default, so re-starting an old campaign gives it a fresh window.


async def get_promotion(promo_id: int) -> dict | None:
    """One promotion with its bonus rules (each rule carries the trigger and
    bonus product names/units already joined in, so callers never have to
    round-trip products themselves)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM promotions WHERE id = $1", promo_id)
        if row is None:
            return None
        promo = dict(row)
        promo["bonuses"] = await _fetch_promo_bonuses(conn, promo_id)
        return promo


async def get_active_promotion() -> dict | None:
    """The single running campaign, or None. Also self-heals an expired one:
    a promotion whose ends_at has passed is reported as inactive even if the
    scheduler hasn't ticked yet, so a restart-during-expiry can never leave a
    stale banner up in the bot or Mini App."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM promotions WHERE active AND (ends_at IS NULL OR ends_at > CURRENT_TIMESTAMP) LIMIT 1"
        )
        if row is None:
            return None
        promo = dict(row)
        promo["bonuses"] = await _fetch_promo_bonuses(conn, promo["id"])
        return promo


async def list_promotions() -> list[dict]:
    """Every campaign ever created, running one first — the admin panel's list."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM promotions ORDER BY active DESC, created_at DESC")
        out = []
        for row in rows:
            promo = dict(row)
            promo["bonuses"] = await _fetch_promo_bonuses(conn, promo["id"])
            out.append(promo)
        return out


async def _fetch_promo_bonuses(conn, promo_id: int) -> list[dict]:
    rows = await conn.fetch(
        """
        SELECT b.*,
               tp.name AS trigger_name, tp.name_ru AS trigger_name_ru, tp.unit AS trigger_unit,
               bp.name AS bonus_name,   bp.name_ru AS bonus_name_ru,   bp.unit AS bonus_product_unit,
               -- The bonus product's real shelf price, so the cart can show it
               -- struck through next to 0 ("you're getting 25 000 so'm free")
               -- instead of a bare "bepul" that reads as worth nothing.
               bp.price AS bonus_price, bp.photo_id AS bonus_photo_id
        FROM promotion_bonuses b
        JOIN products tp ON tp.id = b.trigger_product_id
        JOIN products bp ON bp.id = b.bonus_product_id
        WHERE b.promo_id = $1
        ORDER BY b.id
        """,
        promo_id,
    )
    return [dict(r) for r in rows]


async def create_promotion(name: str, name_ru: str | None, conditions: str | None,
                           conditions_ru: str | None, days: int,
                           image_url: str | None) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO promotions (name, name_ru, conditions, conditions_ru, days, image_url)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
            name, name_ru, conditions, conditions_ru, int(days), image_url,
        )


async def update_promotion(promo_id: int, **fields) -> None:
    """Partial update. Editing a running campaign is allowed on purpose (fix a
    typo in the shartlar mid-flight) — only `days` needs a restart to take
    effect, since ends_at was already stamped at launch."""
    allowed = {"name", "name_ru", "conditions", "conditions_ru", "days", "image_url"}
    sets, values = [], []
    for key, value in fields.items():
        if key in allowed:
            values.append(value)
            sets.append(f"{key} = ${len(values)}")
    if not sets:
        return
    values.append(promo_id)
    async with pool.acquire() as conn:
        await conn.execute(
            f"UPDATE promotions SET {', '.join(sets)} WHERE id = ${len(values)}", *values
        )


async def set_promotion_bonuses(promo_id: int, rules: list[dict]) -> None:
    """Replace this campaign's whole bonus-rule list in one transaction.

    Same replace-don't-merge approach product_set_items already uses: the
    admin form always submits the complete list, so a row deleted in the UI
    has to disappear here too."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM promotion_bonuses WHERE promo_id = $1", promo_id)
            for rule in rules:
                await conn.execute(
                    """INSERT INTO promotion_bonuses
                       (promo_id, trigger_product_id, trigger_quantity, bonus_product_id,
                        bonus_amount, bonus_unit, bonus_stock_qty, max_bonus_amount)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
                    promo_id,
                    int(rule["trigger_product_id"]), float(rule["trigger_quantity"]),
                    int(rule["bonus_product_id"]), float(rule["bonus_amount"]),
                    rule["bonus_unit"], float(rule["bonus_stock_qty"]),
                    rule.get("max_bonus_amount"),
                )


async def start_promotion(promo_id: int, days: int | None = None) -> dict | None:
    """Launch (or relaunch) one campaign for `days` days from now, and stop
    every other one — only a single aksiya runs at a time (a partial unique
    index on `active` backs this up). Clears announced_at so a relaunch can
    send its announcement again."""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("UPDATE promotions SET active = FALSE WHERE active AND id != $1", promo_id)
            if days is None:
                days = await conn.fetchval("SELECT days FROM promotions WHERE id = $1", promo_id)
            if days is None:
                return None
            row = await conn.fetchrow(
                """UPDATE promotions SET
                       active = TRUE, days = $2,
                       started_at = CURRENT_TIMESTAMP,
                       ends_at = CURRENT_TIMESTAMP + ($3 || ' days')::INTERVAL,
                       announced_at = NULL
                   WHERE id = $1 RETURNING id""",
                promo_id, int(days), str(int(days)),
            )
    if row is None:
        return None
    return await get_promotion(promo_id)


async def stop_promotion(promo_id: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute("UPDATE promotions SET active = FALSE WHERE id = $1", promo_id)


async def delete_promotion(promo_id: int) -> None:
    """Hard delete — bonus rules cascade. Past orders keep their bonus lines
    regardless: those are frozen into orders.items as plain JSON at checkout,
    not looked up from here."""
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM promotions WHERE id = $1", promo_id)


async def mark_promotion_announced(promo_id: int) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE promotions SET announced_at = CURRENT_TIMESTAMP WHERE id = $1", promo_id
        )


async def expire_promotions() -> list[dict]:
    """Deactivate every campaign whose window has closed. Returns the ones
    that just ended, so the scheduler can tell the admins."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """UPDATE promotions SET active = FALSE
               WHERE active AND ends_at IS NOT NULL AND ends_at <= CURRENT_TIMESTAMP
               RETURNING *"""
        )
        return [dict(r) for r in rows]


async def get_bonus_trigger_product_ids() -> set[int]:
    """Product ids that trigger a bonus under the currently running campaign —
    what the catalog and Mini App use to stamp a "🎁 Bonus" badge on a card
    without loading the whole rule set per product."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT DISTINCT b.trigger_product_id
               FROM promotion_bonuses b JOIN promotions p ON p.id = b.promo_id
               WHERE p.active AND (p.ends_at IS NULL OR p.ends_at > CURRENT_TIMESTAMP)"""
        )
        return {r["trigger_product_id"] for r in rows}


async def set_promotion_showcase(promo_id: int, enabled: bool) -> None:
    """Turn the daily 3-bonus announcement on/off for one campaign, without
    touching the campaign itself — the "it's getting annoying" switch."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE promotions SET showcase_enabled = $2 WHERE id = $1", promo_id, enabled
        )


async def advance_promotion_showcase(promo_id: int, new_cursor: int, on_date) -> None:
    """Record that today's showcase went out and move the cursor along."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE promotions SET showcase_cursor = $2, last_showcase_date = $3 WHERE id = $1",
            promo_id, new_cursor, on_date,
        )
