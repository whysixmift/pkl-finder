import unittest
from unittest.mock import AsyncMock, MagicMock
from main import run_startup_diagnostics

class MockBotInfo:
    def __init__(self):
        self.username = "PKLFinderMockBot"

class TestStartupDiagnostics(unittest.IsolatedAsyncioTestCase):
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
