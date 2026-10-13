import uuid
from datetime import datetime, UTC
from collections.abc import Callable, Iterator
from typing import Any

import fitz  # PyMuPDF
from PIL import Image

from app.ai.filename_extractor import extract_metadata
from app.logger import Timer, log, log_event, log_job_event
from app.models.orm import IngestJob, Paper, Question, QuestionPage, QuestionPart
from app.services.ingest_events import add_event
from app.pdf.image_processing import get_dimensions, standardize, to_webp_bytes
from app.storage.s3_client import copy_only, delete_object, get_presigned_url, put_image


def iter_pdf_pages(pdf_bytes: bytes) -> Iterator[Image.Image]:
    """Yield each page as a 300 dpi RGB image, rendering lazily.

    A 300 dpi A4 page is ~26 MB, so an 80-page booklet held at once is ~2 GB.
    The pixmap is released as soon as its pixels are copied into the PIL image,
    and the next page is not rendered until the caller asks for it.
    """
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=300)
            try:
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            finally:
                del pix
            yield img
            # The suspended generator frame would otherwise keep this page alive
            # while the next one is rendered.
            del img


def upload_pages(
    pdf_bytes: bytes, filename: str, db: Any, suggested_metadata: dict | None = None
) -> dict:
    """Render ``pdf_bytes`` into temp page images. ``suggested_metadata`` (already known, e.g.
    from an auto-import job) skips the filename extraction."""
    with Timer() as t_total:
        upload_id = str(uuid.uuid4())
        pages = []
        t_raster = t_proc = t_s3 = 0.0

        # Render, standardise and upload one page at a time, dropping every
        # reference to a page before the next is rendered (see iter_pdf_pages).
        page_iter = iter_pdf_pages(pdf_bytes)
        i = 0
        while True:
            with Timer() as _t:
                img = next(page_iter, None)
            t_raster += _t.elapsed
            if img is None:
                break

            with Timer() as _t:
                std = standardize(img)
                webp = to_webp_bytes(std)
                w, h = get_dimensions(std)
            t_proc += _t.elapsed
            del img, std

            key = f"tmp/{upload_id}/page_{i}.webp"

            with Timer() as _t:
                put_image(key, webp)
                url = get_presigned_url(key, expires_in=7200)
            t_s3 += _t.elapsed
            del webp

            pages.append({
                "temp_key": key,
                "url": url,
                "dimensions": {"width": w, "height": h},
            })
            i += 1

        n = len(pages)
        log_event("upload_pages", "rasterize", seconds=round(t_raster, 3), pages=n)
        log_event("upload_pages", "img_proc", seconds=round(t_proc, 3), pages=n)
        log_event("upload_pages", "s3_upload", seconds=round(t_s3, 3), pages=n)

        with Timer() as t_meta:
            suggested = (
                suggested_metadata
                if suggested_metadata is not None
                else extract_metadata(filename, db)
            )
        log_event("upload_pages", "ai_extract", seconds=t_meta.s)

    log_event("upload_pages", "total", seconds=t_total.s)
    return {"pages": pages, "suggested_metadata": suggested}


def confirm_import(
    payload: dict,
    created_by: Any,
    db: Any,
    before_commit: Callable[[Paper], None] | None = None,
) -> Paper:
    """Create the paper and its images. ``before_commit(paper)``, if given, runs after the S3
    copies and just before the commit, so whatever it writes (e.g. ``source_job_id`` and a job
    outcome) commits in the same transaction as the paper; if it raises, nothing is committed."""
    try:
        paper = Paper(
            subject_id=payload["subject_id"],
            stream_id=payload["stream_id"],
            level_id=payload["level_id"],
            school_id=payload["school_id"],
            exam_type_id=payload["exam_type_id"],
            year=payload["year"],
            paper_number=payload["paper_number"],
            is_premium=payload.get("is_premium", True),
            created_by=created_by.id,
            created_at=datetime.now(UTC),
        )
        db.add(paper)
        db.flush()

        pages_to_move: list[tuple[str, str]] = []
        for q_data in payload["questions"]:
            question = Question(
                question_number=q_data["question_number"],
                section=q_data.get("section"),
                proposal_question_index=q_data.get("proposal_question_index"),
                created_at=datetime.now(UTC),
            )
            # Topics and marks arrive later, at the topic-review step; until then
            # the question holds the single blank part every question must have.
            question.parts.append(QuestionPart(part_order=0, label="", marks=None))
            paper.questions.append(question)

            for p_data in q_data["pages"]:
                canonical_key = (
                    f"papers/{paper.id}/q{q_data['question_number']}"
                    f"/{p_data['page_type']}_{p_data['page_order']}.webp"
                )
                question.pages.append(QuestionPage(
                    page_order=p_data["page_order"],
                    image_key=canonical_key,
                    page_type=p_data["page_type"],
                    width_px=p_data["width_px"],
                    height_px=p_data["height_px"],
                    source_page=p_data.get("source_page"),
                    source_rect=p_data.get("source_rect"),
                ))
                pages_to_move.append((p_data["temp_key"], canonical_key))

        db.flush()
    except Exception:
        db.rollback()
        raise

    # Copy temp uploads to their canonical keys WITHOUT deleting the sources,
    # then commit, then delete the sources. This keeps the S3 move transactional
    # with the DB write:
    #   - If a copy fails partway, or the commit fails, the temp sources are
    #     still intact (so the import is retryable) and we delete any canonical
    #     objects already written so they don't leak.
    #   - Source deletion happens only after the DB is durable, so a failure
    #     there can at worst orphan a temp object, never a committed paper.
    copied_keys: list[str] = []
    try:
        for temp_key, canonical_key in pages_to_move:
            copy_only(temp_key, canonical_key)
            copied_keys.append(canonical_key)
        if before_commit is not None:
            before_commit(paper)
        db.commit()
    except Exception:
        db.rollback()
        for key in copied_keys:
            try:
                delete_object(key)
            except Exception:
                pass
        raise

    for temp_key, _ in pages_to_move:
        try:
            delete_object(temp_key)
        except Exception:
            log.warning("confirm_import/temp_delete_failed key=%s", temp_key, exc_info=True)

    return paper


def delete_paper(paper_id: int, db: Any, actor: Any = None) -> list[str]:
    """Delete a paper and its DB cascades; return S3 image keys that the caller
    should clean up after the surrounding transaction commits. When the paper came from an
    auto-import job (``source_job_id``, or the job's ``confirmed_paper_ids``) a ``paper_deleted``
    event is logged against that job."""
    paper = (
        db.query(Paper)
        .filter(Paper.id == paper_id)
        .first()
    )
    if paper is None:
        return []

    image_keys: list[str] = [
        page.image_key for question in paper.questions for page in question.pages
    ]

    job_ids = {paper.source_job_id} if paper.source_job_id is not None else set()
    job_ids |= {
        j.id for j in db.query(IngestJob).filter(IngestJob.confirmed_paper_ids.isnot(None))
        if paper_id in (j.confirmed_paper_ids or [])
    }
    details = dict(
        paper_id=paper_id, year=paper.year, paper_number=paper.paper_number,
        school_id=paper.school_id, questions=len(paper.questions), images=len(image_keys),
    )

    db.delete(paper)
    db.flush()
    for job_id in sorted(job_ids, key=str):
        add_event(db, job_id, "paper_deleted", actor_user_id=getattr(actor, "id", None), **details)
        log_job_event(job_id, "paper_deleted", user_id=getattr(actor, "id", None), **details)
    db.flush()
    return image_keys
