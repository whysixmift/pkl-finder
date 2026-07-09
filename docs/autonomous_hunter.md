# AI Internship Hunter - Autonomous Platform Features

This document provides a detailed technical overview of the autonomous company discovery, career crawling, CV ingestion, and secure SMTP email queue dispatch systems implemented in the PKL Finder platform.

---

## 1. Dynamic CV Profile Ingestion (`/uploadcv`)

Instead of matching job postings against a static hardcoded string profile, the bot supports uploading dynamic CV documents.

### File Parsing Service (`CVService`)
* **File Types**: Supported formats are **PDF** and **DOCX**.
* **PDF Extraction**: Done via the `pypdf` library. It reads and merges text pages.
* **Word Document Extraction**: Done via the `python-docx` library, which aggregates text paragraphs.
* **Caching**: Extracted text is saved in the `cv_profiles` SQLite table.
* **Dynamic Matching**: During AI evaluations, the evaluator queries the database for the latest active profile. If none is found, it falls back to the default profile.

---

## 2. Company Discovery Engine (`CompanyDiscoveryEngine`)

The discovery engine crawls search engines to locate companies in Indonesia that align with specific technological keywords.

### Search Queries
The engine loops over predefined search queries, including:
* `"software house indonesia"`
* `"robotics company indonesia"`
* `"embedded systems indonesia"`
* `"iot startup indonesia"`
* `"artificial intelligence indonesia"`

### Harvesting & Domain Resolution
1. Google Search results are fetched using rotated User-Agent headers.
2. URLs are parsed to extract the root protocol and host (e.g., `https://example.com`).
3. **Filtering**: Global directories, news sites, and recruitment portals are excluded (e.g., `linkedin.com`, `glints.com`, `wikipedia.org`, etc.).
4. The cleaned website URL and estimated company name are registered in the `companies` database table.

---

## 3. Career Page Crawler & Email Harvester

Once companies are discovered, the platform crawls their sites to detect openings and contact emails.

### Career Portal Probing
The crawler checks anchors for links containing terms like "career", "karir", "jobs", or "join", and probes common endpoints:
`/career`, `/careers`, `/jobs`, `/join-us`, `/karir`, `/recruitment`, `/work-with-us`, `/opportunities`, `/work`

### Email Harvester Regex
If no active internship page is detected, the crawler scans the homepage and career page HTML for email addresses using regex patterns.

* **Prioritized Mailboxes**: Addresses containing `career`, `jobs`, `recruitment`, `recruit`, `talent`, `hr`, or `people`.
* **Fallback Mailboxes**: Addresses starting with `info@`.
* **Ignored Mailboxes (Junk Filter)**: Common support, legal, and billing mailboxes (like `support@`, `privacy@`, `security@`, `legal@`, `abuse@`, `billing@`) are explicitly bypassed.

---

## 4. Open Application Flow & AI Email Writer

If a company website contains a recruitment email but has no active internship posting, the system initiates an **Open Application** flow.

### Flow Architecture
1. The company's details are sent to the OpenRouter AI Evaluator.
2. The AI evaluates the company profile against the candidate's CV text.
3. If the fit score is $\ge 70$, the AI generates a customized application email consisting of:
   * A targeted subject line.
   * A personalized body pitching the candidate's specific skills (Python, Embedded Systems, IoT, etc.) to the company.
4. The draft is queued in the `email_queue` table with a status of `draft`.

---

## 5. SMTP Configuration & Approval Queue

The SMTP dispatcher manages mail delivery for approved drafts.

### Secure Symmetric Encryption
To store SMTP passwords securely, the system uses the `cryptography.fernet` module.
* A Fernet key is generated on startup and cached in the persistent data volume (`data/secret.key`).
* Passwords entered via the `/credentials` command are encrypted before database persistence.

### Verification Check
When credentials are configured, the platform executes a synchronous verification check in a thread pool (`aiosmtplib` equivalent):
1. Connects to host:port.
2. Upgrades connection via SSL or StartTLS based on configuration.
3. Authenticates using username and decrypted password.
4. If authentication fails, the configuration is rejected.

### Telegram Approval Queue Handler
Administrators manage queued drafts via Telegram using `/queue`:
* **Approve**: Changes draft status to `approved`.
* **Reject**: Marks draft as `rejected`.
* **Edit**: Allows replacing the email body text.
* **Send**: Dispatches the email immediately.
* **SendAll**: Dispatches all approved emails in the database queue using the active SMTP configuration.
