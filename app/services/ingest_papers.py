"""``ingest_paper``: the queryable record of each paper an ingest job proposed.

Source of truth: the job's ``proposal`` / ``proposal_edited`` (what the paper holds) and
``report["review_outcome"]`` (what the admin decided) stay authoritative for the review flow, which
reads only them. ``ingest_paper`` is written alongside them, in the same transaction as each change,
so the two never disagree, and it is what matching queries read. See docs/DATA_MODEL.md.
"""

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.orm import IngestJob, IngestPaper, School

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


def school_named(db: Session, name: str) -> School | None:
    """The school called ``name``, ignoring case and surrounding spaces."""
    return db.scalar(select(School).where(func.lower(School.name) == name.strip().lower()))


def _school_fields(db: Session, metadata: dict, school_id: int | None) -> dict[str, Any]:
    """``school_id`` and ``new_school_name`` as stored: a chosen school drops any typed name, and a
    typed name equal to an existing school (any case) becomes that school's id (#87)."""
    name = ((metadata or {}).get("new_school_name") or "").strip() or None
    if school_id is not None or name is None:
        return {"school_id": school_id, "new_school_name": None}
    existing = school_named(db, name)
    if existing is not None:
        return {"school_id": existing.id, "new_school_name": None}
    return {"school_id": None, "new_school_name": name}


def create_new_school(db: Session, metadata: dict) -> dict:
    """``metadata`` with a ``school_id``: the given one, else the school named ``new_school_name``,
    found ignoring case (another admin may have created it since it was typed) or created now. A
    school found or created is also given to every other pending paper carrying the same new name,
    so they keep matching. Raises ``ValueError`` if there is neither. Does not commit (#87)."""
    out = {k: v for k, v in metadata.items() if k != "new_school_name"}
    if out.get("school_id") is not None:
        return out
    name = (metadata.get("new_school_name") or "").strip()
    if not name:
        raise ValueError("Choose a school, or type the name of a new one")
    school = school_named(db, name)
    if school is None:
        school = School(name=name)
        db.add(school)
        db.flush()
    waiting = db.scalars(select(IngestPaper).where(
        IngestPaper.status == "pending", IngestPaper.school_id.is_(None),
        func.lower(func.trim(IngestPaper.new_school_name)) == name.lower(),
    ))
    for row in waiting:
        row.school_id, row.new_school_name = school.id, None
    return {**out, "school_id": school.id}


def set_metadata(db: Session, job: IngestJob, key: str, metadata: dict, source: str = "admin") -> IngestPaper | None:
    """Store ``metadata`` (the seven fields, plus ``new_school_name`` for a school not in the list
    yet) on the paper's row. ``source`` becomes ``admin`` only if a value actually changed. Does not
    commit. Returns None for an unknown key."""
    row = _row_or_sync(db, job, key)
    if row is None:
        return None
    new = _clean(metadata)
    new.update(_school_fields(db, metadata, new["school_id"]))
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


def question_previews(job: IngestJob, key: str, store, rects: str = "question_rects") -> list[tuple[dict, dict | None]]:
    """Every question of proposal paper ``key`` with a preview of its first rectangle of ``rects``
    (``question_rects`` or ``answer_rects``): ``{number, url, page, rect}``, the review page image,
    the page's sizes and the rectangle (PDF points), or None when it has none with an image."""
    from app.services.ingest_jobs import job_prefix
    from app.services.ingest_review import REVIEW_URL_TTL, pixel_size

    out = []
    for k, paper in _proposal_papers(job):
        if k != key:
            continue
        pages = {p["page"]: p for p in paper.get("pages", [])}
        for q in paper.get("questions", []):
            preview = None
            for rect in q.get(rects) or []:
                page = pages.get(rect["page"])
                if page is None or not page.get("image"):
                    continue
                width_px, height_px = pixel_size(page["width_pt"], page["height_pt"])
                preview = {
                    "number": q.get("number"),
                    "url": store.presign(job_prefix(job.source_key) + page["image"], REVIEW_URL_TTL),
                    "page": {
                        "page": page["page"], "width_pt": page["width_pt"], "height_pt": page["height_pt"],
                        "width_px": width_px, "height_px": height_px,
                    },
                    "rect": {n: rect[n] for n in ("page", "x0", "y0", "x1", "y1")},
                }
                break
            out.append((q, preview))
    return out


def first_preview(job: IngestJob, key: str, store, rects: str = "question_rects") -> dict | None:
    """The first question (``rects="answer_rects"``: the first answer) of proposal paper ``key``
    that has a preview (see ``question_previews``), or None if it has none."""
    return next((p for _, p in question_previews(job, key, store, rects) if p is not None), None)


def _clear_link(row: IngestPaper) -> None:
    """Break ``row``'s link, on both sides, and clear both rows' automatic match state and answer
    mapping (a mapping belongs to one pair, #92)."""
    other = row.matched_ingest_paper
    row.matched_ingest_paper_id = None
    if other is not None and other.matched_ingest_paper_id == row.id:
        other.matched_ingest_paper_id = None
    for r in (row, other):
        if r is not None:
            r.match_status = None
            r.match_note = None
            r.proposed_paper_id = None
            r.answer_map = None


PARTNER_ROLE = {"answer_only": "question", "question": "answer_only"}


