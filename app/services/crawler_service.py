import re
import json
import urllib.parse
from typing import List, Dict, Any, Optional, Tuple
from bs4 import BeautifulSoup
import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.db import async_session_maker
from app.database.models import Company, Job, EmailQueue
from app.ai.evaluator import evaluator, AIResult
from app.services.email_service import email_service
from app.services.cv_service import cv_service
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
        """Walks over discovered companies in DB, finds career portals/emails, and generates applications."""
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

                    # Retrieve CV
                    cv_text = await cv_service.get_active_cv_text(session)
                    
                    # Generate Open Application if email exists
                    if email:
                        logger.info(f"Discovered recruitment email for {company.name}: {email}. Pitching open application...")
                        await self.generate_open_application(session, company, email, cv_text)

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
            href = a_tag.get("href", "")
            text = a_tag.text.lower()
            if any(k in text or any(p in href.lower() for p in CAREER_PATHS) for k in ["career", "karir", "job", "kerja", "join"]):
                absolute_url = urllib.parse.urljoin(homepage, href)
                career_url = absolute_url
                break

        # If not found, try probing default endpoints
        if not career_url:
            for path in CAREER_PATHS:
                probe_url = urllib.parse.urljoin(homepage, path)
                # Quick check if endpoint exists
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
            # Crawl career page for emails
            career_html = await self.fetch_url(career_url)
            if career_html:
                emails.extend(self.extract_emails(career_html))

        # Filter emails
        recruitment_email = None
        for email in emails:
            # Prioritize recruitment-specific boxes
            if any(k in email.lower() for k in ["career", "jobs", "recruitment", "recruit", "talent", "hr", "people"]):
                recruitment_email = email
                break
        
        if not recruitment_email and emails:
            # Fallback to info@ if no specific recruitment address exists
            for email in emails:
                if email.lower().startswith("info@"):
                    recruitment_email = email
                    break
            
            # If still nothing, take the first email
            if not recruitment_email:
                recruitment_email = emails[0]

        return career_url, recruitment_email

    def extract_emails(self, text: str) -> List[str]:
        """Harvest email addresses from plain text / HTML using regex."""
        # Find recruitment-specific emails first
        matches = RECRUIT_EMAIL_REGEX.findall(text)
        # Find info emails
        info_matches = INFO_EMAIL_REGEX.findall(text)
        
        all_emails = list(set(matches + info_matches))
        return [email.strip() for email in all_emails]

    async def generate_open_application(
        self, session: AsyncSession, company: Company, email: str, cv_text: Optional[str]
    ) -> None:
        """Evaluates company fit and writes a custom cold email draft for open applications."""
        # Verify if draft already exists
        dup_stmt = select(EmailQueue).where(
            (EmailQueue.company_id == company.id) & (EmailQueue.recipient_email == email)
        )
        dup_res = await session.execute(dup_stmt)
        if dup_res.scalar_one_or_none():
            logger.debug(f"Open Application draft already exists for {company.name}. Skipping.")
            return

        # Prepare context for AI evaluator
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
            # Utilize the evaluator engine
            # We construct a custom completions payload for email drafting
            logger.info(f"Invoking AI to generate open application for {company.name}")
            
            # Call OpenRouter client custom endpoint or parse response
            api_result = await evaluator.evaluate_job(
                title="Open Application",
                company=company.name,
                location="Remote",
                description=prompt
            )

            # If recommended, we draft the email
            # Wait, the evaluator returns AIResult (recommended, score, reason, matched_skills, missing_skills, summary).
            # We can run another prompt specifically to write the email or parse it.
            # Let's make a dedicated AI Email writer method!
            if api_result.recommended and api_result.score >= settings.SCORE_THRESHOLD:
                # Generate unique email via OpenRouter
                subject, body = await self.write_cold_email(company.name, cv_context)
                
                # Queue draft
                await email_service.queue_email_draft(
                    session=session,
                    company_id=company.id,
                    recipient_email=email,
                    subject=subject,
                    body=body,
                    source="open_application",
                    job_id=None
                )
                logger.info(f"Queued open application draft for {company.name} ({email})")
                
        except Exception as e:
            logger.error(f"Failed to generate open application for {company.name}: {e}", exc_info=True)

    async def write_cold_email(self, company_name: str, cv_text: str) -> Tuple[str, str]:
        """Call OpenRouter LLM to write a professional cold email matching CV details."""
        system_prompt = """
        You are a professional email copywriter writing unique cold emails for internship applications.
        Write a concise, professional, and convincing cold email to the recruitment team requesting a PKL / internship.
        Do NOT use templates.
        Do NOT use generic bracket placeholders (e.g. [Company Name], [My Name]). Write the actual company name and candidate details.
        
        The candidate is:
        Name: Julian
        School: SMK Negeri 2 Bekasi (Rekayasa Perangkat Lunak / Software Engineering)
        Skills: Python, Java, C++, Robotics, Embedded Systems, IoT, Git.
        Experience: FIRST Tech Challenge, Hack Club Mentor.
        Looking for: PKL (Praktek Kerja Lapangan) or Internship.
        
        You must output ONLY a JSON object with:
        {
          "subject": "Unique, catchy subject line",
          "body": "Complete email body"
        }
        """

        prompt = f"Write an internship application email to: {company_name}"
        
        payload = {
            "model": settings.OPENROUTER_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "response_format": {"type": "json_object"}
        }

        headers = {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/avrjulian/pkl-finder",
            "X-Title": "PKL Finder Bot",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(settings.OPENROUTER_API_URL, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            
            # Clean markdown code blocks if present
            if content.startswith("```"):
                match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", content)
                if match:
                    content = match.group(1)

            parsed = json.loads(content)
            return parsed["subject"], parsed["body"]

# Shared instance
career_crawler = CompanyCareerCrawler()
