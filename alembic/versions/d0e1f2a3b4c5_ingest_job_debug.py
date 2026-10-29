"""ingest_job.debug

The debug bundle (segments.json, ingest.json) copied onto the job at report time, so the worker's
scratch folder and the job's S3 prefix can be deleted when the job settles.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-10-13 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'd0e1f2a3b4c5'
down_revision: Union[str, None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ingest_job', sa.Column('debug', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('ingest_job', 'debug')
