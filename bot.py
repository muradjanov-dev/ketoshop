"""
Ketoshop
Telegram Marketplace Bot for organic & natural products in Uzbekistan
"""
import asyncio
import logging
import os

from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import MenuButtonWebApp, WebAppInfo

from config import BOT_TOKEN, ADMIN_IDS
from database import init_db, close_db, get_extra_admin_ids
from pg_storage import PostgresStorage
from activity import ActivityMiddleware
from subscription_gate import SubscriptionGateMiddleware
from state_guard import StateResetOnCommandMiddleware
import tg_safety

# Handlers
from handlers.webapp_data import router as webapp_data_router
from handlers.start import router as start_router
from handlers.catalog import router as catalog_router
from handlers.cart import router as cart_router
from handlers.seller import router as seller_router
from handlers.search import router as search_router
from handlers.reviews import router as reviews_router
from handlers.nps import router as nps_router
from handlers.delivery import router as delivery_router
from handlers.admin import router as admin_router
from handlers.broadcast_admin import router as broadcast_admin_router
from handlers.support_relay import router as support_relay_router
from link_guard import router as link_guard_router
from handlers.courier import router as courier_router
from bloggers import router as bloggers_router
from meta_leads import router as meta_leads_router
from meta_ads import router as meta_ads_router
from ad_sources import router as ad_sources_router
from ai_sales import router as ai_sales_router
from abandoned_cart import router as abandoned_cart_router
from retention import router as retention_router
from keto_explainer import router as keto_explainer_router
from stock_alerts import router as stock_alerts_router
from referral_stats import router as referral_stats_router
from retention_stats import router as retention_stats_router

from webapp_server import create_webapp


