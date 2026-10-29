"""Per-job Claude cost: ``ingest_job.report["cost"]``, summed across every call of the job."""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from app.log_context import current_context  # noqa: F401  (re-exported for callers/tests)
from app.logger import log_claude_call

log = logging.getLogger("pillora")

_SUMMED = ("input_tokens", "output_tokens", "cache_write", "cache_hit")


def session_factory():
    """The sessionmaker the cost writes use; tests replace this."""
    from app.db import SessionLocal

    return SessionLocal


def add_cost(job_id, fields: dict, factory=None) -> None:
    """Add one call's ``fields`` (from ``log_claude_call``) to the job's ``report["cost"]``.

    Runs in its own short transaction and locks the job row (``SELECT ... FOR UPDATE``) while it
    reads and rewrites the report, so calls from concurrent tasks of one job cannot lose each
    other's update. Never raises: cost bookkeeping must not fail a Claude call.
    """
    from app.models.orm import IngestJob

    try:
        with (factory or session_factory())() as db:
            job = db.execute(
                select(IngestJob).where(IngestJob.id == uuid.UUID(str(job_id))).with_for_update()
            ).scalar_one_or_none()
            if job is None:
                return
            report = dict(job.report or {})
            cost = dict(report.get("cost") or {})
            cost["calls"] = int(cost.get("calls", 0)) + 1
            for key in _SUMMED:
                cost[key] = int(cost.get(key, 0)) + int(fields.get(key, 0))
            cost["cost_usd"] = round(float(cost.get("cost_usd", 0)) + float(fields.get("cost_usd", 0)), 6)
            report["cost"] = cost
            job.report = report  # reassign: JSON columns are not change-tracked in place
            db.commit()
    except Exception:
        log.exception("could not record job cost")


def record_usage(purpose: str, model: str, usage, request_id: str | None = None, **call) -> None:
    """Log a call (:func:`~app.logger.log_claude_call`, ``call`` its reply, seconds and stop
    reason) and add it to the current job's cost.

    The job is the one in the log context (set by the runner per task); a call outside a job
    is only logged.
    """
    fields = log_claude_call(purpose, model, usage, request_id, **call)
    job_id = current_context().get("job_id")
    if job_id:
        add_cost(job_id, fields)
