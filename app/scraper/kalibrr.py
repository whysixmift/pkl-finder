from datetime import datetime, timedelta, timezone
import urllib.parse
from typing import Dict, Any, List
from bs4 import BeautifulSoup
from app.scraper.base import BaseScraper
from app.utils.logger import logger

class KalibrrScraper(BaseScraper):
    def __init__(self) -> None:
        super().__init__("kalibrr")

    async def scrape(self, keyword: str, location: str) -> List[Dict[str, Any]]:
        """Scrapes jobs from Kalibrr matching keyword and location."""
        jobs: List[Dict[str, Any]] = []
        encoded_keyword = urllib.parse.quote(keyword)
        
        # Format the Kalibrr job board URL
        # e.g., https://www.kalibrr.com/job-board/y/1?query=python&location=Jakarta
        url = f"https://www.kalibrr.com/job-board/y/1?query={encoded_keyword}"
        if location:
            url += f"&location={urllib.parse.quote(location)}"
            
        logger.info(f"[{self.source_name}] Scraping URL: {url}")
        
        html = await self.fetch_url(url)
        if not html:
            logger.warning(f"[{self.source_name}] No HTML returned for search {keyword} in {location}")
            return jobs

        try:
            soup = BeautifulSoup(html, "html.parser")
            
            # Find job cards
            # In Kalibrr, job cards are usually nested inside divs with test attributes or specific classes
            job_cards = soup.select("div[itemtype='http://schema.org/JobPosting']") or \
                        soup.select(".k-border-b.k-border-tertiary-color-10") or \
                        soup.select("div[class*='JobCard']")
            
            logger.info(f"[{self.source_name}] Found {len(job_cards)} potential job cards")

            for card in job_cards[:10]: # Limit to top 10 per keyword
                try:
                    # Extract Title
                    title_elem = card.select_one("a[itemprop='title']") or \
                                 card.select_one("h2 a") or \
                                 card.select_one("a[class*='k-text-primary']")
                    if not title_elem:
                        continue
                    
                    title = title_elem.text.strip()
                    job_url = title_elem.get("href", "")
                    if job_url and not job_url.startswith("http"):
                        job_url = f"https://www.kalibrr.com{job_url}"

                    # Extract Company
                    company_elem = card.select_one("span[itemprop='name']") or \
                                   card.select_one("a[class*='k-text-subdued']") or \
                                   card.select_one("span[class*='Company']")
                    company = company_elem.text.strip() if company_elem else "Unknown Company"

                    # Extract Location
                    location_elem = card.select_one("span[itemprop='addressLocality']") or \
                                    card.select_one("span[class*='k-text-subdued']:nth-of-type(2)") or \
                                    card.select_one("div[class*='Location']")
                    job_location = location_elem.text.strip() if location_elem else location or "Indonesia"

                    # Extract Description/Snippet
                    desc_elem = card.select_one("div[itemprop='description']") or \
                                card.select_one("div[class*='Description']") or \
                                card.select_one("div[class*='k-text-subdued']")
                    description = desc_elem.text.strip() if desc_elem else f"Internship position at {company} in {job_location}."

                    # Extract employment type / work mode / salary
                    salary_elem = card.select_one("span[class*='Salary']") or card.select_one("div[class*='salary']")
                    salary = salary_elem.text.strip() if salary_elem else None

                    # Work mode estimation (Hybrid/Remote/Onsite)
                    work_mode = "Hybrid" if "hybrid" in description.lower() or "hybrid" in title.lower() else (
                        "Remote" if "remote" in description.lower() or "remote" in title.lower() or "work from home" in description.lower() else "On-site"
                    )

                    # Employment type estimation
                    employment_type = "Internship" if any(x in title.lower() or x in description.lower() for x in ["intern", "magang", "pkl", "co-op"]) else "Full-time"

                    # Posted date estimation (e.g. "a day ago", "3 days ago")
                    posted_elem = card.select_one("span[class*='k-text-subdued']:last-child") or card.select_one("span[itemprop='datePosted']")
                    posted_date = datetime.now(timezone.utc).replace(tzinfo=None)
                    if posted_elem:
                        posted_text = posted_elem.text.lower()
                        if "day" in posted_text:
                            days = [int(s) for s in posted_text.split() if s.isdigit()]
                            if days:
                                posted_date = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days[0])
                        elif "week" in posted_text:
                            weeks = [int(s) for s in posted_text.split() if s.isdigit()]
                            if weeks:
                                posted_date = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(weeks=weeks[0])

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
                    logger.error(f"[{self.source_name}] Error parsing job card: {card_error}", exc_info=True)
                    continue

        except Exception as parse_error:
            logger.error(f"[{self.source_name}] Error parsing HTML: {parse_error}", exc_info=True)

        return jobs
