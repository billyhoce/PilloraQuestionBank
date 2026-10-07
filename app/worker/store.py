"""The pipeline's task store over the ``ingest_task`` table (SQLAlchemy, Postgres in production).

Satisfies ``pipeline.store.Store`` so the same ``Runner`` that drives the local SQLite store
drives the webapp's tables. Every method opens its own short session: the runner's heartbeat
thread and the worker's liveness thread use the store while the main thread is inside a stage,
and a SQLAlchemy session is not thread-safe.

Claiming is ``SELECT ... FOR UPDATE SKIP LOCKED`` (Postgres) followed by an update guarded by
``WHERE status = 'ready'`` whose row count says whether this claimer won. SQLite (the unit tests)
ignores ``FOR UPDATE``; the guarded update alone keeps two claimers from taking one task there.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pipeline.outcome import Outcome
from pipeline.store import (
    BLOCKED,
    DONE,
    FAILED,
    JOB_FAILED,
    JOB_QUEUED,
    JOB_RUNNING,
    PENDING,
    READY,
    RUNNING,
    SKIPPED,
    Job,
    Task,
    TaskSpec,
)
from sqlalchemy import select
from sqlalchemy import update as _update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.orm import IngestJob, IngestTask, WorkerHeartbeat

# Job states the worker never moves a job out of (the API owns them) and
# job states whose tasks it will pick up.
API_OWNED = ("cancelled", "confirmed", "expired")
CLAIMABLE_JOB_STATUSES = ("queued", "running")

REPORT_STAGE = "report"
SOURCE_NAME = "source.pdf"

_FINISHED = (DONE, SKIPPED, FAILED, BLOCKED)


def update(model):
    """An UPDATE that leaves the session's loaded objects alone (each method re-reads what it
    needs, and the in-Python evaluator cannot compare SQLite's naive datetimes)."""
    return _update(model).execution_options(synchronize_session=False)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _aware(moment: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes (all stored as UTC); Postgres aware ones."""
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


def derive_job_status(tasks: Sequence[Task], has_proposal: bool) -> tuple[str, str | None]:
    """The job's status (and, when it failed, why) from its tasks: the one rule, run after
    every completion, so the API never recomputes it.

    * ``running`` -- a task is running, or some have finished/started and others are still to run;
    * ``queued`` -- nothing has been started yet;
    * ``review_ready`` -- ``report`` is done and its proposal is stored on the job. Sections that
      failed do not stop this: the proposal lists them as failed for the admin to see;
    * ``failed`` -- nothing is left to run and there is no proposal to review, or a job-level stage
      (``register``, ``segment``, ``split``) failed or was blocked: the report would then describe
      a booklet nothing was extracted from. The error names the first such task.
    """
    if any(t.status == RUNNING for t in tasks):
        return JOB_RUNNING, None
    job_level_broken = next(
        (t for t in tasks if t.section is None and t.stage != REPORT_STAGE and t.status in (FAILED, BLOCKED)),
        None,
    )
    pending = any(t.status in (READY, PENDING) for t in tasks)
    report = next((t for t in tasks if t.section is None and t.stage == REPORT_STAGE), None)
    if job_level_broken is None and report is not None and report.status == DONE and has_proposal:
        return "review_ready", None
    if job_level_broken is not None and not pending:
        return JOB_FAILED, f"{job_level_broken.stage} {job_level_broken.status}: " + (
            job_level_broken.error or job_level_broken.reason or "no reason recorded"
        )
    if pending:
        started = any(t.status in _FINISHED or t.attempts for t in tasks)
        return (JOB_RUNNING if started else JOB_QUEUED), None
    # Nothing left to run, no proposal: report failed, or finished without writing one.
    if report is not None and report.status in (FAILED, BLOCKED):
        return JOB_FAILED, f"report {report.status}: {report.error or report.reason}"
    return JOB_FAILED, "the pipeline finished without a proposal"


class SqlStore:
    def __init__(
        self,
        session_factory: Callable[[], Session],
        scratch_root: Path | str,
        clock: Callable[[], datetime] = _utc_now,
        version: str | None = None,
    ) -> None:
        self._factory = session_factory
        self._scratch = Path(scratch_root)
        self._clock = clock
        self._version = version
        # The task this process is running (one at a time), for the liveness thread.
        self._current: tuple[int, uuid.UUID] | None = None

    @contextmanager
    def _session(self):
        db = self._factory()
        try:
            yield db
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    # --- the runner's loop ------------------------------------------------
    def claim_ready(self, lease_seconds: float) -> Task | None:
        with self._session() as db:
            for _ in range(5):  # a lost race (SQLite) or a vanished row: look again
                row = db.execute(
                    select(IngestTask)
                    .join(IngestJob, IngestJob.id == IngestTask.job_id)
                    .where(IngestTask.status == READY, IngestJob.status.in_(CLAIMABLE_JOB_STATUSES))
                    .order_by(IngestJob.created_at, IngestJob.id, IngestTask.id)
                    .limit(1)
                    .with_for_update(skip_locked=True, of=IngestTask)
                ).scalar_one_or_none()
                if row is None:
                    db.rollback()
                    return None
                before = self._task(row)
                now = self._clock()
                won = db.execute(
                    update(IngestTask)
                    .where(IngestTask.id == row.id, IngestTask.status == READY)
                    .values(
                        status=RUNNING,
                        attempts=IngestTask.attempts + 1,
                        reason="",
                        error="",
                        warnings=[],
                        needs_review=False,
                        fingerprint=None,
                        started_at=now,
                        finished_at=None,
                        duration_ms=None,
                        lease_until=now + timedelta(seconds=lease_seconds),
                    )
                ).rowcount
                if won != 1:
                    db.rollback()
                    continue
                db.commit()
                claimed = self._task(db.get(IngestTask, row.id, populate_existing=True))
                self._current = (claimed.id, row.job_id)
                self._touch_worker(db, row.job_id)
                db.commit()
                # The row is cleared; the caller still sees what the last run left.
                return replace(
                    claimed,
                    fingerprint=before.fingerprint,
                    warnings=before.warnings,
                    needs_review=before.needs_review,
                )
            return None

    def heartbeat(self, task_id: int, lease_seconds: float) -> bool:
        with self._session() as db:
            won = db.execute(
                update(IngestTask)
                .where(IngestTask.id == task_id, IngestTask.status == RUNNING)
                .values(lease_until=self._clock() + timedelta(seconds=lease_seconds))
            ).rowcount
            db.commit()
            return won == 1

    def complete(
        self,
        task_id: int,
        outcome: Outcome,
        *,
        fingerprint: str | None = None,
        spawn: Sequence[TaskSpec] = (),
    ) -> bool:
        if outcome.status not in (DONE, SKIPPED):
            raise ValueError(f"complete() takes done or skipped, not {outcome.status}")
        with self._session() as db:
            finished = self._finish(db, task_id, outcome, fingerprint)
            if finished and spawn:
                self._add_tasks(db, spawn)
            db.commit()
        self._release(task_id)
        return finished

    def fail(self, task_id: int, outcome: Outcome) -> bool:
        if outcome.status != FAILED:
            raise ValueError(f"fail() takes failed, not {outcome.status}")
        with self._session() as db:
            finished = self._finish(db, task_id, outcome, None)
            db.commit()
        self._release(task_id)
        return finished

    def _finish(self, db: Session, task_id: int, outcome: Outcome, fingerprint: str | None) -> bool:
        row = db.execute(
            select(IngestTask.started_at).where(IngestTask.id == task_id, IngestTask.status == RUNNING)
        ).first()
        if row is None:
            return False
        now = self._clock()
        started = _aware(row[0])
        duration = int((now - started).total_seconds() * 1000) if started else None
        won = db.execute(
            update(IngestTask)
            .where(IngestTask.id == task_id, IngestTask.status == RUNNING)
            .values(
                status=outcome.status,
                reason=outcome.reason,
                error=outcome.error,
                warnings=list(outcome.warnings),
                needs_review=outcome.needs_review,
                fingerprint=fingerprint if outcome.status == DONE else None,
                lease_until=None,
                finished_at=now,
                duration_ms=duration,
            )
        ).rowcount
        return won == 1

    def _release(self, task_id: int) -> None:
        if self._current is not None and self._current[0] == task_id:
            self._current = None

    def add_tasks(self, specs: Sequence[TaskSpec]) -> list[Task]:
        with self._session() as db:
            created = self._add_tasks(db, specs)
            db.commit()
            return created

    def _add_tasks(self, db: Session, specs: Sequence[TaskSpec]) -> list[Task]:
        """Insert the tasks that do not exist yet. The existence check is the fast path;
        the unique constraints (and the partial index for a NULL section) settle a race."""
        created: list[Task] = []
        for spec in specs:
            job_id = uuid.UUID(str(spec.job_id))
            exists = db.execute(
                select(IngestTask.id).where(
                    IngestTask.job_id == job_id,
                    IngestTask.stage == spec.stage,
                    IngestTask.section.is_(None) if spec.section is None else IngestTask.section == spec.section,
                )
            ).first()
            if exists:
                continue
            row = IngestTask(job_id=job_id, section=spec.section, stage=spec.stage, status=PENDING)
            try:
                with db.begin_nested():
                    db.add(row)
                    db.flush()
            except IntegrityError:
                continue
            created.append(self._task(row))
        return created

    def reset_stale(self, retry_limit: int) -> list[Task]:
        with self._session() as db:
            now = self._clock()
            rows = db.execute(
                select(IngestTask).where(IngestTask.status == RUNNING, IngestTask.lease_until < now)
            ).scalars().all()
            changed: list[Task] = []
            for row in rows:
                if row.attempts >= retry_limit:
                    values = dict(
                        status=FAILED,
                        lease_until=None,
                        finished_at=now,
                        needs_review=True,
                        error=f"the lease expired on each of {row.attempts} attempt(s); "
                        "the runner stopped responding",
                    )
                else:
                    values = dict(status=READY, lease_until=None)
                won = db.execute(
                    update(IngestTask)
                    .where(IngestTask.id == row.id, IngestTask.status == RUNNING, IngestTask.lease_until < now)
                    .values(**values)
                ).rowcount
                if won == 1:
                    changed.append(row)
            db.commit()
            return [self._task(db.get(IngestTask, r.id, populate_existing=True)) for r in changed]

    def reopen(self, task_ids: Sequence[int]) -> None:
        if not task_ids:
            return
        with self._session() as db:
            db.execute(
                update(IngestTask)
                .where(IngestTask.id.in_(list(task_ids)), IngestTask.status.in_(_FINISHED))
                .values(status=PENDING, attempts=0, reason="", error="", lease_until=None, finished_at=None)
            )
            db.commit()

    # --- bookkeeping ------------------------------------------------------
    def add_job(self, job_id: str, source: str) -> Job:
        raise NotImplementedError("jobs are created by POST /api/import/jobs, not the worker")

    def get_job(self, job_id: str) -> Job | None:
        with self._session() as db:
            row = db.get(IngestJob, uuid.UUID(str(job_id)))
            return self._job(row) if row else None

    def jobs(self) -> list[Job]:
        """The jobs the worker may still work on, oldest first."""
        with self._session() as db:
            rows = db.execute(
                select(IngestJob)
                .where(IngestJob.status.in_(CLAIMABLE_JOB_STATUSES))
                .order_by(IngestJob.created_at, IngestJob.id)
            ).scalars().all()
            return [self._job(row) for row in rows]

    def tasks(self, job_id: str | None = None) -> list[Task]:
        with self._session() as db:
            query = select(IngestTask).order_by(IngestTask.id)
            if job_id is not None:
                query = query.where(IngestTask.job_id == uuid.UUID(str(job_id)))
            return [self._task(row) for row in db.execute(query).scalars()]

    def set_status(self, task_ids: Sequence[int], status: str, reason: str = "") -> None:
        if not task_ids:
            return
        with self._session() as db:
            db.execute(
                update(IngestTask)
                .where(IngestTask.id.in_(list(task_ids)), IngestTask.status == PENDING)
                .values(status=status, reason=reason)
            )
            db.commit()

    def set_job_status(self, job_id: str, status: str) -> None:
        """Derive the job's status from its tasks (:func:`derive_job_status`).

        The runner passes its own verdict (``done``/``failed``/...); it has no notion of
        ``review_ready`` or of a job the admin cancelled, so it is ignored here and the status
        is recomputed from the rows. A job in an API-owned state is never touched."""
        uid = uuid.UUID(str(job_id))
        with self._session() as db:
            job = db.get(IngestJob, uid, with_for_update=True)
            if job is None or job.status in API_OWNED:
                return
            tasks = [
                self._task(row)
                for row in db.execute(
                    select(IngestTask).where(IngestTask.job_id == uid).order_by(IngestTask.id)
                ).scalars()
            ]
            derived, error = derive_job_status(tasks, job.proposal is not None)
            job.status = derived
            job.error = error
            db.commit()

    # --- the worker's own state -------------------------------------------
    def touch_worker(self, lease_seconds: float | None = None) -> None:
        """Write the worker heartbeat (and extend the running task's lease), from any thread."""
        current = self._current
        with self._session() as db:
            self._touch_worker(db, current[1] if current else None)
            if current is not None and lease_seconds is not None:
                db.execute(
                    update(IngestTask)
                    .where(IngestTask.id == current[0], IngestTask.status == RUNNING)
                    .values(lease_until=self._clock() + timedelta(seconds=lease_seconds))
                )
            db.commit()

    def _touch_worker(self, db: Session, job_id: uuid.UUID | None) -> None:
        values = dict(seen_at=self._clock(), version=self._version, current_job_id=job_id)
        if db.execute(update(WorkerHeartbeat).where(WorkerHeartbeat.id == 1).values(**values)).rowcount:
            return
        try:
            with db.begin_nested():
                db.add(WorkerHeartbeat(id=1, **values))
                db.flush()
        except IntegrityError:  # another process inserted the row first
            db.execute(update(WorkerHeartbeat).where(WorkerHeartbeat.id == 1).values(**values))

    # --- conversions ------------------------------------------------------
    @staticmethod
    def _task(row: IngestTask) -> Task:
        return Task(
            id=row.id,
            job_id=str(row.job_id),
            section=row.section,
            stage=row.stage,
            status=row.status,
            attempts=row.attempts,
            reason=row.reason or "",
            error=row.error or "",
            warnings=tuple(row.warnings or ()),
            needs_review=bool(row.needs_review),
            fingerprint=row.fingerprint,
            lease_until=_aware(row.lease_until),
            started_at=_aware(row.started_at),
            finished_at=_aware(row.finished_at),
            duration_ms=row.duration_ms,
        )

    def _job(self, row: IngestJob) -> Job:
        return Job(
            id=str(row.id),
            source=str(self._scratch / str(row.id) / SOURCE_NAME),
            status=row.status,
            created_at=_aware(row.created_at),
        )
