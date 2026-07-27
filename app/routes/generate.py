from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models.orm import CoverTitle, Paper, Question, User
from app.pdf.layout_engine import Block, CoverSpec, LayoutEngine, render_combined
from app.routes.auth import can_view_premium, get_current_user
from app.routes.questions import (
    _PAPER_EAGER,
    _SUBTOPICS_EAGER,
    _TAG_EAGER,
    _TOPIC_EAGER,
    _apply_filters,
    serialize_list_item,
)
from app.schemas.generate import (
    GeneratePaperRequest,
    SelectRequest,
    SelectResponse,
)
from app.services.generate import count_select, in_order_select, knapsack_select
from app.services.generation_config import get_or_create_config
from app.storage.s3_client import get_image_bytes

router = APIRouter(prefix="/api", tags=["generation"])


def _source_label(q: Question) -> str:
    """Provenance credit for a question, drawn above it on the question paper.

    Format: ``[School/Year/ExamType/{paper_number}/Q{question_number}]`` — e.g.
    ``[Bendemeer Secondary School/2024/Prelim/2/Q6]``. Uses the question's
    original number (not the renumbered position). ``paper_number`` is stored as
    a bare ``"1"``/``"2"`` and is rendered as-is.
    """
    p = q.paper
    return (
        f"[{p.school.name}/{p.year}/{p.exam_type.name}/"
        f"{p.paper_number}/Q{q.question_number}]"
    )


def _resolve_generation_options(
    payload: GeneratePaperRequest, current_user: User, db: Session
) -> tuple[bool, str, str, str, str, str]:
    """Resolve the effective (include_cover, title, body, header, instructions,
    footer).

    The page-header branding always comes from the admin generation config — it
    is page furniture, not a per-paper choice, so even admins can't override it
    per generation. Admins control the remaining fields verbatim. For non-admin
    users the admin-set generation config wins: a cover page is always included,
    the body/instructions/footer come from the config, and the title must be one
    of the configured cover titles — an empty title falls back to the first
    configured one (so generation still works if the client never loaded the
    config), and an unknown title is rejected so the dropdown can't be bypassed
    with a hand-crafted request. With no titles configured the cover is untitled.
    """
    cfg = get_or_create_config(db)
    if current_user.role == "admin":
        return (
            payload.include_cover,
            payload.cover_title,
            payload.cover_body,
            cfg.header_text,
            payload.additional_instructions,
            payload.footer_text,
        )

    titles = [t.name for t in db.query(CoverTitle).order_by(CoverTitle.id).all()]
    if not titles:
        title = ""
    elif not payload.cover_title:
        title = titles[0]
    elif payload.cover_title in titles:
        title = payload.cover_title
    else:
        raise HTTPException(
            status_code=400,
            detail="Cover title must be one of the configured titles",
        )
    return (
        True,
        title,
        cfg.cover_body,
        cfg.header_text,
        cfg.additional_instructions,
        cfg.footer_text,
    )


