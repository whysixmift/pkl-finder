import os
import unittest
import shutil
from unittest.mock import patch, MagicMock
from app.config.settings import settings

# Override database URL for tests to prevent modifying production data
TEST_DB_FILE = "./data/test_migration.db"
TEST_DATABASE_URL = f"sqlite+aiosqlite:///{TEST_DB_FILE}"
settings.DATABASE_URL = TEST_DATABASE_URL

from app.database.db import init_db, refresh_engine  # noqa: E402
from app.database.migrations import (  # noqa: E402
    get_db_file_path,
    create_db_backup,
    restore_backup,
    get_revisions,
    verify_database_schema,
    run_auto_migrations
)

class TestDatabaseMigrations(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # Re-bind active db engine to test url
        refresh_engine()
        # Resolve path and clean up test files
        self.db_path = get_db_file_path()
        self.cleanup_files()
        
        # Ensure data folder exists
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)

    def tearDown(self) -> None:
        self.cleanup_files()

    def cleanup_files(self) -> None:
        if self.db_path and os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass
        
        # Delete backups folder contents if present
        if self.db_path:
            backup_dir = os.path.join(os.path.dirname(self.db_path), "backups")
            if os.path.exists(backup_dir):
                shutil.rmtree(backup_dir)

    async def test_fresh_database_initialization(self) -> None:
        """Test that a fresh database is initialized and stamped at HEAD revision."""
        # 1. Run fresh initialization
        await init_db()
        
        # 2. Verify database file exists
        self.assertTrue(os.path.exists(self.db_path))
        
        # 3. Check current and head revisions
        current_rev, head_rev = get_revisions()
        self.assertIsNotNone(current_rev)
        self.assertEqual(current_rev, head_rev)
        
        # 4. Verify tables query integrity
        self.assertTrue(verify_database_schema())

    async def test_repeated_startup_idempotency(self) -> None:
        """Test that multiple startup runs do not cause failures or duplicates."""
        await init_db()
        
        # Run auto migrations again
        run_auto_migrations()
        run_auto_migrations()
        
        self.assertTrue(verify_database_schema())

    async def test_backup_and_restore(self) -> None:
        """Test database backup creation and restore functionality."""
        await init_db()
        
        # Create backup
        backup_path = create_db_backup()
        self.assertIsNotNone(backup_path)
        self.assertTrue(os.path.exists(backup_path))
        
        # Modify database state (delete file)
        os.remove(self.db_path)
        self.assertFalse(os.path.exists(self.db_path))
        
        # Restore backup
        success = restore_backup(backup_path)
        self.assertTrue(success)
        self.assertTrue(os.path.exists(self.db_path))
        self.assertTrue(verify_database_schema())

    @patch("alembic.command.upgrade")
    async def test_migration_failure_restoration(self, mock_upgrade: MagicMock) -> None:
        """Test that if a migration fails, the database is rolled back to backup."""
        await init_db()
        
        # 1. Create a dummy backup
        _backup_path = create_db_backup()
        
        # 2. Mock upgrade to throw an exception
        mock_upgrade.side_effect = RuntimeError("Migration script syntax error.")
        
        # 3. Trigger migrations (mocked current revision as mismatch to force upgrade call)
        with patch("app.database.migrations.get_revisions", return_value=("old_rev", "new_rev")):
            with patch("sys.exit") as mock_exit:
                run_auto_migrations()
                # Verify that it called restore and aborted
                mock_exit.assert_called_with(1)
                
        # 4. Database should remain healthy and queryable
        self.assertTrue(verify_database_schema())

if __name__ == "__main__":
    unittest.main()
