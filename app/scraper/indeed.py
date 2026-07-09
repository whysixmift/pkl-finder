import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Dict, Any, List
from app.scraper.base import BaseScraper
from app.utils.logger import logger

class IndeedScraper(BaseScraper):
    def __init__(self) -> None:
        super().__init__("indeed")

    async def scrape(self, keyword: str, location: str) -> List[Dict[str, Any]]:
        """Scrapes jobs from Indeed Indonesia using RSS feeds to avoid Cloudflare blocks."""
        if self.is_disabled:
            logger.debug(f"[{self.source_name}] Scraper is disabled due to persistent 403 Forbidden blocks.")
            return []

        jobs = []
        encoded_keyword = urllib.parse.quote(keyword)
        
        # Indeed RSS feed endpoint
        url = f"https://id.indeed.com/rss?q={encoded_keyword}"
        if location:
            url += f"&l={urllib.parse.quote(location)}"
            
        logger.info(f"[{self.source_name}] Scraping RSS URL: {url}")
        
        xml_content = await self.fetch_url(url)
        
        # Handle 403 auto-disable check
        if self.last_status_code == 403:
            logger.error(
                f"[{self.source_name}] Indeed RSS endpoint returned 403 Forbidden. "
                "The IP or client has been blocked by Indeed. Disabling Indeed scraper to avoid log flood."
            )
            self.is_disabled = True
            return []

        if not xml_content:
            logger.warning(f"[{self.source_name}] No XML returned from Indeed RSS feed")
            return jobs

        try:
            # Parse XML safely using standard library ElementTree
            root = ET.fromstring(xml_content.encode("utf-8"))
            items = root.findall(".//item")
            logger.info(f"[{self.source_name}] Found {len(items)} items in RSS feed")

            for item in items[:10]:
                try:
                    title_node = item.find("title")
                    raw_title = title_node.text.strip() if title_node is not None and title_node.text else ""
                    if not raw_title:
                        continue

                    # Indeed RSS titles are usually: "Job Title - Company Name - Location"
                    parts = [p.strip() for p in raw_title.split(" - ")]
                    
                    title = parts[0]
                    company = parts[1] if len(parts) > 1 else "Unknown Company"
                    job_location = parts[2] if len(parts) > 2 else location or "Indonesia"

                    # URL
                    link_node = item.find("link")
                    job_url = link_node.text.strip() if link_node is not None and link_node.text else ""
                    
                    # Description
                    desc_node = item.find("description")
                    description = desc_node.text.strip() if desc_node is not None and desc_node.text else ""
                    description = re.sub('<[^<]+?>', '', description)

                    # Date (timezone-neutral UTC)
                    pub_date = datetime.now(timezone.utc).replace(tzinfo=None)
                    date_node = item.find("pubDate")
                    if date_node is not None and date_node.text:
                        try:
                            pub_date = datetime.strptime(date_node.text.strip()[:25], "%a, %d %b %Y %H:%M:%S")
                        except ValueError:
                            pass

                    # Work Mode and Employment Type estimation
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
                        "posted_date": pub_date,
                        "source": self.source_name,
                        "salary": None,
                        "work_mode": work_mode,
                        "employment_type": employment_type
                    })

                except Exception as card_error:
                    logger.error(f"[{self.source_name}] Error parsing RSS item: {card_error}")
                    continue

        except Exception as parse_error:
            logger.error(f"[{self.source_name}] Error parsing Indeed RSS XML: {parse_error}", exc_info=True)

        return jobs
