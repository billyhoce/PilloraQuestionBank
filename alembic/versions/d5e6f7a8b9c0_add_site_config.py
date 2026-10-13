"""add site config (About page content + image-protection toggle)

Two site-wide settings that are neither reference data nor generation presets:

* ``about_content`` — the rich-text HTML shown on the public ``/about`` page,
  edited in place by an admin.
* ``protect_images`` — a client-side deterrent against casual copying of
  question images (right-click / drag / long-press). Off by default.

A **separate** singleton table rather than extra columns on
``generation_config``: that table is scoped to paper-generation presets and its
endpoint requires authentication, whereas both settings here must reach
signed-out visitors — ``/about`` is public and so is the Browse page that reads
the image flag.

Revision ID: d5e6f7a8b9c0
Revises: 9f0a1b2c3d4e
Create Date: 2026-08-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, None] = '9f0a1b2c3d4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Inlined so the migration stays self-contained; mirrors
# DEFAULT_ABOUT_CONTENT in app/services/site_config.py.
_DEFAULT_ABOUT_CONTENT = (
    "<h2>About Pillora</h2>"
    "<p>Pillora Learning maintains this question bank so students and tutors can build "
    "topical practice from real secondary school exam papers.</p>"
    "<p>Browse questions by subject, level and topic, then generate a custom paper as a "
    "downloadable PDF.</p>"
    "<p>Admins can edit this page from the About tab.</p>"
)


def upgrade() -> None:
    site_config = op.create_table(
        'site_config',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('about_content', sa.Text(), nullable=False),
        sa.Column(
            'protect_images',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.CheckConstraint('id = 1', name='ck_site_config_singleton'),
    )

    op.bulk_insert(
        site_config,
        [{'id': 1, 'about_content': _DEFAULT_ABOUT_CONTENT, 'protect_images': False}],
    )


def downgrade() -> None:
    op.drop_table('site_config')
