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

async def run_migrations() -> None:
    """Detect and apply missing columns to existing SQLite tables based on ORM models."""
    from sqlalchemy import inspect, text
    try:
        async with engine.connect() as conn:
            def _migrate(sync_conn):
                inspector = inspect(sync_conn)
                for table_name, table_obj in Base.metadata.tables.items():
                    if not inspector.has_table(table_name):
                        continue
                    
                    # Fetch columns currently defined in the SQLite file
                    existing_columns = {col["name"] for col in inspector.get_columns(table_name)}
                    
                    # Compare against columns defined in the ORM schema
                    for col_name, col_obj in table_obj.columns.items():
                        if col_name not in existing_columns:
                            col_type = col_obj.type.compile(dialect=sync_conn.dialect)
                            
                            # Handle default constraints safely for SQLite alter table operations
                            null_stmt = "NULL" if col_obj.nullable else "NOT NULL"
                            default_stmt = ""
                            if col_obj.default is not None:
                                if hasattr(col_obj.default, "arg") and not callable(col_obj.default.arg):
                                    arg = col_obj.default.arg
                                    if isinstance(arg, str):
                                        default_stmt = f" DEFAULT '{arg}'"
                                    elif isinstance(arg, (int, float, bool)):
                                        default_stmt = f" DEFAULT {int(arg) if isinstance(arg, bool) else arg}"
                            
                            # SQLite doesn't allow adding NOT NULL columns without default values.
                            # Fallback to NULL if it's NOT NULL but lacks a default value.
                            if not col_obj.nullable and not default_stmt:
                                null_stmt = "NULL"

                            sql = f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type} {null_stmt}{default_stmt}"
                            logger.info(f"Applying schema migration: {sql}")
                            sync_conn.execute(text(sql))
            
            await conn.run_sync(_migrate)
            logger.info("Schema migrations checking complete.")
    except Exception as e:
        logger.error(f"Failed to auto-migrate database schema: {e}", exc_info=True)

async def init_db() -> None:
    """Initialize database tables and run automatic migrations."""
    try:
        # Resolve SQLite folder path and create if missing
        if "sqlite" in DATABASE_URL:
            db_file_path = DATABASE_URL.replace("sqlite+aiosqlite:///", "")
            if db_file_path.startswith("./"):
                db_file_path = db_file_path[2:]
            
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
            logger.info("Database tables initialized.")
        
        # Detect and apply column changes/migrations dynamically
        await run_migrations()
    except Exception as e:
        logger.critical(f"Failed to initialize database: {e}", exc_info=True)
        raise e
