from typing import Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from app.agents.base_agent import BaseAgent
from app.database.models import CVProfile
from app.services.cv_service import cv_service
from app.utils.logger import logger

class CVAgent(BaseAgent):
    """Autonomous agent responsible for CV ingestion, storage, text extraction, and skill profiling."""

    def __init__(self) -> None:
        super().__init__(
            agent_name="CVAgent",
            feature_description="CV Document Ingestion, Physical Attachment Storage & Skill Profiler"
        )

    async def ingest_cv(
        self,
        session: AsyncSession,
        user_id: int,
        filename: str,
        file_bytes: bytes
    ) -> CVProfile:
        """Process CV upload, extract text, persist physical file to disk, and save profile."""
        start = self.mark_start()
        try:
            profile = await cv_service.save_cv(session, user_id, filename, file_bytes)
            self.mark_success(start)
            return profile
        except Exception as e:
            self.mark_failure(start, e)
            raise e

    async def get_user_cv(self, session: AsyncSession, user_id: int) -> Optional[CVProfile]:
        """Fetch candidate's active CV profile including file attachment path."""
        start = self.mark_start()
        try:
            profile = await cv_service.get_active_cv_profile(session, user_id)
            self.mark_success(start)
            return profile
        except Exception as e:
            self.mark_failure(start, e)
            return None

cv_agent = CVAgent()
