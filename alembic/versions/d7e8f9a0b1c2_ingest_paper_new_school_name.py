"""ingest_paper.new_school_name

A school the admin types during review that is not in the reference list (#87) is held on the
pending paper as ``new_school_name`` (with no ``school_id``); the school row is only created when a
question paper carrying it is confirmed, so a skipped job or a typo leaves nothing behind.

Revision ID: d7e8f9a0b1c2
Revises: c6d7e8f9a0b1
Create Date: 2026-10-21 15:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'd7e8f9a0b1c2'
down_revision: Union[str, None] = 'c6d7e8f9a0b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ingest_paper', sa.Column('new_school_name', sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column('ingest_paper', 'new_school_name')
