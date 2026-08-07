from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models.orm import CoverTitle, Paper, Question, User
from app.pdf.layout_engine import (
    Block,
    CoverSpec,
    LayoutEngine,
    LayoutPlan,
    PageChrome,
    render_combined,
)
from app.routes.auth import get_current_user
from app.deps import ImageFetcher, Presigner, get_image_fetcher, get_presigner
from app.services.question_query import (
    PAPER_EAGER,
    PARTS_EAGER,
    TAG_EAGER,
    apply_filters,
)
from app.services.question_serialization import serialize_list_item
from app.schemas.generate import (
    GeneratePaperRequest,
    SelectRequest,
    SelectResponse,
)
from app.services.generate import count_select, in_order_select, knapsack_select
from app.services.generation_config import get_or_create_config
from app.services.premium import can_view_paper, premium_gate, restrict_premium_pool

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


@dataclass(frozen=True)
class ResolvedGenerationOptions:
    """The generation settings actually used for a render, after role rules.

    A named record rather than a tuple: the four text fields below are all
    ``str`` and all get stamped somewhere on the PDF, so a positional unpack
    could transpose the header with the footer without any type error — and the
    mistake would only show up by eye, in generated output.
    """

    include_cover: bool
    title: str
    body: str
    header_text: str
    additional_instructions: str
    footer_text: str


def _resolve_generation_options(
    payload: GeneratePaperRequest, current_user: User, db: Session
) -> ResolvedGenerationOptions:
    """Resolve the effective generation options for this user.

    Admins control every field verbatim, including the page-header branding —
    except that an omitted ``header_text`` (``None``) falls back to the config
    preset, so a client that never loaded the config still gets the branding. An
    explicit ``""`` prints no header. For non-admin users the admin-set
    generation config wins: a cover page is always included, the
    body/header/instructions/footer come from the config, and the title must be
    one of the configured cover titles — an empty title falls back to the first
    configured one (so generation still works if the client never loaded the
    config), and an unknown title is rejected so the dropdown can't be bypassed
    with a hand-crafted request. With no titles configured the cover is untitled.
    """
    cfg = get_or_create_config(db)
    if current_user.role == "admin":
        return ResolvedGenerationOptions(
            include_cover=payload.include_cover,
            title=payload.cover_title,
            body=payload.cover_body,
            header_text=(
                cfg.header_text if payload.header_text is None else payload.header_text
            ),
            additional_instructions=payload.additional_instructions,
            footer_text=payload.footer_text,
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
    return ResolvedGenerationOptions(
        include_cover=True,
        title=title,
        body=cfg.cover_body,
        header_text=cfg.header_text,
        additional_instructions=cfg.additional_instructions,
        footer_text=cfg.footer_text,
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
    presign: Presigner = Depends(get_presigner),
):
    """Auto-select a set of questions for the given target and algorithm.

    Reuses the Browse filter suite to build the candidate pool and excludes any
    already-chosen questions. The target is either a marks total
    (``target_type="marks"``) or a question count (``target_type="count"``),
    picked with the chosen algorithm (``"random"`` or ``"in-order"``). Returns the
    selected questions (never a 404 — an empty result with a warning keeps the
    live builder UI responsive).
    """
    gate = premium_gate(current_user)
    f = payload.filters
    # Level is joined explicitly (rather than reached through `.has()` like the
    # browse filters do) because the premium pool restriction filters on it.
    base = db.query(Question).join(Question.paper).join(Paper.level)
    query = apply_filters(
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
    # A user can only generate with premium papers in the school levels they
    # hold, so the rest never enter the candidate pool.
    query = restrict_premium_pool(query, current_user)
    if payload.exclude_question_ids:
        query = query.filter(Question.id.notin_(payload.exclude_question_ids))

    candidates = (
        query.options(PAPER_EAGER, selectinload(Question.pages), PARTS_EAGER, TAG_EAGER)
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

    total_marks = sum(q.total_marks or 0 for q in selected)
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
        "items": [serialize_list_item(q, presign, gate) for q in selected],
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
    fetch_bytes: ImageFetcher = Depends(get_image_fetcher),
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
        .options(PAPER_EAGER, selectinload(Question.pages))
        .all()
    )
    by_id = {q.id: q for q in rows}
    ordered = [by_id[qid] for qid in payload.question_ids if qid in by_id]

    # Server-side paywall: a user may not render a premium question outside the
    # school levels they hold, even if its id is posted directly (the UI already
    # blocks it).
    if any(not can_view_paper(current_user, q.paper) for q in ordered):
        raise HTTPException(
            status_code=403,
            detail="Premium content requires a premium subscription",
        )

    total_marks = sum(q.total_marks or 0 for q in ordered)
    opts = _resolve_generation_options(payload, current_user, db)

    def section(is_question: bool) -> tuple[LayoutEngine, "LayoutPlan"]:
        """Build one section's (engine, plan).

        Question paper: images scaled and centered within 30 mm side margins,
        credited, and carrying the instructions. Answer paper: native size,
        flush to the left margin, no credit line, no instructions.
        """
        engine = LayoutEngine(fit_width=is_question, show_credit=is_question)
        plan = engine.compute_layout(
            _blocks_for(ordered, "question" if is_question else "answer"),
            additional_instructions=opts.additional_instructions if is_question else "",
            chrome=PageChrome(
                header_text=opts.header_text,
                footer_label=opts.footer_text,
                cover=_cover_for(
                    payload,
                    opts.include_cover,
                    opts.title,
                    opts.body,
                    total_marks,
                    is_questions=is_question,
                ),
            ),
        )
        return engine, plan

    if payload.variant == "combined":
        sections = [section(is_question=True)]
        a_engine, a_plan = section(is_question=False)
        if a_plan.blocks:  # no trailing blank page when nothing has answers
            sections.append((a_engine, a_plan))
        pdf = render_combined(sections, fetch_bytes=fetch_bytes)
    else:
        engine, plan = section(is_question=payload.variant == "question")
        pdf = engine.render(plan, fetch_bytes=fetch_bytes)
    return Response(content=pdf, media_type="application/pdf")
