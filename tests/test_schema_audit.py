import unittest
import os
import sqlalchemy as sa
from sqlalchemy import create_engine
from app.config.settings import settings

# Redirect database for tests
TEST_DB_FILE = "./data/test_schema_audit.db"
TEST_DATABASE_URL = f"sqlite+aiosqlite:///{TEST_DB_FILE}"
settings.DATABASE_URL = TEST_DATABASE_URL

from app.database.db import init_db, refresh_engine
from app.database.schema_audit import perform_schema_audit

class TestSchemaAudit(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        refresh_engine()
        self.db_path = TEST_DB_FILE
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

    def tearDown(self) -> None:
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

    async def test_schema_audit_synced(self) -> None:
        """Test that schema-audit returns True when database matches ORM metadata."""
        await init_db()
        
        sync_url = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "sqlite:///")
        engine = create_engine(sync_url)
        
        success, report = perform_schema_audit(engine)
        self.assertTrue(success)
        self.assertIn("✓ id", "".join(report))

    async def test_schema_audit_missing_table(self) -> None:
        """Test that schema-audit flags missing tables."""
        await init_db()
        
        sync_url = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "sqlite:///")
        engine = create_engine(sync_url)
        
        # Manually drop a table
        with engine.begin() as conn:
            conn.execute(sa.text("DROP TABLE smtp_configs"))
            
        success, report = perform_schema_audit(engine)
        self.assertFalse(success)
        self.assertIn("✗ Table 'smtp_configs' is missing in the database", "".join(report))

    async def test_schema_audit_missing_column(self) -> None:
        """Test that schema-audit flags missing columns."""
        await init_db()
        
        sync_url = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "sqlite:///")
        engine = create_engine(sync_url)
        
        # SQLite doesn't support dropping columns easily in old versions without recreation,
        # but we can simulate a missing column by renaming a column
        with engine.begin() as conn:
            conn.execute(sa.text("ALTER TABLE cv_profiles RENAME COLUMN cv_text TO cv_text_old"))
            
        success, report = perform_schema_audit(engine)
        self.assertFalse(success)
        self.assertIn("✗ cv_text missing", "".join(report))

if __name__ == "__main__":
    unittest.main()
