"""add generation config and cover titles

Revision ID: d4e5f6a7b8c9
Revises: c1a2b3d4e5f6
Create Date: 2026-07-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c1a2b3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Seed values inlined so the migration stays self-contained. They mirror
# app/services/generation_config.py, preserving the pre-config cover defaults.
_DEFAULT_COVER_BODY = (
    "<p>Dear students,</p>"
    "<p>Did you know that research shows students learn best when they focus on topical practice "
    "first before moving on to full-paper practice? Many students jump straight into full exam "
    "papers as practice without realising that they are losing marks in the SAME few areas every "
    "time.</p>"
    "<p>That is why I have compiled and vetted these topical worksheets, making sure they contain "
    "only exam-style questions.</p>"
    "<p>I recommend identifying your weaker topics and practising them using these topical "
    "worksheets before moving to timed full papers. If you need help figuring out your weaker "
    "areas, or need to clarify anything about any specific topic, come book a consultation "
    "session with me through my website, without having to sign up for any tuition package.</p>"
    "<p>For more resources such as Math and Science notes, topical worksheets, WA1–3/EOY papers, "
    'and textbook/workbook answers, please visit '
    '<a href="https://www.pillora.com.sg">www.pillora.com.sg</a>.</p>'
    "<p>You can do it! All the best :)</p>"
    "<p>Teacher Jia Xin<br>Founder of Pillora Learning</p>"
)


def upgrade() -> None:
    # Admin-curated cover titles; non-admin users must pick from this list.
    cover_title = op.create_table(
        'cover_title',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=255), nullable=False, unique=True),
    )

    # Singleton row of generation presets applied to non-admin generations.
    generation_config = op.create_table(
        'generation_config',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('subtitle1_placeholder', sa.String(length=255), nullable=False),
        sa.Column('subtitle2_placeholder', sa.String(length=255), nullable=False),
        sa.Column('cover_body', sa.Text(), nullable=False),
        sa.Column('header_text', sa.Text(), nullable=False),
        sa.Column('footer_text', sa.String(length=255), nullable=False),
        sa.CheckConstraint('id = 1', name='ck_generation_config_singleton'),
    )

    op.bulk_insert(cover_title, [{'id': 1, 'name': 'Topical Worksheets'}])
    op.bulk_insert(
        generation_config,
        [{
            'id': 1,
            'subtitle1_placeholder': 'e.g. Secondary 3 Mathematics',
            'subtitle2_placeholder': 'e.g. 2024 Prelim',
            'cover_body': _DEFAULT_COVER_BODY,
            'header_text': '',
            'footer_text': '',
        }],
    )


def downgrade() -> None:
    op.drop_table('generation_config')
    op.drop_table('cover_title')
