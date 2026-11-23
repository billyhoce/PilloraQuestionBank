"""scored pending matching: cover school name, suggested partner, school aliases

``ingest_paper.cover_school_name`` keeps a cover's school that matched no school ("BPGHS") so two
pending papers can still be compared on it; ``ingest_paper.suggested_ingest_paper_id`` is the
pending question paper suggested for an answer-only paper on weaker evidence; ``school_alias``
holds names learned when an admin confirms such a paper with a school.

Revision ID: f3a4b5c6d7e8
Revises: e8f9a0b1c2d3
Create Date: 2026-10-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3a4b5c6d7e8'
down_revision: Union[str, None] = 'e8f9a0b1c2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ingest_paper', sa.Column('cover_school_name', sa.String(length=128), nullable=True))
    op.add_column('ingest_paper', sa.Column('suggested_ingest_paper_id', sa.Integer(), nullable=True))
    op.create_foreign_key(
        'fk_ingest_paper_suggested_ingest_paper_id', 'ingest_paper', 'ingest_paper',
        ['suggested_ingest_paper_id'], ['id'], ondelete='SET NULL',
    )
    op.create_table(
        'school_alias',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('alias', sa.String(length=128), nullable=False, unique=True),
        sa.Column('school_id', sa.Integer(), sa.ForeignKey('school.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('school_alias')
    op.drop_constraint('fk_ingest_paper_suggested_ingest_paper_id', 'ingest_paper', type_='foreignkey')
    op.drop_column('ingest_paper', 'suggested_ingest_paper_id')
    op.drop_column('ingest_paper', 'cover_school_name')
