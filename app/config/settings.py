import os
import sys
from typing import List
from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # API Keys
    OPENROUTER_API_KEY: str = "mock_key"
    PRIMARY_MODEL: str = "google/gemma-4-31b-it:free"
    FALLBACK_MODELS: str = "qwen/qwen-2.5-72b-instruct:free,deepseek/deepseek-chat:free"
    OPENROUTER_API_URL: str = "https://openrouter.ai/api/v1/chat/completions"

    @property
    def OPENROUTER_MODEL(self) -> str:
        return self.PRIMARY_MODEL

    @property
    def fallback_models_list(self) -> List[str]:
        return [m.strip() for m in self.FALLBACK_MODELS.split(",") if m.strip()]

    # Telegram Bot Settings
    TELEGRAM_BOT_TOKEN: str = "mock_token"
    TELEGRAM_ADMIN_ID: int = 0

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/jobs.db"

    # Scraper & Scheduler Settings
    CHECK_INTERVAL_MINUTES: int = 60
    MAX_JOBS_PER_RUN: int = 20
    LOG_LEVEL: str = "INFO"
    TIMEZONE: str = "Asia/Jakarta"
    USER_AGENT: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    # Filtering Settings
    SCORE_THRESHOLD: int = 70

    # Search Configuration
    SEARCH_KEYWORDS: str = "internship software engineering,magang backend,intern iot,pkl rpl"
    SEARCH_LOCATIONS: str = "Jakarta,Bekasi,Depok,Tangerang,Bogor,Remote"

    @property
    def keywords_list(self) -> List[str]:
        return [kw.strip() for kw in self.SEARCH_KEYWORDS.split(",") if kw.strip()]

    @property
    def locations_list(self) -> List[str]:
        return [loc.strip() for loc in self.SEARCH_LOCATIONS.split(",") if loc.strip()]

    # Pydantic Configuration
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

# Instantiate settings singleton with validation trapping
try:
    settings = Settings()
except ValidationError as e:
    print("=" * 60, file=sys.stderr)
    print("FATAL ERROR: CONFIGURATION VALIDATION FAILED (.env)", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    for error in e.errors():
        field = " -> ".join(str(p) for p in error['loc'])
        print(f"[-] Variable: {field}", file=sys.stderr)
        print(f"    Message : {error['msg']}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print("Please fix the environment variables and try again.", file=sys.stderr)
    sys.exit(1)
