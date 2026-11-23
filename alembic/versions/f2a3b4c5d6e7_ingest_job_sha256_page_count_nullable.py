"""ingest_job sha256 and page_count nullable

The upload no longer reads the PDF; the worker's ``register`` task fills both in.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-10-14 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f2a3b4c5d6e7'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('ingest_job', 'sha256', existing_type=sa.String(64), nullable=True)
    op.alter_column('ingest_job', 'page_count', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE ingest_job SET sha256 = repeat('0', 64) WHERE sha256 IS NULL")
    op.execute("UPDATE ingest_job SET page_count = 0 WHERE page_count IS NULL")
    op.alter_column('ingest_job', 'page_count', existing_type=sa.Integer(), nullable=False)
    op.alter_column('ingest_job', 'sha256', existing_type=sa.String(64), nullable=False)
