from typing import Optional

import anthropic
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload, selectinload

from app.ai.topic_labeler import TruncatedResponseError, label_question
from app.db import get_db
from app.logger import Timer, log
from app.models.orm import Paper, Question, Topic
from app.pdf.image_processing import downscale_for_ai
from app.routes.auth import require_admin
from app.services.ingest import confirm_import, delete_paper, upload_pages
from app.services.question_parts import scoped_topic_ids, set_question_parts, validate_parts
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


class AiPartSuggestion(BaseModel):
    # The part designation as printed, e.g. "(a)(i)"; "" for an unparted question.
    label: str = ""
    marks: Optional[int] = None
    selections: list[AiTopicSelection] = []


class AiTopicsResponse(BaseModel):
    parts: list[AiPartSuggestion] = []


class TopicAssignment(BaseModel):
    topic_id: int
    subtopics: list[SubtopicSuggestion] = []


class PartIn(BaseModel):
    # Bounded to the width of question_part.label so an over-long label is
    # rejected with a 422 rather than silently truncated on the way in.
    label: str = Field("", max_length=32)
    marks: Optional[int] = None
    topic_assignments: list[TopicAssignment] = []


class QuestionPartsIn(BaseModel):
    question_id: int
    parts: list[PartIn] = []


class SaveTopicsPayload(BaseModel):
    paper_id: int
    questions: list[QuestionPartsIn]


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
        except TruncatedResponseError as e:
            log.error(f"{'ai_topics':<22}| truncated | question_id={payload.question_id} {e}")
            raise HTTPException(
                status_code=502,
                detail="The AI response was cut off — please retry this question.",
            )
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
    return {"parts": result["parts"]}


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
    requested_ids = {qp.question_id for qp in payload.questions}
    if not requested_ids.issubset(paper_question_ids):
        raise HTTPException(status_code=422, detail="One or more questions do not belong to this paper")

    valid_topic_ids = scoped_topic_ids(db, paper.subject_id, paper.stream_id)

    # Validate every question's parts before writing any of them, so a 422 on
    # the last question doesn't leave the earlier ones half-rewritten.
    for qp in payload.questions:
        validate_parts(db, qp.parts, valid_topic_ids)

    # set_question_parts re-validates each question — deliberately, so it is safe
    # to call on its own from the single-question admin routes. The repeat costs
    # nothing here: the Subtopic rows it checks are already in the identity map.
    for qp in payload.questions:
        set_question_parts(db, qp.question_id, qp.parts, valid_topic_ids)

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
