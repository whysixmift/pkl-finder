# Project Architecture

The PKL Finder application is built using Clean Architecture principles, ensuring clear separation of concerns, modular components, and ease of extensibility. The system is designed to run asynchronously in a single-process event loop, driving concurrent web scrapers, local AI evaluators, and active Telegram bot clients.

## Architecture Layers

```
+-------------------------------------------------------------+
|                      Infrastructure Layer                   |
|  - httpx (HTTP Fetcher)      - APScheduler (Task Trigger)   |
|  - SQLite & SQLAlchemy       - python-telegram-bot (API)    |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|                      Adapters Layer                         |
|  - BaseScraper Subclasses (Glints, Indeed, LinkedIn, etc.)  |
|  - OpenRouterEvaluator Client                               |
|  - Telegram Command & Callback Handlers                     |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|                      Services Layer                         |
|  - JobService (Scraping, AI Matching, DB Deduplication,    |
|                History, Favorites Management)               |
+-------------------------------------------------------------+
                              |
                              v
+-------------------------------------------------------------+
|                        Domain Layer                         |
|  - SQLAlchemy Entities (Job, AIScore, Company, History,     |
|                         Favorite)                           |
+-------------------------------------------------------------+
```

### 1. Domain Layer (Entities)
Located in `app/database/models.py`, this layer defines the central domain entities representing core models of the business logic. These entities have no dependencies on external libraries other than SQLAlchemy decorators to declare schemas. They describe the structure of Jobs, Companies, AI Scores, Favorites, and histories.

### 2. Services Layer (Use Cases)
Located in `app/services/job_service.py`, this layer orchestrates the application's flow of control. It exposes high-level capabilities to the adapters:
* Running the complete scraping pipeline.
* Passing scraped entries to the AI evaluation engine.
* Deciding whether a job is recommended based on the score threshold.
* Storing unique entries into the database.
* Managing student favorites and action logging.

The service layer is entirely decoupled from the delivery mechanisms (Telegram commands, REST endpoints) and execution triggers (scheduler, manual run).

### 3. Adapters Layer (Interfaces)
This layer translates external events into application use cases, and app objects into external service payloads:
* **Scraper System (`app/scraper/`)**: Adapts raw portal search layouts (Glints, Indeed, LinkedIn, Jobstreet, Kalibrr, Google) to a standardized Python dictionary structure.
* **AI Evaluator (`app/ai/`)**: Adapts candidate CV parameters and job descriptions into LLM prompts, parsing JSON results into typed `AIResult` models.
* **Telegram Handlers (`app/bot/`)**: Adapts Telegram commands (`/start`, `/search`, `/latest`, etc.) and Callback Queries into database lookups and service operations.

### 4. Infrastructure Layer
This layer contains external software packages, driver connectors, and network clients:
* **APScheduler (`app/scheduler/`)**: Powers timed background loop execution.
* **aiosqlite / SQLite**: Handles disk persistence.
* **httpx**: Executes async network transactions with OpenRouter and target job portals.

---

## Data Flow Pipeline

The standard operating lifecycle flow behaves as follows:

1. **Trigger**: The APScheduler interval clock or an admin Telegram `/search` command invokes `JobService.run_scraping_and_matching()`.
2. **Scraping**: The service executes all registered scrapers concurrently. Each scraper generates a target HTTP query using random User-Agents, processes the returned HTML or RSS XML, and returns a standardized job dictionary list.
3. **Deduplication**: The service maps incoming jobs by their URL and queries the database for existing matches using a SHA-256 hash key (`Job.job_key`). Already existing jobs are skipped.
4. **Evaluation**: For each new job, the description and title are compiled into a structured prompt containing the student CV profile. This is dispatched to the OpenRouter API. If the connection fails, the system redirects the job to the rule-based local regex matching engine.
5. **Persistence**: The evaluation result is stored in the `ai_scores` table, linked to the `Job` record. The transaction is committed.
6. **Notification**: If the evaluation score is greater than or equal to the configured threshold, the service returns the job. The scheduler or command handler receives it, formats it into an HTML message, attaches interactive favoriting markup, and dispatches it to the admin's Telegram chat.
