"""Answers are all or none (#89): how much of a paper has answers.

A paper's **answer coverage** is ``none`` (no question has an answer), ``all`` (every question has
one) or ``partial`` (anything in between). A paper with no questions is ``none``. "Has an answer"
means an answer box (``answer_rects``) on a pending proposal paper, and an ``answer`` page
(``question_page.page_type = 'answer'``) on a confirmed one.

Coverage is a warning, never a hard stop, with one exception: an answer-only paper is never
attached to (or proposed for) a bank paper whose coverage is ``all``. See
docs/features/qa-pairing.md ("Answers are all or none").
"""

from collections.abc import Iterable

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.orm import IngestJob, Question, QuestionPage

NONE, PARTIAL, ALL = "none", "partial", "all"


def coverage_of(total: int, answered: int) -> str:
    if answered == 0:
        return NONE
    return ALL if answered >= total else PARTIAL


def answered_numbers(paper: dict) -> list:
    """The numbers of proposal paper ``paper``'s questions that have an answer box, in order."""
    return [q["number"] for q in paper.get("questions") or [] if q.get("answer_rects")]


def proposal_coverage(paper: dict) -> dict:
    """``{"answer_coverage", "unanswered"}`` of one proposal paper: its coverage and the numbers of
    its questions without an answer box, in order."""
    questions = paper.get("questions") or []
    unanswered = [q["number"] for q in questions if not q.get("answer_rects")]
    return {"answer_coverage": coverage_of(len(questions), len(questions) - len(unanswered)), "unanswered": unanswered}


def current_papers(job: IngestJob) -> dict[str, dict]:
    """``job``'s current proposal papers (the admin's edit, else the worker's) by paper key."""
    from app.services.ingest_confirm import paper_key  # confirm imports this module

    proposal = job.proposal_edited if job.proposal_edited is not None else job.proposal
    return {paper_key(p, i): p for i, p in enumerate((proposal or {}).get("papers", []))}


def job_coverage(job: IngestJob) -> dict[str, dict]:
    """Coverage of every paper of ``job``'s current proposal, by paper key. Empty while the job has
    no proposal."""
    return {key: proposal_coverage(p) for key, p in current_papers(job).items()}


def paper_answer_numbers(job: IngestJob, key: str) -> list:
    """The numbers of proposal paper ``key``'s questions that have an answer box: for an answer-only
    paper, the answers a linked confirm brings in by number."""
    paper = current_papers(job).get(key)
    return answered_numbers(paper) if paper is not None else []


def bank_coverage(db: Session, paper_ids: Iterable[int]) -> dict[int, str]:
    """Coverage of each confirmed paper in ``paper_ids`` (one query); a paper with no questions is
    ``none``."""
    ids = list(set(paper_ids))
    if not ids:
        return {}
    has_answer = (
        select(QuestionPage.question_id)
        .where(QuestionPage.page_type == "answer")
        .group_by(QuestionPage.question_id)
        .subquery()
    )
    rows = db.execute(
        select(
            Question.paper_id,
            func.count(Question.id),
            func.sum(case((has_answer.c.question_id.isnot(None), 1), else_=0)),
        )
        .outerjoin(has_answer, has_answer.c.question_id == Question.id)
        .where(Question.paper_id.in_(ids))
        .group_by(Question.paper_id)
    )
    out = {i: NONE for i in ids}
    for paper_id, total, answered in rows:
        out[paper_id] = coverage_of(total, int(answered or 0))
    return out
