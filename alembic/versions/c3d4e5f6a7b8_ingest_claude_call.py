"""ingest_claude_call: one row per Claude call made for an ingest job

Replaces the running total in ``ingest_job.report["cost"]`` so the job detail can break cost
down per call and the job list can sum spend across jobs. Each job that already has a
``report["cost"]`` total gets one ``legacy`` row holding it, dated at the job's creation.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-11-23 12:00:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    calls = op.create_table(
        'ingest_claude_call',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('job_id', sa.Uuid(), sa.ForeignKey('ingest_job.id', ondelete='CASCADE'), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('paper_key', sa.String(length=16), nullable=True),
        sa.Column('source', sa.String(length=16), nullable=True),
        sa.Column('stage', sa.String(length=16), nullable=True),
        sa.Column('section', sa.String(length=8), nullable=True),
        sa.Column('run', sa.Integer(), server_default='0', nullable=False),
        sa.Column('attempt', sa.Integer(), nullable=True),
        sa.Column('model', sa.String(length=64), nullable=False),
        sa.Column('input_tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('output_tokens', sa.Integer(), server_default='0', nullable=False),
        sa.Column('cache_write', sa.Integer(), server_default='0', nullable=False),
        sa.Column('cache_hit', sa.Integer(), server_default='0', nullable=False),
        sa.Column('cost_usd', sa.Float(), nullable=True),
        sa.Column('seconds', sa.Float(), nullable=True),
        sa.Column('request_id', sa.String(length=128), nullable=True),
    )
    op.create_index('ix_ingest_claude_call_job_id_id', 'ingest_claude_call', ['job_id', 'id'])
    op.create_index('ix_ingest_claude_call_at', 'ingest_claude_call', ['at'])

    rows = []
    for job_id, report, created_at in op.get_bind().execute(
        sa.text("SELECT id, report, created_at FROM ingest_job WHERE report IS NOT NULL")
    ):
        if isinstance(report, str):
            report = json.loads(report)
        cost = (report or {}).get('cost') or {}
        if not cost.get('calls'):
            continue
        rows.append({
            'job_id': job_id, 'at': created_at, 'kind': 'legacy', 'run': 0, 'model': '',
            'input_tokens': int(cost.get('input_tokens', 0)), 'output_tokens': int(cost.get('output_tokens', 0)),
            'cache_write': int(cost.get('cache_write', 0)), 'cache_hit': int(cost.get('cache_hit', 0)),
            'cost_usd': float(cost.get('cost_usd', 0)),
        })
    if rows:
        op.bulk_insert(calls, rows)


def downgrade() -> None:
    op.drop_index('ix_ingest_claude_call_at', table_name='ingest_claude_call')
    op.drop_index('ix_ingest_claude_call_job_id_id', table_name='ingest_claude_call')
    op.drop_table('ingest_claude_call')
