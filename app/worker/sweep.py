"""The daily sweep: removes the scratch folders of settled (cancelled or confirmed) jobs.

Pending jobs (``review_ready`` / ``failed``) never expire: they stay until the admin confirms or
cancels them. The ``expired`` status survives only on historical rows.

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

log = logging.getLogger("pillora.worker")

# Daily keeps the sweep to one query a day.
SWEEP_EVERY = timedelta(days=1)
# A cancelled job's scratch folder may still be in use by the task that was running when it was
# cancelled; leave it this long before removing it.
CANCELLED_SCRATCH_GRACE = timedelta(days=1)


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
    """The sweep if it is due (``None`` when not); returns the ids of the jobs whose scratch it removed."""
    now = clock()
    if not claim_sweep(session_factory, now):
        return None
    return clean_cancelled_scratch(session_factory, scratch_root, now)
