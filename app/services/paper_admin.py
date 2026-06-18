"""Service functions for the admin "Manage Papers" feature: editing paper
metadata, adding/updating/deleting questions, and editing question page images.

Image edits mirror the import pipeline's conventions: a single uploaded image is
standardized to the same WebP format used for PDF pages and parked under a
``tmp/`` key, then moved to a canonical ``papers/...`` key when the owning
question is saved.
"""

import io
import uuid
from typing import Any, Optional

from PIL import Image

from app.models.orm import Paper, Question, QuestionPage, QuestionTopic
from app.pdf.image_processing import get_dimensions, standardize, to_webp_bytes
from app.storage.s3_client import copy_only, delete_object, get_presigned_url, put_image

# Temporary range used while shuffling page_order values around so the
# unique(question_id, page_type, page_order) constraint is never violated
# mid-flush (PostgreSQL checks unique constraints per statement, not per
# transaction).
_REORDER_OFFSET = 10000


def upload_single_image(image_bytes: bytes) -> dict:
    """Standardize an uploaded image to the canonical WebP page format and stash
    it under a temp key, returning the temp key, a preview URL, and dimensions."""
    img = Image.open(io.BytesIO(image_bytes))
    img.load()
    img = img.convert("RGB")

    std = standardize(img)
    webp = to_webp_bytes(std)
    w, h = get_dimensions(std)

    upload_id = str(uuid.uuid4())
    key = f"tmp/{upload_id}/page_0.webp"
    put_image(key, webp)
    url = get_presigned_url(key, expires_in=7200)

    return {"temp_key": key, "url": url, "dimensions": {"width": w, "height": h}}


def _canonical_key(paper_id: int, question_number: int, page_type: str) -> str:
    return (
        f"papers/{paper_id}/q{question_number}"
        f"/{page_type}_{uuid.uuid4().hex[:8]}.webp"
    )


def _delete_quietly(keys: Any) -> None:
    """Best-effort delete of S3 objects; never raises."""
    for key in keys:
        try:
            delete_object(key)
        except Exception:
            pass


def commit_with_page_moves(
    db: Any, new_pairs: list[tuple[str, str]], removed_keys: list[str] = []
) -> None:
    """Make a question-page edit durable, keeping S3 transactional with the DB.

    ``new_pairs`` are ``(temp_key, canonical_key)`` for freshly uploaded pages
    whose DB rows already reference ``canonical_key``. ``removed_keys`` are the
    S3 keys of pages the edit deletes.

    Copies temp → canonical (sources left in place), commits, then settles S3.
    If a copy or the commit fails, the DB is rolled back and any canonical copy
    already written is removed, so the temp sources stay intact and the edit is
    retryable. Irreversible deletions (temp sources, removed pages) happen only
    after the DB is durable.
    """
    copied: list[str] = []
    try:
        for temp_key, canonical_key in new_pairs:
            copy_only(temp_key, canonical_key)
            copied.append(canonical_key)
        db.commit()
    except Exception:
        db.rollback()
        _delete_quietly(copied)
        raise

    _delete_quietly(temp_key for temp_key, _ in new_pairs)
    _delete_quietly(removed_keys)


def update_paper(paper_id: int, data: dict, db: Any) -> Optional[Paper]:
    """Update paper metadata. If subject or stream changes, all topic labels on
    the paper's questions are cleared (they are scoped to subject+stream).
    Returns the paper, or None if not found."""
    paper = (
        db.query(Paper)
        .filter(Paper.id == paper_id)
        .first()
    )
    if paper is None:
        return None

    subject_or_stream_changed = (
        paper.subject_id != data["subject_id"]
        or paper.stream_id != data["stream_id"]
    )

    paper.subject_id = data["subject_id"]
    paper.stream_id = data["stream_id"]
    paper.level_id = data["level_id"]
    paper.school_id = data["school_id"]
    paper.exam_type_id = data["exam_type_id"]
    paper.year = data["year"]
    paper.paper_number = data["paper_number"]

    if subject_or_stream_changed:
        question_ids = [q.id for q in paper.questions]
        if question_ids:
            db.query(QuestionTopic).filter(
                QuestionTopic.question_id.in_(question_ids)
            ).delete(synchronize_session=False)

    db.flush()
    return paper


