import asyncio
from telegram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.config.settings import settings
from app.services.job_service import JobService
from app.bot.handlers import format_job_message, get_job_keyboard
from app.utils.logger import logger

# Initialize AsyncIOScheduler
scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)

# Lock to prevent concurrent overlapping executions (Issue 8)
_scheduler_lock = asyncio.Lock()

async def scheduled_scrape_and_match() -> None:
    """Background job executed periodically to scan for new internships."""
    if _scheduler_lock.locked():
        logger.warning("Scraping and matching job is already running. Skipping execution to prevent overlap.")
        return

    async with _scheduler_lock:
        logger.info("Executing scheduled scraping and matching task")
        try:
            # Initialize job service
            job_service = JobService()
            new_jobs = await job_service.run_scraping_and_matching()
            
            if new_jobs:
                logger.info(f"Scheduled task found {len(new_jobs)} new recommended jobs. Sending Telegram alerts.")
                bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
                
                # Using async context manager for standalone Bot connection lifecycle
                async with bot:
                    for job in new_jobs:
                        try:
                            text = format_job_message(job)
                            keyboard = get_job_keyboard(job, is_fav=False)
                            
                            await bot.send_message(
                                chat_id=settings.TELEGRAM_ADMIN_ID,
                                text=text,
                                reply_markup=keyboard,
                                parse_mode="HTML"
                            )
                            # Add brief sleep between notifications to respect Telegram rate limits
                            await asyncio.sleep(0.5)
                            
                        except Exception as send_err:
                            logger.error(f"Failed to send Telegram notification for job ID {job.id}: {send_err}")
            else:
                logger.info("Scheduled task finished. No new recommended jobs found.")
                
        except Exception as e:
            logger.error(f"Error during scheduled scraping execution: {e}", exc_info=True)

def setup_scheduler() -> None:
    """Setup and start the APScheduler background tasks."""
    try:
        # Add interval job
        scheduler.add_job(
            scheduled_scrape_and_match,
            trigger="interval",
            minutes=settings.CHECK_INTERVAL_MINUTES,
            id="job_scraping_job",
            replace_existing=True
        )
        scheduler.start()
        logger.info(f"Scheduler successfully started. Interval: {settings.CHECK_INTERVAL_MINUTES} minutes.")
    except Exception as e:
        logger.critical(f"Failed to initialize scheduler: {e}", exc_info=True)
        raise e
