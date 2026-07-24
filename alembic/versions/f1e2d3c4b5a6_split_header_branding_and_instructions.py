"""split page-header branding from additional instructions

Renames ``generation_config.header_text`` (which drove the below-rule exam
instructions) to ``additional_instructions``, and adds a fresh ``header_text``
column for the branding drawn right-aligned on the top rule of every page. The
new column is backfilled with the two-line Pillora tagline for the singleton
row, then its server default is dropped to match the ORM (which supplies the
value on insert).

Revision ID: f1e2d3c4b5a6
Revises: d4e5f6a7b8c9
Create Date: 2026-07-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1e2d3c4b5a6'
down_revision: Union[str, None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Inlined so the migration stays self-contained (mirrors
# app/services/generation_config.py DEFAULT_HEADER_TEXT).
_DEFAULT_HEADER_TEXT = (
    "Visit www.pillora.com.sg for more learning resources.\n"
    "Join @PilloraSecondary on Telegram to learn together!"
)


def upgrade() -> None:
    # Existing header_text held the below-rule instructions — keep that data.
    op.alter_column('generation_config', 'header_text', new_column_name='additional_instructions')
    # New branding header, backfilled for the singleton row via server_default,
    # then the default is dropped so the schema matches the ORM.
    op.add_column(
        'generation_config',
        sa.Column('header_text', sa.Text(), nullable=False, server_default=_DEFAULT_HEADER_TEXT),
    )
    op.alter_column('generation_config', 'header_text', server_default=None)


def downgrade() -> None:
    op.drop_column('generation_config', 'header_text')
    op.alter_column('generation_config', 'additional_instructions', new_column_name='header_text')
