from typing import Optional

import anthropic
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload, selectinload

from app.ai.topic_labeler import label_question
from app.db import get_db
from app.logger import Timer, log
from app.models.orm import Paper, Question, QuestionSubtopic, QuestionTopic, Subtopic, Topic
from app.pdf.image_processing import downscale_for_ai
from app.routes.auth import require_admin
from app.services.ingest import confirm_import, delete_paper, upload_pages
from app.storage.s3_client import delete_object, get_image_bytes, get_presigned_url



router = APIRouter(prefix="/api/import", tags=["import"])


class PageIn(BaseModel):
    temp_key: str
    page_type: str
    page_order: int
    width_px: int
    height_px: int


class QuestionIn(BaseModel):
    question_number: int
    marks: Optional[int] = None
    pages: list[PageIn]


class ConfirmImportPayload(BaseModel):
    subject_id: int
    stream_id: int
    level_id: int
    school_id: int
    exam_type_id: int
    year: int
    paper_number: str
    # Imported papers are premium by default; the admin can untick this at the
    # final import step.
    is_premium: bool = True
    questions: list[QuestionIn]


class AiTopicsRequest(BaseModel):
    question_id: int


class SubtopicSuggestion(BaseModel):
    subtopic_id: int


class AiTopicSelection(BaseModel):
    topic_id: int
    subtopic_id: Optional[int] = None


class AiTopicsResponse(BaseModel):
    selections: list[AiTopicSelection] = []
    marks: Optional[int] = None


class TopicAssignment(BaseModel):
    topic_id: int
    subtopics: list[SubtopicSuggestion] = []


class QuestionTopicsIn(BaseModel):
    question_id: int
    marks: Optional[int] = None
    topic_assignments: list[TopicAssignment]


class SaveTopicsPayload(BaseModel):
    paper_id: int
    question_topics: list[QuestionTopicsIn]


@router.post("/upload-pdf")
async def upload_pdf(
    file: UploadFile = File(...),
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=422, detail="Only PDF files are accepted")
    with Timer() as t:
        pdf_bytes = await file.read()
        result = upload_pages(pdf_bytes, file.filename or "", db)
    log.info(f"{'upload_pdf':<22}| TOTAL     | {t.s}")
    return result


def _serialize_paper_questions(paper: Paper) -> list[dict]:
    return [
        {
            "id": q.id,
            "question_number": q.question_number,
            "marks": q.marks,
            "pages": [
                {
                    "page_order": p.page_order,
                    "page_type": p.page_type,
                    "width_px": p.width_px,
                    "height_px": p.height_px,
                    "url": get_presigned_url(p.image_key),
                }
                for p in sorted(q.pages, key=lambda p: (p.page_type, p.page_order))
            ],
        }
        for q in sorted(paper.questions, key=lambda q: q.question_number)
    ]


