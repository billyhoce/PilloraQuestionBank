"""``ingest_paper``: the queryable record of each paper an ingest job proposed.

Source of truth: the job's ``proposal`` / ``proposal_edited`` (what the paper holds) and
``report["review_outcome"]`` (what the admin decided) stay authoritative for the review flow, which
reads only them. ``ingest_paper`` is written alongside them, in the same transaction as each change,
so the two never disagree, and it is what matching queries read. See docs/DATA_MODEL.md.
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import IngestJob, IngestPaper

METADATA_FIELDS = ("school_id", "year", "level_id", "subject_id", "exam_type_id", "stream_id", "paper_number")


def _proposal_papers(job: IngestJob) -> list[tuple[str, dict]]:
    from app.services.ingest_confirm import paper_key  # confirm imports this module's siblings

    proposal = job.proposal if job.proposal is not None else job.proposal_edited
    return [(paper_key(p, i), p) for i, p in enumerate((proposal or {}).get("papers", []))]


def _clean(metadata: dict | None) -> dict[str, Any]:
    """The seven fields of ``metadata``; empty strings and missing values become None."""
    out: dict[str, Any] = {}
    for field in METADATA_FIELDS:
        value = (metadata or {}).get(field)
        out[field] = None if value in ("", None) else value
    if out["year"] is not None:
        try:
            out["year"] = int(out["year"])
        except (TypeError, ValueError):
            out["year"] = None
    if out["paper_number"] is not None:
        out["paper_number"] = str(out["paper_number"])
    return out


def sync_job_papers(db: Session, job: IngestJob) -> list[IngestPaper]:
    """Upsert one row per proposal paper (on ``(job_id, paper_key)``), with its role and the
    metadata the worker read: ``report["paper_metadata"][key]`` (source ``cover``), else the old
    job-wide ``filename_metadata`` (source ``filename``). A re-run keeps the row and its status,
    matches and any admin-edited metadata; it refreshes the role and, while pending and not
    admin-edited, the cover metadata. Does not commit."""
    report = job.report or {}
    per_paper = report.get("paper_metadata") or {}
    existing = {r.paper_key: r for r in db.scalars(select(IngestPaper).where(IngestPaper.job_id == job.id))}
    rows = []
    for key, paper in _proposal_papers(job):
        role = "answer_only" if paper.get("role") == "answer_only" else "question"
        row = existing.get(key)
        if row is None:
            if key in per_paper:
                meta, source = _clean(per_paper[key]), "cover"
            elif report.get("filename_metadata"):
                meta, source = _clean(report["filename_metadata"]), "filename"
            else:
                meta, source = _clean(None), None
            row = IngestPaper(job_id=job.id, paper_key=key, role=role, status="pending", metadata_source=source, **meta)
            db.add(row)
        else:
            row.role = role
            if row.status == "pending" and row.metadata_source != "admin" and key in per_paper:
                for f, v in _clean(per_paper[key]).items():  # a re-run's fresher cover reading
                    setattr(row, f, v)
                row.metadata_source = "cover"
        rows.append(row)
    db.flush()
    return rows


def get_row(db: Session, job: IngestJob, key: str) -> IngestPaper | None:
    return db.scalar(select(IngestPaper).where(IngestPaper.job_id == job.id, IngestPaper.paper_key == key))


def _row_or_sync(db: Session, job: IngestJob, key: str) -> IngestPaper | None:
    row = get_row(db, job, key)
    if row is None:  # a job from before the table (and not backfilled): create its rows lazily
        sync_job_papers(db, job)
        row = get_row(db, job, key)
    return row


def set_metadata(db: Session, job: IngestJob, key: str, metadata: dict, source: str = "admin") -> IngestPaper | None:
    """Store ``metadata`` (the seven fields) on the paper's row. ``source`` becomes ``admin`` only
    if a value actually changed. Does not commit. Returns None for an unknown key."""
    row = _row_or_sync(db, job, key)
    if row is None:
        return None
    new = _clean(metadata)
    if any(getattr(row, f) != v for f, v in new.items()):
        for f, v in new.items():
            setattr(row, f, v)
        row.metadata_source = source
    return row


def set_status(db: Session, job: IngestJob, key: str, status: str, paper_id: int | None = None) -> None:
    """Record the admin's outcome for a paper. Does not commit: call it inside the outcome's own
    transaction."""
    row = _row_or_sync(db, job, key)
    if row is None:
        return
    row.status = status
    if paper_id is not None:
        row.paper_id = paper_id
