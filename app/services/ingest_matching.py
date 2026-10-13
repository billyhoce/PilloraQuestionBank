"""Automatic matching of a pending answer-only paper to a confirmed paper (#83).

Rules, for a pending ``answer_only`` ``ingest_paper`` that is not linked to another pending paper
(a link the admin set always wins and is never touched):

* All seven key fields known and exactly one confirmed ``paper`` has that key -> ``proposed``
  (``proposed_paper_id``); the admin accepts with one click.
* All seven known and several papers share the key (``paper`` has no unique index, so duplicates can
  exist) -> ``manual`` ("N papers have this key").
* No exact match, or some field unknown: papers sharing ``school_id``, ``year`` and ``subject_id``
  with the row are *partial* candidates -> ``manual`` if any ("partial: ...").
* Otherwise NULL: nothing to do.

``paper_number`` is not normalised in the bank, so it is compared after trimming and case-folding
only. Nothing here commits; callers run it inside their own transaction.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.orm import IngestJob, IngestPaper, Paper
from app.services.ingest_papers import METADATA_FIELDS

PARTIAL_FIELDS = ("school_id", "year", "subject_id")
_LABELS = {
    "school_id": "school", "year": "year", "level_id": "level", "subject_id": "subject",
    "exam_type_id": "exam type", "stream_id": "stream", "paper_number": "paper number",
}


def _norm(value) -> str:
    return str(value).strip().lower()


def _paper_number_clause(value):
    return func.lower(func.trim(Paper.paper_number)) == _norm(value)


def exact_candidates(db: Session, row: IngestPaper) -> list[Paper]:
    q = select(Paper)
    for f in METADATA_FIELDS:
        value = getattr(row, f)
        q = q.where(_paper_number_clause(value) if f == "paper_number" else getattr(Paper, f) == value)
    return list(db.scalars(q.order_by(Paper.id)))


def partial_candidates(db: Session, row: IngestPaper) -> list[Paper]:
    if any(getattr(row, f) is None for f in PARTIAL_FIELDS):
        return []
    q = select(Paper)
    for f in PARTIAL_FIELDS:
        q = q.where(getattr(Paper, f) == getattr(row, f))
    return list(db.scalars(q.order_by(Paper.id)))


def _set(row: IngestPaper, status, paper_id=None, note=None) -> None:
    row.match_status, row.proposed_paper_id, row.match_note = status, paper_id, note


def match_row(db: Session, row: IngestPaper) -> None:
    """(Re)compute the automatic match of ``row``. A no-op unless it is a pending answer-only paper
    with no pending-paper link; a settled paper's proposal is cleared."""
    if row.status != "pending":
        _set(row, None)
        return
    if row.role != "answer_only" or row.matched_ingest_paper_id is not None:
        return
    unknown = [f for f in METADATA_FIELDS if getattr(row, f) is None]
    if not unknown:
        exact = exact_candidates(db, row)
        if len(exact) == 1:
            _set(row, "proposed", exact[0].id)
            return
        if len(exact) > 1:
            _set(row, "manual", None, f"{len(exact)} papers have this key")
            return
    partial = partial_candidates(db, row)
    if not partial:
        _set(row, None)
    elif unknown:
        _set(row, "manual", None, "partial: unknown " + ", ".join(_LABELS[f] for f in unknown))
    else:
        differ = [
            _LABELS[f] for f in METADATA_FIELDS
            if f not in PARTIAL_FIELDS and all(
                (_norm(getattr(row, f)) != _norm(getattr(p, f))) if f == "paper_number" else getattr(row, f) != getattr(p, f)
                for p in partial
            )
        ]
        _set(row, "manual", None, "partial: " + (", ".join(differ) or "key") + " differ")


def match_job(db: Session, job: IngestJob) -> None:
    """Match every pending answer-only paper of ``job``."""
    for row in db.scalars(select(IngestPaper).where(IngestPaper.job_id == job.id)):
        if row.role == "answer_only":
            match_row(db, row)


def match_for_new_paper(db: Session, paper: Paper) -> None:
    """A paper was just created: re-match the pending answer-only papers that share its school, year
    and subject (the partial key, so exact and partial candidates are both covered), in review-ready
    jobs. Never raises: matching is a convenience and must not fail the confirm. Runs in a savepoint
    so a failure leaves the caller's transaction intact."""
    try:
        with db.begin_nested():
            rows = db.scalars(
                select(IngestPaper)
                .join(IngestJob, IngestJob.id == IngestPaper.job_id)
                .where(
                    IngestPaper.role == "answer_only", IngestPaper.status == "pending",
                    IngestJob.status == "review_ready",
                    IngestPaper.school_id == paper.school_id, IngestPaper.year == paper.year,
                    IngestPaper.subject_id == paper.subject_id,
                )
            ).all()
            for row in rows:
                match_row(db, row)
    except Exception:
        from app.logger import log
        log.warning("ingest_matching/match_for_new_paper failed paper=%s", getattr(paper, "id", None), exc_info=True)


def match_info(db: Session, job: IngestJob) -> dict[str, dict]:
    """The job's automatic matches by paper key: ``{status, note, paper}`` where ``paper`` (for a
    proposal whose paper still exists) describes the proposed paper."""
    out = {}
    rows = db.scalars(
        select(IngestPaper).where(
            IngestPaper.job_id == job.id, IngestPaper.match_status.isnot(None), IngestPaper.status == "pending",
        )
    )
    for row in rows:
        if row.matched_ingest_paper_id is not None:
            continue  # a pending-paper link takes precedence
        info = {"status": row.match_status, "note": row.match_note, "paper": None}
        if row.match_status == "proposed":
            paper = db.get(Paper, row.proposed_paper_id) if row.proposed_paper_id else None
            if paper is None:
                continue
            info["paper"] = {
                "id": paper.id, "school": paper.school.name, "year": paper.year, "level": paper.level.name,
                "subject": paper.subject.name, "exam_type": paper.exam_type.name,
                "stream": paper.stream.name, "paper_number": paper.paper_number,
            }
        out[row.paper_key] = info
    return out
