# PKL Finder - Multi-Tenant AI Internship Hunter SaaS

PKL Finder is a production-grade, multi-tenant automated internship (PKL) hunting platform. It is engineered to scrape internship listings across multiple job sites, perform semantic AI evaluation using LLMs via OpenRouter, maintain isolated user data stores, and automatically manage target outreach email campaigns.

---

## Technical Architecture

The platform is designed around a decoupled, modular architecture split into distinct layers:

1. **Orchestration Layer (`main.py`)**: Bootstraps the application, executes startup diagnostics, runs migrations to the latest database version, and schedules background jobs.
2. **Database & Migration Layer (`app/database/`)**: Governs SQLite connections via SQLAlchemy 2.0 async engine (`aiosqlite`) and manages schema changes dynamically using Alembic.
3. **Scraper Engine (`app/scraper/`)**: Hosts individual scraper providers inheriting from `BaseScraper` with built-in retry logic, user-agent rotation, and backoff delay strategies.
4. **AI Evaluator (`app/ai/`)**: Standardizes semantic job match evaluations and cold email drafting via the `BaseLLMProvider` abstraction, supporting fallback regex matching and OpenRouter failovers.
5. **Business Services (`app/services/`)**: Orchestrates core business operations such as CV text ingestion, global job storage, multi-tenant AI matching loops, and email scheduling.
6. **Telegram Interface (`app/bot/`)**: Provides conversational commands, state-machine setup workflows, and callback query handlers for user interactions.

```
+-------------------------------------------------------+
|                 Telegram Bot Interface                |
+-------------------------------------------------------+
                           |
                           v
+-------------------------------------------------------+
|                    Business Services                  |
|    (JobService, CVService, EmailService, Crawler)     |
+-------------------------------------------------------+
       |                   |                   |
       v                   v                   v
+--------------+    +--------------+    +--------------+
| Scraper Hub  |    |  AI Engine   |    | SQLAlchemy   |
| (BaseScraper)|    | (BaseLLMPro) |    | (Multi-Ten)  |
+--------------+    +--------------+    +--------------+
```

---

## Directory Structure

```
pkl-finder/
├── .github/
│   └── workflows/
│       └── ci.yml            # CI/CD lint, type check, unit tests, and build flow
├── alembic/                  # Alembic migration configurations and version files
├── app/
│   ├── ai/                   # LLM provider clients, prompt templates, and structures
│   ├── bot/                  # Telegram UI command routes and callbacks
│   ├── config/               # Pydantic environment configurations
│   ├── database/             # SQLite connection pools, ORM models, and validations
│   ├── scheduler/            # Background cron triggers and scheduling locks
│   ├── scraper/              # Base class and site-specific scrapers
│   ├── services/             # Operations mapping scrapers, AI matching, and SMTP
│   └── utils/                # Rotating file loggers
├── data/                     # Persistent database volumes and keys
├── logs/                     # Rotation logs
├── tests/                    # Pytest integration, unit, and migration suites
├── Dockerfile                # Consolidated application runner
├── docker-compose.yml        # Multi-volume orchestration file
├── requirements.txt          # Python dependencies list
└── README.md                 # System documentation
```

---

## Core Systems Implementation

### 1. Database Versioning and Integrity
The database employs SQLite with strict schema enforcement. Database upgrades are managed programmatically on startup by comparing the active SQLite database revision against the latest compiled Alembic scripts.
- **Auto-Backup**: Prior to applying migrations, the database engine makes a timestamped backup copy in `data/backups/`.
- **Retention**: Only the 10 most recent backups are retained; older files are removed automatically to conserve disk space.
- **Failover**: If a migration script encounters an error, the active database is rolled back, the prior backup is restored, and the application aborts startup to prevent corruption.
- **Verification**: Following any schema change, a validation suite performs test queries against all defined metadata tables to ensure columns, keys, and indexes exist.

### 2. Multi-Tenant Resource Isolation
The platform is designed to handle multiple concurrent users safely. Shared resources are separated from private user assets:
- **Global Resources**: `jobs` and `companies` tables are shared. Jobs are scraped, normalized, and stored once globally to prevent redundant requests and scraper blocks.
- **User Isolated Resources**: `cv_profiles`, `smtp_configs`, `portfolios`, `cover_letters`, `favorites`, `history`, and `email_queue` tables are isolated using a mandatory `user_id` foreign key.
- **Authorization**: Access to query or update user-specific data via Telegram is verified against the `update.effective_user.id` to prevent cross-tenant data leaks.

