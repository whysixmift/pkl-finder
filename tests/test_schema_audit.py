import unittest
import os
import sqlalchemy as sa
from sqlalchemy import create_engine
from app.config.settings import settings

TEST_DB_FILE = "./data/test_schema_audit.db"
TEST_DATABASE_URL = f"sqlite+aiosqlite:///{TEST_DB_FILE}"

from app.database.db import init_db, refresh_engine  # noqa: E402
from app.database.schema_audit import perform_schema_audit  # noqa: E402

class TestSchemaAudit(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.orig_url = settings.DATABASE_URL
        self.db_path = TEST_DB_FILE
        settings.DATABASE_URL = TEST_DATABASE_URL
        refresh_engine()
        from app.database.db import engine
        await engine.dispose()
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

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

    async def test_schema_audit_synced(self) -> None:
        """Test that schema-audit returns True when database matches ORM metadata."""
        await init_db()
        
        sync_url = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "sqlite:///")
        engine = create_engine(sync_url)
        try:
            success, report = perform_schema_audit(engine)
            self.assertTrue(success)
            self.assertIn("✓ id", "".join(report))
        finally:
            engine.dispose()

    async def test_schema_audit_missing_table(self) -> None:
        """Test that schema-audit flags missing tables."""
        await init_db()
        
        sync_url = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "sqlite:///")
        engine = create_engine(sync_url)
        try:
            # Manually drop a table
            with engine.begin() as conn:
                conn.execute(sa.text("DROP TABLE smtp_configs"))
                
            success, report = perform_schema_audit(engine)
            self.assertFalse(success)
            self.assertIn("✗ Table 'smtp_configs' is missing in the database", "".join(report))
        finally:
            engine.dispose()

    async def test_schema_audit_missing_column(self) -> None:
        """Test that schema-audit flags missing columns."""
        await init_db()
        
        sync_url = settings.DATABASE_URL.replace("sqlite+aiosqlite:///", "sqlite:///")
        engine = create_engine(sync_url)
        try:
            with engine.begin() as conn:
                conn.execute(sa.text("ALTER TABLE cv_profiles RENAME COLUMN cv_text TO cv_text_old"))
                
            success, report = perform_schema_audit(engine)
            self.assertFalse(success)
            self.assertIn("✗ cv_text", "".join(report))
        finally:
            engine.dispose()

if __name__ == "__main__":
    unittest.main()
