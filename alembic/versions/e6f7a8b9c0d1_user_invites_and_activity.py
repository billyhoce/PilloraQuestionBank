"""normalize user emails and add sign-in activity columns

Three changes to ``app_user``, all in service of admins pre-creating accounts so
premium access is live before the customer signs up:

* ``last_login_at`` — stamped on every successful sign-in (both the password path
  and the Google callback share ``_set_session_cookie``, so it is written once
  there). Null for an account that has never signed in, which includes every
  unclaimed invite.
* ``papers_generated`` — running count incremented by ``POST /api/generate/paper``.
  A counter rather than a log table; nothing needs per-generation history yet.
* **Emails are lower-cased.** Addresses were previously stored and matched
  verbatim while Google's OIDC ``email`` claim is canonical lower-case, so an
  admin inviting ``Billy@Gmail.com`` would get a *second*, unentitled row the
  moment that person signed in with Google. ``normalize_email`` in
  ``app/services/auth.py`` now folds case on every write and lookup; this
  backfills the rows written before it existed.

The backfill is written to fail loudly rather than silently merge: if two rows
differ only by case, the unique index on ``email`` rejects the update. That is
the right outcome — those are two real accounts with separate premium grants,
and which one survives is a judgement call, not something a migration should
make. Resolve them by hand, then re-run.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-08-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, None] = 'd5e6f7a8b9c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'app_user',
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        'app_user',
        sa.Column('papers_generated', sa.Integer(), nullable=False, server_default='0'),
    )
    op.execute(sa.text("UPDATE app_user SET email = lower(email) WHERE email <> lower(email)"))


def downgrade() -> None:
    # The lower-casing is not reversed: the original casing is not recorded, and
    # lower-case addresses work fine under the old code.
    op.drop_column('app_user', 'papers_generated')
    op.drop_column('app_user', 'last_login_at')
