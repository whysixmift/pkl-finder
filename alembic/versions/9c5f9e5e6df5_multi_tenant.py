"""multi_tenant

Revision ID: 9c5f9e5e6df5
Revises: 66d1ff3fb82b
Create Date: 2026-07-10 20:21:50.735126

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c5f9e5e6df5'
down_revision: Union[str, Sequence[str], None] = '66d1ff3fb82b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(inspector, table_name: str, col_name: str) -> bool:
    """Helper to check if a column exists in a table."""
    columns = [c['name'] for c in inspector.get_columns(table_name)]
    return col_name in columns


def index_exists(inspector, table_name: str, index_name: str) -> bool:
    """Helper to check if an index exists in a table."""
    indexes = [i['name'] for i in inspector.get_indexes(table_name)]
    return index_name in indexes


def upgrade() -> None:
    """Upgrade schema safely with data-aware deduplication and idempotent helpers."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def safe_add_column(table_name: str, column_name: str, col_type) -> None:
        if not column_exists(inspector, table_name, column_name):
            print(f"[MIGRATION] Adding column {table_name}.{column_name}")
            with op.batch_alter_table(table_name, schema=None) as batch_op:
                batch_op.add_column(sa.Column(column_name, col_type, server_default='0', nullable=False))
        else:
            print(f"[MIGRATION] Column {table_name}.{column_name} already exists. Skipping ADD COLUMN.")

    def safe_create_index(index_name: str, table_name: str, columns: list, unique: bool) -> None:
        if not index_exists(inspector, table_name, index_name):
            print(f"[MIGRATION] Creating index {index_name} on {table_name}({', '.join(columns)})")
            with op.batch_alter_table(table_name, schema=None) as batch_op:
                batch_op.create_index(index_name, columns, unique=unique)
        else:
            print(f"[MIGRATION] Index {index_name} on {table_name} already exists. Skipping CREATE INDEX.")

    # 1. Add user_id columns safely
    safe_add_column('ai_scores', 'user_id', sa.Integer())
    safe_add_column('cover_letters', 'user_id', sa.Integer())
    safe_add_column('cv_profiles', 'user_id', sa.Integer())
    safe_add_column('email_queue', 'user_id', sa.Integer())
    safe_add_column('favorites', 'user_id', sa.Integer())
    safe_add_column('history', 'user_id', sa.Integer())
    safe_add_column('portfolios', 'user_id', sa.Integer())
    safe_add_column('smtp_configs', 'user_id', sa.Integer())

    # 2. Create non-unique user_id indexes safely
    safe_create_index('ix_ai_scores_user_id', 'ai_scores', ['user_id'], unique=False)
    safe_create_index('ix_email_queue_user_id', 'email_queue', ['user_id'], unique=False)
    safe_create_index('ix_favorites_user_id', 'favorites', ['user_id'], unique=False)
    safe_create_index('ix_history_user_id', 'history', ['user_id'], unique=False)

    # 3. Data-Aware De-duplication Scan & Deletion Report before creating UNIQUE indexes
    # Scan and report duplicates for favorites
    if not index_exists(inspector, 'favorites', 'ix_favorites_user_job'):
        fav_dupes = bind.execute(sa.text(
            "SELECT user_id, job_id, COUNT(*), MAX(id) FROM favorites GROUP BY user_id, job_id HAVING COUNT(*) > 1"
        )).all()
        if fav_dupes:
            print(f"\n[DATA MIGRATION CLEANUP] Detected {len(fav_dupes)} duplicate user-job pair(s) in favorites table:")
            for row in fav_dupes:
                print(f"  - user_id: {row[0]}, job_id: {row[1]} -> found {row[2]} rows. Strategy: Keep newest row id: {row[3]}, delete older duplicates.")
            bind.execute(sa.text(
                "DELETE FROM favorites WHERE id NOT IN ("
                "  SELECT MAX(id) FROM favorites GROUP BY user_id, job_id"
                ")"
            ))

    # Scan and report duplicates for ai_scores
    if not index_exists(inspector, 'ai_scores', 'ix_ai_scores_user_job'):
        score_dupes = bind.execute(sa.text(
            "SELECT user_id, job_id, COUNT(*), MAX(id) FROM ai_scores GROUP BY user_id, job_id HAVING COUNT(*) > 1"
        )).all()
        if score_dupes:
            print(f"\n[DATA MIGRATION CLEANUP] Detected {len(score_dupes)} duplicate user-job pair(s) in ai_scores table:")
            for row in score_dupes:
                print(f"  - user_id: {row[0]}, job_id: {row[1]} -> found {row[2]} rows. Strategy: Keep newest row id: {row[3]}, delete older duplicates.")
            bind.execute(sa.text(
                "DELETE FROM ai_scores WHERE id NOT IN ("
                "  SELECT MAX(id) FROM ai_scores GROUP BY user_id, job_id"
                ")"
            ))

    # Scan and report duplicates for cover_letters
    if not index_exists(inspector, 'cover_letters', 'ix_cover_letters_user_id'):
        cl_dupes = bind.execute(sa.text(
            "SELECT user_id, COUNT(*), MAX(id) FROM cover_letters GROUP BY user_id HAVING COUNT(*) > 1"
        )).all()
        if cl_dupes:
            print(f"\n[DATA MIGRATION CLEANUP] Detected {len(cl_dupes)} duplicate cover_letters for user(s):")
            for row in cl_dupes:
                print(f"  - user_id: {row[0]} -> found {row[1]} rows. Strategy: Keep newest row id: {row[2]}, delete older duplicates.")
            bind.execute(sa.text(
                "DELETE FROM cover_letters WHERE id NOT IN ("
                "  SELECT MAX(id) FROM cover_letters GROUP BY user_id"
                ")"
            ))

    # Scan and report duplicates for cv_profiles
    if not index_exists(inspector, 'cv_profiles', 'ix_cv_profiles_user_id'):
        cv_dupes = bind.execute(sa.text(
            "SELECT user_id, COUNT(*), MAX(id) FROM cv_profiles GROUP BY user_id HAVING COUNT(*) > 1"
        )).all()
        if cv_dupes:
            print(f"\n[DATA MIGRATION CLEANUP] Detected {len(cv_dupes)} duplicate cv_profiles for user(s):")
            for row in cv_dupes:
                print(f"  - user_id: {row[0]} -> found {row[1]} rows. Strategy: Keep newest row id: {row[2]}, delete older duplicates.")
            bind.execute(sa.text(
                "DELETE FROM cv_profiles WHERE id NOT IN ("
                "  SELECT MAX(id) FROM cv_profiles GROUP BY user_id"
                ")"
            ))

    # Scan and report duplicates for portfolios
    if not index_exists(inspector, 'portfolios', 'ix_portfolios_user_id'):
        port_dupes = bind.execute(sa.text(
            "SELECT user_id, COUNT(*), MAX(id) FROM portfolios GROUP BY user_id HAVING COUNT(*) > 1"
        )).all()
        if port_dupes:
            print(f"\n[DATA MIGRATION CLEANUP] Detected {len(port_dupes)} duplicate portfolios for user(s):")
            for row in port_dupes:
                print(f"  - user_id: {row[0]} -> found {row[1]} rows. Strategy: Keep newest row id: {row[2]}, delete older duplicates.")
            bind.execute(sa.text(
                "DELETE FROM portfolios WHERE id NOT IN ("
                "  SELECT MAX(id) FROM portfolios GROUP BY user_id"
                ")"
            ))

    # Scan and report duplicates for smtp_configs
    if not index_exists(inspector, 'smtp_configs', 'ix_smtp_configs_user_id'):
        smtp_dupes = bind.execute(sa.text(
            "SELECT user_id, COUNT(*), MAX(id) FROM smtp_configs GROUP BY user_id HAVING COUNT(*) > 1"
        )).all()
        if smtp_dupes:
            print(f"\n[DATA MIGRATION CLEANUP] Detected {len(smtp_dupes)} duplicate smtp_configs for user(s):")
            for row in smtp_dupes:
                print(f"  - user_id: {row[0]} -> found {row[1]} rows. Strategy: Keep newest row id: {row[2]}, delete older duplicates.")
            bind.execute(sa.text(
                "DELETE FROM smtp_configs WHERE id NOT IN ("
                "  SELECT MAX(id) FROM smtp_configs GROUP BY user_id"
                ")"
            ))

    # 4. Create UNIQUE indexes safely
    safe_create_index('ix_ai_scores_user_job', 'ai_scores', ['user_id', 'job_id'], unique=True)
    safe_create_index('ix_cover_letters_user_id', 'cover_letters', ['user_id'], unique=True)
    safe_create_index('ix_cv_profiles_user_id', 'cv_profiles', ['user_id'], unique=True)
    safe_create_index('ix_favorites_user_job', 'favorites', ['user_id', 'job_id'], unique=True)
    safe_create_index('ix_portfolios_user_id', 'portfolios', ['user_id'], unique=True)
    safe_create_index('ix_smtp_configs_user_id', 'smtp_configs', ['user_id'], unique=True)


