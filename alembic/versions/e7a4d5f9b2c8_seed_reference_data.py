"""seed reference data

Revision ID: e7a4d5f9b2c8
Revises: eb12b366e454
Create Date: 2026-05-08 02:31:10.628945

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7a4d5f9b2c8"
down_revision: Union[str, None] = "eb12b366e454"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Lightweight table definitions for op.bulk_insert. We deliberately do NOT
# import the ORM here: migrations must be insulated from future model changes,
# so we redeclare only the columns this migration touches.

school_level_table = sa.table(
    "school_level",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
)

subject_table = sa.table(
    "subject",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
)

stream_table = sa.table(
    "stream",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("school_level_id", sa.Integer),
)

level_table = sa.table(
    "level",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("sort_order", sa.Integer),
    sa.column("school_level_id", sa.Integer),
)

exam_type_table = sa.table(
    "exam_type",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
)

user_table = sa.table(
    "app_user",
    sa.column("id", sa.Integer),
    sa.column("email", sa.String),
    sa.column("password_hash", sa.String),
    sa.column("role", sa.String),
)


SCHOOL_LEVELS: list[dict] = [
    {"name": "Primary"},
    {"name": "Secondary"},
]

SUBJECTS: list[dict] = [
    {"name": "Math"},
    {"name": "Science"},
]

# The "school_level" key on each stream/level is resolved to school_level_id
# in upgrade() after SCHOOL_LEVELS is inserted.
STREAMS: list[dict] = [
    {"name": "Foundation", "school_level": "Primary"},
    {"name": "Standard", "school_level": "Primary"},
    {"name": "G1", "school_level": "Secondary"},
    {"name": "G2", "school_level": "Secondary"},
    {"name": "G3", "school_level": "Secondary"},
]

LEVELS: list[dict] = [
    {"name": "1", "sort_order": 1, "school_level": "Primary"},
    {"name": "2", "sort_order": 2, "school_level": "Primary"},
    {"name": "3", "sort_order": 3, "school_level": "Primary"},
    {"name": "4", "sort_order": 4, "school_level": "Primary"},
    {"name": "5", "sort_order": 5, "school_level": "Primary"},
    {"name": "6", "sort_order": 6, "school_level": "Primary"},
    {"name": "1", "sort_order": 7, "school_level": "Secondary"},
    {"name": "2", "sort_order": 8, "school_level": "Secondary"},
    {"name": "3", "sort_order": 9, "school_level": "Secondary"},
    {"name": "4", "sort_order": 10, "school_level": "Secondary"},
]

EXAM_TYPES: list[dict] = [
    {"name": "WA1"},
    {"name": "WA2"},
    {"name": "WA3"},
    {"name": "End-of-Year"},
    {"name": "Prelim"},
    {"name": "PSLE"},
    {"name": "O-Level"},
]

# Initial admin user
USERS: list[dict] = [
    {
        "email": "admin@pillora.com",
        "password_hash": "$2b$12$xonr9H5ielxtIe3B1LKY6euSnfrUHTIkgFFz.bEZLUvM2kC6AOvgu",
        "role": "admin",
    },
]


def upgrade() -> None:
    bind = op.get_bind()

    if SCHOOL_LEVELS:
        op.bulk_insert(school_level_table, SCHOOL_LEVELS)

    school_level_ids = {
        row.name: row.id
        for row in bind.execute(sa.text("SELECT id, name FROM school_level"))
    }

    if SUBJECTS:
        op.bulk_insert(subject_table, SUBJECTS)
    if STREAMS:
        op.bulk_insert(
            stream_table,
            [
                {
                    "name": s["name"],
                    "school_level_id": school_level_ids[s["school_level"]],
                }
                for s in STREAMS
            ],
        )
    if LEVELS:
        op.bulk_insert(
            level_table,
            [
                {
                    "name": l["name"],
                    "sort_order": l["sort_order"],
                    "school_level_id": school_level_ids[l["school_level"]],
                }
                for l in LEVELS
            ],
        )
    if EXAM_TYPES:
        op.bulk_insert(exam_type_table, EXAM_TYPES)
    if USERS:
        op.bulk_insert(user_table, USERS)


def downgrade() -> None:
    bind = op.get_bind()

    if USERS:
        emails = [u["email"] for u in USERS]
        bind.execute(
            sa.text("DELETE FROM app_user WHERE email = ANY(:emails)"),
            {"emails": emails},
        )
    if EXAM_TYPES:
        names = [e["name"] for e in EXAM_TYPES]
        bind.execute(
            sa.text("DELETE FROM exam_type WHERE name = ANY(:names)"),
            {"names": names},
        )
    if LEVELS:
        names = [l["name"] for l in LEVELS]
        bind.execute(
            sa.text("DELETE FROM level WHERE name = ANY(:names)"),
            {"names": names},
        )
    if STREAMS:
        names = [s["name"] for s in STREAMS]
        bind.execute(
            sa.text("DELETE FROM stream WHERE name = ANY(:names)"),
            {"names": names},
        )
    if SUBJECTS:
        names = [s["name"] for s in SUBJECTS]
        bind.execute(
            sa.text("DELETE FROM subject WHERE name = ANY(:names)"),
            {"names": names},
        )
    if SCHOOL_LEVELS:
        names = [sl["name"] for sl in SCHOOL_LEVELS]
        bind.execute(
            sa.text("DELETE FROM school_level WHERE name = ANY(:names)"),
            {"names": names},
        )
