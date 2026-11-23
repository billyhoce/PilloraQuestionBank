"""ingest_paper match proposal

Automatic matching (#83): an answer-only ``ingest_paper`` is matched to a confirmed ``paper`` with
the same seven-field key. ``match_status`` is NULL (nothing to do), ``proposed`` (exactly one
paper, in ``proposed_paper_id``) or ``manual`` (several or only partial matches); ``match_note``
says why, in a few words.

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-10-14 15:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'b5c6d7e8f9a0'
down_revision: Union[str, None] = 'a4b5c6d7e8f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('ingest_paper', sa.Column('match_status', sa.String(length=16), nullable=True))
    op.add_column('ingest_paper', sa.Column('proposed_paper_id', sa.Integer(), nullable=True))
    op.add_column('ingest_paper', sa.Column('match_note', sa.String(length=200), nullable=True))
    op.create_foreign_key(
        'fk_ingest_paper_proposed_paper_id', 'ingest_paper', 'paper', ['proposed_paper_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_ingest_paper_proposed_paper_id', 'ingest_paper', type_='foreignkey')
    op.drop_column('ingest_paper', 'match_note')
    op.drop_column('ingest_paper', 'proposed_paper_id')
    op.drop_column('ingest_paper', 'match_status')
