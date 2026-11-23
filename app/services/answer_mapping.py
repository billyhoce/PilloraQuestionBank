"""What the answer mapping table (#92) shows: the questions of one paper of a pair beside the
answers of the other, each with a thumbnail, and the pair's stored mapping.

A pair is an answer-only paper and either a pending question paper or (for an attach) a bank paper.
The table is shown for a booklet chosen in the "Match this paper" popup and from "Check answers…"
on a linked pair. A mapping is ``{answer label: question label | null}`` (``ingest_paper.answer_map``
on the answer paper's row); an answer it does not name goes onto the question with its number. See
docs/features/qa-pairing.md ("The answer mapping table").
"""

from sqlalchemy.orm import Session

from app.models.orm import IngestJob, IngestPaper, Paper
from app.services.ingest_confirm import answer_label
from app.services.ingest_papers import PARTNER_ROLE, MatchError, answer_row, question_previews


def _pending_questions(db: Session, row: IngestPaper, store) -> list[dict]:
    job = db.get(IngestJob, row.job_id)
    return [
        {"label": answer_label(q["number"]), "answered": bool(q.get("answer_rects")), "preview": preview}
        for q, preview in question_previews(job, row.paper_key, store, "question_rects")
    ]


def _pending_answers(db: Session, row: IngestPaper, store) -> list[dict]:
    job = db.get(IngestJob, row.job_id)
    return [
        {"label": answer_label(q["number"]), "preview": preview}
        for q, preview in question_previews(job, row.paper_key, store, "answer_rects")
        if q.get("answer_rects")
    ]


def _bank_questions(paper: Paper, store) -> list[dict]:
    out = []
    for q in sorted(paper.questions, key=lambda q: q.question_number):
        pages = sorted((p for p in q.pages if p.page_type == "question"), key=lambda p: p.page_order)
        out.append({
            "label": str(q.question_number),
            "answered": any(p.page_type == "answer" for p in q.pages),
            "preview": {"number": q.question_number, "url": store.presign(pages[0].image_key)} if pages else None,
        })
    return out


def mapping_table(
    db: Session, store, row: IngestPaper, ingest_paper_id: int | None = None, paper_id: int | None = None
) -> dict:
    """``{questions, answers, mapping}`` for pending paper ``row`` and its partner: the pending paper
    ``ingest_paper_id``, the bank paper ``paper_id`` (an answer-only ``row`` only), or, with neither,
    its current link. ``questions`` are ``{label, answered, preview}`` (``answered``: it has answers
    of its own), ``answers`` ``{label, preview}`` (the answers with answer boxes); ``mapping`` is the
    pair's stored ``answer_map`` when the partner is the current link, else null (by number)."""
    if paper_id is not None:
        if row.role != "answer_only":
            raise MatchError(422, "Only an answer-only paper is attached to a paper in the bank")
        paper = db.get(Paper, paper_id)
        if paper is None:
            raise MatchError(404, f"Paper {paper_id} does not exist")
        return {"questions": _bank_questions(paper, store), "answers": _pending_answers(db, row, store), "mapping": None}
    if ingest_paper_id is None:
        if row.matched_ingest_paper_id is None:
            raise MatchError(409, f"Paper {row.paper_key!r} is not paired with a pending paper")
        ingest_paper_id = row.matched_ingest_paper_id
    other = db.get(IngestPaper, ingest_paper_id)
    if other is None:
        raise MatchError(404, "That paper does not exist")
    if row.role not in PARTNER_ROLE or other.role != PARTNER_ROLE[row.role]:
        raise MatchError(422, "Those two papers cannot be paired")
    question, answers = (other, row) if row.role == "answer_only" else (row, other)
    linked = row.matched_ingest_paper_id == other.id
    return {
        "questions": _pending_questions(db, question, store),
        "answers": _pending_answers(db, answers, store),
        "mapping": answer_row(row).answer_map if linked else None,
    }
