"""The task store: what the runner needs from wherever tasks live.

A Protocol, with nothing SQLite-shaped in it, so the webapp can satisfy it with
SQLAlchemy over Postgres (``SELECT ... FOR UPDATE SKIP LOCKED`` for the claim).
The identity of a task is ``(job_id, section, stage)``; ``section`` is ``None``
for a job-scope stage. ``add_tasks`` must be idempotent on that key -- note that
SQL treats NULLs as distinct, so a Postgres unique constraint needs
``NULLS NOT DISTINCT`` (or an equivalent expression index) for ``section``.

Task statuses::

    pending   waiting on a dependency (also where ``reopen`` puts a task to run again)
    ready     runnable; ``claim_ready`` picks from these
    running   claimed; its lease expires at ``lease_until``
    done / skipped / failed   finished
    blocked   a dependency failed or was blocked, so this never ran
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, Sequence

from .outcome import Outcome

PENDING = "pending"
READY = "ready"
RUNNING = "running"
DONE = "done"
SKIPPED = "skipped"
FAILED = "failed"
BLOCKED = "blocked"

STATUSES = (PENDING, READY, RUNNING, DONE, SKIPPED, FAILED, BLOCKED)
TERMINAL = (DONE, SKIPPED, FAILED, BLOCKED)

JOB_QUEUED = "queued"
JOB_RUNNING = "running"
JOB_DONE = "done"
JOB_FAILED = "failed"


@dataclass(frozen=True)
class TaskSpec:
    """A task to create. New tasks start ``pending``; the runner promotes them."""

    job_id: str
    stage: str
    section: str | None = None


@dataclass(frozen=True)
class Job:
    id: str  # a string (a UUID in the webapp)
    source: str  # the booklet PDF
    status: str
    created_at: datetime


@dataclass(frozen=True)
class Task:
    id: int
    job_id: str
    section: str | None
    stage: str
    status: str
    attempts: int = 0
    reason: str = ""
    error: str = ""
    warnings: tuple[str, ...] = ()
    needs_review: bool = False
    fingerprint: str | None = None  # of the inputs a ``done`` task's artefacts were made from
    lease_until: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None

    @property
    def key(self) -> tuple[str | None, str]:
        return (self.section, self.stage)


class Store(Protocol):
    # --- the runner's loop ------------------------------------------------
    def claim_ready(self, lease_seconds: float) -> Task | None:
        """Atomically take the oldest ready task (earliest job first) as running.

        The stored fingerprint, warnings and review flag are cleared (a runner killed
        mid-task must not leave a fingerprint vouching for half-written artefacts), but
        the returned :class:`Task` still carries the previous run's values, so the runner
        can complete a task whose fingerprint still matches without running it."""

    def heartbeat(self, task_id: int, lease_seconds: float) -> bool:
        """Extend a running task's lease; ``False`` when it is no longer ours."""

    def complete(
        self,
        task_id: int,
        outcome: Outcome,
        *,
        fingerprint: str | None = None,
        spawn: Sequence[TaskSpec] = (),
    ) -> bool:
        """Record a ``done`` or ``skipped`` outcome on a running task, with the fingerprint
        of the inputs it ran on (kept for a ``done`` task only) and the tasks its fan-out
        creates, **in one transaction**: a crash cannot leave a finished fan-out stage
        whose tasks were never created (``report`` would then run early). ``spawn`` is
        ignored, and ``False`` returned, when the task is no longer ours."""

    def fail(self, task_id: int, outcome: Outcome) -> bool:
        """Record a ``failed`` outcome (its error, warnings) on a running task."""

    def add_tasks(self, specs: Sequence[TaskSpec]) -> list[Task]:
        """Create the tasks that do not exist yet; returns only the new ones."""

    def reset_stale(self, retry_limit: int) -> list[Task]:
        """Hand back running tasks whose lease expired: ``ready`` again, or ``failed``
        once they have used ``retry_limit`` attempts. Returns the tasks changed."""

    def reopen(self, task_ids: Sequence[int]) -> None:
        """Return finished tasks (``done``, ``skipped``, ``failed``, ``blocked``) to
        ``pending`` with no attempts used, keeping their fingerprint, warnings and review
        flag so the run that follows can still reuse an unchanged result. Running, ready
        and pending tasks are left alone."""

    # --- bookkeeping the runner also needs --------------------------------
    def add_job(self, job_id: str, source: str) -> Job: ...

    def get_job(self, job_id: str) -> Job | None: ...

    def jobs(self) -> list[Job]: ...

    def tasks(self, job_id: str | None = None) -> list[Task]: ...

    def set_status(self, task_ids: Sequence[int], status: str, reason: str = "") -> None:
        """Move ``pending`` tasks to ``ready``, ``blocked`` or ``skipped``."""

    def set_job_status(self, job_id: str, status: str) -> None: ...
