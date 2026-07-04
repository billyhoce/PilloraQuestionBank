from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, selectinload

from app.db import get_db
from app.models.orm import Question, User
from app.pdf.layout_engine import LayoutEngine  # noqa: F401  (used by the deferred PDF route)
from app.routes.auth import get_current_user
from app.routes.questions import (
    _PAPER_EAGER,
    _SUBTOPICS_EAGER,
    _TOPIC_EAGER,
    _apply_filters,
    serialize_list_item,
)
from app.schemas.generate import SelectRequest, SelectResponse
from app.services.generate import knapsack_select
from app.storage.s3_client import get_image_bytes, get_presigned_url  # noqa: F401  (deferred PDF route)

router = APIRouter(prefix="/api", tags=["generation"])


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
        f.subtopic_keyword,
    )
    if payload.exclude_question_ids:
        query = query.filter(Question.id.notin_(payload.exclude_question_ids))

    candidates = (
        query.options(_PAPER_EAGER, selectinload(Question.pages), _TOPIC_EAGER, _SUBTOPICS_EAGER)
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
