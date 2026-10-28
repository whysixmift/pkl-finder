from typing import List, Dict, Any, Optional
from sqlalchemy import select
from app.agents.base_agent import BaseAgent
from app.database.db import async_session_maker
from app.database.models import Company
from app.services.discovery_service import discovery_engine
from app.services.crawler_service import career_crawler
from app.utils.logger import logger

class DiscoveryAgent(BaseAgent):
    """Autonomous agent responsible for discovering companies and harvesting recruitment emails."""

    def __init__(self) -> None:
        super().__init__(
            agent_name="DiscoveryAgent",
            feature_description="Autonomous Company & HR Recruitment Email Discovery Harvester"
        )

    async def run(self) -> Dict[str, Any]:
        """Discover new technology companies and crawl career portals for recruitment emails."""
        start = self.mark_start()
        discovered_count = 0
        crawled_count = 0

        try:
            logger.info(f"[{self.agent_name}] Starting company discovery cycle...")
            # 1. Discover new companies
            if not discovery_engine.is_disabled:
                await discovery_engine.discover_companies()

            # 2. Crawl existing companies for recruitment emails
            await career_crawler.crawl_all_companies()

            # Tally stats
            async with async_session_maker() as session:
                stmt_disc = select(Company).where(Company.is_discovered.is_(True))
                res_disc = await session.execute(stmt_disc)
                discovered_count = len(res_disc.scalars().all())

                stmt_email = select(Company).where(Company.recruitment_email.isnot(None))
                res_email = await session.execute(stmt_email)
                crawled_count = len(res_email.scalars().all())

            self.mark_success(start)
            return {
                "discovered_companies": discovered_count,
                "companies_with_email": crawled_count,
                "status": "success"
            }
        except Exception as e:
            self.mark_failure(start, e)
            return {
                "discovered_companies": discovered_count,
                "companies_with_email": crawled_count,
                "error": str(e)
            }

discovery_agent = DiscoveryAgent()
