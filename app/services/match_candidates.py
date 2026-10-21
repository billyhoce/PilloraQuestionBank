"""The "Match this paper" search (#91): the booklets a paper that needs a partner could be paired
with, ranked by how many of the admin's filled fields agree, rather than filtered.

* **Blank means "any":** only the filled fields are compared, each *exactly* (``paper_number``
  trimmed and case-folded, as in automatic matching; no fuzzy matching). A school is the same if the
  ids are equal, or if neither has an id and the new-school names are equal (#87).
* **Exact** matches agree on every filled field. **Best** matches, listed only when there is no
  exact one, are the top ten by number of agreeing fields; a booklet that agrees on nothing is left
  out.
* **Sources:** pending papers of the other role (answer-only <-> question) in ``review_ready`` jobs
  or in the paper's own job; for an answer-only paper also bank papers. A question paper never
  matches a bank paper (that would be a duplicate). Bank papers that already have answers on every
  question are returned with coverage ``all`` so the popup can grey them out.

See docs/features/qa-pairing.md ("Match this paper").
"""

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.orm import IngestJob, IngestPaper, Paper
from app.services.answer_coverage import answered_numbers, bank_coverage, current_papers, proposal_coverage
from app.services.ingest_papers import METADATA_FIELDS, first_preview

BEST_LIMIT = 10
EXACT_LIMIT = 50


def _norm(value) -> str:
    return str(value).strip().lower()


def _filled(query: dict, field: str) -> bool:
    if field == "school_id":
        return query.get("school_id") is not None or bool((query.get("new_school_name") or "").strip())
    return query.get(field) not in (None, "")


def _same(field: str, query: dict, fields: dict) -> bool:
    if field == "school_id":
        if query.get("school_id") is not None:
            return fields.get("school_id") == query["school_id"]
        return fields.get("school_id") is None and _norm(fields.get("new_school_name") or "") == _norm(query["new_school_name"])
    value = fields.get(field)
    if value is None:
        return False
    if field == "paper_number":
        return _norm(value) == _norm(query[field])
    return value == query[field]


def rank(query: dict, items: list[dict], limit: int = BEST_LIMIT) -> dict[str, list[dict]]:
    """``{"exact", "best"}`` of ``items`` (each with ``details``: the seven key fields and
    ``new_school_name``) against ``query`` (the same shape; blank fields mean "any"). Each returned
    item gains ``agree`` and ``differ``, the filled fields it does and does not share, in key order.
    Input order is kept among equals."""
    filled = [f for f in METADATA_FIELDS if _filled(query, f)]
    ranked = []
    for it in items:
        agree = [f for f in filled if _same(f, query, it["details"])]
        ranked.append({**it, "agree": agree, "differ": [f for f in filled if f not in agree]})
    exact = [it for it in ranked if not it["differ"]]
    if exact:
        return {"exact": exact[:EXACT_LIMIT], "best": []}
    best = sorted((it for it in ranked if it["agree"]), key=lambda it: -len(it["agree"]))
    return {"exact": [], "best": best[:limit]}


def _details(obj) -> dict:
    return {
        **{f: getattr(obj, f) for f in METADATA_FIELDS},
        "new_school_name": getattr(obj, "new_school_name", None),
    }


def _pending_items(db: Session, row: IngestPaper) -> list[dict]:
    """Pending papers of the other role, in review-ready jobs or ``row``'s own job: its own job
    first, then the newest; not ``row`` itself nor its current partner."""
    role = "question" if row.role == "answer_only" else "answer_only"
    q = (
        select(IngestPaper, IngestJob)
        .join(IngestJob, IngestJob.id == IngestPaper.job_id)
        .where(
            IngestPaper.role == role, IngestPaper.status == "pending", IngestPaper.id != row.id,
            (IngestJob.status == "review_ready") | (IngestPaper.job_id == row.job_id),
        )
    )
    if row.matched_ingest_paper_id is not None:
        q = q.where(IngestPaper.id != row.matched_ingest_paper_id)
    return [
        {"kind": "pending", "row": r, "job": j, "details": _details(r)}
        for r, j in db.execute(q.order_by((IngestPaper.job_id != row.job_id), IngestJob.created_at.desc(), IngestPaper.id))
    ]


