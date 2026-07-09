from datetime import datetime, timedelta, timezone
import urllib.parse
from typing import Dict, Any, List
from bs4 import BeautifulSoup
from app.scraper.base import BaseScraper
from app.utils.logger import logger

class GlintsScraper(BaseScraper):
    def __init__(self) -> None:
        super().__init__("glints")

    async def scrape(self, keyword: str, location: str) -> List[Dict[str, Any]]:
        """Scrapes jobs from Glints matching keyword and location."""
        jobs = []
        encoded_keyword = urllib.parse.quote(keyword)
        
        # e.g., https://glints.com/id/en/opportunities/jobs?keyword=python
        url = f"https://glints.com/id/en/opportunities/jobs?keyword={encoded_keyword}"
        if location:
            url += f"&location={urllib.parse.quote(location)}"
            
        logger.info(f"[{self.source_name}] Scraping URL: {url}")
        
        html = await self.fetch_url(url)
        if not html:
            logger.warning(f"[{self.source_name}] No HTML returned for Glints search: {keyword}")
            return jobs

        try:
            soup = BeautifulSoup(html, "html.parser")
            
            # Glints job cards often have Container or Card in their classes
            job_cards = soup.select("[class*='CompactOpportunityCardsc__CardContainer']") or \
                        soup.select("[class*='JobCard']") or \
                        soup.select("div[class*='CardContainer']") or \
                        soup.select("div.compact-job-card")
            
            logger.info(f"[{self.source_name}] Found {len(job_cards)} potential job cards")

            for card in job_cards[:10]:
                try:
                    # Extract URL and Title
                    title_elem = card.select_one("h3[class*='JobTitle']") or \
                                 card.select_one("a[class*='JobTitle']") or \
                                 card.select_one("h3") or \
                                 card.select_one("a")
                    if not title_elem:
                        continue
                    
                    title = title_elem.text.strip()
                    
                    # Find the anchor tag for the URL
                    anchor = card if card.name == 'a' else card.select_one("a")
                    job_url = anchor.get("href", "") if anchor else ""
                    if job_url and not job_url.startswith("http"):
                        job_url = f"https://glints.com{job_url}"

                    # Extract Company
                    company_elem = card.select_one("[class*='CompanyName']") or \
                                   card.select_one("[class*='CompanyLink']") or \
                                   card.select_one("div[class*='company']")
                    company = company_elem.text.strip() if company_elem else "Unknown Company"

                    # Extract Location
                    location_elem = card.select_one("[class*='CardLocation']") or \
                                    card.select_one("[class*='LocationText']") or \
                                    card.select_one("span[class*='location']")
                    job_location = location_elem.text.strip() if location_elem else location or "Indonesia"

                    # Extract Salary
                    salary_elem = card.select_one("[class*='SalaryText']") or \
                                  card.select_one("[class*='salary']")
                    salary = salary_elem.text.strip() if salary_elem else None

                    # Extract Description/Snippet (Glints cards sometimes have a text summary)
                    desc_elem = card.select_one("[class*='Description']") or \
                                card.select_one("[class*='Snippet']")
                    description = desc_elem.text.strip() if desc_elem else f"Internship position for {title} at {company}."

                    # Work Mode (Hybrid/Remote/Onsite)
                    work_mode_elem = card.select_one("[class*='WorkMode']") or card.select_one("[class*='WorkType']")
                    work_mode = work_mode_elem.text.strip() if work_mode_elem else "On-site"
                    if "remote" in title.lower() or "remote" in description.lower():
                        work_mode = "Remote"
                    elif "hybrid" in title.lower() or "hybrid" in description.lower():
                        work_mode = "Hybrid"

                    # Employment Type
                    employment_type = "Internship" if any(x in title.lower() or x in description.lower() for x in ["intern", "magang", "pkl"]) else "Full-time"

                    posted_date = datetime.now(timezone.utc).replace(tzinfo=None) # default to now

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
                    logger.error(f"[{self.source_name}] Error parsing job card: {card_error}")
                    continue

        except Exception as parse_error:
            logger.error(f"[{self.source_name}] Error parsing Glints HTML: {parse_error}", exc_info=True)

        return jobs
