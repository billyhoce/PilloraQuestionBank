from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload

from app.ai.topic_labeler import label_question
from app.db import get_db
from app.models.orm import Paper, Question, Topic
from app.routes.auth import require_admin
from app.services.ingest import confirm_import, upload_pages
from app.storage.s3_client import get_image_bytes, get_presigned_url

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
    questions: list[QuestionIn]


class AiTopicsRequest(BaseModel):
    paper_id: int


@router.post("/upload-pdf")
async def upload_pdf(
    file: UploadFile = File(...),
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=422, detail="Only PDF files are accepted")
    pdf_bytes = await file.read()
    return upload_pages(pdf_bytes, file.filename or "", db)


@router.post("/confirm", status_code=201)
def confirm(
    payload: ConfirmImportPayload,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    paper = confirm_import(payload.model_dump(), current_user, db)
    return {"paper_id": paper.id}


@router.post("/ai-topics")
def ai_topics(
    payload: AiTopicsRequest,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    paper = (
        db.query(Paper)
        .options(
            selectinload(Paper.questions).selectinload(Question.pages),
            selectinload(Paper.subject),
            selectinload(Paper.stream),
        )
        .filter(Paper.id == payload.paper_id)
        .first()
    )
    if paper is None:
        raise HTTPException(status_code=404, detail="Paper not found")

    topics_orm = (
        db.query(Topic)
        .options(selectinload(Topic.subtopics))
        .filter(Topic.subject_id == paper.subject_id, Topic.stream_id == paper.stream_id)
        .all()
    )
    topics = [
        {
            "id": t.id,
            "name": t.name,
            "subtopics": [{"id": s.id, "name": s.name} for s in t.subtopics],
        }
        for t in topics_orm
    ]

    for question in paper.questions:
        question_pages = [p for p in question.pages if p.page_type == "question"]
        image_bytes_list = [get_image_bytes(p.image_key) for p in question_pages]
        label_question(question, topics, image_bytes_list, db)

    return {"message": "Topics labeled"}
