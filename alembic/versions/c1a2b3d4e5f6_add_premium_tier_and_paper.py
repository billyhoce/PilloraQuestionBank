"""add premium user tier and paper.is_premium

Revision ID: c1a2b3d4e5f6
Revises: 7a435cb7ab82
Create Date: 2026-07-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, None] = '7a435cb7ab82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Widen the user role check constraint to allow the new 'premium' tier.
    # Postgres check constraints cannot be altered in place, so drop & recreate.
    op.drop_constraint('ck_user_role', 'app_user', type_='check')
    op.create_check_constraint(
        'ck_user_role', 'app_user', "role IN ('admin', 'public', 'premium')"
    )

    # Papers can be flagged premium; only premium/admin users may view their
    # images or generate with their questions. Existing papers default to free.
    op.add_column(
        'paper',
        sa.Column('is_premium', sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('paper', 'is_premium')

    op.drop_constraint('ck_user_role', 'app_user', type_='check')
    op.create_check_constraint(
        'ck_user_role', 'app_user', "role IN ('admin', 'public')"
    )
