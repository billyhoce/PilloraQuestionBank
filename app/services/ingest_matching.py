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

Pending <-> pending (#84): when all seven fields are known and *no* confirmed paper has the key, the
row is auto-linked to the one pending ``question`` ``ingest_paper`` with the exact key, of another
``review_ready`` job or of its own job (#90: a booklet whose papers the pipeline did not pair)
(``matched_ingest_paper_id`` on both rows, ``match_status`` ``auto``, ``match_note``
"auto-linked"); several such papers -> ``manual``. A single confirmed-paper match wins over this
(the #83 proposal). The same runs from the question side: a question paper (on ``match_job`` or a
metadata edit) tries the pending answer-only papers with its key, its own job's included. An *auto* link is recomputed from scratch on every re-evaluation
(metadata edit, new job, new paper), so it follows the data; a link the admin set (``match_status``
NULL) is never touched.

Rejections (#88): Unmatch on a linked pair, or "Not this one" on a proposed confirmed paper, records
the pair in ``ingest_match_rejection``. Every rule above skips a rejected pair (a pending pair counts
in either direction), so that pair is never proposed again while both papers stay free to match
something else.

New schools (#87): a paper whose school the admin typed as new has no ``school_id`` but a
``new_school_name``; its school counts as known. Two pending papers have the same school if their
``school_id``s are equal, or if neither has one and their ``new_school_name``s are equal (trimmed,
case-folded). A confirmed paper always has an id, so a new-school paper only matches pending papers.

Answers are all or none (#89): a confirmed paper whose every question already has an answer page
(coverage ``all``) is never a candidate, exact or partial; a partly answered one still is.

``paper_number`` is not normalised in the bank, so it is compared after trimming and case-folding
only. Nothing here commits; callers run it inside their own transaction.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.orm import IngestJob, IngestMatchRejection, IngestPaper, Paper
from app.services.answer_coverage import ALL, bank_coverage
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


def unknown_fields(row: IngestPaper) -> list[str]:
    """The key fields ``row`` does not know yet (a new school's name counts as knowing the school)."""
    return [
        f for f in METADATA_FIELDS
        if getattr(row, f) is None and not (f == "school_id" and row.new_school_name)
    ]


def _ip_school_clause(row: IngestPaper):
    """Pending papers with ``row``'s school: the same id, or both new with the same name."""
    if row.school_id is not None:
        return IngestPaper.school_id == row.school_id
    return IngestPaper.school_id.is_(None) & (func.lower(func.trim(IngestPaper.new_school_name)) == _norm(row.new_school_name))


def _ip_key_clauses(q, row: IngestPaper):
    for f in METADATA_FIELDS:
        value = getattr(row, f)
        if f == "school_id":
            q = q.where(_ip_school_clause(row))
        else:
            q = q.where(_ip_number_clause(value) if f == "paper_number" else getattr(IngestPaper, f) == value)
    return q


def rejected_paper_ids(db: Session, row: IngestPaper) -> set[int]:
    """The confirmed papers the admin turned down for ``row``."""
    return set(db.scalars(
        select(IngestMatchRejection.rejected_paper_id).where(
            IngestMatchRejection.ingest_paper_id == row.id, IngestMatchRejection.rejected_paper_id.isnot(None),
        )
    ))


def rejected_ingest_ids(db: Session, row: IngestPaper) -> set[int]:
    """The pending papers the admin turned down as ``row``'s partner, recorded from either side."""
    R = IngestMatchRejection
    pairs = db.execute(
        select(R.ingest_paper_id, R.rejected_ingest_paper_id).where(
            R.rejected_ingest_paper_id.isnot(None), (R.ingest_paper_id == row.id) | (R.rejected_ingest_paper_id == row.id),
        )
    )
    return {b if a == row.id else a for a, b in pairs}


def reject(db: Session, row: IngestPaper, *, other: IngestPaper | None = None, paper_id: int | None = None) -> None:
    """Record that ``row`` must not be matched to ``other`` (a pending paper) or ``paper_id`` (a
    confirmed paper) again. Idempotent."""
    if other is not None:
        if other.id not in rejected_ingest_ids(db, row):
            db.add(IngestMatchRejection(ingest_paper_id=row.id, rejected_ingest_paper_id=other.id))
    elif paper_id is not None and paper_id not in rejected_paper_ids(db, row):
        db.add(IngestMatchRejection(ingest_paper_id=row.id, rejected_paper_id=paper_id))
    db.flush()


def _without(q, column, ids):
    return q.where(column.notin_(ids)) if ids else q


def _open_to_answers(db: Session, papers: list[Paper]) -> list[Paper]:
    """``papers`` without those that already have answers on every question."""
    coverage = bank_coverage(db, (p.id for p in papers))
    return [p for p in papers if coverage[p.id] != ALL]


def exact_candidates(db: Session, row: IngestPaper) -> list[Paper]:
    if row.school_id is None:  # a new school: no confirmed paper can have it
        return []
    q = _without(select(Paper), Paper.id, rejected_paper_ids(db, row))
    for f in METADATA_FIELDS:
        value = getattr(row, f)
        q = q.where(_paper_number_clause(value) if f == "paper_number" else getattr(Paper, f) == value)
    return _open_to_answers(db, list(db.scalars(q.order_by(Paper.id))))


def partial_candidates(db: Session, row: IngestPaper) -> list[Paper]:
    if any(getattr(row, f) is None for f in PARTIAL_FIELDS):
        return []
    q = _without(select(Paper), Paper.id, rejected_paper_ids(db, row))
    for f in PARTIAL_FIELDS:
        q = q.where(getattr(Paper, f) == getattr(row, f))
    return _open_to_answers(db, list(db.scalars(q.order_by(Paper.id))))


def _pending_partners(db: Session, row: IngestPaper, role: str) -> list[IngestPaper]:
    """Unlinked pending ``role`` papers with ``row``'s exact key, bar those rejected as its partner:
    of other ``review_ready`` jobs, or of ``row``'s own job (#90), whose status does not matter
    because ``report`` matches a booklet's papers before the job turns ``review_ready``."""
    q = (
        select(IngestPaper)
        .join(IngestJob, IngestJob.id == IngestPaper.job_id)
        .where(
            IngestPaper.role == role, IngestPaper.status == "pending", IngestPaper.id != row.id,
            IngestPaper.matched_ingest_paper_id.is_(None),
            (IngestJob.status == "review_ready") | (IngestPaper.job_id == row.job_id),
        )
    )
    q = _ip_key_clauses(_without(q, IngestPaper.id, rejected_ingest_ids(db, row)), row)
    return list(db.scalars(q.order_by(IngestPaper.id)))


def pending_question_candidates(db: Session, row: IngestPaper) -> list[IngestPaper]:
    """The pending question papers answer-only paper ``row`` could be auto-linked to."""
    return _pending_partners(db, row, "question")


def _ip_number_clause(value):
    return func.lower(func.trim(IngestPaper.paper_number)) == _norm(value)


def _break_link(row: IngestPaper) -> None:
    other = row.matched_ingest_paper
    row.matched_ingest_paper_id = None
    if other is not None and other.matched_ingest_paper_id == row.id:
        other.matched_ingest_paper_id = None
    for r in (row, other):
        if r is not None:
            r.answer_map = None  # a mapping belongs to one pair (#92)
            if r.match_status == "auto":
                r.match_status = r.match_note = None


def _set(row: IngestPaper, status, paper_id=None, note=None) -> None:
    row.match_status, row.proposed_paper_id, row.match_note = status, paper_id, note


def match_row(db: Session, row: IngestPaper) -> None:
    """(Re)compute the automatic match of ``row`` (see the module doc). A settled paper's proposal is
    cleared; an admin's link is left alone; an auto link is dropped and re-made if it still holds,
    keeping the pair's answer mapping when it is re-made with the same partner (#92)."""
    partner = kept_map = None
    if row.status == "pending" and row.matched_ingest_paper_id is not None and row.match_status == "auto":
        partner = row.matched_ingest_paper
        kept_map = (row if row.role == "answer_only" else partner).answer_map
        _break_link(row)
    _match(db, row)
    if partner is not None and row.matched_ingest_paper_id == partner.id:
        (row if row.role == "answer_only" else partner).answer_map = kept_map
    elif partner is not None and partner.status == "pending" and partner.matched_ingest_paper_id is None:
        _match(db, partner)  # freed: it may fit another paper


def _match(db: Session, row: IngestPaper) -> None:
    if row.status != "pending":
        _set(row, None)
        return
    if row.matched_ingest_paper_id is not None:
        return
    if row.role == "question":
        candidates = _answer_candidates(db, row)
        if not candidates and row.match_status == "manual":
            _set(row, None)  # an earlier ambiguity that no longer holds
        if len(candidates) == 1:
            _match(db, candidates[0])
        elif len(candidates) > 1:
            note = f"{len(candidates)} pending answer papers have this key"
            _set(row, "manual", None, note)
            for c in candidates:
                _set(c, "manual", None, note)
        return
    if row.role != "answer_only":
        return
    unknown = unknown_fields(row)
    if not unknown:
        exact = exact_candidates(db, row)
        if len(exact) == 1:
            _set(row, "proposed", exact[0].id)
            return
        if len(exact) > 1:
            _set(row, "manual", None, f"{len(exact)} papers have this key")
            return
        pending = pending_question_candidates(db, row)
        if len(pending) == 1:
            other = pending[0]
            row.matched_ingest_paper_id, other.matched_ingest_paper_id = other.id, row.id
            _set(row, "auto", None, "auto-linked")
            _set(other, "auto", None, "auto-linked")
            db.flush()
            return
        if len(pending) > 1:
            _set(row, "manual", None, f"{len(pending)} pending question papers have this key")
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


def _answer_candidates(db: Session, row: IngestPaper) -> list[IngestPaper]:
    """The pending answer-only papers question paper ``row`` could be auto-linked to (each is then
    matched from its own side, which decides uniqueness)."""
    if row.status != "pending" or row.matched_ingest_paper_id is not None:
        return []
    if unknown_fields(row):
        return []
    return _pending_partners(db, row, "answer_only")


def match_job(db: Session, job: IngestJob) -> None:
    """Match every pending answer-only paper of ``job``, and link the pending answer papers (older
    jobs' or its own) that fit its question papers."""
    for row in db.scalars(select(IngestPaper).where(IngestPaper.job_id == job.id)):
        if row.role in ("answer_only", "question"):
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
    proposal whose paper still exists) describes the proposed paper, with its ``answer_coverage``."""
    out = {}
    rows = db.scalars(
        select(IngestPaper).where(
            IngestPaper.job_id == job.id, IngestPaper.match_status.in_(("proposed", "manual")),
            IngestPaper.role == "answer_only",
            IngestPaper.status == "pending",
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
                "answer_coverage": bank_coverage(db, [paper.id])[paper.id],
            }
        out[row.paper_key] = info
    return out
