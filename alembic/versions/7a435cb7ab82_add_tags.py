"""add tags

Revision ID: 7a435cb7ab82
Revises: eb12b366e454
Create Date: 2026-07-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '7a435cb7ab82'
down_revision: Union[str, None] = 'eb12b366e454'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tag',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    # question_tag: 0+ tags per question. Deleting a tag cascades, stripping it
    # from every question that carried it (tags are lightweight labels).
    op.create_table(
        'question_tag',
        sa.Column('question_id', sa.Integer(), nullable=False),
        sa.Column('tag_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['question_id'], ['question.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['tag.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('question_id', 'tag_id'),
    )


def downgrade() -> None:
    op.drop_table('question_tag')
    op.drop_table('tag')
