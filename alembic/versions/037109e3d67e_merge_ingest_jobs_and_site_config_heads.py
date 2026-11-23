"""merge ingest jobs and site config heads

Revision ID: 037109e3d67e
Revises: a2b3c4d5e6f7, e6f7a8b9c0d1
Create Date: 2026-10-13 10:46:16.496076

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '037109e3d67e'
down_revision: Union[str, None] = ('a2b3c4d5e6f7', 'e6f7a8b9c0d1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
