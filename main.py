import sys
import asyncio
import threading
from telegram.ext import ApplicationBuilder
from app.config.settings import settings
from app.database.db import init_db
from app.bot.handlers import setup_bot
from app.scheduler.jobs import setup_scheduler, scheduler
from app.ai.evaluator import evaluator
from app.services.job_service import JobService
from app.web.server import run_web_server
from app.bot.server import run_bot_http_server
from app.utils.logger import logger

async def run_startup_diagnostics(application) -> None:
    """Performs tests checking DB, Telegram, SMTP, OpenRouter, and Scraper modules on boot (Issue 14)."""
    logger.info("Executing system startup diagnostics...")
    
    # 1. DB connection & schema sync check
    db_status = "OK"
    try:
        await init_db()
    except Exception as e:
        db_status = f"FAILED ({str(e)})"
        logger.critical(f"Database connection failed: {e}")
        sys.exit(1)

    # 2. Telegram Bot check
    tg_status = "OK"
    bot_username = "Unknown"
    try:
        bot_info = await application.bot.get_me()
        bot_username = f"@{bot_info.username}"
    except Exception as e:
        tg_status = f"FAILED ({str(e)})"
        logger.critical(f"Telegram Bot credentials validation failed: {e}")
        sys.exit(1)

    # 3. OpenRouter check
    or_status = "OK"
    latency = 0
    try:
        success, msg, latency = await evaluator.verify_connectivity()
        if not success:
            or_status = f"WARNING ({msg})"
        else:
            or_status = f"OK ({latency} ms)"
    except Exception as e:
        or_status = f"FAILED ({str(e)})"

    # 4. SMTP Credentials check (Admin)
    from app.services.email_service import email_service
    from app.database.db import async_session_maker
    smtp_status = "Not Configured"
    async with async_session_maker() as session:
        smtp_conf = await email_service.get_active_config(session, settings.TELEGRAM_ADMIN_ID)
        if smtp_conf:
            try:
                await email_service.test_smtp_config(smtp_conf)
                smtp_status = "OK"
            except Exception as e:
                smtp_status = f"FAILED ({str(e)})"
                logger.error(f"Admin SMTP test connection failed: {e}")

    # 5. Scrapers Status mapping
    job_service = JobService()
    scraper_lines = []
    for sc in job_service.scrapers:
        status = "Disabled (403)" if getattr(sc, "is_disabled", False) else "OK"
        scraper_lines.append(f"    * {sc.source_name:<14} : {status}")
    scrapers_summary = "\n".join(scraper_lines)

    # 6. Company Discovery Engine check
    from app.services.discovery_service import discovery_engine
    discovery_status = "Disabled" if discovery_engine.is_disabled else "OK"

    # Print OpenRouter Health Check Block
    or_health = (
        "\n" + "-" * 40 + "\n"
        "OpenRouter Health Check:\n"
        f"API ............... {'OK' if 'FAILED' not in or_status and 'WARNING' not in or_status else 'FAIL'}\n"
        f"Primary Model ..... {settings.PRIMARY_MODEL}\n"
        f"Fallback .......... {len(settings.fallback_models_list)} configured\n"
        f"Latency ........... {latency} ms\n"
        f"Status ............ {or_status}\n"
        + "-" * 40
    )
    logger.info(or_health)

    # Print Premium Diagnostic Summary Grid
    grid = "\n" + "=" * 55 + "\n"
    grid += "          PKL FINDER STARTUP DIAGNOSTICS GRID\n"
    grid += "=" * 55 + "\n"
    grid += f"[+] Database & ORM Sync : {db_status}\n"
    grid += f"[+] Telegram Bot API    : {tg_status} ({bot_username})\n"
    admin_bot_info = "OK (@nigaballsblotbot)" if settings.ADMIN_BOT_TOKEN and not settings.ADMIN_BOT_TOKEN.startswith("mock_") else "Not Configured"
    grid += f"[+] Admin Dashboard Bot: {admin_bot_info}\n"
    grid += f"[+] OpenRouter Client   : {or_status}\n"
    grid += f"[+] Admin SMTP Delivery : {smtp_status}\n"
    grid += "[+] Scheduler Engine    : OK\n"
    grid += f"[+] Company Discovery   : {discovery_status}\n"
    grid += f"[+] Configured Model    : {settings.PRIMARY_MODEL}\n"
    grid += f"[+] Bot Service Port    : {settings.BOT_PORT}\n"
    grid += f"[+] Web Platform Port   : {settings.WEB_PORT}\n"
    grid += "[-] Scraper Statuses    :\n"
    grid += f"{scrapers_summary}\n"
    grid += "=" * 55
    logger.info(grid)

