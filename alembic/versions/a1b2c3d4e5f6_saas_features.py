"""saas_features

Revision ID: a1b2c3d4e5f6
Revises: 9c5f9e5e6df5
Create Date: 2026-10-28 17:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '9c5f9e5e6df5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def table_exists(inspector, table_name: str) -> bool:
    """Helper to check if a table exists."""
    return table_name in inspector.get_table_names()


def column_exists(inspector, table_name: str, col_name: str) -> bool:
    """Helper to check if a column exists in a table."""
    if not table_exists(inspector, table_name):
        return False
    columns = [c['name'] for c in inspector.get_columns(table_name)]
    return col_name in columns


def index_exists(inspector, table_name: str, index_name: str) -> bool:
    """Helper to check if an index exists in a table."""
    if not table_exists(inspector, table_name):
        return False
    indexes = [i['name'] for i in inspector.get_indexes(table_name)]
    return index_name in indexes


def upgrade() -> None:
    """Upgrade schema safely with idempotent helpers."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. Add file_path to cv_profiles if missing
    if table_exists(inspector, 'cv_profiles') and not column_exists(inspector, 'cv_profiles', 'file_path'):
        print("[MIGRATION] Adding column cv_profiles.file_path")
        with op.batch_alter_table('cv_profiles', schema=None) as batch_op:
            batch_op.add_column(sa.Column('file_path', sa.String(500), nullable=True))

    # 2. Create user_whitelist table if missing
    if not table_exists(inspector, 'user_whitelist'):
        print("[MIGRATION] Creating table user_whitelist")
        op.create_table(
            'user_whitelist',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column('telegram_id', sa.Integer(), nullable=True),
            sa.Column('username', sa.String(255), nullable=True),
            sa.Column('notes', sa.String(255), nullable=True),
            sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        with op.batch_alter_table('user_whitelist', schema=None) as batch_op:
            batch_op.create_index('ix_user_whitelist_telegram_id', ['telegram_id'], unique=True)
            batch_op.create_index('ix_user_whitelist_username', ['username'], unique=True)

    # 3. Create user_google_auth table if missing
    if not table_exists(inspector, 'user_google_auth'):
        print("[MIGRATION] Creating table user_google_auth")
        op.create_table(
            'user_google_auth',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('email', sa.String(255), nullable=False),
            sa.Column('access_token_encrypted', sa.Text(), nullable=False),
            sa.Column('refresh_token_encrypted', sa.Text(), nullable=True),
            sa.Column('token_expiry', sa.DateTime(), nullable=True),
            sa.Column('scopes', sa.Text(), nullable=True),
            sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
        )
        with op.batch_alter_table('user_google_auth', schema=None) as batch_op:
            batch_op.create_index('ix_user_google_auth_user_id', ['user_id'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if table_exists(inspector, 'user_google_auth'):
        op.drop_table('user_google_auth')

    if table_exists(inspector, 'user_whitelist'):
        op.drop_table('user_whitelist')

    if table_exists(inspector, 'cv_profiles') and column_exists(inspector, 'cv_profiles', 'file_path'):
        with op.batch_alter_table('cv_profiles', schema=None) as batch_op:
            batch_op.drop_column('file_path')
