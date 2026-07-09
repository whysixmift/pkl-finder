import unittest
from unittest.mock import AsyncMock, patch
from app.scraper.kalibrr import KalibrrScraper
from app.scraper.glints import GlintsScraper
from app.scraper.indeed import IndeedScraper

class TestScrapers(unittest.IsolatedAsyncioTestCase):
    @patch("app.scraper.base.BaseScraper.fetch_url", new_callable=AsyncMock)
    async def test_kalibrr_parsing(self, mock_fetch) -> None:
        """Test Kalibrr HTML parsing logic with mocked response."""
        mock_html = """
        <div itemtype="http://schema.org/JobPosting">
            <a itemprop="title" href="/job-board/y/1/job/1234">Python Developer Intern</a>
            <span itemprop="name">TechCorp</span>
            <span itemprop="addressLocality">Bekasi</span>
            <div itemprop="description">Looking for Python and IoT intern.</div>
            <span class="k-text-subdued">2 days ago</span>
        </div>
        """
        mock_fetch.return_value = mock_html
        
        scraper = KalibrrScraper()
        jobs = await scraper.scrape("python", "Bekasi")
        
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Python Developer Intern")
        self.assertEqual(jobs[0]["company"], "TechCorp")
        self.assertEqual(jobs[0]["location"], "Bekasi")
        self.assertEqual(jobs[0]["source"], "kalibrr")

    @patch("app.scraper.base.BaseScraper.fetch_url", new_callable=AsyncMock)
    async def test_indeed_rss_parsing(self, mock_fetch) -> None:
        """Test Indeed RSS XML parsing logic with mocked response."""
        mock_xml = """<?xml version="1.0" encoding="UTF-8" ?>
        <rss version="2.0">
        <channel>
            <item>
                <title>Backend Engineer Intern - Tech Indonesia - Jakarta</title>
                <link>https://id.indeed.com/viewjob?jk=123</link>
                <description>Python, SQL, API development.</description>
                <pubDate>Fri, 10 Jul 2026 12:00:00 GMT</pubDate>
            </item>
        </channel>
        </rss>
        """
        mock_fetch.return_value = mock_xml
        
        scraper = IndeedScraper()
        jobs = await scraper.scrape("backend", "Jakarta")
        
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Backend Engineer Intern")
        self.assertEqual(jobs[0]["company"], "Tech Indonesia")
        self.assertEqual(jobs[0]["location"], "Jakarta")
        self.assertEqual(jobs[0]["source"], "indeed")

    @patch("app.scraper.base.BaseScraper.fetch_url", new_callable=AsyncMock)
    async def test_glints_parsing(self, mock_fetch) -> None:
        """Test Glints HTML parsing logic with mocked response."""
        mock_html = """
        <div class="CompactOpportunityCardsc__CardContainer-sc-15w8tq9-0">
            <h3 class="CompactOpportunityCardsc__JobTitle-sc-15w8tq9-1"><a href="/id/en/opportunities/jobs/python-intern">Python Intern</a></h3>
            <div class="CompactOpportunityCardsc__CompanyName-sc-15w8tq9-2">Astra International</div>
            <span class="CompactOpportunityCardsc__CardLocation-sc-15w8tq9-3">Jakarta</span>
            <div class="CompactOpportunityCardsc__Description-sc-15w8tq9-4">Python programming internship.</div>
        </div>
        """
        mock_fetch.return_value = mock_html
        
        scraper = GlintsScraper()
        jobs = await scraper.scrape("python", "Jakarta")
        
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["title"], "Python Intern")
        self.assertEqual(jobs[0]["company"], "Astra International")
        self.assertEqual(jobs[0]["location"], "Jakarta")
        self.assertEqual(jobs[0]["source"], "glints")

if __name__ == "__main__":
    unittest.main()
