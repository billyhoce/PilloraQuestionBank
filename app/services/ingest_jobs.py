"""Auto-import jobs: create, list, cancel, retry and progress. Processing lives in the worker."""

import hashlib
import logging
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from sqlalchemy.orm import Session

from app.models.orm import IngestJob, IngestTask, WorkerHeartbeat
from app.storage.object_store import ObjectStore
from app.worker.store import SqlStore

log = logging.getLogger(__name__)

# The worker touches its heartbeat every 30 s (app.worker.main); older than this and the API
# reports it offline. The one place the threshold lives: the UI only reads ``worker_alive``.
WORKER_STALE_SECONDS = 90
# Job states retry does not apply to (the API owns them; same set as cancel refuses).
_NOT_RETRYABLE = ("confirmed", "cancelled", "expired")
_SETTLED = ("done", "skipped")


class InvalidPdfError(ValueError):
    pass


class JobNotCancellableError(Exception):
    def __init__(self, status: str):
        super().__init__(status)
        self.status = status


def source_key_for(job_id: uuid.UUID) -> str:
    return f"tmp/ingest/{job_id}/source.pdf"


def job_prefix(job_id: uuid.UUID) -> str:
    return f"tmp/ingest/{job_id}/"


def inspect_pdf(pdf_bytes: bytes) -> int:
    """Return the page count; raise InvalidPdfError if the bytes are not a usable PDF.
    Only the page tree is read — nothing is rendered."""
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            if doc.needs_pass:
                raise InvalidPdfError("The PDF is password protected")
            n = doc.page_count
    except InvalidPdfError:
        raise
    except Exception as e:
        raise InvalidPdfError("The file is not a readable PDF") from e
    if n < 1:
        raise InvalidPdfError("The PDF has no pages")
    return n


def create_job(
    pdf_bytes: bytes,
    filename: str,
    admin: Any,
    db: Session,
    store: ObjectStore,
) -> IngestJob:
    page_count = inspect_pdf(pdf_bytes)
    job_id = uuid.uuid4()
    key = source_key_for(job_id)

    store.put(key, pdf_bytes, "application/pdf")
    try:
        job = IngestJob(
            id=job_id,
            created_by=admin.id,
            filename=filename,
            source_key=key,
            sha256=hashlib.sha256(pdf_bytes).hexdigest(),
            page_count=page_count,
            status="queued",
        )
        job.tasks.append(IngestTask(section=None, stage="register", status="ready"))
        db.add(job)
        db.flush()
    except Exception:
        try:
            store.delete_prefix(job_prefix(job_id))
        except Exception:
            pass
        raise
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
    # Reassign rather than mutate: JSON columns are not change-tracked in place.
    job.report = {**(job.report or {}), "filename_metadata": metadata}
    db.flush()
    return metadata


def cancel_job(job: IngestJob) -> str:
    """Mark the job cancelled; returns the S3 prefix the caller deletes after commit."""
    if job.status in ("confirmed", "cancelled", "expired"):
        raise JobNotCancellableError(job.status)
    job.status = "cancelled"
    return job_prefix(job.id)


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


def retry_job(job: IngestJob, db: Session) -> int:
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
