"""ingest_event.job_id nullable

Reconciler findings about things that have no job row (a missing job's S3 prefix, an orphan
``papers/`` key, a stale ``tmp/`` object) are recorded as events without a job.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-10-13 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, None] = 'd0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('ingest_event', 'job_id', existing_type=postgresql.UUID(as_uuid=True), nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM ingest_event WHERE job_id IS NULL")
    op.alter_column('ingest_event', 'job_id', existing_type=postgresql.UUID(as_uuid=True), nullable=False)
