import os
import unittest
from unittest.mock import AsyncMock, MagicMock
from app.config.settings import settings

TEST_DB_FILE = "./data/test_startup.db"
TEST_DATABASE_URL = f"sqlite+aiosqlite:///{TEST_DB_FILE}"

from app.database.db import refresh_engine
from main import run_startup_diagnostics

class MockBotInfo:
    def __init__(self):
        self.username = "PKLFinderMockBot"

class TestStartupDiagnostics(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.orig_url = settings.DATABASE_URL
        self.db_path = TEST_DB_FILE
        settings.DATABASE_URL = TEST_DATABASE_URL
        refresh_engine()

    async def asyncTearDown(self) -> None:
        from app.database.db import engine
        await engine.dispose()
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass
        settings.DATABASE_URL = self.orig_url
        refresh_engine()

    async def test_diagnostics_grid(self):
        # 1. Setup mock application
        mock_application = MagicMock()
        mock_application.bot.get_me = AsyncMock(return_value=MockBotInfo())
        
        print("\n=== RUNNING MOCK STARTUP DIAGNOSTICS ===")
        # 2. Execute actual startup diagnostics function
        try:
            await run_startup_diagnostics(mock_application)
            print("=========================================\n")
        except SystemExit as e:
            # Trap system exit if any step fails
            self.assertEqual(e.code, 0, "Startup diagnostics raised fatal error exit.")

if __name__ == "__main__":
    unittest.main()
