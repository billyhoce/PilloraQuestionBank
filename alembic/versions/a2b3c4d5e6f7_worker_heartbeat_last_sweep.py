"""add worker_heartbeat.last_sweep_at

Persists when the worker last ran its daily expiry sweep, so the sweep runs at most once a day
across restarts (and two workers cannot both claim it).

Revision ID: a2b3c4d5e6f7
Revises: e5f6a7b8c9d0
Create Date: 2026-10-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('worker_heartbeat', sa.Column('last_sweep_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('worker_heartbeat', 'last_sweep_at')
