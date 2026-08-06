from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db import get_db
from app.deps import Presigner, get_presigner
from app.models.orm import Question, QuestionPage, User
from app.routes.auth import can_view_premium, get_current_user_optional
from app.schemas.questions import QuestionDetailResponse, QuestionListResponse
from app.services.question_query import (
    PAPER_EAGER,
    PARTS_EAGER,
    TAG_EAGER,
    apply_filters,
)
from app.services.question_serialization import (
    part_infos,
    serialize_list_item,
    tag_infos,
    topic_infos,
)

router = APIRouter(prefix="/api", tags=["questions"])


@router.get("/questions", response_model=QuestionListResponse)
def list_questions(
    subject_id: Optional[int] = None,
    stream_id: Optional[int] = None,
    level_id: Optional[int] = None,
    year: Optional[int] = None,
    school_id: Optional[int] = None,
    exam_type_id: Optional[int] = None,
    topic_ids: List[int] = Query(default=[]),
    exclusive: bool = False,
    tag_ids: List[int] = Query(default=[]),
    search: Optional[str] = None,
    paper_number: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
    presign: Presigner = Depends(get_presigner),
):
    viewer_premium = can_view_premium(current_user)
    filter_args = (
        subject_id,
        stream_id,
        level_id,
        year,
        school_id,
        exam_type_id,
        topic_ids,
        exclusive,
        tag_ids,
        search,
        paper_number,
    )

    base = db.query(Question).join(Question.paper)
    total = apply_filters(base, *filter_args).count()

    questions = (
        apply_filters(base, *filter_args)
        .options(PAPER_EAGER, selectinload(Question.pages), PARTS_EAGER, TAG_EAGER)
        .order_by(Question.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [serialize_list_item(q, presign, viewer_premium) for q in questions]

    return {"total": total, "items": items}


@router.get("/questions/{question_id}", response_model=QuestionDetailResponse)
def get_question(
    question_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
    presign: Presigner = Depends(get_presigner),
):
    question = (
        db.query(Question)
        .filter(Question.id == question_id)
        .options(joinedload(Question.paper), selectinload(Question.pages), PARTS_EAGER, TAG_EAGER)
        .one_or_none()
    )
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    locked = question.paper.is_premium and not can_view_premium(current_user)

    def _page_dict(p: QuestionPage) -> dict:
        return {
            "id": p.id,
            "page_order": p.page_order,
            "page_type": p.page_type,
            "width_px": p.width_px,
            "height_px": p.height_px,
            "url": None if locked else presign(p.image_key),
        }

    sorted_pages = sorted(question.pages, key=lambda p: (p.page_type, p.page_order))
    return {
        "id": question.id,
        "question_number": question.question_number,
        "marks": question.total_marks,
        "question_pages": [_page_dict(p) for p in sorted_pages if p.page_type == "question"],
        "answer_pages": [_page_dict(p) for p in sorted_pages if p.page_type == "answer"],
        "topics": topic_infos(question),
        "parts": part_infos(question),
        "tags": tag_infos(question),
        "locked": locked,
    }