@router.post("/confirm", status_code=201)
def confirm(
    payload: ConfirmImportPayload,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    paper = confirm_import(payload.model_dump(), current_user, db)
    paper = (
        db.query(Paper)
        .options(selectinload(Paper.questions).selectinload(Question.pages))
        .filter(Paper.id == paper.id)
        .first()
    )
    return {
        "paper_id": paper.id,
        "questions": _serialize_paper_questions(paper),
    }


@router.post("/ai-topics", response_model=AiTopicsResponse)
def ai_topics(
    payload: AiTopicsRequest,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    with Timer() as t_total:
        with Timer() as t_db:
            question = (
                db.query(Question)
                .options(
                    selectinload(Question.pages),
                    joinedload(Question.paper).joinedload(Paper.subject),
                    joinedload(Question.paper).joinedload(Paper.stream),
                )
                .filter(Question.id == payload.question_id)
                .first()
            )
        log.info(f"{'ai_topics':<22}| db_query  | {t_db.s}")

        if question is None:
            raise HTTPException(status_code=404, detail="Question not found")

        paper = question.paper
        with Timer() as t_topics:
            topics_orm = (
                db.query(Topic)
                .options(selectinload(Topic.subtopics))
                .filter(Topic.subject_id == paper.subject_id, Topic.stream_id == paper.stream_id)
                .order_by(Topic.topic_number)
                .all()
            )
        log.info(f"{'ai_topics':<22}| db_topics | {t_topics.s}")

        topics = [
            {
                "id": t.id,
                "name": t.name,
                "topic_number": t.topic_number,
                "subtopics": [{"id": s.id, "name": s.name} for s in t.subtopics],
            }
            for t in topics_orm
        ]

        question_pages = [p for p in question.pages if p.page_type == "question"]
        n = len(question_pages)

        t_s3 = 0.0
        raw_list = []
        for p in question_pages:
            with Timer() as _t:
                raw_list.append(get_image_bytes(p.image_key))
            t_s3 += _t.elapsed
        log.info(f"{'ai_topics':<22}| s3_fetch  | {t_s3:.3f}s  ({n} pages)")

        t_ds = 0.0
        image_bytes_list = []
        for raw in raw_list:
            with Timer() as _t:
                image_bytes_list.append(downscale_for_ai(raw))
            t_ds += _t.elapsed
        log.info(f"{'ai_topics':<22}| downscale | {t_ds:.3f}s  ({n} pages)")

        try:
            with Timer() as t_label:
                result = label_question(question, topics, image_bytes_list)
            log.info(f"{'ai_topics':<22}| ai_label  | {t_label.s}")
        except anthropic.RateLimitError as e:
            log.error(f"{'ai_topics':<22}| rate_limit| question_id={payload.question_id} {e}")
            raise HTTPException(
                status_code=429,
                detail="AI topic labeling is rate limited — please retry in a moment.",
            )
        except anthropic.APIError as e:
            log.error(f"{'ai_topics':<22}| api_error | question_id={payload.question_id} {e}")
            raise HTTPException(
                status_code=503,
                detail="AI topic labeling is temporarily unavailable — please retry.",
            )

    log.info(f"{'ai_topics':<22}| TOTAL     | {t_total.s}")
    return {"selections": result["selections"], "marks": result["marks"]}


@router.post("/save-topics", status_code=201)
def save_topics(
    payload: SaveTopicsPayload,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    paper = (
        db.query(Paper)
        .options(selectinload(Paper.questions))
        .filter(Paper.id == payload.paper_id)
        .first()
    )
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    paper_question_ids = {q.id for q in paper.questions}
    requested_ids = {qt.question_id for qt in payload.question_topics}
    if not requested_ids.issubset(paper_question_ids):
        raise HTTPException(status_code=422, detail="One or more questions do not belong to this paper")

    valid_topic_ids = {
        tid for (tid,) in db.query(Topic.id)
        .filter(Topic.subject_id == paper.subject_id, Topic.stream_id == paper.stream_id)
        .all()
    }

    # Phase 1: validate all assignments before any writes so a 422 leaves
    # the DB unchanged (no half-written state).
    for qt in payload.question_topics:
        for assignment in qt.topic_assignments:
            if assignment.topic_id not in valid_topic_ids:
                raise HTTPException(status_code=422, detail=f"Invalid topic_id {assignment.topic_id}")
            for s in assignment.subtopics:
                subtopic = db.get(Subtopic, s.subtopic_id)
                if subtopic is None or subtopic.topic_id != assignment.topic_id:
                    raise HTTPException(
                        status_code=422,
                        detail=f"subtopic_id {s.subtopic_id} does not belong to topic_id {assignment.topic_id}",
                    )

    # Phase 2: delete existing assignments for all questions in this paper.
    db.query(QuestionSubtopic).filter(QuestionSubtopic.question_id.in_(paper_question_ids)).delete(synchronize_session=False)
    db.query(QuestionTopic).filter(QuestionTopic.question_id.in_(paper_question_ids)).delete(synchronize_session=False)

    # Phase 3: update marks and insert new assignments.
    questions_by_id = {q.id: q for q in paper.questions}
    for qt in payload.question_topics:
        questions_by_id[qt.question_id].marks = qt.marks

        inserted_topic_ids: set[int] = set()
        for assignment in qt.topic_assignments:
            if assignment.topic_id not in inserted_topic_ids:
                db.add(QuestionTopic(question_id=qt.question_id, topic_id=assignment.topic_id))
                db.flush()  # composite FK on question_subtopic requires this row to exist first
                inserted_topic_ids.add(assignment.topic_id)

            seen_subtopic_ids: set[int] = set()
            for s in assignment.subtopics:
                if s.subtopic_id in seen_subtopic_ids:
                    continue
                seen_subtopic_ids.add(s.subtopic_id)
                db.add(QuestionSubtopic(
                    question_id=qt.question_id,
                    subtopic_id=s.subtopic_id,
                    topic_id=assignment.topic_id,
                ))

    db.flush()
    return {"message": "Topics saved"}


@router.delete("/papers/{paper_id}", status_code=204)
def delete_paper_route(
    paper_id: int,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    image_keys = delete_paper(paper_id, db)
    # Commit the DB deletion before performing irreversible S3 deletions, so a
    # failed commit can't leave paper rows pointing at already-deleted images.
    db.commit()
    for key in image_keys:
        try:
            delete_object(key)
        except Exception:
            pass
    return None
