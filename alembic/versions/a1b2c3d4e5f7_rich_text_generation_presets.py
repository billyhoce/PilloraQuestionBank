"""rich-text header, instructions and footer presets

The page header, additional instructions and footer became rich text (the same
editor and sanitizer as the cover body — app/pdf/rich_text.py), so:

* ``footer_text`` grows from ``String(255)`` to ``Text``, since HTML markup is
  far longer than the label it wraps.
* the three stored values are converted from plain text to paragraph HTML, so
  the admin editor round-trips them faithfully (line breaks stay line breaks and
  web addresses become real links). The renderer still accepts plain text, so
  this is about what the editor shows, not what the PDF draws.

Revision ID: a1b2c3d4e5f7
Revises: c9d8e7f6a5b4
Create Date: 2026-08-07 00:00:00.000000

"""
import re
from html import escape
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f7'
down_revision: Union[str, None] = 'c9d8e7f6a5b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_RICH_TEXT_COLUMNS = ('header_text', 'additional_instructions', 'footer_text')

# Inlined so the migration stays self-contained (mirrors _URL_TOKEN in
# app/pdf/rich_text.py, which auto-links these addresses at render time).
_URL_TOKEN = re.compile(
    r"https?://\S+|www\.\S+|[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.[a-z]{2,}(?:/\S*)?",
    re.I,
)


def _linkify(line: str) -> str:
    """Escape a plain-text line, wrapping web addresses in anchors."""
    out, pos = [], 0
    for m in _URL_TOKEN.finditer(line):
        token = m.group().rstrip('.,;:!?)')
        href = token if token.lower().startswith(('http://', 'https://')) else f'https://{token}'
        out.append(escape(line[pos:m.start()]))
        out.append(f'<a href="{escape(href, quote=True)}">{escape(token)}</a>')
        out.append(escape(m.group()[len(token):]))
        pos = m.end()
    out.append(escape(line[pos:]))
    return ''.join(out)


def _to_html(value: str) -> str:
    """Plain text -> paragraph HTML. Blank lines split paragraphs; single
    newlines become <br>. Values that already contain markup are left alone."""
    if not value or '<' in value:
        return value
    paragraphs, block = [], []
    for line in value.split('\n'):
        if line.strip():
            block.append(_linkify(line.strip()))
        elif block:
            paragraphs.append('<br>'.join(block))
            block = []
    if block:
        paragraphs.append('<br>'.join(block))
    return ''.join(f'<p>{p}</p>' for p in paragraphs)


def upgrade() -> None:
    op.alter_column(
        'generation_config',
        'footer_text',
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=False,
    )
    conn = op.get_bind()
    row = conn.execute(
        sa.text(f"SELECT {', '.join(_RICH_TEXT_COLUMNS)} FROM generation_config WHERE id = 1")
    ).first()
    if row is None:
        return
    converted = {col: _to_html(value or '') for col, value in zip(_RICH_TEXT_COLUMNS, row)}
    assignments = ', '.join(f'{col} = :{col}' for col in _RICH_TEXT_COLUMNS)
    conn.execute(
        sa.text(f'UPDATE generation_config SET {assignments} WHERE id = 1'), converted
    )


def downgrade() -> None:
    # The HTML is left in place: it is valid input for the columns either way,
    # and stripping tags would lose the links the admin added since. Narrowing
    # footer_text back to 255 chars therefore fails loudly if the stored markup
    # has outgrown it — better than silently truncating an admin's footer.
    op.alter_column(
        'generation_config',
        'footer_text',
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
