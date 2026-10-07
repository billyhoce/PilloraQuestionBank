"""add ingest_job, ingest_task, worker_heartbeat and paper.source_job_id

The data model for automatic import: a job per source PDF, its task graph, and
the worker's heartbeat row. ``paper.source_job_id`` records which job produced a
paper (NULL for manual imports; SET NULL when the job is deleted).

Job-level tasks have ``section IS NULL``, which a plain UNIQUE (job_id, section,
stage) does not constrain in Postgres, so a partial unique index covers them.
It is portable to every Postgres version (``NULLS NOT DISTINCT`` needs PG15).

Revision ID: e5f6a7b8c9d0
Revises: 9f0a1b2c3d4e
Create Date: 2026-10-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, None] = '9f0a1b2c3d4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JOB_STATUSES = ('queued', 'running', 'review_ready', 'failed', 'confirmed', 'cancelled', 'expired')
TASK_STATUSES = ('pending', 'ready', 'running', 'done', 'skipped', 'failed', 'blocked')


def upgrade() -> None:
    # create_type=False: the enums are created explicitly (and dropped in
    # downgrade) rather than implicitly as a side effect of create_table.
    job_status = postgresql.ENUM(*JOB_STATUSES, name='ingest_job_status', create_type=False)
    task_status = postgresql.ENUM(*TASK_STATUSES, name='ingest_task_status', create_type=False)
    job_status.create(op.get_bind(), checkfirst=True)
    task_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'ingest_job',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(length=512), nullable=False),
        sa.Column('source_key', sa.String(length=512), nullable=False),
        sa.Column('sha256', sa.String(length=64), nullable=False),
        sa.Column('page_count', sa.Integer(), nullable=False),
        sa.Column('status', job_status, server_default='queued', nullable=False),
        sa.Column('proposal', postgresql.JSONB(), nullable=True),
        sa.Column('proposal_edited', postgresql.JSONB(), nullable=True),
        sa.Column('report', postgresql.JSONB(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('confirmed_paper_ids', postgresql.ARRAY(sa.Integer()), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'ingest_task',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Uuid(), nullable=False),
        sa.Column('section', sa.String(length=8), nullable=True),
        sa.Column('stage', sa.String(length=16), nullable=False),
        sa.Column('status', task_status, server_default='pending', nullable=False),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('warnings', postgresql.JSONB(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column('needs_review', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('fingerprint', sa.String(length=64), nullable=True),
        sa.Column('lease_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['job_id'], ['ingest_job.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('job_id', 'section', 'stage', name='uq_ingest_task_job_section_stage'),
    )
    op.create_index(
        'uq_ingest_task_job_stage_jobwide', 'ingest_task', ['job_id', 'stage'],
        unique=True, postgresql_where=sa.text('section IS NULL'),
    )

    op.create_table(
        'worker_heartbeat',
        sa.Column('id', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('version', sa.String(length=64), nullable=True),
        sa.Column('current_job_id', sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(['current_job_id'], ['ingest_job.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('id = 1', name='ck_worker_heartbeat_singleton'),
    )

    op.add_column('paper', sa.Column('source_job_id', sa.Uuid(), nullable=True))
    op.create_foreign_key(
        'fk_paper_source_job', 'paper', 'ingest_job', ['source_job_id'], ['id'], ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_paper_source_job', 'paper', type_='foreignkey')
    op.drop_column('paper', 'source_job_id')
    op.drop_table('worker_heartbeat')
    op.drop_index('uq_ingest_task_job_stage_jobwide', table_name='ingest_task')
    op.drop_table('ingest_task')
    op.drop_table('ingest_job')
    postgresql.ENUM(name='ingest_task_status').drop(op.get_bind(), checkfirst=True)
    postgresql.ENUM(name='ingest_job_status').drop(op.get_bind(), checkfirst=True)
