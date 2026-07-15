import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db import get_db
from app.routes.auth import can_view_premium, get_current_user_optional
from app.models.orm import (
    ExamType,
    Level,
    Paper,
    Question,
    QuestionPage,
    QuestionSubtopic,
    QuestionTag,
    QuestionTopic,
    School,
    SchoolLevel,
    Stream,
    Subject,
    Subtopic,
    Tag,
    Topic,
    User,
)
from app.schemas.questions import QuestionDetailResponse, QuestionListResponse
from app.storage.s3_client import get_presigned_url

router = APIRouter(prefix="/api", tags=["questions"])


def _apply_filters(
    q,
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
    paper_number=None,
):
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

    if topic_ids:
        q = q.filter(
            Question.topics.any(QuestionTopic.topic_id.in_(topic_ids))
        )
        if exclusive:
            q = q.filter(
                ~Question.topics.any(QuestionTopic.topic_id.notin_(topic_ids))
            )

    if tag_ids:
        q = q.filter(
            Question.tags.any(QuestionTag.tag_id.in_(tag_ids))
        )

    if paper_number:
        pn = paper_number.strip()
        if pn:
            # Exact, case-insensitive match (no wildcards). Paper numbers are short
            # strings that may contain letters, e.g. "1", "2", "a", "b".
            q = q.filter(Paper.paper_number.ilike(pn))

    if search:
        kw = search.strip()
        if kw:
            pattern = f"%{kw}%"
            clauses = [
                Question.topics.any(
                    QuestionTopic.topic.has(Topic.name.ilike(pattern))
                ),
                Question.question_subtopics.any(
                    QuestionSubtopic.subtopic.has(Subtopic.name.ilike(pattern))
                ),
                Question.tags.any(
                    QuestionTag.tag.has(Tag.name.ilike(pattern))
                ),
                Paper.school.has(School.name.ilike(pattern)),
                Paper.subject.has(Subject.name.ilike(pattern)),
                Paper.level.has(Level.name.ilike(pattern)),
                Paper.level.has(
                    Level.school_level.has(SchoolLevel.name.ilike(pattern))
                ),
                Paper.stream.has(Stream.name.ilike(pattern)),
                Paper.stream.has(
                    Stream.school_level.has(SchoolLevel.name.ilike(pattern))
                ),
                Paper.exam_type.has(ExamType.name.ilike(pattern)),
            ]
            # A "T{n}" token (e.g. "T10") matches the topic number.
            m = re.fullmatch(r"[Tt]\s*(\d+)", kw)
            if m:
                clauses.append(
                    Question.topics.any(
                        QuestionTopic.topic.has(
                            Topic.topic_number == int(m.group(1))
                        )
                    )
                )
            if kw.isdigit():
                clauses.append(Paper.year == int(kw))
            q = q.filter(or_(*clauses))

    return q


def _paper_info(paper: Paper) -> dict:
    return {
        "id": paper.id,
        "year": paper.year,
        "paper_number": paper.paper_number,
        "is_premium": paper.is_premium,
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


def _topic_infos(question: Question) -> list[dict]:
    if not question.topics:
        return []
    subtopics_by_topic: dict[int, list[str]] = {}
    for qs in question.question_subtopics:
        subtopics_by_topic.setdefault(qs.topic_id, []).append(qs.subtopic.name)
    return [
        {
            "topic_name": qt.topic.name,
            "topic_number": qt.topic.topic_number,
            "subtopic_names": subtopics_by_topic.get(qt.topic_id, []),
        }
        for qt in question.topics
    ]


def _tag_infos(question: Question) -> list[dict]:
    return [
        {"id": qt.tag.id, "name": qt.tag.name}
        for qt in question.tags
    ]


def serialize_list_item(q: Question, can_view_premium: bool = True) -> dict:
    """Build a QuestionListItem dict for a question (with eager-loaded relations).

    When the question belongs to a premium paper and the viewer isn't entitled
    (``can_view_premium`` is False), the image URL is withheld and ``locked`` is
    set so the frontend shows a paywall placeholder instead of the image.
    """
    locked = q.paper.is_premium and not can_view_premium
    return {
        "id": q.id,
        "question_number": q.question_number,
        "marks": q.marks,
        "paper_info": _paper_info(q.paper),
        "topics": _topic_infos(q),
        "tags": _tag_infos(q),
        "first_page_url": None if locked else _first_page_url(q),
        "locked": locked,
    }


_PAPER_EAGER = selectinload(Question.paper).options(
    joinedload(Paper.subject),
    joinedload(Paper.stream),
    joinedload(Paper.level),
    joinedload(Paper.school),
    joinedload(Paper.exam_type),
)
_TOPIC_EAGER = selectinload(Question.topics).options(
    joinedload(QuestionTopic.topic),
)
_SUBTOPICS_EAGER = selectinload(Question.question_subtopics).options(
    joinedload(QuestionSubtopic.subtopic),
)
_TAG_EAGER = selectinload(Question.tags).options(
    joinedload(QuestionTag.tag),
)


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
    total = _apply_filters(base, *filter_args).count()

    questions = (
        _apply_filters(base, *filter_args)
        .options(_PAPER_EAGER, selectinload(Question.pages), _TOPIC_EAGER, _SUBTOPICS_EAGER, _TAG_EAGER)
        .order_by(Question.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [serialize_list_item(q, viewer_premium) for q in questions]

    return {"total": total, "items": items}


@router.get("/questions/{question_id}", response_model=QuestionDetailResponse)
def get_question(
    question_id: int,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    question = (
        db.query(Question)
        .filter(Question.id == question_id)
        .options(joinedload(Question.paper), selectinload(Question.pages), _TOPIC_EAGER, _SUBTOPICS_EAGER, _TAG_EAGER)
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
            "url": None if locked else get_presigned_url(p.image_key),
        }

    sorted_pages = sorted(question.pages, key=lambda p: (p.page_type, p.page_order))
    return {
        "id": question.id,
        "question_number": question.question_number,
        "marks": question.marks,
        "question_pages": [_page_dict(p) for p in sorted_pages if p.page_type == "question"],
        "answer_pages": [_page_dict(p) for p in sorted_pages if p.page_type == "answer"],
        "topics": _topic_infos(question),
        "tags": _tag_infos(question),
        "locked": locked,
    }