def link_papers(
    db: Session, job: IngestJob, key: str, other_id: int, metadata: dict | None = None, mapping: dict | None = None
) -> IngestPaper:
    """Pair paper ``key`` of ``job`` with the pending ``ingest_paper`` ``other_id`` of the other
    role (answer-only <-> question), of a review-ready job or of ``job`` itself, by setting
    ``matched_ingest_paper_id`` on both rows. Replaces any earlier link of either row without
    rejecting it. ``metadata`` (the popup's "Also update this paper's details") is saved on ``key``'s
    row first, as by ``set_metadata``; ``mapping`` (the answer mapping table, #92) is stored as the
    answer paper's ``answer_map``, and none means by number. Does not commit."""
    row = _row_or_sync(db, job, key)
    if row is None:
        raise MatchError(404, f"This job has no paper {key!r}")
    if row.status != "pending":
        raise MatchError(409, f"Paper {key!r} was already {row.status}")
    if row.role not in PARTNER_ROLE:
        raise MatchError(422, f"Paper {key!r} cannot be paired")
    other = db.get(IngestPaper, other_id)
    if other is None:
        raise MatchError(404, "That paper does not exist")
    other_job = db.get(IngestJob, other.job_id)
    if (
        other.id == row.id or other.role != PARTNER_ROLE[row.role] or other.status != "pending"
        or (other.job_id != job.id and other_job.status != "review_ready")
    ):
        wanted = "question paper" if row.role == "answer_only" else "answer-only paper"
        raise MatchError(422, f"That is not a pending {wanted} awaiting review")
    if metadata is not None:
        set_metadata(db, job, key, metadata)
    for r in (row, other):
        if r.matched_ingest_paper_id is not None:
            _clear_link(r)
    row.matched_ingest_paper_id = other.id
    other.matched_ingest_paper_id = row.id
    for r in (row, other):  # an admin's link: no automatic status
        r.match_status = r.match_note = r.proposed_paper_id = None
        r.answer_map = None
    answer_row(row).answer_map = mapping
    db.flush()
    return row


def answer_row(row: IngestPaper) -> IngestPaper | None:
    """The answer-only paper of ``row``'s pair: ``row`` itself, or its linked partner."""
    if row.role == "answer_only":
        return row
    return row.matched_ingest_paper


def set_answer_map(db: Session, job: IngestJob, key: str, mapping: dict | None) -> None:
    """Save an edited answer mapping ("Check answers…", #92) on linked paper ``key``'s pair (on the
    answer paper's row, whichever side ``key`` is). ``409`` unless it is pending and linked. Does not
    commit."""
    row = _row_or_sync(db, job, key)
    if row is None:
        raise MatchError(404, f"This job has no paper {key!r}")
    if row.status != "pending":
        raise MatchError(409, f"Paper {key!r} was already {row.status}")
    answers = answer_row(row) if row.matched_ingest_paper_id is not None else None
    if answers is None:
        raise MatchError(409, f"Paper {key!r} is not paired with a pending paper")
    answers.answer_map = mapping
    db.flush()


def unlink_paper(db: Session, job: IngestJob, key: str) -> None:
    """Unmatch paper ``key``: remove its link (on both sides) and record the pair as rejected, so
    automatic matching never re-makes it; then re-match both papers, which may find another partner.
    Does not commit."""
    from app.services.ingest_matching import match_row, reject  # imports this module's constants

    row = _row_or_sync(db, job, key)
    if row is None:
        raise MatchError(404, f"This job has no paper {key!r}")
    other = row.matched_ingest_paper
    _clear_link(row)
    if other is not None:
        reject(db, row, other=other)
    db.flush()
    match_row(db, row)  # back to what the bank offers, or another pending partner
    if other is not None and other.matched_ingest_paper_id is None:
        match_row(db, other)
    db.flush()


def reject_proposed_paper(db: Session, job: IngestJob, key: str) -> None:
    """"Not this one": record answer-only paper ``key``'s proposed confirmed paper as rejected and
    re-match it. ``409`` unless it is pending with a proposal. Does not commit."""
    from app.services.ingest_matching import match_row, reject

    row = _row_or_sync(db, job, key)
    if row is None:
        raise MatchError(404, f"This job has no paper {key!r}")
    if row.status != "pending":
        raise MatchError(409, f"Paper {key!r} was already {row.status}")
    if row.match_status != "proposed" or row.proposed_paper_id is None:
        raise MatchError(409, f"Paper {key!r} has no proposed paper")
    reject(db, row, paper_id=row.proposed_paper_id)
    match_row(db, row)
    db.flush()


def paper_links(db: Session, job: IngestJob) -> dict[str, dict]:
    """The job's linked papers by paper key: the partner's ingest paper id, job id, filename, key and
    ``details`` (its seven fields and ``new_school_name``), ``matched_by`` (``auto`` or ``admin``),
    ``answer_numbers`` and ``answer_map``. ``answer_numbers`` are the partner's question numbers that
    have an answer box; for a question paper they are where its confirm puts the linked answers, by
    the pair's mapping (#92) — the review warns about the rest (#89). ``answer_map`` is the pair's
    stored mapping, or null (by number)."""
    from app.services.answer_coverage import paper_answer_numbers
    from app.services.ingest_confirm import answer_label

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
            "details": {**{f: getattr(other, f) for f in METADATA_FIELDS}, "new_school_name": other.new_school_name},
            "matched_by": "auto" if row.match_status == "auto" else "admin",
            "answer_numbers": paper_answer_numbers(other_job, other.paper_key) if other_job else [],
            "answer_map": answer_row(row).answer_map,
        }
        mapping = out[row.paper_key]["answer_map"]
        if row.role == "question" and mapping:  # where the answers land, not what they are numbered
            out[row.paper_key]["answer_numbers"] = [
                mapping[answer_label(n)] if answer_label(n) in mapping else n
                for n in out[row.paper_key]["answer_numbers"]
                if mapping.get(answer_label(n), n) is not None
            ]
    return out
