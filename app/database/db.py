import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from app.config.settings import settings
from app.database.models import Base
from app.utils.logger import logger

DATABASE_URL = settings.DATABASE_URL

# Setup sqlite engine and async session maker
engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    connect_args={"timeout": 30} if "sqlite" in DATABASE_URL else {}
)

async_session_maker = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    class_=AsyncSession
)

async def init_db() -> None:
    """Initialize database tables."""
    try:
        # Resolve SQLite folder path and create if missing
        if "sqlite" in DATABASE_URL:
            db_file_path = DATABASE_URL.replace("sqlite+aiosqlite:///", "")
            # If path has a leading slash or dot, clean it up
            if db_file_path.startswith("./"):
                db_file_path = db_file_path[2:]
            
            # Resolve to project root absolute path if relative
            if not os.path.isabs(db_file_path):
                project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                db_file_path = os.path.join(project_root, db_file_path)
            
            db_dir = os.path.dirname(db_file_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
                logger.info(f"Ensured database directory exists at: {db_dir}")

        async with engine.begin() as conn:
            # Create all tables if they don't exist
            await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables initialized successfully.")
    except Exception as e:
        logger.critical(f"Failed to initialize database: {e}", exc_info=True)
        raise e