def create_question(
    paper: Paper, data: dict, db: Any
) -> tuple[Question, list[tuple[str, str]]]:
    """Create a new question on a paper. Every page in ``data['pages']`` is a
    freshly uploaded image referenced by ``temp_key``.

    Writes the DB rows (pointing at canonical keys) but does not touch S3;
    returns the question and the ``(temp_key, canonical_key)`` pairs for the
    caller to move via :func:`commit_with_page_moves`."""
    question = Question(
        paper_id=paper.id,
        question_number=data["question_number"],
        marks=data.get("marks"),
    )
    db.add(question)
    db.flush()

    new_pairs: list[tuple[str, str]] = []
    counters: dict[str, int] = {}
    for p in data["pages"]:
        ptype = p["page_type"]
        counters[ptype] = counters.get(ptype, 0) + 1
        canonical = _canonical_key(paper.id, question.question_number, ptype)
        db.add(QuestionPage(
            question_id=question.id,
            page_order=counters[ptype],
            image_key=canonical,
            page_type=ptype,
            width_px=p["width_px"],
            height_px=p["height_px"],
        ))
        new_pairs.append((p["temp_key"], canonical))

    db.flush()
    return question, new_pairs


def apply_page_changes(
    paper_id: int, question: Question, desired: list[dict], db: Any
) -> tuple[list[str], list[tuple[str, str]]]:
    """Reconcile a question's pages against the desired ordered list.

    Each desired page is either an existing page ``{id, page_type, page_order}``
    or a new page ``{temp_key, page_type, page_order, width_px, height_px}``.
    Pages absent from the list are removed. Handles arbitrary add/replace/delete/
    reorder without ever colliding on the unique (question_id, page_type,
    page_order) constraint.

    Writes only the DB rows; returns ``(removed_keys, new_pairs)`` where
    ``removed_keys`` are the S3 keys of removed pages and ``new_pairs`` are the
    ``(temp_key, canonical_key)`` pairs of added pages, for the caller to settle
    via :func:`commit_with_page_moves`.
    """
    existing = {p.id: p for p in question.pages}
    desired_ids = {d["id"] for d in desired if d.get("id") is not None}

    # 1. Delete pages no longer present; flush so their slots are released.
    removed_keys: list[str] = []
    for pid, page in list(existing.items()):
        if pid not in desired_ids:
            removed_keys.append(page.image_key)
            db.delete(page)
    db.flush()

    survivors = {pid: p for pid, p in existing.items() if pid in desired_ids}

    # 2. Park survivors in a high page_order range to free the target slots.
    for page in survivors.values():
        page.page_order += _REORDER_OFFSET
    db.flush()

    # Compute the final per-type page_order for each desired page.
    counters: dict[str, int] = {}
    finals: list[tuple[dict, int]] = []
    for d in desired:
        ptype = d["page_type"]
        counters[ptype] = counters.get(ptype, 0) + 1
        finals.append((d, counters[ptype]))

    # 3. Insert new pages directly at their final order (slots are free).
    new_pairs: list[tuple[str, str]] = []
    for d, order in finals:
        if d.get("id") is None:
            canonical = _canonical_key(paper_id, question.question_number, d["page_type"])
            db.add(QuestionPage(
                question_id=question.id,
                page_order=order,
                image_key=canonical,
                page_type=d["page_type"],
                width_px=d["width_px"],
                height_px=d["height_px"],
            ))
            new_pairs.append((d["temp_key"], canonical))
    db.flush()

    # 4. Move survivors from the high range down to their final order. Each
    #    survivor's destination is uniquely its own, so no collision occurs.
    for d, order in finals:
        if d.get("id") is not None:
            page = survivors[d["id"]]
            page.page_type = d["page_type"]
            page.page_order = order
    db.flush()

    return removed_keys, new_pairs


def delete_question(question_id: int, db: Any) -> Optional[list[str]]:
    """Delete a question (cascades pages + topics). Returns the S3 image keys to
    clean up after commit, or None if the question was not found."""
    question = (
        db.query(Question)
        .filter(Question.id == question_id)
        .first()
    )
    if question is None:
        return None

    image_keys = [p.image_key for p in question.pages]
    db.delete(question)
    db.flush()
    return image_keys
