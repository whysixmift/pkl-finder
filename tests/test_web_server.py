import os
import unittest
import asyncio
from fastapi.testclient import TestClient
from app.config.settings import settings

TEST_DB_FILE = "./data/test_web.db"
TEST_DATABASE_URL = f"sqlite+aiosqlite:///{TEST_DB_FILE}"

from app.database.db import refresh_engine
from app.web.server import create_web_app
from app.bot.server import create_bot_http_app
from app.web.security import create_admin_session

class TestWebServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.orig_url = settings.DATABASE_URL
        cls.db_path = TEST_DB_FILE
        settings.DATABASE_URL = TEST_DATABASE_URL
        refresh_engine()
        
        # Initialize tables
        from app.database.models import Base
        from app.database.db import engine
        async def init_tables():
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        asyncio.run(init_tables())

        cls.web_app = create_web_app()
        cls.client = TestClient(cls.web_app, follow_redirects=False)
        
        cls.bot_app = create_bot_http_app("@PKLFinderTestBot")
        cls.bot_client = TestClient(cls.bot_app)
        cls.env_existed = os.path.exists("./.env")
        if cls.env_existed:
            with open("./.env", "r") as f:
                cls.orig_env_content = f.read()

    @classmethod
    def tearDownClass(cls) -> None:
        from app.database.db import engine, refresh_engine
        asyncio.run(engine.dispose())
        if os.path.exists(cls.db_path):
            try:
                os.remove(cls.db_path)
            except Exception:
                pass
        env_file = "./.env"
        if getattr(cls, "env_existed", False):
            with open(env_file, "w") as f:
                f.write(cls.orig_env_content)
        elif os.path.exists(env_file):
            try:
                os.remove(env_file)
            except Exception:
                pass
        settings.DATABASE_URL = cls.orig_url
        refresh_engine()

    def setUp(self) -> None:
        self.client.cookies.clear()

    def test_public_landing_page(self) -> None:
        """Test public landing page loads with HTTP 200."""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("PKL Finder", response.text)
        self.assertIn("Multi-Tenant Autonomous", response.text)

    def test_admin_login_wrong_password(self) -> None:
        """Test admin login with wrong password returns 401."""
        response = self.client.post("/admin/login", data={"password": "wrong_password"})
        self.assertEqual(response.status_code, 401)
        self.assertIn("Password admin salah", response.text)

    def test_admin_login_correct_password(self) -> None:
        """Test admin login with correct password 'uranium235aregoated' sets session cookie."""
        response = self.client.post("/admin/login", data={"password": "uranium235aregoated"})
        self.assertEqual(response.status_code, 303)
        self.assertIn("pkl_admin_session", response.cookies)
        self.assertEqual(response.headers["location"], "/admin/dashboard")

    def test_admin_dashboard_protected_redirect(self) -> None:
        """Test accessing /admin/dashboard without auth redirects to /admin/login."""
        response = self.client.get("/admin/dashboard")
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/admin/login")

    def test_admin_dashboard_authorized(self) -> None:
        """Test accessing /admin/dashboard with valid session token loads dashboard."""
        token = create_admin_session()
        self.client.cookies.set("pkl_admin_session", token)
        
        response = self.client.get("/admin/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Executive Dashboard Overview", response.text)
        self.assertIn("Total PT / Perusahaan", response.text)

    def test_admin_add_user_whitelist_username_and_id(self) -> None:
        """Test adding users via web form supporting both username and user ID."""
        token = create_admin_session()
        self.client.cookies.set("pkl_admin_session", token)

        # 1. Add by username
        resp1 = self.client.post("/admin/users/add", data={"identifier": "@superdev", "notes": "Web Form Test"})
        self.assertEqual(resp1.status_code, 303)

        # 2. Add by User ID
        resp2 = self.client.post("/admin/users/add", data={"identifier": "987654321", "notes": "Numeric ID Test"})
        self.assertEqual(resp2.status_code, 303)

        # Verify both appear on users page
        get_resp = self.client.get("/admin/users")
        self.assertEqual(get_resp.status_code, 200)
        self.assertIn("@superdev", get_resp.text)
        self.assertIn("987654321", get_resp.text)

    def test_api_health_and_stats(self) -> None:
        """Test REST API endpoints."""
        health_resp = self.client.get("/api/health")
        self.assertEqual(health_resp.status_code, 200)
        self.assertEqual(health_resp.json()["port"], 20129)

        stats_resp = self.client.get("/api/stats")
        self.assertEqual(stats_resp.status_code, 200)
        self.assertIn("total_companies", stats_resp.json())

    def test_bot_http_service_port_20128(self) -> None:
        """Test Port 20128 Bot service HTTP server."""
        resp = self.bot_client.get("/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["port"], 20128)
        self.assertEqual(data["service"], "pkl-finder-bot")

        health_resp = self.bot_client.get("/health")
        self.assertEqual(health_resp.status_code, 200)
        self.assertEqual(health_resp.json()["status"], "healthy")

    def test_admin_settings_protected_redirect(self) -> None:
        """Test accessing /admin/settings without auth redirects to /admin/login."""
        response = self.client.get("/admin/settings")
        self.assertEqual(response.status_code, 307)
        self.assertEqual(response.headers["location"], "/admin/login")

    def test_admin_settings_page_and_save(self) -> None:
        """Test viewing and updating .env configurations via web admin dashboard."""
        token = create_admin_session()
        self.client.cookies.set("pkl_admin_session", token)

        # 1. View settings page
        get_resp = self.client.get("/admin/settings")
        self.assertEqual(get_resp.status_code, 200)
        self.assertIn("Pengaturan Environment (.env)", get_resp.text)
        self.assertIn("TELEGRAM_BOT_TOKEN", get_resp.text)
        self.assertIn("Raw .env Editor", get_resp.text)

        # 2. Save structured settings form
        post_data = {
            "telegram_bot_token": "test_token_updated_via_admin",
            "telegram_admin_id": "7891011",
            "openrouter_api_key": "sk-or-v1-new-key-12345",
            "primary_model": "google/gemma-4-31b-it:free",
            "fallback_models": "qwen/qwen-2.5-72b-instruct:free",
            "openrouter_api_url": "https://openrouter.ai/api/v1/chat/completions",
            "google_client_id": "test_client_id.apps.googleusercontent.com",
            "google_client_secret": "test_client_secret",
            "google_redirect_uri": "http://localhost:20129/api/auth/google/callback",
            "admin_password": "uranium235aregoated",
            "bot_port": "20128",
            "web_port": "20129",
            "host": "0.0.0.0",
            "web_base_url": "http://localhost:20129",
            "database_url": "sqlite+aiosqlite:///data/jobs.db",
            "check_interval_minutes": "45",
            "max_jobs_per_run": "25",
            "score_threshold": "75",
            "search_keywords": "intern backend,pkl software",
            "search_locations": "Jakarta,Remote",
        }
        post_resp = self.client.post("/admin/settings/form", data=post_data)
        self.assertEqual(post_resp.status_code, 303)
        self.assertIn("/admin/settings", post_resp.headers["location"])

        # Verify updated settings reflected in settings singleton
        from app.config.settings import settings
        self.assertEqual(settings.TELEGRAM_BOT_TOKEN, "test_token_updated_via_admin")
        self.assertEqual(settings.TELEGRAM_ADMIN_ID, 7891011)
        self.assertEqual(settings.SCORE_THRESHOLD, 75)

        # 3. Save raw .env editor
        raw_payload = "TELEGRAM_BOT_TOKEN=raw_token_test\nTELEGRAM_ADMIN_ID=9999\nADMIN_PASSWORD=uranium235aregoated\n"
        raw_resp = self.client.post("/admin/settings/raw", data={"raw_env_content": raw_payload})
        self.assertEqual(raw_resp.status_code, 303)
        self.assertEqual(settings.TELEGRAM_BOT_TOKEN, "raw_token_test")

        # 4. Reset to example
        reset_resp = self.client.post("/admin/settings/reset")
        self.assertEqual(reset_resp.status_code, 303)

if __name__ == "__main__":
    unittest.main()
