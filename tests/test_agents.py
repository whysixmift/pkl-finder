import os
import unittest
import asyncio
from app.config.settings import settings

TEST_DB_FILE = "./data/test_agents.db"
TEST_DATABASE_URL = f"sqlite+aiosqlite:///{TEST_DB_FILE}"

from app.database.db import init_db, refresh_engine, async_session_maker
from app.database.models import Company, Job, CVProfile, UserWhitelist
from app.agents import (
    access_control_agent,
    cv_agent,
    email_drafting_agent,
    email_dispatch_agent,
    scraper_agent,
    discovery_agent,
    matching_agent,
    scheduler_agent,
)

class TestAgents(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.orig_url = settings.DATABASE_URL
        cls.db_path = TEST_DB_FILE
        if os.path.exists(cls.db_path):
            try:
                os.remove(cls.db_path)
            except Exception:
                pass
        settings.DATABASE_URL = TEST_DATABASE_URL
        refresh_engine()

    @classmethod
    def tearDownClass(cls) -> None:
        from app.database.db import engine, refresh_engine
        asyncio.run(engine.dispose())
        if os.path.exists(cls.db_path):
            try:
                os.remove(cls.db_path)
            except Exception:
                pass
        settings.DATABASE_URL = cls.orig_url
        refresh_engine()

    async def asyncSetUp(self) -> None:
        settings.DATABASE_URL = TEST_DATABASE_URL
        refresh_engine()
        from app.database.models import Base
        from app.database.db import engine
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            for table in reversed(Base.metadata.sorted_tables):
                await conn.execute(table.delete())

    async def asyncTearDown(self) -> None:
        from app.database.models import Base
        from app.database.db import engine
        async with engine.begin() as conn:
            for table in reversed(Base.metadata.sorted_tables):
                await conn.execute(table.delete())
        await engine.dispose()

    async def test_access_control_agent_whitelist_username_and_id(self) -> None:
        """Test whitelist access verification by both username and user ID."""
        settings.TELEGRAM_ADMIN_ID = 999999
        self.assertTrue(await access_control_agent.is_allowed(999999))
        self.assertFalse(await access_control_agent.is_allowed(12345, "unauthorized_user"))

        # Add user by username (with @)
        success, msg, data = await access_control_agent.add_to_whitelist("@cooldev", "VIP Student")
        self.assertTrue(success)
        self.assertEqual(data["username"], "cooldev")

        # Verify username is allowed
        self.assertTrue(await access_control_agent.is_allowed(55555, "cooldev"))
        self.assertTrue(await access_control_agent.is_allowed(55555, "@CoolDev"))

        # Add user by numeric User ID
        success, msg, data = await access_control_agent.add_to_whitelist("778899", "SMK Bekasi")
        self.assertTrue(success)
        self.assertEqual(data["telegram_id"], 778899)
        self.assertTrue(await access_control_agent.is_allowed(778899))

        # Test toggle status
        users = await access_control_agent.list_whitelisted_users()
        user_id_to_toggle = users[0]["id"]
        t_ok, t_msg = await access_control_agent.toggle_status(user_id_to_toggle)
        self.assertTrue(t_ok)

        # Test removal
        r_ok, r_msg = await access_control_agent.remove_from_whitelist(user_id_to_toggle)
        self.assertTrue(r_ok)

    async def test_cv_agent_ingest_and_retrieve(self) -> None:
        """Test CV agent ingesting a mock text / doc and saving to profile."""
        async with async_session_maker() as session:
            profile = CVProfile(
                user_id=101,
                filename="julian_cv.pdf",
                file_path="./data/cvs/101_julian_cv.pdf",
                cv_text="SMK 2 Bekasi Software Engineering Python C++ IoT"
            )
            session.add(profile)
            await session.commit()

        async with async_session_maker() as session:
            fetched = await cv_agent.get_user_cv(session, 101)
            self.assertIsNotNone(fetched)
            self.assertEqual(fetched.user_id, 101)
            self.assertIn("Python", fetched.cv_text)

    async def test_email_drafting_agent_attaches_cv(self) -> None:
        """Test that EmailDraftingAgent creates personalized draft and attaches CV."""
        async with async_session_maker() as session:
            company = Company(name="PT Inovasi Teknologi", recruitment_email="hr@inovasi.id")
            session.add(company)
            await session.flush()

            job = Job(
                job_key="mock_key_test_agent",
                title="Python Backend Intern",
                company_id=company.id,
                company_name=company.name,
                location="Jakarta",
                description="Backend engineer intern with Python and FastAPI experience.",
                url="https://inovasi.id/career/python-intern",
                source="glints"
            )
            session.add(job)

            cv = CVProfile(
                user_id=202,
                filename="my_cv.pdf",
                file_path="./data/cvs/202_my_cv.pdf",
                cv_text="SMK 2 Bekasi Software Engineering. Python, Git, Linux."
            )
            session.add(cv)
            await session.commit()

            draft = await email_drafting_agent.draft_email_for_job(
                session=session,
                user_id=202,
                company_id=company.id,
                job_id=job.id
            )
            self.assertIsNotNone(draft)
            self.assertEqual(draft.recipient_email, "hr@inovasi.id")
            self.assertIn("PT Inovasi Teknologi", draft.subject + draft.body)

    async def test_all_agents_telemetry_reporting(self) -> None:
        """Test that each agent produces valid telemetry status."""
        agents = [
            scraper_agent, discovery_agent, cv_agent, matching_agent,
            email_drafting_agent, email_dispatch_agent, access_control_agent, scheduler_agent
        ]
        self.assertEqual(len(agents), 8)
        for ag in agents:
            st = ag.get_status()
            self.assertIn("name", st)
            self.assertIn("feature", st)
            self.assertIn("status", st)
            self.assertIn("total_runs", st)

if __name__ == "__main__":
    unittest.main()