def _bank_items(db: Session, query: dict) -> list[dict]:
    """Bank papers sharing at least one filled field with ``query`` (all of them when none is
    filled), newest first. The ranking decides which are shown."""
    clauses = []
    for f in METADATA_FIELDS:
        if f == "school_id" and query.get("school_id") is None:
            continue  # a new school is never in the bank
        if not _filled(query, f):
            continue
        if f == "paper_number":
            clauses.append(func.lower(func.trim(Paper.paper_number)) == _norm(query[f]))
        else:
            clauses.append(getattr(Paper, f) == query[f])
    q = select(Paper)
    if clauses:
        q = q.where(or_(*clauses))
    elif any(_filled(query, f) for f in METADATA_FIELDS):
        return []  # only a new school was given: no bank paper has it
    return [{"kind": "bank", "paper": p, "details": _details(p)} for p in db.scalars(q.order_by(Paper.id.desc()))]


def _pending_out(db: Session, row: IngestPaper, it: dict, store) -> dict:
    other, job = it["row"], it["job"]
    paper = current_papers(job).get(other.paper_key) or {}
    coverage = proposal_coverage(paper)["answer_coverage"]
    partner = other.matched_ingest_paper
    partner_job = db.get(IngestJob, partner.job_id) if partner is not None else None
    answer_only = other.role == "answer_only"
    return {
        "kind": "pending", "ingest_paper_id": other.id, "paper_id": None,
        "job_id": str(job.id), "filename": job.filename, "paper_key": other.paper_key,
        "same_job": job.id == row.job_id, "role": other.role,
        "partner": None if partner is None else {
            "ingest_paper_id": partner.id, "job_id": str(partner.job_id),
            "filename": partner_job.filename if partner_job else None, "paper_key": partner.paper_key,
        },
        "preview": first_preview(job, other.paper_key, store, "answer_rects" if answer_only else "question_rects"),
        "question_numbers": [] if answer_only else [q["number"] for q in paper.get("questions") or []],
        "answer_numbers": answered_numbers(paper),
        "answer_coverage": coverage,
    }


def _bank_out(db: Session, it: dict, coverage: dict, store) -> dict:
    paper: Paper = it["paper"]
    questions = sorted(paper.questions, key=lambda q: q.question_number)
    preview = None
    for q in questions:
        pages = sorted((p for p in q.pages if p.page_type == "question"), key=lambda p: p.page_order)
        if pages:
            preview = {"number": q.question_number, "url": store.presign(pages[0].image_key)}
            break
    return {
        "kind": "bank", "ingest_paper_id": None, "paper_id": paper.id,
        "job_id": None, "filename": None, "paper_key": None, "same_job": False, "role": "question",
        "partner": None, "preview": preview,
        "question_numbers": [q.question_number for q in questions],
        "answer_numbers": [q.question_number for q in questions if any(p.page_type == "answer" for p in q.pages)],
        "answer_coverage": coverage.get(paper.id, "none"),
    }


def find_candidates(db: Session, store, row: IngestPaper, query: dict) -> dict[str, list[dict]]:
    """``{"exact", "best"}``: the booklets pending paper ``row`` could be paired with, ranked
    against ``query`` (see the module doc). Each is ``{kind, ingest_paper_id, paper_id, job_id,
    filename, paper_key, same_job, role, details, agree, differ, partner, preview,
    question_numbers, answer_numbers, answer_coverage}``."""
    items = _pending_items(db, row)
    if row.role == "answer_only":
        items += _bank_items(db, query)
    ranked = rank(query, items)
    shown = ranked["exact"] + ranked["best"]
    coverage = bank_coverage(db, (it["paper"].id for it in shown if it["kind"] == "bank"))

    def out(it):
        body = _pending_out(db, row, it, store) if it["kind"] == "pending" else _bank_out(db, it, coverage, store)
        return {**body, "details": it["details"], "agree": it["agree"], "differ": it["differ"]}

    return {k: [out(it) for it in v] for k, v in ranked.items()}
