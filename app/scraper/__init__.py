from app.scraper.base import BaseScraper
from app.scraper.glints import GlintsScraper
from app.scraper.linkedin import LinkedInScraper
from app.scraper.indeed import IndeedScraper
from app.scraper.jobstreet import JobstreetScraper
from app.scraper.kalibrr import KalibrrScraper
from app.scraper.google_jobs import GoogleJobsScraper

__all__ = [
    "BaseScraper",
    "GlintsScraper",
    "LinkedInScraper",
    "IndeedScraper",
    "JobstreetScraper",
    "KalibrrScraper",
    "GoogleJobsScraper",
]
