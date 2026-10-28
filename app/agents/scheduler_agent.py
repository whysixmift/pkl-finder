import asyncio
from typing import Dict, Any, List
from app.agents.base_agent import BaseAgent
from app.agents.scraper_agent import scraper_agent
from app.agents.matching_agent import matching_agent
from app.agents.discovery_agent import discovery_agent
from app.agents.email_drafting_agent import email_drafting_agent
from app.database.db import async_session_maker
from app.config.settings import settings
from app.utils.logger import logger

class SchedulerAgent(BaseAgent):
    """Autonomous agent responsible for scheduled background crawls, AI matching, and task orchestration."""

    def __init__(self) -> None:
        super().__init__(
            agent_name="SchedulerAgent",
            feature_description="Autonomous Background Scheduler & End-to-End Pipeline Orchestrator"
        )

    async def execute_full_cycle(self) -> Dict[str, Any]:
        """Execute end-to-end autonomous pipeline:
        1. Scrape jobs from all platforms (ScraperAgent)
        2. Match jobs with user CVs (MatchingAgent)
        3. Discover new companies & recruitment emails (DiscoveryAgent)
        4. Auto-draft outreach emails for matching companies (EmailDraftingAgent)
        """
        start = self.mark_start()
        logger.info(f"[{self.agent_name}] Initiating scheduled autonomous cycle...")
        summary: Dict[str, Any] = {}

        try:
            # 1. Scrape jobs
            new_jobs = await scraper_agent.run()
            summary["scraped_new_jobs"] = len(new_jobs)

            # 2. Semantic matching
            recommendations = await matching_agent.match_jobs_for_users(new_jobs)
            summary["recommended_matches"] = len(recommendations)

            # 3. Company discovery and email crawling
            discovery_result = await discovery_agent.run()
            summary["discovery"] = discovery_result

            # 4. Auto-draft cold emails for top matches with recruiter emails
            drafts_created = 0
            async with async_session_maker() as session:
                for uid, job in recommendations:
                    if job.company_id:
                        draft = await email_drafting_agent.draft_email_for_job(
                            session=session,
                            user_id=uid,
                            company_id=job.company_id,
                            job_id=job.id
                        )
                        if draft:
                            drafts_created += 1
            summary["auto_drafts_created"] = drafts_created

            self.mark_success(start)
            logger.info(f"[{self.agent_name}] Scheduled autonomous cycle finished successfully: {summary}")
            return summary

        except Exception as e:
            self.mark_failure(start, e)
            logger.error(f"[{self.agent_name}] Scheduled autonomous cycle encountered an error: {e}", exc_info=True)
            return {"error": str(e)}

scheduler_agent = SchedulerAgent()
