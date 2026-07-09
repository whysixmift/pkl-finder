# Scraper System Architecture

The scraper system crawler is located in `app/scraper/`. It crawls job postings from multiple job portals, maps them to a unified schema, and filters out duplicate entries.

## BaseScraper Architecture

All scrapers inherit from `BaseScraper` in `app/scraper/base.py`. The base class handles:

1. **User-Agent Rotation**: Rotates through a list of real-world User-Agents on each request to prevent fingerprinting.
2. **Standard Headers**: Sets common browser headers (`Accept`, `Accept-Language`, `Connection: keep-alive`) to mimic organic browser traffic.
3. **Resilient HTTP Client**: Uses `httpx.AsyncClient` with a 15-second timeout and support for redirects.
4. **Retry Loop with Exponential Backoff**: Retries failed requests up to 3 times, doubling the wait time on each attempt.
5. **Anti-Fingerprint Delays**: Includes a randomized sleep delay (1.0 to 3.0 seconds) before sending requests to prevent triggering rate limits.

---

## Scraper Modules

### 1. Kalibrr Scraper (`kalibrr.py`)
* **Target URL**: `https://www.kalibrr.com/job-board/y/1?query={keyword}&location={location}`
* **Parsing Engine**: `BeautifulSoup4` with `html.parser`.
* **Strategy**: Standard DOM parser. It selects containers matching `div[itemtype='http://schema.org/JobPosting']` or cards with class `k-border-b`. It extracts titles, links, companies, locations, descriptions, and salary ranges.
* **Date Parsing**: Estimates the post date by parsing text strings (e.g. `"2 days ago"` or `"a week ago"`) into timezone-neutral UTC datetimes.

### 2. Glints Scraper (`glints.py`)
* **Target URL**: `https://glints.com/id/en/opportunities/jobs?keyword={keyword}&location={location}`
* **Parsing Engine**: `BeautifulSoup4` with `html.parser`.
* **Strategy**: DOM parser targetting container components containing class patterns like `CompactOpportunityCardsc__CardContainer`. Extracts position URLs, titles, company links, locations, and salary info.
* **Work Mode & Type Matching**: Estimates the work mode (Remote/Hybrid/Onsite) and type (Internship/Full-time) by analyzing titles and card descriptions.

### 3. LinkedIn Scraper (`linkedin.py`)
* **Target URL**: `https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords={keyword}&location={location}&start=0`
* **Parsing Engine**: `BeautifulSoup4` with `html.parser`.
* **Strategy**: Targets LinkedIn's public guest job search API. This endpoint returns a list of simple HTML list items (`<li>`), which requires less resources to scrape and is less likely to trigger rate limits than the main search page.
* **URL Sanitization**: Extracts job links and removes referral tracking query parameters.

### 4. Indeed Scraper (`indeed.py`)
* **Target URL**: `https://id.indeed.com/rss?q={keyword}&l={location}`
* **Parsing Engine**: `xml.etree.ElementTree` (Standard Python Library).
* **Strategy**: Bypasses Indeed's Cloudflare protections by querying their public RSS XML feed instead of the HTML search interface.
* **Parsing Strategy**: Walks the XML tree to extract job items. The job title, company, and location are parsed from the `<title>` tag (which follows the pattern `[Title] - [Company] - [Location]`).

### 5. Jobstreet Scraper (`jobstreet.py`)
* **Target URL**: `https://www.jobstreet.co.id/id/job-search/{keyword}-jobs`
* **Parsing Engine**: `BeautifulSoup4` and `json` parsing.
* **Strategy**: Extracts job data from the server-side rendered state (`window.SEEK_REDUX_DATA`) embedded in a `<script>` tag on the search results page. This provides access to structured JSON data without traversing the DOM. If the script tag is missing, the scraper falls back to parsing DOM elements with `article` tags.

### 6. Google Jobs Scraper (`google_jobs.py`)
* **Target URL**: `https://www.google.com/search?q={keyword}+internship+in+{location}&num=15`
* **Parsing Engine**: `BeautifulSoup4` with `html.parser`.
* **Strategy**: Queries Google Search using a mobile User-Agent to retrieve basic HTML results. It parses search result containers with class `.kCrYT` and extracts titles, links, and snippets.
* **URL Redirect Parsing**: Extracts the destination URL from Google's redirect link format (`/url?q=...`) and filters out non-job URLs (e.g. YouTube, social media sites).

---

## Portal Deduplication

To prevent duplicate job entries across multiple sources, the application generates a unique SHA-256 hash of the job URL (`job_key`). Before running evaluations or writing to the database, the system verifies that the `job_key` does not already exist in the database.
