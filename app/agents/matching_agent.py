import json
from typing import List, Tuple, Dict, Any, Optional
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agents.base_agent import BaseAgent
from app.config.settings import settings
from app.database.db import async_session_maker
from app.database.models import Job, AIScore, History, CVProfile
from app.ai.evaluator import evaluator
from app.utils.logger import logger

class MatchingAgent(BaseAgent):
    """Autonomous agent responsible for semantic matching and scoring of jobs against CVs."""

    def __init__(self) -> None:
        super().__init__(
            agent_name="MatchingAgent",
            feature_description="Semantic AI Job Matcher & Scoring Engine (OpenRouter + Regex Fallback)"
        )

    async def match_jobs_for_users(self, jobs: List[Job], target_user_id: Optional[int] = None) -> List[Tuple[int, Job]]:
        """Evaluate a list of jobs against all registered user CVs, persisting AIScore records."""
        start = self.mark_start()
        recommendations: List[Tuple[int, Job]] = []

        if not jobs:
            self.mark_success(start)
            return []

        try:
            async with async_session_maker() as session:
                # Fetch user CV profiles
                if target_user_id:
                    stmt = select(CVProfile).where(CVProfile.user_id == target_user_id)
                else:
                    stmt = select(CVProfile)
                res = await session.execute(stmt)
                cv_profiles: List[CVProfile] = list(res.scalars().all())

                if not cv_profiles:
                    # Fallback to Admin profile
                    default_cv_text = "SMK Negeri 2 Bekasi Software Engineering. Python, C++, Embedded Systems, IoT, Robotics."
                    cv_profiles = [CVProfile(user_id=target_user_id or settings.TELEGRAM_ADMIN_ID, filename="default", cv_text=default_cv_text)]

                for cv_profile in cv_profiles:
                    uid = cv_profile.user_id
                    cv_text = cv_profile.cv_text

                    for job in jobs[:settings.MAX_JOBS_PER_RUN]:
                        try:
                            # Check cache
                            cache_stmt = select(AIScore).where((AIScore.user_id == uid) & (AIScore.job_id == job.id))
                            cache_res = await session.execute(cache_stmt)
                            existing_score = cache_res.scalar_one_or_none()

                            if existing_score:
                                if existing_score.recommended and existing_score.score >= settings.SCORE_THRESHOLD:
                                    recommendations.append((uid, job))
                                continue

                            eval_result = await evaluator.evaluate_job(
                                title=job.title,
                                company=job.company_name,
                                location=job.location,
                                description=job.description,
                                cv_text=cv_text
                            )

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

                            history = History(
                                user_id=uid,
                                job_id=job.id,
                                action="evaluated",
                                details=f"Score: {ai_score.score}. Recommended: {ai_score.recommended}",
                            )
                            session.add(history)

                            if ai_score.recommended and ai_score.score >= settings.SCORE_THRESHOLD:
                                recommendations.append((uid, job))

                        except Exception as e:
                            logger.error(f"[{self.agent_name}] Error matching job {job.id} for user {uid}: {e}")

                await session.commit()

            # Eager load relationships
            loaded: List[Tuple[int, Job]] = []
            async with async_session_maker() as session:
                for uid, j in recommendations:
                    stmt = select(Job).options(selectinload(Job.ai_scores)).where(Job.id == j.id)
                    res = await session.execute(stmt)
                    j_loaded = res.scalar_one_or_none()
                    if j_loaded:
                        loaded.append((uid, j_loaded))

            self.mark_success(start)
            return loaded

        except Exception as e:
            self.mark_failure(start, e)
            return []

matching_agent = MatchingAgent()
