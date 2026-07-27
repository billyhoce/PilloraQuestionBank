"""add user first/last name and Google OAuth linkage

Adds ``first_name`` / ``last_name`` to ``app_user`` (backfilled to '' for
existing rows) and ``google_sub``, the stable Google subject id set once an
account signs in with Google. ``password_hash`` becomes nullable because
accounts created through Google never have one.

Revision ID: b7c8d9e0f1a2
Revises: f1e2d3c4b5a6
Create Date: 2026-07-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, None] = 'f1e2d3c4b5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Names are required for new manual registrations, but existing rows (and
    # Google accounts that don't report a given/family name) fall back to ''.
    # The UI shows the email address when both are blank.
    op.add_column('app_user', sa.Column('first_name', sa.String(length=100), server_default='', nullable=False))
    op.add_column('app_user', sa.Column('last_name', sa.String(length=100), server_default='', nullable=False))

    # Google's 'sub' claim — unique per Google account, and stable even if the
    # user changes the email address on it.
    op.add_column('app_user', sa.Column('google_sub', sa.String(length=255), nullable=True))
    op.create_unique_constraint('uq_app_user_google_sub', 'app_user', ['google_sub'])

    # Google-only accounts have no password to hash.
    op.alter_column('app_user', 'password_hash', existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    # The old schema cannot represent a passwordless account. Blanking the hash
    # keeps the NOT NULL restore possible; those users can no longer log in
    # (verify_password rejects an empty hash) until a password is set.
    op.execute("UPDATE app_user SET password_hash = '' WHERE password_hash IS NULL")
    op.alter_column('app_user', 'password_hash', existing_type=sa.String(length=255), nullable=False)

    op.drop_constraint('uq_app_user_google_sub', 'app_user', type_='unique')
    op.drop_column('app_user', 'google_sub')
    op.drop_column('app_user', 'last_name')
    op.drop_column('app_user', 'first_name')
