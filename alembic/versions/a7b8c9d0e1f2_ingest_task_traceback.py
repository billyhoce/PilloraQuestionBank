"""add ingest_task.traceback

The truncated traceback of the exception a failed stage raised, shown on the job detail page.

Revision ID: a7b8c9d0e1f2
Revises: 037109e3d67e
Create Date: 2026-10-13 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, None] = '037109e3d67e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ingest_task', sa.Column('traceback', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('ingest_task', 'traceback')