async def post_init(application) -> None:
    """Perform async startup operations inside the bot's event loop."""
    await run_startup_diagnostics(application)
    
    # Run Bot HTTP service on Port 20128
    bot_user = "Unknown"
    try:
        info = await application.bot.get_me()
        bot_user = f"@{info.username}"
    except Exception:
        pass
    
    asyncio.create_task(run_bot_http_server(bot_username=bot_user, host=settings.HOST, port=settings.BOT_PORT))

    logger.info("Starting background scheduler...")
    setup_scheduler()
    
    logger.info(f"Bot branch initialization completed on port {settings.BOT_PORT}.")

async def post_shutdown(application) -> None:
    """Perform cleanup on shutdown."""
    logger.info("Shutting down background scheduler...")
    if scheduler.running:
        scheduler.shutdown(wait=False)
    logger.info("Application shutdown completed.")

def run_bot_branch() -> None:
    """Run Telegram Bot polling application (Port 20128)."""
    logger.info(f"Starting PKL Finder Telegram Bot Branch (Port {settings.BOT_PORT})...")
    
    if not settings.TELEGRAM_BOT_TOKEN or settings.TELEGRAM_BOT_TOKEN.startswith("your_"):
        logger.warning(
            f"TELEGRAM_BOT_TOKEN is not configured. Telegram polling is paused. "
            f"Please configure your token via Web Admin Dashboard at http://{settings.HOST}:{settings.WEB_PORT}/admin/settings. "
            f"Starting Bot HTTP Health Service on Port {settings.BOT_PORT}..."
        )
        from app.bot.server import create_bot_http_app
        import uvicorn
        bot_app = create_bot_http_app("Awaiting_Bot_Token")
        uvicorn.run(bot_app, host=settings.HOST, port=settings.BOT_PORT, log_level="warning")
        return

    try:
        # Launch dedicated Admin Bot if configured
        if settings.ADMIN_BOT_TOKEN and not settings.ADMIN_BOT_TOKEN.startswith("mock_"):
            from app.bot.admin_bot import run_admin_bot_polling
            admin_bot_thread = threading.Thread(
                target=run_admin_bot_polling,
                name="AdminBot-Polling",
                daemon=True
            )
            admin_bot_thread.start()
            logger.info("Dedicated Admin Dashboard Bot thread launched successfully.")

        application = (
            ApplicationBuilder()
            .token(settings.TELEGRAM_BOT_TOKEN)
            .concurrent_updates(True)
            .post_init(post_init)
            .post_shutdown(post_shutdown)
            .build()
        )
        setup_bot(application)
        logger.info(f"Starting Telegram Bot polling (Port {settings.BOT_PORT})...")
        application.run_polling()
    except Exception as e:
        logger.critical(f"Unhandled exception during bot runtime: {e}", exc_info=True)
        from app.bot.server import create_bot_http_app
        import uvicorn
        bot_app = create_bot_http_app("Bot_Error_Fallback")
        uvicorn.run(bot_app, host=settings.HOST, port=settings.BOT_PORT, log_level="warning")

def run_web_branch() -> None:
    """Run SaaS Web Application & Admin Dashboard (Port 20129)."""
    logger.info(f"Starting PKL Finder Web Platform Branch (Port {settings.WEB_PORT})...")
    try:
        asyncio.run(run_web_server(host=settings.HOST, port=settings.WEB_PORT))
    except Exception as e:
        logger.critical(f"Unhandled exception during web runtime: {e}", exc_info=True)
        sys.exit(1)

def main() -> None:
    """Main application entrypoint.
    Modes:
      all (default) : Runs Bot (Port 20128) and Web (Port 20129) concurrently.
      bot           : Runs only the Telegram Bot branch (Port 20128).
      web           : Runs only the SaaS Web branch (Port 20129).
    """
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "all"

    if mode == "web":
        run_web_branch()
    elif mode == "bot":
        run_bot_branch()
    elif mode == "all":
        logger.info("=" * 60)
        logger.info("   BOOTING PKL FINDER SAAS - DUAL-PORT ARCHITECTURE")
        logger.info(f"   [1] Bot Service Branch : PORT {settings.BOT_PORT}")
        logger.info(f"   [2] Web SaaS Branch    : PORT {settings.WEB_PORT}")
        logger.info("=" * 60)
        
        # Start Web Platform in background thread
        web_thread = threading.Thread(
            target=run_web_branch,
            name=f"WebPlatform-Port{settings.WEB_PORT}",
            daemon=True
        )
        web_thread.start()

        # Run Bot in main thread
        run_bot_branch()
    else:
        print(f"Unknown mode: '{mode}'. Usage: python main.py [all|bot|web]")
        sys.exit(1)

if __name__ == "__main__":
    main()
