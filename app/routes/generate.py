from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models.orm import Question, User
from app.pdf.layout_engine import Block, CoverSpec, LayoutEngine, render_combined
from app.routes.auth import get_current_user
from app.routes.questions import (
    _PAPER_EAGER,
    _SUBTOPICS_EAGER,
    _TAG_EAGER,
    _TOPIC_EAGER,
    _apply_filters,
    serialize_list_item,
)
from app.schemas.generate import (
    CoverDefaultsResponse,
    GeneratePaperRequest,
    SelectRequest,
    SelectResponse,
)
from app.services.generate import knapsack_select
from app.storage.s3_client import get_image_bytes

router = APIRouter(prefix="/api", tags=["generation"])


def _source_label(q: Question) -> str:
    """Provenance credit for a question, drawn above it on the question paper.

    Format: ``[School/Year/ExamType/P{paper_number}/Q{question_number}]`` — e.g.
    ``[Bendemeer Secondary School/2024/Prelim/P2/Q6]``. Uses the question's
    original number (not the renumbered position). ``paper_number`` is stored as
    a bare ``"1"``/``"2"`` so a ``P`` prefix is added here.
    """
    p = q.paper
    return (
        f"[{p.school.name}/{p.year}/{p.exam_type.name}/"
        f"P{p.paper_number}/Q{q.question_number}]"
    )


def _footer_label(subtitle2: str, is_questions: bool) -> str:
    """Text centered under the footer rule on every page of a section, e.g.
    ``"2024 Prelim Questions"`` (or just ``"Questions"`` when no subtitle)."""
    word = "Questions" if is_questions else "Answers"
    return f"{subtitle2} {word}".strip()


def _cover_for(payload: GeneratePaperRequest, total_marks: int, is_questions: bool) -> CoverSpec | None:
    """Build the cover spec for a section, or ``None`` when covers are disabled."""
    if not payload.include_cover:
        return None
    return CoverSpec(
        title=payload.cover_title,
        subtitle1=payload.cover_subtitle1,
        subtitle2=payload.cover_subtitle2,
        body=payload.cover_body,
        total_marks=total_marks,
        is_questions=is_questions,
    )


def _blocks_for(ordered: list[Question], variant: str) -> list[Block]:
    """Build one Block per question holding its ``variant`` pages, numbered by
    selection order. In the answer variant a question with no answer pages is
    skipped, but its number stays reserved."""
    blocks: list[Block] = []
    for idx, q in enumerate(ordered, start=1):
        pages = sorted(
            (pg for pg in q.pages if pg.page_type == variant),
            key=lambda pg: pg.page_order,
        )
        if variant == "answer" and not pages:
            continue  # reserve the number, but nothing to render
        blocks.append(Block(label=str(idx), source_label=_source_label(q), pages=pages))
    return blocks


@router.get("/generate/cover-defaults", response_model=CoverDefaultsResponse)
def cover_defaults(current_user: User = Depends(get_current_user)):
    """Serve the canonical cover-page defaults so the frontend can pre-fill the
    editable cover fields from a single source of truth."""
    return CoverDefaultsResponse()


@router.post("/generate/select", response_model=SelectResponse)
def select_questions(
    payload: SelectRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Auto-select a randomized set of questions summing near ``target_marks``.

    Reuses the Browse filter suite to build the candidate pool, excludes any
    already-chosen questions, then runs the randomized knapsack. Returns the
    selected questions (never a 404 — an empty result with a warning keeps the
    live builder UI responsive).
    """
    f = payload.filters
    base = db.query(Question).join(Question.paper)
    query = _apply_filters(
        base,
        f.subject_id,
        f.stream_id,
        f.level_id,
        f.year,
        f.school_id,
        f.exam_type_id,
        f.topic_ids,
        f.exclusive,
        f.tag_ids,
        f.search,
        f.paper_number,
    )
    if payload.exclude_question_ids:
        query = query.filter(Question.id.notin_(payload.exclude_question_ids))

    candidates = (
        query.options(_PAPER_EAGER, selectinload(Question.pages), _TOPIC_EAGER, _SUBTOPICS_EAGER, _TAG_EAGER)
        .order_by(Question.id)
        .all()
    )

    selected = knapsack_select(candidates, payload.target_marks)
    total_marks = sum(q.marks for q in selected)
    exact = total_marks == payload.target_marks

    warning = None
    if not candidates:
        warning = "No questions match the current filters."
    elif not selected:
        warning = "No questions with marks match the current filters."
    elif not exact:
        warning = (
            f"Could not reach exactly {payload.target_marks} marks. "
            f"Closest achievable is {total_marks} marks."
        )

    return {
        "items": [serialize_list_item(q) for q in selected],
        "total_marks": total_marks,
        "target_marks": payload.target_marks,
        "exact": exact,
        "warning": warning,
    }


@router.post("/generate/paper")
def generate_paper(
    payload: GeneratePaperRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Render a PDF (question paper, answer paper, or both combined) from a
    manual selection.

    Questions are laid out in ``question_ids`` order and numbered 1..N. The same
    numbers are used in both variants, so an answer keeps the number of its
    question even when earlier questions have no answer pages (those are skipped
    in the answer variant, but their number is still reserved). The ``combined``
    variant renders the question paper followed by the answer paper in one PDF.
    """
    rows = (
        db.query(Question)
        .filter(Question.id.in_(payload.question_ids))
        .options(_PAPER_EAGER, selectinload(Question.pages))
        .all()
    )
    by_id = {q.id: q for q in rows}
    ordered = [by_id[qid] for qid in payload.question_ids if qid in by_id]

    # Question paper: scale images centered within 30 mm side margins.
    # Answer paper: keep native size, flush to the left margin.
    total_marks = sum(q.marks or 0 for q in ordered)
    subtitle2 = payload.cover_subtitle2

    if payload.variant == "combined":
        q_engine = LayoutEngine(fit_width=True, show_credit=True)
        q_plan = q_engine.compute_layout(
            _blocks_for(ordered, "question"), header_text=payload.header_text
        )
        q_plan.footer_label = _footer_label(subtitle2, is_questions=True)
        q_plan.cover = _cover_for(payload, total_marks, is_questions=True)
        sections = [(q_engine, q_plan)]
        a_blocks = _blocks_for(ordered, "answer")
        if a_blocks:  # no trailing blank page when nothing has answers
            a_engine = LayoutEngine(fit_width=False)
            a_plan = a_engine.compute_layout(a_blocks)
            a_plan.footer_label = _footer_label(subtitle2, is_questions=False)
            a_plan.cover = _cover_for(payload, total_marks, is_questions=False)
            sections.append((a_engine, a_plan))
        pdf = render_combined(sections, fetch_bytes=get_image_bytes)
    else:
        is_question = payload.variant == "question"
        blocks = _blocks_for(ordered, payload.variant)
        engine = LayoutEngine(fit_width=is_question, show_credit=is_question)
        header = payload.header_text if is_question else ""
        plan = engine.compute_layout(blocks, header_text=header)
        plan.footer_label = _footer_label(subtitle2, is_questions=is_question)
        plan.cover = _cover_for(payload, total_marks, is_questions=is_question)
        pdf = engine.render(plan, fetch_bytes=get_image_bytes)
    return Response(content=pdf, media_type="application/pdf")
