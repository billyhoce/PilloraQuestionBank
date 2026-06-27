"""initial schema

Revision ID: eb12b366e454
Revises:
Create Date: 2026-05-08 02:30:10.628945

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'eb12b366e454'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

school_level_table = sa.table(
    "school_level",
    sa.column("name", sa.String),
)

subject_table = sa.table(
    "subject",
    sa.column("name", sa.String),
)

stream_table = sa.table(
    "stream",
    sa.column("name", sa.String),
    sa.column("school_level_id", sa.Integer),
)

level_table = sa.table(
    "level",
    sa.column("name", sa.String),
    sa.column("sort_order", sa.Integer),
    sa.column("school_level_id", sa.Integer),
)

exam_type_table = sa.table(
    "exam_type",
    sa.column("name", sa.String),
)

user_table = sa.table(
    "app_user",
    sa.column("email", sa.String),
    sa.column("password_hash", sa.String),
    sa.column("role", sa.String),
)

SCHOOL_LEVELS = [
    {"name": "Primary"},
    {"name": "Secondary"},
]

SUBJECTS = [
    {"name": "E Math"},
    {"name": "A Math"},
    {"name": "Science"},
]

STREAMS = [
    {"name": "Foundation", "school_level": "Primary"},
    {"name": "Standard",   "school_level": "Primary"},
    {"name": "G1",         "school_level": "Secondary"},
    {"name": "G2",         "school_level": "Secondary"},
    {"name": "G3",         "school_level": "Secondary"},
]

LEVELS = [
    {"name": "1", "sort_order": 1,  "school_level": "Primary"},
    {"name": "2", "sort_order": 2,  "school_level": "Primary"},
    {"name": "3", "sort_order": 3,  "school_level": "Primary"},
    {"name": "4", "sort_order": 4,  "school_level": "Primary"},
    {"name": "5", "sort_order": 5,  "school_level": "Primary"},
    {"name": "6", "sort_order": 6,  "school_level": "Primary"},
    {"name": "1", "sort_order": 7,  "school_level": "Secondary"},
    {"name": "2", "sort_order": 8,  "school_level": "Secondary"},
    {"name": "3", "sort_order": 9,  "school_level": "Secondary"},
    {"name": "4", "sort_order": 10, "school_level": "Secondary"},
]

EXAM_TYPES = [
    {"name": "WA1"},
    {"name": "WA2"},
    {"name": "WA3"},
    {"name": "End-of-Year"},
    {"name": "Prelim"},
    {"name": "PSLE"},
    {"name": "O-Level"},
]

ADMIN_USER = {
    "email": "admin@pillora.com",
    "password_hash": "$2b$12$xonr9H5ielxtIe3B1LKY6euSnfrUHTIkgFFz.bEZLUvM2kC6AOvgu",
    "role": "admin",
}


def upgrade() -> None:
    op.create_table('app_user',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=16), server_default='public', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role IN ('admin', 'public')", name='ck_user_role'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('exam_type',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=32), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('school',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=128), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('school_level',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=32), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('subject',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('level',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=32), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('school_level_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['school_level_id'], ['school_level.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name', 'school_level_id')
    )
    op.create_table('stream',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=32), nullable=False),
    sa.Column('school_level_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['school_level_id'], ['school_level.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('name')
    )
    op.create_table('paper',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('subject_id', sa.Integer(), nullable=False),
    sa.Column('stream_id', sa.Integer(), nullable=False),
    sa.Column('level_id', sa.Integer(), nullable=False),
    sa.Column('school_id', sa.Integer(), nullable=False),
    sa.Column('exam_type_id', sa.Integer(), nullable=False),
    sa.Column('year', sa.Integer(), nullable=False),
    sa.Column('paper_number', sa.String(length=8), nullable=False),
    sa.Column('created_by', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['app_user.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['exam_type_id'], ['exam_type.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['level_id'], ['level.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['school_id'], ['school.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['stream_id'], ['stream.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['subject_id'], ['subject.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('topic',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('subject_id', sa.Integer(), nullable=False),
    sa.Column('stream_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=512), nullable=False),
    sa.Column('topic_number', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['stream_id'], ['stream.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['subject_id'], ['subject.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('subject_id', 'stream_id', 'name', name='uq_topic_subject_stream_name'),
    sa.UniqueConstraint('subject_id', 'stream_id', 'topic_number', name='uq_topic_subject_stream_number'),
    )
    op.create_table('question',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('paper_id', sa.Integer(), nullable=False),
    sa.Column('question_number', sa.Integer(), nullable=False),
    sa.Column('marks', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['paper_id'], ['paper.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('subtopic',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('topic_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=512), nullable=False),
    sa.ForeignKeyConstraint(['topic_id'], ['topic.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('topic_id', 'name', name='uq_subtopic_topic_name')
    )
    op.create_table('question_page',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('question_id', sa.Integer(), nullable=False),
    sa.Column('page_order', sa.Integer(), nullable=False),
    sa.Column('image_key', sa.String(length=512), nullable=False),
    sa.Column('page_type', sa.String(length=16), nullable=False),
    sa.Column('width_px', sa.Integer(), nullable=False),
    sa.Column('height_px', sa.Integer(), nullable=False),
    sa.CheckConstraint("page_type IN ('question', 'answer')", name='ck_qpage_page_type'),
    sa.CheckConstraint('width_px > 0 AND height_px > 0', name='ck_qpage_positive_dims'),
    sa.ForeignKeyConstraint(['question_id'], ['question.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('question_id', 'page_type', 'page_order', name='uq_qpage_q_type_order')
    )
    # question_topic: 0+ topics per question.
    # Composite PK (question_id, topic_id) allows question_subtopic to reference this pair.
    op.create_table('question_topic',
    sa.Column('question_id', sa.Integer(), nullable=False),
    sa.Column('topic_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['question_id'], ['question.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['topic_id'], ['topic.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('question_id', 'topic_id'),
    )
    # question_subtopic: 0+ subtopics per question.
    # Composite FK (question_id, topic_id) → question_topic enforces at DB level that
    # a subtopic can only be assigned when the matching topic is already assigned to
    # the question.  Cascade removes subtopic rows when the topic assignment changes.
    op.create_table('question_subtopic',
    sa.Column('question_id', sa.Integer(), nullable=False),
    sa.Column('subtopic_id', sa.Integer(), nullable=False),
    sa.Column('topic_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(
        ['question_id', 'topic_id'],
        ['question_topic.question_id', 'question_topic.topic_id'],
        name='fk_qsubtopic_question_topic',
        ondelete='CASCADE',
    ),
    sa.ForeignKeyConstraint(['subtopic_id'], ['subtopic.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('question_id', 'subtopic_id'),
    )

    op.bulk_insert(school_level_table, SCHOOL_LEVELS)

    bind = op.get_bind()
    school_level_ids = {
        row.name: row.id
        for row in bind.execute(sa.text("SELECT id, name FROM school_level"))
    }

    op.bulk_insert(subject_table, SUBJECTS)
    op.bulk_insert(
        stream_table,
        [{"name": s["name"], "school_level_id": school_level_ids[s["school_level"]]} for s in STREAMS],
    )
    op.bulk_insert(
        level_table,
        [{"name": l["name"], "sort_order": l["sort_order"], "school_level_id": school_level_ids[l["school_level"]]} for l in LEVELS],
    )
    op.bulk_insert(exam_type_table, EXAM_TYPES)
    op.bulk_insert(user_table, [ADMIN_USER])


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM app_user WHERE email = :email"), {"email": ADMIN_USER["email"]})
    bind.execute(sa.text("DELETE FROM exam_type WHERE name = ANY(:names)"), {"names": [e["name"] for e in EXAM_TYPES]})
    bind.execute(sa.text("DELETE FROM level WHERE name = ANY(:names)"), {"names": list({l["name"] for l in LEVELS})})
    bind.execute(sa.text("DELETE FROM stream WHERE name = ANY(:names)"), {"names": [s["name"] for s in STREAMS]})
    bind.execute(sa.text("DELETE FROM subject WHERE name = ANY(:names)"), {"names": [s["name"] for s in SUBJECTS]})
    bind.execute(sa.text("DELETE FROM school_level WHERE name = ANY(:names)"), {"names": [sl["name"] for sl in SCHOOL_LEVELS]})
    op.drop_table('question_subtopic')
    op.drop_table('question_topic')
    op.drop_table('question_page')
    op.drop_table('subtopic')
    op.drop_table('question')
    op.drop_table('topic')
    op.drop_table('paper')
    op.drop_table('stream')
    op.drop_table('level')
    op.drop_table('subject')
    op.drop_table('school_level')
    op.drop_table('school')
    op.drop_table('exam_type')
    op.drop_table('app_user')
