"""Admin "Manage Papers" routes: view/edit/delete imported papers and their
questions (metadata, topics, marks, and page images)."""

from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload, selectinload

from app.db import get_db
from app.models.orm import (
    Paper,
    Question,
    QuestionPage,
    QuestionTopic,
    Subtopic,
    Topic,
)
from app.routes.auth import require_admin
from app.routes.questions import _paper_info
from app.services.ingest import delete_paper
from app.services.paper_admin import (
    apply_page_changes,
    create_question,
    delete_question,
    update_paper,
    upload_single_image,
)
from app.storage.s3_client import delete_object, get_presigned_url

router = APIRouter(prefix="/api", tags=["papers-admin"])

_VALID_PAGE_TYPES = {"question", "answer"}


# --------------------------------------------------------------------------- #
# Request models
# --------------------------------------------------------------------------- #

class PaperMetadataIn(BaseModel):
    subject_id: int
    stream_id: int
    level_id: int
    school_id: int
    exam_type_id: int
    year: int
    paper_number: str


class PageIn(BaseModel):
    id: Optional[int] = None
    temp_key: Optional[str] = None
    page_type: str
    page_order: int
    width_px: Optional[int] = None
    height_px: Optional[int] = None


class QuestionIn(BaseModel):
    question_number: int
    marks: Optional[int] = None
    subtopic_ids: List[int] = []
    pages: List[PageIn]


# --------------------------------------------------------------------------- #
# Eager-load options & serialization
# --------------------------------------------------------------------------- #

_PAPER_REFS = (
    joinedload(Paper.subject),
    joinedload(Paper.stream),
    joinedload(Paper.level),
    joinedload(Paper.school),
    joinedload(Paper.exam_type),
)

_QUESTION_EAGER = (
    selectinload(Question.pages),
    selectinload(Question.topics)
    .joinedload(QuestionTopic.subtopic)
    .joinedload(Subtopic.topic),
)


def _serialize_question(q: Question) -> dict:
    pages = sorted(q.pages, key=lambda p: (p.page_type, p.page_order))
    return {
        "id": q.id,
        "question_number": q.question_number,
        "marks": q.marks,
        "pages": [
            {
                "id": p.id,
                "page_type": p.page_type,
                "page_order": p.page_order,
                "width_px": p.width_px,
                "height_px": p.height_px,
                "url": get_presigned_url(p.image_key),
            }
            for p in pages
        ],
        "topics": [
            {
                "subtopic_id": qt.subtopic_id,
                "subtopic_name": qt.subtopic.name,
                "topic_name": qt.subtopic.topic.name,
            }
            for qt in q.topics
        ],
    }


def _reload_question(question_id: int, db: Session) -> Question:
    # Expire cached instance state so the eager loads below reflect the
    # mutations just flushed (rather than any stale identity-map collections).
    db.expire_all()
    return (
        db.query(Question)
        .options(*_QUESTION_EAGER)
        .filter(Question.id == question_id)
        .one()
    )


def _validate_pages(pages: List[PageIn], *, allow_existing: bool) -> None:
    for p in pages:
        if p.page_type not in _VALID_PAGE_TYPES:
            raise HTTPException(status_code=422, detail=f"Invalid page_type '{p.page_type}'")
        if p.id is not None:
            if not allow_existing:
                raise HTTPException(status_code=422, detail="New questions cannot reference existing pages")
        elif p.temp_key is None or p.width_px is None or p.height_px is None:
            raise HTTPException(
                status_code=422,
                detail="New pages require temp_key, width_px and height_px",
            )


def _ensure_unique_question_number(
    db: Session, paper_id: int, question_number: int, exclude_id: Optional[int] = None
) -> None:
    query = db.query(Question.id).filter(
        Question.paper_id == paper_id,
        Question.question_number == question_number,
    )
    if exclude_id is not None:
        query = query.filter(Question.id != exclude_id)
    if query.first() is not None:
        raise HTTPException(
            status_code=409,
            detail=f"Question number {question_number} already exists in this paper",
        )


def _set_topics(
    db: Session, question_id: int, subtopic_ids: List[int], subject_id: int, stream_id: int
) -> None:
    valid_ids = {
        sid
        for (sid,) in db.query(Subtopic.id)
        .join(Topic, Topic.id == Subtopic.topic_id)
        .filter(Topic.subject_id == subject_id, Topic.stream_id == stream_id)
        .all()
    }
    db.query(QuestionTopic).filter(
        QuestionTopic.question_id == question_id
    ).delete(synchronize_session=False)

    seen: set[int] = set()
    for sid in subtopic_ids:
        if sid not in valid_ids:
            raise HTTPException(status_code=422, detail=f"Invalid subtopic_id {sid}")
        if sid in seen:
            continue
        seen.add(sid)
        db.add(QuestionTopic(question_id=question_id, subtopic_id=sid))


