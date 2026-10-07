"""The daily sweep: abandoned ingest jobs expire, and their S3 prefix and scratch folder go.

A job that has sat in ``review_ready`` or ``failed`` for more than :data:`EXPIRE_AFTER` is marked
``expired`` and its ``tmp/ingest/{job_id}/`` prefix deleted (after the commit, as the API's cancel
does). The bucket lifecycle rule on ``tmp/`` (docs/DEPLOYMENT.md) backs a failed delete up.

The sweep is claimed by an atomic update of ``worker_heartbeat.last_sweep_at``, so it runs at most
once per :data:`SWEEP_EVERY` across restarts and across workers.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy import update as _update

from app.models.orm import IngestJob, WorkerHeartbeat
from app.services.ingest_jobs import job_prefix

log = logging.getLogger("pillora.worker")

# A week gives an admin a working week plus a weekend to come back to a proposal; the S3
# lifecycle rule on tmp/ uses the same figure, so the two agree on when abandoned data goes.
EXPIRE_AFTER = timedelta(days=7)
# Daily is plenty for a 7-day threshold (a job lingers at most ~1 day past it) and keeps the
# sweep to one query a day.
SWEEP_EVERY = timedelta(days=1)
# A cancelled job's scratch folder may still be in use by the task that was running when it was
# cancelled; leave it this long before removing it.
CANCELLED_SCRATCH_GRACE = timedelta(days=1)

STALE_STATUSES = ("review_ready", "failed")


def _update_core(model):
    return _update(model).execution_options(synchronize_session=False)


def claim_sweep(session_factory, now: datetime) -> bool:
    """Atomically claim the daily sweep; ``False`` when one ran within :data:`SWEEP_EVERY`."""
    with session_factory() as db:
        won = db.execute(
            _update_core(WorkerHeartbeat)
            .where(
                WorkerHeartbeat.id == 1,
                or_(
                    WorkerHeartbeat.last_sweep_at.is_(None),
                    WorkerHeartbeat.last_sweep_at < now - SWEEP_EVERY,
                ),
            )
            .values(last_sweep_at=now)
        ).rowcount
        db.commit()
        return won == 1


def _remove_scratch(scratch_root: Path, job_id) -> None:
    folder = scratch_root / str(job_id)
    try:
        shutil.rmtree(folder, ignore_errors=True)
    except OSError:
        log.exception("sweep: could not remove scratch %s", folder)


def expire_stale_jobs(session_factory, object_store, scratch_root: Path, now: datetime) -> list[uuid.UUID]:
    """Expire the stale jobs, then delete their S3 prefixes and scratch folders."""
    cutoff = now - EXPIRE_AFTER
    expired: list[uuid.UUID] = []
    with session_factory() as db:
        ids = db.execute(
            select(IngestJob.id).where(IngestJob.status.in_(STALE_STATUSES), IngestJob.updated_at < cutoff)
        ).scalars().all()
        for job_id in ids:
            # Guarded: a job retried or confirmed since the select is left alone.
            won = db.execute(
                _update_core(IngestJob)
                .where(
                    IngestJob.id == job_id,
                    IngestJob.status.in_(STALE_STATUSES),
                    IngestJob.updated_at < cutoff,
                )
                .values(status="expired", updated_at=now)
            ).rowcount
            if won:
                expired.append(job_id)
        db.commit()
    for job_id in expired:
        prefix = job_prefix(job_id)
        try:
            object_store.delete_prefix(prefix)
        except Exception:
            log.exception("sweep: could not delete %s (the bucket lifecycle rule will)", prefix)
        _remove_scratch(scratch_root, job_id)
        log.info("sweep: job %s expired", job_id)
    return expired


def clean_cancelled_scratch(session_factory, scratch_root: Path, now: datetime) -> list[uuid.UUID]:
    """Remove the scratch folders of jobs cancelled or confirmed more than the grace period ago.
    (Confirming deletes the job's S3 prefix itself; only the worker knows the scratch folder.)"""
    cutoff = now - CANCELLED_SCRATCH_GRACE
    with session_factory() as db:
        ids = db.execute(
            select(IngestJob.id).where(IngestJob.status.in_(("cancelled", "confirmed")), IngestJob.updated_at < cutoff)
        ).scalars().all()
    cleaned = [i for i in ids if (scratch_root / str(i)).exists()]
    for job_id in cleaned:
        _remove_scratch(scratch_root, job_id)
    return cleaned


def run_sweep(
    session_factory,
    object_store,
    scratch_root: Path,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> list[uuid.UUID] | None:
    """The sweep if it is due (``None`` when not); returns the ids of the jobs it expired."""
    now = clock()
    if not claim_sweep(session_factory, now):
        return None
    expired = expire_stale_jobs(session_factory, object_store, scratch_root, now)
    clean_cancelled_scratch(session_factory, scratch_root, now)
    return expired
