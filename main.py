import sys
from telegram.ext import ApplicationBuilder
from app.config.settings import settings
from app.database.db import init_db
from app.bot.handlers import setup_bot
from app.scheduler.jobs import setup_scheduler, scheduler
from app.utils.logger import logger

async def post_init(application) -> None:
    """Perform async startup operations inside the bot's event loop."""
    logger.info("Initializing database tables...")
    await init_db()
    
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
        
    if not settings.OPENROUTER_API_KEY or settings.OPENROUTER_API_KEY.startswith("your_"):
        logger.warning("OPENROUTER_API_KEY is not configured. Fallback matching rules will be active.")

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
