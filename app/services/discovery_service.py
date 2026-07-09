import urllib.parse
import re
from typing import List, Set, Dict, Any
from bs4 import BeautifulSoup
import httpx
from sqlalchemy import select
from app.database.db import async_session_maker
from app.database.models import Company
from app.scraper.base import BaseScraper
from app.utils.logger import logger

DISCOVERY_QUERIES = [
    "software house indonesia",
    "robotics company indonesia",
    "embedded systems indonesia",
    "iot startup indonesia",
    "artificial intelligence indonesia",
    "computer vision indonesia",
    "firmware company indonesia",
    "technology startup indonesia",
    "engineering company indonesia"
]

EXCLUDED_DOMAINS = {
    "google.com", "youtube.com", "facebook.com", "instagram.com", "twitter.com",
    "linkedin.com", "indeed.com", "glints.com", "jobstreet.co.id", "jobstreet.com",
    "kalibrr.com", "medium.com", "wikipedia.org", "github.com", "glassdoor.com",
    "glassdoor.co.id", "kaskus.co.id", "kompas.com", "detik.com", "techinasia.com",
    "reddit.com", "pinterest.com", "jobstreet.co.id", "jobstreet.id", "co.id", "com"
}

class CompanyDiscoveryEngine(BaseScraper):
    def __init__(self) -> None:
        super().__init__("company_discovery")

    def _extract_domain(self, url: str) -> Optional[str]:
        """Extract the root protocol + host from a URL."""
        try:
            parsed = urllib.parse.urlparse(url)
            if not parsed.netloc:
                return None
            netloc = parsed.netloc.lower()
            if netloc.startswith("www."):
                netloc = netloc[4:]
            
            # Skip broad directories
            if netloc in EXCLUDED_DOMAINS or any(netloc.endswith(f".{d}") for d in EXCLUDED_DOMAINS):
                return None
                
            return f"{parsed.scheme}://{netloc}"
        except Exception:
            return None

    def _clean_company_name(self, domain: str) -> str:
        """Derive a company name from its domain address."""
        parsed = urllib.parse.urlparse(domain)
        host = parsed.netloc
        if host.startswith("www."):
            host = host[4:]
        name = host.split(".")[0].replace("-", " ").replace("_", " ")
        return name.title()

    async def discover_companies(self, limit_per_query: int = 15) -> List[Company]:
        """Queries Google Search to discover local tech company websites and registers them in DB."""
        logger.info("Executing automated company discovery crawls")
        discovered_domains: Set[str] = set()
        discovered_records: List[Company] = []

        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Mobile Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8"
        }

        # Perform searches
        for query in DISCOVERY_QUERIES:
            encoded_query = urllib.parse.quote(query)
            url = f"https://www.google.com/search?q={encoded_query}&num={limit_per_query}"
            
            logger.debug(f"Searching query: {query}")
            html = await self.fetch_url(url, headers=headers)
            if not html:
                continue

            try:
                soup = BeautifulSoup(html, "html.parser")
                cards = soup.select(".kCrYT")
                for card in cards:
                    a_tag = card.select_one("a")
                    if not a_tag:
                        continue
                    
                    href = a_tag.get("href", "")
                    if href.startswith("/url?q="):
                        parsed_url = urllib.parse.urlparse(href)
                        query_params = urllib.parse.parse_qs(parsed_url.query)
                        target_url = query_params.get("q", [None])[0]
                        
                        if target_url:
                            domain = self._extract_domain(target_url)
                            if domain:
                                discovered_domains.add(domain)
            except Exception as e:
                logger.error(f"Error parsing discovery search output: {e}")

        logger.info(f"Discovered {len(discovered_domains)} unique domains after filtering")

        # Save to database
        async with async_session_maker() as session:
            for domain in discovered_domains:
                try:
                    name = self._clean_company_name(domain)
                    
                    # Verify if company name or website already exists
                    stmt = select(Company).where(
                        (Company.website == domain) | (Company.name == name)
                    )
                    res = await session.execute(stmt)
                    existing = res.scalar_one_or_none()
                    
                    if not existing:
                        new_company = Company(
                            name=name,
                            website=domain,
                            is_discovered=True,
                            status="discovered"
                        )
                        session.add(new_company)
                        discovered_records.append(new_company)
                except Exception as e:
                    logger.error(f"Error checking/saving discovered company {domain}: {e}")

            await session.commit()
            
        logger.info(f"Registered {len(discovered_records)} new companies in database")
        return discovered_records

# Shared instance
discovery_engine = CompanyDiscoveryEngine()
