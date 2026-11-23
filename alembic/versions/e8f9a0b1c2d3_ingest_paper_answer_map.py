"""ingest_paper.answer_map

The answer mapping table (#92): an answer-only paper linked to a pending question paper keeps which
of its answers go onto which questions (``{answer label: question label | null}``). NULL means "by
question number", as before.

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
Create Date: 2026-10-21 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = 'e8f9a0b1c2d3'
down_revision: Union[str, None] = 'd7e8f9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ingest_paper', sa.Column('answer_map', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('ingest_paper', 'answer_map')