def _cover_for(
    payload: GeneratePaperRequest,
    include_cover: bool,
    title: str,
    body: str,
    total_marks: int,
    is_questions: bool,
) -> CoverSpec | None:
    """Build the cover spec for a section, or ``None`` when covers are disabled."""
    if not include_cover:
        return None
    return CoverSpec(
        title=title,
        subtitle1=payload.cover_subtitle1,
        subtitle2=payload.cover_subtitle2,
        body=body,
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


@router.post("/generate/select", response_model=SelectResponse)
def select_questions(
    payload: SelectRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Auto-select a set of questions for the given target and algorithm.

    Reuses the Browse filter suite to build the candidate pool and excludes any
    already-chosen questions. The target is either a marks total
    (``target_type="marks"``) or a question count (``target_type="count"``),
    picked with the chosen algorithm (``"random"`` or ``"in-order"``). Returns the
    selected questions (never a 404 — an empty result with a warning keeps the
    live builder UI responsive).
    """
    viewer_premium = can_view_premium(current_user)
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
    if not viewer_premium:
        # Non-premium users can't generate with premium papers, so keep them out
        # of the candidate pool entirely.
        query = query.filter(Paper.is_premium.is_(False))
    if payload.exclude_question_ids:
        query = query.filter(Question.id.notin_(payload.exclude_question_ids))

    candidates = (
        query.options(_PAPER_EAGER, selectinload(Question.pages), _TOPIC_EAGER, _SUBTOPICS_EAGER, _TAG_EAGER)
        .order_by(Question.id)
        .all()
    )

    if payload.target_type == "count":
        selected = count_select(
            candidates, payload.target_value, randomize=(payload.algorithm == "random")
        )
    elif payload.algorithm == "in-order":
        selected = in_order_select(candidates, payload.target_value)
    else:
        selected = knapsack_select(candidates, payload.target_value)

    total_marks = sum(q.marks or 0 for q in selected)
    count = len(selected)
    exact = (count == payload.target_value) if payload.target_type == "count" \
        else (total_marks == payload.target_value)

    warning = None
    if not candidates:
        warning = "No questions match the current filters."
    elif not selected:
        warning = (
            "No questions with marks match the current filters."
            if payload.target_type == "marks"
            else "No questions match the current filters."
        )
    elif not exact:
        if payload.target_type == "count":
            warning = (
                f"Could not select {payload.target_value} questions. "
                f"Only {count} match the current filters."
            )
        else:
            warning = (
                f"Could not reach exactly {payload.target_value} marks. "
                f"Closest achievable is {total_marks} marks."
            )

    return {
        "items": [serialize_list_item(q, viewer_premium) for q in selected],
        "total_marks": total_marks,
        "count": count,
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

    # Server-side paywall: non-premium users may not render premium questions,
    # even if a premium question id is posted directly (the UI already blocks it).
    if not can_view_premium(current_user) and any(q.paper.is_premium for q in ordered):
        raise HTTPException(
            status_code=403,
            detail="Premium content requires a premium subscription",
        )

    # Question paper: scale images centered within 30 mm side margins.
    # Answer paper: keep native size, flush to the left margin.
    total_marks = sum(q.marks or 0 for q in ordered)
    include_cover, title, body, header_text, additional_instructions, footer_text = (
        _resolve_generation_options(payload, current_user, db)
    )

    if payload.variant == "combined":
        q_engine = LayoutEngine(fit_width=True, show_credit=True)
        q_plan = q_engine.compute_layout(
            _blocks_for(ordered, "question"), additional_instructions=additional_instructions
        )
        q_plan.header_text = header_text
        q_plan.footer_label = footer_text
        q_plan.cover = _cover_for(payload, include_cover, title, body, total_marks, is_questions=True)
        sections = [(q_engine, q_plan)]
        a_blocks = _blocks_for(ordered, "answer")
        if a_blocks:  # no trailing blank page when nothing has answers
            a_engine = LayoutEngine(fit_width=False)
            a_plan = a_engine.compute_layout(a_blocks)
            a_plan.header_text = header_text
            a_plan.footer_label = footer_text
            a_plan.cover = _cover_for(payload, include_cover, title, body, total_marks, is_questions=False)
            sections.append((a_engine, a_plan))
        pdf = render_combined(sections, fetch_bytes=get_image_bytes)
    else:
        is_question = payload.variant == "question"
        blocks = _blocks_for(ordered, payload.variant)
        engine = LayoutEngine(fit_width=is_question, show_credit=is_question)
        instructions = additional_instructions if is_question else ""
        plan = engine.compute_layout(blocks, additional_instructions=instructions)
        plan.header_text = header_text
        plan.footer_label = footer_text
        plan.cover = _cover_for(payload, include_cover, title, body, total_marks, is_questions=is_question)
        pdf = engine.render(plan, fetch_bytes=get_image_bytes)
    return Response(content=pdf, media_type="application/pdf")
