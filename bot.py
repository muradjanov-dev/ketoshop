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
from handlers.courier import router as courier_router
from meta_leads import router as meta_leads_router
from meta_ads import router as meta_ads_router

from webapp_server import create_webapp


async def main():
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    logger = logging.getLogger(__name__)

    # Initialize database
    await init_db()
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
    dp.include_router(search_router)
    dp.include_router(catalog_router)
    dp.include_router(reviews_router)
    dp.include_router(nps_router)
    dp.include_router(cart_router)
    dp.include_router(delivery_router)
    dp.include_router(seller_router)
    dp.include_router(admin_router)
    dp.include_router(courier_router)
    # Catch-all for free text that no state/handler above claimed — must stay
    # last so it never steals a message a real flow was waiting on.
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

    # Keto musobaqasi (referral contest) — daily reminder while active, and
    # auto-finish (winner announcement) once the 7-day window is up. Dormant
    # (no-op tick) until an admin starts a contest via the admin panel.
    from referral_contest import scheduler_loop as contest_scheduler_loop
    contest_task = asyncio.create_task(contest_scheduler_loop(bot))

    # Start polling
    logger.info("Bot started! Press Ctrl+C to stop.")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        broadcast_task.cancel()
        reco_task.cancel()
        backup_task.cancel()
        keto_task.cancel()
        contest_task.cancel()
        meta_leads_task.cancel()
        meta_ads_task.cancel()
        if runner:
            await runner.cleanup()
        await close_db()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
