"""ingest_job_status gains awaiting_upload

A job exists before its PDF does when the browser uploads straight to S3.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-10-14 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, None] = 'f2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A new enum value cannot be used in the transaction that adds it.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE ingest_job_status ADD VALUE IF NOT EXISTS 'awaiting_upload' BEFORE 'queued'")


def downgrade() -> None:
    # Postgres cannot drop an enum value; unused values are harmless. Cancel such jobs first.
    op.execute("UPDATE ingest_job SET status = 'cancelled' WHERE status = 'awaiting_upload'")
