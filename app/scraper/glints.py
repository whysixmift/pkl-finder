from datetime import datetime, timezone
import urllib.parse
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup
from app.scraper.base import BaseScraper
from app.utils.logger import logger

class GlintsScraper(BaseScraper):
    def __init__(self) -> None:
        super().__init__("glints")

    async def scrape(self, keyword: str, location: str) -> List[Dict[str, Any]]:
        """Scrapes jobs from Glints matching keyword and location with Playwright fallback."""
        if self.is_disabled:
            logger.debug(f"[{self.source_name}] Scraper is disabled.")
            return []

        jobs = []
        encoded_keyword = urllib.parse.quote(keyword)
        
        # Glints opportunities search page
        url = f"https://glints.com/id/en/opportunities/jobs?keyword={encoded_keyword}"
        if location:
            url += f"&location={urllib.parse.quote(location)}"
            
        logger.info(f"[{self.source_name}] Scraping URL: {url}")
        
        # 1. Attempt static HTML scraping first
        html = await self.fetch_url(url)
        if html:
            jobs = self._parse_html(html, location)
            
        # 2. If static scraping returns 0 jobs, trigger Playwright fallback (Issue 3)
        if not jobs:
            logger.warning(f"[{self.source_name}] Static scraping returned 0 jobs. Falling back to Playwright headless browser.")
            try:
                playwright_html = await self._fetch_with_playwright(url)
                if playwright_html:
                    jobs = self._parse_html(playwright_html, location)
            except Exception as pe:
                logger.error(f"[{self.source_name}] Playwright fallback failed: {pe}", exc_info=True)

        return jobs

    async def _fetch_with_playwright(self, url: str) -> Optional[str]:
        """Runs a headless browser using Playwright to render dynamically loaded job cards."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.error(f"[{self.source_name}] Playwright library not installed. Cannot use browser fallback.")
            return None

        playwright_instance = None
        browser = None
        try:
            playwright_instance = await async_playwright().start()
            # Launch Chromium in headless mode
            browser = await playwright_instance.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = await context.new_page()
            
            logger.info(f"[{self.source_name}] Playwright navigating to {url}")
            await page.goto(url, wait_until="load", timeout=30000)
            
            # Wait for either of the common job card container selector classes to render
            try:
                await page.wait_for_selector("[class*='JobCard']", timeout=8000)
            except Exception:
                try:
                    await page.wait_for_selector("[class*='CardContainer']", timeout=5000)
                except Exception:
                    logger.debug(f"[{self.source_name}] Playwright wait timeout: selector not loaded. Continuing parsing anyway.")
            
            # Give JS hydration a brief moment to settle
            await page.wait_for_timeout(2000)
            
            content = await page.content()
            return content
            
        finally:
            if browser:
                await browser.close()
            if playwright_instance:
                await playwright_instance.stop()

        return None

    def _parse_html(self, html: str, default_location: str) -> List[Dict[str, Any]]:
        """Parses the static or Playwright-rendered Glints HTML structure."""
        jobs = []
        try:
            soup = BeautifulSoup(html, "html.parser")
            
            # Glints job cards selectors
            job_cards = soup.select("[class*='CompactOpportunityCardsc__CardContainer']") or \
                        soup.select("[class*='JobCard']") or \
                        soup.select("div[class*='CardContainer']") or \
                        soup.select("div.compact-job-card") or \
                        soup.select("[class*='CompactOpportunityCardsc__CardWrapper']")

            logger.info(f"[{self.source_name}] Found {len(job_cards)} potential job cards")

            for card in job_cards[:10]:
                try:
                    title_elem = card.select_one("h3[class*='JobTitle']") or \
                                 card.select_one("a[class*='JobTitle']") or \
                                 card.select_one("h3") or \
                                 card.select_one("a")
                    if not title_elem:
                        continue
                    
                    title = title_elem.text.strip()
                    
                    anchor = card if card.name == 'a' else card.select_one("a")
                    job_url = anchor.get("href", "") if anchor else ""
                    if job_url and not job_url.startswith("http"):
                        job_url = f"https://glints.com{job_url}"

                    company_elem = card.select_one("[class*='CompanyName']") or \
                                   card.select_one("[class*='CompanyLink']") or \
                                   card.select_one("div[class*='company']")
                    company = company_elem.text.strip() if company_elem else "Unknown Company"

                    location_elem = card.select_one("[class*='CardLocation']") or \
                                    card.select_one("[class*='LocationText']") or \
                                    card.select_one("span[class*='location']")
                    job_location = location_elem.text.strip() if location_elem else default_location or "Indonesia"

                    salary_elem = card.select_one("[class*='SalaryText']") or \
                                  card.select_one("[class*='salary']")
                    salary = salary_elem.text.strip() if salary_elem else None

                    desc_elem = card.select_one("[class*='Description']") or \
                                card.select_one("[class*='Snippet']")
                    description = desc_elem.text.strip() if desc_elem else f"Internship position for {title} at {company}."

                    work_mode_elem = card.select_one("[class*='WorkMode']") or card.select_one("[class*='WorkType']")
                    work_mode = work_mode_elem.text.strip() if work_mode_elem else "On-site"
                    if "remote" in title.lower() or "remote" in description.lower():
                        work_mode = "Remote"
                    elif "hybrid" in title.lower() or "hybrid" in description.lower():
                        work_mode = "Hybrid"

                    employment_type = "Internship" if any(x in title.lower() or x in description.lower() for x in ["intern", "magang", "pkl"]) else "Full-time"
                    posted_date = datetime.now(timezone.utc).replace(tzinfo=None)

                    jobs.append({
                        "title": title,
                        "company": company,
                        "location": job_location,
                        "description": description,
                        "url": job_url,
                        "posted_date": posted_date,
                        "source": self.source_name,
                        "salary": salary,
                        "work_mode": work_mode,
                        "employment_type": employment_type
                    })

                except Exception as card_error:
                    logger.debug(f"[{self.source_name}] Error parsing job card: {card_error}")
                    continue

        except Exception as parse_error:
            logger.error(f"[{self.source_name}] Error parsing HTML content: {parse_error}", exc_info=True)

        return jobs
