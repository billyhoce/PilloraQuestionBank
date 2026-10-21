import uuid
from typing import Literal, Optional

import anthropic
from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, joinedload, selectinload

from app.ai.topic_labeler import TruncatedResponseError
from app.db import get_db
from app.deps import (
    ImageFetcher,
    get_image_fetcher,
    get_object_store,
    get_question_labeller,
)
from app.log_context import set_context
from app.services.ingest_events import add_event
from app.logger import Timer, log, log_event, log_job_event
from app.models.orm import INGEST_JOB_STATUSES, IngestJob, IngestPaper, Paper, Question, Topic
from app.pdf.image_processing import downscale_for_ai
from app.routes.auth import require_admin
from app.services.ingest import confirm_import, delete_paper, upload_pages
from app.services.answer_coverage import job_coverage
from app.services.ingest_matching import match_info, match_row
from app.services.ingest_papers import (
    MatchError,
    get_row as get_paper_row,
    link_papers,
    paper_links,
    reject_proposed_paper,
    set_metadata as set_paper_metadata,
    sync_job_papers,
    unlink_paper,
)
from app.services.match_candidates import find_candidates
from app.services.ingest_confirm import ReviewActionError, attach_answers, confirm_job_paper, skip_job_paper
from app.services.ingest_jobs import (
    InvalidPdfError,
    JobNotCancellableError,
    JobNotRetryableError,
    UploadError,
    cancel_job,
    create_upload,
    finish_upload,
    job_progress,
    retry_job,
    worker_state,
)
from app.services.ingest_review import (
    NoProposalError,
    ProposalEditError,
    PageRangeError,
    build_review,
    extract_page_range,
    save_edited_proposal,
)
from app.services.paper_admin import school_level_conflict
from app.services.question_parts import scoped_topic_ids, set_question_parts, validate_parts
from app.storage.object_store import ObjectStore
from app.storage.s3_client import delete_object, get_presigned_url



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


class PaperMetadataIn(BaseModel):
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


class ConfirmImportPayload(PaperMetadataIn):
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
def upload_pdf(
    file: UploadFile = File(...),
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=422, detail="Only PDF files are accepted")
    with Timer() as t:
        pdf_bytes = file.file.read()
        result = upload_pages(pdf_bytes, file.filename or "", db)
    log_event("upload_pdf", "total", seconds=t.s)
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


def _confirm_response(db: Session, paper_id: int) -> dict:
    paper = (
        db.query(Paper)
        .options(selectinload(Paper.questions).selectinload(Question.pages))
        .filter(Paper.id == paper_id)
        .first()
    )
    return {
        "paper_id": paper.id,
        "questions": _serialize_paper_questions(paper),
    }


