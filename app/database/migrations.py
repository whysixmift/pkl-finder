import os
import sys
import shutil
import glob
from datetime import datetime
from typing import Tuple, Optional
from sqlalchemy import create_engine, text
from alembic.config import Config
from alembic import command
from alembic.script import ScriptDirectory
from alembic.runtime.migration import MigrationContext
from app.config.settings import settings
from app.database.models import Base
from app.utils.logger import logger

BACKUP_RETENTION = 10

def get_db_file_path() -> Optional[str]:
    """Resolve the SQLite database filepath from the database URL."""
    db_url = settings.DATABASE_URL
    if "sqlite" not in db_url:
        return None
    
    db_file_path = db_url.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
    if db_file_path.startswith("./"):
        db_file_path = db_file_path[2:]
        
    if not os.path.isabs(db_file_path):
        project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        db_file_path = os.path.join(project_root, db_file_path)
    return db_file_path

def create_db_backup() -> Optional[str]:
    """Create a timestamped backup of the current SQLite database."""
    db_path = get_db_file_path()
    if not db_path or not os.path.exists(db_path):
        return None

    # Get backup directory
    backup_dir = os.path.join(os.path.dirname(db_path), "backups")
    os.makedirs(backup_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup_filename = f"jobs_{timestamp}.db"
    backup_path = os.path.join(backup_dir, backup_filename)

    try:
        shutil.copy2(db_path, backup_path)
        logger.info(f"Created database backup: {backup_path}")
        
        # Enforce backup retention policies
        enforce_backup_retention(backup_dir)
        return backup_path
    except Exception as e:
        logger.error(f"Failed to create database backup: {e}")
        return None

def enforce_backup_retention(backup_dir: str) -> None:
    """Retain only the latest N backup files, deleting older ones."""
    backup_files = glob.glob(os.path.join(backup_dir, "jobs_*.db"))
    # Sort by modification time (oldest first)
    backup_files.sort(key=os.path.getmtime)

    if len(backup_files) > BACKUP_RETENTION:
        excess_count = len(backup_files) - BACKUP_RETENTION
        for i in range(excess_count):
            try:
                os.remove(backup_files[i])
                logger.info(f"Removed old backup: {backup_files[i]}")
            except Exception as e:
                logger.error(f"Failed to remove old backup file {backup_files[i]}: {e}")

def restore_backup(backup_path: str) -> bool:
    """Restore the database file from a backup."""
    db_path = get_db_file_path()
    if not db_path:
        return False
    try:
        shutil.copy2(backup_path, db_path)
        logger.warning(f"Database successfully restored from backup: {backup_path}")
        return True
    except Exception as e:
        logger.critical(f"CRITICAL: Failed to restore database backup {backup_path}: {e}")
        return False

def get_revisions() -> Tuple[Optional[str], Optional[str]]:
    """Fetch the current database revision and the head revision from Alembic."""
    db_url = settings.DATABASE_URL
    sync_url = db_url.replace("sqlite+aiosqlite:///", "sqlite:///")
    engine = create_engine(sync_url)
    
    alembic_cfg = Config("alembic.ini")
    script = ScriptDirectory.from_config(alembic_cfg)
    
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        current_rev = context.get_current_revision()
        
    head_rev = script.get_current_head()
    return current_rev, head_rev

def verify_database_schema() -> bool:
    """Execute a simple query against every registered table to verify schema integrity."""
    db_url = settings.DATABASE_URL
    sync_url = db_url.replace("sqlite+aiosqlite:///", "sqlite:///")
    engine = create_engine(sync_url)
    
    logger.info("Verifying database schema integrity...")
    try:
        with engine.connect() as conn:
            for table_name in Base.metadata.tables.keys():
                # Execute simple select on each table to verify structure
                conn.execute(text(f"SELECT 1 FROM {table_name} LIMIT 1"))
                logger.info(f"Table verification check: {table_name} ........ OK")
        return True
    except Exception as e:
        logger.error(f"Database schema verification failed: {e}")
        return False

def run_auto_migrations() -> None:
    """Main orchestrator for managing dynamic schema migrations on startup."""
    db_path = get_db_file_path()
    if not db_path or not os.path.exists(db_path):
        # Database does not exist yet; it will be created by create_all in init_db
        return

    # 1. Fetch revisions
    try:
        current_rev, head_rev = get_revisions()
    except Exception as e:
        logger.error(f"Failed to fetch database revisions: {e}")
        return

    logger.info(f"Current Database Revision ....... {current_rev or 'None (Fresh)'}")
    logger.info(f"Latest Migration Revision ....... {head_rev}")

    if current_rev == head_rev:
        logger.info("Database schema is fully up-to-date. No migrations pending.")
        # Verify schema integrity anyway
        if not verify_database_schema():
            logger.critical("Database schema verification failed. Aborting startup.")
            sys.exit(1)
        return

    # 2. Create backup before migrations
    backup_path = create_db_backup()
    if not backup_path:
        logger.critical("Aborting migration: Failed to secure database backup.")
        sys.exit(1)

    # 3. Apply migrations
    logger.info("Applying pending database migrations...")
    alembic_cfg = Config("alembic.ini")
    
    try:
        command.upgrade(alembic_cfg, "head")
        logger.info("Database Migration ..... COMPLETE")
        
        # 4. Verify after migration
        if not verify_database_schema():
            raise RuntimeError("Database schema verification failed post-migration.")
            
    except Exception as e:
        logger.critical(f"\n=======================================================\n"
                        f"DATABASE MIGRATION FAILED!\n"
                        f"Error: {e}\n"
                        f"=======================================================")
        
        # 5. Restore from backup
        logger.warning("Rolling back database to previous working state...")
        if restore_backup(backup_path):
            logger.info("Database restored successfully. Migration changes aborted.")
        else:
            logger.critical("DATABASE CORRUPTION: Rollback restoration failed!")
            
        sys.exit(1)
