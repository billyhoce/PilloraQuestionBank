from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db import get_db
from app.models.orm import (
    Paper,
    Question,
    QuestionPage,
    QuestionTopic,
    Subtopic,
    User,
)
from app.routes.auth import get_current_user
from app.schemas.questions import QuestionDetailResponse, QuestionListResponse
from app.storage.s3_client import get_presigned_url

router = APIRouter(prefix="/api", tags=["questions"])


def _apply_filters(q, subject_id, stream_id, level_id, year, school_id, exam_type_id, topic_id, subtopic_id):
    if subject_id is not None:
        q = q.filter(Paper.subject_id == subject_id)
    if stream_id is not None:
        q = q.filter(Paper.stream_id == stream_id)
    if level_id is not None:
        q = q.filter(Paper.level_id == level_id)
    if year is not None:
        q = q.filter(Paper.year == year)
    if school_id is not None:
        q = q.filter(Paper.school_id == school_id)
    if exam_type_id is not None:
        q = q.filter(Paper.exam_type_id == exam_type_id)
    if topic_id is not None or subtopic_id is not None:
        q = q.join(QuestionTopic, QuestionTopic.question_id == Question.id)
        if topic_id is not None:
            q = q.join(Subtopic, Subtopic.id == QuestionTopic.subtopic_id).filter(Subtopic.topic_id == topic_id)
        if subtopic_id is not None:
            q = q.filter(QuestionTopic.subtopic_id == subtopic_id)
    return q


def _paper_info(paper: Paper) -> dict:
    return {
        "id": paper.id,
        "year": paper.year,
        "paper_number": paper.paper_number,
        "subject_name": paper.subject.name,
        "stream_name": paper.stream.name,
        "level_name": paper.level.name,
        "school_name": paper.school.name,
        "exam_type_name": paper.exam_type.name,
    }


def _first_page_url(question: Question) -> Optional[str]:
    pages = sorted(
        [p for p in question.pages if p.page_type == "question"],
        key=lambda p: p.page_order,
    )
    if not pages:
        return None
    try:
        return get_presigned_url(pages[0].image_key)
    except Exception:
        return None


_PAPER_EAGER = selectinload(Question.paper).options(
    joinedload(Paper.subject),
    joinedload(Paper.stream),
    joinedload(Paper.level),
    joinedload(Paper.school),
    joinedload(Paper.exam_type),
)
_TOPICS_EAGER = selectinload(Question.topics).options(
    joinedload(QuestionTopic.subtopic).joinedload(Subtopic.topic),
)


@router.get("/questions", response_model=QuestionListResponse)
def list_questions(
    subject_id: Optional[int] = None,
    stream_id: Optional[int] = None,
    level_id: Optional[int] = None,
    year: Optional[int] = None,
    school_id: Optional[int] = None,
    exam_type_id: Optional[int] = None,
    topic_id: Optional[int] = None,
    subtopic_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    filter_args = (subject_id, stream_id, level_id, year, school_id, exam_type_id, topic_id, subtopic_id)

    base = db.query(Question).join(Question.paper)
    total = _apply_filters(base.distinct(), *filter_args).count()

    questions = (
        _apply_filters(base.distinct(), *filter_args)
        .options(_PAPER_EAGER, selectinload(Question.pages), _TOPICS_EAGER)
        .order_by(Question.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [
        {
            "id": q.id,
            "question_number": q.question_number,
            "marks": q.marks,
            "paper_info": _paper_info(q.paper),
            "topics": [
                {"topic_name": qt.subtopic.topic.name, "subtopic_name": qt.subtopic.name}
                for qt in q.topics
            ],
            "first_page_url": _first_page_url(q),
        }
        for q in questions
    ]

    return {"total": total, "items": items}


@router.get("/questions/{question_id}", response_model=QuestionDetailResponse)
def get_question(
    question_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    question = (
        db.query(Question)
        .filter(Question.id == question_id)
        .options(selectinload(Question.pages), _TOPICS_EAGER)
        .one_or_none()
    )
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    def _page_dict(p: QuestionPage) -> dict:
        return {
            "id": p.id,
            "page_order": p.page_order,
            "page_type": p.page_type,
            "width_px": p.width_px,
            "height_px": p.height_px,
            "url": get_presigned_url(p.image_key),
        }

    sorted_pages = sorted(question.pages, key=lambda p: (p.page_type, p.page_order))
    return {
        "id": question.id,
        "question_number": question.question_number,
        "marks": question.marks,
        "question_pages": [_page_dict(p) for p in sorted_pages if p.page_type == "question"],
        "answer_pages": [_page_dict(p) for p in sorted_pages if p.page_type == "answer"],
        "topics": [
            {"topic_name": qt.subtopic.topic.name, "subtopic_name": qt.subtopic.name}
            for qt in question.topics
        ],
    }
