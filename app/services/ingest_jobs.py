"""Auto-import jobs: create, list, cancel, retry and progress. Processing lives in the worker."""

import logging
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.logger import log_job_event
from app.services.ingest_events import add_event
from app.models.orm import IngestJob, IngestTask, WorkerHeartbeat
from app.storage.object_store import ObjectStore
from app.worker.store import SqlStore

log = logging.getLogger(__name__)

# The worker touches its heartbeat every 30 s (app.worker.main); older than this and the API
# reports it offline. The one place the threshold lives: the UI only reads ``worker_alive``.
WORKER_STALE_SECONDS = 90
# Job states retry does not apply to (the API owns them; same set as cancel refuses).
_NOT_RETRYABLE = ("awaiting_upload", "confirmed", "cancelled", "expired")
_SETTLED = ("done", "skipped")


class InvalidPdfError(ValueError):
    pass


class JobNotCancellableError(Exception):
    def __init__(self, status: str):
        super().__init__(status)
        self.status = status


def source_key_for(job_id: uuid.UUID) -> str:
    """Where a NEW job's source PDF goes: ``ingest/`` has no lifecycle rule, unlike ``tmp/``."""
    return f"ingest/{job_id}/source.pdf"


def job_prefix(source_key: str) -> str:
    """The job's S3 prefix (trailing slash), derived from its stored ``source_key``.

    Never rebuilt from the job id: jobs created before the move still live under the legacy
    ``tmp/ingest/{job_id}/`` and their stored key says so."""
    return source_key.rsplit("/", 1)[0] + "/"


MAX_UPLOAD_BYTES = 100 * 1024 * 1024
UPLOAD_TTL_SECONDS = 15 * 60
PDF_CONTENT_TYPE = "application/pdf"


