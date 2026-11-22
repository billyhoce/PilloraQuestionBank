"""drop ingest_task.fingerprint

The pipeline no longer fingerprints finished tasks: a task reruns only when its artefacts are
missing or it is retried, so the stored hash has no reader.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-11-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('ingest_task', 'fingerprint')


def downgrade() -> None:
    op.add_column('ingest_task', sa.Column('fingerprint', sa.String(length=64), nullable=True))
