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


def upgrade() -> None:
    """Upgrade schema safely with data-aware deduplication."""
    # 1. Step 1: Add user_id column to all tables without the UNIQUE indexes yet
    with op.batch_alter_table('ai_scores', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), server_default='0', nullable=False))
        batch_op.create_index(batch_op.f('ix_ai_scores_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('cover_letters', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), server_default='0', nullable=False))

    with op.batch_alter_table('cv_profiles', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), server_default='0', nullable=False))

    with op.batch_alter_table('email_queue', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), server_default='0', nullable=False))
        batch_op.create_index(batch_op.f('ix_email_queue_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('favorites', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), server_default='0', nullable=False))
        batch_op.create_index(batch_op.f('ix_favorites_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('history', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), server_default='0', nullable=False))
        batch_op.create_index(batch_op.f('ix_history_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('portfolios', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), server_default='0', nullable=False))

    with op.batch_alter_table('smtp_configs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), server_default='0', nullable=False))

    # 2. Step 2: Data-Aware De-duplication Scan & Deletion Report
    bind = op.get_bind()

    # Scan and report duplicates for favorites
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

    # 3. Step 3: Create the UNIQUE indexes safely now that constraints are satisfied
    with op.batch_alter_table('ai_scores', schema=None) as batch_op:
        batch_op.create_index('ix_ai_scores_user_job', ['user_id', 'job_id'], unique=True)

    with op.batch_alter_table('cover_letters', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_cover_letters_user_id'), ['user_id'], unique=True)

    with op.batch_alter_table('cv_profiles', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_cv_profiles_user_id'), ['user_id'], unique=True)

    with op.batch_alter_table('favorites', schema=None) as batch_op:
        batch_op.create_index('ix_favorites_user_job', ['user_id', 'job_id'], unique=True)

    with op.batch_alter_table('portfolios', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_portfolios_user_id'), ['user_id'], unique=True)

    with op.batch_alter_table('smtp_configs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_smtp_configs_user_id'), ['user_id'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('smtp_configs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_smtp_configs_user_id'))
        batch_op.drop_column('user_id')

    with op.batch_alter_table('portfolios', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_portfolios_user_id'))
        batch_op.drop_column('user_id')

    with op.batch_alter_table('history', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_history_user_id'))
        batch_op.drop_column('user_id')

    with op.batch_alter_table('favorites', schema=None) as batch_op:
        batch_op.drop_index('ix_favorites_user_job')
        batch_op.drop_index(batch_op.f('ix_favorites_user_id'))
        batch_op.drop_column('user_id')

    with op.batch_alter_table('email_queue', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_email_queue_user_id'))
        batch_op.drop_column('user_id')

    with op.batch_alter_table('cv_profiles', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_cv_profiles_user_id'))
        batch_op.drop_column('user_id')

    with op.batch_alter_table('cover_letters', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_cover_letters_user_id'))
        batch_op.drop_column('user_id')

    with op.batch_alter_table('ai_scores', schema=None) as batch_op:
        batch_op.drop_index('ix_ai_scores_user_job')
        batch_op.drop_index(batch_op.f('ix_ai_scores_user_id'))
        batch_op.drop_column('user_id')
