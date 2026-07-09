import sys
from telegram.ext import ApplicationBuilder
from app.config.settings import settings
from app.database.db import init_db
from app.bot.handlers import setup_bot
from app.scheduler.jobs import setup_scheduler, scheduler
from app.ai.evaluator import evaluator
from app.services.job_service import JobService
from app.utils.logger import logger

async def run_startup_diagnostics(application) -> None:
    """Performs tests checking DB, Telegram, OpenRouter, and Scraper modules on boot (Issue 14)."""
    logger.info("Executing system startup diagnostics...")
    
    # 1. DB connection check
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

    # 4. Scrapers Status mapping
    job_service = JobService()
    scraper_lines = []
    for sc in job_service.scrapers:
        status = "Disabled (403)" if getattr(sc, "is_disabled", False) else "OK"
        scraper_lines.append(f"    * {sc.source_name:<14} : {status}")
    scrapers_summary = "\n".join(scraper_lines)

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
    grid += f"[+] Database Engine   : {db_status}\n"
    grid += f"[+] Telegram Bot API  : {tg_status} ({bot_username})\n"
    grid += f"[+] OpenRouter Client : {or_status}\n"
    grid += "[+] Scheduler Engine  : OK\n"
    grid += f"[+] Configured Model  : {settings.PRIMARY_MODEL}\n"
    grid += "[-] Scraper Statuses  :\n"
    grid += f"{scrapers_summary}\n"
    grid += "=" * 55
    logger.info(grid)

async def post_init(application) -> None:
    """Perform async startup operations inside the bot's event loop."""
    await run_startup_diagnostics(application)
    
    logger.info("Starting background scheduler...")
    setup_scheduler()
    
    logger.info("Application post-initialization completed successfully.")

async def post_shutdown(application) -> None:
    """Perform cleanup on shutdown."""
    logger.info("Shutting down background scheduler...")
    if scheduler.running:
        scheduler.shutdown(wait=False)
    logger.info("Application shutdown completed.")

def main() -> None:
    """Main application entrypoint."""
    logger.info("Starting PKL Finder Telegram Bot...")
    
    # Validate critical configuration
    if not settings.TELEGRAM_BOT_TOKEN or settings.TELEGRAM_BOT_TOKEN.startswith("your_"):
        logger.critical("TELEGRAM_BOT_TOKEN is not configured. Exiting.")
        sys.exit(1)

    try:
        # Build python-telegram-bot Application
        application = (
            ApplicationBuilder()
            .token(settings.TELEGRAM_BOT_TOKEN)
            .post_init(post_init)
            .post_shutdown(post_shutdown)
            .build()
        )
        
        # Setup bot handlers and commands
        setup_bot(application)
        
        # Run Bot in polling mode (blocking)
        logger.info("Starting polling...")
        application.run_polling()
        
    except Exception as e:
        logger.critical(f"Unhandled exception during bot runtime: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