def downgrade() -> None:
    """Downgrade schema safely using idempotent helpers."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def safe_drop_index(index_name: str, table_name: str) -> None:
        if index_exists(inspector, table_name, index_name):
            print(f"[MIGRATION] Dropping index {index_name} on {table_name}")
            with op.batch_alter_table(table_name, schema=None) as batch_op:
                batch_op.drop_index(index_name)

    def safe_drop_column(table_name: str, column_name: str) -> None:
        if column_exists(inspector, table_name, column_name):
            print(f"[MIGRATION] Dropping column {table_name}.{column_name}")
            with op.batch_alter_table(table_name, schema=None) as batch_op:
                batch_op.drop_column(column_name)

    # 1. Drop unique indexes safely
    safe_drop_index('ix_smtp_configs_user_id', 'smtp_configs')
    safe_drop_index('ix_portfolios_user_id', 'portfolios')
    safe_drop_index('ix_favorites_user_job', 'favorites')
    safe_drop_index('ix_cv_profiles_user_id', 'cv_profiles')
    safe_drop_index('ix_cover_letters_user_id', 'cover_letters')
    safe_drop_index('ix_ai_scores_user_job', 'ai_scores')

    # 2. Drop non-unique indexes safely
    safe_drop_index('ix_history_user_id', 'history')
    safe_drop_index('ix_favorites_user_id', 'favorites')
    safe_drop_index('ix_email_queue_user_id', 'email_queue')
    safe_drop_index('ix_ai_scores_user_id', 'ai_scores')

    # 3. Drop user_id columns safely
    safe_drop_column('smtp_configs', 'user_id')
    safe_drop_column('portfolios', 'user_id')
    safe_drop_column('history', 'user_id')
    safe_drop_column('favorites', 'user_id')
    safe_drop_column('email_queue', 'user_id')
    safe_drop_column('cv_profiles', 'user_id')
    safe_drop_column('cover_letters', 'user_id')
    safe_drop_column('ai_scores', 'user_id')