### 3. Resilient Scraper Provider Architecture
All scrapers (LinkedIn, Glints, JobStreet, Kalibrr, Indeed, and Google Jobs) inherit from `BaseScraper`. 
- **Graceful Degradation**: If one scraper fails due to rate-limiting, Cloudflare blocks, or structural DOM changes, the scraping cycle bypasses the provider and continues processing other scrapers.
- **Rotated Headers**: Rotation of User-Agents and connection parameters is applied on each outbound request.
- **Cloudflare Bypass**: RSS parsing feeds are implemented for Indeed to bypass browser challenge pages.

### 4. Semantic AI Engine and OpenRouter Abstraction
AI evaluations are decoupled from conversational handlers and standard jobs:
- **Abstraction**: High-level services call `BaseLLMProvider`, isolating the system from OpenRouter-specific clients and payloads.
- **Failover Routing**: OpenRouter calls compile a failover queue starting with the primary model (`google/gemma-4-31b-it:free`) and falling back to alternative options if timeouts, 429 rate-limits, or credit depletion occur.
- **Retry Backoff**: Transient errors trigger automatic exponential backoff retries. Permanent errors (e.g. 401 Unauthorized, 402 Insufficient Funds) trigger immediate failover to the next candidate model.
- **Fallback Matcher**: If all LLM providers fail, the system falls back to a local regex-based rule matcher.

### 5. Email Application and Approval Pipeline
outbound cold emails are handled securely using encrypted configurations:
- **Encryption**: SMTP passwords are encrypted in the database using Fernet symmetric encryption. The key is persisted at `data/secret.key` in the docker volume.
- **SMTP Verification**: Configurations are validated via test connections before being saved.
- **Approval Workflow**: Cold emails are generated by the AI matching engine and queued as `draft` entries in `email_queue`. They must be manually approved (`/queue` and inline button options) by the user before being dispatched to the recruiter.

---

## Deployment Instructions

### Prerequisites
1. Docker and Docker Compose installed.
2. A Telegram bot token obtained from `@BotFather`.
3. An OpenRouter API Key.

### Environment Configuration
Create a `.env` file in the root directory based on `.env.example`:
```env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_ADMIN_ID=your_telegram_user_id
OPENROUTER_API_KEY=your_openrouter_api_key
PRIMARY_MODEL=google/gemma-4-31b-it:free
FALLBACK_MODELS=qwen/qwen-2.5-72b-instruct:free,google/gemma-2-9b-it:free
```

### Running with Docker Compose
To build and start the service in background daemon mode:
```bash
docker compose up --build -d
```

To view current application runtime logs:
```bash
docker compose logs -f
```

To stop the running container services:
```bash
docker compose down
```

---

## Operational Commands

### User Commands
- `/start` - Initial welcome handshake.
- `/help` - Lists command options.
- `/search` - Runs scraping pipelines globally and semantic matching for the user.
- `/latest` - Lists the 10 newest semantic recommendations matching the user's CV.
- `/profile` - Displays the user's uploaded CV, portfolio links, and cover letters.
- `/uploadcv` - Conversational state to upload a new CV (.PDF or .DOCX).
- `/uploadportfolio` - Saves portfolio link or files.
- `/uploadcoverletter` - Saves cover letter text template.
- `/credentials` - Configures SMTP sender configurations.
- `/email` - Displays the active SMTP configuration.
- `/queue` - Lists pending email drafts with inline actions (Approve, Reject, Send, Edit).
- `/sendall` - Dispatches all approved email drafts in the queue.
- `/favorites` - Lists favorited job openings.
- `/history` - Logs matching operations and user bookmarks history.

### Administrator Commands (Restricted)
- `/health` - Verifies database connectivity, migrations, and LLM statuses.
- `/models` - Measures latency and connection health of configured OpenRouter models.
- `/providers` - Shows active and disabled scraper engines.
- `/migrations` - Displays the current Alembic revision.
- `/schema` - Compares database schema against ORM mappings.
- `/doctor` - Run complete diagnostic and troubleshooting checks.
- `/system` - Monitors host CPU, RAM, and disk utilization.
- `/cache` - Monitors the size of global intelligence caches.
- `/metrics` - Tracks conversion metrics and email delivery rates.
- `/logs` - Retreives the 15 newest log entries from the rotation files.

---

## Testing and Code Quality

### Running Tests
Execute the pytest integration test suite from the virtual environment:
```bash
.venv/bin/pytest -W ignore::DeprecationWarning
```

### Linting and Formatting
Check and fix python style and formatting guidelines:
```bash
.venv/bin/ruff check . --fix
```

### Static Type Checks
Run strict static type analysis:
```bash
.venv/bin/mypy --ignore-missing-imports --disable-error-code union-attr --disable-error-code arg-type --disable-error-code assignment --disable-error-code index --disable-error-code attr-defined .
```
