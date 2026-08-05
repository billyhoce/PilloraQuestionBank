"""move topics, subtopics and marks from the question onto its parts

Introduces ``question_part`` — one row per printed part of a question ("(a)",
"(a)(i)", "(b)") — and re-points ``question_topic`` / ``question_subtopic`` at
``part_id`` instead of ``question_id``. ``question.marks`` is dropped; a
question's total is now ``SUM(question_part.marks)``.

Existing data is backfilled losslessly: every question gets exactly one part
(``part_order = 0``, ``label = ''``) carrying its old marks, and all of its
topic/subtopic rows move to that part.

``downgrade()`` is exact for data that was only ever backfilled. Once a question
has genuinely been split it is **lossy**: part labels and the per-part marks
split cannot be represented in the old schema, so marks are re-summed onto the
question and topic/subtopic rows are de-duplicated across parts.

Revision ID: c9d8e7f6a5b4
Revises: b7c8d9e0f1a2
Create Date: 2026-08-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9d8e7f6a5b4'
down_revision: Union[str, None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'question_part',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('question_id', sa.Integer(), nullable=False),
        sa.Column('part_order', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=32), server_default='', nullable=False),
        sa.Column('marks', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['question_id'], ['question.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('question_id', 'part_order', name='uq_qpart_question_order'),
        sa.CheckConstraint('part_order >= 0', name='ck_qpart_order_nonneg'),
    )

    # Every existing question becomes a single unlabelled part holding its marks.
    op.execute(
        "INSERT INTO question_part (question_id, part_order, label, marks) "
        "SELECT id, 0, '', marks FROM question"
    )

    # The composite FK points at question_topic's primary key, so it has to go
    # before that key can be replaced. It is re-created at the end.
    op.drop_constraint('fk_qsubtopic_question_topic', 'question_subtopic', type_='foreignkey')

    # --- question_topic: question_id -> part_id ---------------------------- #
    op.add_column('question_topic', sa.Column('part_id', sa.Integer(), nullable=True))
    op.execute(
        "UPDATE question_topic qt SET part_id = p.id "
        "FROM question_part p WHERE p.question_id = qt.question_id"
    )
    op.alter_column('question_topic', 'part_id', existing_type=sa.Integer(), nullable=False)
    op.drop_constraint('question_topic_pkey', 'question_topic', type_='primary')
    op.drop_column('question_topic', 'question_id')
    op.create_primary_key('question_topic_pkey', 'question_topic', ['part_id', 'topic_id'])
    op.create_foreign_key(
        'fk_qtopic_question_part', 'question_topic', 'question_part',
        ['part_id'], ['id'], ondelete='CASCADE',
    )

    # --- question_subtopic: question_id -> part_id ------------------------- #
    op.add_column('question_subtopic', sa.Column('part_id', sa.Integer(), nullable=True))
    op.execute(
        "UPDATE question_subtopic qs SET part_id = p.id "
        "FROM question_part p WHERE p.question_id = qs.question_id"
    )
    op.alter_column('question_subtopic', 'part_id', existing_type=sa.Integer(), nullable=False)
    op.drop_constraint('question_subtopic_pkey', 'question_subtopic', type_='primary')
    op.drop_column('question_subtopic', 'question_id')
    op.create_primary_key('question_subtopic_pkey', 'question_subtopic', ['part_id', 'subtopic_id'])
    op.create_foreign_key(
        'fk_qsubtopic_question_part', 'question_subtopic', 'question_part',
        ['part_id'], ['id'], ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_qsubtopic_question_topic', 'question_subtopic', 'question_topic',
        ['part_id', 'topic_id'], ['part_id', 'topic_id'], ondelete='CASCADE',
    )

    op.drop_column('question', 'marks')


def downgrade() -> None:
    op.add_column('question', sa.Column('marks', sa.Integer(), nullable=True))
    op.execute(
        "UPDATE question q SET marks = s.total FROM ("
        "  SELECT question_id, SUM(marks) AS total FROM question_part GROUP BY question_id"
        ") s WHERE s.question_id = q.id"
    )

    op.drop_constraint('fk_qsubtopic_question_topic', 'question_subtopic', type_='foreignkey')

    # --- question_topic: part_id -> question_id ---------------------------- #
    op.add_column('question_topic', sa.Column('question_id', sa.Integer(), nullable=True))
    op.execute(
        "UPDATE question_topic qt SET question_id = p.question_id "
        "FROM question_part p WHERE p.id = qt.part_id"
    )
    # Two parts of the same question can share a topic; the old key cannot.
    op.execute(
        "DELETE FROM question_topic a USING question_topic b "
        "WHERE a.question_id = b.question_id AND a.topic_id = b.topic_id "
        "AND a.part_id > b.part_id"
    )
    op.alter_column('question_topic', 'question_id', existing_type=sa.Integer(), nullable=False)
    op.drop_constraint('question_topic_pkey', 'question_topic', type_='primary')
    op.drop_constraint('fk_qtopic_question_part', 'question_topic', type_='foreignkey')
    op.drop_column('question_topic', 'part_id')
    op.create_primary_key('question_topic_pkey', 'question_topic', ['question_id', 'topic_id'])
    op.create_foreign_key(
        'question_topic_question_id_fkey', 'question_topic', 'question',
        ['question_id'], ['id'], ondelete='CASCADE',
    )

    # --- question_subtopic: part_id -> question_id ------------------------- #
    op.add_column('question_subtopic', sa.Column('question_id', sa.Integer(), nullable=True))
    op.execute(
        "UPDATE question_subtopic qs SET question_id = p.question_id "
        "FROM question_part p WHERE p.id = qs.part_id"
    )
    op.execute(
        "DELETE FROM question_subtopic a USING question_subtopic b "
        "WHERE a.question_id = b.question_id AND a.subtopic_id = b.subtopic_id "
        "AND a.part_id > b.part_id"
    )
    op.alter_column('question_subtopic', 'question_id', existing_type=sa.Integer(), nullable=False)
    op.drop_constraint('question_subtopic_pkey', 'question_subtopic', type_='primary')
    op.drop_constraint('fk_qsubtopic_question_part', 'question_subtopic', type_='foreignkey')
    op.drop_column('question_subtopic', 'part_id')
    op.create_primary_key('question_subtopic_pkey', 'question_subtopic', ['question_id', 'subtopic_id'])
    op.create_foreign_key(
        'question_subtopic_question_id_fkey', 'question_subtopic', 'question',
        ['question_id'], ['id'], ondelete='CASCADE',
    )
    op.create_foreign_key(
        'fk_qsubtopic_question_topic', 'question_subtopic', 'question_topic',
        ['question_id', 'topic_id'], ['question_id', 'topic_id'], ondelete='CASCADE',
    )

    op.drop_table('question_part')
