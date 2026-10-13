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
    if status != "pending":
        row.match_status = row.proposed_paper_id = row.match_note = None  # a settled paper has no proposal


# --- matching an answer-only paper to a question paper (manual, #82) -------------------------


class MatchError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _first_question_preview(job: IngestJob, key: str, store) -> dict | None:
    """The first question of proposal paper ``key`` as ``{url, page, rect}``: its review page image,
    the page's sizes and the question's first rectangle (PDF points), or None if it has none."""
    from app.services.ingest_jobs import job_prefix
    from app.services.ingest_review import REVIEW_URL_TTL, pixel_size

    for k, paper in _proposal_papers(job):
        if k != key:
            continue
        pages = {p["page"]: p for p in paper.get("pages", [])}
        for q in paper.get("questions", []):
            for rect in q.get("question_rects") or []:
                page = pages.get(rect["page"])
                if page is None or not page.get("image"):
                    continue
                width_px, height_px = pixel_size(page["width_pt"], page["height_pt"])
                return {
                    "number": q.get("number"),
                    "url": store.presign(job_prefix(job.source_key) + page["image"], REVIEW_URL_TTL),
                    "page": {
                        "page": page["page"], "width_pt": page["width_pt"], "height_pt": page["height_pt"],
                        "width_px": width_px, "height_px": height_px,
                    },
                    "rect": {n: rect[n] for n in ("page", "x0", "y0", "x1", "y1")},
                }
    return None


def _metadata_of(row: IngestPaper) -> dict[str, Any]:
    return {f: getattr(row, f) for f in METADATA_FIELDS}


def pending_question_papers(
    db: Session, store, filters: dict[str, Any], exclude_job_id=None
) -> list[dict]:
    """Pending question papers of ``review_ready`` jobs (other than ``exclude_job_id``) whose
    metadata equals every given filter (``filters`` holds only the fields to constrain), newest
    job first, each with what the match panel needs to preview its first question."""
    q = (
        select(IngestPaper, IngestJob)
        .join(IngestJob, IngestJob.id == IngestPaper.job_id)
        .where(IngestPaper.role == "question", IngestPaper.status == "pending", IngestJob.status == "review_ready")
    )
    if exclude_job_id is not None:
        q = q.where(IngestPaper.job_id != exclude_job_id)
    for field, value in filters.items():
        q = q.where(getattr(IngestPaper, field) == value)
    out = []
    for row, job in db.execute(q.order_by(IngestJob.created_at.desc(), IngestPaper.id)):
        out.append({
            "ingest_paper_id": row.id,
            "job_id": str(job.id),
            "filename": job.filename,
            "paper_key": row.paper_key,
            "metadata": _metadata_of(row),
            "matched_ingest_paper_id": row.matched_ingest_paper_id,
            "preview": _first_question_preview(job, row.paper_key, store),
        })
    return out


def _clear_link(row: IngestPaper, decline: bool = False) -> None:
    """Break ``row``'s link, on both sides. ``decline`` marks both ``unlinked`` so automatic
    matching does not re-make it (until a metadata edit resets that)."""
    other = row.matched_ingest_paper
    row.matched_ingest_paper_id = None
    if other is not None and other.matched_ingest_paper_id == row.id:
        other.matched_ingest_paper_id = None
    for r in (row, other):
        if r is not None:
            r.match_status = "unlinked" if decline else None
            r.match_note = None
            r.proposed_paper_id = None


def link_papers(db: Session, job: IngestJob, key: str, other_id: int) -> IngestPaper:
    """Link answer-only paper ``key`` of ``job`` to the pending question ``ingest_paper`` ``other_id``
    (of another review-ready job), by setting ``matched_ingest_paper_id`` on both rows. Replaces any
    earlier link of either row. Does not commit."""
    row = _row_or_sync(db, job, key)
    if row is None:
        raise MatchError(404, f"This job has no paper {key!r}")
    if row.status != "pending":
        raise MatchError(409, f"Paper {key!r} was already {row.status}")
    if row.role != "answer_only":
        raise MatchError(422, f"Paper {key!r} is not an answer-only paper")
    other = db.get(IngestPaper, other_id)
    if other is None:
        raise MatchError(404, "That question paper does not exist")
    other_job = db.get(IngestJob, other.job_id)
    if other.job_id == job.id or other.role != "question" or other.status != "pending" or other_job.status != "review_ready":
        raise MatchError(422, "That is not a pending question paper of another job")
    for r in (row, other):
        if r.matched_ingest_paper_id is not None:
            _clear_link(r)
    row.matched_ingest_paper_id = other.id
    other.matched_ingest_paper_id = row.id
    for r in (row, other):  # an admin's link: no automatic status
        r.match_status = r.match_note = r.proposed_paper_id = None
    db.flush()
    return row


def unlink_paper(db: Session, job: IngestJob, key: str) -> None:
    """Remove the link of paper ``key`` (and its partner's side). Does not commit."""
    row = _row_or_sync(db, job, key)
    if row is None:
        raise MatchError(404, f"This job has no paper {key!r}")
    _clear_link(row, decline=True)
    db.flush()
    from app.services.ingest_matching import match_row  # imports this module's constants

    match_row(db, row)  # back to what the bank offers
    db.flush()


def paper_links(db: Session, job: IngestJob) -> dict[str, dict]:
    """The job's linked papers by paper key: the partner's ingest paper id, job id, filename and key."""
    out = {}
    rows = db.scalars(
        select(IngestPaper).where(IngestPaper.job_id == job.id, IngestPaper.matched_ingest_paper_id.isnot(None))
    )
    for row in rows:
        other = row.matched_ingest_paper
        if other is None:
            continue
        other_job = db.get(IngestJob, other.job_id)
        out[row.paper_key] = {
            "ingest_paper_id": other.id, "job_id": str(other.job_id),
            "filename": other_job.filename if other_job else None, "paper_key": other.paper_key,
        }
    return out
