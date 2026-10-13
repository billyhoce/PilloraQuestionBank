"""The daily reconciler: compares the database with S3 and the scratch disk and reports (and,
once ``INGEST_RECONCILE_DELETE=true``, cleans) whatever the happy path missed.

Run from the daily sweep (:func:`app.worker.sweep.run_sweep`). Each check yields
:class:`Finding` s, which are logged with the job's context and written to ``ingest_event`` (kind
``reconcile``; ``job_id`` is NULL when the finding has no job). Every mutating action -- deleting
an object or folder, marking a stuck job failed -- happens only when ``delete`` is true; in
dry-run the finding's action says what *would* happen. A failure in one check never stops the
others.

| check                | rule                                                        | grace                |
|----------------------|-------------------------------------------------------------|----------------------|
| ``orphan_job_prefix``| ``ingest/{id}/`` / ``tmp/ingest/{id}/`` of a missing/settled job | 1 day after settle |
| ``stale_temp``       | anything under ``tmp/`` (but the legacy ``tmp/ingest/``)    | 24 h                 |
| ``orphan_scratch``   | scratch folder of a job not queued / running / failed       | 1 day                |
| ``orphan_paper_image``| ``papers/`` key no ``question_page`` references            | 7 days               |
| ``abandoned_upload`` | ``awaiting_upload`` job whose browser upload never finished | 1 h after creation  |
| ``stuck_job``        | queued / running, no live lease, no progress                | 6 h                  |
| ``missing_source``   | pending job whose source object is gone                     | report only          |
"""

from __future__ import annotations

import logging
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.logger import log_event, log_job_event
from app.models.orm import IngestJob, IngestTask, QuestionPage
from app.services.ingest_events import add_event
from app.services.ingest_jobs import cancel_job

log = logging.getLogger("pillora.worker")

SETTLED_STATUSES = ("confirmed", "cancelled", "expired")
PENDING_STATUSES = ("queued", "running", "review_ready", "failed")
SCRATCH_KEEP_STATUSES = ("queued", "running", "failed")

PREFIX_GRACE = timedelta(days=1)
TEMP_GRACE = timedelta(hours=24)
SCRATCH_GRACE = timedelta(days=1)
PAPER_IMAGE_GRACE = timedelta(days=7)
STUCK_AFTER = timedelta(hours=6)
UPLOAD_GRACE = timedelta(hours=1)

JOB_ROOTS = ("ingest/", "tmp/ingest/")

# Actions: what was done (delete mode) / would be done (dry run).
DELETED, WOULD_DELETE, DELETE_FAILED = "deleted", "would_delete", "delete_failed"
MARKED_FAILED, WOULD_MARK_FAILED = "marked_failed", "would_mark_failed"
CANCELLED, WOULD_CANCEL = "cancelled", "would_cancel"
REPORT_ONLY = "report_only"


@dataclass(frozen=True)
class Finding:
    kind: str
    key_or_path: str
    job_id: uuid.UUID | None
    age: timedelta
    action: str


