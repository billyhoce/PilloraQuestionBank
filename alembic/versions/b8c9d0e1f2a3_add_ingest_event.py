"""add ingest_event

Append-only audit trail of an ingest job's transitions.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-10-13 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ingest_event',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('job_id', sa.Uuid(), sa.ForeignKey('ingest_job.id', ondelete='CASCADE'), nullable=False),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('ingest_task.id', ondelete='SET NULL'), nullable=True),
        sa.Column('at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('actor_user_id', sa.Integer(), sa.ForeignKey('app_user.id', ondelete='SET NULL'), nullable=True),
        sa.Column('data', postgresql.JSONB(), server_default=sa.text("'{}'"), nullable=False),
    )
    op.create_index('ix_ingest_event_job_id_id', 'ingest_event', ['job_id', 'id'])


def downgrade() -> None:
    op.drop_index('ix_ingest_event_job_id_id', table_name='ingest_event')
    op.drop_table('ingest_event')
