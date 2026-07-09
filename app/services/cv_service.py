import io
from typing import Optional
from pypdf import PdfReader
from docx import Document
from sqlalchemy import select, desc
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

    async def save_cv(self, session: AsyncSession, filename: str, file_bytes: bytes) -> CVProfile:
        """Extract text and save CV profile to database."""
        if filename.lower().endswith(".pdf"):
            cv_text = self.extract_text_from_pdf(file_bytes)
        elif filename.lower().endswith(".docx"):
            cv_text = self.extract_text_from_docx(file_bytes)
        else:
            raise ValueError("Format file tidak didukung. Harap upload file PDF atau DOCX.")

        if not cv_text:
            raise ValueError("Gagal mengekstrak teks dari CV. File mungkin kosong atau tidak terbaca.")

        profile = CVProfile(filename=filename, cv_text=cv_text)
        session.add(profile)
        await session.commit()
        logger.info(f"Successfully saved new CV profile from file: {filename}")
        return profile

    async def get_active_cv_text(self, session: AsyncSession) -> Optional[str]:
        """Retrieve the latest uploaded CV text from database."""
        try:
            stmt = select(CVProfile).order_by(desc(CVProfile.uploaded_at)).limit(1)
            res = await session.execute(stmt)
            profile = res.scalar_one_or_none()
            if profile:
                return profile.cv_text
            return None
        except Exception as e:
            logger.error(f"Error fetching active CV text: {e}", exc_info=True)
            return None

# Shared service instance
cv_service = CVService()
