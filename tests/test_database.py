import unittest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select
from app.database.models import Base, Job, Company, Favorite, History, AIScore

class TestDatabase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        """Set up in-memory sqlite database engine and session maker."""
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        self.session_maker = async_sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def asyncTearDown(self) -> None:
        """Dispose the engine to clean up memory."""
        await self.engine.dispose()

    async def test_company_and_job_relationship(self) -> None:
        """Test creating a company and linking it to a job posting."""
        async with self.session_maker() as session:
            company = Company(name="Tesla Robotics")
            session.add(company)
            await session.flush()

            job = Job(
                job_key="tesla_job_1",
                title="Robotics Control Intern",
                company_id=company.id,
                company_name=company.name,
                location="Remote",
                description="Working on PID tuning and motor controls.",
                url="https://tesla.com/intern",
                posted_date=datetime.now(timezone.utc).replace(tzinfo=None),
                source="indeed",
            )
            session.add(job)
            await session.commit()

        async with self.session_maker() as session:
            stmt = select(Job).where(Job.job_key == "tesla_job_1")
            res = await session.execute(stmt)
            db_job = res.scalar_one_or_none()

            self.assertIsNotNone(db_job)
            self.assertEqual(db_job.company_name, "Tesla Robotics")
            self.assertEqual(db_job.title, "Robotics Control Intern")

    async def test_favorites_and_history(self) -> None:
        """Test tracking favorites and history events linked to a job."""
        async with self.session_maker() as session:
            job = Job(
                job_key="fav_job_1",
                title="Embedded C++ Intern",
                company_name="IoT Tech",
                location="Bekasi",
                description="C++ microcontrollers development.",
                url="https://iotech.com/intern",
                posted_date=datetime.now(timezone.utc).replace(tzinfo=None),
                source="glints",
            )
            session.add(job)
            await session.flush()

            # Link favorite and history entries
            fav = Favorite(job_id=job.id)
            hist = History(job_id=job.id, action="scraped", details="Found on Glints")
            session.add_all([fav, hist])
            await session.commit()

        async with self.session_maker() as session:
            stmt = select(Favorite).where(Favorite.job_id == job.id)
            res = await session.execute(stmt)
            self.assertIsNotNone(res.scalar_one_or_none())

            hist_stmt = select(History).where(History.job_id == job.id)
            hist_res = await session.execute(hist_stmt)
            histories = hist_res.scalars().all()
            self.assertEqual(len(histories), 1)
            self.assertEqual(histories[0].action, "scraped")

if __name__ == "__main__":
    unittest.main()
