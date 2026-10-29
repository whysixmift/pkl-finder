import os
import re
from datetime import datetime, timezone
import io
from typing import Optional
from pypdf import PdfReader
from docx import Document
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import CVProfile
from app.utils.logger import logger

CV_STORAGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "cvs"
)

class CVService:
    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Sanitize filename to prevent path traversal."""
        clean = re.sub(r'[^a-zA-Z0-9_\.-]', '_', os.path.basename(name))
        return clean or "cv_document.pdf"

    @staticmethod
    def extract_text_from_pdf(file_bytes: bytes) -> str:
        """Extract all text pages from PDF bytes."""
        try:
            reader = PdfReader(io.BytesIO(file_bytes))
            text = ""
            for page in reader.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
            return text.strip()
        except Exception as e:
            logger.error(f"Error extracting text from PDF: {e}", exc_info=True)
            raise ValueError(f"Gagal membaca PDF: {str(e)}")

    @staticmethod
    def extract_text_from_docx(file_bytes: bytes) -> str:
        """Extract text paragraphs from DOCX bytes."""
        try:
            doc = Document(io.BytesIO(file_bytes))
            text = ""
            for paragraph in doc.paragraphs:
                if paragraph.text:
                    text += paragraph.text + "\n"
            return text.strip()
        except Exception as e:
            logger.error(f"Error extracting text from DOCX: {e}", exc_info=True)
            raise ValueError(f"Gagal membaca DOCX: {str(e)}")

    async def save_cv(self, session: AsyncSession, user_id: int, filename: str, file_bytes: bytes) -> CVProfile:
        """Extract text, persist the physical CV file to disk for email attachments, and save profile."""
        clean_name = self._sanitize_filename(filename)
        if clean_name.lower().endswith(".pdf"):
            cv_text = self.extract_text_from_pdf(file_bytes)
        elif clean_name.lower().endswith(".docx"):
            cv_text = self.extract_text_from_docx(file_bytes)
        else:
            raise ValueError("Format file tidak didukung. Harap upload file PDF atau DOCX.")

        if not cv_text:
            raise ValueError("Gagal mengekstrak teks dari CV. File mungkin kosong atau tidak terbaca.")

        # Persist physical file to disk
        os.makedirs(CV_STORAGE_DIR, exist_ok=True)
        saved_filename = f"{user_id}_{clean_name}"
        saved_file_path = os.path.join(CV_STORAGE_DIR, saved_filename)
        try:
            with open(saved_file_path, "wb") as f:
                f.write(file_bytes)
            logger.info(f"Persisted CV file to disk: {saved_file_path}")
        except Exception as e:
            logger.error(f"Failed to persist CV file on disk: {e}")
            saved_file_path = None

        # AI CV Intelligence Analysis
        try:
            from app.ai.evaluator import evaluator
            intel = await evaluator.analyze_cv_intelligence(cv_text)
        except Exception as e:
            logger.error(f"Error during AI CV analysis: {e}")
            intel = {}

        import json
        detected_roles_json = json.dumps(intel.get("recommended_roles", []))
        detected_skills_json = json.dumps(intel.get("top_skills", []))
        search_keywords_json = json.dumps(intel.get("search_keywords", []))
        candidate_summary = intel.get("summary", "")

        stmt = select(CVProfile).where(CVProfile.user_id == user_id)
        res = await session.execute(stmt)
        profile = res.scalar_one_or_none()

        if profile:
            profile.filename = clean_name
            profile.file_path = saved_file_path
            profile.cv_text = cv_text
            profile.detected_roles = detected_roles_json
            profile.detected_skills = detected_skills_json
            profile.search_keywords = search_keywords_json
            profile.candidate_summary = candidate_summary
            profile.uploaded_at = datetime.now(timezone.utc).replace(tzinfo=None)
        else:
            profile = CVProfile(
                user_id=user_id,
                filename=clean_name,
                file_path=saved_file_path,
                cv_text=cv_text,
                detected_roles=detected_roles_json,
                detected_skills=detected_skills_json,
                search_keywords=search_keywords_json,
                candidate_summary=candidate_summary
            )
            session.add(profile)

        await session.commit()
        logger.info(f"Successfully saved CV profile for user {user_id} from file: {filename}")
        return profile

    async def get_active_cv_profile(self, session: AsyncSession, user_id: int) -> Optional[CVProfile]:
        """Retrieve full active CV profile for user."""
        try:
            stmt = select(CVProfile).where(CVProfile.user_id == user_id)
            res = await session.execute(stmt)
            return res.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching active CV profile for user {user_id}: {e}", exc_info=True)
            return None

    async def get_active_cv_text(self, session: AsyncSession, user_id: int) -> Optional[str]:
        """Retrieve the latest uploaded CV text from database for a user."""
        profile = await self.get_active_cv_profile(session, user_id)
        return profile.cv_text if profile else None

# Shared service instance
cv_service = CVService()
