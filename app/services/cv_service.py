from datetime import datetime, timezone
import io
from typing import Optional
from pypdf import PdfReader
from docx import Document
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import CVProfile
from app.utils.logger import logger

class CVService:
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
        """Extract text and save or update CV profile to database for a user."""
        if filename.lower().endswith(".pdf"):
            cv_text = self.extract_text_from_pdf(file_bytes)
        elif filename.lower().endswith(".docx"):
            cv_text = self.extract_text_from_docx(file_bytes)
        else:
            raise ValueError("Format file tidak didukung. Harap upload file PDF atau DOCX.")

        if not cv_text:
            raise ValueError("Gagal mengekstrak teks dari CV. File mungkin kosong atau tidak terbaca.")

        stmt = select(CVProfile).where(CVProfile.user_id == user_id)
        res = await session.execute(stmt)
        profile = res.scalar_one_or_none()

        if profile:
            profile.filename = filename
            profile.cv_text = cv_text
            profile.uploaded_at = datetime.now(timezone.utc).replace(tzinfo=None)
        else:
            profile = CVProfile(user_id=user_id, filename=filename, cv_text=cv_text)
            session.add(profile)

        await session.commit()
        logger.info(f"Successfully saved CV profile for user {user_id} from file: {filename}")
        return profile

    async def get_active_cv_text(self, session: AsyncSession, user_id: int) -> Optional[str]:
        """Retrieve the latest uploaded CV text from database for a user."""
        try:
            stmt = select(CVProfile).where(CVProfile.user_id == user_id)
            res = await session.execute(stmt)
            profile = res.scalar_one_or_none()
            if profile:
                return profile.cv_text
            return None
        except Exception as e:
            logger.error(f"Error fetching active CV text for user {user_id}: {e}", exc_info=True)
            return None

# Shared service instance
cv_service = CVService()
