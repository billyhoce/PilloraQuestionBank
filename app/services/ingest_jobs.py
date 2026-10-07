"""Auto-import jobs: create, list and cancel. Processing lives in the worker."""

import hashlib
import logging
import uuid
from typing import Any

import fitz  # PyMuPDF
from sqlalchemy.orm import Session

from app.models.orm import IngestJob, IngestTask
from app.storage.object_store import ObjectStore

log = logging.getLogger(__name__)


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
