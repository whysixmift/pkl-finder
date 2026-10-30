import os
import json
from typing import Optional, List, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base_agent import BaseAgent
from app.ai.evaluator import evaluator
from app.database.models import EmailQueue, Company, Job, CVProfile
from app.services.cv_service import cv_service
from app.services.email_service import email_service
from app.utils.contact_parser import extract_clean_emails
from app.utils.logger import logger

class EmailDraftingAgent(BaseAgent):
    """Autonomous agent responsible for crafting personalized cold emails based on candidate CV and company data."""

    def __init__(self) -> None:
        super().__init__(
            agent_name="EmailDraftingAgent",
            feature_description="Personalized Outreach Cold Email Generator with Auto-CV Attachment"
        )

    async def draft_email_for_job(
        self,
        session: AsyncSession,
        user_id: int,
        company_id: int,
        job_id: Optional[int] = None,
        recipient_email: Optional[str] = None
    ) -> Optional[EmailQueue]:
        """Generate a personalized application email tailored specifically to the company and CV, and queue it with CV attachment."""
        start = self.mark_start()
        try:
            # 1. Fetch Company details
            comp_stmt = select(Company).where(Company.id == company_id)
            comp_res = await session.execute(comp_stmt)
            company = comp_res.scalar_one_or_none()
            if not company:
                self.mark_failure(start, ValueError("Company not found"))
                return None

            # 2. Fetch Job details if provided
            job: Optional[Job] = None
            if job_id:
                job_stmt = select(Job).where(Job.id == job_id)
                job_res = await session.execute(job_stmt)
                job = job_res.scalar_one_or_none()

            # 3. Fetch candidate's active CV
            cv_profile = await cv_service.get_active_cv_profile(session, user_id)
            cv_text = cv_profile.cv_text if cv_profile else ""
            cv_attachment = [cv_profile.file_path] if (cv_profile and cv_profile.file_path and os.path.exists(cv_profile.file_path)) else None

            # 4. Resolve recipient email with smart validation & zero dummy fallback
            target_email = recipient_email
            if not target_email and job and job.description:
                detected_emails = extract_clean_emails(job.description)
                if detected_emails:
                    target_email = detected_emails[0]
                    company.recruitment_email = target_email
                    await session.flush()

            if not target_email and company.recruitment_email:
                if not any(b in company.recruitment_email.lower() for b in ["perusahaan.co.id", "example.com", "noreply"]):
                    target_email = company.recruitment_email

            if not target_email:
                # Never inject fake dummy emails! Raise explicit error so caller can prompt user
                raise ValueError("MISSING_RECIPIENT_EMAIL")

            # 5. Generate personalized text via AI
            job_title = job.title if job else "Software Engineer / Professional Tech Role"
            job_desc = job.description if job else ""
            subject, body = await evaluator.write_cold_email(
                company_name=company.name,
                cv_text=cv_text,
                job_title=job_title,
                job_description=job_desc
            )

            # 6. Queue the draft with attachment
            draft = await email_service.queue_email_draft(
                session=session,
                user_id=user_id,
                company_id=company.id,
                recipient_email=target_email,
                subject=subject,
                body=body,
                source="internship" if job_id else "open_application",
                job_id=job_id,
                attachments=cv_attachment
            )

            self.mark_success(start)
            logger.info(f"[{self.agent_name}] Queued email draft ID {draft.id} for {company.name} with CV attachment: {bool(cv_attachment)}")
            return draft

        except Exception as e:
            self.mark_failure(start, e)
            logger.error(f"[{self.agent_name}] Failed to draft cold email for company {company_id}: {e}", exc_info=True)
            return None

email_drafting_agent = EmailDraftingAgent()
