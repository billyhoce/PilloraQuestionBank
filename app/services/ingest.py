import uuid
from datetime import datetime
from typing import Any

import pdf2image
from PIL import Image

from app.ai.filename_extractor import extract_metadata
from app.models.orm import Paper, Question, QuestionPage
from app.pdf.image_processing import get_dimensions, standardize, to_webp_bytes
from app.storage.s3_client import copy_object, put_image


def pdf_to_images(pdf_bytes: bytes) -> list[Image.Image]:
    return pdf2image.convert_from_bytes(pdf_bytes)


def upload_pages(pdf_bytes: bytes, filename: str, db: Any) -> dict:
    images = pdf_to_images(pdf_bytes)
    upload_id = str(uuid.uuid4())
    pages = []
    for i, img in enumerate(images):
        std = standardize(img)
        webp = to_webp_bytes(std)
        w, h = get_dimensions(std)
        key = f"tmp/{upload_id}/page_{i}.webp"
        put_image(key, webp)
        pages.append({"temp_key": key, "dimensions": {"width": w, "height": h}})
    suggested = extract_metadata(filename, db)
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
            created_by=created_by.id,
            created_at=datetime.utcnow(),
        )
        db.add(paper)
        db.flush()

        pages_to_move: list[tuple[str, str]] = []
        for q_data in payload["questions"]:
            question = Question(
                paper_id=paper.id,
                question_number=q_data["question_number"],
                marks=q_data.get("marks"),
                created_at=datetime.utcnow(),
            )
            db.add(question)
            db.flush()

            for p_data in q_data["pages"]:
                canonical_key = (
                    f"papers/{paper.id}/q{q_data['question_number']}"
                    f"/{p_data['page_type']}_{p_data['page_order']}.webp"
                )
                db.add(QuestionPage(
                    question_id=question.id,
                    page_order=p_data["page_order"],
                    image_key=canonical_key,
                    page_type=p_data["page_type"],
                    width_px=p_data["width_px"],
                    height_px=p_data["height_px"],
                ))
                pages_to_move.append((p_data["temp_key"], canonical_key))

        for temp_key, canonical_key in pages_to_move:
            copy_object(temp_key, canonical_key)

        return paper
    except Exception:
        db.rollback()
        raise
