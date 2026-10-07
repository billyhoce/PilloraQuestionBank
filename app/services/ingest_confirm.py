"""Confirming (or skipping) one proposed paper of an auto-import job.

The admin's reviewed rectangles (``proposal_edited`` if there is one, else ``proposal``) are
cropped out of the job's ``source.pdf`` into page images and handed to the Manual flow's own
``confirm_import``, unchanged. See docs/features/ingestion.md ("Confirming a paper").
"""

import uuid
from collections.abc import Callable
from typing import Any

import fitz  # PyMuPDF
from PIL import Image

from app.logger import log
from app.models.orm import IngestJob, Paper
from app.pdf.image_processing import get_dimensions, standardize, to_webp_bytes
from app.services.ingest import confirm_import
from app.services.ingest_jobs import job_prefix
from app.storage.object_store import ObjectStore
from app.storage.s3_client import delete_object, put_image

CROP_DPI = 300


class ReviewActionError(Exception):
    """A confirm/skip the job's state or the paper does not allow; ``status`` is the HTTP code."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def paper_key(paper: dict, index: int) -> str:
    """What identifies a proposal paper in the API: its question label (``q1``), else its answer
    label (``a1``) for an answer-only paper (``label: null``), else its 1-based position. Question
    and answer labels come from different sections, so a key never clashes."""
    return paper.get("label") or paper.get("answer_label") or f"paper{index + 1}"


def effective_proposal(job: IngestJob) -> dict:
    proposal = job.proposal_edited if job.proposal_edited is not None else job.proposal
    if proposal is None:
        raise ReviewActionError(409, "This job has no proposal to confirm yet")
    return proposal


def outcomes(job: IngestJob) -> dict[str, str]:
    return dict((job.report or {}).get("review_outcome") or {})


def _find_paper(job: IngestJob, key: str) -> dict:
    for i, paper in enumerate(effective_proposal(job).get("papers", [])):
        if paper_key(paper, i) == key:
            return paper
    raise ReviewActionError(404, f"This job has no paper {key!r}")


def _check_open(job: IngestJob, key: str) -> None:
    if job.status != "review_ready":
        raise ReviewActionError(409, f"A {job.status} job cannot be confirmed")
    done = outcomes(job).get(key)
    if done:
        raise ReviewActionError(409, f"Paper {key!r} was already {done}")


def render_crop(page: "fitz.Page", rect: dict) -> tuple[bytes, int, int]:
    """One rectangle (PDF points) as a standardised WebP: ``(bytes, width_px, height_px)``.
    The pixmap and the PIL images are released before returning."""
    pix = page.get_pixmap(dpi=CROP_DPI, clip=fitz.Rect(rect["x0"], rect["y0"], rect["x1"], rect["y1"]))
    try:
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    finally:
        del pix
    std = standardize(img)
    webp = to_webp_bytes(std)
    w, h = get_dimensions(std)
    del img, std
    return webp, w, h


def build_confirm_payload(
    pdf_bytes: bytes,
    paper: dict,
    metadata: dict,
    put: Callable[[str, bytes], None] = put_image,
    upload_id: str | None = None,
) -> tuple[dict, list[str]]:
    """Render every rectangle of ``paper`` one at a time, upload it to
    ``tmp/{upload_id}/page_{n}.webp`` with ``put`` and return ``(payload, temp_keys)``, the
    payload being what ``confirm_import`` takes.

    Each proposal question becomes one payload question (``question_number`` = its number); its
    ``question_rects`` become ``question`` pages and its ``answer_rects`` ``answer`` pages, in
    list order, ``page_order`` counting from 1 per type like the Manual flow. Orphan answers are
    not imported. On a failure the images already uploaded are deleted again."""
    upload_id = upload_id or str(uuid.uuid4())
    keys: list[str] = []
    questions = []
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            n = 0
            for q in paper["questions"]:
                pages = []
                for page_type, rects in (("question", q["question_rects"]), ("answer", q["answer_rects"])):
                    for order, rect in enumerate(rects, start=1):
                        if not 1 <= rect["page"] <= doc.page_count:
                            raise ReviewActionError(422, f"Question {q['number']} uses page {rect['page']}, which the PDF lacks")
                        webp, w, h = render_crop(doc[rect["page"] - 1], rect)
                        key = f"tmp/{upload_id}/page_{n}.webp"
                        put(key, webp)
                        keys.append(key)
                        del webp
                        n += 1
                        pages.append({
                            "temp_key": key, "page_type": page_type, "page_order": order,
                            "width_px": w, "height_px": h,
                        })
                questions.append({"question_number": q["number"], "pages": pages})
    except Exception:
        _delete_quietly(keys)
        raise
    return {**metadata, "questions": questions}, keys


def _delete_quietly(keys: list[str]) -> None:
    for key in keys:
        try:
            delete_object(key)
        except Exception:
            pass


def _record(job: IngestJob, key: str, outcome: str, paper_id: int | None) -> bool:
    """Store one paper's outcome on the job; returns True when that settles the whole job."""
    done = {**outcomes(job), key: outcome}
    job.report = {**(job.report or {}), "review_outcome": done}
    if paper_id is not None:
        job.confirmed_paper_ids = [*(job.confirmed_paper_ids or []), paper_id]
    papers = effective_proposal(job).get("papers", [])
    settled = bool(papers) and all(paper_key(p, i) in done for i, p in enumerate(papers))
    if settled:
        job.status = "confirmed"
    return settled


def _drop_job_objects(job_id: uuid.UUID, store: ObjectStore) -> None:
    prefix = job_prefix(job_id)
    try:
        store.delete_prefix(prefix)
    except Exception:
        log.error(f"{'confirm_job_paper':<22}| s3_delete | prefix={prefix}")


def confirm_job_paper(
    job: IngestJob, key: str, metadata: dict, admin: Any, db: Any, store: ObjectStore
) -> tuple[Paper, bool]:
    """Create the paper for proposal paper ``key``. Returns ``(paper, job_settled)``."""
    db.refresh(job, with_for_update=True)  # serialise two clicks on the same paper
    _check_open(job, key)
    paper_data = _find_paper(job, key)
    if not paper_data.get("questions"):
        raise ReviewActionError(422, f"Paper {key!r} has no questions to import; skip it instead")
    payload, _ = build_confirm_payload(store.get(job.source_key), paper_data, metadata)
    job_id = job.id
    paper = confirm_import(payload, admin, db)  # commits
    paper.source_job_id = job_id
    settled = _record(job, key, "confirmed", paper.id)
    db.commit()
    if settled:
        _drop_job_objects(job_id, store)
    return paper, settled


def skip_job_paper(job: IngestJob, key: str, db: Any, store: ObjectStore) -> bool:
    """Mark proposal paper ``key`` skipped. Returns whether that settles the job."""
    db.refresh(job, with_for_update=True)
    _check_open(job, key)
    _find_paper(job, key)
    job_id = job.id
    settled = _record(job, key, "skipped", None)
    db.commit()
    if settled:
        _drop_job_objects(job_id, store)
    return settled
