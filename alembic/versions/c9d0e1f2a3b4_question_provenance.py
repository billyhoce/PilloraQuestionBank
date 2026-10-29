"""question provenance

Nullable pointers from a confirmed question back to its place in the source PDF.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-10-13 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('question', sa.Column('section', sa.String(64), nullable=True))
    op.add_column('question', sa.Column('proposal_question_index', sa.Integer(), nullable=True))
    op.add_column('question_page', sa.Column('source_page', sa.Integer(), nullable=True))
    op.add_column('question_page', sa.Column('source_rect', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('question_page', 'source_rect')
    op.drop_column('question_page', 'source_page')
    op.drop_column('question', 'proposal_question_index')
    op.drop_column('question', 'section')
