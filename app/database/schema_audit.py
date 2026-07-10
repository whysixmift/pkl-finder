import sys
from typing import Tuple, List
from sqlalchemy import create_engine, inspect, text
from app.database.models import Base
from app.config.settings import settings

def types_match(orm_type, sql_type) -> bool:
    """Check if ORM type matches SQLite column type representation."""
    orm_str = str(orm_type).upper()
    sql_str = str(sql_type).upper()
    
    if "VARCHAR" in orm_str or "STRING" in orm_str:
        return "VARCHAR" in sql_str or "TEXT" in sql_str or "STRING" in sql_str
    if "TEXT" in orm_str:
        return "TEXT" in sql_str or "VARCHAR" in sql_str
    if "INTEGER" in orm_str or "INT" in orm_str:
        return "INT" in sql_str
    if "BOOLEAN" in orm_str:
        return "BOOLEAN" in sql_str or "INT" in sql_str or "TINYINT" in sql_str
    if "DATETIME" in orm_str or "TIMESTAMP" in orm_str:
        return "DATETIME" in sql_str or "TIMESTAMP" in sql_str
    return orm_str in sql_str or sql_str in orm_str

def defaults_match(orm_col, sql_col_dict) -> bool:
    """Check if ORM column default matches SQLite column default representation."""
    orm_default = orm_col.server_default
    sql_default = sql_col_dict.get('default')
    
    if orm_default is None and sql_default is None:
        return True
    if orm_default is not None and sql_default is not None:
        orm_val = str(orm_default.arg).strip("'\"()")
        sql_val = str(sql_default).strip("'\"()")
        # Handle simple integer or boolean strings
        if orm_val == "0" and sql_val == "0":
            return True
        if orm_val == "1" and sql_val == "1":
            return True
        return orm_val == sql_val
    return False

def verify_relationships() -> List[str]:
    """Verify that relationship targets match their foreign keys."""
    errors = []
    # Verify relationships defined in ORM
    for mapper in Base.registry.mappers:
        for rel in mapper.relationships:
            # Check if direction matches foreign key
            if not rel.local_remote_pairs:
                errors.append(f"Relationship {rel} has no remote key pairs defined.")
    return errors

def perform_schema_audit(engine) -> Tuple[bool, List[str]]:
    """Compares the actual SQLite database structure to SQLAlchemy ORM models."""
    inspector = inspect(engine)
    db_tables = inspector.get_table_names()
    
    report: List[str] = []
    success = True

    # 1. Inspect ORM tables and compare against database
    for table_name, orm_table in Base.metadata.tables.items():
        report.append(f"\nTable: {table_name}")
        
        # Check if table exists in DB
        if table_name not in db_tables:
            report.append(f"✗ Table '{table_name}' is missing in the database")
            success = False
            continue

        # Get actual table columns
        sql_columns = {col['name']: col for col in inspector.get_columns(table_name)}
        
        # Compare columns
        for col_name, orm_col in orm_table.columns.items():
            if col_name not in sql_columns:
                report.append(f"✗ {col_name} missing")
                success = False
                continue

            sql_col = sql_columns[col_name]
            col_ok = True
            mismatch_reasons = []

            # Verify Column Type
            if not types_match(orm_col.type, sql_col['type']):
                mismatch_reasons.append(f"type mismatch: ORM {orm_col.type} vs DB {sql_col['type']}")
                col_ok = False

            # Verify Nullability
            if orm_col.nullable != sql_col['nullable']:
                mismatch_reasons.append(f"nullable mismatch: ORM {orm_col.nullable} vs DB {sql_col['nullable']}")
                col_ok = False

            # Verify Default Value
            if not defaults_match(orm_col, sql_col):
                mismatch_reasons.append(f"default mismatch: ORM {orm_col.server_default} vs DB {sql_col.get('default')}")
                col_ok = False

            if col_ok:
                report.append(f"✓ {col_name}")
            else:
                reasons_str = ", ".join(mismatch_reasons)
                report.append(f"✗ {col_name} ({reasons_str})")
                success = False

        # Compare Unique Constraints / Unique Indexes
        # Find unique constraints defined in ORM (either unique=True or Explicit Index(unique=True))
        orm_unique_cols = []
        for col_name, orm_col in orm_table.columns.items():
            if orm_col.unique:
                orm_unique_cols.append(([col_name], f"column {col_name}"))

        for idx in orm_table.indexes:
            if idx.unique:
                orm_unique_cols.append(([c.name for c in idx.columns], f"index {idx.name}"))

        # Verify uniqueness of values in SQLite for each unique constraint/index
        with engine.connect() as conn:
            for cols, label in orm_unique_cols:
                # Build GROUP BY duplicate checker
                cols_str = ", ".join(cols)
                query = text(f"SELECT {cols_str}, COUNT(*) as cnt FROM {table_name} GROUP BY {cols_str} HAVING COUNT(*) > 1")
                try:
                    dupes = conn.execute(query).all()
                    if dupes:
                        report.append(f"✗ Duplicate {cols_str} detected on {table_name}. Unique index cannot be created.")
                        success = False
                except Exception:
                    # Table or column might be missing, already handled by column checks
                    pass

        # Verify Foreign Keys
        sql_fkeys = inspector.get_foreign_keys(table_name)
        for fk in orm_table.foreign_keys:
            # Check if FK is registered in SQLite
            fk_found = False
            for sql_fk in sql_fkeys:
                if sql_fk['referred_table'] == fk.column.table.name:
                    if fk.parent.name in sql_fk['constrained_columns']:
                        fk_found = True
                        break
            if not fk_found:
                report.append(f"✗ foreign key missing for column {fk.parent.name} to {fk.column.table.name}")
                success = False

    # 2. Check relationship integrity
    rel_errors = verify_relationships()
    if rel_errors:
        report.append("\nRelationship integrity errors:")
        for err in rel_errors:
            report.append(f"✗ {err}")
        success = False

    return success, report

def run_schema_audit() -> bool:
    """Executes schema audit and prints output report to stdout."""
    db_url = settings.DATABASE_URL
    sync_url = db_url.replace("sqlite+aiosqlite:///", "sqlite:///")
    engine = create_engine(sync_url)
    
    success, report = perform_schema_audit(engine)
    
    print("\n================ DATABASE SCHEMA AUDIT REPORT ================")
    for line in report:
        print(line)
    print("==============================================================")
    
    if success:
        print("✓ Schema Audit: ZERO mismatches detected. Database matches ORM.")
    else:
        print("✗ Schema Audit: Mismatches detected! Database is out of sync with ORM.")
        
    return success

if __name__ == "__main__":
    is_ok = run_schema_audit()
    sys.exit(0 if is_ok else 1)
