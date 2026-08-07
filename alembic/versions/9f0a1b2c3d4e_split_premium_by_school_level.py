"""split premium access by school level

Premium stops being a role value and becomes a set of school levels a user holds,
so Primary and Secondary premium can be sold separately.

Existing ``role='premium'`` users bought unrestricted premium, so they are
granted *every* school level — over-granting is visible and revocable in User
Management, whereas silently downgrading a paying account is not.

Revision ID: 9f0a1b2c3d4e
Revises: a1b2c3d4e5f7
Create Date: 2026-08-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '9f0a1b2c3d4e'
down_revision: Union[str, None] = 'a1b2c3d4e5f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'user_premium_school_level',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('school_level_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['app_user.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['school_level_id'], ['school_level.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'school_level_id'),
    )

    # Grandfather existing premium users into every school level.
    op.execute(
        sa.text(
            "INSERT INTO user_premium_school_level (user_id, school_level_id) "
            "SELECT u.id, sl.id FROM app_user u CROSS JOIN school_level sl "
            "WHERE u.role = 'premium'"
        )
    )
    op.execute(sa.text("UPDATE app_user SET role = 'public' WHERE role = 'premium'"))

    # Postgres check constraints cannot be altered in place, so drop & recreate.
    op.drop_constraint('ck_user_role', 'app_user', type_='check')
    op.create_check_constraint('ck_user_role', 'app_user', "role IN ('admin', 'public')")


def downgrade() -> None:
    op.drop_constraint('ck_user_role', 'app_user', type_='check')
    op.create_check_constraint(
        'ck_user_role', 'app_user', "role IN ('admin', 'public', 'premium')"
    )

    # Any entitlement at all collapses back to the old blanket 'premium' tier.
    op.execute(
        sa.text(
            "UPDATE app_user SET role = 'premium' WHERE role = 'public' AND id IN "
            "(SELECT user_id FROM user_premium_school_level)"
        )
    )

    op.drop_table('user_premium_school_level')
