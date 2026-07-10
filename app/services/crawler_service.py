import re
import urllib.parse
from typing import List, Optional, Tuple
from bs4 import BeautifulSoup
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.db import async_session_maker
from app.database.models import Company, EmailQueue, CVProfile
from app.config.settings import settings
from app.ai.evaluator import evaluator
from app.services.email_service import email_service
from app.scraper.base import BaseScraper
from app.utils.logger import logger

CAREER_PATHS = [
    "/career", "/careers", "/jobs", "/join-us", "/karir",
    "/recruitment", "/work-with-us", "/opportunities", "/work", "/join"
]

RECRUIT_EMAIL_REGEX = re.compile(
    r'\b[A-Za-z0-9._%+-]+@(?!support\b|privacy\b|security\b|legal\b|abuse\b|billing\b|info\b)[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
)
INFO_EMAIL_REGEX = re.compile(r'\binfo@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')

class CompanyCareerCrawler(BaseScraper):
    def __init__(self) -> None:
        super().__init__("career_crawler")

    async def crawl_all_companies(self) -> None:
        """Walks over discovered companies in DB, finds career portals/emails, and generates applications for all users."""
        logger.info("Starting company career crawling and harvester cycle")
        async with async_session_maker() as session:
            stmt = select(Company).where(Company.status == "discovered")
            res = await session.execute(stmt)
            companies = res.scalars().all()

            for company in companies:
                try:
                    logger.info(f"Crawling company: {company.name} ({company.website})")
                    career_url, email = await self.crawl_company_website(company.website)
                    
                    company.career_url = career_url
                    company.recruitment_email = email
                    company.status = "crawled"
                    await session.commit()

                    if email:
                        logger.info(f"Discovered recruitment email for {company.name}: {email}. Pitching open applications...")
                        
                        # Query all active user CV profiles
                        cv_stmt = select(CVProfile)
                        cv_res = await session.execute(cv_stmt)
                        cv_profiles = cv_res.scalars().all()

                        if not cv_profiles:
                            # Fallback default admin CV
                            default_cv_text = "SMK Negeri 2 Bekasi Software Engineering. Python, C++, Embedded Systems, IoT, Robotics."
                            mock_admin_cv = CVProfile(user_id=settings.TELEGRAM_ADMIN_ID, filename="default", cv_text=default_cv_text)
                            cv_profiles = [mock_admin_cv]

                        for profile in cv_profiles:
                            await self.generate_open_application(session, profile.user_id, company, email, profile.cv_text)

                except Exception as e:
                    logger.error(f"Error crawling company ID {company.id} ({company.name}): {e}", exc_info=True)
                    company.status = "failed"
                    await session.commit()

    async def crawl_company_website(self, homepage: str) -> Tuple[Optional[str], Optional[str]]:
        """Scans home domain for career links and recruitment emails."""
        html = await self.fetch_url(homepage)
        if not html:
            return None, None

        soup = BeautifulSoup(html, "html.parser")
        
        # 1. Search for career links in anchors
        career_url = None
        for a_tag in soup.find_all("a", href=True):
            raw_href = a_tag.get("href", "")
            href_str = raw_href[0] if isinstance(raw_href, list) else str(raw_href)
            text = a_tag.text.lower()
            if any(k in text or any(p in href_str.lower() for p in CAREER_PATHS) for k in ["career", "karir", "job", "kerja", "join"]):
                absolute_url = urllib.parse.urljoin(homepage, href_str)
                career_url = absolute_url
                break

        # If not found, try probing default endpoints
        if not career_url:
            for path in CAREER_PATHS:
                probe_url = urllib.parse.urljoin(homepage, path)
                headers = self.get_random_headers()
                try:
                    async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                        resp = await client.get(probe_url, headers=headers)
                        if resp.status_code == 200:
                            career_url = probe_url
                            break
                except Exception:
                    continue

        # 2. Search for emails in homepage and career page
        emails = self.extract_emails(html)
        
        if career_url and not emails:
            career_html = await self.fetch_url(career_url)
            if career_html:
                emails.extend(self.extract_emails(career_html))

        # Filter emails
        recruitment_email = None
        for email in emails:
            if any(k in email.lower() for k in ["career", "jobs", "recruitment", "recruit", "talent", "hr", "people"]):
                recruitment_email = email
                break
        
        if not recruitment_email and emails:
            for email in emails:
                if email.lower().startswith("info@"):
                    recruitment_email = email
                    break
            
            if not recruitment_email:
                recruitment_email = emails[0]

        return career_url, recruitment_email

    def extract_emails(self, text: str) -> List[str]:
        """Harvest email addresses from plain text / HTML using regex."""
        matches = RECRUIT_EMAIL_REGEX.findall(text)
        info_matches = INFO_EMAIL_REGEX.findall(text)
        all_emails = list(set(matches + info_matches))
        return [email.strip() for email in all_emails]

    async def generate_open_application(
        self, session: AsyncSession, user_id: int, company: Company, email: str, cv_text: Optional[str]
    ) -> None:
        """Evaluates company fit and writes a custom cold email draft for open applications."""
        # Verify if draft already exists for this user
        dup_stmt = select(EmailQueue).where(
            (EmailQueue.company_id == company.id) & 
            (EmailQueue.recipient_email == email) &
            (EmailQueue.user_id == user_id)
        )
        dup_res = await session.execute(dup_stmt)
        if dup_res.scalar_one_or_none():
            logger.debug(f"Open Application draft already exists for {company.name} and user {user_id}. Skipping.")
            return

        cv_context = cv_text or "Default CV Profile: SMK Negeri 2 Bekasi Software Engineering. Skills: Python, Java, C++, Robotics, Embedded Systems, IoT, Android Studio, Git."
        
        prompt = f"""
        Company Name: {company.name}
        Website: {company.website}
        
        Candidate CV:
        {cv_context}
        
        Task:
        1. Determine if this company is a match for an internship / PKL (recommended: true/false, score: 0-100, summary, reason list).
        2. If recommended (score >= 70), draft a professional, highly personalized cold application email seeking an internship/PKL. Include:
           - Subject: Requesting Internship / PKL Opportunity - [Candidate Name]
           - Email Body addressing the company name and pitching the candidate's skills (Python, Embedded Systems, IoT, C++).
           - Do not use generic placeholders like [Insert date] or [Insert Company name] in the body - write the actual name.
           
        Format your response as a JSON object with:
        {{
          "recommended": true/false,
          "score": 0-100,
          "summary": "Brief explanation",
          "reason": ["reason 1", "reason 2"],
          "matched_skills": ["skill 1"],
          "missing_skills": [],
          "email_subject": "Draft Subject",
          "email_body": "Dear recruitment team..."
        }}
        """

        try:
            logger.info(f"Invoking AI to generate open application for {company.name} for user {user_id}")
            
            api_result = await evaluator.evaluate_job(
                title="Open Application",
                company=company.name,
                location="Remote",
                description=prompt
            )

            if api_result.recommended and api_result.score >= settings.SCORE_THRESHOLD:
                subject, body = await evaluator.write_cold_email(company.name, cv_context)
                
                await email_service.queue_email_draft(
                    session=session,
                    user_id=user_id,
                    company_id=company.id,
                    recipient_email=email,
                    subject=subject,
                    body=body,
                    source="open_application",
                    job_id=None
                )
                logger.info(f"Queued open application draft for {company.name} ({email}) and user {user_id}")
                
        except Exception as e:
            logger.error(f"Failed to generate open application for {company.name} and user {user_id}: {e}", exc_info=True)

# Shared instance
career_crawler = CompanyCareerCrawler()
