"""ingest_match_rejection

Rejecting one wrong pair (#88): Unmatch on a linked pending pair, or "Not this one" on a proposed
bank paper, records the pair here so automatic matching never proposes it again but stays free to
find another partner. This replaces ``ingest_paper.match_status = 'unlinked'``, which blocked all
automatic linking for both papers; existing ``unlinked`` rows are reset to NULL (the pair they
declined is no longer known, since unlinking cleared it).

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-10-21 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'c6d7e8f9a0b1'
down_revision: Union[str, None] = 'b5c6d7e8f9a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ingest_match_rejection',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('ingest_paper_id', sa.Integer(), sa.ForeignKey('ingest_paper.id', ondelete='CASCADE'), nullable=False),
        sa.Column(
            'rejected_ingest_paper_id', sa.Integer(), sa.ForeignKey('ingest_paper.id', ondelete='CASCADE'),
            nullable=True,
        ),
        sa.Column('rejected_paper_id', sa.Integer(), sa.ForeignKey('paper.id', ondelete='CASCADE'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            '(rejected_ingest_paper_id IS NULL) <> (rejected_paper_id IS NULL)',
            name='ck_ingest_match_rejection_one_target',
        ),
    )
    op.create_index('ix_ingest_match_rejection_ingest_paper_id', 'ingest_match_rejection', ['ingest_paper_id'])
    op.create_index(
        'ix_ingest_match_rejection_rejected_ingest_paper_id', 'ingest_match_rejection', ['rejected_ingest_paper_id']
    )
    op.execute("UPDATE ingest_paper SET match_status = NULL WHERE match_status = 'unlinked'")


def downgrade() -> None:
    op.drop_index('ix_ingest_match_rejection_rejected_ingest_paper_id', table_name='ingest_match_rejection')
    op.drop_index('ix_ingest_match_rejection_ingest_paper_id', table_name='ingest_match_rejection')
    op.drop_table('ingest_match_rejection')
