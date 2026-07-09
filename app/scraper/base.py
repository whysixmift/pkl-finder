import random
import asyncio
from typing import Dict, Any, List, Optional
import httpx
from app.utils.logger import logger

# List of common real-world user agents for rotation
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 10; K) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/605.1.15"
]

class BaseScraper:
    """Base scraper providing shared configurations, request clients, headers, and resilient parsing utilities."""

    def __init__(self, source_name: str) -> None:
        self.source_name = source_name
        self.timeout = 15.0
        self.last_status_code: Optional[int] = None
        self.is_disabled: bool = False

    def get_random_headers(self) -> Dict[str, str]:
        """Generate headers with rotated user-agent and standard browser headers."""
        ua = random.choice(USER_AGENTS)
        return {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Cache-Control": "max-age=0"
        }

    async def fetch_url(
        self, url: str, headers: Optional[Dict[str, str]] = None, retries: int = 3, is_json: bool = False
    ) -> Optional[Any]:
        """Fetch content from a URL with retries, exponential backoff, and error handling."""
        if self.is_disabled:
            logger.debug(f"[{self.source_name}] Request skipped. Scraper is currently disabled.")
            return None

        req_headers = headers or self.get_random_headers()
        backoff = 2.0
        self.last_status_code = None

        # Custom connection pooling via reusable AsyncClient limits
        limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, limits=limits) as client:
            for attempt in range(retries):
                try:
                    # Random delay between 1-3 seconds to prevent rate limits
                    await asyncio.sleep(random.uniform(1.0, 3.0))
                    
                    response = await client.get(url, headers=req_headers)
                    self.last_status_code = response.status_code
                    
                    if response.status_code == 429:
                        logger.warning(f"[{self.source_name}] Rate limited (429). Retrying after {backoff}s. Attempt {attempt + 1}/{retries}")
                        await asyncio.sleep(backoff)
                        backoff *= 2
                        continue

                    if response.status_code >= 500:
                        logger.warning(f"[{self.source_name}] Server error ({response.status_code}). Retrying... Attempt {attempt + 1}/{retries}")
                        await asyncio.sleep(backoff)
                        backoff *= 2
                        continue

                    response.raise_for_status()
                    
                    if is_json:
                        return response.json()
                    return response.text

                except httpx.HTTPStatusError as e:
                    self.last_status_code = e.response.status_code
                    logger.error(f"[{self.source_name}] HTTP status error on fetch for {url}: {e}")
                    # Permanent failures (Issue 4) - Do NOT retry
                    if self.last_status_code in [401, 403, 404, 422]:
                        logger.error(f"[{self.source_name}] Permanent HTTP status error {self.last_status_code}. Aborting retries.")
                        return None
                    if attempt == retries - 1:
                        return None
                    await asyncio.sleep(backoff)
                    backoff *= 2
                except httpx.HTTPError as e:
                    logger.error(f"[{self.source_name}] HTTP error on fetch for {url}: {e}")
                    if attempt == retries - 1:
                        return None
                    await asyncio.sleep(backoff)
                    backoff *= 2
                except Exception as e:
                    logger.error(f"[{self.source_name}] Unexpected error fetching {url}: {e}", exc_info=True)
                    return None

        return None

    async def scrape(self, keyword: str, location: str) -> List[Dict[str, Any]]:
        """
        Abstract scrape method. Must be overridden by subclasses.
        """
        raise NotImplementedError("Scrapers must implement the scrape method.")
