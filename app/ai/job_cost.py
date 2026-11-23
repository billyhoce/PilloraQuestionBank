"""Per-job Claude cost: one ``ingest_claude_call`` row per call made for a job.

Written by :func:`record_usage` (the worker's segment and metadata calls); read by the job routes
as a job's breakdown (:func:`job_cost`), each listed job's total (:func:`costs_by_job`) and the
spend of this and last month (:func:`monthly_spend`).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta, timezone

from sqlalchemy import func, select

from app.log_context import current_context
from app.logger import log_claude_call

log = logging.getLogger("pillora")

# A job's one row from before calls were itemised: its old report["cost"] totals.
LEGACY = "legacy"
# Spend is counted per calendar month in Singapore time (no daylight saving, so a fixed offset).
SPEND_TZ = timezone(timedelta(hours=8))

_TOKENS = ("input_tokens", "output_tokens", "cache_write", "cache_hit")


def session_factory():
    """The sessionmaker the cost writes use; tests replace this."""
    from app.db import SessionLocal

    return SessionLocal


def add_call(
    job_id, fields: dict, *, kind: str, source: str | None = None, context: dict | None = None,
    seconds: float | None = None, request_id: str | None = None, factory=None,
) -> None:
    """Store one call (``fields`` from ``log_claude_call``) as a row of the job.

    ``context`` is the log context of the call: its stage, section, task attempt and ``paper``
    (the paper key a metadata call is for). The row's ``run`` counts the job's retries so far.
    Its own short transaction; never raises: cost bookkeeping must not fail a Claude call.
    """
    from app.models.orm import IngestClaudeCall, IngestEvent, IngestJob

    context = context or {}
    try:
        job_uuid = uuid.UUID(str(job_id))
        with (factory or session_factory())() as db:
            if db.get(IngestJob, job_uuid) is None:
                return
            run = db.scalar(
                select(func.count()).select_from(IngestEvent)
                .where(IngestEvent.job_id == job_uuid, IngestEvent.kind == "retry")
            )
            attempt = context.get("task_attempt")
            db.add(IngestClaudeCall(
                job_id=job_uuid, at=datetime.now(UTC), kind=kind,
                paper_key=_short(context.get("paper")), source=source,
                stage=_short(context.get("stage")), section=_short(context.get("section"), 8),
                run=run or 0, attempt=attempt if isinstance(attempt, int) else None,
                model=str(fields.get("model", ""))[:64],
                **{key: int(fields.get(key, 0)) for key in _TOKENS},
                cost_usd=fields.get("cost_usd"),
                seconds=round(seconds, 2) if isinstance(seconds, (int, float)) else None,
                request_id=request_id[:128] if isinstance(request_id, str) else None,
            ))
            db.commit()
    except Exception:
        log.exception("could not record job cost")


def _short(value, length: int = 16) -> str | None:
    return str(value)[:length] if value else None


def record_usage(
    purpose: str, model: str, usage, request_id: str | None = None, *,
    kind: str, source: str | None = None, **call,
) -> None:
    """Log a call (:func:`~app.logger.log_claude_call`, ``call`` its reply, seconds and stop
    reason) and store it against the current job as a ``kind`` call.

    The job is the one in the log context (set by the runner per task); a call outside a job
    is only logged.
    """
    fields = log_claude_call(purpose, model, usage, request_id, **call)
    context = dict(current_context())
    job_id = context.get("job_id")
    if job_id:
        add_call(
            job_id, fields, kind=kind, source=source, context=context,
            seconds=call.get("seconds"), request_id=request_id,
        )


# --- reads --------------------------------------------------------------------------------


def _call_out(row) -> dict:
    return {
        "id": row.id, "at": row.at, "kind": row.kind, "paper_key": row.paper_key,
        "source": row.source, "run": row.run, "attempt": row.attempt, "model": row.model,
        **{key: getattr(row, key) for key in _TOKENS},
        "cost_usd": row.cost_usd,
    }


def job_cost(db, job_id) -> dict | None:
    """The job's Claude cost: totals and every call in the order made; ``None`` without any.

    ``calls`` counts the itemised calls only (a ``legacy`` row stands for an unknown number);
    ``unpriced`` is true when some call's model had no price, so the total is short of it."""
    from app.models.orm import IngestClaudeCall

    rows = db.scalars(
        select(IngestClaudeCall).where(IngestClaudeCall.job_id == job_id).order_by(IngestClaudeCall.id)
    ).all()
    if not rows:
        return None
    return {
        "total_usd": round(sum(r.cost_usd or 0 for r in rows), 6),
        "calls": sum(1 for r in rows if r.kind != LEGACY),
        **{key: sum(getattr(r, key) for r in rows) for key in _TOKENS},
        "unpriced": any(r.cost_usd is None for r in rows),
        "items": [_call_out(r) for r in rows],
    }


def costs_by_job(db, job_ids) -> dict:
    """Each job's total Claude cost in USD, for the jobs that made any call."""
    from app.models.orm import IngestClaudeCall

    ids = list(job_ids)
    if not ids:
        return {}
    rows = db.execute(
        select(IngestClaudeCall.job_id, func.sum(IngestClaudeCall.cost_usd))
        .where(IngestClaudeCall.job_id.in_(ids))
        .group_by(IngestClaudeCall.job_id)
    ).all()
    return {job_id: round(total or 0, 6) for job_id, total in rows}


def month_bounds(now: datetime) -> tuple[datetime, datetime]:
    """The starts of last month and this month in Singapore time, as UTC instants."""
    local = now.astimezone(SPEND_TZ)
    this_start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_start = (this_start - timedelta(days=1)).replace(day=1)
    return last_start.astimezone(UTC), this_start.astimezone(UTC)


def monthly_spend(db, now: datetime | None = None) -> dict:
    """Claude spend of this and last calendar month (Singapore time), across every job:
    ``{"this_month": {"month": "2026-11", "usd", "jobs"}, "last_month": {...}}``.
    A call counts in the month it was made; ``jobs`` counts the jobs with a call in it."""
    from app.models.orm import IngestClaudeCall

    last_start, this_start = month_bounds(now or datetime.now(UTC))

    def total(start, end) -> dict:
        query = select(func.sum(IngestClaudeCall.cost_usd), func.count(func.distinct(IngestClaudeCall.job_id)))
        query = query.where(IngestClaudeCall.at >= start)
        if end is not None:
            query = query.where(IngestClaudeCall.at < end)
        usd, jobs = db.execute(query).one()
        return {"month": start.astimezone(SPEND_TZ).strftime("%Y-%m"), "usd": round(usd or 0, 6), "jobs": jobs}

    return {"this_month": total(this_start, None), "last_month": total(last_start, this_start)}
