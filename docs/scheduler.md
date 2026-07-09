# Scheduler System

The PKL Finder application uses `APScheduler` (Advanced Python Scheduler) to run scraping and matching cycles in the background.

## Background Scheduler Setup

The scheduler is initialized in `app/scheduler/jobs.py` using `AsyncIOScheduler`. This scheduler runs on the active event loop, preventing the need to spawn additional OS-level threads.

```python
scheduler = AsyncIOScheduler(timezone=settings.TIMEZONE)
```

The timezone is loaded from the `TIMEZONE` environment variable (default: `Asia/Jakarta`). This ensures scheduled tasks execute at consistent times on servers running in different timezones.

---

## Scheduled Task Registration

The background task is registered inside the `setup_scheduler()` function:

```python
scheduler.add_job(
    scheduled_scrape_and_match,
    trigger="interval",
    minutes=settings.CHECK_INTERVAL_MINUTES,
    id="job_scraping_job",
    replace_existing=True
)
scheduler.start()
```

* **Trigger Type**: `interval` triggers tasks at repeating intervals.
* **Interval Duration**: Configured via the `CHECK_INTERVAL_MINUTES` environment variable (default: 60 minutes).
* **Identifier**: `job_scraping_job` uniquely identifies the task. Specifying `replace_existing=True` prevents duplicate job registrations when restarting the application.

---

## Task Execution Flow

When the interval timer fires, the scheduler executes the `scheduled_scrape_and_match` routine:

1. **Initialization**: Creates a new `JobService` instance.
2. **Execution**: Calls `job_service.run_scraping_and_matching()`. This function runs the scrapers, matches jobs using the AI engine, and saves recommendations to the database.
3. **Notification Check**: If new recommended jobs are found, the scheduler initializes a standalone Telegram `Bot` client:
   ```python
   bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
   async with bot:
       # Loop over jobs and call bot.send_message()
   ```
4. **Rate Limit Handling**: To comply with Telegram's message rate limit (max 30 messages per second), the notification loop includes a 0.5-second delay between messages.
5. **Session Teardown**: Closing the `async with bot:` context manager shuts down the bot's internal HTTP connections, preventing connection leaks.
