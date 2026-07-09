import unittest
from app.scheduler.jobs import scheduler, setup_scheduler
from app.config.settings import settings

class TestScheduler(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        """Clear existing jobs and make sure scheduler is in clean state."""
        if scheduler.running:
            scheduler.shutdown(wait=False)
        scheduler.remove_all_jobs()

    async def asyncTearDown(self) -> None:
        """Ensure scheduler is shutdown after tests."""
        if scheduler.running:
            scheduler.shutdown(wait=False)

    async def test_setup_scheduler_registers_job(self) -> None:
        """Test that setup_scheduler adds the scraping job with correct configurations."""
        setup_scheduler()
        
        # Verify job is successfully scheduled
        job = scheduler.get_job("job_scraping_job")
        self.assertIsNotNone(job)
        self.assertEqual(job.id, "job_scraping_job")
        
        # Verify configured interval matches settings in seconds
        expected_seconds = settings.CHECK_INTERVAL_MINUTES * 60
        self.assertEqual(job.trigger.interval.seconds, expected_seconds)

if __name__ == "__main__":
    unittest.main()