async def _register_commands(bot: Bot, logger) -> None:
    """Publish the "/" menu. Per-chat scopes are best-effort: a chat the bot
    has never seen (an admin who never messaged it, a blogger who hasn't
    started it yet) makes Telegram reject that one scope, which must not stop
    the others — the default list is what matters most."""
    from aiogram.types import BotCommandScopeDefault, BotCommandScopeChat
    from keyboards import BUYER_COMMANDS, ADMIN_COMMANDS, BLOGGER_COMMAND

    try:
        await bot.set_my_commands(BUYER_COMMANDS, scope=BotCommandScopeDefault())
        logger.info("Bot commands registered (%d for everyone)", len(BUYER_COMMANDS))
    except Exception:
        logger.exception("Failed to set default bot commands")

    for admin_id in ADMIN_IDS:
        try:
            await bot.set_my_commands(BUYER_COMMANDS + ADMIN_COMMANDS,
                                      scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception:
            logger.warning("Could not set admin commands for %s", admin_id, exc_info=True)

    try:
        from database import get_blogger_user_ids
        for blogger_id in await get_blogger_user_ids():
            if blogger_id in ADMIN_IDS:
                continue
            try:
                await bot.set_my_commands(BUYER_COMMANDS + [BLOGGER_COMMAND],
                                          scope=BotCommandScopeChat(chat_id=blogger_id))
            except Exception:
                logger.warning("Could not set blogger commands for %s", blogger_id, exc_info=True)
    except Exception:
        logger.exception("Failed to set blogger command scopes")


async def main():
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    logger = logging.getLogger(__name__)

    # Initialize database
    await init_db()
    # Qayta sotuv tables (retention.py) — before any handler can read an offer.
    import retention
    await retention.ensure_schema()
    logger.info("Database initialized")

    # Categories used to be a hardcoded list (locales.py); now admins can add
    # their own from either admin panel. Registers every DB category into
    # locales.CATEGORIES/get_category_name so the many existing call sites
    # (bot keyboards, webapp category tabs, admin.html dropdown) keep working
    # unchanged — create_category() keeps this in sync live after startup.
    from database import sync_categories_to_locales
    await sync_categories_to_locales()

    # Merge admins added at runtime (via the bot's "Add admin" flow) into the
    # hardcoded/env ADMIN_IDS list. Mutated in place (not reassigned) so
    # every module that already did `from config import ADMIN_IDS` sees the
    # update immediately — they all hold a reference to this same list.
    extra_admins = await get_extra_admin_ids()
    for admin_id in extra_admins:
        if admin_id not in ADMIN_IDS:
            ADMIN_IDS.append(admin_id)
    if extra_admins:
        logger.info("Loaded %d extra admin(s) from DB", len(extra_admins))

    from config import WEBAPP_URL
    logger.info("WEBAPP_URL = '%s'", WEBAPP_URL)

    # Initialize bot and dispatcher — Postgres-backed FSM so checkout state
    # survives bot restarts (users mid-cheque don't get wedged).
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    # Guarantees a message still arrives when a name/address/note interpolated
    # into an HTML template contains a bare "<" or "&" — see tg_safety.py.
    tg_safety.install(bot)
    storage = PostgresStorage()
    dp = Dispatcher(storage=storage)

    # Channel-subscription gate — must run before activity logging so a
    # blocked (not-yet-subscribed) attempt never counts as real engagement.
    gate_mw = SubscriptionGateMiddleware()
    dp.message.outer_middleware(gate_mw)
    dp.callback_query.outer_middleware(gate_mw)

    # Activity logging for the admin dashboard (daily active users + top
    # buttons/sections) — registered before routers so every update is seen.
    activity_mw = ActivityMiddleware()
    dp.message.outer_middleware(activity_mw)
    dp.callback_query.outer_middleware(activity_mw)

    # A slash command always wins over whatever "waiting for X" state a
    # stale flow left behind — see state_guard.py.
    dp.message.outer_middleware(StateResetOnCommandMiddleware())

    # Register the slash commands so typing "/" offers them — a real table of
    # contents for the bot (owner request 2026-09-01: "shu yerda tayyor
    # shortcutlar bo'lsin"). Three scopes, because the useful list differs per
    # audience: everyone gets the shop, admins additionally get the panel and
    # the operational commands, and each partner blogger gets /bloger. The
    # chat's menu button is taken by the Mini App, so this typed list plus the
    # persistent reply keyboard (keyboards.persistent_menu_keyboard) are the
    # two ways around.
    await _register_commands(bot, logger)

    # Warm the aksiya cache before the first update is handled — the synchronous
    # keyboard builders read it without awaiting (promotions.cached_active), so
    # a cold cache would hide the aksiya button until something else refreshed it.
    import promotions
    try:
        await promotions.get_active(force=True)
    except Exception:
        logger.exception("Failed to warm the promotion cache")

    # Point the persistent chat menu button at THIS deployment's Mini App.
    # Without this the button keeps whatever URL was set via BotFather, which
    # can silently point at a different deployment (the app shell loads but
    # every /api/* call hits the wrong server and fails initData auth).
    if WEBAPP_URL:
        try:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text="🌿 Do'kon",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            )
            logger.info("Chat menu button set to Mini App: %s", WEBAPP_URL)
        except Exception:
            logger.exception("Failed to set chat menu button")

    # Register routers (order matters! webapp_data first to catch web_app_data
    # messages; broadcast_admin right after start so its admin-only slash
    # commands (/nps_now, /tips_now, …) always win even if the admin happens
    # to be stuck mid-FSM in some other flow — e.g. search's "waiting_query"
    # state has no text filter, so without this a stray "/nps_test" typed
    # while mid-search gets swallowed as a search query instead of a command)
    # Group link guard first — a non-admin's link in a group is deleted
    # before any other handler can react to it (see link_guard.py).
    dp.include_router(link_guard_router)
    dp.include_router(webapp_data_router)
    dp.include_router(start_router)
    dp.include_router(broadcast_admin_router)
    # Meta lead inbox — admin-only /leads, /leads_test and the
    # "Bog'landim" callback. Registered high so its slash commands beat
    # any FSM state an admin happens to be stuck in, same reasoning as
    # broadcast_admin above.
    dp.include_router(meta_leads_router)
    # Reklama statistikasi — /reklama, /reklama_holat. Ads Manager
    # brauzerdagi FB profiliga bog'liq; bu esa token bilan ishlaydi,
    # shuning uchun statistika har doim qo'l ostida bo'ladi.
    dp.include_router(meta_ads_router)
    dp.include_router(ad_sources_router)
    dp.include_router(referral_stats_router)
    dp.include_router(retention_stats_router)
    dp.include_router(search_router)
    dp.include_router(catalog_router)
    dp.include_router(reviews_router)
    dp.include_router(nps_router)
    dp.include_router(cart_router)
    dp.include_router(delivery_router)
    dp.include_router(seller_router)
    dp.include_router(admin_router)
    dp.include_router(courier_router)
    # Bloger kabineti — /bloger and the partner's own stats screens.
    dp.include_router(bloggers_router)
    # /savat_eslatma and /sovga admin stats — before the AI/relay catch-alls.
    dp.include_router(abandoned_cart_router)
    dp.include_router(retention_router)
    dp.include_router(keto_explainer_router)
    # /ombor — current low / out-of-stock list.
    dp.include_router(stock_alerts_router)
    # Catch-all for free text that no state/handler above claimed — must stay
    # last so it never steals a message a real flow was waiting on.
    # AI sotuvchi support_relay dan oldin: hech kim ushlamagan matnni avval
    # AI ko'radi (suhbat yoqilgan bo'lsa), yoqilmagan bo'lsa relay oladi.
    dp.include_router(ai_sales_router)
    dp.include_router(support_relay_router)

    # Start aiohttp web server for Mini App
    runner = None
    port = int(os.getenv("PORT", 8080))
    try:
        app = create_webapp(bot, storage=storage)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info("WebApp server started on port %d", port)
    except Exception:
        logger.exception("Failed to start WebApp server")

    # Background scheduler for the 2-day tips broadcast.
    from broadcast import scheduler_loop
    broadcast_task = asyncio.create_task(scheduler_loop(bot))

    # Background scheduler for personalized recommendations (order-history based).
    from personal_recommend import scheduler_loop as reco_scheduler_loop
    reco_task = asyncio.create_task(reco_scheduler_loop(bot))

    # Daily full-DB backup, sent to every admin on Telegram.
    from db_backup import scheduler_loop as backup_scheduler_loop
    backup_task = asyncio.create_task(backup_scheduler_loop(bot))

    # Keto gamification — daily refresh of every user's pinned Keto card.
    from gamification import scheduler_loop as keto_scheduler_loop
    keto_task = asyncio.create_task(keto_scheduler_loop(bot))

    # Meta (Facebook/Instagram) Lead Ads -> Telegram. Polls the Graph API and
    # pushes every new Instant Form lead to all admins. Dormant no-op unless
    # META_PAGE_TOKEN is set, so this is safe to deploy before the token is.
    from meta_leads import scheduler_loop as meta_leads_scheduler_loop
    meta_leads_task = asyncio.create_task(meta_leads_scheduler_loop(bot))

    # Kunlik reklama xulosasi + "sarf yo'q" qorovuli.
    from meta_ads import scheduler_loop as meta_ads_scheduler_loop
    meta_ads_task = asyncio.create_task(meta_ads_scheduler_loop(bot))

    # Aksiya / Bonus — closes a campaign out the moment its window ends (so
    # bonuses stop being granted without anyone touching the admin panel) and
    # keeps the shared campaign cache warm. No-op tick when nothing is running.
    from promotions import scheduler_loop as promo_scheduler_loop
    promo_task = asyncio.create_task(promo_scheduler_loop(bot))

    # Kunlik qiziqish eslatmasi — one nudge a day about the product each
    # person keeps looking at, with the aksiya offer attached when that
    # product is part of it. Stands down on days another broadcast already
    # went out (see daily_interest.py).
    from daily_interest import scheduler_loop as interest_scheduler_loop
    interest_task = asyncio.create_task(interest_scheduler_loop(bot))

    # Maqsadlar — the daily-sales and monthly-profit targets. Records the
    # day's figures on every tick and pushes the standing to the ADMINS twice
    # a day; nothing here ever reaches a buyer.
    from targets import scheduler_loop as targets_scheduler_loop
    targets_task = asyncio.create_task(targets_scheduler_loop(bot))

    # Sovg'a kampaniyasi — 100 gr Eritritol on every 111 000 so'm+ order for
    # 30 days, starting with the 09:00 announcement. Books every delivered
    # gift into Chiqimlar.
    from gift_campaign import scheduler_loop as gift_scheduler_loop
    gift_task = asyncio.create_task(gift_scheduler_loop(bot))

    # Kuryer xarajati — 25 000 (Toshkent) / 5 000 (viloyat pochtasi) booked
    # into Chiqimlar for every delivered order, see delivery_costs.py.
    from delivery_costs import scheduler_loop as delivery_cost_loop
    delivery_cost_task = asyncio.create_task(delivery_cost_loop(bot))

    # Tashlab ketilgan savat — 3 h and 24 h reminders with one-tap checkout.
    from abandoned_cart import scheduler_loop as cart_reminder_loop
    cart_reminder_task = asyncio.create_task(cart_reminder_loop(bot))

    # Qayta sotuv — one personal message a week at most: "tugab qolmadimi?",
    # 2nd-order gift, win-back. Daily at 09:30, see retention.py.
    from retention import scheduler_loop as retention_loop
    retention_task = asyncio.create_task(retention_loop(bot))

    # One-off, 18.09.2026 17:30: explain Keto coins to everyone in plain words
    # and switch spending on (keto_explainer.py).
    from keto_explainer import scheduler_loop as keto_explainer_loop
    keto_explainer_task = asyncio.create_task(keto_explainer_loop(bot))

    # Ombor ogohlantirishlari — every admin hears when a product runs low (<5)
    # or out, each time it reaches that level, from any code path.
    from stock_alerts import scheduler_loop as stock_alerts_loop
    stock_alerts_task = asyncio.create_task(stock_alerts_loop(bot))

    # "Nima yangi" — this release's notes to every admin, once, in daytime.
    # Daily "Kun mahsuloti": one product to every buyer and to the channel.
    from product_of_day import scheduler_loop as product_of_day_loop
    product_of_day_task = asyncio.create_task(product_of_day_loop(bot))

    from release_notes import scheduler_loop as release_notes_loop
    release_notes_task = asyncio.create_task(release_notes_loop(bot))

    # Start polling
    logger.info("Bot started! Press Ctrl+C to stop.")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        broadcast_task.cancel()
        reco_task.cancel()
        backup_task.cancel()
        keto_task.cancel()
        promo_task.cancel()
        interest_task.cancel()
        targets_task.cancel()
        gift_task.cancel()
        delivery_cost_task.cancel()
        cart_reminder_task.cancel()
        retention_task.cancel()
        keto_explainer_task.cancel()
        stock_alerts_task.cancel()
        product_of_day_task.cancel()
        release_notes_task.cancel()
        meta_leads_task.cancel()
        meta_ads_task.cancel()
        if runner:
            await runner.cleanup()
        await close_db()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