class UploadError(Exception):
    """The uploaded object is not what ``create_upload`` asked for. ``status`` is the HTTP status."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def create_upload(
    filename: str,
    size: int,
    admin: Any,
    db: Session,
    store: ObjectStore,
) -> tuple[IngestJob, dict]:
    """Create the job in ``awaiting_upload`` (no task yet) and presign the browser's S3 POST.

    ``size`` is the file's declared size; the policy itself allows 1 B to :data:`MAX_UPLOAD_BYTES`."""
    if not 1 <= size <= MAX_UPLOAD_BYTES:
        raise UploadError(422, f"A PDF must be between 1 byte and {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
    job_id = uuid.uuid4()
    key = source_key_for(job_id)
    post = store.presign_post(key, PDF_CONTENT_TYPE, 1, MAX_UPLOAD_BYTES, UPLOAD_TTL_SECONDS)
    job = IngestJob(
        id=job_id, created_by=admin.id, filename=filename, source_key=key, status="awaiting_upload",
    )
    db.add(job)
    db.flush()
    return job, post


def finish_upload(job: IngestJob, admin: Any, db: Session, store: ObjectStore) -> IngestJob:
    """The browser says the S3 POST finished: check the object, queue the job.

    Idempotent-safe: only an ``awaiting_upload`` job proceeds (anything else is a 409), and the
    status flip is a conditional UPDATE so two concurrent calls cannot both insert the task."""
    if job.status != "awaiting_upload":
        raise UploadError(409, f"A {job.status} job is not awaiting an upload")
    head = store.head(job.source_key)
    if head is None:
        raise UploadError(409, "The upload has not reached storage")
    if not 1 <= head.size <= MAX_UPLOAD_BYTES:
        raise UploadError(422, "The uploaded file has an invalid size")
    if head.content_type != PDF_CONTENT_TYPE:
        raise UploadError(422, "Only PDF files are accepted")
    claimed = db.execute(
        update(IngestJob)
        .where(IngestJob.id == job.id, IngestJob.status == "awaiting_upload")
        .values(status="queued")
    ).rowcount
    if not claimed:
        raise UploadError(409, "The upload was already finished")
    db.add(IngestTask(job_id=job.id, section=None, stage="register", status="ready"))
    db.flush()
    db.refresh(job)
    add_event(
        db, job.id, "created", actor_user_id=admin.id, filename=job.filename, size=head.size,
    )
    db.flush()
    log_job_event(job.id, "created", filename=job.filename, size=head.size, user_id=admin.id)
    return job


def record_filename_metadata(job: IngestJob, db: Session, extract_metadata) -> dict:
    """Run the filename extraction for ``job`` and store it in ``report["filename_metadata"]``.

    Called by the worker's ``register`` task (not by the POST, which must return fast). The
    review/confirm step reads the result to pre-fill the metadata sidebar. Any failure falls back
    to empty metadata so the job still proceeds. ``extract_metadata`` is injected (see
    ``app.deps.get_metadata_extractor``) so tests need no Claude call.
    """
    try:
        metadata = extract_metadata(job.filename, db)
    except Exception:
        log.exception("filename metadata extraction failed for job %s", job.id)
        metadata = {}
    # The extraction adds its cost to ``report["cost"]`` from another session; re-read so the
    # write below does not clobber it.
    db.refresh(job)
    # Reassign rather than mutate: JSON columns are not change-tracked in place.
    job.report = {**(job.report or {}), "filename_metadata": metadata}
    db.flush()
    return metadata


def cancel_job(job: IngestJob, db: Session | None = None, actor: Any = None) -> str:
    """Mark the job cancelled; returns the S3 prefix the caller deletes after commit."""
    if job.status in ("confirmed", "cancelled", "expired"):
        raise JobNotCancellableError(job.status)
    previous = job.status
    job.status = "cancelled"
    if db is not None:
        add_event(db, job.id, "cancelled", actor_user_id=getattr(actor, "id", None), previous_status=previous)
    log_job_event(job.id, "cancelled", previous_status=previous)
    return job_prefix(job.source_key)


class JobNotRetryableError(Exception):
    def __init__(self, status: str, reason: str | None = None):
        super().__init__(status)
        self.status = status
        self.reason = reason or f"A {status} job cannot be retried"


def heartbeat_age_s(db: Session, now: datetime | None = None) -> float | None:
    """Seconds since the worker last touched its heartbeat; ``None`` if it never has."""
    row = db.get(WorkerHeartbeat, 1)
    if row is None:
        return None
    seen = row.seen_at if row.seen_at.tzinfo else row.seen_at.replace(tzinfo=UTC)
    return max(0.0, ((now or datetime.now(UTC)) - seen).total_seconds())


def worker_state(db: Session) -> dict:
    age = heartbeat_age_s(db)
    return {
        "worker_alive": age is not None and age <= WORKER_STALE_SECONDS,
        "heartbeat_age_s": None if age is None else round(age),
    }


def job_progress(job: IngestJob) -> dict:
    """Progress of a job from its tasks.

    ``done``/``total`` count tasks (``done`` = done or skipped; ``total`` grows as the job's
    sections fan out). ``stage`` is the stage of the running task, else of the task that
    finished most recently, else ``None`` before anything has started."""
    tasks = list(job.tasks)
    running = next((t for t in tasks if t.status == "running"), None)
    if running is not None:
        stage = running.stage
    else:
        finished = [t for t in tasks if t.finished_at is not None]
        # Naive (SQLite) and aware (Postgres) datetimes never mix within one backend.
        stage = max(finished, key=lambda t: (t.finished_at, t.id)).stage if finished else None
    return {
        "stage": stage,
        "tasks_done": sum(1 for t in tasks if t.status in _SETTLED),
        "tasks_total": len(tasks),
        "warnings_count": sum(len(t.warnings or ()) for t in tasks),
        "needs_review": any(t.needs_review for t in tasks),
    }


def retry_job(job: IngestJob, db: Session, actor: Any = None) -> int:
    """Return the job's failed and blocked tasks, and everything downstream of them, to ``ready``
    by running the pipeline's own ``Runner.retry`` over the ``ingest_task`` rows; the job's
    status is re-derived so the worker picks it up. Returns how many tasks were reopened."""
    if job.status in _NOT_RETRYABLE:
        raise JobNotRetryableError(job.status)
    if (job.report or {}).get("review_outcome"):
        # A retry can regenerate the proposal, which would orphan the papers already decided.
        raise JobNotRetryableError(
            job.status, "Papers of this job are already confirmed or skipped; it cannot be retried"
        )
    from pipeline.registry import default_registry
    from pipeline.runner import Runner

    store = _RequestStore(db)

    def no_job_dir(_job_id: str) -> Path:
        raise RuntimeError("the API never runs a stage")

    db.flush()
    reopened = Runner(store, default_registry(), no_job_dir).retry(str(job.id))
    db.expire(job)  # the store updated the rows with bulk UPDATEs
    add_event(
        db, job.id, "retry", actor_user_id=getattr(actor, "id", None),
        reopened=len(reopened), tasks=[f"{t.stage}:{t.section or '-'}" for t in reopened],
    )
    db.commit()  # the reopen committed in the store; the event is its own small transaction
    log_job_event(job.id, "retry", reopened=len(reopened), tasks=[f"{t.stage}:{t.section or '-'}" for t in reopened])
    return len(reopened)


class _RequestStore(SqlStore):
    """``SqlStore`` on the request's own session, so a retry shares its transaction (and a
    test's savepoint) rather than opening and closing sessions of its own."""

    def __init__(self, db: Session) -> None:
        super().__init__(lambda: db, Path("."))
        self._db = db

    @contextmanager
    def _session(self):
        yield self._db
