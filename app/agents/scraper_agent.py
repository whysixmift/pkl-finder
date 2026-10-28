import hashlib
from typing import List, Dict, Any, Tuple, Optional
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.agents.base_agent import BaseAgent
from app.config.settings import settings
from app.database.db import async_session_maker
from app.database.models import Job, Company
from app.scraper import (
    GlintsScraper,
    LinkedInScraper,
    IndeedScraper,
    JobstreetScraper,
    KalibrrScraper,
    GoogleJobsScraper,
)
from app.utils.logger import logger

class ScraperAgent(BaseAgent):
    """Autonomous agent responsible for job crawling across all supported job portals."""

    def __init__(self) -> None:
        super().__init__(
            agent_name="ScraperAgent",
            feature_description="Autonomous Multi-Platform Job Vacancy Scraper & Aggregator"
        )
        self.scrapers = [
            GlintsScraper(),
            LinkedInScraper(),
            IndeedScraper(),
            JobstreetScraper(),
            KalibrrScraper(),
            GoogleJobsScraper(),
        ]

    def _generate_job_key(self, url: str) -> str:
        """Generate a unique SHA-256 hash representing the job URL."""
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    async def run(self, keywords: Optional[List[str]] = None, locations: Optional[List[str]] = None) -> List[Job]:
        """Crawl jobs across all active scrapers, deduplicate, and persist new listings."""
        start = self.mark_start()
        kw_list = keywords or settings.keywords_list
        loc_list = locations or settings.locations_list

        all_raw_jobs: List[Dict[str, Any]] = []
        scraper_stats: Dict[str, Any] = {}

        try:
            for scraper in self.scrapers:
                if getattr(scraper, "is_disabled", False):
                    scraper_stats[scraper.source_name] = "Disabled (403)"
                    continue

                found_count = 0
                for kw in kw_list:
                    for loc in loc_list:
                        try:
                            jobs = await scraper.scrape(kw, loc)
                            if jobs:
                                all_raw_jobs.extend(jobs)
                                found_count += len(jobs)
                        except Exception as e:
                            logger.error(f"[{self.agent_name}] Error in {scraper.source_name} for '{kw}'-'{loc}': {e}")

                scraper_stats[scraper.source_name] = f"{found_count} jobs"

            # Deduplicate by URL
            unique_raw: Dict[str, Dict[str, Any]] = {}
            for j in all_raw_jobs:
                unique_raw[j["url"]] = j

            new_jobs: List[Job] = []

            async with async_session_maker() as session:
                for url, raw_job in unique_raw.items():
                    job_key = self._generate_job_key(url)

                    # Check if job already exists
                    stmt = select(Job).where(Job.job_key == job_key)
                    res = await session.execute(stmt)
                    if res.scalar_one_or_none():
                        continue

                    try:
                        async with session.begin_nested():
                            company_name = raw_job["company"]
                            comp_stmt = select(Company).where(Company.name == company_name)
                            comp_res = await session.execute(comp_stmt)
                            company = comp_res.scalar_one_or_none()

                            if not company:
                                company = Company(name=company_name)
                                session.add(company)
                                await session.flush()

                            job = Job(
                                job_key=job_key,
                                title=raw_job["title"],
                                company_id=company.id,
                                company_name=company_name,
                                location=raw_job["location"],
                                description=raw_job["description"],
                                url=raw_job["url"],
                                posted_date=raw_job["posted_date"],
                                source=raw_job["source"],
                                salary=raw_job.get("salary"),
                                work_mode=raw_job.get("work_mode"),
                                employment_type=raw_job.get("employment_type")
                            )
                            session.add(job)
                            await session.flush()
                            new_jobs.append(job)

                    except IntegrityError:
                        continue

                await session.commit()

            self.mark_success(start)
            logger.info(f"[{self.agent_name}] Scraped {len(all_raw_jobs)} total listings, stored {len(new_jobs)} new records.")
            return new_jobs

        except Exception as e:
            self.mark_failure(start, e)
            return []

scraper_agent = ScraperAgent()
