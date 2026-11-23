"""add ingest_paper

One queryable row per paper an ingest job proposed (role, the seven metadata fields and their
source, status, the paper it became, the paper it matched). Backfills a row for every existing
job that has a proposal, so old pending jobs can be matched too.

Backfill (best effort): metadata from ``report.paper_metadata[key]`` (source ``cover``), else the
old job-wide ``report.filename_metadata`` (source ``filename``); status from
``report.review_outcome[key]`` (``paper_id`` is left NULL: old jobs do not record which paper was
made from which key). Metadata ids that no longer exist are dropped to NULL.

Revision ID: a4b5c6d7e8f9
Revises: a3b4c5d6e7f8
Create Date: 2026-10-14 13:00:00.000000

"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'a4b5c6d7e8f9'
down_revision: Union[str, None] = 'a3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FIELDS = ("school_id", "year", "level_id", "subject_id", "exam_type_id", "stream_id", "paper_number")
_REFS = {"school_id": "school", "level_id": "level", "subject_id": "subject",
         "exam_type_id": "exam_type", "stream_id": "stream"}


def upgrade() -> None:
    op.create_table(
        'ingest_paper',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('job_id', sa.Uuid(), nullable=False),
        sa.Column('paper_key', sa.String(length=64), nullable=False),
        sa.Column('role', sa.String(length=16), server_default='question', nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=True),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('level_id', sa.Integer(), nullable=True),
        sa.Column('subject_id', sa.Integer(), nullable=True),
        sa.Column('exam_type_id', sa.Integer(), nullable=True),
        sa.Column('stream_id', sa.Integer(), nullable=True),
        sa.Column('paper_number', sa.String(length=32), nullable=True),
        sa.Column('metadata_source', sa.String(length=16), nullable=True),
        sa.Column('status', sa.String(length=16), server_default='pending', nullable=False),
        sa.Column('paper_id', sa.Integer(), nullable=True),
        sa.Column('matched_ingest_paper_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['job_id'], ['ingest_job.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['school_id'], ['school.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['level_id'], ['level.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['subject_id'], ['subject.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['exam_type_id'], ['exam_type.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['stream_id'], ['stream.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['paper_id'], ['paper.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['matched_ingest_paper_id'], ['ingest_paper.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('job_id', 'paper_key', name='uq_ingest_paper_job_key'),
    )
    op.create_index('ix_ingest_paper_job_id', 'ingest_paper', ['job_id'])
    _backfill(op.get_bind())


def _backfill(bind) -> None:
    ids = {col: {r[0] for r in bind.execute(sa.text(f"SELECT id FROM {table}"))} for col, table in _REFS.items()}
    insert = sa.text(
        "INSERT INTO ingest_paper (job_id, paper_key, role, school_id, year, level_id, subject_id, "
        "exam_type_id, stream_id, paper_number, metadata_source, status) VALUES "
        "(:job_id, :paper_key, :role, :school_id, :year, :level_id, :subject_id, :exam_type_id, "
        ":stream_id, :paper_number, :metadata_source, :status)"
    )
    jobs = bind.execute(sa.text("SELECT id, proposal, report FROM ingest_job WHERE proposal IS NOT NULL")).fetchall()
    for job_id, proposal, report in jobs:
        proposal = json.loads(proposal) if isinstance(proposal, str) else proposal
        report = json.loads(report) if isinstance(report, str) else (report or {})
        per_paper = report.get("paper_metadata") or {}
        outcomes = report.get("review_outcome") or {}
        for i, paper in enumerate((proposal or {}).get("papers", [])):
            key = paper.get("label") or paper.get("answer_label") or f"paper{i + 1}"
            if key in per_paper:
                meta, source = per_paper[key] or {}, "cover"
            elif report.get("filename_metadata"):
                meta, source = report["filename_metadata"], "filename"
            else:
                meta, source = {}, None
            row = {f: meta.get(f) if meta.get(f) != "" else None for f in _FIELDS}
            for col, known in ids.items():
                if row[col] not in known:
                    row[col] = None
            if row["year"] is not None:
                try:
                    row["year"] = int(row["year"])
                except (TypeError, ValueError):
                    row["year"] = None
            if row["paper_number"] is not None:
                row["paper_number"] = str(row["paper_number"])[:32]
            status = outcomes.get(key)
            bind.execute(insert, {
                "job_id": job_id, "paper_key": key,
                "role": "answer_only" if paper.get("role") == "answer_only" else "question",
                "metadata_source": source,
                "status": status if status in ("confirmed", "skipped") else "pending",
                **row,
            })


def downgrade() -> None:
    op.drop_index('ix_ingest_paper_job_id', table_name='ingest_paper')
    op.drop_table('ingest_paper')