def _aware(moment: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes (stored as UTC); Postgres aware ones."""
    if moment is not None and moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


def _job_id_of(key: str) -> uuid.UUID | None:
    """The job id in ``ingest/{id}/...`` or ``tmp/ingest/{id}/...``, else ``None``."""
    for root in JOB_ROOTS:
        if key.startswith(root):
            try:
                return uuid.UUID(key[len(root):].split("/", 1)[0])
            except ValueError:
                return None
    return None


def _try_delete(finding_kind: str, fn, delete: bool) -> str:
    if not delete:
        return WOULD_DELETE
    try:
        fn()
        return DELETED
    except Exception:
        log.exception("reconcile: could not delete (%s)", finding_kind)
        return DELETE_FAILED


class Reconciler:
    def __init__(self, session_factory, object_store, scratch_root: Path, now: datetime, delete: bool = False) -> None:
        self.factory = session_factory
        self.objects = object_store
        self.scratch = Path(scratch_root)
        self.now = now
        self.delete = delete
        self.findings: list[Finding] = []

    # --- the run --------------------------------------------------------------
    def run(self) -> list[Finding]:
        checks = (
            self.check_abandoned_uploads,
            self.check_job_prefixes_and_sources,
            self.check_stale_temp,
            self.check_orphan_scratch,
            self.check_orphan_paper_images,
            self.check_stuck_jobs,
        )
        for check in checks:
            try:
                check()
            except Exception:
                log.exception("reconcile: %s failed", check.__name__)
        self._record()
        return self.findings

    def _add(self, kind, key, job_id, age, action) -> None:
        self.findings.append(Finding(kind, key, job_id, max(age, timedelta(0)), action))

    def _record(self) -> None:
        """Log every finding (with the job context when it has one) and write its ``ingest_event``."""
        for f in self.findings:
            fields = dict(
                kind=f.kind, key_or_path=f.key_or_path, age_seconds=int(f.age.total_seconds()),
                action=f.action, dry_run=not self.delete,
            )
            if f.job_id is not None:
                log_job_event(f.job_id, "reconcile", logging.WARNING, **fields)
            else:
                log_event("ingest_reconcile", f.kind, logging.WARNING, **fields)
        if not self.findings:
            return
        with self.factory() as db:
            for f in self.findings:
                add_event(
                    db, f.job_id, "reconcile", at=self.now, check=f.kind, key_or_path=f.key_or_path,
                    age_seconds=int(f.age.total_seconds()), action=f.action, dry_run=not self.delete,
                )
            db.commit()
        log.info("reconcile: %d finding(s), %s", len(self.findings), "delete mode" if self.delete else "dry run")

    # --- S3 job prefixes + missing sources ---------------------------------------
    def check_job_prefixes_and_sources(self) -> None:
        by_job: dict[uuid.UUID, list] = {}
        keys: set[str] = set()
        for root in JOB_ROOTS:
            for obj in self.objects.list_objects(root):
                keys.add(obj.key)
                job_id = _job_id_of(obj.key)
                if job_id is not None:
                    by_job.setdefault(job_id, []).append(obj)
        with self.factory() as db:
            jobs = {j.id: j for j in db.scalars(select(IngestJob))}
        for job_id, objs in by_job.items():
            job = jobs.get(job_id)
            if job is not None and job.status not in SETTLED_STATUSES:
                continue
            if job is not None:
                settled_at = _aware(job.updated_at)
            else:  # no row to say when it settled: the newest object is the best evidence
                settled_at = max(_aware(o.last_modified) for o in objs)
            age = self.now - settled_at
            if age <= PREFIX_GRACE:
                continue
            prefix = next(r for r in JOB_ROOTS if objs[0].key.startswith(r)) + f"{job_id}/"
            action = _try_delete("orphan_job_prefix", lambda p=prefix: self.objects.delete_prefix(p), self.delete)
            self._add("orphan_job_prefix", prefix, job_id if job is not None else None, age, action)
        for job in jobs.values():
            if job.status in PENDING_STATUSES and job.source_key not in keys:
                self._add("missing_source", job.source_key, job.id, self.now - _aware(job.updated_at), REPORT_ONLY)

    # --- tmp/ -----------------------------------------------------------------
    def check_stale_temp(self) -> None:
        for obj in self.objects.list_objects("tmp/"):
            if obj.key.startswith("tmp/ingest/"):
                continue  # the legacy job layout: the prefix check owns it (a pending job still needs it)
            age = self.now - _aware(obj.last_modified)
            if age > TEMP_GRACE:
                action = _try_delete("stale_temp", lambda k=obj.key: self.objects.delete(k), self.delete)
                self._add("stale_temp", obj.key, None, age, action)

    # --- scratch ------------------------------------------------------------------
    def check_orphan_scratch(self) -> None:
        if not self.scratch.is_dir():
            return
        with self.factory() as db:
            jobs = {r.id: (r.status, r.updated_at) for r in db.execute(select(IngestJob.id, IngestJob.status, IngestJob.updated_at))}
        for folder in sorted(self.scratch.iterdir()):
            try:
                job_id = uuid.UUID(folder.name)
            except ValueError:
                continue
            if not folder.is_dir():
                continue
            known = jobs.get(job_id)
            if known is not None and known[0] in SCRATCH_KEEP_STATUSES:
                continue
            if known is not None:
                since = _aware(known[1])
            else:
                since = datetime.fromtimestamp(folder.stat().st_mtime, UTC)
            age = self.now - since
            if age <= SCRATCH_GRACE:
                continue
            action = _try_delete("orphan_scratch", lambda f=folder: shutil.rmtree(f), self.delete)
            self._add("orphan_scratch", str(folder), job_id if known is not None else None, age, action)

    # --- papers/ ------------------------------------------------------------------------
    def check_orphan_paper_images(self) -> None:
        with self.factory() as db:
            referenced = set(db.scalars(select(QuestionPage.image_key)))
        for obj in self.objects.list_objects("papers/"):
            if obj.key in referenced:
                continue
            age = self.now - _aware(obj.last_modified)
            if age > PAPER_IMAGE_GRACE:
                action = _try_delete("orphan_paper_image", lambda k=obj.key: self.objects.delete(k), self.delete)
                self._add("orphan_paper_image", obj.key, None, age, action)

    # --- abandoned uploads --------------------------------------------------------------------
    def check_abandoned_uploads(self) -> None:
        """An ``awaiting_upload`` job older than :data:`UPLOAD_GRACE`: the browser never called
        ``uploaded``. Cancelled, and any partial object removed, only in delete mode."""
        with self.factory() as db:
            jobs = db.scalars(select(IngestJob).where(IngestJob.status == "awaiting_upload")).all()
            for job in jobs:
                age = self.now - _aware(job.created_at)
                if age <= UPLOAD_GRACE:
                    continue
                key, prefix = job.source_key, None
                if self.delete:
                    prefix = cancel_job(job, db)
                    db.commit()
                    action = _try_delete("abandoned_upload", lambda p=prefix: self.objects.delete_prefix(p), True)
                    action = CANCELLED if action == DELETED else action
                else:
                    action = WOULD_CANCEL
                self._add("abandoned_upload", key, job.id, age, action)

    # --- stuck jobs ------------------------------------------------------------------------
    def check_stuck_jobs(self) -> None:
        """A queued/running job with no task holding a live lease and no activity for
        :data:`STUCK_AFTER`. Marked ``failed`` (reason ``stuck``) so it shows up and Retry works."""
        with self.factory() as db:
            jobs = db.scalars(select(IngestJob).where(IngestJob.status.in_(("queued", "running")))).all()
            for job in jobs:
                tasks = db.scalars(select(IngestTask).where(IngestTask.job_id == job.id)).all()
                if any(t.status == "running" and (_aware(t.lease_until) or self.now) > self.now for t in tasks):
                    continue
                last = max(
                    [_aware(job.updated_at)]
                    + [_aware(m) for t in tasks for m in (t.started_at, t.finished_at) if m is not None]
                )
                age = self.now - last
                if age <= STUCK_AFTER:
                    continue
                if self.delete:
                    reason = f"stuck: no live lease and no task progress for {int(age.total_seconds() // 3600)} h"
                    # Fail the tasks that cannot run on their own, so Retry has something to reopen.
                    for t in tasks:
                        if t.status in ("ready", "running"):
                            t.status, t.reason, t.error, t.lease_until = "failed", "stuck", reason, None
                    job.status, job.error = "failed", reason
                    db.commit()
                self._add("stuck_job", job.source_key, job.id, age, MARKED_FAILED if self.delete else WOULD_MARK_FAILED)