@router.post("/confirm", status_code=201)
def confirm(
    payload: ConfirmImportPayload,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    # A paper's premium group comes from its level's school level, so a stream
    # from a different school level would gate it to the wrong customers.
    conflict = school_level_conflict(db, payload.stream_id, payload.level_id)
    if conflict:
        raise HTTPException(status_code=422, detail=conflict)

    paper = confirm_import(payload.model_dump(), current_user, db)
    return _confirm_response(db, paper.id)


@router.post("/ai-topics", response_model=AiTopicsResponse)
def ai_topics(
    payload: AiTopicsRequest,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
    fetch_bytes: ImageFetcher = Depends(get_image_fetcher),
    label_question=Depends(get_question_labeller),
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
        log_event("ai_topics", "db_query", seconds=t_db.s)

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
        log_event("ai_topics", "db_topics", seconds=t_topics.s)

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
                raw_list.append(fetch_bytes(p.image_key))
            t_s3 += _t.elapsed
        log_event("ai_topics", "s3_fetch", seconds=round(t_s3, 3), pages=n)

        t_ds = 0.0
        image_bytes_list = []
        for raw in raw_list:
            with Timer() as _t:
                image_bytes_list.append(downscale_for_ai(raw))
            t_ds += _t.elapsed
        log_event("ai_topics", "downscale", seconds=round(t_ds, 3), pages=n)

        try:
            with Timer() as t_label:
                result = label_question(question, topics, image_bytes_list)
            log_event("ai_topics", "ai_label", seconds=t_label.s)
        except TruncatedResponseError as e:
            log.error("ai_topics/truncated question_id=%s: %s", payload.question_id, e)
            raise HTTPException(
                status_code=502,
                detail="The AI response was cut off — please retry this question.",
            )
        except anthropic.RateLimitError as e:
            log.error("ai_topics/rate_limit question_id=%s: %s", payload.question_id, e)
            raise HTTPException(
                status_code=429,
                detail="AI topic labeling is rate limited — please retry in a moment.",
            )
        except anthropic.APIError as e:
            log.error("ai_topics/api_error question_id=%s: %s", payload.question_id, e)
            raise HTTPException(
                status_code=503,
                detail="AI topic labeling is temporarily unavailable — please retry.",
            )

    log_event("ai_topics", "total", seconds=t_total.s)
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
    image_keys = delete_paper(paper_id, db, current_user)
    # Commit the DB deletion before performing irreversible S3 deletions, so a
    # failed commit can't leave paper rows pointing at already-deleted images.
    db.commit()
    for key in image_keys:
        try:
            delete_object(key)
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Auto-import jobs
# ---------------------------------------------------------------------------


def _task_out(t) -> dict:
    return {
        "id": t.id,
        "section": t.section,
        "stage": t.stage,
        "status": t.status,
        "attempts": t.attempts,
        "reason": t.reason,
        "error": t.error,
        "traceback": t.traceback,
        "warnings": t.warnings,
        "needs_review": t.needs_review,
        "started_at": t.started_at,
        "finished_at": t.finished_at,
        "duration_ms": t.duration_ms,
    }


def _job_out(job: IngestJob) -> dict:
    return {
        "id": str(job.id),
        "filename": job.filename,
        "status": job.status,
        "page_count": job.page_count,
        "error": job.error,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "confirmed_paper_ids": job.confirmed_paper_ids,
        **job_progress(job),
    }


def _paper_summary(row: IngestPaper, coverage: dict | None = None) -> dict:
    """One proposed paper as the job list shows it: enough for an at-a-glance review queue card.
    ``answer_coverage`` (``none``/``partial``/``all``, of its own answer boxes) and ``unanswered``
    (its question numbers without one) come from the job's current proposal."""
    coverage = coverage or {"answer_coverage": "none", "unanswered": []}
    return {
        "key": row.paper_key,
        "role": row.role,
        "status": row.status,
        "school_id": row.school_id,
        "new_school_name": row.new_school_name,
        "year": row.year,
        "level_id": row.level_id,
        "subject_id": row.subject_id,
        "exam_type_id": row.exam_type_id,
        "stream_id": row.stream_id,
        "paper_number": row.paper_number,
        "linked": row.matched_ingest_paper_id is not None,
        "match_status": row.match_status,
        **coverage,
    }


def _papers_by_job(db: Session, jobs: list[IngestJob]) -> dict:
    """Each job's ``ingest_paper`` rows (one query for the whole list), in paper-key order."""
    by_job: dict = {j.id: [] for j in jobs}
    if not by_job:
        return by_job
    rows = (
        db.query(IngestPaper)
        .filter(IngestPaper.job_id.in_(list(by_job)))
        .order_by(IngestPaper.job_id, IngestPaper.paper_key)
        .all()
    )
    coverage = {j.id: job_coverage(j) for j in jobs}
    for r in rows:
        by_job[r.job_id].append(_paper_summary(r, coverage[r.job_id].get(r.paper_key)))
    return by_job


def _get_own_job(db: Session, job_id: uuid.UUID, user) -> IngestJob:
    """The job to act on. Every route here is admin-only and admins are trusted with each other's
    jobs, so any admin may open or act on any job; a non-admin (unreachable through these routes)
    would still be limited to their own."""
    q = db.query(IngestJob).filter(IngestJob.id == job_id)
    if getattr(user, "role", None) != "admin":
        q = q.filter(IngestJob.created_by == user.id)
    job = q.first()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    set_context(job_id=str(job.id), user_id=str(user.id))
    return job


class UploadIn(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    size: int


@router.post("/uploads", status_code=201)
def create_ingest_upload(
    body: UploadIn,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
):
    """Create the job (``awaiting_upload``) and return the presigned S3 POST the browser uploads to."""
    try:
        job, post = create_upload(body.filename, body.size, current_user, db, store)
    except UploadError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    set_context(job_id=str(job.id), user_id=str(current_user.id))
    return {"job_id": str(job.id), "url": post["url"], "fields": post["fields"]}


@router.post("/jobs/{job_id}/uploaded")
def ingest_upload_finished(
    job_id: uuid.UUID,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
):
    """The browser finished its S3 POST: verify the object and queue the job."""
    job = _get_own_job(db, job_id, current_user)
    try:
        finish_upload(job, current_user, db, store)
    except UploadError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)
    return {"job_id": str(job.id), "status": job.status}


@router.get("/jobs")
def list_ingest_jobs(
    status: Optional[str] = None,
    job_id: Optional[uuid.UUID] = None,
    paper_id: Optional[int] = None,
    unmatched_answers: bool = False,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Every admin's jobs, optionally narrowed by status (one, or several comma-separated), job id, or a paper id (the job that
    confirmed that paper, by ``paper.source_job_id`` or the job's recorded ``confirmed_paper_ids``), or to the jobs
    with an answer-only paper still pending and linked to no question paper (``unmatched_answers``)."""
    statuses = [s.strip() for s in status.split(",")] if status is not None else None
    if statuses is not None and any(s not in INGEST_JOB_STATUSES for s in statuses):
        raise HTTPException(status_code=422, detail="Unknown job status")
    q = db.query(IngestJob).options(selectinload(IngestJob.tasks))
    if statuses is not None:
        q = q.filter(IngestJob.status.in_(statuses))
    if job_id is not None:
        q = q.filter(IngestJob.id == job_id)
    if paper_id is not None:
        # confirmed_paper_ids is INT[] on Postgres and JSON on SQLite, so match it in Python.
        ids = {
            j for j, in db.query(Paper.source_job_id).filter(Paper.id == paper_id, Paper.source_job_id.isnot(None))
        }
        ids |= {j.id for j in db.query(IngestJob).filter(IngestJob.confirmed_paper_ids.isnot(None))
                if paper_id in (j.confirmed_paper_ids or [])}
        q = q.filter(IngestJob.id.in_(ids))
    if unmatched_answers:
        q = q.filter(
            db.query(IngestPaper.id)
            .filter(
                IngestPaper.job_id == IngestJob.id,
                IngestPaper.role == "answer_only",
                IngestPaper.status == "pending",
                IngestPaper.matched_ingest_paper_id.is_(None),
            )
            .exists()
        )
    jobs = q.order_by(IngestJob.created_at.desc(), IngestJob.id).all()
    papers = _papers_by_job(db, jobs)
    return {"data": [{**_job_out(j), "papers": papers[j.id]} for j in jobs], **worker_state(db)}


@router.get("/jobs/{job_id}")
def get_ingest_job(
    job_id: uuid.UUID,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    job = _get_own_job(db, job_id, current_user)
    return {
        **_job_out(job),
        "report": job.report,
        "tasks": [_task_out(t) for t in job.tasks],
        **worker_state(db),
    }


@router.post("/jobs/{job_id}/retry")
def retry_ingest_job(
    job_id: uuid.UUID,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    job = _get_own_job(db, job_id, current_user)
    try:
        reopened = retry_job(job, db, current_user)
    except JobNotRetryableError as e:
        raise HTTPException(status_code=409, detail=e.reason)
    db.refresh(job)
    return {**_job_out(job), "reopened": reopened}


@router.delete("/jobs/{job_id}", status_code=204)
def cancel_ingest_job(
    job_id: uuid.UUID,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
):
    job = _get_own_job(db, job_id, current_user)
    try:
        prefix = cancel_job(job, db, current_user)
    except JobNotCancellableError as e:
        raise HTTPException(status_code=409, detail=f"A {e.status} job cannot be cancelled")
    # Commit the status change before the irreversible S3 delete, as the paper
    # delete does; a failed delete only orphans temp objects.
    db.commit()
    try:
        store.delete_prefix(prefix)
    except Exception:
        log.error("cancel_ingest_job/s3_delete failed prefix=%s", prefix)
    return None


@router.get("/jobs/{job_id}/review")
def review_ingest_job(
    job_id: uuid.UUID,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
):
    job = _get_own_job(db, job_id, current_user)
    try:
        review = build_review(job, store)
    except NoProposalError:
        raise HTTPException(status_code=409, detail="This job has no proposal to review yet")
    # Papers linked to a paper of another job (by key), for the "linked to ..." note.
    # ``proposals``: automatic matches of answer-only papers to confirmed papers, by key (#83).
    return {**review, "matches": paper_links(db, job), "proposals": match_info(db, job)}


@router.put("/jobs/{job_id}/proposal")
def save_proposal(
    job_id: uuid.UUID,
    payload: dict = Body(...),
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Save the admin's corrections as ``proposal_edited`` (the original ``proposal`` is kept).
    Body: ``{"papers": [{"questions": [...], "orphan_answers": [...]}, ...]}``, one entry per
    proposal paper; everything else is taken from the original."""
    job = _get_own_job(db, job_id, current_user)
    if job.status != "review_ready":
        raise HTTPException(status_code=409, detail=f"A {job.status} job's proposal cannot be edited")
    try:
        save_edited_proposal(job, payload)
    except NoProposalError:
        raise HTTPException(status_code=409, detail="This job has no proposal to edit yet")
    except ProposalEditError as e:
        raise HTTPException(status_code=422, detail=str(e))
    add_event(db, job.id, "proposal_edited", actor_user_id=current_user.id)
    db.commit()
    log_job_event(job.id, "proposal_saved", edited=True)
    return {"saved": True}


class ManualPagesIn(BaseModel):
    first_page: int
    last_page: int


@router.post("/jobs/{job_id}/manual-pages")
def manual_pages(
    job_id: uuid.UUID,
    payload: ManualPagesIn,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
):
    """Hand a page range of the job's source PDF to the Manual import flow: the same
    ``{pages, suggested_metadata}`` the Manual flow's own PDF upload returns."""
    job = _get_own_job(db, job_id, current_user)
    try:
        pdf = extract_page_range(store.get(job.source_key), payload.first_page, payload.last_page)
    except PageRangeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except InvalidPdfError as e:
        raise HTTPException(status_code=422, detail=str(e))
    report = job.report or {}
    # An old job has one filename guess; a newer one has one entry per paper (take the first).
    metadata = report.get("filename_metadata") or next(iter((report.get("paper_metadata") or {}).values()), None)
    return upload_pages(pdf, job.filename, db, suggested_metadata=metadata)


class JobConfirmIn(PaperMetadataIn):
    # Which proposal paper: its question label, else its answer label (see paper_key).
    paper_label: str
    # A school not in the list yet (#87): give its name instead of school_id; confirm creates it.
    school_id: Optional[int] = None
    new_school_name: Optional[str] = Field(None, max_length=128)


class PaperMetadataEditIn(BaseModel):
    """The review sidebar's seven fields as the admin has them so far; any may be unset.
    ``new_school_name`` is a school typed that is not in the list yet (used when ``school_id`` is
    unset; a name equal to an existing school resolves to it)."""

    school_id: Optional[int] = None
    new_school_name: Optional[str] = Field(None, max_length=128)
    year: Optional[int] = None
    level_id: Optional[int] = None
    subject_id: Optional[int] = None
    exam_type_id: Optional[int] = None
    stream_id: Optional[int] = None
    paper_number: Optional[str] = None


@router.put("/jobs/{job_id}/papers/{paper_key}/metadata")
def save_paper_metadata(
    job_id: uuid.UUID,
    paper_key: str,
    payload: PaperMetadataEditIn,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Record the admin's edits to one paper's metadata on its ``ingest_paper`` row (source
    ``admin`` when a value changed). Called as the admin edits the review sidebar."""
    job = _get_own_job(db, job_id, current_user)
    if job.status != "review_ready":
        raise HTTPException(status_code=409, detail=f"A {job.status} job's metadata cannot be edited")
    db.refresh(job, with_for_update=True)
    row = get_paper_row(db, job, paper_key) or (sync_job_papers(db, job) and get_paper_row(db, job, paper_key))
    if row is None:
        raise HTTPException(status_code=404, detail=f"This job has no paper {paper_key!r}")
    if row.status != "pending":
        raise HTTPException(status_code=409, detail=f"Paper {paper_key!r} was already {row.status}")
    set_paper_metadata(db, job, paper_key, payload.model_dump())
    match_row(db, row)  # the key may now match (or stop matching) a confirmed paper
    db.commit()
    return {"saved": True, "metadata_source": row.metadata_source, "proposal": match_info(db, job).get(paper_key)}


@router.get("/jobs/{job_id}/papers/{paper_key}/candidates")
def paper_candidates(
    job_id: uuid.UUID,
    paper_key: str,
    school_id: Optional[int] = None,
    new_school_name: Optional[str] = None,
    year: Optional[int] = None,
    level_id: Optional[int] = None,
    subject_id: Optional[int] = None,
    exam_type_id: Optional[int] = None,
    stream_id: Optional[int] = None,
    paper_number: Optional[str] = None,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
):
    """"Match this paper": the booklets this paper could be paired with, ranked against the given
    fields (blank = any) as ``{exact, best}``. See ``app.services.match_candidates``."""
    job = _get_own_job(db, job_id, current_user)
    row = get_paper_row(db, job, paper_key) or (sync_job_papers(db, job) and get_paper_row(db, job, paper_key))
    if row is None:
        raise HTTPException(status_code=404, detail=f"This job has no paper {paper_key!r}")
    query = {
        "school_id": school_id, "new_school_name": new_school_name, "year": year, "level_id": level_id,
        "subject_id": subject_id, "exam_type_id": exam_type_id, "stream_id": stream_id, "paper_number": paper_number,
    }
    return find_candidates(db, store, row, query)


class JobMatchIn(BaseModel):
    ingest_paper_id: int
    # "Also update this paper's details": saved on this paper in the same transaction.
    metadata: Optional[PaperMetadataEditIn] = None


@router.post("/jobs/{job_id}/papers/{paper_key}/match")
def match_job_paper(
    job_id: uuid.UUID,
    paper_key: str,
    payload: JobMatchIn,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Pair a pending paper with a pending paper of the other role (answer-only <-> question), of
    another review-ready job or this one (both rows get each other's id in
    ``matched_ingest_paper_id``), optionally saving this paper's ``metadata`` first. Nothing is
    attached yet; confirming the question paper settles the pair. The response is what this paper
    has now."""
    job = _get_own_job(db, job_id, current_user)
    if job.status != "review_ready":
        raise HTTPException(status_code=409, detail=f"A {job.status} job's papers cannot be matched")
    db.refresh(job, with_for_update=True)
    try:
        metadata = payload.metadata.model_dump() if payload.metadata is not None else None
        link_papers(db, job, paper_key, payload.ingest_paper_id, metadata)
    except MatchError as e:
        db.rollback()
        raise HTTPException(status_code=e.status, detail=e.message)
    db.commit()
    return _match_state(db, job, paper_key)


def _match_state(db: Session, job, paper_key: str) -> dict:
    """What matching now offers one paper: its link (``matches``) and its proposal."""
    return {"matches": paper_links(db, job).get(paper_key), "proposal": match_info(db, job).get(paper_key)}


@router.delete("/jobs/{job_id}/papers/{paper_key}/match")
def unmatch_job_paper(
    job_id: uuid.UUID,
    paper_key: str,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Unmatch: remove a paper's link (on both sides) and reject that pair, so automatic matching
    never re-makes it. Both papers are re-matched; the response is what this paper has now."""
    job = _get_own_job(db, job_id, current_user)
    db.refresh(job, with_for_update=True)
    try:
        unlink_paper(db, job, paper_key)
    except MatchError as e:
        db.rollback()
        raise HTTPException(status_code=e.status, detail=e.message)
    db.commit()
    return _match_state(db, job, paper_key)


@router.delete("/jobs/{job_id}/papers/{paper_key}/proposed-paper")
def reject_job_paper_proposal(
    job_id: uuid.UUID,
    paper_key: str,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
):
    """"Not this one": reject an answer-only paper's proposed confirmed paper and re-run matching,
    which may propose or link something else. The response is what this paper has now."""
    job = _get_own_job(db, job_id, current_user)
    if job.status != "review_ready":
        raise HTTPException(status_code=409, detail=f"A {job.status} job's papers cannot be matched")
    db.refresh(job, with_for_update=True)
    try:
        reject_proposed_paper(db, job, paper_key)
    except MatchError as e:
        db.rollback()
        raise HTTPException(status_code=e.status, detail=e.message)
    db.commit()
    return _match_state(db, job, paper_key)


class JobSkipIn(BaseModel):
    paper_label: str


@router.post("/jobs/{job_id}/confirm", status_code=201)
def confirm_job(
    job_id: uuid.UUID,
    payload: JobConfirmIn,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
):
    """Confirm one proposed paper of a reviewed job: crop its rectangles from ``source.pdf``,
    run ``confirm_import``, and answer like ``/confirm`` (plus ``job_status``) so the topic-review
    step follows unchanged."""
    job = _get_own_job(db, job_id, current_user)
    conflict = school_level_conflict(db, payload.stream_id, payload.level_id)
    if conflict:
        raise HTTPException(status_code=422, detail=conflict)
    metadata = payload.model_dump(exclude={"paper_label"})
    answers: dict = {}
    try:
        paper, settled = confirm_job_paper(
            job, payload.paper_label, metadata, current_user, db, store, answers_info=answers
        )
    except ReviewActionError as e:
        db.rollback()
        raise HTTPException(status_code=e.status, detail=e.message)
    return {
        **_confirm_response(db, paper.id), "job_status": "confirmed" if settled else "review_ready",
        "answers_from": answers.get("answers_from"), "unmatched": answers.get("unmatched", []),
    }


@router.post("/jobs/{job_id}/skip")
def skip_job(
    job_id: uuid.UUID,
    payload: JobSkipIn,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
):
    """Skip one proposed paper; the job is ``confirmed`` once every paper is confirmed or skipped."""
    job = _get_own_job(db, job_id, current_user)
    try:
        settled = skip_job_paper(job, payload.paper_label, db, store, current_user)
    except ReviewActionError as e:
        db.rollback()
        raise HTTPException(status_code=e.status, detail=e.message)
    return {"job_status": "confirmed" if settled else "review_ready"}


class JobAttachIn(BaseModel):
    key: str
    paper_id: int
    mode: Optional[Literal["append", "replace"]] = None


@router.post("/jobs/{job_id}/attach")
def attach_job(
    job_id: uuid.UUID,
    payload: JobAttachIn,
    current_user=Depends(require_admin),
    db: Session = Depends(get_db),
    store: ObjectStore = Depends(get_object_store),
):
    """Attach an answer-only paper's answers to an existing paper, matched by question number.
    Omitting ``mode`` replaces a question's answers when it has none and appends otherwise.
    Answers whose number matches no question are returned as ``unmatched``."""
    job = _get_own_job(db, job_id, current_user)
    try:
        result = attach_answers(job, payload.key, payload.paper_id, payload.mode, current_user, db, store)
    except ReviewActionError as e:
        db.rollback()
        raise HTTPException(status_code=e.status, detail=e.message)
    return {**result, "job_status": "confirmed" if result["job_settled"] else "review_ready"}