# --------------------------------------------------------------------------- #
# Papers
# --------------------------------------------------------------------------- #

@router.get("/papers")
def list_papers(
    subject_id: Optional[int] = None,
    stream_id: Optional[int] = None,
    level_id: Optional[int] = None,
    year: Optional[int] = None,
    school_id: Optional[int] = None,
    exam_type_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 50,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(Paper)
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

    total = q.count()
    papers = (
        q.options(*_PAPER_REFS)
        .order_by(Paper.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    counts = dict(
        db.query(Question.paper_id, func.count(Question.id))
        .filter(Question.paper_id.in_([p.id for p in papers]))
        .group_by(Question.paper_id)
        .all()
    )

    items = [
        {**_paper_info(p), "question_count": counts.get(p.id, 0)}
        for p in papers
    ]
    return {"total": total, "items": items}


@router.post("/papers/upload-image")
async def upload_image(
    file: UploadFile = File(...),
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(status_code=422, detail="Only image files are accepted")
    data = await file.read()
    return upload_single_image(data)


@router.get("/papers/{paper_id}")
def get_paper(
    paper_id: int,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    paper = (
        db.query(Paper)
        .options(
            *_PAPER_REFS,
            selectinload(Paper.questions).selectinload(Question.pages),
            selectinload(Paper.questions)
            .selectinload(Question.topics)
            .joinedload(QuestionTopic.subtopic)
            .joinedload(Subtopic.topic),
        )
        .filter(Paper.id == paper_id)
        .first()
    )
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    questions = sorted(paper.questions, key=lambda q: q.question_number)
    return {
        "id": paper.id,
        "subject_id": paper.subject_id,
        "stream_id": paper.stream_id,
        "level_id": paper.level_id,
        "school_id": paper.school_id,
        "exam_type_id": paper.exam_type_id,
        "year": paper.year,
        "paper_number": paper.paper_number,
        "paper_info": _paper_info(paper),
        "questions": [_serialize_question(q) for q in questions],
    }


@router.put("/papers/{paper_id}")
def update_paper_route(
    paper_id: int,
    payload: PaperMetadataIn,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    try:
        paper = update_paper(paper_id, payload.model_dump(), db)
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Invalid metadata reference")
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")
    return {"id": paper.id, "paper_info": _paper_info(paper)}


@router.delete("/papers/{paper_id}", status_code=204)
def delete_paper_route(
    paper_id: int,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    image_keys = delete_paper(paper_id, db)
    for key in image_keys:
        try:
            delete_object(key)
        except Exception:
            pass
    return None


# --------------------------------------------------------------------------- #
# Questions
# --------------------------------------------------------------------------- #

@router.post("/papers/{paper_id}/questions", status_code=201)
def add_question_route(
    paper_id: int,
    payload: QuestionIn,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    _ensure_unique_question_number(db, paper.id, payload.question_number)
    _validate_pages(payload.pages, allow_existing=False)

    question = create_question(
        paper,
        {
            "question_number": payload.question_number,
            "marks": payload.marks,
            "pages": [p.model_dump() for p in payload.pages],
        },
        db,
    )
    _set_topics(db, question.id, payload.subtopic_ids, paper.subject_id, paper.stream_id)
    db.flush()
    return _serialize_question(_reload_question(question.id, db))


@router.put("/questions/{question_id}")
def update_question_route(
    question_id: int,
    payload: QuestionIn,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    question = (
        db.query(Question)
        .options(selectinload(Question.pages), joinedload(Question.paper))
        .filter(Question.id == question_id)
        .first()
    )
    if question is None:
        raise HTTPException(status_code=404, detail="Question not found")

    _ensure_unique_question_number(
        db, question.paper_id, payload.question_number, exclude_id=question.id
    )
    _validate_pages(payload.pages, allow_existing=True)

    paper = question.paper
    question.question_number = payload.question_number
    question.marks = payload.marks

    removed_keys = apply_page_changes(
        paper.id, question, [p.model_dump() for p in payload.pages], db
    )
    _set_topics(db, question.id, payload.subtopic_ids, paper.subject_id, paper.stream_id)
    db.flush()

    for key in removed_keys:
        try:
            delete_object(key)
        except Exception:
            pass

    return _serialize_question(_reload_question(question.id, db))


@router.delete("/questions/{question_id}", status_code=204)
def delete_question_route(
    question_id: int,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    image_keys = delete_question(question_id, db)
    if image_keys is None:
        raise HTTPException(status_code=404, detail="Question not found")
    for key in image_keys:
        try:
            delete_object(key)
        except Exception:
            pass
    return None
