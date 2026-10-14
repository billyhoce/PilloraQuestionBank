"""Confirming (or skipping) one proposed paper of an auto-import job.

The admin's reviewed rectangles (``proposal_edited`` if there is one, else ``proposal``) are
cropped out of the job's ``source.pdf`` into page images and handed to the Manual flow's own
``confirm_import``, unchanged. See docs/features/auto-import.md ("Confirm and skip") and docs/features/qa-pairing.md.
"""

import uuid
from collections.abc import Callable
from typing import Any

import fitz  # PyMuPDF
from PIL import Image

from app.logger import log, log_job_event
from app.models.orm import IngestJob, Paper, QuestionPage
from app.pdf.image_processing import get_dimensions, standardize, to_webp_bytes
from app.services.ingest import confirm_import
from app.services.ingest_events import add_event
from app.services.ingest_jobs import job_prefix
from app.services.ingest_papers import get_row, set_metadata, set_status
from app.services.paper_admin import apply_page_changes, commit_with_page_moves
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
    list order, ``page_order`` counting from 1 per type like the Manual flow. Provenance rides
    along: each question carries its ``section`` (the paper's question label) and
    ``proposal_question_index``, each page its ``source_page`` and ``source_rect``. Orphan answers are
    not imported. On a failure the images already uploaded are deleted again."""
    upload_id = upload_id or str(uuid.uuid4())
    keys: list[str] = []
    questions = []
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
            n = 0
            for q_index, q in enumerate(paper["questions"]):
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
                            "source_page": rect["page"],
                            "source_rect": {k: rect[k] for k in ("x0", "y0", "x1", "y1")},
                        })
                questions.append({
                    "question_number": q["number"], "pages": pages,
                    "section": paper.get("label") or paper.get("answer_label"),
                    "proposal_question_index": q_index,
                })
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
    if paper_id is not None and paper_id not in (job.confirmed_paper_ids or []):
        job.confirmed_paper_ids = [*(job.confirmed_paper_ids or []), paper_id]
    papers = effective_proposal(job).get("papers", [])
    settled = bool(papers) and all(paper_key(p, i) in done for i, p in enumerate(papers))
    if settled:
        job.status = "confirmed"
    return settled


def _drop_job_objects(source_key: str, store: ObjectStore) -> None:
    prefix = job_prefix(source_key)
    try:
        store.delete_prefix(prefix)
    except Exception:
        log.error("confirm_job_paper/s3_delete failed prefix=%s", prefix)


def _linked_answers(db: Any, job: IngestJob, key: str):
    """The pending answer-only ``ingest_paper`` linked to question paper ``key`` and its job, or
    ``(None, None)``. A read only: ``confirm_job_paper`` re-checks it once both jobs are locked."""
    row = get_row(db, job, key)
    if row is None or row.role != "question" or row.matched_ingest_paper_id is None:
        return None, None
    partner = row.matched_ingest_paper
    if partner is None or partner.job_id == job.id:
        return None, None
    return partner, db.get(IngestJob, partner.job_id)


def _answers_usable(db: Any, job: IngestJob, key: str, partner, partner_job) -> bool:
    row = get_row(db, job, key)
    db.refresh(partner)
    return (
        partner_job.status == "review_ready" and partner.status == "pending" and partner.role == "answer_only"
        and partner.matched_ingest_paper_id == getattr(row, "id", None)
        and partner.paper_key not in outcomes(partner_job)
    )


def _linked_answer_payload(partner_job, partner, payload: dict, store: ObjectStore):
    """Crop the linked answer paper's answer rects (from ITS job's source.pdf) and add them to the
    question ``payload`` as answer pages, after the question's own answer pages. Returns
    ``(attached_numbers, unmatched_numbers, temp_keys)``."""
    paper_data = _find_paper(partner_job, partner.paper_key)
    by_number = {}
    for pq in payload["questions"]:
        n = _question_number(pq["question_number"])
        if n is not None:
            by_number.setdefault(n, pq)
    rects_by_number: dict[int, list[dict]] = {}
    unmatched: list[Any] = []
    for q in paper_data.get("questions", []):
        if not q.get("answer_rects"):
            continue
        number = _question_number(q["number"])
        if number is None or number not in by_number:
            unmatched.append(q["number"])
        else:
            rects_by_number.setdefault(number, []).extend(q["answer_rects"])
    if not rects_by_number:
        return [], unmatched, []
    numbers = sorted(rects_by_number)
    cropped = {**paper_data, "questions": [
        {"number": n, "question_rects": [], "answer_rects": rects_by_number[n]} for n in numbers
    ]}
    extra, temp_keys = build_confirm_payload(store.get(partner_job.source_key), cropped, {})
    for number, eq in zip(numbers, extra["questions"]):
        target = by_number[number]
        base = sum(1 for p in target["pages"] if p["page_type"] == "answer")
        for p in eq["pages"]:
            target["pages"].append({**p, "page_order": base + p["page_order"]})
    return numbers, unmatched, temp_keys


def confirm_job_paper(
    job: IngestJob, key: str, metadata: dict, admin: Any, db: Any, store: ObjectStore,
    answers_info: dict | None = None,
) -> tuple[Paper, bool]:
    """Create the paper for proposal paper ``key``. Returns ``(paper, job_settled)``.

    If the paper is linked to a pending answer-only paper of another job (#84), that job's answers
    come in too: cropped from the other job's ``source.pdf``, appended after this paper's own answer
    pages, and the answer paper is recorded ``attached`` in the same transaction. ``answers_info``,
    if given, is filled with ``answers_from`` (``{job_id, filename, paper_key, attached}`` or None),
    ``unmatched`` (answer numbers with no question) and ``answers_job_settled``."""
    partner, partner_job = _linked_answers(db, job, key)
    # Lock both jobs, lowest id first, so two confirms of a linked pair cannot deadlock.
    for j in sorted([j for j in (job, partner_job) if j is not None], key=lambda j: str(j.id)):
        db.refresh(j, with_for_update=True)  # also serialises two clicks on the same paper
    _check_open(job, key)
    paper_data = _find_paper(job, key)
    if paper_data.get("role") == "answer_only":
        raise ReviewActionError(
            422, f"Paper {key!r} holds answers only and cannot be confirmed as a paper; attach it to its question paper (or skip it)"
        )
    if not paper_data.get("questions"):
        raise ReviewActionError(422, f"Paper {key!r} has no questions to import; skip it instead")
    if partner is not None and not _answers_usable(db, job, key, partner, partner_job):
        log.warning(
            "confirm_job_paper/linked_answers_unavailable job=%s key=%s answer_job=%s", job.id, key, partner_job.id
        )
        partner = partner_job = None
    payload, temp_keys = build_confirm_payload(store.get(job.source_key), paper_data, metadata)
    attached: list[int] = []
    unmatched: list[Any] = []
    if partner is not None:
        try:
            attached, unmatched, extra_keys = _linked_answer_payload(partner_job, partner, payload, store)
        except Exception:
            _delete_quietly(temp_keys)
            raise
        temp_keys += extra_keys
        if not attached:
            partner = partner_job = None  # nothing to bring in: the answer paper stays pending
    job_id = job.id
    source_key = job.source_key
    settled = False
    answers_settled = False
    partner_key = partner.paper_key if partner is not None else None
    partner_filename = partner_job.filename if partner_job is not None else None
    partner_job_id = partner_job.id if partner_job is not None else None
    partner_source = partner_job.source_key if partner_job is not None else None

    def link_and_record(paper: Paper) -> None:
        # Runs inside confirm_import's transaction, so the paper, its source job and the
        # job's outcome (and the answer job's) commit together or not at all.
        nonlocal settled, answers_settled
        paper.source_job_id = job_id
        settled = _record(job, key, "confirmed", paper.id)
        set_metadata(db, job, key, metadata)  # what the admin confirmed (admin-sourced if it differs)
        set_status(db, job, key, "confirmed", paper.id)
        add_event(
            db, job_id, "paper_confirmed", actor_user_id=getattr(admin, "id", None),
            paper_id=paper.id, paper_label=key, job_settled=settled,
            answers_from_job=str(partner_job_id) if partner_job_id else None,
        )
        if partner is not None:
            answers_settled = _record(partner_job, partner_key, "attached", paper.id)
            set_status(db, partner_job, partner_key, "attached", paper.id)
            add_event(
                db, partner_job_id, "paper_attached", actor_user_id=getattr(admin, "id", None),
                paper_id=paper.id, paper_label=partner_key, attached=attached,
                unmatched=[str(n) for n in unmatched], job_settled=answers_settled,
                via_job=str(job_id),
            )

    try:
        paper = confirm_import(payload, admin, db, before_commit=link_and_record)  # commits once
    except Exception:
        _delete_quietly(temp_keys)
        raise
    log_job_event(
        job_id, "paper_confirmed", paper_id=paper.id, paper_label=key, job_settled=settled,
        answers_from_job=str(partner_job_id) if partner_job_id else None,
    )
    if settled:
        _drop_job_objects(source_key, store)
    if partner_job_id is not None:
        log_job_event(
            partner_job_id, "paper_attached", paper_id=paper.id, paper_label=partner_key, attached=attached,
            unmatched=[str(n) for n in unmatched], job_settled=answers_settled, via_job=str(job_id),
        )
        if answers_settled:
            _drop_job_objects(partner_source, store)
    if answers_info is not None:
        answers_info["unmatched"] = unmatched
        answers_info["answers_from"] = (
            {"job_id": str(partner_job_id), "filename": partner_filename, "paper_key": partner_key, "attached": attached}
            if partner_job_id is not None else None
        )
        answers_info["answers_job_settled"] = answers_settled
    return paper, settled


def _release_link(db: Any, job: IngestJob, key: str) -> None:
    """A skipped paper gives up its link; the partner (if still pending) is looked at afresh."""
    from app.services.ingest_matching import match_row
    from app.services.ingest_papers import _clear_link

    row = get_row(db, job, key)
    if row is None or row.matched_ingest_paper_id is None:
        return
    partner = row.matched_ingest_paper
    _clear_link(row)
    if partner is not None and partner.status == "pending":
        match_row(db, partner)


def skip_job_paper(job: IngestJob, key: str, db: Any, store: ObjectStore, admin: Any = None) -> bool:
    """Mark proposal paper ``key`` skipped. Returns whether that settles the job."""
    db.refresh(job, with_for_update=True)
    _check_open(job, key)
    _find_paper(job, key)
    job_id = job.id
    source_key = job.source_key
    settled = _record(job, key, "skipped", None)
    set_status(db, job, key, "skipped")
    _release_link(db, job, key)
    add_event(db, job_id, "paper_skipped", actor_user_id=getattr(admin, "id", None), paper_label=key, job_settled=settled)
    db.commit()
    log_job_event(job_id, "paper_skipped", paper_label=key, job_settled=settled)
    if settled:
        _drop_job_objects(source_key, store)
    return settled


# --- attaching an answer-only paper's answers to an existing paper -----------------------------

ATTACH_MODES = ("append", "replace")


def _question_number(value: Any) -> int | None:
    """A proposal question number as the integer ``question.question_number`` holds: ``1``,
    ``"1"`` and ``" 01 "`` all mean 1. A label that is not a plain number (``"1a"``) is None, so it
    can never match and is reported back as unmatched."""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def attach_answers(
    job: IngestJob, key: str, paper_id: int, mode: str | None, admin: Any, db: Any, store: ObjectStore
) -> dict:
    """Attach the answer rectangles of answer-only proposal paper ``key`` to the existing paper
    ``paper_id``, matching proposal questions to the paper's questions by number.

    ``mode`` is ``append`` (new answer pages after the existing ones) or ``replace`` (they replace
    the question's existing answer pages); ``None`` applies the default per question: replace when
    it has no answer pages yet, else append. Answer numbers with no matching question are not
    attached but returned in ``unmatched``. The crops are copied to their canonical keys before the
    commit and the temp keys deleted after it (as in confirm); the page rows, the job's outcome, the
    ``ingest_paper`` row and the event commit together, and a failure rolls everything back.

    Returns ``{"attached": [numbers], "unmatched": [numbers], "modes": {number: mode},
    "job_settled": bool}``."""
    if mode is not None and mode not in ATTACH_MODES:
        raise ReviewActionError(422, f"mode must be one of {', '.join(ATTACH_MODES)}")
    db.refresh(job, with_for_update=True)  # serialise two clicks on the same paper
    _check_open(job, key)
    paper_data = _find_paper(job, key)
    if paper_data.get("role") != "answer_only":
        raise ReviewActionError(422, f"Paper {key!r} is not an answer-only paper; confirm it instead")
    target = db.get(Paper, paper_id)
    if target is None:
        raise ReviewActionError(404, f"Paper {paper_id} does not exist")
    by_number = {q.question_number: q for q in target.questions}

    rects_by_number: dict[int, list[dict]] = {}  # matched question number -> its answer rects
    unmatched: list[Any] = []
    for q in paper_data.get("questions", []):
        if not q.get("answer_rects"):
            continue
        number = _question_number(q["number"])
        if number is None or number not in by_number:
            unmatched.append(q["number"])
        else:
            rects_by_number.setdefault(number, []).extend(q["answer_rects"])
    if not rects_by_number:
        shown = ", ".join(str(n) for n in unmatched) or "none"
        raise ReviewActionError(
            422, f"None of this paper's answers match a question of paper {paper_id} (unmatched: {shown})"
        )

    numbers = sorted(rects_by_number)
    cropped = {**paper_data, "questions": [
        {"number": n, "question_rects": [], "answer_rects": rects_by_number[n]} for n in numbers
    ]}
    payload, temp_keys = build_confirm_payload(store.get(job.source_key), cropped, {})
    job_id, source_key = job.id, job.source_key
    modes: dict[int, str] = {}
    removed_keys: list[str] = []
    new_pairs: list[tuple[str, str]] = []
    settled = False
    try:
        for number, pq in zip(numbers, payload["questions"]):
            question = by_number[number]
            existing = sorted(question.pages, key=lambda p: (p.page_type, p.page_order))
            used = mode or ("append" if any(p.page_type == "answer" for p in existing) else "replace")
            modes[number] = used
            desired = [
                {"id": p.id, "page_type": p.page_type, "page_order": p.page_order}
                for p in existing if used == "append" or p.page_type != "answer"
            ]
            new_pages = pq["pages"]
            desired += [
                {k: p[k] for k in ("temp_key", "page_type", "page_order", "width_px", "height_px")}
                for p in new_pages
            ]
            removed, pairs = apply_page_changes(paper_id, question, desired, db)
            removed_keys.extend(removed)
            new_pairs.extend(pairs)
            for (_, canonical), p in zip(pairs, new_pages):  # provenance of the new answer pages
                row = db.query(QuestionPage).filter(QuestionPage.image_key == canonical).one()
                row.source_page, row.source_rect = p["source_page"], p["source_rect"]
        settled = _record(job, key, "attached", paper_id)
        set_status(db, job, key, "attached", paper_id)
        add_event(
            db, job_id, "paper_attached", actor_user_id=getattr(admin, "id", None), paper_id=paper_id,
            paper_label=key, attached=numbers, unmatched=[str(n) for n in unmatched], job_settled=settled,
        )
        commit_with_page_moves(db, new_pairs, removed_keys)  # copies, commits, then settles S3
    except Exception:
        db.rollback()
        _delete_quietly(temp_keys)
        raise
    log_job_event(
        job_id, "paper_attached", paper_id=paper_id, paper_label=key, attached=numbers,
        unmatched=[str(n) for n in unmatched], job_settled=settled,
    )
    if settled:
        _drop_job_objects(source_key, store)
    return {
        "attached": numbers, "unmatched": unmatched,
        "modes": {str(n): m for n, m in modes.items()}, "job_settled": settled,
    }
