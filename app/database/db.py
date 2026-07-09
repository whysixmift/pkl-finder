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

def refresh_engine() -> None:
    """Re-bind the async engine and session maker dynamically if settings.DATABASE_URL changes."""
    global engine, async_session_maker
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=False,
        connect_args={"timeout": 30} if "sqlite" in settings.DATABASE_URL else {}
    )
    async_session_maker = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession
    )

async def init_db() -> None:
    """Initialize database tables and run automatic migrations."""
    refresh_engine()
    from app.database.migrations import run_auto_migrations, get_db_file_path, verify_database_schema
    from alembic.config import Config
    from alembic import command
    
    db_path = get_db_file_path()
    is_fresh = False
    if db_path and not os.path.exists(db_path):
        is_fresh = True
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
            logger.info(f"Created database directory at: {db_dir}")

    try:
        if is_fresh:
            logger.info("Initializing fresh database schema...")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            
            # Stamp database as head so Alembic knows it is initialized at current version
            alembic_cfg = Config("alembic.ini")
            command.stamp(alembic_cfg, "head")
            logger.info("Database schema initialized and stamped at HEAD revision.")
            
            # Verify table connectivity
            verify_database_schema()
        else:
            # Existing database, execute programmatic migrations
            run_auto_migrations()
            
    except Exception as e:
        logger.critical(f"Failed to initialize database: {e}", exc_info=True)
        raise e
