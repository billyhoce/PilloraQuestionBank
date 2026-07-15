import uuid
from datetime import datetime, UTC
from typing import Any

import fitz  # PyMuPDF
from PIL import Image

from app.ai.filename_extractor import extract_metadata
from app.logger import Timer, log
from app.models.orm import Paper, Question, QuestionPage
from app.pdf.image_processing import get_dimensions, standardize, to_webp_bytes
from app.storage.s3_client import copy_only, delete_object, get_presigned_url, put_image


def pdf_to_images(pdf_bytes: bytes) -> list[Image.Image]:
    images = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=300)
            images.append(Image.frombytes("RGB", [pix.width, pix.height], pix.samples))
    return images


def upload_pages(pdf_bytes: bytes, filename: str, db: Any) -> dict:
    with Timer() as t_total:
        with Timer() as t_raster:
            images = pdf_to_images(pdf_bytes)
        log.info(f"{'upload_pages':<22}| rasterize | {t_raster.s}  ({len(images)} pages)")

        upload_id = str(uuid.uuid4())
        pages = []
        t_proc = t_s3 = 0.0

        for i, img in enumerate(images):
            with Timer() as _t:
                std = standardize(img)
                webp = to_webp_bytes(std)
                w, h = get_dimensions(std)
            t_proc += _t.elapsed

            key = f"tmp/{upload_id}/page_{i}.webp"

            with Timer() as _t:
                put_image(key, webp)
                url = get_presigned_url(key, expires_in=7200)
            t_s3 += _t.elapsed

            pages.append({
                "temp_key": key,
                "url": url,
                "dimensions": {"width": w, "height": h},
            })

        n = len(images)
        log.info(f"{'upload_pages':<22}| img_proc  | {t_proc:.3f}s  ({n} pages)")
        log.info(f"{'upload_pages':<22}| s3_upload | {t_s3:.3f}s  ({n} pages)")

        with Timer() as t_meta:
            suggested = extract_metadata(filename, db)
        log.info(f"{'upload_pages':<22}| ai_extract| {t_meta.s}")

    log.info(f"{'upload_pages':<22}| TOTAL     | {t_total.s}")
    return {"pages": pages, "suggested_metadata": suggested}


def confirm_import(payload: dict, created_by: Any, db: Any) -> Paper:
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
                marks=q_data.get("marks"),
                created_at=datetime.now(UTC),
            )
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
            pass

    return paper


def delete_paper(paper_id: int, db: Any) -> list[str]:
    """Delete a paper and its DB cascades; return S3 image keys that the caller
    should clean up after the surrounding transaction commits."""
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

    db.delete(paper)
    db.flush()
    return image_keys
