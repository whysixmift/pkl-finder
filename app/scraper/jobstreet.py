import json
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, Any, List
from bs4 import BeautifulSoup
from app.scraper.base import BaseScraper
from app.utils.logger import logger

class JobstreetScraper(BaseScraper):
    def __init__(self) -> None:
        super().__init__("jobstreet")

    async def scrape(self, keyword: str, location: str) -> List[Dict[str, Any]]:
        """Scrapes jobs from Jobstreet (SEEK platform) using JSON extraction and HTML parsing."""
        jobs = []
        encoded_keyword = urllib.parse.quote(keyword)
        
        # Jobstreet search URL structure
        url = f"https://www.jobstreet.co.id/id/job-search/{encoded_keyword}-jobs"
        if location:
            url += f"-in-{urllib.parse.quote(location)}"
            
        logger.info(f"[{self.source_name}] Scraping URL: {url}")
        
        html = await self.fetch_url(url)
        if not html:
            logger.warning(f"[{self.source_name}] No HTML returned for Jobstreet search: {keyword}")
            return jobs

        try:
            soup = BeautifulSoup(html, "html.parser")
            
            # Seek platforms embed initial state in a script tag containing SEEK_REDUX_DATA
            redux_script = None
            for script in soup.find_all("script"):
                if script.string and "window.SEEK_REDUX_DATA" in script.string:
                    redux_script = script.string
                    break
                    
            if redux_script:
                try:
                    # Extract the JSON payload
                    json_str = redux_script.split("window.SEEK_REDUX_DATA = ")[1].split(";\n")[0].strip()
                    # Just in case it has different line endings
                    if ";" in json_str:
                        json_str = json_str.split(";")[0]
                        
                    data = json.loads(json_str)
                    results = data.get("results", {}).get("jobs", [])
                    logger.info(f"[{self.source_name}] Successfully parsed {len(results)} jobs from REDUX state")
                    
                    for job in results[:10]:
                        title = job.get("title", "")
                        if not title:
                            continue
                        
                        job_id = job.get("id", "")
                        job_url = f"https://www.jobstreet.co.id/id/job/{job_id}" if job_id else ""
                        
                        company = job.get("advertiser", {}).get("description", "Unknown Company")
                        job_location = job.get("location", "Indonesia")
                        description = job.get("teaser", "") or f"Job vacancy at {company}"
                        
                        salary = job.get("salary", {}).get("label", None)
                        work_mode = job.get("workType", "On-site")
                        if "remote" in title.lower() or "remote" in description.lower():
                            work_mode = "Remote"
                        
                        employment_type = "Internship" if any(x in title.lower() or x in description.lower() for x in ["intern", "magang", "pkl"]) else "Full-time"
                        
                        # Posted date parsing
                        posted_date = datetime.utcnow()
                        age_str = job.get("listingDateDisplay", "")
                        if age_str:
                            days = [int(s) for s in age_str.split() if s.isdigit()]
                            if days:
                                posted_date = datetime.utcnow() - timedelta(days=days[0])

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
                    
                    if jobs:
                        return jobs
                except Exception as e:
                    logger.error(f"[{self.source_name}] Failed to parse REDUX data: {e}")

            # Fallback to DOM parsing if script block is not found or fails
            job_cards = soup.select("article") or soup.select("[data-card-type='JobCard']")
            logger.info(f"[{self.source_name}] Fallback to DOM. Found {len(job_cards)} job cards")
            
            for card in job_cards[:10]:
                try:
                    title_elem = card.select_one("a[data-automation='jobTitle']") or card.select_one("h1 a") or card.select_one("h3 a")
                    if not title_elem:
                        continue
                    title = title_elem.text.strip()
                    job_url = title_elem.get("href", "")
                    if job_url and not job_url.startswith("http"):
                        job_url = f"https://www.jobstreet.co.id{job_url}"

                    company_elem = card.select_one("a[data-automation='jobCompany']") or card.select_one("span[data-automation='jobCompany']")
                    company = company_elem.text.strip() if company_elem else "Unknown Company"

                    location_elem = card.select_one("a[data-automation='jobLocation']") or card.select_one("span[data-automation='jobLocation']")
                    job_location = location_elem.text.strip() if location_elem else location or "Indonesia"

                    desc_elem = card.select_one("span[data-automation='jobTeaser']") or card.select_one("p")
                    description = desc_elem.text.strip() if desc_elem else ""

                    work_mode = "On-site"
                    if "remote" in title.lower() or "remote" in description.lower():
                        work_mode = "Remote"

                    employment_type = "Internship" if any(x in title.lower() or x in description.lower() for x in ["intern", "magang", "pkl"]) else "Full-time"

                    jobs.append({
                        "title": title,
                        "company": company,
                        "location": job_location,
                        "description": description,
                        "url": job_url,
                        "posted_date": datetime.utcnow(),
                        "source": self.source_name,
                        "salary": None,
                        "work_mode": work_mode,
                        "employment_type": employment_type
                    })
                except Exception as card_error:
                    logger.error(f"[{self.source_name}] Error parsing DOM job card: {card_error}")
                    continue

        except Exception as parse_error:
            logger.error(f"[{self.source_name}] Error parsing Jobstreet HTML: {parse_error}", exc_info=True)

        return jobs
