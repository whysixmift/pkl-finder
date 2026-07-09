from datetime import datetime
import urllib.parse
from typing import Dict, Any, List
from bs4 import BeautifulSoup
from app.scraper.base import BaseScraper
from app.utils.logger import logger

class LinkedInScraper(BaseScraper):
    def __init__(self) -> None:
        super().__init__("linkedin")

    async def scrape(self, keyword: str, location: str) -> List[Dict[str, Any]]:
        """Scrapes jobs from LinkedIn Guest search endpoint."""
        jobs = []
        encoded_keyword = urllib.parse.quote(keyword)
        encoded_location = urllib.parse.quote(location or "Indonesia")
        
        # Public guest job search endpoint which returns clean HTML list items
        url = f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={encoded_keyword}&location={encoded_location}&start=0"
        
        logger.info(f"[{self.source_name}] Scraping URL: {url}")
        
        html = await self.fetch_url(url)
        if not html:
            logger.warning(f"[{self.source_name}] No HTML returned for LinkedIn search: {keyword}")
            return jobs

        try:
            soup = BeautifulSoup(html, "html.parser")
            
            # Guest search API returns list items (li)
            job_cards = soup.select("li")
            logger.info(f"[{self.source_name}] Found {len(job_cards)} potential jobs")

            for card in job_cards[:10]:
                try:
                    # Title
                    title_elem = card.select_one(".base-search-card__title") or card.select_one("h3")
                    if not title_elem:
                        continue
                    title = title_elem.text.strip()

                    # URL
                    url_elem = card.select_one("a.base-card__full-link") or card.select_one("a")
                    if not url_elem:
                        continue
                    job_url = url_elem.get("href", "").split("?")[0] # Clean query parameters

                    # Company
                    company_elem = card.select_one(".base-search-card__subtitle") or card.select_one("h4")
                    company = company_elem.text.strip() if company_elem else "Unknown Company"

                    # Location
                    location_elem = card.select_one(".job-search-card__location") or card.select_one("span")
                    job_location = location_elem.text.strip() if location_elem else location or "Indonesia"

                    # Posted Date
                    posted_date = datetime.utcnow()
                    date_elem = card.select_one("time")
                    if date_elem:
                        datetime_str = date_elem.get("datetime")
                        if datetime_str:
                            try:
                                posted_date = datetime.strptime(datetime_str, "%Y-%m-%d")
                            except ValueError:
                                pass

                    # Work Mode and Employment Type estimation
                    description = f"Internship vacancy for {title} at {company} in {job_location}."
                    work_mode = "On-site"
                    if "remote" in title.lower() or "remote" in description.lower():
                        work_mode = "Remote"
                    elif "hybrid" in title.lower() or "hybrid" in description.lower():
                        work_mode = "Hybrid"

                    employment_type = "Internship" if any(x in title.lower() or x in description.lower() for x in ["intern", "magang", "pkl"]) else "Full-time"

                    jobs.append({
                        "title": title,
                        "company": company,
                        "location": job_location,
                        "description": description,
                        "url": job_url,
                        "posted_date": posted_date,
                        "source": self.source_name,
                        "salary": None,
                        "work_mode": work_mode,
                        "employment_type": employment_type
                    })

                except Exception as card_error:
                    logger.error(f"[{self.source_name}] Error parsing job card: {card_error}")
                    continue

        except Exception as parse_error:
            logger.error(f"[{self.source_name}] Error parsing LinkedIn HTML: {parse_error}", exc_info=True)

        return jobs
