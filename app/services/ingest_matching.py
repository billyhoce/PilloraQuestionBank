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

Pending <-> pending (#84, scored): when no confirmed paper has the key, the row's pending
``question`` partners (unlinked, of another ``review_ready`` job or of its own job (#90: a booklet
whose papers the pipeline did not pair)) are *scored* by ``match_evidence.score``: a field known on
both sides that differs rules a partner out, a blank field does not, and agreeing fields, the
filename without Qns/Soln, the cover school's text, fitting answer numbers and a shared upload add
evidence. A clear, strong winner is auto-linked (``matched_ingest_paper_id`` on both rows,
``match_status`` ``auto``, ``match_note`` "auto-linked"); a clear winner on weaker evidence is
``suggested`` (``suggested_ingest_paper_id``, the reasons in ``match_note``); a close race ->
``manual``. This comes before the partial hints above. A single confirmed-paper match wins over all
of it (the #83 proposal). The same runs from the question side: a question paper (on ``match_job``
or a metadata edit) scores the pending answer-only papers, its own job's included, and the best is
matched from its own side. An *auto* link is recomputed from scratch on every re-evaluation
(metadata edit, new job, new paper), so it follows the data; a link the admin set (``match_status``
NULL) is never touched.

Rejections (#88): Unmatch on a linked pair, "Not this one" on a proposed confirmed paper, or "Not a
pair" on a suggestion records the pair in ``ingest_match_rejection``. Every rule above skips a
rejected pair (a pending pair counts in either direction), so that pair is never proposed again
while both papers stay free to match something else.

New schools (#87): a paper whose school the admin typed as new has no ``school_id`` but a
``new_school_name``; its school counts as known. A confirmed paper always has an id, so a new-school
paper only matches pending papers, where its name is compared like a cover's unresolved school.

Answers are all or none (#89): a confirmed paper whose every question already has an answer page
(coverage ``all``) is never a candidate, exact or partial; a partly answered one still is. A
*pending* question paper is linked only when it has no answers of its own (coverage ``none``): a
partly answered one counts as answered, from either side.

``paper_number`` is not normalised in the bank, so it is compared through
``match_evidence.normalise_paper_number`` (``P1`` = ``Paper 1`` = ``1``). Nothing here commits;
callers run it inside their own transaction.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.orm import IngestJob, IngestMatchRejection, IngestPaper, Paper
from app.services import match_evidence
from app.services.answer_coverage import ALL, answered_numbers, bank_coverage, current_papers
from app.services.ingest_papers import METADATA_FIELDS, open_to_answers

PARTIAL_FIELDS = ("school_id", "year", "subject_id")
_LABELS = match_evidence.LABELS


def _same_number(a, b) -> bool:
    return match_evidence.normalise_paper_number(a) == match_evidence.normalise_paper_number(b)


def unknown_fields(row: IngestPaper) -> list[str]:
    """The key fields ``row`` does not know yet (a new school's name counts as knowing the school)."""
    return [
        f for f in METADATA_FIELDS
        if getattr(row, f) is None and not (f == "school_id" and row.new_school_name)
    ]


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
        if f != "paper_number":
            q = q.where(getattr(Paper, f) == getattr(row, f))
    papers = [p for p in db.scalars(q.order_by(Paper.id)) if _same_number(p.paper_number, row.paper_number)]
    return _open_to_answers(db, papers)


def partial_candidates(db: Session, row: IngestPaper) -> list[Paper]:
    if any(getattr(row, f) is None for f in PARTIAL_FIELDS):
        return []
    q = _without(select(Paper), Paper.id, rejected_paper_ids(db, row))
    for f in PARTIAL_FIELDS:
        q = q.where(getattr(Paper, f) == getattr(row, f))
    return _open_to_answers(db, list(db.scalars(q.order_by(Paper.id))))


def _pending_partners(db: Session, row: IngestPaper, role: str) -> list[IngestPaper]:
    """Unlinked pending ``role`` papers that could be ``row``'s partner, bar those rejected as its
    partner: of other ``review_ready`` jobs, or of ``row``'s own job (#90), whose status does not
    matter because ``report`` matches a booklet's papers before the job turns ``review_ready``.
    Whether they fit is for ``_scored`` to say."""
    q = (
        select(IngestPaper)
        .join(IngestJob, IngestJob.id == IngestPaper.job_id)
        .where(
            IngestPaper.role == role, IngestPaper.status == "pending", IngestPaper.id != row.id,
            IngestPaper.matched_ingest_paper_id.is_(None),
            (IngestJob.status == "review_ready") | (IngestPaper.job_id == row.job_id),
        )
    )
    q = _without(q, IngestPaper.id, rejected_ingest_ids(db, row))
    rows = list(db.scalars(q.order_by(IngestPaper.id)))
    if role == "question":  # only a question paper with no answers of its own takes another's
        rows = [r for r in rows if open_to_answers(r, db.get(IngestJob, r.job_id))]
    return rows


def side(db: Session, row: IngestPaper) -> match_evidence.Side:
    """``row`` as evidence for ``match_evidence.score``."""
    job = db.get(IngestJob, row.job_id)
    paper = current_papers(job).get(row.paper_key) or {}
    if row.role == "answer_only":
        numbers = answered_numbers(paper)
    else:
        numbers = [q["number"] for q in paper.get("questions") or []]
    return match_evidence.Side(
        fields={f: getattr(row, f) for f in METADATA_FIELDS},
        new_school=row.new_school_name, cover_school=row.cover_school_name,
        filename=job.filename, numbers=frozenset(numbers), created_by=job.created_by, created_at=job.created_at,
    )


def _scored(db: Session, row: IngestPaper, role: str) -> list[tuple[IngestPaper, match_evidence.Evidence]]:
    """``row``'s pending ``role`` partners, each with the evidence that the pair is one paper."""
    mine = side(db, row)
    out = []
    for other in _pending_partners(db, row, role):
        theirs = side(db, other)
        answers, questions = (mine, theirs) if row.role == "answer_only" else (theirs, mine)
        out.append((other, match_evidence.score(answers, questions)))
    return out


def pending_question_candidates(db: Session, row: IngestPaper) -> list[IngestPaper]:
    """The pending question papers answer-only paper ``row`` could be paired with, best first."""
    scored = [(c, e) for c, e in _scored(db, row, "question") if e.veto is None]
    return [c for c, _ in sorted(scored, key=lambda ce: -ce[1].score)]


def _note(evidence: match_evidence.Evidence) -> str:
    return "; ".join(evidence.reasons)[:200]


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


def _set(row: IngestPaper, status, paper_id=None, note=None, suggested: IngestPaper | None = None) -> None:
    row.match_status, row.proposed_paper_id, row.match_note = status, paper_id, note
    row.suggested_ingest_paper_id = suggested.id if suggested is not None else None


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
        kind, best, _, close = match_evidence.pick(_answer_candidates(db, row))
        if row.match_status == "manual":
            _set(row, None)  # an earlier ambiguity: recomputed below
        if kind in ("link", "suggest"):
            _match(db, best)  # its own side decides: another question paper may fit it better
        elif kind == "several":
            note = f"{len(close)} pending answer papers could be its answers"
            _set(row, "manual", None, note)
            for c in close:
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
    kind, best, evidence, close = match_evidence.pick(_scored(db, row, "question"))
    if kind == "link":
        row.matched_ingest_paper_id, best.matched_ingest_paper_id = best.id, row.id
        _set(row, "auto", None, "auto-linked")
        _set(best, "auto", None, "auto-linked")
        db.flush()
        return
    if kind == "suggest":
        _set(row, "suggested", None, _note(evidence), suggested=best)
        return
    if kind == "several":
        _set(row, "manual", None, f"{len(close)} pending question papers could be its partner")
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
                (not _same_number(row.paper_number, p.paper_number)) if f == "paper_number" else getattr(row, f) != getattr(p, f)
                for p in partial
            )
        ]
        _set(row, "manual", None, "partial: " + (", ".join(differ) or "key") + " differ")


def _answer_candidates(db: Session, row: IngestPaper) -> list[tuple[IngestPaper, match_evidence.Evidence]]:
    """The pending answer-only papers question paper ``row`` could take the answers of, scored
    (the best is then matched from its own side, which decides)."""
    if row.status != "pending" or row.matched_ingest_paper_id is not None:
        return []
    if not open_to_answers(row, db.get(IngestJob, row.job_id)):
        return []
    return _scored(db, row, "answer_only")


def suggestion(db: Session, row: IngestPaper) -> IngestPaper | None:
    """The pending question paper suggested for answer-only paper ``row``, while the suggestion
    still holds: both pending and unlinked, and the partner's job (if another) still under review."""
    if row.match_status != "suggested" or row.suggested_ingest_paper_id is None or row.status != "pending":
        return None
    if row.matched_ingest_paper_id is not None:
        return None
    other = db.get(IngestPaper, row.suggested_ingest_paper_id)
    if other is None or other.status != "pending" or other.matched_ingest_paper_id is not None:
        return None
    if other.job_id != row.job_id and db.get(IngestJob, other.job_id).status != "review_ready":
        return None
    return other


def reject_suggestion(db: Session, row: IngestPaper) -> IngestPaper | None:
    """"Not a pair": record answer-only paper ``row``'s suggested pair as rejected and re-match both
    papers. Returns the paper that was suggested, or None if there was no suggestion."""
    other = suggestion(db, row)
    if other is None:
        return None
    reject(db, row, other=other)
    _set(row, None)
    db.flush()
    match_row(db, row)
    if other.matched_ingest_paper_id is None:
        match_row(db, other)
    db.flush()
    return other


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
    """The job's automatic matches by paper key: ``{status, note, paper, suggestion}`` where
    ``paper`` (for a proposal whose paper still exists) describes the proposed paper, with its
    ``answer_coverage``, and ``suggestion`` (for a suggestion that still holds) the suggested pending
    question paper: ``{ingest_paper_id, job_id, filename, paper_key}``."""
    out = {}
    rows = db.scalars(
        select(IngestPaper).where(
            IngestPaper.job_id == job.id, IngestPaper.match_status.in_(("proposed", "manual", "suggested")),
            IngestPaper.role == "answer_only",
            IngestPaper.status == "pending",
        )
    )
    for row in rows:
        if row.matched_ingest_paper_id is not None:
            continue  # a pending-paper link takes precedence
        info = {"status": row.match_status, "note": row.match_note, "paper": None, "suggestion": None}
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
        elif row.match_status == "suggested":
            other = suggestion(db, row)
            if other is None:
                continue
            info["suggestion"] = suggestion_out(db, other)
        out[row.paper_key] = info
    return out


def suggestion_out(db: Session, other: IngestPaper) -> dict:
    other_job = db.get(IngestJob, other.job_id)
    return {
        "ingest_paper_id": other.id, "job_id": str(other.job_id),
        "filename": other_job.filename, "paper_key": other.paper_key,
    }
