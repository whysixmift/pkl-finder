# 🚀 AI-Powered PKL & Internship Finder Telegram Bot

An automated, production-ready, 24/7 AI-driven Internship (PKL) Finder Telegram Bot built for Indonesian students. 

The bot automatically scrapes internship opportunities from multiple job websites (Glints, LinkedIn, Indeed, Jobstreet, Kalibrr, Google Jobs), evaluates details against your CV/profile using an LLM via OpenRouter, stores data locally in SQLite via SQLAlchemy, and delivers instant notifications of high-matching roles directly to Telegram.

---

## 🛠 Features

- **Clean Architecture & Modular Design**: Segregated configuration, database, models, scrapers, AI modules, and scheduler.
- **Resilient Multi-Source Scraping**: Built-in scraper engines for Glints, LinkedIn, Indeed, Jobstreet, Kalibrr, and Google Jobs using User-Agent rotation and backoff delay strategies.
- **RSS-based Scrapers**: Bypasses heavy Cloudflare blocks on sites like Indeed and LinkedIn guest search APIs.
- **AI-Powered Matching Engine**: Integrates with OpenRouter (using cheap/free models like Qwen 30B) to score job fit. Fallback regex-matching is active if the API is offline.
- **Interactive Telegram UI**: Supports inline button callbacks (favoriting/unfavoriting directly from messages) and HTML message layouts.
- **Background Scheduler**: Powered by APScheduler to scan for jobs automatically on a configurable timeline.
- **Robust Persistence**: Employs SQLAlchemy 2.0 with `asyncio` and `aiosqlite`.
- **VPS Deployment Ready**: Containerized with Docker and Docker Compose.

---

## 📂 Folder Structure

```text
pkl-finder/
├── app/
│   ├── ai/               # AI Evaluator clients and prompts
│   ├── bot/              # Telegram command and callback handlers
│   ├── config/           # Pydantic environment configurations
│   ├── database/         # SQLite and SQLAlchemy database connections/models
│   ├── scheduler/        # Background scheduler task setups
│   ├── scraper/          # Scraper engine modules for Glints, Indeed, etc.
│   ├── services/         # Orchestrator services linking scrapers, AI, and DB
│   └── utils/            # Shared utilities (logger configurations)
├── data/                 # Folder containing sqlite DB file (Docker-mounted)
├── logs/                 # Rotating file logs (Docker-mounted)
├── tests/                # Local test suite
├── Dockerfile            # Multi-layer Docker build recipe
├── docker-compose.yml    # Orchestration configuration
├── requirements.txt      # Stable package dependencies
├── .env.example          # Sample environment variables template
├── .gitignore            # Version control exclusions
├── main.py               # Main runtime bootstrapper
└── README.md             # This document
```

---

## ⚙️ Configuration Setup

### 1. Telegram Bot Token (BotFather)
1. Open Telegram and search for [@BotFather](https://t.me/BotFather).
2. Start a chat and send `/newbot`.
3. Follow the instructions to choose a name and username.
4. Copy the generated API Token.
5. Get your personal Telegram Chat ID (e.g., via [@userinfobot](https://t.me/userinfobot) or [@IDBot](https://t.me/myidbot)) and copy it for `TELEGRAM_ADMIN_ID`.

### 2. OpenRouter API Key
1. Sign up on [OpenRouter](https://openrouter.ai/).
2. Deposit minor funds or use free models.
3. Go to **API Keys** and generate a new key.
4. Copy it for `OPENROUTER_API_KEY`.

---

## 🚀 Installation & Running

### Option A: Local Run (Development)

1. **Clone or Navigate to the Folder**:
   ```bash
   cd pkl-finder
   ```

2. **Setup Virtual Environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Setup Environment File**:
   ```bash
   cp .env.example .env
   ```
   Open `.env` and fill in `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_ID`, and `OPENROUTER_API_KEY`.

5. **Run Tests**:
   ```bash
   python -m unittest discover tests
   ```

6. **Start Bot**:
   ```bash
   python main.py
   ```

---

### Option B: Run with Docker (Production Recommended)

Docker ensures that the bot, database, and scheduled tasks run in isolation and automatically start on system reboots.

1. **Setup Environment File**:
   ```bash
   cp .env.example .env
   # Populate values inside .env
   ```

2. **Launch Container**:
   ```bash
   docker compose up -d
   ```

3. **Check Service Logs**:
   ```bash
   docker compose logs -f
   ```

4. **Stop Container**:
   ```bash
   docker compose down
   ```

---

## 📲 Telegram Bot Commands

Once the bot starts, search your bot username in Telegram, press **Start** (or send `/start`), and use the following commands:

- `/search` — Manually trigger scrapers and evaluate match criteria. Best matches are sent instantly.
- `/latest` — Lists the 5 newest jobs matched by the system.
- `/favorites` — Lists all jobs you have favorited.
- `/profile` — View the candidate profile text used by the matching AI.
- `/stats` — Displays database statistics including source distribution.
- `/recheck` — Re-evaluates all saved vacancies in the DB (useful if you change your profile prompt or score threshold).
- `/settings` — Display configurations loaded from `.env` (API keys are masked).
- `/history` — Displays the 10 last actions taken by the bot.
- `/help` — Lists all commands.

---

## ☁️ Deploying to a Ubuntu VPS

1. **SSH into your VPS**:
   ```bash
   ssh user@your_vps_ip
   ```

2. **Install Docker and Git**:
   ```bash
   sudo apt update
   sudo apt install -y git docker.io docker-compose
   sudo systemctl enable --now docker
   ```

3. **Upload/Clone the pkl-finder project folder**.
4. **Create `.env`** file and insert credentials.
5. **Start service in background daemon mode**:
   ```bash
   docker compose up -d
   ```

---

## 🔧 Troubleshooting

- **Error: 401 Unauthorized Bot Token**: Check that `TELEGRAM_BOT_TOKEN` in your `.env` does not contain spaces and is exact.
- **Error: 429 Rate Limits**: The bot contains random delays between scraper requests and handles OpenRouter rate limits with backoff. If you hit limits, increase `CHECK_INTERVAL_MINUTES` in your `.env`.
- **Database Locks**: SQLite is configured with default connection timeouts. If database locks occur under heavy loads, ensure you're using `sqlite+aiosqlite` driver in `DATABASE_URL`.
