import json
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple
from sqlalchemy import select, func, desc
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from app.config.settings import settings
from app.database.db import async_session_maker
from app.database.models import Job, AIScore, Company, Favorite, History, CVProfile
from app.ai.evaluator import evaluator
from app.services.cv_service import cv_service
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

    async def run_scraping_and_matching(self) -> List[Tuple[int, Job]]:
        """Runs scrapers, saves global Job records, and matches them against user CVs.
        Returns:
            List[Tuple[user_id, Job]] newly recommended jobs per user.
        """
        logger.info("Starting automated job scraping and matching cycle")
        all_scraped_jobs: List[Dict[str, Any]] = []

        keywords = settings.keywords_list
        locations = settings.locations_list

        # Track scraper execution summary
        scraper_stats: Dict[str, Any] = {}

        # Run scrapers
        for scraper in self.scrapers:
            if getattr(scraper, "is_disabled", False):
                scraper_stats[scraper.source_name] = "disabled (403)"
                continue

            scraper_jobs_found = 0
            for kw in keywords:
                for loc in locations:
                    try:
                        logger.debug(f"Running {scraper.source_name} for '{kw}' in '{loc}'")
                        jobs = await scraper.scrape(kw, loc)
                        if jobs:
                            all_scraped_jobs.extend(jobs)
                            scraper_jobs_found += len(jobs)
                    except Exception as e:
                        logger.error(f"Error executing scraper {scraper.source_name} for '{kw}' in '{loc}': {e}", exc_info=True)
            
            if getattr(scraper, "is_disabled", False):
                scraper_stats[scraper.source_name] = "disabled (403)"
            else:
                scraper_stats[scraper.source_name] = f"{scraper_jobs_found} jobs"

        logger.info(f"Total jobs crawled from all sources before deduplication: {len(all_scraped_jobs)}")

        # Deduplicate results in memory based on URL
        unique_scraped: Dict[str, Dict[str, Any]] = {}
        for j in all_scraped_jobs:
            unique_scraped[j["url"]] = j

        newly_inserted_jobs: List[Job] = []
        duplicate_skips = 0

        # 1. Global Job Insertion (Scrape once, store once)
        async with async_session_maker() as session:
            for url, raw_job in unique_scraped.items():
                job_key = self._generate_job_key(url)

                # Check if job exists in DB
                stmt = select(Job).where(Job.job_key == job_key)
                res = await session.execute(stmt)
                existing_job = res.scalar_one_or_none()

                if existing_job:
                    continue

                try:
                    async with session.begin_nested():
                        # Fetch or create company record
                        company_name = raw_job["company"]
                        comp_stmt = select(Company).where(Company.name == company_name)
                        comp_res = await session.execute(comp_stmt)
                        company = comp_res.scalar_one_or_none()
                        
                        if not company:
                            company = Company(name=company_name)
                            session.add(company)
                            await session.flush()

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
                        newly_inserted_jobs.append(new_job)

                except IntegrityError:
                    duplicate_skips += 1
                    logger.debug(f"Duplicate job skipped: {raw_job['title']} at {raw_job['company']}")
                    continue

            await session.commit()

        logger.info(f"Stored {len(newly_inserted_jobs)} new global jobs in database.")

        if not newly_inserted_jobs:
            self._log_structured_summary(scraper_stats, len(unique_scraped), duplicate_skips, 0)
            return []

        # 2. User-Specific Matching (Perform matching afterwards)
        final_user_recommendations: List[Tuple[int, Job]] = []

        async with async_session_maker() as session:
            # Query all active users with custom CV profiles
            stmt = select(CVProfile)
            res = await session.execute(stmt)
            cv_profiles: List[CVProfile] = list(res.scalars().all())

            # Fallback to the main administrator if no users are registered yet
            if not cv_profiles:
                default_cv_text = "SMK Negeri 2 Bekasi Software Engineering. Python, C++, Embedded Systems, IoT, Robotics."
                mock_admin_cv = CVProfile(user_id=settings.TELEGRAM_ADMIN_ID, filename="default", cv_text=default_cv_text)
                cv_profiles = [mock_admin_cv]

            for cv_profile in cv_profiles:
                uid = cv_profile.user_id
                cv_text = cv_profile.cv_text
                logger.info(f"Processing AI matches for User ID: {uid}")

                for job in newly_inserted_jobs[:settings.MAX_JOBS_PER_RUN]:
                    try:
                        eval_result = await evaluator.evaluate_job(
                            title=job.title,
                            company=job.company_name,
                            location=job.location,
                            description=job.description,
                            cv_text=cv_text
                        )

                        # Insert user-specific AI score
                        ai_score = AIScore(
                            user_id=uid,
                            job_id=job.id,
                            recommended=eval_result.recommended,
                            score=eval_result.score,
                            reason=json.dumps(eval_result.reason),
                            matched_skills=json.dumps(eval_result.matched_skills),
                            missing_skills=json.dumps(eval_result.missing_skills),
                            summary=eval_result.summary,
                            company_category=eval_result.company_category,
                            work_mode=eval_result.work_mode,
                            priority=eval_result.priority
                        )
                        session.add(ai_score)

                        # Log to user history
                        history = History(
                            user_id=uid,
                            job_id=job.id,
                            action="evaluated",
                            details=f"Score: {ai_score.score}. Recommended: {ai_score.recommended}",
                        )
                        session.add(history)

                        if ai_score.recommended and ai_score.score >= settings.SCORE_THRESHOLD:
                            final_user_recommendations.append((uid, job))

                    except Exception as eval_err:
                        logger.error(f"Error matching job {job.title} for user {uid}: {eval_err}", exc_info=True)
                        history = History(
                            user_id=uid,
                            job_id=job.id,
                            action="evaluation_failed",
                            details=str(eval_err),
                        )
                        session.add(history)

            await session.commit()

        # Eager load relationships before returning
        async with async_session_maker() as session:
            loaded_recommendations = []
            for uid, j in final_user_recommendations:
                stmt = select(Job).options(selectinload(Job.ai_scores)).where(Job.id == j.id)
                res = await session.execute(stmt)
                job_loaded = res.scalar_one()
                loaded_recommendations.append((uid, job_loaded))

            self._log_structured_summary(scraper_stats, len(unique_scraped), duplicate_skips, len(loaded_recommendations))
            return loaded_recommendations

    def _log_structured_summary(self, scrapers: Dict[str, Any], unique_scraped: int, duplicate_skips: int, recommended: int) -> None:
        """Print clean concise summary report to INFO log."""
        summary = "\n" + "=" * 50 + "\n"
        summary += "SCRAPING CYCLE COMPLETE SUMMARY:\n\n"
        summary += "Scrapers Status:\n"
        for scraper_name, status in scrapers.items():
            summary += f"- {scraper_name:<12}: {status}\n"
        summary += f"\nUnique Crawled : {unique_scraped}\n"
        summary += f"Duplicates Skipped: {duplicate_skips}\n"
        summary += f"AI Recommended    : {recommended} notifications generated\n"
        summary += "=" * 50
        logger.info(summary)

    async def get_latest_jobs(self, user_id: int, limit: int = 10, recommended_only: bool = False) -> List[Job]:
        """Fetch newest jobs from database, populated with user-specific AI score matching."""
        async with async_session_maker() as session:
            stmt = select(Job).outerjoin(AIScore, (Job.id == AIScore.job_id) & (AIScore.user_id == user_id)).options(selectinload(Job.ai_scores)).order_by(desc(Job.created_at))
            
            if recommended_only:
                stmt = stmt.join(AIScore, (Job.id == AIScore.job_id) & (AIScore.user_id == user_id)).where(AIScore.recommended.is_(True))
                
            stmt = stmt.limit(limit)
            res = await session.execute(stmt)
            return list(res.scalars().all())

    async def get_favorites(self, user_id: int) -> List[Job]:
        """Fetch all favorite jobs for a user."""
        async with async_session_maker() as session:
            stmt = (
                select(Job)
                .options(selectinload(Job.ai_scores))
                .join(Favorite)
                .where(Favorite.user_id == user_id)
                .order_by(desc(Favorite.created_at))
            )
            res = await session.execute(stmt)
            return list(res.scalars().all())

    async def add_favorite(self, user_id: int, job_id: int) -> bool:
        """Add a job to favorites for a user."""
        async with async_session_maker() as session:
            stmt = select(Job).where(Job.id == job_id)
            res = await session.execute(stmt)
            job = res.scalar_one_or_none()
            if not job:
                return False

            # Check if already favorited
            fav_stmt = select(Favorite).where((Favorite.user_id == user_id) & (Favorite.job_id == job_id))
            fav_res = await session.execute(fav_stmt)
            existing = fav_res.scalar_one_or_none()
            
            if not existing:
                fav = Favorite(user_id=user_id, job_id=job_id)
                session.add(fav)
                history = History(user_id=user_id, job_id=job_id, action="favorited")
                session.add(history)
                await session.commit()
            return True

    async def remove_favorite(self, user_id: int, job_id: int) -> bool:
        """Remove a job from favorites for a user."""
        async with async_session_maker() as session:
            stmt = select(Favorite).where((Favorite.user_id == user_id) & (Favorite.job_id == job_id))
            res = await session.execute(stmt)
            fav = res.scalar_one_or_none()
            if fav:
                await session.delete(fav)
                history = History(user_id=user_id, job_id=job_id, action="unfavorited")
                session.add(history)
                await session.commit()
                return True
            return False

    async def get_history(self, user_id: int, limit: int = 20) -> List[Tuple[Job, History]]:
        """Fetch history log of recommended or interacted jobs for a user."""
        async with async_session_maker() as session:
            stmt = (
                select(Job, History)
                .join(History, Job.id == History.job_id)
                .options(selectinload(Job.ai_scores))
                .where(History.user_id == user_id)
                .order_by(desc(History.created_at))
                .limit(limit)
            )
            res = await session.execute(stmt)
            return list(res.all())

    async def get_db_stats(self, user_id: int) -> Dict[str, Any]:
        """Fetch database statistics for a user."""
        async with async_session_maker() as session:
            total_jobs_stmt = select(func.count(Job.id))
            rec_jobs_stmt = select(func.count(Job.id)).join(AIScore).where((AIScore.user_id == user_id) & (AIScore.recommended.is_(True)))
            fav_jobs_stmt = select(func.count(Favorite.id)).where(Favorite.user_id == user_id)
            
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

    async def recheck_all_jobs(self, user_id: int) -> List[Job]:
        """Re-runs AI evaluation on all existing jobs in the database for a specific user."""
        logger.info(f"Executing manual AI recheck on all database jobs for user {user_id}")
        updated_recommendations: List[Job] = []
        
        async with async_session_maker() as session:
            stmt = select(Job).options(selectinload(Job.ai_scores))
            res = await session.execute(stmt)
            jobs = res.scalars().all()

            # Load CV text for this user
            cv_text = await cv_service.get_active_cv_text(session, user_id)
            if not cv_text:
                cv_text = "SMK Negeri 2 Bekasi Software Engineering. Python, C++, Embedded Systems, IoT, Robotics."

            for job in jobs:
                try:
                    eval_result = await evaluator.evaluate_job(
                        title=job.title,
                        company=job.company_name,
                        location=job.location,
                        description=job.description,
                        cv_text=cv_text
                    )

                    # Check if user-specific AIScore already exists
                    score_stmt = select(AIScore).where((AIScore.user_id == user_id) & (AIScore.job_id == job.id))
                    score_res = await session.execute(score_stmt)
                    ai_score = score_res.scalar_one_or_none()

                    if ai_score:
                        ai_score.recommended = eval_result.recommended
                        ai_score.score = eval_result.score
                        ai_score.reason = json.dumps(eval_result.reason)
                        ai_score.matched_skills = json.dumps(eval_result.matched_skills)
                        ai_score.missing_skills = json.dumps(eval_result.missing_skills)
                        ai_score.summary = eval_result.summary
                        ai_score.company_category = eval_result.company_category
                        ai_score.work_mode = eval_result.work_mode
                        ai_score.priority = eval_result.priority
                        ai_score.evaluated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    else:
                        ai_score = AIScore(
                            user_id=user_id,
                            job_id=job.id,
                            recommended=eval_result.recommended,
                            score=eval_result.score,
                            reason=json.dumps(eval_result.reason),
                            matched_skills=json.dumps(eval_result.matched_skills),
                            missing_skills=json.dumps(eval_result.missing_skills),
                            summary=eval_result.summary,
                            company_category=eval_result.company_category,
                            work_mode=eval_result.work_mode,
                            priority=eval_result.priority
                        )
                        session.add(ai_score)

                    # Log to history
                    history_entry = History(
                        user_id=user_id,
                        job_id=job.id,
                        action="recheck_evaluated",
                        details=f"Recheck score: {eval_result.score}. Recommended: {eval_result.recommended}",
                    )
                    session.add(history_entry)

                    if eval_result.recommended and eval_result.score >= settings.SCORE_THRESHOLD:
                        updated_recommendations.append(job)

                except Exception as e:
                    logger.error(f"Error rechecking job {job.id} - {job.title} for user {user_id}: {e}", exc_info=True)

            await session.commit()
            
        return updated_recommendations
