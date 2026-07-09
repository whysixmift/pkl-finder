import urllib.parse
from datetime import datetime
from typing import Dict, Any, List
from bs4 import BeautifulSoup
from app.scraper.base import BaseScraper
from app.utils.logger import logger

class GoogleJobsScraper(BaseScraper):
    def __init__(self) -> None:
        super().__init__("google_jobs")

    async def scrape(self, keyword: str, location: str) -> List[Dict[str, Any]]:
        """Scrapes jobs by querying Google Search with specific parameters."""
        jobs = []
        # Construct a search query targeting job listings
        search_query = f"{keyword} internship magang {location}"
        encoded_query = urllib.parse.quote(search_query)
        
        # Google search URL (using mobile/basic UI for simple HTML parse)
        url = f"https://www.google.com/search?q={encoded_query}&num=15"
        
        logger.info(f"[{self.source_name}] Scraping Google Search: {url}")
        
        # Using a mobile User-Agent is more reliable for basic HTML retrieval from Google
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7"
        }
        
        html = await self.fetch_url(url, headers=headers)
        if not html:
            logger.warning(f"[{self.source_name}] No HTML returned for search query: {search_query}")
            return jobs

        try:
            soup = BeautifulSoup(html, "html.parser")
            
            # Google mobile search results are typically in cards/containers with class 'kCrYT'
            search_results = soup.select(".kCrYT")
            logger.info(f"[{self.source_name}] Found {len(search_results)} search result containers")

            # We process them in pairs: one has the title/link, the next has the description/snippet
            for i in range(0, len(search_results) - 1, 2):
                title_block = search_results[i]
                desc_block = search_results[i+1]
                
                try:
                    # Extract Title and Link
                    link_elem = title_block.select_one("a")
                    if not link_elem:
                        continue
                    
                    raw_url = link_elem.get("href", "")
                    if not raw_url.startswith("/url?q="):
                        continue
                        
                    # Extract target URL from Google redirect URL
                    parsed_url = urllib.parse.urlparse(raw_url)
                    query_params = urllib.parse.parse_qs(parsed_url.query)
                    job_url = query_params.get("q", [None])[0]
                    if not job_url:
                        continue
                        
                    # Exclude major search domains/portals that aren't specific jobs (e.g. google.com, facebook.com)
                    if any(domain in job_url for domain in ["google.com", "youtube.com", "facebook.com", "instagram.com", "twitter.com"]):
                        continue

                    title_elem = title_block.select_one("h3")
                    if not title_elem:
                        continue
                    
                    title = title_elem.text.strip()
                    # Clean title suffixes (e.g., "- Glassdoor", "- Tech in Asia")
                    for suffix in [" - Indeed", " - Glassdoor", " - LinkedIn", " | Jobstreet", " - Loker"]:
                        if suffix in title:
                            title = title.split(suffix)[0].strip()

                    # Extract snippet
                    snippet_elem = desc_block.select_one(".BNeawe")
                    description = snippet_elem.text.strip() if snippet_elem else f"Job listing found on web: {title}"

                    # Estimate company name from title or description
                    # Many Google titles are: "Job Title - Company Name"
                    company = "Unknown Company"
                    if " at " in title.lower():
                        company = title.lower().split(" at ")[-1].strip().title()
                    elif " - " in title:
                        company = title.split(" - ")[-1].strip()

                    # Filter location
                    job_location = location or "Indonesia"

                    # Date estimation
                    posted_date = datetime.utcnow()

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
                    logger.debug(f"[{self.source_name}] Error parsing result pair: {card_error}")
                    continue

        except Exception as parse_error:
            logger.error(f"[{self.source_name}] Error parsing Google Search HTML: {parse_error}", exc_info=True)

        return jobs
