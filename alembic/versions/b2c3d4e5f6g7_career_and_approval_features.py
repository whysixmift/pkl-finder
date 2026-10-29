"""career_and_approval_features

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-10-29 15:53:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def column_exists(inspector, table_name: str, col_name: str) -> bool:
    """Helper to check if a column exists in a table."""
    if table_name not in inspector.get_table_names():
        return False
    columns = [c['name'] for c in inspector.get_columns(table_name)]
    return col_name in columns


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. Add career intelligence fields to cv_profiles
    if not column_exists(inspector, 'cv_profiles', 'detected_roles'):
        op.add_column('cv_profiles', sa.Column('detected_roles', sa.Text(), nullable=True))
    if not column_exists(inspector, 'cv_profiles', 'detected_skills'):
        op.add_column('cv_profiles', sa.Column('detected_skills', sa.Text(), nullable=True))
    if not column_exists(inspector, 'cv_profiles', 'search_keywords'):
        op.add_column('cv_profiles', sa.Column('search_keywords', sa.Text(), nullable=True))
    if not column_exists(inspector, 'cv_profiles', 'candidate_summary'):
        op.add_column('cv_profiles', sa.Column('candidate_summary', sa.Text(), nullable=True))

    # 2. Add approval workflow fields to user_whitelist
    if not column_exists(inspector, 'user_whitelist', 'email'):
        op.add_column('user_whitelist', sa.Column('email', sa.String(255), nullable=True))
    if not column_exists(inspector, 'user_whitelist', 'status'):
        op.add_column('user_whitelist', sa.Column('status', sa.String(50), nullable=False, server_default='approved'))
    if not column_exists(inspector, 'user_whitelist', 'source'):
        op.add_column('user_whitelist', sa.Column('source', sa.String(50), nullable=False, server_default='telegram'))


def downgrade() -> None:
    # SQLite batch mode downgrade if ever rolled back
    with op.batch_alter_table('cv_profiles') as batch_op:
        batch_op.drop_column('candidate_summary')
        batch_op.drop_column('search_keywords')
        batch_op.drop_column('detected_skills')
        batch_op.drop_column('detected_roles')

    with op.batch_alter_table('user_whitelist') as batch_op:
        batch_op.drop_column('source')
        batch_op.drop_column('status')
        batch_op.drop_column('email')
