import json
import hashlib
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from sqlalchemy import select, func, desc
from sqlalchemy.orm import selectinload
from app.config.settings import settings
from app.database.db import async_session_maker
from app.database.models import Job, AIScore, Company, Favorite, History
from app.ai.evaluator import evaluator
from app.scraper import (
    GlintsScraper,
    LinkedInScraper,
    IndeedScraper,
    JobstreetScraper,
    KalibrrScraper,
    GoogleJobsScraper,
)
from app.utils.logger import logger

class JobService:
    def __init__(self) -> None:
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

    async def run_scraping_and_matching(self) -> List[Job]:
        """Runs scrapers, matches against candidate profile using AI, and saves to database."""
        logger.info("Starting automated job scraping and matching cycle")
        all_scraped_jobs: List[Dict[str, Any]] = []

        keywords = settings.keywords_list
        locations = settings.locations_list

        # Execute scrapers across keywords and locations
        for scraper in self.scrapers:
            for kw in keywords:
                for loc in locations:
                    try:
                        logger.info(f"Running {scraper.source_name} for '{kw}' in '{loc}'")
                        jobs = await scraper.scrape(kw, loc)
                        all_scraped_jobs.extend(jobs)
                    except Exception as e:
                        logger.error(f"Error executing scraper {scraper.source_name} for '{kw}' in '{loc}': {e}", exc_info=True)

        logger.info(f"Total jobs scraped from all sources before deduplication: {len(all_scraped_jobs)}")

        # Deduplicate results in memory based on URL
        unique_scraped: Dict[str, Dict[str, Any]] = {}
        for j in all_scraped_jobs:
            unique_scraped[j["url"]] = j

        logger.info(f"Unique jobs scraped: {len(unique_scraped)}")

        newly_recommended_jobs: List[Job] = []
        jobs_processed = 0

        async with async_session_maker() as session:
            for url, raw_job in unique_scraped.items():
                if jobs_processed >= settings.MAX_JOBS_PER_RUN:
                    logger.info(f"Reached MAX_JOBS_PER_RUN limit ({settings.MAX_JOBS_PER_RUN}). Stopping evaluation loop.")
                    break

                job_key = self._generate_job_key(url)

                # Check if job already exists in DB
                stmt = select(Job).where(Job.job_key == job_key)
                res = await session.execute(stmt)
                existing_job = res.scalar_one_or_none()

                if existing_job:
                    continue

                # Prepare new Job
                logger.info(f"Processing new job: {raw_job['title']} at {raw_job['company']}")
                
                # Fetch or create company record
                company_name = raw_job["company"]
                comp_stmt = select(Company).where(Company.name == company_name)
                comp_res = await session.execute(comp_stmt)
                company = comp_res.scalar_one_or_none()
                
                if not company:
                    company = Company(name=company_name)
                    session.add(company)
                    await session.flush() # Populate ID

                # Insert Job record
                new_job = Job(
                    job_key=job_key,
                    title=raw_job["title"],
                    company_id=company.id,
                    company_name=company_name,
                    location=raw_job["location"],
                    description=raw_job["description"],
                    url=raw_job["url"],
                    posted_date=raw_job["posted_date"],
                    source=raw_job["source"],
                    salary=raw_job["salary"],
                    work_mode=raw_job["work_mode"],
                    employment_type=raw_job["employment_type"],
                )
                session.add(new_job)
                await session.flush()

                # AI Matching evaluation
                try:
                    eval_result = await evaluator.evaluate_job(
                        title=new_job.title,
                        company=new_job.company_name,
                        location=new_job.location,
                        description=new_job.description,
                    )

                    ai_score = AIScore(
                        job_id=new_job.id,
                        recommended=eval_result.recommended,
                        score=eval_result.score,
                        reason=json.dumps(eval_result.reason),
                        matched_skills=json.dumps(eval_result.matched_skills),
                        missing_skills=json.dumps(eval_result.missing_skills),
                        summary=eval_result.summary,
                    )
                    session.add(ai_score)

                    # Create History log
                    history_entry = History(
                        job_id=new_job.id,
                        action="evaluated",
                        details=f"Evaluated with score: {ai_score.score}. Recommended: {ai_score.recommended}",
                    )
                    session.add(history_entry)

                    if ai_score.recommended and ai_score.score >= settings.SCORE_THRESHOLD:
                        newly_recommended_jobs.append(new_job)

                except Exception as eval_err:
                    logger.error(f"Error evaluating job {new_job.title} with AI: {eval_err}", exc_info=True)
                    # Create failed history log
                    history_entry = History(
                        job_id=new_job.id,
                        action="evaluation_failed",
                        details=str(eval_err),
                    )
                    session.add(history_entry)

                jobs_processed += 1

            await session.commit()

        # Eager load AI scores for recommendations before returning
        async with async_session_maker() as session:
            final_recommended = []
            for j in newly_recommended_jobs:
                stmt = select(Job).options(selectinload(Job.ai_score)).where(Job.id == j.id)
                res = await session.execute(stmt)
                final_recommended.append(res.scalar_one())

            return final_recommended

    async def get_latest_jobs(self, limit: int = 10, recommended_only: bool = False) -> List[Job]:
        """Fetch newest jobs from database."""
        async with async_session_maker() as session:
            stmt = select(Job).options(selectinload(Job.ai_score)).order_by(desc(Job.created_at))
            
            if recommended_only:
                stmt = stmt.join(AIScore).where(AIScore.recommended == True)
                
            stmt = stmt.limit(limit)
            res = await session.execute(stmt)
            return list(res.scalars().all())

    async def get_favorites(self) -> List[Job]:
        """Fetch all favorite jobs."""
        async with async_session_maker() as session:
            stmt = select(Job).options(selectinload(Job.ai_score)).join(Favorite).order_by(desc(Favorite.created_at))
            res = await session.execute(stmt)
            return list(res.scalars().all())

    async def add_favorite(self, job_id: int) -> bool:
        """Add a job to favorites."""
        async with async_session_maker() as session:
            # Check if job exists
            stmt = select(Job).where(Job.id == job_id)
            res = await session.execute(stmt)
            job = res.scalar_one_or_none()
            if not job:
                return False

            # Check if already favorite
            fav_stmt = select(Favorite).where(Favorite.job_id == job_id)
            fav_res = await session.execute(fav_stmt)
            existing = fav_res.scalar_one_or_none()
            
            if not existing:
                fav = Favorite(job_id=job_id)
                session.add(fav)
                history = History(job_id=job_id, action="favorited")
                session.add(history)
                await session.commit()
            return True

    async def remove_favorite(self, job_id: int) -> bool:
        """Remove a job from favorites."""
        async with async_session_maker() as session:
            stmt = select(Favorite).where(Favorite.job_id == job_id)
            res = await session.execute(stmt)
            fav = res.scalar_one_or_none()
            if fav:
                await session.delete(fav)
                history = History(job_id=job_id, action="unfavorited")
                session.add(history)
                await session.commit()
                return True
            return False

    async def get_history(self, limit: int = 20) -> List[Tuple[Job, History]]:
        """Fetch history log of recommended or interacted jobs."""
        async with async_session_maker() as session:
            stmt = (
                select(Job, History)
                .join(History, Job.id == History.job_id)
                .options(selectinload(Job.ai_score))
                .order_by(desc(History.created_at))
                .limit(limit)
            )
            res = await session.execute(stmt)
            return list(res.all())

    async def get_db_stats(self) -> Dict[str, Any]:
        """Fetch database statistics."""
        async with async_session_maker() as session:
            total_jobs_stmt = select(func.count(Job.id))
            rec_jobs_stmt = select(func.count(Job.id)).join(AIScore).where(AIScore.recommended == True)
            fav_jobs_stmt = select(func.count(Favorite.id))
            
            total_jobs = await session.execute(total_jobs_stmt)
            rec_jobs = await session.execute(rec_jobs_stmt)
            fav_jobs = await session.execute(fav_jobs_stmt)

            # Query source counts
            source_stmt = select(Job.source, func.count(Job.id)).group_by(Job.source)
            sources = await session.execute(source_stmt)
            source_breakdown = {source: count for source, count in sources.all()}

            return {
                "total_jobs": total_jobs.scalar() or 0,
                "recommended_jobs": rec_jobs.scalar() or 0,
                "favorites_count": fav_jobs.scalar() or 0,
                "source_breakdown": source_breakdown,
            }

    async def recheck_all_jobs(self) -> List[Job]:
        """Re-runs AI evaluation on all existing jobs in the database."""
        logger.info("Executing manual AI recheck on all database jobs")
        updated_recommendations: List[Job] = []
        
        async with async_session_maker() as session:
            # Fetch all jobs
            stmt = select(Job).options(selectinload(Job.ai_score))
            res = await session.execute(stmt)
            jobs = res.scalars().all()

            for job in jobs:
                try:
                    eval_result = await evaluator.evaluate_job(
                        title=job.title,
                        company=job.company_name,
                        location=job.location,
                        description=job.description,
                    )

                    if job.ai_score:
                        job.ai_score.recommended = eval_result.recommended
                        job.ai_score.score = eval_result.score
                        job.ai_score.reason = json.dumps(eval_result.reason)
                        job.ai_score.matched_skills = json.dumps(eval_result.matched_skills)
                        job.ai_score.missing_skills = json.dumps(eval_result.missing_skills)
                        job.ai_score.summary = eval_result.summary
                        job.ai_score.evaluated_at = datetime.utcnow()
                    else:
                        ai_score = AIScore(
                            job_id=job.id,
                            recommended=eval_result.recommended,
                            score=eval_result.score,
                            reason=json.dumps(eval_result.reason),
                            matched_skills=json.dumps(eval_result.matched_skills),
                            missing_skills=json.dumps(eval_result.missing_skills),
                            summary=eval_result.summary,
                        )
                        session.add(ai_score)

                    # Log to history
                    history_entry = History(
                        job_id=job.id,
                        action="recheck_evaluated",
                        details=f"Recheck score: {eval_result.score}. Recommended: {eval_result.recommended}",
                    )
                    session.add(history_entry)

                    if eval_result.recommended and eval_result.score >= settings.SCORE_THRESHOLD:
                        updated_recommendations.append(job)

                except Exception as e:
                    logger.error(f"Error rechecking job {job.id} - {job.title}: {e}", exc_info=True)

            await session.commit()
            
        return updated_recommendations
